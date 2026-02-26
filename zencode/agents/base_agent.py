from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class BaseAgent:
    name: str = "base"
    role: str = "General"
    emoji: str = "⬡"
    color: str = "#00f5ff"
    system_prompt: str = ""
    temperature: float = 0.3
    max_tokens: int = 8192
    tools: List[str] = field(default_factory=list)

    def build_messages(self, prompt: str, history: List[Dict]) -> List[Dict]:
        msgs = list(history)
        msgs.append({"role": "user", "content": prompt})
        return msgs

    def format_system(self, extra: str = None) -> str:
        base = self.system_prompt.strip()
        return f"{base}\n\n{extra.strip()}" if extra and extra.strip() else base

    def get_tool_schemas(self) -> list:
        if not self.tools:
            return []
        try:
            from zencode.tools.file_manager import ALL_SCHEMAS
            m = {s["function"]["name"]: s for s in ALL_SCHEMAS}
            return [m[t] for t in self.tools if t in m]
        except Exception:
            return []
