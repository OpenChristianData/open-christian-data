"""Verify a Gutenberg acquisition whose exact ZIP download URL was not retained."""
from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, load_json, sha256_file
from ocd_kernel.tei.install_accepted import _io_path


def _file(root: Path, item: dict[str, Any], label: str) -> Path:
    if (not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}
            or not isinstance(item["bytes"], int) or isinstance(item["bytes"], bool)
            or item["bytes"] <= 0 or not isinstance(item["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
        raise PipelineError(f"{label} needs exact path, bytes, and sha256")
    path = resolve_repo_path(root, item["path"])
    if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
        raise PipelineError(f"{label} missing or changed: {item['path']}")
    return path


def bind_record_only(
    root: Path, row: dict[str, Any], work: dict[str, Any], receipt: dict[str, Any], receipt_rel: str
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], str]:
    wid = work["work_id"]
    keys = {
        "schema", "ebook_id", "work_id", "title", "retained_html_title", "source_url",
        "package_download_url_status", "package", "html", "members", "rights_claim",
        "rights", "verification", "source_scope",
    }
    ebook_id = receipt.get("ebook_id")
    if (set(receipt) != keys or receipt["schema"] != "ocd-acquisition-source-receipt-v2"
            or not isinstance(ebook_id, str) or re.fullmatch(r"[1-9][0-9]*", ebook_id) is None
            or receipt["work_id"] != wid or receipt["title"] != work["title"]
            or receipt["package_download_url_status"] != "unknown-not-retained"):
        raise PipelineError(f"{wid} Gutenberg record-only receipt identity invalid")
    prefix = f"raw/gutenberg/{ebook_id}"
    package_rel = f"{prefix}/pg{ebook_id}-h.zip"
    html_rel = f"{prefix}/html/pg{ebook_id}-images.html"
    source_url = f"https://www.gutenberg.org/ebooks/{ebook_id}"
    if (receipt_rel != f"{prefix}/acquisition-receipt.json"
            or receipt["package"].get("path") != package_rel
            or receipt["html"].get("path") != html_rel
            or receipt["source_url"] != source_url or row.get("url") != source_url):
        raise PipelineError(f"{wid} Gutenberg source/record path or URL differs")
    if row.get("provider") != "Project Gutenberg" or row.get("media_type") != "text/html":
        raise PipelineError(f"{wid} Gutenberg provider/media type differs")
    if (row.get("primary_source") != {"name": "retained-gutenberg-html", "role": "primary-source", **receipt["html"]}
            or row.get("archive_member") != f"pg{ebook_id}-images.html"
            or "containing_source" in row or row.get("source_scope") != receipt["source_scope"]):
        raise PipelineError(f"{wid} Gutenberg extracted HTML binding or source scope differs")
    scope = receipt["source_scope"]
    if (not isinstance(scope, str)
            or not scope.startswith(f"Principal extracted HTML {html_rel} is the retained text source; ")
            or f"ZIP {package_rel} is the retained acquisition package" not in scope
            or "No TEI acceptance or publication clearance is implied." not in scope):
        raise PipelineError(f"{wid} Gutenberg source scope does not distinguish text and package")
    rights = receipt["rights"]
    if (not isinstance(rights, str) or not rights.strip() or row.get("warnings") != [rights]
            or "rights review" not in rights.lower()):
        raise PipelineError(f"{wid} Gutenberg rights warning differs")
    evidence = work.get("evidence")
    if (not isinstance(evidence, list) or package_rel not in evidence
            or (html_rel not in evidence and work.get("textual_forms"))):
        raise PipelineError(f"{wid} Gutenberg work lacks package evidence or has unbound HTML")
    package_path = _file(root, receipt["package"], f"{wid} ZIP package")
    html_path = _file(root, receipt["html"], f"{wid} principal HTML")
    claim = receipt["rights_claim"]
    claim_text = claim.get("text") if isinstance(claim, dict) else None
    claimed_values = [claim_text] if isinstance(claim_text, str) else claim_text
    if (not isinstance(claim, dict) or set(claim) != {"source", "text"}
            or claim["source"] != html_rel + "#meta[name=dc.rights]"
            or not isinstance(claimed_values, list) or not claimed_values
            or any(not isinstance(value, str) or not value.strip() for value in claimed_values)):
        raise PipelineError(f"{wid} Gutenberg rights claim binding invalid")
    try:
        tree = html.parse(str(_io_path(html_path)))
    except (OSError, etree.ParserError) as exc:
        raise PipelineError(f"{wid} Gutenberg HTML cannot be parsed: {exc}") from exc
    titles = [" ".join(value.split()) for value in tree.xpath("//title/text()")]
    rights_values = tree.xpath(
        "//meta[translate(@name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='dc.rights']/@content"
    )
    links = tree.xpath("//a/@href | //link/@href")
    if (titles != [receipt["retained_html_title"]]
            or rights_values != claimed_values or source_url not in links):
        raise PipelineError(f"{wid} Gutenberg HTML title, rights, or embedded record URL differs")
    members_expected = receipt["members"]
    verification = receipt["verification"]
    if (not isinstance(members_expected, list) or not members_expected
            or not isinstance(verification, dict)
            or set(verification) not in ({"member_count", "primary_html"}, {"member_count", "primary_html", "source_verification"})
            or verification["member_count"] != len(members_expected)
            or verification["primary_html"] != f"pg{ebook_id}-images.html"):
        raise PipelineError(f"{wid} Gutenberg exact member inventory missing")
    source_verification = verification.get("source_verification")
    if source_verification is not None:
        if (not isinstance(source_verification, dict) or set(source_verification) != {"path", "sha256"}
                or source_verification["path"] != f"{prefix}/source-verification.json"):
            raise PipelineError(f"{wid} Gutenberg source verification reference invalid")
        check_path = resolve_repo_path(root, source_verification["path"])
        if not check_path.is_file() or sha256_file(check_path) != source_verification["sha256"]:
            raise PipelineError(f"{wid} Gutenberg source verification changed")
        prior = load_json(check_path)
        if (prior.get("archive") != receipt["package"]
                or prior.get("member_count") != len(members_expected)
                or [(m["name"], m["bytes"], m["sha256"], m["crc32"]) for m in prior["members"]]
                != [(m["name"], m["bytes"], m["sha256"], m["crc32"]) for m in members_expected]
                or prior.get("scope") not in scope):
            raise PipelineError(f"{wid} Gutenberg prior source verification differs")
    retained = [{
        "path": package_rel, "bytes": receipt["package"]["bytes"], "sha256": receipt["package"]["sha256"],
        "media_type": "application/zip", "scope": "Original retained Project Gutenberg acquisition package.",
    }]
    observed_names: set[str] = set()
    primary_count = 0
    try:
        with zipfile.ZipFile(_io_path(package_path)) as archive:
            infos = [item for item in archive.infolist() if not item.is_dir()]
            if [item.filename for item in infos] != [m.get("name") for m in members_expected]:
                raise PipelineError(f"{wid} Gutenberg ZIP order or member names differ from receipt")
            for info, expected in zip(infos, members_expected, strict=True):
                name = info.filename
                parts = PurePosixPath(name).parts
                if (not name or name.startswith("/") or chr(92) in name or ":" in name
                        or name in observed_names or any(part in {"", ".", ".."} for part in parts)
                        or PurePosixPath(name).as_posix() != name):
                    raise PipelineError(f"{wid} Gutenberg ZIP member path unsafe or duplicate: {name}")
                observed_names.add(name)
                if (not isinstance(expected, dict) or set(expected) != {"name", "bytes", "sha256", "crc32"}
                        or not isinstance(expected["bytes"], int) or isinstance(expected["bytes"], bool)
                        or expected["bytes"] <= 0 or not isinstance(expected["sha256"], str)
                        or re.fullmatch(r"[0-9a-f]{64}", expected["sha256"]) is None
                        or not isinstance(expected["crc32"], str)
                        or re.fullmatch(r"[0-9a-f]{8}", expected["crc32"]) is None):
                    raise PipelineError(f"{wid} Gutenberg receipt member invalid: {name}")
                digest = hashlib.sha256()
                size = 0
                with archive.open(info) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        size += len(chunk)
                        digest.update(chunk)
                if (size != expected["bytes"] or digest.hexdigest() != expected["sha256"]
                        or f"{info.CRC:08x}" != expected["crc32"]):
                    raise PipelineError(f"{wid} Gutenberg ZIP member bytes differ: {name}")
                media = {".html": "text/html", ".jpg": "image/jpeg", ".png": "image/png"}.get(
                    PurePosixPath(name).suffix.lower()
                )
                if media is None:
                    raise PipelineError(f"{wid} Gutenberg ZIP member media type unsupported: {name}")
                extracted_rel = f"{prefix}/html/{name}"
                _file(root, {"path": extracted_rel, "bytes": size, "sha256": digest.hexdigest()},
                      f"{wid} extracted member")
                if name == verification["primary_html"]:
                    primary_count += 1
                    if (extracted_rel != html_rel or size != receipt["html"]["bytes"]
                            or digest.hexdigest() != receipt["html"]["sha256"]):
                        raise PipelineError(f"{wid} Gutenberg principal HTML differs from ZIP")
                retained.append({
                    "path": extracted_rel, "bytes": size, "sha256": digest.hexdigest(),
                    "media_type": media,
                    "scope": scope if name == verification["primary_html"]
                    else "Verified supporting member of the retained Project Gutenberg package.",
                })
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise PipelineError(f"{wid} cannot verify Gutenberg ZIP: {exc}") from exc
    if primary_count != 1:
        raise PipelineError(f"{wid} Gutenberg principal HTML absent or duplicate")
    extracted_root = _io_path(resolve_repo_path(root, f"{prefix}/html"))
    extracted_names = {path.relative_to(extracted_root).as_posix()
                       for path in extracted_root.rglob("*") if path.is_file()}
    if extracted_names != observed_names:
        raise PipelineError(f"{wid} Gutenberg extracted tree has unaccounted files")
    original = {
        "source_path": html_rel, "source_bytes": receipt["html"]["bytes"],
        "source_sha256": receipt["html"]["sha256"], "source_scope": scope,
    }
    evidence_paths = [receipt_rel, package_rel, html_rel]
    if source_verification is not None:
        evidence_paths.append(source_verification["path"])
    return retained, original, evidence_paths, receipt_rel
