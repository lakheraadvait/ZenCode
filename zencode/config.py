#!/usr/bin/env python3
"""ZENCODE v11 — config.py"""

import json
from pathlib import Path
from datetime import datetime
from typing import Any

CONFIG_DIR  = Path.home() / ".zencode"
CONFIG_FILE = CONFIG_DIR / "config.json"

MISTRAL_MODELS = {
    "codestral-latest": {
        "alias": "code", "context_window": 256_000, "max_output": 16_384,
        "tier": "code", "description": "Best for code — 256k context",
    },
    "mistral-large-latest": {
        "alias": "large", "context_window": 131_072, "max_output": 16_384,
        "tier": "frontier", "description": "Top reasoning & architecture",
    },
    "mistral-medium-latest": {
        "alias": "medium", "context_window": 131_072, "max_output": 16_384,
        "tier": "frontier", "description": "Balanced speed & quality",
    },
    "mistral-small-latest": {
        "alias": "small", "context_window": 131_072, "max_output": 16_384,
        "tier": "efficient", "description": "Fast & cheap",
    },
    "open-mistral-nemo": {
        "alias": "nemo", "context_window": 131_072, "max_output": 16_384,
        "tier": "open", "description": "Open weights",
    },
}

DEFAULT_CONFIG: dict[str, Any] = {
    "version": "11.0.0",
    "created_at": "",
    "api_key": "",
    "model": "codestral-latest",
    "temperature": 0.3,
    "max_tokens": 8192,
    "workspace": ".",
    "syntax_theme": "monokai",
    "show_token_count": True,
    "splash_on_start": True,
    "chat_history_limit": 60,
    "show_agent_badge": True,
    "auto_accept": True,
    "show_diff": True,
    "diff_context_lines": 4,
    "max_debug_iterations": 6,
    "max_context_files": 60,
    "max_context_chars": 40000,
}

_RULES: dict[str, tuple] = {
    "temperature":          (float, 0.0, 1.0,  None),
    "max_tokens":           (int,   256, 32768, None),
    "chat_history_limit":   (int,   1,   200,   None),
    "max_debug_iterations": (int,   1,   15,    None),
    "max_context_files":    (int,   1,   200,   None),
    "diff_context_lines":   (int,   0,   10,    None),
    "model": (str, None, None, list(MISTRAL_MODELS.keys())),
}

_BOOL_KEYS = {"auto_accept", "show_diff", "show_token_count", "splash_on_start", "show_agent_badge"}


class ZenConfig:
    def __init__(self):
        self._data: dict[str, Any] = {}
        self._runtime_workspace: str = "."
        self._load()

    def _ensure_dir(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def _load(self):
        self._ensure_dir()
        if CONFIG_FILE.exists():
            try:
                saved = json.loads(CONFIG_FILE.read_text("utf-8"))
                self._data = {**DEFAULT_CONFIG, **saved}
                self._data["workspace"] = self._runtime_workspace
                return
            except Exception:
                pass
        self._data = DEFAULT_CONFIG.copy()
        self._data["created_at"] = datetime.now().isoformat()
        self._data["workspace"] = self._runtime_workspace
        self._save()

    def _save(self):
        self._ensure_dir()
        self._data["_updated_at"] = datetime.now().isoformat()
        CONFIG_FILE.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), "utf-8"
        )

    def _validate(self, key: str, value: Any) -> Any:
        if key in _BOOL_KEYS:
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes", "on")
            return bool(value)
        if key not in _RULES:
            return value
        typ, vmin, vmax, allowed = _RULES[key]
        try: value = typ(value)
        except Exception: raise ValueError(f"'{key}' must be {typ.__name__}")
        if vmin is not None and value < vmin: raise ValueError(f"'{key}' >= {vmin}")
        if vmax is not None and value > vmax: raise ValueError(f"'{key}' <= {vmax}")
        if allowed and value not in allowed:
            raise ValueError(f"'{key}' must be: {', '.join(str(a) for a in allowed)}")
        return value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        value = self._validate(key, value)
        self._data[key] = value
        self._save()

    def set_workspace(self, path: str):
        self._data["workspace"] = str(Path(path).resolve())

    def workspace(self) -> Path:
        return Path(self._data.get("workspace", ".")).resolve()

    def auto_accept(self) -> bool:
        return bool(self._data.get("auto_accept", False))

    def all(self) -> dict:
        return dict(self._data)

    def reset(self) -> None:
        key = self._data.get("api_key", "")
        ws  = self._data.get("workspace", ".")
        self._data = DEFAULT_CONFIG.copy()
        self._data["api_key"] = key
        self._data["workspace"] = ws
        self._data["created_at"] = datetime.now().isoformat()
        self._save()

    def model_info(self, model: str = None) -> dict:
        m = model or self._data.get("model", "codestral-latest")
        return MISTRAL_MODELS.get(m, {})

    def path(self) -> Path:
        return CONFIG_FILE

    def zenrules_path(self) -> Path:
        return self.workspace() / ".zenrules"

    def load_zenrules(self) -> str:
        p = self.zenrules_path()
        if p.exists():
            try: return p.read_text("utf-8").strip()
            except Exception: pass
        return ""


cfg = ZenConfig()
