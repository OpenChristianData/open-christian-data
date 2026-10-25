"""Cached accepted BCP1549 historical scope and exact private inverse."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.release import bcp1549_public as boundary
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import (
    public_rows_with_omissions, restore_private_source_locations,
)
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "library/works/bcp-1549/forms/bcp-1549-retained-electronic/editions/bcp-1549-retained-electronic-witness/acceptance.json"
MEMBERS = ACCEPTANCE.with_name("source-member-set.json")
PROJECTION = ROOT / "library/works/bcp-1549/integration/bcp1549-current-v1/stage-projection.json"


def digest(value):
    return sha256(canonical_bytes(value)).hexdigest()


def native_nodes(value):
    if isinstance(value, dict):
        if "kind" in value:
            yield value
        for child in value.values():
            yield from native_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from native_nodes(child)


@pytest.fixture(scope="module")
def transformed():
    assert sha256(ACCEPTANCE.read_bytes()).hexdigest() == boundary.ACCEPTANCE_SHA256
    assert sha256(ACCEPTANCE.with_name("master.tei.xml").read_bytes()).hexdigest() == boundary.MASTER_SHA256
    assert sha256(MEMBERS.read_bytes()).hexdigest() == (
        "f22ff0f58dcd14bb7e5c9e89042e477674cea1e551c20a56b12278af202b4aa1")
    assert sha256(PROJECTION.read_bytes()).hexdigest() == (
        "16e2a7e79783b24e4a5f09e840eeadade90ce91b90ee9393c611e7cd625d7ed2")
    saved = json.loads(PROJECTION.read_bytes())
    with cached_edition_lookups():
        private, _ = compose_work_metadata(
            ROOT, [dict(row, license=boundary.LICENSE) for row in saved["rows"]],
            saved["receipt"])
    assert digest(private) == boundary.PRIVATE_ROWS_SHA256
    authority = {"acceptance_sha256": boundary.ACCEPTANCE_SHA256,
                 "master_sha256": boundary.MASTER_SHA256}
    public, inverse = public_rows_with_omissions(private, item_id=boundary.ITEM, **authority)
    return private, public, inverse, authority


@pytest.mark.requires_local_artifacts
def test_historical_words_links_roles_and_private_inverse(transformed):
    private, public, inverse, authority = transformed
    assert len(private) == 34 and len(public) == 33
    assert digest(public) == boundary.PUBLIC_ROWS_SHA256
    assert not _scan(public, boundary.ITEM)
    assert [row["record_id"] for row in public] == [
        row["record_id"] for i, row in enumerate(private) if i != 6]
    assert "THE CONTENTES OF THIS BOOKE" in public[0]["text"]
    assert "Although a formal break with the Papacy" not in public[0]["text"]
    assert "THE few pages at my disposal" in public[1]["text"]
    assert all("Web author: Charles Wohlers" not in row["text"] for row in public)
    assert all("Next Readings" not in row["text"] for row in public)
    assert all("Click on the image" not in row["text"] for row in public)
    nodes = [node for row in public for node in native_nodes(row["structure"])]
    assert sum(node["kind"] == "source-reference" for node in nodes) == 34
    assert sum(node["kind"] == "image-reference" for node in nodes) == 48
    assert any("source-anchor:" in node.get("attributes", {}).get("source_annotations", "")
               for node in nodes)
    assert any("source-literal-role:" in node.get("attributes", {}).get("source_annotations", "")
               for node in nodes)
    assert any("row_span" in node.get("attributes", {}) for node in nodes)
    assert any("columns" in node.get("attributes", {}) for node in nodes)
    assert all(row.get("source_links") == private[i]["source_links"]
               for i, row in enumerate(public) if i < 6)
    assert restore_private_source_locations(
        public, inverse, item_id=boundary.ITEM, **authority) == private


@pytest.mark.requires_local_artifacts
def test_changed_public_content_and_receipt_fail_closed(transformed):
    private, public, inverse, authority = transformed
    altered = deepcopy(public)
    altered[1]["text"] += " altered"
    with pytest.raises(PipelineError):
        restore_private_source_locations(altered, inverse, item_id=boundary.ITEM, **authority)
    altered = deepcopy(inverse)
    altered["fields"].pop()
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, altered, item_id=boundary.ITEM, **authority)
    altered = deepcopy(inverse)
    altered["site_omitted"].pop()
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, altered, item_id=boundary.ITEM, **authority)
    changed = deepcopy(private)
    changed[1]["text"] += " altered"
    with pytest.raises(PipelineError):
        public_rows_with_omissions(changed, item_id=boundary.ITEM, **authority)
    with pytest.raises(PipelineError):
        public_rows_with_omissions(private, item_id=boundary.ITEM,
                                   acceptance_sha256="0" * 64,
                                   master_sha256=boundary.MASTER_SHA256)
