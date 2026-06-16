from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from pathlib import Path

import fitz
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential


MAX_PAGES_PER_REQUEST = 2


def get_document_intelligence_client() -> DocumentIntelligenceClient:
    endpoint = os.getenv("DOCUMENTINTELLIGENCE_ENDPOINT") or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    api_key = os.getenv("DOCUMENTINTELLIGENCE_API_KEY") or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_API_KEY")
    if not endpoint:
        raise RuntimeError("DOCUMENTINTELLIGENCE_ENDPOINT is required; set it in .env")
    if not api_key:
        raise RuntimeError("DOCUMENTINTELLIGENCE_API_KEY is required; set it in .env")
    return DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(api_key))


def _analyze_pdf_batch(client: DocumentIntelligenceClient, batch_path: Path):
    with batch_path.open("rb") as stream:
        poller = client.begin_analyze_document("prebuilt-layout", body=stream)
        return poller.result()


def _copy_regions(regions, page_offset: int):
    copied = []
    for region in regions or []:
        copied.append(SimpleNamespace(page_number=getattr(region, "page_number", 0) + page_offset))
    return copied


def _copy_spans(spans):
    copied = []
    for span in spans or []:
        copied.append(SimpleNamespace(offset=getattr(span, "offset", 0), length=getattr(span, "length", 0)))
    return copied


def _merge_azure_results(results):
    merged = SimpleNamespace(pages=[], paragraphs=[])
    for page_offset, result in results:
        for page in getattr(result, "pages", None) or []:
            merged.pages.append(
                SimpleNamespace(
                    page_number=getattr(page, "page_number", 0) + page_offset,
                    lines=getattr(page, "lines", None) or [],
                    words=getattr(page, "words", None) or [],
                )
            )
        for paragraph in getattr(result, "paragraphs", None) or []:
            merged.paragraphs.append(
                SimpleNamespace(
                    content=getattr(paragraph, "content", ""),
                    bounding_regions=_copy_regions(getattr(paragraph, "bounding_regions", None), page_offset),
                    spans=_copy_spans(getattr(paragraph, "spans", None)),
                )
            )
    return merged


def _analyze_pdf_range(client: DocumentIntelligenceClient, doc: fitz.Document, start_page: int, end_page: int):
    with tempfile.NamedTemporaryFile(suffix=f".pages{start_page + 1}-{end_page}.pdf", delete=False) as tmp:
        batch_path = Path(tmp.name)

    batch_doc = fitz.open()
    try:
        batch_doc.insert_pdf(doc, from_page=start_page, to_page=end_page - 1)
        batch_doc.save(str(batch_path))
    finally:
        batch_doc.close()

    try:
        batch_size = batch_path.stat().st_size
        if batch_size > int(os.getenv("DOCUMENTINTELLIGENCE_MAX_BYTES", "4000000")) and end_page - start_page > 1:
            mid_page = start_page + max(1, (end_page - start_page) // 2)
            left = _analyze_pdf_range(client, doc, start_page, mid_page)
            right = _analyze_pdf_range(client, doc, mid_page, end_page)
            return left + right

        return [(start_page, _analyze_pdf_batch(client, batch_path))]
    finally:
        try:
            batch_path.unlink()
        except Exception:
            pass


def analyze_pdf(source_uri: str):
    batches = analyze_pdf_batches(source_uri)
    return _merge_azure_results(batches)


def analyze_pdf_batches(source_uri: str):
    path = Path(source_uri)
    if not path.exists():
        raise RuntimeError(f"source PDF not found: {source_uri}")

    client = get_document_intelligence_client()

    with fitz.open(str(path)) as doc:
        start_page = 0
        batch_results = []
        while start_page < doc.page_count:
            end_page = min(start_page + MAX_PAGES_PER_REQUEST, doc.page_count)
            batch_result = _analyze_pdf_range(client, doc, start_page, end_page)
            batch_results.extend(batch_result)
            start_page = end_page

        return batch_results