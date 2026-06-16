from __future__ import annotations

import json
import socket
import time
from typing import Optional

from ..core.pipeline import _process_source
from ..db.db import connect


WORKER_NAME = f"ocr-worker-{socket.gethostname()}"


def claim_job(conn) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id, payload
            FROM ingestion.job_queue
            WHERE stage = 'ocr' AND status IN ('pending', 'failed') AND scheduled_at <= NOW()
            ORDER BY scheduled_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        job_id, payload = row
        cur.execute(
            """
            UPDATE ingestion.job_queue
            SET status = 'in_progress', worker = %s, attempts = attempts + 1, started_at = NOW()
            WHERE job_id = %s
            """,
            (WORKER_NAME, job_id),
        )
        conn.commit()
        return {"job_id": job_id, "payload": payload}


def _payload_as_dict(payload: object) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        return json.loads(payload)
    raise RuntimeError(f"Unexpected OCR payload type: {type(payload)!r}")


def process_job(conn, job: dict) -> None:
    job_id = job["job_id"]
    payload = _payload_as_dict(job["payload"])
    source_id = payload.get("source_id")
    if not source_id:
        raise RuntimeError("ocr job missing source_id")

    try:
        _process_source(source_id)
        with conn.cursor() as cur:
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
    print("ocr-worker starting")
    while True:
        try:
            with connect() as conn:
                job = claim_job(conn)
                if not job:
                    time.sleep(poll_interval)
                    continue
                process_job(conn, job)
        except KeyboardInterrupt:
            print("ocr-worker stopping")
            return
        except Exception as exc:
            print("ocr-worker error:", exc)
            return


if __name__ == "__main__":
    run_loop()