"""Corrected variants must retain the existing routes' exact authority checks."""
from copy import deepcopy

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import commentary_source_native as native
from ocd_kernel.projection.categories import commentary_group_policy as grouped


def test_findlay_preserves_old_variant_and_binds_corrected_revision(monkeypatch):
    edition = "expositors-bible--g-g-findlay--findlay-expositorgal--ccel-electronic"
    old = native.FINDLAY_EDITIONS[edition]
    acceptance = {"identity": {"work_id": native.FINDLAY_WORK, "textual_form_id": old[0],
                               "edition_id": edition, "acquisition_id": old[1]}, "source": {}}
    assert native._findlay_expected(acceptance) == old
    acceptance["representation_revision"] = {"id": "findlay-expositorgal-source-text-corrections-20261008-v1"}
    corrected = native._findlay_expected(acceptance)
    assert corrected[5:] == (old[5] + 3 * 88, *old[6:])
    monkeypatch.setattr(native, "_sha", lambda raw: corrected[2])
    metadata = {"acceptance": acceptance, "language": "en", "master_path": __file__}
    assert native.route(metadata) == "findlay"
    crossed = deepcopy(metadata)
    crossed["acceptance"]["representation_revision"]["id"] = "unreviewed-revision"
    with pytest.raises(PipelineError, match="exact accepted witness"):
        native.route(crossed)
    monkeypatch.setattr(native, "_sha", lambda raw: "0" * 64)
    with pytest.raises(PipelineError, match="exact accepted witness"):
        native.route(metadata)


def test_corrected_revisions_cannot_claim_other_editions():
    eph = "expositors-bible--g-g-findlay--findlay-expositoreph--ccel-electronic"
    with pytest.raises(PipelineError, match="different edition"):
        native._findlay_expected({"identity": {"edition_id": eph}, "representation_revision": {
            "id": "findlay-expositorgal-source-text-corrections-20261008-v1"}})
    other = next(key for key in grouped.PROFILES if "dods" not in key)
    with pytest.raises(PipelineError, match="different edition"):
        grouped.select({"identity": {"edition_id": other}, "root": ".", "accepted": {
            "representation_revision": {"id": "dods-expositorjohn1-source-text-corrections-20261008-v1"}}},
            category="commentary")
