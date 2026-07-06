"""Tests for the JE apparatus-TEI materializer (batch 06 spine)."""
from __future__ import annotations

import io

import pytest
from lxml import etree

from build.lib.canonical_token import canonical_token_id
from build.tei.materialize_je import apparatus_token, materialize_page_document, resolve_edition_page_key
from build.tei.writer import TEI_NS, XML_ID

LEM = f"{{{TEI_NS}}}lem"
RDG = f"{{{TEI_NS}}}rdg"
NOTE = f"{{{TEI_NS}}}note"
W = f"{{{TEI_NS}}}w"
ZONE = f"{{{TEI_NS}}}zone"
PB = f"{{{TEI_NS}}}pb"
WITNESS = f"{{{TEI_NS}}}witness"
RESP_STMT = f"{{{TEI_NS}}}respStmt"


def _position(candidates: list[dict]) -> dict:
    return {
        "position_id": "vol_02:page_0010:body:c1:l000:p000",
        "reference_bbox": {"x": 419, "y": 228, "w": 269, "h": 62},
        "candidate_set": candidates,
    }


def test_attested_token_emits_lem_with_wit_and_losing_rdg() -> None:
    position = _position(
        [
            {"candidate_id": "cand_001", "raw_reading": "on", "attesting_families": ["abbyy", "kraken", "tesseract"]},
            {"candidate_id": "cand_002", "raw_reading": "in", "attesting_families": ["azure-ai-vision"]},
        ]
    )
    event = {
        "event_id": "evt-1",
        "status_authority": "consensus",
        "decision_extras_carried": {"chosen_reading_index": 0, "origin_kind": "observed"},
    }

    w = apparatus_token(position, event, page_id="page_0010", ordinal=0)

    assert etree.QName(w).localname == "w"
    assert w.get(XML_ID) == "w_page_0010_0000"
    assert w.get("facs") == "#z_page_0010_0000"

    app = w[0]
    assert etree.QName(app).localname == "app"

    lem = app.find(LEM)
    assert lem.get("wit") == "#abbyy #kraken #tesseract"
    assert lem.get("cert") == "high"
    assert lem.get("resp") is None
    assert lem.text == "on"

    rdgs = app.findall(RDG)
    assert len(rdgs) == 1
    assert rdgs[0].get("wit") == "#azure-ai-vision"
    assert rdgs[0].text == "in"


def test_witnessless_token_emits_resp_no_wit_and_provenance_note() -> None:
    position = _position(
        [
            {"candidate_id": "cand_001", "raw_reading": "Aaron", "attesting_families": ["abbyy"]},
            {"candidate_id": "cand_002", "raw_reading": "Aavon", "attesting_families": ["tesseract"]},
        ]
    )
    event = {
        "event_id": "je:vol_02:page_0010:p001:policy-v1",
        "actor_id": "system:corrector",
        "status_authority": "consensus",
        "decision_extras_carried": {"chosen_reading_index": 0, "origin_kind": "machine_composed"},
    }

    w = apparatus_token(position, event, page_id="page_0010", ordinal=1)
    app = w[0]

    lem = app.find(LEM)
    assert lem.get("wit") is None
    assert lem.get("resp") == "#corrector"
    assert lem.get("cert") == "high"
    assert lem.text == "Aaron"

    # The losing OCR candidate is still recorded as a witnessed rdg.
    rdgs = app.findall(RDG)
    assert len(rdgs) == 1
    assert rdgs[0].get("wit") == "#tesseract"

    # Provenance points back to the originating decision event (replay lineage).
    note = app.find(NOTE)
    assert note.get("type") == "provenance"
    assert note.text == "decision_event_id: je:vol_02:page_0010:p001:policy-v1"


def test_single_candidate_attested_token_has_no_rdg() -> None:
    position = _position([{"candidate_id": "cand_001", "raw_reading": "the", "attesting_families": ["abbyy", "azure-ai-vision"]}])
    event = {
        "event_id": "evt-x",
        "status_authority": "consensus",
        "decision_extras_carried": {"chosen_reading_index": 0, "origin_kind": "observed"},
    }
    w = apparatus_token(position, event, page_id="page_0010", ordinal=2)
    app = w[0]
    assert app.find(LEM).get("wit") == "#abbyy #azure-ai-vision"
    assert app.findall(RDG) == []


def _doc_position(position_id: str, text: str, x: int) -> dict:
    return {
        "position_id": position_id,
        "reference_bbox": {"x": x, "y": 20, "w": 30, "h": 10},
        "candidate_set": [
            {"candidate_id": "cand_001", "raw_reading": text, "attesting_families": ["abbyy", "tesseract"]},
            {"candidate_id": "cand_002", "raw_reading": f"{text}x", "attesting_families": ["azure-ai-vision"]},
        ],
    }


def _wct_page() -> dict:
    positions = [
        _doc_position("vol_02:page_0010:body:c1:l000:p000", "on", 10),
        _doc_position("vol_02:page_0010:body:c1:l000:p001", "the", 50),
        _doc_position("vol_02:page_0010:body:c1:l000:p002", "sea", 90),
    ]
    return {
        "work_id": "jewish-encyclopedia.vol_02",
        "volume_id": "vol_02",
        "page_id": "page_0010",
        "source_image": {
            "path": "raw/jewish-encyclopedia/ia-pages/vol_02/page_0010.jpg",
            "sha256": "abc123",
        },
        "available_engines": [
            {"engine_id": "ia-abbyy-v1", "family": "abbyy"},
            {"engine_id": "tesseract-py314-v1", "family": "tesseract"},
            {"engine_id": "kraken-py312-v1", "family": "kraken"},
            {"engine_id": "azure-ai-vision-v1", "family": "azure-ai-vision"},
        ],
        "reading_order": [position["position_id"] for position in positions],
        "positions": positions,
    }


def _event_for(
    wct_page: dict,
    edition_page_key: dict,
    ordinal: int,
    *,
    origin_kind: str = "observed",
    structural_path: str | None = None,
) -> dict:
    position_id = wct_page["reading_order"][ordinal]
    return {
        "event_id": f"evt-{ordinal}",
        "canonical_token_id": canonical_token_id(
            "jewish-encyclopedia.vol_02",
            "vol_02",
            edition_page_key,
            ordinal,
        ),
        "structural_path_at_decision": structural_path or position_id,
        "status_authority": "consensus",
        "actor_id": "system:corrector",
        "decision_extras_carried": {"chosen_reading_index": 0, "origin_kind": origin_kind},
    }


def _serialized_bytes(tree: etree._ElementTree) -> bytes:
    output = io.BytesIO()
    tree.write(output, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    return output.getvalue()


def test_resolve_edition_page_key_uses_source_image_sha_manifest_match() -> None:
    wct_page = _wct_page()
    ia_manifest = {"pages": [{"sha256": "sha256:abc123", "page_num": 10}]}

    assert resolve_edition_page_key(wct_page, ia_manifest) == {"section": "body", "anchor": 10, "ordinal": 0}


def test_page_document_emits_released_tokens_and_matching_zones_in_order() -> None:
    wct_page = _wct_page()
    edition_page_key = {"section": "body", "anchor": 10, "ordinal": 0}
    events = [
        _event_for(wct_page, edition_page_key, 0),
        _event_for(wct_page, edition_page_key, 2),
    ]

    tree = materialize_page_document(
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    )

    words = tree.findall(f".//{W}")
    zones = tree.findall(f".//{ZONE}")
    assert [word.get(XML_ID) for word in words] == ["w_page_0010_0000", "w_page_0010_0002"]
    assert [word.get("facs") for word in words] == ["#z_page_0010_0000", "#z_page_0010_0002"]
    assert [zone.get(XML_ID) for zone in zones] == ["z_page_0010_0000", "z_page_0010_0002"]
    assert [(zone.get("ulx"), zone.get("uly"), zone.get("lrx"), zone.get("lry")) for zone in zones] == [
        ("10", "20", "40", "30"),
        ("90", "20", "120", "30"),
    ]
    assert [word.find(f".//{LEM}").text for word in words] == ["on", "sea"]

    pb = tree.find(f".//{PB}")
    assert pb.get(XML_ID) == "pb_page_0010"
    assert pb.get("n") == "10"
    assert pb.get("facs") == "#surface_page_0010"
    assert tree.find(f".//{RESP_STMT}").get(XML_ID) == "corrector"
    assert [witness.get(XML_ID) for witness in tree.findall(f".//{WITNESS}")] == [
        "abbyy",
        "tesseract",
        "kraken",
        "azure-ai-vision",
    ]


def test_page_document_raises_on_structural_path_mismatch() -> None:
    wct_page = _wct_page()
    edition_page_key = {"section": "body", "anchor": 10, "ordinal": 0}
    events = [
        _event_for(
            wct_page,
            edition_page_key,
            0,
            structural_path="vol_02:page_0010:body:c1:l999:p999",
        )
    ]

    with pytest.raises(ValueError, match="structural_path_at_decision"):
        materialize_page_document(
            wct_page,
            events,
            work_id="jewish-encyclopedia.vol_02",
            volume_id="vol_02",
            edition_page_key=edition_page_key,
        )


def test_page_document_materializes_witnessless_machine_composed_lemma() -> None:
    wct_page = _wct_page()
    edition_page_key = {"section": "body", "anchor": 10, "ordinal": 0}
    events = [_event_for(wct_page, edition_page_key, 1, origin_kind="machine_composed")]

    tree = materialize_page_document(
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    )

    lem = tree.find(f".//{LEM}")
    note = tree.find(f".//{NOTE}[@type='provenance']")
    assert lem.get("wit") is None
    assert lem.get("resp") == "#corrector"
    assert lem.text == "the"
    assert note.text == "decision_event_id: evt-1"


def test_page_document_is_deterministic_for_same_inputs() -> None:
    wct_page = _wct_page()
    edition_page_key = {"section": "body", "anchor": 10, "ordinal": 0}
    events = [
        _event_for(wct_page, edition_page_key, 0),
        _event_for(wct_page, edition_page_key, 1, origin_kind="machine_composed"),
    ]

    first = materialize_page_document(
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    )
    second = materialize_page_document(
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    )

    assert _serialized_bytes(first) == _serialized_bytes(second)
