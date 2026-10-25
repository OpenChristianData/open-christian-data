"""Focused Watson style/inverse guard without reprojecting the accepted book."""

from collections import Counter
from copy import deepcopy
import json

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release import watson_body_public as watson
from ocd_kernel.release.public_rows import (HASH_BOUND_ITEMS, public_rows_with_omissions,
                                            restore_private_source_locations)


def sample_rows(monkeypatch):
    monkeypatch.setattr(watson, "COUNTS", Counter({key: 1 for key in watson.STYLES}))
    rows = []
    for index in range(10):
        row = {"record_id": f"record-{index}", "license": watson.LICENSE,
               "text": f"text-{index}", "source_references": [f"source-{index}"],
               "structure": []}
        if index < 5:
            kind, style = list(watson.STYLES)[index]
            attributes = {"style": style}
            if kind == "source-reference":
                attributes["source_target"] = "exact-source-target"
            row["structure"].append({"kind": kind, "attributes": attributes,
                                     "content": [{"kind": "text", "text": row["text"]}]})
        rows.append(row)
    monkeypatch.setattr(watson, "PRIVATE_ROWS_SHA256", watson._digest(rows))
    public, _ = watson._transform(rows)
    monkeypatch.setattr(watson, "PUBLIC_ROWS_SHA256", watson._digest(public))
    return rows


def test_source_classes_map_to_semantic_index_and_exact_inverse(monkeypatch):
    private = sample_rows(monkeypatch)
    public, receipt = public_rows_with_omissions(
        private, item_id=watson.ITEM, acceptance_sha256=watson.ACCEPTANCE_SHA256,
        master_sha256=watson.MASTER_SHA256)
    assert watson.ITEM in HASH_BOUND_ITEMS
    assert [entry["fields"][0]["public_type"] for entry in receipt["entries"][:5]] == [
        None, "source-scripture-index", "scripture-index-book-heading",
        "scripture-index-reference-list", "scripture-index-link"]
    assert public[4]["structure"][0]["attributes"]["source_target"] == "exact-source-target"
    assert restore_private_source_locations(
        json.loads(json.dumps(public)), json.loads(json.dumps(receipt)),
        item_id=watson.ITEM, acceptance_sha256=watson.ACCEPTANCE_SHA256,
        master_sha256=watson.MASTER_SHA256) == private
    changed = deepcopy(public)
    changed[4]["structure"][0]["attributes"]["source_target"] = "different"
    with pytest.raises(PipelineError):
        restore_private_source_locations(changed, receipt, item_id=watson.ITEM,
                                         acceptance_sha256=watson.ACCEPTANCE_SHA256,
                                         master_sha256=watson.MASTER_SHA256)
    incomplete = deepcopy(receipt)
    incomplete["entries"][4]["fields"].clear()
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, incomplete, item_id=watson.ITEM,
                                         acceptance_sha256=watson.ACCEPTANCE_SHA256,
                                         master_sha256=watson.MASTER_SHA256)


def test_watson_dispatch_rejects_unapproved_authority():
    with pytest.raises(PipelineError):
        public_rows_with_omissions([], item_id=watson.ITEM,
                                   acceptance_sha256="0" * 64,
                                   master_sha256=watson.MASTER_SHA256)
    with pytest.raises(PipelineError):
        restore_private_source_locations([], {}, item_id=watson.ITEM,
                                         acceptance_sha256="0" * 64,
                                         master_sha256=watson.MASTER_SHA256)
