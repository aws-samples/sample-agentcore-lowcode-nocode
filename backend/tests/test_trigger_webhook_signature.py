"""HMAC signature verification for webhook triggers (Task 01)."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock, patch


def _hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_accepted_when_matching() -> None:
    import os

    os.environ.setdefault("TRIGGERS_TABLE_NAME", "t")
    os.environ.setdefault("TRIGGER_INVOCATIONS_TABLE_NAME", "ti")
    os.environ.setdefault(
        "TRIGGER_ROUTER_LAMBDA_ARN",
        "arn:aws:lambda:us-east-1:1:function:x",
    )
    os.environ.setdefault(
        "TRIGGER_SCHEDULER_ROLE_ARN", "arn:aws:iam::1:role/x"
    )

    from app.routers.triggers import _verify_signature

    body = b'{"hello": "world"}'
    secret = "s3cret"
    good = _hex(secret, body)

    trigger = MagicMock()
    trigger.webhook_secret_arn = "arn"
    with patch("app.routers.triggers._get_manager") as gm:
        gm.return_value.get_webhook_secret.return_value = secret
        assert _verify_signature(trigger, body, good) is True
        assert _verify_signature(trigger, body, f"sha256={good}") is True
        assert _verify_signature(trigger, body, "bad") is False
        assert _verify_signature(trigger, body, "") is False


def test_signature_rejected_when_secret_missing() -> None:
    import os

    os.environ.setdefault("TRIGGERS_TABLE_NAME", "t")
    os.environ.setdefault("TRIGGER_INVOCATIONS_TABLE_NAME", "ti")

    from app.routers.triggers import _verify_signature

    trigger = MagicMock()
    trigger.webhook_secret_arn = "arn"
    with patch("app.routers.triggers._get_manager") as gm:
        gm.return_value.get_webhook_secret.return_value = None
        assert _verify_signature(trigger, b"x", "aa") is False
