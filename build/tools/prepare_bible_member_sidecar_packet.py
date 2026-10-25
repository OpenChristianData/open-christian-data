"""Prepare exact, stage-only acquisition accounting for five retained Bible editions."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file
from ocd_kernel.tei.install_accepted import _io_path


IDS = (
    "anderson-1864-new-testament",
    "brenton-septuagint",
    "original-douay-rheims",
    "revised-version-with-apocrypha",
    "world-english-bible-classic",
)
BASE = "plans/2026-09-22-source-preflight"
EVIDENCE = f"{BASE}/five-bible-member-evidence-20260926.json"
PACKET = f"{BASE}/five-bible-member-sidecar-packet-20260926.json"

PROFILES = {
    "anderson-1864-new-testament": (
        "BibleCorps", "Pinned BibleCorps Anderson 1864 USFM electronic witness",
        ["BibleCorps identifies the retained translation as public domain; publication rights still need separate review.",
         "The retained printed witness has an 1865 title page and 1864 copyright and preface; exact printed-edition correspondence remains for human review."],
    ),
    "brenton-septuagint": (
        "eBible.org", "Corrected eBible eng-Brenton electronic USFM edition",
        ["The retained eBible edition identifies Brenton's translation as public domain; publication rights still need separate review.",
         "The official PDF is a generated rendering witness, not an independent historical print edition or transformation authority."],
    ),
    "original-douay-rheims": (
        "janvier-s/original-douay-rheims", "Original Douay-Rheims structured release v1.0",
        ["The retained release declares CC0 1.0 for its structured text; historical witness fidelity and publication review remain separate.",
         "This original Rheims/Douai translation is distinct from the Challoner revision. The release claims 73 books but retains 77 tagged and USFM files, including extra Esdras/Manasses material and a duplicate Prayer of Manasses filename; no normalization is implied."],
    ),
    "revised-version-with-apocrypha": (
        "eBible.org", "eBible ENGRV5 complete Revised Version with Apocrypha USFM edition",
        ["The retained eBible edition is identified as public domain; publication rights still need separate review.",
         "The electronic edition and retained 1895/1913 print scans are distinct witnesses; exact print equivalence is not claimed. Baruch chapter 6 is source-labeled Epistle of Jeremy and is not a separate source file."],
    ),
    "world-english-bible-classic": (
        "eBible.org", "eBible 2020 stable World English Bible Classic USFM edition",
        ["eBible identifies the unchanged WEB text as public domain but reserves the trademarked World English Bible name for faithful copies; any changed text requires separate naming and publication review.",
         "The retained USFM package is the 2020 stable electronic edition; no TEI reconstruction or human acceptance is implied."],
    ),
}


def _ref(root: Path, relative: str) -> dict[str, str]:
    path = resolve_repo_path(root, relative)
    if not path.is_file():
        raise PipelineError(f"missing evidence file: {relative}")
    return {"path": relative, "sha256": sha256_file(path)}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise PipelineError(f"refusing to overwrite evidence: {path}")
    path.write_bytes((json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))


def _entry(root: Path, wid: str) -> dict:
    work = _ref(root, f"library/works/{wid}/work.json")
    state = _ref(root, f"library/works/{wid}/state.json")
    config_ref = None if wid == "world-english-bible-classic" else _ref(root, f"sources/structured-text/{wid}/config.json")
    if config_ref is None:
        receipt_rel = "raw/ebible/eng-web/usfm/acquisition-receipt.json"
        receipt = _json(resolve_repo_path(root, receipt_rel))
        source_root = "raw/ebible/eng-web/usfm/members"
        package_rel = receipt["package"]["path"]
        source_url = receipt["source_url"]
    else:
        receipt_rel = None
        receipt = None
        config = _json(resolve_repo_path(root, config_ref["path"]))
        if config["resource_id"] != wid:
            raise PipelineError(f"{wid} config identity differs")
        source_root = config["source_root"]
        package_rel = config["source_file"] if "source_file" in config else config["authority"]["archive_path"]
        source_url = config.get("source_download_url", config["source_url"])
    source_dir = resolve_repo_path(root, source_root)
    package_path = resolve_repo_path(root, package_rel)
    if not source_dir.is_dir() or not package_path.is_file():
        raise PipelineError(f"{wid} extracted source tree or package missing")
    provider, edition_title, warnings = PROFILES[wid]
    text: list[dict] = []
    support: list[dict] = []
    with zipfile.ZipFile(_io_path(package_path)) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        if len(names) != len(set(names)):
            raise PipelineError(f"{wid} repeated archive name")
        for path in sorted((path for path in source_dir.rglob("*") if path.is_file()), key=lambda path: path.relative_to(source_dir).as_posix()):
            subpath = path.relative_to(source_dir).as_posix()
            if wid == "anderson-1864-new-testament":
                archive_name = source_dir.parent.name + "/USFM/" + subpath
            elif wid == "original-douay-rheims":
                archive_name = source_dir.name + "/" + subpath
            else:
                archive_name = subpath
            if archive_name not in names:
                raise PipelineError(f"{wid} extracted member absent from package: {subpath}")
            with archive.open(archive_name) as stream:
                digest = hashlib.sha256()
                size = 0
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            if path.stat().st_size != size or sha256_file(path) != digest.hexdigest():
                raise PipelineError(f"{wid} extracted member differs from package: {subpath}")
            suffix = path.suffix.lower()
            media = {".json": "application/json", ".usfm": "text/plain", ".sfm": "text/plain",
                     ".htm": "text/html", ".css": "text/css", ".asc": "text/plain",
                     ".md": "text/markdown", "": "text/plain"}.get(suffix)
            if media is None:
                raise PipelineError(f"{wid} unknown extracted member media: {subpath}")
            member = {"path": source_root.rstrip("/") + "/" + subpath,
                      "archive_member": archive_name, "bytes": size,
                      "sha256": digest.hexdigest(), "media_type": media}
            if suffix in {".usfm", ".sfm", ".json"}:
                text.append(member)
            else:
                support.append(member)
    if wid == "anderson-1864-new-testament" and len(text) != 30:
        raise PipelineError("Anderson USFM sequence changed")
    if wid == "brenton-septuagint" and (len(text), len(support)) != (60, 3):
        raise PipelineError("Brenton source inventory changed")
    if wid == "original-douay-rheims" and (len(text), len(support)) != (651, 3):
        raise PipelineError("Douay source inventory changed")
    if wid == "revised-version-with-apocrypha" and (len(text), len(support)) != (80, 3):
        raise PipelineError("Revised Version source inventory changed")
    if wid == "world-english-bible-classic" and (len(text), len(support)) != (83, 3):
        raise PipelineError("WEB source inventory changed")
    if receipt is not None and (receipt["package"]["sha256"] != sha256_file(package_path)
                                or receipt["verification"]["member_count"] != len(names)):
        raise PipelineError(f"{wid} retained acquisition receipt differs")
    scope = (f"Complete {len(text)}-member extracted electronic textual set under {source_root}. "
             f"ZIP {package_rel} is the acquisition package, not a text source. "
             "Other extracted files are support evidence. Source accounting does not establish faithful TEI, human acceptance, rights clearance, or publication.")
    return {"work_id": wid, "work": work, "state": state, "config": config_ref,
            "source_root": source_root, "source_url": source_url,
            "package": {"path": package_rel, "bytes": package_path.stat().st_size,
                        "sha256": sha256_file(package_path)},
            "archive_members": names, "textual_members": text, "support_members": support,
            "acquisition_receipt": _ref(root, receipt_rel) if receipt_rel else None,
            "provider": provider, "edition_title": edition_title,
            "source_scope": scope, "warnings": warnings}


def prepare(root: Path) -> tuple[dict, dict]:
    evidence = {"contract": "ocd-bible-member-evidence-v1",
                "entries": [_entry(root, wid) for wid in IDS]}
    _write(root / EVIDENCE, evidence)
    evidence_ref = _ref(root, EVIDENCE)
    rows = []
    for entry in evidence["entries"]:
        wid = entry["work_id"]
        row = {"work_id": wid, "work": entry["work"], "state": entry["state"],
               "bible_member_evidence": evidence_ref,
               "primary_sources": entry["textual_members"],
               "textual_form_id": wid + "-retained-en",
               "edition_id": wid + "-electronic",
               "acquisition_id": wid + "-acquired",
               "edition_title": entry["edition_title"], "provider": entry["provider"],
               "url": entry["source_url"], "language": "en",
               "source_scope": entry["source_scope"], "warnings": entry["warnings"]}
        if entry["config"] is not None:
            row["config"] = entry["config"]
        rows.append(row)
    packet = {"contract": "ocd-library-sidecar-batch-v1", "entries": rows}
    _write(root / PACKET, packet)
    return evidence, packet


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    evidence, packet = prepare(root)
    print(json.dumps({"evidence_path": EVIDENCE, "evidence_sha256": sha256_file(root / EVIDENCE),
                      "packet_path": PACKET, "packet_sha256": sha256_file(root / PACKET),
                      "works": len(packet["entries"]),
                      "textual_members": sum(len(x["textual_members"]) for x in evidence["entries"])}, sort_keys=True))
