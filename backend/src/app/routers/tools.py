"""Tool Generator router — exposes AI tool generation and testing endpoints.

Endpoints:
- POST /api/generate-tool — Generate a Lambda tool from natural language
- POST /api/test-tool — Start async tool test (returns testId)
- GET  /api/test-tool/{test_id} — Poll for test results
"""

import asyncio
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app.models.tool_generation_models import (
    ToolGenerateRequest,
    ToolTestRequest,
)
from app.services.tool_generator import generate_tool
from app.services.tool_tester import test_tool

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory store for async test results (keyed by testId)
_test_results: dict[str, dict[str, Any]] = {}


@router.post("/generate-tool")
async def generate_tool_endpoint(request: ToolGenerateRequest) -> dict:
    """Generate a Lambda tool using AI from a natural language description."""
    region = os.getenv("APP_AWS_REGION", os.getenv("AWS_REGION", "us-east-1"))

    result = await asyncio.to_thread(
        generate_tool,
        prompt=request.prompt,
        conversation_history=request.conversation_history,
        existing_tool=request.existing_tool,
        region=region,
    )

    return result


@router.post("/test-tool")
async def start_test_tool(request: ToolTestRequest) -> dict:
    """Start an async tool test. Returns a testId for polling."""
    test_id = uuid.uuid4().hex[:12]
    _test_results[test_id] = {"status": "running"}

    region = os.getenv("APP_AWS_REGION", os.getenv("AWS_REGION", "us-east-1"))

    # Convert Pydantic test cases to dicts for the service
    test_cases_raw = [tc.model_dump(by_alias=True) for tc in request.test_cases]

    async def _run():
        try:
            result = await asyncio.to_thread(
                test_tool,
                lambda_code=request.lambda_code,
                test_cases=test_cases_raw,
                region=region,
            )
            _test_results[test_id] = {**result, "status": "complete"}
        except Exception as exc:
            logger.exception("Async tool test failed: %s", exc)
            _test_results[test_id] = {
                "status": "complete",
                "success": False,
                "results": [],
                "allPassed": False,
                "error": str(exc),
            }

    asyncio.create_task(_run())

    return {"testId": test_id}


@router.get("/test-tool/{test_id}")
async def poll_test_tool(test_id: str) -> dict:
    """Poll for async test results."""
    if test_id not in _test_results:
        raise HTTPException(status_code=404, detail="Test not found")

    return _test_results[test_id]
