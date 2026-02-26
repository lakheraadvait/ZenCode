"""
ZENCODE v10 — core.py
Autonomous orchestration engine.
- Workspace = CWD at launch
- All agents understand multi-language projects
- Diff tracker intercepts file_write when auto_accept=False
- Build plans parsed and executed autonomously
- Debug agent loops until project runs
"""
from __future__ import annotations

import json, re, sys, time, subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Dict, Optional, Any

def _ensure(pkg, imp=None):
    try: return __import__(imp or pkg)
    except ImportError:
        print(f"  installing {pkg}...")
        subprocess.check_call([sys.executable,"-m","pip","install",pkg,"-q",
                               "--break-system-packages"])
        return __import__(imp or pkg)

_ensure("mistralai")
from mistralai import Mistral

from zencode.config import cfg
from zencode.agents import AGENTS, AGENT_REGISTRY, BaseAgent
from zencode.tools import dispatch as tool_dispatch, ToolResult, set_diff_tracker
from zencode.diff import DiffTracker, DiffSet


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    tool_id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[ToolResult] = None
    duration_ms: int = 0


@dataclass
class ZenResponse:
    text: str
    agent_name: str
    agent_role: str
    agent_emoji: str
    agent_color: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    tool_calls: List[ToolCall] = field(default_factory=list)
    error: Optional[str] = None
    diff_set: Optional[DiffSet] = None  # pending diffs if auto_accept=False

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class StreamChunk:
    """
    chunk_type: delta | tool_call | tool_result | status | newline | done | diff_ready
    """
    chunk_type: str
    delta: str = ""
    agent_name: str = ""
    agent_color: str = "#00f5ff"
    agent_emoji: str = "⬡"
    status_msg: str = ""
    status_level: str = "info"      # info | ok | warn | error
    tool_call: Optional[ToolCall] = None
    done: bool = False
    response: Optional[ZenResponse] = None
    diff_set: Optional[DiffSet] = None   # emitted when diffs are staged for review


# ── Build plan ─────────────────────────────────────────────────────────────────

@dataclass
class BuildTask:
    agent: str
    label: str
    description: str


@dataclass
class BuildPlan:
    name: str
    target_dir: str    # "." = workspace root
    stack: str
    tasks: List[BuildTask]


def parse_build_plan(text: str) -> Optional[BuildPlan]:
    if "BUILD PLAN:" not in text:
        return None
    name_m   = re.search(r"BUILD PLAN:\s*(.+?)(?:\n|$)", text)
    target_m = re.search(r"TARGET DIR:\s*(.+?)(?:\n|$)", text)
    stack_m  = re.search(r"STACK:\s*(.+?)(?:\n|$)", text)
    name      = name_m.group(1).strip()   if name_m   else "project"
    target    = target_m.group(1).strip() if target_m else "."
    stack     = stack_m.group(1).strip()  if stack_m  else "Python"
    tasks = []
    for m in re.finditer(r"\[(\w+)\]\s+([A-Z]\d+):\s*(.+?)(?:\n|$)", text, re.I):
        agent = m.group(1).lower()
        if agent in AGENTS:
            tasks.append(BuildTask(agent=agent, label=m.group(2), description=m.group(3).strip()))
    return BuildPlan(name=name, target_dir=target, stack=stack, tasks=tasks) if tasks else None


# ── Memory ─────────────────────────────────────────────────────────────────────

class Memory:
    def __init__(self):
        self._msgs: List[Dict] = []

    def add(self, role: str, content: str):
        self._msgs.append({"role": role, "content": content})
        limit = int(cfg.get("chat_history_limit", 60))
        if len(self._msgs) > limit:
            self._msgs = self._msgs[-limit:]

    def get(self) -> List[Dict]:
        return list(self._msgs)

    def clear(self):
        self._msgs.clear()

    def __len__(self): return len(self._msgs)

    @property
    def turns(self): return sum(1 for m in self._msgs if m["role"] == "user")


# ── ZenCore ────────────────────────────────────────────────────────────────────

_MAX_ITERS = 24   # max tool iterations per agent call

BUILD_MODE_DIRECTIVE = (
    "AUTOMATED BUILD MODE ENABLED. Do not ask for confirmation. "
    "Execute tasks sequentially and complete each task fully before responding."
)


class ZenCore:
    def __init__(self):
        self.memory = Memory()
        self._client: Optional[Mistral] = None
        self._pending_plan: Optional[BuildPlan] = None
        self._original_prompt: str = ""

    def _get_client(self) -> Mistral:
        if self._client is None:
            key = cfg.get("api_key","")
            if not key:
                raise RuntimeError(
                    "No API key set.\n"
                    "  Run:  zencode --setkey YOUR_MISTRAL_KEY\n"
                    "  Or:   setconfig api_key YOUR_KEY"
                )
            self._client = Mistral(api_key=key)
        return self._client

    def _invalidate_client(self):
        self._client = None

    def _ws_context(self) -> str:
        try:
            from zencode.workspace_scanner import get_scanner
            return get_scanner(cfg.workspace()).get_full_context()
        except Exception as e:
            return f"(workspace scan failed: {e})"

    def _make_tracker(self, agent_name: str = "", task: str = "") -> DiffTracker:
        tracker = DiffTracker(cfg.workspace())
        tracker.start(agent_name=agent_name, task=task)
        set_diff_tracker(tracker)
        return tracker

    def _clear_tracker(self):
        set_diff_tracker(None)

    # ── Core agent loop ────────────────────────────────────────────────────────

    def _run_agent(
        self,
        agent: BaseAgent,
        prompt: str,
        history: List[Dict],
        system_extra: str = "",
        use_diff_tracker: bool = False,
        tracker: Optional[DiffTracker] = None,
    ) -> Iterator[StreamChunk]:
        """
        Run one agent to completion.
        Streams tool_call, tool_result, delta, done chunks.
        If use_diff_tracker: intercepts file_write calls, emits diff_ready at end.
        """
        model   = cfg.get("model","codestral-latest")
        client  = self._get_client()
        schemas = agent.get_tool_schemas()

        msgs   = agent.build_messages(prompt, history)
        system = agent.format_system(system_extra or None)
        if system:
            msgs = [{"role":"system","content":system}] + msgs

        # Start diff tracking if requested
        if use_diff_tracker and tracker is None:
            tracker = self._make_tracker(agent.name, prompt[:60])
        elif use_diff_tracker and tracker is not None:
            set_diff_tracker(tracker)

        t_start = time.time()
        all_tcs: List[ToolCall] = []
        tok_in = tok_out = 0
        final_text = ""

        try:
            for _iter in range(_MAX_ITERS):
                kwargs = dict(
                    model=model,
                    max_tokens=min(int(cfg.get("max_tokens",8192)), agent.max_tokens),
                    temperature=agent.temperature,
                    messages=msgs,
                )
                if schemas:
                    kwargs["tools"] = schemas
                    kwargs["tool_choice"] = "auto"

                resp   = client.chat.complete(**kwargs)
                choice = resp.choices[0]
                tok_in  += getattr(resp.usage,"prompt_tokens",0)
                tok_out += getattr(resp.usage,"completion_tokens",0)

                # ── Tool call loop
                if schemas and choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                    msgs.append({
                        "role": "assistant",
                        "content": choice.message.content or "",
                        "tool_calls": [
                            {"id":tc.id,"type":"function",
                             "function":{"name":tc.function.name,
                                         "arguments":tc.function.arguments}}
                            for tc in choice.message.tool_calls
                        ],
                    })
                    for tc in choice.message.tool_calls:
                        name = tc.function.name
                        try:
                            raw  = tc.function.arguments
                            args = json.loads(raw) if isinstance(raw,str) else raw
                        except Exception:
                            args = {}
                        zen_tc = ToolCall(tool_id=tc.id, name=name, arguments=args)
                        yield StreamChunk(
                            chunk_type="tool_call",
                            agent_name=agent.name, agent_color=agent.color,
                            agent_emoji=agent.emoji, tool_call=zen_tc,
                        )
                        t0 = time.perf_counter()
                        result = tool_dispatch(name, args)
                        zen_tc.result = result
                        zen_tc.duration_ms = int((time.perf_counter()-t0)*1000)
                        all_tcs.append(zen_tc)
                        yield StreamChunk(
                            chunk_type="tool_result",
                            agent_name=agent.name, agent_color=agent.color,
                            agent_emoji=agent.emoji, tool_call=zen_tc,
                        )
                        msgs.append({
                            "role":"tool",
                            "content":result.to_api_str(),
                            "tool_call_id":tc.id,
                            "name":name,
                        })
                    continue

                # ── Final text — stream it live
                parts: List[str] = []
                try:
                    with client.chat.stream(
                        model=model,
                        max_tokens=min(int(cfg.get("max_tokens",8192)), agent.max_tokens),
                        temperature=agent.temperature,
                        messages=msgs,
                    ) as sctx:
                        for event in sctx:
                            try: d = event.data.choices[0].delta.content or ""
                            except (AttributeError,IndexError): d = ""
                            if d:
                                parts.append(d)
                                yield StreamChunk(
                                    chunk_type="delta", delta=d,
                                    agent_name=agent.name, agent_color=agent.color,
                                    agent_emoji=agent.emoji,
                                )
                    final_text = "".join(parts)
                except Exception:
                    final_text = choice.message.content or ""
                    if final_text:
                        yield StreamChunk(
                            chunk_type="delta", delta=final_text,
                            agent_name=agent.name, agent_color=agent.color,
                            agent_emoji=agent.emoji,
                        )
                break

        except Exception as exc:
            if use_diff_tracker:
                self._clear_tracker()
            yield StreamChunk(
                chunk_type="done", done=True,
                agent_name=agent.name, agent_color="#ff4444", agent_emoji="✖",
                response=ZenResponse(
                    text="", agent_name=agent.name, agent_role=agent.role,
                    agent_emoji="✖", agent_color="#ff4444", model=model,
                    error=str(exc),
                ),
            )
            return

        # ── Collect diffs if tracking
        diff_set = None
        if use_diff_tracker and tracker:
            diff_set = tracker.pending
            tracker.stop()
            self._clear_tracker()
            if diff_set.diffs:
                yield StreamChunk(
                    chunk_type="diff_ready",
                    agent_name=agent.name, agent_color=agent.color,
                    agent_emoji=agent.emoji,
                    diff_set=diff_set,
                )

        latency = int((time.time()-t_start)*1000)
        yield StreamChunk(
            chunk_type="done", done=True,
            agent_name=agent.name, agent_color=agent.color, agent_emoji=agent.emoji,
            response=ZenResponse(
                text=final_text, agent_name=agent.name, agent_role=agent.role,
                agent_emoji=agent.emoji, agent_color=agent.color, model=model,
                tokens_in=tok_in, tokens_out=tok_out, latency_ms=latency,
                tool_calls=all_tcs, diff_set=diff_set,
            ),
        )

    # ── Public: chat stream ────────────────────────────────────────────────────

    def stream(self, user_input: str) -> Iterator[StreamChunk]:
        """User-facing chat. Always goes to chat agent."""
        agent = AGENTS["chat"]
        self.memory.add("user", user_input)
        history  = self.memory.get()[:-1]
        ws_ctx   = self._ws_context()
        final_text = ""
        for chunk in self._run_agent(agent, user_input, history, ws_ctx):
            if chunk.chunk_type == "done":
                if chunk.response and chunk.response.ok:
                    final_text = chunk.response.text
                    self.memory.add("assistant", final_text)
                    plan = parse_build_plan(final_text)
                    if plan:
                        self._pending_plan = plan
                        self._original_prompt = user_input
            yield chunk

    def has_pending_plan(self) -> bool:
        return self._pending_plan is not None

    def get_pending_plan(self) -> Optional[BuildPlan]:
        return self._pending_plan

    # ── Public: execute build ──────────────────────────────────────────────────

    def execute_build(
        self,
        original_prompt: str = "",
        auto_accept: bool = None,
    ) -> Iterator[StreamChunk]:
        """Execute pending build plan task by task."""
        plan = self._pending_plan
        if not plan:
            yield StreamChunk(chunk_type="status", status_msg="No build plan.",
                              status_level="error")
            return

        if original_prompt:
            self._original_prompt = original_prompt

        # auto_accept: use arg, else config
        if auto_accept is None:
            auto_accept = cfg.auto_accept()

        original_ws = cfg.workspace()
        active_ws = original_ws

        # Handle subdir target (temporarily)
        if plan.target_dir and plan.target_dir not in (".", ""):
            active_ws = original_ws / plan.target_dir
            if not active_ws.exists():
                active_ws.mkdir(parents=True, exist_ok=True)
            cfg.set_workspace(str(active_ws))

        try:
            yield StreamChunk(
                chunk_type="status",
                status_msg=f"⚡ BUILDING: {plan.name}  ·  {plan.stack}  ·  {cfg.workspace()}",
                status_level="ok",
                agent_name="chat", agent_color="#00ff9f", agent_emoji="◉",
            )

            completed: List[str] = []

            for task in plan.tasks:
                agent = AGENTS.get(task.agent, AGENTS["coder"])

                yield StreamChunk(
                    chunk_type="status",
                    status_msg=f"[{task.label}] {agent.emoji} {agent.name.upper()}: {task.description}",
                    agent_name=agent.name, agent_color=agent.color, agent_emoji=agent.emoji,
                )

                # Refresh context after each task
                ws_ctx = self._ws_context()
                prior  = "\n".join(completed[-3:]) if completed else "(first task)"

                task_prompt = (
                    f"PROJECT: {plan.name}\n"
                    f"STACK: {plan.stack}\n"
                    f"ORIGINAL REQUEST: {self._original_prompt}\n"
                    f"TARGET DIR: {cfg.workspace()}\n\n"
                    f"PRIOR WORK:\n{prior}\n\n"
                    f"YOUR TASK ({task.label}): {task.description}\n\n"
                    f"Work in: {cfg.workspace()}\n"
                    f"Use relative paths from that root.\n"
                )

                task_text = ""
                for chunk in self._run_agent(
                    agent, task.description, [],
                    BUILD_MODE_DIRECTIVE + "\n\n" + task_prompt + "\n\n" + ws_ctx,
                    use_diff_tracker=not auto_accept,
                ):
                    if chunk.chunk_type == "diff_ready":
                        # CLI will handle review; emit to caller
                        yield chunk
                        continue
                    if chunk.chunk_type == "done":
                        if chunk.response and chunk.response.ok:
                            task_text = chunk.response.text
                            writes = [
                                tc.arguments.get("path","")
                                for tc in chunk.response.tool_calls
                                if tc.name in ("file_write","file_patch")
                                and tc.result and tc.result.success
                            ]
                            summary = f"Task {task.label} ({agent.name}): {task.description[:60]}"
                            if writes:
                                summary += f" → {', '.join(writes[:3])}"
                            completed.append(summary)
                    yield chunk

                # Refresh scanner after each task
                try:
                    from zencode.workspace_scanner import refresh_scanner
                    refresh_scanner(cfg.workspace())
                except Exception:
                    pass
        finally:
            cfg.set_workspace(str(original_ws))

        self._pending_plan = None

        yield StreamChunk(
            chunk_type="status",
            status_msg=f"✅ BUILD COMPLETE — {plan.name}",
            status_level="ok",
            agent_name="chat", agent_color="#00ff9f", agent_emoji="◉",
        )

    # ── Public: direct build (plan + execute in one) ───────────────────────────

    def direct_build(self, prompt: str, auto_accept: bool = None) -> Iterator[StreamChunk]:
        """Plan then immediately execute. Used by: build "prompt"."""
        if auto_accept is None:
            auto_accept = cfg.auto_accept()

        yield StreamChunk(chunk_type="status", status_msg="◈ Planning...",
                          agent_name="chat", agent_color="#00ff9f", agent_emoji="◉")

        ws_ctx      = self._ws_context()
        plan_prompt = (
            f"Build this: {prompt}\n\n"
            "Output a BUILD PLAN using the exact format with agent tasks.\n"
            "Consider the current workspace context below.\n\n"
            f"{ws_ctx}"
        )

        plan_text = ""
        for chunk in self._run_agent(AGENTS["chat"], plan_prompt, [], BUILD_MODE_DIRECTIVE):
            if chunk.chunk_type == "delta":
                plan_text += chunk.delta
            yield chunk

        plan = parse_build_plan(plan_text)
        if not plan:
            plan = BuildPlan(
                name=prompt[:50], target_dir=".", stack="auto",
                tasks=[
                    BuildTask("architect","A1",f"Scaffold the project: {prompt}"),
                    BuildTask("coder",    "C1",f"Implement all required code for: {prompt}"),
                    BuildTask("debug",    "D1","Run the project, fix ALL errors until it works"),
                ],
            )
        self._pending_plan = plan
        self._original_prompt = prompt

        yield StreamChunk(chunk_type="newline")

        for chunk in self.execute_build(prompt, auto_accept=auto_accept):
            yield chunk

    # ── Public: autonomous debug ───────────────────────────────────────────────

    def autonomous_debug(self, context: str = "") -> Iterator[StreamChunk]:
        ws_ctx   = self._ws_context()
        prompt   = (
            f"The project has errors. Fix them autonomously.\n"
            f"{('Context: ' + context) if context else ''}\n\n"
            f"Start by running the project, then fix all errors.\n\n{ws_ctx}"
        )
        yield StreamChunk(
            chunk_type="status",
            status_msg="⚠ DEBUG — Autonomous fix loop starting...",
            agent_name="debug", agent_color="#ff4444", agent_emoji="⚠",
        )
        # Debug agent ALWAYS writes directly (no diff staging)
        for chunk in self._run_agent(AGENTS["debug"], prompt, [],
                                     use_diff_tracker=False):
            yield chunk

    # ── Helpers ────────────────────────────────────────────────────────────────

    def clear_memory(self): self.memory.clear()
    def memory_stats(self) -> Dict:
        return {"messages": len(self.memory), "turns": self.memory.turns,
                "limit": cfg.get("chat_history_limit",60)}

    # ── v11: direct agent streaming (for git session etc) ──────────────────────
    def stream_agent(self, agent_name: str, user_input: str) -> Iterator[StreamChunk]:
        """Stream a specific agent directly (no memory, no build plan parsing)."""
        agent = AGENTS.get(agent_name, AGENTS["chat"])
        ws_ctx = self._ws_context()
        for chunk in self._run_agent(agent, user_input, [], ws_ctx, use_diff_tracker=False):
            yield chunk


core = ZenCore()
