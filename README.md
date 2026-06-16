# Exam Intelligence — Project Overview

Overview
--------

End-to-end exam intelligence prototype demonstrating full-stack engineering: backend services (FastAPI), an ingestion and OCR pipeline, LLM-driven enrichment and query agents, and a React dashboard for analytics and exploration. The project showcases systems design, data engineering, and applied ML/LLM integration.

Highlights
----------
- Built an ingestion pipeline that handles PDF uploads, splits documents into Azure-friendly OCR batches, and persists structured page/chunk data.
- Implemented background workers for embeddings, enrichment, and LLM-driven question synthesis with rate-limiting and batching controls.
- Developed a React + Vite dashboard with searchable question archive, analytics summaries, and an interactive agent UI.
- Engineered cross-origin API handling and robust PDF download links for frontend/backend separation.

Key technologies
----------------
- Backend: Python, FastAPI, PostgreSQL
- Frontend: React, Vite, Tailwind CSS
- ML/LLM: Google GenAI (Gemini) SDK integration, embeddings pipeline
- OCR: Azure Document Intelligence (batch-safe processing)

Note on data layer
------------------
The prototype uses a lightweight SQL-first data access layer and source manifests for efficient analytics and querying. The repository includes Coral source manifests used during development to register and query datasets; these manifests can be adapted or replaced to integrate other SQL-backed data layers as needed.

Quick start (developer)
-----------------------
Install and run the backend (local dev):

```powershell
pip install -e .
exam-intel init-db
exam-api --reload
```

Install and run the frontend (local dev):

```powershell
cd frontend
npm install
npm run dev
```

If your frontend is served from a different host than the API, set the API base before starting the dev server:

```powershell
$env:VITE_API_BASE = "https://your-api-host"
npm run dev
```

What’s implemented
------------------
- File upload and ingestion endpoint (`POST /ingest/upload`).
- OCR batch processing that splits PDFs into 2-page requests for Azure.
- Workers for embedding, enrichment, and LLM-driven processing with configurable rate limits.
- API endpoints used by the dashboard: question list, question detail, analytics summary, and PDF download.
- Frontend: dashboard (pagination), detail panel, analytics tab, agent tab, and ingestion UI.

Where to look in the repo
-------------------------
- API and workers: `src/exam_intelligence/`
- Frontend: `frontend/`
- Agent example: `agents/coral_gemini_exam_agent/`



