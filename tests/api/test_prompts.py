"""Tests for prompt CRUD endpoints (GET, POST, PUT)."""

from __future__ import annotations

import httpx


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


# -- GET /api/prompts/ --


async def test_list_prompts_empty(client: httpx.AsyncClient):
    """GET /api/prompts/ with no prompts returns empty list."""
    resp = await client.get("/api/prompts/")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_prompts_returns_summaries(client: httpx.AsyncClient):
    """GET /api/prompts/ with 2 registered prompts returns list of 2 PromptSummary objects."""
    await _register_prompt(client, "alpha", "Hello {{ name }}", "Alpha prompt")
    await _register_prompt(client, "beta", "Hi {{ greeting }}", "Beta prompt")

    resp = await client.get("/api/prompts/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    ids = {p["id"] for p in data}
    assert ids == {"alpha", "beta"}
    # Each should have summary fields
    for p in data:
        assert "purpose" in p
        assert "template_variables" in p
        assert "anchor_variables" in p


# -- GET /api/prompts/{id} --


async def test_get_prompt_detail(client: httpx.AsyncClient):
    """GET /api/prompts/{id} returns PromptDetail with template text."""
    await _register_prompt(client, "my-prompt", "Hello {{ user }}", "Detail test")

    resp = await client.get("/api/prompts/my-prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "my-prompt"
    assert data["purpose"] == "Detail test"
    assert data["template"] == "Hello {{ user }}"
    assert "user" in data["template_variables"]


async def test_get_prompt_not_found(client: httpx.AsyncClient):
    """GET /api/prompts/nonexistent returns 404."""
    resp = await client.get("/api/prompts/nonexistent")
    assert resp.status_code == 404


# -- POST /api/prompts/ --


async def test_create_prompt_returns_201(client: httpx.AsyncClient):
    """POST /api/prompts/ with valid data returns 201 with PromptSummary."""
    resp = await _register_prompt(client, "new-prompt", "{{ greeting }} world", "New prompt")
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "new-prompt"
    assert data["purpose"] == "New prompt"
    assert "greeting" in data["template_variables"]


async def test_create_prompt_duplicate_returns_409(client: httpx.AsyncClient):
    """POST /api/prompts/ with duplicate ID returns 409."""
    await _register_prompt(client, "dupe")
    resp = await _register_prompt(client, "dupe")
    assert resp.status_code == 409


# -- DELETE /api/prompts/{id} --


async def test_delete_prompt(client: httpx.AsyncClient):
    """DELETE /api/prompts/{id} removes the prompt."""
    await _register_prompt(client, "del-prompt")
    resp = await client.delete("/api/prompts/del-prompt")
    assert resp.status_code == 204

    # Verify it's gone
    resp = await client.get("/api/prompts/del-prompt")
    assert resp.status_code == 404


async def test_delete_prompt_not_found(client: httpx.AsyncClient):
    """DELETE /api/prompts/nonexistent returns 404."""
    resp = await client.delete("/api/prompts/nonexistent")
    assert resp.status_code == 404


# -- PATCH /api/prompts/{id} --


async def test_update_purpose(client: httpx.AsyncClient):
    """PATCH /api/prompts/{id} with purpose updates it."""
    await _register_prompt(client, "patch-prompt", purpose="Old purpose")

    resp = await client.patch(
        "/api/prompts/patch-prompt",
        json={"purpose": "New purpose"},
    )
    assert resp.status_code == 200
    assert resp.json()["purpose"] == "New purpose"

    # Verify via GET
    detail = await client.get("/api/prompts/patch-prompt")
    assert detail.json()["purpose"] == "New purpose"


async def test_update_purpose_not_found(client: httpx.AsyncClient):
    """PATCH /api/prompts/nonexistent returns 404."""
    resp = await client.patch(
        "/api/prompts/nonexistent",
        json={"purpose": "x"},
    )
    assert resp.status_code == 404


# -- PUT /api/prompts/{id}/template --


async def test_update_template(client: httpx.AsyncClient):
    """PUT /api/prompts/{id}/template with valid template returns updated PromptSummary."""
    await _register_prompt(client, "upd-prompt", "Old {{ var }}", "Update test")

    resp = await client.put(
        "/api/prompts/upd-prompt/template",
        json={"template": "New {{ different }}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "upd-prompt"
    assert "different" in data["template_variables"]


async def test_update_template_not_found(client: httpx.AsyncClient):
    """PUT /api/prompts/nonexistent/template returns 404."""
    resp = await client.put(
        "/api/prompts/nonexistent/template",
        json={"template": "something"},
    )
    assert resp.status_code == 404


# -- Phase 31: tool_schemas and mocks support --


async def test_create_prompt_with_tool_schemas_and_mocks(client: httpx.AsyncClient):
    """POST /api/prompts/ accepts tool_schemas and mocks fields."""
    resp = await client.post(
        "/api/prompts/",
        json={
            "id": "schema-prompt",
            "purpose": "Prompt with schemas",
            "template": "Hello {{ name }}",
            "tool_schemas": [
                {
                    "name": "transfer_to_number",
                    "description": "Transfer call",
                    "parameters": [
                        {"name": "target", "type": "string", "required": True},
                    ],
                }
            ],
            "mocks": [
                {
                    "tool_name": "transfer_to_number",
                    "scenarios": [
                        {"match_args": {"target": "ventas"}, "response": "Transferred"},
                    ],
                }
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "schema-prompt"


async def test_get_prompt_returns_tool_schemas_and_mocks(client: httpx.AsyncClient):
    """GET /api/prompts/{id} returns tool_schemas and mocks when present."""
    await client.post(
        "/api/prompts/",
        json={
            "id": "detail-schema",
            "purpose": "Detail with schemas",
            "template": "Hello {{ name }}",
            "tool_schemas": [
                {
                    "name": "lookup",
                    "description": "Look up data",
                    "parameters": [],
                }
            ],
            "mocks": [
                {
                    "tool_name": "lookup",
                    "scenarios": [
                        {"match_args": {"key": "test"}, "response": "Found: {{ key }}"},
                    ],
                }
            ],
        },
    )

    resp = await client.get("/api/prompts/detail-schema")
    assert resp.status_code == 200
    data = resp.json()

    # tool_schemas should be present
    assert data["tool_schemas"] is not None
    assert len(data["tool_schemas"]) == 1
    assert data["tool_schemas"][0]["name"] == "lookup"

    # mocks should be present
    assert data["mocks"] is not None
    assert len(data["mocks"]) == 1
    assert data["mocks"][0]["tool_name"] == "lookup"


async def test_get_prompt_without_schemas_returns_none(client: httpx.AsyncClient):
    """GET /api/prompts/{id} returns None for tool_schemas and mocks when absent."""
    await _register_prompt(client, "plain-detail", "Hello {{ name }}", "Plain prompt")

    resp = await client.get("/api/prompts/plain-detail")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_schemas"] is None
    assert data["mocks"] is None


# -- PUT /api/prompts/{id}/variables --


async def test_update_variables(client: httpx.AsyncClient):
    """PUT /api/prompts/{id}/variables updates variable definitions."""
    await _register_prompt(client, "var-prompt", "Hello {{ name }}", "Var test")

    resp = await client.put(
        "/api/prompts/var-prompt/variable-definitions",
        json={
            "variables": [
                {
                    "name": "name",
                    "var_type": "string",
                    "description": "Customer name",
                    "is_anchor": True,
                },
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "var-prompt"
    assert "name" in data["anchor_variables"]

    # Verify via GET that variable_definitions are persisted
    detail = await client.get("/api/prompts/var-prompt")
    defs = detail.json()["variable_definitions"]
    assert len(defs) == 1
    assert defs[0]["name"] == "name"
    assert defs[0]["is_anchor"] is True
    assert defs[0]["description"] == "Customer name"


async def test_update_variables_not_found(client: httpx.AsyncClient):
    """PUT /api/prompts/nonexistent/variable-definitions returns 404."""
    resp = await client.put(
        "/api/prompts/nonexistent/variable-definitions",
        json={"variables": []},
    )
    assert resp.status_code == 404


async def test_update_variables_removes_anchor(client: httpx.AsyncClient):
    """PUT /api/prompts/{id}/variables can toggle anchor off."""
    # Create with anchor
    await client.post(
        "/api/prompts/",
        json={
            "id": "anchor-toggle",
            "purpose": "Toggle test",
            "template": "Hello {{ name }}",
            "variables": [
                {"name": "name", "var_type": "string", "is_anchor": True},
            ],
        },
    )

    # Remove anchor
    resp = await client.put(
        "/api/prompts/anchor-toggle/variable-definitions",
        json={
            "variables": [
                {"name": "name", "var_type": "string", "is_anchor": False},
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["anchor_variables"] == []


# -- PUT /api/prompts/{id}/tools --


async def test_update_tools(client: httpx.AsyncClient):
    """PUT /api/prompts/{id}/tools updates tool definitions."""
    await _register_prompt(client, "tool-prompt", "Hello {{ name }}", "Tool test")

    new_tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up data",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]
    resp = await client.put(
        "/api/prompts/tool-prompt/tools",
        json={"tools": new_tools},
    )
    assert resp.status_code == 200
    assert resp.json()["tool_count"] == 1

    # Verify via GET
    detail = await client.get("/api/prompts/tool-prompt")
    tools = detail.json()["tools"]
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "lookup"


async def test_update_tools_not_found(client: httpx.AsyncClient):
    """PUT /api/prompts/nonexistent/tools returns 404."""
    resp = await client.put(
        "/api/prompts/nonexistent/tools",
        json={"tools": []},
    )
    assert resp.status_code == 404


async def test_update_tools_clear(client: httpx.AsyncClient):
    """PUT /api/prompts/{id}/tools with empty list clears tools."""
    await client.post(
        "/api/prompts/",
        json={
            "id": "clear-tools",
            "purpose": "Clear test",
            "template": "Hello {{ name }}",
            "tools": [{"type": "function", "function": {"name": "old_tool"}}],
        },
    )

    resp = await client.put(
        "/api/prompts/clear-tools/tools",
        json={"tools": []},
    )
    assert resp.status_code == 200
    assert resp.json()["tool_count"] == 0

    detail = await client.get("/api/prompts/clear-tools")
    assert detail.json()["tools"] is None


# -- POST /api/prompts/extract-variables --


async def test_extract_variables(client: httpx.AsyncClient):
    """POST /api/prompts/extract-variables extracts Jinja2 variables."""
    resp = await client.post(
        "/api/prompts/extract-variables",
        json={"template": "Hello {{ name }}, your order {{ order_id }} is ready."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert sorted(data["variables"]) == ["name", "order_id"]
    assert data["errors"] == []


async def test_extract_variables_empty_template(client: httpx.AsyncClient):
    """POST /api/prompts/extract-variables with no variables returns empty list."""
    resp = await client.post(
        "/api/prompts/extract-variables",
        json={"template": "Hello world, no variables here."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["variables"] == []
    assert data["errors"] == []


async def test_extract_variables_complex_template(client: httpx.AsyncClient):
    """POST /api/prompts/extract-variables handles filters and nested access."""
    resp = await client.post(
        "/api/prompts/extract-variables",
        json={"template": "{{ greeting | upper }} {{ user }}! {% if show_details %}Details: {{ details }}{% endif %}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "greeting" in data["variables"]
    assert "user" in data["variables"]
    assert "details" in data["variables"]
    assert "show_details" in data["variables"]
