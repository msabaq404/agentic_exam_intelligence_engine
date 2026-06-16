from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ..clients.llm_client import get_gemini_client

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SYSTEM_PROMPT_PATH = PROJECT_ROOT / "agents" / "coral_gemini_exam_agent" / "system_prompt.md"


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _run_coral(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=True)


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


def draft_query(question: str, context_text: str = "") -> tuple[str, str]:
    client = get_gemini_client()
    prompt_parts = [load_system_prompt()]
    if context_text.strip():
        prompt_parts.append("\n\nContext:\n" + context_text.strip())
    prompt_parts.append("\n\nUser question:\n" + question.strip())
    prompt_parts.append("\n\nReturn JSON only.")
    response = client.infer("".join(prompt_parts), params={"max_tokens": 500, "temperature": 0.1})
    payload = parse_json_payload(response["text"])
    sql = str(payload["sql"]).strip()
    if not sql.lower().startswith("select"):
        raise ValueError("Only SELECT statements are allowed")
    notes = str(payload.get("notes", "")).strip()
    return sql, notes


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
    parsed = json.loads(payload)
    if isinstance(parsed, list):
        return parsed
    return [parsed]


def answer_question(question: str, sql: str, rows: list[dict[str, Any]], notes: str = "", context_text: str = "") -> str:
    client = get_gemini_client()
    prompt = [
        "You are answering a question about exam intelligence data.",
        f"Question: {question}",
        "",
        f"SQL used:\n{sql}",
        "",
    ]
    if context_text.strip():
        prompt.extend([f"Context:\n{context_text.strip()}", ""])
    if notes:
        prompt.extend([f"Planner notes: {notes}", ""])
    prompt.extend(
        [
            "Coral result rows (JSON):",
            json.dumps(rows, ensure_ascii=False, default=str),
            "",
            "Write a concise answer grounded only in the rows above. If the rows are empty, say that clearly.",
        ]
    )
    response = client.infer("\n".join(prompt))
    return response["text"].strip()


def ask_agent(question: str, context_text: str = "") -> dict[str, Any]:
    sql, notes = draft_query(question, context_text=context_text)
    rows = run_coral_sql(sql)
    answer = answer_question(question, sql, rows, notes=notes, context_text=context_text)
    return {
        "question": question,
        "sql": sql,
        "notes": notes,
        "rows": rows,
        "answer": answer,
    }
