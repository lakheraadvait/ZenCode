#!/usr/bin/env python3
"""
ZENCODE v11 — Autonomous AI Code Shell
More capable than Cursor. Runs anywhere. No IDE needed.

  zencode                 — launch in current directory
  zencode --setkey KEY    — save your Mistral API key
  zencode --yes           — auto-accept all changes (no prompts)
  zencode --workspace DIR — use a specific directory
"""

import os, sys, shutil, time, signal, textwrap, subprocess, re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# ── Auto-install deps ──────────────────────────────────────────────────────────
def _ensure(pkg, imp=None):
    try: return __import__(imp or pkg)
    except ImportError:
        print(f"  installing {pkg}...", flush=True)
        subprocess.check_call([sys.executable,"-m","pip","install",pkg,"-q",
                               "--break-system-packages"])
        return __import__(imp or pkg)

_ensure("rich")
_ensure("click")
_ensure("prompt_toolkit","prompt_toolkit")
_ensure("mistralai")
_ensure("requests")

import click
from rich.console import Console
from rich.panel   import Panel
from rich.text    import Text
from rich.table   import Table
from rich.rule    import Rule
from rich.align   import Align
from rich.live    import Live
from rich.syntax  import Syntax
from rich.markdown import Markdown
from rich.tree    import Tree
from rich          import box
from prompt_toolkit             import PromptSession
from prompt_toolkit.history     import InMemoryHistory
from prompt_toolkit.styles      import Style as PTStyle
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.auto_suggest   import AutoSuggestFromHistory
from prompt_toolkit.key_binding    import KeyBindings

try:
    from zencode.config          import cfg, MISTRAL_MODELS
    from zencode.core            import core, ZenResponse, StreamChunk, ToolCall, BuildPlan
    from zencode.agents          import AGENTS, AGENT_REGISTRY
    from zencode.tools           import file_read, run_code, ToolResult
    from zencode.workspace_scanner import get_scanner, refresh_scanner
    from zencode.diff            import (DiffReviewer, DiffSet, DiffTracker,
                                         render_diff_rich, render_diffset_summary)
    from zencode.diff.engine     import FileDiff
except ImportError as e:
    print(f"\n  ✖  Import error: {e}\n  Run: pip install -e .\n")
    sys.exit(1)

# ── Console & palette ──────────────────────────────────────────────────────────
console = Console(force_terminal=True, color_system="truecolor", highlight=False)
VERSION = "11.0.0"
HISTORY = InMemoryHistory()

CYAN   = "#00f5ff"
BLUE   = "#0088ff"
VIOLET = "#7c3aed"
PINK   = "#f472b6"
GREEN  = "#00ff9f"
YELLOW = "#ffe600"
RED    = "#ff4444"
ORANGE = "#f97316"
WHITE  = "#e8eaf6"
DIM    = "#3d4a5c"
GRAD   = [CYAN,"#00d9ff","#00bfff",BLUE,"#4466ff",VIOLET,"#a855f7",PINK]

def W(): return shutil.get_terminal_size().columns
def gradient(text: str) -> Text:
    t = Text()
    for i, ch in enumerate(text):
        t.append(ch, style=f"bold {GRAD[i % len(GRAD)]}")
    return t
def soft_rule():   console.print(f"[{DIM}]{'─' * min(W(), 88)}[/]")
def section_rule(t): console.print(Rule(title=f"[{DIM}]{t}[/]", style=DIM))
def ok(m):    console.print(f"  [{GREEN}]✔[/]  [{WHITE}]{m}[/]")
def warn(m):  console.print(f"  [{YELLOW}]⚠[/]  [{WHITE}]{m}[/]")
def err(m):   console.print(f"  [{RED}]✖[/]  [{RED}]{m}[/]")
def info(m):  console.print(f"  [{CYAN}]⬡[/]  [{DIM}]{m}[/]")
def dot(m, color=CYAN): console.print(f"  [{color}]●[/]  [{WHITE}]{m}[/]")

LOGO = [
    "███████╗███████╗███╗   ██╗ ██████╗ ██████╗ ██████╗ ███████╗",
    "╚══███╔╝██╔════╝████╗  ██║██╔════╝██╔═══██╗██╔══██╗██╔════╝",
    "  ███╔╝ █████╗  ██╔██╗ ██║██║     ██║   ██║██║  ██║█████╗  ",
    " ███╔╝  ██╔══╝  ██║╚██╗██║██║     ██║   ██║██║  ██║██╔══╝  ",
    "███████╗███████╗██║ ╚████║╚██████╗╚██████╔╝██████╔╝███████╗",
    "╚══════╝╚══════╝╚═╝  ╚═══╝ ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝",
]

def show_splash():
    if not cfg.get("splash_on_start", True): return
    console.clear()
    console.print()
    for line in LOGO:
        console.print(Align.center(gradient(line)))
        time.sleep(0.02)
    console.print()
    console.print(Align.center(Text(
        f"⚡  AUTONOMOUS AI CODE SHELL  v{VERSION}  ⚡", style=f"bold {CYAN}"
    )))
    console.print(Align.center(Text(
        "MORE CAPABLE THAN CURSOR", style=f"dim {VIOLET}"
    )))
    console.print()

    ws      = cfg.workspace()
    key_ok  = bool(cfg.get("api_key",""))
    scanner = get_scanner(ws)
    proj    = scanner.get_info()
    git     = scanner.get_git()
    auto    = cfg.auto_accept()
    rules   = cfg.load_zenrules()

    stack_str = ""
    if proj.get("framework"): stack_str = proj["framework"]
    elif proj.get("language"): stack_str = proj["language"]

    key_line = (
        f"[bold {GREEN}]✔  key loaded[/]" if key_ok
        else f"[bold {RED}]✗  zencode --setkey YOUR_MISTRAL_KEY[/]"
    )
    files_line = (
        f"[bold {GREEN}]{scanner.file_count()} files[/]"
        + (f"  [{CYAN}]{stack_str}[/]" if stack_str else "")
    ) if scanner.file_count() else f"[{DIM}]empty directory[/]"

    accept_line = (
        f"[bold {YELLOW}]AUTO-ACCEPT ON[/]  [{DIM}](all changes written immediately)[/]"
        if auto else
        f"[{DIM}]diff review on — type [/][bold {CYAN}]autoaccept on[/][{DIM}] to disable[/]"
    )

    git_line = ""
    if git.get("branch"):
        dirty = f"  [{YELLOW}]{len(git.get('dirty',[]))} unstaged[/]" if git.get("dirty") else ""
        git_line = f"\n[{DIM}]  git          [/][bold {CYAN}]{git['branch']}[/]{dirty}"

    rules_line = f"\n[{DIM}]  .zenrules    [/][bold {GREEN}]✔ active[/]" if rules else ""

    body = (
        f"[{DIM}]  workspace    [/][bold {CYAN}]{ws}[/]\n"
        f"[{DIM}]  project      [/]{files_line}\n"
        f"[{DIM}]  model        [/][bold {CYAN}]{cfg.get('model')}[/]\n"
        f"[{DIM}]  changes      [/]{accept_line}\n"
        f"[{DIM}]  key          [/]{key_line}"
        f"{git_line}{rules_line}"
    )
    console.print(Align.center(Panel(
        body, border_style=CYAN, box=box.DOUBLE_EDGE,
        padding=(0, 4), width=min(78, W()-4),
    )))
    console.print()

    hints = [
        ("chat","AI session"),("build \"...\"","build project"),
        ("fix","auto-debug"),("diff","show pending"),
        ("scan","file tree"),("tree","rich tree"),
        ("git","git ops"),("rules","manage .zenrules"),
        ("help","all commands"),
    ]
    hs = "   ".join(f"[bold {CYAN}]{c}[/] [{DIM}]{d}[/]" for c,d in hints)
    console.print(Align.center(Text.from_markup(hs)))
    console.print()


# ── @file reference parser ─────────────────────────────────────────────────────

def _expand_at_refs(text: str) -> tuple[str, List[str]]:
    """
    Parse @filename or @path/to/file references in user input.
    Returns (expanded_text, list_of_resolved_paths).
    """
    ws = cfg.workspace()
    pattern = r"@([\w./\\-]+)"
    refs = re.findall(pattern, text)
    loaded = []
    injected = []

    for ref in refs:
        # Try direct path, then fuzzy match in workspace
        candidates = [ws / ref]
        if not (ws / ref).exists():
            # Search for it
            sc = get_scanner(ws)
            all_files = sc.get_file_list()
            matches = [f for f in all_files if ref.lower() in f.lower()]
            if matches:
                candidates = [ws / matches[0]]

        for p in candidates:
            if p.exists() and p.is_file():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    rel = str(p.relative_to(ws)) if str(p).startswith(str(ws)) else str(p)
                    loaded.append(rel)
                    lines = len(content.splitlines())
                    injected.append(f"\n--- @{rel} ({lines} lines) ---\n{content}\n---")
                except Exception:
                    pass
                break

    if injected:
        expanded = text + "\n\n[REFERENCED FILES]\n" + "\n".join(injected)
    else:
        expanded = text

    return expanded, loaded


# ── Tool rendering ─────────────────────────────────────────────────────────────

TOOL_ICONS = {
    "file_read":"📖","file_write":"✏","file_patch":"🔧","file_delete":"🗑",
    "file_rename":"↩","file_copy":"📋",
    "list_directory":"📁","create_directory":"📂",
    "find_files":"🔍","grep_files":"🔎","search_in_files":"🔍",
    "run_code":"▶","run_shell":"⚙","run_any_command":"🧪","run_tests":"✅","install_packages":"📦",
    "web_fetch":"🌐","web_search_tool":"🔍",
    "git_command":"⎇","mcp_call":"⬡","delete_tests":"🧹",
}

def render_tool_call(tc: ToolCall):
    icon = TOOL_ICONS.get(tc.name,"⬡")
    arg = ""
    for key in ("path","command","packages","pattern","query","code","url","new_path"):
        if key in tc.arguments:
            v = tc.arguments[key]
            if isinstance(v, list): v = ", ".join(str(x) for x in v)
            v = str(v)
            arg = f"  [{DIM}]{v[:80]}{'…' if len(v)>80 else ''}[/]"
            break
    console.print(f"  [{VIOLET}]{icon}[/]  [{WHITE}]{tc.name}[/]{arg}")

def render_tool_result(tc: ToolCall):
    if tc.result is None: return
    r = tc.result
    dur = f" [{DIM}]{tc.duration_ms}ms[/]" if tc.duration_ms else ""
    if r.success:
        preview = r.output.strip().replace("\n"," ↵ ")[:140]
        console.print(f"  [{GREEN}]✔[/]{dur}  [{DIM}]{preview}[/]")
    else:
        console.print(f"  [{RED}]✖[/]{dur}  [{RED}]{r.error[:180]}[/]")


# ── Diff review UI ─────────────────────────────────────────────────────────────

def run_diff_review(diff_set: DiffSet, auto_accept: bool = False) -> int:
    ws = cfg.workspace()
    if auto_accept:
        reviewer = DiffReviewer(console, auto_accept=True)
        accepted, _ = reviewer.review(diff_set, ws)
        if accepted: ok(f"Auto-accepted {len(accepted)} file(s)")
        return len(accepted)
    if not diff_set.diffs: return 0
    console.print()
    render_diffset_summary(diff_set, console)
    console.print(Text.from_markup(
        f"  [{CYAN}]Review:[/]  "
        f"[bold {GREEN}][a][/]ccept  "
        f"[bold {RED}][r][/]eject  "
        f"[bold {CYAN}][A][/] accept-all  "
        f"[bold {WHITE}][d][/] show-diff  "
        f"[bold {YELLOW}][s][/]kip"
    ))
    console.print()
    pt_style = PTStyle.from_dict({"":"#e8eaf6"})
    accepted_all = False
    accepted_count = 0
    for i, diff in enumerate(diff_set.diffs):
        if accepted_all:
            _write_diff(diff, ws); accepted_count += 1
            console.print(f"  [{GREEN}]✔[/]  [{WHITE}]{diff.path}[/]  [{DIM}]auto-accepted[/]")
            continue
        status_color = GREEN if diff.is_new else (RED if diff.is_delete else CYAN)
        status_label = "NEW" if diff.is_new else ("DEL" if diff.is_delete else "MOD")
        console.print(
            f"  [{status_color}][{status_label}][/]  [{WHITE}]{diff.path}[/]  "
            f"[{DIM}]({i+1}/{len(diff_set.diffs)})[/]  "
            f"[{GREEN}]+{diff.lines_added}[/] [{RED}]-{diff.lines_removed}[/]"
        )
        while True:
            try:
                resp = PromptSession(style=pt_style).prompt(
                    HTML('<ansigray>  [a/r/A/d/s] › </ansigray>')
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                resp = "s"
            if resp == "d": render_diff_rich(diff, console); continue
            elif resp in ("a","y","","accept"): _write_diff(diff, ws); accepted_count += 1; console.print(f"  [{GREEN}]✔  accepted[/]"); break
            elif resp in ("r","n","reject","no"): console.print(f"  [{RED}]✖  rejected[/]"); break
            elif resp in ("a_all","all") or resp == chr(65):
                _write_diff(diff, ws); accepted_count += 1; accepted_all = True
                console.print(f"  [{GREEN}]✔  accepted (all remaining auto-accepted)[/]"); break
            elif resp in ("s","skip"): console.print(f"  [{DIM}]↷  skipped[/]"); break
            else: console.print(f"  [{DIM}]a=accept  r=reject  A=accept all  d=diff  s=skip[/]")
        console.print()
    if accepted_count: ok(f"Applied {accepted_count}/{len(diff_set.diffs)} change(s)")
    return accepted_count


def _write_diff(diff: FileDiff, workspace: Path):
    target = workspace / diff.path
    if diff.is_delete:
        if target.exists(): target.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(diff.new_content, encoding="utf-8")


def show_full_diff(diff_set: DiffSet):
    if not diff_set or not diff_set.diffs:
        warn("No pending diffs to show."); return
    console.print(); section_rule("DIFF VIEW")
    for diff in diff_set.diffs:
        render_diff_rich(diff, console); console.print()
    render_diffset_summary(diff_set, console)


_pending_diffs: List[DiffSet] = []

def _push_diff(ds: DiffSet): _pending_diffs.append(ds)
def _has_pending_diffs() -> bool: return bool(_pending_diffs)
def _flush_diffs(auto: bool = False) -> int:
    total = 0
    while _pending_diffs:
        ds = _pending_diffs.pop(0)
        total += run_diff_review(ds, auto_accept=auto)
    return total


# ── Stream renderer ────────────────────────────────────────────────────────────

def render_chunks(chunk_iter, show_badge: bool = True,
                  auto_accept: bool = None) -> Optional[ZenResponse]:
    if auto_accept is None: auto_accept = cfg.auto_accept()
    buf = ""; final_resp = None; live = None
    syntax_theme = cfg.get("syntax_theme","monokai")

    def _start():
        nonlocal live, buf
        buf = ""
        live = Live("", console=console, refresh_per_second=20, vertical_overflow="visible")
        live.__enter__()

    def _stop():
        nonlocal live
        if live:
            try: live.__exit__(None,None,None)
            except Exception: pass
            live = None

    console.print(); _start()
    for chunk in chunk_iter:
        if chunk.chunk_type == "delta":
            buf += chunk.delta
            if live: live.update(Markdown(buf, code_theme=syntax_theme))
        elif chunk.chunk_type == "tool_call":
            _stop(); render_tool_call(chunk.tool_call); _start()
        elif chunk.chunk_type == "tool_result":
            _stop(); render_tool_result(chunk.tool_call); _start()
        elif chunk.chunk_type == "status":
            _stop()
            lvl = chunk.status_level or "info"
            col = {"ok":GREEN,"warn":YELLOW,"error":RED}.get(lvl, chunk.agent_color or CYAN)
            icon = {"ok":"●","warn":"⚠","error":"✖"}.get(lvl,"◉")
            console.print(f"  [{col}]{icon}[/]  [{WHITE}]{chunk.status_msg}[/]")
            console.print(); _start()
        elif chunk.chunk_type == "diff_ready":
            _stop()
            if chunk.diff_set and chunk.diff_set.diffs:
                _push_diff(chunk.diff_set)
                n = len(chunk.diff_set.diffs)
                console.print()
                console.print(Text.from_markup(
                    f"  [{VIOLET}]◈[/]  [{CYAN}]{n} file(s) staged[/]  "
                    f"[{DIM}]— type [/][bold {GREEN}]accept[/] [{DIM}]or review below[/]"
                ))
                if cfg.get("show_diff",True):
                    for diff in chunk.diff_set.diffs:
                        render_diff_rich(diff, console)
            _start()
        elif chunk.chunk_type == "newline":
            _stop(); console.print(); _start()
        elif chunk.chunk_type == "done":
            _stop(); final_resp = chunk.response; break
    _stop()
    if final_resp is None: return None

    if show_badge and cfg.get("show_agent_badge",True):
        name = final_resp.agent_name; color = final_resp.agent_color
        emoji = final_resp.agent_emoji
        role = AGENTS[name].role if name in AGENTS else ""
        badge = (f"[bold {color}]{emoji}  {name.upper()}[/]"
                 + (f"  [{DIM}]{role}[/]" if role else ""))
        console.print(Rule(title=badge, style=DIM))

    if not final_resp.ok: console.print(); err(final_resp.error)
    if final_resp.ok and cfg.get("show_token_count",True):
        tc = len(final_resp.tool_calls)
        tc_str = f"  [{DIM}]· {tc} tool call{'s' if tc!=1 else ''}[/]" if tc else ""
        console.print(Text.from_markup(
            f"  [{DIM}]{final_resp.tokens_in} in"
            f"  ·  {final_resp.tokens_out} out"
            f"  ·  {final_resp.latency_ms}ms"
            f"  ·  {final_resp.model}[/]{tc_str}"
        ))
    console.print()
    if _pending_diffs: _flush_diffs(auto=auto_accept)
    return final_resp


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_chat(auto_accept: bool = None):
    if auto_accept is None: auto_accept = cfg.auto_accept()
    ws = cfg.workspace(); scanner = get_scanner(ws); proj = scanner.get_info()
    proj_str = proj.get("framework") or proj.get("language") or ""
    rules = cfg.load_zenrules()
    mode_badge = (
        f"[bold {YELLOW}]AUTO-ACCEPT[/]" if auto_accept
        else f"[{CYAN}]DIFF REVIEW[/]"
    )
    console.print()
    console.print(Align.center(Panel(
        f"[bold {CYAN}]◉  ZENCODE CHAT[/]  {mode_badge}\n"
        f"[{DIM}]dir:[/] [bold {WHITE}]{ws}[/]"
        + (f"  [{CYAN}]({proj_str})[/]" if proj_str else "")
        + (f"  [{DIM}]{scanner.file_count()} files[/]" if scanner.file_count() else "")
        + (f"\n[{GREEN}]● .zenrules active[/]" if rules else "")
        + "\n\n"
        f"[{DIM}]Describe what to build or ask anything.[/]\n"
        f"[{DIM}]Use [/][bold {CYAN}]@filename[/][{DIM}] to reference files in your message.[/]\n"
        f"[{CYAN}]go[/][{DIM}] run plan  [/][{CYAN}]fix[/][{DIM}] debug  [/]"
        f"[{CYAN}]accept[/][{DIM}] apply diffs  [/][{CYAN}]diff[/][{DIM}] view diffs  [/]"
        f"[{CYAN}]back[/][{DIM}] exit[/]",
        border_style=CYAN, box=box.DOUBLE_EDGE,
        padding=(0,4), width=min(72,W()-4),
    )))
    console.print()

    session = PromptSession(
        history=InMemoryHistory(), auto_suggest=AutoSuggestFromHistory(),
        style=PTStyle.from_dict({"":"#e8eaf6"}),
    )
    prompt_html = HTML('<ansibrightcyan><b>you</b></ansibrightcyan><ansigray> › </ansigray>')
    last_prompt = ""

    while True:
        try:
            user = session.prompt(prompt_html).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user: continue
        if user.lower() in ("exit","quit","back","q"): ok("Back to shell"); console.print(); break

        # In-chat commands
        if user.lower() == "go":
            if core.has_pending_plan(): _exec_build(last_prompt, auto_accept)
            else: warn("No pending build plan. Describe a project first."); console.print()
            continue
        if user.lower() in ("fix","debug"): _exec_debug(); continue
        if user.lower() in ("accept","apply","yes","y"):
            if _has_pending_diffs(): _flush_diffs(auto=True)
            else: warn("No pending diffs."); console.print()
            continue
        if user.lower() == "diff":
            if _pending_diffs: show_full_diff(_pending_diffs[0])
            else: warn("No pending diffs."); console.print()
            continue
        if user.lower() == "reject":
            count = len(_pending_diffs); _pending_diffs.clear()
            warn(f"Rejected {count} pending diff set(s)."); console.print(); continue
        if user.lower().startswith("autoaccept"):
            parts = user.split(); val = parts[1] if len(parts) > 1 else "on"
            cfg.set("auto_accept", val); auto_accept = cfg.auto_accept()
            ok(f"Auto-accept: {'ON' if auto_accept else 'OFF'}"); console.print(); continue
        if user.lower() == "/scan": cmd_scan(); continue
        if user.lower() == "/index": cmd_index(); continue
        if user.lower() == "/tree": cmd_tree(); continue
        if user.lower() == "/mem": cmd_memory(); continue
        if user.lower() == "/clear": core.clear_memory(); ok("Memory cleared"); console.print(); continue

        # @file expansion
        expanded, loaded = _expand_at_refs(user)
        if loaded:
            console.print()
            for f in loaded:
                console.print(f"  [{CYAN}]@[/]  [{WHITE}]{f}[/]  [{DIM}]loaded into context[/]")
            console.print()

        last_prompt = user
        render_chunks(core.stream(expanded), auto_accept=auto_accept)

        if core.has_pending_plan():
            plan = core.get_pending_plan()
            console.print(Align.center(Panel(
                f"[bold {GREEN}]BUILD PLAN READY: {plan.name}[/]\n"
                f"[{DIM}]{len(plan.tasks)} tasks  ·  stack: {plan.stack}  ·  target: {plan.target_dir}[/]\n\n"
                f"[bold {CYAN}]Automated build mode:[/] executing now.",
                border_style=GREEN, box=box.DOUBLE_EDGE,
                padding=(0,4), width=min(64,W()-4),
            )))
            console.print()
            _exec_build(last_prompt, auto_accept=auto_accept)


def _exec_build(original_prompt: str = "", auto_accept: bool = None):
    if auto_accept is None: auto_accept = cfg.auto_accept()
    plan = core.get_pending_plan()
    if not plan: warn("No build plan."); return
    console.print(); section_rule(f"BUILDING: {plan.name}"); console.print()
    render_chunks(core.execute_build(original_prompt, auto_accept=auto_accept),
                  show_badge=False, auto_accept=auto_accept)
    try:
        sc = refresh_scanner(cfg.workspace())
        ok(f"Done — {sc.file_count()} files in {cfg.workspace()}"); console.print()
    except Exception: pass


def _exec_debug():
    console.print(); section_rule("AUTONOMOUS DEBUGGER"); console.print()
    dot("Debug agent running — will fix all errors autonomously...", RED); console.print()
    render_chunks(core.autonomous_debug(), show_badge=False, auto_accept=True)
    try: refresh_scanner(cfg.workspace())
    except Exception: pass


def cmd_build(args: List[str], auto_accept: bool = None):
    if auto_accept is None: auto_accept = cfg.auto_accept()
    prompt = " ".join(args).strip().strip("\"'")
    if not prompt:
        console.print()
        console.print(Align.center(Panel(
            f"[bold {CYAN}]build[/] — Build any project from a description\n\n"
            f"[{DIM}]Examples:[/]\n"
            f"  [bold {WHITE}]build \"Flask REST API with JWT auth and SQLite\"[/]\n"
            f"  [bold {WHITE}]build \"React todo app with Tailwind and shadcn\"[/]\n"
            f"  [bold {WHITE}]build \"CLI calculator in Go with readline\"[/]\n"
            f"  [bold {WHITE}]build \"Rust web scraper with reqwest and tokio\"[/]\n"
            f"  [bold {WHITE}]build \"Discord bot in Python with slash commands\"[/]\n\n"
            f"[{DIM}]Workspace = current directory. Named projects get a subdir.[/]",
            border_style=CYAN, box=box.ROUNDED,
            padding=(1,4), width=min(72,W()-4),
        )))
        console.print(); return

    console.print()
    console.print(Align.center(Panel(
        f"[bold {GREEN}]◉  ZENCODE BUILD[/]\n"
        f"[{DIM}]prompt:[/] [bold {WHITE}]{prompt[:80]}[/]\n"
        f"[{DIM}]dir:[/] [bold {CYAN}]{cfg.workspace()}[/]\n"
        f"[{DIM}]mode:[/] "
        + (f"[bold {YELLOW}]AUTO-ACCEPT[/]" if auto_accept else f"[{CYAN}]DIFF REVIEW[/]"),
        border_style=GREEN, box=box.DOUBLE_EDGE,
        padding=(0,4), width=min(72,W()-4),
    )))
    console.print()
    render_chunks(core.direct_build(prompt, auto_accept=auto_accept),
                  show_badge=False, auto_accept=auto_accept)
    try:
        sc = refresh_scanner(cfg.workspace())
        ok(f"Done — {sc.file_count()} files in {cfg.workspace()}")
    except Exception: pass
    console.print()


def cmd_fix(args: List[str]): _exec_debug()


def cmd_accept():
    if _has_pending_diffs():
        n = _flush_diffs(auto=True); ok(f"Applied {n} change(s)")
    else: warn("No pending diffs.")
    console.print()


def cmd_reject():
    if _pending_diffs:
        n = len(_pending_diffs); _pending_diffs.clear()
        warn(f"Rejected {n} pending diff set(s) — no files changed.")
    else: warn("No pending diffs.")
    console.print()


def cmd_diff():
    if _pending_diffs:
        for ds in _pending_diffs: show_full_diff(ds)
    else: warn("No staged diffs. Diffs appear after agent file changes.")
    console.print()


def cmd_scan():
    ws = cfg.workspace(); console.print(); section_rule(f"WORKSPACE: {ws.name}"); console.print()
    sc = refresh_scanner(ws)
    if sc.is_empty(): warn(f"Empty: {ws}"); console.print(); return
    proj = sc.get_info(); git = sc.get_git()
    parts = []
    if proj.get("language"):    parts.append(proj["language"])
    if proj.get("framework"):   parts.append(proj["framework"])
    if proj.get("entry_points"):parts.append(f"entry: {', '.join(proj['entry_points'][:2])}")
    if proj.get("run_cmd"):     parts.append(f"run: {proj['run_cmd']}")
    if proj.get("test_cmd"):    parts.append(f"test: {proj['test_cmd']}")
    if proj.get("dependencies"):parts.append(f"{len(proj['dependencies'])} deps")
    if parts: info(f"Detected: [{GREEN}]{' · '.join(parts)}[/]"); console.print()

    if git.get("branch"):
        dirty = f"  [{YELLOW}]{len(git.get('dirty',[]))} unstaged[/]" if git.get("dirty") else f"  [{GREEN}]clean[/]"
        info(f"Git: [{CYAN}]{git['branch']}[/]{dirty}")
        if git.get("commits"): info(f"Last commit: [{DIM}]{git['commits'][0]}[/]")
        console.print()

    rules = cfg.load_zenrules()
    if rules:
        info(f"[{GREEN}].zenrules active[/] — {len(rules.splitlines())} lines"); console.print()

    t = Table(
        box=box.SIMPLE_HEAD, border_style=DIM,
        header_style=f"bold {CYAN}", show_edge=False, padding=(0,2),
    )
    t.add_column("FILE", style=WHITE, min_width=32)
    t.add_column("TYPE", style=f"bold {VIOLET}", min_width=5)
    t.add_column("LINES", style=DIM, justify="right", min_width=6)
    t.add_column("SIZE",  style=DIM, justify="right", min_width=8)
    t.add_column("SYMBOLS", style=DIM, min_width=20)

    files = sorted(sc.get_file_list())
    sc_files = sc._files
    for fp in files[:50]:
        entry = sc_files.get(fp, {})
        p = ws / fp
        try: sz = p.stat().st_size; sz_s = f"{sz:,}B" if sz<1024 else f"{sz//1024}KB"
        except: sz_s = "—"
        syms = entry.get("symbols",[])
        sym_str = ", ".join(syms[:4]) + ("…" if len(syms)>4 else "") if syms else ""
        secret = " ⚠" if entry.get("has_secret") else ""
        t.add_row(fp+secret, Path(fp).suffix or "—",
                  str(entry.get("lines","—")), sz_s, sym_str)
    if len(files) > 50:
        t.add_row(f"[{DIM}]... ({len(files)-50} more)[/]","","","","")
    console.print(t)
    info(f"{len(files)} files  ·  {ws}"); console.print()


def cmd_tree():
    """Rich visual file tree."""
    ws = cfg.workspace(); console.print(); section_rule(f"FILE TREE: {ws.name}"); console.print()
    sc = get_scanner(ws)
    if sc.is_empty(): warn("Empty workspace."); return

    SKIP = {"__pycache__",".git","node_modules",".venv","venv","dist","build"}
    EXT_COLORS = {
        ".py": CYAN, ".js": YELLOW, ".ts": BLUE, ".jsx": YELLOW, ".tsx": BLUE,
        ".go": CYAN, ".rs": ORANGE, ".rb": RED, ".php": VIOLET, ".java": ORANGE,
        ".md": GREEN, ".json": YELLOW, ".yaml": DIM, ".yml": DIM,
        ".html": ORANGE, ".css": PINK, ".scss": PINK,
        ".sh": GREEN, ".env": RED, ".toml": YELLOW,
    }

    tree = Tree(f"[bold {CYAN}]{ws.name}/[/]")

    def _add_dir(parent_node, path: Path, depth: int):
        if depth > 5: return
        try:
            items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError: return
        for item in items:
            if item.name.startswith(".") and item.name not in {".env",".env.example",".gitignore",".zenrules"}: continue
            if item.name in SKIP or item.name.endswith(".egg-info"): continue
            if item.is_dir():
                node = parent_node.add(f"[bold {DIM}]{item.name}/[/]")
                _add_dir(node, item, depth+1)
            else:
                ext = item.suffix.lower()
                color = EXT_COLORS.get(ext, WHITE)
                try: sz = item.stat().st_size; sz_s = f"[{DIM}] {sz//1024}K[/]" if sz>=1024 else ""
                except: sz_s = ""
                parent_node.add(f"[{color}]{item.name}[/]{sz_s}")

    _add_dir(tree, ws, 0)
    console.print(tree)
    info(f"{sc.file_count()} files  ·  {ws}"); console.print()


def cmd_index():
    ws = cfg.workspace(); console.print(); section_rule("CODEBASE INDEX"); console.print()
    from zencode.workspace_scanner import WorkspaceScanner
    sc = WorkspaceScanner(ws).scan()
    if sc.is_empty(): warn(f"Empty: {ws}"); console.print(); return
    ctx = sc.get_full_context(max_chars=8000)
    console.print(Syntax(ctx, "text", theme=cfg.get("syntax_theme","monokai"),
                         line_numbers=False, padding=(1,2)))
    info(f"{sc.file_count()} files indexed  ·  this is what AI agents see"); console.print()


def cmd_read(path: str):
    if not path: err("Usage: read <path>"); return
    result = file_read(path)
    if not result.success: err(result.error); return
    console.print(); section_rule(f"  {path}"); console.print()
    ext_map = {
        ".py":"python",".js":"javascript",".ts":"typescript",".jsx":"javascript",
        ".tsx":"typescript",".go":"go",".rs":"rust",".rb":"ruby",".php":"php",
        ".java":"java",".cpp":"cpp",".c":"c",".cs":"csharp",
        ".json":"json",".yaml":"yaml",".yml":"yaml",".toml":"toml",
        ".sh":"bash",".md":"markdown",".html":"html",".css":"css",".sql":"sql",
        ".lua":"lua",".swift":"swift",
    }
    lang = ext_map.get(Path(path).suffix.lower(),"text")
    console.print(Syntax(result.output, lang,
                         theme=cfg.get("syntax_theme","monokai"),
                         line_numbers=True, padding=(0,2)))
    m = result.metadata; console.print()
    info(f"{m.get('total_lines',0)} lines  ·  {m.get('size_bytes',0):,} bytes  ·  {path}")
    console.print()


def cmd_run(path: str, extra: List[str]):
    if not path: err("Usage: run <path>"); return
    console.print(); section_rule(f"RUN  {path}"); console.print()
    from zencode.tools import run_code
    result = run_code(path=path, args=extra, timeout=60)
    if result.success: ok(f"Exit 0  ·  [{DIM}]{result.metadata.get('duration_ms',0)}ms[/]")
    else: err(f"Exit {result.metadata.get('exit_code','?')}  ·  {result.error}")
    if result.output and result.output != "(no output)":
        console.print()
        console.print(Syntax(result.output,"text",theme=cfg.get("syntax_theme","monokai"),padding=(1,2)))
    console.print()


def cmd_git(args: List[str]):
    """Git operations — or open interactive git session."""
    if args:
        # Direct git command
        cmd = " ".join(args)
        console.print(); section_rule(f"GIT: {cmd}"); console.print()
        from zencode.tools import git_command
        result = git_command(cmd)
        if result.success: ok(result.output or "Done")
        else: err(result.error)
        console.print(); return

    # Interactive git session
    ws = cfg.workspace()
    console.print()
    console.print(Align.center(Panel(
        f"[bold {ORANGE}]⎇  GIT SESSION[/]\n"
        f"[{DIM}]workspace:[/] [{WHITE}]{ws}[/]\n\n"
        f"[{DIM}]Describe what you want to do with git.[/]\n"
        f"[{DIM}]Examples: 'commit everything', 'create a feature branch', 'show history'[/]\n"
        f"[{CYAN}]back[/][{DIM}] or [/][{CYAN}]exit[/][{DIM}] to leave[/]",
        border_style=ORANGE, box=box.DOUBLE_EDGE, padding=(0,4), width=min(70,W()-4),
    )))
    console.print()

    # Quick status
    from zencode.tools import git_command
    status = git_command("status --short")
    if status.success and status.output:
        console.print(Syntax(status.output,"bash",theme=cfg.get("syntax_theme","monokai"),padding=(0,2)))
        console.print()

    session = PromptSession(history=InMemoryHistory(), auto_suggest=AutoSuggestFromHistory(),
                            style=PTStyle.from_dict({"":"#e8eaf6"}))
    prompt_html = HTML(f'<ansibrightred><b>git</b></ansibrightred><ansigray> › </ansigray>')

    while True:
        try: user = session.prompt(prompt_html).strip()
        except (EOFError, KeyboardInterrupt): break
        if not user: continue
        if user.lower() in ("exit","quit","back","q"): ok("Back to shell"); console.print(); break
        render_chunks(core.stream_agent("git", user), auto_accept=True)


def cmd_search(args: List[str]):
    """Search across files — regex, pattern, or substring."""
    if not args: err("Usage: search <pattern> [path] [--regex] [--ext .py]"); return
    pattern = args[0]; path = "."; file_ext = None; regex = False
    for i, a in enumerate(args[1:]):
        if a == "--regex": regex = True
        elif a.startswith("--ext"): file_ext = args[i+2] if i+2 < len(args) else None
        elif not a.startswith("--"): path = a

    from zencode.tools import grep_files
    console.print(); section_rule(f"SEARCH: {pattern}"); console.print()
    result = grep_files(pattern, path=path, file_ext=file_ext, context_lines=2, regex=regex)
    if result.success:
        console.print(Syntax(result.output,"text",theme=cfg.get("syntax_theme","monokai"),padding=(1,2)))
        info(f"{result.metadata.get('matches',0)} match(es)")
    else: err(result.error)
    console.print()


def cmd_rules(args: List[str]):
    """Manage .zenrules — the project brain for AI agents."""
    ws = cfg.workspace(); rules_path = cfg.zenrules_path()

    if not args or args[0] == "show":
        console.print(); section_rule(".ZENRULES"); console.print()
        if not rules_path.exists():
            warn(f"No .zenrules in {ws}")
            console.print()
            console.print(Align.center(Panel(
                f"[{DIM}].zenrules tells AI agents how to behave in YOUR project.[/]\n\n"
                f"[{CYAN}]rules init[/][{DIM}] — create a starter .zenrules file[/]\n"
                f"[{CYAN}]rules edit[/][{DIM}] — open .zenrules in your editor[/]\n"
                f"[{CYAN}]rules set \"<rule>\"[/][{DIM}] — append a rule[/]\n\n"
                f"[{DIM}]Example rules:[/]\n"
                f"  [bold]Use TypeScript strict mode always[/]\n"
                f"  [bold]Follow Airbnb ESLint style guide[/]\n"
                f"  [bold]All functions must have JSDoc comments[/]\n"
                f"  [bold]Use environment variables for all secrets[/]",
                border_style=CYAN, box=box.ROUNDED, padding=(1,4), width=min(72,W()-4),
            )))
            console.print(); return
        content = rules_path.read_text("utf-8")
        console.print(Syntax(content,"markdown",theme=cfg.get("syntax_theme","monokai"),
                             line_numbers=True, padding=(0,2)))
        info(f"{len(content.splitlines())} rules  ·  {rules_path}"); console.print()

    elif args[0] == "init":
        if rules_path.exists():
            warn(f".zenrules already exists — use 'rules show' or 'rules edit'"); return
        proj = get_scanner(ws).get_info()
        lang = proj.get("language","unknown"); fw = proj.get("framework","")
        starter = f"""# .zenrules — ZENCODE Project Rules
# These rules are injected into every AI agent prompt.
# Be specific. These override all defaults.

## Language & Stack
- Language: {lang}{f', Framework: {fw}' if fw else ''}
- Follow idiomatic {lang} conventions

## Code Style
- Always include error handling
- Write clear variable and function names
- Add comments for complex logic

## Project Conventions
- Use environment variables for all secrets and config
- Never hardcode credentials or API keys
- Keep functions small and focused (single responsibility)

## Testing
- Write tests for all new functionality
- {'pytest' if 'python' in lang.lower() else 'relevant test framework'} for testing

## Git
- Follow Conventional Commits format: feat/fix/chore/docs/refactor/test
- Keep commits small and atomic
"""
        rules_path.write_text(starter, "utf-8")
        ok(f"Created .zenrules at {rules_path}")
        console.print(); cmd_rules(["show"])

    elif args[0] == "edit":
        editor = os.environ.get("EDITOR","nano")
        if not rules_path.exists(): cmd_rules(["init"]); return
        os.system(f'{editor} "{rules_path}"')
        ok("Saved .zenrules"); console.print()

    elif args[0] == "set" and len(args) > 1:
        rule = " ".join(args[1:]).strip('"\'')
        if not rules_path.exists(): rules_path.write_text("# .zenrules\n", "utf-8")
        with open(rules_path, "a", encoding="utf-8") as f:
            f.write(f"\n- {rule}")
        ok(f"Added rule: {rule}"); console.print()

    elif args[0] == "clear":
        if rules_path.exists(): rules_path.unlink(); ok("Cleared .zenrules")
        else: warn("No .zenrules to clear")
        console.print()


def cmd_config():
    console.print()
    data = cfg.all(); api = data.pop("api_key","")
    masked = (api[:6]+"••••"+api[-4:]) if len(api)>10 else f"[{RED}]not set[/]"
    lines = [f"  [{DIM}]{'api_key':<26}[/] [bold {CYAN}]{masked}[/]"]
    groups = {
        "model":   ["model","temperature","max_tokens"],
        "review":  ["auto_accept","show_diff","diff_context_lines"],
        "debug":   ["max_debug_iterations"],
        "context": ["max_context_files","max_context_chars"],
        "ui":      ["syntax_theme","show_token_count","splash_on_start"],
        "chat":    ["chat_history_limit"],
    }
    for group, keys in groups.items():
        lines.append(f"\n  [{DIM}]── {group} ──[/]")
        for k in keys:
            if k in data:
                v = str(data[k]); color = YELLOW if k=="auto_accept" and data[k] else CYAN
                lines.append(f"  [{DIM}]{k:<26}[/] [bold {color}]{v}[/]")
    console.print(Align.center(Panel(
        "\n".join(lines), title=f"[bold {CYAN}]⬡  CONFIG v{VERSION}[/]",
        subtitle=f"[{DIM}]{cfg.path()}[/]",
        border_style=CYAN, box=box.ROUNDED, padding=(0,2), width=min(82,W()-4),
    )))
    console.print()


def cmd_setconfig(key: str, val: str):
    old = cfg.get(key,"<unset>")
    try: cfg.set(key, val)
    except ValueError as e: err(str(e)); return
    ok(f"[{DIM}]{key}[/]  [{DIM}]{old}[/]  [{CYAN}]→[/]  [bold {WHITE}]{cfg.get(key)}[/]")
    if key == "api_key": core._invalidate_client(); ok("Client refreshed")
    console.print()


def cmd_autoaccept(val: str):
    on = val.lower() in ("on","true","1","yes","")
    cfg.set("auto_accept", on)
    if on: ok(f"[bold {YELLOW}]AUTO-ACCEPT ON[/]  [{DIM}]— all changes written immediately[/]")
    else: ok(f"[{CYAN}]DIFF REVIEW ON[/]  [{DIM}]— you review each change[/]")
    console.print()


def cmd_models():
    console.print(); section_rule("MISTRAL MODELS"); console.print()
    cur = cfg.get("model")
    t = Table(box=box.SIMPLE_HEAD, border_style=DIM, header_style=f"bold {CYAN}",
              show_edge=False, padding=(0,2))
    t.add_column("", width=3); t.add_column("MODEL", style=f"bold {CYAN}", min_width=24)
    t.add_column("ALIAS", style=DIM, min_width=8); t.add_column("TIER", style=VIOLET, min_width=10)
    t.add_column("CTX", style=WHITE, justify="right", min_width=8); t.add_column("INFO", style=DIM)
    for mid, m in MISTRAL_MODELS.items():
        active = mid == cur
        t.add_row(
            f"[bold {GREEN}]▶[/]" if active else "",
            f"[bold {GREEN}]{mid}[/]" if active else mid,
            m["alias"], m["tier"], f"{m['context_window']:,}", m["description"],
        )
    console.print(t)
    info(f"Active: [bold {CYAN}]{cur}[/]  ·  change: [bold {WHITE}]setconfig model <name>[/]"); console.print()


def cmd_memory():
    s = core.memory_stats(); console.print()
    console.print(Align.center(Panel(
        f"  [{DIM}]messages  [/][bold {CYAN}]{s['messages']}[/]\n"
        f"  [{DIM}]turns     [/][bold {CYAN}]{s['turns']}[/]\n"
        f"  [{DIM}]limit     [/][bold {CYAN}]{s['limit']}[/]",
        title=f"[bold {CYAN}]⬡  MEMORY[/]",
        border_style=CYAN, box=box.ROUNDED, padding=(0,2), width=min(36,W()-4),
    )))
    console.print()


def cmd_help():
    console.print()
    t = Table(box=box.SIMPLE_HEAD, border_style=DIM, header_style=f"bold {CYAN}",
              show_edge=False, padding=(0,2), min_width=70)
    t.add_column("COMMAND", style=f"bold {CYAN}", min_width=32)
    t.add_column("DESCRIPTION", style=WHITE)
    rows = [
        ("── AI ──",""),
        ("chat",                  "Open AI session — build, edit, ask anything"),
        ("chat @file1 @file2",    "Reference specific files in your AI conversation"),
        ("build \"<prompt>\"",   "Build a project directly from a description"),
        ("fix",                   "Autonomous debug loop — runs, fixes, repeats"),
        ("── FILES ──",""),
        ("tree",                  "Rich visual file tree with colors"),
        ("scan",                  "File list with types, lines, symbols"),
        ("read <path>",           "Display file with syntax highlighting"),
        ("run <path>",            "Execute any file"),
        ("search <pattern>",      "Search file contents (supports --regex, --ext .py)"),
        ("index",                 "Full codebase context (what AI agents see)"),
        ("── GIT ──",""),
        ("git",                   "Interactive git session (AI-powered)"),
        ("git <cmd>",             "Direct git command: git log, git diff, git status"),
        ("── RULES ──",""),
        ("rules",                 "Show .zenrules for this project"),
        ("rules init",            "Create starter .zenrules from project type"),
        ("rules edit",            "Edit .zenrules in $EDITOR"),
        ("rules set \"<rule>\"",  "Append a rule to .zenrules"),
        ("── DIFFS ──",""),
        ("accept / reject",       "Accept or reject staged file changes"),
        ("diff",                  "View staged diffs before deciding"),
        ("autoaccept on/off",     "Toggle auto-accept (skip review)"),
        ("── CONFIG ──",""),
        ("models",                "List available Mistral models"),
        ("config",                "View all settings"),
        ("setconfig <k> <v>",     "Change a setting (e.g. setconfig model mistral-large-latest)"),
        ("memory / clearmem",     "Conversation memory stats / clear"),
        ("── SHELL ──",""),
        ("clear",                 "Redraw splash"),
        ("help / ?",              "This table"),
        ("exit / q",              "Quit"),
    ]
    for cmd, desc in rows:
        if cmd.startswith("──"): t.add_row(f"[{DIM}]{cmd}[/]","")
        else: t.add_row(cmd, desc)
    console.print(Align.center(t))
    console.print()
    console.print(Align.center(Text.from_markup(
        f"[bold {CYAN}]@file[/] [{DIM}]references work in chat: type[/] [bold {WHITE}]'refactor @app.py to use async'[/]\n"
        f"[{DIM}]Workspace = directory you run zencode from. All languages supported.[/]\n"
        f"[{DIM}]Internet access via web_fetch and web_search. Git access via git_command.[/]"
    )))
    console.print()


# ── Prompt + dispatch ──────────────────────────────────────────────────────────

_session: Optional[PromptSession] = None

def _get_session() -> PromptSession:
    global _session
    if _session is None:
        _session = PromptSession(
            history=HISTORY, auto_suggest=AutoSuggestFromHistory(),
            style=PTStyle.from_dict({"":"#e8eaf6"}),
        )
    return _session

def zenprompt() -> HTML:
    ws = cfg.workspace().name or str(cfg.workspace())
    plan  = " [plan]"  if core.has_pending_plan()  else ""
    diffs = " [diff]"  if _has_pending_diffs()     else ""
    auto  = " [auto]"  if cfg.auto_accept()        else ""
    rules = " [rules]" if cfg.load_zenrules()      else ""
    return HTML(
        f'<ansibrightcyan><b>❯ zencode</b></ansibrightcyan>'
        f'<ansigray> [{ws}{plan}{diffs}{auto}{rules}] </ansigray>'
        f'<ansibrightcyan><b>❯ </b></ansibrightcyan>'
    )

ALIASES = {
    "c":"chat","b":"build","cfg":"config","s":"scan","t":"tree",
    "m":"models","r":"read","h":"help","?":"help",
    "q":"exit","cls":"clear","idx":"index",
    "aa":"autoaccept","a":"accept","rej":"reject",
    "sr":"search","g":"git",
}

def dispatch(raw: str, auto_accept: bool = None) -> Optional[str]:
    if auto_accept is None: auto_accept = cfg.auto_accept()
    parts = raw.strip().split()
    if not parts: return None
    cmd  = ALIASES.get(parts[0].lower(), parts[0].lower())
    args = parts[1:]

    if cmd == "help":        cmd_help()
    elif cmd == "chat":      cmd_chat(auto_accept)
    elif cmd == "build":     cmd_build(args, auto_accept)
    elif cmd in ("fix","debug"): cmd_fix(args)
    elif cmd == "accept":    cmd_accept()
    elif cmd == "reject":    cmd_reject()
    elif cmd == "diff":      cmd_diff()
    elif cmd == "autoaccept": cmd_autoaccept(args[0] if args else "on")
    elif cmd == "scan":      cmd_scan()
    elif cmd == "tree":      cmd_tree()
    elif cmd == "index":     cmd_index()
    elif cmd == "read":      cmd_read(args[0] if args else "")
    elif cmd == "run":       cmd_run(args[0] if args else "", args[1:])
    elif cmd == "search":    cmd_search(args)
    elif cmd == "git":       cmd_git(args)
    elif cmd == "rules":     cmd_rules(args)
    elif cmd == "models":    cmd_models()
    elif cmd == "config":    cmd_config()
    elif cmd == "memory":    cmd_memory()
    elif cmd == "clearmem":  core.clear_memory(); ok("Memory cleared"); console.print()
    elif cmd == "setconfig":
        if len(args) >= 2: cmd_setconfig(args[0], " ".join(args[1:]))
        else: err("Usage: setconfig <key> <value>")
    elif cmd == "resetconfig": cfg.reset(); ok("Config reset"); console.print()
    elif cmd == "go":
        if core.has_pending_plan(): _exec_build("", auto_accept)
        else: warn("No pending build plan."); console.print()
    elif cmd == "clear": show_splash()
    elif cmd in ("exit","quit"): return "EXIT"
    else:
        err(f"Unknown: [{WHITE}]{cmd}[/]")
        info("Type [bold]help[/] or [bold]?[/]")
    return None


def shell_loop(auto_accept: bool = False):
    if auto_accept: cfg.set("auto_accept", True)
    show_splash()

    def _sigint(sig, frame):
        console.print(
            f"\n  [{YELLOW}]⚠[/]  [{DIM}]Ctrl+C — type [/]"
            f"[bold {CYAN}]exit[/][{DIM}] to quit[/]\n"
        )
    signal.signal(signal.SIGINT, _sigint)
    session = _get_session()

    while True:
        try: raw = session.prompt(zenprompt())
        except KeyboardInterrupt: continue
        except EOFError:
            console.print(); ok("Goodbye."); time.sleep(0.2); break

        if dispatch((raw or "").strip(), auto_accept=auto_accept) == "EXIT":
            console.print()
            console.print(Align.center(Panel(
                f"[bold {CYAN}]ZENCODE OFFLINE[/]\n[{DIM}]see you next time[/]",
                border_style=DIM, box=box.DOUBLE_EDGE,
                padding=(0,6), width=min(36,W()-4),
            )))
            console.print(); time.sleep(0.3); break


# ── Entry point ────────────────────────────────────────────────────────────────

@click.command(context_settings={"help_option_names":["--help"]})
@click.option("--version", is_flag=True,  help="Show version.")
@click.option("--setkey",  default=None,  metavar="KEY", help="Save Mistral API key and exit.")
@click.option("--yes",     is_flag=True,  default=False, help="Auto-accept all changes (no diff prompts).")
@click.option("--workspace", default=None, metavar="PATH", help="Use a specific directory (default: current dir).")
def main(version, setkey, yes, workspace):
    """ZENCODE v11 — Autonomous AI Code Shell. More capable than Cursor.

    \b
    Run from any directory:
      cd ~/myproject && zencode
      zencode --yes            auto-accept everything
      zencode --setkey KEY     save your Mistral API key

    \b
    In chat, use @filename to reference files:
      you › refactor @app.py to use async/await
      you › what does @src/auth.go do?
    """
    if version:
        console.print(gradient(f"ZENCODE v{VERSION}")); return
    if setkey:
        cfg.set("api_key", setkey)
        console.print(f"  [{GREEN}]✔[/]  Key saved → {cfg.path()}")
        console.print(f"  [{CYAN}]⬡[/]  Run [bold]zencode[/] to start"); return

    target = Path(workspace).resolve() if workspace else Path.cwd()
    if not target.exists():
        console.print(f"  [{RED}]✖[/]  Directory not found: {workspace}"); return
    cfg.set_workspace(str(target))
    shell_loop(auto_accept=yes)


if __name__ == "__main__":
    main()
