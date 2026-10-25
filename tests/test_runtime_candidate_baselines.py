"""Explicit runtime identity refreshes conserve all provenance and accounting fields."""
import json
import pytest
from tests.runtime_candidate_baselines import _assert_runtime_member

OLD, CURRENT = "a" * 64, "b" * 64


def _record(digest, **changes):
    return json.dumps(dict(source_manifest_sha256=digest, text="retained text",
                           positions=[1, 3, 8], members=[{"path": "raw/source", "sha256": "c" * 64}],
                           **changes)).encode()


@pytest.mark.parametrize("name", ["provenance.json", "source-accountability.json"])
def test_only_explicit_manifest_identity_may_change(name):
    _assert_runtime_member(name, _record(CURRENT), _record(OLD), original_sha256=OLD, runtime_sha256=CURRENT)


@pytest.mark.parametrize("field,value", [("text", "changed text"), ("positions", [1, 2, 8]),
                                         ("members", [{"path": "raw/other", "sha256": "c" * 64}])])
def test_runtime_identity_refresh_rejects_source_or_position_changes(field, value):
    after = json.loads(_record(CURRENT)); after[field] = value
    with pytest.raises(AssertionError):
        _assert_runtime_member("source-accountability.json", json.dumps(after).encode(), _record(OLD),
                               original_sha256=OLD, runtime_sha256=CURRENT)


@pytest.mark.parametrize("name,old,current", [("unresolved.jsonl", OLD, CURRENT),
                                               ("provenance.json", "d" * 64, CURRENT),
                                               ("source-accountability.json", OLD, "d" * 64)])
def test_unbound_runtime_refresh_is_rejected(name, old, current):
    with pytest.raises(AssertionError):
        _assert_runtime_member(name, _record(CURRENT), _record(OLD), original_sha256=old, runtime_sha256=current)


def test_unchanged_non_json_member_keeps_exact_bytes():
    _assert_runtime_member("content.tei.xml", b"<TEI/>", b"<TEI/>", original_sha256=OLD, runtime_sha256=CURRENT)
