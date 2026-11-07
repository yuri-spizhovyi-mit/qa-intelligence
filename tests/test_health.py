from fastapi.testclient import TestClient

from qa_intelligence.main import app


def test_health_returns_ok_status_only():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
