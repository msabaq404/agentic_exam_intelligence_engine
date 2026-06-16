# Frontend

React/Vite dashboard for the exam intelligence workspace.

## What is here

- A PYQ dashboard with clickable question cards.
- A detail panel showing importance, accuracy, and other per-question analytics.
- An analytics tab wired to backend summary endpoints.
- An agent tab wired to `/api/agent/ask` with markdown/math rendering.
- An ingestion tab to upload files to `/ingest/upload`.

## Run locally

```powershell
cd frontend
npm install
npm run dev
```

## Backend API host

By default the frontend uses `http://127.0.0.1:8000`. Override with:

```powershell
$env:VITE_API_BASE = "https://your-api-host"
npm run dev
```

## Notes

- For cross-domain setups, download links are resolved against `VITE_API_BASE`.
- Ensure the backend has CORS enabled for your frontend origin.
