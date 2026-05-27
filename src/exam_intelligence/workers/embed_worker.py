from __future__ import annotations

import json
import time
import uuid
import socket
from typing import Optional

from ..db.db import connect
from ..clients.embeddings import embed_text
import os


WORKER_NAME = f"embed-worker-{socket.gethostname()}"


def claim_job(conn) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id, chunk_id, payload
            FROM ingestion.job_queue
            WHERE stage = 'embed' AND status = 'pending' AND scheduled_at <= NOW()
            ORDER BY scheduled_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        job_id, chunk_id, payload = row
        cur.execute(
            """
            UPDATE ingestion.job_queue
            SET status = 'in_progress', worker = %s, attempts = attempts + 1, started_at = NOW()
            WHERE job_id = %s
            """,
            (WORKER_NAME, job_id),
        )
        conn.commit()
        return {"job_id": job_id, "chunk_id": chunk_id, "payload": payload}


def process_job(conn, job: dict) -> None:
    job_id = job["job_id"]
    chunk_id = job["chunk_id"]
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT chunk_text FROM ingestion.pdf_chunks WHERE chunk_id = %s", (chunk_id,))
            r = cur.fetchone()
            if not r:
                raise RuntimeError(f"chunk not found: {chunk_id}")
            chunk_text = r[0]

            # compute embedding
            model = None
            vec = embed_text(chunk_text, model=model)

            embedding_id = uuid.uuid4().hex
            cur.execute(
                "INSERT INTO ingestion.embeddings (embedding_id, chunk_id, model, vector, score, created_at) VALUES (%s,%s,%s,%s,%s,NOW())",
                (embedding_id, chunk_id, model or 'fallback', json.dumps(vec), None),
            )

            # mark job completed and set chunk status
            cur.execute(
                "UPDATE ingestion.job_queue SET status = 'completed', finished_at = NOW() WHERE job_id = %s",
                (job_id,),
            )
            cur.execute(
                "UPDATE ingestion.pdf_chunks SET enrichment_status = 'embedded' WHERE chunk_id = %s",
                (chunk_id,),
            )
            conn.commit()

            # Optionally enqueue LLM candidates after embedding pass
            try:
                top_k_env = os.environ.get("LLM_TOP_K")
                if top_k_env:
                    from . import enqueuer

                    try:
                        top_k = int(top_k_env)
                    except Exception:
                        top_k = 0
                    if top_k > 0:
                        n = enqueuer.enqueue_llm_candidates(batch_limit=200, top_k=top_k)
                        if n:
                            print(f"Enqueued {n} llm jobs after embedding (top_k={top_k})")
            except Exception:
                # keep embed worker resilient; do not fail the job if enqueuer errors
                pass

    except Exception as exc:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion.job_queue SET status = 'failed', last_error = %s, finished_at = NOW() WHERE job_id = %s",
                (str(exc), job_id),
            )
            conn.commit()
        raise


def run_loop(poll_interval: float = 1.0) -> None:
    print("embed-worker starting")
    while True:
        try:
            with connect() as conn:
                job = claim_job(conn)
                if not job:
                    time.sleep(poll_interval)
                    continue
                process_job(conn, job)
        except KeyboardInterrupt:
            print("embed-worker stopping")
            return
        except Exception as exc:
            print("embed-worker error:", exc)
            time.sleep(2)


if __name__ == "__main__":
    run_loop()
