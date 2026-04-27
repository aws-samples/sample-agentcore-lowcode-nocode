"""AWS Lambda handler for the Workflow Lambda.

Wraps the existing FastAPI application using the Mangum adapter,
translating API Gateway HTTP API events into ASGI requests.

Requirements: 1.1, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8
"""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
