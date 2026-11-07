from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from qa_intelligence.analysis import FakeAnalysisProvider, UnusableAnalysisError
from qa_intelligence.main import app, get_analysis_provider, get_analysis_store
from qa_intelligence.schemas import ReviewRequest
from qa_intelligence.storage import SQLiteAnalysisStore

URL = "/api/v1/analyses"
REQUEST = {
    "requirement_id": "REQ-1", "text": " Validate energy events. ",
    "acceptance_criteria": [],
}


@pytest.fixture
def store(tmp_path):
    return SQLiteAnalysisStore(tmp_path / "analyses.sqlite3")


@pytest.fixture
def client(store):
    app.dependency_overrides[get_analysis_store] = lambda: SQLiteAnalysisStore(store.path)
    app.dependency_overrides[get_analysis_provider] = FakeAnalysisProvider
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def create(client):
    response = client.post(URL, json=REQUEST)
    assert response.status_code == 200
    return response.json()


def review_body(saved):
    return {
        "review_id": str(uuid4()), "draft_sha256": saved["draft_sha256"],
        "decision": "approved", "reviewer": "reviewer-1",
    }


def test_saved_input_and_draft_survive_new_store_instances(client):
    saved = create(client)
    record = client.get(f'{URL}/{saved["analysis_id"]}').json()
    assert record["draft"] == saved
    assert record["request"]["text"] == "Validate energy events."
    assert record["review_status"] == "pending"
    assert record["reviews"] == []
    assert len(saved["draft_sha256"]) == 64


def test_review_history_digest_and_retry_behavior(client):
    saved = create(client)
    url = f'{URL}/{saved["analysis_id"]}/reviews'
    body = review_body(saved)
    first = client.post(url, json=body)
    assert first.status_code == 201
    replay = client.post(url, json=body)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    conflict = {**body, "decision": "changes_requested", "comment": "Clarify acceptance."}
    assert client.post(url, json=conflict).status_code == 409
    assert client.post(url, json={**review_body(saved), "draft_sha256": "0" * 64}).status_code == 409
    change = {
        **review_body(saved), "decision": "changes_requested", "comment": "Clarify acceptance."
    }
    assert client.post(url, json=change).status_code == 201
    assert client.post(url, json=body).status_code == 200
    record = client.get(f'{URL}/{saved["analysis_id"]}').json()
    assert record["draft"] == saved
    assert record["review_status"] == "changes_requested"
    assert [item["decision"] for item in record["reviews"]] == ["approved", "changes_requested"]


@pytest.mark.parametrize("identifier, status", [(str(uuid4()), 404), ("invalid-id", 422)])
def test_unknown_and_malformed_ids(client, identifier, status):
    assert client.get(f"{URL}/{identifier}").status_code == status
    body = review_body({"draft_sha256": "0" * 64})
    assert client.post(f"{URL}/{identifier}/reviews", json=body).status_code == status


@pytest.mark.parametrize("changes", [
    {"decision": "unknown"},
    {"reviewer": "   "},
    {"draft_sha256": "invalid"},
    {"decision": "changes_requested", "comment": "   "},
])
def test_invalid_reviews_do_not_change_history(client, changes):
    saved = create(client)
    body = {**review_body(saved), **changes}
    assert client.post(f'{URL}/{saved["analysis_id"]}/reviews', json=body).status_code == 422
    assert client.get(f'{URL}/{saved["analysis_id"]}').json()["reviews"] == []


def test_concurrent_identical_reviews_are_saved_once(client, store):
    saved = create(client)
    request = ReviewRequest(**review_body(saved))
    analysis_id = store.get(saved["analysis_id"]).draft.analysis_id
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: store.review(analysis_id, request), range(2)))
    assert sorted(created for _, created in results) == [False, True]
    assert len(store.get(analysis_id).reviews) == 1


def test_failed_provider_does_not_save_an_analysis(client, store):
    class FailedProvider(FakeAnalysisProvider):
        def analyze(self, request):
            raise UnusableAnalysisError("invalid_output")

    app.dependency_overrides[get_analysis_provider] = FailedProvider
    assert client.post(URL, json=REQUEST).status_code == 502
    assert not store.path.exists()


def test_unusable_storage_is_503_and_health_still_works(client, store):
    store.path.write_text("not a SQLite database")
    response = client.post(URL, json=REQUEST)
    assert response.status_code == 503
    assert response.json() == {"detail": "Analysis storage is unavailable"}
    assert client.get("/health").json() == {"status": "ok"}


def test_oversized_review_is_rejected_before_storage(client, store):
    response = client.post(
        f"{URL}/{uuid4()}/reviews", content=b"x" * 262145,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert not store.path.exists()
