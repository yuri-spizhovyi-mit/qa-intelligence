from typing import Protocol

from qa_intelligence.schemas import (
    AnalysisDraft,
    AnalysisMetadata,
    AnalysisRequest,
    AnalysisResponse,
)


class AnalysisProvider(Protocol):
    def analyze(self, request: AnalysisRequest) -> AnalysisDraft: ...


class FakeAnalysisProvider:
    """Deterministic fixture. Performs no semantic analysis and makes no external calls."""

    def analyze(self, request: AnalysisRequest) -> AnalysisDraft:
        questions = (
            []
            if request.acceptance_criteria
            else ["What acceptance criteria define success for this requirement?"]
        )
        return AnalysisDraft(
            questions=questions,
            risks=["Deterministic fixture only; no semantic analysis was performed."],
            test_cases=[],
            metadata=AnalysisMetadata(
                provider="fake",
                model="deterministic-v1",
                prompt_version="fake-v1",
                token_usage=None,
            ),
        )


class AnalysisService:
    def __init__(self, provider: AnalysisProvider) -> None:
        self._provider = provider

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        draft = self._provider.analyze(request)
        return AnalysisResponse(
            requirement_id=request.requirement_id,
            status="draft",
            questions=draft.questions,
            risks=draft.risks,
            test_cases=draft.test_cases,
            metadata=draft.metadata,
        )
