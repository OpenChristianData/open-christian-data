"""Exercise public privacy transforms with synthetic accepted-row shapes."""

from copy import deepcopy
import base64
import json

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.release import catholic_encyclopedia_public as catholic
from ocd_kernel.release import final_public_privacy as privacy


AUTHORITY = {"acceptance_sha256": "a" * 64, "master_sha256": "b" * 64}


def _node(kind, content, **attributes):
    return {"kind": kind, "attributes": attributes, "content": content}


def _text(value):
    return {"kind": "text", "text": value}


def _carrier_rows(item):
    if item in privacy.BIBLES:
        count = 23143 if item.startswith("isaac-leeser") else 7954
        private = privacy.BIBLES[item]
        return [{"record_id": str(index), "text": "Retained verse.",
                 "versification": private, "locator": {"versification": private}}
                for index in range(count)]
    if item == privacy.IGNATIUS:
        return [{"record_id": "one", "text": "Historical letter.",
                 "structure": [_node("reference", [_text("Page 141")],
                                      source_target=privacy.IGNATIUS_PRIVATE_TARGET)],
                 "source_references": [{"target": privacy.IGNATIUS_PRIVATE_TARGET}]}]
    if item == privacy.BARNES:
        key, value, count = "number", "c" * 64, 166
    else:
        key, value = "source_annotations", "urn:ocd:private:retained-source"
        count = 7 if item == privacy.PRAYERS else 65 if item in privacy.AJOPS else 1574
    return [{"record_id": "one", "text": "Historical wording and attribution.",
             "structure": [_node("paragraph", [_text("Retained words.")], **{key: value})
                           for _ in range(count)]}]


CASES = [
    *privacy.BIBLES,
    privacy.BARNES,
    privacy.PRAYERS,
    privacy.IGNATIUS,
    "ajops-v1-2024-a2--ajops-v1-2024-a2-publisher-jats",
    "john-owen-mortification--john-owen-mortification-ccel-thml-electronic",
]


@pytest.mark.parametrize("item", CASES)
def test_public_carriers_remove_only_reviewed_fields_and_restore_exact_rows(item):
    private = _carrier_rows(item)
    before = deepcopy(private)

    public, receipt = privacy.public_rows(private, item_id=item, **AUTHORITY)

    assert private == before
    assert [row["text"] for row in public] == [row["text"] for row in private]
    if item in privacy.BIBLES:
        label = privacy.BIBLES[item].rsplit(":", 1)[0]
        assert all(row["versification"] == row["locator"]["versification"] == label
                   for row in public)
    elif item == privacy.IGNATIUS:
        assert public[0]["structure"][0]["attributes"]["source_target"] == "#Page_141"
        assert public[0]["source_references"] == [{"target": "#Page_141"}]
    else:
        assert all(node["attributes"] == {} for node in public[0]["structure"])
    assert privacy.restore(public, receipt, item_id=item, **AUTHORITY) == before


@pytest.mark.parametrize("mutation", ["public-text", "private-preimage", "authority", "field-path"])
def test_private_carrier_inverse_rejects_tampering(mutation):
    public, receipt = privacy.public_rows(_carrier_rows(privacy.IGNATIUS),
                                          item_id=privacy.IGNATIUS, **AUTHORITY)
    if mutation == "public-text":
        public[0]["text"] = "Altered historical text."
    elif mutation == "private-preimage":
        receipt["rewrites"][0]["fields"][0]["private"] = "another-source"
    elif mutation == "authority":
        receipt["authority"]["master_sha256"] = "d" * 64
    else:
        receipt["rewrites"][0]["fields"][0]["path"] = ["missing", "source_target"]
    with pytest.raises(PipelineError):
        privacy.restore(public, receipt, item_id=privacy.IGNATIUS, **AUTHORITY)


def test_private_carrier_inverse_survives_canonical_json_serialization():
    private = _carrier_rows(privacy.IGNATIUS)
    public, receipt = privacy.public_rows(private, item_id=privacy.IGNATIUS, **AUTHORITY)
    stored = json.loads(canonical_bytes(public))
    assert privacy.restore(stored, receipt, item_id=privacy.IGNATIUS, **AUTHORITY) == private


def test_private_carrier_artifact_is_independent_of_dictionary_key_order():
    private = _carrier_rows(privacy.IGNATIUS)
    canonical = json.loads(canonical_bytes(private))
    assert privacy.public_rows(private, item_id=privacy.IGNATIUS, **AUTHORITY) == privacy.public_rows(
        canonical, item_id=privacy.IGNATIUS, **AUTHORITY)


@pytest.mark.parametrize('reverse', [False, True])
def test_private_carrier_inverse_accepts_legacy_field_order_without_mutating_it(reverse):
    private = _carrier_rows(privacy.IGNATIUS)
    public, receipt = privacy.public_rows(private, item_id=privacy.IGNATIUS, **AUTHORITY)
    if reverse:
        receipt['rewrites'][0]['fields'].reverse()
    before = deepcopy(receipt)
    assert privacy.restore(json.loads(canonical_bytes(public)), receipt,
                           item_id=privacy.IGNATIUS, **AUTHORITY) == private
    assert receipt == before


@pytest.mark.parametrize('mutation', ['missing-field', 'duplicate-field'])
def test_private_carrier_order_compatibility_keeps_completeness_checks(mutation):
    public, receipt = privacy.public_rows(_carrier_rows(privacy.IGNATIUS),
                                          item_id=privacy.IGNATIUS, **AUTHORITY)
    fields = receipt['rewrites'][0]['fields']
    if mutation == 'missing-field':
        fields.pop()
    else:
        fields.append(deepcopy(fields[0]))
    with pytest.raises(PipelineError):
        privacy.restore(json.loads(canonical_bytes(public)), receipt,
                        item_id=privacy.IGNATIUS, **AUTHORITY)


@pytest.mark.parametrize("mutation", ["unreviewed-item", "missing-carrier", "generic-private-field", "invalid-authority"])
def test_public_carrier_transform_rejects_unreviewed_inputs(mutation):
    rows = _carrier_rows(privacy.IGNATIUS)
    item = privacy.IGNATIUS
    authority = dict(AUTHORITY)
    if mutation == "unreviewed-item":
        item = "unreviewed-work"
    elif mutation == "missing-carrier":
        rows[0]["source_references"] = []
    elif mutation == "generic-private-field":
        rows[0]["provenance"] = {"source_location": "retained-input"}
    else:
        authority["master_sha256"] = None
    with pytest.raises(PipelineError):
        privacy.public_rows(rows, item_id=item, **authority)


def _source_node(kind, content, *, html=None, **attrs):
    fields = {"rend": "html-attributes:" + json.dumps(html)} if html is not None else {}
    return _node(kind, content, source_annotations=json.dumps({"fields": fields}), **attrs)


def _catholic_article():
    paragraph = lambda text: _source_node("paragraph", [_text(text)])
    credits = _source_node("division", [
        paragraph("About this page"),
        paragraph("APA citation. Author. (1907). Historical article."),
        paragraph("Transcription. Historical transcriber credit."),
        paragraph("Contact information. Modern site contact."),
    ])
    publication = _source_node("division", [credits], html={"class": "pub"})
    article = _source_node("division", [
        paragraph("Preserved historical article."),
        paragraph("Please help support the mission of New Advent with a donation."),
        _source_node("figure", [_text("Site-derived image caption.")]),
        _source_node("division", [publication]),
    ], subtype="h1")
    main = _source_node("division", [article], html={"id": "springfield2"})
    footer = _source_node("division", [paragraph("Copyright © 2026 by New Advent LLC")],
                          html={"id": "ogdenville"})
    return {"record_id": "synthetic-article", "sequence": 49,
            "unit_kind": "encyclopedia-entry", "text": "Private native rendering.",
            "provenance": {"source_url": "https://www.newadvent.org/cathen/00003a.htm",
                           "source_location": "raw/synthetic/private.html"},
            "structure": [_source_node("division", [main, footer])]}


def test_catholic_article_keeps_historical_words_and_credits_without_site_or_private_fields():
    private = _catholic_article()
    before = deepcopy(private)
    public = catholic._article(private)

    assert private == before
    assert "Preserved historical article." in public["text"]
    assert "APA citation. Author. (1907). Historical article." in public["text"]
    assert "Historical transcriber credit." in public["text"]
    encoded = json.dumps(public)
    for removed in ("Contact information.", "Copyright", "donation", "Site-derived",
                    "source_annotations", "source_location", "raw/synthetic"):
        assert removed not in encoded
    assert public["provenance"]["source_url"] == private["provenance"]["source_url"]


@pytest.mark.parametrize("mutation", ["missing-credit", "unexpected-credit", "wrong-envelope", "private-text"])
def test_catholic_article_rejects_changed_source_boundaries(mutation):
    private = _catholic_article()
    article = private["structure"][0]["content"][0]["content"][0]
    publication = article["content"][-1]["content"][0]["content"][0]
    if mutation == "missing-credit":
        del publication["content"][1]
    elif mutation == "unexpected-credit":
        publication["content"].append(_source_node("paragraph", [_text("Unreviewed site prose.")]))
    elif mutation == "wrong-envelope":
        private["structure"][0]["content"].pop()
    else:
        article["content"][0]["content"][0]["text"] = "Read raw/private/source.xml"
    with pytest.raises(PipelineError):
        catholic._article(private)


def test_catholic_public_transform_requires_exact_authority_and_complete_denominator():
    with pytest.raises(PipelineError, match="exact accepted authority"):
        catholic.public_rows([], **AUTHORITY)
    with pytest.raises(PipelineError, match="complete accepted native row denominator"):
        catholic.public_rows([_catholic_article()], acceptance_sha256=catholic.ACCEPTANCE_SHA256,
                              master_sha256=catholic.MASTER_SHA256)


def test_catholic_inverse_payload_round_trip_rejects_trailing_compressed_input():
    private = _catholic_article()
    packed = catholic._packed(private)
    assert catholic._unpack(packed) == private
    bad = base64.b64encode(base64.b64decode(packed) + b"unbound trailing bytes").decode("ascii")
    with pytest.raises(PipelineError, match="private inverse payload invalid"):
        catholic._unpack(bad)


def _harper_case(monkeypatch):
    cell = _node("table-cell", [_text("Retained cell.")],
                 source_annotations=privacy.HARPER_ANNOTATION_PREFIX + "cell", colspan="2")
    table = _node("table", [_node("table-row", [cell])],
                  source_annotations=privacy.HARPER_ANNOTATION_PREFIX + "table", role="harmony")
    rows = [{"record_id": privacy.HARPER_RECORD_ID, "text": "Retained cell.",
             "structure": [table, _node("paragraph", [_text("Source note.")],
                                       source_annotations="historical-layer")]}]
    monkeypatch.setattr(privacy, "HARPER_PRIVATE_ROWS_SHA256", privacy._digest(rows))
    monkeypatch.setitem(privacy.EXPECTED_FIELDS, privacy.HARPER, 2)
    authority = {"acceptance_sha256": privacy.HARPER_ACCEPTANCE_SHA256,
                 "master_sha256": privacy.HARPER_MASTER_SHA256}
    return rows, authority


def test_harper_dispatcher_omits_only_internal_annotations_and_restores(monkeypatch):
    from ocd_kernel.release import public_rows as dispatch
    from ocd_kernel.release.public_allowlist import _scan
    rows, authority = _harper_case(monkeypatch)
    before = deepcopy(rows)
    expected = deepcopy(rows)
    del expected[0]["structure"][0]["attributes"]["source_annotations"]
    del expected[0]["structure"][0]["content"][0]["content"][0]["attributes"]["source_annotations"]
    assert privacy.HARPER in dispatch.HASH_BOUND_ITEMS
    public, inverse = dispatch.public_rows_with_omissions(rows, item_id=privacy.HARPER, **authority)
    assert rows == before and public == expected
    assert _scan(public, "Harper fixture") == []
    assert dispatch.restore_private_source_locations(public, inverse, item_id=privacy.HARPER,
                                                    **authority) == before
    inverse["rewrites"][0]["fields"][0]["private"] += "changed"
    with pytest.raises(PipelineError):
        dispatch.restore_private_source_locations(public, inverse, item_id=privacy.HARPER,
                                                  **authority)


@pytest.mark.parametrize("mutation", ["master", "acceptance", "record", "words", "prefix", "count"])
def test_harper_rejects_changed_authority_content_and_annotation_scope(monkeypatch, mutation):
    rows, authority = _harper_case(monkeypatch)
    if mutation in {"master", "acceptance"}:
        authority[mutation + "_sha256"] = "0" * 64
    elif mutation == "record":
        rows[0]["record_id"] += "changed"
    elif mutation == "words":
        rows[0]["text"] += " invented words"
    elif mutation == "prefix":
        rows[0]["structure"][0]["attributes"]["source_annotations"] = "urn:ocd:other:table"
        monkeypatch.setattr(privacy, "HARPER_PRIVATE_ROWS_SHA256", privacy._digest(rows))
    else:
        monkeypatch.setitem(privacy.EXPECTED_FIELDS, privacy.HARPER, 3)
    with pytest.raises(PipelineError):
        privacy.public_rows(rows, item_id=privacy.HARPER, **authority)
