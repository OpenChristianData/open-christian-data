"""Read-only, source-native XML/JSON feature discovery; not fidelity approval.

No producer imports, recovery parsing, entity expansion, or source modification.
Locations are occurrence addresses, not XPath or JSON Pointer expressions.
"""
from __future__ import annotations

import codecs
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any
from xml.parsers import expat


class _Object(list):
    """Keep JSON object pairs, including repeated keys, distinct from arrays."""


class _Number(str):
    """Retain number spelling without float rounding or overflow."""


class _UnsupportedXML(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _json_features(text: str, add, issue) -> None:
    def reject_constant(value):
        raise ValueError(f"non-JSON numeric constant: {value}")

    value = json.loads(text, object_pairs_hook=_Object, parse_int=_Number,
                       parse_float=_Number, parse_constant=reject_constant)

    def walk(node, location):
        if isinstance(node, _Object):
            add("json-value", "object", location, len(node))
            seen = Counter()
            for ordinal, (key, child) in enumerate(node, 1):
                address = f"{location}/member[{ordinal}]"
                add("json-field", key, address, key)
                seen[key] += 1
                if seen[key] > 1:
                    issue("duplicate-json-key", address, f"repeated object key: {key!r}")
                walk(child, address + "/value")
        elif isinstance(node, list):
            add("json-value", "array", location, len(node))
            for ordinal, child in enumerate(node, 1):
                walk(child, f"{location}/item[{ordinal}]")
        else:
            kind = ("number" if isinstance(node, _Number) else "null" if node is None
                    else "boolean" if isinstance(node, bool) else "string")
            add("json-value", kind, location, str(node) if isinstance(node, _Number) else node)

    walk(value, "$")


def _xml_features(text: str, encoding: str, add, issue) -> None:
    parser = expat.ParserCreate(namespace_separator="}")
    parser.ordered_attributes = True
    stack: list[list] = []
    root_count = 0
    event = 0
    namespaces = []

    def name(value):
        return "{" + value if "}" in value else value

    def location():
        return stack[-1][0] if stack else "/document"

    def emit(kind, key, value):
        nonlocal event
        event += 1
        add(kind, key, f"{location()}/event[{event}]", value,
            line=parser.CurrentLineNumber, column=parser.CurrentColumnNumber)

    def start(tag, attrs):
        nonlocal root_count
        if stack:
            stack[-1][1] += 1
            address = f"{location()}/element[{stack[-1][1]}]"
        else:
            root_count += 1
            address = f"/document/element[{root_count}]"
        stack.append([address, 0])
        emit("xml-element", name(tag), None)
        for prefix, uri in namespaces:
            emit("xml-namespace", prefix or "", uri)
        namespaces.clear()
        for index in range(0, len(attrs), 2):
            key, value = name(attrs[index]), attrs[index + 1]
            emit("xml-attribute", key, value)
            if key in ("class", "{http://www.idpf.org/2007/ops}type"):
                for token in value.split():
                    emit("xml-token", key + "=" + token, token)

    def declaration(version, declared, standalone):
        emit("xml-declaration", "xml", {"version": version, "encoding": declared,
                                        "standalone": standalone})
        if declared:
            actual = codecs.lookup(encoding).name
            expected = codecs.lookup(declared).name
            if actual.removesuffix("-sig") != expected.removesuffix("-sig"):
                issue("encoding-declaration-mismatch", location(),
                      f"declared {declared}; explicitly decoded as {encoding}")

    def doctype(*args):
        emit("xml-doctype", args[0], {"system_id": args[1], "public_id": args[2]})
        raise _UnsupportedXML("DTDs/entities require a source-specific reader; no expansion attempted")

    parser.StartElementHandler = start
    parser.EndElementHandler = lambda tag: stack.pop()
    parser.CharacterDataHandler = lambda value: emit("xml-text", "text", value)
    parser.CommentHandler = lambda value: emit("xml-comment", "comment", value)
    parser.ProcessingInstructionHandler = lambda target, data: emit("xml-pi", target, data)
    parser.StartNamespaceDeclHandler = lambda prefix, uri: namespaces.append((prefix, uri))
    parser.XmlDeclHandler = declaration
    parser.StartDoctypeDeclHandler = doctype
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.Parse(text, True)


def check_rules(rules: object) -> list[dict[str, str]]:
    """Validate exact feature declarations; no wildcards or implicit defaults."""
    if not isinstance(rules, list):
        raise ValueError("policy must be a JSON array of feature rules")
    seen = set()
    for rule in rules:
        if (not isinstance(rule, dict) or set(rule) != {"kind", "name", "disposition", "reason"}
                or any(not isinstance(v, str) for v in rule.values())
                or not rule["kind"].strip() or not rule["reason"].strip()
                or rule["disposition"] not in ("mapped", "excluded", "unsupported")):
            raise ValueError("each rule needs kind, name, mapped/excluded/unsupported disposition, and reason")
        key = rule["kind"], rule["name"]
        if key in seen:
            raise ValueError(f"duplicate feature rule: {key!r}")
        seen.add(key)
    return rules


def preflight(path: Path, *, encoding: str = "utf-8", rules: object = None,
              max_bytes: int = 64 * 1024 * 1024) -> dict[str, Any]:
    """Inventory a file or directory without following links or modifying inputs.

    All files are accounted; only JSON and strict XML/XHTML/ThML are parsed.
    A supplied policy declares intended handling, not verified TEI preservation.
    """
    codecs.lookup(encoding)
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    checked_rules = check_rules(rules) if rules is not None else None
    policy = {(r["kind"], r["name"]): r for r in checked_rules or []}
    members, occurrences, diagnostics = [], [], []

    def linked(p):
        return p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())

    def visit(p, relative):
        def issue(code, location, message):
            diagnostics.append(dict(member=relative, code=code, location=location, message=message))

        if linked(p):
            members.append(dict(path=relative, status="not-read", reason="linked-path"))
            issue("linked-path", "/", "symlinks and junctions are not followed")
            return
        if p.is_dir():
            try:
                children = sorted(p.iterdir(), key=lambda child: child.name)
            except OSError as exc:
                issue("unreadable-directory", "/", str(exc))
                return
            for child in children:
                visit(child, child.name if relative == "." else relative + "/" + child.name)
            return
        record = dict(path=relative, status="not-read")
        members.append(record)
        try:
            size = p.stat().st_size
            record["bytes"] = size
            if size > max_bytes:
                issue("size-limit", "/", f"{size} bytes exceeds per-member limit {max_bytes}")
                return
            data = p.read_bytes()
        except OSError as exc:
            issue("unreadable-member", "/", str(exc))
            return
        record.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        suffix = p.suffix.lower()
        format_name = ("json" if suffix == ".json" else "xml" if suffix in
                       (".xml", ".xhtml", ".thml", ".tei") else "unsupported")
        record["format"] = format_name
        if format_name == "unsupported":
            issue("unsupported-format", "/", "member retained in census; no reader for this extension")
            return
        def add(kind, name, location, value, **extra):
            occurrences.append(dict(member=relative, ordinal=len(occurrences) + 1,
                                    kind=kind, name=name, location=location, value=value, **extra))
        try:
            text = data.decode(encoding, errors="strict")
            if format_name == "json":
                _json_features(text, add, issue)
            else:
                _xml_features(text, encoding, add, issue)
        except UnicodeDecodeError as exc:
            issue("decode-error", f"byte[{exc.start}]", exc.reason)
            return
        except (json.JSONDecodeError, expat.ExpatError, _UnsupportedXML, ValueError,
                LookupError, RecursionError) as exc:
            issue("parse-error", "/", str(exc))
            record["status"] = "partial"
            return
        record["status"] = "inventoried"

    visit(path, "." if path.is_dir() else path.name)
    if not members:
        diagnostics.append(dict(member=".", code="empty-input", location="/",
                                message="no file members inventoried"))
    features = {}
    for occurrence in occurrences:
        key = occurrence["kind"], occurrence["name"]
        if key not in features:
            rule = policy.get(key)
            features[key] = dict(kind=key[0], name=key[1], count=0,
                                 disposition=rule["disposition"] if rule else "undeclared",
                                 reason=rule["reason"] if rule else "")
        features[key]["count"] += 1
    unresolved = [o for o in occurrences if features[o["kind"], o["name"]]["disposition"]
                  in ("undeclared", "unsupported")]
    status = ("blocked" if diagnostics else "needs-disposition" if checked_rules is not None
              and unresolved else "declared" if checked_rules is not None else "inventoried")
    return dict(report_version=1, status=status, encoding=encoding,
                inventory_complete=bool(members) and all(m["status"] == "inventoried" for m in members)
                and not any(d["code"] == "unreadable-directory" for d in diagnostics),
                source_fidelity="not-assessed", acquisition_completeness="not-assessed",
                policy_sha256=hashlib.sha256(_canonical(checked_rules)).hexdigest()
                if checked_rules is not None else None,
                members=members, features=sorted(features.values(), key=lambda f: (f["kind"], f["name"])),
                occurrences=occurrences, unresolved_occurrences=unresolved,
                diagnostics=diagnostics)
