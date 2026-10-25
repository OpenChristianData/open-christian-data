"""Focused mutation checks for the exact PG public-row candidate."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from urllib.parse import quote, unquote

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.release.public_allowlist import _scan


CANDIDATE = Path(__file__).with_name("public_rows_candidate.py")
if CANDIDATE.exists():
    SPEC = importlib.util.spec_from_file_location(
        "ocd_kernel.release.public_rows_candidate", CANDIDATE)
    assert SPEC is not None and SPEC.loader is not None
    boundary = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(boundary)
else:
    from ocd_kernel.release import public_rows as boundary

JUDSON = "edward-judson-life-of-adoniram-judson--judson-life-of-adoniram-judson-1883-pg70894"
GERHARDT = "gerhardt-spiritual-songs--gerhardt-spiritual-songs-gutenberg-electronic"
JARENA = "jarena-lee-religious-experience-and-journal--jarena-lee-religious-experience-and-journal-gutenberg-electronic"
KEBLE = "keble-christian-year--keble-christian-year-gutenberg-electronic"
PATON = "paton-missionary-new-hebrides-autobiography-3vol-aggregate--paton-autobiography-three-volume-pg-edition"
PG49917 = "pg49917-assumption-sermon-i--pg49917-assumption-sermon-i-pg49917-edition"
CLEMENT = "pg71937-stromata--pg71937-stromata-pg73020-edition"
DERHAM = "william-derham-physico-theology-1720--pg75254-1720-london"
TYERMAN = "tyerman-oxford-methodists-1873--pg70497-1873-harper-brothers"


def authority(item_id: str) -> dict[str, str]:
    acceptance, master = boundary.PG_ITEMS[item_id]
    return {"acceptance_sha256": acceptance, "master_sha256": master}


def rows(attributes: dict, *, kind: str = "native-unit") -> list[dict]:
    return [{"record_id": "one", "text": "Original text", "language": "en",
             "provenance": {"edition_title": "Original edition"},
             "structure": [{"kind": kind, "attributes": attributes,
                            "content": [{"kind": "text", "text": "Original text"}]}]}]


def encoded(prefix: str, value) -> str:
    return prefix + quote(json.dumps(value, ensure_ascii=False, separators=(",", ":")), safe="")


@pytest.mark.parametrize("item_id,attributes,kind,expected", [
    (GERHARDT, {"source_annotations": "urn:ocd:source-ordinal:41", "language": "de"},
     "list", "source-ordinal:41"),
    (KEBLE, {"source_annotations": "urn:ocd:source-alt-and-title:Book%20cover",
             "style": "presentation-style-omitted-sha256:" + "a" * 64},
     "image-reference", "source-alt-and-title:Book cover"),
    (JUDSON, {"source_annotations": encoded("urn:ocd:pg-book:native-inverse:",
                                             [["n", "5"], ["url", "images/cover.jpg"]]),
              "source_target": "data:image/jpeg;base64,AAAA", "source_id": "img_images_cover.jpg"},
     "image-reference", "source-image:images/cover.jpg"),
    (TYERMAN, {"source_annotations": encoded("urn:ocd:pg-book:native-inverse:",
                                              [["url", "images/frontispiece.jpg"]]),
               "source_target": "data:image/jpeg;base64,AAAA"},
     "image-reference", "source-image:images/frontispiece.jpg"),
    (DERHAM, {"source_annotations": encoded("urn:ocd:pg-book:native-inverse:",
                                             {"tag": "milestone", "attributes": [
                                                 ["unit", "source-image-reference"],
                                                 ["rend", "source-image-member:images/titlepage.jpg source-alt:"]]}),
              "source_target": "data:image/jpeg;base64,AAAA"},
     "image-reference", "source-image:images/titlepage.jpg"),
    (JARENA, {"source_target": "raw/gutenberg/66953/html/images/frontispiece.jpg",
              "source_id": "img_images_frontispiece.jpg"},
     "image-reference", "source-image:frontispiece.jpg"),
    (PATON, {"source_annotations": encoded("urn:ocd:paton:native-inverse:",
                                            [["unit", "source-rule"], ["rend", "pb c002"]])},
     "milestone", "source-annotation:"),
    (PG49917, {"source_annotations": encoded("urn:ocd:pg49917:source-marker:",
                                              {"unit": "source-html-comment", "n": "1221",
                                               "rend": "comment-digest:" + "a" * 64})},
     "milestone", "source-annotation:"),
    (CLEMENT, {"source_annotations": encoded("urn:ocd:clement:source-marker:",
                                              {"unit": "source-image-reference", "n": "736",
                                               "rend": "source-image-member:images/line.jpg source-alt: "
                                                       "presentation-style-omitted-sha256:" + "b" * 64}),
               "style": "source-class:smaller presentation-style-omitted-sha256:" + "c" * 64},
     "image-reference", "source-annotation:"),
    (DERHAM, {"source_annotations": encoded("urn:ocd:pg-book:native-inverse:",
                                             {"tag": "figure", "attributes": [["n", "14368"],
                                               ["rend", "source-class:figcenter "
                                                        "presentation-style-omitted-sha256:" + "d" * 64]],
                                              "children_attributes": [{"position": 1, "tag": "figDesc",
                                                                       "attributes": [["rend", "source-class:caption"]]}]})},
     "source-figure", "source-annotation:"),
])
def test_scoped_safe_annotations_and_images_restore_exactly(item_id, attributes, kind, expected) -> None:
    private = rows(attributes | {"source_target" : attributes.get("source_target", "https://example.org/link"),
                                 "row_span": "2"}, kind=kind)
    before = deepcopy(private)
    public, artifact = boundary.public_rows_with_omissions(private, item_id=item_id, **authority(item_id))
    assert artifact is not None and artifact["contract"] == boundary.PG_CONTRACT
    assert private == before
    assert not _scan(public, "synthetic PG public rows")
    node = public[0]["structure"][0]
    field = "source_target" if expected.startswith("source-image:") else "source_annotations"
    assert node["attributes"][field].startswith(expected)
    assert node["attributes"]["row_span"] == "2"
    assert node["content"][0]["text"] == "Original text"
    assert boundary.restore_private_source_locations(public, artifact, item_id=item_id,
                                                     **authority(item_id)) == private


@pytest.mark.parametrize("tamper", ["text", "language", "link", "span", "annotation",
                                     "receipt_hash", "receipt_field", "legacy_contract", "authority"])
def test_pg_inverse_rejects_semantic_or_receipt_mutation(tamper: str) -> None:
    annotation = encoded("urn:ocd:pg-book:native-inverse:", [["n", "5"], ["url", "images/cover.jpg"]])
    private = rows({"source_annotations": annotation, "source_target": "data:image/jpeg;base64,AAAA",
                    "language": "en", "row_span": "2"}, kind="image-reference")
    public, artifact = boundary.public_rows_with_omissions(private, item_id=JUDSON, **authority(JUDSON))
    assert artifact is not None
    public, artifact = deepcopy(public), deepcopy(artifact)
    attrs = public[0]["structure"][0]["attributes"]
    if tamper == "text":
        public[0]["structure"][0]["content"][0]["text"] = "Changed"
    elif tamper == "language":
        attrs["language"] = "fr"
    elif tamper == "link":
        attrs["source_target"] = "https://example.org/other"
    elif tamper == "span":
        attrs["row_span"] = "3"
    elif tamper == "annotation":
        attrs["source_annotations"] += "%20"
    elif tamper == "receipt_hash":
        artifact["omissions"][0]["original_row_sha256"] = "0" * 64
    elif tamper == "receipt_field":
        artifact["omissions"][0]["fields"][0]["path"] = ["text"]
    elif tamper == "legacy_contract":
        artifact = {"contract": boundary.CONTRACT, "item_id": JUDSON, "row_count": 1,
                    "omissions": [{"row_index": 0, "record_id": "one", "field": boundary.FIELD,
                                   "value": "raw/private.xml", "original_row_sha256": "0" * 64,
                                   "public_row_sha256": sha256(canonical_bytes(public[0])).hexdigest()}]}
    else:
        artifact["authority"]["master_sha256"] = "0" * 64
    with pytest.raises(PipelineError):
        boundary.restore_private_source_locations(public, artifact, item_id=JUDSON, **authority(JUDSON))


def test_wrong_authority_and_unknown_source_annotation_fail_closed() -> None:
    with pytest.raises(PipelineError, match="authority differs"):
        boundary.public_rows_with_omissions(
            rows({"source_annotations": "urn:ocd:source-ordinal:41"}),
            item_id=GERHARDT, acceptance_sha256="0" * 64,
            master_sha256=authority(GERHARDT)["master_sha256"])
    with pytest.raises(PipelineError, match="unapproved"):
        boundary.public_rows_with_omissions(
            rows({"source_annotations": "urn:ocd:unknown:private"}),
            item_id=GERHARDT, **authority(GERHARDT))
