"""Stage three held CCEL companion volumes under existing Expositor IDs.

This extends acquired-source accounting after the pinned 39-member stage. Each
volume is its own provisional textual form, electronic edition, and acquisition.
It does not settle independent intellectual-work boundaries or accept TEI.
"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build.tools.prepare_expositors_sidecars import (
    ATTRIBUTION_REL,
    RIGHTS_REL,
    _credit,
    _header,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file, write_json
from ocd_kernel.library.identities import load_work, validate_identity_update, validate_record
from ocd_kernel.library.state import load_state
from ocd_kernel.tei.install_accepted import _io_path


CONTRACT = "ocd-expositors-three-companion-sidecar-stage-v1"
PACKET_REL = "plans/2026-09-22-source-preflight/expositors-three-companion-sidecar-packet-20260926.json"
PREVIOUS_PACKET_REL = "plans/2026-09-22-source-preflight/expositors-39-member-sidecar-packet-20260926.json"
PREVIOUS_APPLY_REL = "plans/2026-09-22-source-preflight/expositors-39-member-sidecar-apply-20260926.json"
COMPANIONS = {
    "expositors-bible--marcus-dods": ("dods_expositorjohn2.xml", "lib035"),
    "expositors-bible--george-adam-smith": ("smith_ga_expositorisa1.xml", "lib034"),
    "expositors-bible--g-t-stokes": ("stokes_expositoracts1.xml", "lib034"),
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(_io_path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PipelineError(f"expected JSON object: {path}")
    return value


def companion_rows(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    prior = _json(resolve_repo_path(root, PREVIOUS_PACKET_REL))
    applied = _json(resolve_repo_path(root, PREVIOUS_APPLY_REL))
    if (prior.get("contract") != "ocd-expositors-39-member-sidecar-stage-v1"
            or applied.get("contract") != "ocd-expositors-sidecar-apply-v1"
            or applied.get("packet_sha256") != sha256_file(resolve_repo_path(root, PREVIOUS_PACKET_REL))
            or len(applied.get("installed", [])) != 22):
        raise PipelineError("prior 39-member Expositor stage is not the installed baseline")
    outside = {item["path"]: item for item in prior["outside_pinned_profiles"]}
    installed = {item["work_id"]: item for item in applied["installed"]}
    selected = prior["source_members"]
    rows: list[dict[str, Any]] = []
    before: dict[str, dict[str, str]] = {}
    for wid, (filename, family) in COMPANIONS.items():
        relative = f"raw/ccel/expositors-bible/{filename}"
        prior_row = outside.get(relative)
        previous = installed.get(wid)
        if (prior_row is None or previous is None or prior_row.get("work_id") != wid
                or "held companion" not in prior_row.get("disposition", "")):
            raise PipelineError(f"{wid} companion or prior installed work binding missing")
        work_rel = f"library/works/{wid}/work.json"
        state_rel = f"library/works/{wid}/state.json"
        credit_rel = f"library/works/{wid}/SOURCE_CREDIT.md"
        work_path = resolve_repo_path(root, work_rel)
        state_path = resolve_repo_path(root, state_rel)
        credit_path = resolve_repo_path(root, credit_rel)
        expected = previous["after"]
        before[wid] = {"work": sha256_file(work_path), "state": sha256_file(state_path),
                       "credit": sha256_file(credit_path)}
        if any(before[wid][key] != expected[f"{key if key != 'credit' else 'SOURCE_CREDIT'}.{ 'md' if key == 'credit' else 'json'}"]
               for key in ("work", "state", "credit")):
            raise PipelineError(f"{wid} differs from prior installed generation")
        old_credit = _credit(wid, [item for item in selected if item["work_id"] == wid])
        if credit_path.read_text(encoding="utf-8") != old_credit:
            raise PipelineError(f"{wid} source credit differs from installed stage")
        source_path = resolve_repo_path(root, relative)
        if (not source_path.is_file() or source_path.stat().st_size != prior_row["bytes"]
                or sha256_file(source_path) != prior_row["sha256"]):
            raise PipelineError(f"{wid} retained companion XML differs from prior census")
        header = _header(source_path)
        if (header["title"] != prior_row["source_title"]
                or header["author"] != prior_row["source_author"]
                or header["language"] != "eng"
                or header["book_id"] != header["url"].removesuffix(".html").rsplit("/", 1)[-1]):
            raise PipelineError(f"{wid} retained companion header differs")
        peers = [item for item in selected if item["work_id"] == wid]
        if not peers or header["author"] not in {item["source_author"] for item in peers}:
            raise PipelineError(f"{wid} companion author differs from pinned peer")
        profile_rel = f"sources/commentaries/expositors-bible/{family}.reconstruction-profile.json"
        profile = _json(resolve_repo_path(root, profile_rel))
        excluded = [item for item in profile.get("excluded_members", []) if item.get("path") == relative]
        if len(excluded) != 1 or "Same-author retained member omitted" not in excluded[0].get("reason", ""):
            raise PipelineError(f"{wid} profile does not identify held same-author member")
        rows.append({"work_id": wid, "member_id": f"{filename.removesuffix('.xml').replace('_', '-')}",
                     "path": relative, "bytes": prior_row["bytes"], "sha256": prior_row["sha256"],
                     "source_title": header["title"], "source_author": header["author"],
                     "source_url": header["url"], "print_source": header["print_source"],
                     "profile": {"path": profile_rel,
                                 "sha256": sha256_file(resolve_repo_path(root, profile_rel))},
                     "profile_exclusion_reason": excluded[0]["reason"]})
    return rows, before


def _updated_credit(old_credit: str, row: dict[str, Any]) -> str:
    marker = "\nThe following retained companion volume is outside this pinned source\n"
    if old_credit.count(marker) != 1:
        raise PipelineError("installed credit lacks the one held companion marker")
    base = old_credit.split(marker, 1)[0]
    insert_at = "\n\nSourced via CCEL.org."
    if base.count(insert_at) != 1:
        raise PipelineError("installed credit attribution boundary differs")
    new_item = f"\n- {row['source_title']} — {row['path']} (SHA-256 {row['sha256']})"
    return base.replace(insert_at, new_item + insert_at) + "\n"


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
    packet_path = root / PACKET_REL
    if packet_path.exists():
        raise PipelineError(f"packet already exists: {packet_path}")
    rows, before = companion_rows(root)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    proposed: list[tuple[str, dict[str, Any] | str, str | None]] = []
    for row in rows:
        wid, member_id = row["work_id"], row["member_id"]
        work_rel, state_rel = f"library/works/{wid}/work.json", f"library/works/{wid}/state.json"
        credit_rel = f"library/works/{wid}/SOURCE_CREDIT.md"
        work, state = load_work(root / work_rel), load_state(root / state_rel)
        old_credit = resolve_repo_path(root, credit_rel).read_text(encoding="utf-8")
        new_work, new_state = copy.deepcopy(work), copy.deepcopy(state)
        form_id = f"{wid}--{member_id}--retained-en"
        edition_id = f"{wid}--{member_id}--ccel-electronic"
        acquisition_id = f"{wid}--{member_id}--acquired"
        acq_rel = (f"library/works/{wid}/forms/{form_id}/editions/{edition_id}"
                   f"/acquisitions/{acquisition_id}.json")
        if resolve_repo_path(root, acq_rel).exists():
            raise PipelineError(f"{wid} companion acquisition already exists")
        scope = (f"Complete retained CCEL ThML XML file for {row['source_title']}. "
                 "This companion volume extends source accounting only; independent work, "
                 "print-edition identity, TEI acceptance, rights, and publication remain unresolved.")
        warnings = ["Companion XML was outside the earlier pinned LIB-034/035 current-claim profile; "
                    "its retained header and author match the separately accounted volume. "
                    "The author-cohort catalog identity does not establish one intellectual work or print edition.",
                    "CCEL source formatting and attribution conditions require release review and visible credit."]
        retained = {"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"],
                    "media_type": "application/xml", "scope": scope}
        acquisition = {"schema_version": "2.0", "acquisition_id": acquisition_id,
                       "edition_id": edition_id, "provider": "Christian Classics Ethereal Library",
                       "url": row["source_url"], "route": "born-digital",
                       "retained_files": [retained], "source_path": row["path"],
                       "source_bytes": row["bytes"], "source_sha256": row["sha256"],
                       "source_scope": scope, "warnings": warnings}
        validate_record("acquisition", acquisition, context=acq_rel)
        proposed.append((acq_rel, acquisition, None))
        new_work["textual_forms"].append({"textual_form_id": form_id, "language": "en",
                                          "editions": [{"edition_id": edition_id,
                                                        "title": row["source_title"],
                                                        "language": "en",
                                                        "acquisition_ids": [acquisition_id]}]})
        for evidence in (row["path"], row["profile"]["path"], PACKET_REL):
            if evidence not in new_work["evidence"]:
                new_work["evidence"].append(evidence)
        evidence = [PACKET_REL, PREVIOUS_PACKET_REL, row["profile"]["path"],
                    row["path"], RIGHTS_REL, ATTRIBUTION_REL, credit_rel, acq_rel]
        for target_id, target_type in ((acquisition_id, "acquisition"), (edition_id, "edition")):
            new_state["targets"].append({"target_id": target_id, "target_type": target_type,
                                         "stage": "acquired", "updated_at": now, "evidence": evidence})
        validate_identity_update(work, new_work)
        validate_record("work", new_work, context=wid)
        validate_record("state", new_state, context=wid)
        proposed.extend([(work_rel, new_work, before[wid]["work"]),
                         (state_rel, new_state, before[wid]["state"]),
                         (credit_rel, _updated_credit(old_credit, row), before[wid]["credit"])])
    packet = {"contract": CONTRACT, "source_members": rows, "before": before,
              "prior_packet": {"path": PREVIOUS_PACKET_REL,
                               "sha256": sha256_file(root / PREVIOUS_PACKET_REL)},
              "prior_apply": {"path": PREVIOUS_APPLY_REL,
                              "sha256": sha256_file(root / PREVIOUS_APPLY_REL)},
              "scope": "Three held same-author XML companions only; independent work boundaries remain unresolved"}
    write_json(packet_path, packet)
    _io_path(destination).mkdir(parents=True)
    files = []
    for relative, document, before_digest in proposed:
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(document, str):
            target.write_text(document, encoding="utf-8")
        else:
            write_json(target, document)
        files.append({"path": relative, "before_sha256": before_digest,
                      "proposed_sha256": sha256_file(target)})
    receipt = {"contract": CONTRACT, "packet_path": PACKET_REL,
               "packet_sha256": sha256_file(packet_path), "sources": len(rows),
               "files": sorted(files, key=lambda item: item["path"])}
    write_json(_io_path(destination / "receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = stage(args.repository_root, args.destination)
    print(json.dumps({"destination": str(args.destination), "sources": result["sources"],
                      "files": len(result["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
