"""test_local_schaff_tesseract.py -- TDD tests for B2.3 parser.

Run: py -3 -m pytest tests/test_local_schaff_tesseract.py -v

Fixture files in tests/fixtures/local_schaff_tesseract/ are actual Tesseract
stdout output from the B2.2 probe pages (TEST-13). Generate them with:
  py -3 build/tools/generate_tess_fixtures.py
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "local_schaff_tesseract"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.local_schaff_tesseract import (  # noqa: E402
    CONFIG_HASH,
    LOCKED_LANG,
    LOCKED_PREPROCESSING,
    LOCKED_PSM,
    _parse_bbox,
    _parse_hocr,
    _parse_wconf,
    assemble_volume_json,
    is_article_heading,
    should_skip_page,
    write_sidecar,
)


# ---------------------------------------------------------------------------
# Config lock
# ---------------------------------------------------------------------------

def test_locked_psm():
    """PSM=1 locked at B2.2 (correct two-column order on 3/3 verifiable pages)."""
    assert LOCKED_PSM == 1


def test_locked_lang():
    """eng locked at B2.2 (eng+lat WER reference unavailable -- DjVu no form-feeds)."""
    assert LOCKED_LANG == "eng"


def test_locked_preprocessing():
    """raw locked at B2.2 (0.1pt below deskew=94.3, within 2pt simplicity threshold)."""
    assert LOCKED_PREPROCESSING == "raw"


def test_config_hash():
    """config_hash matches the sha256 computed at B2.2."""
    assert CONFIG_HASH == "69f7a4887aedad0e7158706cb3cf9ff212eff7bf5cc55f194ab65b484adc45ab"


_SAMPLE_HOCR = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head><title></title></head>
<body>
  <div class='ocr_page' id='page_1'
       title='image "/tmp/test.jpg"; bbox 0 0 5034 6959; ppageno 0'>
    <div class='ocr_carea' id='block_1_1' title='bbox 100 200 1200 260'>
      <p class='ocr_par' id='par_1_1' lang='eng' title='bbox 100 200 1200 260'>
        <span class='ocr_line' id='line_1_1'
              title='bbox 100 200 1200 228; baseline 0.002 -5; x_size 57.5; x_descenders 7.5; x_ascenders 13.5'>
          <span class='ocrx_word' id='word_1_1'
                title='bbox 100 200 400 226; x_wconf 97'>AARON,</span>
          <span class='ocrx_word' id='word_1_2'
                title='bbox 410 200 480 226; x_wconf 40'>the</span>
        </span>
      </p>
    </div>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# _parse_bbox / _parse_wconf helpers
# ---------------------------------------------------------------------------

def test_parse_bbox_standard():
    bbox = _parse_bbox("bbox 100 200 400 228")
    assert bbox == {"x": 100, "y": 200, "w": 300, "h": 28}


def test_parse_bbox_missing_returns_none():
    assert _parse_bbox("x_wconf 95") is None


def test_parse_wconf_present():
    assert _parse_wconf("bbox 10 20 50 40; x_wconf 87") == 87.0


def test_parse_wconf_absent_returns_none():
    assert _parse_wconf("bbox 10 20 50 40") is None


# ---------------------------------------------------------------------------
# _parse_hocr
# ---------------------------------------------------------------------------

def test_parse_hocr_image_size():
    _, _, image_size = _parse_hocr(_SAMPLE_HOCR)
    assert image_size == [5034, 6959]


def test_parse_hocr_block_count():
    _, blocks, _ = _parse_hocr(_SAMPLE_HOCR)
    assert len(blocks) == 1


def test_parse_hocr_block_bbox():
    _, blocks, _ = _parse_hocr(_SAMPLE_HOCR)
    assert blocks[0]["bbox"] == {"x": 100, "y": 200, "w": 1100, "h": 60}


def test_parse_hocr_line_text():
    _, blocks, _ = _parse_hocr(_SAMPLE_HOCR)
    assert blocks[0]["lines"][0]["text"] == "AARON, the"


def test_parse_hocr_word_confidence():
    _, blocks, _ = _parse_hocr(_SAMPLE_HOCR)
    words = blocks[0]["lines"][0]["words"]
    assert words[0]["confidence"] == 97.0
    assert words[0]["low_confidence"] is False
    assert words[1]["confidence"] == 40.0
    assert words[1]["low_confidence"] is True


def test_parse_hocr_word_bbox():
    _, blocks, _ = _parse_hocr(_SAMPLE_HOCR)
    assert blocks[0]["lines"][0]["words"][0]["bbox"] == {"x": 100, "y": 200, "w": 300, "h": 26}


def test_parse_hocr_confidence_mean():
    conf, _, _ = _parse_hocr(_SAMPLE_HOCR)
    # Two words: 97 and 40 -> mean 68.5
    assert conf == pytest.approx(68.5, abs=0.1)


def test_parse_hocr_empty_html():
    conf, blocks, image_size = _parse_hocr("")
    assert conf == 0.0
    assert blocks == []
    assert image_size == [0, 0]


def test_parse_hocr_line_metrics_extracted():
    """Line records carry x_size, baseline, x_descenders, x_ascenders from hOCR."""
    _, blocks, _ = _parse_hocr(_SAMPLE_HOCR)
    line = blocks[0]["lines"][0]
    assert line["x_size"] == pytest.approx(57.5, abs=0.01)
    assert line["x_descenders"] == pytest.approx(7.5, abs=0.01)
    assert line["x_ascenders"] == pytest.approx(13.5, abs=0.01)
    # baseline is [slope, intercept]
    assert line["baseline"] == [pytest.approx(0.002, abs=1e-4), pytest.approx(-5, abs=0.01)]


# ---------------------------------------------------------------------------
# write_sidecar
# ---------------------------------------------------------------------------

def test_write_sidecar_creates_file(tmp_path):
    """write_sidecar creates the sidecar file at the given path."""
    sidecar = tmp_path / "page_0001.oss-tesseract.json"
    write_sidecar(sidecar, {"confidence_mean": 94.2, "text": "test", "words": []})
    assert sidecar.exists()


def test_write_sidecar_valid_json(tmp_path):
    """write_sidecar output is parseable JSON with the written values."""
    sidecar = tmp_path / "page.json"
    write_sidecar(sidecar, {"confidence_mean": 88.5, "text": "hello", "words": []})
    parsed = json.loads(sidecar.read_text(encoding="utf-8"))
    assert parsed["confidence_mean"] == 88.5
    assert parsed["text"] == "hello"


def test_write_sidecar_overwrites_atomically(tmp_path):
    """write_sidecar overwrites an existing file (os.replace, not Path.rename)."""
    sidecar = tmp_path / "page.json"
    write_sidecar(sidecar, {"confidence_mean": 90.0, "text": "v1", "words": []})
    write_sidecar(sidecar, {"confidence_mean": 94.2, "text": "v2", "words": []})
    parsed = json.loads(sidecar.read_text(encoding="utf-8"))
    assert parsed["text"] == "v2"
    assert parsed["confidence_mean"] == 94.2


# ---------------------------------------------------------------------------
# should_skip_page
# ---------------------------------------------------------------------------

def test_should_skip_page_absent(tmp_path):
    """Returns False when sidecar does not exist."""
    assert should_skip_page(tmp_path / "nonexistent.json") is False


def test_should_skip_page_valid(tmp_path):
    """Returns True when sidecar exists with confidence_mean > 0."""
    sidecar = tmp_path / "page.json"
    write_sidecar(sidecar, {"confidence_mean": 93.5, "text": "ok", "words": []})
    assert should_skip_page(sidecar) is True


def test_should_skip_page_zero_confidence(tmp_path):
    """Returns False when sidecar has confidence_mean == 0 (broken prior run)."""
    sidecar = tmp_path / "page.json"
    write_sidecar(sidecar, {"confidence_mean": 0.0, "text": "", "words": []})
    assert should_skip_page(sidecar) is False


def test_should_skip_page_corrupt_json(tmp_path):
    """Returns False when sidecar exists but contains invalid JSON."""
    sidecar = tmp_path / "page.json"
    sidecar.write_text("{ not valid json", encoding="utf-8")
    assert should_skip_page(sidecar) is False


# ---------------------------------------------------------------------------
# is_article_heading (text-only, no fixtures required)
# ---------------------------------------------------------------------------

def test_heading_form1_inline():
    """Form 1: 'CAPS_TERM: body text on same line'."""
    assert is_article_heading("CHURCH ORDER: A term applied to ecclesiastical") is True


def test_heading_form2_standalone_colon():
    """Form 2: 'CAPS_TERM:' entire line with trailing colon."""
    assert is_article_heading("CHANDIEU:") is True


def test_heading_form3_standalone_allcaps():
    """Form 3: ALL-CAPS standalone line with >= 4 alpha chars."""
    assert is_article_heading("CHRISTIANITY") is True


def test_body_line_not_heading():
    """Body text starting lowercase is not a heading."""
    assert is_article_heading("the doctrine was established in the fourth") is False


def test_single_lowercase_word_not_heading():
    """Single lowercase word is not a heading."""
    assert is_article_heading("bibliography.") is False


def test_roman_numeral_section_not_heading():
    """Roman-numeral section header within article body is not a heading."""
    assert is_article_heading("I. History:") is False


def test_running_header_not_heading():
    """Standard running page header is excluded from heading detection."""
    assert is_article_heading("THE NEW SCHAFF-HERZOG") is False


def test_short_allcaps_not_heading():
    """ALL-CAPS with fewer than 4 alpha chars is not a Form 3 heading."""
    assert is_article_heading("THE") is False


def test_line_starting_with_two_caps_with_colon():
    """Two-or-more leading uppercase letters with colon matches."""
    assert is_article_heading("AB: short article") is True


def test_heading_with_comma_and_colon():
    """Headings with comma-separated sub-fields and colon."""
    assert is_article_heading("AUGUSTINE, AURELIUS: Bishop of Hippo") is True


def test_heading_form4_crossref():
    """Form 4: 'HEADWORD. See TARGET.' cross-reference article."""
    assert is_article_heading("GETHSEMANE. See JERUSALEM, V., 5.") is True


def test_heading_form4_crossref_multiword():
    """Form 4: multi-word headword cross-reference."""
    assert is_article_heading("EDEN, GARDEN OF. See PARADISE.") is True


def test_heading_form5_pronunciation_guide():
    """Form 5: 'HEADWORD, phonetic.' with lowercase stress-marked phonetic."""
    assert is_article_heading("GEZER, gi'zer.") is True


def test_form5_body_line_with_comma_not_heading():
    """Body text starting with caps + comma + plain lowercase is not a heading."""
    assert is_article_heading("PAUL, the apostle of the Gentiles") is False


@pytest.mark.skipif(
    not (FIXTURE_DIR / "vol_04_page_0480.txt").exists(),
    reason="Fixture not generated -- run build/tools/generate_tess_fixtures.py",
)
def test_heading_count_vol04_page0480():
    """All 3 article headings detected on vol 4 p.480 (D5 FN regression guard)."""
    text = (FIXTURE_DIR / "vol_04_page_0480.txt").read_text(encoding="utf-8")
    headings = [l.strip() for l in text.splitlines() if is_article_heading(l.strip())]
    assert len(headings) == 3, f"Expected 3 headings, got {len(headings)}: {headings}"


# ---------------------------------------------------------------------------
# assemble_volume_json
# ---------------------------------------------------------------------------

def _make_sidecar(vol_dir: Path, page_num: int, conf: float, text: str) -> None:
    sidecar = vol_dir / f"page_{page_num:04d}.oss-tesseract.json"
    write_sidecar(sidecar, {
        "page": page_num,
        "confidence_mean": conf,
        "word_count": len(text.split()),
        "text": text,
        "words": [],
    })


def test_assemble_creates_output_file(tmp_path):
    """assemble_volume_json writes the assembled JSON to out_dir/vol_NN.json."""
    vol_dir = tmp_path / "vol_01"
    vol_dir.mkdir()
    out_dir = tmp_path / "out"
    _make_sidecar(vol_dir, 1, 93.5, "Some text here")
    out_path = assemble_volume_json(1, vol_dir=vol_dir, out_dir=out_dir)
    assert out_path.exists()
    assert out_path.name == "vol_01.json"


def test_assemble_structure(tmp_path):
    """Assembled JSON has expected top-level keys and page list."""
    vol_dir = tmp_path / "vol_03"
    vol_dir.mkdir()
    out_dir = tmp_path / "out"
    _make_sidecar(vol_dir, 1, 92.0, "Page one")
    _make_sidecar(vol_dir, 2, 94.0, "Page two")
    data = json.loads(assemble_volume_json(3, vol_dir=vol_dir, out_dir=out_dir).read_text(encoding="utf-8"))
    assert data["volume"] == 3
    assert data["page_count"] == 2
    assert data["pages_with_data"] == 2
    assert len(data["pages"]) == 2
    assert data["config_hash"] == CONFIG_HASH
    assert "assembled_at" in data


def test_assemble_confidence_mean(tmp_path):
    """Volume confidence_mean is the mean of non-zero page means."""
    vol_dir = tmp_path / "vol_01"
    vol_dir.mkdir()
    out_dir = tmp_path / "out"
    _make_sidecar(vol_dir, 1, 90.0, "a")
    _make_sidecar(vol_dir, 2, 94.0, "b")
    data = json.loads(assemble_volume_json(1, vol_dir=vol_dir, out_dir=out_dir).read_text(encoding="utf-8"))
    assert data["confidence_mean"] == 92.0


def test_assemble_skips_zero_confidence(tmp_path):
    """Pages with confidence_mean==0 are included in pages list but excluded from mean."""
    vol_dir = tmp_path / "vol_01"
    vol_dir.mkdir()
    out_dir = tmp_path / "out"
    _make_sidecar(vol_dir, 1, 0.0, "")  # broken run
    _make_sidecar(vol_dir, 2, 90.0, "text")
    data = json.loads(assemble_volume_json(1, vol_dir=vol_dir, out_dir=out_dir).read_text(encoding="utf-8"))
    assert data["page_count"] == 2
    assert data["pages_with_data"] == 1
    assert data["confidence_mean"] == 90.0


def test_assemble_no_sidecars_raises(tmp_path):
    """assemble_volume_json raises ValueError when no sidecars exist."""
    vol_dir = tmp_path / "vol_01"
    vol_dir.mkdir()
    out_dir = tmp_path / "out"
    with pytest.raises(ValueError, match="No oss-tesseract sidecar"):
        assemble_volume_json(1, vol_dir=vol_dir, out_dir=out_dir)


def test_assemble_missing_vol_dir_raises(tmp_path):
    """assemble_volume_json raises FileNotFoundError when vol dir absent."""
    out_dir = tmp_path / "out"
    with pytest.raises(FileNotFoundError):
        assemble_volume_json(1, vol_dir=tmp_path / "no_such_dir", out_dir=out_dir)


# ---------------------------------------------------------------------------
# Fixture-based heading detection (requires generated fixture files)
# See: py -3 build/tools/generate_tess_fixtures.py
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (FIXTURE_DIR / "vol_03_page_0100.txt").exists(),
    reason="Fixture not generated -- run build/tools/generate_tess_fixtures.py",
)
def test_heading_count_vol03_page0100():
    """Entry-dense page (vol 3 p.100) yields >= 2 detected headings.

    Actual fixture: 'CHURCH ORDER' and 'CHURCH PATRON SAINT' -- two long articles
    spanning most of the page, not many short ones.
    """
    text = (FIXTURE_DIR / "vol_03_page_0100.txt").read_text(encoding="utf-8")
    headings = [l.strip() for l in text.splitlines() if is_article_heading(l.strip())]
    assert len(headings) >= 2, f"Only {len(headings)} headings: {headings[:5]}"


@pytest.mark.skipif(
    not (FIXTURE_DIR / "vol_03_page_0075.txt").exists(),
    reason="Fixture not generated -- run build/tools/generate_tess_fixtures.py",
)
def test_heading_count_vol03_page0075():
    """Random probe page (vol 3 p.75) yields at least 1 detected heading."""
    text = (FIXTURE_DIR / "vol_03_page_0075.txt").read_text(encoding="utf-8")
    headings = [l.strip() for l in text.splitlines() if is_article_heading(l.strip())]
    assert len(headings) >= 1, f"No headings found -- FN rate may be > 10%"


@pytest.mark.skipif(
    not (FIXTURE_DIR / "vol_03_page_0331.txt").exists(),
    reason="Fixture not generated -- run build/tools/generate_tess_fixtures.py",
)
def test_no_running_headers_in_headings_vol03_page0331():
    """Running headers are excluded from headings on vol 3 p.331."""
    from build.parsers.local_schaff_tesseract import is_running_header
    text = (FIXTURE_DIR / "vol_03_page_0331.txt").read_text(encoding="utf-8")
    headings = [l.strip() for l in text.splitlines() if is_article_heading(l.strip())]
    running_headers_in_headings = [h for h in headings if is_running_header(h)]
    assert running_headers_in_headings == [], (
        f"Running headers leaked into detected headings: {running_headers_in_headings}"
    )
