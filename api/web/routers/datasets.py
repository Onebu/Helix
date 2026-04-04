"""Dataset CRUD endpoints: list, get, add, update, delete, import.

All routes are nested under a prompt context (/{prompt_id}/dataset).
This router shares the /api/prompts prefix with the prompts router.

Routes:
    GET    /{prompt_id}/dataset              List all test cases
    GET    /{prompt_id}/dataset/{case_id}    Get a single test case
    POST   /{prompt_id}/dataset              Add a new test case (201)
    PUT    /{prompt_id}/dataset/{case_id}    Update an existing test case
    DELETE /{prompt_id}/dataset/{case_id}    Delete a test case (204)
    POST   /{prompt_id}/dataset/import       Import cases from file upload
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.dataset.models import PriorityTier, TestCase
from api.dataset.service import DatasetService
from api.storage.models import User
from api.web.auth import get_current_user
from api.web.deps import get_dataset_service
from api.web.schemas import (
    TestCaseCreateRequest,
    TestCaseResponse,
    TestCaseUpdateRequest,
)

router = APIRouter()


def _case_to_response(case: TestCase) -> TestCaseResponse:
    """Map a domain TestCase to an API TestCaseResponse."""
    return TestCaseResponse(
        id=case.id,
        name=case.name,
        description=case.description,
        tier=case.tier.value,
        variables=case.variables,
        expected_output=case.expected_output,
        tags=case.tags,
        chat_history=case.chat_history,
        tools=case.tools,
    )


@router.get("/{prompt_id}/dataset", response_model=list[TestCaseResponse])
async def list_cases(
    prompt_id: str,
    service: DatasetService = Depends(get_dataset_service),
    user: User = Depends(get_current_user),
) -> list[TestCaseResponse]:
    """List all test cases for a prompt."""
    cases = await service.list_cases(prompt_id)
    return [_case_to_response(c) for c in cases]


@router.get("/{prompt_id}/dataset/{case_id}", response_model=TestCaseResponse)
async def get_case(
    prompt_id: str,
    case_id: str,
    service: DatasetService = Depends(get_dataset_service),
    user: User = Depends(get_current_user),
) -> TestCaseResponse:
    """Get a single test case by ID."""
    case = await service.get_case(prompt_id, case_id)
    return _case_to_response(case)


@router.post("/{prompt_id}/dataset", response_model=TestCaseResponse, status_code=201)
async def add_case(
    prompt_id: str,
    body: TestCaseCreateRequest,
    service: DatasetService = Depends(get_dataset_service),
    user: User = Depends(get_current_user),
) -> TestCaseResponse:
    """Add a new test case to a prompt's dataset."""
    case = TestCase(
        name=body.name,
        description=body.description,
        chat_history=body.chat_history,
        variables=body.variables,
        tools=body.tools,
        expected_output=body.expected_output,
        tier=PriorityTier(body.tier),
        tags=body.tags,
    )
    created, warnings = await service.add_case(prompt_id, case)
    resp = _case_to_response(created)
    resp.validation_warnings = warnings
    return resp


@router.put("/{prompt_id}/dataset/{case_id}", response_model=TestCaseResponse)
async def update_case(
    prompt_id: str,
    case_id: str,
    body: TestCaseUpdateRequest,
    service: DatasetService = Depends(get_dataset_service),
    user: User = Depends(get_current_user),
) -> TestCaseResponse:
    """Update an existing test case (partial update)."""
    existing = await service.get_case(prompt_id, case_id)

    # Merge non-None fields from body onto existing case
    updated_data = existing.model_dump()
    for field_name, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            if field_name == "tier":
                updated_data[field_name] = PriorityTier(value)
            else:
                updated_data[field_name] = value

    updated_case = TestCase(**updated_data)
    result = await service.update_case(prompt_id, case_id, updated_case)
    return _case_to_response(result)


@router.delete("/{prompt_id}/dataset/{case_id}", status_code=204)
async def delete_case(
    prompt_id: str,
    case_id: str,
    service: DatasetService = Depends(get_dataset_service),
    user: User = Depends(get_current_user),
) -> None:
    """Delete a test case."""
    await service.delete_case(prompt_id, case_id)


@router.post("/{prompt_id}/dataset/import", response_model=list[TestCaseResponse])
async def import_cases(
    prompt_id: str,
    file: UploadFile = File(...),
    service: DatasetService = Depends(get_dataset_service),
    user: User = Depends(get_current_user),
) -> list[TestCaseResponse]:
    """Import test cases from an uploaded JSON or YAML file."""
    # Enforce 10 MB upload limit
    max_size = 10 * 1024 * 1024
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail="File too large. Maximum upload size is 10 MB.")
    suffix = Path(file.filename).suffix if file.filename else ".json"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        cases = await service.import_cases(prompt_id, tmp_path)
        return [_case_to_response(c) for c in cases]
    finally:
        tmp_path.unlink(missing_ok=True)
