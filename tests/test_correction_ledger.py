import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.correction_ledger import (  # noqa: E402
    list_corrections_by_status,
    load_correction_ledger,
    render_ledger_html,
    validate_correction_ledger,
)


TEST_TMP = REPO_ROOT / "tests" / "_tmp_correction_ledger"


def _case_dir(name: str) -> Path:
    path = TEST_TMP / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record(**overrides) -> dict:
    record = {
        "correction_id": "corr-0001",
        "resource_id": "sample-commentary",
        "entry_id": "sample.Gen.1.1",
        "field": "commentary_text",
        "original_value": "THE0T0KOS",
        "proposed_value": "THEOTOKOS",
        "correction_type": "text",
        "reason": "OCR digit confusion.",
        "evidence_source": "scan page 10",
        "evidence_quote_or_locator": "p.10 line 4",
        "reviewer": "tester",
        "status": "proposed",
        "confidence": 0.92,
        "created_at": "2026-05-06T00:00:00+00:00",
        "updated_at": "2026-05-06T00:00:00+00:00",
    }
    record.update(overrides)
    return record


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    return path


def test_valid_ledger_loads():
    path = _write_jsonl(_case_dir("valid") / "ledger.jsonl", [_record()])

    records = load_correction_ledger(path)

    assert records[0].correction_id == "corr-0001"
    assert records[0].status == "proposed"


def test_duplicate_correction_id_fails():
    path = _write_jsonl(_case_dir("duplicate") / "ledger.jsonl", [_record(), _record()])

    with pytest.raises(ValueError, match="Duplicate correction_id: corr-0001"):
        load_correction_ledger(path)


def test_missing_required_field_fails():
    record = _record()
    del record["reason"]
    path = _write_jsonl(_case_dir("missing") / "ledger.jsonl", [record])

    with pytest.raises(ValueError, match="missing required fields: reason"):
        load_correction_ledger(path)


def test_invalid_status_fails():
    path = _write_jsonl(_case_dir("bad_status") / "ledger.jsonl", [_record(status="waiting")])

    with pytest.raises(ValueError, match="Invalid status"):
        load_correction_ledger(path)


def test_invalid_correction_type_fails():
    path = _write_jsonl(_case_dir("bad_type") / "ledger.jsonl", [_record(correction_type="rewrite")])

    with pytest.raises(ValueError, match="Invalid correction_type"):
        load_correction_ledger(path)


def test_list_by_status_works():
    path = _write_jsonl(
        _case_dir("status") / "ledger.jsonl",
        [_record(correction_id="corr-1", status="approved"), _record(correction_id="corr-2", status="rejected")],
    )

    records = list_corrections_by_status(path, "approved")

    assert [record.correction_id for record in records] == ["corr-1"]


def test_timezone_aware_timestamp_validation():
    path = _write_jsonl(_case_dir("naive_time") / "ledger.jsonl", [_record(created_at="2026-05-06T00:00:00")])

    with pytest.raises(ValueError, match="timezone-aware"):
        load_correction_ledger(path)


def test_html_rendering_escapes_values_safely():
    html = render_ledger_html([validate_correction_ledger(_write_jsonl(_case_dir("html") / "ledger.jsonl", [_record(proposed_value="<b>fixed</b>")]))[0]])

    assert "<b>fixed</b>" not in html
    assert "&lt;b&gt;fixed&lt;/b&gt;" in html
