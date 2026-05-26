from __future__ import annotations

DDL = """
CREATE SCHEMA IF NOT EXISTS exam;
CREATE SCHEMA IF NOT EXISTS ingestion;

CREATE TABLE IF NOT EXISTS ingestion.sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    subject TEXT,
    year INTEGER,
    upload_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum TEXT NOT NULL,
    owner_user_id TEXT,
    source_uri TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exam.questions (
    question_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES ingestion.sources(source_id),
    year INTEGER,
    topic TEXT NOT NULL,
    subtopic TEXT,
    difficulty TEXT NOT NULL,
    question_type TEXT NOT NULL,
    concepts_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    prerequisites_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    semantic_tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    pattern_type TEXT,
    conceptual_depth DOUBLE PRECISION NOT NULL DEFAULT 0,
    importance_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exam.textbook_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES ingestion.sources(source_id),
    chapter TEXT NOT NULL,
    section TEXT,
    main_concept TEXT NOT NULL,
    prerequisites_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    formulas_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    definitions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    semantic_tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    exam_relevance_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    conceptual_importance DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exam.chapter_links (
    question_id TEXT NOT NULL REFERENCES exam.questions(question_id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES exam.textbook_chunks(chunk_id) ON DELETE CASCADE,
    link_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    link_reason TEXT NOT NULL,
    PRIMARY KEY (question_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS exam.topic_statistics (
    topic TEXT PRIMARY KEY,
    frequency INTEGER NOT NULL DEFAULT 0,
    avg_marks DOUBLE PRECISION NOT NULL DEFAULT 0,
    recurrence_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    trend_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    importance_index DOUBLE PRECISION NOT NULL DEFAULT 0,
    chapter_roi_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exam.pattern_clusters (
    cluster_id TEXT PRIMARY KEY,
    pattern_name TEXT NOT NULL,
    related_topics_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    frequency INTEGER NOT NULL DEFAULT 0,
    conceptual_type TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exam.student_performance (
    user_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    accuracy DOUBLE PRECISION NOT NULL DEFAULT 0,
    weakness_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_practiced TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, topic)
);

CREATE INDEX IF NOT EXISTS idx_questions_topic_year ON exam.questions (topic, year);
CREATE INDEX IF NOT EXISTS idx_textbook_chunks_chapter ON exam.textbook_chunks (chapter);
CREATE INDEX IF NOT EXISTS idx_student_performance_user_weakness ON exam.student_performance (user_id, weakness_score DESC);
"""
