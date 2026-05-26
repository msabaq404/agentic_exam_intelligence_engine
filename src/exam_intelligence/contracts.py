from __future__ import annotations

PYQ_ANALYSIS_PROMPT = """You are an exam intelligence enrichment engine.

Analyze one exam question and return STRICT JSON only.

Your tasks:
1. Identify the primary topic.
2. Identify the subtopic.
3. Estimate difficulty.
4. Detect question type.
5. Extract core concepts tested.
6. Extract prerequisite concepts.
7. Identify recurring pattern type.
8. Generate semantic retrieval tags.
9. Estimate conceptual depth.
10. Estimate importance to the exam.
11. Return a confidence score.

Allowed difficulty values:
- Easy
- Medium
- Hard

Allowed question types:
- MCQ
- NAT
- MSQ
- Numerical
- Theory

Output schema:
{
  "topic": "",
  "subtopic": "",
  "difficulty": "",
  "question_type": "",
  "concepts": [],
  "prerequisites": [],
  "semantic_tags": [],
  "pattern_type": "",
  "conceptual_depth": 0.0,
  "importance_score": 0.0,
  "confidence": 0.0
}"""

TEXTBOOK_PARSING_PROMPT = """You are a semantic educational parser.

Analyze one textbook chunk and return STRICT JSON only.

Your tasks:
1. Identify chapter and section.
2. Extract the main concept.
3. Extract prerequisite concepts.
4. Extract important formulas.
5. Extract key definitions.
6. Estimate exam relevance.
7. Estimate conceptual importance.
8. Generate semantic tags.
9. Detect commonly examined concepts.

Output schema:
{
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
}"""

PYQ_ANALYSIS_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "topic": {"type": "string"},
        "subtopic": {"type": "string"},
        "difficulty": {"type": "string", "enum": ["Easy", "Medium", "Hard"]},
        "question_type": {"type": "string", "enum": ["MCQ", "NAT", "MSQ", "Numerical", "Theory"]},
        "concepts": {"type": "array", "items": {"type": "string"}},
        "prerequisites": {"type": "array", "items": {"type": "string"}},
        "semantic_tags": {"type": "array", "items": {"type": "string"}},
        "pattern_type": {"type": "string"},
        "conceptual_depth": {"type": "number"},
        "importance_score": {"type": "number"},
        "confidence": {"type": "number"},
    },
    "required": [
        "topic",
        "subtopic",
        "difficulty",
        "question_type",
        "concepts",
        "prerequisites",
        "semantic_tags",
        "pattern_type",
        "conceptual_depth",
        "importance_score",
        "confidence",
    ],
}

TEXTBOOK_PARSING_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "chapter": {"type": "string"},
        "section": {"type": "string"},
        "main_concept": {"type": "string"},
        "prerequisites": {"type": "array", "items": {"type": "string"}},
        "formulas": {"type": "array", "items": {"type": "string"}},
        "definitions": {"type": "array", "items": {"type": "string"}},
        "exam_relevance_score": {"type": "number"},
        "conceptual_importance": {"type": "number"},
        "commonly_examined_concepts": {"type": "array", "items": {"type": "string"}},
        "semantic_tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
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
}
