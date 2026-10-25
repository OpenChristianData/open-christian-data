"""Apply the bounded language/category prerequisite, then shared guarded install."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path

from build.tools.stage_georgii_aliud import ROOT, WORK, EDITION, EVIDENCE
from build.tools.prepare_georgii_aliud import canonical, TITLE, ORIGINAL_TITLE
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, install_accepted_work


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promoted",type=Path,required=True)
    parser.add_argument("--receipt-sha256",required=True)
    parser.add_argument("--evidence",type=Path,required=True)
    parser.add_argument("--coordination-clearance",type=Path,required=True)
    parser.add_argument("--clearance-sha256",required=True)
    args = parser.parse_args()
    clearance_bytes = args.coordination_clearance.read_bytes()
    if sha256(clearance_bytes).hexdigest() != args.clearance_sha256:
        raise ValueError("coordinator clearance receipt pin differs")
    clearance = json.loads(clearance_bytes)
    if (clearance.get("work_id") != "lambertus-epitaphium-georgii-aliud"
            or clearance.get("authorized_by") != "coordinator:/root"
            or clearance.get("canonical_install_authorized") is not True
            or clearance.get("first_owner_short_release_complete") is not True):
        raise ValueError("serialized sibling installation clearance missing")
    promoted = args.promoted.absolute()
    stage_bytes = (promoted/"stage-receipt.json").read_bytes()
    if sha256(stage_bytes).hexdigest() != args.receipt_sha256:
        raise ValueError("staged receipt pin differs")
    receipt = json.loads(stage_bytes)
    if receipt["status"] != "pass" or receipt["rows"] != 1 or receipt["promoted_root"] != promoted.as_posix():
        raise ValueError("stage contract differs")
    if _files(ROOT/WORK) != receipt["before"]:
        raise ValueError("complete canonical work preimage changed")
    sibling_ids = ("lambertus-epitaphium-georgii-primum", "lambertus-epitaphium-georgii-tertium")
    sibling_before = {work_id: _files(ROOT/"library/works"/work_id) for work_id in sibling_ids}
    validate_acceptance(promoted/EDITION/"acceptance.json",root=promoted)
    original_bytes = io_path(ROOT/WORK/"work.json").read_bytes()
    original = json.loads(original_bytes)
    revised_bytes = io_path(promoted/WORK/"work.json").read_bytes()
    revised = json.loads(revised_bytes)
    expected = json.loads(original_bytes)
    if original["title"] != ORIGINAL_TITLE: raise ValueError("original title preimage differs")
    expected["title"] = TITLE
    form = expected["textual_forms"][0]
    form["language"] = "la"
    form["editions"][0].update(language="la",category="poetry")
    if revised != expected:
        raise ValueError("staged metadata exceeds language/category prerequisite")
    validate_identity_update(original,revised)
    if io_path(promoted/EDITION/"master.tei.xml").read_bytes() != io_path(promoted/EVIDENCE/"candidate.tei.xml").read_bytes():
        raise ValueError("promoted master is not the accepted candidate")
    args.evidence.mkdir(parents=True,exist_ok=False)
    (args.evidence/"original-work.json").write_bytes(original_bytes)
    (args.evidence/"staged-receipt.json").write_bytes(stage_bytes)
    (args.evidence/"coordination-clearance.json").write_bytes(clearance_bytes)
    temporary = ROOT/WORK/".georgii-aliud-work-metadata.tmp"
    if temporary.exists():
        raise FileExistsError(temporary)
    temporary.write_bytes(revised_bytes)
    temporary.replace(ROOT/WORK/"work.json")
    metadata = dict(status="pass",changed_fields=["title","textual_forms[0].language","textual_forms[0].editions[0].language","textual_forms[0].editions[0].category"],
                    before_sha256=sha256(original_bytes).hexdigest(),after_sha256=sha256(revised_bytes).hexdigest(),
                    evidence="Complete second ALIUD six-line Latin epitaph within source triplex; precise qualified title plus poetry category; immutable identity and acquisition unchanged.")
    (args.evidence/"metadata-prerequisite.json").write_bytes(canonical(metadata))
    try:
        result = install_accepted_work(ROOT,promoted,work_id="lambertus-epitaphium-georgii-aliud")
    except Exception:
        if (not io_path(ROOT/EDITION/"master.tei.xml").exists() and io_path(ROOT/WORK/"work.json").read_bytes() == revised_bytes):
            temporary.write_bytes(original_bytes)
            temporary.replace(ROOT/WORK/"work.json")
            (args.evidence/"metadata-rollback.json").write_bytes(canonical(dict(status="rolled-back",reason="guarded install failed before accepted master became live")))
        raise
    validate_acceptance(ROOT/EDITION/"acceptance.json",root=ROOT)
    sibling_after = {work_id: _files(ROOT/"library/works"/work_id) for work_id in sibling_ids}
    if sibling_after != sibling_before:
        raise ValueError("sibling generation changed during serialized second-poem installation")
    (args.evidence/"sibling-conservation.json").write_bytes(canonical(dict(status="pass",before=sibling_before,after=sibling_after)))
    (args.evidence/"installation.json").write_bytes(canonical(result))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
