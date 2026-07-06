"""Materialize JE apparatus TEI from the decision-event ledger folded with the WCT.

Authority order (ADR-0019): ledger -> TEI -> HF. The committed TEI is a deterministic
projection of the append-only decision-event ledger folded with the word-confusion-table
(WCT) attestations. Nothing edits TEI in place; a new reading is a new event and the TEI is
re-materialized from scratch. This module is the ledger+WCT -> TEI half; the drift checker
(drift_check.py) proves the committed TEI is rebuildable from the same inputs.

Per architecture plan section 7:
  - Attested chosen reading (origin_kind=observed): <w facs xml:id><app>
        <lem wit="#abbyy #azure" cert="high">chosen</lem><rdg wit="#tesseract">losing</rdg>
    </app></w>
  - Witnessless reading (origin_kind in {machine_composed, human_amended}; ADR-0018/0014):
    a <lem> with NO @wit, carrying @resp + @cert and a <note type="provenance"> pointing to
    the originating decision_event_id.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from lxml import etree

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.canonical_token import canonical_token_id
from build.tools.import_corrected_page_to_ledger import _edition_key_for_wct_page
from build.tei.writer import TEI_NS, serialize, stamp_header, tei_el

# Certainty is a faithful projection of the ledger authority status, not a free assertion.
_STATUS_CERT = {
    "consensus": "high",
    "reviewed": "high",
    "llm_resolved": "medium",
    "unresolved": "low",
}

# ADR-0018/0014: readings the machine composed or a human amended are witnessless -- they
# were not observed in any OCR witness, so they carry @resp (who is responsible) not @wit.
_WITNESSLESS_ORIGINS = frozenset({"machine_composed", "human_amended"})

# The @resp target for each ledger actor. ADR-0021: the JE corrector releases as
# system:corrector; its composed readings are attributed to the corrector, registered as a
# <respStmt xml:id="corrector"> in the header (see document_header).
_RESP_FOR_ACTOR = {
    "system:corrector": "#corrector",
    "system:llm-review": "#llm-review",
    "maintainer": "#reviewer",
}
_DEFAULT_RESP = "#corrector"


def token_xml_id(page_id: str, ordinal: int) -> str:
    """xml:id for a token's <w>. NCName-safe (page_id + zero-padded ordinal, no colons)."""
    return f"w_{page_id}_{ordinal:04d}"


def zone_xml_id(page_id: str, ordinal: int) -> str:
    """xml:id for a token's facsimile <zone>."""
    return f"z_{page_id}_{ordinal:04d}"


def _wit_string(families: list[str]) -> str:
    return " ".join(f"#{family}" for family in families)


def apparatus_token(
    position: dict,
    event: dict,
    *,
    page_id: str,
    ordinal: int,
) -> etree._Element:
    """Build the <w> apparatus element for one WCT position folded with its ledger event."""
    extras = event.get("decision_extras_carried", {})
    chosen_index = extras.get("chosen_reading_index", 0)
    origin_kind = extras.get("origin_kind")
    candidates = position["candidate_set"]
    cert = _STATUS_CERT.get(event.get("status_authority"), "low")
    witnessless = origin_kind in _WITNESSLESS_ORIGINS

    word = tei_el(
        "w",
        {"xml:id": token_xml_id(page_id, ordinal), "facs": "#" + zone_xml_id(page_id, ordinal)},
    )
    app = tei_el("app")
    word.append(app)

    chosen = candidates[chosen_index]
    if witnessless:
        resp = _RESP_FOR_ACTOR.get(event.get("actor_id"), _DEFAULT_RESP)
        lem = tei_el("lem", {"resp": resp, "cert": cert}, text=chosen["raw_reading"])
    else:
        lem = tei_el("lem", {"wit": _wit_string(chosen["attesting_families"]), "cert": cert}, text=chosen["raw_reading"])
    app.append(lem)

    for index, candidate in enumerate(candidates):
        if index == chosen_index:
            continue
        app.append(tei_el("rdg", {"wit": _wit_string(candidate["attesting_families"])}, text=candidate["raw_reading"]))

    if witnessless:
        app.append(tei_el("note", {"type": "provenance"}, text=f"decision_event_id: {event['event_id']}"))

    return word


def resolve_edition_page_key(wct_page: dict, ia_manifest: dict) -> dict:
    """Resolve a WCT page to the edition page key used when ledger events were minted."""
    return dict(_edition_key_for_wct_page(wct_page, ia_manifest))


def materialize_page_document(
    wct_page: dict,
    events: list[dict],
    *,
    work_id: str,
    volume_id: str,
    edition_page_key: dict,
    header_meta: dict | None = None,
) -> etree._ElementTree:
    """Fold one WCT page and its ledger events into a deterministic TEI document."""
    page_id = str(wct_page["page_id"])
    positions_by_id = _positions_by_id(wct_page)
    events_by_ct = {event["canonical_token_id"]: event for event in events}

    emitted: list[tuple[int, dict, dict]] = []
    for ordinal, position_id in enumerate(wct_page["reading_order"]):
        ct = canonical_token_id(work_id, volume_id, edition_page_key, ordinal)
        event = events_by_ct.get(ct)
        if event is None:
            continue
        if event.get("structural_path_at_decision") != position_id:
            raise ValueError(
                f"{page_id} ordinal {ordinal}: structural_path_at_decision "
                f"{event.get('structural_path_at_decision')!r} does not match WCT position_id {position_id!r}"
            )
        emitted.append((ordinal, positions_by_id[position_id], event))

    root = tei_el("TEI")
    root.append(_document_header(wct_page, header_meta))
    root.append(_facsimile(wct_page, emitted))
    root.append(_text_body(wct_page, edition_page_key, emitted))
    return etree.ElementTree(root)


def _positions_by_id(wct_page: Mapping[str, Any]) -> dict[str, dict]:
    positions: dict[str, dict] = {}
    for position in wct_page["positions"]:
        position_id = position.get("position_id")
        if not isinstance(position_id, str):
            raise ValueError(f"{wct_page.get('page_id')}: WCT position missing position_id")
        positions[position_id] = position
    return positions


def _document_header(wct_page: Mapping[str, Any], header_meta: Mapping[str, Any] | None) -> etree._Element:
    meta = dict(header_meta or {})
    source_image = wct_page.get("source_image", {})
    header = stamp_header(
        title=str(meta.get("title", f"Jewish Encyclopedia {wct_page['volume_id']} {wct_page['page_id']}")),
        author=str(meta.get("author", "Jewish Encyclopedia contributors")),
        contributors=list(meta.get("contributors", [])),
        source_url=str(meta.get("source_url", source_image.get("path", ""))),
        source_sha256=str(meta.get("source_sha256", source_image.get("sha256", ""))),
        print_source=str(meta.get("print_source", "Jewish Encyclopedia, 1901-1906")),
    )

    title_stmt = header.find(f".//{{{TEI_NS}}}titleStmt")
    corrector = tei_el("respStmt", {"xml:id": "corrector"})
    corrector.append(tei_el("resp", text="Machine corrector"))
    corrector.append(tei_el("name", text="Open Christian Data corrector"))
    title_stmt.append(corrector)

    source_desc = header.find(f".//{{{TEI_NS}}}sourceDesc")
    list_wit = tei_el("listWit")
    for family in _engine_families(wct_page):
        list_wit.append(tei_el("witness", {"xml:id": family}, text=family))
    source_desc.append(list_wit)
    return header


def _engine_families(wct_page: Mapping[str, Any]) -> list[str]:
    families: list[str] = []
    for engine in wct_page.get("available_engines", []):
        family = engine.get("family") if isinstance(engine, Mapping) else engine
        if not isinstance(family, str) or family in families:
            continue
        families.append(family)
    return families


def _facsimile(wct_page: Mapping[str, Any], emitted: Sequence[tuple[int, dict, dict]]) -> etree._Element:
    page_id = str(wct_page["page_id"])
    facsimile = tei_el("facsimile")
    surface = tei_el("surface", {"xml:id": f"surface_{page_id}"})
    source_image = wct_page.get("source_image", {})
    surface.append(tei_el("graphic", {"url": str(source_image.get("path", ""))}))
    for ordinal, position, _event in emitted:
        bbox = position["reference_bbox"]
        x = bbox["x"]
        y = bbox["y"]
        w = bbox["w"]
        h = bbox["h"]
        surface.append(
            tei_el(
                "zone",
                {
                    "xml:id": zone_xml_id(page_id, ordinal),
                    "ulx": _coord(x),
                    "uly": _coord(y),
                    "lrx": _coord(x + w),
                    "lry": _coord(y + h),
                },
            )
        )
    facsimile.append(surface)
    return facsimile


def _text_body(
    wct_page: Mapping[str, Any],
    edition_page_key: Mapping[str, Any],
    emitted: Sequence[tuple[int, dict, dict]],
) -> etree._Element:
    page_id = str(wct_page["page_id"])
    text = tei_el("text")
    body = tei_el("body")
    body.append(
        tei_el(
            "pb",
            {
                "xml:id": f"pb_{page_id}",
                "n": str(edition_page_key["anchor"]),
                "facs": f"#surface_{page_id}",
            },
        )
    )
    ab = tei_el("ab", {"xml:id": f"ab_{page_id}"})
    for ordinal, position, event in emitted:
        ab.append(apparatus_token(position, event, page_id=page_id, ordinal=ordinal))
    body.append(ab)
    text.append(body)
    return text


def _coord(value: Any) -> str:
    return str(value)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _page_id_from_structural_path(structural_path: str) -> str:
    for component in structural_path.split(":"):
        if component.startswith("page_"):
            return component
    raise ValueError(f"Could not derive page_id from structural_path_at_decision {structural_path!r}")


def _events_by_page(events: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    by_page: dict[str, list[dict]] = {}
    for event in events:
        structural_path = event.get("structural_path_at_decision")
        if not isinstance(structural_path, str):
            raise ValueError(f"Ledger event missing structural_path_at_decision: {event.get('event_id')!r}")
        page_id = _page_id_from_structural_path(structural_path)
        by_page.setdefault(page_id, []).append(dict(event))
    return by_page


def _count_words(tree: etree._ElementTree) -> int:
    return len(tree.findall(f".//{{{TEI_NS}}}w"))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--wct-dir", type=Path, required=True)
    parser.add_argument("--ia-manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--work-id", default="jewish-encyclopedia.vol_02")
    parser.add_argument("--volume-id", default="vol_02")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    ledger_events = _read_jsonl(args.ledger)
    events_by_page = _events_by_page(ledger_events)
    ia_manifest = _read_json(args.ia_manifest)

    pages_written = 0
    tokens_emitted = 0
    tokens_skipped = 0
    for page_id in sorted(events_by_page):
        wct_path = args.wct_dir / f"{page_id}.json"
        wct_page = _read_json(wct_path)
        edition_page_key = resolve_edition_page_key(wct_page, ia_manifest)
        tree = materialize_page_document(
            wct_page,
            events_by_page[page_id],
            work_id=args.work_id,
            volume_id=args.volume_id,
            edition_page_key=edition_page_key,
        )
        emitted_count = _count_words(tree)
        serialize(tree, args.out_dir / f"{page_id}.tei.xml")
        pages_written += 1
        tokens_emitted += emitted_count
        tokens_skipped += len(wct_page["reading_order"]) - emitted_count
        print(f"wrote {page_id}: emitted={emitted_count} skipped={len(wct_page['reading_order']) - emitted_count}")

    print(f"summary: pages_written={pages_written} tokens_emitted={tokens_emitted} tokens_skipped={tokens_skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
