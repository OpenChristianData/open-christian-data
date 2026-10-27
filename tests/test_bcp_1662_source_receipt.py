"""Focused regressions for BCP 1662 producer-to-manifest source identity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from build.parsers import bcp1662, bcp_full_text
from build.parsers.bcp_1662_source_receipt import (
    SOURCE_HASH_SCOPE,
    SOURCE_MANIFEST,
    verified_source_member_set_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
MEMBER_SET_SHA256 = "19aba9a7977d71ea713221fba41e6cac9f900bf01ab8a18e5fb8f8566e95b93d"
SERVICE_NAMES = tuple(
    relative_path.replace("/", "__")
    for relative_path, _title in bcp_full_text._ESKIMO_1662_SERVICES
)
CALENDAR_NAMES = tuple(filename for filename, _description in bcp1662.SOURCE_PAGES)


ORIGINAL_MANIFEST = Path("sources/structured-text/bcp-1662/bcp-1662.source-manifest.json")
ORIGINAL_MANIFEST_SHA256 = "193a4f01c92ae15a4d0bdad646d5ee5fdb33faf314b4163a0132722bdf6c9e03"
CURRENT_CONVERTER_SHA256 = "8a5689509dbb745ee0b25ddbb82b1b862b0770f6380b3a45916a1ada722a1c91"
CURRENT_VALIDATOR_SHA256 = "bbab7667b024733054b05ffeb358a14a0f6d1d8bbd392ee9bbdac76feeb8e7f1"
CURRENT_VALIDATOR_CLOSURE_SHA256 = "dfe7a6006d815db1362ee947fb3bb89de4f5f4604d16c1e181def238fcf8ebaa"
RUNTIME_MANIFEST = Path("tests/fixtures/reconstruction-runtime/bcp-1662.source-manifest.json")
RUNTIME_VALIDATOR_CLOSURE_SHA256 = "ef0413d685c36964481be76e5db2b9e6ae3c3957a888967aae4c9861a4503970"


def test_v2_manifest_preserves_retained_authorities_and_only_updates_current_runtime() -> None:
    from ocd_kernel.reconstruction.contract import SourceManifest

    original = (ROOT / ORIGINAL_MANIFEST).read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_MANIFEST_SHA256
    expected = json.loads(original)
    expected["converter"]["implementation_sha256"] = CURRENT_CONVERTER_SHA256
    expected["validator"]["implementation_sha256"] = CURRENT_VALIDATOR_SHA256
    expected["validator"]["import_closure_sha256"] = CURRENT_VALIDATOR_CLOSURE_SHA256
    assert SOURCE_MANIFEST.as_posix() == "sources/structured-text/bcp-1662/bcp-1662.source-manifest.v2.json"
    assert json.loads((ROOT / SOURCE_MANIFEST).read_bytes()) == expected
    for role, digest in (("converter", CURRENT_CONVERTER_SHA256), ("validator", CURRENT_VALIDATOR_SHA256)):
        assert hashlib.sha256((ROOT / expected[role]["implementation_path"]).read_bytes()).hexdigest() == digest
    SourceManifest.load(ROOT / SOURCE_MANIFEST, repository_root=ROOT)
    # Historical full runtime declarations stay strict instead of acquiring a bypass.
    with pytest.raises(ValueError, match="converter implementation authority drifted"):
        SourceManifest.load(ROOT / ORIGINAL_MANIFEST, repository_root=ROOT)


def test_v2_manifest_is_covered_by_explicit_current_route_auditors() -> None:
    from build.tools import check_source_manifest_materialization as materialization
    from ocd_kernel.reconstruction import closure_verification

    # Keep the published v2 record frozen while auditing the current runtime copy.
    path = ROOT / RUNTIME_MANIFEST
    record = json.loads(path.read_bytes())
    expected = json.loads((ROOT / SOURCE_MANIFEST).read_bytes())
    expected["validator"]["import_closure_sha256"] = RUNTIME_VALIDATOR_CLOSURE_SHA256
    assert record == expected
    bindings, errors = materialization._manifest_bindings(path, record, repository_root=ROOT)
    assert errors == []
    assert len(bindings) == len(record["authorities"]) + 3
    assert all(materialization._validate_binding(binding) == [] for binding in bindings)
    check = closure_verification.check_validator_manifest_closure(ROOT, RUNTIME_MANIFEST)
    assert check.matches and check.live_sha256 == RUNTIME_VALIDATOR_CLOSURE_SHA256
    retained = closure_verification.check_validator_manifest_closure(ROOT, SOURCE_MANIFEST)
    assert not retained.matches and retained.live_sha256 == RUNTIME_VALIDATOR_CLOSURE_SHA256
    inventory = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/retained-manifest-inventory.json").read_bytes())
    assert inventory[ORIGINAL_MANIFEST.as_posix()] == ORIGINAL_MANIFEST_SHA256
    assert SOURCE_MANIFEST.as_posix() not in inventory


@pytest.mark.parametrize(
    ("member_kind", "logical_names"),
    (
        ("service", SERVICE_NAMES),
        ("calendar-part", CALENDAR_NAMES),
    ),
)
def test_producers_share_exact_governed_member_set_receipt(
    member_kind: str,
    logical_names: tuple[str, ...],
) -> None:
    assert (
        verified_source_member_set_sha256(
            ROOT,
            member_kind=member_kind,
            logical_names=logical_names,
        )
        == MEMBER_SET_SHA256
    )


@pytest.mark.parametrize(
    ("member_kind", "logical_names"),
    (
        ("service", SERVICE_NAMES[:-1]),
        ("service", tuple(reversed(SERVICE_NAMES))),
        ("calendar-part", CALENDAR_NAMES[:-1]),
        ("calendar-part", tuple(reversed(CALENDAR_NAMES))),
    ),
)
def test_producer_subset_omission_or_reordering_fails_closed(
    member_kind: str,
    logical_names: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="do not match the governed source subset"):
        verified_source_member_set_sha256(
            ROOT,
            member_kind=member_kind,
            logical_names=logical_names,
        )


def test_full_text_metadata_preserves_partial_and_human_boundaries() -> None:
    config = bcp_full_text.EDITIONS["bcp-1662"]
    record = bcp_full_text._build_record(
        "bcp-1662",
        config,
        [],
        f"sha256:{MEMBER_SET_SHA256}",
    )
    meta = record["meta"]
    provenance = meta["provenance"]
    assert meta["completeness"] == "partial"
    assert provenance["source_hash"] == f"sha256:{MEMBER_SET_SHA256}"
    assert provenance["source_hash_scope"] == SOURCE_HASH_SCOPE
    assert "human acceptance" in provenance["notes"]
    assert "publication authorization remain unresolved" in provenance["notes"]


def test_collect_metadata_preserves_partial_and_human_boundaries() -> None:
    config = json.loads(bcp1662.CONFIG_PATH.read_bytes())
    meta = bcp1662.build_meta(config, MEMBER_SET_SHA256, "2026-09-01")
    provenance = meta["provenance"]
    assert meta["completeness"] == "partial"
    assert provenance["source_hash"] == f"sha256:{MEMBER_SET_SHA256}"
    assert SOURCE_HASH_SCOPE in provenance["notes"]
    assert "human acceptance" in provenance["notes"]
    assert "publication authorization" in provenance["notes"]


def _stub_full_text_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bcp_full_text,
        "_fetch_and_cache",
        lambda edition_slug, url, cache_name, source, force=False: b"<html></html>",
    )
    monkeypatch.setattr(
        bcp_full_text,
        "extract_paragraphs_from_eskimo_html",
        lambda html: ["Exact retained source paragraph."],
    )


def test_full_text_public_entrypoint_uses_exact_service_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_full_text_inputs(monkeypatch)
    output_dir = tmp_path / "data" / "structured-text"
    monkeypatch.setattr(bcp_full_text, "REPO_ROOT", tmp_path)
    calls: list[tuple[Path, str, tuple[str, ...]]] = []

    def receipt(
        repository_root: Path,
        *,
        member_kind: str,
        logical_names: list[str],
    ) -> str:
        calls.append((repository_root, member_kind, tuple(logical_names)))
        return MEMBER_SET_SHA256

    monkeypatch.setattr(bcp_full_text, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(bcp_full_text, "verified_source_member_set_sha256", receipt)

    assert bcp_full_text.parse_edition("bcp-1662") == len(SERVICE_NAMES)
    assert calls == [(bcp_full_text.REPO_ROOT, "service", SERVICE_NAMES)]
    output = json.loads((output_dir / "bcp-1662.json").read_bytes())
    provenance = output["meta"]["provenance"]
    assert provenance["source_hash"] == f"sha256:{MEMBER_SET_SHA256}"
    assert provenance["source_hash_scope"] == SOURCE_HASH_SCOPE


def test_full_text_public_entrypoint_rejects_receipt_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_full_text_inputs(monkeypatch)
    output_dir = tmp_path / "data" / "structured-text"
    monkeypatch.setattr(bcp_full_text, "REPO_ROOT", tmp_path)

    def reject_receipt(
        repository_root: Path,
        *,
        member_kind: str,
        logical_names: list[str],
    ) -> str:
        del repository_root, member_kind, logical_names
        raise ValueError("governed receipt rejected")

    monkeypatch.setattr(bcp_full_text, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(
        bcp_full_text,
        "verified_source_member_set_sha256",
        reject_receipt,
    )

    with pytest.raises(ValueError, match="governed receipt rejected"):
        bcp_full_text.parse_edition("bcp-1662")
    assert not (output_dir / "bcp-1662.json").exists()


def _stub_collect_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    output_dir = tmp_path / "data" / "prayers" / "bcp-1662"
    monkeypatch.setattr(bcp1662, "REPO_ROOT", tmp_path)
    output_file = output_dir / "collects.json"
    monkeypatch.setattr(bcp1662, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(bcp1662, "OUTPUT_FILE", output_file)
    monkeypatch.setattr(bcp1662, "setup_logging", lambda: None)
    monkeypatch.setattr(bcp1662, "download_all_pages", lambda force=False: None)
    monkeypatch.setattr(
        bcp1662,
        "parse_all_pages",
        lambda dry_run=False: ([{"prayer_id": "retained-test-collect"}], 0),
    )
    monkeypatch.setattr(bcp1662, "report_quality", lambda records: None)
    monkeypatch.setattr(sys, "argv", ["bcp1662.py"])
    return output_file


def test_collect_public_entrypoint_uses_exact_calendar_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_file = _stub_collect_entrypoint(tmp_path, monkeypatch)
    calls: list[tuple[Path, str, tuple[str, ...]]] = []

    def receipt(
        repository_root: Path,
        *,
        member_kind: str,
        logical_names: list[str],
    ) -> str:
        calls.append((repository_root, member_kind, tuple(logical_names)))
        return MEMBER_SET_SHA256

    monkeypatch.setattr(bcp1662, "verified_source_member_set_sha256", receipt)

    bcp1662.main()
    assert calls == [(bcp1662.REPO_ROOT, "calendar-part", CALENDAR_NAMES)]
    output = json.loads(output_file.read_bytes())
    provenance = output["meta"]["provenance"]
    assert provenance["source_hash"] == f"sha256:{MEMBER_SET_SHA256}"
    assert SOURCE_HASH_SCOPE in provenance["notes"]


def test_collect_public_entrypoint_rejects_receipt_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_file = _stub_collect_entrypoint(tmp_path, monkeypatch)

    def reject_receipt(
        repository_root: Path,
        *,
        member_kind: str,
        logical_names: list[str],
    ) -> str:
        del repository_root, member_kind, logical_names
        raise ValueError("governed receipt rejected")

    monkeypatch.setattr(
        bcp1662,
        "verified_source_member_set_sha256",
        reject_receipt,
    )

    with pytest.raises(ValueError, match="governed receipt rejected"):
        bcp1662.main()
    assert not output_file.exists()


def test_collect_parser_write_emits_manifest_with_measured_delta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "data" / "prayers" / "bcp-1662" / "collects.json"
    monkeypatch.setattr(bcp1662, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(bcp1662, "OUTPUT_DIR", output_path.parent)
    monkeypatch.setattr(bcp1662, "OUTPUT_FILE", output_path)
    output_path.parent.mkdir(parents=True)
    previous = {
        "meta": {"id": "bcp-1662-collects"},
        "data": [{"prayer_id": "advent-1", "text": "Old collect text.", "token_count": 3}],
    }
    output_path.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    before_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
    output = {
        "meta": {"id": "bcp-1662-collects"},
        "data": [{"prayer_id": "advent-1", "text": "The collect text."}],
    }

    bcp1662._write_output_with_manifest(output)

    relative_path = "data/prayers/bcp-1662/collects.json"
    manifests = list((tmp_path / "review" / "writer-manifests").glob("*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["writer_identity"] == "bcp1662_parser"
    assert manifest["data_paths"] == [relative_path]
    assert manifest["checksums"][relative_path] == {
        "before_sha256": before_sha256,
        "after_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }
    assert manifest["expected_delta_counts"][relative_path] == {
        "entries_changed": 1,
        "fields_changed": 2,
    }


def test_full_text_parser_write_emits_manifest_with_measured_delta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "data" / "structured-text" / "bcp-1662.json"
    monkeypatch.setattr(bcp_full_text, "REPO_ROOT", tmp_path)
    previous = {
        "meta": {"id": "bcp-1662", "title": "Old title"},
        "data": {"sections": []},
    }
    output_path.parent.mkdir(parents=True)
    output_path.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
    before_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
    record = {
        "meta": {"id": "bcp-1662", "title": "Book of Common Prayer 1662"},
        "data": {"sections": [{"title": "Morning Prayer", "paragraphs": ["Text."]}]},
    }

    bcp_full_text._write_bcp_1662_record(output_path, record)

    relative_path = "data/structured-text/bcp-1662.json"
    manifests = list((tmp_path / "review" / "writer-manifests").glob("*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["writer_identity"] == "bcp_full_text_parser"
    assert manifest["data_paths"] == [relative_path]
    assert manifest["checksums"][relative_path] == {
        "before_sha256": before_sha256,
        "after_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }
    assert manifest["expected_delta_counts"][relative_path] == {
        "entries_changed": 1,
        "fields_changed": 2,
    }
