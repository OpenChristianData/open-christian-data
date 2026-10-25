"""Source-bound PG33105 hymn/translation rows; complete master remains authoritative."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET

import html5lib
from lxml import etree

from ocd_kernel.library._common import PipelineError

WORK_ID = "l744-pg33105-chinook-hymns"
SOURCE_MEMBER_PATH = "raw/gutenberg/33105/html/pg33105-images.html"
SOURCE_SHA = "a56254c11f6ed220052501248fcca2fb84b37239cadb6168ccd37e6f3526d60f"
BODY_SHA = "fe0631519d7fda021d0b2112ffd4f517787eaaa7c7e166ed888bba4232c3d67e"
MAPPING_VERSION = "ocd-pg33105-paired-hymn-sections-v1"
T = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

def _space(text: str) -> str:
    return " ".join(text.split())

def _master(path: Path) -> ET.Element:
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw or raw.count(b"</teiHeader>") != 1:
        raise PipelineError("PG33105 master envelope differs")
    if _sha(raw.split(b"</teiHeader>", 1)[1]) != BODY_SHA:
        raise PipelineError("PG33105 whole reconstructed body differs from reviewed source")
    return ET.fromstring(raw)

def _source(path: Path):
    raw = path.read_bytes()
    if _sha(raw) != SOURCE_SHA:
        raise PipelineError("PG33105 retained HTML bytes differ")
    return html5lib.parse(raw, treebuilder="etree", namespaceHTMLElements=False)

def _master_section(unit: ET.Element) -> list[dict[str, Any]]:
    verses = [el for el in unit.iter(T + "div") if "source-class:verse" in el.get("rend", "").split()]
    stanzas = []
    for ordinal, verse in enumerate(verses, 1):
        paragraphs = [el for el in verse.iter(T + "p") if el.get("n")]
        lines = []
        number = ordinal
        for paragraph in paragraphs:
            text = _space("".join(paragraph.itertext()))
            labels = [el for el in paragraph.iter(T + "seg") if "source-class:vn" in el.get("rend", "").split()]
            if labels:
                if len(labels) != 1 or lines:
                    raise PipelineError("PG33105 stanza label attachment differs")
                label = _space("".join(labels[0].itertext()))
                match = re.fullmatch(r"(\d+)\.?", label)
                if not match or not text.startswith(label):
                    raise PipelineError("PG33105 stanza number differs")
                number = int(match.group(1))
                text = text[len(label):].lstrip()
            if not text:
                raise PipelineError("PG33105 empty verse paragraph")
            lines.append(text)
        if not lines:
            raise PipelineError("PG33105 verse lacks source paragraph lines")
        stanzas.append(dict(number=number, lines=lines))
    if not stanzas:
        raise PipelineError("PG33105 hymn section has no source verses")
    return stanzas

def _assemble(sequence: int, headings: list[str], tune: str, labels: list[str | None], groups: list[list[dict]],
              *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str) -> dict:
    title = " ".join(headings)
    stanzas = [stanza for group in groups for stanza in group]
    text = "\n\n".join("\n".join(stanza["lines"]) for stanza in stanzas)
    return dict(**{key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")},
        record_id=f"{identity['edition_id']}:hymn:{sequence:03d}", sequence=sequence, category="hymns", language=language,
        text=text, representation_revision=representation_revision,
        locator=dict(kind="hymn-occurrence", text_part="body", part_titles=[],
            divisions=[dict(order=sequence, type="hymn", titles=headings)], occurrence=sequence),
        provenance=dict(edition_title=edition_title), notes=[], references=[], occurrence_id=f"pg33105-{sequence:03d}",
        hymn_text_id="text-" + _sha((title + "\n" + text).encode())[:20], title=title, tune=tune,
        first_line=groups[0][0]["lines"][0], stanzas=stanzas, segments=[dict(kind="stanza", **stanza) for stanza in stanzas],
        sections=[dict(label=label, stanzas=group) for label, group in zip(labels, groups, strict=True)])

def _rows_master(tree: ET.Element, **metadata) -> list[dict]:
    nodes = {node.get(XML_ID): node for node in tree.iter() if node.get(XML_ID)}
    result = []
    for number in range(1, 21):
        original = nodes.get(f"h{number}")
        translated = nodes.get(f"h{number}a")
        if original is None or translated is None:
            raise PipelineError("PG33105 paired hymn boundary is missing")
        headings = [_space("".join(head.itertext())) for head in original.iter(T + "head")]
        if not headings or headings[-1] != f"No. {number}.":
            raise PipelineError("PG33105 numbered heading order differs")
        translations = [_space("".join(head.itertext())) for head in translated.iter(T + "head")]
        if translations != ["TRANSLATION."]:
            raise PipelineError("PG33105 translation heading differs")
        tunes = [_space("".join(p.itertext())) for p in original.iter(T + "p") if "source-class:tune" in p.get("rend", "").split()]
        if len(tunes) != 1:
            raise PipelineError("PG33105 tune source carrier differs")
        result.append(_assemble(number, headings, tunes[0], [None, translations[0]],
            [_master_section(original), _master_section(translated)], **metadata))
    return result

def _source_expectations(root) -> list[dict]:
    """Independent direct HTML-child traversal; no master selector or stanza mapper."""
    container = next(node for node in root.iter("div") if node.get("id") == "hymns")
    divisions = [node for node in container if node.tag == "div" and re.fullmatch(r"h\d+a?", node.get("id", ""))]
    if [node.get("id") for node in divisions] != [key for n in range(1, 21) for key in (f"h{n}", f"h{n}a")]:
        raise PipelineError("PG33105 source pair sequence differs")
    expectations = []
    for index in range(0, 40, 2):
        pair = divisions[index:index + 2]
        groups = []
        for unit in pair:
            stanzas = []
            for child in unit:
                if child.tag != "div" or child.get("class") != "verse":
                    continue
                number = len(stanzas) + 1
                lines = []
                for paragraph in child:
                    if paragraph.tag != "p":
                        raise PipelineError("PG33105 source verse contains nonparagraph")
                    pieces = [paragraph.text or ""]
                    for span in paragraph:
                        if span.tag == "span" and span.get("class") == "vn":
                            if lines:
                                raise PipelineError("PG33105 source stanza label is late")
                            numeric = "".join(span.itertext()).strip()
                            if not re.fullmatch(r"[0-9]+\.?", numeric):
                                raise PipelineError("PG33105 source stanza label is nonnumeric")
                            number = int(numeric.rstrip("."))
                        else:
                            pieces.extend(span.itertext())
                        pieces.append(span.tail or "")
                    line = re.sub(r"\s+", " ", "".join(pieces)).strip()
                    if not line:
                        raise PipelineError("PG33105 source line is empty")
                    lines.append(line)
                stanzas.append(dict(number=number, lines=lines))
            groups.append(stanzas)
        original, translation = pair
        headings = [re.sub(r"\s+", " ", "".join(node.itertext())).strip() for node in original if node.tag == "h3"]
        translated_headings = ["".join(node.itertext()).strip() for node in translation if node.tag == "h4"]
        tunes = [re.sub(r"\s+", " ", "".join(node.itertext())).strip() for node in original if node.tag == "p" and node.get("class") == "tune"]
        if len(tunes) != 1 or translated_headings != ["TRANSLATION."]:
            raise PipelineError("PG33105 source tune/translation heading differs")
        expectations.append(dict(headings=headings, tune=tunes[0], labels=[None,"TRANSLATION."], groups=groups))
    return expectations

def _receipt(path: Path, rows: list[dict]) -> dict:
    schema = Path(__file__).resolve().parents[3] / "schemas/v2/categories/hymns.schema.json"
    common = schema.parents[1] / "public-row.schema.json"
    return dict(mapping_version=MAPPING_VERSION, assembler_version="ocd-hymns-assembler-provisional-v1",
        master_sha256=_sha(path.read_bytes()), source_sha256=SOURCE_SHA, policy_sha256=_sha(schema.read_bytes()),
        common_schema_sha256=_sha(common.read_bytes()), output_sha256=_sha(_canonical(rows)), row_count=20,
        anchors=[dict(record_id=row["record_id"], source_order=row["sequence"], text_sha256=_sha(row["text"].encode()),
            section_count=2, source_ids=[f"h{row['sequence']}",f"h{row['sequence']}a"]) for row in rows],
        inventory=[dict(hymn=row["sequence"], section_count=2, stanza_count=len(row["stanzas"])) for row in rows], references=[],
        warnings=["PG33105 rows contain 20 numbered hymn/English-translation pairs. Closing prayers, 142 interlinear tables and surrounding matter remain in the full master outside this hymn selection.",
            "Edition language code mul records source-attested multiple languages, including paired Chinook Jargon/English and the source's four-language hymn 20 medley. Repetition and chorus cues remain literal verse lines, not inferred musical structure.",
            "Source tune labels retain their full wording. Paragraphs supply line boundaries; whitespace is collapsed and source stanza-number labels become numeric stanza fields.",
            "Source hymn-information paragraphs outside verses are excluded from text rows; the complete master retains their medley-language and permission statements."],
        exclusions=[dict(scope="source:#home,#note,#pg-header,#pg-footer", count=4, reason="Title/preface/provider/license matter remains in the complete master outside hymn rows."),
            dict(scope="source:#hymns closing prayer/blessing", count=2, reason="Non-hymn prayers and all 142 interlinear tables remain in the complete master."),
            dict(scope="source hymninfo/page/typography", count=None, reason="Hymn-information paragraphs, page markers and visual formatting remain in the master; numbered hymns and translations are projected.")],
        unsupported=[], independent_check=dict(status="pending", errors=[]))

def project_chinook_document(tei_path: Path, *, retained_path: Path, identity: Mapping[str,str],
        language: str, representation_revision: str, edition_title: str) -> dict:
    if identity.get("work_id") != WORK_ID or language != "mul":
        raise PipelineError("PG33105 mapping requires exact work and source-attested multiple languages code mul")
    _source(retained_path)
    metadata = dict(identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title)
    rows = _rows_master(_master(tei_path), **metadata)
    from .hymns import _validator
    for row in rows:
        if errors := list(_validator().iter_errors(row)):
            raise PipelineError(f"PG33105 hymn schema: {errors[0].message}")
    return dict(rows=rows, receipt=_receipt(tei_path, rows))

def verify_chinook_document(tei_path: Path, rows: list[dict], receipt: Mapping[str,Any], *, retained_path: Path,
        identity: Mapping[str,str], language: str, representation_revision: str, edition_title: str) -> list[str]:
    """Observe retained HTML directly; never call the producer or its stanza traversal."""
    try:
        if identity.get("work_id") != WORK_ID or language != "mul":
            raise PipelineError("PG33105 checker identity/language differs")
        expected = _source_expectations(_source(retained_path))
        metadata = dict(identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title)
        expected_rows = [_assemble(i, **value, **metadata) for i,value in enumerate(expected,1)]
        # Complete actual master body is separately pinned to the source-checked reconstruction.
        # No producer traversal is reused by this independent HTML observer.
        _master(tei_path)
        errors = []
        if rows != expected_rows:
            errors.append("PG33105 rows differ from independently observed HTML hymn/translation pairs")
        if dict(receipt) != _receipt(tei_path, expected_rows):
            errors.append("PG33105 receipt/output/selection binding differs")
        from .hymns import _validator
        for index,row in enumerate(rows,1):
            errors.extend(f"PG33105 row {index}: {error.message}" for error in _validator().iter_errors(row))
        return errors
    except (PipelineError,OSError,ValueError,KeyError,TypeError,ET.ParseError,etree.XMLSyntaxError,StopIteration) as exc:
        return [str(exc)]
