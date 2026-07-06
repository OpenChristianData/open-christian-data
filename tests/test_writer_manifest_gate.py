"""Tests for the A1 writer-manifest pre-commit gate (block case only).

The allow case lands in A2 with the first parser-emitted manifest. A1 ships
two blocking shapes:

  1. A staged data/ edit with no paired writer manifest.
  2. A staged manifest whose writer_identity is not in the build/lib/
     writer_identities allowlist (the forgery shape).

The gate has no allow path while writer_identities is empty -- by design.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools import check_writer_manifest_gate as gate  # noqa: E402


def _manifest(writer_identity: str = "ia_schaff_herzog_parser", data_paths=None) -> dict:
    return {
        "schema_version": "1.0.0",
        "writer": "parser",
        "writer_version": "build/parsers/ia_schaff_herzog.py@v1.0.0",
        "writer_identity": writer_identity,
        "run_id": "test-run",
        "started_at": "2026-05-12T10:00:00+00:00",
        "data_paths": list(data_paths or ["data/reference/schaff-herzog-encyclopedia.json"]),
        "checksums": {
            (data_paths[0] if data_paths else "data/reference/schaff-herzog-encyclopedia.json"): {
                "before_sha256": "a" * 64,
                "after_sha256": "b" * 64,
            }
        },
        "expected_delta_counts": {
            (data_paths[0] if data_paths else "data/reference/schaff-herzog-encyclopedia.json"): {
                "entries_changed": 1,
                "fields_changed": 1,
            }
        },
        "allowed_field_paths": ["/data/*/layers/*/display"],
        "partial_completion_policy": "all_or_nothing",
        "renames": [],
    }


def test_no_data_edits_passes_through():
    rc, messages = gate.evaluate_gate(
        ["docs/README.md", "schemas/v1/foo.schema.json"],
        load_manifest=lambda p: None,
    )
    assert rc == 0
    assert messages == []


def test_non_json_data_paths_pass_through():
    # Markdown docs under data/ are human-written documentation, not parser output.
    # They must commit without a writer manifest.
    rc, messages = gate.evaluate_gate(
        ["data/sermons/MANIFEST.md", "data/README.md"],
        load_manifest=lambda p: None,
    )
    assert rc == 0
    assert messages == []


def test_data_edit_with_no_manifest_blocks():
    rc, messages = gate.evaluate_gate(
        ["data/reference/schaff-herzog-encyclopedia.json"],
        load_manifest=lambda p: None,
    )
    assert rc == 1
    joined = "\n".join(messages)
    assert "no review/writer-manifests" in joined
    assert "schaff-herzog-encyclopedia" in joined


def test_data_edit_with_manifest_carrying_unregistered_identity_blocks():
    # No identity is registered at A1 -- the allowlist is empty. Any manifest
    # is rejected. This is the forgery-path test.
    rc, messages = gate.evaluate_gate(
        [
            "data/reference/schaff-herzog-encyclopedia.json",
            "review/writer-manifests/test-run.json",
        ],
        load_manifest=lambda p: _manifest(),
        identity_authoriser=lambda i: False,  # Mirrors empty allowlist.
    )
    assert rc == 1
    joined = "\n".join(messages)
    assert "writer_identity" in joined
    assert "writer_identities.py" in joined


def test_data_edit_uncovered_by_manifest_blocks():
    # Manifest exists and writer_identity is somehow registered, but the data
    # path isn't declared in the manifest's data_paths.
    rc, messages = gate.evaluate_gate(
        [
            "data/reference/schaff-herzog-encyclopedia.json",
            "review/writer-manifests/test-run.json",
        ],
        load_manifest=lambda p: _manifest(data_paths=["data/some/other.json"]),
        identity_authoriser=lambda i: True,  # Pretend identity is registered.
    )
    assert rc == 1
    joined = "\n".join(messages)
    assert "not declared in any staged manifest" in joined


def test_unreadable_manifest_blocks_with_clear_message():
    rc, messages = gate.evaluate_gate(
        [
            "data/reference/schaff-herzog-encyclopedia.json",
            "review/writer-manifests/test-run.json",
        ],
        load_manifest=lambda p: None,
        identity_authoriser=lambda i: True,
    )
    assert rc == 1
    joined = "\n".join(messages)
    assert "could not be loaded" in joined


def test_allow_case_now_active_at_a2():
    from build.lib import writer_identities

    assert "ia_schaff_herzog_parser" in writer_identities.registered_identities()
