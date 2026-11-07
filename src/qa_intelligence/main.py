import logging
import os

import anthropic
from fastapi import Depends, FastAPI, HTTPException
from openai import APIError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from qa_intelligence.analysis import (
    AnalysisProvider, AnalysisService, FakeAnalysisProvider, UnusableAnalysisError,
)
from qa_intelligence.body_limit import ANALYSES_PATH, BodyLimitMiddleware
from qa_intelligence.claude_provider import ClaudeAnalysisProvider
from qa_intelligence.openai_provider import OpenAIAnalysisProvider
from qa_intelligence.schemas import AnalysisRequest, AnalysisResponse

app = FastAPI(title="QA Intelligence")
app.add_middleware(BodyLimitMiddleware)
logger = logging.getLogger("uvicorn.error")


def get_analysis_provider() -> AnalysisProvider | None:
    mode = os.getenv("QA_ANALYSIS_PROVIDER", "fake")
    if mode == "fake":
        return FakeAnalysisProvider()
    if mode == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        model = os.getenv("QA_CLAUDE_MODEL", "").strip()
        return ClaudeAnalysisProvider(key, model) if key and model else None
    key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("QA_OPENAI_MODEL", "").strip()
    if mode == "openai" and key and model:
        return OpenAIAnalysisProvider(key, model)
    return None


@app.get("/health")
def health() -> dict[str, str]:
    """Process liveness only; makes no provider, database, or environment access."""
    return {"status": "ok"}


@app.post(
    ANALYSES_PATH,
    response_model=AnalysisResponse,
    summary="Analyze a requirement",
    description=(
        "Returns a draft. The default fake provider returns deterministic fixtures. "
        "Claude or OpenAI configuration enables model analysis. See metadata.provider. "
        "Request bodies are limited to 262144 bytes "
        "(HTTP 413), independently of the per-field character limits (HTTP 422)."
    ),
    responses={
        413: {"description": "Request body exceeds 262144 bytes"},
        502: {"description": "Analysis provider failed or returned an unusable draft"},
        503: {"description": "Analysis provider configuration is invalid"},
        504: {"description": "Analysis provider timed out"},
    },
)
def create_analysis(
    request: AnalysisRequest,
    provider: AnalysisProvider | None = Depends(get_analysis_provider),
) -> AnalysisResponse:
    if provider is None:
        raise HTTPException(503, "Analysis provider configuration is incomplete or invalid")
    try:
        return AnalysisService(provider).analyze(request)
    except (APITimeoutError, anthropic.APITimeoutError):
        raise HTTPException(504, "Analysis provider timed out") from None
    except (APIError, anthropic.APIError, ValidationError, UnusableAnalysisError) as exc:
        status = "unavailable"
        if isinstance(exc, (APIStatusError, anthropic.APIStatusError)):
            status = exc.status_code
        logger.warning(
            "Analysis provider failed: category=%s upstream_status=%s",
            type(exc).__name__,
            status,
        )
        raise HTTPException(502, "Analysis provider did not return a usable draft") from None
