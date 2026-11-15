"""Explicit maintenance import. SQLite is read-only; PostgreSQL commits atomically."""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from qa_intelligence.schemas import AnalysisRequest, AnalysisResponse, ReviewRecord, SavedAnalysisResponse
from qa_intelligence.storage import StorageUnavailableError


class ImportRejectedError(Exception):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validated_payload(model, raw):
    value = model.model_validate(raw)
    if _canonical(value.model_dump(mode="json")) != _canonical(raw):
        raise ImportRejectedError("Source contains noncanonical or unsupported fields")
    return value


def _validate_snapshot(snapshot):
    identities = {}
    for row in snapshot["analyses"]:
        request = _validated_payload(AnalysisRequest, row["request_json"])
        draft = _validated_payload(SavedAnalysisResponse, row["draft_json"])
        if draft.analysis_id != UUID(row["analysis_id"]) or draft.analysis_id in identities:
            raise ImportRejectedError("Source analysis identity is inconsistent")
        unsaved = AnalysisResponse.model_validate(draft.model_dump())
        content = {
            "analysis_id": str(draft.analysis_id), "created_at": draft.created_at.isoformat(),
            "request": request.model_dump(mode="json"), "draft": unsaved.model_dump(mode="json"),
        }
        digest = hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
        if digest != draft.draft_sha256:
            raise ImportRejectedError("Source analysis digest is invalid")
        identities[draft.analysis_id] = digest
    review_ids = set()
    for row in snapshot["reviews"]:
        review = _validated_payload(ReviewRecord, row["review_json"])
        if (review.review_id != UUID(row["review_id"]) or review.review_id in review_ids or
            review.analysis_id != UUID(row["analysis_id"]) or
            identities.get(review.analysis_id) != review.draft_sha256):
            raise ImportRejectedError("Source review identity or digest is inconsistent")
        review_ids.add(review.review_id)


def _read_source(source: Path):
    try:
        path = source.resolve(strict=True)
        # This operator tool reads a small, quiescent local snapshot, not a live feed.
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise ImportRejectedError("Source is not a supported small SQLite snapshot")
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("BEGIN")
            if connection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] > 10000 or \
               connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] > 50000:
                raise ImportRejectedError("Source exceeds the bounded import row limit")
            snapshot = {
                "analyses": [{
                    "analysis_id": str(UUID(row["analysis_id"])),
                    "request_json": json.loads(row["request_json"]),
                    "draft_json": json.loads(row["draft_json"]),
                } for row in connection.execute("SELECT * FROM analyses ORDER BY analysis_id")],
                "reviews": [{
                    "review_id": str(UUID(row["review_id"])), "analysis_id": str(UUID(row["analysis_id"])),
                    "review_json": json.loads(row["review_json"]),
                } for row in connection.execute("SELECT * FROM reviews ORDER BY sequence")],
            }
        _validate_snapshot(snapshot)
        return snapshot
    except (OSError, sqlite3.Error, ValueError, TypeError, ValidationError):
        raise ImportRejectedError("Source snapshot could not be read or validated") from None


def _summary(snapshot):
    return {
        "analyses": len(snapshot["analyses"]), "reviews": len(snapshot["reviews"]),
        "content_sha256": hashlib.sha256(_canonical(snapshot).encode("utf-8")).hexdigest(),
    }


def inspect_sqlite(source: Path):
    """Return counts/content fingerprint only; never return draft text or secrets."""
    return _summary(_read_source(source))


def _read_target(connection):
    return {
        "analyses": [{**row, "analysis_id": str(row["analysis_id"])} for row in connection.execute(
            "SELECT analysis_id, request_json, draft_json FROM analyses ORDER BY analysis_id"
        )],
        "reviews": [{**row, "review_id": str(row["review_id"]), "analysis_id": str(row["analysis_id"])}
            for row in connection.execute("SELECT review_id, analysis_id, review_json FROM reviews ORDER BY sequence")],
    }


def inspect_postgres(target):
    with target._connection() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = _read_target(connection)
        _validate_snapshot(snapshot)
        return _summary(snapshot)


def import_sqlite(source: Path, target):
    # Fully validate the coherent read-only source before opening a write transaction.
    snapshot = _read_source(source)
    from psycopg.types.json import Jsonb

    with target._connection() as connection:
        # Maintenance operation: serialize imports and block concurrent target writes.
        connection.execute("LOCK TABLE analyses, reviews IN SHARE ROW EXCLUSIVE MODE")
        current = _read_target(connection)
        if current["analyses"] or current["reviews"]:
            if _canonical(current) != _canonical(snapshot):
                raise ImportRejectedError("Target is neither empty nor an exact source match")
            return {**_summary(snapshot), "imported": False}
        for row in snapshot["analyses"]:
            connection.execute(
                "INSERT INTO analyses (analysis_id, request_json, draft_json) VALUES (%s, %s, %s)",
                (UUID(row["analysis_id"]), Jsonb(row["request_json"]), Jsonb(row["draft_json"])),
            )
        for row in snapshot["reviews"]:
            connection.execute(
                "INSERT INTO reviews (review_id, analysis_id, review_json) VALUES (%s, %s, %s)",
                (UUID(row["review_id"]), UUID(row["analysis_id"]), Jsonb(row["review_json"])),
            )
        if _canonical(_read_target(connection)) != _canonical(snapshot):
            raise ImportRejectedError("Target verification differs from the source")
        return {**_summary(snapshot), "imported": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate or atomically import a quiescent SQLite snapshot")
    parser.add_argument("--sqlite", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="Write to the explicitly configured PostgreSQL target")
    arguments = parser.parse_args(argv)
    try:
        if arguments.apply:
            dsn = os.getenv("QA_DATABASE_URL", "").strip()
            if not dsn:
                raise ImportRejectedError("QA_DATABASE_URL is required for apply")
            from qa_intelligence.postgres_store import PostgresAnalysisStore
            report = import_sqlite(arguments.sqlite, PostgresAnalysisStore(dsn))
        else:
            report = {**inspect_sqlite(arguments.sqlite), "mode": "validate-only"}
    except (ImportRejectedError, StorageUnavailableError, ImportError):
        print("Import rejected; verify source integrity, target state and configuration", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
