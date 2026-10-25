"""Focused source, candidate, and fail-closed checks for bsb829 parts."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.openmgh_bsb829_parts_oracle import check
from build.tools import prepare_openmgh_bsb829_parts as parts


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    destination = tmp_path_factory.mktemp("bsb829-parts") / "candidate"
    return destination, parts.prepare(destination)


def test_exact_24_candidates_reproduce_and_project(generated: tuple[Path, dict]) -> None:
    destination, receipt = generated
    assert len(receipt["candidates"]) == 24
    assert receipt["source_sha256"] == parts.SOURCE_SHA
    assert receipt["canonical_install"] == "not-performed"
    for row in receipt["candidates"]:
        candidate = destination / row["work_id"] / "candidate.tei.xml"
        assert sha256(candidate.read_bytes()).hexdigest() == row["candidate_sha256"]
        assert row["oracle"]["status"] == "pass"
        assert row["xsd_status"] == "pass"
        assert row["native_prose_projection_rows"] == 1
        assert row["native_prose_independent_check"] == "pass"


def test_oracle_rejects_content_and_container_tampering(generated: tuple[Path, dict]) -> None:
    destination, receipt = generated
    row = next(item for item in receipt["candidates"]
               if item["work_id"] == "bernald-letter-to-alboinus-1")
    source = (parts.ROOT / parts.SOURCE).read_bytes()
    candidate = (destination / row["work_id"] / "candidate.tei.xml").read_bytes()
    boundary = parts.ROOT / row["boundary_path"]
    selected = json.loads(boundary.read_bytes())
    kwargs = dict(first_id=selected["start_xml_id"], last_id=selected["end_xml_id"],
                  selected_type=selected["native_type"],
                  part_ordinal=selected["source_part_ordinal"],
                  section_ordinal=selected["source_section_ordinal_zero_based"])
    assert check(source, candidate, **kwargs)["status"] == "pass"
    root = etree.fromstring(candidate)
    body = root.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
    assert body is not None
    text = next(node for node in body.iter() if node.text and node.text.strip())
    text.text = (text.text or "") + " invented"
    with pytest.raises(ValueError, match="trees differ"):
        check(source, etree.tostring(root), **kwargs)
    with pytest.raises(ValueError, match="section ordinal is invalid"):
        check(source, candidate, **(kwargs | {"section_ordinal": 99}))


def test_frozen_source_receipts_and_existing_output_fail_closed(
    generated: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination, receipt = generated
    monkeypatch.setattr(parts, "SOURCE_SHA", "0" * 64)
    with pytest.raises(ValueError, match="frozen source or receipt changed"):
        parts._source()
    monkeypatch.undo()
    monkeypatch.setattr(parts, "BATCH_SHA", "0" * 64)
    with pytest.raises(ValueError, match="frozen source or receipt changed"):
        parts._source()
    monkeypatch.undo()
    monkeypatch.setattr(parts, "RECEIPT_SHA", "0" * 64)
    with pytest.raises(ValueError, match="frozen source or receipt changed"):
        parts._source()
    monkeypatch.undo()
    first = receipt["candidates"][0]
    path = destination / first["work_id"] / "candidate.tei.xml"
    with pytest.raises(ValueError, match="existing evidence differs"):
        parts._write_once(path, b"tampered candidate")
    assert sha256(path.read_bytes()).hexdigest() == first["candidate_sha256"]


def test_cross_letter_range_is_rejected() -> None:
    _source, _root, source_parts = parts._source()
    with pytest.raises(ValueError, match="crosses source sections"):
        parts._selection(source_parts, "bsb00000829_00015_7", "bsb00000829_00020_26")
