"""SQLAlchemy 2.0 ORM models for Helix database tables.

Uses Mapped[] + mapped_column() style following diga_eval conventions.
Defines 10 tables: evolution_runs, llm_call_records, settings, prompt_configs,
presets, playground_variables, personas, tool_format_guides, prompts, test_cases.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class User(Base):
    """User accounts for authentication.

    Stores credentials and profile info. Passwords are bcrypt-hashed.
    The username is used as the foreign key in data-owning tables (denormalized
    for query simplicity — this tool has at most dozens of users, not millions).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvolutionRun(Base):
    """Stores metadata for a single evolution run.

    Tracks models used, hyperparameters, cost/token totals,
    and results (fitness score, generations completed).
    """

    __tablename__ = "evolution_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    prompt_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)

    # Model configuration snapshot
    meta_model: Mapped[str] = mapped_column(String(255), nullable=False)
    target_model: Mapped[str] = mapped_column(String(255), nullable=False)
    judge_model: Mapped[str | None] = mapped_column(String(255))

    # Provider names (nullable for backward compatibility with existing rows)
    meta_provider: Mapped[str | None] = mapped_column(String(50))
    target_provider: Mapped[str | None] = mapped_column(String(50))
    judge_provider: Mapped[str | None] = mapped_column(String(50))

    # Hyperparameters snapshot
    hyperparameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Cost tracking
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_api_calls: Mapped[int] = mapped_column(Integer, default=0)

    # Results
    best_fitness_score: Mapped[float | None] = mapped_column(Float)
    generations_completed: Mapped[int] = mapped_column(Integer, default=0)

    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # RunManager UUID for live-to-completed lookup
    run_uuid: Mapped[str | None] = mapped_column(String(36), index=True)

    # Owner (nullable for backwards compat with pre-auth rows)
    user_id: Mapped[str | None] = mapped_column(String(150), index=True)

    # Relationships
    llm_calls: Mapped[list["LLMCallRecord"]] = relationship(
        "LLMCallRecord", back_populates="evolution_run", cascade="all, delete-orphan"
    )


class LLMCallRecord(Base):
    """Stores metadata for a single LLM API call within an evolution run.

    Each call records model, role, token usage, cost, and timing.
    """

    __tablename__ = "llm_call_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evolution_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("evolution_runs.id"), index=True
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    generation_id: Mapped[str | None] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_type: Mapped[str | None] = mapped_column(String(50))

    # Relationships
    evolution_run: Mapped["EvolutionRun"] = relationship("EvolutionRun", back_populates="llm_calls")


class Setting(Base):
    """Key-value store for per-user configuration.

    Each row represents a config category (e.g. "global_config",
    "generation_defaults", "api_keys") scoped to a user.
    The data column holds the actual config dict as JSON.

    API keys are stored encrypted (Fernet) in the "api_keys" category.
    user_id is nullable for backwards compat with pre-auth rows.
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(150), index=True)


class PromptConfig(Base):
    """Per-prompt configuration overrides.

    One row per prompt. Individual typed columns for common fields
    plus an extra JSON column for extensibility. Replaces config.json sidecars.
    """

    __tablename__ = "prompt_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(255))
    temperature: Mapped[float | None] = mapped_column(Float)
    thinking_budget: Mapped[int | None] = mapped_column(Integer)
    playground_turn_limit: Mapped[int | None] = mapped_column(Integer)
    playground_budget: Mapped[float | None] = mapped_column(Float)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class Preset(Base):
    """Config and evolution presets.

    type discriminates between "config" and "evolution".
    data JSON holds the preset values.
    is_default marks the active preset.
    """

    __tablename__ = "presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlaygroundVariable(Base):
    """Variable values per prompt for the playground.

    Composite unique constraint on (prompt_id, variable_name).
    Value is Text (not JSON) since variable values are always strings.
    Replaces localStorage persistence.
    """

    __tablename__ = "playground_variables"
    __table_args__ = (
        UniqueConstraint("prompt_id", "variable_name", name="uq_playground_prompt_var"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    variable_name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class Persona(Base):
    """Persona profiles per prompt for synthesis/test generation.

    Schema aligns with the PersonaProfile domain model (synthesis/models.py)
    to avoid a mapping layer. Composite unique constraint on (prompt_id, persona_id).
    Replaces personas.yaml sidecars.
    """

    __tablename__ = "personas"
    __table_args__ = (
        UniqueConstraint("prompt_id", "persona_id", name="uq_persona_prompt_persona"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    persona_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(500), nullable=False)
    traits: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    communication_style: Mapped[str] = mapped_column(String(500), nullable=False)
    goal: Mapped[str] = mapped_column(String(500), nullable=False)
    edge_cases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    behavior_criteria: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    language: Mapped[str] = mapped_column(String(10), default="en")
    channel: Mapped[str] = mapped_column(String(20), default="text")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ToolFormatGuide(Base):
    """Format guide examples for LLM-based tool mock generation.

    Stores per-prompt, per-tool example JSON responses that the LLM uses
    as reference when generating mock tool responses. Composite unique
    constraint ensures one format guide per (prompt_id, tool_name).
    """

    __tablename__ = "tool_format_guides"
    __table_args__ = (
        UniqueConstraint("prompt_id", "tool_name", name="uq_format_guide_prompt_tool"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    examples: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Prompt(Base):
    """Stores prompt templates and metadata in the database.

    Replaces filesystem-based prompt storage (prompts/<id>/prompt.md, variables.json,
    tools.json, etc.). Each row represents a complete prompt with all its configuration.

    Attributes:
        id: Slug primary key (e.g. "pizza-ivr").
        purpose: Human-readable description of the prompt's purpose.
        template: Jinja2 template content (always reflects the active version).
        variables: Serialized list[VariableDefinition] as JSON.
        tools: OpenAI/OpenRouter tool definitions as JSON.
        tool_schemas: YAML tool schema definitions as JSON.
        mocks: Mock response definitions as JSON.
        active_version: Which version number is currently active (default 1).
        created_at: Timestamp when the prompt was created.
        updated_at: Timestamp of the last update (auto-set on update).
    """

    __tablename__ = "prompts"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(150), index=True)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list | None] = mapped_column(JSON)
    tools: Mapped[list | None] = mapped_column(JSON)
    tool_schemas: Mapped[list | None] = mapped_column(JSON)
    mocks: Mapped[list | None] = mapped_column(JSON)
    active_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class PromptVersion(Base):
    """Stores versioned snapshots of prompt templates.

    Each version captures the template text at a point in time. The active
    version is tracked by Prompt.active_version (no is_active column here).

    Attributes:
        id: Auto-incrementing primary key.
        prompt_id: Foreign key to prompts.id.
        version: Version number (1, 2, 3, ...).
        template: Template text snapshot for this version.
        created_at: Timestamp when the version was created.
    """

    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_id", "version", name="uq_prompt_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("prompts.id"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TestCaseRecord(Base):
    """Stores test cases in the database instead of per-prompt dataset/ files.

    Each row represents a single evaluation test case belonging to a prompt.
    Replaces the filesystem pattern of prompts/<prompt_id>/dataset/case-<id>.json.

    Attributes:
        id: UUID string primary key.
        prompt_id: Foreign key to the parent prompt (indexed for fast lookups).
        name: Optional human-readable name.
        description: Optional description of what this case tests.
        chat_history: List of message dicts for multi-turn conversations.
        variables: Variable values to inject into the Jinja2 template.
        tools: Optional tool definitions for the LLM call.
        expected_output: Optional expected output for scoring.
        tier: Priority tier string (critical, normal, low).
        tags: Searchable tags for filtering and grouping.
        created_at: Timestamp when the case was created.
    """

    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    prompt_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    chat_history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    variables: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tools: Mapped[list | None] = mapped_column(JSON)
    expected_output: Mapped[dict | None] = mapped_column(JSON)
    tier: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
