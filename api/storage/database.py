"""Async database engine and session factory.

Provides a Database class wrapping SQLAlchemy async engine
with connection pooling, session management, and startup
seed/import logic for migrating from file-based config.
"""

import json
import logging
from pathlib import Path

import yaml
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.storage.models import (
    Base,
    EvolutionRun,
    Persona,
    Prompt,
    PromptConfig,
    TestCaseRecord,
)

logger = logging.getLogger(__name__)

# Fields that must NEVER be stored in the database (security constraint)
_SENSITIVE_KEY_PATTERNS = {"api_key", "secret_key"}


def _is_sensitive_field(field_name: str) -> bool:
    """Check if a field name matches a sensitive key pattern."""
    lower = field_name.lower()
    return any(pattern in lower for pattern in _SENSITIVE_KEY_PATTERNS)


class Database:
    """Async database connection manager.

    Wraps SQLAlchemy async engine with connection pooling.
    Auto-converts postgresql:// URLs to postgresql+asyncpg://.
    """

    def __init__(self, database_url: str):
        # Convert postgresql:// to postgresql+asyncpg:// for async driver
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        # SQLite uses StaticPool; PostgreSQL uses connection pooling
        if database_url.startswith("sqlite"):
            from sqlalchemy.pool import StaticPool

            self.engine = create_async_engine(
                database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False,
            )
        else:
            self.engine = create_async_engine(
                database_url,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                echo=False,
            )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def get_session(self) -> AsyncSession:
        """Create a new async session. Caller manages lifecycle."""
        return self.session_factory()

    async def create_tables(self) -> None:
        """Create all tables from Base metadata. For dev/testing only."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def ensure_columns(self) -> None:
        """Add any missing columns to ALL tables in Base.metadata.

        SQLAlchemy's create_all does not add columns to existing tables.
        This method inspects the live schema and issues ALTER TABLE for
        any columns defined in ORM models but absent from the DB.

        Generalized to iterate all tables, not just evolution_runs.
        Idempotent and future-proof.
        """
        # Map SQLAlchemy column types to SQLite-compatible DDL types
        _type_map = {
            "String": "VARCHAR",
            "Integer": "INTEGER",
            "Float": "FLOAT",
            "DateTime": "DATETIME",
            "JSON": "JSON",
            "Boolean": "BOOLEAN",
            "Text": "TEXT",
        }

        def _sync_ensure(connection):
            inspector = sa_inspect(connection)

            for table in Base.metadata.sorted_tables:
                table_name = table.name
                # Skip tables that don't exist yet (create_tables will handle them)
                if not inspector.has_table(table_name):
                    continue

                existing = {col["name"] for col in inspector.get_columns(table_name)}

                for col in table.columns:
                    if col.name not in existing:
                        col_type_name = type(col.type).__name__
                        ddl_type = _type_map.get(col_type_name, "TEXT")
                        sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {ddl_type}"
                        connection.execute(text(sql))
                        logger.info(
                            "Added missing column: %s.%s (%s)",
                            table_name,
                            col.name,
                            ddl_type,
                        )

        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(_sync_ensure)
        except Exception:
            logger.warning("ensure_columns failed (table may not exist yet)", exc_info=True)

    async def import_prompt_sidecars(self, prompts_dir: str) -> None:
        """Import config.json and personas.yaml sidecars into the database.

        For each prompt directory:
        - If config.json exists and no PromptConfig row for that prompt_id: import
        - If personas.yaml exists and no Persona rows for that prompt_id: import

        Idempotent -- skips prompts that already have data in DB.
        Malformed files are logged and skipped (don't crash startup).

        Args:
            prompts_dir: Path to the prompts directory.
        """
        prompts_path = Path(prompts_dir)
        if not prompts_path.exists():
            logger.info("Prompts directory not found at %s, skipping import", prompts_dir)
            return

        async with self.session_factory() as session:
            for prompt_dir in sorted(prompts_path.iterdir()):
                if not prompt_dir.is_dir():
                    continue

                prompt_id = prompt_dir.name
                await self._import_config_json(session, prompt_dir, prompt_id)
                await self._import_personas_yaml(session, prompt_dir, prompt_id)

            await session.commit()

    async def _import_config_json(
        self, session: AsyncSession, prompt_dir: Path, prompt_id: str
    ) -> None:
        """Import a config.json sidecar into PromptConfig table."""
        config_path = prompt_dir / "config.json"
        if not config_path.exists():
            return

        # Check if already imported
        result = await session.execute(
            select(PromptConfig).where(PromptConfig.prompt_id == prompt_id)
        )
        if result.scalar_one_or_none() is not None:
            logger.debug("PromptConfig for '%s' already exists, skipping", prompt_id)
            return

        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning(
                "Failed to parse config.json for prompt '%s', skipping",
                prompt_id,
                exc_info=True,
            )
            return

        # Map known fields to typed columns, rest goes to extra
        # Also accept role-prefixed fields (meta_model -> model, etc.)
        provider = data.get("meta_provider") or data.get("provider")
        model = data.get("meta_model") or data.get("model")
        temperature = data.get("meta_temperature") or data.get("temperature")
        thinking_budget = data.get("meta_thinking_budget") or data.get("thinking_budget")

        # Everything else goes in extra
        _mapped_keys = {
            "provider",
            "model",
            "temperature",
            "thinking_budget",
            "meta_provider",
            "target_provider",
            "judge_provider",
            "meta_model",
            "target_model",
            "judge_model",
            "meta_temperature",
            "target_temperature",
            "judge_temperature",
            "meta_thinking_budget",
            "target_thinking_budget",
            "judge_thinking_budget",
        }
        extra = {
            k: v for k, v in data.items() if k not in _mapped_keys and not _is_sensitive_field(k)
        }
        # Include target/judge provider/model in extra for downstream use
        for key in [
            "target_provider",
            "judge_provider",
            "target_model",
            "judge_model",
            "target_temperature",
            "judge_temperature",
            "target_thinking_budget",
            "judge_thinking_budget",
        ]:
            if key in data:
                extra[key] = data[key]

        prompt_config = PromptConfig(
            prompt_id=prompt_id,
            provider=provider,
            model=model,
            temperature=temperature,
            thinking_budget=thinking_budget,
            extra=extra if extra else None,
        )
        session.add(prompt_config)
        logger.info("Imported config.json for prompt: %s", prompt_id)

    async def _import_personas_yaml(
        self, session: AsyncSession, prompt_dir: Path, prompt_id: str
    ) -> None:
        """Import a personas.yaml sidecar into Persona table."""
        personas_path = prompt_dir / "personas.yaml"
        if not personas_path.exists():
            return

        # Check if already imported
        result = await session.execute(select(Persona).where(Persona.prompt_id == prompt_id))
        existing = result.scalars().all()
        if existing:
            logger.debug("Personas for '%s' already exist, skipping", prompt_id)
            return

        try:
            data = yaml.safe_load(personas_path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.warning(
                "Failed to parse personas.yaml for prompt '%s', skipping",
                prompt_id,
                exc_info=True,
            )
            return

        personas_list = data.get("personas", [])
        if not personas_list:
            return

        for persona_data in personas_list:
            try:
                persona = Persona(
                    prompt_id=prompt_id,
                    persona_id=persona_data["id"],
                    role=persona_data["role"],
                    traits=persona_data.get("traits", []),
                    communication_style=persona_data["communication_style"],
                    goal=persona_data["goal"],
                    edge_cases=persona_data.get("edge_cases", []),
                    behavior_criteria=persona_data.get("behavior_criteria", []),
                    language=persona_data.get("language", "en"),
                    channel=persona_data.get("channel", "text"),
                )
                session.add(persona)
            except (KeyError, TypeError) as e:
                logger.warning(
                    "Skipping malformed persona in '%s': %s",
                    prompt_id,
                    e,
                )

        logger.info(
            "Imported %d personas for prompt: %s",
            len(personas_list),
            prompt_id,
        )

    async def import_prompts_from_filesystem(self, prompts_dir: str) -> int:
        """One-time migration: import prompts from filesystem to DB.

        For each prompt directory containing prompt.md:
        - Read prompt.md (template), purpose.md, variables.json, tools.json
        - Read tools.yaml, mocks.yaml if they exist
        - Insert a Prompt row in the DB
        - Read dataset/case-*.json files and insert TestCaseRecord rows
        - Import config.json and personas.yaml sidecars

        Returns number of prompts imported.
        Idempotent: skips prompts that already exist in DB.
        """
        import uuid

        prompts_path = Path(prompts_dir)
        if not prompts_path.exists():
            logger.info("Prompts directory not found at %s, skipping migration", prompts_dir)
            return 0

        imported = 0
        async with self.session_factory() as session:
            for prompt_dir in sorted(prompts_path.iterdir()):
                if not prompt_dir.is_dir():
                    continue

                prompt_id = prompt_dir.name
                template_path = prompt_dir / "prompt.md"
                if not template_path.exists():
                    logger.debug("No prompt.md in %s, skipping", prompt_id)
                    continue

                # Check if already imported
                result = await session.execute(
                    select(Prompt).where(Prompt.id == prompt_id)
                )
                if result.scalar_one_or_none() is not None:
                    logger.debug("Prompt '%s' already in DB, skipping", prompt_id)
                    continue

                try:
                    # Read template
                    template = template_path.read_text(encoding="utf-8")

                    # Read purpose
                    purpose_path = prompt_dir / "purpose.md"
                    purpose = prompt_id
                    if purpose_path.exists():
                        purpose = purpose_path.read_text(encoding="utf-8").strip()

                    # Read variables.json
                    variables_json = None
                    variables_path = prompt_dir / "variables.json"
                    if variables_path.exists():
                        try:
                            raw_vars = json.loads(
                                variables_path.read_text(encoding="utf-8")
                            )
                            # Handle both list format and {"variables": [...]} format
                            if isinstance(raw_vars, dict) and "variables" in raw_vars:
                                variables_json = raw_vars["variables"]
                            elif isinstance(raw_vars, list):
                                variables_json = raw_vars
                        except Exception as exc:
                            logger.warning(
                                "Failed to parse variables.json for %s: %s", prompt_id, exc
                            )

                    # Read tools.json
                    tools_json = None
                    tools_path = prompt_dir / "tools.json"
                    if tools_path.exists():
                        try:
                            raw_tools = json.loads(
                                tools_path.read_text(encoding="utf-8")
                            )
                            if isinstance(raw_tools, dict) and "tools" in raw_tools:
                                tools_json = raw_tools["tools"]
                            elif isinstance(raw_tools, list):
                                tools_json = raw_tools
                        except Exception as exc:
                            logger.warning(
                                "Failed to parse tools.json for %s: %s", prompt_id, exc
                            )

                    # Read tools.yaml
                    tool_schemas_json = None
                    tools_yaml_path = prompt_dir / "tools.yaml"
                    if tools_yaml_path.exists():
                        try:
                            raw_yaml = yaml.safe_load(
                                tools_yaml_path.read_text(encoding="utf-8")
                            ) or {}
                            if "tools" in raw_yaml:
                                tool_schemas_json = raw_yaml["tools"]
                        except Exception as exc:
                            logger.warning(
                                "Failed to parse tools.yaml for %s: %s", prompt_id, exc
                            )

                    # Read mocks.yaml
                    mocks_json = None
                    mocks_yaml_path = prompt_dir / "mocks.yaml"
                    if mocks_yaml_path.exists():
                        try:
                            raw_mocks = yaml.safe_load(
                                mocks_yaml_path.read_text(encoding="utf-8")
                            ) or {}
                            if "mocks" in raw_mocks:
                                mocks_json = raw_mocks["mocks"]
                        except Exception as exc:
                            logger.warning(
                                "Failed to parse mocks.yaml for %s: %s", prompt_id, exc
                            )

                    # Insert Prompt row
                    prompt_row = Prompt(
                        id=prompt_id,
                        purpose=purpose,
                        template=template,
                        variables=variables_json,
                        tools=tools_json,
                        tool_schemas=tool_schemas_json,
                        mocks=mocks_json,
                    )
                    session.add(prompt_row)

                    # Import dataset cases
                    dataset_dir = prompt_dir / "dataset"
                    if dataset_dir.exists():
                        for case_file in sorted(dataset_dir.glob("case-*.json")):
                            try:
                                case_data = json.loads(
                                    case_file.read_text(encoding="utf-8")
                                )
                                case_row = TestCaseRecord(
                                    id=case_data.get("id", str(uuid.uuid4())),
                                    prompt_id=prompt_id,
                                    name=case_data.get("name"),
                                    description=case_data.get("description"),
                                    chat_history=case_data.get("chat_history", []),
                                    variables=case_data.get("variables", {}),
                                    tools=case_data.get("tools"),
                                    expected_output=case_data.get("expected_output"),
                                    tier=case_data.get("tier", "normal"),
                                    tags=case_data.get("tags", []),
                                )
                                session.add(case_row)
                            except Exception as exc:
                                logger.warning(
                                    "Failed to import case %s for %s: %s",
                                    case_file.name, prompt_id, exc,
                                )

                    # Import config.json and personas.yaml sidecars
                    await self._import_config_json(session, prompt_dir, prompt_id)
                    await self._import_personas_yaml(session, prompt_dir, prompt_id)

                    imported += 1
                    logger.info("Imported prompt from filesystem: %s", prompt_id)

                except Exception as exc:
                    logger.warning(
                        "Failed to import prompt '%s': %s", prompt_id, exc, exc_info=True
                    )

            await session.commit()

        logger.info("Filesystem migration complete: %d prompts imported", imported)
        return imported

    async def seed_demo_prompt(self) -> bool:
        """Seed demo pizza-ivr prompt if DB has no prompts.

        Creates a Spanish pizza restaurant IVR prompt with:
        - 1 prompt template with 2 variables and 3 tools
        - 5 test cases (3 passing, 2 intentionally failing)
        - 1 sample completed evolution run

        Returns True if seeded, False if skipped (prompts already exist).
        """
        import uuid

        async with self.session_factory() as session:
            # Check if any prompts exist
            result = await session.execute(select(Prompt.id).limit(1))
            if result.scalar_one_or_none() is not None:
                logger.debug("Prompts already exist in DB, skipping demo seed")
                return False

            # -- Demo prompt template --
            template = (
                "# Pizza IVR - Bella Italia\n"
                "\n"
                'You are a virtual phone assistant for "Bella Italia" pizza restaurant. '
                "Your job is to handle incoming customer calls.\n"
                "\n"
                "## Instructions\n"
                "- Greet the customer warmly by name when available\n"
                "- Help with: orders, reservations, hours, location\n"
                "- For orders: confirm items, delivery address, and payment method\n"
                "- For complaints: show empathy and escalate to a human agent\n"
                "- Be concise but friendly\n"
                "\n"
                "## Customer Info\n"
                "- Name: {{ customer_name }}\n"
                "- Order History: {{ order_history }}\n"
                "\n"
                "## Available Tools\n"
                "Use the provided tools to:\n"
                "- Search the current menu\n"
                "- Check delivery availability\n"
                "- Create orders in the system\n"
            )

            variables = [
                {
                    "name": "customer_name",
                    "var_type": "string",
                    "description": "Customer name",
                    "is_anchor": True,
                },
                {
                    "name": "order_history",
                    "var_type": "string",
                    "description": "Previous order summary",
                    "is_anchor": False,
                },
            ]

            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "search_menu",
                        "description": "Search the pizza menu",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "check_delivery",
                        "description": "Check delivery availability for an address",
                        "parameters": {
                            "type": "object",
                            "properties": {"address": {"type": "string"}},
                            "required": ["address"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "create_order",
                        "description": "Create a new order",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "items": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "address": {"type": "string"},
                                "payment_method": {"type": "string"},
                            },
                            "required": ["items", "address"],
                        },
                    },
                },
            ]

            prompt_row = Prompt(
                id="pizza-ivr",
                purpose="Pizza restaurant IVR phone assistant demo",
                template=template,
                variables=variables,
                tools=tools,
            )
            session.add(prompt_row)

            # -- 5 test cases (3 passing, 2 intentionally failing) --

            test_cases = [
                TestCaseRecord(
                    id=str(uuid.uuid4()),
                    prompt_id="pizza-ivr",
                    name="Greeting",
                    description="User greets, expects friendly response using their name",
                    chat_history=[
                        {"role": "user", "content": "Hello!"},
                    ],
                    variables={"customer_name": "Maria", "order_history": ""},
                    expected_output={"require_content": True},
                    tier="normal",
                    tags=["greeting", "demo"],
                ),
                TestCaseRecord(
                    id=str(uuid.uuid4()),
                    prompt_id="pizza-ivr",
                    name="Menu inquiry",
                    description="User asks about the menu, expects search_menu tool call",
                    chat_history=[
                        {"role": "user", "content": "What pizzas do you have?"},
                    ],
                    variables={"customer_name": "Carlos", "order_history": ""},
                    expected_output={
                        "match_args": {"tool_name": "search_menu"},
                    },
                    tier="normal",
                    tags=["menu", "tool-call", "demo"],
                ),
                TestCaseRecord(
                    id=str(uuid.uuid4()),
                    prompt_id="pizza-ivr",
                    name="Order placement",
                    description="Multi-turn order flow, expects create_order tool call",
                    chat_history=[
                        {"role": "user", "content": "I'd like to order a pizza"},
                        {
                            "role": "assistant",
                            "content": "Of course! What pizza would you like to order?",
                        },
                        {
                            "role": "user",
                            "content": (
                                "A large margherita, deliver to 123 Main Street, "
                                "pay by card"
                            ),
                        },
                    ],
                    variables={"customer_name": "Ana", "order_history": ""},
                    expected_output={
                        "match_args": {"tool_name": "create_order"},
                    },
                    tier="critical",
                    tags=["order", "tool-call", "demo"],
                ),
                TestCaseRecord(
                    id=str(uuid.uuid4()),
                    prompt_id="pizza-ivr",
                    name="Escalation failure",
                    description=(
                        "Angry user expects exact escalation phrasing "
                        "(intentionally fails -- prompt does not always use exact words)"
                    ),
                    chat_history=[
                        {
                            "role": "user",
                            "content": (
                                "I'm very upset! My order arrived cold and "
                                "late! I want to speak to someone!"
                            ),
                        },
                    ],
                    variables={"customer_name": "Pedro", "order_history": "3 previous orders"},
                    expected_output={
                        "require_content": True,
                        "must_contain": "human agent",
                    },
                    tier="normal",
                    tags=["escalation", "failing", "demo"],
                ),
                TestCaseRecord(
                    id=str(uuid.uuid4()),
                    prompt_id="pizza-ivr",
                    name="Edge case off-topic",
                    description=(
                        "User asks unrelated question, expects polite redirect "
                        "(intentionally fails -- edge case handling)"
                    ),
                    chat_history=[
                        {
                            "role": "user",
                            "content": "Can you help me book a flight to Paris?",
                        },
                    ],
                    variables={"customer_name": "John", "order_history": ""},
                    expected_output={
                        "require_content": True,
                        "must_contain": "only help with pizza",
                    },
                    tier="low",
                    tags=["off-topic", "edge-case", "failing", "demo"],
                ),
            ]

            for tc in test_cases:
                session.add(tc)

            # -- 1 sample evolution run with full visualization data --
            # Build candidate IDs for lineage
            seed_id = "seed-0000"
            gen1_ids = [f"g1-island{i}" for i in range(4)]
            gen2_ids = [f"g2-island{i}" for i in range(4)]
            gen3_ids = [f"g3-island{i}" for i in range(4)]
            best_id = gen3_ids[1]  # Island 1 wins

            # Lineage events: seed → gen1 → gen2 → gen3
            lineage_events = [
                {
                    "candidate_id": seed_id,
                    "parent_ids": [],
                    "generation": 0,
                    "island": 0,
                    "fitness_score": 0.45,
                    "normalized_score": 0.45,
                    "rejected": False,
                    "mutation_type": "seed",
                    "survived": True,
                    "template": None,
                },
            ]
            # Gen 1: each island refines from seed
            gen1_scores = [0.55, 0.60, 0.52, 0.58]
            for i, cid in enumerate(gen1_ids):
                lineage_events.append({
                    "candidate_id": cid,
                    "parent_ids": [seed_id],
                    "generation": 1,
                    "island": i,
                    "fitness_score": gen1_scores[i],
                    "normalized_score": gen1_scores[i],
                    "rejected": False,
                    "mutation_type": "rcc",
                    "survived": True,
                    "template": None,
                })
            # Gen 2: each island refines its own
            gen2_scores = [0.62, 0.70, 0.58, 0.65]
            for i, cid in enumerate(gen2_ids):
                lineage_events.append({
                    "candidate_id": cid,
                    "parent_ids": [gen1_ids[i]],
                    "generation": 2,
                    "island": i,
                    "fitness_score": gen2_scores[i],
                    "normalized_score": gen2_scores[i],
                    "rejected": False,
                    "mutation_type": "rcc",
                    "survived": True,
                    "template": None,
                })
            # Gen 3: island 1 produces the best candidate
            gen3_scores = [0.68, 0.85, 0.64, 0.72]
            for i, cid in enumerate(gen3_ids):
                lineage_events.append({
                    "candidate_id": cid,
                    "parent_ids": [gen2_ids[i]],
                    "generation": 3,
                    "island": i,
                    "fitness_score": gen3_scores[i],
                    "normalized_score": gen3_scores[i],
                    "rejected": False,
                    "mutation_type": "rcc",
                    "survived": True,
                    "template": (
                        "# Pizza IVR - Bella Italia (Optimized)\n\n"
                        "You are a professional and friendly phone assistant for "
                        '"Bella Italia" pizza restaurant.\n\n'
                        "## Rules\n"
                        "- Always greet using {{ customer_name }} when available\n"
                        "- For orders: confirm items, delivery address, and payment\n"
                        "- For complaints: show empathy and escalate to a human agent\n"
                        "- Use the provided tools to search menu and create orders\n"
                        "- Stay on topic — politely redirect off-topic requests\n"
                    ) if cid == best_id else None,
                })

            # Generation records for the fitness chart
            generation_records = [
                {
                    "generation": 0,
                    "best_fitness": 0.45,
                    "avg_fitness": 0.45,
                    "best_normalized": 0.45,
                    "avg_normalized": 0.45,
                    "candidates_evaluated": 1,
                    "cost_summary": {"total_usd": 0.0},
                },
                {
                    "generation": 1,
                    "best_fitness": 0.60,
                    "avg_fitness": 0.5625,
                    "best_normalized": 0.60,
                    "avg_normalized": 0.5625,
                    "candidates_evaluated": 4,
                    "cost_summary": {"total_usd": 0.0042},
                },
                {
                    "generation": 2,
                    "best_fitness": 0.70,
                    "avg_fitness": 0.6375,
                    "best_normalized": 0.70,
                    "avg_normalized": 0.6375,
                    "candidates_evaluated": 4,
                    "cost_summary": {"total_usd": 0.0038},
                },
                {
                    "generation": 3,
                    "best_fitness": 0.85,
                    "avg_fitness": 0.7225,
                    "best_normalized": 0.85,
                    "avg_normalized": 0.7225,
                    "candidates_evaluated": 4,
                    "cost_summary": {"total_usd": 0.0041},
                },
            ]

            # Case results for the best candidate
            tc_tiers = ["normal", "normal", "critical", "normal", "low"]
            tc_scores = [1.0, 1.0, 1.0, 0.0, 0.25]
            tc_passed = [True, True, True, False, False]
            tc_reasons = [
                "Response contains warm greeting with customer name",
                "search_menu tool called correctly",
                "create_order tool called with correct arguments",
                "Escalation offered but phrasing differs from expected",
                "Response redirects but missing exact 'only help with pizza' phrase",
            ]
            case_results = []
            for i, tc in enumerate(test_cases):
                case_results.append({
                    "case_id": tc.id,
                    "tier": tc_tiers[i],
                    "score": tc_scores[i],
                    "passed": tc_passed[i],
                    "reason": tc_reasons[i],
                })

            # Seed case results (baseline before evolution)
            seed_scores = [0.8, 0.5, 0.6, 0.0, 0.0]
            seed_passed = [True, False, False, False, False]
            seed_reasons = [
                "Basic greeting present but impersonal",
                "Described menu instead of using search_menu tool",
                "Attempted order but missed tool call",
                "No escalation path offered",
                "Engaged with off-topic request instead of redirecting",
            ]
            seed_case_results = []
            for i, tc in enumerate(test_cases):
                seed_case_results.append({
                    "case_id": tc.id,
                    "tier": tc_tiers[i],
                    "score": seed_scores[i],
                    "passed": seed_passed[i],
                    "reason": seed_reasons[i],
                })

            evolution_run = EvolutionRun(
                prompt_id="pizza-ivr",
                status="completed",
                meta_model="demo",
                target_model="demo",
                judge_model="demo",
                meta_provider="demo",
                target_provider="demo",
                judge_provider="demo",
                hyperparameters={
                    "generations": 3,
                    "islands": 4,
                    "conversations_per_island": 5,
                    "sample_size": 5,
                    "demo": True,
                },
                best_fitness_score=0.85,
                generations_completed=3,
                total_cost_usd=0.0121,
                total_api_calls=48,
                total_input_tokens=24500,
                total_output_tokens=18200,
                extra_metadata={
                    "lineage_events": lineage_events,
                    "generation_records": generation_records,
                    "case_results": case_results,
                    "seed_case_results": seed_case_results,
                    "best_candidate_id": best_id,
                    "best_normalized_score": 0.85,
                    "termination_reason": "max_generations_reached",
                },
            )
            session.add(evolution_run)

            await session.commit()

        logger.info(
            "Seeded demo pizza-ivr prompt with 5 test cases and 1 evolution run"
        )
        return True

    async def close(self) -> None:
        """Dispose of the engine and release all connections."""
        await self.engine.dispose()
