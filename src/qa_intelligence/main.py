import logging
import os
from pathlib import Path
from uuid import UUID

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from openai import APIError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from qa_intelligence.analysis import (
    AnalysisProvider, AnalysisService, FakeAnalysisProvider, UnusableAnalysisError,
)
from qa_intelligence.body_limit import ANALYSES_PATH, BodyLimitMiddleware
from qa_intelligence.claude_provider import ClaudeAnalysisProvider
from qa_intelligence.openai_provider import OpenAIAnalysisProvider
from qa_intelligence.schemas import (
    AnalysisRecord, AnalysisRequest, ReviewRecord, ReviewRequest, SavedAnalysisResponse,
)
from qa_intelligence.storage import (
    AnalysisNotFoundError, AnalysisStore, ReviewConflictError, SQLiteAnalysisStore,
    StorageUnavailableError,
)

app = FastAPI(title="QA Intelligence")
app.add_middleware(BodyLimitMiddleware)
logger = logging.getLogger("uvicorn.error")


def get_analysis_store() -> AnalysisStore:
    directory = Path(os.getenv("QA_DATA_DIR", "/tmp/qa-intelligence"))
    return SQLiteAnalysisStore(directory / "analyses.sqlite3")


@app.exception_handler(StorageUnavailableError)
def storage_unavailable(request: Request, exc: StorageUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Analysis storage is unavailable"})


@app.exception_handler(AnalysisNotFoundError)
def analysis_not_found(request: Request, exc: AnalysisNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Analysis not found"})


@app.exception_handler(ReviewConflictError)
def review_conflict(request: Request, exc: ReviewConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


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
    response_model=SavedAnalysisResponse,
    summary="Analyze a requirement",
    description=(
        "Saves an immutable draft with its input and returns its ID and content digest. "
        "The default fake provider returns deterministic fixtures. "
        "Claude or OpenAI configuration enables model analysis. See metadata.provider. "
        "Request bodies are limited to 262144 bytes "
        "(HTTP 413), independently of the per-field character limits (HTTP 422)."
    ),
    responses={
        413: {"description": "Request body exceeds 262144 bytes"},
        502: {"description": "Analysis provider failed or returned an unusable draft"},
        503: {"description": "Provider configuration is invalid or storage is unavailable"},
        504: {"description": "Analysis provider timed out"},
    },
)
def create_analysis(
    request: AnalysisRequest,
    provider: AnalysisProvider | None = Depends(get_analysis_provider),
    store: AnalysisStore = Depends(get_analysis_store),
) -> SavedAnalysisResponse:
    if provider is None:
        raise HTTPException(503, "Analysis provider configuration is incomplete or invalid")
    try:
        draft = AnalysisService(provider).analyze(request)
        return store.save(request, draft)
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
        if isinstance(exc, UnusableAnalysisError):
            logger.warning("Analysis output rejected: reason=%s", exc.reason)
        elif isinstance(exc, ValidationError):
            logger.warning(
                "Analysis output rejected: validation_types=%s",
                sorted({error["type"] for error in exc.errors(include_input=False)}),
            )
        raise HTTPException(502, "Analysis provider did not return a usable draft") from None


@app.get(
    ANALYSES_PATH + "/{analysis_id}",
    response_model=AnalysisRecord,
    responses={404: {"description": "Analysis not found"}, 503: {"description": "Storage unavailable"}},
)
def get_analysis(
    analysis_id: UUID, store: AnalysisStore = Depends(get_analysis_store)
) -> AnalysisRecord:
    return store.get(analysis_id)


@app.post(
    ANALYSES_PATH + "/{analysis_id}/reviews",
    response_model=ReviewRecord,
    status_code=201,
    responses={
        200: {"description": "Identical review replay"},
        404: {"description": "Analysis not found"},
        409: {"description": "Draft digest mismatch or conflicting review ID"},
        413: {"description": "Request body exceeds 262144 bytes"},
        503: {"description": "Storage unavailable"},
    },
)
def review_analysis(
    analysis_id: UUID,
    request: ReviewRequest,
    response: Response,
    store: AnalysisStore = Depends(get_analysis_store),
) -> ReviewRecord:
    review, created = store.review(analysis_id, request)
    response.status_code = 201 if created else 200
    return review
