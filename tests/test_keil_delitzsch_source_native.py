"""Exact accepted Keil-Delitzsch route and retained source-unit guards."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import commentary_source_native as native


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "library/works/keil-delitzsch/forms/keil-delitzsch-retained-en/editions/keil-delitzsch-retained-electronic/master.tei.xml"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _metadata() -> dict:
    return {"acceptance": {"identity": {
        "work_id": native.KEIL[0], "textual_form_id": native.KEIL_FORM,
        "edition_id": native.KEIL[1], "acquisition_id": native.KEIL[2],
    }, "source": {"source_kind": "retained-member-set"}}}


def test_keil_route_requires_exact_accepted_identity_and_source_kind() -> None:
    valid = _metadata()
    assert native.route(valid) == "keil"
    for section, key, value in (
        ("identity", "edition_id", "another-edition"),
        ("identity", "acquisition_id", "another-acquisition"),
        ("identity", "textual_form_id", "another-form"),
        ("source", "source_kind", "another-source"),
    ):
        changed = deepcopy(valid)
        changed["acceptance"][section][key] = value
        with pytest.raises(PipelineError, match="Keil retained route"):
            native.route(changed)


@pytest.mark.requires_local_artifacts
def test_keil_profile_preserves_exact_book_chapter_and_occurrence_scope() -> None:
    body = ET.parse(MASTER).getroot().find(f"{TEI}text/{TEI}body")
    assert body is not None
    assert len(native._profile(body, "keil")) == 39

    book = body[0]
    chapter = next(node for node in book if node.tag == f"{TEI}div" and node.get("type") == "chapter")
    occurrence = next(node for node in chapter if node.tag == f"{TEI}div" and node.get("type") == "commentary-occurrence")
    original = occurrence.get(XML_ID)
    occurrence.set(XML_ID, "commentary-GEN-001-99999")
    with pytest.raises(PipelineError, match="occurrence order"):
        native._profile(body, "keil")
    occurrence.set(XML_ID, original)

    original_number = chapter.get("n")
    chapter.set("n", "2")
    with pytest.raises(PipelineError, match="chapter gaps"):
        native._profile(body, "keil")
    chapter.set("n", original_number)
    assert len(native._profile(body, "keil")) == 39
