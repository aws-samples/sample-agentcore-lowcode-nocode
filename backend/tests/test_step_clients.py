"""Phase 7 wiring: the per-deploy client factory (services/step_clients.py).

The critical property: with NO target on the event, the factory returns a
default-session client in the home region — byte-for-byte the previous behavior.
With a target, it delegates to deploy_target.session_for_target.
"""

from __future__ import annotations

import boto3
import pytest

from app.services import step_clients as sc


def test_no_target_returns_home_region(monkeypatch):
    monkeypatch.setenv("APP_AWS_REGION", "us-east-1")
    monkeypatch.delenv("DEPLOY_TARGETS_ENABLED", raising=False)
    session = sc.session_for_event({})
    assert isinstance(session, boto3.Session)
    assert session.region_name == "us-east-1"


def test_event_region_overrides_home(monkeypatch):
    monkeypatch.setenv("APP_AWS_REGION", "us-east-1")
    session = sc.session_for_event({"target_region": "eu-west-1"})
    assert session.region_name == "eu-west-1"


def test_none_event_is_safe(monkeypatch):
    monkeypatch.setenv("APP_AWS_REGION", "us-east-1")
    session = sc.session_for_event(None)
    assert session.region_name == "us-east-1"


def test_client_is_default_session_when_no_target(monkeypatch):
    monkeypatch.setenv("APP_AWS_REGION", "us-east-1")
    c = sc.client({}, "s3")
    # A real boto3 s3 client (no assume-role happened).
    assert c.meta.service_model.service_name == "s3"


def test_target_account_delegates_to_deploy_target(monkeypatch):
    # When a target account is present, the factory MUST route through
    # deploy_target.session_for_target (which enforces the gate + landed check).
    called = {}

    def _fake_session_for_target(account_id=None, region=None):
        called["account_id"] = account_id
        called["region"] = region
        return boto3.Session(region_name=region or "us-east-1")

    monkeypatch.setattr(
        "app.services.deploy_target.session_for_target", _fake_session_for_target
    )
    sc.session_for_event({"target_account_id": "986177197847", "target_region": "us-east-1"})
    assert called == {"account_id": "986177197847", "region": "us-east-1"}


def test_target_disabled_raises(monkeypatch):
    # A target on the event but the feature disabled → TargetError bubbles up
    # (deploy must fail loudly, not silently fall back to home).
    monkeypatch.setenv("APP_AWS_REGION", "us-east-1")
    monkeypatch.delenv("DEPLOY_TARGETS_ENABLED", raising=False)
    monkeypatch.setenv("TAG_POLICY_TABLE_NAME", "does-not-exist-table")
    from app.services.deploy_target import TargetError

    with pytest.raises(TargetError):
        sc.session_for_event({"target_account_id": "986177197847"})
