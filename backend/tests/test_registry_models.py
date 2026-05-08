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
