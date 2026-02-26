"""ZENCODE v11 — minimal event bus (IDE removed, kept for tool compat)."""

class _Bus:
    def publish(self, event: str, data: dict): pass

bus = _Bus()
