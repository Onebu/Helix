"""Tests for GET/PUT prompt config API endpoints and synthesis config fix.

Tests validate DB-backed per-prompt config: reads/writes go to the PromptConfig table,
config.json sidecars are no longer written by PUT. Response shapes unchanged.

Covers requirements: CFG-01, CFG-03, CFG-04, DB-01, DB-02
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.storage.models import PromptConfig

# -- Helpers --


async def _register_prompt(
    client: httpx.AsyncClient,
    prompt_id: str = "test-prompt",
    template: str = "Hello {{ name }}",
    purpose: str = "A test prompt",
) -> httpx.Response:
    """POST a new prompt and return the response."""
    return await client.post(
        "/api/prompts/",
        json={
            "id": prompt_id,
            "purpose": purpose,
            "template": template,
        },
    )


async def _add_case(client: httpx.AsyncClient, prompt_id: str) -> None:
    await client.post(
        f"/api/prompts/{prompt_id}/dataset",
        json={
            "name": "config test case",
            "variables": {"name": "world"},
            "expected_output": {"contains": "Hello"},
        },
    )


# -- GET /api/prompts/{id}/config --


class TestGetPromptConfig:
    """GET /api/prompts/{id}/config returns effective merged config from DB."""

    async def test_returns_effective_config_all_global(self, client: httpx.AsyncClient):
        """Prompt with no DB PromptConfig row returns all-global values."""
        await _register_prompt(client, "cfg-test")

        resp = await client.get("/api/prompts/cfg-test/config")
        assert resp.status_code == 200
        data = resp.json()

        # Should have meta/target/judge role configs
        assert "meta" in data
        assert "target" in data
        assert "judge" in data

        # Meta defaults from GeneConfig
        assert data["meta"]["provider"] == "openrouter"
        assert data["meta"]["model"] == "anthropic/claude-sonnet-4"

        # Target defaults
        assert data["target"]["provider"] == "openrouter"
        assert data["target"]["model"] == "openai/gpt-4o-mini"

        # Judge defaults
        assert data["judge"]["provider"] == "openrouter"
        assert data["judge"]["model"] == "anthropic/claude-sonnet-4"

    async def test_returns_empty_overrides_when_no_db_row(self, client: httpx.AsyncClient):
        """Prompt with no DB PromptConfig row returns empty overrides dict."""
        await _register_prompt(client, "no-cfg")

        resp = await client.get("/api/prompts/no-cfg/config")
        assert resp.status_code == 200
        data = resp.json()

        assert data["overrides"] == {}

    async def test_returns_merged_overrides_from_db(
        self, client: httpx.AsyncClient, db_session: AsyncSession
    ):
        """Prompt with DB PromptConfig row returns merged effective values."""
        await _register_prompt(client, "has-cfg")

        # Seed a PromptConfig row in DB
        pc = PromptConfig(
            prompt_id="has-cfg",
            provider="gemini",
            model="gemini-2.5-pro",
            temperature=0.9,
            extra={
                "meta_provider": "gemini",
                "meta_model": "gemini-2.5-pro",
                "meta_temperature": 0.9,
            },
        )
        db_session.add(pc)
        await db_session.commit()

        resp = await client.get("/api/prompts/has-cfg/config")
        assert resp.status_code == 200
        data = resp.json()

        # Meta should reflect overrides
        assert data["meta"]["provider"] == "gemini"
        assert data["meta"]["model"] == "gemini-2.5-pro"
        assert data["meta"]["temperature"] == 0.9

        # Target/judge should remain global defaults
        assert data["target"]["provider"] == "openrouter"
        assert data["judge"]["provider"] == "openrouter"

        # Overrides dict should list the prompt-level fields
        assert "meta_provider" in data["overrides"]
        assert "meta_model" in data["overrides"]
        assert "meta_temperature" in data["overrides"]

    async def test_returns_404_for_nonexistent_prompt(self, client: httpx.AsyncClient):
        """GET config for non-existent prompt returns 404."""
        resp = await client.get("/api/prompts/nonexistent/config")
        assert resp.status_code == 404

    async def test_temperature_fallback_to_generation(self, client: httpx.AsyncClient):
        """When no per-role temperature set, temperature falls back to generation.temperature."""
        await _register_prompt(client, "gen-temp")

        resp = await client.get("/api/prompts/gen-temp/config")
        assert resp.status_code == 200
        data = resp.json()

        # Per-role temperature not set, should show generation.temperature fallback
        # GeneConfig defaults generation.temperature to 0.7
        assert data["meta"]["temperature"] == 0.7
        assert data["target"]["temperature"] == 0.7
        assert data["judge"]["temperature"] == 0.7


# -- PUT /api/prompts/{id}/config --


class TestPutPromptConfig:
    """PUT /api/prompts/{id}/config writes to DB PromptConfig and returns updated values."""

    async def test_writes_to_db_and_returns_effective(
        self, client: httpx.AsyncClient, db_session: AsyncSession
    ):
        """PUT writes PromptConfig to DB (not config.json) and returns updated effective config."""
        await _register_prompt(client, "put-test")

        resp = await client.put(
            "/api/prompts/put-test/config",
            json={
                "meta_provider": "gemini",
                "meta_model": "gemini-2.5-pro",
                "meta_temperature": 0.9,
                "meta_thinking_budget": -1,
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        # Effective values should reflect the new overrides
        assert data["meta"]["provider"] == "gemini"
        assert data["meta"]["model"] == "gemini-2.5-pro"
        assert data["meta"]["temperature"] == 0.9
        assert data["meta"]["thinking_budget"] == -1

        # Verify DB row was created
        result = await db_session.execute(
            select(PromptConfig).where(PromptConfig.prompt_id == "put-test")
        )
        row = result.scalar_one()
        assert row is not None
        assert row.extra["meta_provider"] == "gemini"

    async def test_does_not_write_config_json(self, client: httpx.AsyncClient, tmp_path):
        """PUT does NOT write or modify config.json sidecar -- persistence is DB only."""
        await _register_prompt(client, "no-json")

        # Verify no config.json is created anywhere (filesystem is not used)
        config_path = tmp_path / "no-json" / "config.json"
        assert not config_path.exists(), "No filesystem dir should exist for prompts"

        await client.put(
            "/api/prompts/no-json/config",
            json={
                "target_model": "gpt-4o",
                "target_provider": "openai",
            },
        )

        assert not config_path.exists(), "config.json should not be written by PUT"

    async def test_excludes_none_fields_from_overrides(self, client: httpx.AsyncClient):
        """PUT with None fields omits them from overrides dict."""
        await _register_prompt(client, "none-test")

        resp = await client.put(
            "/api/prompts/none-test/config",
            json={
                "target_model": "gpt-4o",
                "target_provider": "openai",
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        # Only the explicitly set fields should be in overrides
        assert "target_model" in data["overrides"]
        assert "target_provider" in data["overrides"]
        # None fields should NOT be in overrides
        assert "meta_provider" not in data["overrides"]
        assert "meta_temperature" not in data["overrides"]
        assert "generation" not in data["overrides"]

    async def test_put_returns_404_for_nonexistent_prompt(self, client: httpx.AsyncClient):
        """PUT config for non-existent prompt returns 404."""
        resp = await client.put(
            "/api/prompts/nonexistent/config",
            json={"meta_model": "test"},
        )
        assert resp.status_code == 404

    async def test_put_then_get_returns_consistent_data(self, client: httpx.AsyncClient):
        """PUT followed by GET returns consistent data."""
        await _register_prompt(client, "roundtrip")

        # PUT config
        await client.put(
            "/api/prompts/roundtrip/config",
            json={
                "meta_provider": "gemini",
                "meta_model": "gemini-2.5-pro",
                "target_temperature": 0.0,
                "judge_thinking_budget": 2048,
            },
        )

        # GET config
        resp = await client.get("/api/prompts/roundtrip/config")
        assert resp.status_code == 200
        data = resp.json()

        assert data["meta"]["provider"] == "gemini"
        assert data["meta"]["model"] == "gemini-2.5-pro"
        assert data["target"]["temperature"] == 0.0
        assert data["judge"]["thinking_budget"] == 2048

        # Overrides should reflect what was PUT
        assert "meta_provider" in data["overrides"]
        assert "target_temperature" in data["overrides"]
        assert "judge_thinking_budget" in data["overrides"]

    async def test_overrides_shows_only_non_null_fields(self, client: httpx.AsyncClient):
        """Overrides dict in response shows only non-null prompt-level overrides."""
        await _register_prompt(client, "override-test")

        resp = await client.put(
            "/api/prompts/override-test/config",
            json={
                "meta_model": "custom-model",
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        # Only meta_model should be in overrides
        assert data["overrides"] == {"meta_model": "custom-model"}


# -- Synthesis router fix (CFG-03) --


class TestSynthesisUsesPromptConfig:
    """Synthesis background task should use load_prompt_config."""

    async def test_synthesis_router_imports_load_prompt_config(self):
        """The synthesis module should reference load_prompt_config."""
        import inspect

        from api.web.routers import synthesis

        source = inspect.getsource(synthesis._run_synthesis_background)
        assert "load_prompt_config" in source

    async def test_synthesis_router_uses_merged_config(self):
        """The synthesis background task should use merged_config, not raw config."""
        import inspect

        from api.web.routers import synthesis

        source = inspect.getsource(synthesis._run_synthesis_background)
        # Should reference merged_config for provider creation
        assert "merged_config" in source
        # Should NOT directly use config.meta_provider (should be merged_config.meta_provider)
        # The pattern "config.meta_provider" should be replaced with "merged_config.meta_provider"
        # We check that "merged_config.meta_provider" appears
        assert "merged_config.meta_provider" in source


# -- Evolution router config precedence (CFG-05) --


class TestEvolutionUsesPromptConfig:
    @patch("api.evolution.runner.run_evolution", new_callable=AsyncMock)
    async def test_prompt_config_is_base_and_request_overrides_win(
        self,
        mock_run_evolution: AsyncMock,
        client: httpx.AsyncClient,
    ):
        run_started = asyncio.Event()

        async def run_evolution(*args, **kwargs):
            run_started.set()

        mock_run_evolution.side_effect = run_evolution

        await _register_prompt(client, "evolution-config")
        await _add_case(client, "evolution-config")
        response = await client.put(
            "/api/prompts/evolution-config/config",
            json={
                "meta_model": "prompt-meta",
                "meta_provider": "gemini",
                "target_model": "prompt-target",
                "target_provider": "openai",
                "judge_model": "prompt-judge",
                "judge_provider": "gemini",
                "generation": {
                    "temperature": 0.2,
                    "max_tokens": 1234,
                    "top_p": 0.8,
                },
                "meta_thinking_budget": 128,
                "target_thinking_budget": 256,
                "judge_thinking_budget": 512,
            },
        )
        assert response.status_code == 200

        response = await client.post(
            "/api/evolution/start",
            json={
                "prompt_id": "evolution-config",
                "target_model": "request-target",
                "target_provider": "openrouter",
                "inference_temperature": 0.6,
                "meta_thinking_budget": 1024,
                "target_thinking_level": "low",
            },
        )
        assert response.status_code == 200
        await asyncio.wait_for(run_started.wait(), timeout=1)

        merged_config = mock_run_evolution.call_args.args[0]
        assert merged_config.meta_model == "prompt-meta"
        assert merged_config.meta_provider == "gemini"
        assert merged_config.target_model == "prompt-target"
        assert merged_config.target_provider == "openai"
        assert merged_config.judge_model == "prompt-judge"
        assert merged_config.judge_provider == "gemini"
        assert mock_run_evolution.call_args.kwargs | {
            "meta_model": "prompt-meta",
            "meta_provider": "gemini",
            "target_model": "request-target",
            "target_provider": "openrouter",
            "judge_model": "prompt-judge",
            "judge_provider": "gemini",
        } == mock_run_evolution.call_args.kwargs

        status = response.json()
        assert status["meta_model"] == "prompt-meta"
        assert status["meta_provider"] == "gemini"
        assert status["target_model"] == "request-target"
        assert status["target_provider"] == "openrouter"
        assert status["judge_model"] == "prompt-judge"
        assert status["judge_provider"] == "gemini"

        generation_config = mock_run_evolution.call_args.kwargs["generation_config"]
        assert generation_config.temperature == 0.6
        assert generation_config.max_tokens == 1234
        assert generation_config.top_p == 0.8

        thinking_config = mock_run_evolution.call_args.kwargs["thinking_config"]
        assert thinking_config == {
            "meta": {"thinking_budget": 1024},
            "target": {"thinking_level": "low"},
            "judge": {"thinking_budget": 512},
        }

    @patch("api.evolution.runner.run_evolution", new_callable=AsyncMock)
    async def test_runner_and_persistence_share_effective_config_objects(
        self,
        mock_run_evolution: AsyncMock,
        client: httpx.AsyncClient,
        app: FastAPI,
    ):
        run_started = asyncio.Event()

        async def run_evolution(*args, **kwargs):
            run_started.set()

        mock_run_evolution.side_effect = run_evolution
        await _register_prompt(client, "effective-objects")
        await _add_case(client, "effective-objects")
        await client.put(
            "/api/prompts/effective-objects/config",
            json={
                "generation": {"temperature": 0.25, "max_tokens": 777},
                "target_thinking_budget": 333,
            },
        )

        response = await client.post(
            "/api/evolution/start",
            json={"prompt_id": "effective-objects", "top_p": 0.75},
        )
        await asyncio.wait_for(run_started.wait(), timeout=1)

        info = app.state.run_manager._runs[response.json()["run_id"]]
        runner_generation = mock_run_evolution.call_args.kwargs["generation_config"]
        runner_thinking = mock_run_evolution.call_args.kwargs["thinking_config"]
        assert info.generation_config is runner_generation
        assert info.thinking_config is runner_thinking
        assert runner_generation.model_dump() == {
            "temperature": 0.25,
            "max_tokens": 777,
            "top_p": 0.75,
            "top_k": None,
            "frequency_penalty": None,
            "presence_penalty": None,
        }
        assert runner_thinking == {"target": {"thinking_budget": 333}}
