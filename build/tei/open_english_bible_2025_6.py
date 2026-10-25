"""Faithful one-root TEI reconstruction of the two retained OEB 2025.6 variants."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Mapping
from zipfile import ZipFile

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
TOKEN = re.compile(r"\\(?P<name>\+?[A-Za-z][A-Za-z0-9]*\*?)")
LINE = re.compile(r"^\\(?P<marker>[A-Za-z][A-Za-z0-9]*)(?:[ \t](?P<payload>.*))?$")
HEADS = frozenset({"id", "ide", "h", "toc1", "toc2", "toc3", "mt", "mt1", "mt2", "mt3", "s", "s2", "ms", "d"})
SECTION_HEADS = frozenset({"s", "s2", "ms", "d"})
BLOCKS = frozenset({"p", "m", "q", "q1", "q2", "q3", "pi"})
BREAKS = frozenset({"b", "nb"})
LINE_MARKERS = HEADS | BLOCKS | BREAKS | {"c", "v", "periph", "rem"}
INLINE = frozenset({"em", "em*", "f", "f*", "fr", "ft", "nd", "nd*", "qs", "qs*", "wj", "wj*", "+nd", "+nd*"})


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _node(parent: etree._Element, name: str, **attributes: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{name}", **attributes)


def _logical(root: Path, value: str) -> Path:
    return resolve_repo_path(root, value).resolve(strict=True)


def _profile(manifest: SourceManifest) -> dict[str, object]:
    value = json.loads(manifest.authority_path("profile").read_bytes())
    if not isinstance(value, dict) or value.get("contract") != "ocd-open-english-bible-2025-6-profile-v1":
        raise ValueError("OEB source profile contract mismatch")
    return value


def _verified_sources(manifest: SourceManifest, profile: Mapping[str, object]) -> dict[str, list[tuple[Mapping[str, object], bytes]]]:
    """Reconcile complete ZIP envelopes, receipts, extracted members and profile rows."""
    result: dict[str, list[tuple[Mapping[str, object], bytes]]] = {}
    authorities = {str(item["name"]): item for item in manifest.record["authorities"]}
    source_members = {str(item["name"]): item for item in manifest.record.get("source_members", ())}
    for variant_record in profile.get("variants", ()):
        variant = str(variant_record["variant"])
        if variant not in {"US", "Cth"}:
            raise ValueError(f"unsupported OEB witness: {variant}")
        archive_spec = variant_record["archive"]
        receipt_spec = variant_record["receipt"]
        inventory_spec = variant_record["inventory"]
        archive_path = manifest.authority_path(str(archive_spec["authority_name"]))
        receipt_path = manifest.authority_path(str(receipt_spec["authority_name"]))
        inventory_path = manifest.authority_path(str(inventory_spec["authority_name"]))
        archive_bytes, receipt_bytes, inventory_bytes = archive_path.read_bytes(), receipt_path.read_bytes(), inventory_path.read_bytes()
        receipt = json.loads(receipt_bytes.decode("utf-8"))
        if (len(archive_bytes), _sha(archive_bytes)) != (archive_spec["bytes"], archive_spec["sha256"]):
            raise ValueError(f"{variant} archive differs from profile")
        if (len(receipt_bytes), _sha(receipt_bytes)) != (receipt_spec["bytes"], receipt_spec["sha256"]):
            raise ValueError(f"{variant} acquisition receipt differs from profile")
        if (len(inventory_bytes), _sha(inventory_bytes)) != (inventory_spec["bytes"], inventory_spec["sha256"]):
            raise ValueError(f"{variant} raw member inventory differs from profile")
        normalized = inventory_bytes.replace(b"\r\n", b"\n")
        if b"\r" in normalized or not normalized.endswith(b"\n") or _sha(normalized) != inventory_spec["canonical_lf_sha256"]:
            raise ValueError(f"{variant} canonical receipt inventory hash differs")
        if receipt.get("manifest_row") != "L605" or receipt.get("variant") != variant or receipt.get("release") != profile.get("release"):
            raise ValueError(f"{variant} acquisition receipt identity differs")
        if receipt.get("package", {}).get("sha256") != _sha(archive_bytes):
            raise ValueError(f"{variant} receipt package digest differs")
        expected_inventory = [tuple(line.split("\t")) for line in normalized.decode("utf-8").splitlines()]
        profile_entries = variant_record.get("archive_entries")
        if not isinstance(profile_entries, list) or len(expected_inventory) != variant_record.get("archive_member_count"):
            raise ValueError(f"{variant} complete archive profile is invalid")
        extracted_by_archive_name: dict[str, bytes] = {}
        observed_entries: list[dict[str, object]] = []
        selected: list[tuple[Mapping[str, object], bytes]] = []
        with ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"{variant} source archive CRC failure")
            infos = archive.infolist()
            if len(infos) != len(profile_entries) or len(infos) != len(expected_inventory):
                raise ValueError(f"{variant} archive member count differs")
            for position, (info, profile_entry, inventory_row) in enumerate(zip(infos, profile_entries, expected_inventory), 1):
                content = archive.read(info)
                digest = _sha(content)
                expected_name, expected_size, expected_crc, expected_digest = inventory_row
                if expected_digest == "<directory>":
                    expected_digest_value = None
                else:
                    expected_digest_value = expected_digest
                observed = {"index": position, "name": info.filename, "is_directory": info.is_dir(), "bytes": info.file_size, "compressed_bytes": info.compress_size, "crc32": f"{info.CRC:08x}", "sha256": expected_digest_value, "extraction_path": profile_entry.get("extraction_path"), "authority_name": profile_entry.get("authority_name")}
                if (expected_name, int(expected_size), expected_crc.casefold()) != (info.filename, info.file_size, f"{info.CRC:08x}"):
                    raise ValueError(f"{variant} ordered inventory row differs at {position}")
                if expected_digest != ("<directory>" if info.is_dir() else digest) or profile_entry != observed:
                    raise ValueError(f"{variant} complete archive inventory differs at {position}: {info.filename}")
                pure = PurePosixPath(info.filename)
                if pure.is_absolute() or ".." in pure.parts or "\\" in info.filename:
                    raise ValueError(f"{variant} unsafe archive member path")
                extraction = _logical(manifest.repository_root, str(profile_entry["extraction_path"]))
                if info.is_dir():
                    if not extraction.is_dir():
                        raise ValueError(f"{variant} extracted directory is missing: {info.filename}")
                else:
                    authority_name = profile_entry.get("authority_name")
                    authority = authorities.get(str(authority_name))
                    source_member = source_members.get(str(authority_name))
                    if not extraction.is_file() or extraction.read_bytes() != content:
                        raise ValueError(f"{variant} extracted member differs from ZIP: {info.filename}")
                    if authority is None or authority.get("role") != "extracted-source-member" or source_member is None:
                        raise ValueError(f"{variant} extracted member authority is absent: {info.filename}")
                    if any(authority.get(key) != source_member.get(key) for key in ("path", "bytes", "sha256")):
                        raise ValueError(f"{variant} extracted member manifest link differs: {info.filename}")
                    if (source_member.get("logical_name"), source_member.get("bytes"), source_member.get("sha256")) != (info.filename, len(content), digest):
                        raise ValueError(f"{variant} extracted member identity differs: {info.filename}")
                    extracted_by_archive_name[info.filename] = content
                observed_entries.append(observed)
                if info.filename.startswith("usfm/") and info.filename.endswith(".usfm"):
                    selected.append((profile_entry, content))
        if observed_entries != profile_entries:
            raise ValueError(f"{variant} archive entry profile differs")
        extraction_root = _logical(manifest.repository_root, f"raw/ebible/open-english-bible-2025.6/{variant}/usfm")
        disk_files = {item.relative_to(extraction_root).as_posix() for item in extraction_root.rglob("*") if item.is_file()}
        archive_files = {entry["name"] for entry in profile_entries if not entry["is_directory"]}
        if disk_files != archive_files:
            raise ValueError(f"{variant} extraction tree has missing or unlisted files")
        expected_book_order = variant_record.get("book_member_order")
        if [str(entry["name"]) for entry, _ in selected] != expected_book_order:
            raise ValueError(f"{variant} USFM book/front-page order differs")
        source_records = variant_record.get("usfm_files")
        if not isinstance(source_records, list) or len(source_records) != 45 or len(selected) != len(source_records):
            raise ValueError(f"{variant} USFM member set differs")
        for (entry, content), source_record in zip(selected, source_records):
            if entry["name"] != source_record["member"] or len(content) != source_record["bytes"] or _sha(content) != source_record["sha256"] or entry["authority_name"] != source_record["authority_name"]:
                raise ValueError(f"{variant} source USFM profile differs: {entry['name']}")
            result.setdefault(variant, []).append((source_record, content))
    if list(result) != list(profile.get("variant_order", [])):
        raise ValueError("OEB variant order differs from profile")
    return result


def _pointer(variant: str, filename: str, line_number: int | None = None, token_number: int | None = None) -> str:
    from urllib.parse import quote
    base = f"source-usfm:{variant}/{quote(filename, safe='')}"
    if line_number is not None:
        base += f"#line={line_number}"
    if token_number is not None:
        base += f"&token={token_number}"
    return base


def _append_text(parent: etree._Element, value: str) -> None:
    if not value:
        return
    if len(parent):
        child = parent[-1]
        child.tail = (child.tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _inline(parent: etree._Element, payload: str, line_pointer: str) -> Counter[str]:
    """Retain each inline control as an ordered milestone or footnote field."""
    counts: Counter[str] = Counter()
    current = parent
    note: etree._Element | None = None
    note_parent: etree._Element | None = None
    field: etree._Element | None = None
    cursor = 0
    token_number = 0
    for match in TOKEN.finditer(payload):
        _append_text(current, payload[cursor:match.start()])
        cursor = match.end()
        name = match.group("name")
        if name not in INLINE:
            raise ValueError(f"unsupported inline USFM control {name!r} at {line_pointer}")
        counts[name] += 1
        token_number += 1
        token_pointer = f"{line_pointer}&token={token_number}"
        if name == "f":
            if note is not None:
                raise ValueError(f"nested footnote opener at {token_pointer}")
            note_parent = current
            note = _node(current, "note", type="usfm-footnote", place="foot", ana="#usfm-f", corresp=token_pointer)
            current = note
            field = None
        elif name == "f*":
            if note is None or note_parent is None:
                raise ValueError(f"footnote closer without opener at {token_pointer}")
            marker = _node(note, "milestone", unit="usfm-marker", n="f*", corresp=token_pointer)
            current = note_parent
            note = None
            note_parent = None
            field = None
        elif name == "fr":
            if note is None:
                raise ValueError(f"footnote reference outside footnote at {token_pointer}")
            field = _node(note, "label", type="usfm-fr", corresp=token_pointer)
            current = field
        elif name == "ft":
            if note is None:
                raise ValueError(f"footnote text outside footnote at {token_pointer}")
            field = _node(note, "seg", type="usfm-ft", corresp=token_pointer)
            current = field
        else:
            _node(current, "milestone", unit="usfm-marker", n=name, corresp=token_pointer)
    _append_text(current, payload[cursor:])
    if note is not None:
        raise ValueError(f"unterminated source footnote at {line_pointer}")
    return counts


def _source_lines(content: bytes, label: str) -> list[str]:
    if b"\r" in content or content.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"unsupported USFM encoding or line boundary: {label}")
    lines = content.decode("utf-8", errors="strict").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _render_variant(variant: str, source_files: list[tuple[Mapping[str, object], bytes]], target: etree._Element, variant_profile: Mapping[str, object]) -> dict[str, object]:
    profile_books: list[dict[str, object]] = []
    total_line_markers: Counter[str] = Counter()
    total_inline: Counter[str] = Counter()
    chapter_count = verse_count = source_line_count = continuation_count = blank_count = 0
    group = _node(target, "body")
    for file_record, content in source_files:
        filename = str(file_record["filename"])
        member = str(file_record["member"])
        lines = _source_lines(content, f"{variant}/{member}")
        id_line = next((LINE.fullmatch(line) for line in lines if LINE.fullmatch(line) and LINE.fullmatch(line).group("marker") == "id"), None)
        if id_line is None or id_line.group("payload") is None:
            raise ValueError(f"missing USFM id in {variant}/{member}")
        book_id = str(id_line.group("payload")).split(maxsplit=1)[0]
        if book_id != file_record["book_id"]:
            raise ValueError(f"source ID differs from profile for {variant}/{member}")
        member_pointer = _pointer(variant, filename)
        if book_id == "FRT":
            member_div = _node(group, "div", type="front-matter", n="FRT", corresp=member_pointer)
        else:
            member_div = _node(group, "div", type="book", n=book_id, corresp=member_pointer)
            member_div.set(XML_ID, f"{variant}-{book_id}")
        active_chapter: etree._Element | None = None
        active_verse_id: str | None = None
        active_periph: etree._Element | None = None
        active_section: etree._Element | None = None
        file_line_markers: Counter[str] = Counter()
        file_inline: Counter[str] = Counter()
        file_chapters = file_verses = file_continuations = file_blanks = 0
        for line_number, raw in enumerate(lines, 1):
            source_line_count += 1
            pointer = _pointer(variant, filename, line_number)
            leading = LINE.fullmatch(raw)
            if raw == "":
                blank_count += 1
                file_blanks += 1
                parent = active_section if active_section is not None else (active_periph if active_periph is not None else (active_chapter if active_chapter is not None else member_div))
                _node(parent, "milestone", unit="source-line", n="blank", corresp=pointer)
                continue
            if leading is None or leading.group("marker") not in LINE_MARKERS:
                if active_verse_id is None:
                    raise ValueError(f"unmarked nonempty line has no preceding verse in {variant}/{member}:{line_number}")
                continuation_count += 1
                file_continuations += 1
                parent = active_section if active_section is not None else (active_periph if active_periph is not None else (active_chapter if active_chapter is not None else member_div))
                continuation = _node(parent, "ab", type="source-continuation", corresp=pointer)
                _node(continuation, "ptr", type="preceding-verse", target=f"#{active_verse_id}")
                file_inline.update(_inline(continuation, raw, pointer))
                continue
            marker = str(leading.group("marker"))
            payload = leading.group("payload") or ""
            file_line_markers[marker] += 1
            total_line_markers[marker] += 1
            if marker == "periph":
                active_chapter = None
                active_verse_id = None
                active_section = None
                active_periph = _node(member_div, "div", type="periph", n=payload, ana="#usfm-periph", corresp=pointer)
                continue
            base_parent = active_periph if active_periph is not None else (active_chapter if active_chapter is not None else member_div)
            parent = active_section if active_section is not None else base_parent
            if marker == "c":
                active_section = None
                value = payload.strip()
                if not value.isdecimal() or value != payload:
                    raise ValueError(f"invalid chapter number at {variant}/{member}:{line_number}")
                active_chapter = _node(member_div, "div", type="chapter", n=value, ana="#usfm-c", corresp=pointer)
                active_verse_id = None
                file_chapters += 1
                chapter_count += 1
            elif marker == "v":
                if active_chapter is None:
                    raise ValueError(f"verse before chapter at {variant}/{member}:{line_number}")
                verse_number, separator, verse_text = payload.partition(" ")
                if not separator or not verse_number:
                    raise ValueError(f"malformed verse line at {variant}/{member}:{line_number}")
                active_verse_id = f"{variant}-{book_id}-line-{line_number}"
                active_verse = _node(parent, "ab", type="verse", n=verse_number, ana="#usfm-v", corresp=pointer)
                active_verse.set(XML_ID, active_verse_id)
                file_inline.update(_inline(active_verse, verse_text, pointer))
                file_verses += 1
                verse_count += 1
            elif marker in HEADS:
                if marker in SECTION_HEADS:
                    active_section = _node(base_parent, "div", type="usfm-section", n=marker, ana=f"#usfm-{marker}")
                    head = _node(active_section, "head", type=f"usfm-{marker}", ana=f"#usfm-{marker}", corresp=pointer)
                else:
                    head = _node(parent, "ab", type=f"usfm-{marker}", ana=f"#usfm-{marker}", corresp=pointer)
                file_inline.update(_inline(head, payload, pointer))
            elif marker in BLOCKS:
                block = _node(parent, "ab", type=f"usfm-{marker}", ana=f"#usfm-{marker}", corresp=pointer)
                file_inline.update(_inline(block, payload, pointer))
            elif marker == "rem":
                note = _node(parent, "note", type="usfm-rem", ana="#usfm-rem", corresp=pointer)
                file_inline.update(_inline(note, payload, pointer))
            elif marker in BREAKS:
                _node(parent, "milestone", unit="usfm-line-marker", n=marker, corresp=pointer)
            else:
                raise ValueError(f"unsupported line USFM marker {marker!r} at {variant}/{member}:{line_number}")
        expected_line_counts = file_record["line_marker_counts"]
        expected_inline_counts = file_record["marker_token_counts"]
        if dict(sorted(file_line_markers.items())) != expected_line_counts:
            raise ValueError(f"line marker profile differs for {variant}/{member}")
        if dict(sorted(file_inline.items())) != {key: value for key, value in expected_inline_counts.items() if key not in file_line_markers}:
            # Inline and line marker names overlap only for c/v and f fields are inline;
            # derive inline counts independently below from all token counts.
            all_counts = Counter(expected_inline_counts)
            for marker_name, count in file_line_markers.items():
                all_counts[marker_name] -= count
            expected_inline = {key: value for key, value in all_counts.items() if value}
            if dict(sorted(file_inline.items())) != dict(sorted(expected_inline.items())):
                raise ValueError(f"inline marker profile differs for {variant}/{member}")
        if (len(lines), file_chapters, file_verses, file_blanks, file_continuations) != (file_record["line_count"], file_record["chapter_count"], file_record["verse_count"], file_record["blank_line_count"], file_record["continuation_line_count"]):
            raise ValueError(f"source line/chapter/verse counts differ for {variant}/{member}")
        total_inline.update(file_inline)
        profile_books.append({"member": member, "book_id": book_id, "line_count": len(lines), "chapter_count": file_chapters, "verse_count": file_verses, "line_marker_counts": dict(sorted(file_line_markers.items())), "inline_marker_counts": dict(sorted(file_inline.items())), "blank_line_count": file_blanks, "continuation_line_count": file_continuations})
    if (source_line_count, chapter_count, verse_count, blank_count, continuation_count) != (variant_profile["source_line_count"], variant_profile["chapter_count"], variant_profile["verse_count"], variant_profile["blank_source_line_count"], variant_profile["unmarked_continuation_line_count"]):
        raise ValueError(f"variant-wide line/chapter/verse counts differ for {variant}")
    aggregate_expected = Counter(variant_profile["marker_token_counts"])
    for marker_name, count in total_line_markers.items():
        aggregate_expected[marker_name] -= count
    expected_inline = {key: value for key, value in aggregate_expected.items() if value}
    if dict(sorted(total_inline.items())) != dict(sorted(expected_inline.items())):
        raise ValueError(f"variant-wide inline marker census differs for {variant}")
    return {"variant": variant, "source_line_count": source_line_count, "chapter_count": chapter_count, "verse_count": verse_count, "blank_source_line_count": blank_count, "continuation_line_count": continuation_count, "line_marker_counts": dict(sorted(total_line_markers.items())), "inline_marker_counts": dict(sorted(total_inline.items())), "books": profile_books}



def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    profile = _profile(manifest)
    policy = json.loads(manifest.authority_path("policy").read_bytes())
    source_files_by_variant = _verified_sources(manifest, profile)
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "open-english-bible-2025-6-L605")
    root.set(XML_LANG, "en")
    root.set("ana", "#nonaccepted-candidate")
    header = _node(root, "teiHeader")
    file_desc = _node(header, "fileDesc")
    title_stmt = _node(file_desc, "titleStmt")
    _node(title_stmt, "title").text = str(profile["title"])
    _node(_node(file_desc, "publicationStmt"), "p").text = "Nonaccepted technical reconstruction candidate; human acceptance, rights review, and publication are separate decisions."
    archive_specs = {str(item["variant"]): item["archive"] for item in profile["variants"]}
    source_text = (f"Open English Bible {profile['release']} USFM release retained from {profile['source_url']}; "
                   f"US package SHA-256 {archive_specs['US']['sha256']}; Cth package SHA-256 {archive_specs['Cth']['sha256']}. "
                   f"Declared contents: {profile['scope']['description']}")
    _node(_node(file_desc, "sourceDesc"), "p").text = source_text
    encoding = _node(header, "encodingDesc")
    _node(encoding, "p").text = str(policy["mapping"])
    _node(encoding, "p").text = str(policy["scope"])
    group = _node(_node(root, "text"), "group")
    variant_accounts = []
    for variant in profile["variant_order"]:
        variant_text = _node(group, "text", type="witness", n=str(variant))
        variant_text.set(XML_ID, f"oeb-2025-6-{str(variant).lower()}")
        variant_profile = next(item for item in profile["variants"] if item["variant"] == variant)
        variant_accounts.append(_render_variant(str(variant), source_files_by_variant[str(variant)], variant_text, variant_profile))
    xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    accountability = {"contract": "ocd-open-english-bible-2025-6-accountability-v1", "source_id": profile["source_id"], "source_manifest_sha256": manifest.sha256, "profile_sha256": next(item["sha256"] for item in manifest.record["authorities"] if item["name"] == "profile"), "tei_sha256": _sha(xml), "tei_root_count": 1, "variant_order": list(profile["variant_order"]), "scope": profile["scope"], "variants": variant_accounts, "archive_accounting": [{"variant": variant["variant"], "archive_sha256": variant["archive"]["sha256"], "receipt_sha256": variant["receipt"]["sha256"], "raw_inventory_sha256": variant["inventory"]["sha256"], "canonical_inventory_sha256": variant["inventory"]["canonical_lf_sha256"], "archive_member_count": variant["archive_member_count"], "archive_file_count": variant["archive_file_count"], "extracted_file_count": variant["archive_file_count"], "archive_entries": [{"index": entry["index"], "member": entry["name"], "is_directory": entry["is_directory"], "bytes": entry["bytes"], "crc32": entry["crc32"], "sha256": entry["sha256"], "extraction_path": entry["extraction_path"]} for entry in variant["archive_entries"]]} for variant in profile["variants"]]}
    provenance = policy["provenance"]
    unresolved = b"".join(_json(item) for item in policy["unresolved"])
    return {"README.source.md": manifest.authority_path("readme").read_bytes(), "content.tei.xml": xml, "source-accountability.json": _json(accountability), "provenance.json": _json(provenance), "unresolved.jsonl": unresolved}


_convert.converter_id = "ocd-open-english-bible-2025-6-usfm-to-tei"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()
