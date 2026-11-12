from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from demo_energy_hub import create_app

EVENT = {
    "event_id": "8d0e6a52-3c1f-4b8e-a7d2-91f0c4e5b6a3",
    "device_id": "  meter-demo-01 ",
    "occurred_at": "2026-03-02T10:15:00+01:00",
    "energy_wh": 212,
}


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


def test_create_normalize_and_retrieve_event(client):
    response = client.post("/v1/events", json=EVENT)
    assert response.status_code == 201
    assert response.headers["location"] == f'/v1/events/{EVENT["event_id"]}'
    assert response.json() == {
        **EVENT, "device_id": "meter-demo-01", "occurred_at": "2026-03-02T09:15:00Z"
    }
    assert client.get(response.headers["location"]).json() == response.json()


@pytest.mark.parametrize("value", [0, 25000])
def test_inclusive_energy_boundaries(client, value):
    assert client.post("/v1/events", json={**EVENT, "energy_wh": value}).status_code == 201


@pytest.mark.parametrize("field, value", [
    ("energy_wh", -1), ("energy_wh", 25001),
    ("energy_wh", 10.5), ("energy_wh", 10.0), ("energy_wh", "10"),
    ("energy_wh", True), ("energy_wh", False), ("energy_wh", None),
    ("device_id", ""), ("device_id", "   "), ("device_id", 123), ("device_id", None),
    ("occurred_at", "2026-03-02T10:15:00"), ("occurred_at", 1772446500),
    ("occurred_at", "2026-03-02T10:15:00+01:99"),
    ("occurred_at", "2026-03-02T10:15:00.1234567Z"),
    ("event_id", "invalid-id"),
])
def test_invalid_input_is_not_stored(client, field, value):
    assert client.post("/v1/events", json={**EVENT, field: value}).status_code == 422
    assert client.get(f'/v1/events/{EVENT["event_id"]}').status_code == 404


@pytest.mark.parametrize("field", list(EVENT))
def test_required_fields(client, field):
    payload = {key: value for key, value in EVENT.items() if key != field}
    assert client.post("/v1/events", json=payload).status_code == 422
    assert client.get(f'/v1/events/{EVENT["event_id"]}').status_code == 404


def test_equivalent_normalized_replay(client):
    original = client.post("/v1/events", json=EVENT)
    replay = client.post("/v1/events", json={
        **EVENT,
        "event_id": EVENT["event_id"].upper(),
        "device_id": "meter-demo-01",
        "occurred_at": "2026-03-02T09:15:00Z",
    })
    assert original.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == original.json()


def test_conflicting_and_invalid_replays_preserve_original(client):
    original = client.post("/v1/events", json=EVENT).json()
    assert client.post("/v1/events", json={**EVENT, "energy_wh": 213}).status_code == 409
    assert client.post("/v1/events", json={**EVENT, "energy_wh": "212"}).status_code == 422
    assert client.get(f'/v1/events/{EVENT["event_id"]}').json() == original


@pytest.mark.parametrize("identifier, status", [
    (EVENT["event_id"], 404), ("invalid-id", 422),
])
def test_unknown_and_malformed_lookup(client, identifier, status):
    assert client.get(f"/v1/events/{identifier}").status_code == status


def test_new_app_instance_has_no_previous_events(client):
    assert client.post("/v1/events", json=EVENT).status_code == 201
    with TestClient(create_app()) as restarted:
        assert restarted.get(f'/v1/events/{EVENT["event_id"]}').status_code == 404


def test_concurrent_equivalent_submissions():
    app = create_app()

    def submit(_):
        with TestClient(app) as client:
            return client.post("/v1/events", json=EVENT).status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(submit, range(2))) == [200, 201]


def test_browser_page_is_available(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Event JSON" in response.text
    assert "Retrieve event" in response.text
    assert "cleared when the demo restarts" in response.text
