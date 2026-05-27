from __future__ import annotations

DDL = """
CREATE SCHEMA IF NOT EXISTS exam;
CREATE SCHEMA IF NOT EXISTS ingestion;

CREATE TABLE IF NOT EXISTS ingestion.sources (
    source_id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_subtype TEXT,
    subject TEXT,
    publication_year INTEGER,
    coverage_start_year INTEGER,
    coverage_end_year INTEGER,
    coverage_years_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    upload_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum TEXT NOT NULL,
    owner_user_id TEXT,
    filename TEXT NOT NULL,
    source_uri TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion.pdf_pages (
    page_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES ingestion.sources(source_id),
    page_number INTEGER NOT NULL,
    page_text TEXT NOT NULL,
    ocr_confidence DOUBLE PRECISION DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ingestion.pdf_chunks (
    chunk_id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL REFERENCES ingestion.pdf_pages(page_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES ingestion.sources(source_id) ON DELETE CASCADE,
    chunk_order INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    chunk_kind TEXT,
    extracted_entities_json JSONB DEFAULT '[]'::jsonb,
    enrichment_status TEXT DEFAULT 'pending',
    enriched_question_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exam.questions (
    question_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES ingestion.sources(source_id),
    source_uri TEXT NOT NULL,
    page_number INTEGER,
    question_number INTEGER,
    question_text TEXT NOT NULL,
    exam_year INTEGER,
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
    raw_structured_json JSONB NOT NULL DEFAULT '{}'::jsonb,
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

CREATE INDEX IF NOT EXISTS idx_questions_topic_year ON exam.questions (topic, exam_year);
CREATE INDEX IF NOT EXISTS idx_textbook_chunks_chapter ON exam.textbook_chunks (chapter);
CREATE INDEX IF NOT EXISTS idx_student_performance_user_weakness ON exam.student_performance (user_id, weakness_score DESC);

-- Job queue for multi-stage enrichment pipeline
CREATE TABLE IF NOT EXISTS ingestion.job_queue (
    job_id TEXT PRIMARY KEY,
    chunk_id TEXT REFERENCES ingestion.pdf_chunks(chunk_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending | in_progress | failed | completed
    worker TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    payload JSONB DEFAULT '{}'::jsonb,
    scheduled_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- OCR and layout artifacts (store per-page OCR and confidence)
CREATE TABLE IF NOT EXISTS ingestion.ocr_artifacts (
    artifact_id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL REFERENCES ingestion.pdf_pages(page_id) ON DELETE CASCADE,
    ocr_text TEXT NOT NULL,
    ocr_confidence DOUBLE PRECISION DEFAULT NULL,
    layout_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Extracted tables from PDFs
CREATE TABLE IF NOT EXISTS ingestion.extracted_tables (
    table_id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL REFERENCES ingestion.pdf_pages(page_id) ON DELETE CASCADE,
    rows_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Embeddings storage (vectors as JSON array for portability)
CREATE TABLE IF NOT EXISTS ingestion.embeddings (
    embedding_id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL REFERENCES ingestion.pdf_chunks(chunk_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    vector JSONB NOT NULL,
    score DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Raw LLM outputs for traceability
CREATE TABLE IF NOT EXISTS ingestion.raw_llm_outputs (
    output_id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL REFERENCES ingestion.pdf_chunks(chunk_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    prompt_hash TEXT,
    response_json JSONB NOT NULL,
    confidence DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Simple cache for LLM responses keyed by prompt+content hash
CREATE TABLE IF NOT EXISTS ingestion.llm_cache (
    cache_key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    response_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""
