"""Located, advisory text observations; no editorial verdicts or corrections.

UTF-8 plain text, selected JSON strings, and explicit XML text/tail segments are supported.
The caller supplies language/profile; no language, edition, or correctness is inferred.
"""
from __future__ import annotations

from collections import Counter
from bisect import bisect_left
import hashlib
import json
from pathlib import Path
import re
import unicodedata

VERSION = "4"
_ENGLISH = frozenset({"en", "eng", "en-us", "en-gb"})
_LEXICAL_RULES = ("adjacent_repetition", "latin_digit_inside_word")
_CHAR_RULES = ("replacement_character_present", "encoding_sequence_present", "invisible_character_present")
_TOKEN = re.compile(r"\w+(?:['’ʼ‐‑-]\w*)*", re.UNICODE)
# Common Latin-1/Windows-1252 renderings of UTF-8 damage. The Greek forms
# matter for polytonic source text: e.g. ``Î¼``, ``Ïƒ``, and ``á¼¡``.
# These remain advisory markers, not an automatic diagnosis or correction.
_CP1252_DECODED_HIGH_BYTES = "€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ"
_MOJIBAKE_BYTE = re.escape(_CP1252_DECODED_HIGH_BYTES)
_MOJIBAKE = re.compile(
    rf"(?:[ÃÂÎÏ][\u0080-\u00bf{_MOJIBAKE_BYTE}]"
    rf"|á[\u0080-\u00bf{_MOJIBAKE_BYTE}]|â€|Å“|Ã&brvbr)"
)
_INVISIBLE = re.compile("[\u200b\u2060\ufeff]")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_constant(value):
    raise ValueError(f"nonfinite JSON constant is unsupported: {value}")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _select(document, pointer: str) -> str:
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ValueError("JSON pointer must be empty or start with /")
    value = document
    for part in pointer.split("/")[1:] if pointer else ():
        if re.search(r"~(?![01])", part):
            raise ValueError(f"invalid JSON pointer escape: {pointer!r}")
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
            index = int(part)
            if index >= len(value):
                raise ValueError(f"JSON pointer index out of range: {pointer!r}")
            value = value[index]
        else:
            raise ValueError(f"JSON pointer does not resolve: {pointer!r}")
    if not isinstance(value, str):
        raise ValueError(f"JSON pointer must select a string: {pointer!r}")
    return value


def _observations(text: str, english: bool, profile: str, expected: Counter):
    for match in re.finditer("�", text):
        yield "replacement_character_present", match.start(), match.end(), "U+FFFD is present. The original reading and cause are not determined."
    for match in _MOJIBAKE.finditer(text):
        yield "encoding_sequence_present", match.start(), match.end(), "A sequence associated with encoding damage is present; source context must establish its interpretation."
    for match in _INVISIBLE.finditer(text):
        if profile == "standard-ebooks" and match.group() == "\u2060" and text[match.end():match.end()+1] == "—":
            expected["word_joiner_before_em_dash"] += 1
            continue
        yield "invisible_character_present", match.start(), match.end(), "An invisible character is present. Word-joining and other intentional source typography may explain it."
    if not english:
        return
    tokens = [m for m in _TOKEN.finditer(text)
              if not (m.start() and unicodedata.category(text[m.start()-1]).startswith("M"))
              and not (m.end() < len(text) and unicodedata.category(text[m.end()]).startswith("M"))]
    for token in tokens:
        if re.fullmatch(r"[A-Za-z]{2,}[01][A-Za-z]{2,}", token.group()):
            yield "latin_digit_inside_word", token.start(), token.end(), "A digit occurs inside a Latin-letter token. This observation does not identify an erroneous or intended reading."
    for previous, current in zip(tokens, tokens[1:]):
        gap = text[previous.end():current.start()]
        if (re.fullmatch(r"[A-Za-z]{2,}", previous.group())
                and re.fullmatch(r"[A-Za-z]{2,}", current.group())
                and previous.group().lower() == current.group().lower()
                and gap and gap.isspace() and not any(c in gap for c in "\u2029\f\v")
                and not re.search(r"\n[ \t]*\n", gap.replace("\r\n", "\n").replace("\r", "\n"))):
            yield "adjacent_repetition", previous.start(), current.end(), "The same token occurs adjacently. Grammar, rhetoric, historical usage, or source formatting may explain it; no error is established."


def lint_file(path: Path, *, pointers: tuple[str, ...] | None = None,
              language: str | None = None, profile: str = "conservative") -> dict:
    """Read without modifying; positions are decoded-unit Unicode code points.

    A file-initial UTF-8 BOM is not part of the decoded unit. CRLF and all other
    source characters are preserved. JSON fields are interpreted as plain text;
    embedded markup, alternative readings, and language changes are not parsed.
    """
    if profile not in {"conservative", "standard-ebooks"}:
        raise ValueError(f"unsupported source profile: {profile!r}")
    if language is not None and not isinstance(language, str):
        raise ValueError("language must be a string or None")
    path = Path(path).resolve(strict=True)
    suffix = path.suffix.lower()
    if suffix not in {".txt", ".json"}:
        raise ValueError(f"unsupported input format: {suffix}; use an explicit plain-text adapter")
    if suffix == ".txt" and pointers is not None:
        raise ValueError("cannot select JSON pointers in plain text")
    if suffix == ".json" and (not pointers or isinstance(pointers, str)):
        raise ValueError("JSON requires explicit string-field pointers")
    data = path.read_bytes()
    decoded = data.decode("utf-8-sig", errors="strict")
    if suffix == ".txt":
        units = [("text", decoded)]
    else:
        if any(not isinstance(p, str) for p in pointers):
            raise ValueError("JSON pointers must be strings")
        if len(set(pointers)) != len(pointers):
            raise ValueError("duplicate JSON pointers are not allowed")
        document = json.loads(decoded, object_pairs_hook=_object, parse_constant=_reject_constant)
        units = [(pointer, _select(document, pointer)) for pointer in sorted(pointers)]
    report = _lint_units(path, data, units, language, profile, suffix)
    if path.read_bytes() != data:
        raise ValueError(f"source changed during reading: {path}")
    return report


def lint_json_strings(path: Path) -> dict:
    """Screen every JSON string value, including authored text overrides."""
    path = Path(path).resolve(strict=True)
    data = path.read_bytes()
    document = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_object, parse_constant=_reject_constant)
    units, stack = [], [("", document)]
    while stack:
        pointer, value = stack.pop()
        if isinstance(value, str):
            units.append((pointer, value))
        elif isinstance(value, dict):
            stack.extend((pointer + "/" + key.replace("~", "~0").replace("/", "~1"), child)
                         for key, child in value.items())
        elif isinstance(value, list):
            stack.extend((pointer + f"/{index}", child) for index, child in enumerate(value))
    report = _lint_units(path, data, sorted(units), None, "conservative", ".json")
    report["coverage"]["scope"] = "all_json_string_values"
    if path.read_bytes() != data:
        raise ValueError(f"source changed during reading: {path}")
    return report


def _lint_units(path, data, units, language, profile, suffix):
    source_hash = _sha(data)
    english = language is not None and language.lower() in _ENGLISH
    found = []
    expected = Counter()
    for locator, text in units:
        unit_hash = _sha(text.encode("utf-8"))
        line_breaks = None
        for rule, start, end, explanation in _observations(text, english, profile, expected):
            if line_breaks is None:
                line_breaks = [match.start() for match in re.finditer(r"\r\n|[\r\n]", text)]
            identity = [VERSION, source_hash, locator, unit_hash, rule, start, end, language, profile]
            found.append({
                "id": _sha(json.dumps(identity, ensure_ascii=False).encode("utf-8")),
                "rule": rule, "locator": locator, "unit_sha256": unit_hash,
                "start": start, "end": end, "line": bisect_left(line_breaks, start) + 1,
                "text": text[start:end], "context": text[max(0, start-80):end+80],
                "explanation": explanation, "review_status": "unreviewed",
                "editorial_assessment": "not_determined",
            })
    found.sort(key=lambda f: (f["locator"], f["start"], f["end"], f["rule"]))
    return {
        "format": "ocd-advisory-text-observations-v1", "tool_version": VERSION,
        "unicode_version": unicodedata.unidata_version,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "source_path": str(path), "source_sha256": source_hash,
        "language": language, "profile": profile, "text_correctness": "not_assessed",
        "coverage": {"scope": "plain_text_file" if suffix == ".txt" else "explicit_json_string_fields_only",
                     "units": len(units), "characters": sum(len(t) for _, t in units),
                     "empty_units": sum(not t.strip() for _, t in units),
                     "locators": [p for p, _ in units],
                     "offset_basis": "decoded unit Unicode code points; line numbers within unit; initial UTF-8 BOM excluded",
                     "limits": "No edition judgment, spelling normalization, cross-witness comparison, embedded-markup interpretation, or passage-language detection."},
        "rules_run": list(_CHAR_RULES) + (list(_LEXICAL_RULES) if english else []),
        "rules_not_run": [] if english else list(_LEXICAL_RULES),
        "rule_scope_note": "English token rules require explicit en/eng/en-US/en-GB; other language labels and unlabeled text receive character observations only.",
        "expected_typography": [{"rule": k, "count": v} for k, v in sorted(expected.items())],
        "groups": [{"rule": k, "count": v} for k, v in sorted(Counter(f["rule"] for f in found).items())],
        "observations": found,
    }


def lint_xml_file(path: Path, *, profile: str = "conservative") -> dict:
    """Character-only observations on every XML element text/tail segment.

    Segment boundaries remain separate; reading order and editorial correctness
    are not inferred from the XML tree.
    """
    from lxml import etree
    if profile not in {"conservative", "standard-ebooks"}:
        raise ValueError(f"unsupported source profile: {profile!r}")
    path = Path(path).resolve(strict=True)
    data = path.read_bytes()
    from build.lib.text_xml_reader import read_text_xml
    root, reader_evidence = read_text_xml(data)
    units = []
    roles = {}
    regions = {}
    # Build positional XPath once: getpath repeatedly counts wide sibling lists.
    stack = [(root, "/*[1]", False, None, "other", None)]
    while stack:
        node, location, tail, parent, region, reading = stack.pop()
        if tail:
            if node.tail is not None:
                locator = location + "/following-text()"
                units.append((locator, node.tail))
                roles[locator] = etree.QName(parent).localname
                regions[locator] = (region, reading)
            continue
        if not isinstance(node.tag, str):
            continue
        name = etree.QName(node).localname
        if name == "teiHeader":
            region = "header"
        elif name in {"front", "body", "back"}:
            region = name
        if name in {"sic", "corr"}:
            reading = name
        if node.text is not None:
            units.append((location + "/text()[1]", node.text))
            roles[location + "/text()[1]"] = name
            regions[location + "/text()[1]"] = (region, reading)
        children = []
        counts = Counter()
        for child in node:
            kind = "*" if isinstance(child.tag, str) else (
                "comment()" if isinstance(child, etree._Comment) else "processing-instruction()")
            counts[kind] += 1
            child_location = f"{location}/{kind}[{counts[kind]}]"
            children.extend(((child, child_location, False, None, region, reading),
                             (child, child_location, True, node, region, reading)))
        stack.extend(reversed(children))
    report = _lint_units(path, data, units, None, profile, ".xml")
    report["implementation_sha256"] = _sha(json.dumps(
        [report["implementation_sha256"], reader_evidence["implementation_sha256"]]).encode("ascii"))
    for observation in report["observations"]:
        observation["region"], observation["reading"] = regions[observation["locator"]]
    if path.read_bytes() != data:
        raise ValueError(f"source changed during reading: {path}")
    report["coverage"].update(
        scope="all_element_text_and_child_tails", roles=roles, xml_reader=reader_evidence,
        offset_basis="XML-normalized segment Unicode code points; line numbers within segment",
        limits="Attributes, comments and processing-instruction values are not screened. Element text and child tails, including expanded internal entities, headers, notes and alternatives, are screened separately. Locators and offsets refer to the expanded XML tree. ID uniqueness, schema validity and external DTD validation/default attributes are not assessed. No cross-segment or lexical reading-stream claims.")
    return report
