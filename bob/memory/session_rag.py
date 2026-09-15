from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from bob.context import pairs_from_messages
from bob.memory.embed import Embedder


class SessionVectorStore:
    """Vector store for per-session conversation turns."""

    def __init__(self, path: Path, dim: int = 384) -> None:
        self.path = path
        self.dim = dim
        self._db = None
        self._table = None

    def load(self) -> None:
        import lancedb

        self.path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.path))
        names = set(self._db.table_names())
        if "session_turns" in names:
            self._table = self._db.open_table("session_turns")
            return
        seed = {
            "id": "_seed",
            "session_id": -1,
            "text": "",
            "enabled": False,
            "created": 0.0,
            "updated": 0.0,
            "vector": [0.0] * self.dim,
        }
        self._table = self._db.create_table("session_turns", data=[seed])
        try:
            self._table.delete("id = '_seed'")
        except Exception:
            pass

    def add(self, turn_id: str, session_id: int, text: str, vector: np.ndarray) -> None:
        now = time.time()
        row = {
            "id": turn_id,
            "session_id": int(session_id),
            "text": text,
            "enabled": True,
            "created": now,
            "updated": now,
            "vector": np.asarray(vector, dtype=np.float32).reshape(-1).tolist(),
        }
        self._table.add([row])

    def search(self, vector: np.ndarray, session_id: int, limit: int = 4) -> list[dict[str, Any]]:
        query = np.asarray(vector, dtype=np.float32).reshape(-1).tolist()
        try:
            hits = self._table.search(query).limit(max(limit * 6, 12)).to_list()
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for hit in hits:
            if hit.get("id") == "_seed":
                continue
            if int(hit.get("session_id") or -1) != int(session_id):
                continue
            if not hit.get("enabled", True):
                continue
            out.append(hit)
            if len(out) >= limit:
                break
        return out


class SessionMemory:
    """Retrieve earlier turns from the current chat session via embeddings."""

    def __init__(self, root: Path, embedder: Embedder) -> None:
        self.root = root
        self.embedder = embedder
        self.vectors = SessionVectorStore(root / "lancedb")
        self.ready = False
        self._lock = threading.RLock()

    def load(self) -> None:
        with self._lock:
            self.vectors.dim = self.embedder.dim
            self.vectors.load()
            self.ready = True

    def index_messages(self, session_id: int, messages: list[dict[str, Any]]) -> None:
        if not self.ready or not messages:
            return
        with self._lock:
            for user, assistant, tool_note in pairs_from_messages(messages):
                self._index_turn_locked(session_id, user, assistant, tool_note)

    def index_turn(self, session_id: int, user_text: str, assistant_text: str, tool_note: str = "") -> None:
        user = (user_text or "").strip()
        assistant = (assistant_text or "").strip()
        if not self.ready or not user or not assistant:
            return
        with self._lock:
            self._index_turn_locked(session_id, user, assistant, tool_note)

    def _index_turn_locked(
        self,
        session_id: int,
        user_text: str,
        assistant_text: str,
        tool_note: str = "",
    ) -> None:
        text = f"User: {user_text}\nBob: {assistant_text}"
        note = (tool_note or "").strip()
        if note:
            text += f"\n({note})"
        vector = self.embedder.encode(text)
        turn_id = f"{int(session_id)}:{uuid.uuid4().hex}"
        self.vectors.add(turn_id, session_id, text, vector)

    def retrieve(self, session_id: int, query: str, limit: int = 6) -> str:
        if not self.ready or not query.strip():
            return ""
        with self._lock:
            vector = self.embedder.encode(query)
            hits = self.vectors.search(vector, session_id=session_id, limit=max(1, int(limit)))
        lines = [str(row.get("text") or "").strip() for row in hits]
        lines = [line for line in lines if line]
        if not lines:
            return ""
        return (
            "Earlier in this conversation (background only — do not read aloud):\n"
            + "\n".join(f"- {line}" for line in lines)
        )

    def clear_session(self, session_id: int) -> None:
        if not self.ready:
            return
        with self._lock:
            try:
                self.vectors._table.delete(f"session_id = {int(session_id)}")
            except Exception:
                pass
