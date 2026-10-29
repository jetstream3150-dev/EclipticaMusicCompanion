"""Bounded local-only battle summaries; raw VRChat logs are never stored here."""
import json
import os
import tempfile
from pathlib import Path


class BattleResults:
    def __init__(self, path, limit=100):
        self.path = Path(path)
        self.limit = limit
        self.rows = []
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(data, list):
                self.rows = [r for r in data if isinstance(r, dict)][-limit:]
        except (OSError, ValueError, UnicodeError):
            pass

    def append(self, row):
        rows = (self.rows + [dict(row)])[-self.limit:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                    dir=self.path.parent, prefix='.results-', suffix='.tmp',
                    delete=False) as stream:
                name = stream.name
                json.dump(rows, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)
        self.rows = rows

    def latest(self, limit=20):
        return list(reversed(self.rows[-limit:]))
