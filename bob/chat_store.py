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


def display_session_title(title: str | None) -> str:
    return (title or "").strip() or "New conversation"


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
            cols = {str(row[1]) for row in self._conn.execute("PRAGMA table_info(sessions)").fetchall()}
            if "updated_at" not in cols:
                self._conn.execute("ALTER TABLE sessions ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
                self._conn.execute(
                    "UPDATE sessions SET updated_at = created_at WHERE updated_at IS NULL OR updated_at = ''"
                )
            if "title_generated" not in cols:
                self._conn.execute(
                    "ALTER TABLE sessions ADD COLUMN title_generated INTEGER NOT NULL DEFAULT 0"
                )
            self._conn.commit()

    def latest_session_id(self) -> int | None:
        with self._lock:
            row = self._conn.execute("SELECT id FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
        return int(row["id"]) if row else None

    def new_session(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessions (title, updated_at, title_generated) VALUES ('', datetime('now'), 0)"
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def current_session(self) -> int:
        sid = self.latest_session_id()
        return sid if sid is not None else self.new_session()

    def session_message_count(self, session_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?",
                (int(session_id),),
            ).fetchone()
        return int(row["n"] or 0) if row else 0

    def session_title(self, session_id: int) -> str:
        with self._lock:
            row = self._conn.execute("SELECT title FROM sessions WHERE id = ?", (int(session_id),)).fetchone()
        return str(row["title"] or "") if row else ""

    def session_title_generated(self, session_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT title_generated FROM sessions WHERE id = ?",
                (int(session_id),),
            ).fetchone()
        return bool(row and int(row["title_generated"] or 0))

    def touch_session(self, session_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET updated_at = datetime('now') WHERE id = ?",
                (int(session_id),),
            )
            self._conn.commit()

    def update_session_title(self, session_id: int, title: str, *, generated: bool = True) -> None:
        cleaned = (title or "").strip()[:80]
        with self._lock:
            self._conn.execute(
                """
                UPDATE sessions
                SET title = ?, title_generated = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (cleaned, 1 if generated else 0, int(session_id)),
            )
            self._conn.commit()

    def add_message(self, session_id: int, role: str, content: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at = datetime('now') WHERE id = ?",
                (int(session_id),),
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
                SELECT s.id, s.created_at, s.updated_at, s.title, s.title_generated,
                       (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS n
                FROM sessions s
                ORDER BY datetime(COALESCE(NULLIF(s.updated_at, ''), s.created_at)) DESC, s.id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"] or row["created_at"] or ""),
                "title": str(row["title"] or ""),
                "title_generated": bool(int(row["title_generated"] or 0)),
                "count": int(row["n"] or 0),
            }
            for row in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
