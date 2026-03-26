"""PromptRegistry service: register, load, list, update, and delete prompts.

The registry is the user-facing service for managing prompts with their full
configuration. It stores prompts in the database (Prompt ORM model) and uses
Jinja2 for template variable extraction. No filesystem reads or writes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from jinja2 import Environment, meta
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.config.loader import load_prompt_config
from api.config.models import GeneConfig
from api.exceptions import PromptAlreadyExistsError, PromptNotFoundError
from api.registry.models import PromptRecord, PromptRegistration, VariableDefinition
from api.registry.schemas import MockDefinition, ToolSchemaDefinition
from api.storage.models import Persona, Prompt, PromptConfig, PromptVersion, TestCaseRecord
from api.synthesis.models import PersonaProfile

logger = logging.getLogger(__name__)


def _extract_anchor_variables(variable_defs: list[VariableDefinition]) -> set[str]:
    """Extract anchor variable names, including dot-notation for nested anchors.

    For top-level variables with is_anchor=True, adds the variable name.
    For variables with items_schema, checks each sub-field and adds
    dot-notation paths (e.g. "items.name") for anchored sub-fields.

    Args:
        variable_defs: List of VariableDefinition objects.

    Returns:
        Set of anchor variable name strings.
    """
    anchors: set[str] = set()
    for v in variable_defs:
        if v.is_anchor:
            anchors.add(v.name)
        if v.items_schema:
            for sub in v.items_schema:
                if sub.is_anchor:
                    anchors.add(f"{v.name}.{sub.name}")
    return anchors


class PromptRegistry:
    """Service for registering, loading, and managing prompts via the database.

    Each prompt is stored as a row in the prompts table with JSON columns
    for variables, tools, tool_schemas, and mocks. No filesystem access.

    Attributes:
        session_factory: Async session factory for database access.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory
        self._jinja_env = Environment()

    async def register(self, prompt_data: PromptRegistration) -> PromptRecord:
        """Register a new prompt by inserting into the database.

        Args:
            prompt_data: The prompt registration data.

        Returns:
            A PromptRecord with the registered prompt's metadata.

        Raises:
            PromptAlreadyExistsError: If a prompt with this ID already exists.
        """
        async with self.session_factory() as session:
            # Check for existing prompt
            result = await session.execute(
                select(Prompt).where(Prompt.id == prompt_data.id)
            )
            if result.scalar_one_or_none() is not None:
                raise PromptAlreadyExistsError(
                    f"Prompt '{prompt_data.id}' already exists"
                )

            # Extract template variables
            template_variables = self.extract_variables(prompt_data.template)

            # Build variable definitions -- merge explicit with auto-extracted
            variable_defs = self._build_variable_definitions(
                prompt_data.variables, template_variables
            )

            # Determine anchor variables from definitions
            anchor_variables = _extract_anchor_variables(variable_defs)

            # Serialize variable defs to JSON-compatible dicts
            variables_json = [v.model_dump() for v in variable_defs]

            # Prepare tool_schemas and mocks as typed models for the return value
            tool_schema_models: list[ToolSchemaDefinition] | None = None
            tool_schemas_json: list[dict] | None = None
            if prompt_data.tool_schemas is not None:
                tool_schema_models = [
                    ToolSchemaDefinition(**d) for d in prompt_data.tool_schemas
                ]
                tool_schemas_json = prompt_data.tool_schemas

            mock_models: list[MockDefinition] | None = None
            mocks_json: list[dict] | None = None
            if prompt_data.mocks is not None:
                mock_models = [MockDefinition(**d) for d in prompt_data.mocks]
                # Basic validation: ensure all mock responses are non-empty strings
                for mock_def in mock_models:
                    for scenario in mock_def.scenarios:
                        if not scenario.response.strip():
                            raise ValueError(
                                f"Mock response for tool '{mock_def.tool_name}' "
                                f"must be a non-empty string"
                            )
                mocks_json = prompt_data.mocks

            # Insert prompt row
            prompt_row = Prompt(
                id=prompt_data.id,
                purpose=prompt_data.purpose,
                template=prompt_data.template,
                variables=variables_json,
                tools=prompt_data.tools,
                tool_schemas=tool_schemas_json,
                mocks=mocks_json,
                active_version=1,
            )
            session.add(prompt_row)

            # Auto-create version 1
            version_row = PromptVersion(
                prompt_id=prompt_data.id,
                version=1,
                template=prompt_data.template,
            )
            session.add(version_row)
            await session.commit()

            logger.info(
                "Registered prompt '%s' with %d variables (%d anchors)",
                prompt_data.id,
                len(template_variables),
                len(anchor_variables),
            )

            return PromptRecord(
                id=prompt_data.id,
                purpose=prompt_data.purpose,
                template_variables=template_variables,
                anchor_variables=anchor_variables,
                commit_hash=None,
                created_at=datetime.now(UTC),
                tool_schemas=tool_schema_models,
                mocks=mock_models,
            )

    async def load_prompt(
        self, prompt_id: str, base_config: GeneConfig | None = None
    ) -> PromptRecord:
        """Load a registered prompt by ID from the database.

        Reads the Prompt row and reconstructs the PromptRecord. If base_config
        is provided, queries PromptConfig for per-prompt overrides and merges.

        Args:
            prompt_id: The prompt identifier.
            base_config: Optional base GeneConfig to merge per-prompt overrides onto.

        Returns:
            A PromptRecord with all data populated.

        Raises:
            PromptNotFoundError: If no prompt with this ID exists.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(Prompt).where(Prompt.id == prompt_id)
            )
            prompt_row = result.scalar_one_or_none()
            if prompt_row is None:
                raise PromptNotFoundError(f"Prompt '{prompt_id}' not found")

            # Reconstruct variable definitions from JSON
            variable_defs = [
                VariableDefinition(**v) for v in (prompt_row.variables or [])
            ]
            anchor_variables = _extract_anchor_variables(variable_defs)
            template_variables = self.extract_variables(prompt_row.template)

            # Reconstruct tools
            tools = prompt_row.tools if prompt_row.tools else None

            # Reconstruct tool_schemas
            tool_schema_models: list[ToolSchemaDefinition] | None = None
            if prompt_row.tool_schemas:
                tool_schema_models = [
                    ToolSchemaDefinition(**d) for d in prompt_row.tool_schemas
                ]

            # Reconstruct mocks
            mock_models: list[MockDefinition] | None = None
            if prompt_row.mocks:
                mock_models = [MockDefinition(**d) for d in prompt_row.mocks]

            # Load personas from Persona table
            persona_result = await session.execute(
                select(Persona).where(Persona.prompt_id == prompt_id)
            )
            persona_rows = persona_result.scalars().all()
            persona_models: list[PersonaProfile] = [
                PersonaProfile(
                    id=p.persona_id,
                    role=p.role,
                    traits=p.traits,
                    communication_style=p.communication_style,
                    goal=p.goal,
                    edge_cases=p.edge_cases,
                    behavior_criteria=p.behavior_criteria,
                    language=p.language,
                    channel=p.channel,
                )
                for p in persona_rows
            ]

            # Merge per-prompt config if base_config is provided
            merged_config = None
            if base_config is not None:
                config_result = await session.execute(
                    select(PromptConfig).where(PromptConfig.prompt_id == prompt_id)
                )
                config_row = config_result.scalar_one_or_none()
                if config_row is not None:
                    overrides: dict = {}
                    if config_row.provider:
                        overrides["meta_provider"] = config_row.provider
                    if config_row.model:
                        overrides["meta_model"] = config_row.model
                    if config_row.temperature is not None:
                        overrides["meta_temperature"] = config_row.temperature
                    if config_row.thinking_budget is not None:
                        overrides["meta_thinking_budget"] = config_row.thinking_budget
                    # Merge extra fields (target/judge overrides, etc.)
                    if config_row.extra:
                        overrides.update(config_row.extra)
                    merged_config = load_prompt_config(
                        base_config, prompt_dir=None, overrides_dict=overrides
                    )
                else:
                    merged_config = base_config

            return PromptRecord(
                id=prompt_id,
                purpose=prompt_row.purpose,
                template=prompt_row.template,
                template_variables=template_variables,
                anchor_variables=anchor_variables,
                commit_hash=None,
                created_at=prompt_row.created_at or datetime.now(UTC),
                config=merged_config,
                tools=tools,
                tool_schemas=tool_schema_models,
                mocks=mock_models,
                personas=persona_models,
            )

    async def list_prompts(self) -> list[str]:
        """List all registered prompt IDs, sorted alphabetically.

        Returns:
            Sorted list of prompt IDs.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(Prompt.id).order_by(Prompt.id)
            )
            return list(result.scalars().all())

    async def update_template(
        self, prompt_id: str, new_template: str, message: str
    ) -> PromptRecord:
        """Update the template for an existing prompt.

        Updates the Prompt.template column and re-extracts variables.

        Args:
            prompt_id: The prompt identifier.
            new_template: The new Jinja2 template content.
            message: Description of the update (logged but no git commit).

        Returns:
            Updated PromptRecord with new template variables.

        Raises:
            PromptNotFoundError: If no prompt with this ID exists.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(Prompt).where(Prompt.id == prompt_id)
            )
            prompt_row = result.scalar_one_or_none()
            if prompt_row is None:
                raise PromptNotFoundError(f"Prompt '{prompt_id}' not found")

            # Update template
            prompt_row.template = new_template

            # Create a new version for the template edit
            new_ver = await self._create_next_version(session, prompt_id, new_template)
            prompt_row.active_version = new_ver

            await session.commit()

            # Re-extract variables
            template_variables = self.extract_variables(new_template)

            # Read existing variable definitions for anchor info
            variable_defs = [
                VariableDefinition(**v) for v in (prompt_row.variables or [])
            ]
            anchor_variables = _extract_anchor_variables(variable_defs)

            logger.info(
                "Updated template for prompt '%s': %s (version %d)",
                prompt_id,
                message,
                new_ver,
            )

            return PromptRecord(
                id=prompt_id,
                purpose=prompt_row.purpose,
                template_variables=template_variables,
                anchor_variables=anchor_variables,
                commit_hash=None,
                created_at=prompt_row.created_at or datetime.now(UTC),
            )

    async def delete_prompt(self, prompt_id: str) -> None:
        """Delete a prompt and all associated data (test cases, config, personas).

        Args:
            prompt_id: The prompt identifier.

        Raises:
            PromptNotFoundError: If no prompt with this ID exists.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(Prompt).where(Prompt.id == prompt_id)
            )
            prompt_row = result.scalar_one_or_none()
            if prompt_row is None:
                raise PromptNotFoundError(f"Prompt '{prompt_id}' not found")

            # Delete cascaded data
            await session.execute(
                delete(TestCaseRecord).where(TestCaseRecord.prompt_id == prompt_id)
            )
            await session.execute(
                delete(PromptConfig).where(PromptConfig.prompt_id == prompt_id)
            )
            await session.execute(
                delete(Persona).where(Persona.prompt_id == prompt_id)
            )

            # Delete the prompt itself
            await session.delete(prompt_row)
            await session.commit()

            logger.info("Deleted prompt '%s' and all associated data", prompt_id)

    @staticmethod
    async def _create_next_version(
        session: AsyncSession, prompt_id: str, template: str
    ) -> int:
        """Create the next version for a prompt and return the version number."""
        max_ver_result = await session.execute(
            select(func.max(PromptVersion.version)).where(
                PromptVersion.prompt_id == prompt_id
            )
        )
        max_ver = max_ver_result.scalar() or 0
        new_ver = max_ver + 1
        session.add(PromptVersion(
            prompt_id=prompt_id, version=new_ver, template=template
        ))
        return new_ver

    async def create_version(self, prompt_id: str, template: str) -> dict:
        """Create a new version for a prompt.

        Inserts a new PromptVersion row with version = max(existing) + 1,
        sets it as the active version, and updates Prompt.template.

        Idempotent: if the latest version already has the same template,
        returns it instead of creating a duplicate.

        Args:
            prompt_id: The prompt identifier.
            template: The template text for the new version.

        Returns:
            Dict with version number, template text, created_at ISO string,
            and ``already_existed`` boolean.

        Raises:
            PromptNotFoundError: If the prompt does not exist.
        """
        async with self.session_factory() as session:
            # Verify prompt exists
            result = await session.execute(
                select(Prompt).where(Prompt.id == prompt_id)
            )
            prompt_row = result.scalar_one_or_none()
            if prompt_row is None:
                raise PromptNotFoundError(f"Prompt '{prompt_id}' not found")

            # Check if the latest version already has the same template
            latest = await session.execute(
                select(PromptVersion)
                .where(PromptVersion.prompt_id == prompt_id)
                .order_by(PromptVersion.version.desc())
                .limit(1)
            )
            latest_row = latest.scalar_one_or_none()
            if latest_row is not None and latest_row.template == template:
                logger.info(
                    "Version %d for prompt '%s' already matches, skipping duplicate",
                    latest_row.version,
                    prompt_id,
                )
                return {
                    "version": latest_row.version,
                    "template": template,
                    "created_at": latest_row.created_at.isoformat()
                    if latest_row.created_at
                    else datetime.now(UTC).isoformat(),
                    "already_existed": True,
                }

            # Create next version and set as active
            new_ver = await self._create_next_version(session, prompt_id, template)
            prompt_row.active_version = new_ver
            prompt_row.template = template
            await session.commit()

            logger.info(
                "Created version %d for prompt '%s'",
                new_ver,
                prompt_id,
            )

            return {
                "version": new_ver,
                "template": template,
                "created_at": datetime.now(UTC).isoformat(),
                "already_existed": False,
            }

    async def list_versions(self, prompt_id: str) -> list[dict]:
        """List all versions for a prompt, ordered by version number ascending.

        Args:
            prompt_id: The prompt identifier.

        Returns:
            List of dicts with version, template, and created_at for each version.

        Raises:
            PromptNotFoundError: If the prompt does not exist.
        """
        async with self.session_factory() as session:
            # Verify prompt exists
            result = await session.execute(
                select(Prompt).where(Prompt.id == prompt_id)
            )
            if result.scalar_one_or_none() is None:
                raise PromptNotFoundError(f"Prompt '{prompt_id}' not found")

            ver_result = await session.execute(
                select(PromptVersion)
                .where(PromptVersion.prompt_id == prompt_id)
                .order_by(PromptVersion.version.asc())
            )
            versions = ver_result.scalars().all()

            return [
                {
                    "version": v.version,
                    "template": v.template,
                    "created_at": v.created_at.isoformat()
                    if v.created_at
                    else datetime.now(UTC).isoformat(),
                }
                for v in versions
            ]

    async def activate_version(self, prompt_id: str, version: int) -> dict:
        """Activate a specific version for a prompt.

        Sets Prompt.active_version and copies the version's template
        to Prompt.template.

        Args:
            prompt_id: The prompt identifier.
            version: The version number to activate.

        Returns:
            Dict with version number and template text.

        Raises:
            PromptNotFoundError: If the prompt or version does not exist.
        """
        async with self.session_factory() as session:
            # Verify prompt exists
            result = await session.execute(
                select(Prompt).where(Prompt.id == prompt_id)
            )
            prompt_row = result.scalar_one_or_none()
            if prompt_row is None:
                raise PromptNotFoundError(f"Prompt '{prompt_id}' not found")

            # Get the target version
            ver_result = await session.execute(
                select(PromptVersion).where(
                    PromptVersion.prompt_id == prompt_id,
                    PromptVersion.version == version,
                )
            )
            version_row = ver_result.scalar_one_or_none()
            if version_row is None:
                raise PromptNotFoundError(
                    f"Version {version} not found for prompt '{prompt_id}'"
                )

            # Update prompt to use this version
            prompt_row.active_version = version
            prompt_row.template = version_row.template
            await session.commit()

            logger.info(
                "Activated version %d for prompt '%s'",
                version,
                prompt_id,
            )

            return {
                "version": version,
                "template": version_row.template,
            }

    async def get_version_template(self, prompt_id: str, version: int) -> str:
        """Get the template text for a specific version.

        Args:
            prompt_id: The prompt identifier.
            version: The version number.

        Returns:
            The template text for the specified version.

        Raises:
            PromptNotFoundError: If the version does not exist.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(PromptVersion).where(
                    PromptVersion.prompt_id == prompt_id,
                    PromptVersion.version == version,
                )
            )
            version_row = result.scalar_one_or_none()
            if version_row is None:
                raise PromptNotFoundError(
                    f"Version {version} not found for prompt '{prompt_id}'"
                )
            return version_row.template

    def extract_variables(self, template_source: str) -> set[str]:
        """Extract variable names from a Jinja2 template.

        Uses jinja2 Environment.parse() + meta.find_undeclared_variables()
        to reliably extract all template variables, including those with filters.

        Args:
            template_source: The Jinja2 template string.

        Returns:
            Set of variable names found in the template.
        """
        ast = self._jinja_env.parse(template_source)
        return meta.find_undeclared_variables(ast)

    def _build_variable_definitions(
        self,
        explicit_vars: list[VariableDefinition] | None,
        template_variables: set[str],
    ) -> list[VariableDefinition]:
        """Build variable definitions by merging explicit with auto-extracted.

        If explicit_vars is provided, use them. For any template variables not
        covered by explicit definitions, create default VariableDefinition entries.

        Args:
            explicit_vars: Optional explicit variable definitions from the user.
            template_variables: Variable names extracted from the template.

        Returns:
            Complete list of VariableDefinition for all template variables.
        """
        if explicit_vars is not None:
            # Use explicit definitions, add any missing auto-extracted ones
            explicit_names = {v.name for v in explicit_vars}
            result = list(explicit_vars)
            for var_name in sorted(template_variables - explicit_names):
                result.append(VariableDefinition(name=var_name))
            return result

        # No explicit definitions -- auto-extract all
        return [VariableDefinition(name=name) for name in sorted(template_variables)]
