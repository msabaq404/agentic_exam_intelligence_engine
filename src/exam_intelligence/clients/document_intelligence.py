from __future__ import annotations

import os
from pathlib import Path

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential


def get_document_intelligence_client() -> DocumentIntelligenceClient:
    endpoint = os.getenv("DOCUMENTINTELLIGENCE_ENDPOINT") or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    api_key = os.getenv("DOCUMENTINTELLIGENCE_API_KEY") or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_API_KEY")
    if not endpoint:
        raise RuntimeError("DOCUMENTINTELLIGENCE_ENDPOINT is required; set it in .env")
    if not api_key:
        raise RuntimeError("DOCUMENTINTELLIGENCE_API_KEY is required; set it in .env")
    return DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(api_key))


def analyze_pdf(source_uri: str):
    path = Path(source_uri)
    if not path.exists():
        raise RuntimeError(f"source PDF not found: {source_uri}")

    client = get_document_intelligence_client()
    with path.open("rb") as stream:
        poller = client.begin_analyze_document("prebuilt-layout", body=stream)
        return poller.result()