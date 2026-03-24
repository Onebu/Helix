"""Shared test fixtures for Helix."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clean_gene_env(monkeypatch):
    """Remove GENE_* env vars to prevent .env pollution across tests.

    load_dotenv() is called at module import time via api.web.app's
    module-level ``app = create_app()``.  This leaks .env values into
    every test that transitively imports from the web layer.

    We also neutralize load_dotenv so that test fixtures calling
    create_app() don't re-load .env values after cleanup.
    """
    monkeypatch.setattr("api.web.app.load_dotenv", lambda *a, **kw: None)
    for key in list(os.environ):
        if key.startswith("GENE_"):
            monkeypatch.delenv(key)


@pytest.fixture
def tmp_prompts_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for prompt storage in tests."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    return prompts_dir


@pytest.fixture
def sample_gene_config():
    """Create a GeneConfig with test values using constructor args (no env vars needed)."""
    from api.config.models import GeneConfig

    return GeneConfig(
        openrouter_api_key="test-api-key-12345",
        database_url="postgresql://test:test@localhost:5432/test_gene",
        meta_model="anthropic/claude-sonnet-4",
        target_model="openai/gpt-4o-mini",
        judge_model="anthropic/claude-sonnet-4",
        concurrency_limit=5,
        prompts_dir="./test-prompts",
    )
