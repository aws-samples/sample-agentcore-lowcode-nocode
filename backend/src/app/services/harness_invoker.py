"""Harness data-plane invoker (Task 11).

Uses ``bedrock-agentcore:InvokeHarness`` per the error surfaced by
``InvokeAgentRuntime`` for harness-managed runtimes:
    "The agent runtime ... is managed by a harness and cannot be invoked
    directly. Use the InvokeHarness API with the relevant harness ID instead."

InvokeHarness returns an EventStream under ``resp['stream']``. We accumulate
all message events into a single text response for the non-streaming router
path.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from app.models.harness_models import HarnessInvokeResponse, HarnessRecord

logger = logging.getLogger(__name__)


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


class HarnessInvoker:
    def __init__(self) -> None:
        self._dp = boto3.client("bedrock-agentcore", region_name=_region())

    def invoke(
        self,
        harness: HarnessRecord,
        prompt: str,
        session_id: Optional[str] = None,
    ) -> HarnessInvokeResponse:
        if not harness.arn:
            return HarnessInvokeResponse(
                success=False,
                error="harness has no ARN yet — wait for READY",
            )
        started = time.time()
        sid = _coerce_session_id(session_id)
        params: dict[str, Any] = {
            "harnessArn": harness.arn,
            "runtimeSessionId": sid,
            "messages": [
                {"role": "user", "content": [{"text": prompt}]}
            ],
        }
        try:
            resp = self._dp.invoke_harness(**params)
        except ClientError as e:
            return HarnessInvokeResponse(
                success=False,
                error=str(e),
                duration_ms=int((time.time() - started) * 1000),
            )

        text, stream_err = _drain_stream(resp.get("stream"))
        if stream_err:
            return HarnessInvokeResponse(
                success=False,
                response=text or None,
                session_id=sid,
                error=stream_err,
                duration_ms=int((time.time() - started) * 1000),
            )
        return HarnessInvokeResponse(
            success=True,
            response=text,
            session_id=sid,
            duration_ms=int((time.time() - started) * 1000),
        )


def _coerce_session_id(session_id: Optional[str]) -> str:
    # AWS requires runtimeSessionId to be >= 33 chars. Pad with a deterministic
    # suffix so caller-supplied short IDs (e.g. "sess-A") still map to a stable
    # session on AWS's side, and minted IDs always exceed the minimum.
    base = (session_id or "").strip()
    if not base:
        return f"agentcore-{uuid.uuid4().hex}"
    if len(base) >= 33:
        return base
    # Stable pad from the caller-supplied prefix so subsequent invokes with the
    # same short ID hit the same runtime session.
    suffix = uuid.uuid5(uuid.NAMESPACE_DNS, base).hex
    return f"{base}-{suffix}"[:128]


def _drain_stream(stream: Any) -> tuple[str, Optional[str]]:
    """Accumulate all events from the EventStream into plain assistant text.

    InvokeHarness returns Bedrock Converse-style streaming events wrapped in
    the harness envelope. Events arrive as dicts; each one has exactly one
    key/value pair containing a JSON object (or bytes blob with JSON inside).

    Observed event shapes (live-tested against us-east-1):
      {"role": "assistant"}                         — message start
      {"contentBlockIndex": 0, "delta": {"text": "Hi"}}  — delta chunk
      {"contentBlockIndex": 0}                      — block stop
      {"stopReason": "end_turn"}                    — message stop
      {"usage": {...}, "metrics": {...}}            — tokens + latency

    Returns (accumulated_text, error_message). If the stream raises
    (``runtimeClientError`` / ``EventStreamError``) — e.g. Bedrock refuses
    a legacy model — the caller sees a truthful error, not an empty string
    passed off as success.
    """
    if stream is None:
        return "", None
    parts: list[str] = []
    try:
        for event in stream:
            payload = _extract_payload(event)
            if not isinstance(payload, dict):
                continue
            delta = payload.get("delta")
            if isinstance(delta, dict):
                text = delta.get("text")
                if isinstance(text, str):
                    parts.append(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("stream drain error: %s", e)
        return "".join(parts), str(e)
    return "".join(parts), None


def _extract_payload(event: Any) -> Any:
    """Pull the inner JSON payload out of a harness stream event.

    Events may be:
      {"chunk": {"bytes": b"...json..."}}           — bedrock-style wrapper
      {"<typed-member-name>": {...inline object...}}
      raw dict (shape already matches)
    """
    if not isinstance(event, dict):
        return None
    # Single-key wrapper case
    if len(event) == 1:
        (v,) = event.values()
        if isinstance(v, dict) and "bytes" in v:
            b = v["bytes"]
            raw = b.decode("utf-8", errors="replace") if isinstance(b, (bytes, bytearray)) else str(b)
            try:
                return json.loads(raw)
            except ValueError:
                return {"raw": raw}
        if isinstance(v, (bytes, bytearray)):
            try:
                return json.loads(v.decode("utf-8", errors="replace"))
            except ValueError:
                return {"raw": v.decode("utf-8", errors="replace")}
        if isinstance(v, dict):
            return v
        return None
    return event
