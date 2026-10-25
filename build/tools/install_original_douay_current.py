"""Install only the pinned Douay generation through the shared guarded installer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, install_accepted_work

from build.tools.stage_original_douay_current import ROOT, WORK, EDITION


WORK_ID = "original-douay-rheims"


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def install(promoted: Path, freeze_path: Path, freeze_sha256: str, evidence: Path, *, fail_at=None) -> dict:
    promoted = promoted.resolve(strict=True)
    freeze_bytes = freeze_path.read_bytes()
    if sha(freeze_bytes) != freeze_sha256:
        raise PipelineError("Douay install freeze SHA differs")
    freeze = json.loads(freeze_bytes)
    if (freeze["status"] != "pass" or freeze["work_id"] != WORK_ID
            or freeze["canonical_install"] or Path(freeze["durable_promoted"]).resolve(strict=True) != promoted
            or {path: sha((ROOT / path).read_bytes()) for path in freeze["runtime_schema_pins"]} != freeze["runtime_schema_pins"]):
        raise PipelineError("Douay promoted root or pinned install runtime changed")
    receipt_bytes = (promoted / "stage-receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    if (sha(receipt_bytes) != freeze["stage_receipt_sha256"] or receipt["status"] != "pass"
            or receipt["work_id"] != WORK_ID or receipt["before"] != freeze["before"]
            or receipt["after"] != freeze["after"] or receipt["bound_master_sha256"] != freeze["bound_master_sha256"]
            or _files(ROOT / WORK) != receipt["before"] or _files(promoted / WORK) != receipt["after"]):
        raise PipelineError("Douay stage or exact canonical preimage differs")
    original_bytes = io_path(ROOT / WORK / "work.json").read_bytes()
    revised_bytes = io_path(promoted / WORK / "work.json").read_bytes()
    original = json.loads(original_bytes)
    revised = json.loads(revised_bytes)
    exact = json.loads(json.dumps(original))
    target = exact["textual_forms"][0]["editions"][0]
    if original["work_id"] != WORK_ID or "category" in target:
        raise PipelineError("Douay metadata preimage differs")
    target["category"] = "bible"
    if revised != exact or sha(original_bytes) != freeze["before_work_sha256"] or sha(revised_bytes) != freeze["after_work_sha256"]:
        raise PipelineError("Douay prerequisite exceeds pinned category field")
    validate_identity_update(original, revised)
    for relative, digest in receipt["before"].items():
        if relative not in {"work.json", "state.json"} and receipt["after"].get(relative) != digest:
            raise PipelineError("Existing Douay authority changed in stage: " + relative)
    acceptance = validate_acceptance(promoted / EDITION / "acceptance.json", root=promoted)
    if (acceptance["source"]["source_sha256"] != receipt["before"]["forms/original-douay-rheims-retained-en/editions/original-douay-rheims-electronic/source-member-set.json"]
            or io_path(promoted / EDITION / "master.tei.xml").read_bytes() != io_path(promoted / WORK / "integration/original-douay-current-v1/candidate.tei.xml").read_bytes()):
        raise PipelineError("Accepted Douay source or candidate differs")
    if evidence.exists():
        raise FileExistsError("Fresh exact Douay install evidence directory required")
    evidence.mkdir(parents=True)
    (evidence / "freeze.json").write_bytes(freeze_bytes)
    (evidence / "stage-receipt.json").write_bytes(receipt_bytes)
    (evidence / "original-work.json").write_bytes(original_bytes)
    (evidence / "metadata-prerequisite.json").write_bytes(canonical({
        "status": "pinned", "changed_fields": ["textual_forms[0].editions[0].category"],
        "before_sha256": sha(original_bytes), "after_sha256": sha(revised_bytes),
        "value": "bible", "rollback_preimage_preserved": True,
    }))
    temporary = ROOT / WORK / ".original-douay-metadata.tmp"
    if temporary.exists() or _files(ROOT / WORK) != receipt["before"]:
        raise PipelineError("Douay prerequisite target or generation changed")
    temporary.write_bytes(revised_bytes)
    temporary.replace(ROOT / WORK / "work.json")
    try:
        result = install_accepted_work(ROOT, promoted, work_id=WORK_ID, fail_at=fail_at)
    except Exception:
        if (not io_path(ROOT / EDITION / "master.tei.xml").exists()
                and io_path(ROOT / WORK / "work.json").read_bytes() == revised_bytes):
            temporary.write_bytes(original_bytes)
            temporary.replace(ROOT / WORK / "work.json")
            if _files(ROOT / WORK) != receipt["before"]:
                raise PipelineError("Failed Douay install did not restore exact canonical preimage")
            (evidence / "metadata-rollback.json").write_bytes(canonical({"status": "rolled-back", "exact_original_generation": True}))
        raise
    if _files(ROOT / WORK) != receipt["after"]:
        raise PipelineError("Installed Douay generation differs from freeze")
    (evidence / "installation.json").write_bytes(canonical(result))
    (evidence / "installed-audit.json").write_bytes(canonical({
        "status": "pass", "files": receipt["after"], "master_sha256": receipt["bound_master_sha256"],
        "only_metadata_prerequisite": "category=bible", "source_members_preserved": True,
    }))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promoted", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.promoted, args.freeze, args.freeze_sha256, args.evidence)))


if __name__ == "__main__":
    main()
