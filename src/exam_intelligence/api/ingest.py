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


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


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
    # save file
    source_id = str(uuid.uuid4())
    filename = f"{source_id}_{file.filename}"
    dest = DATA_DIR / filename
    with dest.open("wb") as out:
        content = await file.read()
        out.write(content)

    checksum = compute_sha256(dest)
    coverage_years = json.loads(coverage_years_json)

    # register source
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion.sources (source_id, source_kind, source_subtype, subject, publication_year, coverage_start_year, coverage_end_year, coverage_years_json, checksum, owner_user_id, filename, source_uri) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    source_id,
                    source_kind,
                    source_subtype,
                    subject,
                    publication_year,
                    coverage_start_year,
                    coverage_end_year,
                    json.dumps(coverage_years),
                    checksum,
                    owner_user_id,
                    file.filename,
                    str(dest.absolute()),
                ),
            )
        conn.commit()

    with connect() as conn:
        with conn.cursor() as cur:
            job_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO ingestion.job_queue (job_id, chunk_id, stage, status, payload, created_at) VALUES (%s,%s,%s,%s,%s,NOW())",
                (
                    job_id,
                    None,
                    "ocr",
                    "pending",
                    json.dumps(
                        {
                            "source_id": source_id,
                            "source_uri": str(dest.absolute()),
                            "filename": file.filename,
                            "source_kind": source_kind,
                        }
                    ),
                ),
            )
        conn.commit()

    return {
        "source_id": source_id,
        "checksum": checksum,
        "pages": 0,
        "chunks": 0,
        "queued_ocr_jobs": 1,
        "source_kind": source_kind,
        "publication_year": publication_year,
        "coverage_start_year": coverage_start_year,
        "coverage_end_year": coverage_end_year,
    }
