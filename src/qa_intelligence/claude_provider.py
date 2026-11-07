from anthropic import Anthropic

from qa_intelligence.analysis import (
    RequirementFindings, TestCaseFindings, UnusableAnalysisError, analysis_instructions,
)
from qa_intelligence.schemas import AnalysisDraft, AnalysisMetadata, AnalysisRequest


class ClaudeAnalysisProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def analyze(self, request: AnalysisRequest) -> AnalysisDraft:
        output_schema = TestCaseFindings if request.generate_test_cases else RequirementFindings
        with Anthropic(
            api_key=self.api_key,
            base_url="https://api.anthropic.com",
            timeout=30.0,
            max_retries=0,
        ) as client:
            response = client.messages.create(
                model=self.model,
                max_tokens=3000 if request.generate_test_cases else 1000,
                system=analysis_instructions(request.generate_test_cases),
                messages=[{"role": "user", "content": request.model_dump_json()}],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": output_schema.model_json_schema(),
                    }
                },
            )
        if response.stop_reason != "end_turn":
            reason = (
                response.stop_reason
                if response.stop_reason in {"max_tokens", "refusal"}
                else "unexpected_stop"
            )
            raise UnusableAnalysisError(reason)
        text = "".join(block.text for block in response.content if block.type == "text")
        findings = output_schema.model_validate_json(text)
        return AnalysisDraft(
            questions=findings.questions,
            risks=findings.risks,
            test_cases=findings.test_cases if isinstance(findings, TestCaseFindings) else [],
            metadata=AnalysisMetadata(
                provider="anthropic",
                model=response.model,
                prompt_version="claude-test-case-drafts-v1" if request.generate_test_cases else "claude-requirements-review-v2",
                token_usage=response.usage.input_tokens + response.usage.output_tokens,
            ),
        )
