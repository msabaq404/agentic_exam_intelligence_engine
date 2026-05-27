from __future__ import annotations

import uuid
from typing import List

from ..db.db import connect


def _heuristic_score(text: str) -> float:
    t = text.lower()
    score = 0.0
    # length-based boost (longer chunks slightly more likely to contain important content)
    score += min(len(t) / 500.0, 2.0)
    # question markers
    if "?" in t:
        score += 1.5
    # keywords indicating problems or calculations
    kws = ["calculate", "derive", "prove", "show", "find", "determine", "solve", "example", "question", "compute"]
    for k in kws:
        if k in t:
            score += 0.7
    # numeric content boost
    if any(c.isdigit() for c in t):
        score += 0.5
    return score


def enqueue_pending_chunks(batch_limit: int = 100, top_k: int = 50) -> int:
    """Enqueue deterministic jobs for pending chunks, but prioritize and only enqueue top_k by heuristic.

    - `batch_limit`: how many pending chunks to consider
    - `top_k`: how many to actually enqueue

    Returns the number of jobs enqueued.
    """
    enqueued = 0
    candidates: List[tuple[str, float, str]] = []  # (chunk_id, score, text_preview)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pc.chunk_id, pc.chunk_text
                FROM ingestion.pdf_chunks pc
                LEFT JOIN ingestion.job_queue jq ON jq.chunk_id = pc.chunk_id AND jq.stage = 'deterministic' AND jq.status IN ('pending','in_progress')
                WHERE pc.enrichment_status = 'pending' AND jq.job_id IS NULL
                LIMIT %s
                """,
                (batch_limit,),
            )
            for chunk_id, chunk_text in cur.fetchall():
                score = _heuristic_score(chunk_text or "")
                preview = (chunk_text or "")[:120].replace("\n", " ")
                candidates.append((chunk_id, score, preview))

            # sort by score desc and take top_k
            candidates.sort(key=lambda x: x[1], reverse=True)
            to_enqueue = candidates[:top_k]
            for chunk_id, score, preview in to_enqueue:
                job_id = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO ingestion.job_queue (job_id, chunk_id, stage, status, payload, created_at) VALUES (%s,%s,%s,%s,%s,NOW())",
                    (job_id, chunk_id, 'deterministic', 'pending', '{}'),
                )
                enqueued += 1
        conn.commit()
    return enqueued


def enqueue_llm_candidates(batch_limit: int = 100, top_k: int = 50) -> int:
    """Select embedded chunks and enqueue LLM-stage jobs for top_k by heuristic score.

    Returns number of llm jobs enqueued.
    """
    enqueued = 0
    candidates: List[tuple[str, float]] = []
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pc.chunk_id, pc.chunk_text
                FROM ingestion.pdf_chunks pc
                LEFT JOIN ingestion.job_queue jq ON jq.chunk_id = pc.chunk_id AND jq.stage = 'llm' AND jq.status IN ('pending','in_progress')
                WHERE pc.enrichment_status = 'embedded' AND jq.job_id IS NULL
                LIMIT %s
                """,
                (batch_limit,),
            )
            for chunk_id, chunk_text in cur.fetchall():
                score = _heuristic_score(chunk_text or "")
                candidates.append((chunk_id, score))

            candidates.sort(key=lambda x: x[1], reverse=True)
            to_enqueue = candidates[:top_k]
            for chunk_id, score in to_enqueue:
                job_id = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO ingestion.job_queue (job_id, chunk_id, stage, status, payload, created_at) VALUES (%s,%s,%s,%s,%s,NOW())",
                    (job_id, chunk_id, 'llm', 'pending', '{}'),
                )
                enqueued += 1
        conn.commit()
    return enqueued


if __name__ == "__main__":
    n = enqueue_pending_chunks()
    print(f"Enqueued {n} deterministic jobs")
