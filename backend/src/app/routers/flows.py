"""Flow CRUD API endpoints.

This module provides REST API endpoints for flow management:
- POST /flows - Create flow
- GET /flows - List all flows
- GET /flows/{flow_id} - Get flow
- PUT /flows/{flow_id} - Update flow
- DELETE /flows/{flow_id} - Delete flow

Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 3.2, 3.3, 4.2, 4.3, 4.5, 6.2, 6.4, 7.4
"""

import logging
import re

from fastapi import APIRouter, HTTPException, status
from botocore.exceptions import ClientError
from pydantic import ValidationError

logger = logging.getLogger(__name__)

from app.models import (
    Flow,
    FlowCreateRequest,
    FlowUpdateRequest,
    FlowSummary,
    FlowListResponse,
    FlowResponse,
)
from app.services.flow_storage import get_flow_storage


router = APIRouter(prefix="/flows", tags=["flows"])


# ============================================================================
# Helpers
# ============================================================================


def _get_flow_storage():
    """Get the active flow storage instance."""
    return get_flow_storage()


def _validate_flow_id(flow_id: str) -> str:
    """Validate flow_id format to prevent injection attacks."""
    if not flow_id or len(flow_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid flow_id")
    if not re.match(r"^[a-zA-Z0-9_-]+$", flow_id):
        raise HTTPException(status_code=400, detail="Invalid flow_id format")
    return flow_id


# ============================================================================
# Endpoints
# ============================================================================


@router.post("", response_model=FlowResponse, status_code=status.HTTP_201_CREATED)
async def create_flow(request: FlowCreateRequest) -> FlowResponse:
    """Create a new flow with an empty workflow.

    Requirements: 1.1, 1.2, 1.3, 1.4
    """
    try:
        storage = _get_flow_storage()
        flow = storage.create(request.name)
        return FlowResponse(
            flow=flow,
            message="Flow created successfully",
        )
    except ClientError:
        logger.exception("DynamoDB error in create_flow")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage service unavailable",
        )
    except ValidationError:
        logger.exception("Validation error in create_flow")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process flow data",
        )


@router.get("", response_model=FlowListResponse)
async def list_flows() -> FlowListResponse:
    """List all flows sorted by updated_at descending.

    Requirements: 2.1
    """
    try:
        flows = _get_flow_storage().list_all()
        summaries = [
            FlowSummary(
                id=c.id,
                name=c.name,
                deployment_status=c.deployment_status,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in flows
        ]
        return FlowListResponse(flows=summaries)
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage service unavailable",
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process flow data",
        )


@router.get("/{flow_id}", response_model=Flow)
async def get_flow(flow_id: str) -> Flow:
    """Get a flow by ID with full workflow.

    Requirements: 3.2, 3.3
    """
    flow_id = _validate_flow_id(flow_id)
    try:
        flow = _get_flow_storage().get(flow_id)
        if flow is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Flow '{flow_id}' not found",
            )
        return flow
    except HTTPException:
        raise
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage service unavailable",
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process flow data",
        )


@router.put("/{flow_id}", response_model=FlowResponse)
async def update_flow(flow_id: str, request: FlowUpdateRequest) -> FlowResponse:
    """Update an existing flow name and/or workflow.

    Requirements: 6.2, 6.4
    """
    flow_id = _validate_flow_id(flow_id)
    try:
        updated = _get_flow_storage().update(
            flow_id,
            name=request.name,
            workflow=request.workflow,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Flow '{flow_id}' not found",
            )
        return FlowResponse(
            flow=updated,
            message="Flow updated successfully",
        )
    except HTTPException:
        raise
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage service unavailable",
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process flow data",
        )


@router.delete("/{flow_id}")
async def delete_flow(flow_id: str) -> dict:
    """Delete a flow by ID.

    Requirements: 4.2, 4.3, 4.5
    """
    flow_id = _validate_flow_id(flow_id)
    try:
        deleted = _get_flow_storage().delete(flow_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Flow '{flow_id}' not found",
            )
        return {"message": f"Flow '{flow_id}' deleted successfully"}
    except HTTPException:
        raise
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage service unavailable",
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process flow data",
        )
