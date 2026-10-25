"""Closed PG33128 hymn selection from the unchanged HTML-native TEI master.

The producer traverses TEI. The checker derives its expectations separately
from the retained HTML using html5lib and never invokes the producer.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.library._common import PipelineError

WORK_ID = "l744-pg33128-gospel-hymns"
SOURCE_MEMBER_PATH = "raw/gutenberg/33128/html/pg33128-images.html"
SOURCE_PATH = SOURCE_MEMBER_PATH
SOURCE_SHA256 = "da72fc391ad5d0f599293ba91194a247e7303a1f77d0eb09bba9bed71228b135"
SOURCE_BYTES = 185532
MAPPING_VERSION = "ocd-pg33128-native-hymns-v1"
ASSEMBLER_VERSION = "ocd-hymns-assembler-provisional-v1"
NS = {"t": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
ENVELOPE = (
    ("raw/gutenberg/33128/pg33128-h.zip", 124710, "1055e9e51d73c72c85c1db2ad32cb9708b49628ace0962694193fb38326ac2a6"),
    (SOURCE_PATH, SOURCE_BYTES, SOURCE_SHA256),
    ("raw/gutenberg/33128/html/33128-cover.png", 85060, "750cd890972a06e4ebebb48e204e7db366b0c33a654f7e6f0fe659b63f87a056"),
    ("raw/gutenberg/33128/acquisition-receipt.json", 1347, "74eecfeaa7f8547416df0b6113f485bbfd70114b267b556ad0ccebe0fa1a964b"),
    ("raw/gutenberg/33128/member-inventory.tsv", 199, "fed6bbe47f49fb636b74cb7bacb476e91048e8e0c56d555db5b07c38b879656a"),
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def select_pg33128_member(included: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Select text only after validating the complete accepted source envelope."""
    if len(included) != 5:
        raise PipelineError("PG33128 requires its complete five-member accepted envelope")
    observed = [(item.get("path"), item.get("bytes"), item.get("sha256")) for item in included]
    if observed != list(ENVELOPE) or [item.get("position") for item in included] != list(range(1, 6)):
        raise PipelineError("PG33128 accepted source-member identities or order differ")
    return dict(included[1])


def _context(retained_path: Path, identity: Mapping[str, str], language: str) -> None:
    if identity.get("work_id") != WORK_ID or language != "mul":
        raise PipelineError("PG33128 requires its exact work identity and mul edition language")
    raw = retained_path.read_bytes()
    if len(raw) != SOURCE_BYTES or _sha(raw) != SOURCE_SHA256:
        raise PipelineError("PG33128 exact retained HTML source changed")


def _parse(path: Path) -> etree._Element:
    return etree.fromstring(path.read_bytes(), etree.XMLParser(resolve_entities=False, no_network=True, recover=False))


def _tei_children(node: etree._Element) -> list[etree._Element]:
    """Expose source children through only converter-declared transparent wrappers."""
    children: list[etree._Element] = []
    for child in node:
        if child.tag == "{" + NS["t"] + "}div" and child.get("type") == "source-block-segment":
            if (child.text or "").strip() or (child.tail or "").strip():
                raise PipelineError("PG33128 transparent wrapper contains invented text")
            children.extend(_tei_children(child))
        else:
            children.append(child)
    return children


def _tei_class(node: etree._Element) -> str:
    value = node.get("rend", "")
    return value.removeprefix("source-class:") if value.startswith("source-class:") else ""


def _line(node: etree._Element) -> tuple[str, int | None]:
    number = None
    parts = [node.text or ""]
    for child in node:
        if child.tag != "{" + NS["t"] + "}seg" or _tei_class(child) not in {"vn", "w", "sc"}:
            raise PipelineError("PG33128 unexpected lyric inline carrier")
        if _tei_class(child) == "vn":
            value = "".join(child.itertext()).strip()
            if number is not None or not value.isdigit():
                raise PipelineError("PG33128 invalid stanza number carrier")
            number = int(value)
        else:
            parts.extend(child.itertext())
        parts.append(child.tail or "")
    text = "".join(parts).strip()
    if not text:
        raise PipelineError("PG33128 empty lyric line")
    return text, number


def _tei_rows(tree: etree._Element, identity: Mapping[str, str], revision: str, edition: str) -> list[dict[str, Any]]:
    units = tree.xpath(".//t:div[@xml:id='h']/t:div[starts-with(@xml:id,'h')]", namespaces=NS)
    expected_ids = [f"h{number}{suffix}" for number in range(1, 39) for suffix in ("", "a")]
    if [unit.get(XML_ID) for unit in units] != expected_ids:
        raise PipelineError("PG33128 38 ordered English/Ojibway occurrence pairs differ")
    rows: list[dict[str, Any]] = []
    for sequence, unit in enumerate(units, 1):
        source_id = unit.get(XML_ID)
        title = unit.get("rend", "").removeprefix("source-title:")
        if not title or not unit.get("rend", "").startswith("source-title:"):
            raise PipelineError("PG33128 source occurrence title missing")
        stanzas: list[dict[str, Any]] = []
        segments: list[dict[str, Any]] = []
        notes: list[dict[str, str]] = []
        tune = None
        heading = None
        for child in _tei_children(unit):
            name = etree.QName(child).localname
            kind = _tei_class(child)
            if name == "head":
                if heading is not None:
                    raise PipelineError("PG33128 duplicate hymn heading")
                heading = "".join(child.itertext()).strip()
            elif name == "p" and kind in {"meter", "srcttl", "tune"}:
                value = "".join(child.itertext()).strip()
                if kind == "tune":
                    if tune is not None: raise PipelineError("PG33128 duplicate tune carrier")
                    tune = value
                else:
                    notes.append(dict(text=value, place="unspecified", label="meter" if kind == "meter" else "source-title"))
            elif name == "div" and kind == "page_break":
                continue
            elif name == "div" and kind == "verse":
                lines: list[str] = []
                stanza_number = None
                label = None
                for line in _tei_children(child):
                    if etree.QName(line).localname != "p" or _tei_class(line) not in {"t0", "t", "t2", "t3", "t4", "vno"}:
                        raise PipelineError("PG33128 unexpected stanza line carrier")
                    text, number = _line(line)
                    if number is not None:
                        if stanza_number is not None or lines: raise PipelineError("PG33128 misplaced stanza number")
                        stanza_number = number
                    if _tei_class(line) == "vno":
                        match = re.fullmatch(r"((?:Chorus[.:]|Cho\.)(?:\s*—)?)(.*)", text)
                        if not match or label is not None or lines: raise PipelineError("PG33128 unexpected chorus label")
                        label = match[1]
                        if match[2].strip(): lines.append(match[2].strip())
                    else:
                        lines.append(text)
                if not lines: raise PipelineError("PG33128 empty stanza or chorus")
                if label is not None:
                    segments.append(dict(kind="refrain", label=label, lines=lines))
                else:
                    stanza = dict(number=stanza_number or len(stanzas) + 1, lines=lines)
                    stanzas.append(stanza)
                    segments.append(dict(kind="stanza", **stanza))
            else:
                raise PipelineError(f"PG33128 unsupported occurrence child {name}/{kind}")
        if not heading or not stanzas:
            raise PipelineError("PG33128 missing source heading or hymn stanzas")
        text = "\n".join(line for segment in segments for line in segment["lines"])
        record_id = f"{identity['edition_id']}:hymn:{_sha(source_id.encode())[:20]}"
        row = {key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")}
        row.update(record_id=record_id, sequence=sequence, category="hymns", language="mul", text=text,
                   representation_revision=revision, locator=dict(kind="hymn-occurrence", text_part="body", part_titles=[], divisions=[dict(order=sequence, type="source-hymn-occurrence", titles=[heading])], occurrence=sequence),
                   provenance=dict(edition_title=edition), notes=notes, references=[], occurrence_id=source_id,
                   hymn_text_id=f"pg33128-{source_id}-{_sha(_canonical(segments))[:16]}", title=title,
                   first_line=stanzas[0]["lines"][0], stanzas=stanzas, segments=segments)
        if tune is not None: row["tune"] = tune
        refrains = [segment for segment in segments if segment["kind"] == "refrain"]
        if len(refrains) > 1: raise PipelineError("PG33128 multiple chorus bodies require a reviewed successor")
        if refrains: row["refrain"] = {key: refrains[0][key] for key in ("label", "lines")}
        rows.append(row)
    if sum(len(row["segments"]) for row in rows) != 390:
        raise PipelineError("PG33128 source verse division census differs")
    return rows


def _receipt(tei_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    schema = Path(__file__).resolve().parents[3] / "schemas/v2/categories/hymns.schema.json"
    common = schema.parents[1] / "public-row.schema.json"
    return dict(mapping_version=MAPPING_VERSION, assembler_version=ASSEMBLER_VERSION,
                master_sha256=_sha(tei_path.read_bytes()), source_sha256=SOURCE_SHA256,
                policy_sha256=_sha(schema.read_bytes()), common_schema_sha256=_sha(common.read_bytes()),
                output_sha256=_sha(_canonical(rows)), row_count=len(rows),
                anchors=[dict(record_id=row["record_id"], source_id=row["occurrence_id"], source_order=row["sequence"], text_sha256=_sha(row["text"].encode())) for row in rows],
                inventory=dict(hymn_pairs=38, hymn_occurrences=76, verse_divisions=390, refrain_bodies=6,
                               lines=sum(len(segment["lines"]) for row in rows for segment in row["segments"])),
                references=[], warnings=["Edition language mul records the source-labeled bilingual collection; no individual Ojibway language code or print collation is asserted."],
                exclusions=[dict(scope=scope, reason=reason) for scope,reason in (
                    ("pg-header", "provider title, credit and terms remain in master and visible source notices"),
                    ("titlepg", "printed title matter remains in complete master"),
                    ("index_e,index_o", "indexes remain in complete master; hymn rows follow collection order"),
                    ("phonics", "pronunciation key remains in complete master"),
                    ("pg-footer", "complete retained license remains in master and data-path license notice"),
                    ("page_break and display typography", "display markers remain in master; stanza numbers and chorus labels are explicitly structured"),
                    ("archive, cover, receipt, inventory", "hash-bound retained support members are not hymn text"))],
                source_disposition=dict(textual_member=SOURCE_PATH, support_member_count=4, accepted_member_count=5, source_order="h1,h1a through h38,h38a", master_scope="complete retained digital witness"),
                unsupported=[], independent_check=dict(status="pending",errors=[]))


def project_pg33128_document(tei_path: Path, *, retained_path: Path, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str) -> dict[str, Any]:
    _context(retained_path, identity, language)
    rows = _tei_rows(_parse(tei_path), identity, representation_revision, edition_title)
    from .hymns import _validator
    validator = _validator()
    for row in rows:
        if errors := list(validator.iter_errors(row)):
            raise PipelineError(f"PG33128 row schema: {errors[0].message}")
    return dict(rows=rows, receipt=_receipt(tei_path,rows))


def verify_pg33128_document(tei_path: Path, rows: list[dict[str, Any]], receipt: Mapping[str, Any], *, retained_path: Path, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str) -> list[str]:
    """Independent HTML-derived checker; neither TEI row producer is invoked."""
    from .pg33128_hymns_check import check_pg33128_document
    return check_pg33128_document(tei_path, rows, receipt, retained_path=retained_path, identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title)
