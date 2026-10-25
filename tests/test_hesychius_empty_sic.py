"""Exact PTA Hesychius marker exception leaves correction checks intact."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection import native_content
from ocd_kernel.projection.categories.native_documents import _pta_hesychius_empty_sic_route
from ocd_kernel.projection.native_content_check import observe_content


TEI = "http://www.tei-c.org/ns/1.0"
PROFILE = native_content.PTA_HESYCHIUS_PROFILE
IDENTITY = {
    "work_id": "hesychius-commentarius-magnus-in-psalmos",
    "textual_form_id": "pta-grc",
    "edition_id": "pta-ef861ab3-hesychius-commentarius-magnus-in-psalmos",
}
MASTER_SHA = "892715353efa05b16332457d36974e9f5d52bf236c5457afe6f9997f20de8d7f"


def _fragment(content: str, parent: str = "p") -> bytes:
    return f'<{parent} xmlns="{TEI}">before {content} after</{parent}>'.encode()


def test_exact_empty_marker_preserves_structure_and_reading() -> None:
    raw = _fragment("<sic/>")
    produced = native_content.project_content(ET.fromstring(raw), source_profile=PROFILE)
    observed, readable = observe_content(raw, source_profile=PROFILE)
    assert produced == observed
    assert [part["kind"] for part in produced["content"]] == [
        "text", "original-text", "text",
    ]
    assert produced["content"][1]["content"] == []
    assert native_content.readable_content(produced) == readable == "before  after"


@pytest.mark.parametrize("raw", [
    _fragment("<sic>reading</sic>"),
    _fragment('<sic rend="editorial"/>'),
    _fragment("<sic><hi>reading</hi></sic>"),
    _fragment("<corr/>"),
    _fragment("<sic/>", parent="seg"),
])
def test_malformed_or_broader_correction_rejected_by_both(raw: bytes) -> None:
    with pytest.raises(PipelineError, match="choice parent"):
        native_content.project_content(ET.fromstring(raw), source_profile=PROFILE)
    with pytest.raises(ValueError, match="choice parent"):
        observe_content(raw, source_profile=PROFILE)


def test_generic_route_still_rejects_standalone_sic() -> None:
    raw = _fragment("<sic/>")
    with pytest.raises(PipelineError, match="choice parent"):
        native_content.project_content(ET.fromstring(raw))
    with pytest.raises(ValueError, match="choice parent"):
        observe_content(raw)


@pytest.mark.parametrize("override", [
    {"identity": IDENTITY | {"edition_id": "other"}},
    {"master_sha256": "0" * 64},
    {"acquisition_id": "other"},
    {"category": "commentary"},
])
def test_profile_requires_exact_accepted_binding(override: dict) -> None:
    context = {
        "identity": IDENTITY,
        "master_sha256": MASTER_SHA,
        "language": "grc",
        "category": "prose",
        "collection": False,
        "projection_profile": PROFILE,
        "allow_acceptance_metadata": True,
        "acquisition_id": "ptaef861",
    } | override
    with pytest.raises(PipelineError, match="exact accepted"):
        _pta_hesychius_empty_sic_route(**context)
