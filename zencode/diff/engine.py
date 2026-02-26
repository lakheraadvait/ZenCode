"""
ZENCODE v10 — diff/engine.py
Pure Python diff engine. No external deps.
Produces colored unified diffs, accept/reject/edit UI.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class FileDiff:
    """Represents a proposed change to one file."""
    path: str           # relative path
    old_content: str    # original content (empty if new file)
    new_content: str    # proposed content
    is_new: bool = False
    is_delete: bool = False

    @property
    def lines_added(self) -> int:
        old = set(self.old_content.splitlines())
        new = set(self.new_content.splitlines())
        return len(new - old)

    @property
    def lines_removed(self) -> int:
        old = set(self.old_content.splitlines())
        new = set(self.new_content.splitlines())
        return len(old - new)

    def unified_diff(self, context: int = 4) -> List[str]:
        """Generate unified diff lines."""
        old_lines = self.old_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)

        if not old_lines and not new_lines:
            return []

        label_old = f"a/{self.path}" if not self.is_new else "/dev/null"
        label_new = f"b/{self.path}"

        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=label_old,
            tofile=label_new,
            n=context,
        ))
        return diff


@dataclass
class DiffSet:
    """A collection of file diffs from one agent action."""
    diffs: List[FileDiff] = field(default_factory=list)
    agent_name: str = ""
    task_description: str = ""

    def add(self, diff: FileDiff):
        self.diffs.append(diff)

    def total_added(self) -> int:
        return sum(d.lines_added for d in self.diffs)

    def total_removed(self) -> int:
        return sum(d.lines_removed for d in self.diffs)

    def __len__(self):
        return len(self.diffs)


# ── Rich Renderer ──────────────────────────────────────────────────────────────

def render_diff_rich(diff: FileDiff, console, syntax_theme: str = "monokai") -> None:
    """Render a single FileDiff to terminal using Rich."""
    from rich.text import Text
    from rich.panel import Panel
    from rich.rule import Rule
    from rich import box

    CYAN   = "#00f5ff"
    GREEN  = "#00ff9f"
    RED    = "#ff4444"
    YELLOW = "#ffe600"
    DIM    = "#3d4a5c"
    WHITE  = "#e8eaf6"
    VIOLET = "#a855f7"

    # Header
    if diff.is_new:
        label = f"[bold {GREEN}]NEW FILE[/]"
    elif diff.is_delete:
        label = f"[bold {RED}]DELETE[/]"
    else:
        added = diff.lines_added
        removed = diff.lines_removed
        label = (
            f"[bold {GREEN}]+{added}[/]  [bold {RED}]-{removed}[/]"
        )

    console.print(Rule(
        title=f"  [{CYAN}]{diff.path}[/]  {label}  ",
        style=DIM,
    ))

    if diff.is_delete:
        console.print(f"  [{RED}]File will be deleted[/]")
        return

    # Get unified diff
    diff_lines = diff.unified_diff(context=3)
    if not diff_lines:
        console.print(f"  [{DIM}]No changes[/]")
        return

    # Render colored diff lines
    output = Text()
    for line in diff_lines:
        line_stripped = line.rstrip("\n")
        if line_stripped.startswith("+++") or line_stripped.startswith("---"):
            output.append(line_stripped + "\n", style=f"bold {WHITE}")
        elif line_stripped.startswith("@@"):
            output.append(line_stripped + "\n", style=f"bold {CYAN}")
        elif line_stripped.startswith("+"):
            output.append(line_stripped + "\n", style=f"{GREEN}")
        elif line_stripped.startswith("-"):
            output.append(line_stripped + "\n", style=f"{RED}")
        else:
            output.append(line_stripped + "\n", style=f"{DIM}")

    console.print(output)


def render_diffset_summary(diffset: DiffSet, console) -> None:
    """Print a one-line summary of all changes in a DiffSet."""
    from rich.text import Text
    GREEN = "#00ff9f"
    RED   = "#ff4444"
    CYAN  = "#00f5ff"
    DIM   = "#3d4a5c"
    WHITE = "#e8eaf6"

    if not diffset.diffs:
        return

    console.print()
    console.print(Text.from_markup(
        f"  [{CYAN}]◈  {len(diffset.diffs)} file(s) changed[/]"
        f"  [{GREEN}]+{diffset.total_added()}[/]"
        f"  [{RED}]-{diffset.total_removed()}[/]"
    ))
    for d in diffset.diffs:
        status = (
            f"[bold {'#00ff9f' if d.is_new else '#00f5ff'}]{'NEW' if d.is_new else 'MOD'}[/]"
            if not d.is_delete else "[bold #ff4444]DEL[/]"
        )
        console.print(f"    {status}  [{WHITE}]{d.path}[/]")
    console.print()


# ── Accept/Reject UI ───────────────────────────────────────────────────────────

class DiffReviewer:
    """
    Interactive diff review UI.
    Shows each changed file and prompts: [a]ccept [r]eject [A]ll [s]kip [?]help
    """

    def __init__(self, console, auto_accept: bool = False):
        self.console = console
        self.auto_accept = auto_accept

    def review(self, diffset: DiffSet, workspace: Path) -> Tuple[List[FileDiff], List[FileDiff]]:
        """
        Review all diffs in diffset.
        Returns (accepted, rejected).
        If auto_accept=True, accepts everything without prompting.
        """
        if not diffset.diffs:
            return [], []

        if self.auto_accept:
            self._apply_all(diffset.diffs, workspace)
            return list(diffset.diffs), []

        from rich.text import Text
        from rich.panel import Panel
        from rich import box
        from prompt_toolkit import prompt as pt_prompt
        from prompt_toolkit.styles import Style as PTStyle
        from prompt_toolkit.formatted_text import HTML

        GREEN  = "#00ff9f"
        CYAN   = "#00f5ff"
        RED    = "#ff4444"
        YELLOW = "#ffe600"
        WHITE  = "#e8eaf6"
        DIM    = "#3d4a5c"

        accepted: List[FileDiff] = []
        rejected: List[FileDiff] = []

        # Show summary first
        render_diffset_summary(diffset, self.console)

        self.console.print(Text.from_markup(
            f"  [{CYAN}]Review changes:[/]  "
            f"[bold {GREEN}][a][/] accept  "
            f"[bold {RED}][r][/] reject  "
            f"[bold {CYAN}][A][/] accept all  "
            f"[bold {YELLOW}][s][/] skip  "
            f"[bold {WHITE}][d][/] show diff  "
            f"[bold {WHITE}][?][/] help"
        ))
        self.console.print()

        pt_style = PTStyle.from_dict({"": "#e8eaf6"})
        accept_all = False

        for i, diff in enumerate(diffset.diffs):
            if accept_all:
                self._apply_diff(diff, workspace)
                accepted.append(diff)
                self.console.print(
                    f"  [{'#00ff9f'}]✔[/]  [{WHITE}]{diff.path}[/]  [{DIM}](auto-accepted)[/]"
                )
                continue

            # Show compact preview first
            status = "NEW" if diff.is_new else ("DEL" if diff.is_delete else "MOD")
            color = "#00ff9f" if diff.is_new else ("#ff4444" if diff.is_delete else "#00f5ff")
            self.console.print(
                f"  [{color}][{status}][/]  [{WHITE}]{diff.path}[/]  "
                f"[{DIM}]({i+1}/{len(diffset.diffs)})[/]"
            )

            while True:
                try:
                    resp = pt_prompt(
                        HTML('<ansigray>  action [a/r/A/d/s/?] › </ansigray>'),
                        style=pt_style,
                    ).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    resp = "s"

                if resp == "?" or resp == "help":
                    self.console.print(
                        f"  [{DIM}]a=accept this file  r=reject  A=accept all remaining  "
                        f"d=show full diff  s=skip (reject)[/]"
                    )
                    continue

                if resp == "d":
                    render_diff_rich(diff, self.console)
                    continue

                if resp in ("a", "y", "yes", ""):
                    self._apply_diff(diff, workspace)
                    accepted.append(diff)
                    self.console.print(f"  [{'#00ff9f'}]✔  accepted[/]")
                    break

                if resp in ("r", "n", "no"):
                    rejected.append(diff)
                    self.console.print(f"  [{'#ff4444'}]✖  rejected[/]")
                    break

                if resp == "a":  # accept all
                    self._apply_diff(diff, workspace)
                    accepted.append(diff)
                    accept_all = True
                    self.console.print(f"  [{'#00ff9f'}]✔  accepted (all remaining auto-accepted)[/]")
                    break

                if resp in ("s", "skip"):
                    rejected.append(diff)
                    self.console.print(f"  [{DIM}]↷  skipped[/]")
                    break

            self.console.print()

        return accepted, rejected

    def _apply_diff(self, diff: FileDiff, workspace: Path):
        """Write the diff to disk."""
        target = workspace / diff.path
        if diff.is_delete:
            if target.exists():
                target.unlink()
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(diff.new_content, encoding="utf-8")

    def _apply_all(self, diffs: List[FileDiff], workspace: Path):
        for d in diffs:
            self._apply_diff(d, workspace)


# ── DiffTracker — intercepts file_write calls ──────────────────────────────────

class DiffTracker:
    """
    Wraps file_write to capture diffs instead of writing immediately.
    Used when auto_accept=False to queue all writes for review.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.pending: DiffSet = DiffSet()
        self._active = False

    def start(self, agent_name: str = "", task: str = ""):
        self.pending = DiffSet(agent_name=agent_name, task_description=task)
        self._active = True

    def stop(self):
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def intercept_write(self, path: str, content: str, mode: str = "write") -> "ToolResult":
        """
        Called instead of file_write when tracking is active.
        Captures the diff and returns a fake success result.
        """
        from zencode.tools.file_manager import ToolResult
        target = self.workspace / path
        old_content = ""
        is_new = not target.exists()

        if target.exists():
            try:
                old_content = target.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

        if mode == "append":
            new_content = old_content + content
        else:
            new_content = content

        diff = FileDiff(
            path=path,
            old_content=old_content,
            new_content=new_content,
            is_new=is_new,
        )
        self.pending.add(diff)

        lines = len(content.splitlines())
        return ToolResult(
            True,
            output=f"[staged] {path} ({lines} lines) — pending review",
            metadata={"path": path, "staged": True},
        )
