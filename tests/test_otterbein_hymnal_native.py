"""Focused accepted PG16455 native hymn and apparatus route guards."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import hymns, otterbein_hymnal_native as route
from ocd_kernel.projection.native_content import project_content, readable_content


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / (
    "library/works/otterbein-hymnal/forms/otterbein-hymnal-gutenberg-retained/"
    "editions/otterbein-hymnal-gutenberg-electronic/master.tei.xml"
)


@pytest.fixture(scope="module")
def accepted_units():
    return route._ordered_units(ET.fromstring(MASTER.read_bytes()))


@pytest.mark.requires_local_artifacts
def test_all_source_units_have_exact_historical_disposition(accepted_units):
    assert len(accepted_units) == 592
    assert Counter(kind for _, _, kind in accepted_units) == Counter({
        "source-labeled-hymn": 548,
        "historical-apparatus": 42,
        "provider-wrapper": 2,
    })
    assert accepted_units[0][2] == accepted_units[-1][2] == "provider-wrapper"
    cowper = accepted_units[223]
    assert cowper[2] == "historical-apparatus"
    assert "William Cowper, 1779." in "".join(cowper[1].itertext())
    assert any(kind == "historical-apparatus" and "INDEX OF FIRST LINES" in "".join(unit.itertext())
               for _, unit, kind in accepted_units)


@pytest.mark.requires_local_artifacts
def test_hymn_numbers_and_page_comments_have_reversible_native_carriers(accepted_units):
    hymn = accepted_units[37][1]
    assert hymn[0].get("n") == "1"
    original = [node for node in hymn.iter(route.NS + "num")]
    assert original and original[0].get("type") == "hymn-number"
    public, numbers, pages = route._public_clone(hymn)
    assert numbers == len(original)
    assert pages == len(list(hymn.iter(route.NS + "pb")))
    assert not list(public.iter(route.NS + "num"))
    segments = [node for node in public.iter(route.NS + "seg")
                if node.get("subtype") == "source-element:num"]
    assert len(segments) == numbers
    assert segments[0].get("type") == "hymn-number"
    native = project_content(public)
    assert "Gloria Patri." in readable_content(native)


@pytest.mark.requires_local_artifacts
def test_marker_only_apparatus_and_source_classes_preserve_meaning(accepted_units):
    marker = next(unit for _, unit, kind in accepted_units
                  if kind == "historical-apparatus" and unit[0].tag == route.NS + "pb")
    public, _, pages = route._public_clone(marker)
    assert pages == 1 and public[0].get("type") is None
    assert readable_content(project_content(public)) == ""
    source_classes = {node.get("rend") for _, unit, kind in accepted_units
                      if kind != "provider-wrapper" for node in unit.iter() if node.get("rend")}
    assert "l" in source_classes and "t" in source_classes
    assert all("source-style:" not in value and ":" not in value for value in source_classes)


@pytest.mark.requires_local_artifacts
def test_unexpected_number_or_page_semantics_fail_closed(accepted_units):
    hymn = copy.deepcopy(accepted_units[37][1])
    next(hymn.iter(route.NS + "num")).set("type", "invented")
    with pytest.raises(PipelineError, match="number shape differs"):
        route._public_clone(hymn)
    marker = copy.deepcopy(next(unit for _, unit, kind in accepted_units
                                if kind == "historical-apparatus" and unit[0].tag == route.NS + "pb"))
    marker[0].set("type", "invented")
    with pytest.raises(PipelineError, match="page-comment shape differs"):
        route._public_clone(marker)


def test_accepted_hymns_dispatches_only_otterbein(monkeypatch):
    meta = {
        "identity": route.IDENTITY, "master_path": Path("accepted.tei.xml"),
        "retained_path": Path("source.html"), "language": "en",
        "representation_revision": route.REVISION,
        "edition": SimpleNamespace(title="The Otterbein Hymnal"),
        "source_url": route.SOURCE_URL,
        "source_sha256": route.SOURCE_SHA256,
        "retained_sha256": route.SOURCE_SHA256,
        "authority": {"master": {"sha256": route.MASTER_SHA256}},
    }
    monkeypatch.setattr(hymns, "_accepted_metadata", lambda *_: meta)
    observed = []

    def project(*args, **kwargs):
        observed.append(("project", kwargs["identity"]))
        return {"rows": [], "receipt": {}}

    def verify(*args, **kwargs):
        observed.append(("verify", kwargs["identity"]))
        return []

    monkeypatch.setattr(route, "project_otterbein_document", project)
    monkeypatch.setattr(route, "verify_otterbein_document", verify)
    result = hymns.project_accepted_hymns(Path("."), acceptance_path=Path("accepted.json"))
    assert result["receipt"]["authority"] == meta["authority"]
    assert hymns.verify_accepted_hymns(
        Path("."), acceptance_path=Path("accepted.json"),
        rows=[], receipt=result["receipt"],
    ) == []
    assert observed == [("project", route.IDENTITY), ("verify", route.IDENTITY)]
