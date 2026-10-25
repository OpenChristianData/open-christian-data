"""Faithful retained-line TEI candidates for the four LIB-069 catechisms."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, reconstruct


CONVERTER_ID = "ocd-lib069-gutenberg-catechisms-to-tei"
CONVERTER_VERSION = "2"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
STRUCTURE_POLICY_VERSION = "ocd-lib069-structure-policy-v1"

_HEADING_KINDS = frozenset(
    {"heading", "lesson", "topic", "section", "part", "appendix", "subheading", "home-chart", "chart-role", "hymns"}
)
_BALTIMORE_LESSON_RE = re.compile(
    r"^LESSON\s+(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|"
    r"ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH|SIXTEENTH|SEVENTEENTH|"
    r"EIGHTEENTH|NINETEENTH|TWENTIETH|TWENTY-FIRST|TWENTY-SECOND|TWENTY-THIRD|"
    r"TWENTY-FOURTH|TWENTY-FIFTH|TWENTY-SIXTH|TWENTY-SEVENTH|TWENTY-EIGHTH|"
    r"TWENTY-NINTH|THIRTIETH|THIRTY-FIRST|THIRTY-SECOND|THIRTY-THIRD|"
    r"THIRTY-FOURTH|THIRTY-FIFTH|THIRTY-SIXTH|THIRTY-SEVENTH)(?:\.|--.*)?$",
    re.IGNORECASE,
)
_BALTIMORE_QUESTION_RE = re.compile(r"^(?:\d+\.\s+Q\.|Q\.\s+\d+\.)\s+\S")
_BALTIMORE_ANSWER_RE = re.compile(r"^A\.\s+\S")
_BALTIMORE_HYMNS_HEADING = "HYMNS"
_UPPER_HEADING_RE = re.compile(r'''[A-Z0-9][A-Z0-9 .,:;!?()'"/_&\-\[\]]*''')
_LUTHER_PART_RE = re.compile(r"^(?:I|II|III|IV|V|VI)\.\s+\S.*$")
_LUTHER_SECTION_RE = re.compile(
    r"^(?:The\s+(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth)\s+"
    r"(?:Commandment|Article|Request|Petition)|Introduction|The Conclusion(?: to the Commandments)?|"
    r"Appendix\s+(?:I|II|III|IV|V)|Morning Devotions|Evening Devotions|The Blessing|Thanking God)$"
)
_LUTHER_SUBHEADING_RE = re.compile(r"^(?:The Simple Way a Father Should|On\s+\S)")
_LUTHER_QUESTION_RE = re.compile(r"^(?:What|Where|How|Who|Which|Do|Can|Are|Is|Have|Please)\b")
_LUTHER_CHART_ROLE_RE = re.compile(
    r"^(?:For Bishops, Pastors and Preachers:|What Hearers owe their Pastors:|For Earthly Authorities|"
    r"For those Under Authority|For Husbands|For Wives|For Parents|For Children|"
    r"For Servants, Maids, Hired Hands and Workers|For the Man and Woman of the House|"
    r"For Young People in General|For Widows|For Everyone in General)$"
)


def _structure_policy(work_id: str) -> dict[str, object]:
    common: dict[str, object] = {
        "contract": STRUCTURE_POLICY_VERSION,
        "line_carrier": "tei:ab-or-head",
        "line_container": "one tei:div per physical-line carrier",
        "container_element": "tei:div",
        "blank_lines": "one carrier in source order",
        "text_rule": "verbatim after transport framing removal",
        "uncertain_structure": "retain the line carrier and record an explicit unresolved disposition",
    }
    if work_id.startswith("baltimore-"):
        common.update(
            {
                "family": "baltimore",
                "heading_rule": "standalone uppercase work-content lines; standalone LESSON lines open lesson containers with the immediate uppercase topic, while inline -- LESSON lines retain their inline topic; HYMNS opens blank-delimited stanza blocks",
                "question_answer_rule": "numbered Q lines group through A lines and their source-contiguous continuations",
                "container_types": ["source-line", "catechism-section", "lesson", "section", "question-answer", "hymns", "stanza"],
            }
        )
    else:
        common.update(
            {
                "family": "luther-small",
                "heading_rule": "Roman-numeral parts and named source headings open typed containers; On and Simple Way lines remain typed subheadings",
                "question_answer_rule": "capitalized source question prompts group through their source-contiguous answers",
                "home_chart_rule": "the thirteen explicit source role headings group following reference lines; table cells are not inferred",
                "container_types": ["source-line", "part", "section", "appendix", "home-chart", "home-chart-entry", "question-answer"],
            }
        )
    return common


@dataclass(frozen=True, slots=True)
class WorkSpec:
    filename: str
    byte_count: int
    sha256: str
    line_count: int
    start_line: int
    end_line: int
    title: str
    creator: str
    contributor: str
    ebook_id: str


WORKS = {
    "baltimore-catechism-no-1": WorkSpec("pg14551.txt", 92_039, "d4b49653b457cc11f39df004896d072892b534e49899def16cdd75761c80993e", 2_620, 33, 2_270, "A catechism of Christian doctrine, no. 1: for first communion classes", "Catholic Church. Plenary Council of Baltimore", "Editor: John Lancaster Spalding; retained header also lists J. De Concilio and Saint Roberto Francesco Romolo Bellarmino as authors", "14551"),
    "baltimore-catechism-no-2": WorkSpec("pg14552.txt", 138_043, "3d4b556fdb094ab8e22a53df85f60ba3310b49c9c65a24281aeecb9119f9746c", 3_675, 30, 3_325, "A catechism of Christian doctrine, no. 2: for confirmation classes", "Catholic Church. Plenary Council of Baltimore", "Retained header lists J. De Concilio and Saint Roberto Francesco Romolo Bellarmino as authors", "14552"),
    "baltimore-catechism-no-3": WorkSpec("pg14553.txt", 438_198, "cff9e639e837f08a9c041719a49e0824ffbb4cf778393968369a0f6274da66f4", 9_253, 32, 8_903, "A catechism of Christian doctrine, no. 3: for two years' course for post-confirmation classes", "Catholic Church. Plenary Council of Baltimore", "Editor: Thomas L. Kinkead; retained header also lists J. De Concilio and Saint Roberto Francesco Romolo Bellarmino as authors", "14553"),
    "luthers-small-catechism": WorkSpec("pg1670.txt", 43_598, "bef45c16f9785a86d2cc0a902415e50fb689915c5aaaf7328773b9949baaf61f", 1_035, 27, 685, "Luther's Little Instruction Book: The Small Catechism of Martin Luther", "Martin Luther", "Translator: Robert E. Smith", "1670"),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class Witness:
    content: bytes
    byte_count: int
    sha256: str
    line_count: int

    @property
    def lines(self) -> tuple[bytes, ...]:
        return tuple(self.content.split(b"\r\n")[:-1])


def inspect_witness(work_id: str, path: str | Path) -> Witness:
    """Fail closed unless *path* is the exact frozen LIB-069 source member."""
    if work_id not in WORKS:
        raise ValueError(f"work is outside LIB-069 scope: {work_id}")
    spec = WORKS[work_id]
    content = Path(path).read_bytes()
    digest = _sha(content)
    line_count = content.count(b"\r\n")
    content.decode("utf-8-sig", errors="strict")
    if (len(content), digest, line_count) != (spec.byte_count, spec.sha256, spec.line_count) or not content.startswith(b"\xef\xbb\xbf") or not content.endswith(b"\r\n") or content.count(b"\n") != line_count:
        raise ValueError(f"{work_id} retained witness identity drift")
    return Witness(content, len(content), digest, line_count)


@dataclass(frozen=True, slots=True)
class CatechismSourceManifest:
    path: Path
    repository_root: Path
    witness_path: Path
    sha256: str
    _record: Mapping[str, object]

    @property
    def record(self) -> Mapping[str, object]:
        return self._record

    def authority_path(self, name: str) -> Path:
        authorities = self._record.get("authorities")
        if not isinstance(authorities, tuple):
            raise ValueError("source manifest authorities are invalid")
        for authority in authorities:
            if isinstance(authority, Mapping) and authority.get("name") == name:
                if authority.get("role") == "primary-source":
                    return self.witness_path
                logical = authority.get("path")
                if not isinstance(logical, str) or Path(logical).is_absolute() or ".." in Path(logical).parts:
                    raise ValueError(f"{name} authority path is invalid")
                return (self.repository_root / logical).resolve(strict=True)
        raise ValueError(f"source manifest has no {name!r} authority")

    def verify(self) -> None:
        if _sha(self.path.read_bytes()) != self.sha256:
            raise ValueError("source manifest bytes drifted")
        authorities = self._record.get("authorities")
        if not isinstance(authorities, tuple) or not authorities:
            raise ValueError("source manifest authority inventory is invalid")
        names: set[str] = set()
        for authority in authorities:
            if not isinstance(authority, Mapping) or not isinstance(authority.get("name"), str) or authority["name"] in names:
                raise ValueError("source manifest authority record is invalid")
            names.add(authority["name"])
            content = self.authority_path(authority["name"]).read_bytes()
            if authority.get("bytes") != len(content) or authority.get("sha256") != _sha(content):
                raise ValueError(f"{authority['name']} authority bytes drifted")
        for binding_name in ("converter", "validator"):
            binding = self._record.get(binding_name)
            if not isinstance(binding, Mapping) or not isinstance(binding.get("implementation_path"), str):
                raise ValueError(f"{binding_name} binding is invalid")
            implementation = (self.repository_root / binding["implementation_path"]).resolve(strict=True)
            if binding.get("implementation_sha256") != _sha(implementation.read_bytes()):
                raise ValueError(f"{binding_name} implementation authority drifted")
        package_schema = self._record.get("package_schema")
        if not isinstance(package_schema, Mapping) or not isinstance(package_schema.get("path"), str):
            raise ValueError("candidate package schema binding is invalid")
        if package_schema.get("sha256") != _sha((self.repository_root / package_schema["path"]).resolve(strict=True).read_bytes()):
            raise ValueError("candidate package schema authority drifted")


def load_source_manifest(path: str | Path, *, repository_root: str | Path, witness_path: str | Path) -> CatechismSourceManifest:
    root = Path(repository_root).resolve(strict=True)
    manifest_path = Path(path).resolve(strict=True)
    manifest_path.relative_to(root)
    content = manifest_path.read_bytes()
    record = json.loads(content.decode("utf-8"))
    if not isinstance(record, dict) or record.get("contract") != "ocd-source-manifest-v1" or record.get("work_id") not in WORKS:
        raise ValueError("source manifest contract or scope mismatch")
    manifest = CatechismSourceManifest(manifest_path, root, Path(witness_path).resolve(strict=True), _sha(content), _freeze(record))  # type: ignore[arg-type]
    manifest.verify()
    inspect_witness(str(record["work_id"]), manifest.witness_path)
    return manifest


def _decode(number: int, line: bytes) -> str:
    return line.decode("utf-8-sig" if number == 1 else "utf-8", errors="strict")


def _category(spec: WorkSpec, number: int) -> str:
    if number < spec.start_line:
        return "gutenberg-header"
    if number == spec.start_line:
        return "gutenberg-start-marker"
    if number < spec.end_line:
        return "work-content"
    if number == spec.end_line:
        return "gutenberg-end-marker"
    return "gutenberg-license"


def _is_baltimore_heading(text: str) -> bool:
    stripped = text.strip()
    return bool(
        stripped
        and _UPPER_HEADING_RE.fullmatch(stripped)
        and any(character.isalpha() for character in stripped)
        and not _BALTIMORE_QUESTION_RE.match(stripped)
        and not _BALTIMORE_ANSWER_RE.match(stripped)
    )


def _is_baltimore_catechism_heading(text: str) -> bool:
    return text.strip().rstrip(".") == "CATECHISM"


def _is_luther_question(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped.endswith("?") and _LUTHER_QUESTION_RE.match(stripped))


def _is_luther_section_heading(text: str) -> bool:
    return bool(_LUTHER_SECTION_RE.fullmatch(text.strip()))


def _is_luther_subheading(text: str) -> bool:
    return bool(_LUTHER_SUBHEADING_RE.match(text.strip()))


def _container(parent: etree._Element, work_id: str, kind: str, start_line: int) -> etree._Element:
    return _node(parent, "div", {"xml:id": f"{work_id}-{kind}-{start_line:05d}", "type": kind})


def _carrier(
    parent: etree._Element,
    work_id: str,
    number: int,
    text: str,
    category: str,
    kind: str,
) -> etree._Element:
    tag = "head" if kind in _HEADING_KINDS else "ab"
    attrs = {
        "xml:id": f"{work_id}-line-{number:05d}",
        "n": str(number),
        "ana": f"#source-line #{category} #{kind}",
        "type": kind,
    }
    line_container = _node(
        parent,
        "div",
        {"xml:id": f"{work_id}-line-container-{number:05d}", "type": "source-line"},
    )
    return _node(line_container, tag, attrs, text)


def _append_baltimore_body(division: etree._Element, work_id: str, witness: Witness) -> None:
    spec = WORKS[work_id]
    catechism: etree._Element | None = None
    current: etree._Element | None = None
    lesson: etree._Element | None = None
    lesson_has_content = False
    question_answer: etree._Element | None = None
    answer_seen = False
    hymns: etree._Element | None = None
    stanza: etree._Element | None = None
    stanza_has_content = False
    hymn_mode = False

    def close_question_answer() -> None:
        nonlocal question_answer, answer_seen
        question_answer = None
        answer_seen = False

    for number, line in enumerate(witness.lines, 1):
        text = _decode(number, line)
        category = _category(spec, number)
        stripped = text.strip()
        is_question = bool(_BALTIMORE_QUESTION_RE.match(stripped))
        is_answer = bool(_BALTIMORE_ANSWER_RE.match(stripped))
        is_heading = _is_baltimore_heading(text)

        if category != "work-content":
            close_question_answer()
            stanza = None
            stanza_has_content = False
            kind = "marker" if category in {"gutenberg-start-marker", "gutenberg-end-marker"} else "wrapper"
            _carrier(division, work_id, number, text, category, kind)
            continue

        if question_answer is not None and (is_question or is_heading):
            close_question_answer()

        if stripped == _BALTIMORE_HYMNS_HEADING:
            close_question_answer()
            hymns = _container(division, work_id, "hymns", number)
            _carrier(hymns, work_id, number, text, category, "hymns")
            current = hymns
            lesson = None
            hymn_mode = True
            stanza = None
            stanza_has_content = False
            continue

        if hymn_mode:
            if not stripped:
                _carrier(stanza if stanza is not None else hymns if hymns is not None else division, work_id, number, text, category, "blank")
                if stanza_has_content:
                    stanza = None
                    stanza_has_content = False
                continue
            if stanza is None:
                stanza = _container(hymns if hymns is not None else division, work_id, "stanza", number)
                stanza_has_content = False
            _carrier(stanza, work_id, number, text, category, "content")
            stanza_has_content = True
            continue

        if _BALTIMORE_LESSON_RE.fullmatch(stripped):
            close_question_answer()
            parent = catechism if catechism is not None else division
            lesson = _container(parent, work_id, "lesson", number)
            _carrier(lesson, work_id, number, text, category, "lesson")
            current = lesson
            lesson_has_content = False
            continue

        if _is_baltimore_catechism_heading(text):
            close_question_answer()
            catechism = _container(division, work_id, "catechism-section", number)
            _carrier(catechism, work_id, number, text, category, "section")
            current = catechism
            lesson = None
            continue

        if is_heading:
            close_question_answer()
            if lesson is not None and not lesson_has_content:
                _carrier(lesson, work_id, number, text, category, "topic")
                continue
            if catechism is not None and lesson is not None:
                catechism = None
            lesson = None
            current = _container(division, work_id, "section", number)
            _carrier(current, work_id, number, text, category, "section")
            continue

        if is_question:
            close_question_answer()
            parent = current if current is not None else division
            question_answer = _container(parent, work_id, "question-answer", number)
            _carrier(question_answer, work_id, number, text, category, "question")
            answer_seen = False
            if lesson is not None:
                lesson_has_content = True
            continue

        if question_answer is not None:
            if not stripped:
                _carrier(question_answer, work_id, number, text, category, "blank")
                if answer_seen:
                    close_question_answer()
            else:
                if is_answer:
                    answer_seen = True
                    kind = "answer"
                elif answer_seen:
                    kind = "answer"
                else:
                    kind = "question-continuation"
                _carrier(question_answer, work_id, number, text, category, kind)
                if lesson is not None:
                    lesson_has_content = True
            continue

        kind = "blank" if not stripped else ("answer" if is_answer else "content")
        _carrier(current if current is not None else division, work_id, number, text, category, kind)
        if lesson is not None and stripped:
            lesson_has_content = True

def _append_luther_body(division: etree._Element, work_id: str, witness: Witness) -> None:
    spec = WORKS[work_id]
    part: etree._Element | None = None
    appendix: etree._Element | None = None
    section: etree._Element | None = None
    home_chart: etree._Element | None = None
    chart_entry: etree._Element | None = None
    question_answer: etree._Element | None = None
    answer_seen = False

    def close_question_answer() -> None:
        nonlocal question_answer, answer_seen
        question_answer = None
        answer_seen = False

    def close_chart_entry() -> None:
        nonlocal chart_entry
        chart_entry = None

    def close_section() -> None:
        nonlocal section, home_chart, chart_entry
        section = None
        home_chart = None
        chart_entry = None

    for number, line in enumerate(witness.lines, 1):
        text = _decode(number, line)
        category = _category(spec, number)
        stripped = text.strip()
        is_part = bool(_LUTHER_PART_RE.fullmatch(stripped))
        is_appendix = bool(re.fullmatch(r"Appendix\s+(?:I|II|III|IV|V)", stripped))
        is_home_chart = stripped == "The Home Chart"
        is_section = _is_luther_section_heading(text)
        is_subheading = _is_luther_subheading(text)
        is_question = _is_luther_question(text)
        is_role = bool(home_chart is not None and _LUTHER_CHART_ROLE_RE.fullmatch(stripped))

        if category != "work-content":
            close_question_answer()
            close_chart_entry()
            kind = "marker" if category in {"gutenberg-start-marker", "gutenberg-end-marker"} else "wrapper"
            _carrier(division, work_id, number, text, category, kind)
            continue

        if question_answer is not None and (is_part or is_appendix or is_home_chart or is_section or is_subheading or is_role or is_question):
            close_question_answer()

        if is_part:
            close_question_answer()
            close_section()
            appendix = None
            part = _container(division, work_id, "part", number)
            _carrier(part, work_id, number, text, category, "part")
            continue

        if is_appendix:
            close_question_answer()
            close_chart_entry()
            close_section()
            part = None
            appendix = _container(division, work_id, "appendix", number)
            _carrier(appendix, work_id, number, text, category, "appendix")
            section = appendix
            continue

        if is_home_chart:
            close_question_answer()
            close_chart_entry()
            parent = appendix if appendix is not None else (part if part is not None else division)
            home_chart = _container(parent, work_id, "home-chart", number)
            _carrier(home_chart, work_id, number, text, category, "home-chart")
            section = home_chart
            continue

        if is_section:
            close_question_answer()
            close_chart_entry()
            parent = appendix if appendix is not None else (part if part is not None else division)
            section = _container(parent, work_id, "section", number)
            _carrier(section, work_id, number, text, category, "section")
            home_chart = None
            continue

        if is_subheading:
            close_question_answer()
            close_chart_entry()
            parent = section if section is not None else (part if part is not None else division)
            _carrier(parent, work_id, number, text, category, "subheading")
            continue

        if is_role:
            close_question_answer()
            close_chart_entry()
            chart_entry = _container(home_chart if home_chart is not None else division, work_id, "home-chart-entry", number)
            _carrier(chart_entry, work_id, number, text, category, "chart-role")
            continue

        if is_question:
            close_question_answer()
            parent = section if section is not None else (part if part is not None else division)
            question_answer = _container(parent, work_id, "question-answer", number)
            _carrier(question_answer, work_id, number, text, category, "question")
            answer_seen = False
            continue

        if question_answer is not None:
            if not stripped:
                _carrier(question_answer, work_id, number, text, category, "blank")
                if answer_seen:
                    close_question_answer()
            else:
                answer_seen = True
                _carrier(question_answer, work_id, number, text, category, "answer")
            continue

        if chart_entry is not None:
            if not stripped:
                _carrier(chart_entry, work_id, number, text, category, "blank")
                close_chart_entry()
            else:
                _carrier(chart_entry, work_id, number, text, category, "reference")
            continue

        kind = "blank" if not stripped else "content"
        parent = section if section is not None else (part if part is not None else division)
        _carrier(parent, work_id, number, text, category, kind)

def _records(work_id: str, witness: Witness) -> list[dict[str, object]]:
    spec = WORKS[work_id]
    result: list[dict[str, object]] = []
    offset = 0
    for number, line in enumerate(witness.lines, 1):
        record = line + b"\r\n"
        end = offset + len(record)
        text = _decode(number, line)
        line_id = f"{work_id}-line-{number:05d}"
        result.append({"id": line_id, "line": number, "byte_start": offset, "byte_end": end, "record_sha256": _sha(record), "text_sha256": _sha(text.encode("utf-8")), "category": _category(spec, number), "disposition": "represented", "target": f"#{line_id}"})
        offset = end
    if offset != witness.byte_count:
        raise ValueError("source byte accounting does not close")
    return result


def _node(parent: etree._Element, name: str, attrs: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    child = etree.SubElement(parent, f"{{{TEI_NS}}}{name}")
    for key, value in (attrs or {}).items():
        child.set(f"{{{XML_NS}}}id" if key == "xml:id" else key, value)
    child.text = text
    return child


def _tei(work_id: str, witness: Witness) -> bytes:
    spec = WORKS[work_id]
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(f"{{{XML_NS}}}id", f"{work_id}-candidate")
    header = _node(root, "teiHeader")
    file_desc = _node(header, "fileDesc")
    title_stmt = _node(file_desc, "titleStmt")
    _node(title_stmt, "title", text=f"{spec.title}: faithful retained-source candidate")
    _node(title_stmt, "author", text=spec.creator)
    resp = _node(title_stmt, "respStmt")
    _node(resp, "resp", text="Exact physical-line transcription")
    _node(resp, "name", text="Open Christian Data")
    publication = _node(file_desc, "publicationStmt")
    _node(publication, "publisher", text="Open Christian Data")
    _node(_node(publication, "availability", {"status": "restricted"}), "p", text="Nonaccepted candidate; publication is not authorized; human identity, edition, rights, textual, and editorial review remain separate.")
    bibl = _node(_node(file_desc, "sourceDesc"), "bibl", {"xml:id": f"{work_id}-retained-source"})
    _node(bibl, "title", text=spec.title)
    _node(bibl, "author", text=spec.creator)
    _node(bibl, "note", {"type": "contributor-statement"}, spec.contributor)
    _node(bibl, "idno", {"type": "URI"}, f"https://www.gutenberg.org/ebooks/{spec.ebook_id}")
    _node(bibl, "idno", {"type": "SHA-256"}, spec.sha256)
    _node(bibl, "extent", text=f"{spec.byte_count} bytes; {spec.line_count} BOM-bearing UTF-8 CRLF physical lines")
    project = _node(_node(header, "encodingDesc"), "projectDesc")
    _node(project, "p", text="Every retained physical line is represented exactly once, verbatim after transport framing removal, and in source order; source-defined structure is attached without text normalization.")
    _node(project, "p", text="The Project Gutenberg header, start/end markers, work content, and license wrapper remain distinctly classified source evidence.")
    _node(_node(header, "revisionDesc"), "change", {"status": "draft"}, "Deterministic nonaccepted LIB-069 candidate generated from the pinned witness.")
    division = _node(_node(_node(root, "text"), "body"), "div", {"xml:id": f"{work_id}-retained-lines", "type": "catechism", "subtype": "gutenberg-source-transcription"})
    if work_id.startswith("baltimore-"):
        _append_baltimore_body(division, work_id, witness)
    else:
        _append_luther_body(division, work_id, witness)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(source_manifest: CatechismSourceManifest) -> Mapping[str, bytes]:
    work_id = str(source_manifest.record["work_id"])
    spec = WORKS[work_id]
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes().decode("utf-8"))
    if profile.get("structure") != _structure_policy(work_id):
        raise ValueError(f"{work_id} structure policy drift")
    witness = inspect_witness(work_id, source_manifest.authority_path("retained-source"))
    records = _records(work_id, witness)
    census = [{"path": f"raw/gutenberg/{spec.filename}", "bytes": spec.byte_count, "sha256": spec.sha256, "included": True, "reason": "The frozen LIB-069 maps assign this sole exact retained Gutenberg member to this work."}]
    accountability = {"contract": "ocd-lib069-source-accountability-v1", "work_id": work_id, "source_sha256": spec.sha256, "source_bytes": spec.byte_count, "physical_lines": spec.line_count, "represented_lines": spec.line_count, "omitted_lines": 0, "duplicated_lines": 0, "member_census": census, "excluded_members": [], "crosswalk_sha256": _sha(_canonical(records)), "crosswalk": records}
    provenance = {"contract": "ocd-lib069-provenance-v1", "work_id": work_id, "title": spec.title, "creator": spec.creator, "contributor_statement": spec.contributor, "source_format": "Project Gutenberg UTF-8 text with BOM and CRLF framing", "source_url": f"https://www.gutenberg.org/ebooks/{spec.ebook_id}", "source_sha256": spec.sha256, "candidate_status": "nonaccepted", "publication_authorized": False, "technical_validation_is_human_acceptance": False, "rights": {"retained_statement": "Project Gutenberg wrapper states a United States public-domain basis, requires users outside the United States to check local law, and binds reuse to the included or online Project Gutenberg License.", "worldwide": "unresolved", "publication": "not authorized"}}
    unresolved = [
        {"id": f"{work_id}-identity", "kind": "identity", "status": "human-review-required", "scope": "title, creator, and contributor roles", "detail": "Retained header role assertions are preserved but not human-accepted."},
        {"id": f"{work_id}-edition", "kind": "edition-witness", "status": "human-review-required", "scope": "whole retained Gutenberg witness", "detail": "Edition and witness identity remain unaccepted."},
        {"id": f"{work_id}-readings", "kind": "substantive-reading-editorial", "status": "human-review-required", "scope": f"all {spec.line_count} retained physical lines", "detail": "No silent correction, modernization, or editorial acceptance was performed."},
        {"id": f"{work_id}-rights", "kind": "rights", "status": "human-review-required", "scope": "jurisdiction, Project Gutenberg license, and trademark terms", "detail": "Worldwide rights and publication permission remain unresolved."},
        {"id": f"{work_id}-acceptance", "kind": "acceptance-publication", "status": "human-review-required", "scope": "whole candidate", "detail": "Technical validation is not human acceptance or publication authorization."},
    ]
    return {"content.tei.xml": _tei(work_id, witness), "source-accountability.json": _canonical(accountability), "provenance.json": _canonical(provenance), "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved), "README.source.md": source_manifest.authority_path("source-readme").read_bytes()}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(source_manifest: CatechismSourceManifest, destination: str | Path) -> CandidatePackage:
    return reconstruct(source_manifest, destination, _convert)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--witness", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    manifest = load_source_manifest(args.manifest, repository_root=args.repository_root, witness_path=args.witness)
    candidate = build_candidate(manifest, args.output)
    print(json.dumps({"candidate_sha256": candidate.sha256, "output": str(candidate.path), "status": candidate.manifest["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
