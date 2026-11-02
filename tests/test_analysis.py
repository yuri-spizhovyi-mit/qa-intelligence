import pytest
from fastapi.testclient import TestClient

from qa_intelligence.analysis import FakeAnalysisProvider
from qa_intelligence.main import app, get_analysis_provider

URL = "/api/v1/analyses"
VALID = {
    "requirement_id": " REQ-1 ",
    "text": "  Energy events require energy_wh between 0 and 25000.  ",
    "acceptance_criteria": [{"id": " AC-1 ", "text": " Out-of-range values are rejected. "}],
}


class SpyProvider(FakeAnalysisProvider):
    def __init__(self):
        self.calls = []

    def analyze(self, request):
        self.calls.append(request)
        return super().analyze(request)


@pytest.fixture
def spy():
    provider = SpyProvider()
    app.dependency_overrides[get_analysis_provider] = lambda: provider
    yield provider
    app.dependency_overrides.clear()


def test_valid_request_is_normalized_and_labeled_fake(spy):
    response = TestClient(app).post(URL, json=VALID)
    assert response.status_code == 200
    body = response.json()
    assert body["requirement_id"] == "REQ-1"
    assert body["status"] == "draft"
    assert body["questions"] == []
    assert body["test_cases"] == []
    assert body["metadata"] == {
        "provider": "fake",
        "model": "deterministic-v1",
        "prompt_version": "fake-v1",
        "token_usage": None,
    }
    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call.requirement_id == "REQ-1"
    assert call.text == "Energy events require energy_wh between 0 and 25000."
    assert call.acceptance_criteria[0].id == "AC-1"
    assert call.acceptance_criteria[0].text == "Out-of-range values are rejected."


def test_empty_criteria_accepted_with_clarification_question(spy):
    response = TestClient(app).post(URL, json={**VALID, "acceptance_criteria": []})
    assert response.status_code == 200
    assert response.json()["questions"] == [
        "What acceptance criteria define success for this requirement?"
    ]
    assert len(spy.calls) == 1


def _without(key):
    return {k: v for k, v in VALID.items() if k != key}


@pytest.mark.parametrize(
    "payload",
    [
        _without("text"),
        {**VALID, "text": "   "},
        {**VALID, "text": "x" * 10001},
        {**VALID, "text": 123},
        {
            **VALID,
            "acceptance_criteria": [
                {"id": "AC-1", "text": "a"},
                {"id": " AC-1 ", "text": "b"},
            ],
        },
    ],
)
def test_invalid_input_is_422_without_provider_call(spy, payload):
    assert TestClient(app).post(URL, json=payload).status_code == 422
    assert spy.calls == []


def test_oversized_body_is_413_without_provider_call(spy):
    client = TestClient(app)
    big = {**VALID, "text": "x" * 262144}
    assert client.post(URL, json=big).status_code == 413

    chunks = iter([b"x" * 150000, b"x" * 150000])  # chunked, no Content-Length
    assert client.post(URL, content=chunks).status_code == 413
    assert spy.calls == []
