"""Focused accepted PG76498 native hymn and apparatus route guards."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import hymns, lutheran_hymnbook_native as route
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.release.public_allowlist import _scan


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / (
    "library/works/evangelical-lutheran-hymn-book-abridged/forms/"
    "evangelical-lutheran-hymn-book-abridged-gutenberg-retained/editions/"
    "evangelical-lutheran-hymn-book-abridged-gutenberg-electronic/master.tei.xml"
)


@pytest.fixture(scope="module")
def accepted_units():
    master = MASTER if MASTER.exists() else Path(__file__).resolve().parents[4] / MASTER.relative_to(ROOT)
    root = ET.fromstring(master.read_bytes())
    return route._ordered_units(root)


def test_historical_apparatus_and_paragraph_chants_keep_source_kind(accepted_units):
    units = accepted_units
    assert len(units) == 1141
    assert [kind for *_, kind in units].count("source-labeled-hymn") == 594
    assert [kind for *_, kind in units].count("historical-apparatus") == 545
    assert [kind for *_, kind in units].count("provider-wrapper") == 2
    hymn = next(item for item in units if item[4].get("n") == "568")
    assert hymn[5] == "source-labeled-hymn"
    native = project_content(hymn[4])
    assert "Gloria in Excelsis" in readable_content(native)
    assert not any(child.tag == route.NS + "lg" for child in hymn[4].iter())
    apparatus = next(item for item in units if item[5] == "historical-apparatus"
                     and "The Order of Morning Service" in "".join(item[4].itertext()))
    structure = project_content(apparatus[4])
    text = readable_content(structure)
    row = route._row(*apparatus[:6], structure, text, sequence=1,
                     language="en", revision=route.REVISION, edition_title="Lutheran Hymn-Book")
    route._validate_rows([row])
    assert row["locator"]["kind"] == "historical-apparatus"
    assert not _scan(row, "historical apparatus")


def test_graphic_and_layout_are_exact_source_only_transformations(accepted_units):
    figure = next(item[4] for item in accepted_units
                  if any(node.tag == route.NS + "graphic" for node in item[4].iter()))
    public, styles, graphics = route._public_clone(figure)
    assert styles >= 1 and graphics == 1
    structure = project_content(public)
    assert not _scan(structure, "Concordia figure")
    assert "source-style:" not in str(structure)
    altered = copy.deepcopy(figure)
    graphic = next(node for node in altered.iter() if node.tag == route.NS + "graphic")
    graphic.set("rend", "class:unknown")
    with pytest.raises(PipelineError, match="graphic carrier differs"):
        route._public_clone(altered)
    altered = copy.deepcopy(figure)
    holder = next(node for node in altered.iter() if "source-style:" in (node.get("rend") or ""))
    holder.set("rend", "source-style:unknown")
    with pytest.raises(PipelineError, match="unexpected source layout"):
        route._public_clone(altered)


def test_marker_only_apparatus_has_native_structure_and_empty_readable_text(accepted_units):
    marker = next(item for item in accepted_units if item[5] == "historical-apparatus"
                  and not readable_content(project_content(item[4])))
    structure = project_content(marker[4])
    row = route._row(*marker[:6], structure, "", sequence=1,
                     language="en", revision=route.REVISION, edition_title="Lutheran Hymn-Book")
    route._validate_rows([row])
    assert row["text"] == "" and row["structure"]


def test_accepted_hymns_dispatches_only_this_exact_work(monkeypatch):
    meta = {
        "identity": route.IDENTITY, "master_path": Path("accepted.tei.xml"),
        "retained_path": Path("source.html"), "language": "en",
        "representation_revision": route.REVISION,
        "edition": SimpleNamespace(title="Lutheran Hymn-Book"),
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

    monkeypatch.setattr(route, "project_lutheran_document", project)
    monkeypatch.setattr(route, "verify_lutheran_document", verify)
    result = hymns.project_accepted_hymns(Path("."), acceptance_path=Path("accepted.json"))
    assert result["receipt"]["authority"] == meta["authority"]
    assert hymns.verify_accepted_hymns(
        Path("."), acceptance_path=Path("accepted.json"),
        rows=[], receipt=result["receipt"],
    ) == []
    assert observed == [("project", route.IDENTITY), ("verify", route.IDENTITY)]
