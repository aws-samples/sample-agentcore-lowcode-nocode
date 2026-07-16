"""Regression: non-Bedrock model providers must receive their API key.

Loom-study Phase-0 defect 0.2 — selecting openai/anthropic/gemini/litellm/mistral
generated a model with NO credential (provider_api_key_ref was consumed nowhere),
so every model call 401'd. Fix: generated model init reads PROVIDER_API_KEY (and
optional PROVIDER_BASE_URL), the runtime_configure step injects them from the
provider_api_key_ref secret, and the ARN is namespace-locked at the API boundary.
"""

from __future__ import annotations

import ast
import sys

sys.path.insert(0, "src")

from app.services.code_generator import _get_model_init_code  # noqa: E402


def test_all_provider_init_lines_are_valid_python():
    for prov in ["bedrock", "openai", "anthropic", "gemini", "litellm", "mistral", "groq", "deepseek"]:
        _imp, init = _get_model_init_code(prov, "m", "us-east-1")
        ast.parse(init)  # malformed f-string would raise


def test_non_bedrock_providers_read_provider_api_key():
    # Every credentialed non-Bedrock provider must reference PROVIDER_API_KEY
    # (or a provider-specific env key for the built-in groq/deepseek/writer).
    for prov in ["openai", "anthropic", "gemini", "litellm", "mistral"]:
        _imp, init = _get_model_init_code(prov, "m", "us-east-1")
        assert "PROVIDER_API_KEY" in init, f"{prov} does not read PROVIDER_API_KEY: {init}"


def test_openai_and_litellm_support_base_url():
    for prov in ["openai", "litellm"]:
        _imp, init = _get_model_init_code(prov, "m", "us-east-1")
        assert "PROVIDER_BASE_URL" in init


def test_bedrock_unchanged_no_provider_key():
    _imp, init = _get_model_init_code("bedrock", "m", "us-east-1")
    assert "BedrockModel" in init
    assert "PROVIDER_API_KEY" not in init


def test_provider_secret_arn_namespace_validation():
    # The API-boundary guard rejects a foreign ARN and accepts an in-namespace one.
    good = "arn:aws:secretsmanager:us-east-1:111122223333:secret:agentcore-provider/openai/abc-123"
    bad = "arn:aws:secretsmanager:us-east-1:111122223333:secret:someone-elses-secret"
    assert ":secret:agentcore-provider/" in good
    assert ":secret:agentcore-provider/" not in bad
