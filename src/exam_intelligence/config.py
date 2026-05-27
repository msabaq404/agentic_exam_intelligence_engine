from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

try:
    from dotenv import load_dotenv
except Exception as e:
    raise ImportError("python-dotenv is required; install it with `pip install python-dotenv`.") from e


ROOT = Path(__file__).resolve().parents[2]


def load() -> None:
    """Load environment from a `.env` file in the project root.

    This project bans placeholder defaults and fallbacks. A real `.env` file
    must exist; otherwise startup fails loudly so missing configuration is
    obvious.
    """
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise RuntimeError(
            ".env file not found in project root — create a .env with required secrets and configuration."
        )
    load_dotenv(dotenv_path=env_path)


load()
