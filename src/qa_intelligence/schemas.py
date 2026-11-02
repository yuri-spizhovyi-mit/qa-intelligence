from typing import Annotated

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


class AnalysisDraft(BaseModel):
    """Provider output, before the service attaches the requirement identifier."""

    questions: list[str]
    risks: list[str]
    test_cases: list[str]
    metadata: AnalysisMetadata


class AnalysisResponse(BaseModel):
    requirement_id: str
    status: str
    questions: list[str]
    risks: list[str]
    test_cases: list[str]
    metadata: AnalysisMetadata
