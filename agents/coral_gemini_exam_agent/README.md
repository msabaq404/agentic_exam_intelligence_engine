# Coral Gemini Exam Agent

This directory contains a small Gemini-powered query agent that talks to the exam data through Coral.

## What it does

- Refreshes the local Coral installs from the checked-in source manifests.
- Uses Gemini to draft one schema-qualified Coral SQL query.
- Runs that query through `coral sql`.
- Uses Gemini again to turn the returned rows into a concise answer.

## Files

- `agent.py`: command-line entry point for the agent.
- `system_prompt.md`: the SQL drafting prompt and table map.

## Run it

Set your Gemini environment variables first:

```powershell
$env:GOOGLE_GENAI_API_KEY = "..."
$env:GOOGLE_GENAI_MODEL = "gemini-2.5-flash"
```

Then ask a question:

```powershell
python agents\coral_gemini_exam_agent\agent.py "What are the most common topics in PYQ questions?"
```

To inspect the drafted SQL without answering:

```powershell
python agents\coral_gemini_exam_agent\agent.py --sql-only "Show the top textbook chapters by exam relevance"
```

## Notes

- The agent expects the Coral CLI to be available on `PATH`.
- It re-imports `sources/community/exam_raw/manifest.yaml` and `sources/community/exam_enriched/manifest.yaml` on startup so the registered Coral sources stay aligned with the repo manifests.
- The Coral source names are used as schemas, so queries must target `exam_raw.*` and `exam_enriched.*`.
