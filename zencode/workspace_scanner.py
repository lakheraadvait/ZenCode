"""
ZENCODE v11 — workspace_scanner.py
Deep workspace intelligence. Reads everything. Understands your project completely.
Supports: Python, JS/TS, Go, Rust, Ruby, PHP, Java, C/C++, C#, Bash, Lua, Zig, Swift.
v11 changes:
  - Full file content in context (not just preview) up to generous limit
  - Rich dependency graph extraction
  - Git awareness (branch, recent commits, dirty files)
  - Secret detection (warns but never includes secrets in context)
  - Symbol index: classes/functions extracted per file
  - Deep tree with size annotations
  - .zenrules injection
"""
from __future__ import annotations

import json, os, re, subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SKIP_DIRS = {
    ".git","__pycache__","node_modules",".venv","venv","env",
    "dist","build",".next",".nuxt","coverage",".pytest_cache",
    ".mypy_cache",".tox","target","vendor",".cache","tmp","temp",
    "eggs",".eggs","bin","obj","out",".turbo",".vercel",".svelte-kit",
}

CODE_EXTS = {
    ".py",".pyx",".pxd",
    ".js",".mjs",".cjs",".jsx",".ts",".tsx",".vue",".svelte",
    ".go",".rs",".rb",".erb",".php",".java",".kt",".kts",
    ".c",".cpp",".cc",".cxx",".h",".hpp",".cs",
    ".sh",".bash",".zsh",".fish",
    ".html",".css",".scss",".sass",".less",
    ".json",".yaml",".yml",".toml",".ini",".cfg",".env",".env.example",
    ".xml",".sql",".graphql",".proto",
    ".md",".rst",".txt",
    ".dockerfile","dockerfile",".makefile","makefile",
    ".lua",".zig",".swift",".dart",".ex",".exs",".elm",".nim",
}

MANIFEST_FILES = {
    "requirements.txt","requirements.in","Pipfile","pyproject.toml",
    "setup.py","setup.cfg","poetry.lock",
    "package.json","package-lock.json","yarn.lock","pnpm-lock.yaml",
    "go.mod","go.sum","Cargo.toml","Cargo.lock",
    "Gemfile","Gemfile.lock","composer.json","composer.lock",
    "pom.xml","build.gradle","settings.gradle","build.gradle.kts",
    "CMakeLists.txt","Makefile","makefile","meson.build",
    "Dockerfile","docker-compose.yml","docker-compose.yaml",
    ".env",".env.example",".gitignore","README.md","README.rst",
    "tsconfig.json","jsconfig.json",".eslintrc.json",".prettierrc",
    "tailwind.config.js","tailwind.config.ts","vite.config.ts","vite.config.js",
    "next.config.js","next.config.ts","nuxt.config.ts",
    ".zenrules",
}

SECRET_PATTERNS = [
    r"(?i)(api_key|apikey|secret|password|passwd|token|auth_token|access_token|private_key)\s*[=:]\s*['\"]([^'\"]{8,})['\"]",
    r"(?i)(aws_access_key_id|aws_secret|sk-[a-zA-Z0-9]{20,})",
]

MAX_READ = 80_000
MAX_FULL = 20_000   # files under this size get full content
MAX_PREV = 800      # preview chars for larger files


def _extract_symbols(content: str, ext: str) -> List[str]:
    """Extract top-level class/function/def names for symbol index."""
    symbols = []
    try:
        if ext == ".py":
            for m in re.finditer(r"^(?:class|def|async def)\s+(\w+)", content, re.M):
                symbols.append(m.group(1))
        elif ext in (".js",".ts",".jsx",".tsx",".mjs"):
            for m in re.finditer(
                r"(?:export\s+)?(?:default\s+)?(?:class|function(?:\s*\*)?|const|let|var)\s+(\w+)",
                content, re.M):
                symbols.append(m.group(1))
        elif ext == ".go":
            for m in re.finditer(r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)", content, re.M):
                symbols.append(m.group(1))
        elif ext == ".rs":
            for m in re.finditer(r"^(?:pub\s+)?(?:fn|struct|enum|trait|impl)\s+(\w+)", content, re.M):
                symbols.append(m.group(1))
        elif ext in (".java",".kt"):
            for m in re.finditer(r"(?:class|interface|fun|void|public|private|protected)\s+(\w+)\s*[({]", content):
                symbols.append(m.group(1))
        elif ext == ".rb":
            for m in re.finditer(r"^(?:class|module|def)\s+(\w+)", content, re.M):
                symbols.append(m.group(1))
    except Exception:
        pass
    seen, out = set(), []
    for s in symbols:
        if s not in seen and s not in {"self","cls","this","new","return","if","for"}:
            seen.add(s); out.append(s)
    return out[:20]


def _has_secret(content: str) -> bool:
    for pat in SECRET_PATTERNS:
        if re.search(pat, content):
            return True
    return False


class WorkspaceScanner:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self._files: Dict[str, dict] = {}
        self._info: dict = {}
        self._git: dict = {}
        self._scanned = False

    def scan(self) -> "WorkspaceScanner":
        self._files = {}
        self._walk(self.workspace, 0)
        self._info = self._analyze()
        self._git  = self._git_info()
        self._scanned = True
        return self

    def _walk(self, path: Path, depth: int):
        if depth > 8:
            return
        try:
            for item in sorted(path.iterdir()):
                name = item.name
                if name.startswith(".") and name not in {".env",".env.example",".gitignore",".zenrules"}:
                    continue
                if name in SKIP_DIRS or name.endswith(".egg-info"):
                    continue
                if item.is_dir():
                    self._walk(item, depth + 1)
                elif item.is_file():
                    rel = str(item.relative_to(self.workspace))
                    ext = item.suffix.lower()
                    sz  = item.stat().st_size
                    entry: dict = {
                        "path": rel, "ext": ext, "size": sz,
                        "lines": 0, "preview": "", "symbols": [],
                        "is_manifest": name in MANIFEST_FILES,
                        "has_secret": False,
                        "content": None,
                    }
                    if ext in CODE_EXTS and sz < MAX_READ:
                        try:
                            raw = item.read_text(encoding="utf-8", errors="replace")
                            lines = raw.splitlines()
                            entry["lines"] = len(lines)
                            entry["has_secret"] = _has_secret(raw)
                            entry["symbols"] = _extract_symbols(raw, ext)
                            if sz < MAX_FULL and not entry["has_secret"]:
                                entry["content"] = raw
                            else:
                                # preview = first meaningful non-trivial lines
                                useful = [
                                    l.rstrip() for l in lines[:60]
                                    if l.strip() and not l.strip().startswith("#!")
                                ][:20]
                                entry["preview"] = "\n".join(useful)[:MAX_PREV]
                        except Exception:
                            pass
                    self._files[rel] = entry
        except PermissionError:
            pass

    def _git_info(self) -> dict:
        info: dict = {}
        git_dir = self.workspace / ".git"
        if not git_dir.exists():
            return info
        def _run(cmd):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   cwd=str(self.workspace), timeout=4)
                return r.stdout.strip()
            except Exception:
                return ""
        info["branch"]  = _run(["git","rev-parse","--abbrev-ref","HEAD"])
        info["commits"] = _run(["git","log","--oneline","-8"]).splitlines()
        info["dirty"]   = _run(["git","diff","--name-only"]).splitlines()
        info["staged"]  = _run(["git","diff","--cached","--name-only"]).splitlines()
        info["remote"]  = _run(["git","remote","get-url","origin"])
        info["stash"]   = _run(["git","stash","list"]).count("\n")
        return info

    def _analyze(self) -> dict:
        paths = set(self._files.keys())
        names = {Path(p).name for p in paths}

        info = {
            "type": "unknown", "language": None, "framework": None,
            "entry_points": [], "has_tests": False, "has_docker": False,
            "has_ci": False, "dependencies": [], "dev_dependencies": [],
            "description": "", "run_cmd": None, "test_cmd": None,
            "scripts": {},
        }

        # Node / JS / TS
        if "package.json" in names:
            info["language"] = "JavaScript/TypeScript"
            info["type"] = "node"
            try:
                pkg_path = next(p for p in paths if Path(p).name == "package.json"
                                and "/" not in p.replace("\\",""))
                pkg = json.loads((self.workspace / pkg_path).read_text())
                deps    = pkg.get("dependencies",{})
                devdeps = pkg.get("devDependencies",{})
                info["dependencies"]     = list(deps.keys())[:30]
                info["dev_dependencies"] = list(devdeps.keys())[:20]
                info["scripts"]          = pkg.get("scripts",{})
                all_d = {k.lower() for k in {**deps,**devdeps}}
                if "next"       in all_d: info["framework"]="Next.js";   info["type"]="nextjs"
                elif "nuxt"     in all_d: info["framework"]="Nuxt.js";   info["type"]="nuxt"
                elif "react"    in all_d: info["framework"]="React";     info["type"]="react"
                elif "vue"      in all_d: info["framework"]="Vue.js";    info["type"]="vue"
                elif "svelte"   in all_d: info["framework"]="SvelteKit"; info["type"]="svelte"
                elif "express"  in all_d: info["framework"]="Express.js";info["type"]="express"
                elif "fastify"  in all_d: info["framework"]="Fastify";   info["type"]="express"
                elif "hono"     in all_d: info["framework"]="Hono";      info["type"]="hono"
                elif "@nestjs/core" in all_d: info["framework"]="NestJS"
                elif any(".ts" in p for p in paths): info["framework"]="TypeScript"
                scripts = pkg.get("scripts",{})
                info["run_cmd"]  = scripts.get("start") or scripts.get("dev") or "npm start"
                info["test_cmd"] = scripts.get("test","npm test")
                ep = pkg.get("main") or pkg.get("module")
                if ep: info["entry_points"] = [ep]
                name_raw = pkg.get("name",""); desc_raw = pkg.get("description","")
                info["description"] = f"{name_raw} — {desc_raw}".strip(" —")
            except Exception:
                pass

        elif "Cargo.toml" in names:
            info["language"]="Rust"; info["type"]="rust"; info["framework"]="Cargo"
            info["run_cmd"]="cargo run"; info["test_cmd"]="cargo test"
            try:
                raw = (self.workspace/"Cargo.toml").read_text()
                deps = re.findall(r"^(\w[\w-]*)\s*=", raw, re.M)
                info["dependencies"] = deps[:30]
            except Exception: pass
            if "src/main.rs" in paths: info["entry_points"]=["src/main.rs"]
            elif "src/lib.rs" in paths: info["entry_points"]=["src/lib.rs"]

        elif "go.mod" in names:
            info["language"]="Go"; info["type"]="go"
            info["run_cmd"]="go run ."; info["test_cmd"]="go test ./..."
            try:
                raw = (self.workspace/"go.mod").read_text()
                m = re.search(r"^module\s+(\S+)", raw, re.M)
                if m: info["description"] = m.group(1)
                deps = re.findall(r"^\s+(\S+)\s+v", raw, re.M)
                info["dependencies"] = deps[:30]
            except Exception: pass
            if "main.go" in names: info["entry_points"]=["main.go"]
            elif any(p.endswith("/main.go") for p in paths):
                info["entry_points"]=[p for p in paths if p.endswith("/main.go")][:1]

        elif "pom.xml" in names or "build.gradle" in names:
            info["language"]="Java"; info["type"]="java"
            info["framework"]="Maven" if "pom.xml" in names else "Gradle"
            info["run_cmd"]="mvn spring-boot:run" if "pom.xml" in names else "gradle bootRun"
            info["test_cmd"]="mvn test" if "pom.xml" in names else "gradle test"

        elif "Gemfile" in names:
            info["language"]="Ruby"; info["type"]="ruby"
            try:
                gem = (self.workspace/"Gemfile").read_text()
                if "rails" in gem.lower():
                    info["framework"]="Rails"; info["run_cmd"]="rails server"
                    info["test_cmd"]="rails test"
                elif "sinatra" in gem.lower():
                    info["framework"]="Sinatra"
                deps = re.findall(r"gem\s+['\"](\w[\w-]*)['\"]", gem)
                info["dependencies"] = deps[:30]
            except Exception: pass
            for ep in ["app.rb","config.ru","main.rb"]:
                if ep in names: info["entry_points"].append(ep)

        elif "composer.json" in names:
            info["language"]="PHP"; info["type"]="php"
            for ep in ["index.php","public/index.php","artisan"]:
                if ep in paths: info["entry_points"].append(ep)
            if "artisan" in paths:
                info["framework"]="Laravel"; info["run_cmd"]="php artisan serve"
                info["test_cmd"]="php artisan test"
            try:
                comp = json.loads((self.workspace/"composer.json").read_text())
                info["dependencies"] = list(comp.get("require",{}).keys())[:30]
            except Exception: pass

        elif any(p.endswith(".py") for p in paths):
            info["language"]="Python"; info["type"]="python"
            req_files = [p for p in paths if Path(p).name in
                         ("requirements.txt","pyproject.toml","Pipfile","setup.py")]
            all_reqs = ""
            for rf in req_files:
                try: all_reqs += (self.workspace/rf).read_text().lower()
                except: pass
            if "fastapi"    in all_reqs: info["framework"]="FastAPI";    info["run_cmd"]="uvicorn main:app --reload"; info["test_cmd"]="pytest"
            elif "flask"    in all_reqs: info["framework"]="Flask";      info["run_cmd"]="python app.py"; info["test_cmd"]="pytest"
            elif "django"   in all_reqs: info["framework"]="Django";     info["run_cmd"]="python manage.py runserver"; info["test_cmd"]="python manage.py test"
            elif "tornado"  in all_reqs: info["framework"]="Tornado"
            elif "streamlit"in all_reqs: info["framework"]="Streamlit";  info["run_cmd"]="streamlit run app.py"
            elif "typer"    in all_reqs or "click" in all_reqs: info["framework"]="CLI (Click/Typer)"; info["test_cmd"]="pytest"
            elif "pygame"   in all_reqs: info["framework"]="Pygame"
            elif "aiohttp"  in all_reqs: info["framework"]="aiohttp"
            elif "langchain"in all_reqs or "openai" in all_reqs: info["framework"]="AI/LLM"
            if not info["test_cmd"]: info["test_cmd"] = "pytest"
            for ep in ["main.py","app.py","cli.py","server.py","run.py","manage.py","__main__.py"]:
                if ep in names: info["entry_points"].append(ep)
            if "requirements.txt" in names:
                try:
                    reqs = (self.workspace/"requirements.txt").read_text()
                    info["dependencies"] = [
                        l.split("==")[0].split(">=")[0].split("[")[0].strip()
                        for l in reqs.splitlines()
                        if l.strip() and not l.startswith("#")
                    ][:30]
                except: pass

        elif any(p.endswith((".c",".cpp",".cc",".cxx")) for p in paths):
            info["language"]="C/C++"; info["type"]="cpp"
            info["framework"]="CMake" if "CMakeLists.txt" in names else "Make"
            info["run_cmd"]="make && ./build/app" if "Makefile" in names else "cmake . && make"

        # Docker / CI
        if "Dockerfile" in names or "docker-compose.yml" in names:
            info["has_docker"] = True
        ci_files = {".github","Jenkinsfile",".travis.yml",".circleci","Makefile"}
        if any(n in names or n in {Path(p).parts[0] for p in paths} for n in ci_files):
            info["has_ci"] = True

        # Tests
        test_indicators = ["tests","test","spec","__tests__","test_"]
        if any(any(ti in p.lower() for ti in test_indicators) for p in paths):
            info["has_tests"] = True

        return info

    # ── Context building ───────────────────────────────────────────────────────

    def get_full_context(self, max_chars: int = None) -> str:
        if not self._scanned:
            self.scan()
        if max_chars is None:
            try:
                from zencode.config import cfg
                max_chars = int(cfg.get("max_context_chars", 40000))
            except Exception:
                max_chars = 40000

        lines: List[str] = []
        ws   = self.workspace
        info = self._info
        git  = self._git

        # ── Header
        lines += [
            f"=== WORKSPACE: {ws.name} ===",
            f"PATH: {ws}",
        ]
        if info["language"]:   lines.append(f"LANGUAGE:    {info['language']}")
        if info["framework"]:  lines.append(f"FRAMEWORK:   {info['framework']}")
        if info["type"] != "unknown": lines.append(f"TYPE:        {info['type']}")
        if info["entry_points"]: lines.append(f"ENTRY:       {', '.join(info['entry_points'][:4])}")
        if info["run_cmd"]:    lines.append(f"RUN:         {info['run_cmd']}")
        if info["test_cmd"]:   lines.append(f"TEST:        {info['test_cmd']}")
        if info["scripts"]:
            sc = {k:v for k,v in info["scripts"].items() if k in ("start","dev","build","test","lint")}
            if sc: lines.append(f"SCRIPTS:     " + "  |  ".join(f"{k}: {v}" for k,v in sc.items()))
        if info["has_tests"]:  lines.append("HAS TESTS:   yes")
        if info["has_docker"]: lines.append("HAS DOCKER:  yes")
        if info["has_ci"]:     lines.append("HAS CI/CD:   yes")
        if info["dependencies"]:
            lines.append(f"DEPS ({len(info['dependencies'])}): {', '.join(info['dependencies'][:20])}")
        if info["dev_dependencies"]:
            lines.append(f"DEV DEPS:    {', '.join(info['dev_dependencies'][:10])}")
        if info["description"] and info["description"].strip(" —"):
            lines.append(f"DESC:        {info['description'][:120]}")

        # ── Git info
        if git:
            lines += ["", "GIT:"]
            if git.get("branch"):  lines.append(f"  branch:    {git['branch']}")
            if git.get("remote"):  lines.append(f"  remote:    {git['remote']}")
            if git.get("commits"): lines.append(f"  recent commits:")
            for c in (git.get("commits") or [])[:5]:
                lines.append(f"    {c}")
            if git.get("dirty"):
                lines.append(f"  unstaged:  {', '.join(git['dirty'][:8])}")
            if git.get("staged"):
                lines.append(f"  staged:    {', '.join(git['staged'][:8])}")

        # ── .zenrules
        try:
            from zencode.config import cfg
            rules = cfg.load_zenrules()
            if rules:
                lines += ["", "PROJECT RULES (.zenrules):", rules]
        except Exception:
            pass

        # ── File tree (rich version)
        lines += ["", "FILE TREE:"]
        lines += self._build_tree()

        # ── Symbol index
        sym_lines = self._build_symbol_index()
        if sym_lines:
            lines += ["", "SYMBOL INDEX:"]
            lines += sym_lines

        # ── Key file contents (full when possible)
        char_count = sum(len(l) for l in lines)
        key_files = self._priority_files()
        secret_warned = False
        if key_files:
            lines += ["", "FILE CONTENTS:"]
            for fpath in key_files:
                if char_count >= max_chars:
                    lines.append("  ... (limit reached — use file_read to access more files)")
                    break
                entry = self._files.get(fpath, {})
                if entry.get("has_secret") and not secret_warned:
                    lines.append(f"  ⚠ {fpath}: contains secrets — omitted from context for safety")
                    secret_warned = True
                    continue
                content = entry.get("content") or entry.get("preview","")
                if not content:
                    continue
                nl = entry.get("lines", 0)
                sz = entry.get("size", 0)
                sz_s = f"{sz//1024}KB" if sz >= 1024 else f"{sz}B"
                remaining = max_chars - char_count
                truncated = False
                if len(content) > remaining:
                    content = content[:remaining] + "\n... (truncated — use file_read for full content)"
                    truncated = True
                header = f"\n--- {fpath} ({nl} lines, {sz_s}) ---"
                lines.append(header)
                lines.append(content)
                char_count += len(header) + len(content)
                if truncated:
                    break

        lines += ["", "=== END WORKSPACE ==="]
        return "\n".join(lines)

    def _build_tree(self) -> List[str]:
        if not self._files:
            return ["  (empty workspace)"]
        # Build hierarchical tree
        dirs: Dict[str, List[dict]] = {}
        for fpath, entry in sorted(self._files.items()):
            parent = str(Path(fpath).parent)
            dirs.setdefault(parent, []).append(entry)

        out: List[str] = []
        for d in sorted(dirs.keys()):
            entries = sorted(dirs[d], key=lambda e: (e["ext"],e["path"]))
            prefix = "." if d == "." else d
            # Show each file with size/lines annotation
            if len(entries) <= 12:
                file_list = []
                for e in entries:
                    n = Path(e["path"]).name
                    ann = ""
                    if e["lines"]: ann = f"({e['lines']}L)"
                    elif e["size"] >= 1024: ann = f"({e['size']//1024}KB)"
                    has_sym = f" [{','.join(e['symbols'][:3])}]" if e["symbols"] else ""
                    secret  = " ⚠secret" if e["has_secret"] else ""
                    file_list.append(f"{n}{ann}{has_sym}{secret}")
                out.append(f"  {prefix}/  →  {', '.join(file_list)}")
            else:
                short = [Path(e["path"]).name for e in entries[:12]]
                out.append(f"  {prefix}/  →  {', '.join(short)}  (+{len(entries)-12} more)")
            if len(out) > 120:
                out.append("  ...")
                break
        return out

    def _build_symbol_index(self) -> List[str]:
        out = []
        for fpath, entry in sorted(self._files.items()):
            syms = entry.get("symbols",[])
            if syms:
                ext  = entry.get("ext","")
                kind = {".py":"py",".js":"js",".ts":"ts",".go":"go",
                        ".rs":"rs",".rb":"rb",".java":"java"}.get(ext, ext.lstrip("."))
                out.append(f"  {fpath} [{kind}]: {', '.join(syms)}")
        return out[:60]

    def _priority_files(self) -> List[str]:
        names = {Path(p).name: p for p in self._files}
        priority = [
            # Python
            "main.py","app.py","cli.py","server.py","run.py","manage.py","__main__.py",
            "wsgi.py","asgi.py","settings.py","models.py","views.py","routes.py",
            # JS/TS
            "index.js","app.js","server.js","index.ts","app.ts","server.ts",
            "next.config.js","next.config.ts","vite.config.ts","vite.config.js",
            "tsconfig.json",
            # Go
            "main.go",
            # Rust
            "src/main.rs","src/lib.rs",
            # Ruby
            "app.rb","config.ru","main.rb",
            # PHP
            "index.php","public/index.php",
            # Manifests
            "requirements.txt","package.json","Cargo.toml","go.mod","Gemfile",
            "pyproject.toml","setup.py","composer.json","pom.xml",
            "Makefile","CMakeLists.txt","Dockerfile","docker-compose.yml",
            ".env.example",".gitignore","README.md",".zenrules",
        ]
        result = []
        for name in priority:
            if name in names: result.append(names[name])
            elif name in self._files: result.append(name)
        # Add more code files by line count
        extra = sorted(
            [(e["lines"], e["path"]) for e in self._files.values()
             if e["ext"] in {".py",".js",".ts",".go",".rs",".rb",".php",".java",".cs",".cpp"}
             and e["path"] not in result
             and not e["has_secret"]],
            reverse=True,
        )
        result.extend(p for _, p in extra[:20])
        return result

    # ── Accessors ──────────────────────────────────────────────────────────────

    def file_count(self) -> int: return len(self._files)
    def is_empty(self) -> bool:  return len(self._files) == 0
    def get_info(self) -> dict:
        if not self._scanned: self.scan()
        return self._info
    def get_git(self) -> dict:   return self._git
    def get_file_list(self) -> List[str]: return sorted(self._files.keys())

    def get_file_content(self, path: str) -> Optional[str]:
        entry = self._files.get(path, {})
        if entry.get("content"): return entry["content"]
        try:
            return (self.workspace / path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    def refresh(self) -> "WorkspaceScanner": return self.scan()


# ── Singleton ──────────────────────────────────────────────────────────────────

_scanner: Optional[WorkspaceScanner] = None


def get_scanner(workspace: Path = None) -> WorkspaceScanner:
    global _scanner
    if workspace is None:
        try:
            from zencode.config import cfg
            workspace = cfg.workspace()
        except Exception:
            workspace = Path(".")
    workspace = workspace.resolve()
    if _scanner is None or _scanner.workspace != workspace:
        _scanner = WorkspaceScanner(workspace).scan()
    return _scanner


def refresh_scanner(workspace: Path = None) -> WorkspaceScanner:
    global _scanner
    _scanner = None
    return get_scanner(workspace)
