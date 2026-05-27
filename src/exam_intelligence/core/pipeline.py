from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Dict, List

from jsonschema import ValidationError, validate

from ..clients.document_intelligence import analyze_pdf
from ..clients.embeddings import embed_text
from ..clients.llm_client import get_gemini_client
from ..core.contracts import PYQ_EXTRACTION_JSON_SCHEMA, PYQ_EXTRACTION_PROMPT
from ..db.db import connect


QUESTION_START_RE = re.compile(r"(?m)^\s*(?:Q(?:uestion)?\.?\s*)?(?P<number>\d{1,3})[\).:\-]\s+")
QUESTION_START_AT_LINE_RE = re.compile(r"^\s*(?:Q(?:uestion)?\.?\s*)?(?P<number>\d{1,3})[\).:\-]\s+")
MAX_BATCH_CHARS = 12000
MAX_BATCH_CANDIDATES = 16


def _load_docling_markdown(source_uri: str) -> str:
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(Path(source_uri))
    return result.document.export_to_markdown()


def _page_text_by_number(azure_result) -> Dict[int, str]:
    page_texts: Dict[int, str] = {}
    paragraphs = getattr(azure_result, "paragraphs", None) or []
    for page in getattr(azure_result, "pages", None) or []:
        page_number = getattr(page, "page_number", None)
        if page_number is None:
            continue
        items = []
        for paragraph in paragraphs:
            regions = getattr(paragraph, "bounding_regions", None) or []
            if regions and regions[0].page_number == page_number:
                content = (getattr(paragraph, "content", "") or "").strip()
                if content:
                    spans = getattr(paragraph, "spans", None) or []
                    offset = min((getattr(span, "offset", 0) for span in spans), default=0)
                    items.append((offset, content))
        items.sort(key=lambda item: item[0])
        if items:
            page_texts[page_number] = "\n\n".join(text for _, text in items)
        else:
            lines = [getattr(line, "content", "") or "" for line in getattr(page, "lines", None) or []]
            page_texts[page_number] = "\n".join(line.strip() for line in lines if line.strip())
    return page_texts


def _split_numbered_blocks(text: str) -> List[dict]:
    matches = list(QUESTION_START_RE.finditer(text))
    blocks: List[dict] = []
    if matches:
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            chunk = text[start:end].strip()
            if chunk:
                blocks.append({"question_number_hint": int(match.group("number")), "text": chunk})
        return blocks

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", text) if paragraph.strip()]
    for paragraph in paragraphs:
        blocks.append({"question_number_hint": None, "text": paragraph})
    return blocks


def _looks_like_question(text: str) -> bool:
    score = 0
    if QUESTION_START_AT_LINE_RE.match(text):
        score += 3
    if "?" in text:
        score += 1
    if re.search(r"(?m)^\s*[A-Da-d][\).]\s+", text):
        score += 2
    if len(text.split()) >= 8:
        score += 1
    if len(text) >= 40:
        score += 1
    return score >= 3


def _candidate_blocks_for_page(page_number: int, text: str) -> List[dict]:
    blocks = []
    for index, block in enumerate(_split_numbered_blocks(text), start=1):
        block_text = re.sub(r"\s+", " ", block["text"]).strip()
        if not block_text or not _looks_like_question(block_text):
            continue
        blocks.append(
            {
                "candidate_id": f"p{page_number}-b{index}",
                "page_number": page_number,
                "question_number_hint": block["question_number_hint"],
                "text": block_text,
            }
        )
    return blocks


def _extract_candidate_blocks(page_texts: Dict[int, str], docling_markdown: str) -> List[dict]:
    candidates: List[dict] = []
    seen_texts = set()

    for page_number, page_text in sorted(page_texts.items()):
        for block in _candidate_blocks_for_page(page_number, page_text):
            key = (block["page_number"], block["text"])
            if key in seen_texts:
                continue
            seen_texts.add(key)
            candidates.append(block)

    if not candidates:
        for index, block in enumerate(_split_numbered_blocks(docling_markdown), start=1):
            block_text = re.sub(r"\s+", " ", block["text"]).strip()
            if not block_text or not _looks_like_question(block_text):
                continue
            key = (0, block_text)
            if key in seen_texts:
                continue
            seen_texts.add(key)
            candidates.append(
                {
                    "candidate_id": f"docling-b{index}",
                    "page_number": None,
                    "question_number_hint": block["question_number_hint"],
                    "text": block_text,
                }
            )

    return candidates


def _batch_candidates(candidates: List[dict]) -> List[List[dict]]:
    batches: List[List[dict]] = []
    current_batch: List[dict] = []
    current_chars = 0

    for candidate in candidates:
        candidate_chars = len(candidate["text"])
        if current_batch and (
            len(current_batch) >= MAX_BATCH_CANDIDATES or current_chars + candidate_chars > MAX_BATCH_CHARS
        ):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(candidate)
        current_chars += candidate_chars

    if current_batch:
        batches.append(current_batch)

    return batches


def _build_extraction_prompt(source_kind: str, source_uri: str, candidates: List[dict]) -> str:
    candidate_lines = []
    for candidate in candidates:
        candidate_lines.append(
            "\n".join(
                [
                    f"CANDIDATE_ID: {candidate['candidate_id']}",
                    f"PAGE_NUMBER: {candidate['page_number']}",
                    f"QUESTION_NUMBER_HINT: {candidate['question_number_hint']}",
                    "TEXT:",
                    candidate["text"],
                ]
            )
        )

    return (
        f"{PYQ_EXTRACTION_PROMPT}\n\n"
        f"SOURCE_KIND: {source_kind}\n"
        f"SOURCE_URI: {source_uri}\n\n"
        "CANDIDATE_BLOCKS:\n"
        + "\n\n---\n\n".join(candidate_lines)
    )


def _extract_pyq_rows(source_kind: str, source_uri: str, page_texts: Dict[int, str]) -> List[dict]:
    docling_markdown = _load_docling_markdown(source_uri)
    candidates = _extract_candidate_blocks(page_texts, docling_markdown)
    if not candidates:
        return []

    client = get_gemini_client()
    all_questions: List[dict] = []

    for batch in _batch_candidates(candidates):
        prompt = _build_extraction_prompt(source_kind, source_uri, batch)
        response = client.infer(prompt, params={"max_tokens": 1400, "temperature": 0.0})
        raw_text = response.get("text", "") if isinstance(response, dict) else str(response)
        parsed = json.loads(raw_text)
        validate(instance=parsed, schema=PYQ_EXTRACTION_JSON_SCHEMA)
        all_questions.extend(parsed["questions"])

    return all_questions


def _insert_question_rows(conn, source_id: str, source_uri: str, page_id_by_number: Dict[int, str], questions: List[dict]) -> dict:
    inserted = 0
    with conn.cursor() as cur:
        for question in questions:
            question_id = uuid.uuid4().hex
            question_text = (question.get("question_text") or "").strip()
            if not question_text:
                continue

            page_number = question.get("page_number")
            chunk_id = uuid.uuid4().hex
            page_id = page_id_by_number.get(page_number) if page_number is not None else None
            if page_id is None and page_id_by_number:
                page_id = next(iter(page_id_by_number.values()))

            cur.execute(
                "INSERT INTO ingestion.pdf_chunks (chunk_id, page_id, source_id, chunk_order, chunk_text, chunk_kind, extracted_entities_json, enrichment_status, enriched_question_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    chunk_id,
                    page_id,
                    source_id,
                    inserted,
                    question_text,
                    "question",
                    json.dumps(question),
                    "embedded",
                    question_id,
                ),
            )

            cur.execute(
                "INSERT INTO exam.questions (question_id, source_id, source_uri, page_number, question_number, question_text, exam_year, topic, subtopic, difficulty, question_type, concepts_json, prerequisites_json, semantic_tags_json, pattern_type, conceptual_depth, importance_score, confidence, raw_structured_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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

            vector = embed_text(question_text)
            cur.execute(
                "INSERT INTO ingestion.embeddings (embedding_id, chunk_id, model, vector, score, created_at) VALUES (%s,%s,%s,%s,%s,NOW())",
                (
                    uuid.uuid4().hex,
                    chunk_id,
                    "sentence-transformers/all-MiniLM-L6-v2",
                    json.dumps(vector),
                    None,
                ),
            )
            inserted += 1

    return {"questions": inserted}


def process_source(source_id: str, *, rebuild: bool = True) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_uri, source_kind, filename FROM ingestion.sources WHERE source_id = %s",
                (source_id,),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"source not found: {source_id}")
            source_uri, source_kind, filename = row

    azure_result = analyze_pdf(source_uri)
    page_texts = _page_text_by_number(azure_result)

    if rebuild:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ingestion.embeddings WHERE chunk_id IN (SELECT chunk_id FROM ingestion.pdf_chunks WHERE source_id = %s)", (source_id,))
                cur.execute("DELETE FROM exam.questions WHERE source_id = %s", (source_id,))
                cur.execute("DELETE FROM ingestion.pdf_chunks WHERE source_id = %s", (source_id,))
                cur.execute("DELETE FROM ingestion.ocr_artifacts WHERE page_id IN (SELECT page_id FROM ingestion.pdf_pages WHERE source_id = %s)", (source_id,))
                cur.execute("DELETE FROM ingestion.pdf_pages WHERE source_id = %s", (source_id,))
                conn.commit()

    page_id_by_number: Dict[int, str] = {}
    with connect() as conn:
        with conn.cursor() as cur:
            for page in getattr(azure_result, "pages", None) or []:
                page_number = getattr(page, "page_number", None)
                if page_number is None:
                    continue
                page_text = page_texts.get(page_number, "")
                page_id = uuid.uuid4().hex
                page_id_by_number[page_number] = page_id
                cur.execute(
                    "INSERT INTO ingestion.pdf_pages (page_id, source_id, page_number, page_text, ocr_confidence) VALUES (%s,%s,%s,%s,%s)",
                    (page_id, source_id, page_number, page_text, None),
                )
                layout_json = {
                    "source_kind": source_kind,
                    "filename": filename,
                    "page_number": page_number,
                    "azure_line_count": len(getattr(page, "lines", None) or []),
                    "azure_word_count": len(getattr(page, "words", None) or []),
                    "docling_normalized": True,
                }
                cur.execute(
                    "INSERT INTO ingestion.ocr_artifacts (artifact_id, page_id, ocr_text, ocr_confidence, layout_json) VALUES (%s,%s,%s,%s,%s)",
                    (uuid.uuid4().hex, page_id, page_text, None, json.dumps(layout_json)),
                )
            conn.commit()

    questions = _extract_pyq_rows(source_kind, source_uri, page_texts)

    with connect() as conn:
        summary = _insert_question_rows(conn, source_id, source_uri, page_id_by_number, questions)
        conn.commit()

    return {
        "source_id": source_id,
        "source_uri": source_uri,
        "questions": summary["questions"],
        "embeddings": summary["questions"],
        "pipeline": "azure_ocr -> docling_candidate_split -> gemini_micro_batch -> embeddings",
    }