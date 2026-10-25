"""Compare independent parser observations without importing a converter.

Agreement covers the declared event projection, not source interpretation or
TEI semantics. XML DTD content, namespace declaration spelling, CDATA boundaries,
and lexical entity spelling are outside that projection. Custom entities fail
closed before a second parser is invoked. JSON uses strict UTF-8 (optional BOM).
Plain text compares strict UTF-8 decoding and physical line-ending sequences,
preserving a leading BOM; it does not infer TEI structure.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
from typing import Any
from xml.parsers import expat

from lxml import etree


class _UnsupportedXML(ValueError):
    pass


class _XMLProjectionError(ValueError):
    pass


class _JSONObject(list):
    pass


class _Events:
    def __init__(self) -> None:
        self.events: list[list[Any]] = []

    def add(self, kind: str, *values: Any) -> None:
        if kind == "text" and self.events and self.events[-1][0] == "text":
            self.events[-1][1] += values[0]
        else:
            self.events.append([kind, *values])

    def start(self, tag: str, attributes: dict[str, str]) -> None:
        self.add("start", tag, sorted([key, value] for key, value in attributes.items()))

    def end(self, tag: str) -> None:
        self.add("end", tag)

    def data(self, text: str) -> None:
        if text:
            self.add("text", text)

    def comment(self, text: str) -> None:
        self.add("comment", text)

    def pi(self, target: str, text: str) -> None:
        self.add("pi", target, text or "")

    def doctype(self, name: str, public: str | None, system: str | None) -> None:
        self.add("doctype", name, public or "", system or "")

    def close(self) -> list[list[Any]]:
        return self.events


def _xml_expat(data: bytes) -> list[list[Any]]:
    events = _Events()
    parser = expat.ParserCreate(namespace_separator="}")
    parser.specified_attributes = True
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def expanded(name: str) -> str:
        return "{" + name if "}" in name else name

    parser.StartElementHandler = lambda tag, attrs: events.start(
        expanded(tag), {expanded(key): value for key, value in attrs.items()})
    parser.EndElementHandler = lambda tag: events.end(expanded(tag))
    parser.CharacterDataHandler = events.data
    parser.CommentHandler = events.comment
    parser.ProcessingInstructionHandler = events.pi
    parser.StartDoctypeDeclHandler = lambda name, system, public, subset: events.doctype(
        name, public, system)

    def reject_entity(*args: Any) -> None:
        raise _UnsupportedXML("Custom entity declarations/references are not corroborated")

    parser.EntityDeclHandler = reject_entity
    parser.ExternalEntityRefHandler = reject_entity
    parser.SkippedEntityHandler = reject_entity
    parser.Parse(data, True)
    return events.events


def _xml_lxml(data: bytes) -> list[list[Any]]:
    target = _Events()
    parser = etree.XMLParser(target=target, resolve_entities=False, load_dtd=False,
                             no_network=True, recover=False, remove_comments=False,
                             remove_pis=False, attribute_defaults=False)
    events = etree.fromstring(data, parser=parser)
    # libxml2's target/SAX attributes can expose '&amp;' as literal '&#38;'
    # when entity expansion is disabled. The ordinary tree API returns the
    # actual normalized attribute value. Keep target events for document-shell
    # order, but corroborate element identity before using tree attributes.
    # String replacement is unsafe: the source may intentionally encode '&#38;'.
    root = etree.fromstring(data, parser=etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, recover=False,
        remove_comments=False, remove_pis=False, attribute_defaults=False))
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    starts = [event for event in events if event[0] == "start"]
    if len(elements) != len(starts):
        raise _XMLProjectionError("lxml target/tree element counts disagree")
    for element, event in zip(elements, starts):
        if element.tag != event[1]:
            raise _XMLProjectionError("lxml target/tree element names disagree")
        event[2] = sorted([key, value] for key, value in element.attrib.items())
    return events


def _number(value: str) -> list[Any]:
    """Exact normalized coefficient/exponent; Decimal.normalize rounds by context."""
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError("Non-finite JSON number")
    sign, digits, exponent = number.as_tuple()
    digits = list(digits)
    if not any(digits):
        return [sign, "0", 0]
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    return [sign, "".join(str(digit) for digit in digits), exponent]


def _json_python(text: str) -> list[list[Any]]:
    def pairs(values: list[tuple[str, Any]]) -> _JSONObject:
        seen: set[str] = set()
        for key, _ in values:
            if key in seen:
                raise ValueError(f"Duplicate JSON object key: {key!r}")
            seen.add(key)
        return _JSONObject(values)

    def reject(value: str) -> None:
        raise ValueError(f"Non-JSON numeric constant: {value}")

    value = json.loads(text, object_pairs_hook=pairs, parse_int=Decimal,
                       parse_float=Decimal, parse_constant=reject)
    events: list[list[Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, _JSONObject):
            events.append(["object-start"])
            for key, child in node:
                events.append(["key", key])
                walk(child)
            events.append(["object-end"])
        elif isinstance(node, list):
            events.append(["array-start"])
            for child in node:
                walk(child)
            events.append(["array-end"])
        elif isinstance(node, Decimal):
            events.append(["number", _number(str(node))])
        else:
            kind = "null" if node is None else "boolean" if isinstance(node, bool) else "string"
            events.append([kind, node])

    walk(value)
    return events


_NODE_SCRIPT = r"""
const fs = require('node:fs');
const events = [];
function walk(value) {
  if (value === null) { events.push(['null', null]); }
  else if (Array.isArray(value)) {
    events.push(['array-start']); value.forEach(walk); events.push(['array-end']);
  } else if (typeof value === 'object') {
    events.push(['object-start']);
    for (const key of Object.keys(value)) { events.push(['key', key]); walk(value[key]); }
    events.push(['object-end']);
  } else if (typeof value === 'number') {
    events.push(['number', Object.is(value, -0) ? '-0' : String(value)]);
  } else { events.push([typeof value, value]); }
}
try {
  walk(JSON.parse(fs.readFileSync(0, 'utf8')));
  process.stdout.write(JSON.stringify({version: process.version, events}));
} catch (error) { process.stderr.write(String(error)); process.exitCode = 2; }
"""


_TEXT_NODE_SCRIPT = r"""
const fs = require('node:fs');
const { TextDecoder } = require('node:util');
try {
  const text = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true})
    .decode(fs.readFileSync(0));
  process.stdout.write(JSON.stringify({
    version: process.version,
    text,
    line_endings: text.match(/\r\n|\r|\n/g) || []
  }));
} catch (error) { process.stderr.write(String(error)); process.exitCode = 2; }
"""


def _node_path() -> str | None:
    installed = Path("C:/Program Files/nodejs/node.exe")
    return str(installed) if installed.is_file() else shutil.which("node")


def corroborate(data: bytes, format: str) -> dict[str, Any]:
    """Return pass/fail/unsupported with exact input binding and bounded findings.

    No external XML resources are loaded. Node receives JSON only on stdin;
    source bytes are never evaluated as JavaScript or written to disk.
    """
    report: dict[str, Any] = {
        "status": "unsupported", "source_sha256": hashlib.sha256(data).hexdigest(),
        "format": format, "parsers": [], "findings": [], "compared_event_counts": {},
        "shared_assumptions": [
            "Parser agreement does not prove source meaning, mapping, or TEI fidelity.",
            "Both parser observations use the same declared event projection and comparison code.",
        ],
    }

    def finding(code: str, detail: str, status: str = "fail") -> dict[str, Any]:
        report["status"] = status
        report["findings"].append({"code": code, "detail": detail})
        return report

    if format.lower() in {"xml", "thml", "tei"}:
        report["parsers"] = [
            {"identity": "stdlib.xml.parsers.expat", "version": expat.EXPAT_VERSION},
            {"identity": "lxml/libxml2", "version": ".".join(map(str, etree.LXML_VERSION)),
             "engine_version": ".".join(map(str, etree.LIBXML_VERSION))},
        ]
        report["shared_assumptions"].append(
            "XML names are expanded; attribute order, lexical entities, CDATA boundaries, "
            "DTD contents, and namespace declaration spelling are not compared. "
            "Only explicit attributes are compared; external DTDs are never fetched.")
        try:
            left = _xml_expat(data)
        except _UnsupportedXML as exc:
            return finding("unsupported-xml-entity", str(exc), "unsupported")
        except expat.ExpatError as exc:
            return finding("expat-parse-error", str(exc))
        report["compared_event_counts"]["expat"] = len(left)
        try:
            right = _xml_lxml(data)
        except _XMLProjectionError as exc:
            return finding("lxml-projection-error", str(exc))
        except etree.XMLSyntaxError as exc:
            return finding("lxml-parse-error", str(exc))
        report["compared_event_counts"]["lxml"] = len(right)
    elif format.lower() in {"text", "plain-text"}:
        report["parsers"] = [{"identity": "Python/utf-8-codec", "version": platform.python_version()}]
        report["shared_assumptions"].append(
            "Exact decoded UTF-8 and CRLF/LF/CR sequences are compared; this does not infer TEI structure or source fidelity.")
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            return finding("python-text-decode-error", str(exc))
        left = [["decoded-text", text], ["line-endings", re.findall(r"\r\n|\r|\n", text)]]
        report["compared_event_counts"]["python-text"] = len(text)
        node = _node_path()
        if node is None:
            return finding("node-unavailable", "Node.js was not found", "unsupported")
        try:
            result = subprocess.run([node, "-e", _TEXT_NODE_SCRIPT], input=data,
                                    capture_output=True, timeout=30, check=False)
        except FileNotFoundError:
            return finding("node-unavailable", "Node.js executable disappeared", "unsupported")
        except (PermissionError, subprocess.TimeoutExpired) as exc:
            return finding("node-execution-error", str(exc))
        if result.returncode != 0:
            return finding("node-text-decode-error", result.stderr.decode("utf-8", errors="replace")[:2000])
        try:
            payload = json.loads(result.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return finding("node-text-output-error", str(exc))
        if (not isinstance(payload, dict) or not isinstance(payload.get("version"), str)
                or not isinstance(payload.get("text"), str)
                or not isinstance(payload.get("line_endings"), list)
                or any(not isinstance(ending, str) for ending in payload["line_endings"])):
            return finding("node-text-output-error", "Node text projection has invalid fields")
        report["parsers"].append({"identity": "Node.js/TextDecoder", "version": payload["version"]})
        right = [["decoded-text", payload["text"]], ["line-endings", payload["line_endings"]]]
        report["compared_event_counts"]["node-text"] = len(payload["text"])
    elif format.lower() == "json":
        report["parsers"] = [{"identity": "stdlib.json", "version": platform.python_version()}]
        report["shared_assumptions"].append(
            "JSON is strict UTF-8 with an optional leading BOM removed for both parsers. "
            "Python retains exact decimal numbers and object insertion order; JavaScript "
            "Number.toString decimal output is compared, not its underlying binary value. "
            "Observable rounding or numeric-key enumeration changes are reported as disagreement.")
        try:
            text = data.decode("utf-8-sig", errors="strict")
            left = _json_python(text)
        except (UnicodeDecodeError, ValueError, InvalidOperation, RecursionError) as exc:
            return finding("python-json-parse-error", str(exc))
        report["compared_event_counts"]["python-json"] = len(left)
        node = _node_path()
        if node is None:
            return finding("node-unavailable", "Node.js was not found", "unsupported")
        try:
            result = subprocess.run([node, "-e", _NODE_SCRIPT], input=text.encode("utf-8"),
                                    capture_output=True, timeout=30, check=False)
        except FileNotFoundError:
            return finding("node-unavailable", "Node.js executable disappeared", "unsupported")
        except (PermissionError, subprocess.TimeoutExpired) as exc:
            return finding("node-execution-error", str(exc))
        if result.returncode != 0:
            return finding("node-json-parse-error", result.stderr.decode("utf-8", errors="replace")[:2000])
        payload = json.loads(result.stdout)
        report["parsers"].append({"identity": "Node.js/JSON.parse", "version": payload["version"]})
        right = payload["events"]
        try:
            for event in right:
                if event[0] == "number":
                    event[1] = _number(event[1])
        except (ValueError, InvalidOperation) as exc:
            return finding("node-number-disagreement", str(exc))
        report["compared_event_counts"]["node-json"] = len(right)
    else:
        return finding("unsupported-format", f"No independent parser pair for {format!r}", "unsupported")

    if left != right:
        first = next((index for index, pair in enumerate(zip(left, right)) if pair[0] != pair[1]),
                     min(len(left), len(right)))
        return finding("parser-event-disagreement", f"Parser event streams differ at zero-based event {first}")
    report["status"] = "pass"
    return report
