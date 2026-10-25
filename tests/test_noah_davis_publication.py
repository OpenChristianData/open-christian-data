"""Exact accepted Noah Davis PG20005 public image boundary."""

from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import quote, unquote

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import project_accepted_prose
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import public_rows_with_omissions, restore_private_source_locations
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "tests" else Path(__file__).resolve().parents[2]
ITEM = "noah-davis-narrative-life-1859--noah-davis-narrative-life-1859-pg20005"
ACCEPTANCE = ROOT / "library/works/noah-davis-narrative-life-1859/forms/english-prose/editions/noah-davis-narrative-life-1859-pg20005/acceptance.json"
ACCEPTANCE_SHA = "4182fcfe5d35afa6524f181219d48434df0e28f52b2fcb3417559454dd20ef4e"
MASTER_SHA = "d732a99bb7cbc42742378de115317732ac3859d95a174c2ddda25b897cbe3c74"
LICENSE = "Public domain (United States); identified historical text and apparatus only"
ANNOTATION_PREFIX = "urn:ocd:pg-book:native-inverse:"


def _images(value):
    if isinstance(value, list):
        for child in value:
            yield from _images(child)
    elif isinstance(value, dict):
        if value.get("kind") == "image-reference":
            yield value
        for key, child in value.items():
            if key != "attributes":
                yield from _images(child)


@pytest.fixture(scope="module")
def rows_and_artifact():
    with cached_edition_lookups():
        projected = project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
    private = [dict(row, license=LICENSE) for row in projected["rows"]]
    private, _ = compose_work_metadata(ROOT, private, projected["receipt"])
    public, artifact = public_rows_with_omissions(
        private, item_id=ITEM, acceptance_sha256=ACCEPTANCE_SHA,
        master_sha256=MASTER_SHA)
    return private, public, artifact


def test_noah_davis_full_accepted_text_and_safe_source_image_inverse(rows_and_artifact):
    private, public, artifact = rows_and_artifact
    assert len(private) == len(public) == 359
    assert [row["text"] for row in public] == [row["text"] for row in private]
    assert sum(len(row["text"]) for row in public) == 109281
    assert not _scan(public, "Noah Davis public rows")
    image_attrs = [image["attributes"] for row in public for image in _images(row)]
    assert len(image_attrs) == 1
    assert image_attrs[0]["source_target"] == "source-image:images/church.jpg"
    assert "data:image/jpeg;base64" not in json.dumps(public)
    assert artifact["authority"]["noah_scope_packet_sha256"] == (
        "9053947dced17b6312584dac29940f8e2c900446cdedc38e60bce60e5af79453")
    assert "pg52_review_candidate_sha256" not in artifact["authority"]
    assert sum(len(entry["fields"]) for entry in artifact["omissions"]) == 295
    assert len(artifact["omissions"]) == 291
    assert restore_private_source_locations(
        public, artifact, item_id=ITEM, acceptance_sha256=ACCEPTANCE_SHA,
        master_sha256=MASTER_SHA) == private


@pytest.mark.parametrize("mutation", ["target_mismatch", "corresp_mismatch", "alt_mismatch"])
def test_noah_davis_private_image_authority_rejects_mutations(rows_and_artifact, mutation):
    private, _, _ = rows_and_artifact
    changed = deepcopy(private)
    images = [image for row in changed for image in _images(row)]
    assert len(images) == 1
    attrs = images[0]["attributes"]
    if mutation == "target_mismatch":
        attrs["source_target"] = "data:image/jpeg;base64,AAAA"
    else:
        source = json.loads(unquote(attrs["source_annotations"].removeprefix(ANNOTATION_PREFIX)))
        source[-1 if mutation == "corresp_mismatch" else -2][1] = (
            "images/other.jpg" if mutation == "corresp_mismatch" else "source-alt:other")
        attrs["source_annotations"] = ANNOTATION_PREFIX + quote(
            json.dumps(source, ensure_ascii=False, separators=(",", ":")), safe="")
    with pytest.raises(PipelineError, match="Noah Davis"):
        public_rows_with_omissions(changed, item_id=ITEM,
            acceptance_sha256=ACCEPTANCE_SHA, master_sha256=MASTER_SHA)


def test_noah_davis_inverse_rejects_changed_public_text_and_receipt(rows_and_artifact):
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


def test_noah_davis_wrong_acceptance_cannot_enter_public_route(rows_and_artifact):
    private, _, _ = rows_and_artifact
    with pytest.raises(PipelineError, match="authority"):
        public_rows_with_omissions(private, item_id=ITEM,
            acceptance_sha256="0" * 64, master_sha256=MASTER_SHA)
