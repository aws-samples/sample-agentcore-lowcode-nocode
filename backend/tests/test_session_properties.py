"""Property-based tests for session ID passthrough (Property 10).

Feature: serverless-migration

Property 10: Session ID Passthrough
For any test-runtime request that includes a session ID string, the
constructed invocation payload or CLI command should contain that exact
session ID.

**Validates: Requirements 9.2**
"""

import sys

sys.path.insert(0, "src")

import json
import types
from unittest.mock import patch, MagicMock

from hypothesis import given, settings, strategies as st

# deployment_handler imports mangum at module level; stub it so the module
# can be loaded in test environments where mangum is not installed.
if "mangum" not in sys.modules:
    sys.modules["mangum"] = types.ModuleType("mangum")
    sys.modules["mangum"].Mangum = MagicMock()  # type: ignore[attr-defined]

try:
    from app.deployment_handler import _invoke_runtime_cli, _invoke_runtime_http
except ImportError:
    import pytest

    pytest.skip(
        "_invoke_runtime_cli / _invoke_runtime_http not yet implemented",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Session IDs: non-empty printable strings (realistic session tokens)
session_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=128,
).filter(lambda s: s.strip() != "")

# Simple payload dicts for test-runtime requests
payload_st = st.fixed_dictionaries(
    {
        "prompt": st.text(min_size=1, max_size=200),
    }
)


# ---------------------------------------------------------------------------
# Property 10 – CLI path
# ---------------------------------------------------------------------------


class TestProperty10SessionIDPassthrough:
    """Property 10: Session ID Passthrough

    For any test-runtime request that includes a session ID string, the
    constructed invocation payload or CLI command should contain that exact
    session ID.

    **Validates: Requirements 9.2**
    """

    @given(session_id=session_id_st, payload=payload_st)
    @settings(max_examples=100)
    def test_cli_command_contains_exact_session_id(self, session_id: str, payload: dict):
        """CLI invocation includes --session-id with the exact value."""
        captured_cmd = None

        def _fake_run(cmd, **kwargs):
            nonlocal captured_cmd
            captured_cmd = cmd
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = '{"response": "ok"}'
            mock_result.stderr = ""
            return mock_result

        with patch("app.deployment_handler.subprocess.run", side_effect=_fake_run):
            _invoke_runtime_cli("/tmp/fake_deploy", payload, session_id=session_id)

        assert captured_cmd is not None, "subprocess.run was not called"
        # The command must contain --session-id followed by the exact session ID
        assert "--session-id" in captured_cmd, f"--session-id flag missing from command: {captured_cmd}"
        sid_index = captured_cmd.index("--session-id")
        assert captured_cmd[sid_index + 1] == session_id, (
            f"Expected session ID {session_id!r} at index {sid_index + 1}, got {captured_cmd[sid_index + 1]!r}"
        )

    @given(session_id=session_id_st, payload=payload_st)
    @settings(max_examples=100)
    def test_http_headers_contain_exact_session_id(self, session_id: str, payload: dict):
        """HTTP invocation includes the session ID header with the exact value."""
        captured_headers = None

        class FakeResponse:
            status = 200
            data = b'{"response": "ok"}'
            headers = {}

        class FakePoolManager:
            def __init__(self, **kwargs):
                pass

            def request(self, method, url, body=None, headers=None, timeout=None):
                nonlocal captured_headers
                captured_headers = dict(headers) if headers else {}
                return FakeResponse()

        # urllib3 is imported locally inside _invoke_runtime_http, so we
        # patch the top-level urllib3 module's PoolManager attribute.
        with patch("urllib3.PoolManager", FakePoolManager):
            _invoke_runtime_http(
                runtime_arn="arn:aws:bedrock-agentcore:us-east-1:123456789:runtime/test",
                region="us-east-1",
                payload=json.dumps(payload),
                session_id=session_id,
            )

        assert captured_headers is not None, "HTTP request was not made"
        header_key = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
        assert header_key in captured_headers, f"Session ID header missing from headers: {captured_headers}"
        assert captured_headers[header_key] == session_id, (
            f"Expected session ID {session_id!r}, got {captured_headers[header_key]!r}"
        )
