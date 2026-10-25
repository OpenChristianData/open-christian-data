"""Stage source-bound v2 library sidecars without changing canonical authority.

Input is a reviewed, explicit batch declaration. This command establishes only
edition/acquisition accounting; it does not validate a reconstruction or accept text.
"""
from __future__ import annotations

import argparse
import copy
import html
import hashlib
import json
import re
import shutil
import uuid
import zipfile

from lxml import etree
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from build.tools.count_dataset_records import _manifest_config_ids
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, canonical_bytes, load_json, safe_identifier, sha256_file, write_json
from ocd_kernel.library.identities import discover_library, immutable_identity, load_work, validate_identity_update, validate_record
from ocd_kernel.library.state import load_state, validate_state
from ocd_kernel.library.acquisitions import validate_acquisition, source_member_set_bytes
from build.tools.library_member_set_binding import bind_member_set
from build.tools.library_bible_member_binding import bind_bible_members
from build.tools.library_ccel_cohort_binding import bind_ccel_cohort_member
from build.tools.library_lib054_binding import bind_lib054_member
from build.tools.library_lib028_binding import bind_lib028_member
from build.tools.library_lookup_ccel_binding import bind_lookup_ccel
from build.tools.library_chrysostom_seven_binding import bind_chrysostom_seven
from build.tools.library_basil_three_binding import bind_basil_three
from build.tools.library_exclusive_manifest_binding import bind_exclusive_manifest
from build.tools.library_exclusive_multi_binding import bind_exclusive_multi_manifest
from build.tools.library_config_free_multi_binding import bind_config_free_multi
from build.tools.library_calvin_direct_ccel_binding import bind_calvin_direct_ccel
from build.tools.library_mixed_manifest_binding import bind_mixed_manifest
from build.tools.library_owen_cohort_binding import bind_owen_cohort_member
from build.tools.library_creeds_packet_binding import bind_creeds_packet
from ocd_kernel.tei.install_accepted import _io_path, _files
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock

CONTRACT = "ocd-library-sidecar-batch-v1"


def _bound(root: Path, reference: dict[str, Any], label: str) -> tuple[Path, str]:
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise PipelineError(f"{label} needs exact path and sha256")
    rel, expected = reference["path"], reference["sha256"]
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise PipelineError(f"{label} has invalid sha256")
    path = resolve_repo_path(root, rel)
    if not path.is_file() or sha256_file(path) != expected:
        raise PipelineError(f"{label} missing or changed: {rel}")
    return path, rel


def _required(row: dict[str, Any], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise PipelineError(f"{row.get('work_id', 'row')} requires {name}")
    return value



def _direct_member_binding(root: Path, row: dict[str, Any], work: dict[str, Any],
                           receipt: dict[str, Any], receipt_rel: str) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], str]:
    """Bind a retained provider XML member directly to its evidenced work."""
    wid = work["work_id"]
    if "archive_member" in row or "containing_source" in row:
        raise PipelineError(f"{wid} direct member cannot have archive or containing-source fields")
    member = receipt.get("member")
    if not isinstance(member, dict) or set(member) != {"path", "bytes", "sha256"}:
        raise PipelineError(f"{wid} receipt member binding missing")
    member_rel = member["path"]
    receipt_dir = PurePosixPath(receipt_rel).parent
    provider_roots = {
        "docsouth": "raw/docsouth/",
        "tcp": "raw/tcp/high-range/",
        "wikisource": "raw/wikisource/",
        "dbnl": "raw/dbnl/",
    }
    providers = [name for name, prefix in provider_roots.items() if receipt_rel.startswith(prefix)]
    if (len(providers) != 1
            or PurePosixPath(receipt_rel).name != "acquisition-receipt.json"
            or not isinstance(member_rel, str)
            or PurePosixPath(member_rel).parent != receipt_dir
            or PurePosixPath(member_rel).suffix.lower() != ".xml"):
        raise PipelineError(f"{wid} direct member/receipt path identity mismatch")
    source_provider = providers[0]
    if source_provider == "tcp" and (
            receipt.get("source_id") != f"tcp-{receipt_dir.name}"
            or PurePosixPath(member_rel).name != f"{receipt_dir.name}.xml"):
        raise PipelineError(f"{wid} TCP receipt/member identity mismatch")
    if source_provider == "wikisource" and (
            receipt.get("source_id") != f"wikisource-{receipt_dir.name}"
            or PurePosixPath(member_rel).name != "wikisource-export.xml"):
        raise PipelineError(f"{wid} Wikisource receipt/member identity mismatch")
    if source_provider == "dbnl" and (
            not receipt.get("source_id", "").startswith("DBNL-")
            or PurePosixPath(member_rel).name != f"{receipt_dir.name}.xml"):
        raise PipelineError(f"{wid} DBNL receipt/member identity mismatch")
    source = row["primary_source"]
    if (not isinstance(source, dict) or source.get("role") != "primary-source"
            or any(source.get(key) != member[key] for key in ("path", "bytes", "sha256"))):
        raise PipelineError(f"{wid} primary XML differs from receipt member")
    if (not isinstance(member["bytes"], int) or isinstance(member["bytes"], bool)
            or member["bytes"] <= 0 or not isinstance(member["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", member["sha256"]) is None):
        raise PipelineError(f"{wid} invalid receipt member bytes/hash")
    if receipt.get("source_url") != _required(row, "url"):
        raise PipelineError(f"{wid} receipt source URL mismatch")
    manifest_row = receipt.get("manifest_row")
    if (not isinstance(manifest_row, str) or not manifest_row
            or receipt_rel not in work["evidence"]
            or member_rel not in work["evidence"]
            or f"research/MANIFEST.md#{manifest_row}" not in work["evidence"]):
        raise PipelineError(f"{wid} work does not bind direct member, receipt, and manifest row")
    rights = receipt.get("rights")
    if not isinstance(rights, str) or not rights.strip():
        raise PipelineError(f"{wid} retained rights warning missing from receipt")
    member_path = resolve_repo_path(root, member_rel)
    if (not member_path.is_file() or member_path.stat().st_size != member["bytes"]
            or sha256_file(member_path) != member["sha256"]):
        raise PipelineError(f"{wid} retained XML bytes/hash differ from receipt member")
    expected_warnings = [rights]
    receipt_work = receipt.get("work")
    if not isinstance(receipt_work, str) or not receipt_work.strip():
        raise PipelineError(f"{wid} receipt work description missing")
    if receipt_work != work["title"]:
        if source_provider in {"wikisource", "dbnl"}:
            raise PipelineError(f"{wid} receipt work title differs from canonical work")
        try:
            tree = etree.parse(str(_io_path(member_path)), etree.XMLParser(resolve_entities=False, no_network=True))
        except (OSError, etree.XMLSyntaxError) as exc:
            raise PipelineError(f"{wid} cannot inspect retained XML header: {exc}") from exc
        title_nodes = tree.xpath("/*/*[local-name()='teiHeader']/*[local-name()='fileDesc']/*[local-name()='titleStmt']/*[local-name()='title']")
        titles = [" ".join(" ".join(node.itertext()).split()) for node in title_nodes]
        matching_titles = [title for title in titles if title.casefold().startswith(work["title"].casefold())]
        if source_provider == "tcp":
            if len(matching_titles) != 1:
                raise PipelineError(f"{wid} retained XML header title must uniquely match canonical work")
            expected_warnings.append(
                f"Receipt work label {receipt_work!r} is shorthand and differs from the canonical work title. "
                "Exactly one retained XML titleStmt/title matches the canonical title; the receipt label is not adopted. "
                "Other retained titleStmt/title entries remain part of the source witness."
            )
        else:
            author_nodes = tree.xpath("/*/*[local-name()='teiHeader']/*[local-name()='fileDesc']/*[local-name()='titleStmt']/*[local-name()='author']")
            if len(title_nodes) != 1 or len(author_nodes) != 1:
                raise PipelineError(f"{wid} retained XML header title/author identity missing")
            header_title = titles[0]
            header_author = " ".join(" ".join(author_nodes[0].itertext()).split())
            if not matching_titles:
                raise PipelineError(f"{wid} retained XML header title differs from canonical work")
            receipt_author = receipt.get("author")
            if not isinstance(receipt_author, str) or not receipt_author.strip():
                raise PipelineError(f"{wid} receipt author description missing")
            expected_warnings.append(
                f"Receipt description: {receipt_work} / {receipt_author}; retained XML header: "
                f"{header_title} / {header_author}. Canonical work identity follows the XML header; "
                "receipt description is not adopted."
            )
    if row.get("warnings") != expected_warnings:
        raise PipelineError(f"{wid} proposed warnings differ from retained receipt and source identity")
    scope = _required(row, "source_scope")
    retained = [{"path": member_rel, "bytes": member["bytes"], "sha256": member["sha256"],
                 "media_type": _required(row, "media_type"), "scope": scope}]
    original = {"source_path": member_rel, "source_bytes": member["bytes"],
                "source_sha256": member["sha256"], "source_scope": scope}
    return retained, original, [receipt_rel, member_rel], receipt_rel


def _gutenberg_package_binding(root: Path, row: dict[str, Any], work: dict[str, Any],
                               receipt: dict[str, Any], receipt_rel: str) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], str]:
    """Bind a Gutenberg ZIP and each exactly matching extracted member."""
    wid = work["work_id"]
    ebook_id = receipt.get("ebook_id")
    if not isinstance(ebook_id, str) or re.fullmatch(r"[1-9][0-9]*", ebook_id) is None:
        raise PipelineError(f"{wid} Gutenberg ebook ID missing")
    prefix = f"raw/gutenberg/{ebook_id}"
    package_rel = f"{prefix}/pg{ebook_id}-h.zip"
    html_prefix = f"{prefix}/html/"
    package, html_source = receipt.get("package"), receipt.get("html")
    if (receipt_rel != f"{prefix}/acquisition-receipt.json"
            or not isinstance(package, dict) or set(package) != {"path", "bytes", "sha256"}
            or not isinstance(html_source, dict) or set(html_source) != {"path", "bytes", "sha256"}
            or package["path"] != package_rel or not isinstance(html_source["path"], str)
            or not html_source["path"].startswith(html_prefix)):
        raise PipelineError(f"{wid} Gutenberg receipt/package/HTML path identity mismatch")
    for label, item in (("package", package), ("HTML", html_source)):
        if (not isinstance(item["bytes"], int) or isinstance(item["bytes"], bool) or item["bytes"] <= 0
                or not isinstance(item["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
            raise PipelineError(f"{wid} Gutenberg {label} bytes/hash invalid")
    if (receipt.get("source_url") != f"https://www.gutenberg.org/ebooks/{ebook_id}"
            or receipt.get("package_url") != f"https://www.gutenberg.org/cache/epub/{ebook_id}/pg{ebook_id}-h.zip"
            or _required(row, "url") != receipt["package_url"]):
        raise PipelineError(f"{wid} Gutenberg provider/package URL mismatch")
    if row.get("provider") != "Project Gutenberg" or row.get("media_type") != "text/html":
        raise PipelineError(f"{wid} Gutenberg provider/HTML media type mismatch")
    source = row.get("primary_source")
    if (not isinstance(source, dict) or source.get("role") != "primary-source"
            or any(source.get(key) != html_source[key] for key in ("path", "bytes", "sha256"))):
        raise PipelineError(f"{wid} Gutenberg primary HTML differs from receipt")
    member = row.get("archive_member")
    if (not isinstance(member, str) or PurePosixPath(member).name != member
            or html_source["path"] != html_prefix + member):
        raise PipelineError(f"{wid} Gutenberg principal archive member mismatch")
    if row.get("containing_source") is not None:
        raise PipelineError(f"{wid} Gutenberg package cannot use containing-source locator")
    rights = receipt.get("rights")
    if not isinstance(rights, str) or not rights.strip() or row.get("warnings") != [rights]:
        raise PipelineError(f"{wid} Gutenberg rights warning differs from receipt")
    evidence = work.get("evidence", [])
    if not isinstance(evidence, list) or any(path not in evidence for path in (receipt_rel, package_rel, html_source["path"])):
        raise PipelineError(f"{wid} Gutenberg work lacks receipt/package/HTML evidence")
    manifest_rows = receipt.get("manifest_rows")
    if manifest_rows is not None:
        if (not isinstance(manifest_rows, list) or not manifest_rows
                or any(not isinstance(value, str) or re.fullmatch(r"L[0-9]+", value) is None
                       or f"research/MANIFEST.md#{value}" not in evidence for value in manifest_rows)):
            raise PipelineError(f"{wid} Gutenberg manifest row differs from work evidence")
    elif (receipt.get("title") != work["title"]
          or not isinstance(receipt.get("verification"), dict)
          or not isinstance(receipt["verification"].get("identity_evidence"), str)
          or not receipt["verification"]["identity_evidence"].strip()
          or not any(isinstance(value, str) and re.fullmatch(r"research/MANIFEST.md#L[0-9]+", value) for value in evidence)):
        raise PipelineError(f"{wid} Gutenberg receipt title/identity evidence mismatch")
    verification = receipt.get("verification")
    if not isinstance(verification, dict) or verification.get("primary_html", member) != member:
        raise PipelineError(f"{wid} Gutenberg principal HTML verification mismatch")
    count_expected = verification.get("member_count")
    if count_expected is None and isinstance(verification.get("member_hash_inventory"), dict):
        count_expected = verification["member_hash_inventory"].get("count")
    if not isinstance(count_expected, int) or isinstance(count_expected, bool) or count_expected < 1:
        raise PipelineError(f"{wid} Gutenberg archive member count missing")
    package_path = resolve_repo_path(root, package_rel)
    if (not package_path.is_file() or package_path.stat().st_size != package["bytes"]
            or sha256_file(package_path) != package["sha256"]):
        raise PipelineError(f"{wid} Gutenberg package bytes/hash differ from receipt")
    scope = _required(row, "source_scope")
    legacy_prefix = (
        f"Complete original Project Gutenberg ZIP {package_rel} and all {count_expected} "
        f"exactly matching extracted archive members under {html_prefix}, including principal "
        f"HTML {html_source['path']} and support images. "
    )
    if not scope.startswith(legacy_prefix) or not scope[len(legacy_prefix):].strip():
        raise PipelineError(f"{wid} Gutenberg source scope differs from verified package/member declaration")
    scope_detail = scope[len(legacy_prefix):]
    text_scope = (f"Principal extracted HTML {html_source['path']} is the retained text source; "
                  f"ZIP {package_rel} is the acquisition package, with other extracted members "
                  f"retained as support files. {scope_detail}")
    retained = [{"path": package_rel, "bytes": package["bytes"], "sha256": package["sha256"],
                 "media_type": "application/zip", "scope": "Original complete acquired Project Gutenberg ZIP package."}]
    found_primary = 0
    try:
        with zipfile.ZipFile(_io_path(package_path)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != count_expected:
                raise PipelineError(f"{wid} Gutenberg archive member count differs from receipt")
            seen: set[str] = set()
            for item in members:
                name = item.filename
                parts = PurePosixPath(name).parts
                if (not name or name.startswith("/") or chr(92) in name or ":" in name
                        or name in seen or any(part in {"", ".", ".."} for part in parts)
                        or PurePosixPath(name).as_posix() != name):
                    raise PipelineError(f"{wid} Gutenberg archive member path unsafe or repeated: {name}")
                seen.add(name)
                media = {".html": "text/html", ".jpg": "image/jpeg", ".png": "image/png"}.get(PurePosixPath(name).suffix.lower())
                if media is None:
                    raise PipelineError(f"{wid} Gutenberg archive member media type unsupported: {name}")
                extracted_rel = html_prefix + name
                extracted_path = resolve_repo_path(root, extracted_rel)
                digest = hashlib.sha256()
                size = 0
                with archive.open(item) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        size += len(chunk)
                        digest.update(chunk)
                checksum = digest.hexdigest()
                if (not extracted_path.is_file() or extracted_path.stat().st_size != size
                        or sha256_file(extracted_path) != checksum):
                    raise PipelineError(f"{wid} Gutenberg extracted member differs from archive: {name}")
                if name == member:
                    found_primary += 1
                    if (size, checksum) != (html_source["bytes"], html_source["sha256"]):
                        raise PipelineError(f"{wid} Gutenberg principal HTML differs from archive/receipt")
                retained.append({"path": extracted_rel, "bytes": size, "sha256": checksum,
                                 "media_type": media,
                                 "scope": text_scope if name == member else
                                          "Exactly matching supporting member of the retained Project Gutenberg ZIP."})
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise PipelineError(f"{wid} cannot verify Gutenberg ZIP members: {exc}") from exc
    if found_primary != 1:
        raise PipelineError(f"{wid} Gutenberg principal HTML missing from archive")
    original = {"source_path": html_source["path"], "source_bytes": html_source["bytes"],
                "source_sha256": html_source["sha256"], "source_scope": text_scope}
    return retained, original, [receipt_rel, package_rel, html_source["path"]], receipt_rel


def _receipt_binding(root: Path, row: dict[str, Any], work: dict[str, Any], cache: dict[tuple[str, str], tuple[int, str]], xml_cache: dict[str, etree._ElementTree]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], str]:
    """Bind a direct XML member or an openMGH archive and its locators."""
    wid = work["work_id"]
    receipt_path, receipt_rel = _bound(root, row["acquisition_receipt"], f"{wid} acquisition receipt")
    receipt = load_json(receipt_path)
    source_id = receipt.get("source_id")
    if receipt.get("schema") not in {"ocd-acquisition-source-receipt-v1", "ocd-acquisition-source-receipt-v2"}:
        raise PipelineError(f"{wid} unsupported acquisition receipt")
    if ("member" in receipt) == ("package" in receipt):
        raise PipelineError(f"{wid} receipt requires exactly one member or package binding")
    if receipt_rel.startswith("raw/gutenberg/"):
        if "package" not in receipt:
            raise PipelineError(f"{wid} Gutenberg receipt requires original package")
        if receipt["schema"] == "ocd-acquisition-source-receipt-v2":
            from build.tools.gutenberg_record_only_binding import bind_record_only
            return bind_record_only(root, row, work, receipt, receipt_rel)
        return _gutenberg_package_binding(root, row, work, receipt, receipt_rel)
    if receipt["schema"] != "ocd-acquisition-source-receipt-v1":
        raise PipelineError(f"{wid} record-only receipt is Gutenberg-specific")
    if not isinstance(source_id, str):
        raise PipelineError(f"{wid} unsupported acquisition receipt")
    if "member" in receipt:
        return _direct_member_binding(root, row, work, receipt, receipt_rel)
    package = receipt.get("package")
    if not isinstance(package, dict) or set(package) != {"path", "bytes", "sha256"}:
        raise PipelineError(f"{wid} receipt package binding missing")
    package_rel = f"raw/openmgh/{source_id}/{source_id}.zip"
    xml_rel = f"raw/openmgh/{source_id}/tei/{source_id}.xml"
    if receipt_rel != f"raw/openmgh/{source_id}/acquisition-receipt.json" or package["path"] != package_rel:
        raise PipelineError(f"{wid} receipt path/package identity mismatch")
    if receipt.get("source_url") != _required(row, "url"):
        raise PipelineError(f"{wid} receipt source URL mismatch")
    containing = row.get("containing_source")
    if not isinstance(containing, dict) or containing.get("title") != receipt.get("work_edition"):
        raise PipelineError(f"{wid} containing-source title differs from receipt")
    locators = containing.get("locator", "")
    if not isinstance(locators, str) or not locators:
        raise PipelineError(f"{wid} containing-source locators missing")
    for locator in locators.split("; "):
        if not locator.startswith(xml_rel + "#") or locator not in work["evidence"] or locator not in containing.get("evidence", []):
            raise PipelineError(f"{wid} locator is not an existing work-evidence anchor: {locator}")
    if receipt_rel not in work["evidence"]:
        raise PipelineError(f"{wid} work does not bind source receipt")
    source = row["primary_source"]
    if source.get("role") != "primary-source" or source.get("path") != xml_rel:
        raise PipelineError(f"{wid} primary XML path differs from receipt identity")
    member = _required(row, "archive_member")
    if PurePosixPath(member).name != member or member != f"{source_id}.xml":
        raise PipelineError(f"{wid} unsafe or unexpected archive member")
    package_path = resolve_repo_path(root, package_rel)
    xml_path = resolve_repo_path(root, xml_rel)
    if (not package_path.is_file() or package_path.stat().st_size != package["bytes"] or sha256_file(package_path) != package["sha256"]):
        raise PipelineError(f"{wid} retained archive bytes/hash differ")
    if (not xml_path.is_file() or xml_path.stat().st_size != source["bytes"] or sha256_file(xml_path) != source["sha256"]):
        raise PipelineError(f"{wid} retained XML bytes/hash differ")
    key = (package_rel, member)
    if key not in cache:
        try:
            with zipfile.ZipFile(_io_path(package_path)) as archive:
                file_members = [item for item in archive.infolist() if not item.is_dir()]
                if len(file_members) != receipt["verification"]["member_count"] or [item.filename for item in file_members] != [member]:
                    raise PipelineError(f"{wid} archive member inventory differs from receipt")
                digest = hashlib.sha256()
                count = 0
                with archive.open(member) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        count += len(chunk)
                        digest.update(chunk)
                cache[key] = (count, digest.hexdigest())
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            raise PipelineError(f"{wid} cannot verify retained archive member: {exc}") from exc
    if cache[key] != (source["bytes"], source["sha256"]):
        raise PipelineError(f"{wid} extracted XML differs from archive member")
    if xml_rel not in xml_cache:
        try:
            xml_cache[xml_rel] = etree.parse(str(_io_path(xml_path)), etree.XMLParser(resolve_entities=False, no_network=True))
        except (OSError, etree.XMLSyntaxError) as exc:
            raise PipelineError(f"{wid} retained XML cannot be parsed for locators: {exc}") from exc
    tree = xml_cache[xml_rel]
    for locator in locators.split("; "):
        fragment = locator.split("#", 1)[1]
        if fragment.startswith("teiHeader/"):
            parts = fragment.split("/")
            if any(re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]*", part) is None for part in parts):
                raise PipelineError(f"{wid} unsupported source XPath locator: {fragment}")
            query = "./" + "/".join("tei:" + part for part in parts)
            matches = tree.getroot().xpath(query, namespaces={"tei": "http://www.tei-c.org/ns/1.0"})
        else:
            matches = tree.xpath("//*[@xml:id=$identity]", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"}, identity=fragment)
        if len(matches) != 1:
            raise PipelineError(f"{wid} source locator must resolve uniquely: {locator} ({len(matches)} matches)")
    scope = _required(row, "source_scope")
    legacy_prefix = "Complete acquired containing-source package and its extracted TEI member; "
    if not scope.startswith(legacy_prefix) or not scope[len(legacy_prefix):].strip():
        raise PipelineError(f"{wid} openMGH source scope differs from verified package/member declaration")
    scope_detail = scope[len(legacy_prefix):]
    text_scope = (f"Extracted TEI XML {xml_rel} is the retained text source; "
                  f"ZIP {package_rel} is the acquisition package. {scope_detail}")
    retained = [{"path": package_rel, "bytes": package["bytes"], "sha256": package["sha256"], "media_type": "application/zip", "scope": "Original complete acquired openMGH archive package."},
                {"path": xml_rel, "bytes": source["bytes"], "sha256": source["sha256"], "media_type": _required(row, "media_type"), "scope": text_scope}]
    original = {"source_path": xml_rel, "source_bytes": source["bytes"], "source_sha256": source["sha256"], "source_scope": text_scope}
    return retained, original, [receipt_rel, package_rel, xml_rel], receipt_rel



def _shared_xml_child_binding(root: Path, row: dict[str, Any], work: dict[str, Any],
                              config: dict[str, Any], manifest_rel: str, config_rel: str,
                              source: dict[str, Any], xml_cache: dict[str, etree._ElementTree],
                              text_cache: dict[str, str], *, child_tag: str = "div1",
                              source_title_expected: str | None = None) -> list[str]:
    """Bind one work to an evidenced direct ThML child of a retained XML volume."""
    wid = work["work_id"]
    source_rel = source["path"]
    if (config.get("resource_id") != wid or config.get("source_file", source_rel) != source_rel
            or config.get("source_hash") != f"sha256:{source['sha256']}"
            or config.get("source_url") != _required(row, "url")
            or config.get("language") != row.get("language")):
        raise PipelineError(f"{wid} shared XML config identity/source binding mismatch")
    if (PurePosixPath(source_rel).suffix.lower() != ".xml"
            or row.get("media_type") != "application/xml" or "url_evidence" in row):
        raise PipelineError(f"{wid} shared XML requires one exact XML source and config URL")
    metadata_path, metadata_rel = _bound(root, row["metadata_evidence"], f"{wid} metadata evidence")
    if (metadata_rel != f"metadata/source-evidence/catalog/{wid}.json"
            or metadata_rel not in work["evidence"]):
        raise PipelineError(f"{wid} work does not cite its bound metadata evidence")
    metadata = load_json(metadata_path)
    if metadata.get("subject") != {"id": wid, "kind": "catalog"}:
        raise PipelineError(f"{wid} metadata evidence subject mismatch")
    containing = row.get("containing_source")
    if not isinstance(containing, dict) or set(containing) != {"title", "locator", "evidence"}:
        raise PipelineError(f"{wid} shared XML requires an exact containing-source locator")
    locator = containing["locator"]
    if (not isinstance(locator, str) or not locator.startswith(source_rel + "#")
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*", locator[len(source_rel) + 1:]) is None
            or containing["title"] != config.get("source_edition")
            or not isinstance(containing["evidence"], list)
            or metadata_rel not in containing["evidence"] or locator not in containing["evidence"]):
        raise PipelineError(f"{wid} containing-source title, locator, or evidence mismatch")
    section_id = locator[len(source_rel) + 1:]
    source_path = resolve_repo_path(root, source_rel)
    if source_rel not in xml_cache:
        try:
            xml_cache[source_rel] = etree.parse(str(_io_path(source_path)), etree.XMLParser(resolve_entities=False, no_network=True))
            text_cache[source_rel] = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, etree.XMLSyntaxError) as exc:
            raise PipelineError(f"{wid} retained shared XML cannot be inspected: {exc}") from exc
    if child_tag not in {"div1", "div2"}:
        raise PipelineError(f"{wid} unsupported shared XML child element: {child_tag}")
    matches = xml_cache[source_rel].xpath(
        f"/ThML/ThML.body//{child_tag}[@id=$identity]", identity=section_id)
    if len(matches) != 1 or not isinstance(matches[0].get("title"), str) or not matches[0].get("title"):
        raise PipelineError(f"{wid} shared XML child must resolve uniquely: {locator}")
    source_title = matches[0].get("title")
    if source_title_expected is not None and source_title != source_title_expected:
        raise PipelineError(f"{wid} shared XML child title differs from source evidence")
    matching_bindings = []
    def inspect_bindings(value: Any) -> None:
        if isinstance(value, dict):
            if (value.get("path") == source_rel and value.get("sha256") == source["sha256"]
                    and isinstance(value.get("locator"), dict)):
                expected = value["locator"].get("expected")
                if isinstance(expected, str):
                    tag = re.search(rf"<{child_tag}\b[^>]*>", expected)
                    if tag is not None and tag.group(0) in text_cache[source_rel]:
                        raw_id = re.search(r'\bid="([^"]+)"', tag.group(0))
                        raw_title = re.search(r'\btitle="([^"]+)"', tag.group(0))
                        if (raw_id is not None and raw_id.group(1) == section_id
                                and raw_title is not None and html.unescape(raw_title.group(1)) == source_title):
                            matching_bindings.append(tag.group(0))
            for child in value.values():
                inspect_bindings(child)
        elif isinstance(value, list):
            for child in value:
                inspect_bindings(child)
    inspect_bindings(metadata.get("dimensions"))
    if manifest_rel == "sources/structured-text/augustine-npnf105/npnf105.source-manifest.json":
        dimensions = metadata.get("dimensions")
        parts = dimensions.get("parts") if isinstance(dimensions, dict) else None
        fields = parts.get("fields") if isinstance(parts, dict) else None
        claims = [field for field in fields if isinstance(field, dict)
                  and field.get("claim_id") == "parts:assigned_div1_scope"] if isinstance(fields, list) else []
        claim_evidence = claims[0].get("evidence") if len(claims) == 1 else None
        if not isinstance(claim_evidence, dict) or claim_evidence.get("classification") != "supported":
            raise PipelineError(f"{wid} NPNF105 assigned div1 claim missing")
        bindings = claim_evidence.get("bindings")
        if (not isinstance(bindings, list) or len(bindings) != 1
                or not isinstance(bindings[0], dict)):
            raise PipelineError(f"{wid} NPNF105 assigned div1 binding must be unique")
        binding = bindings[0]
        locator_claim = binding.get("locator")
        if not isinstance(locator_claim, dict):
            raise PipelineError(f"{wid} NPNF105 assigned div1 locator missing")
        heading_id = locator_claim.get("value")
        expected_heading = locator_claim.get("expected")
        if (child_tag != "div1" or binding.get("path") != source_rel
                or binding.get("sha256") != source["sha256"]
                or binding.get("bytes") != source["bytes"]
                or locator_claim.get("kind") != "xml_id"
                or not isinstance(heading_id, str)
                or not isinstance(expected_heading, str)):
            raise PipelineError(f"{wid} NPNF105 assigned div1 source binding differs")
        headings = xml_cache[source_rel].xpath("//*[@id=$identity]", identity=heading_id)
        if len(headings) != 1 or matches[0] not in headings[0].iterancestors("div1"):
            raise PipelineError(f"{wid} NPNF105 heading does not belong to {locator}")
        def normalized(value: str) -> str:
            return re.sub(r"\s+", " ", value).strip().casefold()

        if normalized("".join(headings[0].itertext())) != normalized(expected_heading):
            raise PipelineError(f"{wid} NPNF105 source heading differs from metadata")
        matching_bindings.append(heading_id)
    if not matching_bindings:
        raise PipelineError(f"{wid} source-hash-bound metadata does not identify XML child {locator}")
    scope = (f"Complete acquired XML volume {source_rel}; work-specific locator {locator} "
             "is recorded in edition.containing_source and does not establish accepted child text.")
    if row.get("source_scope") != scope:
        raise PipelineError(f"{wid} shared XML retained scope must describe complete volume and child locator")
    return [manifest_rel, config_rel, source_rel, metadata_rel]


def _gregory_shared_volume_binding(root: Path, row: dict[str, Any], work: dict[str, Any],
                                   xml_cache: dict[str, etree._ElementTree],
                                   text_cache: dict[str, str]) -> tuple[list[dict[str, Any]], list[str], str]:
    """Account for one NPNF205 child without extending its two-work TEI manifest."""
    wid = work["work_id"]
    report_path, report_rel = _bound(root, row["shared_volume_evidence"], f"{wid} shared volume evidence")
    if report_rel != "plans/2026-09-22-source-preflight/gregory-nyssa-shared-volume-accounting-evidence-20260925.json":
        raise PipelineError(f"{wid} unsupported shared volume evidence route")
    report = load_json(report_path)
    if report.get("report_type") != "gregory-nyssa-shared-volume-source-accounting-evidence":
        raise PipelineError(f"{wid} shared volume evidence contract mismatch")
    rows = report.get("works")
    if (not isinstance(rows, list) or len(rows) != 12
            or any(not isinstance(item, dict) for item in rows)
            or len({item.get("work_id") for item in rows}) != 12):
        raise PipelineError(f"{wid} shared volume evidence work set is invalid")
    matches = [item for item in rows if item["work_id"] == wid]
    if len(matches) != 1:
        raise PipelineError(f"{wid} missing from shared volume evidence")
    evidence = matches[0]
    config_path, config_rel = _bound(root, row["config"], f"{wid} config")
    config = load_json(config_path)
    source = row.get("primary_source")
    volume = report.get("retained_volume")
    root_claim = evidence.get("source_root")
    containing = row.get("containing_source")
    if (not isinstance(source, dict) or source.get("role") != "primary-source"
            or not isinstance(volume, dict)
            or any(source.get(field) != volume.get(field) for field in ("path", "bytes", "sha256"))
            or not isinstance(root_claim, dict) or root_claim.get("match_count") != 1
            or not isinstance(containing, dict) or root_claim.get("locator") != containing.get("locator")
            or root_claim.get("xml_element") not in {"div1", "div2"}
            or not isinstance(root_claim.get("source_title"), str)
            or not root_claim["source_title"].strip()
            or report.get("source_url") != row.get("url")
            or evidence.get("source_url") != row.get("url")
            or evidence.get("language") != row.get("language")
            or evidence.get("config_title") != config.get("title")):
        raise PipelineError(f"{wid} shared volume source, locator, or config claim mismatch")
    for field, reference in (("work", row["work"]), ("state", row["state"]),
                             ("config", row["config"]), ("metadata_evidence", row["metadata_evidence"])):
        claim = evidence.get(field)
        if not isinstance(claim, dict) or any(claim.get(name) != reference.get(name) for name in ("path", "sha256")):
            raise PipelineError(f"{wid} shared volume {field} hash differs from report")
        bound_path, _ = _bound(root, reference, f"{wid} {field}")
        if bound_path.stat().st_size != claim.get("bytes"):
            raise PipelineError(f"{wid} shared volume {field} size differs from report")
    source_path = resolve_repo_path(root, source["path"])
    if not source_path.is_file() or source_path.stat().st_size != source["bytes"] or sha256_file(source_path) != source["sha256"]:
        raise PipelineError(f"{wid} shared volume XML bytes/hash differ")
    evidence_paths = _shared_xml_child_binding(
        root, row, work, config, report_rel, config_rel, source, xml_cache, text_cache,
        child_tag=root_claim["xml_element"], source_title_expected=root_claim["source_title"])
    retained = [{"path": source["path"], "bytes": source["bytes"], "sha256": source["sha256"],
                 "media_type": _required(row, "media_type"), "scope": _required(row, "source_scope")}]
    return retained, evidence_paths, config_rel


def prepare(root: Path, packet: dict[str, Any], now: str) -> list[dict[str, Any]]:
    if packet.get("contract") != CONTRACT or not isinstance(packet.get("entries"), list) or not packet["entries"]:
        raise PipelineError("batch packet requires contract and nonempty entries")
    if set(packet) != {"contract", "entries"}:
        raise PipelineError("unexpected batch packet field")
    if not now.endswith("Z"):
        raise PipelineError("updated_at must be UTC Z")
    occupied = {"forms": set(), "editions": set(), "acquisitions": set()}
    for existing in discover_library(root):
        identities = immutable_identity(existing.record)
        for kind in occupied:
            occupied[kind].update(identities[kind])
    seen: set[str] = set()
    seen_shared_locators: set[str] = set()
    zip_cache: dict[tuple[str, str], tuple[int, str]] = {}
    xml_cache: dict[str, etree._ElementTree] = {}
    text_cache: dict[str, str] = {}
    results = []
    for row in packet["entries"]:
        if not isinstance(row, dict):
            raise PipelineError("batch entry must be object")
        allowed = {"work_id", "work", "state", "source_manifest", "shared_volume_evidence", "config", "primary_source", "textual_form_id", "append_to_existing_form", "edition_id", "acquisition_id", "edition_title", "provider", "url", "language", "media_type", "source_scope", "containing_source", "source_child_element", "url_evidence", "acquisition_receipt", "archive_member", "warnings", "metadata_evidence", "primary_sources", "source_receipt", "cohort_source_set", "support_source", "source_packet", "source_preflight", "attribution_evidence", "lookup_source_evidence", "chrysostom_child_evidence", "basil_child_evidence", "bible_member_evidence", "exclusive_multi_manifest", "config_free_multi_manifest", "mixed_manifest_evidence", "source_profile", "direct_ccel_multi_manifest", "direct_ccel_receipt"}
        if set(row) - allowed:
            raise PipelineError(f"unexpected batch fields for {row.get('work_id')}: {sorted(set(row)-allowed)}")
        if "support_source" in row and not ("source_manifest" in row and "metadata_evidence" in row):
            raise PipelineError(f"{row.get('work_id')} support source requires shared XML evidence")
        if ("source_preflight" in row or "attribution_evidence" in row) and "source_packet" not in row:
            raise PipelineError(f"{row.get('work_id')} LIB-062 evidence requires source packet")
        work_id = safe_identifier(_required(row, "work_id"), field="work_id")
        if work_id in seen:
            raise PipelineError(f"duplicate batch work_id: {work_id}")
        seen.add(work_id)
        form_id = safe_identifier(_required(row, "textual_form_id"), field="textual_form_id")
        append_existing = row.get("append_to_existing_form", False)
        if append_existing is not False and append_existing is not True:
            raise PipelineError(f"{work_id} append_to_existing_form must be a boolean")
        if "append_to_existing_form" in row and append_existing is not True:
            raise PipelineError(f"{work_id} append_to_existing_form must be true when present")
        edition_id = safe_identifier(_required(row, "edition_id"), field="edition_id")
        acquisition_id = safe_identifier(_required(row, "acquisition_id"), field="acquisition_id")
        for kind, identifier in (("forms", form_id), ("editions", edition_id), ("acquisitions", acquisition_id)):
            if kind == "forms" and append_existing:
                continue
            if identifier in occupied[kind]:
                raise PipelineError(f"duplicate global {kind} ID: {identifier}")
            occupied[kind].add(identifier)
        work_path, work_rel = _bound(root, row["work"], f"{work_id} work")
        state_path, state_rel = _bound(root, row["state"], f"{work_id} state")
        expected_work = f"library/works/{work_id}/work.json"
        expected_state = f"library/works/{work_id}/state.json"
        if (work_rel, state_rel) != (expected_work, expected_state):
            raise PipelineError(f"{work_id} sidecar paths do not bind work identity")
        work = load_work(work_path)
        state = load_state(state_path)
        if work["work_id"] != work_id or state["work_id"] != work_id:
            raise PipelineError(f"{work_id} sidecar identity mismatch")
        manifest_rel = shared_volume_rel = config_rel = url_evidence_rel = receipt_rel = source_receipt_rel = None
        member_set = False
        cohort_evidence: list[str] = []
        packet_evidence: list[str] = []
        url = _required(row, "url")
        if "source_child_element" in row and (row["source_child_element"] != "div2"
                or "source_manifest" not in row or "metadata_evidence" not in row):
            raise PipelineError(f"{work_id} div2 child selector requires shared XML manifest and metadata evidence")
        if "mixed_manifest_evidence" in row:
            if row["mixed_manifest_evidence"] is not True or any(name in row for name in (
                    "exclusive_multi_manifest", "config_free_multi_manifest", "bible_member_evidence",
                    "chrysostom_child_evidence", "basil_child_evidence", "lookup_source_evidence",
                    "source_packet", "source_preflight", "attribution_evidence", "source_receipt",
                    "cohort_source_set")):
                raise PipelineError(f"{work_id} mixed-member route has competing evidence")
            retained, source_fields, evidence_paths, packet_evidence = bind_mixed_manifest(root, row, work)
            manifest_rel = row["source_manifest"]["path"]
            config_rel = row["config"]["path"]
            member_set = True
        elif "config_free_multi_manifest" in row:
            if row["config_free_multi_manifest"] is not True or any(name in row for name in (
                    "exclusive_multi_manifest", "bible_member_evidence", "chrysostom_child_evidence",
                    "basil_child_evidence", "lookup_source_evidence", "source_packet",
                    "source_preflight", "attribution_evidence", "source_receipt", "cohort_source_set")):
                raise PipelineError(f"{work_id} config-free member set has competing evidence")
            retained, source_fields, evidence_paths, packet_evidence = bind_config_free_multi(root, row, work)
            manifest_rel = row["source_manifest"]["path"]
            url_evidence_rel = row["url_evidence"]["path"]
            member_set = True
        elif "direct_ccel_multi_manifest" in row:
            if row["direct_ccel_multi_manifest"] is not True or any(name in row for name in (
                    "exclusive_multi_manifest", "config_free_multi_manifest", "mixed_manifest_evidence",
                    "bible_member_evidence", "chrysostom_child_evidence", "basil_child_evidence",
                    "source_packet", "source_receipt", "cohort_source_set")):
                raise PipelineError(f"{work_id} direct CCEL member set has competing evidence")
            retained, source_fields, evidence_paths, packet_evidence = bind_calvin_direct_ccel(root, row, work)
            manifest_rel = row["source_manifest"]["path"]
            config_rel = row["config"]["path"]
            member_set = True
        elif "exclusive_multi_manifest" in row:
            if row["exclusive_multi_manifest"] is not True or any(name in row for name in (
                    "bible_member_evidence", "chrysostom_child_evidence", "basil_child_evidence",
                    "lookup_source_evidence", "source_packet", "source_preflight",
                    "attribution_evidence", "url_evidence", "source_receipt", "cohort_source_set")):
                raise PipelineError(f"{work_id} exclusive multi-member route has competing evidence")
            retained, source_fields, evidence_paths, packet_evidence = bind_exclusive_multi_manifest(root, row, work)
            manifest_rel = row["source_manifest"]["path"]
            config_rel = row["config"]["path"]
            member_set = True
        elif "bible_member_evidence" in row:
            if any(name in row for name in ("source_manifest", "shared_volume_evidence", "source_packet", "source_preflight", "attribution_evidence", "lookup_source_evidence", "url_evidence", "metadata_evidence", "source_receipt", "cohort_source_set", "archive_member", "containing_source", "source_child_element", "support_source", "primary_source", "acquisition_receipt")):
                raise PipelineError(f"{work_id} Bible member evidence has competing source routes")
            retained, source_fields, evidence_paths, packet_evidence = bind_bible_members(root, row, work)
            config_rel = row["config"]["path"] if "config" in row else None
            member_set = True
        elif "acquisition_receipt" in row:
            if any(name in row for name in ("source_manifest", "shared_volume_evidence", "config", "url_evidence", "metadata_evidence", "source_receipt", "cohort_source_set", "source_packet")):
                raise PipelineError(f"{work_id} has competing acquisition evidence branches")
            retained, source_fields, evidence_paths, receipt_rel = _receipt_binding(root, row, work, zip_cache, xml_cache)
        elif "chrysostom_child_evidence" in row:
            if any(name in row for name in ("shared_volume_evidence", "source_packet", "source_preflight", "attribution_evidence", "lookup_source_evidence", "url_evidence", "source_receipt", "cohort_source_set", "archive_member", "source_child_element", "support_source", "primary_sources", "acquisition_receipt")):
                raise PipelineError(f"{work_id} Chrysostom child route has competing source evidence")
            manifest_rel = row["source_manifest"]["path"]
            config_rel = row["config"]["path"]
            retained, source_fields, evidence_paths, packet_evidence = bind_chrysostom_seven(root, row, work)
        elif "basil_child_evidence" in row:
            if any(name in row for name in ("shared_volume_evidence", "source_packet", "source_preflight", "attribution_evidence", "lookup_source_evidence", "url_evidence", "source_receipt", "cohort_source_set", "archive_member", "source_child_element", "support_source", "primary_sources", "acquisition_receipt", "chrysostom_child_evidence")):
                raise PipelineError(f"{work_id} Basil child route has competing source evidence")
            manifest_rel = row["source_manifest"]["path"]
            config_rel = row["config"]["path"]
            retained, source_fields, evidence_paths, packet_evidence = bind_basil_three(root, row, work)
        elif "source_manifest" in row and "config" not in row:
            if any(name in row for name in ("shared_volume_evidence", "source_packet", "source_preflight",
                    "attribution_evidence", "lookup_source_evidence", "source_receipt", "cohort_source_set",
                    "archive_member", "containing_source", "source_child_element", "support_source",
                    "primary_sources", "acquisition_receipt", "chrysostom_child_evidence",
                    "basil_child_evidence", "bible_member_evidence")):
                raise PipelineError(f"{work_id} exclusive manifest has competing source evidence")
            manifest_rel = row["source_manifest"]["path"]
            retained, source_fields, evidence_paths, packet_evidence = bind_exclusive_manifest(root, row, work)
            url_evidence_rel = row["url_evidence"]["path"]
        elif "lookup_source_evidence" in row:
            if any(name in row for name in ("source_manifest", "shared_volume_evidence", "source_packet", "source_preflight", "attribution_evidence", "url_evidence", "metadata_evidence", "source_receipt", "cohort_source_set", "archive_member", "containing_source", "source_child_element", "support_source", "primary_sources", "acquisition_receipt")):
                raise PipelineError(f"{work_id} lookup CCEL route has competing source evidence")
            config_rel = row["config"]["path"]
            retained, source_fields, evidence_paths, packet_evidence = bind_lookup_ccel(root, row, work)
        elif "source_packet" in row:
            if any(name in row for name in ("source_manifest", "shared_volume_evidence", "config", "primary_source", "url_evidence", "metadata_evidence", "source_receipt", "cohort_source_set", "archive_member", "containing_source", "source_child_element", "support_source", "primary_sources")):
                raise PipelineError(f"{work_id} LIB-062 packet has competing source evidence")
            retained, source_fields, evidence_paths, packet_evidence = bind_creeds_packet(root, row, work)
        elif "shared_volume_evidence" in row:
            if any(name in row for name in ("source_manifest", "source_receipt", "url_evidence", "archive_member", "primary_sources", "cohort_source_set")):
                raise PipelineError(f"{work_id} has competing shared-volume evidence branches")
            if "config" not in row or "metadata_evidence" not in row:
                raise PipelineError(f"{work_id} shared-volume config and metadata evidence required")
            retained, evidence_paths, config_rel = _gregory_shared_volume_binding(
                root, row, work, xml_cache, text_cache)
            source_fields = {"source_path": retained[0]["path"], "source_bytes": retained[0]["bytes"],
                             "source_sha256": retained[0]["sha256"], "source_scope": retained[0]["scope"]}
            shared_volume_rel = row["shared_volume_evidence"]["path"]
        else:
            if "source_manifest" not in row or "config" not in row or "archive_member" in row:
                raise PipelineError(f"{work_id} requires exclusive manifest/config route")
            manifest_path, manifest_rel = _bound(root, row["source_manifest"], f"{work_id} source manifest")
            config_path, config_rel = _bound(root, row["config"], f"{work_id} config")
            manifest = load_json(manifest_path)
            config = load_json(config_path)
            manifest_ids = _manifest_config_ids(manifest, root) if manifest.get("contract") == "ocd-source-manifest-v1" else set()
            member_set_declared = "source_receipt" in row
            cohort = "cohort_source_set" in row
            lib028_cohort = cohort and manifest.get("source_id") == "ccel-schaff-npnf2-lib028-three-retained-xml-members"
            shared_xml = "metadata_evidence" in row and not lib028_cohort
            lib054_cohort = cohort and manifest.get("source_id") == "lib054-ten-retained-ccel-puritan-xml"
            owen_cohort = cohort and manifest.get("source_id") in {
                "john-owen-lib050-ten-retained-ccel-xml",
                "john-owen-lib051-ten-retained-ccel-xml",
                "john-owen-lib052-ten-retained-ccel-xml",
            }
            conflicting_cohort_fields = ("source_receipt", "url_evidence", "primary_sources")
            if not lib028_cohort:
                conflicting_cohort_fields += ("metadata_evidence", "containing_source")
            if cohort and any(name in row for name in conflicting_cohort_fields):
                raise PipelineError(f"{work_id} CCEL cohort has competing source evidence branches")
            if lib028_cohort and ("metadata_evidence" not in row or "containing_source" not in row):
                raise PipelineError(f"{work_id} LIB-028 requires metadata and containing-source evidence")
            if member_set_declared:
                if (manifest.get("work_id") != work_id or config.get("resource_id") != work_id
                        or work_id not in manifest_ids):
                    raise PipelineError(f"{work_id} member-set manifest/config work identity differs")
            elif work_id not in manifest_ids or (not shared_xml and not cohort and manifest_ids != {work_id}):
                raise PipelineError(f"{work_id} source manifest identity is not exclusive or shared-child-bound")
            authorities = manifest.get("authorities")
            if not isinstance(authorities, list):
                raise PipelineError(f"{work_id} manifest authorities missing")
            config_auth = [x for x in authorities if isinstance(x, dict) and x.get("path") == config_rel]
            if len(config_auth) != 1 or config_auth[0].get("sha256") != row["config"]["sha256"]:
                raise PipelineError(f"{work_id} config is not bound by current manifest")
            primary = [x for x in authorities if isinstance(x, dict) and x.get("role") == "primary-source"]
            if any(isinstance(x.get("path"), str) and x["path"].partition("#")[0].casefold().endswith(".zip") for x in primary):
                raise PipelineError(f"{work_id} ZIP package cannot be a primary source")
            if "source_receipt" in row:
                if shared_xml or "url_evidence" in row:
                    raise PipelineError(f"{work_id} member set cannot have competing source evidence")
                retained, source_fields, evidence_paths = bind_member_set(
                    root, row, work, manifest, manifest_rel, authorities)
                source_receipt_rel = row["source_receipt"]["path"]
                member_set = True
            else:
                if ("primary_sources" in row or (not cohort and not shared_xml and len(primary) != 1)
                        or row.get("primary_source") not in primary):
                    raise PipelineError(f"{work_id} primary source differs from current manifest")
                source = row["primary_source"]
                source_path = resolve_repo_path(root, source["path"])
                if not source_path.is_file() or source_path.stat().st_size != source["bytes"] or sha256_file(source_path) != source["sha256"]:
                    raise PipelineError(f"{work_id} primary source bytes/hash differ: {source['path']}")
            if config.get("source_url") != url and not (owen_cohort or lib054_cohort):
                if shared_xml or "url_evidence" not in row:
                    raise PipelineError(f"{work_id} URL differs from bound config without URL evidence")
                url_evidence_path, url_evidence_rel = _bound(root, row["url_evidence"], f"{work_id} URL evidence")
                if url not in url_evidence_path.read_text(encoding="utf-8"):
                    raise PipelineError(f"{work_id} URL absent from pinned URL evidence")
            if config.get("language") != row.get("language") and not (owen_cohort or lib054_cohort):
                raise PipelineError(f"{work_id} language differs from bound config")
            if not member_set:
                retained = [{"path": source["path"], "bytes": source["bytes"], "sha256": source["sha256"],
                             "media_type": _required(row, "media_type"), "scope": _required(row, "source_scope")}]
                source_fields = {}
                evidence_paths = [manifest_rel, config_rel, source["path"]]
                if cohort:
                    binder = (bind_lib028_member if lib028_cohort else
                              bind_lib054_member if lib054_cohort else
                              bind_owen_cohort_member if owen_cohort else bind_ccel_cohort_member)
                    cohort_evidence = binder(root, row, work, config, manifest, source)
                    evidence_paths.extend(cohort_evidence)
                    source_fields = {"source_path": source["path"], "source_bytes": source["bytes"],
                                     "source_sha256": source["sha256"], "source_scope": _required(row, "source_scope")}
                if shared_xml:
                    evidence_paths = _shared_xml_child_binding(
                        root, row, work, config, manifest_rel, config_rel, source, xml_cache, text_cache,
                        child_tag=row.get("source_child_element", "div1"))
                    source_fields = {"source_path": source["path"], "source_bytes": source["bytes"],
                                     "source_sha256": source["sha256"], "source_scope": _required(row, "source_scope")}
                    assigned_support = [item for item in primary if isinstance(item.get("work_ids"), list)
                                        and work_id in item["work_ids"] and item != source]
                    support = row.get("support_source")
                    if len(assigned_support) > 1 or (support is None) != (not assigned_support):
                        raise PipelineError(f"{work_id} shared XML support-source assignment mismatch")
                    if assigned_support:
                        item = assigned_support[0]
                        if (support != item or not isinstance(item.get("path"), str)
                                or not item["path"].startswith("raw/ccel/npnf2/")
                                or not isinstance(item.get("bytes"), int) or isinstance(item["bytes"], bool)
                                or not isinstance(item.get("sha256"), str)):
                            raise PipelineError(f"{work_id} shared XML support source differs from manifest")
                        support_path = resolve_repo_path(root, item["path"])
                        if (not support_path.is_file() or support_path.stat().st_size != item["bytes"]
                                or sha256_file(support_path) != item["sha256"]):
                            raise PipelineError(f"{work_id} shared XML support bytes/hash differ")
                        retained.append({"path": item["path"], "bytes": item["bytes"],
                                         "sha256": item["sha256"], "media_type": "image/png",
                                         "scope": "Supplemental source image referenced by the retained XML; historical image snapshot bytes remain unknown."})
                        evidence_paths.append(item["path"])
                elif "support_source" in row:
                    raise PipelineError(f"{work_id} support source requires shared XML evidence")
                if url_evidence_rel is not None:
                    evidence_paths.append(url_evidence_rel)
        if shared_volume_rel is not None or ("metadata_evidence" in row and "source_manifest" in row and "containing_source" in row):
            locator = row["containing_source"]["locator"]
            if locator in seen_shared_locators:
                raise PipelineError(f"duplicate shared XML child locator: {locator}")
            seen_shared_locators.add(locator)
        existing_forms = [form for form in work["textual_forms"] if form["textual_form_id"] == form_id]
        if append_existing:
            if len(existing_forms) != 1:
                raise PipelineError(f"{work_id} existing textual form is absent or ambiguous: {form_id}")
            if "language" in row:
                known_languages = [existing_forms[0].get("language")]
                known_languages.extend(edition.get("language") for edition in existing_forms[0]["editions"])
                if any(language is not None and language != row["language"] for language in known_languages):
                    raise PipelineError(f"{work_id} edition language conflicts with existing textual form")
        elif existing_forms:
            raise PipelineError(f"{work_id} textual form ID already exists")
        if any(t["target_id"] in {edition_id, acquisition_id} for t in state["targets"]):
            raise PipelineError(f"{work_id} target ID already exists")
        edition_dir = f"library/works/{work_id}/forms/{form_id}/editions/{edition_id}"
        acquisition_rel = f"{edition_dir}/acquisitions/{acquisition_id}.json"
        if (root / acquisition_rel).exists() or (root / edition_dir).exists():
            raise PipelineError(f"{work_id} target sidecar path already exists")
        edition = {"edition_id": edition_id, "title": _required(row, "edition_title"), "acquisition_ids": [acquisition_id]}
        if "language" in row:
            edition["language"] = row["language"]
        if "containing_source" in row:
            edition["containing_source"] = row["containing_source"]
        revised_work = copy.deepcopy(work)
        if receipt_rel is not None and receipt_rel not in revised_work["evidence"]:
            revised_work["evidence"].append(receipt_rel)
        if receipt_rel is not None and receipt_rel.startswith("raw/gutenberg/"):
            revised_work["evidence"].extend(path for path in evidence_paths if path not in revised_work["evidence"])
        if member_set:
            revised_work["evidence"].extend(path for path in evidence_paths if path not in revised_work["evidence"])
        if append_existing:
            revised_form = next(form for form in revised_work["textual_forms"] if form["textual_form_id"] == form_id)
            revised_form["editions"].append(edition)
        else:
            form = {"textual_form_id": form_id, "editions": [edition]}
            if "language" in row:
                form["language"] = row["language"]
            revised_work["textual_forms"].append(form)
        validate_identity_update(work, revised_work)
        validate_record("work", revised_work, context=f"{work_id} proposed work")
        acquisition = {"schema_version": "2.0", "acquisition_id": acquisition_id, "edition_id": edition_id,
            "provider": _required(row, "provider"), "url": url, "retained_files": retained, **source_fields}
        if "warnings" in row:
            acquisition["warnings"] = row["warnings"]
        member_set_rel = None
        member_set_value = None
        if member_set:
            member_set_rel = f"{edition_dir}/source-member-set.json"
            acquisition["source_path"] = member_set_rel
            member_set_raw = source_member_set_bytes(acquisition)
            member_set_value = json.loads(member_set_raw)
            acquisition["source_bytes"] = len(member_set_raw)
            acquisition["source_sha256"] = hashlib.sha256(member_set_raw).hexdigest()
            evidence_paths.append(member_set_rel)
        validate_record("acquisition", acquisition, context=f"{work_id} proposed acquisition")
        revised_state = copy.deepcopy(state)
        revised_state["targets"].extend([
            {"target_id": acquisition_id, "target_type": "acquisition", "stage": "acquired", "updated_at": now, "evidence": evidence_paths + [acquisition_rel]},
            {"target_id": edition_id, "target_type": "edition", "stage": "acquired", "updated_at": now, "evidence": evidence_paths + [acquisition_rel]},
        ])
        validate_record("state", revised_state, context=f"{work_id} proposed state")
        output = [(work_rel, revised_work), (state_rel, revised_state), (acquisition_rel, acquisition)]
        if member_set_rel is not None:
            output.append((member_set_rel, member_set_value))
        results.append({"work_id": work_id, "source_manifest": manifest_rel,
            "shared_volume_evidence": shared_volume_rel, "config": config_rel,
            "metadata_evidence": row["metadata_evidence"]["path"] if "metadata_evidence" in row else None,
            "url_evidence": url_evidence_rel,
            "acquisition_receipt": receipt_rel, "source_receipt": source_receipt_rel,
            "cohort_evidence": cohort_evidence, "packet_evidence": packet_evidence, "output": output})
    return sorted(results, key=lambda x: x["work_id"])


def stage(root: Path, packet_path: Path, destination: Path, now: str) -> dict[str, Any]:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists():
        raise PipelineError(f"stage destination already exists: {destination}")
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise PipelineError("stage destination must be outside repository")
    packet = load_json(packet_path)
    results = prepare(root, packet, now)
    receipt = {"contract": "ocd-library-sidecar-stage-v1", "packet_sha256": sha256_file(packet_path),
               "authority": "Proposed sidecars only; no canonical mutations, fidelity finding, acceptance, rights, or publication decision.", "entries": []}
    for result in results:
        entry = {"work_id": result["work_id"], "source_manifest": result["source_manifest"],
                 "shared_volume_evidence": result["shared_volume_evidence"], "config": result["config"],
                 "acquisition_receipt": result["acquisition_receipt"], "source_receipt": result["source_receipt"],
                 "cohort_evidence": result["cohort_evidence"], "packet_evidence": result["packet_evidence"], "files": []}
        for rel, value in result["output"]:
            existing = root / rel
            entry["files"].append({"path": rel, "before_sha256": sha256_file(existing) if existing.is_file() else None,
                                   "proposed_sha256": hashlib.sha256(canonical_bytes(value)).hexdigest()})
        receipt["entries"].append(entry)
    destination.mkdir(parents=True)
    storage_config = root / ".ocd-storage.json"
    if storage_config.is_file():
        shutil.copy2(storage_config, destination / ".ocd-storage.json")
    for result in results:
        old_work_root = root / "library/works" / result["work_id"]
        staged_work_root = destination / "library/works" / result["work_id"]
        shutil.copytree(_io_path(old_work_root), _io_path(staged_work_root))
        for rel in (result["source_manifest"], result["shared_volume_evidence"], result["config"],
                    result["metadata_evidence"], result["url_evidence"], result["acquisition_receipt"],
                    result["source_receipt"], *result["cohort_evidence"], *result["packet_evidence"]):
            if rel is not None and not rel.startswith(("raw/", "reports/", "exports/")):
                target = _io_path(destination / rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / rel, target)
    for result in results:
        for rel, value in result["output"]:
            write_json(_io_path(destination / rel), value)
    write_json(_io_path(destination / "receipt.json"), receipt)
    for result in results:
        work_id = result["work_id"]
        acquisition_rel = result["output"][2][0]
        validate_acquisition(_io_path(destination / acquisition_rel), root=_io_path(destination))
        validate_state(_io_path(destination / f"library/works/{work_id}/state.json"), root=_io_path(destination))
    return receipt


def apply_staged(root: Path, packet_path: Path, destination: Path) -> dict[str, Any]:
    """Install a validated staged batch as per-work guarded transactions.

    All entries are preflighted before the first mutation. Each work swap has
    its own retained journal and automatic rollback on validation failure.
    """
    root, destination = root.resolve(), destination.resolve()
    receipt = load_json(destination / "receipt.json")
    if receipt.get("contract") != "ocd-library-sidecar-stage-v1" or receipt.get("packet_sha256") != sha256_file(packet_path):
        raise PipelineError("staged receipt does not bind current packet")
    packet = load_json(packet_path)
    first_work_id = packet["entries"][0]["work_id"]
    staged_state = load_state(_io_path(destination / f"library/works/{first_work_id}/state.json"))
    staged_now = staged_state["targets"][-1]["updated_at"]
    prepared = prepare(root, packet, staged_now)
    entries = {entry["work_id"]: entry for entry in receipt.get("entries", [])}
    if set(entries) != {entry["work_id"] for entry in prepared}:
        raise PipelineError("staged receipt work set differs from packet")
    for entry in prepared:
        wid = entry["work_id"]
        actual = {item["path"]: item for item in entries[wid]["files"]}
        if set(actual) != {rel for rel, _ in entry["output"]}:
            raise PipelineError(f"{wid} staged receipt file set differs")
        for rel, proposed in entry["output"]:
            item = actual[rel]
            expected_before = sha256_file(root / rel) if (root / rel).is_file() else None
            if item["before_sha256"] != expected_before:
                raise PipelineError(f"{wid} current sidecar changed before apply: {rel}")
            staged = _io_path(destination / rel)
            if sha256_file(staged) != item["proposed_sha256"]:
                raise PipelineError(f"{wid} staged sidecar changed: {rel}")
            if hashlib.sha256(canonical_bytes(proposed)).hexdigest() != item["proposed_sha256"]:
                raise PipelineError(f"{wid} staged sidecar differs from reviewed packet: {rel}")
        validate_acquisition(_io_path(destination / entry["output"][2][0]), root=_io_path(destination))
        validate_state(_io_path(destination / f"library/works/{wid}/state.json"), root=_io_path(destination))
        before_tree = _files(root / "library/works" / wid)
        after_tree = _files(destination / "library/works" / wid)
        if any(after_tree.get(rel) != digest for rel, digest in before_tree.items() if rel not in {"work.json", "state.json"}):
            raise PipelineError(f"{wid} stage changes unrelated work files")
        for rel, digest in after_tree.items():
            if rel not in {"work.json", "state.json"} and rel not in {Path(item["path"]).relative_to(Path("library/works") / wid).as_posix() for item in entries[wid]["files"]} and rel not in before_tree:
                raise PipelineError(f"{wid} stage adds unreviewed file: {rel}")
    installed = []
    operation_root = root / "library" / ".sidecar-operations"
    for entry in prepared:
        wid = entry["work_id"]
        target = root / "library/works" / wid
        source = destination / "library/works" / wid
        with acquire_jsonl_lock(target, acquire_timeout=30.0):
            before_tree = _files(target)
            if sha256_file(target / "work.json") != entries[wid]["files"][0]["before_sha256"]:
                raise PipelineError(f"{wid} changed during batch apply")
            if sha256_file(target / "state.json") != entries[wid]["files"][1]["before_sha256"]:
                raise PipelineError(f"{wid} state changed during batch apply")
            after_tree = _files(source)
            if any(after_tree.get(rel) != digest for rel, digest in before_tree.items() if rel not in {"work.json", "state.json"}):
                raise PipelineError(f"{wid} unrelated file changed before swap")
            operation = operation_root / ("sidecar-" + uuid.uuid4().hex[:16])
            operation.mkdir(parents=True)
            incoming, backup = operation / "incoming", operation / "previous"
            journal = {"contract": "ocd-library-sidecar-operation-v1", "work_id": wid, "phase": "prepared", "before": before_tree, "after": after_tree}
            write_json(operation / "operation.json", journal)
            shutil.copytree(_io_path(source), _io_path(incoming))
            if _files(incoming) != after_tree or _files(target) != before_tree:
                raise PipelineError(f"{wid} changed while preparing incoming generation")
            previous_moved = False
            new_live = False
            try:
                target.rename(backup)
                previous_moved = True
                journal["phase"] = "previous-moved"
                write_json(operation / "operation.json", journal)
                incoming.rename(target)
                new_live = True
                journal["phase"] = "new-live"
                write_json(operation / "operation.json", journal)
                validate_acquisition(_io_path(root / entry["output"][2][0]), root=_io_path(root))
                validate_state(_io_path(target / "state.json"), root=_io_path(root))
                if _files(target) != after_tree:
                    raise PipelineError(f"{wid} installed tree hash mismatch")
                journal["phase"] = "complete"
                write_json(operation / "operation.json", journal)
            except Exception as original_error:
                # Restoration must also run for unexpected validation/I/O errors.
                # A failed first rename has not displaced canonical authority.
                if not previous_moved:
                    journal["phase"] = "failed-before-swap"
                    write_json(operation / "operation.json", journal)
                    raise
                try:
                    if new_live:
                        target.rename(operation / "failed")
                    if not backup.is_dir():
                        raise PipelineError(f"{wid} rollback backup missing: {backup}")
                    backup.rename(target)
                    journal["phase"] = "rolled-back"
                    write_json(operation / "operation.json", journal)
                except Exception as rollback_error:
                    journal["phase"] = "recovery-required"
                    journal["rollback_error"] = str(rollback_error)
                    write_json(operation / "operation.json", journal)
                    raise PipelineError(f"{wid} apply failed and rollback requires recovery: {operation}") from rollback_error
                raise original_error
            installed.append({"work_id": wid, "operation": str(operation), "before": before_tree, "after": after_tree})
    result = {"contract": "ocd-library-sidecar-apply-receipt-v1", "packet_sha256": sha256_file(packet_path), "stage_receipt_sha256": sha256_file(destination / "receipt.json"), "installed": installed}
    write_json(destination / "apply-receipt.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true", help="guardedly install a prevalidated stage")
    args = parser.parse_args()
    try:
        if args.apply:
            result = apply_staged(args.repository_root, args.packet, args.destination)
            print(json.dumps({"installed": len(result["installed"]), "receipt": str(args.destination / "apply-receipt.json")}, sort_keys=True))
            return 0
        receipt = stage(args.repository_root, args.packet, args.destination,
                        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"sidecar staging failed: {exc}\n")
    print(json.dumps({"destination": str(args.destination), "works": len(receipt["entries"]), "files": sum(len(x["files"]) for x in receipt["entries"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
