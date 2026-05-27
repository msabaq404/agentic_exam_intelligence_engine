from __future__ import annotations

import uuid
from typing import Any

from ..db.db import connect
from ..core.enrich import EnrichmentAgent


def run_enrichment(limit: int = 50) -> None:
    agent = EnrichmentAgent()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chunk_id, chunk_text, chunk_kind, source_id FROM ingestion.pdf_chunks WHERE enrichment_status = 'pending' ORDER BY created_at LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()

            for chunk_id, chunk_text, chunk_kind, source_id in rows:
                try:
                    if chunk_kind and chunk_kind.lower() in ("question", "pyq", "mcq", "nq"):
                        result = agent.analyze_pyq(chunk_text)
                        question_id = str(uuid.uuid4())
                        cur.execute(
                            "INSERT INTO exam.questions (question_id, source_id, exam_year, topic, subtopic, difficulty, question_type, concepts_json, prerequisites_json, semantic_tags_json, pattern_type, conceptual_depth, importance_score, confidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                question_id,
                                source_id,
                                None,
                                result["topic"],
                                result.get("subtopic"),
                                result["difficulty"],
                                result["question_type"],
                                json_dump(result.get("concepts", [])),
                                json_dump(result.get("prerequisites", [])),
                                json_dump(result.get("semantic_tags", [])),
                                result.get("pattern_type"),
                                result.get("conceptual_depth", 0.0),
                                result.get("importance_score", 0.0),
                                result.get("confidence", 0.0),
                            ),
                        )
                        cur.execute(
                            "UPDATE ingestion.pdf_chunks SET enrichment_status = 'done', enriched_question_id = %s WHERE chunk_id = %s",
                            (question_id, chunk_id),
                        )
                    else:
                        # treat as textbook chunk
                        result = agent.analyze_textbook(chunk_text)
                        chunk_uuid = str(uuid.uuid4())
                        cur.execute(
                            "INSERT INTO exam.textbook_chunks (chunk_id, source_id, chapter, section, main_concept, prerequisites_json, formulas_json, definitions_json, semantic_tags_json, exam_relevance_score, conceptual_importance) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                chunk_uuid,
                                source_id,
                                result.get("chapter"),
                                result.get("section"),
                                result.get("main_concept"),
                                json_dump(result.get("prerequisites", [])),
                                json_dump(result.get("formulas", [])),
                                json_dump(result.get("definitions", [])),
                                json_dump(result.get("semantic_tags", [])),
                                result.get("exam_relevance_score", 0.0),
                                result.get("conceptual_importance", 0.0),
                            ),
                        )
                        cur.execute(
                            "UPDATE ingestion.pdf_chunks SET enrichment_status = 'done', enriched_question_id = %s WHERE chunk_id = %s",
                            (chunk_uuid, chunk_id),
                        )
                except Exception:
                    cur.execute(
                        "UPDATE ingestion.pdf_chunks SET enrichment_status = 'error' WHERE chunk_id = %s",
                        (chunk_id,),
                    )
        conn.commit()


def json_dump(obj: Any) -> str:
    import json

    return json.dumps(obj)
