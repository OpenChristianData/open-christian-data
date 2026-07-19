"""test_schleitheim_confession.py
Tests for schleitheim_confession.py -- Schleitheim Confession (1527).

Covers:
  - DOCUMENT_CONFIG: schema enum validation for tradition, document_kind, completeness
  - extract_articles: article count, numbering, title and content extraction
  - build_output: required meta and data fields
  - Section count lock against committed output
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ocd_kernel.lib.schema_enums import get_enum  # noqa: E402
from build.parsers.schleitheim_confession import (  # noqa: E402
    DOCUMENT_CONFIG,
    build_output,
    extract_articles,
)

# ---------------------------------------------------------------------------
# Schema enum constants
# ---------------------------------------------------------------------------

_VALID_TRADITIONS = get_enum("doctrinal_document", "meta", "tradition")
_VALID_DOC_KINDS = get_enum("doctrinal_document", "data", "document_kind")
_VALID_COMPLETENESS = get_enum("doctrinal_document", "meta", "completeness")

# ---------------------------------------------------------------------------
# Synthetic HTML fixture (mirrors real anabaptists.org structure)
# ---------------------------------------------------------------------------

_MINIMAL_HTML = b"""
<html><body>
<h1>The Schleitheim Confession</h1>
<p>Preamble text before the articles begins here.</p>

<font color="#008000"><b>I.  Observe concerning baptism:</b></font>  Baptism shall be given to those
who have learned repentance.<p>
This excludes all infant baptism.<p>

<font color="#008000"><b>II.  We are agreed as follows on the ban:</b></font>  The ban shall be
employed with all those who have given themselves to the Lord.<p>
Further ban content here in a second paragraph.<p>

<font color="#008000"><b>III.  In the breaking of bread we are of one mind and are agreed:</b></font>
All those who wish to break one bread shall beforehand be united.<p>

<font color="#008000"><b>IV.  We are agreed on separation:</b></font>  A separation shall be made
from the evil and from the wickedness which the devil planted in the world.<p>

<font color="#008000"><b>V.  We are agreed as follows on pastors in the church of God:</b></font>
The pastor in the church of God shall be one who has a good report.<p>

<font color="#008000"><b>VI.  We are agreed as follows concerning the sword:</b></font>  The sword is
ordained of God outside the perfection of Christ.<p>

<font color="#008000"><b>VII.  We are agreed as follows concerning the oath:</b></font>  We are agreed
that the oath is a confirmation among those who are quarreling.<p>

<div style="margin-left:50px">
The Seven Articles of Schleitheim<br>
Canton Schaffhausen, Switzerland,<br>
February 24, 1527
</div>

</body></html>
"""

# ---------------------------------------------------------------------------
# DOCUMENT_CONFIG schema enum guards
# ---------------------------------------------------------------------------


def test_document_config_tradition_contains_anabaptist():
    assert "anabaptist" in DOCUMENT_CONFIG["tradition"]


def test_document_config_traditions_schema_valid():
    for t in DOCUMENT_CONFIG["tradition"]:
        assert t in _VALID_TRADITIONS, (
            f"Invalid tradition {t!r}. Allowed: {sorted(_VALID_TRADITIONS)}"
        )


def test_document_config_document_kind_valid():
    assert DOCUMENT_CONFIG["document_kind"] in _VALID_DOC_KINDS, (
        f"Invalid document_kind {DOCUMENT_CONFIG['document_kind']!r}"
    )


def test_document_config_document_kind_is_confession():
    assert DOCUMENT_CONFIG["document_kind"] == "confession"


def test_document_config_completeness_valid():
    assert DOCUMENT_CONFIG["completeness"] in _VALID_COMPLETENESS


def test_document_config_required_meta_fields():
    required = {
        "document_id",
        "document_kind",
        "tradition",
        "completeness",
        "title",
        "author",
        "original_publication_year",
        "language",
    }
    missing = required - set(DOCUMENT_CONFIG.keys())
    assert not missing, f"DOCUMENT_CONFIG missing fields: {missing}"


# ---------------------------------------------------------------------------
# extract_articles
# ---------------------------------------------------------------------------


def test_extract_articles_returns_seven():
    articles = extract_articles(_MINIMAL_HTML)
    assert len(articles) == 7, f"Expected 7 articles, got {len(articles)}"


def test_extract_articles_numbering():
    articles = extract_articles(_MINIMAL_HTML)
    numbers = [a["number"] for a in articles]
    assert numbers == ["I", "II", "III", "IV", "V", "VI", "VII"]


def test_extract_articles_titles_nonempty():
    articles = extract_articles(_MINIMAL_HTML)
    for a in articles:
        assert a["title"].strip(), f"Article {a['number']!r} has empty title"


def test_extract_articles_content_nonempty():
    articles = extract_articles(_MINIMAL_HTML)
    for a in articles:
        assert a["content"].strip(), f"Article {a['number']!r} has empty content"


def test_extract_articles_retains_confession_closing_imprint():
    articles = extract_articles(_MINIMAL_HTML)
    assert "The Seven Articles of Schleitheim" in articles[-1]["content"]


def test_extract_articles_first_title_contains_baptism():
    articles = extract_articles(_MINIMAL_HTML)
    assert "baptism" in articles[0]["title"].lower()


def test_extract_articles_first_content_starts_with_baptism():
    articles = extract_articles(_MINIMAL_HTML)
    assert "Baptism" in articles[0]["content"]


def test_extract_articles_preamble_excluded():
    """The preamble paragraph before Article I must not appear in article content."""
    articles = extract_articles(_MINIMAL_HTML)
    combined = " ".join(a["content"] for a in articles)
    assert "Preamble text before the articles" not in combined


def test_extract_articles_multi_paragraph_article():
    """Article I has two paragraphs in the fixture; both must appear in content."""
    articles = extract_articles(_MINIMAL_HTML)
    art_i = articles[0]
    assert "infant baptism" in art_i["content"]


# ---------------------------------------------------------------------------
# build_output
# ---------------------------------------------------------------------------

_FAKE_HASH = "sha256:" + "a" * 64
_FAKE_DATE = "2026-06-17"


def test_build_output_meta_schema_type():
    articles = extract_articles(_MINIMAL_HTML)
    output = build_output(articles, source_hash=_FAKE_HASH, download_date=_FAKE_DATE)
    assert output["meta"]["schema_type"] == "doctrinal_document"


def test_build_output_data_document_kind():
    articles = extract_articles(_MINIMAL_HTML)
    output = build_output(articles, source_hash=_FAKE_HASH, download_date=_FAKE_DATE)
    assert output["data"]["document_kind"] == "confession"


def test_build_output_tradition_is_anabaptist():
    articles = extract_articles(_MINIMAL_HTML)
    output = build_output(articles, source_hash=_FAKE_HASH, download_date=_FAKE_DATE)
    assert "anabaptist" in output["meta"]["tradition"]


def test_build_output_units_count():
    articles = extract_articles(_MINIMAL_HTML)
    output = build_output(articles, source_hash=_FAKE_HASH, download_date=_FAKE_DATE)
    assert len(output["data"]["units"]) == 7


def test_build_output_units_type():
    articles = extract_articles(_MINIMAL_HTML)
    output = build_output(articles, source_hash=_FAKE_HASH, download_date=_FAKE_DATE)
    for unit in output["data"]["units"]:
        assert unit["unit_type"] == "article"


def test_build_output_source_hash_stored():
    articles = extract_articles(_MINIMAL_HTML)
    output = build_output(articles, source_hash=_FAKE_HASH, download_date=_FAKE_DATE)
    assert output["meta"]["provenance"]["source_hash"] == _FAKE_HASH


# ---------------------------------------------------------------------------
# Section count lock against committed output
# ---------------------------------------------------------------------------

_EXPECTED_UNIT_COUNT = 7
_OUTPUT_PATH = REPO_ROOT / "data" / "doctrinal-documents" / "schleitheim-confession-1527.json"
_RAW_CACHE_PATH = REPO_ROOT / "raw" / "anabaptists.org" / "schleitheim-confession-1527.html"
_SOURCE_CONFIG_PATH = REPO_ROOT / "sources" / "doctrinal-documents" / "schleitheim-confession-1527" / "config.json"
_DOCUMENT_CLOSE = "The Seven Articles of Schleitheim"


@pytest.mark.skipif(not _OUTPUT_PATH.exists(), reason="output file not yet generated")
def test_output_unit_count_locked():
    with open(_OUTPUT_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert len(doc["data"]["units"]) == _EXPECTED_UNIT_COUNT, (
        f"Expected {_EXPECTED_UNIT_COUNT} units, got {len(doc['data']['units'])}"
    )


@pytest.mark.skipif(not _OUTPUT_PATH.exists(), reason="output file not yet generated")
def test_output_meta_fields_present():
    with open(_OUTPUT_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)
    for field in (
        "id",
        "title",
        "author",
        "language",
        "schema_type",
        "schema_version",
        "license",
        "tradition",
        "completeness",
        "provenance",
    ):
        assert field in doc["meta"], f"Missing meta field: {field!r}"


@pytest.mark.skipif(not _OUTPUT_PATH.exists(), reason="output file not yet generated")
def test_output_all_units_have_content():
    with open(_OUTPUT_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)
    for unit in doc["data"]["units"]:
        assert unit.get("content", "").strip(), (
            f"Unit {unit.get('number')!r} has empty content"
        )


@pytest.mark.skipif(not _OUTPUT_PATH.exists(), reason="output file not yet generated")
def test_output_provenance_source_hash_format():
    with open(_OUTPUT_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)
    source_hash = doc["meta"]["provenance"]["source_hash"]
    assert source_hash.startswith("sha256:"), f"Expected sha256: prefix, got {source_hash!r}"
    assert len(source_hash) == 71, f"Expected len 71, got {len(source_hash)}"


@pytest.mark.requires_local_artifacts
def test_cached_raw_article_vii_stops_at_confession_terminus():
    """The cached witness must not allow post-document site chrome into Article VII."""
    assert _RAW_CACHE_PATH.exists(), f"Missing cached raw witness: {_RAW_CACHE_PATH}"
    articles = extract_articles(_RAW_CACHE_PATH.read_bytes())
    article_vii = next(article for article in articles if article["number"] == "VII")

    assert _DOCUMENT_CLOSE in article_vii["content"]
    assert "February 24, 1527" in article_vii["content"]
    assert "This material was typed by" not in article_vii["content"]
    assert "Amazon disclosure" not in article_vii["content"]
    assert "Share This Page" not in article_vii["content"]


@pytest.mark.requires_local_artifacts
def test_cached_raw_hash_matches_source_config():
    assert _RAW_CACHE_PATH.exists(), f"Missing cached raw witness: {_RAW_CACHE_PATH}"
    with _SOURCE_CONFIG_PATH.open(encoding="utf-8") as fh:
        config = json.load(fh)
    cached_hash = "sha256:" + hashlib.sha256(_RAW_CACHE_PATH.read_bytes()).hexdigest()
    assert cached_hash == config["source"]["source_hash"]


def test_output_article_vii_stops_at_confession_terminus():
    """The regenerated dataset retains the real close but excludes source-site chrome."""
    with _OUTPUT_PATH.open(encoding="utf-8") as fh:
        doc = json.load(fh)
    article_vii = doc["data"]["units"][-1]["content"]

    assert _DOCUMENT_CLOSE in article_vii
    assert "February 24, 1527" in article_vii
    assert "This material was typed by" not in article_vii
    assert "Amazon disclosure" not in article_vii
    assert "Share This Page" not in article_vii
