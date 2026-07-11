"""StructuralMutator: section-level prompt restructuring via meta-model.

Evolves prompt structure (reorder, split, merge sections) separately from
text content refinement. Section ordering can impact LLM performance by up
to 40% according to research, making structural mutation a valuable
complement to text-focused RCC refinement.

Uses the meta-model to propose ONE structural change per mutation call.
All mutations are validated for variable preservation and Jinja2 syntax
correctness before being accepted.
"""

from __future__ import annotations

import logging
import re

from jinja2 import TemplateSyntaxError

from api.evaluation.renderer import TemplateRenderer, TemplateRenderError
from api.evaluation.validator import TemplateValidator
from api.evolution.models import Candidate
from api.evolution.scouting import canonicalize_template
from api.gateway.cost import CostTracker
from api.gateway.protocol import LLMProvider
from api.registry.sections import SectionParser
from api.types import ModelRole

logger = logging.getLogger(__name__)

# Regex to extract content between <revised_template> delimiters.
_REVISED_TEMPLATE_RE = re.compile(
    r"<revised_template>\s*\n?(.*?)\n?\s*</revised_template>",
    re.DOTALL,
)

# Private module-level constant to avoid file ownership conflict with
# Plan 02's prompts.py. Uses .format() (not Jinja2) for variable injection.
_STRUCTURAL_MUTATION_PROMPT = """\
You are a prompt engineering expert specializing in structural optimization.

Analyze the following prompt template and propose exactly ONE structural change \
to improve its organization. You may:
- Reorder sections to place the most important information first
- Split a long section into two focused sections
- Merge related sections that cover the same topic
- Add or rename section headers for clarity

IMPORTANT RULES:
1. These Jinja2 variables are IMMUTABLE and must appear exactly as-is in the output: \
{required_variables}
   Do NOT rename any variable (e.g., do NOT change {{{{ business_name }}}} to \
{{{{ restaurant_name }}}}).
2. Do NOT modify the content within sections -- only restructure the layout.
3. Do NOT add or remove any Jinja2 control structures.
4. Wrap your revised template in <revised_template> tags.

Current template:
{template}

Provide your restructured version inside <revised_template> tags."""

# Section-aware variant used when the template has identifiable H1/H2 sections.
# Includes a compact section summary so the meta-model understands the template
# structure before proposing changes. Uses .format() with {section_summary},
# {template}, and {required_variables} placeholders.
_SECTION_AWARE_MUTATION_PROMPT = """\
You are a prompt engineering expert specializing in structural optimization.

The following prompt template uses a sectioning standard with H1/H2 headers.

Section structure:
{section_summary}

Analyze the template and propose exactly ONE structural change \
to improve its organization. You may:
- Reorder sections to place the most important information first
- Split a long section into two focused sections
- Merge related sections that cover the same topic
- Add or rename section headers for clarity

IMPORTANT RULES:
1. These Jinja2 variables are IMMUTABLE and must appear exactly as-is in the output: \
{required_variables}
   Do NOT rename any variable (e.g., do NOT change {{{{ business_name }}}} to \
{{{{ restaurant_name }}}}).
2. Do NOT modify the content within sections -- only restructure the layout.
3. Do NOT add or remove any Jinja2 control structures.
4. Maintain the H1/H2 + XML sectioning standard.
5. Wrap your revised template in <revised_template> tags.

Current template:
{template}

Provide your restructured version inside <revised_template> tags."""


class StructuralMutator:
    """Mutates prompt structure by reordering, splitting, or merging sections.

    Uses a meta-model to analyze section arrangement and propose structural
    changes. Validates that all Jinja2 variables are preserved and the
    template renders without syntax errors before accepting a mutation.

    If validation fails (lost variables or syntax error), the original
    candidate is returned unchanged.

    Example:
        mutator = StructuralMutator(
            client=client,
            cost_tracker=tracker,
            validator=TemplateValidator(),
            meta_model="anthropic/claude-sonnet-4",
        )
        mutated = await mutator.mutate(candidate, original, anchor_vars)
    """

    def __init__(
        self,
        client: LLMProvider,
        cost_tracker: CostTracker,
        validator: TemplateValidator,
        meta_model: str,
        extra_kwargs: dict | None = None,
    ) -> None:
        if getattr(client, "owns_cost_accounting", False) is True and getattr(
            client, "cost_tracker", None
        ) is not cost_tracker:
            raise ValueError("Accounting provider and mutator must use the same CostTracker")
        self._client = client
        self._cost_tracker = cost_tracker
        self._validator = validator
        self._meta_model = meta_model
        self._renderer = TemplateRenderer()
        self._extra_kwargs = extra_kwargs

    async def mutate(
        self,
        candidate: Candidate,
        original_template: str,
        anchor_variables: set[str],
    ) -> Candidate:
        """Apply structural mutation to a candidate's template.

        Asks the meta-model to propose ONE structural change (reorder,
        split, merge sections). Validates the result preserves all
        variables and renders without errors. Returns original candidate
        unchanged if mutation is invalid.

        Args:
            candidate: The candidate to mutate.
            original_template: The original (seed) template for variable
                reference.
            anchor_variables: Set of variable names that must be preserved.

        Returns:
            A new Candidate with restructured template if mutation is valid,
            or the original candidate unchanged if validation fails.
        """
        # Parse sections to decide which prompt to use
        sections = SectionParser.parse(candidate.template)
        required_variables_str = ", ".join(sorted(anchor_variables))

        if len(sections) > 1:
            # Template has actual headers -- use section-aware prompt
            section_summary = SectionParser.format_summary(sections)
            prompt_text = _SECTION_AWARE_MUTATION_PROMPT.format(
                section_summary=section_summary,
                template=candidate.template,
                required_variables=required_variables_str,
            )
        else:
            # Unsectioned template -- use original prompt
            prompt_text = _STRUCTURAL_MUTATION_PROMPT.format(
                template=candidate.template,
                required_variables=required_variables_str,
            )

        messages = [{"role": "user", "content": prompt_text}]

        # Call meta-model
        response = await self._client.chat_completion(
            messages,
            model=self._meta_model,
            role=ModelRole.META,
            **(self._extra_kwargs or {}),
        )

        if getattr(self._client, "owns_cost_accounting", False) is not True:
            self._cost_tracker.record(response)

        # Extract mutated template from response
        mutated_template = self._extract_template(response.content or "")

        if not mutated_template or not mutated_template.strip():
            logger.warning("Structural mutation produced empty template, keeping original")
            return candidate

        if canonicalize_template(mutated_template) == canonicalize_template(candidate.template):
            logger.warning("Structural mutation left template unchanged, keeping original")
            return candidate

        # Validate Jinja2 syntax first -- broken syntax would also cause
        # the variable validator's parse() call to fail with TemplateSyntaxError
        try:
            self._renderer.render(
                mutated_template,
                {var: "" for var in anchor_variables},
            )
        except TemplateRenderError as exc:
            logger.warning(
                "Structural mutation produced invalid syntax: %s, keeping original",
                exc,
            )
            return candidate
        except TemplateSyntaxError as exc:
            logger.warning(
                "Structural mutation produced invalid syntax: %s, keeping original",
                exc,
            )
            return candidate

        # Validate variable preservation
        validation = self._validator.validate_preserved(
            original_template, mutated_template, anchor_variables
        )
        if not validation.valid:
            logger.warning(
                "Structural mutation dropped variables %s, keeping original",
                validation.missing_variables,
            )
            return candidate

        # Both validations passed -- create new candidate
        return Candidate(
            template=mutated_template,
            fitness_score=0.0,  # needs re-evaluation
            evaluation=None,
            generation=candidate.generation,
            parent_ids=[candidate.id],
        )

    @staticmethod
    def _extract_template(content: str) -> str:
        """Extract template from <revised_template> delimiters.

        Falls back to using the full content if no delimiters are found.

        Args:
            content: Raw LLM response text.

        Returns:
            Extracted template string.
        """
        match = _REVISED_TEMPLATE_RE.search(content)
        if match:
            return match.group(1)
        return content
