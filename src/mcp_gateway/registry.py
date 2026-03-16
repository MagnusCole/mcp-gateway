"""Optional SQLite registry for dynamic server activate/deactivate at runtime."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ._types import ServerConfig


class Registry:
    """Thin SQLite wrapper for persisting server state across restarts.

    Only used when ``registry:`` is set in the gateway config YAML.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        conn = sqlite3.connect(self._path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                name       TEXT PRIMARY KEY,
                command    TEXT NOT NULL,
                args       TEXT NOT NULL DEFAULT '[]',
                env        TEXT,
                enabled    INTEGER NOT NULL DEFAULT 1,
                tools_json TEXT
            )
        """)
        conn.commit()
        conn.close()

    # ── Public API ───────────────────────────────────────────────────────

    def upsert(self, name: str, config: ServerConfig) -> None:
        conn = sqlite3.connect(self._path)
        conn.execute(
            """INSERT INTO servers (name, command, args, env, enabled)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                 command=excluded.command,
                 args=excluded.args,
                 env=excluded.env,
                 enabled=excluded.enabled
            """,
            (
                name,
                config.command,
                json.dumps(config.args),
                json.dumps(config.env) if config.env else None,
                int(config.enabled),
            ),
        )
        conn.commit()
        conn.close()

    def list_servers(self) -> list[dict]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM servers").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def activate(self, name: str) -> bool:
        return self._set_enabled(name, True)

    def deactivate(self, name: str) -> bool:
        return self._set_enabled(name, False)

    def get_config(self, name: str) -> ServerConfig | None:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM servers WHERE name=?", (name,)).fetchone()
        conn.close()
        if not row:
            return None
        return ServerConfig(
            command=row["command"],
            args=json.loads(row["args"]),
            env=json.loads(row["env"]) if row["env"] else None,
            enabled=bool(row["enabled"]),
        )

    def save_tools(self, name: str, tools_json: str) -> None:
        conn = sqlite3.connect(self._path)
        conn.execute(
            "UPDATE servers SET tools_json=? WHERE name=?", (tools_json, name)
        )
        conn.commit()
        conn.close()

    # ── Internals ────────────────────────────────────────────────────────

    def _set_enabled(self, name: str, enabled: bool) -> bool:
        conn = sqlite3.connect(self._path)
        conn.execute(
            "UPDATE servers SET enabled=? WHERE name=?", (int(enabled), name)
        )
        changed = conn.total_changes > 0
        conn.commit()
        conn.close()
        return changed
