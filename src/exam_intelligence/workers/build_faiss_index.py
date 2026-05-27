from __future__ import annotations

import json
import os
from typing import List

from ..db.db import connect


def _coerce_vector(vec_json):
    if isinstance(vec_json, str):
        return json.loads(vec_json)
    return list(vec_json)


def fetch_embeddings(limit: int = 10000):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT embedding_id, chunk_id, vector FROM ingestion.embeddings ORDER BY created_at LIMIT %s", (limit,))
            for eid, cid, vec_json in cur.fetchall():
                yield eid, cid, _coerce_vector(vec_json)


def build_index(output_path: str = "faiss.index") -> None:
    try:
        import faiss
        import numpy as np
    except Exception:
        print("faiss is not installed. Install with: pip install faiss-cpu")
        return

    items = list(fetch_embeddings())
    if not items:
        print("No embeddings found")
        return
    dim = len(items[0][2])
    xb = np.array([it[2] for it in items], dtype='float32')
    index = faiss.IndexFlatL2(dim)
    index.add(xb)
    faiss.write_index(index, output_path)
    print(f"Wrote {len(items)} vectors to {output_path}")


if __name__ == "__main__":
    build_index()
