import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_ensemble_compare import compare_ocr_files, compare_ocr_texts  # noqa: E402


TEST_TMP = REPO_ROOT / "tests" / "_tmp_ocr_ensemble_compare"


def _case_dir(name: str) -> Path:
    path = TEST_TMP / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_identical_ocr_files_produce_no_disagreement_records():
    result = compare_ocr_texts([("a", "Grace and peace."), ("b", "Grace and peace.")])

    assert result["counts"]["total_disagreements"] == 0
    assert result["disagreement_records"] == []


def test_whitespace_only_difference_is_classified():
    result = compare_ocr_texts([("a", "Grace and peace."), ("b", "Grace   and\npeace.")])

    assert [record["classification"] for record in result["disagreement_records"]] == ["whitespace-only"]


def test_punctuation_only_difference_is_classified():
    result = compare_ocr_texts([("a", "Grace, and peace."), ("b", "Grace and peace")])

    assert [record["classification"] for record in result["disagreement_records"]] == ["punctuation-only"]


def test_likely_ocr_confusion_is_classified_conservatively():
    result = compare_ocr_texts([("a", "modern mercy"), ("b", "modem mercy")])

    assert result["disagreement_records"][0]["classification"] == "likely OCR character confusion"


def test_content_disagreement_is_surfaced():
    result = compare_ocr_texts([("a", "Grace and peace."), ("b", "Judgement and exile.")])

    assert result["disagreement_records"][0]["classification"] == "content disagreement"


def test_html_report_escapes_text_safely():
    root = _case_dir("html_escape")
    a = root / "a.txt"
    b = root / "b.txt"
    html = root / "report.html"
    a.write_text("Grace <script>alert(1)</script>", encoding="utf-8")
    b.write_text("Grace safely", encoding="utf-8")

    compare_ocr_files([a, b], labels=["a", "b"], output_html=html)

    report = html.read_text(encoding="utf-8")
    assert "<script>alert" not in report
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in report


def test_json_output_includes_labels_counts_and_records():
    root = _case_dir("json_output")
    a = root / "a.txt"
    b = root / "b.txt"
    output_json = root / "report.json"
    a.write_text("Grace and peace.", encoding="utf-8")
    b.write_text("Grace and pieces.", encoding="utf-8")

    compare_ocr_files([a, b], labels=["first", "second"], output_json=output_json)

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["labels"] == ["first", "second"]
    assert payload["counts"]["source_count"] == 2
    assert payload["counts"]["total_disagreements"] == 1
    assert payload["disagreement_records"][0]["sources"]["first"] == "peace."
