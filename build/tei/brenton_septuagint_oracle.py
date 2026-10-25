"""Independent source-to-readable-TEI check for the retained Brenton USFM set."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import io_path


TEI = "{http://www.tei-c.org/ns/1.0}"
POINTER = "source-usfm:eng-Brenton/"
MARKER = re.compile(r"\\([+]?[A-Za-z0-9_-]+)(\*)?")
ROLES = {
    "f": ("note", "footnote"),
    "x": ("note", "cross-reference"),
    "add": ("supplied", None),
    "sc": ("hi", "small-caps"),
    "it": ("hi", "italic"),
    "+it": ("hi", "italic"),
    "vp": ("seg", "source-verse-number"),
}
LINE_TYPES = {
    "p": "paragraph-break",
    "nb": "continuation-paragraph",
    "b": "stanza-break",
    "im": "introduction-line",
    "ip": "introduction-paragraph",
    "ib": "introduction-break",
}
PARATEXT = {"FRT", "INT", "BAK", "OTH", "XXA", "XXB", "XXC"}


def _visible_text(node: etree._Element) -> str:
    result = node.text or ""
    for child in node:
        if child.tag != TEI + "note" or child.get("type") != "source-usfm-raw":
            result += _visible_text(child)
        result += child.tail or ""
    return result


def _semantic_descendants(node: etree._Element) -> list[etree._Element]:
    return [
        child for child in node.iterdescendants()
        if child.tag != TEI + "note" or child.get("type") != "source-usfm-raw"
    ]


def verify(repository_root: Path, candidate_path: Path) -> dict[str, object]:
    """Derive expectations from the sidecar and actual members, then inspect TEI."""
    sidecar = repository_root / (
        "library/works/brenton-septuagint/forms/brenton-septuagint-retained-en/"
        "editions/brenton-septuagint-electronic/source-member-set.json"
    )
    declaration = json.loads(io_path(sidecar).read_text(encoding="utf-8"))
    members = declaration["members"]
    if len(members) != 60 or [m["position"] for m in members] != list(range(1, 61)):
        raise ValueError("Brenton declaration is not a 60-member ordered set")
    numeric_order = [int(Path(member["path"]).name.split("-", 1)[0]) for member in members]
    if numeric_order != sorted(numeric_order):
        raise ValueError("Brenton declaration differs from numeric source order")
    xml = etree.parse(str(candidate_path), etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    body = xml.find("./" + TEI + "text/" + TEI + "body")
    if body is None:
        raise ValueError("candidate has no TEI body")
    divisions = list(body)
    if len(divisions) != len(members):
        raise ValueError("candidate member count differs from retained set")
    pointers: dict[str, etree._Element] = {}
    for node in body.iter():
        pointer = node.get("corresp")
        if pointer and pointer.startswith(POINTER) and not pointer.endswith(":label"):
            if pointer in pointers:
                raise ValueError(f"duplicate source pointer: {pointer}")
            pointers[pointer] = node
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for member, division in zip(members, divisions, strict=True):
        path = resolve_repo_path(repository_root, member["path"])
        source = io_path(path).read_bytes()
        if len(source) != member["bytes"] or hashlib.sha256(source).hexdigest() != member["sha256"]:
            raise ValueError(f"retained member differs from declaration: {path.name}")
        lines = source.decode("utf-8").split("\n")
        first = lines[0].split(maxsplit=1)[0]
        if first != "\\id":
            raise ValueError(f"member has no initial ID: {path.name}")
        member_id = lines[0].split(maxsplit=2)[1]
        member_type = "paratext" if member_id in PARATEXT else "book"
        if division.tag != TEI + "div" or division.get("n") != member_id or division.get("type") != member_type:
            raise ValueError(f"member order or identity differs: {path.name}")
        chapter: str | None = None
        expected_pointers: list[str] = []
        for line_number, raw in enumerate(lines, 1):
            marker, separator, payload = raw[1:].partition(" ")
            if not raw.startswith("\\") or not marker:
                raise ValueError(f"invalid source marker at {path.name}:{line_number}")
            pointer = f"{POINTER}{path.name}#line={line_number}"
            expected_pointers.append(pointer)
            node = pointers.get(pointer)
            if node is None:
                raise ValueError(f"missing source line: {pointer}")
            seen.add(pointer)
            raw_notes = [c for c in node if c.tag == TEI + "note" and c.get("type") == "source-usfm-raw"]
            if len(raw_notes) != 1 or raw_notes[0].text != raw:
                raise ValueError(f"raw carrier differs: {pointer}")
            if marker == "id":
                if node is not division:
                    raise ValueError(f"member boundary differs: {pointer}")
                continue
            if marker == "c":
                chapter = payload.split()[0]
                if node.tag != TEI + "div" or node.get("type") != "chapter" or node.get("n") != chapter or node.getparent() is not division:
                    raise ValueError(f"chapter boundary differs: {pointer}")
                counts["chapters"] += 1
                continue
            owner = node
            while owner is not None and owner.tag != TEI + "div":
                owner = owner.getparent()
            if owner is None:
                raise ValueError(f"line has no division owner: {pointer}")
            if chapter is None and owner is not division:
                raise ValueError(f"prechapter line has wrong owner: {pointer}")
            if chapter is not None and (owner.get("type") != "chapter" or owner.get("n") != chapter or owner.getparent() is not division):
                raise ValueError(f"chapter line has wrong owner: {pointer}")
            if marker == "v":
                verse, _, payload = payload.partition(" ")
                if node.tag != TEI + "ab" or node.get("type") != "verse" or node.get("n") != verse:
                    raise ValueError(f"verse role or number differs: {pointer}")
                counts["verses"] += 1
            elif marker == "tr":
                if node.tag != TEI + "cell" or node.get("role") != "label" or node.getparent().tag != TEI + "row":
                    raise ValueError(f"table row role differs: {pointer}")
                counts["table_rows"] += 1
            elif marker in {"tc1", "tc2"}:
                if node.tag != TEI + "cell" or node.get("n") != marker[-1] or node.getparent().tag != TEI + "row":
                    raise ValueError(f"table cell role differs: {pointer}")
                counts["table_cells"] += 1
            elif (node.tag != TEI + "ab" or node.get("n") != marker
                  or node.get("type") != LINE_TYPES.get(marker, f"usfm-{marker}")):
                raise ValueError(f"source line role differs: {pointer}")
            if marker not in {"tr", "b", "ib"}:
                expected_text = MARKER.sub("", payload)
                if expected_text.strip() or _visible_text(node).strip():
                    if _visible_text(node) != expected_text:
                        raise ValueError(f"readable text differs: {pointer}")
            expected_roles = Counter(token for token, closing in MARKER.findall(payload) if not closing and token in ROLES)
            actual_roles = Counter()
            actual_role_order: list[str] = []
            for child in _semantic_descendants(node):
                for token, (tag, value) in ROLES.items():
                    if child.tag == TEI + tag and (value is None or child.get("type") == value or child.get("rend") == value):
                        role = token if token != "+it" else "it"
                        actual_roles[role] += 1
                        actual_role_order.append(role)
                        break
            expected_roles["it"] += expected_roles.pop("+it", 0)
            if expected_roles != actual_roles:
                raise ValueError(f"inline roles differ: {pointer}: {expected_roles} != {actual_roles}")
            expected_role_order = [
                "it" if token == "+it" else token
                for token, closing in MARKER.findall(payload)
                if not closing and token in ROLES
            ]
            if expected_role_order != actual_role_order:
                raise ValueError(f"inline role order differs: {pointer}")
            counts["source_lines"] += 1
        actual_pointers = [
            node.get("corresp") for node in division.iter()
            if node.get("corresp", "").startswith(POINTER)
            and not node.get("corresp", "").endswith(":label")
        ]
        if actual_pointers != expected_pointers:
            raise ValueError(f"source line order differs: {path.name}")
    if seen != set(pointers):
        raise ValueError("candidate contains unaccounted source pointers")
    return {"member_count": len(members), "source_pointers": len(seen), **dict(counts)}
