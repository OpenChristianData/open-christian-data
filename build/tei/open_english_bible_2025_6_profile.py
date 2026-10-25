"""Build the complete, source-derived profile for retained OEB 2025.6 variants."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from zipfile import ZipFile

from ocd_kernel.lib.storage_topology import resolve_repo_path

SOURCE_BASE = "raw/ebible/open-english-bible-2025.6"
SELECTED_OT = ["GEN", "JOS", "RUT", "EST", "PSA", "HOS", "JOL", "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL"]
NEW_TESTAMENT = ["MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM", "HEB", "JAS", "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV"]
ALLOWED_MARKERS = frozenset("b c d em em* f f* fr ft h id ide m ms mt mt1 mt2 mt3 nb nd nd* p periph pi q q1 q2 q3 qs qs* rem s s2 toc1 toc2 toc3 v wj wj* +nd +nd*".split())
TOKEN = re.compile(r"\\(\+?[A-Za-z][A-Za-z0-9]*\*?)")
LINE = re.compile(r"^\\(?P<marker>[A-Za-z][A-Za-z0-9]*)(?:[ \t](?P<payload>.*))?$")
LINE_MARKERS = frozenset("b c d h id ide m ms mt mt1 mt2 mt3 nb p periph pi q q1 q2 q3 rem s s2 toc1 toc2 toc3 v".split())


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def physical_lines(content: bytes, label: str) -> list[str]:
    if b"\r" in content or content.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"unsupported line encoding or boundary in {label}")
    value = content.decode("utf-8", errors="strict")
    lines = value.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _resolve(root: Path, logical: str) -> Path:
    return resolve_repo_path(root, logical).resolve(strict=True)


def build_profile(repo_root: Path) -> bytes:
    root = Path(repo_root).resolve(strict=True)
    variants: list[dict[str, object]] = []
    for variant in ("US", "Cth"):
        archive_logical = f"{SOURCE_BASE}/{variant}/OEB-2025.6-{variant}.usfm.zip"
        receipt_logical = f"{SOURCE_BASE}/{variant}/acquisition-receipt.json"
        inventory_logical = f"{SOURCE_BASE}/{variant}/member-inventory.tsv"
        archive_path = _resolve(root, archive_logical)
        receipt_path = _resolve(root, receipt_logical)
        inventory_path = _resolve(root, inventory_logical)
        archive_bytes, receipt_bytes, inventory_bytes = archive_path.read_bytes(), receipt_path.read_bytes(), inventory_path.read_bytes()
        receipt = json.loads(receipt_bytes.decode("utf-8"))
        if (receipt.get("manifest_row"), receipt.get("variant"), receipt.get("release")) != ("L605", variant, "2025.6"):
            raise ValueError(f"{variant}: acquisition receipt identity mismatch")
        if receipt.get("package", {}).get("sha256") != sha(archive_bytes) or receipt.get("package", {}).get("bytes") != len(archive_bytes):
            raise ValueError(f"{variant}: retained package differs from its receipt")
        if b"\r" in inventory_bytes.replace(b"\r\n", b""):
            raise ValueError(f"{variant}: inventory contains a lone CR")
        normalized_inventory = inventory_bytes.replace(b"\r\n", b"\n")
        if not normalized_inventory.endswith(b"\n"):
            raise ValueError(f"{variant}: canonical inventory must retain terminal LF")
        inventory_sha = sha(normalized_inventory)
        if inventory_sha != receipt.get("verification", {}).get("member_inventory_sha256"):
            raise ValueError(f"{variant}: canonical inventory digest differs from receipt")
        parsed_rows: list[tuple[str, int, str, str]] = []
        for row in normalized_inventory.decode("utf-8", errors="strict").splitlines():
            fields = row.split("\t")
            if len(fields) != 4:
                raise ValueError(f"{variant}: malformed inventory row {row!r}")
            name, size, crc, digest = fields
            parsed_rows.append((name, int(size), crc.casefold(), digest))

        archive_entries: list[dict[str, object]] = []
        source_files: list[dict[str, object]] = []
        marker_counts: Counter[str] = Counter()
        line_marker_counts: Counter[str] = Counter()
        source_line_count = blank_count = continuation_count = chapter_count = verse_count = 0
        with ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"{variant}: archive CRC verification failed")
            infos = archive.infolist()
            if len(infos) != len(parsed_rows):
                raise ValueError(f"{variant}: archive entry count differs from inventory")
            archive_files: dict[str, bytes] = {}
            for index, (info, inventory_row) in enumerate(zip(infos, parsed_rows), 1):
                name, size, crc, digest = inventory_row
                if (name, size, crc) != (info.filename, info.file_size, f"{info.CRC:08x}"):
                    raise ValueError(f"{variant}: ordered archive inventory mismatch at entry {index}: {info.filename}")
                content = archive.read(info)
                actual_sha = sha(content)
                if digest != ("<directory>" if info.is_dir() else actual_sha):
                    raise ValueError(f"{variant}: archive member hash differs at entry {index}: {info.filename}")
                pure = PurePosixPath(info.filename)
                if pure.is_absolute() or ".." in pure.parts or "\\" in info.filename:
                    raise ValueError(f"{variant}: unsafe ZIP member path {info.filename!r}")
                extraction_logical = f"{SOURCE_BASE}/{variant}/usfm/{info.filename.rstrip(chr(47))}"
                extraction_path = _resolve(root, extraction_logical)
                if info.is_dir():
                    if not extraction_path.is_dir():
                        raise ValueError(f"{variant}: extracted directory is absent: {info.filename}")
                    authority_name = None
                else:
                    if not extraction_path.is_file() or extraction_path.read_bytes() != content:
                        raise ValueError(f"{variant}: extracted member differs from ZIP: {info.filename}")
                    authority_name = f"{variant}-extracted-{index:03d}"
                    archive_files[info.filename] = content
                archive_entries.append({"index": index, "name": info.filename, "is_directory": info.is_dir(), "bytes": info.file_size, "compressed_bytes": info.compress_size, "crc32": f"{info.CRC:08x}", "sha256": None if info.is_dir() else actual_sha, "extraction_path": extraction_logical, "authority_name": authority_name})

            extraction_root = _resolve(root, f"{SOURCE_BASE}/{variant}/usfm")
            disk_files = {item.relative_to(extraction_root).as_posix() for item in extraction_root.rglob("*") if item.is_file()}
            zip_files = {name for name, _, _, digest in parsed_rows if digest != "<directory>"}
            if disk_files != zip_files:
                raise ValueError(f"{variant}: extracted tree has {len(disk_files)} files; archive has {len(zip_files)}")

            usfm_members = [(name, content) for name, content in archive_files.items() if name.startswith("usfm/") and name.endswith(".usfm")]
            if len(usfm_members) != 45:
                raise ValueError(f"{variant}: expected 45 USFM files including front page; found {len(usfm_members)}")
            for name, content in usfm_members:
                lines = physical_lines(content, f"{variant}/{name}")
                local_markers: Counter[str] = Counter()
                local_line_markers: Counter[str] = Counter()
                local_blank = local_cont = local_chapters = local_verses = 0
                for raw in lines:
                    if raw == "":
                        local_blank += 1
                    leading = LINE.fullmatch(raw)
                    if leading is not None and leading.group("marker") in LINE_MARKERS:
                        marker = leading.group("marker")
                        local_line_markers[marker] += 1
                        local_chapters += marker == "c"
                        local_verses += marker == "v"
                    elif raw:
                        local_cont += 1
                    for token in TOKEN.findall(raw):
                        local_markers[token] += 1
                unknown = set(local_markers) - ALLOWED_MARKERS
                if unknown:
                    raise ValueError(f"{variant}/{name}: unprofiled markers {sorted(unknown)}")
                marker_counts.update(local_markers)
                line_marker_counts.update(local_line_markers)
                source_line_count += len(lines)
                blank_count += local_blank
                continuation_count += local_cont
                chapter_count += local_chapters
                verse_count += local_verses
                first_id = next((LINE.fullmatch(line).group("payload") for line in lines if LINE.fullmatch(line) and LINE.fullmatch(line).group("marker") == "id"), None)
                if not isinstance(first_id, str) or not first_id:
                    raise ValueError(f"{variant}/{name}: missing source id")
                book_id = first_id.split(maxsplit=1)[0]
                archive_name = f"{variant}-extracted-{next(entry['index'] for entry in archive_entries if entry['name'] == name):03d}"
                source_files.append({"member": name, "filename": name.split("/", 1)[1], "extraction_path": f"{SOURCE_BASE}/{variant}/usfm/{name}", "authority_name": archive_name, "bytes": len(content), "sha256": sha(content), "book_id": book_id, "is_front_page": book_id == "FRT", "line_count": len(lines), "line_marker_counts": dict(sorted(local_line_markers.items())), "marker_token_counts": dict(sorted(local_markers.items())), "blank_line_count": local_blank, "continuation_line_count": local_cont, "chapter_count": local_chapters, "verse_count": local_verses})

        ids = [item["book_id"] for item in source_files]
        biblical_ids = [book_id for book_id in ids if book_id != "FRT"]
        if len(biblical_ids) != 44 or set(biblical_ids) != set(SELECTED_OT + NEW_TESTAMENT) or len(set(biblical_ids)) != 44:
            raise ValueError(f"{variant}: actual book IDs differ from declared partial scope: {ids}")
        if (chapter_count, verse_count) != (565, 13914):
            raise ValueError(f"{variant}: source chapter/verse census differs: {chapter_count}/{verse_count}")
        if marker_counts["wj"] - marker_counts["wj*"] != 1:
            raise ValueError(f"{variant}: source wj balance differs")
        luke = next(item for item in source_files if item["book_id"] == "LUK")
        luke_lines = physical_lines(archive_files[luke["member"]], f"{variant}/{luke['member']}")
        imbalances = [(number, raw) for number, raw in enumerate(luke_lines, 1) if len(re.findall(r"\\wj(?=[ \t\\]|$)", raw)) != len(re.findall(r"\\wj\*", raw))]
        if len(imbalances) != 1 or imbalances[0][0] != 815:
            raise ValueError(f"{variant}: unmatched wj locus differs from Luke 2:2 source line")
        anomaly_line = imbalances[0][1]
        if len(re.findall(r"\\wj(?=\s|$)", anomaly_line)) - len(re.findall(r"\\wj\*", anomaly_line)) != 1:
            raise ValueError(f"{variant}: unmatched wj locus differs from Luke 2:2 source line")

        variants.append({"variant": variant, "archive": {"path": f"{SOURCE_BASE}/{variant}/OEB-2025.6-{variant}.usfm.zip", "bytes": len(archive_bytes), "sha256": sha(archive_bytes), "authority_name": f"{variant}-archive", "package_url": receipt["package_url"]}, "receipt": {"path": f"{SOURCE_BASE}/{variant}/acquisition-receipt.json", "bytes": len(receipt_bytes), "sha256": sha(receipt_bytes), "authority_name": f"{variant}-receipt"}, "inventory": {"path": f"{SOURCE_BASE}/{variant}/member-inventory.tsv", "bytes": len(inventory_bytes), "sha256": sha(inventory_bytes), "canonical_lf_sha256": inventory_sha, "authority_name": f"{variant}-inventory"}, "archive_member_count": len(archive_entries), "archive_file_count": sum(not item["is_directory"] for item in archive_entries), "archive_entries": archive_entries, "usfm_files": source_files, "book_member_order": [item["member"] for item in source_files], "biblical_book_ids": biblical_ids, "source_line_count": source_line_count, "line_marker_counts": dict(sorted(line_marker_counts.items())), "marker_token_counts": dict(sorted(marker_counts.items())), "blank_source_line_count": blank_count, "unmarked_continuation_line_count": continuation_count, "chapter_count": chapter_count, "verse_count": verse_count})

    profile = {"contract": "ocd-open-english-bible-2025-6-profile-v1", "source_id": "open-english-bible-2025-6-L605", "work_id": "open-english-bible", "release": "2025.6", "manifest_row": "L605", "title": "Open English Bible 2025.6", "source_url": "https://openenglishbible.org/oeb/2025.6/", "variant_order": ["US", "Cth"], "variant_structure": "one-TEI-root / text / group / separate text witness branches", "scope": {"status": "partial", "complete_bible": False, "front_page_file": "00-Front Page.usfm", "front_page_code": "FRT", "selected_old_testament_book_ids": SELECTED_OT, "new_testament_book_ids": NEW_TESTAMENT, "biblical_book_count": 44, "selected_old_testament_book_count": 17, "new_testament_book_count": 27, "description": "Genesis, complete New Testament, Psalms, and selected Old Testament books; not a complete Bible."}, "variants": variants}
    return canonical(profile)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an exact local profile from retained OEB 2025.6 sources.")
    parser.add_argument("--write", action="store_true", help="Write profile.json under this source package directory.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    content = build_profile(root)
    if args.write:
        output = Path(__file__).resolve().parents[2] / "sources/manifest-acquisitions/open-english-bible-2025-6/profile.json"
        output.write_bytes(content)
        print(f"wrote {output} ({len(content)} bytes, sha256 {sha(content)})")
    else:
        sys.stdout.buffer.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
