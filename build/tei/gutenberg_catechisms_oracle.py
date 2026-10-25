"""Producer-independent oracle for the four LIB-069 Gutenberg catechisms."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree


ORACLE_ID = "ocd-lib069-gutenberg-catechisms-independent-oracle"
ORACLE_VERSION = "2"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}
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
SPECS = {
    "baltimore-catechism-no-1": ("pg14551.txt", 92_039, "d4b49653b457cc11f39df004896d072892b534e49899def16cdd75761c80993e", 2_620, 33, 2_270),
    "baltimore-catechism-no-2": ("pg14552.txt", 138_043, "3d4b556fdb094ab8e22a53df85f60ba3310b49c9c65a24281aeecb9119f9746c", 3_675, 30, 3_325),
    "baltimore-catechism-no-3": ("pg14553.txt", 438_198, "cff9e639e837f08a9c041719a49e0824ffbb4cf778393968369a0f6274da66f4", 9_253, 32, 8_903),
    "luthers-small-catechism": ("pg1670.txt", 43_598, "bef45c16f9785a86d2cc0a902415e50fb689915c5aaaf7328773b9949baaf61f", 1_035, 27, 685),
}
EXPECTED_AUTHORITY_NAMES = (
    "retained-source",
    "source-readme",
    "reconstruction-profile",
    "source-accountability-schema",
    "validation-policy",
    "tei-p5-xsd",
    "candidate-package-schema",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key}")
            result[key] = value
        return result
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _authority(source_manifest: object, name: str) -> tuple[Mapping[str, object], Path]:
    authorities = getattr(source_manifest, "record").get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source manifest authorities are invalid")
    for authority in authorities:
        if isinstance(authority, Mapping) and authority.get("name") == name:
            return authority, getattr(source_manifest, "authority_path")(name)
    raise ValueError(f"missing authority {name}")


def _role_authority(source_manifest: object, role: str) -> Mapping[str, object]:
    authorities = getattr(source_manifest, "record").get("authorities")
    matches = [item for item in authorities if isinstance(item, Mapping) and item.get("role") == role]
    if len(matches) != 1:
        raise ValueError(f"expected one {role} authority")
    return matches[0]


def _verify_authorities(source_manifest: object) -> None:
    authorities = getattr(source_manifest, "record").get("authorities")
    names = tuple(item.get("name") for item in authorities if isinstance(item, Mapping))
    if names != EXPECTED_AUTHORITY_NAMES:
        raise ValueError("source manifest authority inventory drifted")
    for name in names:
        authority, path = _authority(source_manifest, str(name))
        content = path.read_bytes()
        if authority.get("bytes") != len(content) or authority.get("sha256") != _sha(content):
            raise ValueError(f"{name} authority bytes drift")


def _source(source_manifest: object) -> tuple[str, bytes, tuple[bytes, ...]]:
    work_id = getattr(source_manifest, "record").get("work_id")
    if work_id not in SPECS:
        raise ValueError("work is outside LIB-069")
    _, byte_count, digest, line_count, _, _ = SPECS[str(work_id)]
    content = _authority(source_manifest, "retained-source")[1].read_bytes()
    if len(content) != byte_count or _sha(content) != digest or not content.startswith(b"\xef\xbb\xbf") or not content.endswith(b"\r\n") or content.count(b"\r\n") != line_count or content.count(b"\n") != line_count:
        raise ValueError("retained source identity or framing drift")
    content.decode("utf-8-sig", errors="strict")
    return str(work_id), content, tuple(content.split(b"\r\n")[:-1])


def _decode(number: int, line: bytes) -> str:
    return line.decode("utf-8-sig" if number == 1 else "utf-8", errors="strict")


def _category(start: int, end: int, number: int) -> str:
    if number < start:
        return "gutenberg-header"
    if number == start:
        return "gutenberg-start-marker"
    if number < end:
        return "work-content"
    if number == end:
        return "gutenberg-end-marker"
    return "gutenberg-license"


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
class _ExpectedLine:
    tag: str
    kind: str
    container_path: tuple[tuple[str, str], ...]


def _new_container(
    parent_path: tuple[tuple[str, str], ...], work_id: str, kind: str, number: int
) -> tuple[tuple[str, str], ...]:
    return parent_path + ((f"{work_id}-{kind}-{number:05d}", kind),)


def _expected_line(kind: str, container_path: tuple[tuple[str, str], ...]) -> _ExpectedLine:
    return _ExpectedLine("head" if kind in _HEADING_KINDS else "ab", kind, container_path)


def _is_baltimore_heading(text: str) -> bool:
    stripped = text.strip()
    return bool(
        stripped
        and _UPPER_HEADING_RE.fullmatch(stripped)
        and any(character.isalpha() for character in stripped)
        and not _BALTIMORE_QUESTION_RE.match(stripped)
        and not _BALTIMORE_ANSWER_RE.match(stripped)
    )


def _is_luther_question(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped.endswith("?") and _LUTHER_QUESTION_RE.match(stripped))


def _expected_structure(work_id: str, lines: tuple[bytes, ...]) -> list[_ExpectedLine]:
    _, _, _, _, start, end = SPECS[work_id]
    result: list[_ExpectedLine] = []

    if work_id.startswith("baltimore-"):
        catechism: tuple[tuple[str, str], ...] | None = None
        current: tuple[tuple[str, str], ...] | None = None
        lesson: tuple[tuple[str, str], ...] | None = None
        lesson_has_content = False
        question_answer: tuple[tuple[str, str], ...] | None = None
        answer_seen = False
        hymns: tuple[tuple[str, str], ...] | None = None
        stanza: tuple[tuple[str, str], ...] | None = None
        stanza_has_content = False
        hymn_mode = False

        def close_question_answer() -> None:
            nonlocal question_answer, answer_seen
            question_answer = None
            answer_seen = False

        for number, line in enumerate(lines, 1):
            text = _decode(number, line)
            category = _category(start, end, number)
            stripped = text.strip()
            is_question = bool(_BALTIMORE_QUESTION_RE.match(stripped))
            is_answer = bool(_BALTIMORE_ANSWER_RE.match(stripped))
            is_heading = _is_baltimore_heading(text)

            if category != "work-content":
                close_question_answer()
                stanza = None
                stanza_has_content = False
                result.append(_expected_line("marker" if category in {"gutenberg-start-marker", "gutenberg-end-marker"} else "wrapper", ()))
                continue

            if question_answer is not None and (is_question or is_heading):
                close_question_answer()

            if stripped == _BALTIMORE_HYMNS_HEADING:
                close_question_answer()
                hymns = _new_container((), work_id, "hymns", number)
                result.append(_expected_line("hymns", hymns))
                current = hymns
                lesson = None
                hymn_mode = True
                stanza = None
                stanza_has_content = False
                continue

            if hymn_mode:
                if not stripped:
                    result.append(_expected_line("blank", stanza if stanza is not None else hymns if hymns is not None else ()))
                    if stanza_has_content:
                        stanza = None
                        stanza_has_content = False
                    continue
                if stanza is None:
                    stanza = _new_container(hymns if hymns is not None else (), work_id, "stanza", number)
                    stanza_has_content = False
                result.append(_expected_line("content", stanza))
                stanza_has_content = True
                continue

            if _BALTIMORE_LESSON_RE.fullmatch(stripped):
                close_question_answer()
                parent = catechism if catechism is not None else ()
                lesson = _new_container(parent, work_id, "lesson", number)
                result.append(_expected_line("lesson", lesson))
                current = lesson
                lesson_has_content = False
                continue

            if text.strip().rstrip(".") == "CATECHISM":
                close_question_answer()
                catechism = _new_container((), work_id, "catechism-section", number)
                result.append(_expected_line("section", catechism))
                current = catechism
                lesson = None
                continue

            if is_heading:
                close_question_answer()
                if lesson is not None and not lesson_has_content:
                    result.append(_expected_line("topic", lesson))
                    continue
                if catechism is not None and lesson is not None:
                    catechism = None
                lesson = None
                current = _new_container((), work_id, "section", number)
                result.append(_expected_line("section", current))
                continue

            if is_question:
                close_question_answer()
                parent = current if current is not None else ()
                question_answer = _new_container(parent, work_id, "question-answer", number)
                result.append(_expected_line("question", question_answer))
                answer_seen = False
                if lesson is not None:
                    lesson_has_content = True
                continue

            if question_answer is not None:
                if not stripped:
                    result.append(_expected_line("blank", question_answer))
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
                    result.append(_expected_line(kind, question_answer))
                    if lesson is not None:
                        lesson_has_content = True
                continue

            kind = "blank" if not stripped else ("answer" if is_answer else "content")
            result.append(_expected_line(kind, current if current is not None else ()))
            if lesson is not None and stripped:
                lesson_has_content = True
        return result

    part: tuple[tuple[str, str], ...] | None = None
    appendix: tuple[tuple[str, str], ...] | None = None
    section: tuple[tuple[str, str], ...] | None = None
    home_chart: tuple[tuple[str, str], ...] | None = None
    chart_entry: tuple[tuple[str, str], ...] | None = None
    question_answer: tuple[tuple[str, str], ...] | None = None
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

    for number, line in enumerate(lines, 1):
        text = _decode(number, line)
        category = _category(start, end, number)
        stripped = text.strip()
        is_part = bool(_LUTHER_PART_RE.fullmatch(stripped))
        is_appendix = bool(re.fullmatch(r"Appendix\s+(?:I|II|III|IV|V)", stripped))
        is_home_chart = stripped == "The Home Chart"
        is_section = bool(_LUTHER_SECTION_RE.fullmatch(stripped))
        is_subheading = bool(_LUTHER_SUBHEADING_RE.match(stripped))
        is_question = _is_luther_question(text)
        is_role = bool(home_chart is not None and _LUTHER_CHART_ROLE_RE.fullmatch(stripped))

        if category != "work-content":
            close_question_answer()
            close_chart_entry()
            result.append(_expected_line("marker" if category in {"gutenberg-start-marker", "gutenberg-end-marker"} else "wrapper", ()))
            continue

        if question_answer is not None and (is_part or is_appendix or is_home_chart or is_section or is_subheading or is_role or is_question):
            close_question_answer()

        if is_part:
            close_question_answer()
            close_section()
            appendix = None
            part = _new_container((), work_id, "part", number)
            result.append(_expected_line("part", part))
            continue

        if is_appendix:
            close_question_answer()
            close_chart_entry()
            close_section()
            part = None
            appendix = _new_container((), work_id, "appendix", number)
            result.append(_expected_line("appendix", appendix))
            section = appendix
            continue

        if is_home_chart:
            close_question_answer()
            close_chart_entry()
            parent = appendix if appendix is not None else (part if part is not None else ())
            home_chart = _new_container(parent, work_id, "home-chart", number)
            result.append(_expected_line("home-chart", home_chart))
            section = home_chart
            continue

        if is_section:
            close_question_answer()
            close_chart_entry()
            parent = appendix if appendix is not None else (part if part is not None else ())
            section = _new_container(parent, work_id, "section", number)
            result.append(_expected_line("section", section))
            home_chart = None
            continue

        if is_subheading:
            close_question_answer()
            close_chart_entry()
            parent = section if section is not None else (part if part is not None else ())
            result.append(_expected_line("subheading", parent))
            continue

        if is_role:
            close_question_answer()
            close_chart_entry()
            chart_entry = _new_container(home_chart if home_chart is not None else (), work_id, "home-chart-entry", number)
            result.append(_expected_line("chart-role", chart_entry))
            continue

        if is_question:
            close_question_answer()
            parent = section if section is not None else (part if part is not None else ())
            question_answer = _new_container(parent, work_id, "question-answer", number)
            result.append(_expected_line("question", question_answer))
            answer_seen = False
            continue

        if question_answer is not None:
            if not stripped:
                result.append(_expected_line("blank", question_answer))
                if answer_seen:
                    close_question_answer()
            else:
                answer_seen = True
                result.append(_expected_line("answer", question_answer))
            continue

        if chart_entry is not None:
            if not stripped:
                result.append(_expected_line("blank", chart_entry))
                close_chart_entry()
            else:
                result.append(_expected_line("reference", chart_entry))
            continue

        kind = "blank" if not stripped else "content"
        parent = section if section is not None else (part if part is not None else ())
        result.append(_expected_line(kind, parent))

    return result

def _semantic_ancestors(node: etree._Element, division: etree._Element) -> list[etree._Element]:
    result: list[etree._Element] = []
    current = node.getparent()
    div_tag = f"{{{TEI_NS}}}div"
    while current is not None and current is not division:
        if current.tag == div_tag and current.get("type") != "source-line":
            result.append(current)
        current = current.getparent()
    if current is not division:
        raise ValueError("TEI source line escaped outer division")
    result.reverse()
    return result


def _feature_carriers(division: etree._Element) -> dict[int, etree._Element]:
    carrier_tags = {f"{{{TEI_NS}}}ab", f"{{{TEI_NS}}}head"}
    result: dict[int, etree._Element] = {}
    for node in division.iter():
        if node.tag not in carrier_tags or node.get("n") is None:
            continue
        try:
            number = int(node.get("n"))
        except (TypeError, ValueError) as exc:
            raise ValueError("TEI source-line number is invalid") from exc
        if number in result:
            raise ValueError("TEI source-line number is duplicated")
        result[number] = node
    return result


def _feature_container(division: etree._Element, identifier: str, kind: str) -> etree._Element:
    matches = division.xpath(".//tei:div[@xml:id=$identifier]", namespaces=NS, identifier=identifier)
    if len(matches) != 1 or matches[0].get("type") != kind:
        raise ValueError(f"missing source-defined {kind} container {identifier}")
    return matches[0]


def _feature_parent(container: etree._Element, division: etree._Element) -> etree._Element:
    parent = container.getparent()
    if parent is None:
        raise ValueError("source-defined container has no parent")
    if parent is division:
        return parent
    if parent.tag == f"{{{TEI_NS}}}div" and parent.get("type") != "source-line":
        return parent
    raise ValueError("source-defined container has an invalid parent")


def _validate_source_features(division: etree._Element, work_id: str, lines: tuple[bytes, ...]) -> None:
    _, _, _, _, start, end = SPECS[work_id]
    carriers = _feature_carriers(division)
    if set(carriers) != set(range(1, len(lines) + 1)):
        raise ValueError("source feature census does not cover every source line")
    texts = {number: _decode(number, line).strip() for number, line in enumerate(lines, 1)}

    def work_numbers() -> list[int]:
        return list(range(start, end))

    def assert_carrier(number: int, kind: str, ancestor_id: str | None = None) -> etree._Element:
        node = carriers[number]
        if node.get("type") != kind:
            raise ValueError(f"source feature carrier type drift at line {number}")
        ancestors = _semantic_ancestors(node, division)
        if ancestor_id is not None and not any(item.get(f"{{{XML_NS}}}id") == ancestor_id for item in ancestors):
            raise ValueError(f"source feature attachment drift at line {number}")
        return node

    if work_id.startswith("baltimore-"):
        lesson_numbers = [number for number in work_numbers() if _BALTIMORE_LESSON_RE.fullmatch(texts[number])]
        for number in lesson_numbers:
            lesson_id = f"{work_id}-lesson-{number:05d}"
            container = _feature_container(division, lesson_id, "lesson")
            assert_carrier(number, "lesson", lesson_id)
            parent = _feature_parent(container, division)
            if parent is not division and parent.get("type") != "catechism-section":
                raise ValueError(f"lesson parent drift at line {number}")
            if "--" not in texts[number]:
                following = next((candidate for candidate in range(number + 1, end) if texts[candidate]), None)
                if following is None or not _is_baltimore_heading(texts[following]) or _BALTIMORE_LESSON_RE.fullmatch(texts[following]):
                    raise ValueError(f"lesson topic missing at line {number}")
                assert_carrier(following, "topic", lesson_id)

        catechism_numbers = [number for number in work_numbers() if texts[number].rstrip(".") == "CATECHISM"]
        if not catechism_numbers:
            raise ValueError("source catechism section census drift")
        for catechism_number in catechism_numbers:
            catechism_id = f"{work_id}-catechism-section-{catechism_number:05d}"
            catechism = _feature_container(division, catechism_id, "catechism-section")
            if _feature_parent(catechism, division) is not division:
                raise ValueError(f"catechism section is not top-level at line {catechism_number}")
            assert_carrier(catechism_number, "section", catechism_id)

        hymns_numbers = [number for number in work_numbers() if texts[number] == _BALTIMORE_HYMNS_HEADING]
        if len(hymns_numbers) > 1:
            raise ValueError("source hymns section census drift")
        if hymns_numbers:
            hymns_number = hymns_numbers[0]
            hymns_id = f"{work_id}-hymns-{hymns_number:05d}"
            hymns = _feature_container(division, hymns_id, "hymns")
            if _feature_parent(hymns, division) is not division or any(item.get("type") == "lesson" for item in _semantic_ancestors(hymns, division)):
                raise ValueError("source hymns container is nested under a lesson")
            assert_carrier(hymns_number, "hymns", hymns_id)
            stanza_starts: list[int] = []
            active = False
            for number in range(hymns_number + 1, end):
                if not texts[number]:
                    active = False
                elif not active:
                    stanza_starts.append(number)
                    active = True
            actual_stanzas = division.xpath(".//tei:div[@type='stanza']", namespaces=NS)
            expected_stanzas = [f"{work_id}-stanza-{number:05d}" for number in stanza_starts]
            actual_stanza_ids = [item.get(f"{{{XML_NS}}}id") for item in actual_stanzas]
            if actual_stanza_ids != expected_stanzas:
                raise ValueError("source hymn stanza census or order drift")
            for number in stanza_starts:
                assert_carrier(number, "content", f"{work_id}-stanza-{number:05d}")

        question_numbers = [number for number in work_numbers() if _BALTIMORE_QUESTION_RE.match(texts[number])]
        if not question_numbers:
            raise ValueError("source question census is empty")
        for number in question_numbers:
            question_id = f"{work_id}-question-answer-{number:05d}"
            _feature_container(division, question_id, "question-answer")
            assert_carrier(number, "question", question_id)
        return

    part_numbers = [number for number in work_numbers() if _LUTHER_PART_RE.fullmatch(texts[number])]
    appendix_numbers = [number for number in work_numbers() if re.fullmatch(r"Appendix\s+(?:I|II|III|IV|V)", texts[number])]
    if not part_numbers or len(appendix_numbers) != 3:
        raise ValueError("source part or appendix census drift")
    for number in part_numbers:
        container = _feature_container(division, f"{work_id}-part-{number:05d}", "part")
        if _feature_parent(container, division) is not division:
            raise ValueError(f"part is not top-level at line {number}")
        assert_carrier(number, "part", f"{work_id}-part-{number:05d}")
    for number in appendix_numbers:
        container = _feature_container(division, f"{work_id}-appendix-{number:05d}", "appendix")
        if _feature_parent(container, division) is not division:
            raise ValueError(f"appendix is not top-level at line {number}")
        assert_carrier(number, "appendix", f"{work_id}-appendix-{number:05d}")

    role_numbers = [number for number in work_numbers() if _LUTHER_CHART_ROLE_RE.fullmatch(texts[number])]
    if len(role_numbers) != 13:
        raise ValueError(f"source home-chart role census drift: {len(role_numbers)}")
    home_chart_number = next((number for number in work_numbers() if texts[number] == "The Home Chart"), None)
    if home_chart_number is None:
        raise ValueError("source home-chart heading missing")
    home_chart_id = f"{work_id}-home-chart-{home_chart_number:05d}"
    home_chart = _feature_container(division, home_chart_id, "home-chart")
    if _feature_parent(home_chart, division).get(f"{{{XML_NS}}}id") != f"{work_id}-appendix-{appendix_numbers[-1]:05d}":
        raise ValueError("home-chart appendix attachment drift")
    assert_carrier(home_chart_number, "home-chart", home_chart_id)
    for role_index, number in enumerate(role_numbers):
        entry_id = f"{work_id}-home-chart-entry-{number:05d}"
        entry = _feature_container(division, entry_id, "home-chart-entry")
        if _feature_parent(entry, division).get(f"{{{XML_NS}}}id") != home_chart_id:
            raise ValueError(f"home-chart role parent drift at line {number}")
        next_role = role_numbers[role_index + 1] if role_index + 1 < len(role_numbers) else end
        first_blank = next((candidate for candidate in range(number + 1, next_role) if not texts[candidate]), None)
        interval_stop = first_blank + 1 if first_blank is not None else next_role
        expected_numbers = list(range(number, interval_stop))
        actual_numbers = sorted(
            int(node.get("n"))
            for node in entry.iter()
            if node.tag in {f"{{{TEI_NS}}}ab", f"{{{TEI_NS}}}head"} and node.get("n") is not None
        )
        if actual_numbers != expected_numbers:
            raise ValueError(f"home-chart role interval drift at line {number}")
        for candidate in expected_numbers:
            kind = "chart-role" if candidate == number else ("blank" if not texts[candidate] else "reference")
            assert_carrier(candidate, kind, entry_id)

    appendix_i_id = f"{work_id}-appendix-{appendix_numbers[0]:05d}"
    for heading in ("Morning Devotions", "Evening Devotions"):
        section_number = next((number for number in work_numbers() if texts[number] == heading), None)
        if section_number is None:
            raise ValueError(f"source devotion heading missing: {heading}")
        section_id = f"{work_id}-section-{section_number:05d}"
        devotion = _feature_container(division, section_id, "section")
        if _feature_parent(devotion, division).get(f"{{{XML_NS}}}id") != appendix_i_id:
            raise ValueError(f"{heading} appendix attachment drift")
        assert_carrier(section_number, "section", section_id)

    question_numbers = [number for number in work_numbers() if _is_luther_question(texts[number])]
    if not question_numbers:
        raise ValueError("source question census is empty")
    for number in question_numbers:
        question_id = f"{work_id}-question-answer-{number:05d}"
        _feature_container(division, question_id, "question-answer")
        assert_carrier(number, "question", question_id)



def _crosswalk(work_id: str, lines: tuple[bytes, ...]) -> list[dict[str, object]]:
    _, byte_count, _, _, start, end = SPECS[work_id]
    result: list[dict[str, object]] = []
    offset = 0
    for number, line in enumerate(lines, 1):
        record = line + b"\r\n"
        next_offset = offset + len(record)
        text = _decode(number, line)
        line_id = f"{work_id}-line-{number:05d}"
        result.append({"id": line_id, "line": number, "byte_start": offset, "byte_end": next_offset, "record_sha256": _sha(record), "text_sha256": _sha(text.encode("utf-8")), "category": _category(start, end, number), "disposition": "represented", "target": f"#{line_id}"})
        offset = next_offset
    if offset != byte_count:
        raise ValueError("independent source byte accounting does not close")
    return result


def _profile_policy(source_manifest: object, work_id: str) -> tuple[dict[str, object], dict[str, object]]:
    profile = _strict_json(_authority(source_manifest, "reconstruction-profile")[1].read_bytes(), "profile")
    policy = _strict_json(_authority(source_manifest, "validation-policy")[1].read_bytes(), "policy")
    filename, byte_count, digest, line_count, start, end = SPECS[work_id]
    if profile.get("contract") != "ocd-lib069-reconstruction-profile-v1" or profile.get("work_id") != work_id:
        raise ValueError("profile identity drift")
    if profile.get("source") != {"logical_path": f"raw/gutenberg/{filename}", "bytes": byte_count, "sha256": digest, "physical_lines": line_count, "encoding": "UTF-8 with BOM", "line_ending": "CRLF", "terminal_crlf": True}:
        raise ValueError("profile source binding drift")
    if profile.get("coverage") != {"represented_lines": line_count, "omitted_lines": 0, "duplicated_lines": 0, "start_marker_line": start, "end_marker_line": end}:
        raise ValueError("profile coverage drift")
    census = profile.get("retained_source_census")
    if not isinstance(census, dict) or census.get("assigned_members") != 1 or census.get("included_members") != 1 or census.get("excluded_members") != []:
        raise ValueError("profile census drift")
    if profile.get("structure") != _structure_policy(work_id):
        raise ValueError("profile structure policy drift")
    if policy.get("candidate_status") != "nonaccepted" or policy.get("publication_authorized") is not False or policy.get("human_acceptance_required") is not True:
        raise ValueError("policy acceptance boundary drift")
    checks = policy.get("checks")
    if not isinstance(checks, list) or "meaningful-structure-and-attachment" not in checks:
        raise ValueError("policy structure check missing")
    return profile, policy


def _validate_tei(source_manifest: object, candidate: object, work_id: str, lines: tuple[bytes, ...], profile: Mapping[str, object]) -> None:
    content = getattr(candidate, "member_bytes")("content.tei.xml")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    root = etree.fromstring(content, parser)
    xsd_path = _authority(source_manifest, "tei-p5-xsd")[1]
    etree.XMLSchema(etree.parse(str(xsd_path))).assertValid(etree.ElementTree(root))
    if root.tag != f"{{{TEI_NS}}}TEI" or root.attrib != {f"{{{XML_NS}}}id": f"{work_id}-candidate"}:
        raise ValueError("TEI root scope drift")
    expected_header = {
        "./tei:fileDesc/tei:titleStmt/tei:title": f"{profile['title']}: faithful retained-source candidate",
        "./tei:fileDesc/tei:titleStmt/tei:author": profile["creator"],
        "./tei:fileDesc/tei:titleStmt/tei:respStmt/tei:resp": "Exact physical-line transcription",
        "./tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name": "Open Christian Data",
        "./tei:fileDesc/tei:publicationStmt/tei:publisher": "Open Christian Data",
        "./tei:fileDesc/tei:publicationStmt/tei:availability/tei:p": "Nonaccepted candidate; publication is not authorized; human identity, edition, rights, textual, and editorial review remain separate.",
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:title": profile["title"],
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:author": profile["creator"],
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note": profile["contributor_statement"],
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='URI']": f"https://www.gutenberg.org/ebooks/{SPECS[work_id][0][2:-4]}",
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='SHA-256']": SPECS[work_id][2],
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:extent": f"{SPECS[work_id][1]} bytes; {SPECS[work_id][3]} BOM-bearing UTF-8 CRLF physical lines",
        "./tei:encodingDesc/tei:projectDesc/tei:p[1]": "Every retained physical line is represented exactly once, verbatim after transport framing removal, and in source order; source-defined structure is attached without text normalization.",
        "./tei:encodingDesc/tei:projectDesc/tei:p[2]": "The Project Gutenberg header, start/end markers, work content, and license wrapper remain distinctly classified source evidence.",
        "./tei:revisionDesc/tei:change": "Deterministic nonaccepted LIB-069 candidate generated from the pinned witness.",
    }
    header = root.find(f"{{{TEI_NS}}}teiHeader")
    if header is None:
        raise ValueError("TEI header missing")
    for xpath, expected in expected_header.items():
        matches = header.xpath(xpath, namespaces=NS)
        if len(matches) != 1 or matches[0].text != expected:
            raise ValueError(f"TEI metadata drift at {xpath}")
    expected_attributes = {
        "./tei:fileDesc/tei:publicationStmt/tei:availability": {"status": "restricted"},
        "./tei:fileDesc/tei:sourceDesc/tei:bibl": {
            f"{{{XML_NS}}}id": f"{work_id}-retained-source"
        },
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note": {"type": "contributor-statement"},
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='URI']": {"type": "URI"},
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='SHA-256']": {"type": "SHA-256"},
        "./tei:revisionDesc/tei:change": {"status": "draft"},
    }
    for xpath, expected in expected_attributes.items():
        matches = header.xpath(xpath, namespaces=NS)
        if len(matches) != 1 or dict(matches[0].attrib) != expected:
            raise ValueError(f"TEI metadata attributes drift at {xpath}")
    file_desc = header.find(f"{{{TEI_NS}}}fileDesc")
    if file_desc is None or [child.tag for child in file_desc] != [
        f"{{{TEI_NS}}}titleStmt",
        f"{{{TEI_NS}}}publicationStmt",
        f"{{{TEI_NS}}}sourceDesc",
    ]:
        raise ValueError("TEI file description structure drift")
    title_stmt = file_desc[0]
    publication_stmt = file_desc[1]
    source_desc = file_desc[2]
    if [child.tag for child in title_stmt] != [
        f"{{{TEI_NS}}}title",
        f"{{{TEI_NS}}}author",
        f"{{{TEI_NS}}}respStmt",
    ] or [child.tag for child in title_stmt[2]] != [
        f"{{{TEI_NS}}}resp",
        f"{{{TEI_NS}}}name",
    ]:
        raise ValueError("TEI title statement structure drift")
    if [child.tag for child in publication_stmt] != [
        f"{{{TEI_NS}}}publisher",
        f"{{{TEI_NS}}}availability",
    ] or [child.tag for child in publication_stmt[1]] != [f"{{{TEI_NS}}}p"]:
        raise ValueError("TEI publication statement structure drift")
    bibl = source_desc[0] if len(source_desc) == 1 else None
    if bibl is None or [child.tag for child in bibl] != [
        f"{{{TEI_NS}}}title",
        f"{{{TEI_NS}}}author",
        f"{{{TEI_NS}}}note",
        f"{{{TEI_NS}}}idno",
        f"{{{TEI_NS}}}idno",
        f"{{{TEI_NS}}}extent",
    ]:
        raise ValueError("TEI source description structure drift")
    encoding_desc = header.find(f"{{{TEI_NS}}}encodingDesc")
    revision_desc = header.find(f"{{{TEI_NS}}}revisionDesc")
    if (
        encoding_desc is None
        or revision_desc is None
        or [child.tag for child in header]
        != [f"{{{TEI_NS}}}fileDesc", f"{{{TEI_NS}}}encodingDesc", f"{{{TEI_NS}}}revisionDesc"]
        or [child.tag for child in encoding_desc]
        != [f"{{{TEI_NS}}}projectDesc"]
        or [child.tag for child in encoding_desc[0]]
        != [f"{{{TEI_NS}}}p", f"{{{TEI_NS}}}p"]
        or [child.tag for child in revision_desc]
        != [f"{{{TEI_NS}}}change"]
    ):
        raise ValueError("TEI header structure drift")
    division_matches = root.xpath("./tei:text/tei:body/tei:div", namespaces=NS)
    expected_division_attributes = {
        f"{{{XML_NS}}}id": f"{work_id}-retained-lines",
        "type": "catechism",
        "subtype": "gutenberg-source-transcription",
    }
    if len(division_matches) != 1 or division_matches[0].attrib != expected_division_attributes:
        raise ValueError("TEI work scope drift")
    division = division_matches[0]
    _validate_source_features(division, work_id, lines)
    expected = _expected_structure(work_id, lines)
    div_tag = f"{{{TEI_NS}}}div"
    carrier_tags = {f"{{{TEI_NS}}}ab", f"{{{TEI_NS}}}head"}
    containers: list[etree._Element] = []
    carriers: list[etree._Element] = []
    for node in division.iter():
        if node is division:
            continue
        if node.tag == div_tag:
            if set(node.attrib) != {f"{{{XML_NS}}}id", "type"}:
                raise ValueError("TEI container attributes drift")
            containers.append(node)
        elif node.tag in carrier_tags:
            carriers.append(node)
        else:
            raise ValueError("TEI work contains an unsupported element")
    if len(carriers) != len(expected):
        raise ValueError("TEI line omission, duplication, or invention")
    expected_container_paths: set[tuple[tuple[str, str], ...]] = set()
    for number, expected_line in enumerate(expected, 1):
        for depth in range(1, len(expected_line.container_path) + 1):
            expected_container_paths.add(expected_line.container_path[:depth])
        line_path = expected_line.container_path + ((f"{work_id}-line-container-{number:05d}", "source-line"),)
        for depth in range(1, len(line_path) + 1):
            expected_container_paths.add(line_path[:depth])

    def actual_path(node: etree._Element) -> tuple[tuple[str, str], ...]:
        path: list[tuple[str, str]] = []
        current: etree._Element | None = node if node.tag == div_tag else node.getparent()
        while current is not None and current is not division:
            if current.tag != div_tag:
                raise ValueError("TEI line/container ancestry drift")
            identifier = current.attrib.get(f"{{{XML_NS}}}id")
            kind = current.attrib.get("type")
            if identifier is None or kind is None:
                raise ValueError("TEI container identity missing")
            path.append((identifier, kind))
            current = current.getparent()
        if current is not division:
            raise ValueError("TEI work container escaped outer division")
        return tuple(reversed(path))

    actual_container_paths = [actual_path(node) for node in containers]
    if len(actual_container_paths) != len(set(actual_container_paths)) or set(actual_container_paths) != expected_container_paths:
        raise ValueError("TEI container structure drift")
    for container in containers:
        if container.get("type") == "source-line":
            children = list(container)
            if len(children) != 1 or children[0].tag not in carrier_tags:
                raise ValueError("TEI source-line container cardinality drift")
    reconstructed: list[bytes] = []
    for number, (node, line, expected_line) in enumerate(zip(carriers, lines, expected, strict=True), 1):
        category = _category(SPECS[work_id][4], SPECS[work_id][5], number)
        expected_attrs = {
            f"{{{XML_NS}}}id": f"{work_id}-line-{number:05d}",
            "n": str(number),
            "ana": f"#source-line #{category} #{expected_line.kind}",
            "type": expected_line.kind,
        }
        text = _decode(number, line)
        if (
            node.tag != f"{{{TEI_NS}}}{expected_line.tag}"
            or node.attrib != expected_attrs
            or len(node)
            or node.tail is not None
            or (node.text or "") != text
            or actual_path(node) != expected_line.container_path + ((f"{work_id}-line-container-{number:05d}", "source-line"),)
        ):
            raise ValueError(f"TEI order, text, carrier, attachment, or scope drift at line {number}")
        reconstructed.append((b"\xef\xbb\xbf" if number == 1 else b"") + text.encode("utf-8") + b"\r\n")
    if b"".join(reconstructed) != _authority(source_manifest, "retained-source")[1].read_bytes():
        raise ValueError("TEI does not losslessly reconstruct retained bytes")

def _validate_members(source_manifest: object, candidate: object, work_id: str, lines: tuple[bytes, ...], profile: Mapping[str, object]) -> None:
    package = _strict_json(getattr(candidate, "member_bytes")("manifest.json"), "candidate manifest")
    Draft202012Validator(_strict_json(_authority(source_manifest, "candidate-package-schema")[1].read_bytes(), "package schema")).validate(package)
    record = getattr(source_manifest, "record")
    expected_source_manifest = {
        "path": getattr(source_manifest, "path").relative_to(getattr(source_manifest, "repository_root")).as_posix(),
        "sha256": getattr(source_manifest, "sha256"),
    }
    if package.get("status") != "nonaccepted" or package.get("source_id") != record["source_id"] or package.get("source_manifest") != expected_source_manifest or package.get("converter") != dict(record["converter"]) or package.get("package_schema") != dict(record["package_schema"]):
        raise ValueError("candidate manifest binding drift")
    crosswalk = _crosswalk(work_id, lines)
    filename, byte_count, digest, line_count, _, _ = SPECS[work_id]
    expected_accountability = {"contract": "ocd-lib069-source-accountability-v1", "work_id": work_id, "source_sha256": digest, "source_bytes": byte_count, "physical_lines": line_count, "represented_lines": line_count, "omitted_lines": 0, "duplicated_lines": 0, "member_census": [{"path": f"raw/gutenberg/{filename}", "bytes": byte_count, "sha256": digest, "included": True, "reason": "The frozen LIB-069 maps assign this sole exact retained Gutenberg member to this work."}], "excluded_members": [], "crosswalk_sha256": _sha(_canonical(crosswalk)), "crosswalk": crosswalk}
    accountability = _strict_json(getattr(candidate, "member_bytes")("source-accountability.json"), "accountability")
    Draft202012Validator(_strict_json(_authority(source_manifest, "source-accountability-schema")[1].read_bytes(), "accountability schema")).validate(accountability)
    if accountability != expected_accountability:
        raise ValueError("source accountability drift")
    provenance = _strict_json(getattr(candidate, "member_bytes")("provenance.json"), "provenance")
    expected_provenance = {
        "contract": "ocd-lib069-provenance-v1",
        "work_id": work_id,
        "title": profile["title"],
        "creator": profile["creator"],
        "contributor_statement": profile["contributor_statement"],
        "source_format": "Project Gutenberg UTF-8 text with BOM and CRLF framing",
        "source_url": f"https://www.gutenberg.org/ebooks/{filename[2:-4]}",
        "source_sha256": digest,
        "candidate_status": "nonaccepted",
        "publication_authorized": False,
        "technical_validation_is_human_acceptance": False,
        "rights": {
            "retained_statement": "Project Gutenberg wrapper states a United States public-domain basis, requires users outside the United States to check local law, and binds reuse to the included or online Project Gutenberg License.",
            "worldwide": "unresolved",
            "publication": "not authorized",
        },
    }
    if provenance != expected_provenance:
        raise ValueError("candidate provenance or acceptance drift")
    unresolved_bytes = getattr(candidate, "member_bytes")("unresolved.jsonl")
    unresolved = [_strict_json(line + b"\n", "unresolved") for line in unresolved_bytes.splitlines()]
    expected_unresolved = [
        {"id": f"{work_id}-identity", "kind": "identity", "status": "human-review-required", "scope": "title, creator, and contributor roles", "detail": "Retained header role assertions are preserved but not human-accepted."},
        {"id": f"{work_id}-edition", "kind": "edition-witness", "status": "human-review-required", "scope": "whole retained Gutenberg witness", "detail": "Edition and witness identity remain unaccepted."},
        {"id": f"{work_id}-readings", "kind": "substantive-reading-editorial", "status": "human-review-required", "scope": f"all {line_count} retained physical lines", "detail": "No silent correction, modernization, or editorial acceptance was performed."},
        {"id": f"{work_id}-rights", "kind": "rights", "status": "human-review-required", "scope": "jurisdiction, Project Gutenberg license, and trademark terms", "detail": "Worldwide rights and publication permission remain unresolved."},
        {"id": f"{work_id}-acceptance", "kind": "acceptance-publication", "status": "human-review-required", "scope": "whole candidate", "detail": "Technical validation is not human acceptance or publication authorization."},
    ]
    if unresolved != expected_unresolved:
        raise ValueError("unresolved human boundary drift")
    if getattr(candidate, "member_bytes")("README.source.md") != _authority(source_manifest, "source-readme")[1].read_bytes():
        raise ValueError("candidate README attribution drift")


def _oracle(source_manifest: object, candidate: object) -> dict[str, object]:
    getattr(source_manifest, "verify")()
    _verify_authorities(source_manifest)
    getattr(candidate, "verify_integrity")()
    work_id, content, lines = _source(source_manifest)
    profile, _ = _profile_policy(source_manifest, work_id)
    _validate_tei(source_manifest, candidate, work_id, lines, profile)
    _validate_members(source_manifest, candidate, work_id, lines, profile)
    implementation_sha256 = _sha(Path(__file__).read_bytes())
    validator = getattr(source_manifest, "record")["validator"]
    if validator.get("implementation_sha256") != implementation_sha256 or validator.get("import_closure_sha256") != implementation_sha256:
        raise ValueError("oracle implementation closure drift")
    result: dict[str, object] = {"status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION, "implementation_sha256": implementation_sha256, "import_closure_sha256": implementation_sha256, "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})", "source_manifest_sha256": getattr(source_manifest, "sha256"), "candidate_sha256": getattr(candidate, "sha256"), "profile_sha256": _role_authority(source_manifest, "complete-source-feature-profile")["sha256"], "package_schema_sha256": _role_authority(source_manifest, "candidate-package-schema")["sha256"], "source_sha256": _sha(content), "xsd_sha256": _role_authority(source_manifest, "tei-validation-schema")["sha256"], "policy_sha256": _role_authority(source_manifest, "independent-validation-policy")["sha256"], "findings": []}
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
