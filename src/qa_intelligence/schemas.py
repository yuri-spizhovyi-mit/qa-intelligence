from typing import Annotated, Literal
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


def _trimmed(max_length: int) -> StringConstraints:
    return StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=max_length
    )


class AcceptanceCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, _trimmed(100)]
    text: Annotated[str, _trimmed(2000)]


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: Annotated[str, _trimmed(100)]
    text: Annotated[str, _trimmed(10000)]
    acceptance_criteria: Annotated[list[AcceptanceCriterion], Field(max_length=20)]
    generate_test_cases: Annotated[bool, Field(strict=True)] = False

    @model_validator(mode="after")
    def _reject_duplicate_criterion_ids(self) -> "AnalysisRequest":
        ids = [criterion.id for criterion in self.acceptance_criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("acceptance criterion ids must be unique")
        return self


class AnalysisMetadata(BaseModel):
    provider: str
    model: str
    prompt_version: str
    token_usage: int | None = None


class DraftTestCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    title: str
    category: Literal["positive", "negative", "boundary"]
    preconditions: list[str]
    steps: list[str]
    expected_result: str
    source_criterion_ids: list[str]

    @model_validator(mode="after")
    def validate_content(self) -> "DraftTestCase":
        if not self.steps or not self.source_criterion_ids:
            raise ValueError("Test cases require steps and source criterion IDs")
        if len(self.steps) > 20 or len(self.preconditions) > 20:
            raise ValueError("Too many test instructions")
        values = [
            self.id, self.title, self.expected_result,
            *self.preconditions, *self.steps, *self.source_criterion_ids,
        ]
        if any(not value.strip() or len(value) > 2000 for value in values):
            raise ValueError("Test case text must be nonempty and at most 2000 characters")
        if len(set(self.source_criterion_ids)) != len(self.source_criterion_ids):
            raise ValueError("Source criterion IDs must be unique")
        return self


class AnalysisDraft(BaseModel):
    """Provider output, before the service attaches the requirement identifier."""

    questions: list[str]
    risks: list[str]
    test_cases: list[DraftTestCase]
    metadata: AnalysisMetadata


class AnalysisResponse(BaseModel):
    requirement_id: str
    status: str
    questions: list[str]
    risks: list[str]
    test_cases: list[DraftTestCase]
    metadata: AnalysisMetadata


class SavedAnalysisResponse(AnalysisResponse):
    analysis_id: UUID
    created_at: datetime
    draft_sha256: str


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: UUID
    draft_sha256: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
    decision: Literal["approved", "changes_requested"]
    reviewer: Annotated[str, _trimmed(100)]
    comment: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=2000)] = ""

    @model_validator(mode="after")
    def require_change_reason(self) -> "ReviewRequest":
        if self.decision == "changes_requested" and not self.comment:
            raise ValueError("A change request requires a comment")
        return self


class ReviewRecord(ReviewRequest):
    analysis_id: UUID
    created_at: datetime


class AnalysisRecord(BaseModel):
    request: AnalysisRequest
    draft: SavedAnalysisResponse
    review_status: Literal["pending", "approved", "changes_requested"]
    reviews: list[ReviewRecord]
