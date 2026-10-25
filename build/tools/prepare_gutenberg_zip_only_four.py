"""Stage four Gutenberg ZIP-only works from verified extracted text members."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from lxml import html

from build.tools.prepare_library_sidecar_batch import CONTRACT, stage
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, canonical_bytes, load_json, sha256_file, write_json
from ocd_kernel.tei.install_accepted import _io_path

PACKAGES = {
    "61614": ("apostolic-tradition", "72a7ceef6b4145b08f1131a58a9ae2e5665b4e4c06f7fce01d56cd77879fabc7", "Apostolic Tradition"),
    "38326": ("bede-ecclesiastical-history-of-england", "97221f5e78b47a022f3f2e9be79db30127485e63a8096d8a29fada32e6ca88c8", "Ecclesiastical History"),
    "30362": ("gerhardt-spiritual-songs", "e5f97d62a381a8abc4bf666784b62a3966487be97b3626a916abd6dca3d2b750", "Spiritual Songs"),
    "4272": ("keble-christian-year", "6672add075f8368f8dbbb05c5b3c902be82eeb461ccf83e2680989f71ffc0e15", "Christian Year"),
}
WARNINGS = {
    "61614": "The retained HTML claims public domain in the USA, but its title page states Copyright 1934, Cambridge University Press, and a 1962 reprint by arrangement with Cambridge University Press. Rights review remains open; no publication clearance is implied.",
    "38326": "The retained HTML has both 'This text is in the public domain.' and 'Public domain in the USA.' metadata claims. Rights review of the exact translation, edition, transcription, and jurisdiction remains open; no publication clearance is implied.",
    "30362": "The retained HTML claims public domain in the USA. Rights review of the exact translation, edition, transcription, and jurisdiction remains open; no publication clearance is implied.",
    "4272": "The retained HTML claims public domain in the USA. Rights review of the exact edition, transcription, and jurisdiction remains open; no publication clearance is implied.",
}
NOTES = {
    "61614": "The conflicting 1934 and 1962 notices keep rights and TEI reconstruction on hold.",
    "38326": "Source proofing and completeness review remain open.",
    "30362": "Scan comparison and exact source/work crosswalk remain open.",
    "4272": "Scan collation of the ordered poetry witness remains open.",
}


def _inventory(root: Path, ebook_id: str) -> tuple[dict[str, Any], list[tuple[str, bytes, dict[str, Any]]], dict[str, Any]]:
    work_id, expected_zip, title_fragment = PACKAGES[ebook_id]
    prefix = f"raw/gutenberg/{ebook_id}"
    package_rel = f"{prefix}/pg{ebook_id}-h.zip"
    package_path = resolve_repo_path(root, package_rel)
    if not package_path.is_file() or sha256_file(package_path) != expected_zip:
        raise PipelineError(f"{work_id} retained ZIP missing or changed")
    work_path = root / "library" / "works" / work_id / "work.json"
    state_path = root / "library" / "works" / work_id / "state.json"
    work, state = load_json(work_path), load_json(state_path)
    if (work.get("work_id") != work_id or work.get("textual_forms") or package_rel not in work.get("evidence", [])
            or state.get("work_id") != work_id or state.get("targets")):
        raise PipelineError(f"{work_id} no longer has the expected identity-only source state")
    if resolve_repo_path(root, f"{prefix}/acquisition-receipt.json").exists():
        raise PipelineError(f"{work_id} acquisition receipt already exists")
    files: list[tuple[str, bytes, dict[str, Any]]] = []
    seen: set[str] = set()
    principal: bytes | None = None
    try:
        with zipfile.ZipFile(_io_path(package_path)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                parts = PurePosixPath(name).parts
                if (not name or name.startswith("/") or "\\" in name or ":" in name
                        or name in seen or any(part in {"", ".", ".."} for part in parts)
                        or PurePosixPath(name).as_posix() != name or ((info.external_attr >> 16) & 0o170000) == 0o120000):
                    raise PipelineError(f"{work_id} unsafe or duplicate ZIP member: {name}")
                seen.add(name)
                if PurePosixPath(name).suffix.lower() not in {".html", ".jpg", ".png"}:
                    raise PipelineError(f"{work_id} unsupported ZIP member: {name}")
                with archive.open(info) as stream:
                    data = stream.read()
                if len(data) != info.file_size:
                    raise PipelineError(f"{work_id} ZIP member size differs: {name}")
                row = {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "crc32": f"{info.CRC:08x}"}
                files.append((name, data, row))
                if name == f"pg{ebook_id}-images.html":
                    principal = data
    except (OSError, zipfile.BadZipFile) as exc:
        raise PipelineError(f"{work_id} retained ZIP cannot be read: {exc}") from exc
    if principal is None or len([name for name, _, _ in files if name == f"pg{ebook_id}-images.html"]) != 1:
        raise PipelineError(f"{work_id} does not have exactly one principal HTML")
    tree = html.parse(BytesIO(principal))
    titles = [" ".join(value.split()) for value in tree.xpath("//title/text()")]
    rights = tree.xpath("//meta[translate(@name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='dc.rights']/@content")
    record_url = f"https://www.gutenberg.org/ebooks/{ebook_id}"
    if (len(titles) != 1 or title_fragment.lower() not in titles[0].lower()
            or not rights or any(not value.strip() for value in rights)
            or record_url not in tree.xpath("//a/@href | //link/@href")
            or tree.xpath("/html/@lang") != ["en"]):
        raise PipelineError(f"{work_id} retained HTML identity or metadata differs")
    if ebook_id == "61614" and (b"Copyright 1934, Cambridge University Press" not in principal
                                or b"REPRINTED 1962 BY ARRANGEMENT WITH CAMBRIDGE UNIVERSITY PRESS" not in principal):
        raise PipelineError("Apostolic Tradition conflicting rights notices are absent")
    html_rel = f"{prefix}/html/pg{ebook_id}-images.html"
    source_scope = (
        f"Principal extracted HTML {html_rel} is the retained text source; ZIP {package_rel} is the retained acquisition "
        f"package with all {len(files)} members matched to extracted files. This acquisition does not establish a "
        f"complete TEI reconstruction. {NOTES[ebook_id]} No TEI acceptance or publication clearance is implied."
    )
    principal_row = next(row for name, _, row in files if name == f"pg{ebook_id}-images.html")
    receipt = {
        "schema": "ocd-acquisition-source-receipt-v2", "ebook_id": ebook_id,
        "work_id": work_id, "title": work["title"], "retained_html_title": titles[0],
        "source_url": record_url, "package_download_url_status": "unknown-not-retained",
        "package": {"path": package_rel, "bytes": package_path.stat().st_size, "sha256": expected_zip},
        "html": {"path": html_rel, "bytes": principal_row["bytes"], "sha256": principal_row["sha256"]},
        "members": [row for _, _, row in files],
        "rights_claim": {"source": html_rel + "#meta[name=dc.rights]", "text": rights[0] if len(rights) == 1 else rights},
        "rights": WARNINGS[ebook_id],
        "verification": {"member_count": len(files), "primary_html": f"pg{ebook_id}-images.html"},
        "source_scope": source_scope,
    }
    for name, data, _ in files:
        target = resolve_repo_path(root, f"{prefix}/html/{name}")
        if target.exists() and (not target.is_file() or target.read_bytes() != data):
            raise PipelineError(f"{work_id} extracted destination exists with different bytes: {name}")
    return receipt, files, {"work": work_path, "state": state_path}


def prepare_four(root: Path, packet_path: Path) -> dict[str, Any]:
    root = root.resolve()
    inventories = [(ebook_id, *_inventory(root, ebook_id)) for ebook_id in PACKAGES]
    if packet_path.exists():
        raise PipelineError(f"packet already exists: {packet_path}")
    rows: list[dict[str, Any]] = []
    for ebook_id, receipt, files, refs in inventories:
        work_id = receipt["work_id"]
        prefix = f"raw/gutenberg/{ebook_id}"
        for name, data, row in files:
            target = resolve_repo_path(root, f"{prefix}/html/{name}")
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with _io_path(target).open("xb") as stream:
                    stream.write(data)
            if (not target.is_file() or target.stat().st_size != row["bytes"]
                    or sha256_file(target) != row["sha256"]):
                raise PipelineError(f"{work_id} extracted member failed byte check: {name}")
        receipt_rel = f"{prefix}/acquisition-receipt.json"
        receipt_path = resolve_repo_path(root, receipt_rel)
        write_json(_io_path(receipt_path), receipt)
        receipt_sha = hashlib.sha256(canonical_bytes(receipt)).hexdigest()
        if sha256_file(receipt_path) != receipt_sha:
            raise PipelineError(f"{work_id} written receipt differs")
        ids = {
            "textual_form_id": f"{work_id}-gutenberg-retained",
            "edition_id": f"{work_id}-gutenberg-electronic",
            "acquisition_id": f"{work_id}-gutenberg-acquired",
        }
        rows.append({
            "work_id": work_id,
            "work": {"path": f"library/works/{work_id}/work.json", "sha256": sha256_file(refs["work"])},
            "state": {"path": f"library/works/{work_id}/state.json", "sha256": sha256_file(refs["state"])},
            **ids, "edition_title": "Project Gutenberg retained HTML witness",
            "provider": "Project Gutenberg", "url": receipt["source_url"], "language": "en", "media_type": "text/html",
            "primary_source": {"name": "retained-gutenberg-html", "role": "primary-source", **receipt["html"]},
            "archive_member": receipt["verification"]["primary_html"],
            "source_scope": receipt["source_scope"], "warnings": [receipt["rights"]],
            "acquisition_receipt": {"path": receipt_rel, "sha256": receipt_sha},
        })
    packet = {"contract": CONTRACT, "entries": rows}
    write_json(packet_path, packet)
    return packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--stage-destination", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    packet_path = args.packet.resolve()
    prepared = prepare_four(root, packet_path)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    staged = stage(root, packet_path, args.stage_destination, now)
    print(json.dumps({
        "work_count": len(prepared["entries"]), "packet": str(packet_path),
        "packet_sha256": sha256_file(packet_path), "stage": str(args.stage_destination.resolve()),
        "stage_receipt_sha256": sha256_file(args.stage_destination / "receipt.json"),
        "entries": len(staged["entries"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
