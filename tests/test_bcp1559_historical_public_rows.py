"""Cached accepted BCP1559 historical scope and exact private inverse."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.release import bcp1559_public as boundary
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import public_rows_with_omissions, restore_private_source_locations
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "library/works/bcp-1559/forms/bcp-1559-retained-electronic/editions/bcp-1559-retained-electronic-witness/acceptance.json"
MEMBERS = ACCEPTANCE.with_name("source-member-set.json")
PROJECTION = ROOT / "library/works/bcp-1559/integration/bcp1559-current-v1/stage-projection.json"


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
    assert sha256(MEMBERS.read_bytes()).hexdigest() == "3907571f9368082a0f45e2aba8d4c36d0503a7931631d690ee5dc700d336591e"
    assert sha256(PROJECTION.read_bytes()).hexdigest() == "c2681d4f45a964f61c9af2be4fd80539c36a4d66b8d61159532d99d3af0d7edf"
    saved = json.loads(PROJECTION.read_bytes())
    with cached_edition_lookups():
        private, _ = compose_work_metadata(
            ROOT, [dict(row, license=boundary.LICENSE) for row in saved["rows"]], saved["receipt"])
    assert digest(private) == boundary.PRIVATE_ROWS_SHA256
    authority = {"acceptance_sha256": boundary.ACCEPTANCE_SHA256,
                 "master_sha256": boundary.MASTER_SHA256}
    public, inverse = public_rows_with_omissions(private, item_id=boundary.ITEM, **authority)
    return private, public, inverse, authority


@pytest.mark.requires_local_artifacts
def test_historical_words_links_and_private_inverse(transformed):
    private, public, inverse, authority = transformed
    assert len(private) == 16 and len(public) == 15
    assert digest(public) == boundary.PUBLIC_ROWS_SHA256
    assert not _scan(public, boundary.ITEM)
    assert [row["record_id"] for row in public] == [
        row["record_id"] for i, row in enumerate(private) if i != 1]
    assert "THE MINISTRACION OF BAPTISME" in public[0]["text"]
    assert "GODLY PRAYERS" in public[8]["text"]
    assert "A Proclamation for the Authorizing" in public[9]["text"]
    assert "HERE FOLLOWETH THE" in public[11]["text"]
    for row in public:
        assert "The Elizabethan Prayer Book" not in row["text"]
        assert "A number of variaitons" not in row["text"]
        assert "These prayers were never officially" not in row["text"]
        assert "Web author: Charles Wohlers" not in row["text"]
        assert "see below" not in row["text"].lower()
    nodes = [node for row in public for node in native_nodes(row["structure"])]
    assert sum(node["kind"] == "source-reference" for node in nodes) == 2
    assert sum(node["kind"] == "image-reference" for node in nodes) == 12
    assert sum("source-anchor:" in node.get("attributes", {}).get("source_annotations", "")
               for node in nodes) == 9
    assert sum("row_span" in node.get("attributes", {}) for node in nodes) == 29
    assert sum("columns" in node.get("attributes", {}) for node in nodes) == 44
    assert restore_private_source_locations(public, inverse, item_id=boundary.ITEM, **authority) == private


@pytest.mark.requires_local_artifacts
def test_row_authority_and_receipt_mutations_fail_closed(transformed):
    private, public, inverse, authority = transformed
    altered = deepcopy(public)
    altered[8]["text"] += " altered"
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
    altered = deepcopy(inverse)
    altered["removed_row"]["position"] = 0
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, altered, item_id=boundary.ITEM, **authority)
    altered = deepcopy(private)
    altered[9]["text"] += " altered"
    with pytest.raises(PipelineError):
        public_rows_with_omissions(altered, item_id=boundary.ITEM, **authority)
    with pytest.raises(PipelineError):
        public_rows_with_omissions(private, item_id=boundary.ITEM,
                                   acceptance_sha256="0" * 64,
                                   master_sha256=boundary.MASTER_SHA256)
