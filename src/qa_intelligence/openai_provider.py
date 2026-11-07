from openai import OpenAI
from qa_intelligence.analysis import (
    RequirementFindings, TestCaseFindings, UnusableAnalysisError, analysis_instructions,
)

from qa_intelligence.schemas import AnalysisDraft, AnalysisMetadata, AnalysisRequest


class OpenAIAnalysisProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def analyze(self, request: AnalysisRequest) -> AnalysisDraft:
        output_schema = TestCaseFindings if request.generate_test_cases else RequirementFindings
        with OpenAI(
            api_key=self.api_key,
            base_url="https://api.openai.com/v1",
            timeout=20.0,
            max_retries=0,
        ) as client:
            response = client.responses.parse(
                model=self.model,
                instructions=analysis_instructions(request.generate_test_cases),
                input=request.model_dump_json(),
                text_format=output_schema,
                store=False,
                max_output_tokens=3000 if request.generate_test_cases else 1000,
            )

        findings = response.output_parsed
        if response.status != "completed" or findings is None:
            raise UnusableAnalysisError
        return AnalysisDraft(
            questions=findings.questions,
            risks=findings.risks,
            test_cases=findings.test_cases if isinstance(findings, TestCaseFindings) else [],
            metadata=AnalysisMetadata(
                provider="openai",
                model=response.model,
                prompt_version="test-case-drafts-v1" if request.generate_test_cases else "requirements-review-v2",
                token_usage=response.usage.total_tokens if response.usage else None,
            ),
        )
