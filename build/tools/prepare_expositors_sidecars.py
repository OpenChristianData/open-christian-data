"""Stage exact Expositor's Bible CCEL members under existing catalog identities.

The 22 author-cohort IDs are retained for accounting. Each of the 39 XML
members receives a distinct provisional textual form, electronic edition,
and acquisition. The source books are not asserted to be variants of one work,
nor to share a print edition. This tool never installs canonical sidecars.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file, write_json
from ocd_kernel.library.identities import load_work, validate_identity_update, validate_record
from ocd_kernel.library.state import load_state
from ocd_kernel.tei.install_accepted import _io_path


CONTRACT = "ocd-expositors-39-member-sidecar-stage-v1"
PROFILE_DIR = "sources/commentaries/expositors-bible"
PACKET_REL = "plans/2026-09-22-source-preflight/expositors-39-member-sidecar-packet-20260926.json"
FAMILIES = (33, 34, 35, 36)
EXPECTED_MEMBERS = {33: 12, 34: 10, 35: 9, 36: 8}
EXPECTED_WORKS = {33: 5, 34: 8, 35: 5, 36: 4}
RIGHTS_REL = f"{PROFILE_DIR}/ccel-permission.md"
ATTRIBUTION_REL = "data/commentaries/expositors-bible/README.md"
OUTSIDE_PROFILE = {
    "ball_expositorjer1.xml": ("no canonical Ball work ID in the current library", None),
    "chadwick_expositor2.xml": ("separate Chadwick source accounting", "expositors-bible--g-a-chadwick"),
    "chadwick_mark.xml": ("separate Chadwick source accounting", "expositors-bible--g-a-chadwick"),
    "cox_s_expositoreccl.xml": ("no canonical Cox work ID in the current library", None),
    "dods_expositorjohn2.xml": ("held companion volume outside LIB-035 pinned claim", "expositors-bible--marcus-dods"),
    "rainy_expositorphil.xml": ("no canonical Rainy work ID in the current library", None),
    "smith_ga_expositorisa1.xml": ("held companion volume outside LIB-034 pinned claim", "expositors-bible--george-adam-smith"),
    "stokes_expositoracts1.xml": ("held companion volume outside LIB-034 pinned claim", "expositors-bible--g-t-stokes"),
}
HELD_COMPANIONS = {name for name, (_, wid) in OUTSIDE_PROFILE.items()
                   if wid in {"expositors-bible--marcus-dods", "expositors-bible--george-adam-smith",
                              "expositors-bible--g-t-stokes"}}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(_io_path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PipelineError(f"expected JSON object: {path}")
    return value


def _exact_file(root: Path, relative: str, size: int, digest: str) -> Path:
    path = resolve_repo_path(root, relative)
    if not path.is_file() or path.stat().st_size != size or sha256_file(path) != digest:
        raise PipelineError(f"retained authority missing or changed: {relative}")
    return path


def _text(node: etree._Element | None) -> str:
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def _header(source_path: Path) -> dict[str, str]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        tree = etree.parse(str(_io_path(source_path)), parser)
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"cannot parse retained XML {source_path}: {exc}") from exc
    root = tree.getroot()
    if root.tag != "ThML" or len(root.findall("ThML.head")) != 1 or len(root.findall("ThML.body")) != 1:
        raise PipelineError(f"retained XML lacks one ThML head/body: {source_path}")
    head = root.find("ThML.head")
    assert head is not None
    electronic = head.find("electronicEdInfo")
    if electronic is None:
        raise PipelineError(f"retained XML lacks electronic edition info: {source_path}")
    url = _text(electronic.find('./DC/DC.Identifier[@scheme="URL"]'))
    authors = [_text(node) for node in electronic.findall('./DC/DC.Creator[@sub="Author"]')]
    return {
        "title": _text(electronic.find("./DC/DC.Title")),
        "author": authors[0] if authors else "",
        "url": "https://www.ccel.org" + url if url.startswith("/") else "",
        "book_id": _text(electronic.find("bookID")),
        "print_source": _text(head.find("./printSourceInfo/published")),
        "language": _text(electronic.find('./DC/DC.Language[@scheme="ISO639-3"]')),
        "status": _text(electronic.find("status")),
        "editorial_comments": _text(electronic.find("editorialComments")),
    }


def _family_members(root: Path, number: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    stem = f"{PROFILE_DIR}/lib0{number}"
    manifest_rel = f"{stem}.source-manifest.json"
    manifest_path = resolve_repo_path(root, manifest_rel)
    manifest = _json(manifest_path)
    primary = [item for item in manifest.get("authorities", []) if item.get("role") == "primary-source"]
    profiles = [item for item in manifest.get("authorities", [])
                if item.get("role") == "complete-source-feature-profile"]
    identity = [item for item in manifest.get("authorities", [])
                if item.get("role") == "work-identity-binding"]
    if (manifest.get("contract") != "ocd-source-manifest-v1"
            or len(primary) != EXPECTED_MEMBERS[number]
            or len(profiles) != 1 or len(identity) != EXPECTED_WORKS[number]):
        raise PipelineError(f"LIB-0{number} source-manifest census differs")
    profile_ref = profiles[0]
    profile_path = _exact_file(root, profile_ref["path"], profile_ref["bytes"], profile_ref["sha256"])
    profile = _json(profile_path)
    included = profile.get("included_members")
    work_rows = profile.get("works")
    if (profile.get("ticket") != f"LIB-0{number}"
            or not isinstance(included, list) or len(included) != len(primary)
            or not isinstance(work_rows, list) or len(work_rows) != len(identity)):
        raise PipelineError(f"LIB-0{number} profile membership differs")
    by_name = {item["name"]: item for item in primary}
    by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows: list[dict[str, Any]] = []
    for member in included:
        authority = by_name.get(member.get("authority_name"))
        if (authority is None or member.get("work_id") not in {row.get("work_id") for row in work_rows}
                or any(member.get(key) != authority.get(key) for key in ("bytes", "sha256"))):
            raise PipelineError(f"LIB-0{number} profile member differs from source manifest")
        relative = authority["path"]
        if not relative.startswith("raw/ccel/expositors-bible/") or not relative.endswith(".xml"):
            raise PipelineError(f"LIB-0{number} primary member path differs: {relative}")
        source_path = _exact_file(root, relative, authority["bytes"], authority["sha256"])
        header = _header(source_path)
        if (header["title"] != member.get("source_title")
                or header["author"] != member.get("source_author")
                or header["print_source"] != member.get("print_source")
                or header["url"] != member.get("source_url")
                or header["language"] != "eng"
                or header["book_id"] != header["url"].removesuffix(".html").rsplit("/", 1)[-1]):
            raise PipelineError(f"retained XML header/profile identity differs: {relative}")
        row = {"work_id": member["work_id"], "member_id": member["member_id"],
               "path": relative, "bytes": authority["bytes"], "sha256": authority["sha256"],
               "title": header["title"], "source_author": header["author"],
               "source_url": header["url"], "print_source": header["print_source"],
               "proofreading_status": header["status"],
               "editorial_comments_present": bool(header["editorial_comments"]),
               "manifest": {"path": manifest_rel, "sha256": sha256_file(manifest_path)},
               "profile": {"path": profile_ref["path"], "sha256": profile_ref["sha256"]}}
        rows.append(row)
        by_work[member["work_id"]].append(row)
    if len({row["member_id"] for row in rows}) != len(rows) or set(by_name) != {m["authority_name"] for m in included}:
        raise PipelineError(f"LIB-0{number} profile omits or duplicates primary members")
    identity_paths = {item["path"]: item for item in identity}
    for work_row in work_rows:
        wid = work_row["work_id"]
        relative = f"{stem}/{wid}/config.json"
        claim = identity_paths.get(relative)
        if claim is None or len(by_work[wid]) != work_row.get("member_count"):
            raise PipelineError(f"LIB-0{number} work/member or identity count differs: {wid}")
        config = _json(_exact_file(root, relative, claim["bytes"], claim["sha256"]))
        if config.get("work_id") != wid:
            raise PipelineError(f"LIB-0{number} config work identity differs: {wid}")
    for relative in (RIGHTS_REL, ATTRIBUTION_REL):
        claims = [item for item in manifest["authorities"] if item.get("path") == relative]
        if len(claims) != 1:
            raise PipelineError(f"LIB-0{number} rights/attribution authority missing: {relative}")
        _exact_file(root, relative, claims[0]["bytes"], claims[0]["sha256"])
    return rows, [{"path": manifest_rel, "sha256": sha256_file(manifest_path)},
                  {"path": profile_ref["path"], "sha256": profile_ref["sha256"]}]


def audit(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    references: list[dict[str, str]] = []
    for number in FAMILIES:
        family_rows, family_refs = _family_members(root, number)
        rows.extend(family_rows)
        references.extend(family_refs)
    if len(rows) != 39 or len({row["work_id"] for row in rows}) != 22:
        raise PipelineError("Expositor member/work census differs")
    if len({row["path"] for row in rows}) != 39:
        raise PipelineError("Expositor source file assigned more than once")
    return rows, references


def outside_profile(root: Path, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    directory = resolve_repo_path(root, "raw/ccel/expositors-bible")
    actual = {path.name for path in directory.glob("*.xml")}
    selected_names = {Path(row["path"]).name for row in selected}
    if len(actual) != 47 or actual - selected_names != set(OUTSIDE_PROFILE):
        raise PipelineError("Expositor 47-file retained directory or eight outside-profile members differ")
    result = []
    for name, (disposition, wid) in sorted(OUTSIDE_PROFILE.items()):
        relative = f"raw/ccel/expositors-bible/{name}"
        path = resolve_repo_path(root, relative)
        header = _header(path)
        result.append({"path": relative, "bytes": path.stat().st_size,
                       "sha256": sha256_file(path), "source_title": header["title"],
                       "source_author": header["author"], "work_id": wid,
                       "disposition": disposition})
    return result


def _credit(wid: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"# Source and credit — {wid}", "", "The exact retained electronic witnesses are:", ""]
    for row in rows:
        lines.append(f"- {row['title']} — {row['path']} (SHA-256 {row['sha256']})")
    lines.extend(["", "Sourced via CCEL.org. See the source-local CCEL permission note and",
                  "the Expositor's Bible attribution README. CCEL's conditions apply to",
                  "its files and formatting; this notice does not grant redistribution rights.",
                  "", "The existing catalog ID groups an author's separate books or volumes.",
                  "These member bindings do not establish one intellectual work, one print",
                  "edition, accepted TEI, or publication readiness.", ""])
    held = [name for name in sorted(HELD_COMPANIONS) if OUTSIDE_PROFILE[name][1] == wid]
    if held:
        lines.extend(["The following retained companion volume is outside this pinned source",
                      "profile and remains unaccounted in this stage:", "",
                      *(f"- raw/ccel/expositors-bible/{name}" for name in held), ""])
    return "\n".join(lines)


def stage(root: Path, destination: Path) -> dict[str, Any]:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists():
        raise PipelineError(f"stage destination already exists: {destination}")
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise PipelineError("stage destination must be outside repository")
    rows, references = audit(root)
    outside = outside_profile(root, rows)
    packet_path = root / PACKET_REL
    if packet_path.exists():
        raise PipelineError(f"packet already exists: {packet_path}")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["work_id"]].append(row)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    files: list[tuple[str, dict[str, Any] | str, str | None]] = []
    before: dict[str, dict[str, str]] = {}
    for wid, members in sorted(grouped.items()):
        work_rel, state_rel = (f"library/works/{wid}/{name}.json" for name in ("work", "state"))
        work_path, state_path = root / work_rel, root / state_rel
        before[wid] = {"work": sha256_file(work_path), "state": sha256_file(state_path)}
        work, state = load_work(work_path), load_state(state_path)
        if work["work_id"] != wid or state["work_id"] != wid or work["textual_forms"] or state["targets"]:
            raise PipelineError(f"{wid} is no longer an identity-only author cohort")
        new_work, new_state = copy.deepcopy(work), copy.deepcopy(state)
        credit_rel = f"library/works/{wid}/SOURCE_CREDIT.md"
        if resolve_repo_path(root, credit_rel).exists():
            raise PipelineError(f"source credit already exists: {credit_rel}")
        for row in members:
            member_id = row["member_id"]
            form_id = f"{wid}--{member_id}--retained-en"
            edition_id = f"{wid}--{member_id}--ccel-electronic"
            acquisition_id = f"{wid}--{member_id}--acquired"
            acq_rel = (f"library/works/{wid}/forms/{form_id}/editions/{edition_id}"
                       f"/acquisitions/{acquisition_id}.json")
            if resolve_repo_path(root, acq_rel).exists():
                raise PipelineError(f"acquisition already exists: {acq_rel}")
            scope = (f"Complete retained CCEL ThML XML file for {row['title']}. "
                     "This author-cohort catalog ID does not resolve independent work or "
                     "print-edition identity; source accounting only.")
            warnings = ["Existing author-cohort catalog identity groups separate Expositor's Bible books or volumes. "
                        "Each retained XML file is a separate electronic witness; independent work identity, "
                        "TEI acceptance, rights, and publication remain unresolved.",
                        "CCEL source formatting and attribution conditions require release review and visible credit."]
            if row["proofreading_status"]:
                warnings.append(f"Retained CCEL electronic edition status: {row['proofreading_status']}")
            if row["editorial_comments_present"]:
                warnings.append("Retained electronic edition includes editorial comments requiring release review.")
            retained = {"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"],
                        "media_type": "application/xml", "scope": scope}
            acquisition = {"schema_version": "2.0", "acquisition_id": acquisition_id,
                           "edition_id": edition_id, "provider": "Christian Classics Ethereal Library",
                           "url": row["source_url"], "route": "born-digital",
                           "retained_files": [retained], "source_path": row["path"],
                           "source_bytes": row["bytes"], "source_sha256": row["sha256"],
                           "source_scope": scope, "warnings": warnings}
            validate_record("acquisition", acquisition, context=acq_rel)
            files.append((acq_rel, acquisition, None))
            new_work["textual_forms"].append({"textual_form_id": form_id, "language": "en",
                                              "editions": [{"edition_id": edition_id,
                                                            "title": row["title"], "language": "en",
                                                            "acquisition_ids": [acquisition_id]}]})
            evidence = [PACKET_REL, row["manifest"]["path"], row["profile"]["path"],
                        row["path"], RIGHTS_REL, ATTRIBUTION_REL, credit_rel, acq_rel]
            for target_id, target_type in ((acquisition_id, "acquisition"), (edition_id, "edition")):
                new_state["targets"].append({"target_id": target_id, "target_type": target_type,
                                             "stage": "acquired", "updated_at": now,
                                             "evidence": evidence})
            for ref in (row["path"], row["manifest"]["path"], row["profile"]["path"]):
                if ref not in new_work["evidence"]:
                    new_work["evidence"].append(ref)
        new_work["evidence"].extend([PACKET_REL, credit_rel])
        validate_identity_update(work, new_work)
        validate_record("work", new_work, context=wid)
        validate_record("state", new_state, context=wid)
        files.extend([(work_rel, new_work, before[wid]["work"]),
                      (state_rel, new_state, before[wid]["state"]),
                      (credit_rel, _credit(wid, members), None)])
    packet = {"contract": CONTRACT, "source_members": rows, "author_cohorts": 22,
              "independent_work_identity": "unresolved; no author cohort is accepted as one intellectual work",
              "outside_pinned_profiles": outside,
              "source_scope": "39 pinned XML members only; three same-author companion volumes remain unaccounted",
              "rights_evidence": [RIGHTS_REL, ATTRIBUTION_REL],
              "source_manifest_and_profile_refs": references, "before": before}
    write_json(packet_path, packet)
    _io_path(destination).mkdir(parents=True)
    output = []
    for relative, document, before_digest in files:
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(document, str):
            target.write_text(document, encoding="utf-8")
        else:
            write_json(target, document)
        output.append({"path": relative, "before_sha256": before_digest,
                       "proposed_sha256": sha256_file(target)})
    receipt = {"contract": CONTRACT, "packet_path": PACKET_REL,
               "packet_sha256": sha256_file(packet_path), "source_members": 39,
               "author_cohorts": 22, "files": sorted(output, key=lambda item: item["path"])}
    write_json(_io_path(destination / "receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = stage(args.repository_root, args.destination)
    print(json.dumps({"destination": str(args.destination), "members": result["source_members"],
                      "works": result["author_cohorts"], "files": len(result["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
