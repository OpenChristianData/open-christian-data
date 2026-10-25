"""Deterministically reconstruct LIB-027 from its retained CCEL ThML witness."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping
from xml.parsers import expat

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest, reconstruct
from ocd_kernel.tei.writer import XML_ID, XML_LANG, stamp_header, tei_el


CONVERTER_ID = "ocd-boethius-theological-tractates-retained-thml-to-tei"
CONVERTER_VERSION = "1"
SOURCE_PATH = "raw/ccel/boethius/tracts.xml"
SOURCE_SHA256 = "406487abffb39f63934771ce3b4d23b69ce4488d6bc1ccc6a6cad5b4b1e01de8"
SOURCE_BYTES = 162_005
SELECTED_DIV1 = "iv"
TRACTATE_IDS = ("iv.i", "iv.ii", "iv.iii", "iv.iv", "iv.v")
DIV1_IDS = ("i", "ii", "iii", "iv", "v")
EXPECTED_COUNTS = {
    "b": 3,
    "div1": 1,
    "div2": 5,
    "h2": 1,
    "h3": 1,
    "i": 188,
    "note": 59,
    "p": 297,
    "pb": 64,
    "scripRef": 1,
    "span": 60,
    "sup": 1,
    "sync": 88,
    "unclear": 9,
}
TAG_MAP = {
    "b": "hi",
    "div1": "div",
    "div2": "div",
    "h2": "ab",
    "h3": "ab",
    "i": "hi",
    "note": "note",
    "p": "p",
    "pb": "pb",
    "scripRef": "ref",
    "span": "foreign",
    "sup": "hi",
    "sync": "anchor",
    "unclear": "unclear",
}
RIGHTS_STATEMENT = (
    "The local source config labels the underlying text public domain. CCEL "
    "permits parsing its ThML; do not sell CCEL files or derivatives of CCEL "
    "formatting. Attribution is included in README.source.md. Human acceptance "
    "and publication remain absent."
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def _parse_source(content: bytes) -> etree._ElementTree:
    try:
        return etree.ElementTree(
            etree.fromstring(
                content,
                etree.XMLParser(
                    resolve_entities=False,
                    no_network=True,
                    remove_comments=False,
                    remove_pis=False,
                    remove_blank_text=False,
                    huge_tree=True,
                ),
            )
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained Boethius ThML is not well-formed") from exc


def _scope(tree: etree._ElementTree) -> tuple[list[etree._Element], etree._Element]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained Boethius source has no ThML.body")
    divisions = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    if tuple(node.get("id") for node in divisions) != DIV1_IDS:
        raise ValueError("retained Boethius div1 identity or order drifted")
    selected = [node for node in divisions if node.get("id") == SELECTED_DIV1]
    if len(selected) != 1:
        raise ValueError("retained Boethius assigned div1 census drifted")
    tractates = [
        node for node in selected[0] if isinstance(node.tag, str) and node.tag == "div2"
    ]
    if tuple(node.get("id") for node in tractates) != TRACTATE_IDS:
        raise ValueError("retained Boethius five-tract member census drifted")
    return divisions, selected[0]


def _byte_spans(content: bytes) -> list[dict[str, object]]:
    parser = expat.ParserCreate()
    stack: list[dict[str, object]] = []
    selected: list[dict[str, object]] = []

    def start(name: str, attributes: dict[str, str]) -> None:
        parent_selected = bool(stack and stack[-1]["selected"])
        in_scope = parent_selected or (
            name == "div1" and attributes.get("id") == SELECTED_DIV1
        )
        record: dict[str, object] = {
            "tag": name,
            "source_byte_start": parser.CurrentByteIndex,
            "selected": in_scope,
        }
        stack.append(record)
        if in_scope:
            selected.append(record)

    def end(name: str) -> None:
        if not stack:
            raise ValueError("retained Boethius byte parser stack underflow")
        record = stack.pop()
        if record["tag"] != name:
            raise ValueError("retained Boethius byte parser element mismatch")
        if not record["selected"]:
            return
        start_index = int(record["source_byte_start"])
        opening_end = content.find(b">", start_index) + 1
        if opening_end <= 0:
            raise ValueError("retained Boethius source opening tag is incomplete")
        if content[start_index:opening_end].rstrip().endswith(b"/>"):
            end_index = opening_end
        else:
            end_index = content.find(b">", parser.CurrentByteIndex) + 1
        if end_index < opening_end:
            raise ValueError("retained Boethius source closing tag is incomplete")
        source_slice = content[start_index:end_index]
        record.update(
            source_byte_end=end_index,
            source_byte_count=len(source_slice),
            source_bytes_sha256=_sha(source_slice),
        )

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(content, True)
    except expat.ExpatError as exc:
        raise ValueError("retained Boethius byte parser rejected the source") from exc
    if stack or len(selected) != 778 or any("source_byte_end" not in item for item in selected):
        raise ValueError("retained Boethius byte-span census drifted")
    return selected


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        parent = current.getparent()
        if parent is None or not isinstance(current.tag, str):
            break
        peers = [child for child in parent if child.tag == current.tag]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _tei_attributes(source: etree._Element, number: int) -> dict[str, str]:
    source_id = source.get("id")
    attributes = {
        "xml:id": "boethius-" + (
            _safe_id(source_id) if source_id else f"feature-{number:04d}"
        )
    }
    tag = str(source.tag)
    if tag == "b":
        attributes["rend"] = "bold"
    elif tag == "i":
        attributes["rend"] = "italic"
    elif tag == "sup":
        attributes["rend"] = "superscript"
    elif tag in {"div1", "div2", "h2", "h3"}:
        attributes["type"] = f"source-{tag}"
    elif tag == "p":
        if source.get("class"):
            attributes["rend"] = source.get("class", "")
        if source.get("style"):
            attributes["rendition"] = source.get("style", "")
    elif tag == "note" and source.get("n"):
        attributes["n"] = source.get("n", "")
    elif tag == "pb":
        if source.get("n"):
            attributes["n"] = source.get("n", "")
        if source.get("href"):
            attributes["facs"] = source.get("href", "")
    elif tag == "scripRef":
        attributes["type"] = "scripture"
        if source.get("passage"):
            attributes["cRef"] = source.get("passage", "")
        if source.get("osisRef"):
            attributes["target"] = source.get("osisRef", "")
    elif tag == "span":
        if source.get("lang") == "EL":
            attributes["xml:lang"] = "grc"
        if source.get("class"):
            attributes["rend"] = source.get("class", "")
    return attributes


def _normalized_attributes(node: etree._Element) -> dict[str, str]:
    return {
        ("xml:id" if name == XML_ID else "xml:lang" if name == XML_LANG else name): value
        for name, value in node.attrib.items()
    }


def _append(
    source: etree._Element,
    target_parent: etree._Element,
    spans: list[dict[str, object]],
    rows: list[dict[str, object]],
    parent_feature_id: str | None,
    scope_root: etree._Element,
) -> None:
    number = len(rows) + 1
    span = spans[number - 1]
    if span["tag"] != source.tag:
        raise ValueError("retained Boethius byte and element preorder drifted")
    feature_id = f"boethius-feature-{number:04d}"
    target = tei_el(TAG_MAP[str(source.tag)], _tei_attributes(source, number))
    target.text = source.text or ""
    target.tail = "" if source is scope_root else source.tail or ""
    target_parent.append(target)
    row = {
        "feature_id": feature_id,
        "parent_feature_id": parent_feature_id,
        "source_selector": _selector(source),
        "source_tag": source.tag,
        "source_xml_id": source.get("id"),
        "source_attributes": dict(source.attrib),
        "source_direct_text": source.text or "",
        "source_tail_text": "" if source is scope_root else source.tail or "",
        "source_direct_text_sha256": _sha((source.text or "").encode("utf-8")),
        "source_tail_text_sha256": _sha(
            ("" if source is scope_root else source.tail or "").encode("utf-8")
        ),
        "source_byte_start": span["source_byte_start"],
        "source_byte_end": span["source_byte_end"],
        "source_byte_count": span["source_byte_count"],
        "source_bytes_sha256": span["source_bytes_sha256"],
        "tei_tag": TAG_MAP[str(source.tag)],
        "tei_xml_id": target.get(XML_ID),
        "tei_parent_id": target_parent.get(XML_ID),
        "tei_child_ordinal": len(target_parent),
        "tei_attributes": _normalized_attributes(target),
        "disposition": "represented-exactly",
    }
    rows.append(row)
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError("assigned Boethius scope contains a comment or PI")
        if child.tag not in TAG_MAP:
            raise ValueError(f"unsupported retained Boethius element {child.tag!r}")
        _append(child, target, spans, rows, feature_id, scope_root)


def _load_config(source_manifest: SourceManifest) -> dict[str, object]:
    record = json.loads(source_manifest.authority_path("local-source-config").read_bytes())
    expected = {
        "resource_id": "boethius-theological-tractates",
        "title": "The Theological Tractates",
        "author": "Boethius",
        "contributors": [
            "H.F. Stewart (translator, 1918)",
            "E.K. Rand (translator, 1918)",
        ],
        "source_hash": f"sha256:{SOURCE_SHA256}",
        "source_url": "https://www.ccel.org/ccel/boethius/tracts.xml",
        "source_format": "ThML XML",
        "license": "public-domain",
        "output_file": "data/structured-text/boethius-theological-tractates.json",
        "notes": "CCEL confirmed OK to parse. Crawl-delay 10s per robots.txt. Extracted from div1 id='iv' (all five div2 tractates).",
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError("authoritative Boethius source config metadata drifted")
    return record


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    source_bytes = source_manifest.authority_path("retained-thml").read_bytes()
    if len(source_bytes) != SOURCE_BYTES or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained Boethius source identity mismatch")
    config = _load_config(source_manifest)
    tree = _parse_source(source_bytes)
    divisions, selected = _scope(tree)
    features = [node for node in selected.iter() if isinstance(node.tag, str)]
    counts = dict(sorted(Counter(str(node.tag) for node in features).items()))
    attribute_count = sum(len(node.attrib) for node in features)
    if len(features) != 778 or counts != EXPECTED_COUNTS or attribute_count != 1_208:
        raise ValueError("retained Boethius selected-scope census drifted")
    spans = _byte_spans(source_bytes)

    root = tei_el("TEI", {"xml:id": "boethius-theological-tractates-lib027"})
    root.append(
        stamp_header(
            title=str(config["title"]),
            author=str(config["author"]),
            contributors=[
                {"name": "H.F. Stewart", "role": "translator, 1918"},
                {"name": "E.K. Rand", "role": "translator, 1918"},
            ],
            source_url=str(config["source_url"]),
            source_sha256=SOURCE_SHA256,
            print_source=str(config["source_edition"]),
            rights_statement=RIGHTS_STATEMENT,
        )
    )
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "boethius-theological-tractates-body"})
    text.append(body)
    root.append(text)
    rows: list[dict[str, object]] = []
    _append(selected, body, spans, rows, None, selected)
    if len(rows) != 778:
        raise ValueError("Boethius candidate feature accounting drifted")

    division_accounting = [
        {
            "ordinal": ordinal,
            "div1_id": node.get("id"),
            "title": node.get("title", ""),
            "disposition": (
                "selected-work-represented"
                if node.get("id") == SELECTED_DIV1
                else "excluded-sibling-work"
            ),
        }
        for ordinal, node in enumerate(divisions, start=1)
    ]
    tractate_accounting = [
        {
            "ordinal": ordinal,
            "div2_id": node.get("id"),
            "title": node.get("title", ""),
            "disposition": "represented-exactly",
        }
        for ordinal, node in enumerate(
            [child for child in selected if child.tag == "div2"], start=1
        )
    ]
    accountability = {
        "contract": "ocd-boethius-theological-tractates-source-accountability-v1",
        "schema": "boethius-theological-tractates.source-accountability.schema.json",
        "profile_id": "boethius-theological-tractates-div1-iv-v1",
        "source_scope": "ThML.body/div1[@id='iv'] with all five direct div2 tractates",
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": SOURCE_BYTES,
            "sha256": SOURCE_SHA256,
        },
        "selected_byte_range": {
            "start": spans[0]["source_byte_start"],
            "end": spans[0]["source_byte_end"],
            "bytes": spans[0]["source_byte_count"],
            "sha256": spans[0]["source_bytes_sha256"],
        },
        "feature_count": len(rows),
        "attribute_count": attribute_count,
        "feature_counts": counts,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "invented_feature_count": 0,
        "division_accounting": division_accounting,
        "tractate_accounting": tractate_accounting,
        "crosswalk": rows,
    }
    provenance = {
        "contract": "ocd-boethius-theological-tractates-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source": {
            "path": SOURCE_PATH,
            "bytes": SOURCE_BYTES,
            "sha256": SOURCE_SHA256,
            "url": config["source_url"],
            "format": config["source_format"],
            "edition": config["source_edition"],
        },
        "scope": {"div1_id": SELECTED_DIV1, "div2_ids": list(TRACTATE_IDS)},
        "work": {
            "resource_id": config["resource_id"],
            "title": config["title"],
            "author": config["author"],
            "author_id": config["author_id"],
            "contributors": config["contributors"],
            "language": config["language"],
            "original_language": config["original_language"],
            "license_claim": config["license"],
            "schema_type": config["schema_type"],
            "work_kind": config["work_kind"],
        },
        "human_acceptance": "absent",
        "publication": "not_ready",
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    unresolved = [
        {
            "id": "boethius-print-collation-not-performed",
            "status": "unresolved",
            "question": "Does the retained CCEL XML differ from the identified 1918 print edition?",
            "evidence": "This candidate is bound to the retained CCEL XML; no print collation was performed.",
        },
        {
            "id": "boethius-human-acceptance-and-publication",
            "status": "unresolved",
            "question": "Will a maintainer accept this candidate and separately authorize publication?",
            "evidence": "Technical verification is not human textual acceptance, a rights decision, or publication authorization.",
        },
    ]
    readme = source_manifest.authority_path("source-local-attribution-readme").read_bytes()
    return {
        "content.tei.xml": etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    manifest = SourceManifest.load(
        arguments.source_manifest, repository_root=arguments.repository_root
    )
    candidate = reconstruct(manifest, arguments.destination, _convert)
    print(candidate.sha256)


if __name__ == "__main__":
    main()


__all__: tuple[str, ...] = ()
