import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib import review_state  # noqa: E402
from build.tools.text_confidence_report import build_confidence_report, write_confidence_reports  # noqa: E402


TEST_TMP = REPO_ROOT / "tests" / "_tmp_text_confidence_report"


def _case_dir(name: str) -> Path:
    path = TEST_TMP / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record(path: Path, resource_id: str = "sample-commentary") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "id": resource_id,
            "title": "Sample Commentary",
            "schema_type": "commentary",
            "schema_version": "2.2.0",
        },
        "data": [{"entry_id": f"{resource_id}.Gen.1.1", "commentary_text": "Grace and peace."}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _sidecar(path: Path, record_path: Path, confidence: dict[str, str]) -> Path:
    payload = review_state.empty_sidecar(
        record_path=str(record_path),
        record_resource_id="sample-commentary",
        record_checksum_sha256="0" * 64,
        parser_version_seen="parser@v1",
    )
    payload["confidence"].update(confidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_report_reads_confidence_axes_from_sidecar():
    root = _case_dir("axes")
    record = _record(root / "data" / "sample.json")
    sidecar = _sidecar(
        root / "review" / "state" / "sample.json",
        record,
        {
            "structural_fidelity": "machine-checked",
            "text_fidelity": "human-reviewed",
            "edition_provenance": "witness-compared",
        },
    )

    report = build_confidence_report(record, sidecar_path=sidecar)

    assert report["confidence_axes"]["text_fidelity"] == "human-reviewed"
    assert report["tier"] == "machine-checked"
    assert "witness_count" not in report


def test_unverified_sidecar_axes_drive_missing_evidence():
    root = _case_dir("missing")
    record = _record(root / "data" / "sample.json")
    sidecar = _sidecar(root / "review" / "state" / "sample.json", record, {})

    report = build_confidence_report(record, sidecar_path=sidecar)

    assert report["tier"] == "unverified"
    assert "text_fidelity remains unverified in the sidecar." in report["missing_evidence"]


def test_reference_grade_requires_all_sidecar_axes_reference_grade():
    root = _case_dir("reference")
    record = _record(root / "data" / "sample.json")
    sidecar = _sidecar(
        root / "review" / "state" / "sample.json",
        record,
        {
            "structural_fidelity": "reference-grade",
            "text_fidelity": "reference-grade",
            "edition_provenance": "reference-grade",
        },
    )

    report = build_confidence_report(record, sidecar_path=sidecar)

    assert report["tier"] == "reference-grade"
    assert report["blockers"] == []


def test_json_and_markdown_report_shape():
    root = _case_dir("write")
    record = _record(root / "data" / "sample.json")
    sidecar = _sidecar(root / "review" / "state" / "sample.json", record, {})
    json_path = root / "report.json"
    md_path = root / "report.md"

    write_confidence_reports(build_confidence_report(record, sidecar_path=sidecar), json_path, md_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")
    assert payload["resource_id"] == "sample-commentary"
    assert payload["tier"] == "unverified"
    assert "Confidence Axes" in markdown
    assert "sample-commentary" in markdown
