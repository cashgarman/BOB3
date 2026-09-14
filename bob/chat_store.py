from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChatMessage:
    id: int
    session_id: int
    role: str
    content: str
    created_at: str


class ChatStore:
    """SQLite-backed conversation log. Survives restarts."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    title TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
                """
            )
            self._conn.commit()

    def latest_session_id(self) -> int | None:
        with self._lock:
            row = self._conn.execute("SELECT id FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
        return int(row["id"]) if row else None

    def new_session(self) -> int:
        with self._lock:
            cur = self._conn.execute("INSERT INTO sessions (title) VALUES ('')")
            self._conn.commit()
            return int(cur.lastrowid)

    def current_session(self) -> int:
        sid = self.latest_session_id()
        return sid if sid is not None else self.new_session()

    def add_message(self, session_id: int, role: str, content: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            row = self._conn.execute("SELECT title FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is not None and not str(row["title"] or "").strip() and role == "user":
                self._conn.execute(
                    "UPDATE sessions SET title = ? WHERE id = ?",
                    (content.strip()[:80], session_id),
                )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_messages(self, session_id: int) -> list[ChatMessage]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, session_id, role, content, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
        return [
            ChatMessage(
                id=int(row["id"]),
                session_id=int(row["session_id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def list_sessions(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT s.id, s.created_at, s.title,
                       (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS n
                FROM sessions s
                ORDER BY s.id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "created_at": str(row["created_at"]),
                "title": str(row["title"] or ""),
                "count": int(row["n"] or 0),
            }
            for row in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
