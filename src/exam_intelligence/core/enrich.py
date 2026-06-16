from __future__ import annotations

import json
import uuid
from typing import Dict, Any

from jsonschema import validate, ValidationError

from .contracts import (
    PYQ_ANALYSIS_PROMPT,
    PYQ_ANALYSIS_JSON_SCHEMA,
    TEXTBOOK_PARSING_PROMPT,
    TEXTBOOK_PARSING_JSON_SCHEMA,
)


from ..clients.llm_client import get_gemini_client


def call_llm(prompt: str, text: str) -> str:
    """Call configured LLM client (Gemini) and return a JSON string."""
    client = get_gemini_client()
    full_prompt = prompt + "\n\n" + text
    resp = client.infer(full_prompt, params={"max_tokens": 1024})
    if isinstance(resp, dict):
        if "text" in resp:
            return resp["text"]
        if "output" in resp:
            return resp["output"]
        return json.dumps(resp)
    return json.dumps({"text": str(resp)})


class EnrichmentAgent:
    def __init__(self) -> None:
        pass

    def analyze_pyq(self, chunk_text: str) -> Dict[str, Any]:
        raw = call_llm(PYQ_ANALYSIS_PROMPT, chunk_text)
        obj = json.loads(raw)
        try:
            validate(instance=obj, schema=PYQ_ANALYSIS_JSON_SCHEMA)
        except ValidationError as e:
            raise
        return obj

    def analyze_textbook(self, chunk_text: str) -> Dict[str, Any]:
        raw = call_llm(TEXTBOOK_PARSING_PROMPT, chunk_text)
        obj = json.loads(raw)
        try:
            validate(instance=obj, schema=TEXTBOOK_PARSING_JSON_SCHEMA)
        except ValidationError:
            raise
        return obj
