"""Tests for build/tools/render_ocr_disagreement_html.py."""

from __future__ import annotations

from pathlib import Path

from build.tools.render_ocr_disagreement_html import render_disagreement_html


HOCR_FIXTURE = """\
<!DOCTYPE html>
<html><body>
  <div class="ocr_page" id="page_12" title="bbox 0 0 1000 1500; ppageno 11">
    <span class="ocr_line" id="line_1" title="bbox 100 200 900 240">
      <span class="ocrx_word" title="bbox 100 200 300 240; x_wconf 90">AARON</span>
      <span class="ocrx_word" title="bbox 320 200 900 240; x_wconf 88">was prophet</span>
    </span>
  </div>
</body></html>
"""


def _hocr_path(tmp_path: Path) -> Path:
    p = tmp_path / "fixture_hocr.html"
    p.write_text(HOCR_FIXTURE, encoding="utf-8")
    return p


def _scans_manifest() -> dict:
    return {
        "resource_id": "schaff-herzog-encyclopedia",
        "manifest_version": "1.0.0",
        "manifest_checksum_sha256": None,
        "scans": [
            {
                "volume": 1,
                "page": 12,
                "image_url": "https://example.org/vol1-page12.jpg",
                "image_storage": "external_url",
                "provider": "Internet Archive",
            }
        ],
        "meta": {"created_at_utc": "2026-05-13T00:00:00+00:00", "created_by": "test"},
    }


def _record_with_5_entries() -> dict:
    entries = []
    for i in range(5):
        entries.append(
            {
                "entry_id": f"schaff-herzog.aaron-{i}",
                "term": "AARON",
                "alt_terms": [],
                "definition_blocks": ["AARON was prophet of Moses."],
                "scan_source": {
                    "volume": 1,
                    "page": 12,
                    "manifest_path": "sources/schaff-herzog-encyclopedia/scans_manifest.json",
                },
            }
        )
    return {
        "meta": {"id": "schaff-herzog-encyclopedia", "schema_type": "reference_entry"},
        "data": entries,
    }


def _warning(entry_id: str, surface: str = "AARON") -> dict:
    return {
        "producer": "ocr_scanner",
        "entry_id": entry_id,
        "code": "digit_in_letter",
        "evidence": {
            "surface": surface,
            "snippet": f"...{surface}...",
            "canonical_text": "AARON",
            "witness_text": "AAR0N",
            "suggested_replacement": "AARON",
        },
    }


def test_render_emits_five_disagreement_rows_with_image_and_text(tmp_path: Path) -> None:
    from build.lib.ocr_coordinates import read_hocr

    record = _record_with_5_entries()
    warnings = [_warning(e["entry_id"]) for e in record["data"]]
    coords = read_hocr(_hocr_path(tmp_path))

    html_output = render_disagreement_html(
        record, warnings, _scans_manifest(), coords, max_disagreements=5
    )

    # 5 rows
    assert html_output.count("<tr>") == 6  # header + 5
    assert "AARON" in html_output
    # Every row has the image + bbox
    assert html_output.count("bbox-overlay") == 5


def test_render_skips_entries_without_scan_source(tmp_path: Path) -> None:
    from build.lib.ocr_coordinates import read_hocr

    record = _record_with_5_entries()
    # Strip scan_source from 3 of them
    for entry in record["data"][:3]:
        entry.pop("scan_source")
    warnings = [_warning(e["entry_id"]) for e in record["data"]]
    coords = read_hocr(_hocr_path(tmp_path))

    html_output = render_disagreement_html(
        record, warnings, _scans_manifest(), coords, max_disagreements=10
    )

    # Only the 2 remaining entries with scan_source render
    assert html_output.count("<tr>") == 3  # header + 2
    assert "3 skipped" in html_output


def test_render_html_escapes_xss_payload(tmp_path: Path) -> None:
    from build.lib.ocr_coordinates import read_hocr

    record = _record_with_5_entries()
    # Inject XSS attempt into evidence
    xss = "<script>alert('xss')</script>"
    w = _warning(record["data"][0]["entry_id"])
    w["evidence"]["surface"] = xss
    w["evidence"]["canonical_text"] = xss
    coords = read_hocr(_hocr_path(tmp_path))

    html_output = render_disagreement_html(record, [w], _scans_manifest(), coords)

    assert "<script>alert" not in html_output
    assert "&lt;script&gt;alert" in html_output
