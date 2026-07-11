"""Tests for dataset CRUD endpoints (list, get, add, update, delete, import)."""

from __future__ import annotations

import json

import httpx

# -- Helpers --


async def _register_prompt(
    client: httpx.AsyncClient,
    prompt_id: str = "test-prompt",
) -> None:
    """Register a prompt so the dataset directory exists."""
    resp = await client.post(
        "/api/prompts/",
        json={
            "id": prompt_id,
            "purpose": "For dataset tests",
            "template": "Hello {{ name }}",
        },
    )
    assert resp.status_code == 201


async def _add_case(
    client: httpx.AsyncClient,
    prompt_id: str = "test-prompt",
    name: str = "case-a",
    tier: str = "normal",
    variables: dict | None = None,
) -> dict:
    """POST a new test case and return the response JSON."""
    resp = await client.post(
        f"/api/prompts/{prompt_id}/dataset",
        json={
            "name": name,
            "tier": tier,
            "variables": variables or {"name": "world"},
        },
    )
    assert resp.status_code == 201
    return resp.json()


# -- GET /api/prompts/{id}/dataset --


async def test_list_cases_empty(client: httpx.AsyncClient):
    """GET /api/prompts/{id}/dataset with no cases returns empty list."""
    await _register_prompt(client)
    resp = await client.get("/api/prompts/test-prompt/dataset")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_cases_returns_cases(client: httpx.AsyncClient):
    """GET /api/prompts/{id}/dataset with 2 cases returns list of 2 TestCaseResponse."""
    await _register_prompt(client)
    await _add_case(client, name="alpha")
    await _add_case(client, name="beta")

    resp = await client.get("/api/prompts/test-prompt/dataset")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = {c["name"] for c in data}
    assert names == {"alpha", "beta"}
    # Each should have response fields
    for c in data:
        assert "id" in c
        assert "tier" in c
        assert "variables" in c


# -- GET /api/prompts/{id}/dataset/{case_id} --


async def test_get_case(client: httpx.AsyncClient):
    """GET /api/prompts/{id}/dataset/{case_id} returns single TestCaseResponse."""
    await _register_prompt(client)
    created = await _add_case(client, name="detail-case")
    case_id = created["id"]

    resp = await client.get(f"/api/prompts/test-prompt/dataset/{case_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == case_id
    assert data["name"] == "detail-case"


async def test_get_case_not_found(client: httpx.AsyncClient):
    """GET /api/prompts/{id}/dataset/nonexistent returns 400 (ValueError)."""
    await _register_prompt(client)
    resp = await client.get("/api/prompts/test-prompt/dataset/nonexistent")
    assert resp.status_code == 400


# -- POST /api/prompts/{id}/dataset --


async def test_add_case_returns_201(client: httpx.AsyncClient):
    """POST /api/prompts/{id}/dataset with valid body creates case and returns 201."""
    await _register_prompt(client)
    resp = await client.post(
        "/api/prompts/test-prompt/dataset",
        json={
            "name": "new-case",
            "tier": "critical",
            "variables": {"name": "test"},
            "tags": ["smoke"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "new-case"
    assert data["tier"] == "critical"
    assert "id" in data
    assert data["tags"] == ["smoke"]


async def test_source_metadata_round_trips_through_crud(client: httpx.AsyncClient):
    await _register_prompt(client)
    source_metadata = {"type": "observability", "external_id": "item-1"}

    created = await client.post(
        "/api/prompts/test-prompt/dataset",
        json={
            "name": "imported-case",
            "variables": {"name": "test"},
            "source_metadata": source_metadata,
        },
    )

    assert created.status_code == 201
    assert created.json()["source_metadata"] == source_metadata
    fetched = await client.get(
        f"/api/prompts/test-prompt/dataset/{created.json()['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["source_metadata"] == source_metadata


# -- PUT /api/prompts/{id}/dataset/{case_id} --


async def test_update_case(client: httpx.AsyncClient):
    """PUT /api/prompts/{id}/dataset/{case_id} updates case and returns TestCaseResponse."""
    await _register_prompt(client)
    created = await _add_case(client, name="original")
    case_id = created["id"]

    resp = await client.put(
        f"/api/prompts/test-prompt/dataset/{case_id}",
        json={"name": "updated", "tier": "critical"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "updated"
    assert data["tier"] == "critical"
    # Original fields should be preserved
    assert data["variables"] == {"name": "world"}


async def test_update_case_replaces_source_metadata(client: httpx.AsyncClient):
    await _register_prompt(client)
    created = await client.post(
        "/api/prompts/test-prompt/dataset",
        json={
            "variables": {"name": "world"},
            "source_metadata": {"external_id": "old"},
        },
    )

    response = await client.put(
        f"/api/prompts/test-prompt/dataset/{created.json()['id']}",
        json={"source_metadata": {"external_id": "new"}},
    )

    assert response.status_code == 200
    assert response.json()["source_metadata"] == {"external_id": "new"}


# -- DELETE /api/prompts/{id}/dataset/{case_id} --


async def test_delete_case(client: httpx.AsyncClient):
    """DELETE /api/prompts/{id}/dataset/{case_id} returns 204."""
    await _register_prompt(client)
    created = await _add_case(client)
    case_id = created["id"]

    resp = await client.delete(f"/api/prompts/test-prompt/dataset/{case_id}")
    assert resp.status_code == 204

    # Verify it's gone
    resp = await client.get(f"/api/prompts/test-prompt/dataset/{case_id}")
    assert resp.status_code == 400


async def test_delete_case_not_found(client: httpx.AsyncClient):
    """DELETE /api/prompts/{id}/dataset/nonexistent returns 400."""
    await _register_prompt(client)
    resp = await client.delete("/api/prompts/test-prompt/dataset/nonexistent")
    assert resp.status_code == 400


# -- POST /api/prompts/{id}/dataset/import --


async def test_import_cases_from_file(client: httpx.AsyncClient):
    """POST /api/prompts/{id}/dataset/import with JSON file upload imports cases."""
    await _register_prompt(client)

    cases_data = {
        "cases": [
            {
                "name": "imported-1",
                "variables": {"name": "one"},
                "tier": "normal",
            },
            {
                "name": "imported-2",
                "variables": {"name": "two"},
                "tier": "critical",
            },
        ]
    }
    json_content = json.dumps(cases_data)

    resp = await client.post(
        "/api/prompts/test-prompt/dataset/import",
        files={"file": ("cases.json", json_content, "application/json")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = {c["name"] for c in data}
    assert names == {"imported-1", "imported-2"}


async def test_import_invalid_json_returns_400(client: httpx.AsyncClient):
    """POST import with non-JSON content returns 400 with detail about decode error."""
    await _register_prompt(client)

    resp = await client.post(
        "/api/prompts/test-prompt/dataset/import",
        files={"file": ("cases.json", "not valid json {", "application/json")},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "detail" in data


async def test_import_wrong_structure_returns_400(client: httpx.AsyncClient):
    """POST import with a JSON string literal returns 400 with 'Expected a list' detail."""
    await _register_prompt(client)

    resp = await client.post(
        "/api/prompts/test-prompt/dataset/import",
        files={"file": ("cases.json", '"just a string"', "application/json")},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "detail" in data
    assert "Expected a list of cases" in data["detail"]


async def test_import_dict_without_cases_key_returns_400(client: httpx.AsyncClient):
    """POST import with a dict missing 'cases' key returns 400."""
    await _register_prompt(client)

    content = json.dumps({"items": [{"name": "test"}]})
    resp = await client.post(
        "/api/prompts/test-prompt/dataset/import",
        files={"file": ("cases.json", content, "application/json")},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "detail" in data
    assert "Expected a list of cases" in data["detail"]


async def test_import_list_format_succeeds(client: httpx.AsyncClient):
    """POST import with a plain JSON list (no wrapper) returns 200."""
    await _register_prompt(client)

    content = json.dumps([{"name": "list-case", "variables": {"name": "v"}}])
    resp = await client.post(
        "/api/prompts/test-prompt/dataset/import",
        files={"file": ("cases.json", content, "application/json")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "list-case"


# -- Phase 31: validation_warnings in response --


async def test_add_case_response_has_validation_warnings_field(
    client: httpx.AsyncClient,
):
    """POST response includes validation_warnings field (empty when no schema violations)."""
    await _register_prompt(client)
    resp = await client.post(
        "/api/prompts/test-prompt/dataset",
        json={
            "name": "new-case",
            "tier": "normal",
            "variables": {"name": "test"},
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "validation_warnings" in data
    assert isinstance(data["validation_warnings"], list)
    # No schema file exists, so warnings should be empty
    assert data["validation_warnings"] == []
