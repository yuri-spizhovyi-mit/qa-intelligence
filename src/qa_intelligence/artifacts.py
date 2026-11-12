"""Generate one constrained M3 artifact without importing or executing its code."""

import hashlib
import base64
import json
import re
import sys
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from qa_intelligence.schemas import AnalysisRecord, DraftTestCase


class ArtifactBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_id: UUID
    draft_sha256: str
    case: DraftTestCase
    scenario: str
    code: str
    artifact_sha256: str


def generate_lower_boundary(record: AnalysisRecord, case_id: str) -> ArtifactBundle:
    if (
        record.review_status != "approved"
        or not record.reviews
        or record.reviews[-1].decision != "approved"
        or record.reviews[-1].draft_sha256 != record.draft.draft_sha256
    ):
        raise ValueError("An approved analysis snapshot is required")
    case = next((case for case in record.draft.test_cases if case.id == case_id), None)
    if case is None:
        raise ValueError("Case ID does not exist in the approved snapshot")
    if (
        case.category != "boundary"
        or not re.search(r"\b201\b", case.expected_result)
        or not any(re.search(r"\b0\b", step) for step in case.steps)
    ):
        raise ValueError("Only the explicit lower-boundary/HTTP 201 scenario is supported")
    source = {
        "analysis_id": str(record.draft.analysis_id),
        "draft_sha256": record.draft.draft_sha256,
        "case_id": case.id,
        "source_criterion_ids": case.source_criterion_ids,
    }
    code = (
        "import json\n"
        "from uuid import uuid4\n"
        "\n"
        "from playwright.sync_api import expect\n"
        "from runner_contract import ProductFailure\n"
        "\n"
        f"SOURCE = {source!r}\n"
        "\n"
        "\n"
        "def run(page):\n"
        '    page.goto("http://demo:8000/", wait_until="domcontentloaded")\n'
        "    payload = {\n"
        '        "event_id": str(uuid4()),\n'
        '        "device_id": "meter-playwright-01",\n'
        '        "occurred_at": "2026-03-02T09:15:00Z",\n'
        '        "energy_wh": 0,\n'
        "    }\n"
        '    page.get_by_label("Event JSON", exact=True).fill(json.dumps(payload))\n'
        "    with page.expect_response(\n"
        '        lambda response: response.url == "http://demo:8000/v1/events"\n'
        '        and response.request.method == "POST"\n'
        "    ) as submitted:\n"
        '        page.get_by_role("button", name="Submit event", exact=True).click()\n'
        "    if submitted.value.status != 201:\n"
        '        raise ProductFailure(f"Expected HTTP 201, observed {submitted.value.status}")\n'
        '    expect(page.get_by_role("status")).to_have_text("HTTP 201")\n'
    )
    return ArtifactBundle(
        analysis_id=record.draft.analysis_id,
        draft_sha256=record.draft.draft_sha256,
        case=case,
        scenario="energy_lower_boundary_v1",
        code=code,
        artifact_sha256=hashlib.sha256(code.encode("utf-8")).hexdigest(),
    )


def verify_artifact_review(bundle_bytes: bytes, receipt: dict) -> ArtifactBundle:
    """Local operator receipt binds both manifest bytes and executable code."""
    reviewer = receipt.get("reviewer")
    if receipt.get("decision") != "approved" or not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("Explicit executable-artifact approval is required")
    if hashlib.sha256(bundle_bytes).hexdigest() != receipt.get("bundle_sha256"):
        raise ValueError("Bundle changed after review")
    bundle = ArtifactBundle.model_validate_json(bundle_bytes)
    digest = hashlib.sha256(bundle.code.encode("utf-8")).hexdigest()
    if digest != bundle.artifact_sha256 or digest != receipt.get("artifact_sha256"):
        raise ValueError("Executable artifact changed after review")
    return bundle


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m qa_intelligence.artifacts CASE_ID < approved-record.json")
    if sys.argv[1] == "--verify":
        packet = json.loads(sys.stdin.read())
        bundle = verify_artifact_review(
            base64.b64decode(packet["bundle_base64"], validate=True), packet["receipt"]
        )
        print(bundle.model_dump_json(indent=2))
    else:
        record = AnalysisRecord.model_validate_json(sys.stdin.read())
        print(generate_lower_boundary(record, sys.argv[1]).model_dump_json(indent=2))
