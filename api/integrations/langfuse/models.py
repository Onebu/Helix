"""Request and response contracts for Langfuse imports."""

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from api.dataset.models import TestCase

SourceKind = Literal["dataset", "observation"]


class LangfuseSourceRequest(BaseModel):
    prompt_id: str
    source_kind: SourceKind
    dataset_name: str | None = None
    observation_id: str | None = None

    @model_validator(mode="after")
    def require_matching_source_id(self) -> Self:
        valid = (
            self.source_kind == "dataset"
            and bool(self.dataset_name)
            and not self.observation_id
        ) or (
            self.source_kind == "observation"
            and bool(self.observation_id)
            and not self.dataset_name
        )
        if not valid:
            raise ValueError("Provide exactly one identifier matching source_kind")
        return self


class LangfuseImportRequest(LangfuseSourceRequest):
    selected_external_ids: list[str] = Field(min_length=1)


class MappedCasePreview(BaseModel):
    external_id: str = Field(min_length=1)
    case: TestCase
    warnings: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    duplicate: bool = False
    importable: bool = True


class LangfusePreview(BaseModel):
    source_kind: SourceKind
    items: list[MappedCasePreview]


class LangfuseImportResponse(BaseModel):
    created: int
    skipped_duplicates: int
    invalid: int
    case_ids: list[str]
