import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError

from qa_intelligence.schemas import (
    AnalysisRecord, AnalysisRequest, AnalysisResponse, ReviewRecord,
    ReviewRequest, SavedAnalysisResponse,
)


class AnalysisNotFoundError(LookupError):
    pass


class ReviewConflictError(Exception):
    pass


class StorageUnavailableError(Exception):
    pass


class AnalysisStore(Protocol):
    def save(self, request: AnalysisRequest, draft: AnalysisResponse) -> SavedAnalysisResponse: ...
    def get(self, analysis_id: UUID) -> AnalysisRecord: ...
    def review(self, analysis_id: UUID, request: ReviewRequest) -> tuple[ReviewRecord, bool]: ...


class SQLiteAnalysisStore:
    """Immutable analysis snapshots and append-only review history."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _connection(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=5.0)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS analyses (
                        analysis_id TEXT PRIMARY KEY,
                        request_json TEXT NOT NULL,
                        draft_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS reviews (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        review_id TEXT NOT NULL UNIQUE,
                        analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id),
                        review_json TEXT NOT NULL
                    );
                """)
                with connection:
                    yield connection
        except (OSError, sqlite3.Error, ValidationError, ValueError) as exc:
            raise StorageUnavailableError from exc

    def save(self, request: AnalysisRequest, draft: AnalysisResponse) -> SavedAnalysisResponse:
        analysis_id = uuid4()
        created_at = datetime.now(timezone.utc)
        content = {
            "analysis_id": str(analysis_id),
            "created_at": created_at.isoformat(),
            "request": request.model_dump(mode="json"),
            "draft": draft.model_dump(mode="json"),
        }
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        saved = SavedAnalysisResponse(
            **draft.model_dump(),
            analysis_id=analysis_id,
            created_at=created_at,
            draft_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO analyses (analysis_id, request_json, draft_json) VALUES (?, ?, ?)",
                (str(analysis_id), request.model_dump_json(), saved.model_dump_json()),
            )
        return saved

    def get(self, analysis_id: UUID) -> AnalysisRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT request_json, draft_json FROM analyses WHERE analysis_id = ?",
                (str(analysis_id),),
            ).fetchone()
            if row is None:
                raise AnalysisNotFoundError
            reviews = [
                ReviewRecord.model_validate_json(item["review_json"])
                for item in connection.execute(
                    "SELECT review_json FROM reviews WHERE analysis_id = ? ORDER BY sequence",
                    (str(analysis_id),),
                )
            ]
            return AnalysisRecord(
                request=AnalysisRequest.model_validate_json(row["request_json"]),
                draft=SavedAnalysisResponse.model_validate_json(row["draft_json"]),
                review_status=reviews[-1].decision if reviews else "pending",
                reviews=reviews,
            )

    def review(self, analysis_id: UUID, request: ReviewRequest) -> tuple[ReviewRecord, bool]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT draft_json FROM analyses WHERE analysis_id = ?", (str(analysis_id),)
            ).fetchone()
            if row is None:
                raise AnalysisNotFoundError
            draft = SavedAnalysisResponse.model_validate_json(row["draft_json"])
            if request.draft_sha256 != draft.draft_sha256:
                raise ReviewConflictError("Review digest does not match the saved draft")
            existing = connection.execute(
                "SELECT review_json FROM reviews WHERE review_id = ?", (str(request.review_id),)
            ).fetchone()
            if existing:
                review = ReviewRecord.model_validate_json(existing["review_json"])
                same_request = all(
                    getattr(review, field) == getattr(request, field)
                    for field in ReviewRequest.model_fields
                )
                if review.analysis_id != analysis_id or not same_request:
                    raise ReviewConflictError("Review ID is already used for another decision")
                return review, False
            review = ReviewRecord(
                **request.model_dump(),
                analysis_id=analysis_id,
                created_at=datetime.now(timezone.utc),
            )
            connection.execute(
                "INSERT INTO reviews (review_id, analysis_id, review_json) VALUES (?, ?, ?)",
                (str(review.review_id), str(analysis_id), review.model_dump_json()),
            )
            return review, True
