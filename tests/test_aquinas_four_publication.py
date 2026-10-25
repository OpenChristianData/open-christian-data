"""Exact four-part Aquinas public omission and private inverse."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release import aquinas_public
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import (HASH_BOUND_ITEMS, public_rows_with_omissions,
                                            restore_private_source_locations)
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / ("library/works/aquinas-summa-theologica-four-parts/forms/"
                     "aquinas-summa-theologica-four-parts-gutenberg-retained-en/editions/"
                     "aquinas-summa-theologica-four-parts-gutenberg-electronic/acceptance.json")


@pytest.fixture(scope="module")
def accepted_rows():
    assert sha256(ACCEPTANCE.read_bytes()).hexdigest() == aquinas_public.ACCEPTANCE_SHA256
    with cached_edition_lookups():
        projection = project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
        assert not verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE,
                                         rows=projection["rows"], receipt=projection["receipt"])
        rows, _ = compose_work_metadata(
            ROOT, [dict(row, license=aquinas_public.LICENSE) for row in projection["rows"]],
            projection["receipt"])
    assert aquinas_public._digest(rows) == aquinas_public.PRIVATE_ROWS_SHA256
    return rows


def test_four_historical_rows_and_exact_private_inverse(accepted_rows):
    public, artifact = aquinas_public.public_rows(
        accepted_rows, acceptance_sha256=aquinas_public.ACCEPTANCE_SHA256,
        master_sha256=aquinas_public.MASTER_SHA256)
    assert len(public) == len(artifact["omissions"]) == 4
    assert aquinas_public._digest(public) == aquinas_public.PUBLIC_ROWS_SHA256
    assert not _scan(public, "Aquinas public rows")
    assert aquinas_public.restore_private_rows(
        public, artifact, acceptance_sha256=aquinas_public.ACCEPTANCE_SHA256,
        master_sha256=aquinas_public.MASTER_SHA256) == accepted_rows
    for original, row, omission in zip(accepted_rows, public, artifact["omissions"], strict=True):
        assert original["record_id"] == row["record_id"]
        assert len(omission["private_nodes"]) == 30
        assert aquinas_public.HEADING not in row["text"]
        assert all(original[key] == row[key] for key in original if key not in {"text", "structure"})


def test_omission_receipt_rejects_changed_text_and_incomplete_private_notes(accepted_rows):
    public, artifact = aquinas_public.public_rows(
        accepted_rows, acceptance_sha256=aquinas_public.ACCEPTANCE_SHA256,
        master_sha256=aquinas_public.MASTER_SHA256)
    bad_public = deepcopy(public)
    bad_public[0]["text"] += "changed"
    with pytest.raises(PipelineError):
        aquinas_public.restore_private_rows(
            bad_public, artifact, acceptance_sha256=aquinas_public.ACCEPTANCE_SHA256,
            master_sha256=aquinas_public.MASTER_SHA256)
    for mutation in (lambda r: r["omissions"][0]["private_nodes"].pop(),
                     lambda r: r["omissions"][0].update(private_text="altered"),
                     lambda r: r["omissions"].pop(),
                     lambda r: r["authority"].update(master_sha256="0" * 64)):
        bad_artifact = deepcopy(artifact)
        mutation(bad_artifact)
        with pytest.raises(PipelineError):
            aquinas_public.restore_private_rows(
                public, bad_artifact, acceptance_sha256=aquinas_public.ACCEPTANCE_SHA256,
                master_sha256=aquinas_public.MASTER_SHA256)
    bad_private = deepcopy(accepted_rows)
    bad_private[0]["text"] += "changed"
    with pytest.raises(PipelineError):
        aquinas_public.public_rows(
            bad_private, acceptance_sha256=aquinas_public.ACCEPTANCE_SHA256,
            master_sha256=aquinas_public.MASTER_SHA256)


def test_source_bound_dispatch_rejects_unapproved_authority():
    assert aquinas_public.ITEM in HASH_BOUND_ITEMS
    with pytest.raises(PipelineError, match="acceptance authority"):
        public_rows_with_omissions([], item_id=aquinas_public.ITEM,
                                   acceptance_sha256="0" * 64,
                                   master_sha256=aquinas_public.MASTER_SHA256)
    with pytest.raises(PipelineError, match="acceptance authority"):
        restore_private_source_locations([], {}, item_id=aquinas_public.ITEM,
                                         acceptance_sha256="0" * 64,
                                         master_sha256=aquinas_public.MASTER_SHA256)
