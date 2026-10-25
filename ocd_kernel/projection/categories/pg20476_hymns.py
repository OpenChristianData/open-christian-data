"""Closed PG20476 hymn projection from the complete HTML-native TEI master.

The row checker derives expectations separately from retained HTML.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from lxml import etree
from ocd_kernel.library._common import PipelineError

WORK_ID = "hymns-for-christian-devotion"
SOURCE_PATH = "raw/gutenberg/20476/html/pg20476-images.html"
SOURCE_SHA256 = "f6dc73e560c71b0b1f30510317938a139f0f3d57fb29248500460eeb4453002e"
SOURCE_BYTES = 1488071
NS = {"t": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

def _class(node: etree._Element) -> str:
    for item in node.get("rend", "").split("; "):
        if item.startswith("class:"):
            return item[6:]
    return ""

def _text(node: etree._Element) -> str:
    return "".join(node.itertext()).strip()

def _rows(tree: etree._Element, identity: Mapping[str, str], revision: str, edition: str) -> list[dict[str, Any]]:
    envelope = tree.find("t:text/t:body/t:p", NS)
    if envelope is None or envelope.get(XML_ID) != "source-html-body-envelope":
        raise PipelineError("PG20476 complete source body envelope missing")
    units = [n for n in envelope if n.get("type") == "hymn"]
    if [n.get(XML_ID) for n in units] != [f"h{i:04d}" for i in range(1, 1009)]:
        raise PipelineError("PG20476 ordered 1008 source hymn identities differ")
    rows = []
    for sequence, unit in enumerate(units, 1):
        if unit.get("n") != str(sequence) or _class(unit) != "hymn":
            raise PipelineError("PG20476 hymn source order/class differs")
        headings = [n for n in unit if n.get("type") == "html-h3"]
        titles = [n for n in unit if n.get("type") == "html-p" and _class(n) == "argument"]
        if len(headings) != 1 or not titles:
            raise PipelineError("PG20476 source heading/title missing or duplicated")
        heading = _text(headings[0])
        notes = [dict(text=heading, place="unspecified", label="printed-heading")]
        stanzas = []
        for child in unit:
            kind = child.get("type")
            if kind == "html-h3":
                continue
            if kind == "html-p" and _class(child) in ("author", "argument"):
                if child is not titles[0]:
                    notes.append(dict(text=_text(child), place="unspecified",
                                      label="printed-attribution" if _class(child) == "author" else "additional-argument"))
                continue
            if kind != "stanza" or _class(child) != "verse":
                raise PipelineError("PG20476 unsupported hymn child")
            lines = []
            number = None
            for line in child:
                if _class(line) not in ("l", "t", "t2", "t3") or line.get("type") not in ("verse-line", "html-div"):
                    raise PipelineError("PG20476 unsupported lyric line")
                parts = [line.text or ""]
                for inline in line:
                    if _class(inline) == "vn":
                        value = _text(inline)
                        if lines or number is not None or not value.isdigit():
                            raise PipelineError("PG20476 misplaced or invalid printed stanza number")
                        number = int(value)
                    else:
                        if etree.QName(inline).localname != "hi":
                            raise PipelineError("PG20476 unsupported lyric inline element")
                        parts.extend(inline.itertext())
                    parts.append(inline.tail or "")
                value = "".join(parts).strip()
                if not value:
                    raise PipelineError("PG20476 empty lyric line")
                lines.append(value)
            if not lines:
                raise PipelineError("PG20476 empty stanza")
            stanzas.append(dict(number=number or len(stanzas)+1, lines=lines))
        if not stanzas:
            raise PipelineError("PG20476 hymn has no stanzas")
        segments = [dict(kind="stanza", **s) for s in stanzas]
        sid = unit.get(XML_ID)
        value = {key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")}
        value.update(record_id=f"{identity['edition_id']}:hymn:{_sha(sid.encode())[:20]}",
                     sequence=sequence, category="hymns", language="eng",
                     text="\n".join(line for s in stanzas for line in s["lines"]),
                     representation_revision=revision,
                     locator=dict(kind="hymn-occurrence", text_part="body", part_titles=[],
                                  divisions=[dict(order=sequence, type="source-hymn-occurrence", titles=[heading])], occurrence=sequence),
                     provenance=dict(edition_title=edition), notes=notes, references=[],
                     occurrence_id=sid, hymn_text_id=f"pg20476-{sid}-{_sha(_canonical(segments))[:16]}",
                     title=_text(titles[0]), first_line=stanzas[0]["lines"][0], stanzas=stanzas, segments=segments)
        rows.append(value)
    if sum(len(r["stanzas"]) for r in rows) != 3771 or sum(len(s["lines"]) for r in rows for s in r["stanzas"]) != 17169:
        raise PipelineError("PG20476 complete stanza/line census differs")
    return rows

def _receipt(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    schema = Path(__file__).resolve().parents[3] / "schemas/v2/categories/hymns.schema.json"
    return dict(mapping_version="ocd-pg20476-native-hymns-v1", assembler_version="ocd-hymns-assembler-provisional-v1",
                master_sha256=_sha(path.read_bytes()), source_sha256=SOURCE_SHA256,
                policy_sha256=_sha(schema.read_bytes()), common_schema_sha256=_sha((schema.parents[1]/"public-row.schema.json").read_bytes()),
                output_sha256=_sha(_canonical(rows)), row_count=1008,
                anchors=[dict(record_id=r["record_id"], source_id=r["occurrence_id"], source_order=r["sequence"], text_sha256=_sha(r["text"].encode())) for r in rows],
                inventory=dict(hymn_occurrences=1008, verse_divisions=3771, lines=17169, deeply_indented_lines=313),
                references=[], unsupported=[], independent_check=dict(status="pending", errors=[]),
                warnings=["Printed stanza numbers are structured separately; unlabeled stanzas use source order. Line indentation and inline typography remain in the master. Printed attribution is not an inferred author identity."],
                exclusions=[dict(scope="non-hymn body matter", reason="Provider terms, title matter, section headings, indexes and complete license remain in the master; rows select the 1008 source hymn occurrences.")],
                source_disposition=dict(textual_member=SOURCE_PATH, accepted_member_count=1, support_member_count=1,
                                        source_order="h0001 through h1008", master_scope="complete retained digital witness"))

def project_pg20476_document(tei_path: Path, *, retained_path: Path, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str) -> dict[str, Any]:
    raw = retained_path.read_bytes()
    if identity.get("work_id") != WORK_ID or language not in ("en", "eng") or len(raw) != SOURCE_BYTES or _sha(raw) != SOURCE_SHA256:
        raise PipelineError("PG20476 exact work, language or retained source identity differs")
    tree = etree.fromstring(tei_path.read_bytes(), etree.XMLParser(resolve_entities=False, no_network=True, recover=False))
    rows = _rows(tree, identity, representation_revision, edition_title)
    from .hymns import _validator
    validator = _validator()
    for row in rows:
        if errors := list(validator.iter_errors(row)):
            raise PipelineError(f"PG20476 row schema: {errors[0].message}")
    return dict(rows=rows, receipt=_receipt(tei_path, rows))

def verify_pg20476_document(tei_path: Path, rows: list[dict[str, Any]], receipt: Mapping[str, Any], **kwargs: Any) -> list[str]:
    from .pg20476_hymns_check import check_pg20476_document
    return check_pg20476_document(tei_path, rows, receipt, **kwargs)

