from __future__ import annotations

import json
import os
import re
import uuid
import tempfile
from pathlib import Path
from typing import Dict, List

import fitz

from ..clients.document_intelligence import analyze_pdf, analyze_pdf_batches
from ..db.db import connect


QUESTION_START_RE = re.compile(r"(?m)^\s*(?:Q(?:uestion)?\.?\s*)?(?P<number>\d{1,3})[\).:\-]\s+")
QUESTION_START_AT_LINE_RE = re.compile(r"^\s*(?:Q(?:uestion)?\.?\s*)?(?P<number>\d{1,3})[\).:\-]\s+")
OPTION_LINE_RE = re.compile(r"(?m)^\s*[A-Da-d][\).:\-]\s+")
INLINE_OPTION_RE = re.compile(r"(?:^|\s)[A-Da-d][\).:\-]\s+")
OPTION_BLOCK_RE = re.compile(r"(?m)^(?:\s*[A-Da-d][\).:\-]\s+|.*(?:\b[A-Da-d][\).:\-]\s+).*)$")
MAX_BATCH_CHARS = 12000
MAX_BATCH_CANDIDATES = 16
QUESTION_TYPE_ALIASES = {
    "multiple choice": "MCQ",
    "multiple-choice": "MCQ",
    "mcq": "MCQ",
    "objective": "MCQ",
    "nat": "NAT",
    "msq": "MSQ",
    "numerical": "Numerical",
    "theory": "Theory",
}


def _table_exists(conn, schema: str, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
            (schema, table),
        )
        return cur.fetchone() is not None


def _use_azure_ocr() -> bool:
    return os.getenv("DOCLING_USE_AZURE_OCR", "1").lower() in ("1", "true", "yes")


def _docling_markdown_for_page(page_path: Path) -> str:
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(page_path)
    if not result or not result.document:
        return ""
    return result.document.export_to_markdown()


def _load_docling_markdown(source_uri: str) -> str:
    # Optionally use Azure Document Intelligence for OCR, then hand the
    # Azure-derived markdown to Docling for normalization when supported.
    if _use_azure_ocr():
        azure_result = analyze_pdf(source_uri)
        # Build a lightweight markdown from Azure paragraphs/pages.
        page_texts = _page_text_by_number(azure_result)
        parts: List[str] = []
        for pnum in sorted(page_texts.keys()):
            parts.append(f"## Page {pnum}")
            parts.append(page_texts[pnum])
        azure_markdown = "\n\n".join(parts)

        from docling.document_converter import DocumentConverter

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tmp:
            tmp.write(azure_markdown)
            tmp_path = Path(tmp.name)
        try:
            converter = DocumentConverter()
            result = converter.convert(tmp_path)
            return result.document.export_to_markdown()
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass

    source_path = Path(source_uri)
    markdown_parts: List[str] = []

    with fitz.open(str(source_path)) as doc:
        for page_index in range(doc.page_count):
            with tempfile.NamedTemporaryFile(suffix=f".page{page_index + 1}.png", delete=False) as tmp:
                page_path = Path(tmp.name)

            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pix.save(str(page_path))

            try:
                page_markdown = _docling_markdown_for_page(page_path)
            except Exception:
                page_markdown = ""
            finally:
                try:
                    page_path.unlink()
                except Exception:
                    pass

            if not page_markdown.strip():
                try:
                    page_markdown = doc.load_page(page_index).get_text("text") or ""
                except Exception:
                    page_markdown = ""

            if page_markdown.strip():
                markdown_parts.append(f"## Page {page_index + 1}\n\n{page_markdown.strip()}")

    return "\n\n".join(markdown_parts)


def _local_page_text_by_number(source_uri: str) -> Dict[int, str]:
    page_texts: Dict[int, str] = {}
    source_path = Path(source_uri)

    with fitz.open(str(source_path)) as doc:
        for page_index in range(doc.page_count):
            with tempfile.NamedTemporaryFile(suffix=f".page{page_index + 1}.png", delete=False) as tmp:
                page_path = Path(tmp.name)

            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pix.save(str(page_path))

            try:
                page_markdown = _docling_markdown_for_page(page_path)
            except Exception:
                page_markdown = ""
            finally:
                try:
                    page_path.unlink()
                except Exception:
                    pass

            # Always include the page in the returned mapping. Prefer
            # Docling-normalized markdown when available; otherwise fall
            # back to the raw text extractor so every page is represented
            # (possibly as an empty string) and will be persisted to the DB.
            if page_markdown and page_markdown.strip():
                page_texts[page_index + 1] = page_markdown.strip()
            else:
                try:
                    raw = doc.load_page(page_index).get_text("text") or ""
                except Exception:
                    raw = ""
                page_texts[page_index + 1] = raw.strip()

    return page_texts


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


def _offset_azure_result(azure_result, page_offset: int):
    pages = []
    for page in getattr(azure_result, "pages", None) or []:
        pages.append(
            type(
                "Page",
                (),
                {
                    "page_number": getattr(page, "page_number", 0) + page_offset,
                    "lines": getattr(page, "lines", None) or [],
                    "words": getattr(page, "words", None) or [],
                },
            )
        )

    paragraphs = []
    for paragraph in getattr(azure_result, "paragraphs", None) or []:
        regions = []
        for region in getattr(paragraph, "bounding_regions", None) or []:
            regions.append(
                type(
                    "Region",
                    (),
                    {"page_number": getattr(region, "page_number", 0) + page_offset},
                )
            )
        paragraphs.append(
            type(
                "Paragraph",
                (),
                {
                    "content": getattr(paragraph, "content", "") or "",
                    "bounding_regions": regions,
                    "spans": getattr(paragraph, "spans", None) or [],
                },
            )
        )

    return type("AzureBatchResult", (), {"pages": pages, "paragraphs": paragraphs})()


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


def _looks_like_option_block(text: str) -> bool:
    option_hits = len(OPTION_LINE_RE.findall(text)) + len(INLINE_OPTION_RE.findall(text))
    words = text.split()
    return option_hits >= 2 or (option_hits >= 1 and len(words) <= 20)


def _looks_like_stem_with_following_options(text: str, next_text: str | None) -> bool:
    if not text or _looks_like_option_block(text):
        return False
    if next_text and _looks_like_option_block(next_text):
        return len(text.split()) >= 5 and len(text) >= 30
    return _looks_like_question(text)


def _question_stem_from_candidate(text: str) -> str:
    inline_match = INLINE_OPTION_RE.search(text)
    if inline_match and inline_match.start() > 0:
        stem = text[: inline_match.start()].strip()
        stem = re.sub(r"\s+", " ", stem).strip(" :-")
        if stem:
            return stem

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    stem_lines: List[str] = []
    for line in lines:
        if OPTION_LINE_RE.match(line):
            break
        stem_lines.append(line)
    stem = re.sub(r"\s+", " ", " ".join(stem_lines)).strip()
    return stem or re.sub(r"\s+", " ", text).strip()


def _normalize_question_text(candidate_text: str, extracted_text: str) -> str:
    extracted_clean = re.sub(r"\s+", " ", (extracted_text or "")).strip()
    candidate_clean = re.sub(r"\s+", " ", (candidate_text or "")).strip()

    if not extracted_clean:
        return _question_stem_from_candidate(candidate_text)

    extracted_option_count = len(OPTION_LINE_RE.findall(extracted_text or "")) + len(INLINE_OPTION_RE.findall(extracted_text or ""))
    candidate_option_count = len(OPTION_LINE_RE.findall(candidate_text or "")) + len(INLINE_OPTION_RE.findall(candidate_text or ""))
    extracted_looks_like_options = extracted_option_count >= 2 or (
        extracted_option_count >= 1 and len(extracted_clean) < 120 and not re.search(r"[?.]", extracted_clean)
    )

    # If the extracted text appears to contain option lines, prefer the
    # extracted text (it preserves the option block). If the candidate
    # contains options and the extractor returned the full candidate, keep
    # the candidate (to preserve formatting produced by Docling).
    if extracted_looks_like_options:
        return extracted_clean

    if candidate_option_count >= 2 and extracted_clean == candidate_clean:
        return candidate_clean

    return extracted_clean


def _normalize_question_type(value: str) -> str:
    normalized = re.sub(r"[\s_\-]+", " ", (value or "")).strip().lower()

    # Prefer explicit aliases first
    if normalized in QUESTION_TYPE_ALIASES:
        return QUESTION_TYPE_ALIASES[normalized]

    # Tokenize on common separators
    tokens = re.split(r"[\s/,_\\]+", normalized)

    # Direct canonical matches
    for t in tokens:
        if t in ("mcq", "multiple", "multiplechoice", "multiplechoicequestion", "multiple choice"):
            return "MCQ"
        if t in ("msq", "multiple-select", "multipleselect", "multiple select"):
            return "MSQ"
        if t in ("nat", "short", "shortanswer", "short answer"):
            return "NAT"
        if t in ("numerical", "num", "calculation", "numer", "numerics"):
            return "Numerical"
        if t in ("theory", "conceptual", "essay"):
            return "Theory"

    # Substring heuristics for compound labels (e.g. "Numerical/Design")
    if "numer" in normalized or "calcu" in normalized or "design" in normalized:
        return "Numerical"
    if "multiple" in normalized and "choice" in normalized:
        return "MCQ"
    if "short" in normalized or "nat" in normalized:
        return "NAT"
    if "select" in normalized and "multiple" in normalized:
        return "MSQ"
    if "theory" in normalized or "concept" in normalized:
        return "Theory"

    # As a final fallback, map any value containing one of the canonical words
    if any(k in normalized for k in ["mcq", "nat", "msq", "numer", "theory"]):
        if "mcq" in normalized or "multiple" in normalized:
            return "MCQ"
        if "msq" in normalized or "select" in normalized:
            return "MSQ"
        if "nat" in normalized or "short" in normalized:
            return "NAT"
        if "numer" in normalized:
            return "Numerical"
        if "theory" in normalized:
            return "Theory"

    # Never return an unknown label — default to Theory to keep schema strict.
    return "Theory"


def _candidate_blocks_for_page(page_number: int, text: str) -> List[dict]:
    blocks = []
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", text) if paragraph.strip()]
    index = 0
    block_index = 1
    while index < len(paragraphs):
        paragraph = paragraphs[index]
        next_paragraph = paragraphs[index + 1] if index + 1 < len(paragraphs) else None

        if _looks_like_stem_with_following_options(paragraph, next_paragraph):
            block_parts = [paragraph]
            lookahead = index + 1
            while lookahead < len(paragraphs) and _looks_like_option_block(paragraphs[lookahead]):
                block_parts.append(paragraphs[lookahead])
                lookahead += 1

            block_text = re.sub(r"\s+", " ", "\n\n".join(block_parts)).strip()
            if block_text:
                blocks.append(
                    {
                        "candidate_id": f"p{page_number}-b{block_index}",
                        "page_number": page_number,
                        "question_number_hint": None,
                        "text": block_text,
                    }
                )
                block_index += 1
            index = lookahead
            continue

        index += 1
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


def _enqueue_job(cur, *, chunk_id: str, stage: str, source_id: str) -> str:
    job_id = uuid.uuid4().hex
    cur.execute(
        "INSERT INTO ingestion.job_queue (job_id, chunk_id, stage, status, payload, created_at) VALUES (%s,%s,%s,%s,%s,NOW())",
        (job_id, chunk_id, stage, "pending", json.dumps({"source_id": source_id})),
    )
    return job_id


def _build_source_chunks(source_kind: str, page_texts: Dict[int, str], docling_markdown: str) -> List[dict]:
    normalized_kind = (source_kind or "").strip().lower()
    chunks: List[dict] = []

    if normalized_kind in {"pyq", "question", "mcq", "nq"}:
        candidates = _extract_candidate_blocks(page_texts, docling_markdown)
        if not candidates:
            for index, block in enumerate(_split_numbered_blocks(docling_markdown), start=1):
                block_text = re.sub(r"\s+", " ", block["text"]).strip()
                if not block_text or not _looks_like_question(block_text):
                    continue
                candidates.append(
                    {
                        "candidate_id": f"docling-b{index}",
                        "page_number": None,
                        "question_number_hint": block["question_number_hint"],
                        "text": block_text,
                    }
                )

        for candidate in candidates:
            chunks.append(
                {
                    "page_number": candidate.get("page_number"),
                    "chunk_text": candidate["text"],
                    "chunk_kind": "question",
                }
            )
        return chunks

    for page_number, page_text in sorted(page_texts.items()):
        cleaned = re.sub(r"\s+", " ", page_text).strip()
        if cleaned:
            chunks.append({"page_number": page_number, "chunk_text": cleaned, "chunk_kind": "textbook"})
    return chunks


def _existing_page_numbers(conn, source_id: str) -> set[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT page_number FROM ingestion.pdf_pages WHERE source_id = %s", (source_id,))
        return {row[0] for row in cur.fetchall()}


def _commit_page_batch(
    conn,
    *,
    source_id: str,
    source_kind: str,
    filename: str,
    pages: List[object],
    page_texts: Dict[int, str],
    existing_page_numbers: set[int],
) -> int:
    inserted_chunks = 0
    with conn.cursor() as cur:
        for page in pages:
            page_number = getattr(page, "page_number", None)
            if page_number is None or page_number in existing_page_numbers:
                continue

            page_text = (page_texts.get(page_number) or "").strip()
            page_id = uuid.uuid4().hex
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

            page_chunks = _build_source_chunks(source_kind, {page_number: page_text}, f"## Page {page_number}\n\n{page_text}".strip())
            for index, chunk in enumerate(page_chunks):
                chunk_id = uuid.uuid4().hex
                cur.execute(
                    "INSERT INTO ingestion.pdf_chunks (chunk_id, page_id, source_id, chunk_order, chunk_text, chunk_kind, extracted_entities_json, enrichment_status, enriched_question_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        chunk_id,
                        page_id,
                        source_id,
                        index,
                        chunk["chunk_text"],
                        chunk["chunk_kind"],
                        json.dumps({"source_kind": source_kind, "page_number": page_number}),
                        "pending",
                        None,
                    ),
                )
                _enqueue_job(cur, chunk_id=chunk_id, stage="llm", source_id=source_id)
                _enqueue_job(cur, chunk_id=chunk_id, stage="embed", source_id=source_id)
                inserted_chunks += 1

            existing_page_numbers.add(page_number)

        conn.commit()

    return inserted_chunks


def _process_source(source_id: str, *, rebuild: bool = False) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='ingestion' AND table_name='sources' AND column_name IN ('source_kind','source_type','filename','source_uri')"
            )
            existing = {r[0] for r in cur.fetchall()}

            if 'source_kind' in existing and 'filename' in existing:
                cur.execute(
                    "SELECT source_uri, source_kind, filename FROM ingestion.sources WHERE source_id = %s",
                    (source_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError(f"source not found: {source_id}")
                source_uri, source_kind, filename = row
            elif 'source_type' in existing:
                cur.execute(
                    "SELECT source_uri, source_type, NULL AS filename FROM ingestion.sources WHERE source_id = %s",
                    (source_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError(f"source not found: {source_id}")
                source_uri, source_kind, filename = row
            else:
                cur.execute(
                    "SELECT source_uri, NULL AS source_kind, NULL AS filename FROM ingestion.sources WHERE source_id = %s",
                    (source_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError(f"source not found: {source_id}")
                source_uri, source_kind, filename = row

            if not filename:
                try:
                    from pathlib import Path

                    filename = Path(source_uri).name
                except Exception:
                    filename = source_uri

    with connect() as conn:
        existing_page_numbers = _existing_page_numbers(conn, source_id)

    inserted_chunks = 0
    if _use_azure_ocr():
        for start_page, batch_result in analyze_pdf_batches(source_uri):
            offset_result = _offset_azure_result(batch_result, start_page)
            page_texts = _page_text_by_number(offset_result)
            pages = list(getattr(offset_result, "pages", None) or [])
            with connect() as conn:
                inserted_chunks += _commit_page_batch(
                    conn,
                    source_id=source_id,
                    source_kind=source_kind,
                    filename=filename,
                    pages=pages,
                    page_texts=page_texts,
                    existing_page_numbers=existing_page_numbers,
                )
    else:
        page_texts = _local_page_text_by_number(source_uri)
        pages = [type("Page", (), {"page_number": page_number, "lines": [], "words": []}) for page_number in sorted(page_texts.keys())]
        with connect() as conn:
            inserted_chunks += _commit_page_batch(
                conn,
                source_id=source_id,
                source_kind=source_kind,
                filename=filename,
                pages=pages,
                page_texts=page_texts,
                existing_page_numbers=existing_page_numbers,
            )

    return {
        "source_id": source_id,
        "source_uri": source_uri,
        "chunks": inserted_chunks,
        "jobs_enqueued": inserted_chunks * 2,
        "pipeline": "azure_ocr -> docling_chunking -> llm_worker/embed_worker",
    }