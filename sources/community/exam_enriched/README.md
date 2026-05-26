Coral source: exam_enriched
===========================

Purpose
-------
Expose the persistent structured exam intelligence produced by enrichment agents as first-class Coral tables. This source maps the enrichment DB into SQL-accessible tables for the query agent and analytics engine.

Quick validation
----------------
After creating or updating the persistent DB (sqlite) with enrichment outputs, run:

```bash
coral source lint sources/community/exam_enriched/manifest.yaml
coral source add --file sources/community/exam_enriched/manifest.yaml
coral sql "SELECT topic, frequency FROM exam_topic_statistics ORDER BY frequency DESC LIMIT 20"
```

Notes
-----
- The enrichment pipeline should write to the persistent DB path declared by `EXAM_DB_PATH`.
- Keep `exam_questions` as the authoritative record for solved/enriched questions; the query agent should prefer it over raw `pdf_chunks` for reasoning.
