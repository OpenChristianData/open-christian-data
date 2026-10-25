from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.assessment import (
    build_assessment_report,
    load_agent_assessment,
    load_human_review,
    render_assessment_report,
    validate_agent_assessment,
    validate_human_review,
    write_assessment_report,
)


WORK_ID = "assessment-fixture-work"
EDITION_ID = "assessment-fixture-edition"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _artifact(root: Path, name: str, content: bytes) -> dict[str, str]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "artifact_id": name.replace("/", "-").replace(".", "-"),
        "kind": "tei" if "tei" in name else "source",
        "path": name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "locator": "fixture-root",
    }


def _assessment_record(root: Path, *, assessment_id: str = "agent-a") -> dict[str, object]:
    source = _artifact(root, "source/source.xml", b"source fixture\n")
    tei = _artifact(root, "tei/master.tei.xml", b"<TEI>fixture</TEI>\n")
    return {
        "schema_version": "2.0",
        "assessment_id": assessment_id,
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "assessed_at": "2026-09-06T00:00:00Z",
        "agent": {"name": "fixture-agent", "version": "1"},
        "scope": {
            "kind": "edition",
            "reference": EDITION_ID,
            "description": "the selected fixture edition",
        },
        "artifacts": [source, tei],
        "citations": [],
        "coverage": {
            "completeness": "partial",
            "inspected": ["section-1"],
            "omitted": ["section-2"],
        },
        "outcome": "mixed",
        "summary": "The selected section is internally consistent.",
        "uncertainties": ["The omitted section was not inspected."],
        "issues": [
            {
                "issue_id": "issue-1",
                "severity": "warning",
                "statement": "Coverage is bounded to one section.",
                "evidence_refs": [source["artifact_id"]],
            }
        ],
    }


def _human_record(root: Path, *, review_id: str = "review-a") -> dict[str, object]:
    source = _artifact(root, "source/source.xml", b"source fixture\n")
    tei = _artifact(root, "tei/master.tei.xml", b"<TEI>fixture</TEI>\n")
    return {
        "schema_version": "2.0",
        "review_id": review_id,
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "reviewer": "synthetic reviewer",
        "reviewed_at": "2026-09-06T01:00:00Z",
        "record_origin": "synthetic-test",
        "synthetic": True,
        "decision_area": ["fidelity"],
        "scope": {
            "kind": "selected-portion",
            "reference": "section-1",
            "description": "one selected section of the fixture edition",
        },
        "artifacts": [source, tei],
        "citations": [],
        "coverage": {
            "completeness": "partial",
            "inspected": ["section-1"],
            "omitted": ["section-2"],
        },
        "result": "partially-confirmed",
        "summary": "The selected section was inspected in the synthetic fixture.",
        "uncertainties": ["The omitted section remains unreviewed."],
        "issues": [],
    }


def test_valid_assessment_and_synthetic_review_load_with_root(tmp_path: Path) -> None:
    assessment_path = tmp_path / "assessments" / "agent-a.json"
    review_path = tmp_path / "reviews" / "review-a.json"
    _write_json(assessment_path, _assessment_record(tmp_path))
    _write_json(review_path, _human_record(tmp_path))

    assessment = load_agent_assessment(assessment_path, root=tmp_path)
    review = load_human_review(review_path, root=tmp_path)

    assert assessment["outcome"] == "mixed"
    assert review["synthetic"] is True
    assert review["record_origin"] == "synthetic-test"


def test_artifact_digest_is_required_and_drift_is_rejected(tmp_path: Path) -> None:
    record = _assessment_record(tmp_path)
    missing_digest = copy.deepcopy(record)
    del missing_digest["artifacts"][0]["sha256"]  # type: ignore[index]
    with pytest.raises(PipelineError):
        validate_agent_assessment(missing_digest)

    path = tmp_path / "assessments" / "agent-a.json"
    _write_json(path, record)
    (tmp_path / "source" / "source.xml").write_bytes(b"changed\n")
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        load_agent_assessment(path, root=tmp_path)


def test_citation_only_agent_record_is_valid_without_artifact_binding(tmp_path: Path) -> None:
    record = _assessment_record(tmp_path)
    record["artifacts"] = []
    record["citations"] = [
        {
            "citation_id": "citation-1",
            "label": "source page",
            "url": "https://example.test/source",
            "locator": "section-1",
        }
    ]
    record["issues"] = [
        {
            "issue_id": "issue-1",
            "severity": "info",
            "statement": "The source citation is externally located.",
            "evidence_refs": ["citation-1"],
        }
    ]

    validated = validate_agent_assessment(record)

    assert validated["artifacts"] == []
    assert validated["citations"][0]["citation_id"] == "citation-1"  # type: ignore[index]


def test_partial_or_unknown_coverage_requires_explicit_omitted_scope(tmp_path: Path) -> None:
    record = _assessment_record(tmp_path)
    record["coverage"] = {
        "completeness": "partial",
        "inspected": ["section-1"],
        "omitted": [],
    }

    with pytest.raises(PipelineError):
        validate_agent_assessment(record)

    complete = _assessment_record(tmp_path)
    complete["coverage"] = {
        "completeness": "complete",
        "inspected": ["all"],
        "omitted": ["unreached-section"],
    }
    with pytest.raises(PipelineError):
        validate_agent_assessment(complete)


def test_artifact_and_citation_ids_must_be_disjoint(tmp_path: Path) -> None:
    record = _assessment_record(tmp_path)
    record["citations"] = [
        {
            "citation_id": record["artifacts"][0]["artifact_id"],  # type: ignore[index]
            "label": "same identifier is ambiguous",
            "url": "https://example.test/source",
        }
    ]

    with pytest.raises(PipelineError, match="must be disjoint"):
        validate_agent_assessment(record)


def test_human_record_origin_and_synthetic_marker_must_agree(tmp_path: Path) -> None:
    record = _human_record(tmp_path)
    record["record_origin"] = "human-asserted"
    with pytest.raises(PipelineError):
        validate_human_review(record)

    record = _human_record(tmp_path)
    record["synthetic"] = False
    with pytest.raises(PipelineError):
        validate_human_review(record)


def test_agent_record_cannot_claim_human_review(tmp_path: Path) -> None:
    record = _assessment_record(tmp_path)
    record["reviewer"] = "not allowed"

    with pytest.raises(PipelineError):
        validate_agent_assessment(record)


def test_report_preserves_partial_human_scope_and_never_decides_publication(
    tmp_path: Path,
) -> None:
    assessment_path = tmp_path / "assessments" / "agent-a.json"
    review_path = tmp_path / "reviews" / "review-a.json"
    _write_json(assessment_path, _assessment_record(tmp_path))
    _write_json(review_path, _human_record(tmp_path))

    report = build_assessment_report(
        tmp_path,
        assessment_paths=[assessment_path],
        review_paths=[review_path],
    )
    item = report["items"][0]  # type: ignore[index]

    assert item["agent_assessments"][0]["result"] == "mixed"  # type: ignore[index]
    assert item["human_reviews"][0]["coverage"]["completeness"] == "partial"  # type: ignore[index]
    assert item["flags"]["partial_or_unknown_human_review"] is True  # type: ignore[index]
    assert report["authority"]["acceptance"] == "unchanged"  # type: ignore[index]
    assert report["authority"]["publication"] == "unchanged"  # type: ignore[index]
    assert (
        item["human_reviews"][0]["human_authorship"] == "synthetic-test-record"  # type: ignore[index]
    )

    rendered = render_assessment_report(report)
    assert "Publication effect: unchanged." in rendered
    assert "synthetic-test-record" in rendered
    assert "section-2" in rendered


def test_report_is_deterministic_for_input_order(tmp_path: Path) -> None:
    first = tmp_path / "assessments" / "agent-a.json"
    second = tmp_path / "assessments" / "agent-b.json"
    _write_json(first, _assessment_record(tmp_path, assessment_id="agent-a"))
    second_record = _assessment_record(tmp_path, assessment_id="agent-b")
    _write_json(second, second_record)

    left = build_assessment_report(tmp_path, assessment_paths=[second, first])
    right = build_assessment_report(tmp_path, assessment_paths=[first, second])

    assert left == right
    assert render_assessment_report(left) == render_assessment_report(right)


def test_report_writer_is_canonical_and_does_not_create_reviews(tmp_path: Path) -> None:
    assessment_path = tmp_path / "assessments" / "agent-a.json"
    _write_json(assessment_path, _assessment_record(tmp_path))
    report = build_assessment_report(tmp_path, assessment_paths=[assessment_path])
    json_path = tmp_path / "out" / "report.json"
    markdown_path = tmp_path / "out" / "report.md"

    write_assessment_report(report, json_path=json_path, markdown_path=markdown_path)

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    assert markdown_path.read_text(encoding="utf-8").endswith("\n")
    assert not (tmp_path / "library" / "reviews").exists()


def test_citation_only_report_does_not_claim_artifact_verification(tmp_path: Path) -> None:
    path = tmp_path / "assessments" / "citation-only.json"
    record = _assessment_record(tmp_path, assessment_id="citation-only")
    record["artifacts"] = []
    record["citations"] = [
        {
            "citation_id": "citation-1",
            "label": "source page",
            "url": "https://example.test/source",
        }
    ]
    record["issues"] = []
    _write_json(path, record)

    report = build_assessment_report(tmp_path, assessment_paths=[path])
    rendered = render_assessment_report(report)

    assert report["artifact_hashes_verified"] is False
    assert report["verified_artifact_count"] == 0
    assert report["citations_not_verified"] == 1
    assert "Artifact hashes verified: false (0 artifact(s))." in rendered
