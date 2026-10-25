"""Prepare the five retained Gutenberg trees with unknown historical ZIP download URLs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from lxml import html

from build.tools.prepare_library_sidecar_batch import CONTRACT, stage
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, canonical_bytes, load_json, sha256_file, write_json
from ocd_kernel.tei.install_accepted import _io_path

DESIGN = "plans/2026-09-22-source-preflight/gutenberg-unreceipted-five-work-design-20260925.json"
IDS = {"71811", "66953", "6733", "17826", "53809"}


def _pin(root: Path, item: dict[str, Any], label: str) -> Path:
    if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
            or not isinstance(item["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
        raise PipelineError(f"{label} requires exact path and hash")
    path = resolve_repo_path(root, item["path"])
    if not path.is_file() or sha256_file(path) != item["sha256"]:
        raise PipelineError(f"{label} missing or changed: {item['path']}")
    return path


def _full_file(root: Path, item: dict[str, Any], label: str) -> Path:
    if (not isinstance(item, dict) or not {"path", "bytes", "sha256"}.issubset(item)
            or not isinstance(item["bytes"], int) or isinstance(item["bytes"], bool)
            or item["bytes"] <= 0):
        raise PipelineError(f"{label} needs exact retained file identity")
    path = _pin(root, {"path": item["path"], "sha256": item["sha256"]}, label)
    if path.stat().st_size != item["bytes"]:
        raise PipelineError(f"{label} size differs")
    return path


def _receipt(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    ebook_id, wid = entry["ebook_id"], entry["work_id"]
    prefix = f"raw/gutenberg/{ebook_id}"
    package = entry["original_package"]
    principal = entry["principal_html"]
    source_url = f"https://www.gutenberg.org/ebooks/{ebook_id}"
    if (entry.get("zip_download_url") != "unknown-not-retained"
            or entry.get("source_record_url") != source_url
            or package.get("path") != f"{prefix}/pg{ebook_id}-h.zip"
            or principal.get("path") != f"{prefix}/html/pg{ebook_id}-images.html"
            or entry.get("proposed_receipt_path") != f"{prefix}/acquisition-receipt.json"):
        raise PipelineError(f"{wid} design path/URL identity differs")
    refs = entry["work_and_state"]
    if [item["path"] for item in refs] != [
            f"library/works/{wid}/work.json", f"library/works/{wid}/state.json"]:
        raise PipelineError(f"{wid} design work/state paths differ")
    work = load_json(_pin(root, refs[0], f"{wid} work"))
    state = load_json(_pin(root, refs[1], f"{wid} state"))
    if (work.get("work_id") != wid or work.get("title") != entry["canonical_title"]
            or work.get("textual_forms") or state.get("work_id") != wid or state.get("targets")):
        raise PipelineError(f"{wid} work/state identity no longer matches identity-only design")
    if package["path"] not in work["evidence"] or principal["path"] not in work["evidence"]:
        raise PipelineError(f"{wid} existing work lacks package and principal HTML evidence")
    package_path = _full_file(root, package, f"{wid} ZIP")
    html_path = _full_file(root, principal, f"{wid} principal HTML")
    try:
        tree = html.parse(str(_io_path(html_path)))
    except OSError as exc:
        raise PipelineError(f"{wid} retained HTML unavailable: {exc}") from exc
    titles = [" ".join(value.split()) for value in tree.xpath("//title/text()")]
    claims = tree.xpath(
        "//meta[translate(@name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='dc.rights']/@content"
    )
    if (titles != [entry["retained_html_title"]] or claims != [entry["rights_claim"]["text"]]
            or entry["rights_claim"]["source"] != principal["path"] + "#meta[name=dc.rights]"
            or source_url not in tree.xpath("//a/@href | //link/@href")
            or tree.xpath("/html/@lang") != ["en"]):
        raise PipelineError(f"{wid} retained HTML title, rights, language, or record URL differs")
    designed_members = entry["members"]
    if not isinstance(designed_members, list) or not designed_members:
        raise PipelineError(f"{wid} design member list missing")
    member_rows: list[dict[str, Any]] = []
    observed: set[str] = set()
    with zipfile.ZipFile(_io_path(package_path)) as archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        if [item.filename for item in infos] != [item["name"] for item in designed_members]:
            raise PipelineError(f"{wid} ZIP member order differs from design")
        for info, designed in zip(infos, designed_members, strict=True):
            name = info.filename
            parts = PurePosixPath(name).parts
            if (not name or name.startswith("/") or chr(92) in name or ":" in name
                    or name in observed or any(part in {"", ".", ".."} for part in parts)
                    or PurePosixPath(name).as_posix() != name):
                raise PipelineError(f"{wid} ZIP member name unsafe: {name}")
            observed.add(name)
            digest = hashlib.sha256()
            size = 0
            with archive.open(info) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(chunk)
                    digest.update(chunk)
            row = {"name": name, "bytes": size, "sha256": digest.hexdigest(), "crc32": f"{info.CRC:08x}"}
            if {key: designed[key] for key in ("name", "bytes", "sha256")} != {
                    key: row[key] for key in ("name", "bytes", "sha256")}:
                raise PipelineError(f"{wid} ZIP member differs from design: {name}")
            extracted = f"{prefix}/html/{name}"
            if designed["path"] != extracted:
                raise PipelineError(f"{wid} extracted path differs from design: {name}")
            _full_file(root, {"path": extracted, "bytes": size, "sha256": digest.hexdigest()},
                       f"{wid} extracted member")
            member_rows.append(row)
    extracted_root = _io_path(resolve_repo_path(root, f"{prefix}/html"))
    extracted_names = {path.relative_to(extracted_root).as_posix()
                       for path in extracted_root.rglob("*") if path.is_file()}
    if extracted_names != observed:
        raise PipelineError(f"{wid} extracted tree has unaccounted files")
    if len([m for m in member_rows if m["name"] == f"pg{ebook_id}-images.html"]) != 1:
        raise PipelineError(f"{wid} principal HTML not unique in ZIP")
    verification: dict[str, Any] = {
        "member_count": len(member_rows), "primary_html": f"pg{ebook_id}-images.html",
    }
    scope_note = ""
    if "existing_source_verification" in entry:
        source_check = entry["existing_source_verification"]
        prior = load_json(_pin(root, source_check, f"{wid} prior source verification"))
        if (prior.get("archive") != package or prior.get("member_count") != len(member_rows)
                or prior.get("members") != member_rows
                or prior.get("title") != work["title"]
                or prior.get("scope") != "This retained 1916 second-edition volume only; not the full Cambridge commentary series."):
            raise PipelineError(f"{wid} prior source verification differs")
        verification["source_verification"] = source_check
        scope_note = " " + prior["scope"]
    scope = (
        f"Principal extracted HTML {principal['path']} is the retained text source; "
        f"ZIP {package['path']} is the retained acquisition package with all {len(member_rows)} "
        f"members matched to extracted files. This acquisition does not establish a complete TEI reconstruction."
        f"{scope_note} No TEI acceptance or publication clearance is implied."
    )
    if ebook_id == "71811":
        warning = (
            "Retained HTML states public domain in the USA, but Cambridge University Press "
            "map-caption copyright notices appear in the volume. Rights review remains open; "
            "no publication clearance is implied."
        )
    else:
        warning = (
            "Retained Project Gutenberg HTML states public domain in the USA. Rights review of "
            "the exact edition, transcription, and jurisdiction remains open; no publication "
            "clearance is implied."
        )
    return {
        "schema": "ocd-acquisition-source-receipt-v2", "ebook_id": ebook_id,
        "work_id": wid, "title": work["title"],
        "retained_html_title": entry["retained_html_title"], "source_url": source_url,
        "package_download_url_status": "unknown-not-retained",
        "package": package, "html": {key: principal[key] for key in ("path", "bytes", "sha256")},
        "members": member_rows,
        "rights_claim": entry["rights_claim"], "rights": warning,
        "verification": verification, "source_scope": scope,
    }


def prepare_five(root: Path, design_path: Path, packet_path: Path, updated_at: str) -> dict[str, Any]:
    root = root.resolve()
    design = load_json(design_path)
    entries = design.get("entries")
    if (design.get("contract") != "ocd-gutenberg-five-work-receipt-design-v1"
            or not isinstance(entries, list) or len(entries) != 5
            or {item.get("ebook_id") for item in entries} != IDS):
        raise PipelineError("five-work Gutenberg design contract or identity set differs")
    receipts = []
    rows = []
    for entry in entries:
        receipt = _receipt(root, entry)
        rel = entry["proposed_receipt_path"]
        ids = entry["proposed_ids"]
        if (set(ids) != {"textual_form_id", "edition_id", "acquisition_id"}
                or not all(value.startswith(entry["work_id"] + "-gutenberg-") for value in ids.values())):
            raise PipelineError(f"{entry['work_id']} proposed IDs differ")
        scope = receipt["source_scope"]
        rows.append({
            "work_id": entry["work_id"], "work": entry["work_and_state"][0],
            "state": entry["work_and_state"][1],
            "textual_form_id": ids["textual_form_id"],
            "edition_id": ids["edition_id"], "acquisition_id": ids["acquisition_id"],
            "edition_title": "Project Gutenberg retained HTML witness",
            "provider": "Project Gutenberg", "url": receipt["source_url"],
            "language": "en", "media_type": "text/html",
            "primary_source": {"name": "retained-gutenberg-html", "role": "primary-source", **receipt["html"]},
            "archive_member": receipt["verification"]["primary_html"],
            "source_scope": scope, "warnings": [receipt["rights"]],
            "acquisition_receipt": {"path": rel, "sha256": hashlib.sha256(canonical_bytes(receipt)).hexdigest()},
        })
        receipts.append((rel, receipt))
    if packet_path.exists():
        raise PipelineError(f"packet already exists: {packet_path}")
    for rel, receipt in receipts:
        path = resolve_repo_path(root, rel)
        if path.exists():
            if sha256_file(path) != hashlib.sha256(canonical_bytes(receipt)).hexdigest():
                raise PipelineError(f"existing Gutenberg receipt differs: {rel}")
        else:
            write_json(_io_path(path), receipt)
    packet = {"contract": CONTRACT, "entries": rows}
    write_json(packet_path, packet)
    return packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--design", type=Path, default=Path(DESIGN))
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--stage-destination", type=Path, required=True)
    parser.add_argument("--updated-at", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    packet = args.packet.resolve()
    design = args.design.resolve()
    prepared = prepare_five(root, design, packet, args.updated_at)
    staged = stage(root, packet, args.stage_destination, args.updated_at)
    print(json.dumps({
        "work_count": len(prepared["entries"]), "packet": str(packet),
        "packet_sha256": sha256_file(packet),
        "stage": str(args.stage_destination.resolve()), "stage_receipt_sha256":
        sha256_file(args.stage_destination / "receipt.json"),
        "entries": len(staged["entries"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
