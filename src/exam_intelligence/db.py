from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg


def connection_dsn() -> str:
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    dbname = os.getenv("PGDATABASE", "postgres")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "postgres")
    sslmode = os.getenv("PGSSLMODE", "prefer")
    return (
        f"host={host} port={port} dbname={dbname} user={user} "
        f"password={password} connect_timeout=10 sslmode={sslmode}"
    )


@contextmanager
def connect():
    with psycopg.connect(connection_dsn()) as connection:
        yield connection
