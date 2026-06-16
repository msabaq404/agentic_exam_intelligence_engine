
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from ..db.db import connect

ROOT = Path(os.environ["ROOT"])

OUTPUT_DIR = ROOT / "coral_data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TABLES = [
    "ingestion.sources",
    "ingestion.pdf_pages",
    "ingestion.pdf_chunks",
    "exam.questions",
    "exam.textbook_chunks",
    "exam.chapter_links",
    "ingestion.embeddings",
]


def _listen_for_export_changes() -> None:
    print("export-worker listening for database changes")
    with connect() as conn:
        conn.autocommit = True
        conn.execute("LISTEN export_changed")

        for notify in conn.notifies(timeout=None):
            print("Change detected:", notify.payload)
            export()


def stringify_problematic_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in df.columns:
        series = df[column]

        if series.dtype != "object":
            continue

        sample = next(
            (x for x in series if x is not None),
            None,
        )

        if sample is None:
            continue

        if isinstance(sample, (dict, list)):
            df[column] = series.apply(
                lambda x: json.dumps(x) if x is not None else None
            )

    return df


def export_table(table_name: str) -> None:
    print(f"Exporting {table_name}...")

    query = f"SELECT * FROM {table_name}"

    with connect() as conn:
        df = pd.read_sql(query, conn)

    df = stringify_problematic_columns(df)

    filename = table_name.replace(".", "_") + ".parquet"

    output_path = OUTPUT_DIR / filename

    df.to_parquet(
        output_path,
        engine="pyarrow",
        compression="snappy",
        index=False,
    )

    print(
        f"✓ Exported {table_name} "
        f"({len(df)} rows) -> {output_path}"
    )


def export() -> None:
    for table in TABLES:
        export_table(table)

    print("\nAll tables exported successfully.")


def run_loop() -> None:
    export()
    try:
        _listen_for_export_changes()
    except KeyboardInterrupt:
        print("export-worker stopping")
