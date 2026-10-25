"""Read-only preflight for the sixteen NPNF103 shared-volume sidecars."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from build.tei.npnf103_reconstruction import ASSIGNED
from build.tools.prepare_library_sidecar_batch import prepare
from ocd_kernel.library._common import PipelineError, canonical_bytes, load_json, sha256_file
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import load_state, validate_state
from ocd_kernel.tei.install_accepted import _files, _io_path


PACKET_REL = "plans/2026-09-22-source-preflight/augustine-npnf103-sixteen-sidecar-batch-20260926.json"
SOURCE_REL = "raw/ccel/npnf1/npnf103.xml"
SOURCE_SHA256 = "410f240f8105bb6097316a54a867fa5a4ae02c0d3d03606aefc2df71f5bfc455"


def preflight(root: Path, staged: Path) -> dict[str, Any]:
    """Recompute proposed bytes without installing or changing canonical sidecars."""
    root, staged = root.resolve(), staged.resolve()
    packet_path = root / PACKET_REL
    packet = load_json(packet_path)
    receipt = load_json(_io_path(staged / "receipt.json"))
    expected = dict(ASSIGNED)
    manifest = load_json(root / "sources/structured-text/augustine-npnf103/augustine-npnf103.source-manifest.json")
    profile_rel = "sources/structured-text/augustine-npnf103/augustine-npnf103.reconstruction-profile.json"
    profile = load_json(root / profile_rel)
    profile_authorities = [item for item in manifest.get("authorities", []) if isinstance(item, dict)
                           and item.get("role") == "complete-source-feature-profile"
                           and item.get("path") == profile_rel]
    source_authorities = [item for item in manifest.get("authorities", []) if isinstance(item, dict)
                          and item.get("role") == "primary-source" and item.get("path") == SOURCE_REL]
    if (len(profile_authorities) != 1 or len(source_authorities) != 1
            or profile_authorities[0].get("sha256") != sha256_file(root / profile_rel)
            or profile_authorities[0].get("bytes") != (root / profile_rel).stat().st_size
            or source_authorities[0].get("sha256") != SOURCE_SHA256
            or profile.get("assigned_div2") != [locator for locator, _ in ASSIGNED]
            or profile.get("source_member") != {key: source_authorities[0][key]
                                                for key in ("path", "bytes", "sha256")}):
        raise PipelineError("NPNF103 complete source profile or manifest binding changed")
    rows = packet.get("entries")
    if (packet.get("contract") != "ocd-library-sidecar-batch-v1"
            or not isinstance(rows, list) or len(rows) != 16
            or {row.get("work_id") for row in rows if isinstance(row, dict)} != set(expected.values())
            or len({row.get("work_id") for row in rows if isinstance(row, dict)}) != 16
            or receipt.get("contract") != "ocd-library-sidecar-stage-v1"
            or receipt.get("packet_sha256") != sha256_file(packet_path)
            or not isinstance(receipt.get("entries"), list) or len(receipt["entries"]) != 16
            or sha256_file(_io_path(root / SOURCE_REL)) != SOURCE_SHA256):
        raise PipelineError("NPNF103 packet, receipt, work set, or retained XML changed")
    for locator, work_id in ASSIGNED:
        row = next(item for item in rows if item["work_id"] == work_id)
        containing = row.get("containing_source")
        if (row.get("source_child_element") != "div2"
                or not isinstance(containing, dict)
                or containing.get("locator") != f"{SOURCE_REL}#{locator}"):
            raise PipelineError(f"NPNF103 work locator changed: {work_id}")
    first = receipt["entries"][0]["work_id"]
    staged_state = load_state(_io_path(staged / f"library/works/{first}/state.json"))
    now = staged_state["targets"][-1]["updated_at"]
    prepared = prepare(root, packet, now)
    by_id = {entry["work_id"]: entry for entry in receipt["entries"]}
    if set(by_id) != set(expected.values()):
        raise PipelineError("NPNF103 stage receipt work set differs")
    total = 0
    for result in prepared:
        wid = result["work_id"]
        listed = by_id[wid].get("files")
        if not isinstance(listed, list) or len(listed) != 3:
            raise PipelineError(f"{wid} staged file count differs")
        paths = {item.get("path") for item in listed if isinstance(item, dict)}
        proposed = {rel: value for rel, value in result["output"]}
        if len(paths) != 3 or paths != set(proposed):
            raise PipelineError(f"{wid} staged path set differs")
        for item in listed:
            rel = item["path"]
            current = root / rel
            before = sha256_file(_io_path(current)) if current.is_file() else None
            calculated = hashlib.sha256(canonical_bytes(proposed[rel])).hexdigest()
            actual = sha256_file(_io_path(staged / rel))
            if (item.get("before_sha256") != before
                    or item.get("proposed_sha256") != calculated or actual != calculated):
                raise PipelineError(f"{wid} staged/current sidecar bytes differ: {rel}")
            total += 1
        live_tree = _files(root / "library/works" / wid)
        stage_tree = _files(staged / "library/works" / wid)
        output_rels = {Path(rel).relative_to(Path("library/works") / wid).as_posix() for rel in proposed}
        if (set(stage_tree) != set(live_tree) | output_rels
                or any(stage_tree[rel] != digest for rel, digest in live_tree.items() if rel not in output_rels)):
            raise PipelineError(f"{wid} staged work generation contains unrelated changes")
        acquisition_rel = next(rel for rel in proposed if "/acquisitions/" in rel)
        acquisition = load_json(_io_path(staged / acquisition_rel))
        if (len(acquisition.get("retained_files", [])) != 1
                or acquisition["retained_files"][0]["path"] != SOURCE_REL
                or acquisition.get("source_path") != SOURCE_REL
                or acquisition.get("source_sha256") != SOURCE_SHA256):
            raise PipelineError(f"{wid} acquisition does not retain the exact XML volume")
        validate_acquisition(_io_path(staged / acquisition_rel), root=_io_path(staged))
        validate_state(_io_path(staged / f"library/works/{wid}/state.json"), root=_io_path(staged))
    return {"preflighted": 16, "files": total, "source_sha256": SOURCE_SHA256}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(preflight(args.repository_root, args.stage), sort_keys=True))


if __name__ == "__main__":
    main()
