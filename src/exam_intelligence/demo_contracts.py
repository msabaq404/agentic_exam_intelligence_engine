from __future__ import annotations

import json

from .contracts import (
    PYQ_ANALYSIS_JSON_SCHEMA,
    PYQ_ANALYSIS_PROMPT,
    TEXTBOOK_PARSING_JSON_SCHEMA,
    TEXTBOOK_PARSING_PROMPT,
)


def main() -> None:
    print("PYQ prompt:\n")
    print(PYQ_ANALYSIS_PROMPT)
    print("\nPYQ schema:\n")
    print(json.dumps(PYQ_ANALYSIS_JSON_SCHEMA, indent=2))
    print("\nTextbook prompt:\n")
    print(TEXTBOOK_PARSING_PROMPT)
    print("\nTextbook schema:\n")
    print(json.dumps(TEXTBOOK_PARSING_JSON_SCHEMA, indent=2))


if __name__ == "__main__":
    main()
