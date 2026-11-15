"""Explicit schema command. Does not import or migrate SQLite records."""

import os
import sys

from qa_intelligence.storage import StorageUnavailableError


def main():
    dsn = os.getenv("QA_DATABASE_URL", "").strip()
    if not dsn:
        print("QA_DATABASE_URL is required", file=sys.stderr)
        return 1
    try:
        from qa_intelligence.postgres_store import PostgresAnalysisStore
        installed = PostgresAnalysisStore(dsn).migrate()
    except (ImportError, StorageUnavailableError):
        print("Schema migration failed; verify driver, database and migration version", file=sys.stderr)
        return 1
    print("Schema version 1 installed" if installed else "Schema version 1 already installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
