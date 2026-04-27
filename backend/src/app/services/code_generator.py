"""Code generator for AgentCore Runtime agent code and requirements.

Extracted from routers/deployment.py. Generates Python agent code and
requirements.txt content based on RuntimeConfig, connected tools,
gateway configuration, and template selection.

All generated agents use BedrockAgentCoreApp SDK for the AgentCore Runtime
protocol. Dependencies are pre-bundled into code.zip at deploy time via
S3 dependency bundles, so no pip-install phase is needed during init.

Requirements: 5.1, 5.2, 5.6
"""

import os
from typing import Optional

from app.models.deployment_models import RuntimeConfig


# Provider to package mapping (Strands-only)
PROVIDER_PACKAGES: dict[str, str] = {
    "bedrock": "strands-agents strands-agents-tools",
    "openai": "strands-agents strands-agents-tools openai",
    "anthropic": "strands-agents strands-agents-tools anthropic",
    "gemini": "strands-agents strands-agents-tools google-generativeai",
    "litellm": "strands-agents strands-agents-tools litellm",
    "mistral": "strands-agents strands-agents-tools mistralai",
    "ollama": "strands-agents strands-agents-tools ollama",
    "sagemaker": "strands-agents strands-agents-tools",
    "writer": "strands-agents strands-agents-tools",
    "groq": "strands-agents strands-agents-tools groq",
    "deepseek": "strands-agents strands-agents-tools openai",
    "together": "strands-agents strands-agents-tools litellm",
    "llamaapi": "strands-agents strands-agents-tools",
}

# Backward compat alias
FRAMEWORK_PACKAGES = {"strands_agents": "strands-agents", "custom": ""}


def _to_cross_region_model_id(model_id: str) -> str:
    """Convert on-demand model IDs to cross-region inference profile format.

    On-demand model IDs like ``anthropic.claude-3-5-sonnet-20241022-v2:0``
    fail with ValidationException on Bedrock converse API.  Cross-region
    inference profiles (``us.anthropic.…``) work reliably.

    Already-prefixed IDs (``us.…``, ``global.…``) are returned as-is.

    Appends ``-v1:0`` version suffix when missing — Bedrock inference
    profiles require this suffix (e.g. ``us.anthropic.claude-sonnet-4-20250514-v1:0``).
    """
    if not model_id.startswith(("us.", "global.", "eu.", "ap.")):
        model_id = f"us.{model_id}"
    # Bedrock inference profiles require a version suffix like -v1:0 or -v2:0.
    # If the model ID looks like it's missing one, append -v1:0.
    if "anthropic." in model_id and not _has_version_suffix(model_id):
        model_id = f"{model_id}-v1:0"
    return model_id


def _has_version_suffix(model_id: str) -> bool:
    """Check if model ID already has a version suffix like -v1:0 or -v2:0."""
    import re
    return bool(re.search(r"-v\d+:\d+$", model_id))


def _get_model_id(config: RuntimeConfig) -> str:
    """Extract model ID from RuntimeConfig, with a sensible default.

    Converts to cross-region inference profile format so the Bedrock
    converse API works reliably in any region.

    SECURITY: Validates the model ID to prevent code injection via
    f-string interpolation in generated code templates.
    """
    model_id = config.model.get("modelId", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    model_id = _to_cross_region_model_id(model_id)
    return _sanitize_identifier(model_id)


def _get_region() -> str:
    """Read AWS region from environment."""
    return os.getenv("APP_AWS_REGION", os.getenv("AWS_REGION", "us-east-1"))


import re as _re

# Pattern for valid model IDs: alphanumeric, dots, hyphens, underscores, colons, slashes
_MODEL_ID_PATTERN = _re.compile(r"^[a-zA-Z0-9._:/-]+$")

# Pattern for valid AWS region names (e.g., us-east-1, ap-southeast-2)
_REGION_PATTERN = _re.compile(r"^[a-z]{2}-[a-z]+-\d+$")


def _sanitize_identifier(value: str) -> str:
    """Sanitize a model ID or similar identifier to prevent code injection.

    Only allows alphanumeric characters, dots, hyphens, underscores,
    colons, and forward slashes. Raises ValueError on invalid input.

    SECURITY: This prevents injection via f-string templates like:
      MODEL_ID = "{model_id}"
    where a malicious model_id could close the string and inject code.
    """
    if not value or len(value) > 256:
        raise ValueError(f"Invalid identifier: must be 1-256 characters, got {len(value) if value else 0}")
    if not _MODEL_ID_PATTERN.match(value):
        raise ValueError(
            f"Invalid identifier '{value[:50]}...': contains disallowed characters. "
            f"Only alphanumeric, dots, hyphens, underscores, colons, and slashes are allowed."
        )
    return value


_SAFE_AGENT_ID = _re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


def _sanitize_agent_id(value: str) -> str:
    """Sanitize an agent ID for safe use as a Python variable name fragment.

    SECURITY: Prevents code injection in multi-agent code generation where
    agentId values are interpolated into f-strings as variable names and
    string literals.
    """
    if not value or not _SAFE_AGENT_ID.match(value):
        raise ValueError(
            f"Invalid agent ID: '{value[:50]}'. Must be 1-64 alphanumeric chars, hyphens, underscores, starting with a letter."
        )
    return value


def _sanitize_string_literal(value: str) -> str:
    """Sanitize a value for safe embedding in a Python double-quoted string literal.

    SECURITY: Prevents code injection when embedding config values (URLs,
    client IDs, etc.) inside double-quoted f-string templates.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")


def _escape_triple_quotes(text: str) -> str:
    """Escape text for safe embedding inside triple-double-quoted Python strings.

    SECURITY: Prevents code injection by escaping backslashes first (to avoid
    creating new escape sequences), then triple-double-quotes and curly braces
    (to prevent f-string expression evaluation).
    """
    # Escape existing backslashes to prevent them from creating escape sequences
    text = text.replace("\\", "\\\\")
    # Escape triple-double-quotes
    text = text.replace('"""', '\\"\\"\\"')
    # Escape curly braces to prevent f-string injection
    text = text.replace("{", "{{")
    text = text.replace("}", "}}")
    return text


def _extract_gateway_credentials(gateway_config: Optional[dict]) -> dict:
    """Pull Cognito credentials out of a gateway_config dict.

    SECURITY: All values are sanitized for safe embedding in double-quoted
    Python string literals to prevent code injection.
    """
    result = {
        "url": "",
        "client_id": "",
        "client_secret": "",
        "token_endpoint": "",
        "scope": "",
    }
    if not gateway_config or not isinstance(gateway_config, dict):
        return result
    result["url"] = _sanitize_string_literal(gateway_config.get("gateway_url", ""))
    ci = gateway_config.get("client_info", {})
    if ci:
        result["client_id"] = _sanitize_string_literal(ci.get("client_id", ""))
        result["client_secret"] = _sanitize_string_literal(ci.get("client_secret", ""))
        result["token_endpoint"] = _sanitize_string_literal(ci.get("token_endpoint", ""))
        result["scope"] = _sanitize_string_literal(ci.get("scope", ""))
    return result


# ---------------------------------------------------------------------------
# Template-specific code generators
# ---------------------------------------------------------------------------


def _generate_langchain_web_search(system_prompt: str, model_id: str, region: str) -> str:
    """Generate Web Search agent using BedrockAgentCoreApp + boto3 Converse API.

    Uses DuckDuckGo + Open-Meteo weather via stdlib urllib (zero extra deps beyond boto3).
    """
    return f'''"""AgentCore Runtime - Web Search Agent

Uses BedrockAgentCoreApp SDK for AgentCore Runtime protocol.
Lightweight tool-calling loop via boto3 Converse API.
"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp
import boto3
import json
import os
import re
import time
import urllib.request
import urllib.parse

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """{system_prompt}"""
MODEL_ID = os.environ.get("MODEL_ID", "{model_id}")
REGION = os.environ.get("AWS_REGION", "{region}")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0"

WMO_CODES = {{0:"Clear sky",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",45:"Foggy",48:"Rime fog",51:"Light drizzle",53:"Moderate drizzle",55:"Dense drizzle",61:"Slight rain",63:"Moderate rain",65:"Heavy rain",71:"Slight snow",73:"Moderate snow",75:"Heavy snow",80:"Slight rain showers",81:"Moderate rain showers",82:"Violent rain showers",95:"Thunderstorm",96:"Thunderstorm with hail",99:"Thunderstorm with heavy hail"}}

TOOL_CONFIG = {{
    "tools": [
        {{
            "toolSpec": {{
                "name": "duckduckgo_search",
                "description": "Search the web using DuckDuckGo. Returns top 5 results with title, URL, and snippet.",
                "inputSchema": {{
                    "json": {{
                        "type": "object",
                        "properties": {{
                            "query": {{"type": "string", "description": "The search query"}}
                        }},
                        "required": ["query"]
                    }}
                }}
            }}
        }},
        {{
            "toolSpec": {{
                "name": "get_weather",
                "description": "Get current weather for a city or location. Returns temperature, humidity, wind speed, and conditions. Use this tool whenever the user asks about weather.",
                "inputSchema": {{
                    "json": {{
                        "type": "object",
                        "properties": {{
                            "location": {{"type": "string", "description": "City or location name (e.g. 'Chicago', 'London', 'Tokyo')"}}
                        }},
                        "required": ["location"]
                    }}
                }}
            }}
        }},
        {{
            "toolSpec": {{
                "name": "fetch_webpage",
                "description": "Fetch and extract text content from a webpage URL. Use after searching to get actual page content.",
                "inputSchema": {{
                    "json": {{
                        "type": "object",
                        "properties": {{
                            "url": {{"type": "string", "description": "The URL to fetch"}}
                        }},
                        "required": ["url"]
                    }}
                }}
            }}
        }}
    ]
}}


def _http_get(url: str, timeout: int = 12, retries: int = 2) -> bytes:
    """HTTP GET with retry logic."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={{"User-Agent": UA}})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1 * (attempt + 1))
    raise last_err


def _do_search(query: str) -> str:
    """Run a DuckDuckGo text search via the Instant Answer API (stdlib only)."""
    try:
        url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode({{"q": query, "format": "json", "no_html": "1"}})
        data = json.loads(_http_get(url).decode())
        results = []
        if data.get("Abstract"):
            results.append({{"title": data.get("Heading", query), "snippet": data["Abstract"], "url": data.get("AbstractURL", "")}})
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({{"title": topic.get("Text", "")[:80], "snippet": topic.get("Text", ""), "url": topic.get("FirstURL", "")}})
        return json.dumps(results) if results else json.dumps({{"message": f"No results found for: {{query}}"}})
    except Exception as e:
        return json.dumps({{"error": str(e)}})


def _do_weather(location: str) -> str:
    """Get current weather using Open-Meteo API (free, no API key, reliable from AWS)."""
    try:
        geo_url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({{"name": location, "count": 1}})
        geo = json.loads(_http_get(geo_url, timeout=8).decode())
        results = geo.get("results", [])
        if not results:
            return json.dumps({{"error": f"Location not found: {{location}}"}})
        lat, lon = results[0]["latitude"], results[0]["longitude"]
        place = results[0].get("name", location)
        country = results[0].get("country", "")
        wx_url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({{
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        }})
        wx = json.loads(_http_get(wx_url, timeout=8).decode())
        cur = wx.get("current", {{}})
        code = cur.get("weather_code", -1)
        desc = WMO_CODES.get(code, f"Code {{code}}")
        return json.dumps({{
            "location": f"{{place}}, {{country}}",
            "description": desc,
            "temperature_F": cur.get("temperature_2m"),
            "humidity_pct": cur.get("relative_humidity_2m"),
            "wind_mph": cur.get("wind_speed_10m"),
        }})
    except Exception as e:
        return json.dumps({{"error": str(e)}})


def _do_fetch(url: str) -> str:
    """Fetch a webpage and return its text content.

    SECURITY: Only allows http/https URLs to prevent SSRF via file://, gopher://, etc.
    Blocks requests to private/internal IP ranges (169.254.x.x, 10.x.x.x, etc.).
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return json.dumps({{"error": "Only http and https URLs are allowed"}})
        # Block requests to metadata endpoints and private IPs
        hostname = parsed.hostname or ""
        if hostname in ("169.254.169.254", "metadata.google.internal", "localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return json.dumps({{"error": "Requests to internal/metadata endpoints are blocked"}})
        if hostname.startswith("10.") or hostname.startswith("172.") or hostname.startswith("192.168."):
            return json.dumps({{"error": "Requests to private IP ranges are blocked"}})
        html = _http_get(url, timeout=12).decode("utf-8", errors="replace")
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\\s+", " ", text).strip()
        return text[:8000]
    except Exception as e:
        return f"Error fetching {{url}}: {{e}}"


TOOL_HANDLERS = {{
    "duckduckgo_search": lambda args: _do_search(args.get("query", "")),
    "get_weather": lambda args: _do_weather(args.get("location", "")),
    "fetch_webpage": lambda args: _do_fetch(args.get("url", "")),
}}

_bedrock = None

def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    return _bedrock


def _converse_loop(prompt: str, max_turns: int = 10) -> str:
    """Run a multi-turn Converse API loop with tool use."""
    messages = [{{"role": "user", "content": [{{"text": prompt}}]}}]

    for _ in range(max_turns):
        resp = _get_bedrock().converse(
            modelId=MODEL_ID,
            system=[{{"text": SYSTEM_PROMPT}}],
            messages=messages,
            toolConfig=TOOL_CONFIG,
        )
        output = resp["output"]["message"]
        messages.append(output)

        if resp["stopReason"] == "tool_use":
            tool_results = []
            for block in output["content"]:
                if "toolUse" in block:
                    tu = block["toolUse"]
                    handler = TOOL_HANDLERS.get(tu["name"])
                    result = handler(tu["input"]) if handler else "Unknown tool"
                    tool_results.append({{
                        "toolResult": {{
                            "toolUseId": tu["toolUseId"],
                            "content": [{{"text": result}}],
                        }}
                    }})
            messages.append({{"role": "user", "content": tool_results}})
        else:
            for block in output["content"]:
                if "text" in block:
                    return block["text"]
            return str(output["content"])

    return "Max tool-use turns reached."


@app.entrypoint
def invoke(payload):
    """Process user prompt through the web search agent."""
    message = payload.get("prompt", "Hello")
    response_text = _converse_loop(message)
    return {{"response": response_text}}

if __name__ == "__main__":
    app.run()
'''


def _generate_strands_gateway(system_prompt: str, model_id: str, creds: dict) -> str:
    """Generate Gateway agent using Strands Agent + MCPClient.

    Uses the official pattern from amazon-bedrock-agentcore-samples
    (01-tutorials/02-AgentCore-gateway/04-integration/01-runtime-gateway):
    - MCPClient with streamablehttp_client for Gateway MCP communication
    - MCP client started at module level (tools fetched once, not per request)
    - Strands Agent for tool discovery, calling, and agentic loop
    - BedrockAgentCoreApp for the AgentCore Runtime protocol
    - Tool pagination via get_full_tools_list()

    SECURITY NOTE: Cognito client credentials are embedded as fallback defaults.
    In production, these are injected via environment variables on the Runtime.
    """
    return f'''"""AgentCore Runtime - Gateway Agent

Uses Strands Agent + MCPClient for Gateway tool discovery and invocation.
Official pattern from amazon-bedrock-agentcore-samples.
"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamablehttp_client
import json
import os
import urllib.request
import urllib.parse

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """{system_prompt}"""
MODEL_ID = os.environ.get("MODEL_ID", "{model_id}")
REGION = os.environ.get("AWS_REGION", "us-east-1")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID") or os.environ.get("OAUTH_CLIENT_ID", "")
COGNITO_CLIENT_SECRET = os.environ.get("COGNITO_CLIENT_SECRET") or os.environ.get("OAUTH_CLIENT_SECRET", "")
COGNITO_TOKEN_ENDPOINT = os.environ.get("COGNITO_TOKEN_ENDPOINT") or os.environ.get("OAUTH_TOKEN_ENDPOINT", "")
COGNITO_SCOPE = os.environ.get("COGNITO_SCOPE") or os.environ.get("OAUTH_SCOPE", "")


def _get_gateway_token():
    """Get OAuth2 access token from Cognito for Gateway authentication."""
    if not COGNITO_CLIENT_ID or not COGNITO_TOKEN_ENDPOINT:
        return ""
    try:
        form = {{"grant_type": "client_credentials", "client_id": COGNITO_CLIENT_ID,
                "client_secret": COGNITO_CLIENT_SECRET}}
        if COGNITO_SCOPE:
            form["scope"] = COGNITO_SCOPE
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(COGNITO_TOKEN_ENDPOINT, data=data,
                                      headers={{"Content-Type": "application/x-www-form-urlencoded"}})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())["access_token"]
    except Exception as e:
        print(f"Warning: Failed to get gateway token: {{e}}")
        return ""


def get_full_tools_list(client):
    """Retrieve all tools from MCP client, handling pagination."""
    more_tools = True
    tools = []
    pagination_token = None
    while more_tools:
        tmp_tools = client.list_tools_sync(pagination_token=pagination_token)
        tools.extend(tmp_tools)
        if tmp_tools.pagination_token is None:
            more_tools = False
        else:
            pagination_token = tmp_tools.pagination_token
    return tools


# ── Lazy init: boto3/MCP clients may not have valid creds at module load ──

def _create_transport():
    token = _get_gateway_token()
    headers = {{"Authorization": f"Bearer {{token}}"}} if token else {{}}
    return streamablehttp_client(GATEWAY_URL, headers=headers)

_agent = None

def _get_agent():
    global _agent
    if _agent is not None:
        return _agent
    model = BedrockModel(model_id=MODEL_ID, region_name=REGION)
    if GATEWAY_URL:
        mcp_client = MCPClient(_create_transport)
        mcp_client.start()
        tools = get_full_tools_list(mcp_client)
        _agent = Agent(model=model, tools=tools, system_prompt=SYSTEM_PROMPT)
    else:
        _agent = Agent(model=model, system_prompt=SYSTEM_PROMPT)
    return _agent


@app.entrypoint
def invoke(payload):
    """Strands Agent with MCP Gateway tools."""
    message = payload.get("prompt", "Hello")
    agent = _get_agent()
    result = agent(message)
    return {{"response": str(result)}}

if __name__ == "__main__":
    app.run()
'''


def _generate_customer_support(system_prompt: str, model_id: str, creds: dict) -> str:
    """Generate Customer Support agent — same gateway pattern with support-specific prompt."""
    return _generate_strands_gateway(system_prompt, model_id, creds)


def _generate_gateway_agent(system_prompt: str, model_id: str, creds: dict) -> str:
    """Generate generic agent with MCP Gateway tools."""
    return _generate_strands_gateway(system_prompt, model_id, creds)


def _generate_tools_agent(
    system_prompt: str,
    model_id: str,
    region: str,
    has_browser: bool,
    has_code_interpreter: bool,
) -> str:
    """Generate agent with built-in tools (code interpreter, browser)."""
    imports = [
        '"""AgentCore Runtime Agent — Strands Agent with Built-in Tools"""',
        "import os",
        "import json",
        "",
        "from strands import Agent, tool",
        "from strands.models.bedrock import BedrockModel",
        "from bedrock_agentcore.runtime import BedrockAgentCoreApp",
    ]
    tools_list = []

    if has_code_interpreter:
        imports.append("from bedrock_agentcore.tools.code_interpreter_client import code_session")
    if has_browser:
        imports.append("from bedrock_agentcore.tools.browser_client import browser_session")

    tool_defs = ""
    if has_code_interpreter:
        tools_list.append("execute_python")
        tool_defs += '''
@tool
def execute_python(code: str, description: str = "") -> str:
    """Execute Python code in a secure sandbox. Use for calculations, data analysis, or any Python task."""
    with code_session(REGION) as client:
        response = client.invoke("executeCode", {"code": code, "language": "python", "clearContext": False})
    for event in response.get("stream", [response]):
        result = event.get("result", event)
        return json.dumps(result) if isinstance(result, dict) else str(result)
    return "No output"
'''

    if has_browser:
        tools_list.append("browse_web")
        tool_defs += '''
@tool
def browse_web(url: str, action: str = "navigate") -> str:
    """Browse a web page and return its content."""
    with browser_session(REGION) as client:
        response = client.invoke(action, {"url": url})
    return json.dumps(response) if isinstance(response, dict) else str(response)
'''

    tl = ", ".join(tools_list)
    return (
        "\n".join(imports)
        + f"""

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = \"\"\"{system_prompt}\"\"\"
MODEL_ID = os.environ.get("MODEL_ID", "{model_id}")
REGION = os.environ.get("AWS_REGION", "{region}")
{tool_defs}
_agent = None

def _get_agent():
    global _agent
    if _agent is None:
        model = BedrockModel(model_id=MODEL_ID, region_name=REGION)
        _agent = Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=[{tl}])
    return _agent

@app.entrypoint
def invoke(payload):
    result = _get_agent()(payload.get("prompt", "Hello"))
    return {{"response": str(result)}}

if __name__ == "__main__":
    app.run()
"""
    )


def _generate_mcp_server_runtime(system_prompt: str, model_id: str, region: str) -> str:
    """Generate MCP Server Runtime — tools hosted directly on the runtime via MCP protocol.

    No Gateway or Lambda needed. Tools are embedded Python functions served
    via BedrockAgentCoreApp with MCP protocol handlers.
    """
    return f'''"""AgentCore Runtime - MCP Server with Embedded Tools

Hosts tools directly on the runtime via MCP protocol.
No Gateway or Lambda needed — tools are Python functions served inline.
Uses boto3 Converse API for the agent brain with automatic tool routing.
"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp
import boto3
import json
import os
import urllib.request
import urllib.parse
import re

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """{system_prompt}"""
MODEL_ID = os.environ.get("MODEL_ID", "{model_id}")
REGION = os.environ.get("AWS_REGION", "{region}")

_bedrock = None

def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    return _bedrock


# ── Embedded Tool Definitions ────────────────────────────────────────────


UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0"
WMO_CODES = {{0:"Clear sky",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",45:"Foggy",48:"Rime fog",51:"Light drizzle",53:"Moderate drizzle",55:"Dense drizzle",61:"Slight rain",63:"Moderate rain",65:"Heavy rain",71:"Slight snow",73:"Moderate snow",75:"Heavy snow",80:"Slight rain showers",81:"Moderate rain showers",82:"Violent rain showers",95:"Thunderstorm",96:"Thunderstorm with hail",99:"Thunderstorm with heavy hail"}}


def _http_get(url: str, timeout: int = 10, retries: int = 2) -> bytes:
    """HTTP GET with retry logic."""
    import time as _time
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={{"User-Agent": UA}})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            if attempt < retries:
                _time.sleep(1 * (attempt + 1))
    raise last_err


def tool_get_weather(city: str) -> str:
    """Get current weather using Open-Meteo API (free, no API key, reliable from AWS)."""
    try:
        geo_url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({{"name": city, "count": 1}})
        geo = json.loads(_http_get(geo_url, timeout=8).decode())
        results = geo.get("results", [])
        if not results:
            return json.dumps({{"error": f"Location not found: {{city}}"}})
        lat, lon = results[0]["latitude"], results[0]["longitude"]
        place = results[0].get("name", city)
        country = results[0].get("country", "")
        wx_url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({{
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        }})
        wx = json.loads(_http_get(wx_url, timeout=8).decode())
        cur = wx.get("current", {{}})
        code = cur.get("weather_code", -1)
        desc = WMO_CODES.get(code, f"Code {{code}}")
        return json.dumps({{
            "city": f"{{place}}, {{country}}",
            "temperature_f": cur.get("temperature_2m"),
            "humidity_pct": cur.get("relative_humidity_2m"),
            "wind_mph": cur.get("wind_speed_10m"),
            "description": desc,
        }})
    except Exception as e:
        return json.dumps({{"error": str(e)}})


def tool_search_web(query: str) -> str:
    """Search the web using DuckDuckGo Instant Answer API."""
    try:
        url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
            {{"q": query, "format": "json", "no_html": "1"}}
        )
        data = json.loads(_http_get(url, timeout=12).decode())
        results = []
        if data.get("Abstract"):
            results.append({{"title": data.get("Heading", query), "snippet": data["Abstract"], "url": data.get("AbstractURL", "")}})
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({{"title": topic.get("Text", "")[:80], "snippet": topic.get("Text", ""), "url": topic.get("FirstURL", "")}})
        return json.dumps(results) if results else json.dumps({{"message": f"No results for: {{query}}"}})
    except Exception as e:
        return json.dumps({{"error": str(e)}})


def tool_fetch_url(url: str) -> str:
    """Fetch and extract text content from a URL.

    SECURITY: Validates URL scheme and blocks internal/metadata endpoints.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return json.dumps({{"error": "Only http/https URLs are allowed"}})
        hostname = (parsed.hostname or "").lower()
        if hostname in ("169.254.169.254", "metadata.google.internal", "localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return json.dumps({{"error": "Requests to internal endpoints are blocked"}})
        if hostname.startswith("10.") or hostname.startswith("172.") or hostname.startswith("192.168."):
            return json.dumps({{"error": "Requests to private IP ranges are blocked"}})
        html = _http_get(url, timeout=12).decode("utf-8", errors="replace")
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\\s+", " ", text).strip()
        return text[:8000]
    except Exception as e:
        return json.dumps({{"error": str(e)}})


# ── Tool Registry ────────────────────────────────────────────────────────

TOOLS = [
    {{
        "name": "get_weather",
        "description": "Get current weather for a city. Returns temperature, humidity, wind speed, and conditions.",
        "input_schema": {{
            "type": "object",
            "properties": {{
                "city": {{"type": "string", "description": "City name (e.g. 'London', 'New York')"}}
            }},
            "required": ["city"]
        }},
        "handler": tool_get_weather,
    }},
    {{
        "name": "search_web",
        "description": "Search the web for information. Returns relevant results with titles and snippets.",
        "input_schema": {{
            "type": "object",
            "properties": {{
                "query": {{"type": "string", "description": "Search query"}}
            }},
            "required": ["query"]
        }},
        "handler": tool_search_web,
    }},
    {{
        "name": "fetch_url",
        "description": "Fetch and extract text content from a URL. Useful for reading web pages.",
        "input_schema": {{
            "type": "object",
            "properties": {{
                "url": {{"type": "string", "description": "The URL to fetch"}}
            }},
            "required": ["url"]
        }},
        "handler": tool_fetch_url,
    }},
]

TOOL_CONFIG = {{
    "tools": [
        {{
            "toolSpec": {{
                "name": t["name"],
                "description": t["description"],
                "inputSchema": {{"json": t["input_schema"]}},
            }}
        }}
        for t in TOOLS
    ]
}}

TOOL_HANDLERS = {{t["name"]: t["handler"] for t in TOOLS}}


# ── Agent Loop ───────────────────────────────────────────────────────────


def _converse_loop(prompt: str, max_turns: int = 10) -> str:
    """Run a multi-turn Converse API loop with embedded tools."""
    messages = [{{"role": "user", "content": [{{"text": prompt}}]}}]

    for _ in range(max_turns):
        resp = _get_bedrock().converse(
            modelId=MODEL_ID,
            system=[{{"text": SYSTEM_PROMPT}}],
            messages=messages,
            toolConfig=TOOL_CONFIG,
            inferenceConfig={{"maxTokens": 4096}},
        )
        output = resp["output"]["message"]
        messages.append(output)

        if resp["stopReason"] == "tool_use":
            tool_results = []
            for block in output["content"]:
                if "toolUse" in block:
                    tu = block["toolUse"]
                    handler = TOOL_HANDLERS.get(tu["name"])
                    if handler:
                        args = tu["input"]
                        result = handler(**args) if isinstance(args, dict) else handler()
                    else:
                        result = json.dumps({{"error": f"Unknown tool: {{tu['name']}}"}}  )
                    tool_results.append({{
                        "toolResult": {{
                            "toolUseId": tu["toolUseId"],
                            "content": [{{"text": result}}],
                        }}
                    }})
            messages.append({{"role": "user", "content": tool_results}})
        else:
            for block in output["content"]:
                if "text" in block:
                    return block["text"]
            return str(output["content"])

    return "Max tool-use turns reached."


@app.entrypoint
def invoke(payload):
    """Process user prompt through the MCP server agent with embedded tools."""
    message = payload.get("prompt", "Hello")
    response_text = _converse_loop(message)
    return {{"response": response_text}}

if __name__ == "__main__":
    app.run()
'''


def _generate_memory_agent(
    system_prompt: str,
    model_id: str,
    region: str,
    has_gateway: bool = False,
    creds: dict = None,
) -> str:
    """Generate agent with AgentCore Memory integration + optional Gateway tools.

    Uses MemoryClient from bedrock_agentcore.memory to store/retrieve conversation context.
    When has_gateway=True, uses Strands Agent + MCPClient (official pattern) for Gateway tools.
    Without gateway, uses Strands Agent without tools.
    Pattern from: amazon-bedrock-agentcore-samples
    """
    if has_gateway and creds:
        gateway_imports = """from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamablehttp_client"""
        gateway_env = '''
GATEWAY_URL = os.environ.get("GATEWAY_URL", "")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID") or os.environ.get("OAUTH_CLIENT_ID", "")
COGNITO_CLIENT_SECRET = os.environ.get("COGNITO_CLIENT_SECRET") or os.environ.get("OAUTH_CLIENT_SECRET", "")
COGNITO_TOKEN_ENDPOINT = os.environ.get("COGNITO_TOKEN_ENDPOINT") or os.environ.get("OAUTH_TOKEN_ENDPOINT", "")
COGNITO_SCOPE = os.environ.get("COGNITO_SCOPE") or os.environ.get("OAUTH_SCOPE", "")'''
        gateway_functions = '''

def _get_gateway_token():
    if not COGNITO_CLIENT_ID or not COGNITO_TOKEN_ENDPOINT:
        return ""
    try:
        form = {"grant_type": "client_credentials", "client_id": COGNITO_CLIENT_ID,
                "client_secret": COGNITO_CLIENT_SECRET}
        if COGNITO_SCOPE:
            form["scope"] = COGNITO_SCOPE
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(COGNITO_TOKEN_ENDPOINT, data=data,
                                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())["access_token"]
    except Exception as e:
        print(f"Warning: Failed to get gateway token: {e}")
        return ""


def get_full_tools_list(client):
    """Retrieve all tools from MCP client, handling pagination."""
    more_tools = True
    tools = []
    pagination_token = None
    while more_tools:
        tmp_tools = client.list_tools_sync(pagination_token=pagination_token)
        tools.extend(tmp_tools)
        if tmp_tools.pagination_token is None:
            more_tools = False
        else:
            pagination_token = tmp_tools.pagination_token
    return tools


def _create_transport():
    token = _get_gateway_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return streamablehttp_client(GATEWAY_URL, headers=headers)'''
        gateway_init = """

# Lazy init: MCP client + tool discovery (creds may not be ready at module load)
_gateway_tools = None

def _get_gateway_tools():
    global _gateway_tools
    if _gateway_tools is None:
        _gateway_tools = []
        if GATEWAY_URL:
            mcp_client = MCPClient(_create_transport)
            mcp_client.start()
            _gateway_tools = get_full_tools_list(mcp_client)
    return _gateway_tools"""
        agent_tools = "tools=_get_gateway_tools(), "
    else:
        gateway_imports = ""
        gateway_env = ""
        gateway_functions = ""
        gateway_init = ""
        agent_tools = ""

    return f'''"""AgentCore Runtime - Agent with Memory Integration

Uses Strands Agent + BedrockAgentCoreApp SDK + MemoryClient for conversation persistence.
{"Gateway tools via MCPClient (official pattern)." if has_gateway else "No gateway tools."}
"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
import json
import os
import urllib.request
import urllib.parse
{gateway_imports}

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """{system_prompt}"""
MODEL_ID = os.environ.get("MODEL_ID", "{model_id}")
REGION = os.environ.get("AWS_REGION", "{region}")
MEMORY_ID = os.environ.get("MEMORY_ID", "")
{gateway_env}
{gateway_functions}
{gateway_init}

# Lazy init: boto3 clients may not have valid creds at module load time
_model = None
_agent = None

def _get_agent(**extra_kwargs):
    global _model, _agent
    if _agent is None or extra_kwargs:
        if _model is None:
            _model = BedrockModel(model_id=MODEL_ID, region_name=REGION)
        _agent = Agent(model=_model, {agent_tools}system_prompt=SYSTEM_PROMPT, **extra_kwargs)
    return _agent

# Memory client (lazy init)
_memory_client = None

def _get_memory_client():
    global _memory_client
    if _memory_client is None and MEMORY_ID:
        try:
            from bedrock_agentcore.memory import MemoryClient
            _memory_client = MemoryClient(region_name=REGION)
        except ImportError:
            _memory_client = None
    return _memory_client


def _get_recent_context(actor_id, session_id, k=5):
    """Retrieve recent conversation turns from memory."""
    client = _get_memory_client()
    if not client or not MEMORY_ID:
        return ""
    try:
        turns = client.get_last_k_turns(
            memory_id=MEMORY_ID, actor_id=actor_id,
            session_id=session_id, k=k,
        )
        if not turns:
            return ""
        context_lines = []
        for turn in turns:
            if isinstance(turn, list):
                for message in turn:
                    role = message.get("role", "user")
                    content = message.get("content", {{}})
                    text = content.get("text", "") if isinstance(content, dict) else str(content)
                    context_lines.append(f"{{role}}: {{text}}")
            else:
                role = turn.get("role", "user")
                content = turn.get("content", {{}})
                text = content.get("text", "") if isinstance(content, dict) else str(content)
                context_lines.append(f"{{role}}: {{text}}")
        return "\\n".join(context_lines)
    except Exception as e:
        print(f"Warning: Could not retrieve memory: {{e}}")
        return ""


def _save_to_memory(actor_id, session_id, user_msg, assistant_msg):
    """Save conversation turn to memory."""
    client = _get_memory_client()
    if not client or not MEMORY_ID:
        return
    try:
        client.create_event(
            memory_id=MEMORY_ID, actor_id=actor_id,
            session_id=session_id,
            messages=[(user_msg, "USER"), (assistant_msg, "ASSISTANT")],
        )
    except Exception as e:
        print(f"Warning: Could not save to memory: {{e}}")


@app.entrypoint
def invoke(payload):
    """Process user prompt with memory context and optional Gateway tools."""
    message = payload.get("prompt", "Hello")
    session_id = payload.get("session_id", "default")
    actor_id = payload.get("actor_id", "user")

    # Retrieve recent context from memory
    recent_context = _get_recent_context(actor_id, session_id)
    enriched_prompt = message
    if recent_context:
        enriched_prompt = f"Previous conversation context:\\n{{recent_context}}\\n\\nCurrent message: {{message}}"

    # Strands Agent handles tool discovery + calling via MCPClient automatically
    result = _get_agent()(enriched_prompt)
    response_text = str(result)

    # Save to memory
    _save_to_memory(actor_id, session_id, message, response_text)

    return {{"response": response_text}}

if __name__ == "__main__":
    app.run()
'''


def _generate_default_agent(system_prompt: str, model_id: str, region: str) -> str:
    """Generate lightweight agent using BedrockAgentCoreApp + boto3 Converse API."""
    return f'''"""AgentCore Runtime Agent — BedrockAgentCoreApp + boto3 Converse API"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp
import boto3
import json
import os

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """{system_prompt}"""
MODEL_ID = os.environ.get("MODEL_ID", "{model_id}")
REGION = os.environ.get("AWS_REGION", "{region}")

_bedrock = None

def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    return _bedrock

@app.entrypoint
def invoke(payload):
    """Process user prompt through the Bedrock agent."""
    try:
        prompt = payload.get("prompt", "Hello")
        resp = _get_bedrock().converse(
            modelId=MODEL_ID,
            system=[{{"text": SYSTEM_PROMPT}}],
            messages=[{{"role": "user", "content": [{{"text": prompt}}]}}],
            inferenceConfig={{"maxTokens": 2048}},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        return {{"response": text}}
    except Exception as exc:
        return {{"response": f"Error: {{exc}}"}}

if __name__ == "__main__":
    app.run()
'''


# ---------------------------------------------------------------------------
# Strands Model Provider Helpers
# ---------------------------------------------------------------------------


def _get_model_init_code(provider: str, model_id: str, region: str) -> tuple[str, str]:
    """Return (import_statement, model_init_code) for a Strands model provider."""
    # SECURITY: Sanitize model_id and region to prevent code injection via f-string interpolation
    model_id = _sanitize_identifier(model_id)
    if region and not _REGION_PATTERN.match(region):
        region = "us-east-1"
    if provider in ("bedrock", ""):
        return (
            "from strands.models import BedrockModel",
            f'model = BedrockModel(model_id=os.environ.get("MODEL_ID", "{model_id}"), region_name=os.environ.get("AWS_REGION", "{region}"))',
        )
    elif provider == "openai":
        return (
            "from strands.models.openai import OpenAIModel",
            f'model = OpenAIModel(model_id="{model_id}")',
        )
    elif provider == "anthropic":
        return (
            "from strands.models.anthropic import AnthropicModel",
            f'model = AnthropicModel(model_id="{model_id}")',
        )
    elif provider == "gemini":
        return (
            "from strands.models.gemini import GeminiModel",
            f'model = GeminiModel(model_id="{model_id}")',
        )
    elif provider == "litellm":
        return (
            "from strands.models.litellm import LiteLLMModel",
            f'model = LiteLLMModel(model_id="{model_id}")',
        )
    elif provider == "mistral":
        return (
            "from strands.models.mistral import MistralModel",
            f'model = MistralModel(model_id="{model_id}")',
        )
    elif provider == "ollama":
        return (
            "from strands.models.ollama import OllamaModel",
            f'model = OllamaModel(model_id="{model_id}")',
        )
    elif provider == "sagemaker":
        return (
            "from strands.models.sagemaker import SageMakerModel",
            f'model = SageMakerModel(endpoint_name="{model_id}", region_name=os.environ.get("AWS_REGION", "{region}"))',
        )
    elif provider == "groq":
        return (
            "from strands.models.openai import OpenAIModel",
            f'model = OpenAIModel(model_id="{model_id}", client_args={{"api_key": os.environ.get("GROQ_API_KEY", ""), "base_url": "https://api.groq.com/openai/v1"}})',
        )
    elif provider == "deepseek":
        return (
            "from strands.models.openai import OpenAIModel",
            f'model = OpenAIModel(model_id="{model_id}", client_args={{"api_key": os.environ.get("DEEPSEEK_API_KEY", ""), "base_url": "https://api.deepseek.com/v1"}})',
        )
    elif provider == "together":
        return (
            "from strands.models.litellm import LiteLLMModel",
            f'model = LiteLLMModel(model_id="together_ai/{model_id}")',
        )
    elif provider == "writer":
        return (
            "from strands.models.openai import OpenAIModel",
            f'model = OpenAIModel(model_id="{model_id}", client_args={{"api_key": os.environ.get("WRITER_API_KEY", ""), "base_url": "https://api.writer.com/v1"}})',
        )
    # Fallback to Bedrock
    return (
        "from strands.models import BedrockModel",
        f'model = BedrockModel(model_id=os.environ.get("MODEL_ID", "{model_id}"), region_name=os.environ.get("AWS_REGION", "{region}"))',
    )


def _generate_strands_default(system_prompt: str, model_id: str, region: str, provider: str = "bedrock") -> str:
    """Generate a default Strands Agent using the specified model provider.

    Follows the official bedrock-agentcore-starter-toolkit pattern:
    - BedrockAgentCoreApp created at module level
    - Agent created inside invoke() via load_model() helper
    - Entrypoint: def invoke(payload) — sync, single arg
    """
    model_import, model_init = _get_model_init_code(provider, model_id, region)
    return f'''"""AgentCore Runtime Agent — Strands Agent + BedrockAgentCoreApp SDK"""
import os

from strands import Agent
{model_import}
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """{system_prompt}"""

def load_model():
    {model_init}
    return model

@app.entrypoint
def invoke(payload):
    """Handler for agent invocation."""
    agent = Agent(model=load_model(), system_prompt=SYSTEM_PROMPT)
    prompt = payload.get("prompt", "Hello!")
    result = agent(prompt)
    return {{"response": str(result)}}

if __name__ == "__main__":
    app.run()
'''


# ---------------------------------------------------------------------------
# Multi-Agent Pattern Generators
# ---------------------------------------------------------------------------


def _generate_graph_agent(
    system_prompt: str,
    model_id: str,
    region: str,
    provider: str,
    multi_agent_config: dict,
) -> str:
    """Generate Strands Graph multi-agent code using GraphBuilder."""
    agents = multi_agent_config.get("agents", [])
    if not agents:
        # Empty agents list — fall through to standard single-agent
        return _generate_strands_default(system_prompt, model_id, region, provider)
    edges = multi_agent_config.get("edges", [])
    entry_point = _sanitize_agent_id(multi_agent_config.get("entryPoint", agents[0]["agentId"]))
    model_import, _ = _get_model_init_code(provider, model_id, region)

    agent_defs = ""
    for ag in agents:
        ag_id = _sanitize_agent_id(ag["agentId"])
        _, ag_init = _get_model_init_code(ag.get("modelProvider", provider), ag.get("modelId", model_id), region)
        ag_prompt = _escape_triple_quotes(ag.get("systemPrompt", "You are a helpful agent."))
        safe_var = ag_id.replace("-", "_")
        agent_defs += f'''
    {ag_init.replace("model = ", f"model_{safe_var} = ")}
    agent_{safe_var} = Agent(
        model=model_{safe_var},
        system_prompt="""{ag_prompt}""",
    )
'''

    node_adds = ""
    for ag in agents:
        ag_id = _sanitize_agent_id(ag["agentId"])
        safe_var = ag_id.replace("-", "_")
        node_adds += f'    graph.add_node("{ag_id}", agent_{safe_var})\n'

    edge_adds = ""
    for e in edges:
        src = _sanitize_agent_id(e["source"])
        tgt = _sanitize_agent_id(e["target"])
        edge_adds += f'    graph.add_edge("{src}", "{tgt}")\n'

    return f'''"""AgentCore Runtime — Strands Graph Multi-Agent"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.multiagent.graph import GraphBuilder
{model_import}
import os

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """{system_prompt}"""

_graph = None

def _build_graph():
    global _graph
    if _graph is not None:
        return _graph
{agent_defs}
    graph = GraphBuilder()
{node_adds}{edge_adds}    graph.set_entry_point("{entry_point}")
    _graph = graph.build()
    return _graph

@app.entrypoint
def invoke(payload):
    graph = _build_graph()
    prompt = payload.get("prompt", "Hello!")
    result = graph.run(prompt)
    return {{"response": str(result)}}

if __name__ == "__main__":
    app.run()
'''


def _generate_swarm_agent(
    system_prompt: str,
    model_id: str,
    region: str,
    provider: str,
    multi_agent_config: dict,
) -> str:
    """Generate Strands Swarm multi-agent code."""
    agents = multi_agent_config.get("agents", [])
    if not agents:
        return _generate_strands_default(system_prompt, model_id, region, provider)
    model_import, _ = _get_model_init_code(provider, model_id, region)

    agent_defs = ""
    agent_list_items = []
    for ag in agents:
        ag_id = _sanitize_agent_id(ag["agentId"])
        _, ag_init = _get_model_init_code(ag.get("modelProvider", provider), ag.get("modelId", model_id), region)
        ag_prompt = _escape_triple_quotes(ag.get("systemPrompt", "You are a helpful agent."))
        safe = ag_id.replace("-", "_")
        agent_defs += f'''
    {ag_init.replace("model = ", f"model_{safe} = ")}
    agent_{safe} = Agent(
        model=model_{safe},
        system_prompt="""{ag_prompt}""",
    )
'''
        agent_list_items.append(f"agent_{safe}")

    agents_list = ", ".join(agent_list_items)

    return f'''"""AgentCore Runtime — Strands Swarm Multi-Agent"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.multiagent.swarm import Swarm
{model_import}
import os

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """{system_prompt}"""

_swarm = None

def _build_swarm():
    global _swarm
    if _swarm is not None:
        return _swarm
{agent_defs}
    _swarm = Swarm(agents=[{agents_list}])
    return _swarm

@app.entrypoint
def invoke(payload):
    swarm = _build_swarm()
    prompt = payload.get("prompt", "Hello!")
    result = swarm.execute(prompt)
    return {{"response": str(result)}}

if __name__ == "__main__":
    app.run()
'''


def _generate_workflow_agent(
    system_prompt: str,
    model_id: str,
    region: str,
    provider: str,
    multi_agent_config: dict,
) -> str:
    """Generate Strands Workflow (DAG) multi-agent code with sequential steps."""
    agents = multi_agent_config.get("agents", [])
    steps = multi_agent_config.get("steps", [])
    model_import, _ = _get_model_init_code(provider, model_id, region)

    # Build agent definitions
    agent_defs = ""
    for ag in agents:
        ag_id = _sanitize_agent_id(ag["agentId"])
        _, ag_init = _get_model_init_code(ag.get("modelProvider", provider), ag.get("modelId", model_id), region)
        ag_prompt = _escape_triple_quotes(ag.get("systemPrompt", "You are a helpful agent."))
        safe = ag_id.replace("-", "_")
        agent_defs += f'''
    {ag_init.replace("model = ", f"model_{safe} = ")}
    agents["{ag_id}"] = Agent(
        model=model_{safe},
        system_prompt="""{ag_prompt}""",
    )
'''

    # Build step execution
    step_code = ""
    for i, step in enumerate(steps):
        agent_ids = [_sanitize_agent_id(aid) for aid in step.get("agentIds", [])]
        if len(agent_ids) == 1:
            step_code += f'''
    # Step {i + 1}
    result = str(agents["{agent_ids[0]}"](current_input))
    current_input = result
'''
        elif len(agent_ids) > 1:
            ids_str = ", ".join(f'"{aid}"' for aid in agent_ids)
            step_code += f"""
    # Step {i + 1} (parallel)
    import concurrent.futures
    step_agents = [{ids_str}]
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {{aid: executor.submit(lambda a, inp: str(agents[a](inp)), aid, current_input) for aid in step_agents}}
        results = {{aid: f.result() for aid, f in futures.items()}}
    current_input = "\\n".join(f"[{{aid}}]: {{r}}" for aid, r in results.items())
"""

    if not step_code:
        # If no steps defined, run agents sequentially
        step_code = """
    for agent_id, agent in agents.items():
        result = str(agent(current_input))
        current_input = result
"""

    return f'''"""AgentCore Runtime — Strands Workflow (DAG) Multi-Agent"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
{model_import}
import os

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """{system_prompt}"""

_agents = None

def _build_agents():
    global _agents
    if _agents is not None:
        return _agents
    agents = {{}}
{agent_defs}
    _agents = agents
    return _agents

@app.entrypoint
def invoke(payload):
    agents = _build_agents()
    current_input = payload.get("prompt", "Hello!")
{step_code}
    return {{"response": current_input}}

if __name__ == "__main__":
    app.run()
'''


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_BROWSER_GUIDANCE = """

BROWSER TOOL GUIDELINES:
- When clicking elements, always use the most specific selector possible (prefer text content, role, or test-id over generic tag selectors).
- If a click fails because the element is not visible, scroll to it first or try an alternative visible selector.
- Many sites render duplicate links for responsive layouts. If a selector matches multiple elements, prefer using :visible pseudo-class, nth-match, or filter by visibility.
- Prefer page.getByRole(), page.getByText(), or page.locator('selector').first over broad CSS selectors.
- Before clicking a link, verify it is visible on the page. If not, scroll down or look for an alternative element.
- When navigating pages, wait for page loads to complete before interacting with elements.
- If an action times out, retry with a different strategy (e.g., scroll into view, use a different selector, or navigate directly via URL instead of clicking)."""


def _inject_guardrails(code: str) -> str:
    """Post-process generated code to add guardrail support via env vars.

    Injects ``GUARDRAIL_ID`` / ``GUARDRAIL_VERSION`` env-var reading and
    passes ``guardrail_config`` to any Strands ``BedrockModel`` constructor,
    or ``guardrailConfig`` to boto3 ``converse()`` calls.

    The injection is string-based to keep generation functions simple.
    """
    guardrail_env_block = (
        '\n# Guardrails configuration (injected by AgentCore Flows)\n'
        'GUARDRAIL_ID = os.environ.get("GUARDRAIL_ID", "")\n'
        'GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION", "")\n'
        '_guardrail_config = {"guardrailIdentifier": GUARDRAIL_ID, "guardrailVersion": GUARDRAIL_VERSION} if GUARDRAIL_ID else None\n'
    )

    # Inject env vars after the last top-level import or constant.
    # Find the best insertion point: after MODEL_ID or SYSTEM_PROMPT.
    #
    # For SYSTEM_PROMPT we must handle both single-line and multi-line
    # triple-quoted strings:
    #   SYSTEM_PROMPT = """short prompt"""           (single-line)
    #   SYSTEM_PROMPT = """long\nmultiline\n"""      (multi-line)
    for marker in ['MODEL_ID = os.environ', 'SYSTEM_PROMPT = """']:
        idx = code.find(marker)
        if idx >= 0:
            # Find end of that line
            eol = code.find('\n', idx)
            if eol >= 0:
                # For SYSTEM_PROMPT, find the CLOSING triple-quote.
                if 'SYSTEM_PROMPT' in marker:
                    # Position right after the opening """
                    open_tq = code.find('"""', idx)
                    after_open = open_tq + 3
                    # Search for closing """ starting right after the opening
                    close_idx = code.find('"""', after_open)
                    if close_idx >= 0:
                        # eol = end of the line containing the closing """
                        eol = code.find('\n', close_idx)
                code = code[:eol + 1] + guardrail_env_block + code[eol + 1:]
                break

    # Inject into Strands BedrockModel: add guardrail_config parameter
    if 'BedrockModel(' in code:
        code = code.replace(
            'BedrockModel(model_id=MODEL_ID, region_name=REGION)',
            'BedrockModel(model_id=MODEL_ID, region_name=REGION, guardrail_config=_guardrail_config)',
        )
        code = code.replace(
            'BedrockModel(model_id=MODEL_ID',
            'BedrockModel(model_id=MODEL_ID, guardrail_config=_guardrail_config' if 'guardrail_config' not in code else 'BedrockModel(model_id=MODEL_ID',
        )

    # Inject into boto3 converse() calls: add guardrailConfig parameter
    if '.converse(' in code and 'guardrailConfig' not in code:
        code = code.replace(
            'toolConfig=TOOL_CONFIG,',
            'toolConfig=TOOL_CONFIG,\n            **({{"guardrailConfig": {{"guardrailIdentifier": GUARDRAIL_ID, "guardrailVersion": GUARDRAIL_VERSION}}}} if GUARDRAIL_ID else {{}}),',
        )

    return code


def generate_agent_code(
    config: RuntimeConfig,
    tools: Optional[list] = None,
    gateway_config: Optional[dict] = None,
    template_id: Optional[str] = None,
    gateway_tools: Optional[list] = None,
    custom_tools: Optional[list[dict]] = None,
    portable: bool = False,
) -> str:
    """Generate agent Python code for the given configuration.

    Args:
        config: Runtime configuration from the frontend.
        tools: List of connected tool IDs (e.g. ``["browser", "gateway"]``).
        gateway_config: Gateway deployment result dict with ``gateway_url``, ``client_info``.
        template_id: Optional template identifier for template-specific code.
        gateway_tools: Tool IDs connected to the gateway node.
        custom_tools: AI-generated custom tool definitions (name, description, schema).
        portable: When True, generate code with empty credential defaults so all
            config comes from environment variables at deploy time. Used for
            CloudFormation template generation.

    Returns:
        Generated Python source code as a string.

    Raises:
        ValueError: (deprecated — no longer raised for framework validation).

    Requirements: 5.1, 5.6
    """
    # Portable mode: force empty credentials so generated code relies entirely
    # on environment variables (injected by CloudFormation at deploy time).
    if portable:
        gateway_config = None
    # Framework validation — Strands only (accept any value for backward compat)
    provider = getattr(config, "model_provider", "bedrock") or "bedrock"

    model_id = _get_model_id(config)
    system_prompt = _escape_triple_quotes(config.system_prompt)
    region = _get_region()
    tools = tools or []
    gateway_tools = gateway_tools or []
    custom_tools = custom_tools or []

    # Inject custom tool descriptions so the agent knows what's available via Gateway
    if custom_tools:
        tool_descs = []
        for ct in custom_tools[:10]:
            name = ct.get("toolName", ct.get("tool_name", "unknown"))
            desc = ct.get("description", "")
            tool_descs.append(f"- {name}: {desc}")
        system_prompt += (
            "\n\nYou have access to the following custom tools via the Gateway. "
            "Use them when relevant to the user's request:\n" + "\n".join(tool_descs)
        )

    # For tool-using templates, append a directive to ensure the agent actually
    # calls tools instead of just describing them.
    _TOOL_USE_TEMPLATES = {
        "mcp-server-gateway-target",
        "strands-gateway-agent",
        "customer-support-assistant",
        "customer-support-blueprint",
        "mcp-server-runtime",
    }
    if template_id in _TOOL_USE_TEMPLATES or custom_tools:
        system_prompt += (
            "\n\nIMPORTANT: When the user asks about topics your tools can handle, "
            "ALWAYS call the appropriate tools to get real data. Never just list or "
            "describe your tools — use them to answer the question directly."
        )

    # Check guardrails early so inner helper can reference it
    has_guardrails = "guardrails" in tools

    # Helper to apply guardrails post-processing if connected
    def _maybe_inject_guardrails(code: str) -> str:
        if has_guardrails:
            return _inject_guardrails(code)
        return code

    # Template-specific code generation
    if template_id == "web-search-agent":
        return _maybe_inject_guardrails(_generate_langchain_web_search(system_prompt, model_id, region))

    if template_id == "strands-gateway-agent":
        creds = _extract_gateway_credentials(gateway_config)
        return _maybe_inject_guardrails(_generate_strands_gateway(system_prompt, model_id, creds))

    if template_id == "mcp-server-runtime":
        return _maybe_inject_guardrails(_generate_mcp_server_runtime(system_prompt, model_id, region))

    if template_id == "mcp-server-gateway-target":
        creds = _extract_gateway_credentials(gateway_config)
        return _maybe_inject_guardrails(_generate_strands_gateway(system_prompt, model_id, creds))

    if template_id == "customer-support-assistant":
        creds = _extract_gateway_credentials(gateway_config)
        return _maybe_inject_guardrails(_generate_customer_support(system_prompt, model_id, creds))

    if template_id == "customer-support-blueprint":
        creds = _extract_gateway_credentials(gateway_config)
        return _maybe_inject_guardrails(_generate_customer_support(system_prompt, model_id, creds))

    # Determine connected tools
    has_browser = "browser" in tools
    has_code_interpreter = "code_interpreter" in tools
    has_gateway = "gateway" in tools and (gateway_config or portable)
    has_memory = "memory" in tools

    # Inject browser guidance into system prompt when browser tool is connected
    if has_browser:
        system_prompt = system_prompt + _BROWSER_GUIDANCE

    # Multi-agent pattern routing
    multi_agent_pattern = getattr(config, "multi_agent_pattern", "none") or "none"
    multi_agent_config_data = getattr(config, "multi_agent_config", None)
    if multi_agent_pattern != "none" and multi_agent_config_data:
        if multi_agent_pattern == "graph":
            return _maybe_inject_guardrails(_generate_graph_agent(system_prompt, model_id, region, provider, multi_agent_config_data))
        elif multi_agent_pattern == "swarm":
            return _maybe_inject_guardrails(_generate_swarm_agent(system_prompt, model_id, region, provider, multi_agent_config_data))
        elif multi_agent_pattern == "workflow":
            return _maybe_inject_guardrails(_generate_workflow_agent(system_prompt, model_id, region, provider, multi_agent_config_data))

    # Memory-connected agent (with optional gateway)
    if has_memory:
        if has_gateway:
            creds = _extract_gateway_credentials(gateway_config)
            return _maybe_inject_guardrails(_generate_memory_agent(system_prompt, model_id, region, has_gateway=True, creds=creds))
        return _maybe_inject_guardrails(_generate_memory_agent(system_prompt, model_id, region))

    # Gateway-connected agent
    if has_gateway:
        creds = _extract_gateway_credentials(gateway_config)
        return _maybe_inject_guardrails(_generate_gateway_agent(system_prompt, model_id, creds))

    # Built-in tools agent (falls back to default Converse agent)
    if has_browser or has_code_interpreter:
        return _maybe_inject_guardrails(_generate_tools_agent(system_prompt, model_id, region, has_browser, has_code_interpreter))

    # Default Strands agent with provider-aware model
    return _maybe_inject_guardrails(_generate_strands_default(system_prompt, model_id, region, provider))


def generate_requirements(
    config: RuntimeConfig,
    tools: Optional[list] = None,
    template_id: Optional[str] = None,
    gateway_tools: Optional[list] = None,
) -> str:
    """Generate requirements.txt content for the given configuration.

    Returns empty string — the AgentCore Runtime does NOT install from
    requirements.txt. All dependencies are pre-bundled into code.zip
    via S3 dependency bundles (base.zip or strands-mcp.zip).

    Requirements: 6.1, 6.2
    """
    return ""
