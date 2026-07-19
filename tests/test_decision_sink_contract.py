"""Contract test: ReviewPatchSink output validates against review_patch.schema.json.

Tests that a patch shaped like ReviewPatchSink.build() output:
  - passes validate_review_patch() (schema check, no file I/O)
  - rejects invalid decision_kind (schema enforces the enum)
  - rejects patches missing required fields
"""
from __future__ import annotations

import pytest

from ocd_kernel.lib.atomic_io import SchemaValidationError
from build.tools.apply_review_patch import validate_review_patch


SCHEMA_VERSION = "3.0.0"
TOOL_VERSION = "reviewer-ui/batch-03"


def _sample_patch(**overrides):
    """Return a minimal schema-valid review_patch dict."""
    base = {
        "schema_type": "review_patch",
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at": "2026-07-03T00:00:00Z",
        "content_hashes": {},
        "decisions": [],
    }
    base.update(overrides)
    return base


def test_empty_decisions_patch_validates():
    """A patch with zero decisions is schema-valid."""
    validate_review_patch(_sample_patch())


def test_adjudication_decision_validates():
    """A patch with an adjudication decision (dispute queue) is schema-valid."""
    patch = _sample_patch(
        content_hashes={"data/some/record.json": "sha256:abcdef0123"},
        decisions=[
            {
                "decision_kind": "adjudication",
                "token_id": "ct-sha256:" + "0" * 64,
                "chosen_reading": "foo",
                "queue": "dispute",
            }
        ],
    )
    validate_review_patch(patch)


def test_gold_pass_decision_validates():
    """A patch with an adjudication gold_pass decision is schema-valid."""
    patch = _sample_patch(
        decisions=[
            {
                "decision_kind": "adjudication",
                "token_id": "ct-sha256:" + "a" * 64,
                "chosen_reading": "bar",
                "queue": "gold_pass",
            }
        ]
    )
    validate_review_patch(patch)


def test_multiple_decisions_validate():
    """A patch with multiple decisions is schema-valid."""
    patch = _sample_patch(
        content_hashes={"data/f1.json": "h1", "data/f2.json": "h2"},
        decisions=[
            {"decision_kind": "adjudication", "token_id": "ct-sha256:" + "1" * 64},
            {"decision_kind": "adjudication", "token_id": "ct-sha256:" + "2" * 64},
            {"decision_kind": "adjudication", "token_id": "ct-sha256:" + "3" * 64},
        ],
    )
    validate_review_patch(patch)


def test_invalid_decision_kind_fails():
    """An invalid decision_kind (not in the enum) fails schema validation."""
    patch = _sample_patch(decisions=[{"decision_kind": "unknown_kind"}])
    with pytest.raises(SchemaValidationError):
        validate_review_patch(patch)


def test_missing_schema_type_fails():
    """A patch missing schema_type fails schema validation."""
    patch = _sample_patch()
    del patch["schema_type"]
    with pytest.raises(SchemaValidationError):
        validate_review_patch(patch)


def test_missing_decisions_field_fails():
    """A patch missing the decisions array fails schema validation."""
    patch = _sample_patch()
    del patch["decisions"]
    with pytest.raises(SchemaValidationError):
        validate_review_patch(patch)


def test_missing_content_hashes_fails():
    """A patch missing content_hashes fails schema validation."""
    patch = _sample_patch()
    del patch["content_hashes"]
    with pytest.raises(SchemaValidationError):
        validate_review_patch(patch)


def test_extra_top_level_field_fails():
    """A patch with an unknown top-level field fails (additionalProperties: false)."""
    patch = _sample_patch(unknown_extra_field="should_fail")
    with pytest.raises(SchemaValidationError):
        validate_review_patch(patch)


def test_js_reviewpatchsink_build_output_validates():
    """ReviewPatchSink.build() output from Node.js validates against the schema.

    This is the end-to-end contract gate: runs a Node.js snippet that requires
    decision_sink.js, calls build(), and validates the JSON output via
    validate_review_patch(). Fails RED while decision_sink.js is absent.
    """
    import json
    import subprocess
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    js_path = repo_root / "build" / "lib" / "review_ui_js" / "decision_sink.js"

    snippet = (
        "const { ReviewPatchSink } = require('" + js_path.as_posix() + "');"
        "const sink = new ReviewPatchSink({ toolVersion: 'reviewer-ui/batch-03' });"
        "sink.record({ decision_kind: 'adjudication', token_id: 'ct-sha256:" + "a" * 64 + "', chosen_reading: 'test', queue: 'dispute' });"
        "sink.snapshotHashes({ 'data/test.json': 'sha256:deadbeef' });"
        "console.log(JSON.stringify(sink.build()));"
    )

    result = subprocess.run(
        ["node", "-e", snippet],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(repo_root),
    )
    patch = json.loads(result.stdout.strip())
    validate_review_patch(patch)
