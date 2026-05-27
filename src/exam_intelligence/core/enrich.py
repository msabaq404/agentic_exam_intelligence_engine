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
    """Call configured LLM client (Gemini) if available, otherwise use the local stub.

    Returns a JSON string.
    """
    client = get_gemini_client()
    full_prompt = prompt + "\n\n" + text
    if client is not None:
        # Gemini client is expected to return a JSON-serializable dict
        resp = client.infer(full_prompt, params={"max_tokens": 1024})
        # If the provider returns text, assume key 'text' or 'output'
        if isinstance(resp, dict):
            if "text" in resp:
                return resp["text"]
            if "output" in resp:
                return resp["output"]
            # otherwise return full JSON string
            return json.dumps(resp)

    # Fallback stub when no client configured
    first_line = text.strip().splitlines()[0] if text.strip() else "unknown"
    if "question" in prompt.lower() or "exam" in prompt.lower():
        out = {
            "topic": first_line[:40],
            "subtopic": "general",
            "difficulty": "Medium",
            "question_type": "Theory",
            "concepts": ["concept1"],
            "prerequisites": [],
            "semantic_tags": ["tag1"],
            "pattern_type": "standard",
            "conceptual_depth": 0.5,
            "importance_score": 0.5,
            "confidence": 0.6,
        }
        return json.dumps(out)

    out = {
        "chapter": "Unknown",
        "section": "Unknown",
        "main_concept": first_line[:80],
        "prerequisites": [],
        "formulas": [],
        "definitions": [],
        "exam_relevance_score": 0.0,
        "conceptual_importance": 0.0,
        "commonly_examined_concepts": [],
        "semantic_tags": [],
    }
    return json.dumps(out)


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
