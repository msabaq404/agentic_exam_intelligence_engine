from __future__ import annotations

import json
import socket
import time
import uuid
from typing import Optional

from ..clients.embeddings import embed_text
from ..db.db import connect


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
            cur.execute(
                """
                SELECT pc.chunk_text, s.source_kind
                FROM ingestion.pdf_chunks pc
                JOIN ingestion.sources s ON s.source_id = pc.source_id
                WHERE pc.chunk_id = %s
                """,
                (chunk_id,),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"chunk not found: {chunk_id}")
            chunk_text, source_kind = row

            vector = embed_text(chunk_text)
            embedding_id = uuid.uuid4().hex
            cur.execute(
                "INSERT INTO ingestion.embeddings (embedding_id, chunk_id, source_kind, model, vector, score, created_at) VALUES (%s,%s,%s,%s,%s,%s,NOW())",
                (embedding_id, chunk_id, source_kind, "sentence-transformers/all-MiniLM-L6-v2", json.dumps(vector), None),
            )
            cur.execute(
                "UPDATE ingestion.pdf_chunks SET enrichment_status = 'embedded' WHERE chunk_id = %s",
                (chunk_id,),
            )
            cur.execute(
                "UPDATE ingestion.job_queue SET status = 'completed', finished_at = NOW() WHERE job_id = %s",
                (job_id,),
            )
            conn.commit()
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
