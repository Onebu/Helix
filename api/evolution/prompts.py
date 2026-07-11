"""Prompt templates for the RCC (Refinement through Critical Conversation) engine.

All prompts use Python .format() placeholders -- NOT Jinja2 -- to avoid
template-in-template confusion. Literal Jinja2 braces in the prompts
(explaining variable syntax to the meta-model) are escaped as {{{{ }}}}
so .format() passes them through as {{ }}.

Prompts:
    CRITIC_SYSTEM_PROMPT: Instructs the critic to analyze failing test cases.
    CRITIC_USER_PROMPT: Provides template + failing/passing cases to the critic.
    AUTHOR_SYSTEM_PROMPT: Instructs the author to revise the template.
    AUTHOR_USER_PROMPT: Provides critic analysis + template + required variables.
    FRESH_GENERATION_PROMPT: Generates a template from scratch (no-parent case).
    DIVERSE_RESET_PROMPT: Selects a requested number of diverse candidate IDs.
"""

CRITIC_SYSTEM_PROMPT = """\
You are an expert prompt engineer acting as a critic.
Your job is to analyze an LLM prompt template and identify why it fails certain test cases.

CRITICAL CONSTRAINT -- IMMUTABLE VARIABLES:
The following Jinja2 variable names are FIXED and must NEVER be renamed, removed, or modified:
{required_variables}

These variables are injected at runtime by external systems. Renaming them (e.g., changing \
{{{{ business_name }}}} to {{{{ restaurant_name }}}}) will break the template. Your analysis \
must work WITHIN the existing variable names.

The prompt is being optimized for: {purpose}"""

CRITIC_USER_PROMPT = """\
Here is the evidence from every selected parent:

<parent_evidence>
{parent_evidence}
</parent_evidence>

Here is the current prompt template to critique and improve:

<prompt_template>
{current_template}
</prompt_template>

Here are the test cases where the prompt FAILED:

{failing_cases_formatted}

Here are the test cases where the prompt PASSED (for context):

{passing_cases_summary}

Analyze the failing cases. For each failure:
1. What specific aspect of the prompt caused this failure?
2. What change would fix this case without breaking the passing cases?
3. Are there structural issues (section ordering, missing context, unclear instructions)?

Provide your analysis as a structured critique.

REMINDER: These variables are IMMUTABLE and must not be renamed: {required_variables}"""

AUTHOR_SYSTEM_PROMPT = """\
You are an expert prompt engineer acting as an author.
Your job is to revise an LLM prompt template based on a critic's analysis to fix failing test cases.

CRITICAL RULES:
1. These Jinja2 variables are IMMUTABLE -- they must appear exactly as-is: {required_variables}
   Do NOT rename any variable (e.g., do NOT change {{{{ business_name }}}} to {{{{ restaurant_name }}}}).
2. Fix the issues identified by the critic while preserving behavior on passing cases.
3. Return the revised prompt template inside <revised_template> and </revised_template> delimiters.
4. The revised prompt must be a valid Jinja2 template.

MINIMAL EDIT POLICY:
5. Make MINIMAL, TARGETED changes. Do NOT rewrite or restructure the entire prompt.
6. Preserve the original language, writing style, section structure, and formatting.
7. Only add, remove, or modify lines directly related to the failing test cases.
8. Surgical edits: insert a rule, add an example, reword a sentence -- not a full rewrite.
9. If the original is in Spanish, keep it in Spanish. Do not change the language."""

AUTHOR_USER_PROMPT = """\
The critic analyzed the prompt and identified these issues:

<critic_analysis>
{critic_analysis}
</critic_analysis>

The current prompt template:

<prompt_template>
{template}
</prompt_template>

Required variables that MUST appear in the revised template: {required_variables}

Revise the prompt to address the critic's feedback. Return ONLY the revised prompt template \
inside <revised_template> and </revised_template> delimiters."""

FRESH_GENERATION_PROMPT = """\
You are an expert prompt engineer. Create a new LLM prompt template from scratch.

PURPOSE: {purpose}

The template must use Jinja2 syntax with these REQUIRED variables:
{required_variables}

Variable descriptions:
{variable_descriptions}

Create a well-structured prompt template that:
1. Uses all required variables as {{{{ variable_name }}}} placeholders
2. Has clear instructions for the target LLM
3. Is organized with logical section flow
4. Includes any necessary context or constraints

Return ONLY the prompt template inside <revised_template> and </revised_template> delimiters."""

DIVERSE_RESET_PROMPT = """\
Select {count} prompt candidates that together provide the strongest and most diverse reset set.

Candidates:
{candidates}

Return exactly one comma-separated list of candidate IDs inside <candidate_ids> and
</candidate_ids>. Return IDs from the candidate list only, with no duplicates and no other text."""
