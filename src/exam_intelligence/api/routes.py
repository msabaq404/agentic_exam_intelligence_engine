from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from ..db.db import connect
from ..services.coral_agent import ask_agent as run_coral_agent

router = APIRouter(prefix="/api", tags=["dashboard"])


class AgentAskRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    question_id: str | None = None


def _fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]


def _fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = _fetch_all(sql, params)
    return rows[0] if rows else None


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/pyqs")
def list_pyqs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, alias="page_size", ge=1, le=100),
    limit: int | None = Query(None, ge=1, le=100),
    offset: int | None = Query(None, ge=0),
    topic: str | None = None,
    source_kind: str | None = None,
    year: int | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    if limit is not None:
        page_size = limit

    if offset is not None:
        page = (offset // page_size) + 1 if page_size else 1

    offset_value = (page - 1) * page_size
    where_clauses: list[str] = []
    params: list[Any] = []

    if topic:
        where_clauses.append("q.topic ILIKE %s")
        params.append(f"%{topic}%")
    if source_kind:
        where_clauses.append("s.source_kind = %s")
        params.append(source_kind)
    if year is not None:
        where_clauses.append("q.year = %s")
        params.append(year)
    if search:
        where_clauses.append("(q.question_text ILIKE %s OR q.topic ILIKE %s OR q.subtopic ILIKE %s OR s.filename ILIKE %s)")
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term, search_term])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    count_row = _fetch_one(
        f"""
        SELECT COUNT(*) AS total
        FROM exam.questions q
        JOIN ingestion.sources s ON s.source_id = q.source_id
        {where_sql}
        """,
        tuple(params),
    ) or {"total": 0}

    items = _fetch_all(
        f"""
        SELECT
            q.question_id,
            q.source_id,
            s.source_kind,
            s.filename,
            q.year,
            q.topic,
            q.subtopic,
            q.difficulty,
            q.question_type,
            q.question_number,
            q.page_number,
            q.question_text,
            q.concepts_json,
            q.semantic_tags_json,
            q.importance_score,
            q.conceptual_depth,
            q.confidence,
            q.created_at,
            q.updated_at
        FROM exam.questions q
        JOIN ingestion.sources s ON s.source_id = q.source_id
        {where_sql}
        ORDER BY q.importance_score DESC, q.updated_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [page_size, offset_value]),
    )

    total = int(count_row["total"])
    total_pages = max(1, (total + page_size - 1) // page_size) if total else 1

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "offset": offset_value,
    }


@router.get("/pyqs/{question_id}")
def get_pyq(question_id: str) -> dict[str, Any]:
    question = _fetch_one(
        """
        SELECT
            q.question_id,
            q.source_id,
            s.source_kind,
            s.filename,
            s.source_uri,
            q.year,
            q.topic,
            q.subtopic,
            q.difficulty,
            q.question_type,
            q.page_number,
            q.question_number,
            q.question_text,
            q.concepts_json,
            q.prerequisites_json,
            q.semantic_tags_json,
            q.pattern_type,
            q.conceptual_depth,
            q.importance_score,
            q.confidence,
            q.raw_structured_json,
            q.created_at,
            q.updated_at
        FROM exam.questions q
        JOIN ingestion.sources s ON s.source_id = q.source_id
        WHERE q.question_id = %s
        """,
        (question_id,),
    )
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    links = _fetch_all(
        """
        SELECT
            l.chunk_id,
            l.link_score,
            l.link_reason,
            c.chapter,
            c.section,
            c.main_concept,
            c.exam_relevance_score,
            c.conceptual_importance
        FROM exam.chapter_links l
        JOIN exam.textbook_chunks c ON c.chunk_id = l.chunk_id
        WHERE l.question_id = %s
        ORDER BY l.link_score DESC, c.exam_relevance_score DESC
        """,
        (question_id,),
    )

    analytics = _fetch_one(
        """
        WITH topic_peer_stats AS (
            SELECT
                COUNT(*) AS topic_question_count,
                AVG(importance_score) AS topic_avg_importance,
                AVG(confidence) AS topic_avg_confidence
            FROM exam.questions
            WHERE topic = (
                SELECT topic FROM exam.questions WHERE question_id = %s
            )
        )
        SELECT
            q.importance_score,
            q.confidence,
            q.conceptual_depth,
            COALESCE((SELECT COUNT(*) FROM exam.chapter_links WHERE question_id = q.question_id), 0) AS linked_chunks,
            peer.topic_question_count,
            peer.topic_avg_importance,
            peer.topic_avg_confidence
        FROM exam.questions q
        CROSS JOIN topic_peer_stats peer
        WHERE q.question_id = %s
        """,
        (question_id, question_id),
    ) or {}

    return {
        "question": question,
        "analytics": analytics,
        "related_chunks": links,
        "download_url": f"/api/pyqs/{question_id}/pdf",
    }


@router.get("/pyqs/{question_id}/analytics")
def get_pyq_analytics(question_id: str) -> dict[str, Any]:
    result = get_pyq(question_id)
    return {
        "question_id": question_id,
        "question": result["question"],
        "analytics": result["analytics"],
        "related_chunks": result["related_chunks"],
    }


@router.get("/pyqs/{question_id}/pdf")
def download_pyq_pdf(question_id: str) -> FileResponse:
    row = _fetch_one(
        """
        SELECT s.source_uri, s.filename
        FROM exam.questions q
        JOIN ingestion.sources s ON s.source_id = q.source_id
        WHERE q.question_id = %s
        """,
        (question_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Question not found")

    source_path = Path(str(row["source_uri"]))
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Source PDF not found on disk")

    return FileResponse(path=source_path, filename=row["filename"], media_type="application/pdf")


@router.get("/analytics/summary")
def analytics_summary() -> dict[str, Any]:
    overview = _fetch_one(
        """
        SELECT
            COUNT(*) AS total_questions,
            COUNT(DISTINCT topic) AS total_topics,
            ROUND(AVG(importance_score)::numeric, 3) AS average_importance,
            ROUND(AVG(confidence)::numeric, 3) AS average_confidence
        FROM exam.questions
        """
    ) or {}

    top_topics = _fetch_all(
        """
        SELECT
            topic,
            COUNT(*) AS question_count,
            ROUND(AVG(importance_score)::numeric, 3) AS average_importance,
            ROUND(AVG(confidence)::numeric, 3) AS average_confidence
        FROM exam.questions
        GROUP BY topic
        ORDER BY average_importance DESC, question_count DESC
        LIMIT 10
        """
    )

    by_difficulty = _fetch_all(
        """
        SELECT
            difficulty,
            COUNT(*) AS question_count
        FROM exam.questions
        GROUP BY difficulty
        ORDER BY question_count DESC
        """
    )

    return {
        "overview": overview,
        "top_topics": top_topics,
        "difficulty_breakdown": by_difficulty,
    }


@router.post("/agent/ask")
def ask(question: AgentAskRequest) -> dict[str, Any]:
    context_parts: list[str] = []
    if question.question_id:
        detail = get_pyq(question.question_id)
        context_parts.append(json.dumps(detail["question"], ensure_ascii=False, default=str))
        if detail["related_chunks"]:
            context_parts.append("Related chunks:\n" + json.dumps(detail["related_chunks"], ensure_ascii=False, default=str))

    try:
        return run_coral_agent(question.prompt, context_text="\n\n".join(context_parts))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"Coral CLI not available: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
