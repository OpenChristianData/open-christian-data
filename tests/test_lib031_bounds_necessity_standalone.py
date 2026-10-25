"""Focused integrity checks for the nonaccepted LIB-031 Necessity child."""

from __future__ import annotations

import json
import os
from pathlib import Path

from lxml import etree
import pytest

from build.tei.lib031_bounds_necessity_standalone_oracle import verify
from ocd_kernel.lib.storage_topology import resolve_repo_path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = Path(os.environ.get(
    "OCD_LIB031_NECESSITY_CANDIDATE",
    r"D:\Library\Open Christian Data\candidate-reviews\bounds-necessity-standalone-20260926-v5",
))
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


@pytest.fixture(scope="module")
def evidence() -> tuple[bytes, bytes, dict[str, object]]:
    source = resolve_repo_path(ROOT, "raw/ccel/bounds/necessity.xml").read_bytes()
    package = CANDIDATE / "package"
    tei = (package / "content.tei.xml").read_bytes()
    accounting = json.loads((package / "source-accountability.json").read_bytes())
    return source, tei, accounting


def _mapped(root: etree._Element, row: dict[str, object]) -> etree._Element:
    target_id = str(row["tei_selector"])[1:]
    found = root.xpath("//*[@xml:id=$target_id]", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"}, target_id=target_id)
    assert len(found) == 1
    return found[0]


def test_baseline_exact_source_and_p5(evidence: tuple[bytes, bytes, dict[str, object]]) -> None:
    source, tei, accounting = evidence
    assert accounting["source_division_headings"] == 18
    assert accounting["source_index_links_localized"] == 6
    assert verify(source, tei, accounting) == {
        "source_body_nodes": 692,
        "source_header_nodes": 43,
        "mapped_tei_nodes": 692,
    }


def test_source_byte_mutation_rejected(evidence: tuple[bytes, bytes, dict[str, object]]) -> None:
    source, tei, accounting = evidence
    with pytest.raises(ValueError, match="retained source hash changed"):
        verify(source.replace(b"The Necessity of Prayer", b"The Need for Prayer", 1), tei, accounting)


def test_mapped_text_mutation_rejected(evidence: tuple[bytes, bytes, dict[str, object]]) -> None:
    source, tei, accounting = evidence
    root = etree.fromstring(tei)
    row = next(row for row in accounting["body_crosswalk"] if row["source_tag"] == "p" and row["direct_text"].strip())
    target = _mapped(root, row)
    target.text = (target.text or "") + " invented"
    with pytest.raises(ValueError, match="TEI feature changed"):
        verify(source, etree.tostring(root), accounting)


def test_mapped_feature_deletion_rejected(evidence: tuple[bytes, bytes, dict[str, object]]) -> None:
    source, tei, accounting = evidence
    root = etree.fromstring(tei)
    row = next(row for row in accounting["body_crosswalk"] if row["source_tag"] == "i")
    target = _mapped(root, row)
    target.getparent().remove(target)
    with pytest.raises(ValueError, match="missing TEI feature"):
        verify(source, etree.tostring(root), accounting)


def test_source_link_target_mutation_rejected(evidence: tuple[bytes, bytes, dict[str, object]]) -> None:
    source, tei, accounting = evidence
    root = etree.fromstring(tei)
    row = next(row for row in accounting["body_crosswalk"] if row["source_tag"] == "a")
    target = _mapped(root, row)
    target.set("target", "#invented")
    with pytest.raises(ValueError, match="TEI attributes changed"):
        verify(source, etree.tostring(root), accounting)


def test_tei_valid_invention_rejected(evidence: tuple[bytes, bytes, dict[str, object]]) -> None:
    source, tei, accounting = evidence
    root = etree.fromstring(tei)
    row = next(row for row in accounting["body_crosswalk"] if row["source_tag"] == "p")
    target = _mapped(root, row)
    invented = etree.SubElement(target, f"{{{TEI_NS}}}seg")
    invented.text = "invented passage"
    with pytest.raises(ValueError, match="unaccounted readable TEI content"):
        verify(source, etree.tostring(root), accounting)


def test_division_head_demotion_rejected(evidence: tuple[bytes, bytes, dict[str, object]]) -> None:
    source, tei, accounting = evidence
    root = etree.fromstring(tei)
    row = next(row for row in accounting["body_crosswalk"] if row["source_tag"] == "h2" and row["tei_tag"] == "head")
    target = _mapped(root, row)
    target.tag = f"{{{TEI_NS}}}p"
    with pytest.raises(ValueError, match="TEI feature changed"):
        verify(source, etree.tostring(root), accounting)


def test_original_source_query_uri_not_reused_as_tei_target(evidence: tuple[bytes, bytes, dict[str, object]]) -> None:
    source, tei, accounting = evidence
    root = etree.fromstring(tei)
    row = next(row for row in accounting["body_crosswalk"] if row["source_tag"] == "a")
    target = _mapped(root, row)
    target.set("target", row["attributes"]["href"])
    with pytest.raises(ValueError, match="TEI attributes changed"):
        verify(source, etree.tostring(root), accounting)
