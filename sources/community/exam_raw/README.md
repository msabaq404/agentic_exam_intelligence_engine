Coral source: exam_raw
=====================

Purpose
-------
Expose uploaded PDF documents, pages, and semantic chunks to Coral as queryable SQL tables. This source is the canonical raw input layer for enrichment agents.

Metadata semantics
------------------
- `source_kind` identifies the family of document: `pyq`, `textbook`, `syllabus`, `mock_test`, `notes`, or `reference`.
- `publication_year` is the document publication year.
- `coverage_start_year` and `coverage_end_year` describe the exam-year range covered by a multi-year source.
- `coverage_years_json` supports mixed or disjoint coverage years.

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
- The raw tables are expected to be populated by the uploader into PostgreSQL.
- The enrichment pipeline expects `pdf_chunks` to hold discrete question or paragraph-level units.
