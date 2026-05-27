from __future__ import annotations

import argparse

from .db.db import connect
from .db.schema import DDL


def init_db() -> None:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(DDL)
        connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser(prog="exam-intel")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Create the exam intelligence schemas and tables")
    subparsers.add_parser("run-ocr", help="Run Azure Document Intelligence OCR/layout extraction worker")
    run_pipeline = subparsers.add_parser("run-pipeline", help="Run Azure -> Docling -> embeddings for a source")
    run_pipeline.add_argument("--source-id", required=True, help="Source ID already registered in ingestion.sources")
    run_enrich = subparsers.add_parser("run-enrich", help="Run enrichment on pending chunks")
    run_enrich.add_argument("--limit", type=int, default=50)
    run_enrich.add_argument("--top-k", type=int, default=None, help="If set, enqueue only top-K pending chunks using prioritization heuristic")

    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
    elif args.command == "run-ocr":
        from .workers.ocr_worker import run_loop

        run_loop()
    elif args.command == "run-pipeline":
        from .core.pipeline import process_source

        summary = process_source(args.source_id)
        print(summary)
    elif args.command == "run-enrich":
        # If top_k supplied, use the enqueuer to enqueue prioritized deterministic jobs
        from .workers import enqueuer

        top_k = args.top_k
        if top_k is None:
            # fall back to env var LLM_TOP_K if present
            import os

            try:
                top_k = int(os.environ.get("LLM_TOP_K") or 0) or None
            except Exception:
                top_k = None

        if top_k:
            n = enqueuer.enqueue_pending_chunks(batch_limit=args.limit, top_k=top_k)
            print(f"Enqueued {n} prioritized deterministic jobs (top_k={top_k})")
        else:
            from .workers.runner import run_enrichment

            run_enrichment(limit=args.limit)


if __name__ == "__main__":
    main()
