from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile

from ..db.db import connect

app = FastAPI(title="Exam Ingest API")

DATA_DIR = Path("data/pdfs")
DATA_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_SOURCE_KINDS = {"pyq", "textbook", "notes", "worksheet", "reference"}
ALLOWED_STAGES = {"ocr"}


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _register_source(
    *,
    source_id: str,
    source_kind: str,
    source_subtype: str | None,
    subject: str | None,
    publication_year: int | None,
    coverage_start_year: int | None,
    coverage_end_year: int | None,
    coverage_years_json: str,
    checksum: str,
    owner_user_id: str | None,
    filename: str,
    source_uri: str,
) -> None:
    if source_kind not in ALLOWED_SOURCE_KINDS:
        raise ValueError(f"unsupported source_kind: {source_kind}")

    coverage_years = json.loads(coverage_years_json)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion.sources (source_id, source_type, source_kind, subject, year, checksum, owner_user_id, filename, source_uri) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    source_id,
                    source_kind,
                    source_kind,
                    subject,
                    publication_year,
                    checksum,
                    owner_user_id,
                    filename,
                    source_uri,
                ),
            )
        conn.commit()


def _enqueue_job(source_id: str, source_uri: str, source_kind: str, stage: str, payload: dict | None = None) -> str:
    if stage not in ALLOWED_STAGES:
        raise ValueError(f"unsupported stage: {stage}")

    job_id = str(uuid.uuid4())
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion.job_queue (job_id, chunk_id, stage, status, payload, created_at) VALUES (%s,%s,%s,%s,%s,NOW())",
                (
                    job_id,
                    None,
                    stage,
                    "pending",
                    json.dumps({"source_id": source_id, "source_uri": source_uri, "source_kind": source_kind, **(payload or {})}),
                ),
            )
        conn.commit()
    return job_id


async def _save_uploaded_file(file: UploadFile, source_id: str) -> tuple[Path, str]:
    filename = f"{source_id}_{file.filename}"
    dest = DATA_DIR / filename
    with dest.open("wb") as out:
        out.write(await file.read())
    return dest, compute_sha256(dest)


@app.post("/sources")
async def create_source(
    file: UploadFile = File(...),
    source_kind: str = Form("pyq"),
    source_subtype: str = Form(None),
    subject: str = Form(None),
    publication_year: int = Form(None),
    coverage_start_year: int = Form(None),
    coverage_end_year: int = Form(None),
    coverage_years_json: str = Form("[]"),
    owner_user_id: str = Form(None),
):
    source_id = str(uuid.uuid4())
    dest, checksum = await _save_uploaded_file(file, source_id)
    _register_source(
        source_id=source_id,
        source_kind=source_kind,
        source_subtype=source_subtype,
        subject=subject,
        publication_year=publication_year,
        coverage_start_year=coverage_start_year,
        coverage_end_year=coverage_end_year,
        coverage_years_json=coverage_years_json,
        checksum=checksum,
        owner_user_id=owner_user_id,
        filename=file.filename,
        source_uri=str(dest.absolute()),
    )
    job_id = _enqueue_job(source_id, str(dest.absolute()), source_kind, "ocr", {"filename": file.filename})
    return {
        "source_id": source_id,
        "checksum": checksum,
        "source_kind": source_kind,
        "queued_job_id": job_id,
        "queued_ocr_jobs": 1,
    }


@app.post("/sources/{source_id}/jobs")
def enqueue_source_job(source_id: str, stage: str = Form("ocr"), source_uri: str = Form(...), source_kind: str = Form("pyq")):
    job_id = _enqueue_job(source_id, source_uri, source_kind, stage)
    return {"source_id": source_id, "stage": stage, "job_id": job_id}


@app.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    source_kind: str = Form("pyq"),
    source_subtype: str = Form(None),
    subject: str = Form(None),
    publication_year: int = Form(None),
    coverage_start_year: int = Form(None),
    coverage_end_year: int = Form(None),
    coverage_years_json: str = Form("[]"),
    owner_user_id: str = Form(None),
):
    result = await create_source(
        file=file,
        source_kind=source_kind,
        source_subtype=source_subtype,
        subject=subject,
        publication_year=publication_year,
        coverage_start_year=coverage_start_year,
        coverage_end_year=coverage_end_year,
        coverage_years_json=coverage_years_json,
        owner_user_id=owner_user_id,
    )
    return {
        **result,
        "pages": 0,
        "chunks": 0,
        "publication_year": publication_year,
        "coverage_start_year": coverage_start_year,
        "coverage_end_year": coverage_end_year,
    }
