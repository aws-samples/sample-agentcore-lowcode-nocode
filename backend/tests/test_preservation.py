"""Preservation property tests — MUST PASS on unfixed code.

These tests capture the baseline behavior of non-buggy paths. After the fix
is implemented, these same tests will be re-run to verify no regressions.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**

Property 2: Preservation — Framework Logic, Gateway/MCP, Tools, Requirements,
and Prompt Escaping Preserved
"""

import json
import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.deployment_models import RuntimeConfig
from app.models.enums import AgentFramework, StrandsModelProvider
from app.models.components import RuntimeConfiguration, ModelConfiguration
from app.services import code_generator
from app.services.deployment import (
    generate_agent_code as deployment_generate_agent_code,
    generate_requirements as deployment_generate_requirements,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime_config(**overrides) -> RuntimeConfig:
    """Build a minimal RuntimeConfig for code_generator.py tests."""
    defaults = {
        "name": "test-agent",
        "framework": "strands_agents",
        "model": {
            "modelId": "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "provider": "anthropic",
        },
        "systemPrompt": "You are a helpful assistant.",
    }
    defaults.update(overrides)
    return RuntimeConfig(**defaults)


def _make_runtime_configuration(
    provider: StrandsModelProvider = StrandsModelProvider.BEDROCK, **overrides
) -> RuntimeConfiguration:
    """Build a minimal RuntimeConfiguration for deployment.py tests."""
    defaults = {
        "name": "test-agent",
        "framework": AgentFramework.STRANDS_AGENTS,
        "model": ModelConfiguration(
            provider=provider,
            model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
        ),
        "system_prompt": "You are a helpful assistant.",
    }
    defaults.update(overrides)
    return RuntimeConfiguration(**defaults)


_GATEWAY_CREDS = {
    "url": "https://example.com/gateway",
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "token_endpoint": "https://example.com/oauth2/token",
    "scope": "agentcore/*",
}

# Strategy for safe system prompts (no triple quotes that break f-string embedding)
_safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), blacklist_characters="\\\"'{}`"),
    min_size=1,
    max_size=200,
)

_model_ids = st.sampled_from(
    [
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "anthropic.claude-3-haiku-20240307-v1:0",
        "amazon.nova-pro-v1:0",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    ]
)

_all_providers = st.sampled_from(list(StrandsModelProvider))

# Strands-specific imports expected in deployment.py generated code
_DEPLOYMENT_STRANDS_MARKERS = [
    "from bedrock_agentcore.runtime import BedrockAgentCoreApp",
    "from strands import Agent",
]


# ============================================================================
# Property 3: Framework-Specific Agent Logic Preserved (deployment.py)
# ============================================================================


class TestDeploymentFrameworkLogicPreservation:
    """Preservation tests for deployment.py generate_agent_code() — Strands-only.

    **Validates: Requirements 3.1, 3.6**

    All generated code MUST contain Strands + BedrockAgentCoreApp imports.
    """

    def test_strands_markers_present(self):
        """**Validates: Requirements 3.1, 3.6**

        Generated code MUST contain Strands-specific markers.
        """
        config = _make_runtime_configuration()
        code = deployment_generate_agent_code(config)
        for marker in _DEPLOYMENT_STRANDS_MARKERS:
            assert marker in code, f"Strands generated code missing expected marker: {marker}"

    def test_strands_agents_has_agent_creation(self):
        """**Validates: Requirements 3.1**

        Strands template MUST create Agent inside invoke() (per official
        bedrock-agentcore-starter-toolkit pattern).
        """
        config = _make_runtime_configuration()
        code = deployment_generate_agent_code(config)
        assert "agent = Agent(" in code
        assert "from strands import Agent" in code

    @given(provider=_all_providers, model_id=_model_ids)
    @settings(max_examples=5)
    def test_property_all_providers_embed_model_and_prompt(self, provider, model_id):
        """**Validates: Requirements 3.1, 3.6**

        For ANY provider, the generated Strands code MUST embed the model ID and
        system prompt.
        """
        config = _make_runtime_configuration(
            provider=provider,
            model=ModelConfiguration(provider=provider, model_id=model_id),
        )
        code = deployment_generate_agent_code(config)
        assert model_id in code
        assert "You are a helpful assistant." in code

    @given(provider=_all_providers)
    @settings(max_examples=5)
    def test_property_all_providers_have_invoke(self, provider):
        """**Validates: Requirements 3.1, 3.6**

        For ANY provider, the generated code MUST define an invoke function.
        """
        config = _make_runtime_configuration(provider=provider)
        code = deployment_generate_agent_code(config)
        assert "async def invoke(payload, context):" in code

    @given(provider=_all_providers)
    @settings(max_examples=5)
    def test_property_all_providers_return_response_key(self, provider):
        """**Validates: Requirements 3.1, 3.6**

        For ANY provider, the generated code MUST return {"response": ...}.
        """
        config = _make_runtime_configuration(provider=provider)
        code = deployment_generate_agent_code(config)
        assert '"response"' in code


# ============================================================================
# Property 3: Framework-Specific Agent Logic Preserved (code_generator.py)
# ============================================================================


class TestCodeGeneratorFrameworkLogicPreservation:
    """Preservation tests for code_generator.py template functions.

    **Validates: Requirements 3.1, 3.2, 3.3**

    Each template function MUST contain its framework-specific logic.
    """

    def test_langchain_web_search_has_langgraph_imports(self):
        """**Validates: Requirements 3.1**

        _generate_langchain_web_search MUST contain web search + tool-calling logic.
        Uses lightweight boto3 Converse API loop instead of LangChain/LangGraph.
        """
        code = code_generator._generate_langchain_web_search(
            "You are a search agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "us-east-1",
        )
        assert "duckduckgo_search" in code
        assert "fetch_webpage" in code
        assert "_converse_loop" in code
        assert "BedrockAgentCoreApp" in code

    def test_customer_support_has_gateway_mcp(self):
        """**Validates: Requirements 3.2**

        _generate_customer_support MUST contain MCP protocol + gateway logic.
        """
        code = code_generator._generate_customer_support(
            "You are a support agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            _GATEWAY_CREDS,
        )
        assert "_mcp_request" in code
        assert "_get_gateway_token" in code
        assert "BedrockAgentCoreApp" in code

    def test_gateway_agent_has_mcp_protocol(self):
        """**Validates: Requirements 3.2**

        _generate_gateway_agent MUST contain MCP protocol logic.
        """
        code = code_generator._generate_gateway_agent(
            "You are a gateway agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            _GATEWAY_CREDS,
        )
        assert "_mcp_request" in code
        assert "_get_gateway_token" in code
        assert "BedrockAgentCoreApp" in code

    def test_default_agent_has_boto3_converse(self):
        """**Validates: Requirements 3.1**

        _generate_default_agent MUST use boto3 Bedrock Converse API.
        """
        code = code_generator._generate_default_agent(
            "You are a helpful assistant.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "us-east-1",
        )
        assert "import boto3" in code
        assert ".converse(" in code or "bedrock-runtime" in code


# ============================================================================
# Property 4: Gateway/MCP and Built-in Tools Logic Preserved
# ============================================================================


class TestGatewayMCPPreservation:
    """Preservation tests for gateway/MCP template logic.

    **Validates: Requirements 3.2, 3.3**
    """

    def test_strands_gateway_has_cognito_oauth(self):
        """**Validates: Requirements 3.2**

        _generate_strands_gateway MUST contain Cognito OAuth token acquisition.
        """
        code = code_generator._generate_strands_gateway(
            "You are a gateway agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            _GATEWAY_CREDS,
        )
        assert "def _get_gateway_token():" in code
        assert "grant_type" in code
        assert "client_credentials" in code
        assert "access_token" in code

    def test_strands_gateway_has_mcp_protocol(self):
        """**Validates: Requirements 3.2**

        _generate_strands_gateway MUST contain MCP protocol handling.
        """
        code = code_generator._generate_strands_gateway(
            "You are a gateway agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            _GATEWAY_CREDS,
        )
        assert "def _mcp_request(" in code
        assert "jsonrpc" in code
        assert "def _list_gateway_tools(" in code
        assert "def _call_gateway_tool(" in code
        assert "def _to_bedrock_tools(" in code

    def test_strands_gateway_has_agentic_loop(self):
        """**Validates: Requirements 3.2**

        _generate_strands_gateway MUST contain the Bedrock Converse agentic loop.
        """
        code = code_generator._generate_strands_gateway(
            "You are a gateway agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            _GATEWAY_CREDS,
        )
        assert ".converse(" in code
        assert "tool_use" in code
        assert "toolResult" in code
        assert "max_turns" in code

    def test_strands_gateway_embeds_credentials(self):
        """**Validates: Requirements 3.2**

        _generate_strands_gateway MUST embed gateway credentials.
        """
        code = code_generator._generate_strands_gateway(
            "You are a gateway agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            _GATEWAY_CREDS,
        )
        assert _GATEWAY_CREDS["client_id"] in code
        assert _GATEWAY_CREDS["client_secret"] in code
        assert _GATEWAY_CREDS["token_endpoint"] in code

    def test_customer_support_has_cognito_oauth(self):
        """**Validates: Requirements 3.2**

        _generate_customer_support MUST contain Cognito OAuth token acquisition.
        """
        code = code_generator._generate_customer_support(
            "You are a support agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            _GATEWAY_CREDS,
        )
        assert "def _get_gateway_token():" in code
        assert "grant_type" in code
        assert "client_credentials" in code

    def test_customer_support_has_mcp_helpers(self):
        """**Validates: Requirements 3.2**

        _generate_customer_support MUST use MCP helpers for tool listing.
        """
        code = code_generator._generate_customer_support(
            "You are a support agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            _GATEWAY_CREDS,
        )
        assert "_mcp_request" in code
        assert "_list_gateway_tools" in code

    def test_gateway_agent_has_oauth_and_mcp(self):
        """**Validates: Requirements 3.2**

        _generate_gateway_agent MUST contain OAuth and MCP protocol logic.
        """
        code = code_generator._generate_gateway_agent(
            "You are a gateway agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            _GATEWAY_CREDS,
        )
        assert "def _get_gateway_token():" in code
        assert "_mcp_request" in code
        assert "_list_gateway_tools" in code

    @given(system_prompt=_safe_text, model_id=_model_ids)
    @settings(max_examples=3)
    def test_property_strands_gateway_mcp_helpers_always_present(self, system_prompt, model_id):
        """**Validates: Requirements 3.2**

        For ANY inputs, _generate_strands_gateway MUST always contain all
        MCP helper functions.
        """
        code = code_generator._generate_strands_gateway(system_prompt, model_id, _GATEWAY_CREDS)
        assert "_get_gateway_token" in code
        assert "_mcp_request" in code
        assert "_list_gateway_tools" in code
        assert "_call_gateway_tool" in code
        assert "_to_bedrock_tools" in code


class TestBuiltInToolsPreservation:
    """Preservation tests for built-in tools template.

    **Validates: Requirements 3.3**
    """

    def test_tools_agent_produces_valid_code(self):
        """**Validates: Requirements 3.3**

        _generate_tools_agent MUST produce valid Python with boto3 Converse API.
        Tools agent now delegates to default agent (boto3-based).
        """
        code = code_generator._generate_tools_agent(
            "You are a tools agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "us-east-1",
            has_browser=True,
            has_code_interpreter=False,
        )
        assert "import boto3" in code
        assert "BedrockAgentCoreApp" in code
        compile(code, "<test>", "exec")

    def test_tools_agent_uses_boto3(self):
        """**Validates: Requirements 3.3**

        _generate_tools_agent MUST use boto3 for Bedrock invocation.
        """
        code = code_generator._generate_tools_agent(
            "You are a tools agent.",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "us-east-1",
            has_browser=True,
            has_code_interpreter=False,
        )
        assert "import boto3" in code
        assert "bedrock" in code.lower()


# ============================================================================
# Property 5: Framework-Specific Requirements Preserved
# ============================================================================


class TestRequirementsPreservation:
    """Preservation tests for generate_requirements() in both files.

    **Validates: Requirements 3.4, 3.5**
    """

    # --- code_generator.py requirements ---

    def test_codegen_langchain_web_search_requirements(self):
        """**Validates: Requirements 6.1**

        generate_requirements() returns empty string (deps pre-bundled).
        """
        config = _make_runtime_config()
        reqs = code_generator.generate_requirements(config, tools=[], template_id="web-search-agent")
        assert reqs == ""

    def test_codegen_customer_support_requirements(self):
        """**Validates: Requirements 6.1**"""
        config = _make_runtime_config()
        reqs = code_generator.generate_requirements(config, tools=[], template_id="customer-support-assistant")
        assert reqs == ""

    def test_codegen_strands_gateway_requirements(self):
        """**Validates: Requirements 6.1**"""
        config = _make_runtime_config()
        reqs = code_generator.generate_requirements(config, tools=[], template_id="strands-gateway-agent")
        assert reqs == ""

    def test_codegen_tools_with_browser_requirements(self):
        """**Validates: Requirements 6.1**"""
        config = _make_runtime_config()
        reqs = code_generator.generate_requirements(config, tools=["browser"])
        assert reqs == ""

    def test_codegen_tools_with_gateway_requirements(self):
        """**Validates: Requirements 6.1**"""
        config = _make_runtime_config()
        reqs = code_generator.generate_requirements(config, tools=["gateway"])
        assert reqs == ""

    def test_codegen_default_requirements(self):
        """**Validates: Requirements 6.1**"""
        config = _make_runtime_config()
        reqs = code_generator.generate_requirements(config, tools=[])
        assert reqs == ""

    # --- deployment.py requirements ---

    def test_deployment_strands_deps(self):
        """**Validates: Requirements 3.4** — deps are pre-bundled, not in requirements.txt"""
        config = _make_runtime_configuration()
        reqs = deployment_generate_requirements(config)
        assert reqs == ""

    @given(provider=_all_providers)
    @settings(max_examples=5)
    def test_property_deployment_requirements_empty(self, provider):
        """**Validates: Requirements 3.4**

        For ANY provider, deployment.py generate_requirements() returns empty string.
        """
        config = _make_runtime_configuration(provider=provider)
        reqs = deployment_generate_requirements(config)
        assert reqs == ""


# ============================================================================
# Property 6: System Prompt Escaping Preserved
# ============================================================================


class TestSystemPromptEscapingPreservation:
    """Preservation tests for system prompt escaping in generated code.

    **Validates: Requirements 3.8**
    """

    def test_escape_triple_quotes_function(self):
        """**Validates: Requirements 3.8**

        _escape_triple_quotes MUST replace triple double-quotes.
        """
        result = code_generator._escape_triple_quotes('Hello """world"""')
        assert '"""' not in result
        assert '\\"\\"\\"' in result

    def test_prompt_with_special_chars_in_default_agent(self):
        """**Validates: Requirements 3.8**

        System prompt with special characters MUST produce valid Python.
        """
        special_prompt = "You are an agent. Handle 'quotes' and \\backslashes\\ carefully."
        code = code_generator._generate_default_agent(
            code_generator._escape_triple_quotes(special_prompt),
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "us-east-1",
        )
        # The generated code should be syntactically valid Python
        try:
            compile(code, "<test>", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax error: {e}")

    def test_prompt_with_special_chars_in_deployment(self):
        """**Validates: Requirements 3.8**

        System prompt with special characters in deployment.py MUST produce valid Python.
        """
        config = _make_runtime_configuration(
            system_prompt="You are an agent. Handle 'quotes' and \\backslashes\\ carefully.",
        )
        code = deployment_generate_agent_code(config)
        try:
            compile(code, "<test>", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax error: {e}")

    @given(system_prompt=_safe_text)
    @settings(max_examples=5)
    def test_property_default_agent_always_valid_python(self, system_prompt):
        """**Validates: Requirements 3.8**

        For ANY safe system prompt, _generate_default_agent MUST produce
        syntactically valid Python code.
        """
        escaped = code_generator._escape_triple_quotes(system_prompt)
        code = code_generator._generate_default_agent(escaped, "anthropic.claude-3-5-sonnet-20241022-v2:0", "us-east-1")
        try:
            compile(code, "<test>", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax error for prompt '{system_prompt}': {e}")

    @given(provider=_all_providers, system_prompt=_safe_text)
    @settings(max_examples=5)
    def test_property_deployment_always_valid_python(self, provider, system_prompt):
        """**Validates: Requirements 3.8**

        For ANY provider and safe system prompt, deployment.py generate_agent_code()
        MUST produce syntactically valid Python code.
        """
        config = _make_runtime_configuration(provider=provider, system_prompt=system_prompt)
        code = deployment_generate_agent_code(config)
        try:
            compile(code, "<test>", "exec")
        except SyntaxError as e:
            pytest.fail(
                f"Generated code has syntax error for provider={provider.value}, prompt='{system_prompt[:50]}': {e}"
            )


# ============================================================================
# Template Routing Preservation (code_generator.py)
# ============================================================================


class TestTemplateRoutingPreservation:
    """Preservation tests for generate_agent_code() routing in code_generator.py.

    **Validates: Requirements 3.5**
    """

    def test_routes_langchain_web_search(self):
        """**Validates: Requirements 3.5**

        template_id="web-search-agent" MUST route to _generate_langchain_web_search.
        """
        config = _make_runtime_config()
        code = code_generator.generate_agent_code(config, template_id="web-search-agent")
        assert "Web Search Agent" in code or "duckduckgo_search" in code

    def test_routes_strands_gateway(self):
        """**Validates: Requirements 3.5**

        template_id="strands-gateway-agent" MUST route to _generate_strands_gateway.
        """
        config = _make_runtime_config()
        gateway_config = {
            "gateway_url": _GATEWAY_CREDS["url"],
            "client_info": {
                "client_id": _GATEWAY_CREDS["client_id"],
                "client_secret": _GATEWAY_CREDS["client_secret"],
                "token_endpoint": _GATEWAY_CREDS["token_endpoint"],
                "scope": _GATEWAY_CREDS["scope"],
            },
        }
        code = code_generator.generate_agent_code(
            config, gateway_config=gateway_config, template_id="strands-gateway-agent"
        )
        assert "_mcp_request" in code
        assert "_to_bedrock_tools" in code

    def test_routes_customer_support(self):
        """**Validates: Requirements 3.5**

        template_id="customer-support-assistant" MUST route to _generate_customer_support.
        """
        config = _make_runtime_config()
        gateway_config = {
            "gateway_url": _GATEWAY_CREDS["url"],
            "client_info": {
                "client_id": _GATEWAY_CREDS["client_id"],
                "client_secret": _GATEWAY_CREDS["client_secret"],
                "token_endpoint": _GATEWAY_CREDS["token_endpoint"],
                "scope": _GATEWAY_CREDS["scope"],
            },
        }
        code = code_generator.generate_agent_code(
            config,
            gateway_config=gateway_config,
            template_id="customer-support-assistant",
        )
        assert "_mcp_request" in code or "Gateway" in code

    def test_routes_to_gateway_agent_with_gateway_tool(self):
        """**Validates: Requirements 3.5**

        tools=["gateway"] with gateway_config MUST route to _generate_gateway_agent.
        """
        config = _make_runtime_config()
        gateway_config = {
            "gateway_url": _GATEWAY_CREDS["url"],
            "client_info": {
                "client_id": _GATEWAY_CREDS["client_id"],
                "client_secret": _GATEWAY_CREDS["client_secret"],
                "token_endpoint": _GATEWAY_CREDS["token_endpoint"],
                "scope": _GATEWAY_CREDS["scope"],
            },
        }
        code = code_generator.generate_agent_code(config, tools=["gateway"], gateway_config=gateway_config)
        assert "_mcp_request" in code
        assert "Gateway" in code or "gateway" in code.lower()

    def test_routes_to_tools_agent_with_browser(self):
        """**Validates: Requirements 3.5**

        tools=["browser"] MUST route to _generate_tools_agent.
        """
        config = _make_runtime_config()
        code = code_generator.generate_agent_code(config, tools=["browser"])
        assert "import boto3" in code

    def test_routes_to_default_strands_agent(self):
        """**Validates: Requirements 3.5**

        No template_id and no tools MUST route to _generate_strands_default.
        """
        config = _make_runtime_config()
        code = code_generator.generate_agent_code(config, tools=[])
        # Default agent uses Strands Agent + BedrockAgentCoreApp
        assert "from strands import Agent" in code
        assert "from bedrock_agentcore.runtime import BedrockAgentCoreApp" in code

    def test_unrecognized_framework_still_generates_strands(self):
        """**Validates: Requirements 3.5**

        An unrecognized framework value is accepted and generates Strands code
        (backward compatibility — no longer raises ValueError).
        """
        config = _make_runtime_config(framework="nonexistent_framework")
        code = code_generator.generate_agent_code(config, tools=[])
        assert "from strands import Agent" in code


# ============================================================================
# Deployment.py All 9 Frameworks Supported
# ============================================================================


class TestDeploymentAllProvidersSupported:
    """Verify all Strands model providers produce non-empty code.

    **Validates: Requirements 3.6**
    """

    @pytest.mark.parametrize("provider", list(StrandsModelProvider))
    def test_provider_generates_code(self, provider):
        """**Validates: Requirements 3.6**

        Each provider MUST generate non-empty Strands agent code with
        BedrockAgentCoreApp and Strands imports.
        """
        config = _make_runtime_configuration(provider=provider)
        code = deployment_generate_agent_code(config)
        assert len(code) > 100, f"Provider {provider.value} generated too little code"
        assert "SYSTEM_PROMPT" in code
        assert "model_id=" in code or "MODEL_ID" in code
        assert "from bedrock_agentcore.runtime import BedrockAgentCoreApp" in code
        assert "from strands import Agent" in code


# ============================================================================
# _parse_response_body Preservation
# ============================================================================


class TestParseResponseBodyPreservation:
    """Preservation tests for _parse_response_body — valid input handling.

    **Validates: Requirements 3.1**
    """

    def test_parse_valid_json_with_response_key(self):
        """**Validates: Requirements 3.1**"""
        from app.deployment_handler import _parse_response_body

        body = json.dumps({"response": "Hello from the agent!"})
        result = _parse_response_body(body)
        assert result == "Hello from the agent!"

    def test_parse_valid_json_with_output_key(self):
        """**Validates: Requirements 3.1**"""
        from app.deployment_handler import _parse_response_body

        body = json.dumps({"output": "Agent output here"})
        result = _parse_response_body(body)
        assert result == "Agent output here"

    def test_parse_sse_stream_format(self):
        """**Validates: Requirements 3.1**"""
        from app.deployment_handler import _parse_response_body

        sse_body = 'data: {"partial": "chunk1"}\ndata: {"response": "final answer"}'
        result = _parse_response_body(sse_body)
        assert result == "final answer"

    def test_parse_plain_text_fallback(self):
        """**Validates: Requirements 3.1**"""
        from app.deployment_handler import _parse_response_body

        body = "This is just plain text from the agent."
        result = _parse_response_body(body)
        assert result == body

    def test_parse_empty_string(self):
        """**Validates: Requirements 3.1**"""
        from app.deployment_handler import _parse_response_body

        result = _parse_response_body("")
        assert result == ""

    @given(response_text=st.text(min_size=1, max_size=200))
    @settings(max_examples=5)
    def test_property_parse_json_response_key_extraction(self, response_text):
        """**Validates: Requirements 3.1**"""
        from app.deployment_handler import _parse_response_body

        body = json.dumps({"response": response_text})
        result = _parse_response_body(body)
        assert result == response_text


# ============================================================================
# Frontend Retry Logic Preservation
# ============================================================================


class TestFrontendRetryLogicPreservation:
    """Preservation tests for DeployPanel.tsx retry logic.

    **Validates: Requirements 3.7**
    """

    @pytest.fixture
    def deploy_panel_source(self):
        frontend_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "frontend",
            "src",
            "components",
            "deploy",
            "DeployPanel.tsx",
        )
        with open(frontend_path, "r") as f:
            return f.read()

    def _extract_handle_test(self, source: str) -> str:
        start = source.find("const handleTest = useCallback(async ()")
        assert start != -1, "Could not find handleTest in DeployPanel.tsx"
        section = source[start:]
        end = section.find("}, [deploymentStatus.endpoint")
        assert end != -1, "Could not find end of handleTest useCallback"
        return section[:end]

    def test_max_retries_is_five(self, deploy_panel_source):
        """**Validates: Requirements 3.7**"""
        body = self._extract_handle_test(deploy_panel_source)
        assert "MAX_RETRIES = 5" in body

    def test_retry_loop_structure(self, deploy_panel_source):
        """**Validates: Requirements 3.7**"""
        body = self._extract_handle_test(deploy_panel_source)
        assert "for (let attempt = 1; attempt <= MAX_RETRIES; attempt++)" in body

    def test_cold_start_detection_patterns(self, deploy_panel_source):
        """**Validates: Requirements 3.7**"""
        body = self._extract_handle_test(deploy_panel_source)
        expected_patterns = [
            "initialization time exceeded",
            "Runtime initialization",
            "cold start",
            "Read timeout",
            "read timeout",
            "timed out",
        ]
        for pattern in expected_patterns:
            assert pattern in body, f"Missing cold-start detection pattern: {pattern}"
