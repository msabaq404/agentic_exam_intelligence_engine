from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache
from typing import Any, List

DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
DEFAULT_EMBEDDING_MODEL_PATH = os.getenv("EMBEDDING_MODEL_PATH")


@lru_cache(maxsize=4)
def _load_model(model_name: str, *, local_only: bool) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        raise ImportError(
            "sentence-transformers is required for embeddings. Install the embeddings extra."
        ) from exc

    try:
        if local_only:
            return SentenceTransformer(model_name, local_files_only=True)
        return SentenceTransformer(model_name)
    except Exception as exc:
        raise RuntimeError(f"failed to load embedding model '{model_name}': {exc}") from exc


def embed_text(text: str, model: str = None, dim: int = 128) -> List[float]:
    model_name = model or DEFAULT_EMBEDDING_MODEL or DEFAULT_EMBEDDING_MODEL_PATH
    if not model_name:
        raise RuntimeError(
            "Set EMBEDDING_MODEL_PATH to a local sentence-transformers directory or set EMBEDDING_MODEL to a model id."
        )

    model_path = Path(model_name)
    local_only = model_path.exists() and model_path.is_dir()
    encoder = _load_model(str(model_path if local_only else model_name), local_only=local_only)
    try:
        vector = encoder.encode([text], normalize_embeddings=True)[0]
        return vector.tolist()
    except Exception as exc:
        raise RuntimeError(f"embedding failed for model '{model_name}': {exc}") from exc
