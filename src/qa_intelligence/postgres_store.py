"""Opt-in PostgreSQL adapter; schema installation is an explicit operator step."""

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.resources import files
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from qa_intelligence.schemas import (
    AnalysisRecord, AnalysisRequest, AnalysisResponse, ReviewRecord,
    ReviewRequest, SavedAnalysisResponse,
)
from qa_intelligence.storage import AnalysisNotFoundError, ReviewConflictError, StorageUnavailableError


class PostgresAnalysisStore:
    def __init__(self, dsn: str):
        self._dsn = dsn

    @contextmanager
    def _connection(self):
        try:
            with psycopg.connect(
                self._dsn, connect_timeout=5, row_factory=dict_row,
                options="-c statement_timeout=5000 -c lock_timeout=3000",
            ) as connection:
                yield connection
        except (OSError, psycopg.Error, ValidationError, ValueError):
            # Do not expose driver diagnostics, SQL parameters or connection secrets.
            raise StorageUnavailableError("Analysis storage is unavailable") from None

    def migrate(self) -> bool:
        """Install version 1 once, transactionally; reject changed migration bytes."""
        sql_bytes = files("qa_intelligence").joinpath("migrations/001_analysis_storage.sql").read_bytes()
        checksum = hashlib.sha256(sql_bytes).hexdigest()
        with self._connection() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(714231, 1)")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS qi_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    installed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            installed = connection.execute(
                "SELECT checksum FROM qi_schema_migrations WHERE version = 1"
            ).fetchone()
            if installed:
                if installed["checksum"] != checksum:
                    raise StorageUnavailableError("Installed migration checksum differs")
                return False
            connection.execute(sql_bytes.decode("utf-8"))
            connection.execute(
                "INSERT INTO qi_schema_migrations (version, checksum) VALUES (1, %s)", (checksum,)
            )
            return True

    def save(self, request: AnalysisRequest, draft: AnalysisResponse) -> SavedAnalysisResponse:
        analysis_id = uuid4()
        created_at = datetime.now(timezone.utc)
        # Same canonical digest contract as SQLite; database formatting is excluded.
        content = {
            "analysis_id": str(analysis_id), "created_at": created_at.isoformat(),
            "request": request.model_dump(mode="json"), "draft": draft.model_dump(mode="json"),
        }
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        saved = SavedAnalysisResponse(
            **draft.model_dump(), analysis_id=analysis_id, created_at=created_at,
            draft_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO analyses (analysis_id, request_json, draft_json) VALUES (%s, %s, %s)",
                (analysis_id, Jsonb(request.model_dump(mode="json")), Jsonb(saved.model_dump(mode="json"))),
            )
        return saved

    def get(self, analysis_id: UUID) -> AnalysisRecord:
        with self._connection() as connection:
            # Input, draft and history come from one coherent read snapshot.
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            row = connection.execute(
                "SELECT request_json, draft_json FROM analyses WHERE analysis_id = %s", (analysis_id,)
            ).fetchone()
            if row is None:
                raise AnalysisNotFoundError
            reviews = [
                ReviewRecord.model_validate(item["review_json"])
                for item in connection.execute(
                    "SELECT review_json FROM reviews WHERE analysis_id = %s ORDER BY sequence", (analysis_id,)
                )
            ]
            return AnalysisRecord(
                request=AnalysisRequest.model_validate(row["request_json"]),
                draft=SavedAnalysisResponse.model_validate(row["draft_json"]),
                reviews=reviews, review_status=reviews[-1].decision if reviews else "pending",
            )

    def review(self, analysis_id: UUID, request: ReviewRequest) -> tuple[ReviewRecord, bool]:
        with self._connection() as connection:
            # Serializes append order for this analysis, not all platform writes.
            row = connection.execute(
                "SELECT draft_json FROM analyses WHERE analysis_id = %s FOR UPDATE", (analysis_id,)
            ).fetchone()
            if row is None:
                raise AnalysisNotFoundError
            draft = SavedAnalysisResponse.model_validate(row["draft_json"])
            if request.draft_sha256 != draft.draft_sha256:
                raise ReviewConflictError("Review digest does not match the saved draft")
            existing = connection.execute(
                "SELECT review_json FROM reviews WHERE review_id = %s", (request.review_id,)
            ).fetchone()
            if existing is None:
                proposed = ReviewRecord(
                    **request.model_dump(), analysis_id=analysis_id, created_at=datetime.now(timezone.utc)
                )
                inserted = connection.execute(
                    "INSERT INTO reviews (review_id, analysis_id, review_json) VALUES (%s, %s, %s) "
                    "ON CONFLICT (review_id) DO NOTHING RETURNING review_json",
                    (request.review_id, analysis_id, Jsonb(proposed.model_dump(mode="json"))),
                ).fetchone()
                if inserted:
                    return ReviewRecord.model_validate(inserted["review_json"]), True
                # A concurrent request for another analysis can own this global ID.
                existing = connection.execute(
                    "SELECT review_json FROM reviews WHERE review_id = %s", (request.review_id,)
                ).fetchone()
            if existing is None:
                raise StorageUnavailableError("Review retry could not be resolved")
            review = ReviewRecord.model_validate(existing["review_json"])
            if review.analysis_id != analysis_id or any(
                getattr(review, field) != getattr(request, field) for field in ReviewRequest.model_fields
            ):
                raise ReviewConflictError("Review ID is already used for another decision")
            return review, False
