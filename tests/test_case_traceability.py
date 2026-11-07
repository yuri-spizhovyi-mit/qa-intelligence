from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from qa_intelligence.analysis import FakeAnalysisProvider
from qa_intelligence.main import app, get_analysis_provider
from qa_intelligence.schemas import AnalysisDraft, AnalysisMetadata

CASE = {
    "id": "TC-1",
    "title": "Reject an out-of-range energy value",
    "category": "negative",
    "preconditions": ["The remaining event fields are valid."],
    "steps": ["Submit an event with energy_wh=-1."],
    "expected_result": "HTTP 422",
    "source_criterion_ids": ["AC-1"],
}
REQUEST = {
    "requirement_id": "REQ-1",
    "text": "Validate energy events.",
    "acceptance_criteria": [
        {"id": "AC-1", "text": "Values below zero return HTTP 422."}
    ],
    "generate_test_cases": True,
}


@pytest.mark.parametrize(
    "scenario, expected_status",
    [
        ("valid", 200),
        ("unknown_reference", 502),
        ("duplicate_case_id", 502),
        ("missing_reference", 502),
        ("missing_steps", 502),
        ("too_many_cases", 502),
        ("not_requested", 502),
    ],
)
def test_case_drafts_require_valid_structure_and_traceability(scenario, expected_status):
    case = deepcopy(CASE)
    request = deepcopy(REQUEST)
    if scenario == "unknown_reference":
        case["source_criterion_ids"] = ["AC-UNKNOWN"]
    if scenario == "missing_reference":
        case["source_criterion_ids"] = []
    if scenario == "missing_steps":
        case["steps"] = []
    if scenario == "not_requested":
        request["generate_test_cases"] = False
    cases = [case]
    if scenario == "duplicate_case_id":
        cases = [case, deepcopy(case)]
    if scenario == "too_many_cases":
        cases = [{**case, "id": f"TC-{index}"} for index in range(13)]

    class StubProvider(FakeAnalysisProvider):
        def analyze(self, request):
            return AnalysisDraft(
                questions=[], risks=[], test_cases=cases,
                metadata=AnalysisMetadata(provider="fake", model="stub", prompt_version="stub"),
            )

    app.dependency_overrides[get_analysis_provider] = StubProvider
    try:
        response = TestClient(app).post("/api/v1/analyses", json=request)
        assert response.status_code == expected_status
        if expected_status == 200:
            assert response.json()["status"] == "draft"
            assert response.json()["test_cases"] == [CASE]
        else:
            assert response.json() == {"detail": "Analysis provider did not return a usable draft"}
    finally:
        app.dependency_overrides.clear()
