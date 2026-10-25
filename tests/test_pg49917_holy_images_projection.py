"""Public projection of the retained Holy Images TEI keeps comment digests private."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import (
    HOLY_IMAGES_PROFILE,
    project_document,
    verify_document,
)


ROOT = Path(__file__).resolve().parents[1]
TEI = ROOT / "library/works/pg49917-holy-images/integration/pg49917-html-v1/candidate/package/content.tei.xml"
IDENTITY = {
    "work_id": "pg49917-holy-images",
    "textual_form_id": "pg49917-holy-images-english",
    "edition_id": "pg49917-holy-images-pg49917-edition",
}
CONTEXT = {
    "identity": IDENTITY,
    "language": "en",
    "representation_revision": "pg49917-holy-images-projection-check",
    "edition_title": "St John Damascene on Holy Images",
    "category": "prose",
    "_allow_acceptance_metadata": True,
    "projection_profile": HOLY_IMAGES_PROFILE,
}


def test_holy_images_projector_and_independent_checker_keep_comment_digests_private() -> None:
    output = project_document(TEI, **CONTEXT)
    assert len(output["rows"]) == 2
    assert verify_document(TEI, output["rows"], output["receipt"], **CONTEXT) == []
    private_markers = [entry for entry in output["receipt"]["inventory"]
                       if entry["tag"] == "milestone" and entry["attributes"].get("unit") == "source-html-comment"]
    assert len(private_markers) == 5
    assert all(entry["role"] == "source-generator-only" for entry in private_markers)
    public_bytes = json.dumps(output["rows"], ensure_ascii=False).encode("utf-8")
    assert b"source-html-comment" not in public_bytes
    assert all(entry["attributes"]["n"].encode("ascii") not in public_bytes for entry in private_markers)

    wrong_receipt = copy.deepcopy(output["receipt"])
    marker = next(entry for entry in wrong_receipt["inventory"] if entry["tag"] == "milestone")
    marker["attributes"]["n"] = "0" * 64
    assert verify_document(TEI, output["rows"], wrong_receipt, **CONTEXT)


def test_holy_images_profile_rejects_other_identities_and_missing_profile() -> None:
    with pytest.raises(PipelineError, match="Holy Images source identity differs"):
        project_document(TEI, **{**CONTEXT, "identity": {**IDENTITY, "work_id": "another-work"}})
    with pytest.raises(PipelineError, match="unsupported native milestone unit"):
        project_document(TEI, **{**CONTEXT, "projection_profile": None})
