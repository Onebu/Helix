"""Pydantic models for dataset test cases.

Provides:
- PriorityTier: Enum for test case priority (critical, normal, low)
- TestCase: Model representing a single evaluation test case
- DatasetSummary: Model with aggregated dataset statistics
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from api.dataset.invalidation import InvalidationRecord
from api.types import OTelAttributes


class PriorityTier(StrEnum):
    """Priority tier for a test case.

    Critical cases act as hard constraints during evolution --
    if any critical case fails, the candidate is rejected.
    Normal and low cases contribute weighted scores.
    """

    CRITICAL = "critical"
    NORMAL = "normal"
    LOW = "low"


class TestCase(BaseModel):
    __test__ = False  # Prevent PytestCollectionWarning

    """A single evaluation test case for a prompt.

    Stores the inputs (chat history, variable values, tool definitions)
    and optionally the expected output. Each case has a priority tier
    that determines its weight during fitness evaluation.

    Attributes:
        id: Unique identifier (auto-generated UUID if not provided).
        name: Optional human-readable name.
        description: Optional description of what this case tests.
        chat_history: List of message dicts for multi-turn conversations.
        variables: Variable values to inject into the Jinja2 template.
        tools: Optional tool definitions for the LLM call.
        expected_output: Optional expected output for exact-match scoring.
        tier: Priority tier (critical, normal, low). Default: normal.
        created_at: Timestamp when the case was created.
        tags: Searchable tags for filtering and grouping.
        source_metadata: Generic provenance metadata for imported cases.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
    description: str | None = None
    chat_history: list[dict[str, Any]] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    tools: list[dict[str, Any]] | None = None
    expected_output: dict[str, Any] | None = None
    tier: PriorityTier = PriorityTier.NORMAL
    created_at: datetime = Field(default_factory=datetime.now)
    tags: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    invalidation: InvalidationRecord | None = None
    otel: OTelAttributes | None = None


class DatasetSummary(BaseModel):
    """Aggregated statistics for a prompt's dataset.

    Attributes:
        prompt_id: The prompt this summary describes.
        total_cases: Total number of test cases.
        critical_count: Number of cases with critical priority.
        normal_count: Number of cases with normal priority.
        low_count: Number of cases with low priority.
    """

    prompt_id: str
    total_cases: int
    critical_count: int
    normal_count: int
    low_count: int
