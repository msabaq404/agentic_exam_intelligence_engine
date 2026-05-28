from __future__ import annotations

from fastapi import FastAPI

from .ingest import app as ingest_app

app = FastAPI(title="Exam Intelligence API")
app.mount("/ingest", ingest_app)
