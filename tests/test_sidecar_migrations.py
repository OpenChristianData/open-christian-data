"""Tests for build.lib.sidecar_migrations.

A1 ships the chain mechanism; no production migrations are registered yet (the
current schema is 1.0.0). The chain-equivalence test exercises the mechanism via
hand-crafted 1.0 -> 1.1 -> 1.2 fixture migrations so the walker, registry
validation, and skip-raises behaviour are real, not theoretical.
"""

from __future__ import annotations

import pytest

from build.lib import sidecar_migrations as sm


def test_is_single_step_accepts_consecutive_bumps():
    assert sm.is_single_step("1.0.0", "1.0.1")
    assert sm.is_single_step("1.0.0", "1.1.0")
    assert sm.is_single_step("1.0.0", "2.0.0")
    assert sm.is_single_step("1.4.3", "1.5.0")
    assert sm.is_single_step("3.2.7", "3.2.8")


def test_is_single_step_rejects_skips_and_same():
    assert not sm.is_single_step("1.0.0", "1.0.2")
    assert not sm.is_single_step("1.0.0", "1.2.0")
    assert not sm.is_single_step("1.0.0", "1.0.0")
    assert not sm.is_single_step("1.4.0", "1.4.5")
    # Bumping major must reset minor and patch.
    assert not sm.is_single_step("1.4.3", "2.0.1")
    # Bumping minor must reset patch.
    assert not sm.is_single_step("1.4.3", "1.5.1")


def test_chain_no_op_when_versions_equal():
    assert sm.chain("1.0.0", "1.0.0") == []


def test_chain_raises_when_no_path():
    with pytest.raises(sm.MigrationError):
        sm.chain("1.0.0", "1.1.0", migrations={})


def test_chain_equivalence_walks_single_steps_in_order():
    # Synthetic registry: 1.0.0 -> 1.1.0 -> 1.2.0
    def step_1_0_to_1_1(payload):
        out = dict(payload)
        out["touched_by"] = (out.get("touched_by", []) or []) + ["v1.1.0"]
        return out

    def step_1_1_to_1_2(payload):
        out = dict(payload)
        out["touched_by"] = (out.get("touched_by", []) or []) + ["v1.2.0"]
        return out

    migrations = {
        ("1.0.0", "1.1.0"): step_1_0_to_1_1,
        ("1.1.0", "1.2.0"): step_1_1_to_1_2,
    }
    edges = sm.chain("1.0.0", "1.2.0", migrations=migrations)
    assert edges == [("1.0.0", "1.1.0"), ("1.1.0", "1.2.0")]


def test_chain_rejects_skip_step_in_registry():
    def skip(payload):
        return dict(payload)

    migrations = {("1.0.0", "1.2.0"): skip}
    with pytest.raises(sm.MigrationError):
        sm.chain("1.0.0", "1.2.0", migrations=migrations)


def test_upgrade_chains_steps_and_marks_schema_version():
    def step_1_0_to_1_1(payload):
        out = dict(payload)
        out["touched_by"] = ["v1.1.0"]
        return out

    def step_1_1_to_1_2(payload):
        out = dict(payload)
        out["touched_by"] = list(out.get("touched_by", []) or []) + ["v1.2.0"]
        return out

    migrations = {
        ("1.0.0", "1.1.0"): step_1_0_to_1_1,
        ("1.1.0", "1.2.0"): step_1_1_to_1_2,
    }
    sidecar = {"schema_version": "1.0.0", "entries": {}}
    result = sm.upgrade(sidecar, target_version="1.2.0", migrations=migrations)
    assert result["schema_version"] == "1.2.0"
    assert result["touched_by"] == ["v1.1.0", "v1.2.0"]
    assert result["entries"] == {}


def test_upgrade_no_op_when_already_current():
    sidecar = {"schema_version": "1.0.0", "entries": {}}
    out = sm.upgrade(sidecar, target_version="1.0.0", migrations={})
    assert out == sidecar
    # Should be a copy, not the same object.
    assert out is not sidecar


def test_upgrade_rejects_downgrade():
    sidecar = {"schema_version": "1.2.0"}
    with pytest.raises(sm.MigrationError):
        sm.upgrade(sidecar, target_version="1.0.0", migrations={})


def test_upgrade_raises_when_schema_version_missing():
    with pytest.raises(sm.MigrationError):
        sm.upgrade({}, target_version="1.0.0", migrations={})


def test_current_version_constant_matches_schema_constant():
    # Spec: A1 ships review_state at 1.0.0. If this assert breaks, the migration
    # constant and the on-disk schema have drifted.
    assert sm.CURRENT_VERSION == "1.0.0"


def test_production_registry_is_empty_at_a1():
    # At A1 there are no successor versions; the registry must stay empty so the
    # chain-equivalence test only exercises injected migrations. Adding a real
    # migration is a deliberate act that also requires updating CURRENT_VERSION
    # and bumping schemas/v1/review_state.schema.json.
    assert sm.MIGRATIONS == {}
