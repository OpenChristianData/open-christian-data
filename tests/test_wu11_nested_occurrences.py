"""Bounded WU-11 quotation occurrence contract.

This fixture uses the maintained PIPE-008 quotation projection/checker.  The
source unit is the explicit parent; the source XML ID is the occurrence
anchor.  Repeated wording is intentionally retained as two occurrences.
"""

from __future__ import annotations

import copy
from pathlib import Path

from ocd_kernel.projection.categories.quotations import (
    project_quotations_document,
    verify_quotations_document,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/library-pipeline/categories/quotations/master.tei.xml"
CONTEXT = {
    "identity": {"work_id": "work", "textual_form_id": "form", "edition_id": "edition"},
    "language": "en",
    "representation_revision": "wu11-test-v1",
    "edition_title": "Morning and Evening: bounded quotations fixture",
}


def _project():
    return project_quotations_document(SOURCE, **CONTEXT)


def test_parent_occurrence_order_and_source_context_are_explicit():
    result = _project()
    rows = result["rows"]
    anchors = result["receipt"]["anchors"]

    contract = [
        {
            "parent": "/TEI/text/body/div[1]",
            "occurrence": "d0226pm",
            "order": 1,
            "source_context": {"heading": "Evening, February 26", "locus": "Leviticus 13:13"},
        },
        {
            "parent": "/TEI/text/body/div[2]",
            "occurrence": "d0625am",
            "order": 2,
            "source_context": {"heading": "Morning, June 25", "locus": "Isaiah 40:9"},
        },
        {
            "parent": "/TEI/text/body/div[3]",
            "occurrence": "d0710pm-p3",
            "order": 3,
            "source_context": {"heading": "Evening, July 10", "locus": None},
        },
        {
            "parent": "/TEI/text/body/div[4]",
            "occurrence": "d0929am",
            "order": 4,
            "source_context": {"heading": "Morning, September 29", "locus": "Leviticus 13:13"},
        },
        {
            "parent": "/TEI/text/body/div[5]",
            "occurrence": "d1123pm",
            "order": 5,
            "source_context": {"heading": "Evening, November 23", "locus": "Isaiah 40:9"},
        },
    ]

    assert [anchor["unit_id"] for anchor in anchors] == [item["occurrence"] for item in contract]
    assert [item["parent"] for item in contract] == [f"/TEI/text/body/div[{i}]" for i in range(1, 6)]
    assert [row["sequence"] for row in rows] == [item["order"] for item in contract]
    assert [row["locator"]["heading"] for row in rows] == [item["source_context"]["heading"] for item in contract]
    assert [row["citation"]["locus"] for row in rows] == [item["source_context"]["locus"] for item in contract]
    assert verify_quotations_document(SOURCE, rows, result["receipt"], **CONTEXT) == []


def test_legitimate_overlap_keeps_distinct_parent_occurrences():
    result = _project()
    first, repeated = result["rows"][0], result["rows"][3]

    assert first["text"] == repeated["text"]
    assert first["citation"] == repeated["citation"]
    assert first["record_id"] != repeated["record_id"]
    assert first["sequence"] != repeated["sequence"]
    assert result["receipt"]["anchors"][0]["unit_id"] != result["receipt"]["anchors"][3]["unit_id"]


def test_incomplete_context_or_unexplained_overlap_fails_checker():
    result = _project()

    incomplete = copy.deepcopy(result["rows"])
    incomplete[0]["locator"]["heading"] = None
    assert verify_quotations_document(SOURCE, incomplete, result["receipt"], **CONTEXT)

    unexplained_overlap = copy.deepcopy(result["rows"])
    unexplained_overlap[3]["record_id"] = unexplained_overlap[0]["record_id"]
    assert verify_quotations_document(SOURCE, unexplained_overlap, result["receipt"], **CONTEXT)
