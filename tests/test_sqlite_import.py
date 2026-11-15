"""Reviewed synthetic import checks; only disposable postgres/qi_test is allowed."""

import hashlib
import json
import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.conninfo import conninfo_to_dict

from qa_intelligence.analysis import AnalysisService, FakeAnalysisProvider
from qa_intelligence.import_sqlite import ImportRejectedError, import_sqlite, inspect_postgres, inspect_sqlite, main
from qa_intelligence.postgres_store import PostgresAnalysisStore
from qa_intelligence.schemas import AnalysisRequest, ReviewRequest
from qa_intelligence.storage import SQLiteAnalysisStore, StorageUnavailableError


def target():
    dsn = os.getenv("QA_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("Disposable PostgreSQL fixture is not configured")
    info = conninfo_to_dict(dsn)
    if info.get("dbname") != "qi_test" or info.get("host") != "postgres":
        pytest.fail("Import tests require isolated postgres/qi_test")
    store = PostgresAnalysisStore(dsn)
    store.migrate()
    return store


@pytest.fixture
def store():
    store = target()
    with psycopg.connect(store._dsn) as connection:
        connection.execute("TRUNCATE reviews, analyses RESTART IDENTITY")
    return store


def make_source(tmp_path, second_reviewer="synthetic"):
    source = SQLiteAnalysisStore(tmp_path / "source.sqlite3")
    identifiers = []
    for number in range(2):
        request = AnalysisRequest(
            requirement_id=f"ENERGY-{number}", text="Validate a synthetic café meter event.",
            acceptance_criteria=[],
        )
        draft = AnalysisService(FakeAnalysisProvider()).analyze(request)
        saved = source.save(request, draft)
        identifiers.append(saved.analysis_id)
        source.review(saved.analysis_id, ReviewRequest(
            review_id=uuid4(), draft_sha256=saved.draft_sha256,
            decision="approved", reviewer="synthetic",
        ))
        if number == 0:
            source.review(saved.analysis_id, ReviewRequest(
                review_id=uuid4(), draft_sha256=saved.draft_sha256, decision="changes_requested",
                reviewer=second_reviewer, comment="Clarify the event unit.",
            ))
    return source, identifiers


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_import_preserves_exact_records_and_source_bytes(store, tmp_path):
    source, identifiers = make_source(tmp_path)
    before = file_hash(source.path)
    report = import_sqlite(source.path, store)
    assert report["imported"] is True
    assert report["analyses"] == 2 and report["reviews"] == 3
    assert inspect_postgres(store) == inspect_sqlite(source.path)
    for identifier in identifiers:
        assert store.get(identifier) == source.get(identifier)
    assert file_hash(source.path) == before


def test_identical_import_and_old_review_retry_do_not_append(store, tmp_path):
    source, identifiers = make_source(tmp_path)
    first = import_sqlite(source.path, store)
    retry = import_sqlite(source.path, store)
    assert first["content_sha256"] == retry["content_sha256"]
    assert retry["imported"] is False
    old_review = source.get(identifiers[0]).reviews[0]
    request = ReviewRequest(**{key: getattr(old_review, key) for key in ReviewRequest.model_fields})
    assert store.review(identifiers[0], request) == (old_review, False)
    assert store.get(identifiers[0]).review_status == "changes_requested"
    assert inspect_postgres(store)["reviews"] == 3


def test_different_target_is_rejected_without_overwrite(store, tmp_path):
    source, identifiers = make_source(tmp_path)
    import_sqlite(source.path, store)
    snapshot = store.get(identifiers[0]).draft
    store.review(snapshot.analysis_id, ReviewRequest(
        review_id=uuid4(), draft_sha256=snapshot.draft_sha256, decision="approved", reviewer="later-reviewer"
    ))
    before = inspect_postgres(store)
    with pytest.raises(ImportRejectedError):
        import_sqlite(source.path, store)
    assert inspect_postgres(store) == before


def test_corrupt_analysis_digest_rejects_before_target_writes(store, tmp_path):
    source, identifiers = make_source(tmp_path)
    with sqlite3.connect(source.path) as connection:
        row = connection.execute("SELECT draft_json FROM analyses WHERE analysis_id=?", (str(identifiers[0]),)).fetchone()
        payload = json.loads(row[0])
        payload["risks"].append("Changed after digest creation")
        connection.execute("UPDATE analyses SET draft_json=? WHERE analysis_id=?", (json.dumps(payload), str(identifiers[0])))
    with pytest.raises(ImportRejectedError):
        import_sqlite(source.path, store)
    assert inspect_postgres(store)["analyses"] == 0


def test_corrupt_review_digest_rejects_source(store, tmp_path):
    source, _ = make_source(tmp_path)
    with sqlite3.connect(source.path) as connection:
        row = connection.execute("SELECT sequence, review_json FROM reviews ORDER BY sequence LIMIT 1").fetchone()
        payload = json.loads(row[1])
        payload["draft_sha256"] = "0" * 64
        connection.execute("UPDATE reviews SET review_json=? WHERE sequence=?", (json.dumps(payload), row[0]))
    with pytest.raises(ImportRejectedError):
        import_sqlite(source.path, store)
    assert inspect_postgres(store)["analyses"] == 0


def test_failed_review_insert_rolls_back_entire_transfer(store, tmp_path):
    source, _ = make_source(tmp_path, second_reviewer="blocked-fixture")
    with psycopg.connect(store._dsn) as connection:
        connection.execute("ALTER TABLE reviews ADD CONSTRAINT fixture_reject_reviewer CHECK (review_json->>'reviewer' <> 'blocked-fixture')")
    try:
        with pytest.raises(StorageUnavailableError):
            import_sqlite(source.path, store)
        summary = inspect_postgres(store)
        assert summary["analyses"] == summary["reviews"] == 0
    finally:
        with psycopg.connect(store._dsn) as connection:
            connection.execute("ALTER TABLE reviews DROP CONSTRAINT fixture_reject_reviewer")


def test_concurrent_identical_imports_are_idempotent(store, tmp_path):
    source, _ = make_source(tmp_path)
    barrier = Barrier(2)

    def transfer(_):
        barrier.wait(timeout=5)
        return import_sqlite(source.path, PostgresAnalysisStore(store._dsn))

    with ThreadPoolExecutor(max_workers=2) as workers:
        reports = list(workers.map(transfer, range(2)))
    assert sorted(report["imported"] for report in reports) == [False, True]
    assert inspect_postgres(store) == inspect_sqlite(source.path)


def test_missing_source_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(ImportRejectedError):
        inspect_sqlite(path)
    assert not path.exists()


def test_validate_only_cli_needs_no_target_and_prints_no_content(tmp_path, monkeypatch, capsys):
    source, _ = make_source(tmp_path)
    monkeypatch.delenv("QA_DATABASE_URL", raising=False)
    assert main(["--sqlite", str(source.path)]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["mode"] == "validate-only" and report["analyses"] == 2
    assert "café" not in output and "Clarify" not in output
    assert main(["--sqlite", str(source.path), "--apply"]) == 1


def test_target_outage_leaves_source_unchanged(tmp_path):
    source, _ = make_source(tmp_path)
    before = file_hash(source.path)
    unavailable = PostgresAnalysisStore("host=127.0.0.1 port=1 dbname=qi_test user=qi_test")
    with pytest.raises(StorageUnavailableError):
        import_sqlite(source.path, unavailable)
    assert file_hash(source.path) == before


def test_durability_prepare(tmp_path):
    if os.getenv("QA_IMPORT_PROOF_PHASE") != "prepare":
        pytest.skip("Selected separately before disposable database replacement")
    store = target()
    with psycopg.connect(store._dsn) as connection:
        connection.execute("TRUNCATE reviews, analyses RESTART IDENTITY")
    source, _ = make_source(tmp_path)
    import_sqlite(source.path, store)
    report = inspect_postgres(store)
    assert report == inspect_sqlite(source.path)
    print("IMPORT_PROOF=" + json.dumps(report, sort_keys=True))


def test_durability_verify():
    if os.getenv("QA_IMPORT_PROOF_PHASE") != "verify":
        pytest.skip("Selected separately after disposable database replacement")
    expected = os.environ.get("QA_EXPECTED_IMPORT_DIGEST", "")
    assert re.fullmatch(r"[0-9a-f]{64}", expected)
    store = target()
    report = inspect_postgres(store)
    assert report == {"analyses": 2, "reviews": 3, "content_sha256": expected}
    with psycopg.connect(store._dsn) as connection:
        identifier = connection.execute("SELECT analysis_id FROM analyses ORDER BY analysis_id LIMIT 1").fetchone()[0]
    before = store.get(identifier)
    request = ReviewRequest(
        review_id=uuid4(), draft_sha256=before.draft.draft_sha256,
        decision="approved", reviewer="after-replacement",
    )
    created, inserted = store.review(identifier, request)
    assert inserted is True
    assert store.get(identifier).reviews == [*before.reviews, created]
    assert inspect_postgres(store)["reviews"] == 4
