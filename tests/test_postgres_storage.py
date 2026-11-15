"""Synthetic PostgreSQL contract tests. Run only against disposable qi_test DB."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

psycopg = pytest.importorskip("psycopg")
from psycopg.conninfo import conninfo_to_dict

from qa_intelligence.analysis import AnalysisService, FakeAnalysisProvider
from qa_intelligence.main import app, get_analysis_provider, get_analysis_store
from qa_intelligence.postgres_store import PostgresAnalysisStore
from qa_intelligence.schemas import AnalysisRequest, ReviewRequest
from qa_intelligence.storage import AnalysisNotFoundError, ReviewConflictError, SQLiteAnalysisStore, StorageUnavailableError


@pytest.fixture
def store():
    dsn = os.getenv("QA_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("Disposable PostgreSQL test database is not configured")
    info = conninfo_to_dict(dsn)
    if info.get("dbname") != "qi_test" or info.get("host") != "postgres":
        pytest.fail("Tests require the isolated postgres/qi_test fixture")
    store = PostgresAnalysisStore(dsn)
    store.migrate()
    with psycopg.connect(dsn) as connection:
        connection.execute("TRUNCATE reviews, analyses RESTART IDENTITY")
    yield store


def saved(store):
    request = AnalysisRequest(
        requirement_id="ENERGY-TEST", text="Validate synthetic café meter events.",
        acceptance_criteria=[],
    )
    draft = AnalysisService(FakeAnalysisProvider()).analyze(request)
    return request, draft, store.save(request, draft)


def review(draft, **changes):
    return ReviewRequest(
        **({"review_id": uuid4(), "draft_sha256": draft.draft_sha256,
            "decision": "approved", "reviewer": "synthetic-reviewer"} | changes)
    )


def test_migration_is_versioned_and_repeatable(store):
    assert store.migrate() is False
    with psycopg.connect(store._dsn) as connection:
        rows = connection.execute("SELECT version, checksum FROM qi_schema_migrations").fetchall()
    assert len(rows) == 1 and rows[0][0] == 1 and len(rows[0][1]) == 64


def test_snapshot_and_digest_survive_new_adapter(store):
    request, draft, snapshot = saved(store)
    loaded = PostgresAnalysisStore(store._dsn).get(snapshot.analysis_id)
    assert loaded.request == request
    assert loaded.draft == snapshot
    assert loaded.review_status == "pending" and loaded.reviews == []
    canonical = json.dumps({
        "analysis_id": str(snapshot.analysis_id), "created_at": snapshot.created_at.isoformat(),
        "request": request.model_dump(mode="json"), "draft": draft.model_dump(mode="json"),
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert snapshot.draft_sha256 == hashlib.sha256(canonical.encode()).hexdigest()


def test_review_retries_preserve_history_and_latest_decision(store):
    _, _, snapshot = saved(store)
    first = review(snapshot)
    recorded, created = store.review(snapshot.analysis_id, first)
    assert created is True
    assert store.review(snapshot.analysis_id, first) == (recorded, False)
    changed = review(snapshot, decision="changes_requested", comment="Clarify units")
    store.review(snapshot.analysis_id, changed)
    assert store.review(snapshot.analysis_id, first) == (recorded, False)
    history = store.get(snapshot.analysis_id)
    assert history.review_status == "changes_requested"
    assert [item.review_id for item in history.reviews] == [first.review_id, changed.review_id]
    with pytest.raises(ReviewConflictError):
        store.review(snapshot.analysis_id, first.model_copy(update={"reviewer": "another-reviewer"}))
    assert len(store.get(snapshot.analysis_id).reviews) == 2


def test_digest_mismatch_does_not_append_review(store):
    _, _, snapshot = saved(store)
    with pytest.raises(ReviewConflictError):
        store.review(snapshot.analysis_id, review(snapshot, draft_sha256="0" * 64))
    assert store.get(snapshot.analysis_id).reviews == []


def test_concurrent_identical_reviews_append_once(store):
    _, _, snapshot = saved(store)
    request = review(snapshot)
    barrier = Barrier(2)

    def submit(_):
        barrier.wait(timeout=5)
        return PostgresAnalysisStore(store._dsn).review(snapshot.analysis_id, request)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(submit, range(2)))
    assert sorted(created for _, created in results) == [False, True]
    assert results[0][0] == results[1][0]
    assert len(store.get(snapshot.analysis_id).reviews) == 1


def test_concurrent_review_id_reuse_across_analyses_conflicts(store):
    snapshots = [saved(store)[2], saved(store)[2]]
    review_id = uuid4()
    barrier = Barrier(2)

    def submit(snapshot):
        barrier.wait(timeout=5)
        try:
            store.review(snapshot.analysis_id, review(snapshot, review_id=review_id))
            return "created"
        except ReviewConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(submit, snapshots))
    assert sorted(results) == ["conflict", "created"]
    assert sum(len(store.get(item.analysis_id).reviews) for item in snapshots) == 1


def test_unknown_analysis_cannot_be_read_or_reviewed(store):
    identifier = uuid4()
    with pytest.raises(AnalysisNotFoundError):
        store.get(identifier)
    with pytest.raises(AnalysisNotFoundError):
        store.review(identifier, ReviewRequest(
            review_id=uuid4(), draft_sha256="0" * 64, decision="approved", reviewer="synthetic"
        ))


def test_database_constraints_protect_review_identity_and_parent(store):
    _, _, snapshot = saved(store)
    recorded, _ = store.review(snapshot.analysis_id, review(snapshot))
    with psycopg.connect(store._dsn) as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.transaction():
                connection.execute(
                    "INSERT INTO reviews (review_id, analysis_id, review_json) VALUES (%s, %s, '{}'::jsonb)",
                    (recorded.review_id, snapshot.analysis_id),
                )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with connection.transaction():
                connection.execute(
                    "INSERT INTO reviews (review_id, analysis_id, review_json) VALUES (%s, %s, '{}'::jsonb)",
                    (uuid4(), uuid4()),
                )


def test_api_preserves_review_status_codes(store):
    app.dependency_overrides[get_analysis_store] = lambda: store
    app.dependency_overrides[get_analysis_provider] = FakeAnalysisProvider
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/analyses", json={
                "requirement_id": "ENERGY-API", "text": "Validate events", "acceptance_criteria": []
            })
            assert response.status_code == 200
            snapshot = response.json()
            url = f'/api/v1/analyses/{snapshot["analysis_id"]}/reviews'
            body = {"review_id": str(uuid4()), "draft_sha256": snapshot["draft_sha256"],
                    "decision": "approved", "reviewer": "synthetic"}
            first = client.post(url, json=body)
            assert first.status_code == 201
            retry = client.post(url, json=body)
            assert retry.status_code == 200 and retry.json() == first.json()
            assert client.post(url, json={**body, "reviewer": "different"}).status_code == 409
            assert client.get(f"/api/v1/analyses/{uuid4()}").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_database_outage_is_sanitized_and_health_stays_available():
    unavailable = PostgresAnalysisStore("host=127.0.0.1 port=1 dbname=qi_test user=qi_test")
    app.dependency_overrides[get_analysis_store] = lambda: unavailable
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/analyses/{uuid4()}")
            assert response.status_code == 503
            assert response.json() == {"detail": "Analysis storage is unavailable"}
            assert client.get("/health").json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()


def test_storage_backend_is_explicit_and_fail_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("QA_STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("QA_DATA_DIR", str(tmp_path))
    assert isinstance(get_analysis_store(), SQLiteAnalysisStore)
    monkeypatch.setenv("QA_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("QA_DATABASE_URL", raising=False)
    with pytest.raises(StorageUnavailableError):
        get_analysis_store()
    monkeypatch.setenv("QA_STORAGE_BACKEND", "unsupported")
    with pytest.raises(StorageUnavailableError):
        get_analysis_store()


def test_changed_installed_migration_checksum_is_rejected(store):
    with psycopg.connect(store._dsn) as connection:
        checksum = connection.execute("SELECT checksum FROM qi_schema_migrations WHERE version=1").fetchone()[0]
        connection.execute("UPDATE qi_schema_migrations SET checksum=%s WHERE version=1", ("0" * 64,))
    try:
        with pytest.raises(StorageUnavailableError):
            store.migrate()
    finally:
        with psycopg.connect(store._dsn) as connection:
            connection.execute("UPDATE qi_schema_migrations SET checksum=%s WHERE version=1", (checksum,))
