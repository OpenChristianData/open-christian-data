"""Focused source and boundary checks for the two held bsb829 word pairs."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.openmgh_bsb829_terminal_lines_oracle import check
from build.tools import prepare_openmgh_bsb829_terminal_lines as route


DIRECT = Path(r"D:\Library\Open Christian Data\candidate-reviews\openmgh-bsb829-terminal-lines-20260926")


def test_two_terminal_lines_close_original_word_pairs() -> None:
    receipt = json.loads((DIRECT / "receipt.json").read_bytes())
    assert receipt["source_sha256"] == route.SOURCE_SHA
    assert receipt["canonical_install"] == "not-performed"
    assert len(receipt["candidates"]) == 2
    for row in receipt["candidates"]:
        candidate = (DIRECT / row["work_id"] / "candidate.tei.xml").read_bytes()
        assert sha256(candidate).hexdigest() == row["candidate_sha256"]
        assert row["source_oracle"]["status"] == row["xsd_status"] == "pass"
        assert row["native_prose_projection_rows"] == 1
        root = etree.fromstring(candidate)
        ids = {node.get(route.XML_ID) for node in root.iter() if node.get(route.XML_ID)}
        assert set(row["terminal_word_ids"]) <= ids
        assert row["next_line_id"] not in ids


def test_oracle_rejects_truncated_line_and_invented_text() -> None:
    receipt = json.loads((DIRECT / "receipt.json").read_bytes())
    source = (route.ROOT / route.SOURCE).read_bytes()
    for row in receipt["candidates"]:
        original = (DIRECT / row["work_id"] / "candidate.tei.xml").read_bytes()
        args = {key: row[key] for key in ("division", "first_id", "last_line_id", "next_line_id")}
        assert check(source, original, **args)["status"] == "pass"
        tree = etree.fromstring(original)
        final_word = tree.xpath(".//t:w[@xml:id=$word]",
                                namespaces={"t": route.TEI[1:-1],
                                            "xml": "http://www.w3.org/XML/1998/namespace"},
                                word=row["terminal_word_ids"][-1])[0]
        final_word.getparent().remove(final_word)
        with pytest.raises(ValueError, match="terminal-line trees differ"):
            check(source, etree.tostring(tree), **args)
        tree = etree.fromstring(original)
        ab = tree.find(f"{route.TEI}text/{route.TEI}body/{route.TEI}div/{route.TEI}ab")
        assert ab is not None
        ab[-1].tail = (ab[-1].tail or "") + "invented"
        with pytest.raises(ValueError, match="terminal-line trees differ"):
            check(source, etree.tostring(tree), **args)


def test_frozen_source_and_plan_reject_mutation() -> None:
    original = route.PLAN_SHA
    route.PLAN_SHA = "0" * 64
    try:
        with pytest.raises(ValueError, match="frozen source or plan differs"):
            route._source()
    finally:
        route.PLAN_SHA = original
