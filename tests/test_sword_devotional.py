"""Regression tests for Daily Light SWORD devotional parsing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.pytest_skips import skip_if_missing_data  # noqa: E402
from build.parsers.sword_devotional import (  # noqa: E402
    extract_scripref_cross_references,
    make_entry,
)


OUTPUT_FILE = REPO_ROOT / "data" / "devotionals" / "daily-light" / "daily-light.json"


def test_extract_scripref_cross_references_preserves_raw_and_osis():
    html = (
        '<p>One thing I do.</p>'
        '<scripRef passage=" Php 3:13,14 Joh 17:24 2Ti 1:12 Php 1:6 1Co 9:24,25 He 12:1,2">'
        "Philippians, John, Timothy, Corinthians, Hebrews"
        "</scripRef>"
    )

    refs = extract_scripref_cross_references(html)

    assert refs == [
        {
            "raw": "Php 3:13,14 Joh 17:24 2Ti 1:12 Php 1:6 1Co 9:24,25 He 12:1,2",
            "osis": [
                "Phil.3.13",
                "Phil.3.14",
                "John.17.24",
                "2Tim.1.12",
                "Phil.1.6",
                "1Cor.9.24",
                "1Cor.9.25",
                "Heb.12.1",
                "Heb.12.2",
            ],
        }
    ]


def test_make_entry_includes_cross_references():
    entry = make_entry(
        month=1,
        day=1,
        period="morning",
        html_content='<p>Press toward the mark.</p><scripRef passage="Php 3:14">Philippians 3:14</scripRef>',
        config={},
    )

    assert entry["cross_references"] == [{"raw": "Php 3:14", "osis": ["Phil.3.14"]}]


def test_extract_scripref_cross_references_handles_daily_light_short_book_aliases():
    refs = extract_scripref_cross_references(
        '<scripRef passage="Ho 13:14 La 3:22 Ca 2:3 Na 1:7 Ru 3:1 Es 5:2 3Jo 1:2">refs</scripRef>'
    )

    assert refs[0]["osis"] == [
        "Hos.13.14",
        "Lam.3.22",
        "Song.2.3",
        "Nah.1.7",
        "Ruth.3.1",
        "Esth.5.2",
        "3John.1.2",
    ]


@pytest.fixture(scope="module")
def daily_light_doc():
    skip_if_missing_data(OUTPUT_FILE)
    with OUTPUT_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def test_output_has_cross_references_for_daily_light_entries(daily_light_doc):
    entry = next(e for e in daily_light_doc["data"] if e["entry_id"] == "01-01-morning")

    assert entry["cross_references"], "01-01-morning should expose source scripRef tags"
    assert any("Phil.3.14" in ref["osis"] for ref in entry["cross_references"])
