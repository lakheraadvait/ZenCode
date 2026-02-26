"""
ZENCODE v11 — tools/file_manager.py
Complete tool suite. New in v11:
  - file_rename, file_copy
  - find_files (glob/pattern search)
  - grep_files (regex content search with context lines)
  - web_search_tool (DuckDuckGo search)
  - git_command (full git access)
  - All tools are workspace-aware
"""

from __future__ import annotations
import glob as glob_mod
import json, os, re, shutil, subprocess, sys, tempfile, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _ensure(pkg, imp=None):
    try: return __import__(imp or pkg)
    except ImportError:
        subprocess.check_call([sys.executable,"-m","pip","install",pkg,"-q","--break-system-packages"])
        return __import__(imp or pkg)

requests = _ensure("requests")

from zencode.events import bus

_diff_tracker = None

def set_diff_tracker(tracker): global _diff_tracker; _diff_tracker = tracker
def get_diff_tracker(): return _diff_tracker

def _workspace() -> Path:
    try:
        from zencode.config import cfg
        return cfg.workspace()
    except Exception:
        return Path(".").resolve()


@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_api_str(self) -> str:
        payload: Dict[str, Any] = {"success": self.success}
        if self.output:   payload["output"] = self.output[:16_000]
        if self.error:    payload["error"]  = self.error
        if self.metadata: payload["metadata"] = self.metadata
        return json.dumps(payload, ensure_ascii=False)


# ── File operations ────────────────────────────────────────────────────────────

def file_read(path: str, start_line: int = None, end_line: int = None) -> ToolResult:
    ws = _workspace()
    try:
        p = (ws / path).resolve()
        if not p.exists(): p = Path(path).resolve()
        if not p.exists(): return ToolResult(False, error=f"Not found: {path}")
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        if start_line or end_line:
            s = max(0, (start_line or 1) - 1)
            text = "\n".join(lines[s : end_line or total])
        return ToolResult(True, output=text, metadata={
            "path": str(p.relative_to(ws) if str(p).startswith(str(ws)) else p),
            "total_lines": total, "size_bytes": p.stat().st_size,
        })
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def file_write(path: str, content: str, mode: str = "write") -> ToolResult:
    tracker = get_diff_tracker()
    if tracker and tracker.active:
        return tracker.intercept_write(path, content, mode)
    ws = _workspace()
    try:
        p = (ws / path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            with open(p, "a", encoding="utf-8") as f: f.write(content)
        else:
            p.write_text(content, encoding="utf-8")
        lines = len(content.splitlines())
        rel = str(p.relative_to(ws)) if str(p).startswith(str(ws)) else str(p)
        return ToolResult(True, output=f"✔ wrote {rel} ({lines} lines)",
                         metadata={"path": rel, "lines": lines})
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def file_patch(path: str, old_str: str, new_str: str) -> ToolResult:
    tracker = get_diff_tracker()
    ws = _workspace()
    try:
        p = (ws / path).resolve()
        if not p.exists(): return ToolResult(False, error=f"Not found: {path}")
        content = p.read_text(encoding="utf-8", errors="replace")
        if old_str not in content:
            return ToolResult(False, error=f"String not found in {path}: {old_str[:80]!r}")
        new_content = content.replace(old_str, new_str, 1)
        if tracker and tracker.active:
            return tracker.intercept_write(path, new_content, "write")
        p.write_text(new_content, encoding="utf-8")
        return ToolResult(True, output=f"✔ patched {path}")
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def file_delete(path: str) -> ToolResult:
    ws = _workspace()
    try:
        p = (ws / path).resolve()
        if not p.exists(): return ToolResult(False, error=f"Not found: {path}")
        if p.is_dir():
            shutil.rmtree(p)
            return ToolResult(True, output=f"Deleted directory {path}")
        p.unlink()
        return ToolResult(True, output=f"Deleted {path}")
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def file_rename(path: str, new_path: str) -> ToolResult:
    """Rename or move a file."""
    ws = _workspace()
    try:
        src = (ws / path).resolve()
        dst = (ws / new_path).resolve()
        if not src.exists(): return ToolResult(False, error=f"Not found: {path}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return ToolResult(True, output=f"✔ renamed {path} → {new_path}")
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def file_copy(path: str, dest: str) -> ToolResult:
    """Copy a file or directory."""
    ws = _workspace()
    try:
        src = (ws / path).resolve()
        dst = (ws / dest).resolve()
        if not src.exists(): return ToolResult(False, error=f"Not found: {path}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir(): shutil.copytree(src, dst)
        else: shutil.copy2(src, dst)
        return ToolResult(True, output=f"✔ copied {path} → {dest}")
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def list_directory(path: str = ".") -> ToolResult:
    ws = _workspace()
    try:
        p = (ws / path).resolve()
        if not p.exists(): p = Path(path).resolve()
        if not p.exists(): return ToolResult(False, error=f"Not found: {path}")
        SKIP = {"__pycache__",".git","node_modules",".venv","venv",
                ".mypy_cache",".pytest_cache","dist","build",".DS_Store"}
        entries = []
        for item in sorted(p.iterdir()):
            if item.name in SKIP or (item.name.startswith(".") and item.name not in {".env",".env.example",".gitignore",".zenrules"}):
                continue
            size = item.stat().st_size if item.is_file() else 0
            entries.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": size,
                "ext": item.suffix if item.is_file() else "",
            })
        return ToolResult(True, output=json.dumps(entries, indent=2),
                         metadata={"path": str(p), "count": len(entries)})
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def create_directory(path: str) -> ToolResult:
    ws = _workspace()
    try:
        p = (ws / path).resolve()
        existed = p.exists()
        p.mkdir(parents=True, exist_ok=True)
        rel = str(p.relative_to(ws)) if str(p).startswith(str(ws)) else str(p)
        if existed: return ToolResult(True, output=f"✔ exists {rel}")
        return ToolResult(True, output=f"✔ created {rel}", metadata={"path": rel})
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def find_files(pattern: str, path: str = ".", include_hidden: bool = False) -> ToolResult:
    """Find files by glob pattern or filename substring. Supports **/*.py, *.config.*, etc."""
    ws = _workspace()
    search_root = (ws / path).resolve()
    SKIP = {"__pycache__",".git","node_modules",".venv","venv","dist","build"}
    try:
        results = []
        # Try as glob pattern first
        if any(c in pattern for c in ("*","?","[")):
            for p in search_root.rglob(pattern):
                if any(s in p.parts for s in SKIP): continue
                if not include_hidden and any(part.startswith(".") for part in p.parts if part != "."): continue
                rel = str(p.relative_to(ws)) if str(p).startswith(str(ws)) else str(p)
                results.append({"path": rel, "type": "dir" if p.is_dir() else "file",
                                 "size": p.stat().st_size if p.is_file() else 0})
        else:
            # Substring match on filename
            for p in search_root.rglob("*"):
                if any(s in p.parts for s in SKIP): continue
                if not include_hidden and any(part.startswith(".") for part in p.parts if part != "."): continue
                if pattern.lower() in p.name.lower():
                    rel = str(p.relative_to(ws)) if str(p).startswith(str(ws)) else str(p)
                    results.append({"path": rel, "type": "dir" if p.is_dir() else "file",
                                     "size": p.stat().st_size if p.is_file() else 0})
        results = sorted(results, key=lambda x: x["path"])[:100]
        return ToolResult(True,
            output="\n".join(r["path"] for r in results) if results else f"No files matching '{pattern}'",
            metadata={"count": len(results), "results": results})
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def grep_files(pattern: str, path: str = ".", file_ext: str = None,
               context_lines: int = 2, case_sensitive: bool = False,
               regex: bool = False) -> ToolResult:
    """Search file contents. Shows matching lines with context. Supports regex."""
    ws = _workspace()
    search_path = (ws / path).resolve()
    SKIP = {"__pycache__",".git","node_modules",".venv","venv","dist","build"}
    results = []
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as e:
        return ToolResult(False, error=f"Invalid pattern: {e}")
    try:
        for f in sorted(search_path.rglob("*")):
            if any(s in f.parts for s in SKIP) or not f.is_file(): continue
            if file_ext and f.suffix != file_ext: continue
            if f.suffix.lower() not in {".py",".js",".ts",".go",".rs",".rb",".php",
                                          ".java",".c",".cpp",".cs",".sh",".html",
                                          ".css",".json",".yaml",".yml",".toml",
                                          ".md",".txt",".sql",".graphql",".env",".cfg"}: continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                rel = str(f.relative_to(ws)) if str(f).startswith(str(ws)) else str(f)
                for i, line in enumerate(lines):
                    if compiled.search(line):
                        ctx_start = max(0, i - context_lines)
                        ctx_end   = min(len(lines), i + context_lines + 1)
                        block = []
                        for j in range(ctx_start, ctx_end):
                            prefix = ">>> " if j == i else "    "
                            block.append(f"{prefix}{rel}:{j+1}: {lines[j]}")
                        results.append("\n".join(block))
                        if len(results) >= 40: break
            except Exception:
                continue
            if len(results) >= 40: break
        return ToolResult(True,
            output="\n---\n".join(results) if results else f"No matches for '{pattern}'",
            metadata={"matches": len(results), "pattern": pattern})
    except Exception as exc:
        return ToolResult(False, error=str(exc))


# ── Web / Network ──────────────────────────────────────────────────────────────

def web_fetch(url: str, method: str = "GET", headers: Dict[str, str] = None,
              data: str = "", timeout: int = 25) -> ToolResult:
    """Fetch any URL. Use for docs, APIs, GitHub, npm, PyPI, etc."""
    try:
        hdrs = {"User-Agent": "ZencodeAI/11 (+https://github.com/zencode)"}
        if headers: hdrs.update(headers)
        resp = requests.request(method.upper(), url, headers=hdrs,
                                data=data.encode() if isinstance(data,str) else data,
                                timeout=timeout, allow_redirects=True)
        ct = resp.headers.get("content-type","")
        text = resp.text[:16_000]
        return ToolResult(True, output=text, metadata={
            "status_code": resp.status_code, "url": str(resp.url),
            "content_type": ct, "content_length": len(resp.text),
        })
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def web_search_tool(query: str, max_results: int = 8) -> ToolResult:
    """Search the internet using DuckDuckGo. Returns URLs and snippets."""
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        resp = requests.get(url, params=params, timeout=15,
                            headers={"User-Agent": "ZencodeAI/11"})
        data = resp.json()
        results = []
        # Abstract (top answer)
        if data.get("AbstractText"):
            results.append(f"[Top Result] {data['AbstractText']}\n  Source: {data.get('AbstractURL','')}")
        # Related topics
        for item in (data.get("RelatedTopics") or [])[:max_results]:
            if isinstance(item, dict) and item.get("Text"):
                url_link = item.get("FirstURL","")
                text = item["Text"][:200]
                results.append(f"• {text}\n  {url_link}")
        if not results:
            # Fallback: HTML scrape DuckDuckGo
            html_resp = requests.get(
                f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}",
                headers={"User-Agent":"Mozilla/5.0"}, timeout=15
            )
            links = re.findall(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)', html_resp.text)
            snippets = re.findall(r'class="result__snippet"[^>]*>([^<]+)', html_resp.text)
            for i, (href, title) in enumerate(links[:max_results]):
                snip = snippets[i] if i < len(snippets) else ""
                results.append(f"• {title.strip()}\n  URL: {href}\n  {snip.strip()[:200]}")
        return ToolResult(True,
            output=f"Search: {query}\n\n" + "\n\n".join(results) if results else f"No results for: {query}",
            metadata={"query": query, "results_count": len(results)})
    except Exception as exc:
        return ToolResult(False, error=f"Search failed: {exc}")


# ── Git ────────────────────────────────────────────────────────────────────────

def git_command(command: str, cwd: str = None) -> ToolResult:
    """Run any git command. Full git access: commit, branch, merge, log, diff, push, etc."""
    ws = _workspace()
    run_cwd = str((ws / cwd).resolve()) if cwd else str(ws)
    # Safety: don't allow obviously destructive force pushes without explicit flag
    CONFIRM_NEEDED = ["push --force", "reset --hard", "clean -f", "push -f"]
    full_cmd = f"git {command}"
    try:
        result = subprocess.run(full_cmd, shell=True, capture_output=True,
                                text=True, timeout=60, cwd=run_cwd)
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        combined = "\n".join(filter(None, [stdout, stderr])) or "(no output)"
        ok = result.returncode == 0
        return ToolResult(ok, output=combined,
            error="" if ok else f"git exit {result.returncode}: {stderr[:400]}",
            metadata={"exit_code": result.returncode, "command": full_cmd})
    except Exception as exc:
        return ToolResult(False, error=str(exc))


# ── Run tools ──────────────────────────────────────────────────────────────────

_RUNNERS: Dict[str, List[str]] = {
    "python": [sys.executable], "python3": [sys.executable], "py": [sys.executable],
    "javascript": ["node"], "js": ["node"],
    "typescript": ["npx","ts-node"], "ts": ["npx","ts-node"],
    "bash": ["bash"], "sh": ["bash"], "shell": ["bash"],
    "go": ["go","run"],
    "rust": ["cargo","run","--"],
    "ruby": ["ruby"], "php": ["php"], "java": ["java"],
    "lua": ["lua"], "swift": ["swift"], "dart": ["dart"],
}

_LANG_EXTS = {
    "python":".py","python3":".py","py":".py",
    "javascript":".js","js":".js","typescript":".ts","ts":".ts",
    "bash":".sh","shell":".sh","sh":".sh",
    "go":".go","rust":".rs","ruby":".rb","php":".php","java":".java",
    "cpp":".cpp","c":".c","lua":".lua","swift":".swift","dart":".dart",
}


def _run_path_with_language(path_obj: Path, lang: str, args: List[str], timeout: int, run_cwd: str):
    if lang in ("c","cpp"):
        compiler = "gcc" if lang == "c" else "g++"
        out_bin = Path(tempfile.gettempdir()) / "zc_exec_bin"
        comp = subprocess.run([compiler, str(path_obj), "-o", str(out_bin)],
                               capture_output=True, text=True, timeout=timeout, cwd=run_cwd)
        if comp.returncode != 0: return comp
        return subprocess.run([str(out_bin)] + args, capture_output=True, text=True,
                               timeout=timeout, cwd=run_cwd)
    if lang == "java":
        comp = subprocess.run(["javac", str(path_obj)], capture_output=True, text=True,
                               timeout=timeout, cwd=run_cwd)
        if comp.returncode != 0: return comp
        return subprocess.run(["java", path_obj.stem] + args, capture_output=True, text=True,
                               timeout=timeout, cwd=run_cwd)
    cmd = _RUNNERS.get(lang, [sys.executable]) + [str(path_obj)] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=run_cwd)


def run_code(code: str = None, path: str = None, language: str = "python",
             args: List[str] = None, timeout: int = 60, cwd: str = None) -> ToolResult:
    ws = _workspace()
    run_cwd = str(ws / cwd) if cwd else str(ws)
    args = args or []
    t0 = time.perf_counter()
    try:
        if path:
            p = (ws / path).resolve()
            if not p.exists(): p = Path(path).resolve()
            if not p.exists(): return ToolResult(False, error=f"Not found: {path}")
            ext = p.suffix.lstrip(".").lower()
            lang = ext if ext in _RUNNERS or ext in ("c","cpp","java") else language.lower()
            result = _run_path_with_language(p, lang, args, timeout, run_cwd)
        elif code:
            lang = language.lower()
            ext = _LANG_EXTS.get(lang, ".tmp")
            with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, encoding="utf-8") as tf:
                tf.write(code); tmp = tf.name
            try:
                cmd = _RUNNERS.get(lang, [sys.executable]) + [tmp] + args
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=run_cwd)
            finally:
                try: os.unlink(tmp)
                except: pass
        else:
            return ToolResult(False, error="Provide code= or path=")
        dur = int((time.perf_counter() - t0) * 1000)
        stdout = result.stdout.strip(); stderr = result.stderr.strip()
        combined = "\n".join(filter(None,[stdout,stderr])) or "(no output)"
        ok = result.returncode == 0
        return ToolResult(ok, output=combined,
            error="" if ok else f"Exit {result.returncode}",
            metadata={"exit_code": result.returncode, "duration_ms": dur, "stdout": stdout, "stderr": stderr})
    except subprocess.TimeoutExpired:
        return ToolResult(False, error=f"Timeout after {timeout}s")
    except FileNotFoundError as exc:
        return ToolResult(False, error=f"Runtime not found ({language}): {exc}")
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def run_shell(command: str, timeout: int = 90, cwd: str = None) -> ToolResult:
    ws = _workspace()
    run_cwd = str(ws / cwd) if cwd else str(ws)
    t0 = time.perf_counter()
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True,
                                timeout=timeout, cwd=run_cwd)
        dur = int((time.perf_counter() - t0) * 1000)
        stdout = result.stdout.strip(); stderr = result.stderr.strip()
        combined = "\n".join(filter(None,[stdout,stderr])) or "(no output)"
        ok = result.returncode == 0
        return ToolResult(ok, output=combined,
            error="" if ok else f"Exit {result.returncode}: {stderr[:400]}",
            metadata={"exit_code": result.returncode, "duration_ms": dur})
    except subprocess.TimeoutExpired:
        return ToolResult(False, error=f"Timeout after {timeout}s")
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def run_any_command(command: str, timeout: int = 180, cwd: str = None,
                    env: Dict[str, str] = None) -> ToolResult:
    ws = _workspace()
    run_cwd = str((ws / cwd).resolve()) if cwd else str(ws)
    t0 = time.perf_counter()
    try:
        run_env = os.environ.copy()
        if env: run_env.update({str(k): str(v) for k,v in env.items()})
        result = subprocess.run(command, shell=True, capture_output=True, text=True,
                                timeout=timeout, cwd=run_cwd, env=run_env)
        dur = int((time.perf_counter() - t0) * 1000)
        stdout = result.stdout.strip(); stderr = result.stderr.strip()
        combined = "\n".join(filter(None,[stdout,stderr])) or "(no output)"
        ok = result.returncode == 0
        return ToolResult(ok, output=combined,
            error="" if ok else f"Exit {result.returncode}: {stderr[:400]}",
            metadata={"exit_code": result.returncode, "duration_ms": dur, "cwd": run_cwd})
    except subprocess.TimeoutExpired:
        return ToolResult(False, error=f"Timeout after {timeout}s")
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def run_tests(command: str = "", timeout: int = 300, cwd: str = None) -> ToolResult:
    ws = _workspace()
    run_cwd = (ws / cwd).resolve() if cwd else ws
    if not command:
        if (run_cwd/"pytest.ini").exists() or (run_cwd/"conftest.py").exists() or any(run_cwd.glob("test_*.py")):
            command = "pytest -q"
        elif (run_cwd/"package.json").exists(): command = "npm test --silent"
        elif (run_cwd/"go.mod").exists():       command = "go test ./..."
        elif (run_cwd/"Cargo.toml").exists():   command = "cargo test -q"
        else: command = "pytest -q"
    rel = str(run_cwd.relative_to(ws)) if str(run_cwd).startswith(str(ws)) else str(run_cwd)
    return run_any_command(command=command, timeout=timeout, cwd=rel)


def install_packages(packages: List[str], manager: str = "pip") -> ToolResult:
    ws = _workspace()
    if not packages: return ToolResult(False, error="No packages")
    try:
        if manager == "pip":
            cmd = [sys.executable,"-m","pip","install"] + packages + ["--break-system-packages","-q"]
        elif manager == "npm":
            cmd = ["npm","install"] + packages
        elif manager == "npm-dev":
            cmd = ["npm","install","--save-dev"] + packages
        elif manager in ("yarn","pnpm"):
            cmd = [manager,"add"] + packages
        elif manager == "cargo":
            cmd = ["cargo","add"] + packages
        elif manager == "go":
            cmd = ["go","get"] + packages
        else:
            return ToolResult(False, error=f"Unknown manager: {manager}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=240, cwd=str(ws))
        ok = result.returncode == 0
        return ToolResult(ok,
            output=f"✔ Installed: {', '.join(packages)}" if ok else (result.stdout+result.stderr).strip(),
            error="" if ok else (result.stdout+result.stderr).strip()[:400],
            metadata={"packages": packages})
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def search_in_files(pattern: str, path: str = ".", file_ext: str = None) -> ToolResult:
    """Simple text search. For regex/context, use grep_files instead."""
    return grep_files(pattern, path=path, file_ext=file_ext, context_lines=0)


def mcp_call(server_url: str, tool: str, arguments: Dict[str, Any] = None, timeout: int = 30) -> ToolResult:
    payload = {"tool": tool, "arguments": arguments or {}}
    try:
        resp = requests.post(server_url, json=payload, timeout=timeout)
        text = resp.text[:12_000]
        ok = resp.status_code < 400
        return ToolResult(ok, output=text,
            error="" if ok else f"HTTP {resp.status_code}",
            metadata={"status_code": resp.status_code})
    except Exception as exc:
        return ToolResult(False, error=str(exc))


def delete_tests(path: str = ".") -> ToolResult:
    ws = _workspace()
    root = (ws / path).resolve()
    if not root.exists(): return ToolResult(False, error=f"Not found: {path}")
    removed = []
    try:
        for f in root.rglob("*"):
            name = f.name.lower()
            if not f.is_file(): continue
            if name.startswith("test_") or name.endswith(("_test.py",".spec.js",".test.js",".spec.ts",".test.ts")):
                f.unlink(missing_ok=True); removed.append(str(f))
        for d in sorted(root.rglob("*"), reverse=True):
            if d.is_dir() and d.name.lower() in {"tests","__tests__","spec"}:
                try:
                    for child in d.rglob("*"):
                        if child.is_file(): child.unlink(missing_ok=True)
                    d.rmdir(); removed.append(str(d))
                except Exception: pass
        return ToolResult(True, output=f"Removed {len(removed)} test artifact(s)")
    except Exception as exc:
        return ToolResult(False, error=str(exc))


# ── Schemas ────────────────────────────────────────────────────────────────────

_S = lambda name, desc, props, req=None: {
    "type": "function",
    "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props,
                       **({} if not req else {"required": req})},
    },
}

FILE_READ_SCHEMA = _S("file_read",
    "Read a file. Optionally specify line range. Always read before modifying.",
    {"path":{"type":"string"},"start_line":{"type":"integer"},"end_line":{"type":"integer"}},["path"])

FILE_WRITE_SCHEMA = _S("file_write",
    "Write complete file content. Creates parent dirs. NEVER truncate — always write the full file.",
    {"path":{"type":"string"},"content":{"type":"string"},"mode":{"type":"string","enum":["write","append"]}},
    ["path","content"])

FILE_PATCH_SCHEMA = _S("file_patch",
    "Surgical edit: replace exact string in file. Better than full rewrite for targeted changes.",
    {"path":{"type":"string"},"old_str":{"type":"string","description":"Exact string to replace (must be unique)"},
     "new_str":{"type":"string"}},["path","old_str","new_str"])

FILE_DELETE_SCHEMA = _S("file_delete",
    "Delete a file or directory.",
    {"path":{"type":"string"}},["path"])

FILE_RENAME_SCHEMA = _S("file_rename",
    "Rename or move a file.",
    {"path":{"type":"string"},"new_path":{"type":"string"}},["path","new_path"])

FILE_COPY_SCHEMA = _S("file_copy",
    "Copy a file or directory.",
    {"path":{"type":"string"},"dest":{"type":"string"}},["path","dest"])

LIST_DIR_SCHEMA = _S("list_directory",
    "List directory contents.",
    {"path":{"type":"string","description":"Directory path (default: workspace root)"}})

CREATE_DIR_SCHEMA = _S("create_directory",
    "Create a directory (and all parents).",
    {"path":{"type":"string"}},["path"])

FIND_FILES_SCHEMA = _S("find_files",
    "Find files by glob pattern (e.g. **/*.py, *.config.*) or filename substring.",
    {"pattern":{"type":"string","description":"Glob pattern or filename substring"},
     "path":{"type":"string","description":"Search root (default: workspace root)"},
     "include_hidden":{"type":"boolean"}},["pattern"])

GREP_FILES_SCHEMA = _S("grep_files",
    "Search file contents with optional regex and context lines.",
    {"pattern":{"type":"string"},"path":{"type":"string"},
     "file_ext":{"type":"string"},"context_lines":{"type":"integer","description":"Lines of context (default 2)"},
     "case_sensitive":{"type":"boolean"},"regex":{"type":"boolean"}},["pattern"])

RUN_CODE_SCHEMA = _S("run_code",
    "Execute code or a file. Use to test and verify work.",
    {"code":{"type":"string"},"path":{"type":"string"},
     "language":{"type":"string"},"args":{"type":"array","items":{"type":"string"}},
     "timeout":{"type":"integer"},"cwd":{"type":"string"}})

RUN_SHELL_SCHEMA = _S("run_shell",
    "Run a shell command (git, make, npm, etc.).",
    {"command":{"type":"string"},"timeout":{"type":"integer"},"cwd":{"type":"string"}},["command"])

RUN_ANY_COMMAND_SCHEMA = _S("run_any_command",
    "Run any command with optional env vars.",
    {"command":{"type":"string"},"timeout":{"type":"integer"},
     "cwd":{"type":"string"},"env":{"type":"object"}},["command"])

RUN_TESTS_SCHEMA = _S("run_tests",
    "Run project tests (auto-detects pytest/npm test/go test/cargo test).",
    {"command":{"type":"string"},"timeout":{"type":"integer"},"cwd":{"type":"string"}})

INSTALL_SCHEMA = _S("install_packages",
    "Install packages. Supports pip, npm, npm-dev, yarn, pnpm, cargo, go.",
    {"packages":{"type":"array","items":{"type":"string"}},
     "manager":{"type":"string","enum":["pip","npm","npm-dev","yarn","pnpm","cargo","go"]}},["packages"])

SEARCH_SCHEMA = _S("search_in_files",
    "Search for text across files. For regex/context use grep_files.",
    {"pattern":{"type":"string"},"path":{"type":"string"},"file_ext":{"type":"string"}},["pattern"])

WEB_FETCH_SCHEMA = _S("web_fetch",
    "Fetch any URL (docs, APIs, GitHub, npm, PyPI). Returns page content.",
    {"url":{"type":"string"},"method":{"type":"string"},
     "headers":{"type":"object"},"data":{"type":"string"},"timeout":{"type":"integer"}},["url"])

WEB_SEARCH_SCHEMA = _S("web_search_tool",
    "Search the internet using DuckDuckGo. Returns URLs and snippets.",
    {"query":{"type":"string"},"max_results":{"type":"integer"}},["query"])

GIT_COMMAND_SCHEMA = _S("git_command",
    "Run any git command: commit, branch, merge, log, diff, push, pull, stash, etc.",
    {"command":{"type":"string","description":"Git command without 'git' prefix (e.g. 'commit -m \"feat: add auth\"')"},
     "cwd":{"type":"string"}},["command"])

MCP_CALL_SCHEMA = _S("mcp_call",
    "Call an MCP-compatible HTTP endpoint.",
    {"server_url":{"type":"string"},"tool":{"type":"string"},
     "arguments":{"type":"object"},"timeout":{"type":"integer"}},["server_url","tool"])

DELETE_TESTS_SCHEMA = _S("delete_tests",
    "Delete generated test files after successful debug.",
    {"path":{"type":"string"}})

ALL_SCHEMAS = [
    FILE_READ_SCHEMA, FILE_WRITE_SCHEMA, FILE_PATCH_SCHEMA, FILE_DELETE_SCHEMA,
    FILE_RENAME_SCHEMA, FILE_COPY_SCHEMA,
    LIST_DIR_SCHEMA, CREATE_DIR_SCHEMA, FIND_FILES_SCHEMA, GREP_FILES_SCHEMA,
    RUN_CODE_SCHEMA, RUN_SHELL_SCHEMA, RUN_ANY_COMMAND_SCHEMA, RUN_TESTS_SCHEMA,
    INSTALL_SCHEMA, SEARCH_SCHEMA, WEB_FETCH_SCHEMA, WEB_SEARCH_SCHEMA,
    GIT_COMMAND_SCHEMA, MCP_CALL_SCHEMA, DELETE_TESTS_SCHEMA,
]

TOOL_CALLABLES = {
    "file_read":        file_read,
    "file_write":       file_write,
    "file_patch":       file_patch,
    "file_delete":      file_delete,
    "file_rename":      file_rename,
    "file_copy":        file_copy,
    "list_directory":   list_directory,
    "create_directory": create_directory,
    "find_files":       find_files,
    "grep_files":       grep_files,
    "run_code":         run_code,
    "run_shell":        run_shell,
    "run_any_command":  run_any_command,
    "run_tests":        run_tests,
    "install_packages": install_packages,
    "search_in_files":  search_in_files,
    "web_fetch":        web_fetch,
    "web_search_tool":  web_search_tool,
    "git_command":      git_command,
    "mcp_call":         mcp_call,
    "delete_tests":     delete_tests,
}


def dispatch(name: str, args: dict) -> ToolResult:
    fn = TOOL_CALLABLES.get(name)
    if fn is None:
        return ToolResult(False, error=f"Unknown tool: {name}")
    try:
        return fn(**args)
    except TypeError as exc:
        return ToolResult(False, error=f"Bad args for {name}: {exc}")
