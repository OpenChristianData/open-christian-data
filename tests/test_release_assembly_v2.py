from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2


ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_CATEGORIES = {
    "prose",
    "quotations",
    "devotionals",
    "bible",
    "commentary",
    "topical_indexes",
    "sermons", "hymns", "liturgies", "poetry", "catechisms",
    "doctrinal_documents", "reference_entries", "prayers",
}


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep the real accepted fixture paths short on Windows."""

    return tmp_path_factory.mktemp("r")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def _files(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _failed_release(root: Path, release: Path, *, selection: dict):
    with pytest.raises(PipelineError, match="release contains failed items"):
        assemble_release_v2(root, release, selection=selection)
    assert not release.exists(), "a failed build must never become the candidate"
    diagnostics = list(release.parent.glob(f".{release.name}-*"))
    assert len(diagnostics) == 1
    stage = diagnostics[0]
    assert not (stage / "internal/checks/build-ready.json").exists()
    return _read_json(stage / "internal/release-report.json"), stage


def _promoted_category(
    tmp_path: Path, category: str, label: str, *, namespace: bool = False
) -> tuple[Path, Path]:
    """Create a real category fixture and promote simulated acceptance in temp only."""

    from tests.test_projection_quotations import accepted_fixture
    from ocd_kernel.tei.acceptance import promote_accepted_master

    label = hashlib.sha256(label.encode("utf-8")).hexdigest()[:4]
    fixture_root, acceptance_path = accepted_fixture(tmp_path / f"{label}f", category)
    if namespace:
        fixture_root, acceptance_path = _namespace_fixture(
            fixture_root, acceptance_path, label=label
        )
    promoted = promote_accepted_master(
        fixture_root,
        acceptance_path=acceptance_path,
        destination=tmp_path / f"{label}p",
    )
    return promoted.destination_root, promoted.acceptance_path


def _replace_values(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_values(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_values(child, replacements)
            for key, child in value.items()
        }
    return value


def _namespace_fixture(
    root: Path, acceptance_path: Path, *, label: str
) -> tuple[Path, Path]:
    """Give a second accepted fixture independent authority paths before merging.

    The accepted_fixture helper intentionally models one source and reuses
    compact IDs. The multi-configuration test needs two roots in one library,
    so this helper makes the second simulated acceptance a distinct
    source/identity envelope while retaining its real category TEI.
    """

    from ocd_kernel.tei.acceptance import build_acceptance_record, write_acceptance

    root = root.resolve()
    original = _read_json(acceptance_path)
    old_identity = dict(original["identity"])
    old_work_id = old_identity["work_id"]
    old_edition_id = old_identity["edition_id"]
    old_acquisition_id = old_identity["acquisition_id"]
    textual_form_id = old_identity["textual_form_id"]
    new_work_id = f"work-{label}"
    new_edition_id = f"edition-{label}"
    new_acquisition_id = f"acquisition-{label}"
    old_source_path = "raw/ccel/spurgeon/morneve.xml"
    new_source_path = f"raw/ccel/spurgeon/morneve-{label}.xml"
    old_source_url = "https://www.ccel.org/ccel/spurgeon/morneve.xml"
    new_source_url = f"https://www.ccel.org/ccel/spurgeon/morneve-{label}.xml"
    old_retained_path = "retained/excerpt.xml"
    new_retained_path = f"retained/{label}/excerpt.xml"
    old_candidate_path = "candidate.xml"
    new_candidate_path = f"candidate-{label}.xml"

    old_evidence_paths = {
        "source-accounting": "evidence/source-accounting.json",
        "validation": "evidence/validation.json",
        "accounting": "evidence/accounting.json",
        "fidelity": "evidence/fidelity.json",
        "reproducibility": "evidence/reproducibility.json",
        "schema": "evidence/schema.json",
        "closure": "evidence/closure.json",
        "review": "evidence/review.json",
    }
    new_evidence_paths = {
        name: f"evidence-{label}/{Path(path).name}"
        for name, path in old_evidence_paths.items()
    }

    old_work_root = root / "library" / "works" / old_work_id
    new_work_root = root / "library" / "works" / new_work_id
    old_work_root.rename(new_work_root)
    old_edition_root = (
        new_work_root
        / "forms"
        / textual_form_id
        / "editions"
        / old_edition_id
    )
    new_edition_root = old_edition_root.with_name(new_edition_id)
    old_edition_root.rename(new_edition_root)
    old_acquisition = (
        new_edition_root
        / "acquisitions"
        / f"{old_acquisition_id}.json"
    )
    new_acquisition = old_acquisition.with_name(f"{new_acquisition_id}.json")
    old_acquisition.rename(new_acquisition)

    old_retained = root / old_retained_path
    new_retained = root / new_retained_path
    new_retained.parent.mkdir(parents=True, exist_ok=True)
    old_retained.rename(new_retained)

    old_candidate = root / old_candidate_path
    new_candidate = root / new_candidate_path
    old_candidate.rename(new_candidate)

    old_evidence = root / "evidence"
    new_evidence = root / f"evidence-{label}"
    new_evidence.mkdir(parents=True, exist_ok=True)
    for path in sorted(old_evidence.iterdir()):
        path.rename(new_evidence / path.name)
    old_evidence.rmdir()

    old_master_path = (
        f"library/works/{old_work_id}/forms/{textual_form_id}/editions/"
        f"{old_edition_id}/master.tei.xml"
    )
    new_master_path = (
        f"library/works/{new_work_id}/forms/{textual_form_id}/editions/"
        f"{new_edition_id}/master.tei.xml"
    )
    old_state_path = f"library/works/{old_work_id}/state.json"
    new_state_path = f"library/works/{new_work_id}/state.json"
    old_acquisition_path = (
        f"library/works/{old_work_id}/forms/{textual_form_id}/editions/"
        f"{old_edition_id}/acquisitions/{old_acquisition_id}.json"
    )
    new_acquisition_path = (
        f"library/works/{new_work_id}/forms/{textual_form_id}/editions/"
        f"{new_edition_id}/acquisitions/{new_acquisition_id}.json"
    )
    replacements = {
        old_work_id: new_work_id,
        old_edition_id: new_edition_id,
        old_acquisition_id: new_acquisition_id,
        old_source_path: new_source_path,
        old_source_url: new_source_url,
        old_retained_path: new_retained_path,
        old_candidate_path: new_candidate_path,
        old_master_path: new_master_path,
        old_state_path: new_state_path,
        old_acquisition_path: new_acquisition_path,
        **{
            old_path: new_evidence_paths[name]
            for name, old_path in old_evidence_paths.items()
        },
    }

    from lxml import etree

    old_candidate_digest = hashlib.sha256(new_candidate.read_bytes()).hexdigest()
    candidate_tree = etree.parse(str(new_candidate))
    for element in candidate_tree.iter():
        if element.text in replacements:
            element.text = replacements[element.text]
        for key, value in element.attrib.items():
            if value in replacements:
                element.set(key, replacements[value])
    new_candidate.write_bytes(etree.tostring(candidate_tree, encoding="utf-8"))
    replacements[old_candidate_digest] = hashlib.sha256(new_candidate.read_bytes()).hexdigest()

    for path in sorted(root.rglob("*.json")):
        document = _replace_values(_read_json(path), replacements)
        def refresh_candidate(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("path") == new_candidate_path and "sha256" in value:
                    value["bytes"] = new_candidate.stat().st_size
                for child in value.values():
                    refresh_candidate(child)
            elif isinstance(value, list):
                for child in value:
                    refresh_candidate(child)
        refresh_candidate(document)
        _write_json(path, document)

    transformed_acceptance = new_edition_root / "acceptance.json"
    record = _read_json(transformed_acceptance)
    technical: dict[str, Any] = {
        "producer": record["technical"]["producer"],
        "checker": record["technical"]["checker"],
        "shared_assumptions": record["technical"]["shared_assumptions"],
        "independent_corroboration": record["technical"][
            "independent_corroboration"
        ],
    }
    for name in (
        "validation",
        "accounting",
        "fidelity",
        "reproducibility",
        "schema",
        "closure",
    ):
        proof = record["technical"][name]
        technical[name] = {
            key: proof[key]
            for key in ("path", "status", "command", "exit_code")
        }
    review = record["review"]
    review_input = {
        "report_path": review["report"]["path"],
        "reviewer": review["reviewer"],
        "reviewed_at": review["reviewed_at"],
        "coverage": review["coverage"],
        "source_quality_uncertainty": review["source_quality_uncertainty"],
        "discrepancies": review["discrepancies"],
        "unreviewed_residuals": review["unreviewed_residuals"],
    }
    rebuilt = build_acceptance_record(
        root,
        identity=record["identity"],
        candidate_path=root / record["technical"]["candidate"]["path"],
        source_accounting_path=root / record["source"]["accounting"]["path"],
        scope=record["scope"],
        technical=technical,
        review=review_input,
        representation_revision=record["representation_revision"],
        decision=record["decision"],
        acceptance_id=record["acceptance_id"],
        promotion_status="pending",
        missing_members=record["source"]["missing_members"],
        unknown_members=record["source"]["unknown_members"],
    )
    write_acceptance(transformed_acceptance, rebuilt)
    return root, transformed_acceptance


def _multi_configuration_root(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    quotation_root, quotation_acceptance = _promoted_category(
        tmp_path, "quotations", "quotations"
    )
    devotional_root, devotional_acceptance = _promoted_category(
        tmp_path, "devotionals", "devotionals", namespace=True
    )
    combined = tmp_path / "multi-configuration-root"
    shutil.copytree(quotation_root, combined)
    shutil.copytree(devotional_root, combined, dirs_exist_ok=True)
    return combined, {
        "quotations": combined
        / quotation_acceptance.resolve().relative_to(quotation_root.resolve()),
        "devotionals": combined
        / devotional_acceptance.resolve().relative_to(devotional_root.resolve()),
    }


def _item(
    root: Path,
    item_id: str,
    category: str,
    acceptance_path: Path,
    **extra: Any,
) -> dict[str, Any]:
    relative = acceptance_path.resolve().relative_to(root.resolve()).as_posix()
    selected = {
        "item_id": item_id,
        "category": category,
        "acceptance_path": relative,
        **extra,
    }
    from tests.release_rights_fixture import authorize_release_fixture
    authorize_release_fixture(root, selected)
    return selected


def _selection(*items: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "release_id": "test-release",
        "items": copy.deepcopy(list(items)),
    }


def _identity_only_work(root: Path, work_id: str) -> None:
    work_root = root / "library" / "works" / work_id
    _write_json(work_root / "work.json", {
        "schema_version": "2.0", "work_id": work_id,
        "title": work_id, "evidence": ["fixture"], "textual_forms": [],
    })
    _write_json(work_root / "state.json", {
        "schema_version": "2.0", "work_id": work_id, "targets": [],
    })


def _cohort_selection(root: Path, acceptance: Path) -> dict[str, Any]:
    _identity_only_work(root, "identity-only")
    _identity_only_work(root, "ocr-excluded")
    selected_work_id = _read_json(acceptance)["identity"]["work_id"]
    selection = _selection(_item(
        root, "quote", "quotations", acceptance, license="CC BY-SA 4.0"
    ))
    selection["items"][0]["work_id"] = selected_work_id
    selection["work_coverage"] = {
        "included_work_ids": ["identity-only", selected_work_id],
        "excluded_works": [{
            "work_id": "ocr-excluded", "reason": "OCR / Outside Publishing Scope",
        }],
    }
    return selection


def test_complete_work_cohort_is_private_and_independently_verified(tmp_path: Path) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "cohort")
    selection = _cohort_selection(root, acceptance)
    unlicensed = copy.deepcopy(selection)
    unlicensed["items"][0].pop("license")
    from ocd_kernel.release.selection import validate_release_selection
    with pytest.raises(PipelineError, match="complete work coverage requires an item license"):
        validate_release_selection(unlicensed)
    release = tmp_path / "cohort-release"
    assemble_release_v2(root, release, selection=selection)

    coverage = _read_json(release / "internal/work-coverage.json")
    by_id = {entry["work_id"]: entry for entry in coverage["selected_works"]}
    assert by_id["identity-only"]["disposition"] == "no_accepted_text_selected"
    assert by_id[_read_json(acceptance)["identity"]["work_id"]]["text_items"] == [
        {"item_id": "quote", "status": "warned"}
    ]
    assert coverage["excluded_works"] == [
        {"work_id": "ocr-excluded", "reason": "OCR / Outside Publishing Scope"}
    ]
    assert not (release / "public/work-coverage.json").exists()
    assert b"identity-only" not in b"".join(_files(release / "public").values())
    assert b"ocr-excluded" not in b"".join(_files(release / "public").values())
    assert verify_release_v2(root, release, selection=selection) == {"status": "pass", "errors": []}
    public_rows = [json.loads(line) for line in
                   (release / "public/data/quotations/train.jsonl").read_text(encoding="utf-8").splitlines()]
    assert public_rows and {row["license"] for row in public_rows} == {"CC BY-SA 4.0"}
    second = tmp_path / "cohort-release-second"
    assemble_release_v2(root, second, selection=selection)
    assert _files(release) == _files(second)


def test_item_license_is_projection_metadata_and_independently_bound(tmp_path: Path) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "license-bound")
    selection = _selection(_item(
        root, "quote", "quotations", acceptance, license="CC BY 4.0"
    ))
    release = tmp_path / "license-release"
    assemble_release_v2(root, release, selection=selection)
    rows = [json.loads(line) for line in
            (release / "public/data/quotations/train.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and {row["license"] for row in rows} == {"CC BY 4.0"}
    assert verify_release_v2(root, release, selection=selection) == {"status": "pass", "errors": []}

    changed_selection = copy.deepcopy(selection)
    changed_selection["items"][0]["license"] = "CC0 1.0"
    result = verify_release_v2(root, release, selection=changed_selection)
    assert result["status"] == "fail"
    assert any("reviewed rights normalization" in issue for issue in result["errors"])


def test_release_assembly_caches_catalog_separately_for_each_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ocd_kernel.library.identities as identities

    root, acceptance = _promoted_category(tmp_path, "quotations", "cached-catalog")
    selection = _selection(_item(root, "quote", "quotations", acceptance))
    discover = identities.discover_library
    calls = 0

    def counted_discovery(path: Path):
        nonlocal calls
        calls += 1
        return discover(path)

    monkeypatch.setattr(identities, "discover_library", counted_discovery)
    report = assemble_release_v2(root, tmp_path / "cached-catalog-release", selection=selection)

    assert report["status"] == "pass"
    assert calls == 2


@pytest.mark.parametrize("mutation", ["changed", "missing", "public-copy"])
def test_work_coverage_tampering_fails_independent_verification(
    tmp_path: Path, mutation: str
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", f"tamper-{mutation}")
    selection = _cohort_selection(root, acceptance)
    release = tmp_path / "cohort-release"
    assemble_release_v2(root, release, selection=selection)
    coverage_path = release / "internal/work-coverage.json"
    if mutation == "changed":
        coverage = _read_json(coverage_path)
        coverage["selected_works"][0]["disposition"] = "included_text"
        _write_json(coverage_path, coverage)
    elif mutation == "missing":
        coverage_path.unlink()
    else:
        public_copy = release / "public/work-coverage.json"
        public_copy.write_bytes(coverage_path.read_bytes())
    checked = verify_release_v2(root, release, selection=selection)
    assert checked["status"] == "fail"
    assert checked["errors"]


def test_missing_selected_acceptance_is_reported_in_private_work_coverage(
    tmp_path: Path,
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "cohort-missing-acceptance")
    selection = _cohort_selection(root, acceptance)
    selected_work_id = _read_json(acceptance)["identity"]["work_id"]
    selection["items"][0]["acceptance_path"] += ".missing"
    release = tmp_path / "cohort-release"

    report, release = _failed_release(root, release, selection=selection)

    assert report["status"] == "fail"
    assert report["accounting"]["failed"] == 1
    assert report["items"][0]["status"] == "failed"
    coverage = _read_json(release / "internal/work-coverage.json")
    by_id = {entry["work_id"]: entry for entry in coverage["selected_works"]}
    assert by_id[selected_work_id]["disposition"] == "failed_text_selection"
    assert by_id[selected_work_id]["text_items"] == [
        {"item_id": "quote", "status": "failed"}
    ]
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "fail", "errors": ["release contains failed items"]
    }


@pytest.mark.parametrize("mutation", [
    "omitted", "extra", "duplicate", "unknown", "ocr-text",
])
def test_work_cohort_rejects_incomplete_or_illegal_selection(
    tmp_path: Path, mutation: str
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", f"cohort-{mutation}")
    selection = _cohort_selection(root, acceptance)
    coverage = selection["work_coverage"]
    if mutation == "omitted":
        coverage["included_work_ids"].remove("identity-only")
    elif mutation == "extra":
        coverage["included_work_ids"].append("extra-work")
    elif mutation == "duplicate":
        coverage["included_work_ids"].append("identity-only")
    elif mutation == "unknown":
        coverage["excluded_works"][0]["work_id"] = "unknown-ocr"
    else:
        selected_work_id = _read_json(acceptance)["identity"]["work_id"]
        coverage["included_work_ids"].remove(selected_work_id)
        coverage["excluded_works"].append({
            "work_id": selected_work_id, "reason": "OCR / Outside Publishing Scope",
        })
    destination = tmp_path / "invalid-cohort-release"
    with pytest.raises(PipelineError):
        assemble_release_v2(root, destination, selection=selection)
    assert not destination.exists()


def _build_single(
    tmp_path: Path, *, category: str = "quotations"
) -> tuple[Path, Path, dict[str, Any], Path]:
    root, acceptance = _promoted_category(tmp_path, category, "single")
    selection = _selection(_item(root, "quote", category, acceptance))
    release = tmp_path / "release"
    assemble_release_v2(root, release, selection=selection)
    return root, release, selection, acceptance


def _assert_configuration(release: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    assert config["path"] == f"public/data/{config['category']}/train.jsonl"
    path = release / config["path"]
    content = path.read_bytes()
    rows = [
        json.loads(line)
        for line in content.decode("utf-8").splitlines()
        if line
    ]
    assert rows
    assert config["row_count"] == len(rows)
    assert config["sha256"] == hashlib.sha256(content).hexdigest()
    return rows


def test_whole_row_omission_reports_public_partition_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The item partition follows emitted rows when a private row is omitted."""
    from ocd_kernel.projection.categories import quotations
    from ocd_kernel.release import public_rows as public_rows_module
    from ocd_kernel.release import verify as release_verify

    root, acceptance = _promoted_category(tmp_path, "quotations", "row-omission")
    selection = _selection(_item(root, "quote", "quotations", acceptance))
    original_project = quotations.project_accepted_quotations
    observed_private_counts: list[int] = []

    def two_private_rows(*args: Any, **kwargs: Any) -> dict[str, Any]:
        projection = original_project(*args, **kwargs)
        row = projection["rows"][0]
        return {**projection, "rows": [copy.deepcopy(row), copy.deepcopy(row)]}

    def omit_one_row(rows: list[dict[str, Any]], *, item_id: str, **kwargs: Any):
        assert item_id == "quote"
        observed_private_counts.append(len(rows))
        assert len(rows) == 2
        return rows[:1], {"test_private_row": rows[1]}

    def check_public_partition(
        _root: Path, staged: Path, *, selection: dict[str, Any] | None = None, progress=None,
    ) -> dict[str, Any]:
        report = _read_json(staged / "internal/release-report.json")
        config = report["configurations"][0]
        rows = _assert_configuration(staged, config)
        assert report["items"][0]["row_count"] == config["row_count"] == len(rows) == 1
        return {"status": "pass", "errors": []}

    monkeypatch.setattr(quotations, "project_accepted_quotations", two_private_rows)
    monkeypatch.setattr(public_rows_module, "public_rows_with_omissions", omit_one_row)
    # The test artifact is deliberately synthetic; the real Edwards inverse and
    # independent verifier are covered by their separate source-bound proof.
    monkeypatch.setattr(release_verify, "verify_release_v2", check_public_partition)
    release = tmp_path / "row-omission-release"
    report = assemble_release_v2(root, release, selection=selection)

    assert observed_private_counts == [2]
    assert report["status"] == "pass"
    assert report["items"][0]["row_count"] == 1
    assert _read_json(release / "internal/release-report.json") == report
    assert len(_assert_configuration(release, report["configurations"][0])) == 1


def test_real_accepted_quotation_build_has_private_receipts_and_public_rows(
    tmp_path: Path,
) -> None:
    root, release, selection, _acceptance = _build_single(tmp_path)
    report = _read_json(release / "internal" / "release-report.json")

    assert report["status"] == "pass"
    assert report["release_id"] == "test-release"
    assert report["accounting"]["requested"] == 1
    assert sum(
        report["accounting"][name]
        for name in ("included", "warned", "failed", "excluded")
    ) == 1
    assert len(report["items"]) == 1
    item = report["items"][0]
    assert item["item_id"] == "quote"
    assert item["category"] == "quotations"
    assert item["status"] in {"included", "warned"}
    assert item["row_count"] > 0
    assert item["receipt_path"] == "internal/projection-receipts/quote.json"
    assert (release / item["receipt_path"]).is_file()
    assert len(report["configurations"]) == 1
    rows = _assert_configuration(release, report["configurations"][0])
    assert len(rows) == item["row_count"]
    assert {row["category"] for row in rows} == {"quotations"}

    public_files = _files(release / "public")
    assert public_files
    assert all("receipt" not in path for path in public_files)
    public_text = b"\n".join(content for path, content in public_files.items()
                             if not path.endswith(".arrow")).decode("utf-8")
    assert "source_sha256" not in public_text
    assert "raw/ccel/" not in public_text
    assert "candidate.xml" not in public_text

    assert verify_release_v2(root, release, selection=selection) == {
        "status": "pass",
        "errors": [],
    }
    missing_external = verify_release_v2(root, release)
    assert missing_external["status"] == "fail"
    assert any("external selection" in error for error in missing_external["errors"])


def test_release_rebuild_is_byte_for_byte_deterministic(tmp_path: Path) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "deterministic")
    selection = _selection(_item(root, "quote", "quotations", acceptance))
    first = tmp_path / "release-one"
    second = tmp_path / "release-two"

    first_report = assemble_release_v2(root, first, selection=selection)
    second_report = assemble_release_v2(root, second, selection=selection)

    assert first_report == second_report
    assert _files(first) == _files(second)
    assert verify_release_v2(root, first, selection=selection)["status"] == "pass"
    assert verify_release_v2(root, second, selection=selection)["status"] == "pass"


def test_multi_configuration_build_combines_real_accepted_categories(
    tmp_path: Path,
) -> None:
    root, accepted = _multi_configuration_root(tmp_path)
    selection = _selection(
        _item(root, "quote", "quotations", accepted["quotations"]),
        _item(root, "devotional", "devotionals", accepted["devotionals"]),
    )
    before = _files(root)
    release = tmp_path / "multi-release"
    report = assemble_release_v2(root, release, selection=selection)

    assert report["status"] == "pass"
    assert report["accounting"]["requested"] == 2
    assert report["accounting"]["failed"] == 0
    assert report["accounting"]["excluded"] == 0
    assert report["accounting"]["included"] + report["accounting"]["warned"] == 2
    assert [config["category"] for config in report["configurations"]] == [
        "devotionals",
        "quotations",
    ]
    for config in report["configurations"]:
        _assert_configuration(release, config)
    assert all(
        item["status"] in {"included", "warned"}
        and item["row_count"] > 0
        and (release / item["receipt_path"]).is_file()
        for item in report["items"]
    )
    assert _files(root) == before
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "pass",
        "errors": [],
    }


@pytest.mark.parametrize("category", ["quotations", "unassigned"])
def test_explicit_exclusion_is_accounted_without_public_configuration(
    tmp_path: Path, category: str,
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "excluded")
    selection = _selection(
        _item(
            root,
            "quote",
            category,
            acceptance,
            exclude_reason="held for later review",
        )
    )
    release = tmp_path / "excluded-release"
    report = assemble_release_v2(root, release, selection=selection)

    assert report["status"] == "pass"
    assert report["accounting"] == {
        "requested": 1,
        "included": 0,
        "warned": 0,
        "failed": 0,
        "excluded": 1,
    }
    assert report["items"][0]["status"] == "excluded"
    assert report["items"][0]["category"] == category
    assert report["items"][0]["reasons"] == ["held for later review"]
    assert report["items"][0]["row_count"] == 0
    assert report["items"][0]["receipt_path"] is None
    assert report["configurations"] == []
    assert not _files(release / "public")
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "pass",
        "errors": [],
    }


def test_mixed_success_and_failure_keeps_private_failure_accounting(
    tmp_path: Path,
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "mixed")
    selection = _selection(
        _item(root, "quote", "quotations", acceptance),
        _item(root, "future", "future_category", acceptance),
    )
    release = tmp_path / "mixed-release"
    report, release = _failed_release(root, release, selection=selection)

    assert report["status"] == "fail"
    assert report["accounting"]["requested"] == 2
    assert report["accounting"]["failed"] == 1
    assert report["accounting"]["included"] + report["accounting"]["warned"] == 1
    failed = next(item for item in report["items"] if item["item_id"] == "future")
    assert failed["status"] == "failed"
    assert failed["row_count"] == 0
    assert failed["receipt_path"] is None
    assert failed["reasons"]
    assert any(
        config["category"] == "quotations"
        for config in report["configurations"]
    )
    checked = verify_release_v2(root, release, selection=selection)
    assert checked["status"] == "fail"
    assert checked["errors"] == ["release contains failed items"]


def test_private_public_row_leak_fails_only_its_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ocd_kernel.release import public_rows as public_rows_module

    root, accepted = _multi_configuration_root(tmp_path)
    selection = _selection(
        _item(root, "a-good", "quotations", accepted["quotations"]),
        _item(root, "z-leaking", "devotionals", accepted["devotionals"]),
    )
    original_transform = public_rows_module.public_rows_with_omissions

    def leaking_transform(rows: list[dict[str, Any]], *, item_id: str, **kwargs: Any):
        public_rows, omissions = original_transform(rows, item_id=item_id, **kwargs)
        if item_id == "z-leaking":
            public_rows[0]["private_marker"] = "urn:ocd:retained-source"
        return public_rows, omissions

    monkeypatch.setattr(public_rows_module, "public_rows_with_omissions", leaking_transform)
    release = tmp_path / "privacy-failed-release"
    report, release = _failed_release(root, release, selection=selection)

    assert report["status"] == "fail"
    assert report["accounting"]["failed"] == 1
    good, failed = report["items"]
    assert good["item_id"] == "a-good" and good["status"] in {"included", "warned"}
    assert (release / good["receipt_path"]).is_file()
    assert failed["item_id"] == "z-leaking" and failed["status"] == "failed"
    assert failed["row_count"] == 0 and failed["receipt_path"] is None
    assert any("item z-leaking public rows" in reason for reason in failed["reasons"])
    assert any("private source annotation" in reason for reason in failed["reasons"])
    assert not (release / "internal/projection-receipts/z-leaking.json").exists()
    assert [config["category"] for config in report["configurations"]] == ["quotations"]
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "fail", "errors": ["release contains failed items"],
    }


def test_unsafe_notice_fails_only_its_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ocd_kernel.release import notices as notices_module

    root, accepted = _multi_configuration_root(tmp_path)
    selection = _selection(
        _item(root, "a-good", "quotations", accepted["quotations"]),
        _item(root, "z-unsafe-notice", "devotionals", accepted["devotionals"]),
    )

    def notices_for_item(_root: Path, selected: dict[str, Any], _accepted_path: Path) -> list[str]:
        return ["Good notice\n"] if selected["item_id"] == "a-good" else ["Unsafe notice\n\n\n\n"]

    monkeypatch.setattr(notices_module, "notice_texts_for_item", notices_for_item)
    release = tmp_path / "notice-failed-release"
    report, release = _failed_release(root, release, selection=selection)

    assert report["status"] == "fail"
    assert report["accounting"]["failed"] == 1
    good, failed = report["items"]
    assert good["item_id"] == "a-good" and good["status"] in {"included", "warned"}
    assert (release / good["receipt_path"]).is_file()
    assert failed["item_id"] == "z-unsafe-notice" and failed["status"] == "failed"
    assert failed["row_count"] == 0 and failed["receipt_path"] is None
    assert "public notice is not a safe verbatim Markdown block" in failed["reasons"]
    assert not (release / "internal/projection-receipts/z-unsafe-notice.json").exists()
    assert [config["category"] for config in report["configurations"]] == ["quotations"]
    card = (release / "public/README.md").read_text(encoding="utf-8")
    assert "Good notice" in card and "Unsafe notice" not in card
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "fail", "errors": ["release contains failed items"],
    }


@pytest.mark.parametrize("failure_type", [ValueError, KeyError, TypeError])
def test_malformed_projector_item_retains_other_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_type: type[Exception]
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "malformed")
    import ocd_kernel.projection.categories.bible as bible

    def broken_projector(*args: Any, **kwargs: Any) -> Any:
        raise failure_type("malformed accepted projection")

    monkeypatch.setattr(bible, "project_accepted_bible", broken_projector)
    selection = _selection(
        _item(root, "good", "quotations", acceptance),
        _item(root, "bad", "bible", acceptance),
    )
    release = tmp_path / "malformed-release"
    report, release = _failed_release(root, release, selection=selection)
    assert report["status"] == "fail"
    assert report["accounting"]["failed"] == 1
    assert report["accounting"]["included"] + report["accounting"]["warned"] == 1
    assert "malformed accepted projection" in report["items"][0]["reasons"][0]
    assert report["configurations"][0]["row_count"] > 0
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "fail", "errors": ["release contains failed items"]
    }


@pytest.mark.parametrize("payload", [
    None, [], {"rows": [None], "receipt": {}},
    {"rows": [{}], "receipt": None}, {"rows": [{}], "receipt": []},
    {"rows": [{}], "receipt": {"warnings": None}},
    {"rows": [{}], "receipt": {"warnings": [42]}},
])
def test_malformed_projector_payload_is_an_accounted_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "bad-shape")
    import ocd_kernel.projection.categories.bible as bible
    monkeypatch.setattr(bible, "project_accepted_bible", lambda *args, **kwargs: payload)
    selection = _selection(_item(root, "bad", "bible", acceptance),
                           _item(root, "good", "quotations", acceptance))
    release = tmp_path / "bad-shape-release"
    report, release = _failed_release(root, release, selection=selection)
    assert report["status"] == "fail"
    assert report["accounting"]["failed"] == 1
    assert report["accounting"]["included"] + report["accounting"]["warned"] == 1
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "fail", "errors": ["release contains failed items"]
    }


def test_all_failed_selection_retains_report_without_public_output(
    tmp_path: Path,
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "all-failed")
    selection = _selection(
        _item(root, "unsupported", "future_category", acceptance)
    )
    before = _files(root)
    release = tmp_path / "all-failed-release"
    report, release = _failed_release(root, release, selection=selection)

    assert report["status"] == "fail"
    assert report["accounting"] == {
        "requested": 1,
        "included": 0,
        "warned": 0,
        "failed": 1,
        "excluded": 0,
    }
    assert report["items"][0]["status"] == "failed"
    assert report["items"][0]["reasons"]
    assert report["configurations"] == []
    assert not _files(release / "public")
    assert _files(release / "internal")
    assert _files(root) == before
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "fail",
        "errors": ["release contains failed items"],
    }


@pytest.mark.parametrize(
    "case",
    [
        "missing-schema-version",
        "wrong-schema-version",
        "empty-release-id",
        "missing-items",
        "empty-items",
        "nonobject-item",
        "missing-item-id",
        "missing-category",
        "missing-acceptance-path",
        "absolute-acceptance-path",
        "parent-acceptance-path",
        "backslash-acceptance-path",
        "duplicate-item-id",
        "duplicate-category-target",
    ],
)
def test_invalid_or_duplicate_selection_writes_no_destination(
    tmp_path: Path, case: str
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", f"invalid-{case}")
    valid_item = _item(root, "quote", "quotations", acceptance)
    selection: Any = _selection(valid_item)
    if case == "missing-schema-version":
        selection.pop("schema_version")
    elif case == "wrong-schema-version":
        selection["schema_version"] = "1.0"
    elif case == "empty-release-id":
        selection["release_id"] = ""
    elif case == "missing-items":
        selection.pop("items")
    elif case == "empty-items":
        selection["items"] = []
    elif case == "nonobject-item":
        selection["items"] = ["quote"]
    elif case == "missing-item-id":
        selection["items"][0].pop("item_id")
    elif case == "missing-category":
        selection["items"][0].pop("category")
    elif case == "missing-acceptance-path":
        selection["items"][0].pop("acceptance_path")
    elif case == "absolute-acceptance-path":
        selection["items"][0]["acceptance_path"] = str(acceptance.resolve())
    elif case == "parent-acceptance-path":
        selection["items"][0]["acceptance_path"] = "../acceptance.json"
    elif case == "backslash-acceptance-path":
        selection["items"][0]["acceptance_path"] = (
            "library\\works\\fixture\\acceptance.json"
        )
    elif case == "duplicate-item-id":
        selection["items"].append(copy.deepcopy(valid_item))
    elif case == "duplicate-category-target":
        duplicate = copy.deepcopy(valid_item)
        duplicate["item_id"] = "quote-copy"
        selection["items"].append(duplicate)

    destination = tmp_path / "invalid-release"
    before = _files(root)
    with pytest.raises(PipelineError):
        assemble_release_v2(root, destination, selection=selection)
    assert not destination.exists()
    assert _files(root) == before


def test_existing_destination_is_never_overwritten(tmp_path: Path) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "fresh")
    selection = _selection(_item(root, "quote", "quotations", acceptance))
    destination = tmp_path / "release"
    destination.mkdir()
    marker = destination / "marker.txt"
    marker.write_text("keep me", encoding="utf-8")
    before = _files(destination)

    with pytest.raises(PipelineError):
        assemble_release_v2(root, destination, selection=selection)
    assert _files(destination) == before


def test_destination_inside_input_root_is_rejected(tmp_path: Path) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "inside")
    selection = _selection(_item(root, "quote", "quotations", acceptance))
    destination = root / "release"

    with pytest.raises(PipelineError):
        assemble_release_v2(root, destination, selection=selection)
    assert not destination.exists()


@pytest.mark.parametrize(
    "mutation",
    ["rows", "receipt", "report", "selection-digest", "stored-selection", "extra",
     "check-missing", "check-forged"],
)
def test_independent_checker_rejects_release_tampering(
    tmp_path: Path, mutation: str
) -> None:
    root, release, selection, _acceptance = _build_single(tmp_path)
    report_path = release / "internal" / "release-report.json"
    report = _read_json(report_path)
    config = report["configurations"][0]
    config_path = release / config["path"]
    receipt_path = release / report["items"][0]["receipt_path"]

    if mutation == "rows":
        rows = [
            json.loads(line)
            for line in config_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        rows[0]["text"] += " forged"
        content = b"".join(canonical_bytes(row) for row in rows)
        config_path.write_bytes(content)
        config["row_count"] = len(rows)
        config["sha256"] = hashlib.sha256(content).hexdigest()
        _write_json(report_path, report)
    elif mutation == "receipt":
        receipt = _read_json(receipt_path)
        receipt["row_count"] = 0
        _write_json(receipt_path, receipt)
    elif mutation == "report":
        report["accounting"]["included"] += 1
        _write_json(report_path, report)
    elif mutation == "selection-digest":
        report["selection_sha256"] = "0" * 64
        _write_json(report_path, report)
    elif mutation == "stored-selection":
        stored_path = release / "internal" / "release-selection.json"
        stored = _read_json(stored_path)
        stored["items"][0]["exclude_reason"] = "forged exclusion"
        _write_json(stored_path, stored)
    elif mutation == "check-missing":
        (release / "internal/checks/independent-check.json").unlink()
    elif mutation == "check-forged":
        _write_json(release / "internal/checks/independent-check.json",
                    {"status": "pass", "errors": ["invented result"]})
    else:
        leaked = release / "public" / "private-leak.json"
        leaked.parent.mkdir(parents=True, exist_ok=True)
        leaked.write_text('{"source_sha256":"private"}\n', encoding="utf-8")

    checked = verify_release_v2(root, release, selection=selection)
    assert checked["status"] == "fail"
    assert checked["errors"]


def test_independent_checker_does_not_call_category_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, release, selection, _acceptance = _build_single(tmp_path)
    import ocd_kernel.projection.categories.quotations as quotations

    def producer_must_not_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("release verifier called the producer")

    monkeypatch.setattr(
        quotations, "project_accepted_quotations", producer_must_not_run
    )
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "pass",
        "errors": [],
    }


def test_accepted_master_mutation_after_build_fails_verification(
    tmp_path: Path,
) -> None:
    root, release, selection, _acceptance = _build_single(tmp_path)
    master = next(root.rglob("master.tei.xml"))
    master.write_bytes(master.read_bytes() + b"\n")

    checked = verify_release_v2(root, release, selection=selection)
    assert checked["status"] == "fail"
    assert checked["errors"]


def test_assembler_does_not_need_legacy_json_or_workcatalog(
    tmp_path: Path,
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "authority")
    (root / "WorkCatalog.json").write_text("{ invalid legacy json", encoding="utf-8")
    legacy = root / "data" / "quotations" / "train.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("{ invalid generated legacy json", encoding="utf-8")
    selection = _selection(_item(root, "quote", "quotations", acceptance))

    report = assemble_release_v2(root, tmp_path / "authority-release", selection=selection)
    assert report["status"] == "pass"


def test_build_and_check_clis_accept_an_external_v2_selection_file(
    tmp_path: Path,
) -> None:
    from build.tools.build_hf_release import main as build_main
    from build.tools.check_hf_release import main as check_main

    root, acceptance = _promoted_category(tmp_path, "quotations", "cli")
    selection = _selection(_item(root, "quote", "quotations", acceptance))
    selection_path = tmp_path / "selection.json"
    _write_json(selection_path, selection)
    release = tmp_path / "cli-release"
    args = [
        "--root",
        str(root),
        "--output",
        str(release),
        "--selection",
        str(selection_path),
    ]

    assert build_main(args) == 0
    assert check_main(
        [
            "--root",
            str(root),
            "--release",
            str(release),
            "--selection",
            str(selection_path),
        ]
    ) == 0


@pytest.mark.parametrize("check_result", [
    {"status": "fail", "errors": ["injected independent verifier failure"]},
    {"status": "fail", "errors": []}, None, {}, {"errors": []},
])
def test_independent_verifier_failure_preserves_private_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, check_result: Any
) -> None:
    root, acceptance = _promoted_category(tmp_path, "quotations", "rollback")
    selection = _selection(_item(root, "quote", "quotations", acceptance))
    parent = tmp_path / "rollback-parent"
    parent.mkdir()
    sibling = parent / "unrelated-sibling.txt"
    sibling.write_bytes(b"must survive")
    destination = parent / "release"
    before = _files(parent)
    calls: list[tuple[Path, Path, dict[str, Any]]] = []

    import ocd_kernel.release.verify as release_verify

    def injected_failure(
        checked_root: Path, checked_release: Path, *, selection: dict[str, Any] | None = None, progress=None
    ) -> dict[str, Any]:
        calls.append((checked_root, checked_release, selection or {}))
        return check_result

    monkeypatch.setattr(release_verify, "verify_release_v2", injected_failure)
    with pytest.raises(
        PipelineError, match="independent release verification failed"
    ):
        assemble_release_v2(root, destination, selection=selection)

    assert calls and calls[0][1] != destination
    assert calls[0][2] == selection
    assert not destination.exists()
    assert sibling.read_bytes() == before[sibling.name]
    stage = calls[0][1]
    assert stage.exists() and (stage / "internal/release-report.json").is_file()
    assert not (stage / "internal/checks/build-ready.json").exists()
    assert {path.name for path in parent.iterdir()} == {sibling.name, stage.name}


def test_two_namespaced_quotations_share_one_configuration_with_partitioned_rows(
    tmp_path: Path,
) -> None:
    first_root, first_acceptance = _promoted_category(
        tmp_path, "quotations", "same-config-a", namespace=True
    )
    second_root, second_acceptance = _promoted_category(
        tmp_path, "quotations", "same-config-b", namespace=True
    )
    root = tmp_path / "two-quotations-root"
    shutil.copytree(first_root, root)
    shutil.copytree(second_root, root, dirs_exist_ok=True)
    accepted = {
        "quote-a": root
        / first_acceptance.resolve().relative_to(first_root.resolve()),
        "quote-b": root
        / second_acceptance.resolve().relative_to(second_root.resolve()),
    }
    selection = _selection(
        _item(root, "quote-a", "quotations", accepted["quote-a"]),
        _item(root, "quote-b", "quotations", accepted["quote-b"]),
    )
    before = _files(root)
    release = tmp_path / "same-config-release"
    report = assemble_release_v2(root, release, selection=selection)

    assert report["status"] == "pass"
    assert report["accounting"] == {
        "requested": 2,
        "included": report["accounting"]["included"],
        "warned": report["accounting"]["warned"],
        "failed": 0,
        "excluded": 0,
    }
    assert report["accounting"]["included"] + report["accounting"]["warned"] == 2
    assert len(report["configurations"]) == 1
    config = report["configurations"][0]
    assert config["category"] == "quotations"
    rows = _assert_configuration(release, config)
    assert config["row_count"] == sum(item["row_count"] for item in report["items"])

    offset = 0
    for item in report["items"]:
        identity = _read_json(accepted[item["item_id"]])["identity"]
        partition = rows[offset : offset + item["row_count"]]
        offset += item["row_count"]
        assert partition
        assert all(
            row["work_id"] == identity["work_id"]
            and row["textual_form_id"] == identity["textual_form_id"]
            and row["edition_id"] == identity["edition_id"]
            for row in partition
        )
    assert offset == len(rows)
    assert _files(root) == before
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "pass",
        "errors": [],
    }


def test_accepted_prose_missing_receipt_is_an_accounted_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_tei_acceptance import _fixture_root, _write_valid_acceptance
    from ocd_kernel.tei.acceptance import promote_accepted_master
    from ocd_kernel.projection.categories import prose

    fixture_root = _fixture_root(tmp_path)
    acceptance_path, _record = _write_valid_acceptance(fixture_root)
    promoted = promote_accepted_master(
        fixture_root, acceptance_path=acceptance_path, destination=tmp_path / "promoted",
    )
    root = promoted.destination_root
    projection = prose.project_accepted_prose(root, acceptance_path=promoted.acceptance_path)
    projection.pop("receipt")
    monkeypatch.setattr(prose, "project_accepted_prose", lambda *args, **kwargs: projection)
    selection = _selection(_item(root, "prose", "prose", promoted.acceptance_path))

    report, _stage = _failed_release(root, tmp_path / "missing-receipt", selection=selection)

    assert report["accounting"]["failed"] == 1
    assert report["items"][0]["reasons"] == ["'receipt'"]


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("form_only", [False, True])
def test_real_accepted_prose_build_has_rows_and_independent_verification(
    tmp_path: Path, native: bool, form_only: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_tei_acceptance import _fixture_root, _write_valid_acceptance
    from ocd_kernel.tei.acceptance import promote_accepted_master

    fixture_root = _fixture_root(tmp_path)
    if form_only:
        work_path = next((fixture_root / "library/works").glob("*/work.json"))
        work = _read_json(work_path)
        form = work["textual_forms"][0]
        form["language"] = "fr"
        form["editions"][0].pop("language", None)
        _write_json(work_path, work)
    if native:
        from tests.test_tei_acceptance import _master_path
        from lxml import etree
        master = _master_path(fixture_root)
        tree = etree.parse(str(master))
        head = tree.find('.//{http://www.tei-c.org/ns/1.0}text//{http://www.tei-c.org/ns/1.0}head')
        head.set('type', 'title')
        tree.write(str(master), encoding='utf-8')
    acceptance_path, _record = _write_valid_acceptance(fixture_root)
    promoted = promote_accepted_master(
        fixture_root,
        acceptance_path=acceptance_path,
        destination=tmp_path / "prose-promoted",
    )
    root = promoted.destination_root
    selection = _selection(_item(root, "prose", "prose", promoted.acceptance_path))
    before = _files(root)
    release = tmp_path / "prose-release"

    report = assemble_release_v2(root, release, selection=selection)

    assert report["status"] == "pass"
    assert report["accounting"] == {
        "requested": 1,
        "included": report["accounting"]["included"],
        "warned": report["accounting"]["warned"],
        "failed": 0,
        "excluded": 0,
    }
    assert report["accounting"]["included"] + report["accounting"]["warned"] == 1
    assert len(report["configurations"]) == 1
    config = report["configurations"][0]
    assert config["category"] == "prose"
    rows = _assert_configuration(release, config)
    assert rows and all(row["category"] == "prose" for row in rows)
    if form_only:
        assert all(row["language"] == "fr" for row in rows)
    item = report["items"][0]
    assert item["status"] in {"included", "warned"}
    assert item["row_count"] == len(rows) > 0
    assert item["receipt_path"] == "internal/projection-receipts/prose.json"
    assert (release / item["receipt_path"]).is_file()

    identity = _read_json(promoted.acceptance_path)["identity"]
    assert all(
        {
            row["work_id"],
            row["textual_form_id"],
            row["edition_id"],
        }
        == {
            identity["work_id"],
            identity["textual_form_id"],
            identity["edition_id"],
        }
        for row in rows
    )
    assert _files(root) == before
    if native:
        from ocd_kernel.projection.categories import native_documents as producer
        references = [ref for row in rows for ref in row['source_references'] if 'scripture' in ref]
        monkeypatch.setattr(producer, '_prose_references', lambda *args: pytest.fail('producer called'))
    else:
        from ocd_kernel.projection import envelope as producer
        references = [ref for row in rows for ref in row['references'] if 'scripture' in ref]
        monkeypatch.setattr(producer, 'normalize_reference_record', lambda *args, **kwargs: pytest.fail('producer called'))
    assert any(ref['scripture']['normalized'] == '1Tim.3.16' for ref in references)
    from build.tools.audit_ref_coverage import audit_release
    audit = audit_release(root, release, selection, lambda ref: (True, ''))
    assert any(item['reference'] == '1Tim.3.16' for item in audit['references'])
    assert not any('category has no supported' in item['reason'] for item in audit['unsupported_rows'])
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "pass",
        "errors": [],
    }


@pytest.mark.parametrize("category", ["bible", "commentary", "topical_indexes"])
@pytest.mark.requires_local_artifacts
def test_real_accepted_category_routes_build_and_verify(
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    category: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ocd_kernel.tei.acceptance import promote_accepted_master

    if category == "bible":
        from tests.test_projection_bible import _accepted_bible_fixture

        root, acceptance_path, _case, _source = _accepted_bible_fixture(
            tmp_path_factory
        )
    elif category == "commentary":
        from tests.test_projection_commentary import _accepted_commentary_fixture

        root, acceptance_path, _case, _source = _accepted_commentary_fixture(
            tmp_path_factory
        )
    else:
        from tests.test_projection_topical_indexes import accepted_topic_fixture

        root, acceptance_path = accepted_topic_fixture(tmp_path)

    promoted = promote_accepted_master(
        root,
        acceptance_path=acceptance_path,
        destination=tmp_path / f"{category}-promoted",
    )
    promoted_root = promoted.destination_root
    selection = _selection(
        _item(promoted_root, category, category, promoted.acceptance_path)
    )
    before = _files(promoted_root)
    release = tmp_path / f"{category}-release"

    report = assemble_release_v2(promoted_root, release, selection=selection)

    assert report["status"] == "pass"
    assert report["accounting"] == {
        "requested": 1,
        "included": report["accounting"]["included"],
        "warned": report["accounting"]["warned"],
        "failed": 0,
        "excluded": 0,
    }
    assert report["accounting"]["included"] + report["accounting"]["warned"] == 1
    assert len(report["configurations"]) == 1
    config = report["configurations"][0]
    assert config["category"] == category
    rows = _assert_configuration(release, config)
    assert rows and all(row["category"] == category for row in rows)
    item = report["items"][0]
    assert item["status"] in {"included", "warned"}
    assert item["row_count"] == len(rows) > 0
    assert (release / item["receipt_path"]).is_file()
    assert _files(promoted_root) == before
    if category == 'bible':
        assert [row['locator']['reference']['normalized'] for row in rows] == ['Gen.1.1', 'Gen.1.2', 'Gen.1.3']
        assert all(row['locator']['reference_origin'] == 'tei-verse-components' for row in rows)
        from ocd_kernel.projection.categories import bible

        def forbidden(*args, **kwargs):
            raise AssertionError('release checker called Bible reference producer')

        monkeypatch.setattr(bible, 'normalize_explicit_target', forbidden)
    assert verify_release_v2(promoted_root, release, selection=selection) == {
        "status": "pass",
        "errors": [],
    }


@pytest.mark.requires_local_artifacts
def test_doctrinal_hierarchy_survives_accepted_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_release_accepted_structured import accepted_fixture
    from ocd_kernel.tei.acceptance import promote_accepted_master
    from ocd_kernel.projection.categories import doctrinal_documents

    source_root, acceptance = accepted_fixture(
        tmp_path / "f", "doctrinal_documents", doctrinal_hierarchy=True
    )
    promoted = promote_accepted_master(source_root, acceptance_path=acceptance,
                                      destination=tmp_path / "p")
    root = promoted.destination_root
    selection = _selection(_item(root, "doctrinal_documents", "doctrinal_documents", promoted.acceptance_path))
    release = tmp_path / "out"
    report = assemble_release_v2(root, release, selection=selection)
    assert report["status"] == "pass", report
    rows = _assert_configuration(release, report["configurations"][0])
    assert len(rows) == 1
    row = rows[0]
    assert row["content_format"] == "ocd-native-content-v1"
    assert row['revision_history'] == [{'year':1788, 'body':'Synthetic assembly', 'description':'Synthetic source revision statement.'}]
    assert row["text"].index("Synthetic hierarchy introduction.") < row["text"].index("Synthetic hierarchy conclusion.")
    structure = [node for node in row["structure"]["content"] if node["kind"] != "text"]
    assert len(structure) == 5
    receipt = _read_json(release / report["items"][0]["receipt_path"])
    assert receipt["selection"]["selected_units"] == 2
    assert len(receipt["anchors"][0]["selected_leaf_paths"]) == 2

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("release checker called doctrinal producer")

    monkeypatch.setattr(doctrinal_documents, "project_doctrinal_document", forbidden)
    monkeypatch.setattr(doctrinal_documents, "_source_revision_events", forbidden)
    monkeypatch.setattr(doctrinal_documents.native_content, "project_content", forbidden)
    assert verify_release_v2(root, release, selection=selection) == {"status": "pass", "errors": []}


def test_native_entry_attribution_survives_accepted_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_release_accepted_sermons_prayers import accepted_fixture
    from ocd_kernel.tei.acceptance import promote_accepted_master
    from ocd_kernel.projection.categories import native_documents

    source_root, acceptance = accepted_fixture(tmp_path / "f", "sermons", native_attribution=True)
    promoted = promote_accepted_master(source_root, acceptance_path=acceptance, destination=tmp_path / "p")
    root = promoted.destination_root
    selection = _selection(_item(root, "sermons", "sermons", promoted.acceptance_path))
    release = tmp_path / "out"
    report = assemble_release_v2(root, release, selection=selection)
    assert report["status"] == "pass", report
    rows = _assert_configuration(release, report["configurations"][0])
    assert rows[0]["provenance"]["source_title"] == "Synthetic entry source"
    assert rows[0]["provenance"]["source_credit"] == "Synthetic source provider"
    assert rows[0]["provenance"]["source_url"] == "https://example.org/entry"
    assert rows[0]['primary_reference']['raw'] == rows[0]['primary_passage']
    assert rows[0]['primary_reference']['references'][0]['scripture']['normalized']
    assert all("source_credit" not in row["provenance"] for row in rows[1:])

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("release checker called attribution producer")

    monkeypatch.setattr(native_documents, "_entry_attribution", forbidden)
    monkeypatch.setattr(native_documents, "normalize_reference_record", forbidden)
    assert verify_release_v2(root, release, selection=selection) == {"status": "pass", "errors": []}


@pytest.mark.requires_local_artifacts
def test_commentary_attribution_survives_accepted_release(tmp_path, tmp_path_factory, monkeypatch):
    from tests.test_projection_commentary import _accepted_commentary_fixture
    from ocd_kernel.tei.acceptance import promote_accepted_master
    from ocd_kernel.projection.categories import commentary

    source_root, acceptance, _, _ = _accepted_commentary_fixture(
        tmp_path_factory, entry_attribution=True, explicit_target='Bible:John.3.16a-4.2b'
    )
    promoted = promote_accepted_master(source_root, acceptance_path=acceptance, destination=tmp_path / 'p')
    root = promoted.destination_root
    selection = _selection(_item(root, 'commentary', 'commentary', promoted.acceptance_path))
    release = tmp_path / 'out'
    report = assemble_release_v2(root, release, selection=selection)
    assert report['status'] == 'pass', report
    rows = _assert_configuration(release, report['configurations'][0])
    assert rows[0]['provenance']['source_title'] == 'Synthetic source work'
    assert rows[0]['provenance']['source_url'] == 'https://example.org/commentary-entry'
    assert rows[0]['provenance']['attribution_note'] == 'Synthetic author context'
    scope = rows[0]['locator']['scope']
    assert scope['raw'] == 'Bible:John.3.16a-4.2b'
    assert scope['source_label'] == 'John 3:16a–4:2b'
    assert scope['book_label'] == 'John'
    assert scope['english_book_name'] == 'John'
    assert scope['book_label_language'] == 'en'
    assert scope['normalization_status'] == 'explicit-target-syntax'
    assert scope['reference']['normalized'] == 'John.3.16a-John.4.2b'
    assert scope['reference']['start'] == {'book':'John', 'chapter':3, 'verse':'16a'}
    assert scope['reference']['end'] == {'book':'John', 'chapter':4, 'verse':'2b'}
    crossrefs = [ref for ref in rows[0]['references'] if ref.get('source_role') == 'scripture-cross-reference']
    assert len(crossrefs) == 1
    assert crossrefs[0]['label'] == 'Genesis 1:26–2:3'
    assert crossrefs[0]['source_target'] == 'Bible:Gen.1.26-2.3'
    assert crossrefs[0]['scripture']['normalized'] == 'Gen.1.26-Gen.2.3'
    assert all('attribution_note' not in row['provenance'] for row in rows[1:])

    def forbidden(*args, **kwargs):
        raise AssertionError('release checker called commentary attribution producer')

    monkeypatch.setattr(commentary, '_entry_attribution', forbidden)
    monkeypatch.setattr(commentary, 'normalize_explicit_target', forbidden)
    monkeypatch.setattr(commentary, '_source_scope_labels', forbidden)
    assert verify_release_v2(root, release, selection=selection) == {'status': 'pass', 'errors': []}


@pytest.mark.parametrize('target', ['John', 'John.3'])
@pytest.mark.requires_local_artifacts
def test_commentary_introductions_survive_accepted_release(tmp_path, tmp_path_factory, target):
    from tests.test_projection_commentary import _accepted_commentary_fixture
    from ocd_kernel.tei.acceptance import promote_accepted_master

    source_root, acceptance, _, _ = _accepted_commentary_fixture(tmp_path_factory, explicit_target=target, introduction=True)
    promoted = promote_accepted_master(source_root, acceptance_path=acceptance, destination=tmp_path / 'p')
    root = promoted.destination_root
    selection = _selection(_item(root, 'commentary', 'commentary', promoted.acceptance_path))
    release = tmp_path / 'out'
    report = assemble_release_v2(root, release, selection=selection)
    assert report['status'] == 'pass', report
    rows = _assert_configuration(release, report['configurations'][0])
    assert rows[0]['locator']['unit_role'] == 'introduction'
    reference = rows[0]['locator']['scope']['reference']
    assert reference['kind'] == ('book' if target == 'John' else 'chapter')
    assert reference['start']['verse'] is None
    assert reference['start']['chapter'] == (None if target == 'John' else 3)
    assert verify_release_v2(root, release, selection=selection) == {'status':'pass', 'errors':[]}


@pytest.mark.parametrize("category", [
    "sermons", "prayers", "poetry",
    *[pytest.param(category, marks=pytest.mark.requires_local_artifacts)
      for category in ("hymns", "liturgies", "catechisms", "doctrinal_documents", "reference_entries")],
])
@pytest.mark.parametrize("metadata_level", ["edition", "form"])
def test_remaining_accepted_category_release_connections(
    tmp_path: Path, category: str, metadata_level: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib
    from ocd_kernel.tei.acceptance import promote_accepted_master

    if category in {"sermons", "prayers"}:
        from tests.test_release_accepted_sermons_prayers import accepted_fixture
    elif category in {"hymns", "poetry", "liturgies"}:
        from tests.test_release_accepted_verse_services import accepted_fixture
    else:
        from tests.test_release_accepted_structured import accepted_fixture
    source_root, acceptance = accepted_fixture(tmp_path / "f", category)
    accepted_identity = _read_json(acceptance)["identity"]
    work_path = source_root / "library/works" / accepted_identity["work_id"] / "work.json"
    work = _read_json(work_path)
    form = next(item for item in work["textual_forms"]
                if item["textual_form_id"] == accepted_identity["textual_form_id"])
    edition = next(item for item in form["editions"]
                   if item["edition_id"] == accepted_identity["edition_id"])
    for field in ("category", "language"):
        value = edition.get(field, form.get(field))
        assert value
        if metadata_level == "form":
            form[field] = value
            edition.pop(field, None)
        else:
            edition[field] = value
            form.pop(field, None)
    _write_json(work_path, work)
    promoted = promote_accepted_master(source_root, acceptance_path=acceptance,
                                      destination=tmp_path / "p")
    root = promoted.destination_root
    selection = _selection(_item(root, category, category, promoted.acceptance_path))
    before = _files(root)
    release = tmp_path / "out"
    report = assemble_release_v2(root, release, selection=selection)
    assert report["status"] == "pass", report
    assert report["accounting"]["failed"] == report["accounting"]["excluded"] == 0
    assert report["accounting"]["included"] + report["accounting"]["warned"] == 1
    assert len(report["configurations"]) == 1
    config = report["configurations"][0]
    assert config["category"] == category
    rows = _assert_configuration(release, config)
    assert rows and all(row["category"] == category for row in rows)
    identity = _read_json(promoted.acceptance_path)["identity"]
    assert all(all(row[key] == identity[key] for key in
                   ("work_id", "textual_form_id", "edition_id")) for row in rows)
    assert _files(root) == before

    def forbidden_producer(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("independent release checker called category producer")

    module = importlib.import_module(f"ocd_kernel.projection.categories.{category}")
    monkeypatch.setattr(module, f"project_accepted_{category}", forbidden_producer)
    if category == 'sermons':
        assert rows[0]['primary_reference']['raw'] == rows[0]['primary_passage']
        assert rows[0]['primary_reference']['scripture']['normalized']
        monkeypatch.setattr(module, 'normalize_reference_record', forbidden_producer)
    assert verify_release_v2(root, release, selection=selection) == {
        "status": "pass", "errors": []
    }


def test_devotional_source_targets_survive_accepted_release(tmp_path, monkeypatch):
    from lxml import etree
    from tests import test_projection_quotations as fixtures
    from ocd_kernel.tei.acceptance import promote_accepted_master

    fixture_root = tmp_path / 'synthetic-fixtures'
    copied = fixture_root / 'tests/fixtures/library-pipeline/categories/devotionals'
    shutil.copytree(ROOT / 'tests/fixtures/library-pipeline/categories/devotionals', copied)
    source = etree.parse(str(copied / 'retained.xml'))
    source_ref = source.xpath('//scripRef')[0]
    source_ref.set('osisRef', 'Josh.5.12')
    source_ref.getparent().set('type', 'primary-reading')
    source_ref.set('href', 'https://example.org/source#reading-one')
    body_reference = etree.SubElement(source.xpath('//p')[0], 'scripRef', osisRef='John.1.1')
    body_reference.text = ' John 1:1'
    source.write(str(copied / 'retained.xml'), encoding='utf-8')
    master = etree.parse(str(copied / 'master.tei.xml'))
    ref = master.xpath('//t:body//t:ref', namespaces={'t': 'http://www.tei-c.org/ns/1.0'})[0]
    ref.set('cRef', source_ref.get('osisRef'))
    ref.getparent().getparent().set('type', 'primary-reading')
    ref.set('target', source_ref.get('href'))
    paragraph = master.xpath('//t:body/t:div/t:p', namespaces={'t': 'http://www.tei-c.org/ns/1.0'})[0]
    etree.SubElement(paragraph, '{http://www.tei-c.org/ns/1.0}ref', type='citation', cRef='John.1.1').text = ' John 1:1'
    master.write(str(copied / 'master.tei.xml'), encoding='utf-8')
    monkeypatch.setattr(fixtures, 'ROOT', fixture_root)
    root, acceptance = fixtures.accepted_fixture(tmp_path / 'authority', 'devotionals')
    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path / 'promoted')
    root = promoted.destination_root
    selection = _selection(_item(root, 'devotional', 'devotionals', promoted.acceptance_path))
    release = tmp_path / 'target-release'
    report = assemble_release_v2(root, release, selection=selection)
    assert report['status'] == 'pass'
    rows = _assert_configuration(release, report['configurations'][0])
    assert rows[0]['readings'][0]['role'] == 'primary'
    reference = rows[0]['readings'][0]['source_reference']
    assert reference['cRef'] == 'Josh.5.12'
    assert reference['target'] == 'https://example.org/source#reading-one'
    assert reference['scripture']['normalized'] == 'Josh.5.12'
    assert reference['normalization_attribute'] == 'cRef'
    assert len(rows[0]['divisions'][0]['references']) == 1
    assert rows[0]['divisions'][0]['references'][0]['raw'] == 'John 1:1'
    assert rows[0]['divisions'][0]['references'][0]['scripture']['normalized'] == 'John.1.1'
    from ocd_kernel.projection.categories import devotionals
    def forbidden(*args, **kwargs):
        raise AssertionError('release checker called reference producer')
    monkeypatch.setattr(devotionals, 'normalize_reference_record', forbidden)
    assert verify_release_v2(root, release, selection=selection) == {'status': 'pass', 'errors': []}


@pytest.mark.parametrize('source_location', ['Page 4', 'raw/private/prayer.xml'])
def test_prayer_source_references_survive_accepted_release(tmp_path, monkeypatch, source_location):
    from lxml import etree
    from tests import test_release_accepted_sermons_prayers as fixtures
    from ocd_kernel.tei.acceptance import promote_accepted_master

    copied_root = tmp_path / 'synthetic-fixtures'
    copied = copied_root / 'prayers'
    shutil.copytree(ROOT / 'tests/fixtures/library-pipeline/categories/prayers', copied)
    manifest = _read_json(copied / 'manifest.json')
    case = manifest['cases'][0]
    source_path = copied / case['retained_file']
    source = _read_json(source_path)
    fragment = '<a href="https://example.org/psalm#1" data-reference="Ps.1.1-3">Psalm 1:1–3</a>'
    source['selected_units'][0]['synthetic_attribution'] = {
        'source_title': 'Explicit prayer source',
        'source_location': source_location,
        'source_url': 'https://example.org/prayer-source',
    }
    for field in ('raw_fragment', 'body_fragment'):
        source['selected_units'][0][field] += fragment
    source['fixture_note'] = 'Synthetic reference extension for acceptance API testing, not historical source evidence.'
    _write_json(source_path, source)
    master_path = copied / case['tei_file']
    tree = etree.parse(str(master_path))
    paragraph = tree.xpath('//t:body/t:div/t:p', namespaces={'t': 'http://www.tei-c.org/ns/1.0'})[0]
    ref = etree.SubElement(paragraph, '{http://www.tei-c.org/ns/1.0}ref', type='scripture', cRef='Ps.1.1-3', target='https://example.org/psalm#1')
    ref.text = 'Psalm 1:1–3'
    unit = paragraph.getparent()
    attribution = etree.SubElement(unit, '{http://www.tei-c.org/ns/1.0}note', type='source-attribution')
    for field in ('source_title', 'source_location'):
        etree.SubElement(attribution, '{http://www.tei-c.org/ns/1.0}seg', type=field.replace('_', '-')).text = source['selected_units'][0]['synthetic_attribution'][field]
    etree.SubElement(attribution, '{http://www.tei-c.org/ns/1.0}ref', type='source-url', target=source['selected_units'][0]['synthetic_attribution']['source_url']).text = 'Prayer source'
    tree.write(str(master_path), encoding='utf-8')
    monkeypatch.setattr(fixtures, 'FIXTURE_ROOT', copied_root)
    source_root, acceptance = fixtures.accepted_fixture(tmp_path / 'authority', 'prayers')
    promoted = promote_accepted_master(source_root, acceptance_path=acceptance, destination=tmp_path / 'promoted')
    root = promoted.destination_root
    selection = _selection(_item(root, 'prayer', 'prayers', promoted.acceptance_path))
    release = tmp_path / 'release'
    report = assemble_release_v2(root, release, selection=selection)
    assert report['status'] == 'pass', report
    rows = _assert_configuration(release, report['configurations'][0])
    reference = rows[0]['divisions'][0]['references'][0]
    assert reference['raw'] == 'Psalm 1:1–3'
    assert reference['target'] == 'https://example.org/psalm#1'
    assert reference['cRef'] == 'Ps.1.1-3'
    assert reference['normalization_attribute'] == 'cRef'
    assert reference['scripture']['normalized'] == 'Ps.1.1-Ps.1.3'
    from build.tools.audit_ref_coverage import audit_release
    audit = audit_release(root, release, selection, lambda ref: (True, ''))
    assert any(item['reference'] == 'Ps.1.1-Ps.1.3' for item in audit['references'])
    unknown = audit_release(root, release, selection, lambda ref: (True, 'index unavailable'))
    assert unknown['status'] == 'incomplete'
    assert all(item['outcome'] == 'unverified' for item in unknown['references'])
    for key, value in source['selected_units'][0]['synthetic_attribution'].items():
        if key == 'source_location' and source_location.startswith('raw/'):
            assert key not in rows[0]['provenance']
        else:
            assert rows[0]['provenance'][key] == value
    transform_path = release / 'internal/public-row-transforms/prayer.json'
    if source_location.startswith('raw/'):
        from ocd_kernel.release.public_rows import restore_private_source_locations
        artifact = _read_json(transform_path)
        assert restore_private_source_locations(rows, artifact, item_id='prayer')[0]['provenance']['source_location'] == source_location
        from ocd_kernel.release import resume as release_resume
        original_write = release_resume.atomic_json

        def interrupted_receipt(path, value):
            if path.as_posix().endswith('internal/projection-receipts/prayer.json'):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'partial receipt')
                raise OSError('simulated receipt write failure')
            return original_write(path, value)

        failed_release = tmp_path / 'failed-release'
        with monkeypatch.context() as failure_patch:
            failure_patch.setattr(release_resume, 'atomic_json', interrupted_receipt)
            with pytest.raises(PipelineError, match="infrastructure failed"):
                assemble_release_v2(root, failed_release, selection=selection)
        assert not failed_release.exists()
        diagnostic = next(failed_release.parent.glob(f".{failed_release.name}-*"))
        assert not (diagnostic / 'internal/checks/build-ready.json').exists()
    else:
        assert not transform_path.exists()
    assert all('source_title' not in row['provenance'] for row in rows[1:])
    from ocd_kernel.projection.categories import prayers

    def forbidden(*args, **kwargs):
        raise AssertionError('release checker called prayer attribution producer')

    monkeypatch.setattr(prayers, '_entry_attribution', forbidden)
    monkeypatch.setattr(prayers, 'normalize_reference_record', forbidden)
    assert verify_release_v2(root, release, selection=selection) == {'status': 'pass', 'errors': []}
    if source_location.startswith('raw/'):
        artifact = _read_json(transform_path)
        artifact['omissions'][0]['field'] = 'text'
        _write_json(transform_path, artifact)
        assert verify_release_v2(root, release, selection=selection)['status'] == 'fail'
        transform_path.unlink()
        assert verify_release_v2(root, release, selection=selection)['status'] == 'fail'


@pytest.mark.requires_local_artifacts
def test_topical_explicit_label_survives_accepted_release(tmp_path, monkeypatch):
    from lxml import etree
    from tests import test_projection_topical_indexes as fixtures
    from ocd_kernel.tei.acceptance import promote_accepted_master
    copied = tmp_path / 'synthetic-topics'
    shutil.copytree(fixtures.F, copied)
    case = fixtures.CASES[0]
    retained = copied / case['retained_file']
    records = [json.loads(line) for line in retained.read_text(encoding='utf-8').splitlines()]
    records[0]['definitions'][0] = 'Explicit heading ' + records[0]['definitions'][0]
    records[0]['alternative_labels'] = ['Alternate label', 'Another label']
    retained.write_text(''.join(json.dumps(r)+'\n' for r in records), encoding='utf-8')
    master = copied / case['tei_file']
    tree = etree.parse(str(master))
    topic_unit = tree.xpath('//t:body/t:div', namespaces=fixtures.NS)[0]
    for index, text in enumerate(records[0]['alternative_labels'], 1):
        alternate = etree.Element('{'+fixtures.NS['t']+'}head', type='alternate')
        alternate.text = text
        topic_unit.insert(index, alternate)
    item = tree.xpath('//t:body/t:div/t:list/t:item', namespaces=fixtures.NS)[0]
    label = etree.Element('{'+fixtures.NS['t']+'}label')
    label.text = 'Explicit heading'
    label.tail = ' ' + (item.text or '')
    item.text = None
    item.insert(0, label)
    tree.write(str(master), encoding='utf-8')
    monkeypatch.setattr(fixtures, 'F', copied)
    source, acceptance = fixtures.accepted_topic_fixture(tmp_path / 'authority')
    promoted = promote_accepted_master(source, acceptance_path=acceptance, destination=tmp_path / 'promoted')
    root = promoted.destination_root
    selection = _selection(_item(root, 'topic', 'topical_indexes', promoted.acceptance_path))
    release = tmp_path / 'release'
    report = assemble_release_v2(root, release, selection=selection)
    assert report['status'] == 'pass', report
    rows = _assert_configuration(release, report['configurations'][0])
    assert rows[0]['items'][0]['label'] == 'Explicit heading'
    assert rows[0]['alternative_topics'] == records[0]['alternative_labels']
    assert [row['topic'] for row in rows] == [record['term'] for record in records]
    for row, record in zip(rows, records, strict=True):
        assert len(row['items']) == len(record['definitions'])
        for exported, source_text in zip(row['items'], record['definitions'], strict=True):
            assert exported['text'] == ' '.join(source_text.split())
            _, separator, reference_run = source_text.partition('--')
            expected = ([{'kind': 'source-reference-run',
                          'label': ' '.join(reference_run.split()), 'target': None}]
                        if separator else [])
            assert exported['references'] == expected
    assert verify_release_v2(root, release, selection=selection) == {'status': 'pass', 'errors': []}
