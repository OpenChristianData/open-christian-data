"""Read-only library handoff inventory boundaries."""

import hashlib
import json
from pathlib import Path

import pytest

from build.tools import report_library_handoffs as inventory


def _write(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _work(
    root: Path, work_id: str, *, raw: str | None = None, edition: bool = False
) -> None:
    record = dict(
        schema_version="2.0",
        work_id=work_id,
        title="Shared title",
        evidence=[raw] if raw else ["research/provenance.md"],
        textual_forms=[],
    )
    if edition:
        record["textual_forms"] = [
            dict(
                textual_form_id=f"{work_id}-english",
                language="en",
                editions=[dict(edition_id=f"{work_id}-edition", title="Witness")],
            )
        ]
    _write(root / "library/works" / work_id / "work.json", record)


def _fixture(root: Path, candidates: Path) -> tuple[Path, str]:
    _work(root, "mapped")
    _work(root, "unmapped")
    _work(root, "ocr")
    _work(root, "edition", edition=True)
    _work(root, "raw-only", raw="raw/source.txt#section-1")
    (root / "raw").mkdir()
    (root / "raw/source.txt").write_text("retained", encoding="utf-8")
    ticket_root = root / inventory.TICKETS
    ticket_root.mkdir(parents=True)
    (ticket_root / "37c-001-ocr.md").write_text(
        "# 37c-001\n**What to build:** catalog entry `ocr`\n"
        "**Status:** held\n**Publishing status:** OCR / Outside of Publishing Scope\n",
        encoding="utf-8",
    )
    (ticket_root / "37c-002-mapped.md").write_text(
        "# 37c-002\n**What to build:** catalog entry `mapped`\n**Status:** ready\n",
        encoding="utf-8",
    )
    manifest_path = root / "sources/route/source-manifest.json"
    digest = _write(manifest_path, dict(work_id="mapped", authorities=[]))
    _write(
        candidates / "current/package/manifest.json",
        dict(
            contract="ocd-candidate-package-v1",
            source_manifest=dict(
                path="sources/route/source-manifest.json", sha256=digest
            ),
        ),
    )
    return manifest_path, digest


def test_explicit_partition_and_determinism(tmp_path):
    root, candidates = tmp_path / "repo", tmp_path / "candidates"
    manifest, digest = _fixture(root, candidates)
    package_path = candidates / "current/package/manifest.json"
    package_sha = hashlib.sha256(package_path.read_bytes()).hexdigest()
    _write(
        candidates / "current/validation.json",
        dict(
            status="pass",
            candidate_sha256=package_sha,
            source_manifest_sha256=digest,
        ),
    )

    first = inventory.build_report(root, candidate_root=candidates)
    second = inventory.build_report(root, candidate_root=candidates)
    assert first == second
    assert list(row["work_id"] for row in first["works"]) == sorted(
        row["work_id"] for row in first["works"]
    )
    assert first["counts"]["groups"] == {
        "ocr-outside-publishing-scope": 1,
        "declared-edition": 1,
        "explicit-source-manifest": 1,
        "direct-raw-evidence": 1,
        "lookup": 1,
    }
    mapped = next(row for row in first["works"] if row["work_id"] == "mapped")
    unmapped = next(row for row in first["works"] if row["work_id"] == "unmapped")
    assert mapped["source_manifests"][0]["sha256"] == digest
    assert mapped["candidate_discovery"][0]["recorded_validation"] == "matching-pass"
    assert first["counts"]["candidate_discovery"]["current_manifest_work_ids"] == 1
    assert (
        first["counts"]["candidate_discovery"]["recorded_validation_pass_work_ids"] == 1
    )
    markdown = inventory.render_markdown(first)
    assert "Discovery notes (not failed works)" in markdown
    assert "Recorded passes" in markdown
    assert "```json" not in markdown
    assert unmapped["source_manifests"] == unmapped["candidate_discovery"] == []
    assert mapped["reconciliation"] == "current-source-bound-candidate"
    assert unmapped["reconciliation"] == "no-work-bound-candidate-in-scanned-locations"
    assert next(row for row in first["works"] if row["work_id"] == "ocr")["reconciliation"] == "ocr-outside-publishing-scope"
    assert first["counts"]["reconciliation"]["current-source-bound-candidate"] == 1
    assert first["counts"]["direct_raw_unique_files"] == 1
    assert first["counts"]["direct_raw_missing_files"] == 0
    direct = next(row for row in first["works"] if row["work_id"] == "raw-only")
    assert direct["direct_raw_evidence"][0]["file_path"] == "raw/source.txt"
    assert direct["direct_raw_evidence"][0]["locator"] == "section-1"
    assert direct["direct_raw_evidence"][0]["locator_checked"] is False
    assert manifest.is_file()


def test_inspected_openmgh_receipt_finds_exact_tei_without_claiming_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, candidates = tmp_path / "repo", tmp_path / "candidates"
    _fixture(root, candidates)
    tei = candidates / "inspected" / "package" / "content.tei.xml"
    tei.parent.mkdir(parents=True)
    tei.write_bytes(b"<TEI>retained work</TEI>")
    receipt_path = Path("plans/2026-09-22-source-preflight/inspected.json")
    _write(root / receipt_path, {
        "works": [{
            "work_id": "edition",
            "candidate_root": str(tei.parent.parent),
            "candidate_tei_sha256": hashlib.sha256(tei.read_bytes()).hexdigest(),
        }],
    })
    monkeypatch.setattr(inventory, "INSPECTED_TEI_RECEIPTS", (receipt_path,))

    report = inventory.build_report(root, candidate_root=candidates)
    row = next(item for item in report["works"] if item["work_id"] == "edition")
    assert row["reconciliation"] == "inspected-receipt-bound-tei"
    assert len(row["inspected_tei_receipts"]) == 1
    assert "acceptance require separate checks" in row["inspected_tei_receipts"][0]["claim"]

    tei.write_bytes(b"<TEI>changed</TEI>")
    changed = inventory.build_report(root, candidate_root=candidates)
    row = next(item for item in changed["works"] if item["work_id"] == "edition")
    assert row["reconciliation"] == "no-work-bound-candidate-in-scanned-locations"
    assert any(issue["kind"] == "inspected-tei-binding-invalid" for issue in changed["issues"])


def test_old_manifest_and_failed_or_missing_validation_do_not_pass(tmp_path):
    root, candidates = tmp_path / "repo", tmp_path / "candidates"
    _fixture(root, candidates)
    _write(
        candidates / "old/package/manifest.json",
        dict(
            contract="ocd-candidate-package-v1",
            source_manifest=dict(
                path="sources/route/source-manifest.json", sha256="0" * 64
            ),
        ),
    )
    _write(
        candidates / "current/validation.json",
        dict(
            status="failed",
            candidate_sha256="0" * 64,
            source_manifest_sha256="0" * 64,
        ),
    )
    result = inventory.build_report(root, candidate_root=candidates)
    mapped = next(row for row in result["works"] if row["work_id"] == "mapped")
    assert len(mapped["candidate_discovery"]) == 2
    assert {c["source_binding"] for c in mapped["candidate_discovery"]} == {"current", "stale"}
    assert (
        all(c["recorded_validation"] == "absent-or-not-matching-pass" for c in mapped["candidate_discovery"])
    )
    assert mapped["reconciliation"] == "stale-or-partial-candidate-evidence"
    assert result["counts"]["candidate_discovery"]["current_manifest_matches"] == 1
    assert result["counts"]["candidate_discovery"]["recorded_validation_passes"] == 0
    assert result["counts"]["candidate_discovery"]["current_manifest_work_ids"] == 1
    assert (
        result["counts"]["candidate_discovery"]["recorded_validation_pass_work_ids"]
        == 0
    )
    kinds = {issue["kind"] for issue in result["issues"]}
    assert {
        "candidate-source-manifest-stale",
        "candidate-validation-not-matching-pass",
    } <= kinds


def test_missing_raw_and_unreadable_manifest_are_accounted(tmp_path, monkeypatch):
    root, candidates = tmp_path / "repo", tmp_path / "candidates"
    manifest, _ = _fixture(root, candidates)
    (root / "raw/source.txt").unlink()
    original = inventory._read_json

    def unreadable(path):
        if path == manifest:
            raise OSError("fixture denied")
        return original(path)

    monkeypatch.setattr(inventory, "_read_json", unreadable)
    result = inventory.build_report(root)
    assert result["counts"]["direct_raw_missing_files"] == 1
    assert result["counts"]["source_manifests"] == 0
    assert {issue["kind"] for issue in result["issues"]} >= {
        "raw-evidence-missing",
        "manifest-unreadable-or-invalid",
    }


def test_ocr_wording_requires_explicit_publishing_status():
    assert inventory.OCR.search("**Publishing status:** OCR / Outside Publishing Scope")
    assert inventory.OCR.search(
        "**Publishing status:** OCR / Outside of Publishing Scope"
    )
    assert not inventory.OCR.search(
        "OCR / Outside Publishing Scope mentioned in research"
    )


def test_installed_master_and_work_local_candidate_are_distinct(tmp_path):
    root, candidates = tmp_path / "repo", tmp_path / "candidates"
    _fixture(root, candidates)
    edition_base = root / "library/works/edition/forms/edition-english/editions/edition-edition"
    master = edition_base / "master.tei.xml"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"<TEI/>")
    _write(
        edition_base / "acceptance.json",
        dict(
            contract="ocd-tei-acceptance-v1",
            decision=dict(agent_assessment=dict(status="accepted")),
            identity=dict(work_id="edition", textual_form_id="edition-english", edition_id="edition-edition"),
            promotion=dict(status="promoted", master=dict(
                path="library/works/edition/forms/edition-english/editions/edition-edition/master.tei.xml",
                sha256=hashlib.sha256(master.read_bytes()).hexdigest(),
            )),
        ),
    )
    local = root / "library/works/unmapped/integration/review/candidate.tei.xml"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"<TEI/>")
    report = inventory.build_report(root, candidate_root=candidates)
    by_id = {row["work_id"]: row for row in report["works"]}
    assert by_id["edition"]["reconciliation"] == "recorded-accepted-master"
    assert len(by_id["edition"]["accepted_master_bindings"]) == 1
    assert by_id["unmapped"]["reconciliation"] == "stale-or-partial-candidate-evidence"
    assert by_id["unmapped"]["integration_candidate_discovery"][0]["evidence"] == "candidate-file-only-or-unmatched-validation"
    master.write_bytes(b"<TEI>changed</TEI>")
    changed = inventory.build_report(root, candidate_root=candidates)
    edition = next(row for row in changed["works"] if row["work_id"] == "edition")
    assert edition["reconciliation"] == "installed-master-evidence-mismatch"
    assert "installed-master-binding-mismatch" in {issue["kind"] for issue in changed["issues"]}


def test_unscanned_candidates_are_unknown(tmp_path):
    root, candidates = tmp_path / "repo", tmp_path / "candidates"
    _fixture(root, candidates)
    report = inventory.build_report(root)
    unmapped = next(row for row in report["works"] if row["work_id"] == "unmapped")
    assert unmapped["reconciliation"] == "candidate-search-incomplete"


def test_ir_tei_is_listed_without_guessing_canonical_identity(tmp_path):
    root, candidates = tmp_path / "repo", tmp_path / "candidates"
    _fixture(root, candidates)
    tei = root / "ir/ccel/unmapped.tei.xml"
    tei.parent.mkdir(parents=True)
    tei.write_bytes(b"<TEI/>")
    report = inventory.build_report(root, candidate_root=candidates)
    unmapped = next(row for row in report["works"] if row["work_id"] == "unmapped")
    assert unmapped["reconciliation"] == "no-work-bound-candidate-in-scanned-locations"
    assert report["unassociated_ir_tei"] == [
        dict(path="ir/ccel/unmapped.tei.xml", bytes=6,
             association="unbound; filename and TEI title do not establish canonical work identity")
    ]
    assert "ir/**/*.tei.xml (unassociated inventory)" in report["searched_locations"]
