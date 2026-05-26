from __future__ import annotations

import argparse

from .db import connect
from .schema import DDL


def init_db() -> None:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(DDL)
        connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser(prog="exam-intel")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Create the exam intelligence schemas and tables")

    args = parser.parse_args()

    if args.command == "init-db":
        init_db()


if __name__ == "__main__":
    main()
