"""Guard exactly one reviewed PG33105 metadata prerequisite and accepted generation."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path

from build.tools.prepare_chinook_current import ROOT,LOG,WORK,EDITION,WID,EID,digest,save
from build.tools.refresh_chinook_notice import STAGE_V4
from ocd_kernel.library._common import io_path,PipelineError
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.projection.categories.hymns import project_accepted_hymns,verify_accepted_hymns
from ocd_kernel.projection.categories.chinook_hymns import SOURCE_MEMBER_PATH,SOURCE_SHA
from ocd_kernel.tei.acceptance import _validate_acceptance_for_work
from ocd_kernel.tei.install_accepted import _files,install_accepted_work,_write_json_durable

def _metadata(original,revised):
    expected=copy.deepcopy(original)
    edition=expected["textual_forms"][0]["editions"][0]
    if original["work_id"] != WID or edition["edition_id"] != EID or "category" in edition or "language" in edition:
        raise PipelineError("Chinook metadata preimage differs")
    edition.update(category="hymns",language="mul")
    if revised != expected:
        raise PipelineError("Chinook metadata exceeds two-field prerequisite")
    validate_identity_update(original,revised)

def install(root: Path,stage: Path,proposal_sha256: str,evidence: Path,*,fail_at=None):
    proposal_path=LOG/"adapter-proposal-v4.json"
    if digest(proposal_path.read_bytes()) != proposal_sha256:
        raise PipelineError("Reviewed Chinook proposal changed")
    proposal=json.loads(proposal_path.read_bytes())
    if (proposal["work_id"] != WID or _files(root/WORK) != proposal["before"]
            or _files(stage/WORK) != proposal["after"]):
        raise PipelineError("Exact Chinook canonical/staged generations differ")
    for key in ("adapter","test"):
        if digest((ROOT/proposal[key+"_path"]).read_bytes()) != proposal[key+"_sha256"]:
            raise PipelineError("Reviewed Chinook adapter/test changed")
    if proposal.get("source_member_path") != SOURCE_MEMBER_PATH or proposal.get("source_member_sha256") != SOURCE_SHA:
        raise PipelineError("Reviewed Chinook exact source member changed")
    for relative,expected in proposal["runtime_and_notice_bindings"].items():
        if digest((ROOT/relative).read_bytes()) != expected or (relative.startswith("sources/") and digest(io_path(stage/relative).read_bytes()) != expected):
            raise PipelineError(f"Reviewed Chinook runtime or notice changed: {relative}")
    before=io_path(root/WORK/"work.json").read_bytes()
    after=io_path(stage/WORK/"work.json").read_bytes()
    _metadata(json.loads(before),json.loads(after))
    _validate_acceptance_for_work(stage/EDITION/"acceptance.json",root=stage,work_id=WID)
    output=project_accepted_hymns(stage,acceptance_path=stage/EDITION/"acceptance.json")
    errors=verify_accepted_hymns(stage,acceptance_path=stage/EDITION/"acceptance.json",rows=output["rows"],receipt=output["receipt"])
    if errors or len(output["rows"]) != 20:
        raise PipelineError(f"Reviewed shared Chinook route differs: {errors}")
    evidence.mkdir(parents=True,exist_ok=False)
    save(evidence/"original-work.json",before)
    save(evidence/"proposal.json",proposal)
    if _files(root/WORK) != proposal["before"]:
        raise PipelineError("Immediate canonical generation drift")
    _write_json_durable(root/WORK/"work.json",json.loads(after))
    try:
        result=install_accepted_work(root,stage,work_id=WID,fail_at=fail_at)
    except Exception:
        if not io_path(root/EDITION/"master.tei.xml").exists() and io_path(root/WORK/"work.json").read_bytes() == after:
            # Preserve the exact original bytes rather than reserializing the preimage.
            temporary=io_path(root/WORK/".chinook-metadata-rollback.tmp")
            if temporary.exists():
                raise PipelineError("Unexpected metadata rollback temporary")
            temporary.write_bytes(before)
            temporary.replace(io_path(root/WORK/"work.json"))
            if _files(root/WORK) != proposal["before"]:
                raise PipelineError("Chinook failed-install metadata rollback differs")
            save(evidence/"rollback.json",dict(status="pass",exact_original_generation=True))
        raise
    if _files(root/WORK) != proposal["after"]:
        raise PipelineError("Installed Chinook generation differs")
    operation=Path(result["operation"])/"operation.json"
    journal=json.loads(operation.read_bytes())
    if journal["phase"] != "complete" or journal["after"] != proposal["after"]:
        raise PipelineError("Chinook operation journal incomplete")
    save(evidence/"installation.json",result)
    audit=dict(status="pass",work_id=WID,operation=str(operation),operation_sha256=digest(operation.read_bytes()),
        installed_files=proposal["after"],proposal_sha256=proposal_sha256,rows=20,
        human_acceptance="not-recorded",rights="unresolved",public_publication=False)
    save(evidence/"installed-generation.json",audit)
    return audit

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-proposal-sha256",required=True)
    args=parser.parse_args()
    print(json.dumps(install(ROOT,STAGE_V4,args.expected_proposal_sha256,LOG/"canonical-install"),indent=2))

if __name__ == "__main__":
    main()
