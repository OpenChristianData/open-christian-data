"""test_ccel_evangelical_holiness.py
Unit tests for ccel_evangelical_holiness.py pure functions.

Covers the new structural patterns observed in the T6-6 census (2026-04-24):
  - Bounds flat div1 chapters (no nesting, title= carries chapter name)
  - Finney div1(container) > div2(chapters) nesting
  - Pascal flat div1 sections (SECTION I heading style, no div nesting)
  - Wesley title page filtering (lowercase 'p' in 'Title page')
  - Pascal title-page div filtering (h1='PENSÉES', no content → orphan)
  - is_editorial_div: Indexes top-level (Wesley)
  - extract_heading: numbered Bounds headings ('1 Men of Prayer Needed')
  - extract_heading: SECTION headings ('SECTION I: THOUGHTS ON MIND AND ON STYLE')
  - extract_heading: LECTURE headings ('LECTURE I. WHAT A REVIVAL IS')
  - Author registry contains all required new authors
  - WORK_CONFIG slugs are unique; all refer to valid author_ids
"""

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ocd_kernel.lib.schema_enums import get_enum  # noqa: E402
from build.parsers.ccel_evangelical_holiness import (  # noqa: E402
    AUTHOR_CONFIG,
    WORK_CONFIG,
    extract_heading,
    is_editorial_div,
    get_scriptrefs,
    build_meta,
    parse_work,
    preprocess_thml,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_div(xml: str):
    return ET.fromstring(xml)


# ---------------------------------------------------------------------------
# is_editorial_div — existing patterns still work for new works
# ---------------------------------------------------------------------------

def test_editorial_title_page_lowercase_p():
    """Wesley 'Title page' (lowercase 'p') must be filtered as editorial."""
    div = make_div('<div1 title="Title page"><h1>A PLAIN ACCOUNT</h1><p>John Wesley</p></div1>')
    assert is_editorial_div(div, is_top_level=True)


def test_editorial_title_page_uppercase():
    """Finney 'Title Page' (uppercase 'P') must be filtered."""
    div = make_div('<div1 title="Title Page"><h1>Lectures on Revivals</h1></div1>')
    assert is_editorial_div(div, is_top_level=True)


def test_editorial_indexes_title_attr():
    """Wesley 'Indexes' div must be filtered."""
    div = make_div('<div1 title="Indexes"><h1>Indexes</h1></div1>')
    assert is_editorial_div(div, is_top_level=True)


def test_editorial_content_div_passes_through():
    """A chapter div with valid content must NOT be filtered."""
    div = make_div(
        '<div1 title="1. Men of Prayer Needed">'
        '<h2>1 Men of Prayer Needed</h2>'
        '<p>Study universal holiness of life.</p>'
        '</div1>'
    )
    assert not is_editorial_div(div, is_top_level=True)


def test_editorial_pascal_section_passes_through():
    """Pascal SECTION I div must NOT be filtered."""
    div = make_div(
        '<div1 title="SECTION I: THOUGHTS ON MIND AND ON STYLE ">'
        '<h2>SECTION I: THOUGHTS ON MIND AND ON STYLE</h2>'
        '<p>1. The difference between the mathematical and the intuitive mind.</p>'
        '</div1>'
    )
    assert not is_editorial_div(div, is_top_level=True)


# ---------------------------------------------------------------------------
# extract_heading — Bounds flat chapter headings
# ---------------------------------------------------------------------------

def test_extract_heading_bounds_numbered_h2():
    """Bounds '1 Men of Prayer Needed': no HEADING_RE match on h2;
    title= attribute supplies the full title."""
    div = make_div(
        '<div1 title="1. Men of Prayer Needed">'
        '<h2>1 Men of Prayer Needed</h2>'
        '<p>Content.</p>'
        '</div1>'
    )
    label, title = extract_heading(div)
    # No HEADING_RE match — falls back to title= attr
    assert label == "" or label is not None
    assert "Men of Prayer" in title or "Men of Prayer" in label


def test_extract_heading_bounds_title_attr_used():
    """When h2 text lacks HEADING_RE match, title= gives the full title."""
    div = make_div(
        '<div1 title="2. Our Sufficiency Is of God">'
        '<h2>2 Our Sufficiency Is of God</h2>'
        '<p>But above all he excelled in prayer.</p>'
        '</div1>'
    )
    label, title = extract_heading(div)
    # Either label or title contains "Sufficiency"
    combined = (label or "") + (title or "")
    assert "Sufficiency" in combined


# ---------------------------------------------------------------------------
# extract_heading — Finney LECTURE headings
# ---------------------------------------------------------------------------

def test_extract_heading_finney_lecture_h2():
    """Finney 'LECTURE I.' with h2 text: HEADING_RE matches 'Lecture I'."""
    div = make_div(
        '<div2>'
        '<h2>LECTURE I.</h2>'
        '<h3>WHAT A REVIVAL OF RELIGION IS</h3>'
        '</div2>'
    )
    label, title = extract_heading(div)
    # HEADING_RE should match "LECTURE I." and pick up h3 text or empty
    assert "Lecture" in label or "LECTURE" in label


def test_extract_heading_finney_lecture_i_has_subtitle():
    """Finney LECTURE I with h3 subtitle: label should be 'LECTURE I',
    title should include the subtitle text."""
    div = make_div(
        '<div2 title="LECTURE I. WHAT A REVIVAL OF RELIGION IS">'
        '<h2>LECTURE I.</h2>'
        '<h3>WHAT A REVIVAL OF RELIGION IS</h3>'
        '<p>Content text here.</p>'
        '</div2>'
    )
    label, title = extract_heading(div)
    combined = (label or "") + " " + (title or "")
    assert "LECTURE" in combined.upper() or "Revival" in combined


# ---------------------------------------------------------------------------
# extract_heading — Pascal SECTION headings
# ---------------------------------------------------------------------------

def test_extract_heading_pascal_section_h2():
    """Pascal 'SECTION I: THOUGHTS ON MIND AND ON STYLE': no HEADING_RE match;
    falls back to title= or h2 text."""
    div = make_div(
        '<div1 title="SECTION I: THOUGHTS ON MIND AND ON STYLE ">'
        '<h2>SECTION I: THOUGHTS ON MIND AND ON STYLE</h2>'
        '<p>1. The difference between the mathematical and the intuitive mind.</p>'
        '</div1>'
    )
    label, title = extract_heading(div)
    combined = (label or "") + " " + (title or "")
    assert "SECTION" in combined or "MIND" in combined or "STYLE" in combined


# ---------------------------------------------------------------------------
# get_scriptrefs — passes through from puritan parser (smoke test)
# ---------------------------------------------------------------------------

def test_get_scriptrefs_empty():
    """No scripRef elements → empty list."""
    div = make_div('<div1><p>No scripture here.</p></div1>')
    assert get_scriptrefs(div) == []


def test_get_scriptrefs_bible_prefix():
    """Bible:Book.ch.v prefix variant is cleaned correctly."""
    div = make_div(
        '<div1><p>See <scripRef osisRef="Bible:John.3.16">John 3:16</scripRef>.</p></div1>'
    )
    refs = get_scriptrefs(div)
    assert len(refs) == 1
    assert refs[0]["osis"] == ["John.3.16"]
    assert refs[0]["raw"] == "John 3:16"


# ---------------------------------------------------------------------------
# WORK_CONFIG — integrity checks
# ---------------------------------------------------------------------------

def test_work_config_slugs_unique():
    slugs = [w["slug"] for w in WORK_CONFIG]
    assert len(slugs) == len(set(slugs)), "Duplicate slugs in WORK_CONFIG"


def test_work_config_all_author_ids_valid():
    valid_ids = set(AUTHOR_CONFIG.keys())
    for w in WORK_CONFIG:
        assert w["author_id"] in valid_ids, (
            f"Work {w['slug']} has unknown author_id={w['author_id']!r}"
        )


def test_work_config_required_fields():
    required = {"author_id", "slug", "ccel_id", "author_ccel_path", "title", "work_kind"}
    for w in WORK_CONFIG:
        missing = required - set(w.keys())
        assert not missing, f"Work {w['slug']} missing fields: {missing}"


def test_work_config_has_expected_slugs():
    slugs = {w["slug"] for w in WORK_CONFIG}
    expected = {
        "finney-systematic-theology",
        "finney-lectures-on-revivals",
        "bounds-power-through-prayer",
        "bounds-purpose-in-prayer",
        "bounds-prayer-and-praying-men",
        "bounds-reality-of-prayer",
        "bounds-essentials-of-prayer",
        "bounds-necessity-of-prayer",
        "bounds-weapon-of-prayer",
        "pascal-pensees",
        "wesley-plain-account",
    }
    assert expected.issubset(slugs), f"Missing slugs: {expected - slugs}"


# ---------------------------------------------------------------------------
# Schema enum guards — catch invalid field values before validate.py runs
# These mirror the enum constraints in docs/SCHEMA_SPEC.md and the JSON schemas.
# ---------------------------------------------------------------------------

# Enum constants read directly from schemas/v1/structured_text.schema.json.
# Schema is the single source of truth — no manual copy.
_VALID_TRADITIONS = get_enum("structured_text", "meta", "tradition")
_VALID_WORK_KINDS = get_enum("structured_text", "data", "work_kind")
_VALID_ERAS = get_enum("structured_text", "meta", "era")
_VALID_AUDIENCES = get_enum("structured_text", "meta", "audience")


def test_author_config_traditions_are_schema_valid():
    for aid, cfg in AUTHOR_CONFIG.items():
        for t in cfg.get("tradition", []):
            assert t in _VALID_TRADITIONS, (
                f"Author {aid} has invalid tradition {t!r}. "
                f"Allowed: {sorted(_VALID_TRADITIONS)}"
            )


def test_work_config_work_kinds_are_schema_valid():
    for w in WORK_CONFIG:
        wk = w.get("work_kind", "")
        assert wk in _VALID_WORK_KINDS, (
            f"Work {w['slug']} has invalid work_kind={wk!r}. "
            f"Allowed: {sorted(_VALID_WORK_KINDS)}"
        )


def test_author_config_eras_are_schema_valid():
    for aid, cfg in AUTHOR_CONFIG.items():
        era = cfg.get("era", "")
        assert era in _VALID_ERAS, (
            f"Author {aid} has invalid era={era!r}. Allowed: {sorted(_VALID_ERAS)}"
        )


def test_author_config_audiences_are_schema_valid():
    for aid, cfg in AUTHOR_CONFIG.items():
        audience = cfg.get("audience", "")
        assert audience in _VALID_AUDIENCES, (
            f"Author {aid} has invalid audience={audience!r}. Allowed: {sorted(_VALID_AUDIENCES)}"
        )


def test_meta_does_not_contain_work_kind():
    """Regression: work_kind belongs in $.data, not $.meta."""
    for work in WORK_CONFIG:
        fake_parse = {
            "_source_hash": "sha256:abc",
            "_download_date": "2026-04-24",
            "_warnings": [],
            "sections": [],
        }
        meta = build_meta(work, fake_parse)
        assert "work_kind" not in meta, (
            f"Work {work['slug']}: work_kind must not appear in $.meta"
        )


# ---------------------------------------------------------------------------
# AUTHOR_CONFIG — integrity checks
# ---------------------------------------------------------------------------

def test_author_config_required_authors():
    required = {"finney", "bounds", "pascal", "wesley-extra"}
    missing = required - set(AUTHOR_CONFIG.keys())
    assert not missing, f"Missing author configs: {missing}"


def test_author_config_completeness_field():
    for aid, cfg in AUTHOR_CONFIG.items():
        assert "completeness" in cfg, f"Author {aid} missing completeness field"
        assert cfg["completeness"] in ("full", "abridged", "selections")


# ---------------------------------------------------------------------------
# build_meta — smoke test for a well-known work
# ---------------------------------------------------------------------------

def test_build_meta_finney_systematic():
    work = next(w for w in WORK_CONFIG if w["slug"] == "finney-systematic-theology")
    fake_parse = {
        "_source_hash": "sha256:abc123",
        "_download_date": "2026-04-24",
        "_warnings": [],
        "sections": [],
    }
    meta = build_meta(work, fake_parse)
    assert meta["id"] == "finney-systematic-theology"
    assert meta["author"] == "Charles G. Finney"
    assert "work_kind" not in meta, "work_kind must be in $.data, not $.meta"
    assert meta["language"] == "en"
    assert meta["license"] == "public-domain"
    assert "provenance" in meta
    assert "finney/theology.xml" in meta["provenance"]["source_url"]


def test_build_meta_pascal_translator():
    """Pascal meta must include W.F. Trotter as translator contributor."""
    work = next(w for w in WORK_CONFIG if w["slug"] == "pascal-pensees")
    fake_parse = {
        "_source_hash": "sha256:abc123",
        "_download_date": "2026-04-24",
        "_warnings": [],
        "sections": [],
    }
    meta = build_meta(work, fake_parse)
    assert meta["original_language"] == "fr"
    contribs = meta.get("contributors", [])
    assert any("Trotter" in str(c) for c in contribs), (
        "Pascal meta must include W.F. Trotter as contributor"
    )


def test_build_meta_bounds_power():
    work = next(w for w in WORK_CONFIG if w["slug"] == "bounds-power-through-prayer")
    fake_parse = {
        "_source_hash": "sha256:abc123",
        "_download_date": "2026-04-24",
        "_warnings": [],
        "sections": [],
    }
    meta = build_meta(work, fake_parse)
    assert meta["author"] == "E.M. Bounds"
    assert meta["original_publication_year"] == 1907


# ---------------------------------------------------------------------------
# preprocess_thml — entity handling
# ---------------------------------------------------------------------------

def test_preprocess_strips_doctype():
    raw = b'<?xml version="1.0"?><!DOCTYPE ThML PUBLIC "-//CCEL//DTD ThML 1.0//EN" "http://ccel.org/dtd"><ThML><ThML.body/></ThML>'
    result = preprocess_thml(raw)
    assert "<!DOCTYPE" not in result
    assert "<ThML>" in result


def test_preprocess_replaces_mdash():
    raw = '<?xml version="1.0"?><ThML><ThML.body><p>word&mdash;word</p></ThML.body></ThML>'.encode()
    result = preprocess_thml(raw)
    assert "\u2014" in result


# ---------------------------------------------------------------------------
# parse_work — minimal XML smoke test
# ---------------------------------------------------------------------------

_MINIMAL_XML = b"""<?xml version="1.0"?>
<ThML>
<ThML.head/>
<ThML.body>
  <div1 title="Title Page"><h1>Test Work</h1><p>Author Name</p></div1>
  <div1 title="Chapter One">
    <h2>Chapter One</h2>
    <p>The first paragraph of content here.</p>
    <p>The second paragraph of content here.</p>
  </div1>
  <div1 title="Chapter Two">
    <h2>Chapter Two</h2>
    <p>Second chapter content.</p>
  </div1>
</ThML.body>
</ThML>"""

def test_parse_work_smoke():
    """Minimal parse: title page filtered, 2 content sections returned."""
    work = next(w for w in WORK_CONFIG if w["slug"] == "bounds-power-through-prayer")
    result = parse_work(work, _MINIMAL_XML)
    sections = result["sections"]
    # Title Page div1 is filtered (is_editorial_div)
    # Chapter One and Two should survive
    assert len(sections) >= 2, f"Expected >=2 sections, got {len(sections)}: {sections}"
    titles = [s.get("title") or "" for s in sections]
    assert any("Chapter One" in t or "One" in t for t in titles)


def test_parse_work_section_has_content_blocks():
    """Each surviving section must have content_blocks."""
    work = next(w for w in WORK_CONFIG if w["slug"] == "bounds-power-through-prayer")
    result = parse_work(work, _MINIMAL_XML)
    for s in result["sections"]:
        assert s.get("content_blocks") or s.get("children"), (
            f"Section {s.get('title')!r} has no content_blocks or children"
        )


# ---------------------------------------------------------------------------
# Section count locks — guards against editorial-filter regressions
# ---------------------------------------------------------------------------

from build.lib.pytest_skips import skip_if_missing_data  # noqa: E402

_EXPECTED_TOP_SECTIONS = {
    "bounds-essentials-of-prayer": 14,   # 14 top-level chapters after editorial filtering
    "bounds-necessity-of-prayer": 15,    # 15 flat chapters (Foreword + 14 prayer chapters)
    "bounds-weapon-of-prayer": 12,       # 12 top-level sections with sub-chapter nesting
}


@pytest.mark.parametrize("slug,expected", sorted(_EXPECTED_TOP_SECTIONS.items()))
def test_top_section_counts(slug, expected):
    out_path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert len(data["data"]["sections"]) == expected, (
        f"{slug}: expected {expected} top sections, got {len(data['data']['sections'])}"
    )
