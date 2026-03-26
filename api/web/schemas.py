"""API-specific Pydantic request/response models.

These are separate from domain models to prevent leaking internal
implementation details through the API boundary.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

# --- Settings schemas ---


class RoleConfig(BaseModel):
    """Configuration for a single role (meta/target/judge)."""

    provider: str
    model: str
    has_key: bool
    key_hint: str = ""
    thinking_budget: int | None = None


class SettingsResponse(BaseModel):
    """Response from GET /api/settings."""

    meta: RoleConfig
    target: RoleConfig
    judge: RoleConfig
    concurrency_limit: int
    generation: dict
    providers: list[str]
    has_db_keys: bool = False


class SettingsUpdateRequest(BaseModel):
    """Request body for PUT /api/settings. All fields optional for partial update."""

    meta_provider: str | None = None
    meta_model: str | None = None
    target_provider: str | None = None
    target_model: str | None = None
    judge_provider: str | None = None
    judge_model: str | None = None

    openrouter_api_key: str | None = None
    gemini_api_key: str | None = None
    openai_api_key: str | None = None

    concurrency_limit: int | None = None
    generation: dict | None = None

    meta_thinking_budget: int | None = None
    target_thinking_budget: int | None = None
    judge_thinking_budget: int | None = None


class TestConnectionRequest(BaseModel):
    """Request body for POST /api/settings/test-connection."""

    provider: str
    api_key: str


class TestConnectionResponse(BaseModel):
    """Response from POST /api/settings/test-connection."""

    success: bool
    error: str | None = None


class SettingsDefaultsResponse(BaseModel):
    """Same shape as SettingsResponse but intended for default values."""

    meta: RoleConfig
    target: RoleConfig
    judge: RoleConfig
    concurrency_limit: int
    generation: dict
    providers: list[str]


# --- Prompt config schemas (Phase 48) ---


class RoleConfigResponse(BaseModel):
    """Effective configuration for a single role (meta/target/judge) with merged values."""

    provider: str
    model: str
    temperature: float | None
    thinking_budget: int | None


class ToolMockerConfigResponse(BaseModel):
    """Configuration for the Tool Mocker role (static YAML or LLM-based)."""

    mode: str  # "static" or "llm"
    provider: str | None
    model: str | None


class PromptConfigResponse(BaseModel):
    """Response from GET/PUT /api/prompts/{id}/config.

    Contains effective (merged) values per role and the raw overrides dict
    so the UI can show Global/Override provenance badges.
    """

    meta: RoleConfigResponse
    target: RoleConfigResponse
    judge: RoleConfigResponse
    tool_mocker: ToolMockerConfigResponse
    overrides: dict  # Raw per-prompt overrides from config.json (empty = all global)


# --- Wizard schemas ---


class WizardVariable(BaseModel):
    """Variable definition from wizard form."""

    name: str
    var_type: str = "string"
    description: str | None = None
    is_anchor: bool = False
    examples: list[Any] | None = None
    items_schema: list[WizardVariable] | None = None


# Resolve self-referencing forward ref for items_schema
WizardVariable.model_rebuild()


class WizardGenerateRequest(BaseModel):
    """Request body for wizard template generation."""

    id: str
    purpose: str
    description: str | None = None
    variables: list[WizardVariable] = []
    constraints: str | None = None
    behaviors: str | None = None
    include_tools: bool = False
    tool_descriptions: list[dict] | None = None
    language: str | None = None
    channel: str | None = None


class WizardGenerateResponse(BaseModel):
    """Response from wizard template generation."""

    yaml_template: str


class PromptSummary(BaseModel):
    """Summary representation of a registered prompt."""

    id: str
    purpose: str
    template_variables: list[str]
    anchor_variables: list[str]


class PromptDetail(PromptSummary):
    """Full prompt detail including template content."""

    template: str
    tools: list[dict] | None = None
    tool_schemas: list[dict] | None = None
    mocks: list[dict] | None = None
    variable_definitions: list[dict] | None = None


class CreatePromptRequest(BaseModel):
    """Request body for registering a new prompt."""

    id: str
    purpose: str
    template: str
    variables: list[dict] | None = None
    tools: list[dict] | None = None
    tool_schemas: list[dict] | None = None
    mocks: list[dict] | None = None


class UpdateTemplateRequest(BaseModel):
    """Request body for updating a prompt's template."""

    template: str


class UpdateMocksRequest(BaseModel):
    """Request body for updating a prompt's mock definitions."""

    mocks: list[dict]


class ExtractVariablesRequest(BaseModel):
    """Request body for extracting variables from a template."""

    template: str


class ExtractVariablesResponse(BaseModel):
    """Response with extracted template variables."""

    variables: list[str]
    errors: list[str] = []


class TestCaseResponse(BaseModel):
    """Response representation of a test case."""

    id: str
    name: str | None
    description: str | None
    tier: str
    variables: dict
    expected_output: dict | None
    tags: list[str]
    chat_history: list[dict]
    tools: list[dict] | None = None
    validation_warnings: list[str] = []


class TestCaseCreateRequest(BaseModel):
    """Request body for creating a new test case."""

    name: str | None = None
    description: str | None = None
    chat_history: list[dict] = []
    variables: dict = {}
    tools: list[dict] | None = None
    expected_output: dict | None = None
    tier: str = "normal"
    tags: list[str] = []


class TestCaseUpdateRequest(BaseModel):
    """Request body for updating an existing test case. All fields optional."""

    name: str | None = None
    description: str | None = None
    chat_history: list[dict] | None = None
    variables: dict | None = None
    tools: list[dict] | None = None
    expected_output: dict | None = None
    tier: str | None = None
    tags: list[str] | None = None


# --- Persona schemas ---


class PersonaProfileResponse(BaseModel):
    """Response representation of a persona profile."""

    id: str
    role: str
    traits: list[str]
    communication_style: str
    goal: str
    edge_cases: list[str] = []
    behavior_criteria: list[str] = []
    language: str = "en"
    channel: str = "text"


class CreatePersonaRequest(BaseModel):
    """Request body for creating a new persona."""

    id: str
    role: str
    traits: list[str]
    communication_style: str
    goal: str
    edge_cases: list[str] | None = None
    behavior_criteria: list[str] | None = None
    language: str = "en"
    channel: str = "text"


class UpdatePersonaRequest(BaseModel):
    """Request body for updating a persona. All fields optional for partial update."""

    role: str | None = None
    traits: list[str] | None = None
    communication_style: str | None = None
    goal: str | None = None
    edge_cases: list[str] | None = None
    behavior_criteria: list[str] | None = None
    language: str | None = None
    channel: str | None = None


class ImportPersonasResponse(BaseModel):
    """Response from persona import operation."""

    added_count: int
    skipped_count: int
    total: int


# --- Synthesis schemas ---


class SynthesizeRequest(BaseModel):
    """Request body for starting a synthesis run."""

    persona_ids: list[str] | None = None  # None = all personas
    num_conversations: int = 5
    max_turns: int = 10
    scenario_context: str | None = None
    review_mode: bool = True  # Default True: all new runs use review mode (SYNTH-01)


class SynthesizeResponse(BaseModel):
    """Response from starting a synthesis run."""

    run_id: str
    status: str  # "started"
    total_personas: int
    num_conversations: int


class SynthesisStatusResponse(BaseModel):
    """Status of a running synthesis."""

    run_id: str
    status: str  # "running", "complete", "failed"
    result: dict | None = None


class ReviewDecision(BaseModel):
    """Per-conversation approve/reject decision for synthesis review."""

    conversation_index: int
    action: Literal["approve", "reject"]
    edits: dict | None = None  # Optional: chat_history, variables, expected_output, tags, name


class ReviewRequest(BaseModel):
    """Request body for submitting review decisions on synthesized conversations."""

    run_id: str
    decisions: list[ReviewDecision]


class ReviewResponse(BaseModel):
    """Response from review endpoint with persist counts."""

    approved: int
    rejected: int
    case_ids: list[str]  # IDs of persisted test cases


class EvolutionRunRequest(BaseModel):
    """Request body for starting an evolution run."""

    prompt_id: str
    generations: int = 10
    islands: int = 4
    conversations_per_island: int = 5
    budget_cap_usd: float | None = None
    sample_size: int | None = None
    sample_ratio: float | None = None
    pr_no_parents: float | None = None
    temperature: float | None = None
    structural_mutation_probability: float | None = None

    # Advanced evolution parameters (None = use EvolutionConfig defaults)
    n_seq: int | None = None
    population_cap: int | None = None
    n_emigrate: int | None = None
    reset_interval: int | None = None
    n_reset: int | None = None
    n_top: int | None = None

    # Adaptive sampling (None = use EvolutionConfig defaults)
    adaptive_sampling: bool | None = None
    adaptive_decay_constant: float | None = None
    adaptive_min_rate: float | None = None
    checkpoint_interval: int | None = None

    # Inference parameters (None = use GenerationConfig/GeneConfig defaults)
    # NOTE: Use inference_temperature (not temperature) to avoid ambiguity
    # with EvolutionConfig.temperature (Boltzmann selection temperature)
    inference_temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None

    # Per-run model/provider overrides (None = use GeneConfig defaults)
    meta_model: str | None = None
    meta_provider: str | None = None
    target_model: str | None = None
    target_provider: str | None = None
    judge_model: str | None = None
    judge_provider: str | None = None

    # Per-role thinking config (Gemini only, None = provider default)
    meta_thinking_budget: int | None = None  # 2.5 series: token count (0=off, -1=dynamic)
    meta_thinking_level: str | None = None  # 3.x series: "minimal"|"low"|"medium"|"high"
    target_thinking_budget: int | None = None
    target_thinking_level: str | None = None
    judge_thinking_budget: int | None = None
    judge_thinking_level: str | None = None


class EvolutionRunStatus(BaseModel):
    """Status of a running evolution."""

    run_id: str
    prompt_id: str
    status: str
    started_at: str
    meta_model: str | None = None
    meta_provider: str | None = None
    target_model: str | None = None
    target_provider: str | None = None
    judge_model: str | None = None
    judge_provider: str | None = None
    hyperparameters: dict | None = None


class EvolutionRunHistory(BaseModel):
    """Historical record of a completed evolution run."""

    id: int
    prompt_id: str
    status: str
    best_fitness_score: float | None
    total_cost_usd: float
    generations_completed: int
    created_at: str
    meta_model: str
    target_model: str


# --- Run results (Phase 19 visualization data) ---


class LineageEventResponse(BaseModel):
    """A single lineage event from the evolution run."""

    candidate_id: str
    parent_ids: list[str] = []
    generation: int
    island: int = 0
    fitness_score: float = 0.0
    normalized_score: float = 0.0
    rejected: bool = False
    mutation_type: str = "rcc"
    survived: bool = True
    template: str | None = None


class CaseResultResponse(BaseModel):
    """Evaluation result for a single test case."""

    case_id: str
    tier: str = "normal"
    score: float
    passed: bool = False
    reason: str = ""
    expected: dict | None = None
    actual_content: str | None = None
    actual_tool_calls: list[dict] | None = None
    criteria_results: list[dict] | None = None


class GenerationRecordResponse(BaseModel):
    """Per-generation metrics for fitness progression chart."""

    generation: int
    best_fitness: float
    avg_fitness: float
    best_normalized: float = 0.0
    avg_normalized: float = 0.0
    candidates_evaluated: int = 0
    cost_summary: dict = {}


class RunResultsResponse(BaseModel):
    """Full results for a completed evolution run, used by visualization components."""

    prompt_id: str | None = None
    lineage_events: list[LineageEventResponse] = []
    case_results: list[CaseResultResponse] = []
    seed_case_results: list[CaseResultResponse] = []
    generation_records: list[GenerationRecordResponse] = []
    best_candidate_id: str | None = None
    best_template: str | None = None
    total_cost_usd: float = 0.0
    best_fitness_score: float | None = None
    best_normalized_score: float | None = None
    generations_completed: int = 0
    termination_reason: str | None = None
    meta_model: str | None = None
    target_model: str | None = None
    judge_model: str | None = None
    meta_provider: str | None = None
    target_provider: str | None = None
    judge_provider: str | None = None
    hyperparameters: dict | None = None


# --- Preset schemas ---


class PresetResponse(BaseModel):
    """Response representation of a config or evolution preset."""

    id: int
    name: str
    type: str  # "config" or "evolution"
    data: dict
    is_default: bool
    created_at: str


class CreatePresetRequest(BaseModel):
    """Request body for creating a new preset."""

    name: str
    type: str  # "config" or "evolution"
    data: dict
    is_default: bool = False


class UpdatePresetRequest(BaseModel):
    """Request body for updating a preset. All fields optional."""

    name: str | None = None
    data: dict | None = None
    is_default: bool | None = None


# --- Playground config schemas ---


class PlaygroundConfigResponse(BaseModel):
    """Response with playground config (turn_limit, budget) for a prompt."""

    turn_limit: int | None = None
    budget: float | None = None


class PlaygroundConfigUpdateRequest(BaseModel):
    """Request body for updating playground config (turn_limit, budget)."""

    turn_limit: int | None = None
    budget: float | None = None


# --- Playground variable schemas ---


class PlaygroundVariablesResponse(BaseModel):
    """Response with saved variable values for a prompt."""

    prompt_id: str
    variables: dict[str, str]  # {variable_name: value}


class PlaygroundVariablesUpdateRequest(BaseModel):
    """Request body for saving playground variable values."""

    variables: dict[str, str]  # {variable_name: value}


# --- Playground schemas ---


class ChatRequest(BaseModel):
    """Request body for interactive chat playground."""

    messages: list[dict]  # [{role: "user"/"assistant", content: "..."}]
    variables: dict = {}  # Template variable values
    turn_limit: int = 20
    cost_budget: float = 0.50  # USD
    max_steps: int | None = None  # Max agentic tool loop steps per response (default: 10)


# --- Format guide schemas (Phase 56) ---


class FormatGuideResponse(BaseModel):
    """Response representation of a tool format guide."""

    id: int
    prompt_id: str
    tool_name: str
    examples: list[str]  # List of JSON example strings


class FormatGuideCreateRequest(BaseModel):
    """Request body for creating/updating a format guide (PUT upsert)."""

    tool_name: str
    examples: list[str]  # Each string must be valid JSON


class FormatGuideUpdateRequest(BaseModel):
    """Request body for updating format guide examples."""

    examples: list[str]  # Each string must be valid JSON


class GenerateSampleRequest(BaseModel):
    """Request body for generating a sample mock response."""

    tool_name: str
    scenario_type: str = "success"  # "success", "failure", "edge_case"


class GenerateSampleResponse(BaseModel):
    """Response from sample generation endpoint."""

    sample: str  # Generated JSON response
    scenario_type: str


# --- Prompt versioning schemas (Phase 63) ---


class PromptVersionResponse(BaseModel):
    """Response representation of a prompt version."""

    version: int
    template: str
    created_at: str
    is_active: bool
    already_existed: bool = False


class AcceptVersionRequest(BaseModel):
    """Request body for accepting a new version from evolution results."""

    template: str
