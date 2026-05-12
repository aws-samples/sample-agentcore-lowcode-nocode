"""Registry model unit tests (Task 13) — no network."""

from __future__ import annotations

import pytest

from app.models.registry_models import (
    A2AAgentCardDescriptor,
    A2ADescriptor,
    AgentSkillDefinitionDescriptor,
    AgentSkillMdDescriptor,
    AgentSkillsDescriptor,
    CustomDescriptor,
    McpDescriptor,
    McpServerDescriptor,
    RecordCreateRequest,
    RegistryRecordDescriptors,
    RegistryRecordDescriptorType,
    RegistrySetupRequest,
)


def test_registry_setup_name_rules() -> None:
    with pytest.raises(ValueError):
        RegistrySetupRequest(name="1bad")
    ok = RegistrySetupRequest(name="team_platform_agents")
    assert ok.auto_approval is False


def test_record_create_valid_mcp() -> None:
    req = RecordCreateRequest(
        registry_id="r1",
        name="payment_tool",
        descriptor_type=RegistryRecordDescriptorType.MCP,
        descriptors=RegistryRecordDescriptors(
            mcp=McpDescriptor(server=McpServerDescriptor(inline_content='{"x":1}'))
        ),
    )
    api = req.descriptors.to_api(req.descriptor_type)
    assert "mcp" in api
    assert api["mcp"]["server"]["inlineContent"] == '{"x":1}'


def test_record_create_valid_a2a() -> None:
    req = RecordCreateRequest(
        registry_id="r1",
        name="booking_agent",
        descriptor_type=RegistryRecordDescriptorType.A2A,
        descriptors=RegistryRecordDescriptors(
            a2a=A2ADescriptor(
                agent_card=A2AAgentCardDescriptor(inline_content='{"name":"x"}')
            )
        ),
    )
    api = req.descriptors.to_api(req.descriptor_type)
    assert api["a2a"]["agentCard"]["inlineContent"] == '{"name":"x"}'


def test_record_create_valid_custom() -> None:
    req = RecordCreateRequest(
        registry_id="r1",
        name="internal_api",
        descriptor_type=RegistryRecordDescriptorType.CUSTOM,
        descriptors=RegistryRecordDescriptors(
            custom=CustomDescriptor(inline_content='{"k":"v"}')
        ),
    )
    api = req.descriptors.to_api(req.descriptor_type)
    assert api["custom"]["inlineContent"] == '{"k":"v"}'


def test_record_create_agent_skills() -> None:
    req = RecordCreateRequest(
        registry_id="r1",
        name="data_tools",
        descriptor_type=RegistryRecordDescriptorType.AGENT_SKILLS,
        descriptors=RegistryRecordDescriptors(
            agent_skills=AgentSkillsDescriptor(
                skill_md=AgentSkillMdDescriptor(inline_content="# Title"),
                skill_definition=AgentSkillDefinitionDescriptor(inline_content='{"s":1}'),
            )
        ),
    )
    api = req.descriptors.to_api(req.descriptor_type)
    assert "skillMd" in api["agentSkills"]
    assert "skillDefinition" in api["agentSkills"]


def test_record_descriptor_type_mismatch_errors() -> None:
    req = RecordCreateRequest(
        registry_id="r1",
        name="x",
        descriptor_type=RegistryRecordDescriptorType.MCP,
        descriptors=RegistryRecordDescriptors(
            custom=CustomDescriptor(inline_content="{}")
            # note: no mcp section, yet descriptor_type == MCP
        ),
    )
    with pytest.raises(ValueError):
        req.descriptors.to_api(req.descriptor_type)


def test_record_name_rules() -> None:
    with pytest.raises(ValueError):
        RecordCreateRequest(
            registry_id="r1",
            name="123bad",
            descriptor_type=RegistryRecordDescriptorType.CUSTOM,
            descriptors=RegistryRecordDescriptors(
                custom=CustomDescriptor(inline_content="{}")
            ),
        )


def test_sync_from_url_rejects_http() -> None:
    with pytest.raises(ValueError):
        RecordCreateRequest(
            registry_id="r1",
            name="http_sync",
            descriptor_type=RegistryRecordDescriptorType.MCP,
            sync_from_url="http://example.com/mcp",
        )


def test_sync_from_url_rejects_imds() -> None:
    with pytest.raises(ValueError):
        RecordCreateRequest(
            registry_id="r1",
            name="imds_sync",
            descriptor_type=RegistryRecordDescriptorType.MCP,
            sync_from_url="https://169.254.169.254/latest/meta-data/",
        )


def test_sync_from_url_rejects_rfc1918() -> None:
    for h in ("https://10.0.0.1/x", "https://192.168.1.1/x", "https://172.16.0.1/x"):
        with pytest.raises(ValueError):
            RecordCreateRequest(
                registry_id="r1",
                name="rfc1918_test",
                descriptor_type=RegistryRecordDescriptorType.MCP,
                sync_from_url=h,
            )


def test_sync_from_url_accepts_https_public() -> None:
    req = RecordCreateRequest(
        registry_id="r1",
        name="good_sync",
        descriptor_type=RegistryRecordDescriptorType.MCP,
        sync_from_url="https://api.example.com/mcp",
    )
    assert req.sync_from_url == "https://api.example.com/mcp"


def test_normalise_record_name() -> None:
    from app.services.registry_service import _normalise_record_name

    # Invalid chars are replaced with underscore
    assert _normalise_record_name("My Cool Tool!") == "My_Cool_Tool"
    # Digit-start gets a prefix so it matches the AWS rule
    assert _normalise_record_name("123abc") == "r_123abc"
    # Empty becomes a safe default
    assert _normalise_record_name("") == "record"
    # Already valid passes through
    assert _normalise_record_name("ToolX") == "ToolX"


def test_auto_publish_request_source_type_enum() -> None:
    from app.models.registry_models import AutoPublishRequest, AutoPublishSourceType

    req = AutoPublishRequest(
        source_type=AutoPublishSourceType.HARNESS,
        source_id="harness-abc",
        registry_id="reg-1",
    )
    assert req.source_type is AutoPublishSourceType.HARNESS
    assert req.submit_for_approval is False


def test_auto_publish_tool_builds_mcp_tools_list() -> None:
    """Tool auto-publish emits a JSON-RPC tools/list payload."""
    import json
    from unittest.mock import MagicMock

    from app.models.registry_models import RecordSummary
    from app.services.registry_service import RegistryService

    svc = RegistryService.__new__(RegistryService)
    svc._client = MagicMock()  # type: ignore
    svc._ownership = MagicMock()  # type: ignore
    captured: dict = {}

    def _fake_create(user_id: str, email: str, req) -> RecordSummary:
        captured["req"] = req
        return RecordSummary(
            registry_id="reg-1",
            registry_arn="arn:reg",
            record_id="rec-1",
            record_arn="arn:rec",
            name=req.name,
            description=req.description,
            descriptor_type=req.descriptor_type.value,
            status="DRAFT",
        )

    svc.create_record = _fake_create  # type: ignore

    rec = svc.auto_publish_for_tool(
        "u1",
        "u1@example.com",
        "reg-1",
        {
            "display_name": "Weather Lookup!",
            "description": "Get current weather",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        },
    )
    assert rec is not None
    assert captured["req"].name == "Weather_Lookup"  # normalised
    # Live-tested: AWS's 2025-12-11 MCP schema is private, so auto-publish
    # emits a CUSTOM record whose inline_content IS a JSON-RPC tools/list.
    assert captured["req"].descriptor_type.value == "CUSTOM"
    inline = json.loads(captured["req"].descriptors.custom.inline_content)
    assert inline["resource_type"] == "mcp_tool"
    assert (
        inline["tools_list"]["result"]["tools"][0]["name"] == "Weather_Lookup"
    )
    assert (
        inline["tools_list"]["result"]["tools"][0]["inputSchema"]["properties"][
            "city"
        ]["type"]
        == "string"
    )
