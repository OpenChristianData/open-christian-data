"""Deterministic retained-text to TEI candidate route for LIB-068."""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-lib068-source-local-retained-text-to-tei"
CONVERTER_VERSION = "2"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


@dataclass(frozen=True, slots=True)
class _Spec:
    source_id: str
    path: str
    size: int
    sha256: str
    newline: bytes
    newline_label: str
    line_count: int
    blank_count: int


_SPECS = {
    "donne-devotions-upon-emergent-occasions": _Spec(
        "gutenberg-pg23772-retained",
        "raw/gutenberg/pg23772.txt",
        427_543,
        "f1f2b08f2dcfe9f6618bb8031a5d055b5d58e30f80a399ff866d5b205b1773b7",
        b"\r\n",
        "CRLF with terminal CRLF",
        7_647,
        1_098,
    ),
    "newman-apologia-pro-vita-sua": _Spec(
        "gutenberg-pg22088-retained",
        "raw/gutenberg/pg22088.txt",
        818_680,
        "18e63c1d0bf11c66d6a6fdda83c19de9005c50b06831785a3507fcd1b6a49073",
        b"\r\n",
        "CRLF with terminal CRLF",
        14_174,
        1_553,
    ),
    "taylor-holy-dying": _Spec(
        "ccel-taylor-holy-dying-retained",
        "raw/ccel/taylor-holy-dying.txt",
        626_969,
        "a99a2da53737c99b48acd37c5506926620a0a66d5b74c1f2c0759bbe638679ad",
        b"\n",
        "LF with terminal LF",
        10_057,
        926,
    ),
    "taylor-holy-living": _Spec(
        "ccel-taylor-holy-living-retained",
        "raw/ccel/taylor-holy-living.txt",
        872_260,
        "e10fe562260708ce06081e39d728e738ac0fa8b8a3ee72d696bca5c44cb76856",
        b"\n",
        "LF with terminal LF",
        14_613,
        1_782,
    ),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict(path: Path, label: str) -> dict[str, object]:
    value = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _spec(source_manifest: SourceManifest) -> tuple[str, _Spec]:
    work_id = source_manifest.record.get("work_id")
    if source_manifest.record.get("ticket_id") != "LIB-068" or work_id not in _SPECS:
        raise ValueError("LIB-068 source identity drifted")
    assert isinstance(work_id, str)
    spec = _SPECS[work_id]
    if source_manifest.record.get("source_id") != spec.source_id:
        raise ValueError("LIB-068 source member identity drifted")
    return work_id, spec


def _source_lines(source: bytes, spec: _Spec) -> list[str]:
    if len(source) != spec.size or _sha(source) != spec.sha256:
        raise ValueError("LIB-068 retained source bytes drifted")
    other = b"\n" if spec.newline == b"\r\n" else b"\r"
    if not source.endswith(spec.newline) or other in source.replace(spec.newline, b""):
        raise ValueError("LIB-068 retained source newline contract drifted")
    try:
        lines = source.decode("utf-8", errors="strict").split(spec.newline.decode("ascii"))
    except UnicodeDecodeError as exc:
        raise ValueError("LIB-068 retained source is not strict UTF-8") from exc
    if len(lines) != spec.line_count or sum(line == "" for line in lines) != spec.blank_count:
        raise ValueError("LIB-068 retained source line census drifted")
    return lines


def _unresolved(work_id: str) -> tuple[dict[str, str], ...]:
    kinds = (
        ("projection", "Source-located literary structures, emphasis and local notes are encoded; source-bound technical checks do not replace native visual comparison or human textual acceptance." if work_id.startswith(("newman-", "donne-")) else "The line-faithful projection is technical evidence, not an editorially accepted reading structure."),
        ("identity", "Human review must confirm the bounded work and creator identity."),
        ("edition-witness", "Human review must confirm the retained transcription's edition and witness claims."),
        ("rights", "Human rights review is required before any publication decision."),
        ("editorial", "No headings, divisions, apparatus, spelling, punctuation, or wording receive an editorial disposition here."),
        ("textual-acceptance", "Technical validation is not human textual acceptance."),
        ("publication", "This candidate is not publication-ready or publication-authorized."),
    )
    return tuple(
        {
            "id": f"{work_id}-{kind}-review",
            "status": "unresolved",
            "kind": kind,
            "detail": detail,
        }
        for kind, detail in kinds
    )


def _tei(work_id: str, spec: _Spec, profile: Mapping[str, object], lines: list[str]) -> bytes:
    identity = profile.get("identity")
    if not isinstance(identity, Mapping):
        raise ValueError("LIB-068 identity profile is invalid")
    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    root.set(_XML_ID, f"{work_id}-candidate")
    header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_TEI}}}title").text = str(identity["work_title"])
    etree.SubElement(title_stmt, f"{{{_TEI}}}author").text = str(identity["creator_statement"])
    publication = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{_TEI}}}publisher").text = "Open Christian Data"
    availability = etree.SubElement(publication, f"{{{_TEI}}}availability", status="restricted")
    etree.SubElement(availability, f"{{{_TEI}}}p").text = "Nonaccepted candidate; publication is not authorized."
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{_TEI}}}bibl")
    etree.SubElement(bibl, f"{{{_TEI}}}title").text = str(identity["source_title"])
    etree.SubElement(bibl, f"{{{_TEI}}}author").text = str(identity["creator_statement"])
    etree.SubElement(bibl, f"{{{_TEI}}}note", type="retained-edition").text = str(identity["retained_edition_statement"])
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="source-url").text = str(identity["source_url"])
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="sha256").text = spec.sha256
    encoding = etree.SubElement(header, f"{{{_TEI}}}encodingDesc")
    encoding_statement = (
        "Every retained physical line is represented once, in order, without wording normalization; "
        f"the source uses {spec.newline_label}."
    )
    if work_id.startswith(("newman-", "donne-")):
        encoding_statement += " Literary v2 encodes source-located divisions, headings, paragraphs, local notes, embedded documents, verse, lists and tables. Numbered source-line segments and checked table column fragments preserve the physical witness. hi with rend source-underscore includes the literal underscore delimiters; ref text retains the literal bracketed note number. Empty and space-only lines remain exact, including blanks inside multiline headings. These encodings do not establish editorial acceptance."
    etree.SubElement(encoding, f"{{{_TEI}}}p").text = encoding_statement
    revision = etree.SubElement(header, f"{{{_TEI}}}revisionDesc", status="candidate")
    etree.SubElement(revision, f"{{{_TEI}}}change", when="2026-08-31").text = "Generated as a nonaccepted source-bound candidate."
    text = etree.SubElement(root, f"{{{_TEI}}}text")
    body = etree.SubElement(text, f"{{{_TEI}}}body")
    scope = etree.SubElement(body, f"{{{_TEI}}}div", type="retained-source")
    scope.set(_XML_ID, f"{work_id}-retained-source")
    if work_id in {"newman-apologia-pro-vita-sua", "donne-devotions-upon-emergent-occasions"}:
        _literary_body(scope, work_id, profile, lines)
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    for number, line in enumerate(lines, 1):
        node = etree.SubElement(scope, f"{{{_TEI}}}ab", type="source-line", n=str(number))
        node.text = line
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _literary_body(scope: etree._Element, work_id: str, profile: Mapping[str, object], lines: list[str]) -> None:
    """Render the pinned, source-located literary inventory, retaining line identity.

    Blank-separated source paragraphs are the fallback blocks, never divisions
    of a fixed number of lines. The inventory distinguishes contents entries
    from chapters and records work/station/subdivision nesting explicitly.
    """
    inventory = profile.get("literary_sections")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("LIB-068 literary inventory is required")
    starts = [int(row["line"]) for row in inventory]
    if starts != sorted(set(starts)) or starts[0] != 1:
        raise ValueError("LIB-068 literary inventory order is invalid")
    stack: list[tuple[int, etree._Element]] = [(0, scope)]
    for index, row in enumerate(inventory):
        first = int(row["line"])
        stop = starts[index + 1] if index + 1 < len(starts) else len(lines) + 1
        depth = int(row["depth"])
        while stack[-1][0] >= depth:
            stack.pop()
        if not str(row["anchor"]).strip() or depth != stack[-1][0] + 1 or lines[first - 1] != row["anchor"]:
            raise ValueError(f"LIB-068 literary boundary drift at line {first}")
        section = etree.SubElement(stack[-1][1], f"{{{_TEI}}}div", type=str(row["kind"]), n=str(first))
        section.set(_XML_ID, f"{work_id}-section-{first}")
        stack.append((depth, section))
        cursor = first
        head_end = int(row.get("head_end", first - 1))
        if head_end >= stop or (head_end < first and not (first == 1 and head_end == 0 and row["kind"] == "gutenberg-header")):
            raise ValueError(f"LIB-068 literary heading overlaps next section at {first}")
        if head_end >= first:
            head = etree.SubElement(section, f"{{{_TEI}}}head")
            _literary_lines(head, lines, cursor, head_end + 1)
            cursor = head_end + 1
        while cursor < stop:
            blank = not lines[cursor - 1].strip()
            end = cursor + 1
            while end < stop and bool(not lines[end - 1].strip()) == blank:
                end += 1
            footnote = re.match(r"^\s*\[(\d+)\] ", lines[cursor - 1])
            if blank:
                block = etree.SubElement(section, f"{{{_TEI}}}ab", type="source-whitespace")
            elif footnote:
                block = etree.SubElement(section, f"{{{_TEI}}}note", n=footnote.group(1), type="source-footnote")
                block.set(_XML_ID, f"{work_id}-footnote-{footnote.group(1)}")
            else:
                block = etree.SubElement(section, f"{{{_TEI}}}p")
            _literary_lines(block, lines, cursor, end)
            cursor = end
    _literary_inline(scope, work_id, lines, profile)
    for name, operation in (("lib068_literary_blocks", "apply_blocks"), ("lib068_source_letters", "apply_letters")):
        helper_path = Path(__file__).with_name(f"{name}.py")
        helper_spec = importlib.util.spec_from_file_location(name, helper_path)
        if helper_spec is None or helper_spec.loader is None:
            raise ValueError(f"LIB-068 literary implementation unavailable: {name}")
        helper = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helper)
        getattr(helper, operation)(scope, work_id, lines, profile)


def _literary_inline(scope: etree._Element, work_id: str, lines: list[str], profile: Mapping[str, object]) -> None:
    """Encode explicit source delimiters and local numeric note references.

    Underscores remain visible source characters inside hi; emphasis spanning
    physical lines is split without changing the paragraph or source text.
    """
    definitions: dict[str, int] = {}
    for number, value in enumerate(lines, 1):
        match = re.match(r"^\s*\[(\d+)\] ", value)
        if match:
            if match.group(1) in definitions:
                raise ValueError("LIB-068 duplicate source note number")
            definitions[match.group(1)] = number
    expected_notes = {"newman-apologia-pro-vita-sua": 21, "donne-devotions-upon-emergent-occasions": 386}[work_id]
    if len(definitions) != expected_notes:
        raise ValueError("LIB-068 source footnote census drifted")
    emphasized = False
    literals = {(int(row["line"]), str(row["token"])) for row in profile["literal_numeric_markers"]}
    for number, node in enumerate(scope.iter(f"{{{_TEI}}}seg"), 1):
        if node.get("n") != str(number):
            raise ValueError(f"LIB-068 source inline line identity drift at {number}")
        value = lines[number - 1]
        node.text = None
        container = etree.SubElement(node, f"{{{_TEI}}}hi", rend="source-underscore") if emphasized and value else node

        def append_text(text: str) -> None:
            if len(container):
                container[-1].tail = (container[-1].tail or "") + text
            else:
                container.text = (container.text or "") + text

        cursor = 0
        for token in re.finditer(r"_|\[(\d+)\]", value):
            append_text(value[cursor:token.start()])
            if token.group() == "_":
                if not emphasized:
                    container = etree.SubElement(node, f"{{{_TEI}}}hi", rend="source-underscore")
                append_text("_")
                emphasized = not emphasized
                if not emphasized:
                    container = node
            else:
                note_number = token.group(1)
                definition = definitions.get(note_number)
                is_definition = definition == number and token.start() == len(value) - len(value.lstrip())
                literal_marker = (number, token.group()) in literals
                if is_definition or literal_marker:
                    append_text(token.group())
                elif definition is None:
                    raise ValueError(f"LIB-068 unattached note marker at {number}")
                else:
                    ref = etree.SubElement(container, f"{{{_TEI}}}ref", type="source-note-reference", target=f"#{work_id}-footnote-{note_number}")
                    ref.text = token.group()
            cursor = token.end()
        append_text(value[cursor:])
        if not value.strip() and emphasized:
            raise ValueError(f"LIB-068 unclosed source emphasis before line {number}")
    if emphasized:
        raise ValueError("LIB-068 unclosed source emphasis")


def _literary_lines(parent: etree._Element, lines: list[str], first: int, stop: int) -> None:
    for number in range(first, stop):
        line = etree.SubElement(parent, f"{{{_TEI}}}seg", type="source-line", n=str(number))
        line.text = lines[number - 1]
        if number + 1 < stop:
            line.tail = "\n"


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    work_id, spec = _spec(source_manifest)
    profile = _strict(source_manifest.authority_path("reconstruction-profile"), "LIB-068 profile")
    policy = _strict(source_manifest.authority_path("validation-policy"), "LIB-068 policy")
    version = "2" if work_id.startswith(("newman-", "donne-")) else "1"
    if profile.get("profile_id") != f"lib068-{work_id}-retained-text-v{version}":
        raise ValueError("LIB-068 profile identity drifted")
    if policy.get("policy_id") != f"lib068-{work_id}-policy-v{version}":
        raise ValueError("LIB-068 policy identity drifted")
    source = source_manifest.authority_path("retained-text").read_bytes()
    lines = _source_lines(source, spec)
    census = [{
        "bytes": len(source),
        "decision": "include",
        "path": spec.path,
        "reason": "The sole frozen LIB-068 retained primary-source member for this work.",
        "sha256": _sha(source),
    }]
    unresolved = _unresolved(work_id)
    tei_bytes = _tei(work_id, spec, profile, lines)
    accountability = {
        "contract": f"ocd-lib068-{work_id}-source-accountability-v1",
        "profile_id": profile["profile_id"],
        "work_id": work_id,
        "source_id": spec.source_id,
        "member_census": census,
        "excluded_member_count": 0,
        "source_bytes": len(source),
        "source_sha256": _sha(source),
        "encoding": "strict UTF-8",
        "newline": spec.newline_label,
        "source_line_count": len(lines),
        "blank_line_count": sum(line == "" for line in lines),
        "source_line_sequence_sha256": _sha(_canonical(lines)),
        "represented_line_count": len(lines),
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "invented_line_count": 0,
        "reordered_line_count": 0,
        "unresolved_count": len(unresolved),
    }
    if work_id.startswith(("newman-", "donne-")):
        body = etree.fromstring(tei_bytes).find(f"{{{_TEI}}}text/{{{_TEI}}}body")
        accountability["native_tei_element_counts"] = dict(sorted(Counter(etree.QName(node).localname for node in body.iter() if node is not body).items()))
    authorities = {
        str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")}
        for item in source_manifest.record["authorities"]
    }
    provenance = {
        "contract": f"ocd-lib068-{work_id}-candidate-provenance-v1",
        "status": "nonaccepted",
        "ticket_id": "LIB-068",
        "work_id": work_id,
        "source_id": spec.source_id,
        "source_manifest_sha256": source_manifest.sha256,
        "identity": profile["identity"],
        "rights": profile["rights"],
        "source_member_census": census,
        "candidate_boundary": {
            "technical_validation_status": "candidate-pending-validation",
            "human_acceptance_status": "unresolved",
            "publication_status": "not-authorized",
            "canonical_data_or_ir_written": False,
        },
        "authorities": authorities,
    }
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": source_manifest.authority_path("source-attribution-readme").read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
