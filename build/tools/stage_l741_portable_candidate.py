"""Stage a host-independent L741 candidate from the sealed v14 electronic witness."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/evangelische-gezangen-1806")
EDITION = WORK / "forms/evangelische-gezangen-1806-dbnl-retained/editions/evangelische-gezangen-1806-dbnl-electronic"
MASTER = EDITION / "master.tei.xml"
STAGED_CANDIDATE = EDITION / "acceptance-candidate.tei.xml"
MANIFEST = Path("sources/manifest-acquisitions/l741-evangelische-gezangen-1806/source-manifest.json")
V14 = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20261001-l741-local-uri-v14/baseline/package/content.tei.xml")
V14_SHA256 = "7a15b1a24747f25d637ad0a36243e5e60681ef5cc23bc5128b87fe0f38f36fc2"
SOURCE_SHA256 = "d8132943dd20b1053d1d77bda57cab2b69c9dc567e38ea4450baab914925abb9"
PREFIX = b"file:///D:/Library/Open%20Christian%20Data/raw/dbnl/evangelische-gezangen-1806/score-images/"
PATTERN = re.compile(re.escape(PREFIX) + rb"([A-Za-z0-9_.-]+\.gif)")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def stage(destination: Path) -> dict[str, object]:
    destination = destination.resolve()
    if destination.exists():
        raise ValueError(f"refusing existing stage: {destination}")
    if destination == ROOT or ROOT in destination.parents:
        if destination.parent != ROOT / ".tmp_audit":
            raise ValueError("repository stage must be a direct child of .tmp_audit")
    manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    resources = {
        Path(item["path"]).name: item
        for item in manifest["authorities"]
        if item["role"] == "source-resource"
    }
    if len(resources) != 68:
        raise ValueError("L741 score inventory must contain exactly 68 resources")
    source = ROOT / "raw/dbnl/evangelische-gezangen-1806/evangelische-gezangen-1806.xml"
    if _sha(source.read_bytes()) != SOURCE_SHA256:
        raise ValueError("retained XML changed")
    original = V14.read_bytes()
    if _sha(original) != V14_SHA256:
        raise ValueError("v14 candidate changed")
    seen: set[str] = set()
    replacements: list[dict[str, str]] = []
    # MASTER is repository-relative; one ascent for every directory in its parent.
    prefix = "../" * len(MASTER.parent.parts)

    def replace(match: re.Match[bytes]) -> bytes:
        name = match.group(1).decode("ascii")
        if name not in resources or name in seen:
            raise ValueError(f"unknown or duplicate score reference: {name}")
        seen.add(name)
        item = resources[name]
        physical = ROOT / item["path"]
        content = physical.read_bytes()
        if len(content) != item["bytes"] or _sha(content) != item["sha256"]:
            raise ValueError(f"score resource changed: {name}")
        logical = prefix + item["path"]
        replacements.append({"name": name, "logical_path": item["path"], "master_relative_uri": logical, "sha256": item["sha256"]})
        return logical.encode("ascii")

    normalized, count = PATTERN.subn(replace, original)
    if count != 68 or seen != set(resources):
        raise ValueError("not all 68 source score references were normalized")
    if PREFIX in normalized:
        raise ValueError("absolute score URI remains")
    destination.mkdir(parents=True)
    output = destination / STAGED_CANDIDATE
    output.parent.mkdir(parents=True)
    output.write_bytes(normalized)
    for item in resources.values():
        target = destination / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / item["path"], target)
    target = destination / "raw/dbnl/evangelische-gezangen-1806/evangelische-gezangen-1806.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    for item in replacements:
        resolved = (output.parent / item["master_relative_uri"]).resolve(strict=True)
        if resolved != (destination / item["logical_path"]).resolve(strict=True):
            raise ValueError(f"score URI resolves to wrong target: {item['name']}")
        if _sha(resolved.read_bytes()) != item["sha256"]:
            raise ValueError(f"score URI hash mismatch: {item['name']}")
    restored = normalized
    for item in replacements:
        restored = restored.replace(
            item["master_relative_uri"].encode("ascii"), PREFIX + item["name"].encode("ascii"), 1
        )
    if restored != original:
        raise ValueError("normalized candidate differs beyond the 68 score URIs")
    errors = validate_file(output)
    if errors:
        raise ValueError(f"normalized TEI fails P5: {errors[:3]}")
    receipt = {
        "contract": "ocd-l741-portable-candidate-v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "pass",
        "work_id": "evangelische-gezangen-1806",
        "source_sha256": SOURCE_SHA256,
        "source_manifest_sha256": _sha((ROOT / MANIFEST).read_bytes()),
        "v14_candidate_sha256": V14_SHA256,
        "portable_candidate_sha256": _sha(normalized),
        "candidate_path": STAGED_CANDIDATE.as_posix(),
        "score_uri_count": count,
        "exactly_68_uri_replacements_and_no_other_tei_byte_changes": True,
        "all_score_uri_targets_match_retained_hashes": True,
        "p5_status": "pass",
        "print_page_collation": "unperformed; no print page scans retained",
        "dbnl_intervention_print_checks": "unperformed at pages 151, 352, and 386",
        "rights_clearance": "not determined",
        "human_acceptance": "not performed",
        "publication": "not authorized",
        "resources": replacements,
    }
    receipt_path = destination / "normalization-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"stage": str(destination), "candidate": str(output), "candidate_sha256": _sha(normalized), "receipt": str(receipt_path), "receipt_sha256": _sha(receipt_path.read_bytes()), "score_uris": count}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(stage(args.stage), sort_keys=True))


if __name__ == "__main__":
    main()
