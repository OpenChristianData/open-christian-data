"""Focused mutations of the existing LIB-061 candidate provenance contract."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from build.tei.church_fathers_oracle import _verify_provenance_source_bindings


@pytest.fixture
def bound_provenance(tmp_path):
    envelope = tmp_path / "source-member-equality.json"
    envelope.write_bytes(b'{"members":[]}\n')
    member = {"name": "one", "path": "raw/one.toml", "bytes": 3, "sha256": "a" * 64}
    encoded = json.dumps(
        {"contract": "ocd-source-member-set-v1", "members": [member]},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode() + b"\n"
    digest = hashlib.sha256(encoded).hexdigest()
    envelope_digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    manifest = SimpleNamespace(
        sha256="b" * 64,
        record={"authorities": [{**member, "role": "primary-source"}]},
        authority_path=lambda name: envelope,
    )
    provenance = {
        "source_manifest_sha256": manifest.sha256,
        "source_envelope": {"sha256": envelope_digest, "primary_member_set_sha256": digest},
        "authorities": {
            "primary_source_member_count": 1,
            "primary_source_member_set_sha256": digest,
            "source_member_equality_sha256": envelope_digest,
        },
    }
    return manifest, provenance


def test_exact_bindings_pass(bound_provenance):
    _verify_provenance_source_bindings(*bound_provenance)


@pytest.mark.parametrize("section,field", [
    (None, "source_manifest_sha256"),
    ("source_envelope", "sha256"),
    ("source_envelope", "primary_member_set_sha256"),
    ("authorities", "primary_source_member_count"),
    ("authorities", "primary_source_member_set_sha256"),
    ("authorities", "source_member_equality_sha256"),
])
@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_substituted_binding_rejected(bound_provenance, section, field, missing):
    manifest, original = bound_provenance
    provenance = copy.deepcopy(original)
    target = provenance if section is None else provenance[section]
    if missing:
        del target[field]
    else:
        target[field] = "wrong"
    with pytest.raises(ValueError, match="binding"):
        _verify_provenance_source_bindings(manifest, provenance)


@pytest.mark.parametrize("field,value", [("path", "raw/other.toml"), ("sha256", "c" * 64), ("bytes", 4), ("name", "other")])
def test_member_identity_mutation_rejected(bound_provenance, field, value):
    manifest, provenance = bound_provenance
    manifest.record["authorities"][0][field] = value
    with pytest.raises(ValueError, match="primary_member_set_sha256"):
        _verify_provenance_source_bindings(manifest, provenance)


@pytest.mark.parametrize("section", ["source_envelope", "authorities"])
@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_malformed_binding_section_rejected(bound_provenance, section, value):
    manifest, provenance = bound_provenance
    provenance[section] = value
    with pytest.raises(ValueError, match="bindings missing"):
        _verify_provenance_source_bindings(manifest, provenance)


@pytest.mark.parametrize("add", [False, True])
def test_changed_member_set_rejected(bound_provenance, add):
    manifest, provenance = bound_provenance
    members = manifest.record["authorities"]
    if add:
        members.append({**members[0], "name": "two", "path": "raw/two.toml"})
    else:
        members.clear()
    with pytest.raises(ValueError, match="primary_member_set_sha256"):
        _verify_provenance_source_bindings(manifest, provenance)


def test_changed_equality_envelope_rejected(bound_provenance):
    manifest, provenance = bound_provenance
    manifest.authority_path("source-member-equality").write_bytes(b"changed")
    with pytest.raises(ValueError, match="source_envelope.sha256"):
        _verify_provenance_source_bindings(manifest, provenance)


def test_boolean_is_not_a_member_count(bound_provenance):
    manifest, provenance = bound_provenance
    provenance["authorities"]["primary_source_member_count"] = True
    with pytest.raises(ValueError, match="primary_source_member_count"):
        _verify_provenance_source_bindings(manifest, provenance)
