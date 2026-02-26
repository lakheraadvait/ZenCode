# ZENCODE v10 — Autonomous AI Code Shell

> Works in YOUR directory. Reads YOUR code. Shows diffs. Fixes errors autonomously.

---


## New in 10.0.0

- **GOAT mode**: terminal-first autonomous workflow focused on speed, reliability, and zero-confirmation execution.
- **Run anything / console anything**: new `run_any_command` tool executes arbitrary commands with optional env overrides.
- **Test anything**: new `run_tests` tool auto-detects or accepts explicit test commands across common stacks.
- **Terminal-first, Claude-Code-level workflow**: faster CLI loops, autonomous execution, robust tools, and cleaner command ergonomics.
- **Auto-accept is ON by default** for faster autonomous workflows (no confirmation loops).
- **Automated build mode**: once a build plan is generated, execution starts immediately with no confirmation prompts.
- **Workspace restoration**: build target directories are temporary for that run; workspace resets after build completion.
- **Internet access**: `web_fetch` tool retrieves online content over HTTP(S).
- **MCP support**: `mcp_call` tool invokes MCP-compatible HTTP endpoints.
- **Expanded file management**: agents can read/write/create/delete files as needed, with idempotent directory creation behavior.
- **Test cleanup**: `delete_tests` removes generated test artifacts after successful debug runs.
- **Stronger multi-language execution**: improved path-based execution flow for C/C++/Java alongside existing language support.

---

## Install (one command, system-wide)

**Linux / macOS:**
```bash
bash install.sh
```

**Windows:**
```
install.bat
```

That's it. The installer:
- Checks Python 3.9+
- Installs all Python deps
- Installs `zencode` as a global command
- Adds to PATH automatically
- Prompts for your Mistral API key

---

## Quick Start

```bash
cd ~/myproject   # any directory
zencode          # launches — reads your project instantly
```

Auto-accept everything (like Cursor's apply-all):
```bash
zencode --yes
```

---

## Directory Awareness

ZenCode **uses the directory you run it from** as the workspace:

```
# In an existing Flask project:
cd ~/projects/myflaskapp
zencode
you › add JWT authentication

→ reads all your files, understands your routes/models,
  shows you a diff, you press [a] to accept
```

```
# In a projects folder, naming a new project:
cd ~/projects
zencode
you › make a project called simple-calc in Go

→ creates ~/projects/simple-calc/ with full Go project inside
```

---

## Diff Review (the Cursor feature)

Every file change is shown as a colored diff before being written:

```
  MOD  src/auth.py  +24 -3
─────────────────────────────────
  [a]ccept  [r]eject  [A] accept-all  [d] show-diff  [s]kip
```

```
action [a/r/A/d/s] › a
✔  accepted
```

**Or auto-accept everything:**
```
autoaccept on      # in shell or chat
zencode --yes      # from command line
```

---

## Commands

| Command | What it does |
|---------|-------------|
| `chat` | AI session — full context, diff review |
| `build "prompt"` | Build any project from a description |
| `fix` | Autonomous debug loop — runs, finds error, fixes, repeats |
| `accept` | Apply all staged diffs |
| `reject` | Discard all staged diffs |
| `diff` | View staged diffs in full |
| `autoaccept on/off` | Toggle diff review |
| `scan` | Workspace file tree + stack detection |
| `index` | Full codebase context (what AI sees) |
| `read <file>` | Syntax-highlighted file view |
| `run <file>` | Execute any file |
| `models` | List Mistral models |
| `setconfig k v` | Change any setting |
| `ide` | Launch ZenIDE v7 graphic interface |
| `help` | All commands |
| `exit` | Quit |

**In chat**, extra commands:
- `go` — rerun current pending build plan (build mode usually starts automatically)
- `fix` — run the debug agent
- `accept` / `reject` — review diffs
- `diff` — see staged changes
- `autoaccept on/off` — toggle

---

## Supported Languages

Full detection, scaffolding, and debugging for:
- **Python** (Flask, FastAPI, Django, Streamlit, Click, Pygame)
- **JavaScript / TypeScript** (React, Next.js, Vue, Svelte, Express, NestJS)
- **Go**
- **Rust** (Cargo)
- **Ruby** (Rails, Sinatra)
- **PHP** (Laravel)
- **Java** (Maven, Gradle)
- **C / C++** (CMake, Make)
- **Bash / Shell**

---

## The Autonomous Debug Loop

```
fix
```

Debug agent will:
1. Detect your project's run command
2. Run it
3. Parse the error + traceback — find exact file:line
4. Read the file, apply minimal fix
5. Re-run
6. Repeat until ✅ — up to 6 iterations

Language-aware: knows Python tracebacks, Go compiler errors, Rust borrow checker, npm errors, etc.

---

## Config

```bash
setconfig api_key YOUR_KEY
setconfig model mistral-large-latest   # or codestral-latest (default)
setconfig auto_accept true             # skip diff review
setconfig max_debug_iterations 8
setconfig show_diff false              # hide diffs, just stage them
```

Config stored at `~/.zencode/config.json`.  
Workspace always = CWD at launch (never persisted).
