"""Exact accepted New Advent article-text boundary for private offline release.

The private transform inventory retains each complete accepted row in compressed
form. The inverse re-derives every public row before returning checker input.
Neither historical wording nor private source evidence is rewritten in TEI.
"""

from __future__ import annotations

import base64
from hashlib import sha256
import json
import re
import zlib
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes
from .public_allowlist import _scan


ITEM = "catholic-encyclopedia-vol01--catholic-encyclopedia-vol01-retained-electronic"
CONTRACT = "ocd-public-catholic-encyclopedia-cited-article-text-v1"
ACCEPTANCE_SHA256 = "21696e69bc9caae01cc2e9f74798b1d19aa72fcb2e9a8f4c42b6508920d1de0d"
MASTER_SHA256 = "5d9bd4892220a40418c5c04cf9421f6a1e40fc8232da06df2dc5796ad460fa33"
SOURCE_SET_SHA256 = "159e69948931054b0496e4a4b79a6f22d497a65d6b460a09520d3ca007cc353a"
PRIVATE_COUNT = 11681
PUBLIC_COUNT = 11629
HELD_ARTICLE_POSITIONS = {51, 52, 53}
HELD_ARTICLE_URLS = {
    51: "https://www.newadvent.org/cathen/00001a.htm",
    52: "https://www.newadvent.org/cathen/00002a.htm",
    53: "https://www.newadvent.org/cathen/00005a.htm",
}
ARTICLE_URL = re.compile(r"https://www\.newadvent\.org/cathen/[0-9]{5}[a-z]\.htm\Z")
APA_YEAR = re.compile(r"APA citation\.\s*.*?\((1907|1908|1909|1910|1911|1912|1914|1922)\)\.")
MAX_PRIVATE_ROW_BYTES = 64 * 1024 * 1024
_BLOCKS = {"heading", "paragraph", "source-block", "list-item", "table-row", "quotation-block", "figure-description"}
_SEMANTIC_STYLES = {"italic", "bold", "small-caps", "smallcaps", "underline", "superscript", "subscript"}


def _hash(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _fail(condition: bool, message: str) -> None:
    if not condition:
        raise PipelineError("Catholic Encyclopedia public boundary: " + message)


def _source_fields(node: dict[str, Any]) -> dict[str, Any]:
    attrs = node.get("attributes")
    _fail(isinstance(attrs, dict), "native attributes missing")
    source = attrs.get("source_annotations")
    _fail(isinstance(source, str), "native source annotations missing")
    try:
        parsed = json.loads(source)
    except json.JSONDecodeError as exc:
        raise PipelineError("Catholic Encyclopedia native annotations invalid") from exc
    _fail(isinstance(parsed, dict) and isinstance(parsed.get("fields"), dict), "native source fields missing")
    return parsed["fields"]


def _literal(node: dict[str, Any]) -> str:
    if node.get("kind") == "text":
        return node["text"]
    return "".join(_literal(child) for child in node.get("content", []))


def _class(node: dict[str, Any]) -> str | None:
    fields = _source_fields(node)
    rend = fields.get("rend", "")
    if not isinstance(rend, str) or not rend.startswith("html-attributes:"):
        return None
    try:
        value = json.loads(rend.removeprefix("html-attributes:"))
    except json.JSONDecodeError as exc:
        raise PipelineError("Catholic Encyclopedia source HTML attributes invalid") from exc
    _fail(isinstance(value, dict), "source HTML attributes are not an object")
    return value.get("class")


def _id(node: dict[str, Any]) -> str | None:
    fields = _source_fields(node)
    rend = fields.get("rend", "")
    if not isinstance(rend, str) or not rend.startswith("html-attributes:"):
        return None
    value = json.loads(rend.removeprefix("html-attributes:"))
    _fail(isinstance(value, dict), "source HTML attributes are not an object")
    return value.get("id")


def _plain(node: dict[str, Any]) -> str:
    chunks: list[str] = []
    def walk(part: dict[str, Any]) -> None:
        if part["kind"] == "text":
            chunks.append(part["text"])
            return
        if part["kind"] in _BLOCKS:
            chunks.append("\n")
        for child in part["content"]:
            walk(child)
        if part["kind"] in _BLOCKS | {"line-break"}:
            chunks.append("\n")
    walk(node)
    return "\n".join(" ".join(line.split()) for line in "".join(chunks).split("\n") if line.strip())


def _clean(node: dict[str, Any], omitted: frozenset[int] = frozenset(),
           replacements: dict[int, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    if replacements is not None and id(node) in replacements:
        return replacements[id(node)]
    if id(node) in omitted:
        return None
    kind = node.get("kind")
    if kind == "text":
        text = node.get("text")
        _fail(isinstance(text, str), "native text leaf invalid")
        return {"kind": "text", "text": text} if text else None
    _fail(isinstance(kind, str) and isinstance(node.get("content"), list), "native node invalid")
    # Embedded source pixels and their site-derived alternative descriptions are
    # reserved together; historical article words outside the figure remain.
    if kind in {"figure", "image-reference"}:
        return None
    attrs = node.get("attributes")
    _fail(isinstance(attrs, dict), "native node attributes invalid")
    clean_attrs: dict[str, str] = {}
    if isinstance(attrs.get("language"), str):
        clean_attrs["language"] = attrs["language"]
    if kind == "emphasis" and attrs.get("style") in _SEMANTIC_STYLES:
        clean_attrs["style"] = attrs["style"]
    if kind == "list" and attrs.get("type") in {"ordered", "unordered"}:
        clean_attrs["type"] = attrs["type"]
    if kind == "table-cell":
        for field in ("source_column_count", "source_row_count"):
            if isinstance(attrs.get(field), str) and attrs[field].isdigit():
                clean_attrs[field] = attrs[field]
    content = [clean for child in node["content"]
               if (clean := _clean(child, omitted, replacements)) is not None]
    if not content:
        return None
    return {"kind": kind, "attributes": clean_attrs, "content": content}


def _publication_credits(pub: dict[str, Any], sequence: int) -> list[dict[str, Any]]:
    _fail(_class(pub) == "pub", f"{sequence}: article-local publication block missing")
    sections = pub.get("content")
    _fail(isinstance(sections, list) and len(sections) == 1, f"{sequence}: publication section shape differs")
    section = sections[0]
    _fail(section.get("kind") == "division", f"{sequence}: publication division differs")
    parts = section.get("content", [])
    _fail(parts and _literal(parts[0]).strip() == "About this page", f"{sequence}: publication heading differs")
    credits = []
    contact = 0
    for part in parts[1:]:
        literal = _literal(part).strip()
        if not literal:
            continue
        if literal.startswith("Contact information."):
            contact += 1
            continue
        _fail(literal.startswith(("APA citation.", "MLA citation.", "Transcription.",
                                  "Ecclesiastical approbation.")),
              f"{sequence}: unexpected article-local publication prose")
        cleaned = _clean(part)
        if cleaned is not None:
            credits.append(cleaned)
    _fail(contact == 1, f"{sequence}: modern Contact block differs")
    apa = [text for item in credits if (text := _literal(item)).strip().startswith("APA citation.")]
    _fail(len(apa) == 1 and len(APA_YEAR.findall(apa[0])) == 1,
          f"{sequence}: unique cited historical publication year missing")
    return credits


def _class_paths(node: dict[str, Any], value: str) -> list[tuple[int, ...]]:
    found: list[tuple[int, ...]] = []
    def walk(part: dict[str, Any], path: tuple[int, ...]) -> None:
        if part.get("kind") == "division" and _class(part) == value:
            found.append(path)
        for index, child in enumerate(part.get("content", [])):
            if child.get("kind") != "text":
                walk(child, path + (index,))
    walk(node, ())
    return found


def _at(node: dict[str, Any], path: tuple[int, ...]) -> dict[str, Any]:
    for index in path:
        node = node["content"][index]
    return node


def _article(row: dict[str, Any]) -> dict[str, Any]:
    seq = row.get("sequence")
    _fail(type(seq) is int and 1 <= seq <= PRIVATE_COUNT, "source sequence invalid")
    _fail(row.get("unit_kind") == "encyclopedia-entry", f"{seq}: article kind differs")
    provenance = row.get("provenance")
    _fail(isinstance(provenance, dict) and ARTICLE_URL.fullmatch(provenance.get("source_url", "")) is not None,
          f"{seq}: accepted article URL differs")
    structure = row.get("structure")
    _fail(isinstance(structure, list) and len(structure) == 1, f"{seq}: native root differs")
    original_root = structure[0]
    _fail(original_root.get("kind") == "division" and len(original_root.get("content", [])) == 2,
          f"{seq}: main/footer envelope differs")
    main, footer = original_root["content"]
    _fail(_id(main) == "springfield2" and _id(footer) == "ogdenville",
          f"{seq}: retained source wrapper boundary differs")
    main_content = main.get("content", [])
    h1_sections = [node for node in main_content if node.get("kind") == "division"
                   and node.get("attributes", {}).get("subtype") == "h1"]
    _fail(len(h1_sections) == 1, f"{seq}: one historical article section required")
    pub_paths = _class_paths(h1_sections[0], "pub")
    _fail(len(pub_paths) == 1 and len(pub_paths[0]) >= 2,
          f"{seq}: one article-local publication block required")
    pub = _at(h1_sections[0], pub_paths[0])
    credits = _publication_credits(pub, seq)
    content = []
    donors = [child for child in h1_sections[0]["content"]
              if _literal(child).strip().startswith("Please help support the mission of New Advent")]
    _fail(len(donors) == (0 if seq == 1181 else 1), f"{seq}: source donation boundary differs")
    omitted = frozenset(id(donor) for donor in donors)
    replacements = {id(pub): {"kind": "division", "attributes": {}, "content": credits}}
    for node in main_content:
        if node is h1_sections[0]:
            cleaned = _clean(node, omitted, replacements)
            _fail(cleaned is not None and cleaned["content"], f"{seq}: article body became empty")
            content.append(cleaned)
        else:
            cleaned = _clean(node, omitted, replacements)
            if cleaned is not None:
                content.append(cleaned)
    _fail(content and credits, f"{seq}: public historical text or credits empty")
    public_root = {"kind": "division", "attributes": {}, "content": content}
    public_text = _plain(public_root)
    _fail(public_text and not any(value in public_text for value in (
        "Please help support the mission of New Advent", "Contact information.",
        "Copyright © 2026 by New Advent LLC", "The editor of New Advent is Kevin Knight")),
        f"{seq}: site text remains in public article")
    public = {**row, "text": public_text, "structure": [public_root],
              "provenance": {key: value for key, value in provenance.items() if key != "source_location"}}
    _fail(not _scan(public, f"Catholic article {seq}"), f"{seq}: private marker remains")
    return public


def _status(row: dict[str, Any], expected_sequence: int) -> bool:
    _fail(row.get("sequence") == expected_sequence, f"{expected_sequence}: source order differs")
    if expected_sequence <= 48:
        _fail(row.get("unit_kind") == "encyclopedia-index", f"{expected_sequence}: index kind differs")
        return False
    if expected_sequence == PRIVATE_COUNT:
        _fail(row.get("unit_kind") == "unavailable-source-register", "failure register differs")
        return False
    if expected_sequence in HELD_ARTICLE_POSITIONS:
        _fail(row.get("unit_kind") == "encyclopedia-entry" and
              row.get("provenance", {}).get("source_url") == HELD_ARTICLE_URLS[expected_sequence],
              f"{expected_sequence}: held non-citation page differs")
        return False
    return True


def _packed(row: dict[str, Any], raw: bytes | None = None) -> str:
    if raw is None:
        raw = canonical_bytes(row)
    _fail(len(raw) <= MAX_PRIVATE_ROW_BYTES, "accepted native row exceeds bounded inverse size")
    return base64.b64encode(zlib.compress(raw, level=1)).decode("ascii")


def _unpack(value: str) -> dict[str, Any]:
    _fail(isinstance(value, str), "private inverse payload missing")
    try:
        compressed = base64.b64decode(value, validate=True)
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(compressed, MAX_PRIVATE_ROW_BYTES + 1)
        _fail(decompressor.eof and not decompressor.unconsumed_tail and not decompressor.unused_data
              and len(raw) <= MAX_PRIVATE_ROW_BYTES, "private inverse payload bound differs")
        row = json.loads(raw)
    except (ValueError, zlib.error, json.JSONDecodeError) as exc:
        raise PipelineError("Catholic Encyclopedia private inverse payload invalid") from exc
    _fail(isinstance(row, dict), "private inverse row must be an object")
    return row


def _authority(acceptance_sha256: str | None, master_sha256: str | None) -> None:
    _fail(acceptance_sha256 == ACCEPTANCE_SHA256 and master_sha256 == MASTER_SHA256,
          "exact accepted authority differs")


def public_rows(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _authority(acceptance_sha256, master_sha256)
    _fail(len(rows) == PRIVATE_COUNT, "complete accepted native row denominator differs")
    public: list[dict[str, Any]] = []
    entries = []
    for sequence, original in enumerate(rows, 1):
        included = _status(original, sequence)
        result = _article(original) if included else None
        original_bytes = canonical_bytes(original)
        entries.append({"sequence": sequence, "original_sha256": sha256(original_bytes).hexdigest(),
                        "original_zlib_b64": _packed(original, original_bytes),
                        "public_sha256": _hash(result) if result is not None else None})
        if result is not None:
            public.append(result)
    _fail(len(public) == PUBLIC_COUNT, "cited historical article count differs")
    return public, {"contract": CONTRACT, "item_id": ITEM,
                    "acceptance_sha256": ACCEPTANCE_SHA256, "master_sha256": MASTER_SHA256,
                    "source_member_set_sha256": SOURCE_SET_SHA256,
                    "private_row_count": PRIVATE_COUNT, "public_row_count": PUBLIC_COUNT,
                    "entries": entries}


def restore_private_rows(rows: list[dict[str, Any]], artifact: dict[str, Any], *,
                         acceptance_sha256: str | None, master_sha256: str | None) -> list[dict[str, Any]]:
    _authority(acceptance_sha256, master_sha256)
    _fail(isinstance(artifact, dict) and set(artifact) == {"contract", "item_id", "acceptance_sha256",
        "master_sha256", "source_member_set_sha256", "private_row_count", "public_row_count", "entries"},
        "inverse contract fields differ")
    _fail(artifact["contract"] == CONTRACT and artifact["item_id"] == ITEM
          and artifact["acceptance_sha256"] == ACCEPTANCE_SHA256
          and artifact["master_sha256"] == MASTER_SHA256
          and artifact["source_member_set_sha256"] == SOURCE_SET_SHA256
          and artifact["private_row_count"] == PRIVATE_COUNT
          and artifact["public_row_count"] == PUBLIC_COUNT
          and isinstance(artifact["entries"], list) and len(artifact["entries"]) == PRIVATE_COUNT
          and isinstance(rows, list) and len(rows) == PUBLIC_COUNT, "inverse authority/count differs")
    original_rows: list[dict[str, Any]] = []
    cursor = 0
    for sequence, entry in enumerate(artifact["entries"], 1):
        _fail(isinstance(entry, dict) and set(entry) == {"sequence", "original_sha256",
            "original_zlib_b64", "public_sha256"} and entry["sequence"] == sequence,
            f"{sequence}: inverse inventory differs")
        original = _unpack(entry["original_zlib_b64"])
        _fail(_hash(original) == entry["original_sha256"], f"{sequence}: original inverse digest differs")
        if _status(original, sequence):
            expected = _article(original)
            _fail(cursor < len(rows) and entry["public_sha256"] == _hash(expected)
                  and rows[cursor] == expected,
                  f"{sequence}: public article differs from accepted transform")
            cursor += 1
        else:
            _fail(entry["public_sha256"] is None, f"{sequence}: held source page entered public inventory")
        original_rows.append(original)
    _fail(cursor == PUBLIC_COUNT, "public historical article inventory incomplete")
    return original_rows
