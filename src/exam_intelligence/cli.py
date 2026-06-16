from __future__ import annotations

import argparse
import json
import threading
import time
import uuid

from .db.db import connect
from .db.schema import ensure_compatible_schema



def init_db() -> None:
    with connect() as connection:
        ensure_compatible_schema(connection)
        connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser(prog="exam-intel")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Create the exam intelligence schemas and tables")
    subparsers.add_parser("run-ocr", help="Run Azure Document Intelligence OCR/layout extraction worker")
    run_pipeline = subparsers.add_parser("run-pipeline", help="Run Azure -> Docling -> embeddings for a source")
    run_pipeline.add_argument("--source-id", required=True, help="Source ID already registered in ingestion.sources")
    run_embed = subparsers.add_parser("run-embed", help="Run the embedding worker")
    run_embed.add_argument("--start", action="store_true", help="Run continuously and poll for new jobs")
    run_embed.add_argument("--once", action="store_true", help="Process one pending job and exit")
    run_embed.add_argument("--drain", action="store_true", help="Process all pending jobs and exit")
    run_embed.add_argument("--poll-interval", type=float, default=1.0, help="Polling interval for continuous mode")
    run_llm = subparsers.add_parser("run-llm", help="Run the LLM worker")
    run_llm.add_argument("--start", action="store_true", help="Run continuously and poll for new jobs")
    run_llm.add_argument("--once", action="store_true", help="Process one batch of pending jobs and exit")
    run_llm.add_argument("--drain", action="store_true", help="Process all pending jobs and exit")
    run_llm.add_argument("--poll-interval", type=float, default=1.0, help="Polling interval for continuous mode")
    run_workers = subparsers.add_parser("run-workers", help="Run the embedding and LLM workers together in continuous mode")
    run_workers.add_argument("--poll-interval", type=float, default=1.0, help="Polling interval for both workers")
    run_export = subparsers.add_parser("run-export", help="Export for Coral")
    
    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
    elif args.command == "run-ocr":
        from .workers.ocr_worker import run_loop

        run_loop()
    elif args.command == "run-pipeline":
        job_id = uuid.uuid4().hex
        with connect() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO ingestion.job_queue (job_id, stage, status, payload, created_at) VALUES (%s,%s,%s,%s,NOW())",
                    (job_id, "ocr", "pending", json.dumps({"source_id": args.source_id})),
                )
            connection.commit()
        print({"job_id": job_id, "source_id": args.source_id, "stage": "ocr", "status": "queued"})
    elif args.command == "run-embed":
        from .workers.embed_worker import claim_job, process_job, run_loop

        if args.start:
            run_loop(poll_interval=args.poll_interval)
        else:
            with connect() as connection:
                if args.once:
                    job = claim_job(connection)
                    if job:
                        process_job(connection, job)
                else:
                    while True:
                        job = claim_job(connection)
                        if not job:
                            break
                        process_job(connection, job)
    elif args.command == "run-llm":
        from .workers.llm_worker import claim_jobs, process_job, run_loop

        if args.start:
            run_loop(poll_interval=args.poll_interval)
        else:
            with connect() as connection:
                if args.once:
                    jobs = claim_jobs(connection, batch_size=4)
                    for job in jobs:
                        process_job(connection, job)
                else:
                    while True:
                        jobs = claim_jobs(connection, batch_size=8)
                        if not jobs:
                            break
                        for job in jobs:
                            process_job(connection, job)
    elif args.command == "run-workers":
        from .workers.export_worker import run_loop as run_export_loop
        from .workers.embed_worker import run_loop as run_embed_loop
        from .workers.llm_worker import run_loop as run_llm_loop

        threads = [
            threading.Thread(target=run_export_loop, name="export-worker", daemon=True),
            threading.Thread(
                target=run_embed_loop,
                kwargs={"poll_interval": args.poll_interval},
                name="embed-worker-loop",
                daemon=True,
            ),
            threading.Thread(
                target=run_llm_loop,
                kwargs={"poll_interval": args.poll_interval},
                name="llm-worker-loop",
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()

        try:
            while any(thread.is_alive() for thread in threads):
                time.sleep(1)
        except KeyboardInterrupt:
            return
    elif args.command == "run-export":
        from .workers.export_worker import export
        export()


if __name__ == "__main__":
    main()
