"""Accepted Campion PG-book text-only public boundary and exact inverse."""

from copy import deepcopy
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import project_accepted_prose
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import public_rows_with_omissions, restore_private_source_locations
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "tests" else Path(__file__).resolve().parents[2]
ITEM = "louise-imogen-guiney-blessed-edmund-campion--pg52731-1914"
ACCEPTANCE = ROOT / "library/works/louise-imogen-guiney-blessed-edmund-campion/forms/english/editions/pg52731-1914/acceptance.json"
ACCEPTANCE_SHA = "1eb43ad355ddefb1c55da6a87a7a404fd20a765b7ee7edd70a83ea567c92216e"
MASTER_SHA = "ff6bc90d654f350003a7b49989c5ed2cc4a4ee461d91e282b326a1f5ff395dad"
LICENSE = "Public domain (United States); identified historical text and apparatus only"


@pytest.fixture(scope="module")
def rows_and_artifact():
    with cached_edition_lookups():
        projected = project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
    rows = [dict(row, license=LICENSE) for row in projected["rows"]]
    rows, _ = compose_work_metadata(ROOT, rows, projected["receipt"])
    public, artifact = public_rows_with_omissions(rows, item_id=ITEM,
        acceptance_sha256=ACCEPTANCE_SHA, master_sha256=MASTER_SHA)
    return rows, public, artifact


def _attributes(value, key):
    found = []
    if isinstance(value, list):
        for child in value:
            found.extend(_attributes(child, key))
    elif isinstance(value, dict):
        if "kind" in value and isinstance(value.get("attributes"), dict):
            if key in value["attributes"]:
                found.append(value["attributes"][key])
        for child_key, child in value.items():
            if child_key != "attributes":
                found.extend(_attributes(child, key))
    return found


def test_campion_private_images_and_annotations_have_exact_public_inverse(rows_and_artifact):
    private, public, artifact = rows_and_artifact
    assert len(private) == len(public) == 1
    assert private[0]["text"] == public[0]["text"]
    assert not _scan(public, "Campion public row")
    targets = _attributes(public, "source_target")
    assert sum(target.startswith("source-image:images/") for target in targets) == 12
    assert not any(target.startswith("data:image/") for target in targets)
    assert artifact["contract"] == "ocd-public-pg-source-bookkeeping-v1"
    assert len(artifact["omissions"]) == 1
    assert len(artifact["omissions"][0]["fields"]) == 309
    assert "campion_scope_packet_sha256" in artifact["authority"]
    assert "pg52_review_candidate_sha256" not in artifact["authority"]
    assert restore_private_source_locations(public, artifact, item_id=ITEM,
        acceptance_sha256=ACCEPTANCE_SHA, master_sha256=MASTER_SHA) == private


def test_campion_inverse_rejects_changed_public_text_and_incomplete_receipt(rows_and_artifact):
    _, public, artifact = rows_and_artifact
    changed = deepcopy(public)
    changed[0]["text"] = "tampered " + changed[0]["text"]
    with pytest.raises(PipelineError, match="binding"):
        restore_private_source_locations(changed, artifact, item_id=ITEM,
            acceptance_sha256=ACCEPTANCE_SHA, master_sha256=MASTER_SHA)
    incomplete = deepcopy(artifact)
    incomplete["omissions"][0]["fields"].pop()
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, incomplete, item_id=ITEM,
            acceptance_sha256=ACCEPTANCE_SHA, master_sha256=MASTER_SHA)


def test_campion_wrong_authority_cannot_enter_public_route(rows_and_artifact):
    private, public, artifact = rows_and_artifact
    with pytest.raises(PipelineError, match="authority"):
        public_rows_with_omissions(private, item_id=ITEM,
            acceptance_sha256="0" * 64, master_sha256=MASTER_SHA)
    with pytest.raises(PipelineError, match="authority"):
        restore_private_source_locations(public, artifact, item_id=ITEM,
            acceptance_sha256=ACCEPTANCE_SHA, master_sha256="0" * 64)
