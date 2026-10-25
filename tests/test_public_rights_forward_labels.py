"""Focused tests for the reviewed two-label publication-rights forward fix.

Run after applying forward-labels.patch to the canonical runtime.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release import public_rights


ROOT = Path(__file__).resolve().parents[1]
ITEMS = (
    "bounds-weapon-of-prayer--bounds-weapon-of-prayer-ccel-thml-electronic",
    "george-whitefield-sermons--george-whitefield-sermons-ccel-retained-electronic",
)


def _bound_normalization(item_id: str) -> dict:
    spec = public_rights.SPECS[item_id]
    edition = ROOT / spec["acceptance_path"]
    assessments = list((edition.parent / "rights").glob("*selected-assessment.json"))
    assert len(assessments) == 1
    assessment = json.loads(assessments[0].read_text(encoding="utf-8"))
    bindings = [entry for entry in assessment["evidence"]
                if entry["path"].endswith("selected-assessment-normalization.json")]
    assert len(bindings) == 1
    binding = bindings[0]
    raw = (ROOT / binding["path"]).read_bytes()
    assert sha256(raw).hexdigest() == binding["sha256"]
    value = json.loads(raw)
    for token in binding.get("pointer", "").split("/")[1:]:
        value = value[int(token)] if isinstance(value, list) else value[token]
    assert value["item_id"] == item_id
    return value


@pytest.mark.parametrize("item_id", ITEMS)
def test_current_normalized_label_routes_exactly_and_mixed_labels_fail(item_id: str) -> None:
    spec = public_rights.SPECS[item_id]
    normalized = _bound_normalization(item_id)
    assert normalized["effective_license"] == spec["license_after"] == "public-domain"
    assert spec["license_before"] != spec["license_after"]
    assert public_rights.requires_wrapper(item_id, "public-domain")
    assert not public_rights.requires_wrapper(item_id, spec["license_before"])
    assert public_rights.uses_new_license([{"license": "public-domain"}], item_id)
    assert not public_rights.uses_new_license([{"license": spec["license_before"]}], item_id)
    for labels in (("public-domain", spec["license_before"]), ("unapproved",)):
        with pytest.raises(PipelineError, match="mixed or unapproved publication license"):
            public_rights.uses_new_license([{"license": label} for label in labels], item_id)


@pytest.mark.parametrize("item_id", ITEMS)
def test_wrapper_preserves_exact_row_inverse_and_source_guard(
    item_id: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A local spec clone supplies small deterministic rows while retaining the
    # actual acceptance/master authority values and the full wrapper path.
    spec = deepcopy(public_rights.SPECS[item_id])
    old_private = [{"record_id": f"fixture-{index}", "license": spec["license_before"]}
                   for index in range(spec["baseline_row_count"])]
    selected = [dict(row, license=spec["license_after"]) for row in old_private]
    spec["old_private_rows_sha256"] = public_rights._digest(old_private)
    spec["old_public_rows_sha256"] = public_rights._digest(old_private)
    spec["old_transform_sha256"] = None
    spec["public_row_count"] = len(selected)
    monkeypatch.setitem(public_rights.SPECS, item_id, spec)
    authority = {"item_id": item_id, "acceptance_sha256": spec["acceptance_sha256"],
                 "master_sha256": spec["master_sha256"]}

    public, inverse = public_rights.public_rows(selected, **authority)
    assert public == selected
    assert public_rights.restore(public, inverse, **authority) == selected

    with pytest.raises(PipelineError, match="source authority differs"):
        public_rights.public_rows(selected, **{**authority, "master_sha256": "0" * 64})
    with pytest.raises(PipelineError, match="private rows differ"):
        public_rights.public_rows(selected[:-1], **authority)
    with pytest.raises(PipelineError, match="artifact or public rows differ"):
        public_rights.restore([dict(public[0], license="unapproved"), *public[1:]], inverse,
                              **authority)
