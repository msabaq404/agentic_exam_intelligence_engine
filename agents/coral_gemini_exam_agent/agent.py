from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from exam_intelligence.clients.llm_client import get_gemini_client

RAW_MANIFEST = PROJECT_ROOT / "sources" / "community" / "exam_raw" / "manifest.yaml"
ENRICHED_MANIFEST = PROJECT_ROOT / "sources" / "community" / "exam_enriched" / "manifest.yaml"
SYSTEM_PROMPT_PATH = Path(__file__).with_name("system_prompt.md")


def _run_coral(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=True)


def refresh_sources() -> None:
    for manifest in (RAW_MANIFEST, ENRICHED_MANIFEST):
        _run_coral(["coral", "source", "add", "--file", str(manifest)])


def run_coral_sql(query: str) -> list[dict[str, Any]]:
    result = _run_coral(["coral", "sql", "--format", "json", query])
    output = result.stdout.strip()
    if not output:
        return []

    lines = [line for line in output.splitlines() if line.strip()]
    if lines and lines[0].startswith("json "):
        payload = "\n".join(lines[1:]).strip()
    else:
        payload = output

    if not payload:
        return []
    return json.loads(payload)


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def parse_json_payload(text: str) -> dict[str, Any]:
    candidate = text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            return json.loads(candidate[start : end + 1])
        raise


def draft_query(question: str) -> tuple[str, str]:
    client = get_gemini_client()
    prompt = (
        load_system_prompt()
        + "\n\nUser question:\n"
        + question.strip()
        + "\n\nReturn JSON only."
    )
    response = client.infer(prompt, params={"max_tokens": 500, "temperature": 0.1})
    payload = parse_json_payload(response["text"])
    sql = str(payload["sql"]).strip()
    notes = str(payload.get("notes", "")).strip()
    return sql, notes


def answer_question(question: str, sql: str, rows: list[dict[str, Any]], notes: str = "") -> str:
    client = get_gemini_client()
    prompt = (
        "You are answering a question about exam intelligence data.\n"
        f"Question: {question}\n\n"
        f"SQL used:\n{sql}\n\n"
        + (f"Planner notes: {notes}\n\n" if notes else "")
        + "Coral result rows (JSON):\n"
        + json.dumps(rows, ensure_ascii=False)
        + "\n\nWrite a concise answer grounded only in the rows above. If the rows are empty, say that clearly."
    )
    response = client.infer(prompt)
    return response["text"].strip()


def main() -> None:
    parser = argparse.ArgumentParser(prog="coral-gemini-agent")
    parser.add_argument("question", nargs="*", help="Natural-language question to answer with Coral-backed data")
    parser.add_argument("--sql-only", action="store_true", help="Print the drafted SQL and exit")
    parser.add_argument("--no-refresh", action="store_true", help="Skip re-importing the Coral manifests")
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        question = input("Question: ").strip()

    if not args.no_refresh:
        refresh_sources()

    sql, notes = draft_query(question)
    if args.sql_only:
        print(sql)
        return

    rows = run_coral_sql(sql)
    answer = answer_question(question, sql, rows, notes=notes)
    print(answer)


if __name__ == "__main__":
    main()
