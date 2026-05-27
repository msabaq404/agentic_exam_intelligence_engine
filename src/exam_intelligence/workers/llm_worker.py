from __future__ import annotations

import hashlib
import json
import time
import uuid
import socket
from typing import Optional

from jsonschema import validate, ValidationError

from ..db.db import connect
from ..clients.llm_client import get_gemini_client
from ..core.contracts import PYQ_ANALYSIS_JSON_SCHEMA, TEXTBOOK_PARSING_JSON_SCHEMA, PYQ_ANALYSIS_PROMPT, TEXTBOOK_PARSING_PROMPT


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
    """Claim up to batch_size pending llm jobs and mark them in-progress.

    Returns a list of job dicts.
    """
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
        job_ids = [r[0] for r in rows]
        # mark all claimed jobs in_progress
        cur.execute(
            "UPDATE ingestion.job_queue SET status = 'in_progress', worker = %s, attempts = attempts + 1, started_at = NOW() WHERE job_id = ANY(%s)",
            (WORKER_NAME, job_ids),
        )
        conn.commit()
        for job_id, chunk_id, payload in rows:
            jobs.append({"job_id": job_id, "chunk_id": chunk_id, "payload": payload})
    return jobs


def process_job(conn, job: dict) -> None:
    job_id = job["job_id"]
    chunk_id = job["chunk_id"]
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT chunk_text, chunk_kind, source_id FROM ingestion.pdf_chunks WHERE chunk_id = %s", (chunk_id,))
            r = cur.fetchone()
            if not r:
                raise RuntimeError(f"chunk not found: {chunk_id}")
            chunk_text, chunk_kind, source_id = r

            # choose prompt
            if chunk_kind and chunk_kind.lower() in ("question", "pyq", "mcq", "nq"):
                prompt = PYQ_ANALYSIS_PROMPT
                schema = PYQ_ANALYSIS_JSON_SCHEMA
                is_question = True
            else:
                prompt = TEXTBOOK_PARSING_PROMPT
                schema = TEXTBOOK_PARSING_JSON_SCHEMA
                is_question = False

            # obtain an SDK-backed client; fail loudly if SDK not present
            client = get_gemini_client()
            model_name = getattr(client, "model", None) or "sdk_client"
            cache_key = _prompt_hash(model_name, prompt, chunk_text)

            # check cache
            cur.execute("SELECT response_json FROM ingestion.llm_cache WHERE cache_key = %s", (cache_key,))
            cached = cur.fetchone()
            if cached:
                response_json = cached[0]
            else:
                # call LLM via SDK client (no fallbacks)
                resp = client.infer(prompt + "\n\n" + chunk_text, params={"max_tokens": 2048})

                # normalize response to JSON
                if isinstance(resp, dict):
                    # if provider returns text field, prefer that
                    if "text" in resp:
                        try:
                            response_json = json.loads(resp["text"]) if isinstance(resp["text"], str) else resp["text"]
                        except Exception:
                            response_json = {"text": resp["text"]}
                    elif "output" in resp:
                        try:
                            response_json = json.loads(resp["output"]) if isinstance(resp["output"], str) else resp["output"]
                        except Exception:
                            response_json = {"output": resp["output"]}
                    else:
                        response_json = resp
                else:
                    # assume plain string
                    try:
                        response_json = json.loads(resp)
                    except Exception:
                        response_json = {"text": str(resp)}

                # persist cache
                cur.execute("INSERT INTO ingestion.llm_cache (cache_key, model, response_json, created_at) VALUES (%s,%s,%s,NOW())", (cache_key, model_name, json.dumps(response_json)))

            # persist raw output
            output_id = uuid.uuid4().hex
            cur.execute("INSERT INTO ingestion.raw_llm_outputs (output_id, chunk_id, model, prompt_hash, response_json, created_at) VALUES (%s,%s,%s,%s,%s,NOW())", (output_id, chunk_id, model_name, cache_key, json.dumps(response_json)))

            # validate and insert into exam tables
            # response_json may be a dict already matching schema
            try:
                validate(instance=response_json, schema=schema)
            except ValidationError as e:
                # try to find textual field and parse
                if isinstance(response_json, dict) and "text" in response_json:
                    try:
                        parsed = json.loads(response_json["text"])
                        validate(instance=parsed, schema=schema)
                        response_json = parsed
                    except Exception:
                        raise
                else:
                    raise

            if is_question:
                question_id = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO exam.questions (question_id, source_id, exam_year, topic, subtopic, difficulty, question_type, concepts_json, prerequisites_json, semantic_tags_json, pattern_type, conceptual_depth, importance_score, confidence, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())",
                    (
                        question_id,
                        source_id,
                        None,
                        response_json.get("topic"),
                        response_json.get("subtopic"),
                        response_json.get("difficulty"),
                        response_json.get("question_type"),
                        json.dumps(response_json.get("concepts", [])),
                        json.dumps(response_json.get("prerequisites", [])),
                        json.dumps(response_json.get("semantic_tags", [])),
                        response_json.get("pattern_type"),
                        response_json.get("conceptual_depth", 0.0),
                        response_json.get("importance_score", 0.0),
                        response_json.get("confidence", 0.0),
                    ),
                )
                cur.execute("UPDATE ingestion.pdf_chunks SET enrichment_status = 'done', enriched_question_id = %s WHERE chunk_id = %s", (question_id, chunk_id))
            else:
                chunk_uuid = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO exam.textbook_chunks (chunk_id, source_id, chapter, section, main_concept, prerequisites_json, formulas_json, definitions_json, semantic_tags_json, exam_relevance_score, conceptual_importance, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())",
                    (
                        chunk_uuid,
                        source_id,
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
                cur.execute("UPDATE ingestion.pdf_chunks SET enrichment_status = 'done', enriched_question_id = %s WHERE chunk_id = %s", (chunk_uuid, chunk_id))

            # mark job completed
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


if __name__ == "__main__":
    run_loop()
