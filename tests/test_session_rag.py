from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from bob.memory.session_rag import SessionMemory, SessionVectorStore


def test_session_vector_store_filters_by_session(tmp_path):
    store = SessionVectorStore(tmp_path / "session", dim=4)
    store.load()
    vector = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    store.add("1:a", 1, "User: hello\nBob: hi", vector)
    store.add("2:a", 2, "User: other session", vector)

    hits = store.search(vector, session_id=1, limit=4)
    assert len(hits) == 1
    assert hits[0]["text"].startswith("User: hello")


def test_session_memory_retrieve_formats_block(tmp_path):
    embedder = MagicMock()
    embedder.dim = 4
    embedder.encode.return_value = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    memory = SessionMemory(tmp_path / "session", embedder)
    memory.load()
    memory.index_turn(7, "Search BBC", "Top story is about drones.")
    block = memory.retrieve(7, "BBC headlines", limit=3)

    assert "Earlier in this conversation" in block
    assert "Search BBC" in block
    assert "drones" in block
