from __future__ import annotations

import hashlib
import json
import re
import os
import socket
import time
import uuid
from collections import defaultdict
from typing import Optional

from jsonschema import ValidationError, validate

from ..clients.llm_client import get_gemini_client
from ..core.contracts import PYQ_EXTRACTION_JSON_SCHEMA, PYQ_EXTRACTION_PROMPT, TEXTBOOK_PARSING_JSON_SCHEMA, TEXTBOOK_PARSING_PROMPT
from ..core.pipeline import _normalize_question_text, _normalize_question_type
from ..db.db import connect


WORKER_NAME = f"llm-worker-{socket.gethostname()}"
DEFAULT_CLAIM_BATCH_SIZE = int(os.getenv("GOOGLE_GENAI_WORKER_CLAIM_BATCH_SIZE", "20"))
DEFAULT_REQUEST_BATCH_SIZE = int(os.getenv("GOOGLE_GENAI_WORKER_REQUEST_BATCH_SIZE", "5"))
DEFAULT_REQUEST_BATCH_CHARS = int(os.getenv("GOOGLE_GENAI_WORKER_REQUEST_BATCH_CHARS", "12000"))

TEXTBOOK_BATCH_PROMPT = """You are a semantic educational parser.

Analyze each textbook chunk independently and return STRICT JSON only.

Your tasks for each chunk:
1. Identify chapter and section.
2. Extract the main concept.
3. Extract prerequisite concepts.
4. Extract important formulas.
5. Extract key definitions.
6. Estimate exam relevance.
7. Estimate conceptual importance.
8. Generate semantic tags.
9. Detect commonly examined concepts.

Return this output schema:
{
  "chunks": [
    {
      "candidate_id": "",
      "chapter": "",
      "section": "",
      "main_concept": "",
      "prerequisites": [],
      "formulas": [],
      "definitions": [],
      "exam_relevance_score": 0.0,
      "conceptual_importance": 0.0,
      "commonly_examined_concepts": [],
      "semantic_tags": []
    }
  ]
}"""

TEXTBOOK_BATCH_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "chunks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "candidate_id": {"type": "string"},
                    "chapter": {"type": "string"},
                    "section": {"type": "string"},
                    "main_concept": {"type": "string"},
                    "prerequisites": {"type": "array", "items": {"type": "string"}},
                    "formulas": {"type": "array", "items": {"type": "string"}},
                    "definitions": {
                        "type": "array",
                        "items": {
                            "anyOf": [
                                {"type": "string"},
                                {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "term": {"type": "string"},
                                        "definition": {"type": "string"},
                                    },
                                    "required": ["term", "definition"],
                                },
                            ]
                        },
                    },
                    "exam_relevance_score": {"type": "number"},
                    "conceptual_importance": {"type": "number"},
                    "commonly_examined_concepts": {"type": "array", "items": {"type": "string"}},
                    "semantic_tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "candidate_id",
                    "chapter",
                    "section",
                    "main_concept",
                    "prerequisites",
                    "formulas",
                    "definitions",
                    "exam_relevance_score",
                    "conceptual_importance",
                    "commonly_examined_concepts",
                    "semantic_tags",
                ],
            },
        }
    },
    "required": ["chunks"],
}


def _normalize_difficulty(value: object) -> str:
    normalized = re.sub(r"[\s_\-]+", " ", str(value or "")).strip().lower()
    if normalized in ("easy", "low"):
        return "Easy"
    if normalized in ("medium", "intermediate", "moderate", "mid"):
        return "Medium"
    if normalized in ("hard", "difficult", "high"):
        return "Hard"
    return "Medium"


def _prompt_hash(model: str, prompt: str, text: str) -> str:
    h = hashlib.sha256()
    h.update((model or "").encode("utf-8"))
    h.update(b"::")
    h.update(prompt.encode("utf-8"))
    h.update(b"::")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def _load_chunk_records(conn, chunk_ids: list[str]) -> dict[str, dict]:
    if not chunk_ids:
        return {}

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pc.chunk_id, pc.chunk_text, pc.chunk_kind, pc.source_id, s.source_uri, pp.page_number
            FROM ingestion.pdf_chunks pc
            LEFT JOIN ingestion.pdf_pages pp ON pp.page_id = pc.page_id
            LEFT JOIN ingestion.sources s ON s.source_id = pc.source_id
            WHERE pc.chunk_id = ANY(%s)
            """,
            (chunk_ids,),
        )
        records = {}
        for chunk_id, chunk_text, chunk_kind, source_id, source_uri, page_number in cur.fetchall():
            records[chunk_id] = {
                "chunk_id": chunk_id,
                "chunk_text": chunk_text or "",
                "chunk_kind": chunk_kind or "",
                "source_id": source_id,
                "source_uri": source_uri,
                "page_number": page_number,
            }
        return records


def _split_into_batches(records: list[dict], max_count: int, max_chars: int) -> list[list[dict]]:
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_chars = 0

    for record in records:
        record_chars = len(record.get("chunk_text", ""))
        if current_batch and (len(current_batch) >= max_count or current_chars + record_chars > max_chars):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(record)
        current_chars += record_chars

    if current_batch:
        batches.append(current_batch)

    return batches


def _group_jobs(jobs: list[dict], chunk_records: dict[str, dict]) -> list[tuple[str, str, list[dict]]]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for job in jobs:
        record = chunk_records.get(job["chunk_id"])
        if not record:
            continue
        kind = (record.get("chunk_kind") or "").lower()
        grouped[(record["source_id"], kind)].append({**job, **record})

    ordered_groups: list[tuple[str, str, list[dict]]] = []
    for (source_id, kind), records in grouped.items():
        records.sort(key=lambda record: ((record.get("page_number") or 0), record.get("chunk_id") or ""))
        ordered_groups.append((source_id, kind, records))
    ordered_groups.sort(key=lambda item: (item[0], item[1]))
    return ordered_groups


def _build_pyq_batch_prompt(records: list[dict]) -> str:
    candidate_blocks = []
    for record in records:
        candidate_blocks.append(
            "\n".join(
                [
                    f"CANDIDATE_ID: {record['chunk_id']}",
                    f"PAGE_NUMBER: {record.get('page_number')}",
                    "QUESTION_NUMBER_HINT: None",
                    "TEXT:",
                    record.get("chunk_text", ""),
                ]
            )
        )

    return "\n\n".join(
        [
            PYQ_EXTRACTION_PROMPT,
            f"SOURCE_KIND: {records[0].get('chunk_kind', '') if records else ''}",
            f"SOURCE_URI: {records[0].get('source_uri', '') if records else ''}",
            "CANDIDATE_BLOCKS:",
            "\n\n---\n\n".join(candidate_blocks),
        ]
    )


def _build_textbook_batch_prompt(records: list[dict]) -> str:
    chunk_blocks = []
    for record in records:
        chunk_blocks.append(
            "\n".join(
                [
                    f"CANDIDATE_ID: {record['chunk_id']}",
                    f"PAGE_NUMBER: {record.get('page_number')}",
                    "TEXT:",
                    record.get("chunk_text", ""),
                ]
            )
        )

    return "\n\n".join(
        [
            TEXTBOOK_BATCH_PROMPT,
            "CHUNK_BLOCKS:",
            "\n\n---\n\n".join(chunk_blocks),
        ]
    )


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


def _normalize_textbook_item(item: dict) -> dict:
    return {
        "chapter": item.get("chapter", ""),
        "section": item.get("section", ""),
        "main_concept": item.get("main_concept", ""),
        "prerequisites": item.get("prerequisites", []),
        "formulas": item.get("formulas", []),
        "definitions": item.get("definitions", []),
        "exam_relevance_score": item.get("exam_relevance_score", 0.0),
        "conceptual_importance": item.get("conceptual_importance", 0.0),
        "commonly_examined_concepts": item.get("commonly_examined_concepts", []),
        "semantic_tags": item.get("semantic_tags", []),
    }


def _process_question_batch(conn, entries: list[dict]) -> None:
    if not entries:
        return

    prompt = _build_pyq_batch_prompt(entries)
    client = get_gemini_client()
    model_name = getattr(client, "model", None) or "sdk_client"
    cache_key = _prompt_hash(model_name, PYQ_EXTRACTION_PROMPT, prompt)

    with conn.cursor() as cur:
        cur.execute("SELECT response_json FROM ingestion.llm_cache WHERE cache_key = %s", (cache_key,))
        cached = cur.fetchone()
        if cached:
            response_json = cached[0]
        else:
            resp = client.infer(prompt, params={"max_tokens": 4096, "temperature": 0.0})
            raw_text = resp.get("text", "") if isinstance(resp, dict) else str(resp)
            response_json = json.loads(raw_text)
            cur.execute(
                "INSERT INTO ingestion.llm_cache (cache_key, model, response_json, created_at) VALUES (%s,%s,%s,NOW())",
                (cache_key, model_name, json.dumps(response_json)),
            )

        validate(instance=response_json, schema=PYQ_EXTRACTION_JSON_SCHEMA)
        questions_by_chunk = defaultdict(list)
        for question in response_json.get("questions", []):
            candidate_id = question.get("candidate_id")
            if not candidate_id:
                continue
            question["difficulty"] = _normalize_difficulty(question.get("difficulty"))
            question["question_type"] = _normalize_question_type(question.get("question_type", ""))
            questions_by_chunk[candidate_id].append(question)

        for entry in entries:
            chunk_questions = questions_by_chunk.get(entry["chunk_id"], [])
            chunk_response = {"questions": chunk_questions}
            validate(instance=chunk_response, schema=PYQ_EXTRACTION_JSON_SCHEMA)
            _store_raw_output(cur, chunk_id=entry["chunk_id"], model_name=model_name, prompt_hash=cache_key, response_json=chunk_response)

            inserted_question_id = None
            for question in chunk_questions:
                question_text = _normalize_question_text(entry["chunk_text"], question.get("question_text", ""))
                if not question_text:
                    continue
                question_id = uuid.uuid4().hex
                cur.execute(
                    "INSERT INTO exam.questions (question_id, source_id, source_uri, page_number, question_number, question_text, year, topic, subtopic, difficulty, question_type, concepts_json, prerequisites_json, semantic_tags_json, pattern_type, conceptual_depth, importance_score, confidence, raw_structured_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        question_id,
                        entry["source_id"],
                        entry["source_uri"],
                        entry["page_number"],
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
                    (question_id, entry["chunk_id"]),
                )

            if inserted_question_id is None:
                cur.execute(
                    "UPDATE ingestion.pdf_chunks SET enrichment_status = 'done', enriched_question_id = NULL WHERE chunk_id = %s",
                    (entry["chunk_id"],),
                )

        conn.commit()


def _process_textbook_batch(conn, entries: list[dict]) -> None:
    if not entries:
        return

    prompt = _build_textbook_batch_prompt(entries)
    client = get_gemini_client()
    model_name = getattr(client, "model", None) or "sdk_client"
    cache_key = _prompt_hash(model_name, TEXTBOOK_BATCH_PROMPT, prompt)

    with conn.cursor() as cur:
        cur.execute("SELECT response_json FROM ingestion.llm_cache WHERE cache_key = %s", (cache_key,))
        cached = cur.fetchone()
        if cached:
            response_json = cached[0]
        else:
            resp = client.infer(prompt, params={"max_tokens": 2048})
            raw_text = resp.get("text", "") if isinstance(resp, dict) else str(resp)
            response_json = json.loads(raw_text)
            cur.execute(
                "INSERT INTO ingestion.llm_cache (cache_key, model, response_json, created_at) VALUES (%s,%s,%s,NOW())",
                (cache_key, model_name, json.dumps(response_json)),
            )

        validate(instance=response_json, schema=TEXTBOOK_BATCH_JSON_SCHEMA)
        items_by_id = {item.get("chunk_id"): item for item in response_json.get("chunks", []) if item.get("chunk_id")}

        for entry in entries:
            item = items_by_id.get(entry["chunk_id"]) or {
                "chunk_id": entry["chunk_id"],
                "chapter": "",
                "section": "",
                "main_concept": "",
                "prerequisites": [],
                "formulas": [],
                "definitions": [],
                "exam_relevance_score": 0.0,
                "conceptual_importance": 0.0,
                "commonly_examined_concepts": [],
                "semantic_tags": [],
            }
            validate(instance={"chunks": [item]}, schema=TEXTBOOK_BATCH_JSON_SCHEMA)
            textbook_item = _normalize_textbook_item(item)
            _store_raw_output(cur, chunk_id=entry["chunk_id"], model_name=model_name, prompt_hash=cache_key, response_json={"chunk": item})

            chunk_uuid = uuid.uuid4().hex
            cur.execute(
                "INSERT INTO exam.textbook_chunks (chunk_id, source_id, chunk_text, chapter, section, main_concept, prerequisites_json, formulas_json, definitions_json, semantic_tags_json, exam_relevance_score, conceptual_importance, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())",
                (
                    chunk_uuid,
                    entry["source_id"],
                    entry["chunk_text"],
                    textbook_item["chapter"],
                    textbook_item["section"],
                    textbook_item["main_concept"],
                    json.dumps(textbook_item["prerequisites"]),
                    json.dumps(textbook_item["formulas"]),
                    json.dumps(textbook_item["definitions"]),
                    json.dumps(textbook_item["semantic_tags"]),
                    textbook_item["exam_relevance_score"],
                    textbook_item["conceptual_importance"],
                ),
            )
            cur.execute(
                "UPDATE ingestion.pdf_chunks SET enrichment_status = 'done', enriched_question_id = %s WHERE chunk_id = %s",
                (chunk_uuid, entry["chunk_id"]),
            )

        conn.commit()


def process_job_batch(conn, jobs: list[dict]) -> None:
    if not jobs:
        return

    chunk_ids = [job["chunk_id"] for job in jobs]
    chunk_records = _load_chunk_records(conn, chunk_ids)
    grouped = _group_jobs(jobs, chunk_records)

    for _source_id, kind, records in grouped:
        for batch in _split_into_batches(records, DEFAULT_REQUEST_BATCH_SIZE, DEFAULT_REQUEST_BATCH_CHARS):
            batch_job_ids = [record["job_id"] for record in batch]
            try:
                if kind in ("question", "pyq", "mcq", "nq"):
                    _process_question_batch(conn, batch)
                else:
                    _process_textbook_batch(conn, batch)
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE ingestion.job_queue SET status = 'completed', finished_at = NOW() WHERE job_id = ANY(%s)",
                        (batch_job_ids,),
                    )
                    conn.commit()
            except Exception as exc:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE ingestion.job_queue SET status = 'failed', last_error = %s, finished_at = NOW() WHERE job_id = ANY(%s)",
                        (str(exc), batch_job_ids),
                    )
                    cur.execute("UPDATE ingestion.pdf_chunks SET enrichment_status = 'error' WHERE chunk_id = ANY(%s)", ([record["chunk_id"] for record in batch],))
                    conn.commit()
                raise


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
                    question["difficulty"] = _normalize_difficulty(question.get("difficulty"))
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
                jobs = claim_jobs(conn, batch_size=DEFAULT_CLAIM_BATCH_SIZE)
                if not jobs:
                    time.sleep(poll_interval)
                    continue
                process_job_batch(conn, jobs)
        except KeyboardInterrupt:
            print("llm-worker stopping")
            return
        except Exception as exc:
            print("llm-worker error:", exc)
            time.sleep(2)
