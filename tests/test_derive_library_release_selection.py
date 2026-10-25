"""Focused checks for current, sidecar-derived release selection."""

from __future__ import annotations

import hashlib
from dataclasses import replace
import importlib
import json
from pathlib import Path

import pytest

from build.tools import derive_library_release_selection as tool
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import Edition, Work
from ocd_kernel.release.selection import validate_release_selection


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _fixture(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    works = root / "library/works"
    accepted_work = works / "accepted-work"
    ocr_work = works / "ocr-work"
    edition_root = accepted_work / "forms/english/editions/electronic"
    master = edition_root / "master.tei.xml"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"<TEI>retained text</TEI>")
    accepted = edition_root / "acceptance.json"
    acceptance = {
        "identity": {
            "work_id": "accepted-work",
            "textual_form_id": "english",
            "edition_id": "electronic",
            "acquisition_id": "source-member",
        },
        "promotion": {
            "status": "promoted",
            "master": {"sha256": hashlib.sha256(master.read_bytes()).hexdigest()},
        },
    }
    _json(accepted, acceptance)
    _json(accepted_work / "work.json", {"work_id": "accepted-work"})
    _json(ocr_work / "work.json", {"work_id": "ocr-work"})
    _json(accepted_work / "state.json", {
        "work_id": "accepted-work",
        "targets": [{
            "target_type": "edition", "target_id": "electronic", "stage": "accepted",
            "evidence": [master.relative_to(root).as_posix(), accepted.relative_to(root).as_posix()],
        }],
    })
    _json(ocr_work / "state.json", {"work_id": "ocr-work"})
    ticket = root / "plans/2026-08-31-sample-first-library-verification/issues/37c-001-ocr-work.md"
    ticket.parent.mkdir(parents=True)
    ticket.write_text("**Publishing status:** OCR / Outside Publishing Scope\n", encoding="utf-8")
    edition = Edition(
        work_id="accepted-work",
        textual_form_id="english",
        edition_id="electronic",
        title="Electronic",
        path=master,
        record={"category": "prose", "acquisition_ids": ["source-member"]},
    )
    monkeypatch.setattr(
        tool,
        "discover_library",
        lambda _root: (
            Work("accepted-work", "Accepted", accepted_work / "work.json", {}, (edition,)),
            Work("ocr-work", "OCR", ocr_work / "work.json", {}, ()),
        ),
    )
    monkeypatch.setattr(tool, "validate_work_cohort", lambda *_args: {})
    prior = validate_release_selection(
        {
            "schema_version": "2.0",
            "release_id": "previous-rehearsal",
            "items": [
                {
                    "item_id": "accepted-work--electronic",
                    "work_id": "accepted-work",
                    "category": "prose",
                    "acceptance_path": accepted.relative_to(root).as_posix(),
                    "license": "CC BY 4.0",
                }
            ],
            "work_coverage": {
                "included_work_ids": ["accepted-work"],
                "excluded_works": [{"work_id": "ocr-work", "reason": tool.OCR_REASON}],
            },
        }
    )
    prior_path = root / "previous-selection.json"
    _json(prior_path, prior)
    return prior_path, master


def test_notice_decision_receipt_uses_configured_logical_storage_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    storage = tmp_path.parent / (tmp_path.name + "-durable-library")
    physical = storage / "reports/decisions.json"
    _json(physical, json.loads(prior.read_bytes()))
    _json(tmp_path / ".ocd-storage.json", {"library_root": str(storage)})

    selection, receipt = tool.derive_selection(
        tmp_path, release_id="fresh-rehearsal", notice_selection=physical,
    )

    assert len(selection["items"]) == 1
    assert receipt["notice_selection"] == {
        "path": "reports/decisions.json",
        "sha256": hashlib.sha256(physical.read_bytes()).hexdigest(),
    }


def test_current_cohort_and_promoted_text_derive_without_count_constants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    selection, receipt = tool.derive_selection(
        tmp_path, release_id="fresh-rehearsal", notice_selection=prior
    )
    assert selection["work_coverage"] == {
        "included_work_ids": ["accepted-work"],
        "excluded_works": [{"work_id": "ocr-work", "reason": tool.OCR_REASON}],
    }
    assert len(selection["items"]) == receipt["selected_text_items"] == 1
    assert receipt["included_works_without_selected_text"] == 0
    assert selection["items"][0]["category"] == "prose"
    assert selection["items"][0]["license"] == "CC BY 4.0"
    assert receipt["item_bindings"][0]["license"] == "CC BY 4.0"
    assert {entry["work_id"] for entry in receipt["work_bindings"]} == {
        "accepted-work", "ocr-work"
    }
    assert {
        entry["work_id"] for entry in receipt["work_bindings"] if entry["ocr_excluded"]
    } == {"ocr-work"}


def test_textual_form_category_is_inherited_when_edition_category_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    accepted, ocr = tool.discover_library(tmp_path)
    edition = accepted.editions[0]
    inherited = Edition(
        work_id=edition.work_id,
        textual_form_id=edition.textual_form_id,
        edition_id=edition.edition_id,
        title=edition.title,
        path=edition.path,
        record={key: value for key, value in edition.record.items() if key != "category"},
    )
    work = Work(
        work_id=accepted.work_id,
        title=accepted.title,
        path=accepted.path,
        record={
            "textual_forms": [
                {"textual_form_id": "english", "category": "hymns"}
            ]
        },
        editions=(inherited,),
    )
    monkeypatch.setattr(tool, "discover_library", lambda _root: (work, ocr))

    selection, _receipt = tool.derive_selection(
        tmp_path, release_id="fresh-rehearsal", notice_selection=prior
    )

    assert selection["items"][0]["category"] == "hymns"


@pytest.mark.parametrize("source_category,release_category", [
    ("doctrinal-documents", "doctrinal_documents"),
    ("reference-entries", "reference_entries"),
    ("topical-indexes", "topical_indexes"),
    ("doctrinal_documents", "doctrinal_documents"),
    ("reference_entries", "reference_entries"),
    ("topical_indexes", "topical_indexes"),
])
def test_sidecar_category_routes_to_release_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    source_category: str, release_category: str,
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    accepted, ocr = tool.discover_library(tmp_path)
    edition = replace(accepted.editions[0], record={
        **accepted.editions[0].record, "category": source_category,
    })
    monkeypatch.setattr(tool, "discover_library", lambda _root: (
        replace(accepted, editions=(edition,)), ocr,
    ))

    selection, receipt = tool.derive_selection(
        tmp_path, release_id="fresh-rehearsal", notice_selection=prior,
    )

    assert selection["items"][0]["category"] == release_category
    assert receipt["item_bindings"][0]["category"] == release_category
    assert edition.record["category"] == source_category
    adapter = importlib.import_module(f"ocd_kernel.projection.categories.{release_category}")
    assert callable(getattr(adapter, f"project_accepted_{release_category}"))


def test_exclusion_uses_original_coverage_without_historical_ocr_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    ticket = next((tmp_path / "plans").rglob("37c-001-ocr-work.md"))
    ticket.write_text("**Publishing status:** Included\n", encoding="utf-8")
    selection, receipt = tool.derive_selection(tmp_path, release_id="fresh-rehearsal", notice_selection=prior)
    assert selection["work_coverage"]["excluded_works"] == [{"work_id": "ocr-work", "reason": tool.OCR_REASON}]
    assert receipt["work_exclusion_reasons"] == {"ocr-work": tool.OCR_REASON}


def test_changed_master_rejects_promoted_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior, master = _fixture(tmp_path, monkeypatch)
    master.write_bytes(b"changed after acceptance")
    with pytest.raises(PipelineError, match="promoted master SHA-256 differs"):
        tool.derive_selection(tmp_path, release_id="fresh-rehearsal", notice_selection=prior)


def test_prior_public_notice_is_preserved_and_cannot_lose_its_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    old = json.loads(prior.read_text(encoding="utf-8"))
    binding = {
        "source_path": "sources/structured-text/accepted-work/README.source.md",
        "source_sha256": "a" * 64,
        "notice_path": "data/structured-text/README.md",
        "notice_sha256": "b" * 64,
    }
    old["items"][0].pop("work_id")
    old["items"][0]["public_notices"] = [binding]
    _json(prior, old)
    checked = []
    monkeypatch.setattr(
        tool, "notice_texts_for_item", lambda _root, item, _acceptance: checked.append(item["item_id"])
    )
    selection, _receipt = tool.derive_selection(
        tmp_path, release_id="fresh-rehearsal", notice_selection=prior
    )
    assert selection["items"][0]["public_notices"] == [binding]
    assert checked == ["accepted-work--electronic"]

    acceptance = tmp_path / selection["items"][0]["acceptance_path"]
    record = json.loads(acceptance.read_text(encoding="utf-8"))
    record["promotion"]["status"] = "pending"
    _json(acceptance, record)
    with pytest.raises(PipelineError, match="prior rights decisions lost selected text"):
        tool.derive_selection(tmp_path, release_id="fresh-rehearsal", notice_selection=prior)


@pytest.mark.parametrize("legacy_identity", [False, True])
def test_prior_exclusion_is_preserved_and_bound_without_selecting_held_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy_identity: bool,
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    old = json.loads(prior.read_text(encoding="utf-8"))
    old["items"][0].pop("license")
    old["items"][0]["exclude_reason"] = "Held pending source-rights review"
    if legacy_identity:
        old["items"][0].pop("work_id")
    _json(prior, old)

    selection, receipt = tool.derive_selection(
        tmp_path, release_id="fresh-rehearsal", notice_selection=prior,
    )

    assert selection["items"][0]["exclude_reason"] == "Held pending source-rights review"
    assert receipt["item_bindings"][0]["exclude_reason"] == "Held pending source-rights review"
    assert receipt["selected_text_items"] == receipt["selected_text_work_count"] == 0
    assert receipt["excluded_text_items"] == receipt["included_works_without_selected_text"] == 1
    assert receipt["categories"] == {}


def test_identity_only_non_ocr_work_is_preserved_as_included(tmp_path, monkeypatch):
    prior, _ = _fixture(tmp_path, monkeypatch)
    original = tool.discover_library(tmp_path)
    home = tmp_path / "library/works/container-work"
    _json(home / "work.json", {"work_id": "container-work"})
    _json(home / "state.json", {"work_id": "container-work", "targets": []})
    container = Work("container-work", "Source-attested container", home / "work.json", {}, ())
    monkeypatch.setattr(tool, "discover_library", lambda _root: original + (container,))
    old = json.loads(prior.read_text())
    old["work_coverage"]["included_work_ids"].append("container-work")
    _json(prior, old)
    selection, receipt = tool.derive_selection(tmp_path, release_id="new", notice_selection=prior)
    assert "container-work" in selection["work_coverage"]["included_work_ids"]
    assert "container-work" not in receipt["work_exclusion_reasons"]
    assert receipt["included_works_without_selected_text"] == 1


@pytest.mark.parametrize("damage", ["absent", "missing", "ambiguous"])
def test_missing_or_ambiguous_exclusion_coverage_fails_closed(tmp_path, monkeypatch, damage):
    prior, _ = _fixture(tmp_path, monkeypatch)
    old = json.loads(prior.read_text())
    if damage == "absent":
        old.pop("work_coverage")
        old["items"][0].pop("work_id")
    elif damage == "missing":
        old["work_coverage"]["excluded_works"] = []
    else:
        old["work_coverage"]["included_work_ids"].append("ocr-work")
    _json(prior, old)
    with pytest.raises(PipelineError, match="work_coverage"):
        tool.derive_selection(tmp_path, release_id="new", notice_selection=prior)


def test_unassigned_category_is_allowed_only_for_an_explicitly_excluded_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    accepted, ocr = tool.discover_library(tmp_path)
    edition = accepted.editions[0]
    unclassified = replace(
        edition,
        record={key: value for key, value in edition.record.items() if key != "category"},
    )
    monkeypatch.setattr(tool, "discover_library", lambda _root: (
        replace(accepted, editions=(unclassified,)), ocr,
    ))

    with pytest.raises(PipelineError, match="promoted edition has no exact category"):
        tool.derive_selection(tmp_path, release_id="fresh-rehearsal", notice_selection=prior)

    old = json.loads(prior.read_text(encoding="utf-8"))
    old["items"][0].pop("license")
    old["items"][0].update(category="unassigned", exclude_reason="Held pending review")
    _json(prior, old)

    selection, receipt = tool.derive_selection(
        tmp_path, release_id="fresh-rehearsal", notice_selection=prior,
    )

    assert selection["items"][0]["category"] == "unassigned"
    assert selection["items"][0]["exclude_reason"] == "Held pending review"
    assert receipt["selected_text_items"] == 0
    assert receipt["categories"] == {}


@pytest.mark.parametrize("notices", [[], [{
    "source_path": "sources/structured-text/accepted-work/README.source.md",
    "source_sha256": "a" * 64,
    "notice_path": "data/structured-text/README.md",
    "notice_sha256": "b" * 64,
}]])
def test_prior_exclusion_cannot_also_bind_public_notices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, notices: list[dict[str, str]],
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    old = json.loads(prior.read_text(encoding="utf-8"))
    old["items"][0].pop("license")
    old["items"][0].update(exclude_reason="Held", public_notices=notices)
    _json(prior, old)

    expected = "cannot bind notices to an excluded item" if notices else "public_notices.*non-empty"
    with pytest.raises(PipelineError, match=expected):
        tool.derive_selection(tmp_path, release_id="fresh-rehearsal", notice_selection=prior)


@pytest.mark.parametrize("field,value", [
    ("item_id", "accepted-work--another-edition"),
    ("work_id", "another-work"),
])
def test_prior_exclusion_must_match_accepted_work_and_edition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str,
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    old = json.loads(prior.read_text(encoding="utf-8"))
    old["items"][0].pop("license")
    old["items"][0].update(exclude_reason="Held", **{field: value})
    _json(prior, old)

    with pytest.raises(PipelineError, match="prior exclusion item does not match its accepted edition"):
        tool.derive_selection(tmp_path, release_id="fresh-rehearsal", notice_selection=prior)


def test_prior_exclusion_cannot_follow_a_different_acceptance_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    old = json.loads(prior.read_text(encoding="utf-8"))
    acceptance = tmp_path / old["items"][0]["acceptance_path"]
    _json(tmp_path / "stale-acceptance.json", json.loads(acceptance.read_text(encoding="utf-8")))
    old["items"][0].pop("license")
    old["items"][0].update(exclude_reason="Held", acceptance_path="stale-acceptance.json")
    _json(prior, old)

    with pytest.raises(PipelineError, match="prior exclusion acceptance path differs"):
        tool.derive_selection(tmp_path, release_id="fresh-rehearsal", notice_selection=prior)


@pytest.mark.parametrize("stale_state", ["pending", "missing", "undeclared"])
def test_prior_exclusion_cannot_lose_promoted_accepted_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stale_state: str,
) -> None:
    prior, _master = _fixture(tmp_path, monkeypatch)
    old = json.loads(prior.read_text(encoding="utf-8"))
    old["items"][0].pop("license")
    old["items"][0]["exclude_reason"] = "Held"
    _json(prior, old)
    acceptance = tmp_path / old["items"][0]["acceptance_path"]
    if stale_state == "pending":
        record = json.loads(acceptance.read_text(encoding="utf-8"))
        record["promotion"]["status"] = "pending"
        _json(acceptance, record)
    elif stale_state == "missing":
        acceptance.unlink()
    else:
        _accepted, ocr = tool.discover_library(tmp_path)
        monkeypatch.setattr(tool, "discover_library", lambda _root: (ocr,))

    expected = ("missing JSON sidecar" if stale_state == "missing" else
                "work_coverage differs" if stale_state == "undeclared" else "prior exclusions lost promoted accepted text")
    with pytest.raises(PipelineError, match=expected):
        tool.derive_selection(tmp_path, release_id="fresh-rehearsal", notice_selection=prior)

