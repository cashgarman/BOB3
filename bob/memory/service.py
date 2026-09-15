from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from bob.memory.embed import Embedder
from bob.memory.extract import EXTRACT_PROMPT, parse_facts
from bob.memory.graph import MemoryGraph
from bob.memory.vectors import VectorStore


class MemoryService:
    """Long-term memory. Ingest runs on a background thread after each turn while
    retrieve (pipeline thread) and edit/delete (UI thread) can run at the same
    time, so every store access goes through one lock."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.embedder = Embedder(root.parent.parent / "models" / "embeddings")
        self.vectors = VectorStore(root / "lancedb")
        self.graph = MemoryGraph(root / "kuzu.kz")
        self.ready = False
        self._lock = threading.RLock()

    def load(self) -> None:
        with self._lock:
            self.embedder.load()
            self.vectors.dim = self.embedder.dim
            self.vectors.load()
            self.graph.load()
            self.ready = True

    def retrieve(self, query: str, limit: int = 8) -> str:
        if not self.ready or not query.strip():
            return ""
        with self._lock:
            return self._retrieve(query, limit)

    def _retrieve(self, query: str, limit: int) -> str:
        vector = self.embedder.encode(query)
        hits = self.vectors.search(vector, limit=limit)
        names = _guess_names(query)
        extra_ids = set(self.graph.related_fact_ids(names)) if names else set()
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in hits:
            mid = row.get("id")
            if mid and mid not in seen:
                merged.append(row)
                seen.add(mid)
        if extra_ids:
            by_id = {row["id"]: row for row in self.vectors.list_all() if row.get("enabled", True)}
            for mid in extra_ids:
                if mid in seen or mid not in by_id:
                    continue
                merged.append(by_id[mid])
                seen.add(mid)
                if len(merged) >= limit:
                    break
        lines = [str(row.get("text") or "").strip() for row in merged[:limit]]
        lines = [ln for ln in lines if ln]
        if not lines:
            return ""
        return "Background for you only — do not repeat aloud:\n" + "\n".join(f"- {ln}" for ln in lines)

    def ingest(self, user_text: str, assistant_text: str, generate) -> list[str]:
        if not self.ready:
            return []
        blob = f"User: {user_text}\nBob: {assistant_text}"
        # The LLM call is slow and needs no lock; only the store writes do.
        raw = generate(EXTRACT_PROMPT, blob, 300)
        facts = parse_facts(raw)
        stored = []
        with self._lock:
            for fact in facts:
                vector = self.embedder.encode(fact["text"])
                existing, sim = self.vectors.nearest(vector)
                if existing and sim >= 0.90:
                    mid = existing["id"]
                    self.vectors.update_text(mid, fact["text"], vector)
                    self.graph.remove_fact(mid)
                    self.graph.attach_fact(mid, fact["entities"], fact["relations"])
                    stored.append(mid)
                    continue
                mid = self.vectors.add(fact["text"], vector)
                self.graph.attach_fact(mid, fact["entities"], fact["relations"])
                stored.append(mid)
        return stored

    def list_memories(self) -> list[dict[str, Any]]:
        if not self.ready:
            return []
        with self._lock:
            return self.vectors.list_all()

    def set_enabled(self, memory_id: str, enabled: bool) -> None:
        if self.ready:
            with self._lock:
                self.vectors.set_enabled(memory_id, enabled)

    def edit(self, memory_id: str, text: str) -> None:
        if not self.ready:
            return
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            vector = self.embedder.encode(text)
            self.vectors.update_text(memory_id, text, vector)

    def delete(self, memory_id: str) -> None:
        if not self.ready:
            return
        with self._lock:
            self.vectors.delete(memory_id)
            self.graph.remove_fact(memory_id)

    def forget_all(self) -> None:
        if not self.ready:
            return
        with self._lock:
            self.vectors.clear()
            self.graph.clear()


def _guess_names(text: str) -> list[str]:
    words = []
    for token in text.replace(",", " ").split():
        clean = token.strip(".,!?\"'")
        if len(clean) > 2 and clean[:1].isupper():
            words.append(clean)
    return words
