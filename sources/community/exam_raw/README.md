Coral source: exam_raw
=====================

Purpose
-------
Expose uploaded PDF documents, pages, and semantic chunks to Coral as queryable tables. This source is the canonical raw input layer for enrichment agents.

Quick validation
----------------
Run the following locally (from the workspace root) after installing/configuring Coral and setting `EXAM_PDF_DIR`:

```bash
coral source lint sources/community/exam_raw/manifest.yaml
coral source add --file sources/community/exam_raw/manifest.yaml
coral sql "SELECT source_id, filename FROM pdf_documents LIMIT 10"
```

Notes
-----
- Provide a directory with PDFs or a pre-extracted file layout.
- The enrichment pipeline expects `pdf_chunks` to hold discrete question or paragraph-level units.
