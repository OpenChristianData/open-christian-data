"""Focused accepted-source regression checks for DocSouth public projection."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import unquote

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories import native_documents, prose
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import public_rows_with_omissions, restore_private_source_locations
from ocd_kernel.release.selection import validate_release_selection
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
GAINES = ROOT / "library/works/gaines-african-methodism-south-1890/forms/gaines-docsouth-retained/editions/gaines-docsouth-electronic"
GREEN = ROOT / "library/works/elisha-w-green-life-1888/forms/green-docsouth-retained/editions/green-docsouth-electronic"
GREEN_ITEM = "elisha-w-green-life-1888--green-docsouth-electronic"
GREEN_ACCEPTANCE = "library/works/elisha-w-green-life-1888/forms/green-docsouth-retained/editions/green-docsouth-electronic/acceptance.json"
# Exact U.S.-qualified historical-text selection license used by the release
# assembler. This small fixture tests row composition without requiring run logs.
GREEN_LICENSE = (
    "Public domain (United States): identified pre-1931 historical text and printed apparatus; "
    "DocSouth Data permits unrestricted reuse of text, encoding, and metadata with UNC-Chapel Hill "
    "credit requested (not CC0). Image pixels, scans, site material, and newly written collection "
    "essays are excluded; Australia and global complete-text rights remain unresolved."
)
TEI = "{http://www.tei-c.org/ns/1.0}"


def _nodes(value):
    if isinstance(value, list):
        for child in value:
            yield from _nodes(child)
    elif isinstance(value, dict):
        yield value
        yield from _nodes(value.get("content", []))


@pytest.fixture(scope="module")
def accepted_projections():
    # One validating catalog discovery for the two exact retained editions.
    with cached_edition_lookups():
        gaines = prose.project_accepted_prose(ROOT, acceptance_path=GAINES / "acceptance.json")
        green = prose.project_accepted_prose(ROOT, acceptance_path=GREEN / "acceptance.json")
        yield gaines, green


@pytest.mark.requires_local_artifacts
def test_gaines_accepted_title_page_retains_text_roles_and_private_source(accepted_projections):
    gaines, _ = accepted_projections
    master = GAINES / "master.tei.xml"
    source = etree.parse(str(master))
    title_page = source.find(".//" + TEI + "titlePage")
    assert title_page is not None
    shadow = native_documents._gaines_readable_shadow(title_page)
    assert "".join(title_page.itertext()) == "".join(shadow.itertext())
    assert title_page.tag == TEI + "titlePage"
    assert shadow.tag == TEI + "div"
    assert source.find(".//" + TEI + "language").get("ident") == "eng"
    assert gaines["receipt"]["master_sha256"] == sha256(master.read_bytes()).hexdigest()
    assert len(gaines["rows"]) == 12
    assert "African Methodism in the South" in gaines["rows"][5]["text"]
    native_roles = [node["attributes"] for node in _nodes(gaines["rows"][5]["structure"])
                    if node.get("attributes", {}).get("subtype") in native_documents._GAINES_SOURCE_ROLES]
    observed = Counter(attributes["subtype"] for attributes in native_roles)
    expected = Counter(node.tag.removeprefix(TEI) for node in title_page.iter()
                       if node.tag.removeprefix(TEI) in native_documents._GAINES_SOURCE_ROLES)
    assert observed == expected
    for attributes in native_roles:
        source_role = json.loads(unquote(attributes["source_annotations"].removeprefix("source-role:")))
        assert source_role["tag"] == attributes["subtype"]
        assert source_role["attributes"] in ([], [["type", "main"]])
    assert prose.verify_accepted_prose(ROOT, acceptance_path=GAINES / "acceptance.json",
                                       rows=gaines["rows"], receipt=gaines["receipt"]) == []
    assert _scan(gaines["rows"], "gaines-docsouth-electronic") == []


@pytest.mark.requires_local_artifacts
def test_gaines_source_mutation_fails_producer_and_independent_checker(accepted_projections, tmp_path):
    gaines, _ = accepted_projections
    raw = (GAINES / "master.tei.xml").read_bytes()
    assert raw.count(b'<titlePart type="main">') == 1
    altered = tmp_path / "gaines-altered.tei.xml"
    altered.write_bytes(raw.replace(b'<titlePart type="main">', b'<titlePart type="alternate">', 1))
    identity = {"work_id": "gaines-african-methodism-south-1890",
                "textual_form_id": "gaines-docsouth-retained",
                "edition_id": "gaines-docsouth-electronic"}
    options = dict(identity=identity, language="en", representation_revision="exact-source-test",
                   edition_title="African Methodism in the South", _allow_acceptance_metadata=True,
                   category="prose", acquisition_id="gaines-docsouth-acquired")
    with pytest.raises(PipelineError, match="exact accepted master and identity"):
        native_documents.project_document(altered, **options)
    errors = native_documents.verify_document(altered, gaines["rows"], gaines["receipt"], **options)
    assert len(errors) == 1 and "exact accepted master and identity" in errors[0]


@pytest.fixture(scope="module")
def green_public(accepted_projections):
    _, green = accepted_projections
    selection = validate_release_selection({
        "schema_version": "2.0", "release_id": "docsouth-green-regression",
        "items": [{"item_id": GREEN_ITEM, "category": "prose",
                   "acceptance_path": GREEN_ACCEPTANCE, "license": GREEN_LICENSE}],
    })
    selected = selection["items"][0]
    licensed = [dict(row, license=selected["license"]) for row in green["rows"]]
    private, receipt = compose_work_metadata(ROOT, licensed, green["receipt"])
    authority = {"acceptance_sha256": sha256((GREEN / "acceptance.json").read_bytes()).hexdigest(),
                 "master_sha256": receipt["master_sha256"]}
    public, artifact = public_rows_with_omissions(private, item_id=GREEN_ITEM, **authority)
    return private, public, artifact, authority


@pytest.mark.requires_local_artifacts
def test_green_public_role_receipt_is_exact_and_reversible(green_public):
    private, public, artifact, authority = green_public
    assert len(private) == len(public) == 13
    assert [(entry["row_index"], len(entry["fields"])) for entry in artifact["rewrites"]] == [(3, 8), (11, 1)]
    assert _scan(public, GREEN_ITEM) == []
    assert restore_private_source_locations(public, artifact, item_id=GREEN_ITEM, **authority) == private
    for entry in artifact["rewrites"]:
        for field in entry["fields"]:
            assert field["private"].startswith("urn:ocd:green1888:source-role:")
            assert field["public"].startswith("source-role:")
            assert field["private"].removeprefix("urn:ocd:green1888:") == field["public"]


@pytest.mark.parametrize("mutation", ["public", "receipt_missing", "receipt_shape", "private", "authority"])
@pytest.mark.requires_local_artifacts
def test_green_public_inverse_rejects_tampering(green_public, mutation):
    _, public, artifact, authority = green_public
    changed_rows = deepcopy(public)
    changed_artifact = deepcopy(artifact)
    changed_authority = dict(authority)
    if mutation == "public":
        changed_rows[3]["structure"][0]["attributes"]["source_annotations"] = "source-role:changed"
    elif mutation == "receipt_missing":
        changed_artifact["rewrites"][0]["fields"].pop()
    elif mutation == "receipt_shape":
        changed_artifact["rewrites"][0]["fields"] = None
    elif mutation == "private":
        changed_artifact["rewrites"][0]["fields"][0]["private"] += "x"
    else:
        changed_authority["acceptance_sha256"] = "0" * 64
    with pytest.raises(PipelineError):
        restore_private_source_locations(changed_rows, changed_artifact,
                                         item_id=GREEN_ITEM, **changed_authority)
