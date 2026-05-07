"""FastAPI application entry point.

Requirements: 3.3, 4.2, 6.1
"""

import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import workflows_router
from app.routers.deployment import router as deployment_router
from app.routers.flows import router as flows_router
from app.routers.tools import router as tools_router
from app.routers.triggers import router as triggers_router
from app.routers.triggers import webhook_router as webhooks_router
from app.services.config import load_config
from app.services.dynamodb_storage import DynamoDBWorkflowStorage
from app.services.flow_storage import DynamoDBFlowStorage, set_flow_storage
from app.services.storage import set_workflow_storage

logger = logging.getLogger(__name__)

# Load environment variables (for local development)
load_dotenv()

# Load application config from SSM or environment variables
config = load_config()

# Select storage backend based on config
if config.dynamodb_table_name:
    logger.info(
        "Using DynamoDB storage: table=%s, region=%s",
        config.dynamodb_table_name,
        config.aws_region,
    )
    set_workflow_storage(DynamoDBWorkflowStorage(
        table_name=config.dynamodb_table_name,
        region=config.aws_region,
    ))
else:
    logger.info("Using in-memory storage (no DYNAMODB_TABLE_NAME set)")

# Select flow storage backend based on config
if config.dynamodb_flows_table_name:
    logger.info(
        "Using DynamoDB flow storage: table=%s, region=%s",
        config.dynamodb_flows_table_name,
        config.aws_region,
    )
    set_flow_storage(DynamoDBFlowStorage(
        table_name=config.dynamodb_flows_table_name,
        region=config.aws_region,
    ))
else:
    logger.info("Using in-memory flow storage (no DYNAMODB_FLOWS_TABLE_NAME set)")

app = FastAPI(
    title="AgentCore Workflow Platform API",
    description="Backend API for visual workflow design and AWS AgentCore deployment",
    version="0.1.0",
)

# Configure CORS from config
# SECURITY: Restrict allowed methods and headers to what the API actually uses
# instead of wildcard "*" to reduce attack surface.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Amz-Date", "X-Api-Key"],
)

# Include routers
app.include_router(workflows_router)
app.include_router(flows_router, prefix="/api", tags=["flows"])
app.include_router(deployment_router, prefix="/api", tags=["deployment"])
app.include_router(tools_router, prefix="/api", tags=["tools"])
app.include_router(triggers_router, prefix="/api", tags=["triggers"])
app.include_router(webhooks_router, prefix="/api", tags=["webhooks"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}
