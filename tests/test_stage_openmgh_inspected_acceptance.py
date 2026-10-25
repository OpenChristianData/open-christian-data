"""Focused gates for individually inspected openMGH acceptance staging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tools import stage_openmgh_inspected_acceptance as stage
from ocd_kernel.library._common import PipelineError


def test_only_receipted_inspected_batches_are_normalized() -> None:
    expected = {
        "openmgh-exclusive-pilot-20260926.json": 3,
        "openmgh-bsb830-inspected-batch-20260926.json": 11,
        "openmgh-bsb00000750-child-batch-20260926.json": 12,
        "openmgh-bsb752-inspected-batch-20260926.json": 12,
        "openmgh-bsb752-remaining-six-20260926.json": 6,
        "openmgh-bsb828-inspected-batch-20260926.json": 11,
    }
    for name, count in expected.items():
        batch = json.loads(
            (stage.ROOT / "plans/2026-09-22-source-preflight" / name).read_text(
                encoding="utf-8"
            )
        )
        assert len(batch["works"]) == count
        for item in batch["works"]:
            normalized = stage._normalize_entry(batch, item)
            assert normalized["candidate_sha256"]
            assert normalized["boundary_review_sha256"]
            assert normalized["source_path"].endswith(".xml")
            assert normalized["work_div_ordinal"] > 0


def test_bernald_uses_explicit_category_and_extracted_xml() -> None:
    route = stage._route(
        stage.ROOT,
        Path(
            "sources/openmgh-exclusive/"
            "bernald-avoiding-communion-with-excommunicates/"
            "acceptance-declaration.json"
        ),
        Path(
            "plans/2026-09-22-source-preflight/"
            "openmgh-bsb830-inspected-batch-20260926.json"
        ),
    )
    assert route.category == "prose"
    assert route.source.as_posix().endswith("/tei/bsb00000830.xml")
    assert route.archive.suffix == ".zip"
    assert route.source != route.archive
    assert route.batch_entry["work_div_ordinal"] == 16


def test_missing_category_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original_read = stage._read

    def without_category(path: Path) -> dict[str, object]:
        record = original_read(path)
        if path.name == "acceptance-declaration.json":
            record.pop("category")
        return record

    monkeypatch.setattr(stage, "_read", without_category)
    with pytest.raises(PipelineError, match="explicit per-work decision"):
        stage._route(
            stage.ROOT,
            Path(
                "sources/openmgh-exclusive/"
                "bernald-avoiding-communion-with-excommunicates/"
                "acceptance-declaration.json"
            ),
            Path(
                "plans/2026-09-22-source-preflight/"
                "openmgh-bsb830-inspected-batch-20260926.json"
            ),
        )


def test_unreceipted_scan_cannot_be_acceptance_batch() -> None:
    with pytest.raises(PipelineError, match="unrecognized inspected"):
        stage._normalize_entry(
            {"contract": "ocd-openmgh-exclusive-volume-scan-v1"},
            {"work_id": "speculative", "acceptance_status": "nonaccepted"},
        )


@pytest.mark.parametrize(
    ("batch_name", "work_id"),
    [
        (
            "openmgh-exclusive-pilot-20260926.json",
            "question-on-the-sacraments-of-heretics",
        ),
        ("openmgh-bsb00000750-child-batch-20260926.json", "passio-sancti-memorii"),
        ("openmgh-bsb752-inspected-batch-20260926.json", "actus-sancti-eremberti"),
        ("openmgh-bsb752-remaining-six-20260926.json", "vita-sancti-frodoberti"),
        ("openmgh-bsb828-inspected-batch-20260926.json", "wido-monk-letter-to-archbishop-of-milan"),
    ],
)
def test_other_inspected_batch_routes_require_a_declaration(
    monkeypatch: pytest.MonkeyPatch, batch_name: str, work_id: str
) -> None:
    batch_path = Path("plans/2026-09-22-source-preflight") / batch_name
    batch = json.loads((stage.ROOT / batch_path).read_text(encoding="utf-8"))
    entry = stage._normalize_entry(
        batch, next(item for item in batch["works"] if item["work_id"] == work_id)
    )
    accounting = json.loads(
        (
            Path(entry["candidate_root"]) / "package/source-accountability.json"
        ).read_text(encoding="utf-8")
    )
    declaration = {
        "contract": stage.DECLARATION_CONTRACT,
        "work_id": work_id,
        "category": "prose",
        "category_basis": "Individually reviewed source prose division.",
        "scope": (
            "The complete individually inspected work division in the extracted "
            "openMGH XML; every neighboring division remains outside this selection."
        ),
        "boundary_review_sha256": entry["boundary_review_sha256"],
        "source_div_c14n_sha256": accounting["source_div_c14n_sha256"],
    }
    original_read = stage._read

    def in_memory_declaration(path: Path) -> dict[str, object]:
        return (
            declaration
            if path.name == "acceptance-declaration.json"
            else original_read(path)
        )

    monkeypatch.setattr(stage, "_read", in_memory_declaration)
    route = stage._route(
        stage.ROOT,
        Path("sources/openmgh-exclusive") / work_id / "acceptance-declaration.json",
        batch_path,
    )
    assert route.source.as_posix() == entry["source_path"]
    assert route.archive.suffix == ".zip"
    assert route.batch_entry["work_div_ordinal"] == accounting["work_div_ordinal"]


def test_declaration_must_belong_to_its_work(monkeypatch: pytest.MonkeyPatch) -> None:
    original_read = stage._read
    canonical = (
        stage.ROOT
        / "sources/openmgh-exclusive/bernald-avoiding-communion-with-excommunicates/acceptance-declaration.json"
    )

    def misplaced_declaration(path: Path) -> dict[str, object]:
        if path.name == "acceptance-declaration.json":
            return original_read(canonical)
        return original_read(path)

    monkeypatch.setattr(stage, "_read", misplaced_declaration)
    with pytest.raises(PipelineError, match="exact work-local sidecar"):
        stage._route(
            stage.ROOT,
            Path("sources/openmgh-exclusive/another-work/acceptance-declaration.json"),
            Path(
                "plans/2026-09-22-source-preflight/openmgh-bsb830-inspected-batch-20260926.json"
            ),
        )


def test_752_batch_must_match_its_pinned_durable_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read = stage._read

    def in_memory_declaration(path: Path) -> dict[str, object]:
        if path.name == "acceptance-declaration.json":
            return {"contract": stage.DECLARATION_CONTRACT, "work_id": "actus-sancti-eremberti"}
        return original_read(path)

    original_sha = stage._sha

    def changed_batch_sha(path: Path) -> str:
        if path.name == "openmgh-bsb752-inspected-batch-20260926.json":
            return "0" * 64
        return original_sha(path)

    monkeypatch.setattr(stage, "_read", in_memory_declaration)
    monkeypatch.setattr(stage, "_sha", changed_batch_sha)
    with pytest.raises(PipelineError, match="exact durable receipt"):
        stage._route(
            stage.ROOT,
            Path("sources/openmgh-exclusive/actus-sancti-eremberti/acceptance-declaration.json"),
            Path("plans/2026-09-22-source-preflight/openmgh-bsb752-inspected-batch-20260926.json"),
        )


def test_828_batch_must_match_its_pinned_durable_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_sha = stage._sha

    def changed_batch_sha(path: Path) -> str:
        if path.name == "openmgh-bsb828-inspected-batch-20260926.json":
            return "0" * 64
        return original_sha(path)

    monkeypatch.setattr(stage, "_sha", changed_batch_sha)
    with pytest.raises(PipelineError, match="exact durable receipt"):
        stage._route(
            stage.ROOT,
            Path("sources/openmgh-exclusive/wido-monk-letter-to-archbishop-of-milan/acceptance-declaration.json"),
            Path("plans/2026-09-22-source-preflight/openmgh-bsb828-inspected-batch-20260926.json"),
        )
