"""Readable deterministic TEI reconstruction of the retained partial BCP corpus."""

from __future__ import annotations

from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import platform
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.lib.storage_topology import resolve_repo_path


CONVERTER_ID = "ocd-bcp-1662-retained-html-to-tei"
CONVERTER_VERSION = "2"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_PROFILE_ID = "bcp-1662-complete-source-accountability-v1"
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "p", "param", "source", "track", "wbr"}
_LEGACY_ALT = re.compile(r"\b(?:either|or this|or else|or the following|another)\b", re.IGNORECASE)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: object) -> bytes:
    return (json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _tei(name: str, **attributes: str) -> etree._Element:
    return etree.Element(f"{{{_TEI}}}{name}", attrib=attributes)


class _RetainedHtml(HTMLParser):
    """Lexical census plus source-block boundaries; latin-1 makes offsets byte-stable."""

    def __init__(self, member: str, content: bytes, profile: Mapping[str, object]) -> None:
        super().__init__(convert_charrefs=True)
        self.member = member
        self.profile = profile
        policy = profile["block_policy"]
        self.block_starts = frozenset(str(value) for value in policy["start_elements"])
        self.close_before = frozenset(str(value) for value in policy["close_before_start_elements"])
        self.close_after = frozenset(str(value) for value in policy["close_after_end_elements"])
        self.alternative_break = str(policy["alternative_marker_break_element"])
        self.text = content.decode("iso-8859-1")
        self.line_starts = [0] + [match.end() for match in re.finditer("\n", self.text)]
        self.records: list[dict[str, object]] = []
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.order = 0
        self.block_serial = 0
        self.current_block: str | None = None
        self.block_kinds: dict[str, str] = {}

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def _start_block(self, kind: str) -> str:
        self.block_serial += 1
        self.current_block = f"{self.member}:block-{self.block_serial:05d}"
        self.block_kinds[self.current_block] = kind
        return self.current_block

    def _ensure_block(self) -> str:
        return self.current_block or self._start_block("flow")

    def _add(self, kind: str, name: str | None, value: str, *, byte_start: int,
             disposition: str = "represented", reason: str | None = None,
             role: str | None = None, visible: str | None = None) -> dict[str, object]:
        self.order += 1
        seed = f"{self.member}\0{byte_start}\0{self.order}\0{kind}\0{name or ''}\0{value}".encode("utf-8")
        identifier = f"bcp-observation-{_sha(seed)[:24]}"
        record = {
            "observation_id": identifier, "member": self.member,
            "source_anchor": f"{self.member}:byte-{byte_start}:observation-{self.order}",
            "byte_start": byte_start, "source_order": self.order, "kind": kind,
            "name": name, "value": value, "value_sha256": _sha(value.encode("utf-8")),
            "disposition": disposition, "reason_code": reason,
            "tei_selector": f"#{identifier}" if disposition == "represented" else None,
            "semantic_role": role, "_block": self._ensure_block(),
        }
        if visible is not None:
            record["_visible"] = visible
        self.records.append(record)
        return record

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        start = self._offset()
        values = {name.lower(): value or "" for name, value in attrs}
        if tag in self.block_starts:
            self._start_block(tag)
        navigation = tag == "img" and "/buttons/" in values.get("src", "").lower()
        element = self._add(
            "element", tag, tag, byte_start=start,
            disposition="evidence-only" if navigation else "represented",
            reason="navigation-image" if navigation else None,
            role="image-alternative" if tag == "img" and not navigation else None,
            visible=values.get("alt", "") if tag == "img" and not navigation else None,
        )
        if tag in self.block_starts:
            element["semantic_role"] = "block-boundary"
        for index, (name, value) in enumerate(attrs, start=1):
            entry = self._add(
                "attribute", name.lower(), value or "", byte_start=start,
                disposition="evidence-only" if navigation else "represented",
                reason="navigation-image-attribute" if navigation else None,
                role="image-alternative" if tag == "img" and name.lower() == "alt" and not navigation else None,
            )
            entry["source_anchor"] = f"{self.member}:byte-{start}:attribute-{index}"
        if tag in self.close_before:
            self.current_block = None
        elif tag == self.alternative_break and any(item.get("semantic_role") == "alternative-marker" and item.get("_block") == self.current_block for item in self.records):
            self.current_block = None
        if tag not in _VOID:
            self.stack.append((tag, values))

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
            self.current_block = None

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if not normalized:
            # HTMLParser emits a literal separator between adjacent inline
            # elements as its own data event.  It is not an accountability
            # observation, but dropping it can merge source words (for
            # example, ``Upon`` + ``Christmas``).  Keep it on the preceding
            # text observation's readable projection while leaving its
            # source value, count, and parser fingerprint unchanged.
            if data == " " and self.records:
                previous = self.records[-1]
                next_source = self.text[self._offset() + 1:]
                next_tag = re.match(r"\s*<([A-Za-z][A-Za-z0-9]*)\b", next_source)
                structural = self.block_starts | self.close_before | {"br", "hr", "img", "p"}
                if (
                    previous["kind"] == "text"
                    and previous.get("_block") == self.current_block
                    and next_tag is not None
                    and next_tag.group(1).lower() not in structural
                ):
                    previous["_visible"] = str(previous.get("_visible", previous["value"])) + data
            return
        red = any(name == "font" and attrs.get("color", "").lower() == "red" for name, attrs in self.stack)
        role = "rubric" if red else None
        if red and any(str(marker).lower() in normalized.lower() for marker in self.profile["alternative_markers"]):
            role = "alternative-marker"
        self._add("text", None, data, byte_start=self._offset(), role=role, visible=data)

    def handle_comment(self, data: str) -> None:
        self._add("text", "comment", data, byte_start=self._offset(),
                  disposition="evidence-only", reason="html-comment-edition-evidence")

    def parse(self) -> tuple[tuple[dict[str, object], ...], Mapping[str, str]]:
        self.feed(self.text)
        self.close()
        return tuple(self.records), self.block_kinds


def _parser_fingerprint(records: tuple[dict[str, object], ...]) -> str:
    evidence = [
        {key: item[key] for key in ("member", "byte_start", "source_order", "kind", "name", "value", "disposition", "reason_code")}
        for item in records
    ]
    return _sha(_canonical(evidence))


def _source_authority_checks(source_manifest: SourceManifest, profile: Mapping[str, object]) -> None:
    authorities = source_manifest.record["authorities"]
    primary = [item for item in authorities if item["role"] == "primary-source"]
    failed_authorities = [item for item in authorities if item["role"] == "failed-acquisition-evidence"]
    members, failed = source_manifest.record["source_members"], source_manifest.record["failed_acquisitions"]
    def identity(item: Mapping[str, object]) -> tuple[object, object, object]:
        return item["path"], item["bytes"], item["sha256"]
    if (len(members) != 25 or sum(int(item["bytes"]) for item in members) != 733674
            or source_manifest.record["source_bundle"]["sha256"] != profile["source_bundle_sha256"]
            or {identity(item) for item in members} != {identity(item) for item in primary}
            or len(failed) != 5 or any(item["http_status"] != 404 for item in failed)
            or {identity(item) for item in failed} != {identity(item) for item in failed_authorities}):
        raise ValueError("BCP source member, bundle, or failed-acquisition authority mismatch")


def _inventory(source_manifest: SourceManifest, profile: Mapping[str, object]) -> tuple[tuple[dict[str, object], ...], Mapping[str, str]]:
    _source_authority_checks(source_manifest, profile)
    raw_root = resolve_repo_path(source_manifest.repository_root, "raw").resolve(strict=True)
    authority_by_path = {
        str(authority["path"]): authority
        for authority in source_manifest.record["authorities"]
        if authority["role"] == "primary-source"
    }
    records: list[dict[str, object]] = []
    block_kinds: dict[str, str] = {}
    for member in source_manifest.record["source_members"]:
        authority = authority_by_path[str(member["path"])]
        source_path = source_manifest.authority_path(str(authority["name"])).resolve(strict=True)
        source_path.relative_to(raw_root)
        parsed, kinds = _RetainedHtml(str(member["logical_name"]), source_path.read_bytes(), profile).parse()
        records.extend(parsed)
        block_kinds.update(kinds)
    result = tuple(records)
    expected = profile["inventory"]
    counts = {kind: sum(item["kind"] == kind for item in result) for kind in ("element", "attribute", "text")}
    if (len(result) != expected["total"] or counts["element"] != expected["elements"]
            or counts["attribute"] != expected["attributes"] or counts["text"] != expected["text"]):
        raise ValueError(f"BCP complete inventory drifted: {counts}, total={len(result)}")
    if _parser_fingerprint(result) != profile["parser"]["observation_fingerprint_sha256"]:
        raise ValueError("BCP HTMLParser behavior fingerprint drifted")
    return result, block_kinds


def _visible_layout(block: Mapping[str, object]) -> tuple[str, list[tuple[int, int, dict[str, object]]]]:
    offset = 0
    layout: list[tuple[int, int, dict[str, object]]] = []
    for item in block["records"]:
        if item["disposition"] != "represented" or not item.get("_visible"):
            continue
        visible = str(item["_visible"])
        layout.append((offset, offset + len(visible), item))
        offset += len(visible)
    return "".join(str(item.get("_visible", "")) for item in block["records"] if item["disposition"] == "represented"), layout


def _standalone_authority(block: Mapping[str, object], speaker_model: Mapping[str, object]) -> Mapping[str, object] | None:
    normalized = str(block["normalized"])
    for authority in speaker_model["standalone_roles"]:
        if normalized in authority["block_forms"]:
            return authority
    return None


def _speaker_turns(block: Mapping[str, object], speaker_model: Mapping[str, object]) -> list[dict[str, object]]:
    visible, _ = _visible_layout(block)
    standalone = _standalone_authority(block, speaker_model)
    if standalone is not None:
        if standalone["utterance"] == "immediately-following-block":
            return []
        label = str(standalone["label_form"])
        start = visible.find(label)
        if start < 0 or not visible[start + len(label):].strip():
            raise ValueError("BCP same-block standalone role lacks its declared nonempty utterance")
        return [{"canonical": str(standalone["canonical"]), "start": start,
                 "end": start + len(label), "label": label}]
    boundaries = frozenset(str(value) for value in speaker_model["preceding_boundaries"] if value != "start")
    candidates: list[dict[str, object]] = []
    for role in speaker_model["inline_roles"]:
        canonical = str(role["canonical"])
        for form in role["forms"]:
            pattern = re.compile(rf"(?<![A-Za-z]){re.escape(str(form))}")
            for match in pattern.finditer(visible):
                prefix = visible[:match.start()].rstrip()
                if not prefix or prefix[-1] in boundaries:
                    candidates.append({"canonical": canonical, "start": match.start(),
                                       "end": match.end(), "label": match.group()})
    ordered = sorted(candidates, key=lambda value: (int(value["start"]), int(value["end"]), str(value["canonical"])))
    for previous, current in zip(ordered, ordered[1:]):
        if int(current["start"]) < int(previous["end"]):
            raise ValueError("BCP declarative speaker labels overlap")
    for number, turn in enumerate(ordered):
        end = int(ordered[number + 1]["start"]) if number + 1 < len(ordered) else len(visible)
        if not visible[int(turn["end"]):end].strip():
            raise ValueError("BCP inline speaker role lacks a nonempty governed utterance")
    return ordered


def _group_blocks(records: tuple[dict[str, object], ...], block_kinds: Mapping[str, str],
                  profile: Mapping[str, object]) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    by_key: dict[str, dict[str, object]] = {}
    calendar = {"xmas.html", "lent.html", "easter.html", "trinity.html", "saints.html"}
    for item in records:
        key = str(item["_block"])
        if key not in by_key:
            block = {"key": key, "member": item["member"], "kind": block_kinds[key], "records": []}
            by_key[key] = block
            blocks.append(block)
        by_key[key]["records"].append(item)
    for block in blocks:
        represented = [item for item in block["records"] if item["disposition"] == "represented"]
        visible = "".join(str(item.get("_visible", "")) for item in represented)
        block["visible"], block["normalized"] = visible, " ".join(visible.split())
        first = next((item for item in represented if item["kind"] == "element" and item["name"] == block["kind"]), None)
        seed = f"{block['member']}\0{block['key']}".encode("utf-8")
        block["xml_id"] = str(first["observation_id"]) if first else f"bcp-block-{_sha(seed)[:24]}"
        names = [item for item in represented if item["kind"] == "attribute" and item["name"] == "name"]
        start_names = [item["name"] for item in represented[:3] if item["kind"] == "element"]
        block["observance"] = block["member"] in calendar and start_names == ["center", "strong", "a"] and bool(names)
        block["anchor_name"] = str(names[0]["value"]) if block["observance"] else None
        block["collect_marker"] = block["member"] in calendar and not block["observance"] and block["normalized"].casefold() == "the collect."
        block["turns"] = _speaker_turns(block, profile["speaker_model"])
        block["alternative"] = any(item["semantic_role"] == "alternative-marker" for item in represented)
    for index, block in enumerate(blocks):
        authority = _standalone_authority(block, profile["speaker_model"])
        if authority is None or authority["utterance"] != "immediately-following-block":
            continue
        if index + 1 == len(blocks):
            raise ValueError("BCP standalone role has no following source block")
        following = blocks[index + 1]
        if (following["member"] != block["member"] or not str(following["normalized"]).strip()
                or following["observance"] or following["collect_marker"] or following["alternative"]
                or following.get("consumed_by") is not None
                or _standalone_authority(following, profile["speaker_model"]) is not None):
            raise ValueError("BCP standalone role lacks one eligible immediately following utterance block")
        block["standalone"] = {"canonical": str(authority["canonical"]), "target": following}
        following["consumed_by"] = block
    return blocks


def _append_record(parent: etree._Element, item: Mapping[str, object], *, text: str | None = None) -> None:
    if item["disposition"] != "represented":
        return
    identifier = str(item["observation_id"])
    if item["kind"] == "text":
        node = etree.SubElement(parent, f"{{{_TEI}}}seg", type=str(item["semantic_role"] or "source-text"))
        node.set(_XML_ID, identifier)
        node.text = str(item.get("_visible", item["value"]) if text is None else text)
    elif item["kind"] == "element" and item["name"] == "img":
        node = etree.SubElement(parent, f"{{{_TEI}}}seg", type="drop-cap")
        node.set(_XML_ID, identifier)
        node.text = str(item.get("_visible", ""))
    elif item["kind"] == "element" and item["name"] == "br":
        node = etree.SubElement(parent, f"{{{_TEI}}}lb")
        node.set(_XML_ID, identifier)
    elif item["kind"] == "element" and item["name"] == "hr":
        node = etree.SubElement(parent, f"{{{_TEI}}}milestone", unit="section")
        node.set(_XML_ID, identifier)
    else:
        node = etree.SubElement(parent, f"{{{_TEI}}}anchor")
        node.set(_XML_ID, identifier)


def _render_records(parent: etree._Element, block: Mapping[str, object]) -> None:
    skipped = False
    for item in block["records"]:
        if item["disposition"] != "represented":
            continue
        if not skipped and item["kind"] == "element" and item["observation_id"] == block["xml_id"]:
            skipped = True
            continue
        _append_record(parent, item)


def _append_piece(parent: etree._Element, item: Mapping[str, object], text: str | None,
                  emitted: set[str]) -> None:
    identifier = str(item["observation_id"])
    if identifier not in emitted:
        _append_record(parent, item, text=text)
        emitted.add(identifier)
        return
    if text:
        continuation = etree.SubElement(parent, f"{{{_TEI}}}seg", type="source-continuation", corresp=f"#{identifier}")
        continuation.text = text


def _render_range(parent: etree._Element, block: Mapping[str, object], start: int, end: int,
                  emitted: set[str], *, final: bool = False) -> None:
    cursor = 0
    for item in block["records"]:
        if item["disposition"] != "represented":
            continue
        identifier = str(item["observation_id"])
        if item["kind"] == "element" and identifier == block["xml_id"]:
            continue
        visible = str(item.get("_visible", ""))
        if visible:
            item_start, item_end = cursor, cursor + len(visible)
            piece_start, piece_end = max(start, item_start), min(end, item_end)
            if piece_start < piece_end:
                _append_piece(parent, item, visible[piece_start - item_start:piece_end - item_start], emitted)
            cursor = item_end
        elif start <= cursor < end or final and cursor == end:
            _append_piece(parent, item, None, emitted)


def _render_speaker_sequence(wrapper: etree._Element, block: Mapping[str, object]) -> None:
    turns = list(block["turns"])
    total = len(str(block["visible"]))
    emitted: set[str] = set()
    first_start = int(turns[0]["start"])
    if first_start:
        prelude = etree.SubElement(wrapper, f"{{{_TEI}}}ab", type="source-block")
        _render_range(prelude, block, 0, first_start, emitted)
    for number, turn in enumerate(turns):
        next_start = int(turns[number + 1]["start"]) if number + 1 < len(turns) else total
        speech = etree.SubElement(wrapper, f"{{{_TEI}}}sp", who=f"#bcp-role-{str(turn['canonical']).casefold()}")
        speaker = etree.SubElement(speech, f"{{{_TEI}}}speaker")
        utterance = etree.SubElement(speech, f"{{{_TEI}}}p")
        _render_range(speaker, block, int(turn["start"]), int(turn["end"]), emitted)
        _render_range(utterance, block, int(turn["end"]), next_start, emitted, final=number + 1 == len(turns))
    expected = {
        str(item["observation_id"]) for item in block["records"]
        if item["disposition"] == "represented" and item["observation_id"] != block["xml_id"]
    }
    if emitted != expected:
        raise ValueError("BCP speaker rendering failed complete source anchoring")


def _render_cross_block_speaker(block: Mapping[str, object]) -> etree._Element:
    relationship = block["standalone"]
    target = relationship["target"]
    wrapper = _tei("div", type="source-block")
    wrapper.set(_XML_ID, str(block["xml_id"]))
    speech = etree.SubElement(wrapper, f"{{{_TEI}}}sp", who=f"#bcp-role-{str(relationship['canonical']).casefold()}")
    speaker = etree.SubElement(speech, f"{{{_TEI}}}speaker")
    label_emitted: set[str] = set()
    _render_range(speaker, block, 0, len(str(block["visible"])), label_emitted, final=True)
    expected_label = {
        str(item["observation_id"]) for item in block["records"]
        if item["disposition"] == "represented" and item["observation_id"] != block["xml_id"]
    }
    if label_emitted != expected_label or not "".join(speaker.itertext()).strip():
        raise ValueError("BCP standalone speaker label lost source anchoring")
    target_turns = list(target["turns"])
    first_turn = int(target_turns[0]["start"]) if target_turns else len(str(target["visible"]))
    utterance = etree.SubElement(speech, f"{{{_TEI}}}p")
    utterance.set(_XML_ID, str(target["xml_id"]))
    target_emitted: set[str] = set()
    _render_range(utterance, target, 0, first_turn, target_emitted, final=not target_turns)
    if not "".join(utterance.itertext()).strip():
        raise ValueError("BCP cross-block speaker role has an empty governed utterance")
    total = len(str(target["visible"]))
    for number, turn in enumerate(target_turns):
        next_start = int(target_turns[number + 1]["start"]) if number + 1 < len(target_turns) else total
        nested = etree.SubElement(wrapper, f"{{{_TEI}}}sp", who=f"#bcp-role-{str(turn['canonical']).casefold()}")
        nested_label = etree.SubElement(nested, f"{{{_TEI}}}speaker")
        nested_utterance = etree.SubElement(nested, f"{{{_TEI}}}p")
        _render_range(nested_label, target, int(turn["start"]), int(turn["end"]), target_emitted)
        _render_range(nested_utterance, target, int(turn["end"]), next_start, target_emitted,
                      final=number + 1 == len(target_turns))
    expected_target = {
        str(item["observation_id"]) for item in target["records"]
        if item["disposition"] == "represented" and item["observation_id"] != target["xml_id"]
    }
    if target_emitted != expected_target:
        raise ValueError("BCP cross-block utterance failed complete source anchoring")
    return wrapper


def _render_block(block: Mapping[str, object]) -> etree._Element:
    if block.get("standalone") is not None:
        return _render_cross_block_speaker(block)
    wrapper = _tei("div", type="alternative-marker" if block["alternative"] else "source-block")
    wrapper.set(_XML_ID, str(block["xml_id"]))
    if block["turns"]:
        _render_speaker_sequence(wrapper, block)
        return wrapper
    kind = str(block["kind"])
    if kind == "hr":
        node = _tei("ab", type="section-break")
    elif kind == "center":
        node = _tei("ab", type="source-block", rend="center")
    elif kind in {"h2", "h3"}:
        node = _tei("ab", type="heading", subtype=kind)
    else:
        node = _tei("ab", type="source-block")
    _render_records(node, block)
    wrapper.append(node)
    return wrapper


def _alternative_targets(blocks: list[dict[str, object]]) -> Mapping[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for index, block in enumerate(blocks):
        if not block["alternative"]:
            continue
        targets: list[str] = []
        for following in blocks[index + 1 :]:
            if (following["member"] != block["member"] or following["alternative"]
                    or following["observance"] or following["collect_marker"]):
                break
            if following["normalized"]:
                targets.append(str(following["xml_id"]))
            if following["kind"] == "flow" and following["normalized"]:
                break
        if not targets:
            raise ValueError("BCP alternative marker has no complete following reading block")
        result[str(block["xml_id"])] = tuple(targets)
    return result


def _header(profile: Mapping[str, object], bundle_sha: str) -> etree._Element:
    header = _tei("teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_TEI}}}title").text = str(profile["tei_header"]["title"])
    etree.SubElement(title_stmt, f"{{{_TEI}}}author").text = str(profile["tei_header"]["author"])
    publication = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{_TEI}}}publisher").text = "Open Christian Data"
    availability = etree.SubElement(publication, f"{{{_TEI}}}availability", status=str(profile["tei_header"]["availability_status"]))
    etree.SubElement(availability, f"{{{_TEI}}}p").text = str(profile["tei_header"]["rights_statement"])
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{_TEI}}}bibl")
    etree.SubElement(bibl, f"{{{_TEI}}}title").text = str(profile["tei_header"]["title"])
    etree.SubElement(bibl, f"{{{_TEI}}}ref", target=str(profile["tei_header"]["source_url"])).text = "Retained source provider"
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="SHA-256").text = bundle_sha
    encoding = etree.SubElement(header, f"{{{_TEI}}}encodingDesc")
    etree.SubElement(etree.SubElement(encoding, f"{{{_TEI}}}projectDesc"), f"{{{_TEI}}}p").text = "Readable source-derived liturgical reconstruction for independent fidelity review; not human acceptance."
    revision = etree.SubElement(header, f"{{{_TEI}}}revisionDesc")
    etree.SubElement(revision, f"{{{_TEI}}}change", status="candidate").text = "Deterministic nonaccepted reconstruction."
    return header


def _build_tei(source_manifest: SourceManifest, profile: Mapping[str, object], blocks: list[dict[str, object]]) -> bytes:
    root = _tei("TEI")
    root.append(_header(profile, str(source_manifest.record["source_bundle"]["sha256"])))
    body = etree.SubElement(etree.SubElement(root, f"{{{_TEI}}}text"), f"{{{_TEI}}}body")
    members = {str(item["logical_name"]): item for item in source_manifest.record["source_members"]}
    alternatives = _alternative_targets(blocks)
    for member_name in members:
        member_blocks = [block for block in blocks if block["member"] == member_name]
        metadata = members[member_name]
        member_div = etree.SubElement(body, f"{{{_TEI}}}div", type=str(metadata["kind"]), n=member_name)
        etree.SubElement(member_div, f"{{{_TEI}}}head").text = str(metadata["title"])
        current_observance: etree._Element | None = None
        current_collect: etree._Element | None = None
        for block in member_blocks:
            if block.get("consumed_by") is not None:
                continue
            if block["observance"]:
                current_collect = None
                current_observance = etree.SubElement(member_div, f"{{{_TEI}}}div", type="observance", n=str(block["anchor_name"]))
                current_observance.set(_XML_ID, str(block["xml_id"]))
                _render_records(etree.SubElement(current_observance, f"{{{_TEI}}}head"), block)
                continue
            if block["collect_marker"]:
                if current_observance is None:
                    raise ValueError("BCP calendar collect lacks a source-derived observance")
                current_collect = etree.SubElement(current_observance, f"{{{_TEI}}}div", type="collect")
                current_collect.set(_XML_ID, str(block["xml_id"]))
                _render_records(etree.SubElement(current_collect, f"{{{_TEI}}}head"), block)
                continue
            target = current_collect if current_collect is not None else current_observance if current_observance is not None else member_div
            rendered = _render_block(block)
            if block["xml_id"] in alternatives:
                rendered.set("corresp", " ".join(f"#{item}" for item in alternatives[str(block["xml_id"])]))
            target.append(rendered)
            if current_collect is not None and block["kind"] == "flow" and block["normalized"]:
                current_collect = None
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("contract") != "ocd-bcp-1662-reconstruction-profile-v3" or profile.get("profile_id") != _PROFILE_ID:
        raise ValueError("BCP reconstruction profile identity mismatch")
    if platform.python_implementation() != profile["parser"]["implementation_family"]:
        raise ValueError("BCP parser implementation family mismatch")
    records, block_kinds = _inventory(source_manifest, profile)
    blocks = _group_blocks(records, block_kinds, profile)
    tei_bytes = _build_tei(source_manifest, profile, blocks)
    clean_records = [{key: value for key, value in item.items() if not key.startswith("_")} for item in records]
    counts = {kind: sum(item["kind"] == kind for item in records) for kind in ("element", "attribute", "text")}
    derived_alternatives = sum(block["alternative"] for block in blocks)
    broad_recall = sum(item["kind"] == "text" and item["name"] is None and _LEGACY_ALT.search(str(item["value"])) is not None for item in records)
    accountability = {
        "contract": "ocd-bcp-1662-source-accountability-v1", "schema": "bcp-1662.source-accountability.schema.json",
        "profile_id": _PROFILE_ID, "parser": dict(profile["parser"]),
        "source_bundle": dict(source_manifest.record["source_bundle"]),
        "observation_counts": {"total": len(records), "elements": counts["element"], "attributes": counts["attribute"], "text": counts["text"]},
        "image_alt_counts": {
            "text_bearing": sum(item["kind"] == "element" and item["semantic_role"] == "image-alternative" for item in records),
            "navigation": sum(item["reason_code"] == "navigation-image" for item in records),
        },
        "alternative_counts": {"genuine": derived_alternatives, "legacy_recall": broad_recall},
        "comment_count": sum(item["reason_code"] == "html-comment-edition-evidence" for item in records),
        "document_count": len(source_manifest.record["source_members"]),
        "omitted_observation_count": 0, "duplicate_observation_count": 0, "crosswalk": clean_records,
    }
    authorities = {str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")} for item in source_manifest.record["authorities"]}
    provenance = {
        "contract": "ocd-bcp-1662-candidate-provenance-v1", "status": "nonaccepted",
        "scope": "25 retained HTML members; partial expression only", "source_bundle": dict(source_manifest.record["source_bundle"]),
        "authorities": authorities,
        "identity": {"work": "The Book of Common Prayer (1662)", "author": "Church of England", "provider_claims": ["Lesley Holwell", "Lynda M. Howell", "CVW holwell"], "provider_identity_status": "unresolved"},
        "rights": {"source_config_claim": "public-domain", "status": "human-review-required", "publication_authorized": False},
        "failed_acquisitions": [dict(item) for item in source_manifest.record["failed_acquisitions"]],
    }
    unresolved = [
        {"id": "bcp-expression-scope", "question": "Which print or later transcription expression do the retained members collectively represent?", "consequence": "candidate remains explicitly partial", "escalation": "human-review"},
        {"id": "bcp-failed-acquisitions", "question": "Can the five retained HTTP 404 acquisitions be replaced by source-authoritative text?", "consequence": "five requested sections remain absent", "escalation": "human-review"},
        {"id": "bcp-provider-identity", "question": "Are Lesley Holwell, Lynda M. Howell, and CVW holwell the same provider identity?", "consequence": "provider attribution remains unresolved", "escalation": "human-review"},
        {"id": "bcp-rights-and-publication", "question": "Does the source-config public-domain claim suffice for acceptance and publication?", "consequence": "publication remains unauthorized", "escalation": "human-review"},
        {"id": "bcp-alternative-grouping", "question": "Do the source-derived alternative markers govern exactly the linked following block ranges?", "consequence": "relationships remain reviewable and nonaccepted", "escalation": "human-review"},
    ]
    readme = (
        "# BCP 1662 retained-source candidate\n\n"
        "This deterministic, nonaccepted candidate presents readable source-derived service, observance, collect, block, rubric, speaker, and alternative structure while retaining a complete observation crosswalk. Drop-cap image alternatives are joined to their words; navigation images and comments remain evidence-only.\n\n"
        "The retained files are a partial transcription, not proof of a complete 1662 expression. Five acquisitions returned HTTP 404. Provider identity, rights, alternative scope, and publication require human review.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": tei_bytes, "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
