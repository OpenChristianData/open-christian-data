"""Independent semantic and source-accountability oracle for BCP 1662."""

from __future__ import annotations

import ast
from html.parser import HTMLParser
import hashlib
import inspect
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema
from ocd_kernel.lib.storage_topology import resolve_repo_path


ORACLE_ID = "ocd-bcp-1662-independent-source-oracle"
ORACLE_VERSION = "2"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML = "http://www.w3.org/XML/1998/namespace"
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "p", "param", "source", "track", "wbr"}
_BROAD = re.compile(r"\b(?:either|or this|or else|or the following|another)\b", re.IGNORECASE)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: object) -> bytes:
    return (json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _strict(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


class _IndependentHtmlReader(HTMLParser):
    """Independent lexical reader and finite-state source-block recognizer."""

    def __init__(self, member: str, source: bytes, profile: Mapping[str, object]) -> None:
        super().__init__(convert_charrefs=True)
        self.member = member
        self.source = source.decode("iso-8859-1")
        self.starts = [0] + [match.end() for match in re.finditer("\n", self.source)]
        self.markers = tuple(str(value).casefold() for value in profile["alternative_markers"])
        policy = profile["block_policy"]
        self.boundaries = frozenset(str(value) for value in policy["start_elements"])
        self.close_before = frozenset(str(value) for value in policy["close_before_start_elements"])
        self.close_after = frozenset(str(value) for value in policy["close_after_end_elements"])
        self.alternative_break = str(policy["alternative_marker_break_element"])
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.observations: list[dict[str, object]] = []
        self.sequence = 0
        self.block_number = 0
        self.active_block: str | None = None
        self.kinds: dict[str, str] = {}

    def _position(self) -> int:
        line, column = self.getpos()
        return self.starts[line - 1] + column

    def _new_block(self, kind: str) -> str:
        self.block_number += 1
        self.active_block = f"{self.member}:block-{self.block_number:05d}"
        self.kinds[self.active_block] = kind
        return self.active_block

    def _block(self) -> str:
        return self.active_block or self._new_block("flow")

    def _put(self, kind: str, name: str | None, value: str, start: int, *,
             disposition: str = "represented", reason: str | None = None,
             semantic: str | None = None, visible: str | None = None) -> dict[str, object]:
        self.sequence += 1
        digest_input = f"{self.member}\0{start}\0{self.sequence}\0{kind}\0{name or ''}\0{value}".encode("utf-8")
        identifier = f"bcp-observation-{_sha(digest_input)[:24]}"
        item = {
            "observation_id": identifier, "member": self.member,
            "source_anchor": f"{self.member}:byte-{start}:observation-{self.sequence}",
            "byte_start": start, "source_order": self.sequence, "kind": kind,
            "name": name, "value": value, "value_sha256": _sha(value.encode("utf-8")),
            "disposition": disposition, "reason_code": reason,
            "tei_selector": f"#{identifier}" if disposition == "represented" else None,
            "semantic_role": semantic, "_block": self._block(),
        }
        if visible is not None:
            item["_visible"] = visible
        self.observations.append(item)
        return item

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        position = self._position()
        attr_values = {name.lower(): value or "" for name, value in attrs}
        if tag in self.boundaries:
            self._new_block(tag)
        navigation = tag == "img" and "/buttons/" in attr_values.get("src", "").lower()
        element = self._put(
            "element", tag, tag, position,
            disposition="evidence-only" if navigation else "represented",
            reason="navigation-image" if navigation else None,
            semantic="image-alternative" if tag == "img" and not navigation else None,
            visible=attr_values.get("alt", "") if tag == "img" and not navigation else None,
        )
        if tag in self.boundaries:
            element["semantic_role"] = "block-boundary"
        for attr_number, (name, value) in enumerate(attrs, start=1):
            item = self._put(
                "attribute", name.lower(), value or "", position,
                disposition="evidence-only" if navigation else "represented",
                reason="navigation-image-attribute" if navigation else None,
                semantic="image-alternative" if tag == "img" and name.lower() == "alt" and not navigation else None,
            )
            item["source_anchor"] = f"{self.member}:byte-{position}:attribute-{attr_number}"
        if tag in self.close_before:
            self.active_block = None
        elif tag == self.alternative_break and any(item.get("semantic_role") == "alternative-marker" and item.get("_block") == self.active_block for item in self.observations):
            self.active_block = None
        if tag not in _VOID:
            self.stack.append((tag, attr_values))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag in self.close_after:
            self.active_block = None

    def handle_data(self, text: str) -> None:
        normalized = " ".join(text.split())
        if not normalized:
            # Preserve an inline word boundary in the independent readable
            # projection without adding an accountability observation.  This
            # mirrors the source-level distinction made by the producer while
            # keeping the oracle's lexical census independent.
            if text == " " and self.observations:
                previous = self.observations[-1]
                next_source = self.source[self._position() + 1:]
                next_tag = re.match(r"\s*<([A-Za-z][A-Za-z0-9]*)\b", next_source)
                structural = self.boundaries | self.close_before | {"br", "hr", "img", "p"}
                if (
                    previous["kind"] == "text"
                    and previous.get("_block") == self.active_block
                    and next_tag is not None
                    and next_tag.group(1).lower() not in structural
                ):
                    previous["_visible"] = str(previous.get("_visible", previous["value"])) + text
            return
        red = any(tag == "font" and attrs.get("color", "").casefold() == "red" for tag, attrs in self.stack)
        semantic = "rubric" if red else None
        if red and any(marker in normalized.casefold() for marker in self.markers):
            semantic = "alternative-marker"
        self._put("text", None, text, self._position(), semantic=semantic, visible=text)

    def handle_comment(self, text: str) -> None:
        self._put("text", "comment", text, self._position(), disposition="evidence-only", reason="html-comment-edition-evidence")

    def read(self) -> tuple[tuple[dict[str, object], ...], Mapping[str, str]]:
        self.feed(self.source)
        self.close()
        return tuple(self.observations), self.kinds


def _fingerprint(items: tuple[dict[str, object], ...]) -> str:
    return _sha(_canonical([
        {key: item[key] for key in ("member", "byte_start", "source_order", "kind", "name", "value", "disposition", "reason_code")}
        for item in items
    ]))


def _read_sources(source_manifest: SourceManifest, profile: Mapping[str, object]) -> tuple[tuple[dict[str, object], ...], Mapping[str, str]]:
    authorities = source_manifest.record["authorities"]
    primary = [item for item in authorities if item["role"] == "primary-source"]
    failed_authorities = [item for item in authorities if item["role"] == "failed-acquisition-evidence"]
    members, failed = source_manifest.record["source_members"], source_manifest.record["failed_acquisitions"]
    def identify(item: Mapping[str, object]) -> tuple[object, object, object]:
        return item["path"], item["bytes"], item["sha256"]
    if (len(members) != 25 or sum(int(item["bytes"]) for item in members) != 733674
            or source_manifest.record["source_bundle"]["sha256"] != profile["source_bundle_sha256"]
            or {identify(item) for item in members} != {identify(item) for item in primary}
            or len(failed) != 5 or any(item["http_status"] != 404 for item in failed)
            or {identify(item) for item in failed} != {identify(item) for item in failed_authorities}):
        raise ValueError("independent source authority derivation failed")
    all_items: list[dict[str, object]] = []
    all_kinds: dict[str, str] = {}
    raw_root = resolve_repo_path(source_manifest.repository_root, "raw").resolve(strict=True)
    authority_by_path = {
        str(authority["path"]): authority
        for authority in source_manifest.record["authorities"]
        if authority["role"] == "primary-source"
    }
    for member in members:
        authority = authority_by_path[str(member["path"])]
        source_path = source_manifest.authority_path(str(authority["name"])).resolve(strict=True)
        source_path.relative_to(raw_root)
        reader = _IndependentHtmlReader(
            str(member["logical_name"]),
            source_path.read_bytes(),
            profile,
        )
        items, kinds = reader.read()
        all_items.extend(items)
        all_kinds.update(kinds)
    result = tuple(all_items)
    expected = profile["inventory"]
    counts = {kind: sum(item["kind"] == kind for item in result) for kind in ("element", "attribute", "text")}
    if (len(result) != expected["total"] or counts != {"element": expected["elements"], "attribute": expected["attributes"], "text": expected["text"]}
            or _fingerprint(result) != profile["parser"]["observation_fingerprint_sha256"]):
        raise ValueError("independent parser behavior or complete census drifted")
    return result, all_kinds


def _independent_standalone(block: Mapping[str, object], model: Mapping[str, object]) -> Mapping[str, object] | None:
    normalized = str(block["normalized"])
    matches = [authority for authority in model["standalone_roles"] if normalized in authority["block_forms"]]
    if len(matches) > 1:
        raise ValueError("independent standalone speaker authorities overlap")
    return matches[0] if matches else None


def _independent_speaker_boundaries(block: Mapping[str, object], model: Mapping[str, object]) -> list[dict[str, object]]:
    text = "".join(str(item.get("_visible", "")) for item in block["items"] if item["disposition"] == "represented")
    standalone = _independent_standalone(block, model)
    if standalone is not None:
        if standalone["utterance"] == "immediately-following-block":
            return []
        label = str(standalone["label_form"])
        start = text.find(label)
        if start < 0 or not text[start + len(label):].strip():
            raise ValueError("independent same-block role lacks a source-derived utterance")
        return [{"canonical": str(standalone["canonical"]), "start": start,
                 "end": start + len(label), "label": label}]
    punctuation = frozenset(str(value) for value in model["preceding_boundaries"] if value != "start")
    found: list[dict[str, object]] = []
    for authority in model["inline_roles"]:
        for form in authority["forms"]:
            expression = re.compile(rf"(?<![A-Za-z]){re.escape(str(form))}")
            for occurrence in expression.finditer(text):
                before = text[:occurrence.start()].rstrip()
                if not before or before[-1] in punctuation:
                    found.append({
                        "canonical": str(authority["canonical"]), "start": occurrence.start(),
                        "end": occurrence.end(), "label": occurrence.group(),
                    })
    found.sort(key=lambda value: (int(value["start"]), int(value["end"]), str(value["canonical"])))
    for left, right in zip(found, found[1:]):
        if int(right["start"]) < int(left["end"]):
            raise ValueError("independent speaker labels overlap")
    for number, turn in enumerate(found):
        boundary = int(found[number + 1]["start"]) if number + 1 < len(found) else len(text)
        if not text[int(turn["end"]):boundary].strip():
            raise ValueError("independent inline role lacks a nonempty source-derived utterance")
    return found


def _derive_blocks(items: tuple[dict[str, object], ...], kinds: Mapping[str, str],
                   profile: Mapping[str, object]) -> list[dict[str, object]]:
    ordered: list[dict[str, object]] = []
    index: dict[str, dict[str, object]] = {}
    calendars = {"xmas.html", "lent.html", "easter.html", "trinity.html", "saints.html"}
    for item in items:
        key = str(item["_block"])
        if key not in index:
            value = {"key": key, "member": item["member"], "kind": kinds[key], "items": []}
            index[key] = value
            ordered.append(value)
        index[key]["items"].append(item)
    for block in ordered:
        represented = [item for item in block["items"] if item["disposition"] == "represented"]
        visible = "".join(str(item.get("_visible", "")) for item in represented)
        block["visible"], block["normalized"] = visible, " ".join(visible.split())
        boundary = next((item for item in represented if item["kind"] == "element" and item["name"] == block["kind"]), None)
        seed = f"{block['member']}\0{block['key']}".encode("utf-8")
        block["id"] = str(boundary["observation_id"]) if boundary else f"bcp-block-{_sha(seed)[:24]}"
        attrs = [item for item in represented if item["kind"] == "attribute" and item["name"] == "name"]
        first_tags = [item["name"] for item in represented[:3] if item["kind"] == "element"]
        block["observance"] = block["member"] in calendars and first_tags == ["center", "strong", "a"] and bool(attrs)
        block["anchor"] = str(attrs[0]["value"]) if block["observance"] else None
        block["collect"] = block["member"] in calendars and not block["observance"] and block["normalized"].casefold() == "the collect."
        block["turns"] = _independent_speaker_boundaries(block, profile["speaker_model"])
        block["alternative"] = any(item["semantic_role"] == "alternative-marker" for item in represented)
    for number, block in enumerate(ordered):
        authority = _independent_standalone(block, profile["speaker_model"])
        if authority is None or authority["utterance"] != "immediately-following-block":
            continue
        if number + 1 == len(ordered):
            raise ValueError("independent standalone role lacks a following source block")
        following = ordered[number + 1]
        if (following["member"] != block["member"] or not str(following["normalized"]).strip()
                or following["observance"] or following["collect"] or following["alternative"]
                or following.get("consumed_by") is not None
                or _independent_standalone(following, profile["speaker_model"]) is not None):
            raise ValueError("independent standalone role lacks one eligible following utterance block")
        block["standalone"] = {"canonical": str(authority["canonical"]), "target": following}
        following["consumed_by"] = block
    return ordered


def _alternative_ranges(blocks: list[dict[str, object]]) -> dict[str, tuple[str, ...]]:
    relationships: dict[str, tuple[str, ...]] = {}
    for number, block in enumerate(blocks):
        if not block["alternative"]:
            continue
        target_ids: list[str] = []
        for candidate in blocks[number + 1:]:
            if (candidate["member"] != block["member"] or candidate["alternative"]
                    or candidate["observance"] or candidate["collect"]):
                break
            if candidate["normalized"]:
                target_ids.append(str(candidate["id"]))
            if candidate["kind"] == "flow" and candidate["normalized"]:
                break
        if not target_ids:
            raise ValueError("independent alternative derivation lacks a reading range")
        relationships[str(block["id"])] = tuple(target_ids)
    return relationships


def _runtime_repo_provenance(root: Path) -> tuple[Path, ...]:
    expected = {
        "contract": (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
        "validate": (root / "ocd_kernel/tei/validate.py").resolve(strict=True),
    }
    actual = {
        "contract": Path(inspect.getsourcefile(SourceManifest) or "").resolve(strict=True),
        "validate": Path(inspect.getsourcefile(compiled_schema) or "").resolve(strict=True),
    }
    for name, path in actual.items():
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"loaded repo dependency {name} is outside the repository") from exc
        lowered = path.as_posix().casefold()
        if "__editable__" in lowered or "site-packages" in lowered or not path.samefile(expected[name]):
            raise ValueError(f"loaded repo dependency {name} is an editable or shadow path")
    return tuple(actual[name] for name in sorted(actual))


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    pending = [Path(__file__).resolve(), *_runtime_repo_provenance(root)]
    visited: set[Path] = set()
    forbidden = tuple(str(value) for value in policy["forbidden_import_prefixes"])
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"__import__", "eval", "exec"}:
                raise ValueError("oracle dependency closure contains dynamic execution")
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"oracle dependency closure contains forbidden import {name}")
                candidate = root.joinpath(*name.split("."))
                local = candidate.with_suffix(".py") if candidate.with_suffix(".py").is_file() else candidate / "__init__.py"
                if local.is_file():
                    pending.append(local.resolve(strict=True))
    records = [{"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in sorted(visited, key=lambda value: value.as_posix())]
    return _sha(_canonical(records))


def _verify_semantic_tei(source_manifest: SourceManifest, candidate: CandidatePackage,
                         profile: Mapping[str, object], items: tuple[dict[str, object], ...],
                         blocks: list[dict[str, object]]) -> None:
    content = candidate.member_bytes("content.tei.xml")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(content, parser)
    try:
        compiled_schema().assertValid(root)
    except etree.DocumentInvalid as exc:
        raise ValueError("BCP candidate fails TEI P5") from exc
    ns = {"tei": _TEI, "xml": _XML}
    body = root.find(f"{{{_TEI}}}text/{{{_TEI}}}body")
    if body is None:
        raise ValueError("BCP TEI lacks a body")
    member_nodes = body.xpath("./tei:div[@n]", namespaces=ns)
    members = list(source_manifest.record["source_members"])
    if ([node.get("n") for node in member_nodes] != [item["logical_name"] for item in members]
            or [node.get("type") for node in member_nodes] != [item["kind"] for item in members]
            or [node.findtext(f"{{{_TEI}}}head") for node in member_nodes] != [item["title"] for item in members]):
        raise ValueError("BCP member order, type, or heading mutation")
    header = profile["tei_header"]
    metadata = {
        "title": root.findtext(f"{{{_TEI}}}teiHeader/{{{_TEI}}}fileDesc/{{{_TEI}}}titleStmt/{{{_TEI}}}title"),
        "author": root.findtext(f"{{{_TEI}}}teiHeader/{{{_TEI}}}fileDesc/{{{_TEI}}}titleStmt/{{{_TEI}}}author"),
        "publisher": root.findtext(f"{{{_TEI}}}teiHeader/{{{_TEI}}}fileDesc/{{{_TEI}}}publicationStmt/{{{_TEI}}}publisher"),
        "rights": root.findtext(f"{{{_TEI}}}teiHeader/{{{_TEI}}}fileDesc/{{{_TEI}}}publicationStmt/{{{_TEI}}}availability/{{{_TEI}}}p"),
        "source_title": root.findtext(f"{{{_TEI}}}teiHeader/{{{_TEI}}}fileDesc/{{{_TEI}}}sourceDesc/{{{_TEI}}}bibl/{{{_TEI}}}title"),
        "source_label": root.findtext(f"{{{_TEI}}}teiHeader/{{{_TEI}}}fileDesc/{{{_TEI}}}sourceDesc/{{{_TEI}}}bibl/{{{_TEI}}}ref"),
        "source_hash": root.findtext(f"{{{_TEI}}}teiHeader/{{{_TEI}}}fileDesc/{{{_TEI}}}sourceDesc/{{{_TEI}}}bibl/{{{_TEI}}}idno"),
    }
    expected_metadata = {
        "title": header["title"], "author": header["author"], "publisher": "Open Christian Data",
        "rights": header["rights_statement"], "source_title": header["title"],
        "source_label": "Retained source provider", "source_hash": source_manifest.record["source_bundle"]["sha256"],
    }
    availability = root.find(f"{{{_TEI}}}teiHeader/{{{_TEI}}}fileDesc/{{{_TEI}}}publicationStmt/{{{_TEI}}}availability")
    source_ref = root.find(f"{{{_TEI}}}teiHeader/{{{_TEI}}}fileDesc/{{{_TEI}}}sourceDesc/{{{_TEI}}}bibl/{{{_TEI}}}ref")
    source_id = root.find(f"{{{_TEI}}}teiHeader/{{{_TEI}}}fileDesc/{{{_TEI}}}sourceDesc/{{{_TEI}}}bibl/{{{_TEI}}}idno")
    if (metadata != expected_metadata or availability is None or availability.get("status") != header["availability_status"]
            or source_ref is None or source_ref.get("target") != header["source_url"]
            or source_id is None or source_id.get("type") != "SHA-256"):
        raise ValueError("BCP TEI metadata, rights, or source authority mutation")
    represented = {str(item["observation_id"]) for item in items if item["disposition"] == "represented"}
    evidence_only = {str(item["observation_id"]) for item in items if item["disposition"] == "evidence-only"}
    generated_blocks = {str(block["id"]) for block in blocks if str(block["id"]).startswith("bcp-block-")}
    observed_ids = root.xpath("//tei:text//@xml:id", namespaces=ns)
    if len(observed_ids) != len(set(observed_ids)) or set(observed_ids) != represented | generated_blocks or set(observed_ids) & evidence_only:
        raise ValueError("BCP TEI observation target omission, duplication, or invention")
    nodes_by_id = {
        str(node.get(f"{{{_XML}}}id")): node
        for node in root.xpath("//tei:text//*[@xml:id]", namespaces=ns)
    }
    allowed_tags = {"body", "div", "head", "ab", "sp", "speaker", "p", "seg", "anchor", "lb", "milestone"}
    member_names = {str(item["logical_name"]) for item in members}
    for node in body.iter():
        tag = etree.QName(node).localname
        identifier = node.get(f"{{{_XML}}}id")
        if tag not in allowed_tags:
            raise ValueError(f"BCP TEI contains invented wrapper {tag}")
        if tag == "div" and identifier is None and (node.getparent() is not body or node.get("n") not in member_names):
            raise ValueError("BCP TEI contains invented id-less division")
        if tag in {"seg", "anchor", "lb", "milestone"} and identifier is None:
            if tag != "seg" or node.get("type") != "source-continuation" or node.get("corresp", "").lstrip("#") not in represented:
                raise ValueError("BCP TEI contains invented id-less source content")
    alternatives = _alternative_ranges(blocks)
    block_ids = [str(block["id"]) for block in blocks]
    actual_block_order = [
        str(node.get(f"{{{_XML}}}id"))
        for node in root.xpath("//tei:text//*[@xml:id]", namespaces=ns)
        if node.get(f"{{{_XML}}}id") in set(block_ids)
    ]
    if actual_block_order != block_ids:
        raise ValueError("BCP source block order mutation")
    expected_parent: dict[str, str] = {}
    current_observance: dict[str, str | None] = {}
    current_collect: dict[str, str | None] = {}
    for block in blocks:
        member = str(block["member"])
        if block.get("consumed_by") is not None:
            expected_parent[str(block["id"])] = str(block["consumed_by"]["id"])
        elif block["observance"]:
            current_observance[member], current_collect[member] = str(block["id"]), None
            expected_parent[str(block["id"])] = member
        elif block["collect"]:
            if not current_observance.get(member):
                raise ValueError("independent collect lacks observance")
            current_collect[member] = str(block["id"])
            expected_parent[str(block["id"])] = str(current_observance[member])
        else:
            expected_parent[str(block["id"])] = str(current_collect.get(member) or current_observance.get(member) or member)
            if current_collect.get(member) and block["kind"] == "flow" and block["normalized"]:
                current_collect[member] = None
    for block in blocks:
        node = nodes_by_id.get(str(block["id"]))
        if node is None:
            raise ValueError("BCP source block lacks exactly one TEI node")
        expected_tag = "p" if block.get("consumed_by") is not None else "div"
        if etree.QName(node).localname != expected_tag:
            raise ValueError("BCP block kind or speaker structure mutation")
        parent = node.getparent()
        while parent is not None and etree.QName(parent).localname not in {"div", "body"}:
            parent = parent.getparent()
        actual_parent = parent.get(f"{{{_XML}}}id") if parent is not None and parent.get(f"{{{_XML}}}id") else parent.get("n") if parent is not None else None
        if actual_parent != expected_parent[str(block["id"])]:
            raise ValueError(
                f"BCP hierarchy mutation at {block['id']}: expected {expected_parent[str(block['id'])]!r}, observed {actual_parent!r}"
            )
        if block.get("consumed_by") is not None:
            if (set(node.attrib) != {f"{{{_XML}}}id"} or not "".join(node.itertext()).strip()
                    or node.get("corresp") is not None):
                raise ValueError("BCP cross-block utterance identity, content, or type mutation")
            continue
        if block.get("standalone") is not None:
            relationship = block["standalone"]
            target = relationship["target"]
            speeches = list(node)
            target_turns = list(target["turns"])
            if (node.get("type") != "source-block" or node.get("corresp") is not None
                    or len(speeches) != 1 + len(target_turns)
                    or any(etree.QName(speech).localname != "sp" for speech in speeches)
                    or "".join(node.itertext()) != str(block["visible"]) + str(target["visible"])):
                raise ValueError("BCP standalone/following-block relationship mutation")
            cross_speech = speeches[0]
            if [etree.QName(child).localname for child in cross_speech] != ["speaker", "p"]:
                raise ValueError("BCP standalone speaker child structure mutation")
            label, utterance = cross_speech[0], cross_speech[1]
            first_turn = int(target_turns[0]["start"]) if target_turns else len(str(target["visible"]))
            if (cross_speech.get("who") != f"#bcp-role-{str(relationship['canonical']).casefold()}"
                    or "".join(label.itertext()) != str(block["visible"])
                    or utterance.get(f"{{{_XML}}}id") != str(target["id"])
                    or set(utterance.attrib) != {f"{{{_XML}}}id"}
                    or not "".join(utterance.itertext()).strip()
                    or "".join(utterance.itertext()) != str(target["visible"])[:first_turn]):
                raise ValueError("BCP standalone label or cross-block utterance mutation")
            for container in (label, utterance):
                for anchored in container.xpath(".//*[text()]"):
                    if anchored.get(f"{{{_XML}}}id") is None and anchored.get("corresp") is None:
                        raise ValueError("BCP standalone label or utterance lost its source anchor")
            for number, turn in enumerate(target_turns):
                speech = speeches[number + 1]
                if [etree.QName(child).localname for child in speech] != ["speaker", "p"]:
                    raise ValueError("BCP following-block inline speaker child structure mutation")
                label, utterance = speech[0], speech[1]
                next_start = int(target_turns[number + 1]["start"]) if number + 1 < len(target_turns) else len(str(target["visible"]))
                if (speech.get("who") != f"#bcp-role-{str(turn['canonical']).casefold()}"
                        or "".join(label.itertext()) != str(target["visible"])[int(turn["start"]):int(turn["end"])]
                        or not "".join(utterance.itertext()).strip()
                        or "".join(utterance.itertext()) != str(target["visible"])[int(turn["end"]):next_start]):
                    raise ValueError("BCP following-block inline speaker mutation")
                for container in (label, utterance):
                    for anchored in container.xpath(".//*[text()]"):
                        if anchored.get(f"{{{_XML}}}id") is None and anchored.get("corresp") is None:
                            raise ValueError("BCP following-block inline turn lost its source anchor")
            continue
        visible_node = node.find(f"{{{_TEI}}}head") if block["observance"] or block["collect"] else node
        if visible_node is None or "".join(visible_node.itertext()) != block["visible"]:
            raise ValueError("BCP punctuation, drop-cap, heading, speaker, or block text mutation")
        if block["observance"] and (node.get("type"), node.get("n")) != ("observance", block["anchor"]):
            raise ValueError("BCP observance anchor mutation")
        if block["collect"] and node.get("type") != "collect":
            raise ValueError("BCP collect relationship mutation")
        expected_type = (
            "observance" if block["observance"] else "collect" if block["collect"]
            else "alternative-marker" if block["alternative"] else "source-block"
        )
        if node.get("type") != expected_type:
            raise ValueError("BCP source block type mutation")
        turns = list(block["turns"])
        if turns:
            children = list(node)
            expected_tags = (["ab"] if int(turns[0]["start"]) else []) + ["sp"] * len(turns)
            if [etree.QName(child).localname for child in children] != expected_tags:
                raise ValueError(f"BCP ordered speaker-turn structure mutation at {block['id']}")
            child_offset = 0
            if int(turns[0]["start"]):
                if "".join(children[0].itertext()) != str(block["visible"])[:int(turns[0]["start"])]:
                    raise ValueError("BCP speaker prelude attachment mutation")
                child_offset = 1
            for number, turn in enumerate(turns):
                speech = children[child_offset + number]
                if [etree.QName(child).localname for child in speech] != ["speaker", "p"]:
                    raise ValueError("BCP speaker child structure mutation")
                label, utterance = speech[0], speech[1]
                next_start = int(turns[number + 1]["start"]) if number + 1 < len(turns) else len(str(block["visible"]))
                if (speech.get("who") != f"#bcp-role-{str(turn['canonical']).casefold()}"
                        or "".join(label.itertext()) != str(block["visible"])[int(turn["start"]):int(turn["end"])]
                        or "".join(utterance.itertext()) != str(block["visible"])[int(turn["end"]):next_start]):
                    raise ValueError(f"BCP speaker label or governed utterance mutation at {block['id']}")
                for container in (label, utterance):
                    for anchored in container.xpath(".//*[text()]"):
                        if anchored.get(f"{{{_XML}}}id") is None and anchored.get("corresp") is None:
                            raise ValueError("BCP speaker label or utterance lost its source anchor")
        elif not block["observance"] and not block["collect"]:
            children = list(node)
            expected_subtype = str(block["kind"]) if block["kind"] in profile["heading_model"]["elements"] else None
            expected_ab_type = (
                profile["heading_model"]["tei_type"] if expected_subtype else
                "section-break" if block["kind"] == "hr" else "source-block"
            )
            if (len(children) != 1 or etree.QName(children[0]).localname != "ab"
                    or children[0].get("type") != expected_ab_type or children[0].get("subtype") != expected_subtype):
                raise ValueError("BCP flat source-anchored heading/block model mutation")
        expected_corresp = " ".join(f"#{target}" for target in alternatives.get(str(block["id"]), ())) or None
        if node.get("corresp") != expected_corresp or (node.get("type") == "alternative-marker") != bool(block["alternative"]):
            raise ValueError("BCP extra, removed, or mislinked alternative marker")
    if sum(block["observance"] for block in blocks) != 90 or sum(block["collect"] for block in blocks) != 85:
        raise ValueError("independent calendar relationship census drifted")
    if len(root.xpath("//tei:div[@type='observance']", namespaces=ns)) != 90 or len(root.xpath("//tei:div[@type='collect']", namespaces=ns)) != 85:
        raise ValueError("BCP TEI calendar relationship census mutation")
    expected_speakers: dict[str, int] = {}
    for block in blocks:
        if block.get("standalone") is not None:
            role = str(block["standalone"]["canonical"])
            expected_speakers[role] = expected_speakers.get(role, 0) + 1
        for turn in block["turns"]:
            role = str(turn["canonical"])
            expected_speakers[role] = expected_speakers.get(role, 0) + 1
    observed_speakers: dict[str, int] = {}
    for speech in root.xpath("//tei:sp", namespaces=ns):
        role = str(speech.get("who", "")).removeprefix("#bcp-role-")
        observed_speakers[role] = observed_speakers.get(role, 0) + 1
    normalized_expected = {role.casefold(): count for role, count in expected_speakers.items()}
    if observed_speakers != normalized_expected:
        raise ValueError("BCP source-derived speaker census mutation")
    for item in items:
        if item["semantic_role"] == "image-alternative" and item["kind"] == "element":
            node = nodes_by_id[str(item["observation_id"])]
            if etree.QName(node).localname != "seg" or node.get("type") != "drop-cap" or node.text != item.get("_visible"):
                raise ValueError("BCP drop-cap filename/alternative mutation")
        if item["semantic_role"] in {"rubric", "alternative-marker"} and item["kind"] == "text":
            node = nodes_by_id[str(item["observation_id"])]
            if node.get("type") != item["semantic_role"]:
                raise ValueError("BCP rubric or alternative semantic mutation")
    body_text = "".join(body.itertext())
    for item in items:
        if item["reason_code"] == "html-comment-edition-evidence" and str(item["value"]) in body_text:
            raise ValueError("BCP evidence-only comment leaked into body")


def _multi_source_digest(source_manifest: SourceManifest) -> str:
    members = sorted(
        ({"name": item["name"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]} for item in source_manifest.record["authorities"] if item["role"] == "primary-source"),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    _runtime_repo_provenance(root)
    if (candidate.manifest.get("status") != "nonaccepted"
            or candidate.manifest.get("converter") != source_manifest.record["converter"]
            or candidate.manifest.get("package_schema") != source_manifest.record["package_schema"]
            or candidate.manifest.get("source_manifest") != {"path": source_manifest.path.relative_to(root).as_posix(), "sha256": source_manifest.sha256}):
        raise ValueError("BCP candidate weakened package authority")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile, policy = _strict(profile_bytes, "BCP profile"), _strict(policy_bytes, "BCP policy")
    if platform.python_implementation() != profile["parser"]["implementation_family"]:
        raise ValueError("BCP oracle implementation family mismatch")
    items, kinds = _read_sources(source_manifest, profile)
    blocks = _derive_blocks(items, kinds, profile)
    clean = [{key: value for key, value in item.items() if not key.startswith("_")} for item in items]
    accountability = _strict(candidate.member_bytes("source-accountability.json"), "source-accountability.json")
    schema = _strict(source_manifest.authority_path("source-accountability-schema").read_bytes(), "accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"BCP accountability schema failure: {errors[0].message}")
    counts = {kind: sum(item["kind"] == kind for item in items) for kind in ("element", "attribute", "text")}
    expected_accountability = {
        "contract": "ocd-bcp-1662-source-accountability-v1", "schema": "bcp-1662.source-accountability.schema.json",
        "profile_id": profile["profile_id"], "parser": profile["parser"],
        "source_bundle": dict(source_manifest.record["source_bundle"]),
        "observation_counts": {"total": len(items), "elements": counts["element"], "attributes": counts["attribute"], "text": counts["text"]},
        "image_alt_counts": {"text_bearing": sum(item["kind"] == "element" and item["semantic_role"] == "image-alternative" for item in items), "navigation": sum(item["reason_code"] == "navigation-image" for item in items)},
        "alternative_counts": {"genuine": sum(block["alternative"] for block in blocks), "legacy_recall": sum(item["kind"] == "text" and item["name"] is None and _BROAD.search(str(item["value"])) is not None for item in items)},
        "comment_count": sum(item["reason_code"] == "html-comment-edition-evidence" for item in items),
        "document_count": len(source_manifest.record["source_members"]), "omitted_observation_count": 0,
        "duplicate_observation_count": 0, "crosswalk": clean,
    }
    if accountability != expected_accountability:
        raise ValueError("BCP accountability omission, duplication, invention, parser, or order mutation")
    _verify_semantic_tei(source_manifest, candidate, profile, items, blocks)
    expected_authorities = {str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")} for item in source_manifest.record["authorities"]}
    provenance = _strict(candidate.member_bytes("provenance.json"), "provenance.json")
    if (provenance.get("contract") != "ocd-bcp-1662-candidate-provenance-v1" or provenance.get("status") != "nonaccepted"
            or provenance.get("authorities") != expected_authorities or provenance.get("source_bundle") != source_manifest.record["source_bundle"]
            or provenance.get("failed_acquisitions") != [dict(item) for item in source_manifest.record["failed_acquisitions"]]):
        raise ValueError("BCP provenance authority mutation")
    identity, rights = provenance.get("identity"), provenance.get("rights")
    if (not isinstance(identity, dict) or identity.get("provider_identity_status") != "unresolved"
            or identity.get("provider_claims") != ["Lesley Holwell", "Lynda M. Howell", "CVW holwell"]
            or not isinstance(rights, dict) or rights.get("status") != "human-review-required" or rights.get("publication_authorized") is not False):
        raise ValueError("BCP provider or rights mutation")
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines() if line.strip()]
    if [item.get("id") for item in unresolved] != policy["required_unresolved_ids"]:
        raise ValueError("BCP unresolved ledger mutation")
    readme = candidate.member_bytes("README.source.md")
    if b"readable source-derived" not in readme or b"Drop-cap" not in readme or b"Five acquisitions returned HTTP 404" not in readme or b"human review" not in readme:
        raise ValueError("BCP review warning mutation")
    implementation = Path(__file__).resolve()
    result = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(implementation.read_bytes()), "import_closure_sha256": _closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256, "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes), "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _multi_source_digest(source_manifest), "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes), "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
