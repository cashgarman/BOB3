from __future__ import annotations

from pathlib import Path

import numpy as np


class Embedder:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self._model = None
        self.dim = 384

    def load(self) -> None:
        from sentence_transformers import SentenceTransformer

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._model = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2",
            cache_folder=str(self.cache_dir),
            device="cpu",
        )
        dim_fn = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self.dim = int(dim_fn())

    def encode(self, texts: str | list[str]) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Embedder is not loaded")
        single = isinstance(texts, str)
        batch = [texts] if single else list(texts)
        vectors = self._model.encode(
            batch,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        arr = np.asarray(vectors, dtype=np.float32)
        return arr[0] if single else arr
