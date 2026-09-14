from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np


class VectorStore:
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
        if "memories" in names:
            self._table = self._db.open_table("memories")
            return
        seed = {
            "id": "_seed",
            "text": "",
            "enabled": False,
            "created": 0.0,
            "updated": 0.0,
            "vector": [0.0] * self.dim,
        }
        self._table = self._db.create_table("memories", data=[seed])
        try:
            self._table.delete("id = '_seed'")
        except Exception:
            pass

    def add(
        self,
        text: str,
        vector: np.ndarray,
        memory_id: str | None = None,
        enabled: bool = True,
        created: float | None = None,
    ) -> str:
        mid = memory_id or uuid.uuid4().hex
        now = time.time()
        row = {
            "id": mid,
            "text": text,
            "enabled": bool(enabled),
            "created": float(created) if created else now,
            "updated": now,
            "vector": np.asarray(vector, dtype=np.float32).reshape(-1).tolist(),
        }
        self._table.add([row])
        return mid

    def update_text(self, memory_id: str, text: str, vector: np.ndarray) -> None:
        # Keep the enabled flag and creation time; editing a disabled memory
        # should not silently switch it back on.
        prior = next((r for r in self.list_all() if r["id"] == memory_id), None)
        enabled = bool(prior.get("enabled", True)) if prior else True
        created = float(prior.get("created") or 0) if prior else None
        self.delete(memory_id)
        self.add(text, vector, memory_id=memory_id, enabled=enabled, created=created or None)

    def set_enabled(self, memory_id: str, enabled: bool) -> None:
        rows = [r for r in self.list_all() if r["id"] == memory_id]
        if not rows:
            return
        row = rows[0]
        self.delete(memory_id)
        row["enabled"] = bool(enabled)
        row["updated"] = time.time()
        self._table.add([row])

    def delete(self, memory_id: str) -> None:
        try:
            self._table.delete(f"id = '{memory_id}'")
        except Exception:
            pass

    def clear(self) -> None:
        for row in self.list_all():
            self.delete(row["id"])

    def list_all(self) -> list[dict[str, Any]]:
        try:
            frame = self._table.to_pandas()
        except Exception:
            return []
        rows = []
        for rec in frame.to_dict(orient="records"):
            if rec.get("id") == "_seed":
                continue
            vec = rec.get("vector")
            if hasattr(vec, "tolist"):
                rec["vector"] = vec.tolist()
            rows.append(rec)
        rows.sort(key=lambda r: float(r.get("updated") or 0), reverse=True)
        return rows

    def search(self, vector: np.ndarray, limit: int = 8) -> list[dict[str, Any]]:
        query = np.asarray(vector, dtype=np.float32).reshape(-1).tolist()
        try:
            hits = self._table.search(query).limit(max(limit * 3, 8)).to_list()
        except Exception:
            return []
        out = []
        for hit in hits:
            if hit.get("id") == "_seed" or not hit.get("enabled", True):
                continue
            out.append(hit)
            if len(out) >= limit:
                break
        return out

    def nearest(self, vector: np.ndarray) -> tuple[dict[str, Any] | None, float]:
        hits = self.search(vector, limit=1)
        if not hits:
            return None, 0.0
        hit = hits[0]
        score = hit.get("_distance")
        if score is None:
            return hit, 1.0
        # Lance L2 distance on normalized vectors ~ 2 - 2cos
        dist = float(score)
        sim = max(0.0, 1.0 - dist / 2.0)
        return hit, sim
