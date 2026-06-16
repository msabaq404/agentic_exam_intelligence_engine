from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="exam-api")
    parser.add_argument("--host", default=os.getenv("API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("API_PORT", "8000")))
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn auto-reload for development")
    args = parser.parse_args()
    uvicorn.run("exam_intelligence.api.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
