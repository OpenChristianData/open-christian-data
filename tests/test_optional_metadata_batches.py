"""Verify retained evidence and exact scope of the optional notice batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library.identities import _schema as load_library_schema


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "plans/2026-08-31-library-pipeline-redesign/artifacts/META-003"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_notice_batch_changes_only_evidenced_warnings() -> None:
    evidence = _json(ARTIFACTS / "02-batch-evidence.json")
    batch_path = ROOT / evidence["batch_path"]
    assert hashlib.sha256(batch_path.read_bytes()).hexdigest() == evidence["batch_sha256"]
    batch = _json(batch_path)
    before_path = ARTIFACTS / "00-before-acquisition.json"
    after_path = ARTIFACTS / "01-after-acquisition.json"
    assert hashlib.sha256(before_path.read_bytes()).hexdigest() == evidence["before_sha256"]
    assert hashlib.sha256(after_path.read_bytes()).hexdigest() == evidence["after_sha256"]
    before, after = _json(before_path), _json(after_path)
    validator = jsonschema.Draft202012Validator(
        load_library_schema("acquisition"), format_checker=jsonschema.FormatChecker()
    )
    validator.validate(before)
    validator.validate(after)
    assert after["warnings"] == before["warnings"] + batch["additions"]
    assert {key: value for key, value in before.items() if key != "warnings"} == {
        key: value for key, value in after.items() if key != "warnings"
    }
    assert "rights" not in after
    assert "accessed_at" not in after
    assert evidence["changed_fields"] == ["warnings"]


def test_notice_batch_is_supported_by_exact_retained_lines() -> None:
    evidence = _json(ARTIFACTS / "02-batch-evidence.json")
    source = evidence["source"]
    content = resolve_repo_path(ROOT, source["path"]).read_bytes()
    assert len(content) == source["bytes"]
    assert hashlib.sha256(content).hexdigest() == source["sha256"]
    lines = content.decode("utf-8-sig").splitlines()
    notice = " ".join(" ".join(lines[2:9]).split())
    print_notice = " ".join(" ".join(lines[120:125]).split())
    jurisdiction = " ".join(" ".join(lines[25916:25925]).split())
    assert "under the terms of the Project Gutenberg License" in notice
    assert "If you are not located in the United States" in notice
    assert "1875." in print_notice and "All Rights reserved." in print_notice
    assert "no representations concerning the copyright status" in jurisdiction
    assert "country other than the United States" in jurisdiction
    additions = _json(ROOT / evidence["batch_path"])["additions"]
    for start, end in source["line_ranges"]:
        assert any(f"{source['path']}#L{start}-L{end}" in value for value in additions)


def test_print_notice_extension_preserves_identity_and_matches_retained_evidence() -> None:
    """The new observation must not promote a print identity or rights conclusion."""
    receipt = _json(ARTIFACTS / "09-print-notice-evidence.json")
    batch_path = ROOT / receipt["batch_path"]
    assert hashlib.sha256(batch_path.read_bytes()).hexdigest() == receipt["batch_sha256"]
    batch = _json(batch_path)
    before_path = ARTIFACTS / "07-before-acquisition.json"
    after_path = ARTIFACTS / "08-after-acquisition.json"
    assert hashlib.sha256(before_path.read_bytes()).hexdigest() == receipt["before_sha256"]
    assert hashlib.sha256(after_path.read_bytes()).hexdigest() == receipt["after_sha256"]
    before, after = _json(before_path), _json(after_path)
    for record in (before, after):
        jsonschema.Draft202012Validator(
            load_library_schema("acquisition"), format_checker=jsonschema.FormatChecker()
        ).validate(record)
    expected = json.loads(json.dumps(before))
    assert batch["changes"][0]["before"] == before["warnings"][2]
    expected["warnings"][2] = batch["changes"][0]["after"]
    assert after == expected
    assert "rights" not in after and "accessed_at" not in after
    source = receipt["source"]
    retained = resolve_repo_path(ROOT, source["path"]).read_bytes()
    assert len(retained) == source["bytes"]
    assert hashlib.sha256(retained).hexdigest() == source["sha256"]
    excerpt = "\n".join(retained.decode("utf-8-sig").splitlines()[120:125])
    assert excerpt == source["excerpt"]
    assert "London" in excerpt and "MACMILLAN AND CO." in excerpt
    assert "1875" in excerpt and "All Rights reserved." in excerpt
    assert "not an examined print exemplar or an OCD rights determination" in after["warnings"][2]
