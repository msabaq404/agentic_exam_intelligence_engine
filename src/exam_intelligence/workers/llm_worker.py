from __future__ import annotations

import hashlib
import json
import socket
import time
import uuid
from typing import Optional

from jsonschema import ValidationError, validate

from ..clients.llm_client import get_gemini_client
from ..core.contracts import PYQ_EXTRACTION_JSON_SCHEMA, PYQ_EXTRACTION_PROMPT, TEXTBOOK_PARSING_JSON_SCHEMA, TEXTBOOK_PARSING_PROMPT
from ..core.pipeline import _normalize_question_text, _normalize_question_type
from ..db.db import connect


WORKER_NAME = f"llm-worker-{socket.gethostname()}"


def _prompt_hash(model: str, prompt: str, text: str) -> str:
    h = hashlib.sha256()
    h.update((model or "").encode("utf-8"))
    h.update(b"::")
    h.update(prompt.encode("utf-8"))
    h.update(b"::")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def claim_jobs(conn, batch_size: int = 4) -> list[dict]:
    jobs: list[dict] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id, chunk_id, payload
            FROM ingestion.job_queue
            WHERE stage = 'llm' AND status = 'pending' AND scheduled_at <= NOW()
            ORDER BY scheduled_at
            FOR UPDATE SKIP LOCKED
            LIMIT %s
            """,
            (batch_size,),
        )
        rows = cur.fetchall()
        if not rows:
            return jobs
        job_ids = [row[0] for row in rows]
        cur.execute(
            "UPDATE ingestion.job_queue SET status = 'in_progress', worker = %s, attempts = attempts + 1, started_at = NOW() WHERE job_id = ANY(%s)",
            (WORKER_NAME, job_ids),
        )
        conn.commit()
        for job_id, chunk_id, payload in rows:
            jobs.append({"job_id": job_id, "chunk_id": chunk_id, "payload": payload})
    return jobs


def _load_chunk(conn, chunk_id: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pc.chunk_text, pc.chunk_kind, pc.source_id, s.source_uri, pp.page_number FROM ingestion.pdf_chunks pc LEFT JOIN ingestion.pdf_pages pp ON pp.page_id = pc.page_id LEFT JOIN ingestion.sources s ON s.source_id = pc.source_id WHERE pc.chunk_id = %s",
            (chunk_id,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"chunk not found: {chunk_id}")
        return row


def _store_raw_output(cur, *, chunk_id: str, model_name: str, prompt_hash: str, response_json: dict) -> None:
    output_id = uuid.uuid4().hex
    cur.execute(
        "INSERT INTO ingestion.raw_llm_outputs (output_id, chunk_id, model, prompt_hash, response_json, created_at) VALUES (%s,%s,%s,%s,%s,NOW())",
        (output_id, chunk_id, model_name, prompt_hash, json.dumps(response_json)),
    )


def process_job(conn, job: dict) -> None:
    job_id = job["job_id"]
    chunk_id = job["chunk_id"]
    try:
        chunk_text, chunk_kind, source_id, source_uri, page_number = _load_chunk(conn, chunk_id)
        normalized_kind = (chunk_kind or "").lower()

        if normalized_kind in ("question", "pyq", "mcq", "nq"):
            prompt = PYQ_EXTRACTION_PROMPT
            schema = PYQ_EXTRACTION_JSON_SCHEMA
            client = get_gemini_client()
            model_name = getattr(client, "model", None) or "sdk_client"
            cache_key = _prompt_hash(model_name, prompt, chunk_text)
            candidate_prompt = "\n\n".join(
                [
                    prompt,
                    f"SOURCE_KIND: {normalized_kind}",
                        f"SOURCE_URI: {source_uri}",
                    "CANDIDATE_BLOCKS:",
                    "\n".join(
                        [
                            f"CANDIDATE_ID: {chunk_id}",
                            f"PAGE_NUMBER: {page_number}",
                            "QUESTION_NUMBER_HINT: None",
                            "TEXT:",
                            chunk_text,
                        ]
                    ),
                ]
            )

            with conn.cursor() as cur:
                cur.execute("SELECT response_json FROM ingestion.llm_cache WHERE cache_key = %s", (cache_key,))
                cached = cur.fetchone()
                if cached:
                    response_json = cached[0]
                else:
                    resp = client.infer(candidate_prompt, params={"max_tokens": 4096, "temperature": 0.0})
                    raw_text = resp.get("text", "") if isinstance(resp, dict) else str(resp)
                    response_json = json.loads(raw_text)
                    cur.execute(
                        "INSERT INTO ingestion.llm_cache (cache_key, model, response_json, created_at) VALUES (%s,%s,%s,NOW())",
                        (cache_key, model_name, json.dumps(response_json)),
                    )

                _store_raw_output(cur, chunk_id=chunk_id, model_name=model_name, prompt_hash=cache_key, response_json=response_json)

                for question in response_json.get("questions", []):
                    question["question_type"] = _normalize_question_type(question.get("question_type", ""))
                validate(instance=response_json, schema=schema)

                inserted_question_id = None
                for question in response_json["questions"]:
                    question_text = _normalize_question_text(chunk_text, question.get("question_text", ""))
                    question_id = uuid.uuid4().hex
                    if not question_text:
                        continue
                    cur.execute(
                        "INSERT INTO exam.questions (question_id, source_id, source_uri, page_number, question_number, question_text, year, topic, subtopic, difficulty, question_type, concepts_json, prerequisites_json, semantic_tags_json, pattern_type, conceptual_depth, importance_score, confidence, raw_structured_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            question_id,
                            source_id,
                            source_uri,
                            page_number,
                            question.get("question_number"),
                            question_text,
                            question.get("exam_year"),
                            question.get("topic", ""),
                            question.get("subtopic"),
                            question.get("difficulty", "Medium"),
                            question.get("question_type", "Theory"),
                            json.dumps(question.get("concepts", [])),
                            json.dumps(question.get("prerequisites", [])),
                            json.dumps(question.get("semantic_tags", [])),
                            question.get("pattern_type"),
                            question.get("conceptual_depth", 0.0),
                            question.get("importance_score", 0.0),
                            question.get("confidence", 0.0),
                            json.dumps(question),
                        ),
                    )
                    inserted_question_id = question_id
                    cur.execute(
                        "UPDATE ingestion.pdf_chunks SET enrichment_status = 'done', enriched_question_id = %s WHERE chunk_id = %s",
                        (question_id, chunk_id),
                    )

        else:
            prompt = TEXTBOOK_PARSING_PROMPT
            schema = TEXTBOOK_PARSING_JSON_SCHEMA
            client = get_gemini_client()
            model_name = getattr(client, "model", None) or "sdk_client"
            cache_key = _prompt_hash(model_name, prompt, chunk_text)
            full_prompt = prompt + "\n\n" + chunk_text

            with conn.cursor() as cur:
                cur.execute("SELECT response_json FROM ingestion.llm_cache WHERE cache_key = %s", (cache_key,))
                cached = cur.fetchone()
                if cached:
                    response_json = cached[0]
                else:
                    resp = client.infer(full_prompt, params={"max_tokens": 2048})
                    raw_text = resp.get("text", "") if isinstance(resp, dict) else str(resp)
                    response_json = json.loads(raw_text)
                    cur.execute(
                        "INSERT INTO ingestion.llm_cache (cache_key, model, response_json, created_at) VALUES (%s,%s,%s,NOW())",
                        (cache_key, model_name, json.dumps(response_json)),
                    )

                _store_raw_output(cur, chunk_id=chunk_id, model_name=model_name, prompt_hash=cache_key, response_json=response_json)
                validate(instance=response_json, schema=schema)

                chunk_uuid = uuid.uuid4().hex
                cur.execute(
                    "INSERT INTO exam.textbook_chunks (chunk_id, source_id, chunk_text, chapter, section, main_concept, prerequisites_json, formulas_json, definitions_json, semantic_tags_json, exam_relevance_score, conceptual_importance, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())",
                    (
                        chunk_uuid,
                        source_id,
                        chunk_text,
                        response_json.get("chapter"),
                        response_json.get("section"),
                        response_json.get("main_concept"),
                        json.dumps(response_json.get("prerequisites", [])),
                        json.dumps(response_json.get("formulas", [])),
                        json.dumps(response_json.get("definitions", [])),
                        json.dumps(response_json.get("semantic_tags", [])),
                        response_json.get("exam_relevance_score", 0.0),
                        response_json.get("conceptual_importance", 0.0),
                    ),
                )
                cur.execute(
                    "UPDATE ingestion.pdf_chunks SET enrichment_status = 'done', enriched_question_id = %s WHERE chunk_id = %s",
                    (chunk_uuid, chunk_id),
                )

        with conn.cursor() as cur:
            cur.execute("UPDATE ingestion.job_queue SET status = 'completed', finished_at = NOW() WHERE job_id = %s", (job_id,))
            conn.commit()

    except Exception as exc:
        with conn.cursor() as cur:
            cur.execute("UPDATE ingestion.job_queue SET status = 'failed', last_error = %s, finished_at = NOW() WHERE job_id = %s", (str(exc), job_id))
            cur.execute("UPDATE ingestion.pdf_chunks SET enrichment_status = 'error' WHERE chunk_id = %s", (chunk_id,))
            conn.commit()
        raise


def run_loop(poll_interval: float = 1.0) -> None:
    print("llm-worker starting")
    while True:
        try:
            with connect() as conn:
                jobs = claim_jobs(conn, batch_size=4)
                if not jobs:
                    time.sleep(poll_interval)
                    continue
                for job in jobs:
                    process_job(conn, job)
        except KeyboardInterrupt:
            print("llm-worker stopping")
            return
        except Exception as exc:
            print("llm-worker error:", exc)
            time.sleep(2)
