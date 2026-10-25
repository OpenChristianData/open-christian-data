"""Flat-ab verse remains ordered native content, not invented TEI line units."""

from __future__ import annotations

import copy
import os

import pytest

from ocd_kernel.library._common import io_path

from ocd_kernel.projection.categories.native_documents import (
    project_document, verify_document,
)


@pytest.mark.parametrize("long_path", [False, True])
def test_flat_ab_column_and_anchor_are_preserved_and_independently_checked(tmp_path, long_path):
    if long_path:
        if os.name != "nt":
            pytest.skip("Windows MAX_PATH regression")
        tmp_path = tmp_path / ("retained-edition-" * 7) / ("work-identity-" * 7)
        io_path(tmp_path).mkdir(parents=True)
    master = tmp_path / "flat-ab.tei.xml"
    io_path(master).write_text(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>Retained verse</title></titleStmt>'
        '<publicationStmt><p>Source</p></publicationStmt>'
        '<sourceDesc><p>Extracted XML</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body><div type="work" n="Poem"><ab>First '
        '<cb type="parallel" n="1" spanTo="#end"/>column '
        '<anchor xml:id="end"/><lb n="1"/>verse.</ab></div></body></text></TEI>',
        encoding="utf-8",
    )
    context = {
        "identity": {"work_id": "verse", "textual_form_id": "retained",
                     "edition_id": "electronic"},
        "language": "la", "representation_revision": "source-v1",
        "edition_title": "Retained verse", "category": "poetry",
        "_allow_acceptance_metadata": True,
    }
    projected = project_document(master, **context)
    assert len(projected["rows"]) == 1
    row = projected["rows"][0]
    source_block = row["structure"][0]["content"][0]
    assert source_block["kind"] == "source-block"
    milestones = [node for node in source_block["content"] if node["kind"] != "text"]
    assert [node["kind"] for node in milestones] == [
        "column-break", "anchor", "line-break",
    ]
    assert milestones[0]["attributes"] == {
        "type": "parallel", "number": "1", "source_target": "#end",
    }
    assert verify_document(master, projected["rows"], projected["receipt"], **context) == []
    for mutation in ("drop-column", "repoint-column", "drop-anchor", "invent-line"):
        rows = copy.deepcopy(projected["rows"])
        content = rows[0]["structure"][0]["content"][0]["content"]
        if mutation == "drop-column":
            del content[1]
        elif mutation == "repoint-column":
            content[1]["attributes"]["source_target"] = "#other"
        elif mutation == "drop-anchor":
            del content[3]
        else:
            content.insert(0, {"kind": "verse-line", "attributes": {}, "content": []})
        assert verify_document(master, rows, projected["receipt"], **context)
