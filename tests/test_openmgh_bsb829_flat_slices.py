"""Focused source-boundary and native-projection checks for bsb829 flat works."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.openmgh_bsb829_flat_slices_oracle import check
from build.tools import prepare_openmgh_bsb829_flat_slices as flat


DIRECT = Path(r"D:\Library\Open Christian Data\candidate-reviews\openmgh-bsb829-flat-slices-20260926")


def test_exact_ten_durable_candidates_and_held_linkage() -> None:
    receipt = json.loads((DIRECT / "receipt.json").read_bytes())
    plan = json.loads((flat.ROOT / flat.PLAN).read_bytes())
    assert len(receipt["candidates"]) == len(plan["works"]) == 10
    assert len(plan["held"]) == 2
    assert receipt["source_sha256"] == flat.SOURCE_SHA
    assert receipt["canonical_install"] == "not-performed"
    for row in receipt["candidates"]:
        candidate = DIRECT / row["work_id"] / "candidate.tei.xml"
        assert sha256(candidate.read_bytes()).hexdigest() == row["candidate_sha256"]
        assert row["oracle"]["status"] == row["xsd_status"] == "pass"
        assert row["native_prose_projection_rows"] == 1
        assert row["native_prose_independent_check"] == "pass"
    assert {row["work_id"] for row in plan["held"]} == {
        "beno-letter-to-roman-church-fathers",
        "bruno-of-segni-letter-to-st-george-brothers",
    }
    assert all(row["outside_word_links"] for row in plan["held"])


def test_line_span_oracle_rejects_content_and_boundary_tampering() -> None:
    receipt = json.loads((DIRECT / "receipt.json").read_bytes())
    row = next(item for item in receipt["candidates"]
               if item["work_id"] == "beno-letter-to-the-roman-church")
    source = (flat.ROOT / flat.SOURCE).read_bytes()
    candidate = (DIRECT / row["work_id"] / "candidate.tei.xml").read_bytes()
    boundary = json.loads((flat.ROOT / row["boundary_path"]).read_bytes())
    kwargs = {key: boundary[key] for key in ("division", "first_id", "last_id")}
    assert check(source, candidate, **kwargs)["status"] == "pass"
    tree = etree.fromstring(candidate)
    selected = tree.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
    assert selected is not None
    text = next(node for node in selected.iter() if node.text and node.text.strip())
    text.text = (text.text or "") + " invented"
    with pytest.raises(ValueError, match="trees differ"):
        check(source, etree.tostring(tree), **kwargs)
    with pytest.raises(ValueError, match="ordered line breaks"):
        check(source, candidate, **(kwargs | {"first_id": boundary["last_id"],
                                    "last_id": boundary["first_id"]}))


def test_frozen_source_and_plan_fail_closed() -> None:
    for field in ("SOURCE_SHA", "BATCH_SHA", "RECEIPT_SHA", "PLAN_SHA",
                  "REVIEW_PLAN_SHA", "PROBE_SHA"):
        original = getattr(flat, field)
        setattr(flat, field, "0" * 64)
        try:
            with pytest.raises(ValueError, match="frozen source, plan, or receipt changed"):
                flat._source()
        finally:
            setattr(flat, field, original)
