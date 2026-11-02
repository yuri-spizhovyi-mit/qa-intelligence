from fastapi import Depends, FastAPI

from qa_intelligence.analysis import AnalysisProvider, AnalysisService, FakeAnalysisProvider
from qa_intelligence.body_limit import ANALYSES_PATH, BodyLimitMiddleware
from qa_intelligence.schemas import AnalysisRequest, AnalysisResponse

app = FastAPI(title="QA Intelligence")
app.add_middleware(BodyLimitMiddleware)


def get_analysis_provider() -> AnalysisProvider:
    """Override in tests. Construction has no side effects; the fake provider is the only one."""
    return FakeAnalysisProvider()


@app.get("/health")
def health() -> dict[str, str]:
    """Process liveness only; makes no provider, database, or environment access."""
    return {"status": "ok"}


@app.post(
    ANALYSES_PATH,
    response_model=AnalysisResponse,
    summary="Analyze a requirement (FAKE deterministic provider)",
    description=(
        "FAKE MODE: this endpoint is backed by a deterministic fixture provider "
        "(`provider=fake`). It performs no AI or semantic analysis and generates no test "
        "cases. The result is a draft only. Request bodies are limited to 262144 bytes "
        "(HTTP 413), independently of the per-field character limits (HTTP 422)."
    ),
    responses={413: {"description": "Request body exceeds 262144 bytes"}},
)
def create_analysis(
    request: AnalysisRequest,
    provider: AnalysisProvider = Depends(get_analysis_provider),
) -> AnalysisResponse:
    return AnalysisService(provider).analyze(request)
