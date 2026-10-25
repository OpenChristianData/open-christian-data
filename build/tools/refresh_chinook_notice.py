"""Reconcile one dated language statement and freeze its technical successor."""
from __future__ import annotations
import copy
import argparse
import json
from pathlib import Path
import shutil

from build.tools.prepare_chinook_current import ROOT, LOG, WORK, EDITION, EVIDENCE, MANIFEST, PACKAGE, WID, digest, save
from build.tools.probe_chinook_hymn_projection import STAGE_V3
from build.tei.l744_hymns_oracle import _oracle
from build.tei.l744_hymns import _convert
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage, reconstruct, validate
from ocd_kernel.library._common import io_path
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories.hymns import project_accepted_hymns, verify_accepted_hymns

STAGE_V4=ROOT/".tmp_audit/chinook-acceptance-20261002-v4"
NOTICE=MANIFEST.parent/"README.source.md"

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-reviewed-notice-successor",action="store_true")
    args=parser.parse_args()
    prior_path=LOG/"adapter-proposal-v3.json"
    expected="5c0f04027a16b1fc3c8d2abe0d9b648913670df64cfeab531e849a8b59fdc829"
    if digest(prior_path.read_bytes()) != expected or (STAGE_V4.exists() != args.resume_reviewed_notice_successor):
        raise ValueError("Original proposal changed or successor already exists")
    prior=json.loads(prior_path.read_bytes())
    if _files(ROOT/WORK) != prior["before"] or _files(STAGE_V3/WORK) != prior["after"]:
        raise ValueError("Original generations changed")
    old_notice=(STAGE_V3/NOTICE).read_bytes()
    old_manifest=(STAGE_V3/MANIFEST).read_bytes()
    old=b"The entry is limited to the exact provider title and printed title-page edition/year; no author or language code is asserted."
    new=b"The original source entry was limited to the exact provider title and printed title-page edition/year and omitted author and language codes. The reviewed technical successor records edition language `mul` for this bilingual/multilingual edition only; no individual line language codes are inferred."
    if old_notice.count(old) != 1:
        raise ValueError("Dated language statement differs")
    if not args.resume_reviewed_notice_successor:
        shutil.copytree(io_path(STAGE_V3),io_path(STAGE_V4))
    elif _files(STAGE_V4/WORK) != prior["after"]:
        raise ValueError("Partial successor generation changed")
    save(LOG/"notice-history"/(digest(old_notice)+".source-entry.md"),old_notice)
    save(LOG/"notice-history"/(digest(old_manifest)+".source-manifest.json"),old_manifest)
    revised=old_notice.replace(old,new)
    manifest_record=json.loads(old_manifest)
    authority=next(item for item in manifest_record["authorities"] if item["name"] == "readme")
    if authority["sha256"] != digest(old_notice) or authority["bytes"] != len(old_notice):
        raise ValueError("Original notice authority differs")
    authority.update(sha256=digest(revised),bytes=len(revised))
    manifest_bytes=(json.dumps(manifest_record,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
    for root in (ROOT,STAGE_V4):
        if args.resume_reviewed_notice_successor and ((root/NOTICE).read_bytes()!=revised or (root/MANIFEST).read_bytes()!=manifest_bytes):
            raise ValueError("Partial successor notice/manifest changed")
        save(root/NOTICE,revised)
        save(root/MANIFEST,manifest_bytes)
    manifest=SourceManifest.load(ROOT/MANIFEST,repository_root=ROOT)
    successor=PACKAGE.parent.parent/"manifest-acquisition-20261002-pg33105-notice-v4"
    if not successor.parent.is_dir() or successor.exists():
        raise ValueError("Fresh external successor package required")
    package=reconstruct(manifest,successor,_convert)
    if package.member_bytes("content.tei.xml") != CandidatePackage.load(PACKAGE).member_bytes("content.tei.xml"):
        raise ValueError("Notice successor changed reconstructed TEI")
    # The nonaccepted package retains its original header/schema limits; the
    # renewed accepted header is independently validated below.
    members={name:package.member_bytes(name) for name in package.member_names}
    bound=io_path(STAGE_V4/EDITION/"master.tei.xml").read_bytes()
    members["content.tei.xml"]=bound
    accounting=json.loads(members["source-accountability.json"])
    accounting.update(candidate_sha256=digest(bound),candidate_bytes=len(bound))
    members["source-accountability.json"]=(json.dumps(accounting,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
    class MemoryCandidate:
        sha256=digest(bound)
        def member_bytes(self,name):
            return members[name]
    oracle=_oracle(manifest,MemoryCandidate())
    if oracle["status"] != "pass":
        raise ValueError(f"Current source oracle differs: {oracle['findings']}")
    acceptance_path=STAGE_V4/EDITION/"acceptance.json"
    accepted=json.loads(io_path(acceptance_path).read_bytes())
    command="py -3 -m build.tools.refresh_chinook_notice"
    for name in ("validation","accounting","fidelity","reproducibility","schema","closure"):
        path=STAGE_V4/EVIDENCE/(name+".json")
        record=json.loads(io_path(path).read_bytes())
        record["bindings"]["historical_source_manifest"]=record["bindings"]["source_manifest"]
        record["bindings"]["source_manifest"]=manifest.sha256
        record["bindings"]["historical_package"]=record["bindings"]["package"]
        record["bindings"]["package"]=package.sha256
        record.update(current_oracle=oracle,command=command,
            successor_note="Only the dated source-entry language statement and its manifest authority changed; original replay/package bindings remain historical, retained source and master body unchanged.")
        save(path,record)
        accepted["technical"][name].update(make_file_binding(STAGE_V4,path,fixture_only=False),command=command)
    text="Retained digital witness has no page scans. Provider header says English; printed title says Chinook Jargon and interlinear English is present. Edition language mul records the bilingual/multilingual witness; no individual line language codes are inferred."
    accepted["review"]["source_quality_uncertainty"][0]=text
    review_path=STAGE_V4/EVIDENCE/"review.json"
    review=json.loads(io_path(review_path).read_bytes())
    review["source_quality_uncertainty"][0]=text
    save(review_path,review)
    accepted["review"]["report"]=make_file_binding(STAGE_V4,review_path,fixture_only=False)
    write_acceptance(acceptance_path,accepted)
    validate_acceptance(acceptance_path,root=STAGE_V4)
    validate_state(STAGE_V4/WORK/"state.json",root=STAGE_V4)
    result=project_accepted_hymns(STAGE_V4,acceptance_path=acceptance_path)
    errors=verify_accepted_hymns(STAGE_V4,acceptance_path=acceptance_path,rows=result["rows"],receipt=result["receipt"])
    if errors or len(result["rows"]) != 20 or any(row["language"] != "mul" for row in result["rows"]):
        raise ValueError(f"Current shared projection differs: {errors}")
    save(LOG/"staged-projection-v4.json",result)
    paths=[NOTICE.as_posix(),MANIFEST.as_posix(),"sources/publication-chinook/"+WID+"/README.source.md", "data/hymns/"+WID+"/README.md",
        "ocd_kernel/projection/categories/hymns.py","build/tools/install_chinook_current.py"]
    proposal=copy.deepcopy(prior)
    proposal.update(stage_root=str(STAGE_V4),supersedes="adapter-proposal-v3.json",after=_files(STAGE_V4/WORK),
        status="reviewed-shared-route-integrated",shared_dispatch_applied=True,
        notice_change="Reconcile dated source-entry omitted language with successor edition mul; no individual line codes inferred.",
        runtime_and_notice_bindings={relative:digest((ROOT/relative).read_bytes()) for relative in paths})
    proposal["successor_package"]=dict(path=str(successor),manifest_sha256=package.sha256,members={name:digest(package.member_bytes(name)) for name in package.member_names},historical_manifest_sha256=CandidatePackage.load(PACKAGE).sha256)
    save(LOG/"adapter-proposal-v4.json",proposal)
    audit=dict(status="pass",proposal_sha256=digest((LOG/"adapter-proposal-v4.json").read_bytes()),
        prior_proposal_sha256=expected,source_manifest_sha256=manifest.sha256,source_entry_notice_sha256=digest(revised),
        master_sha256=digest(bound),acceptance_sha256=digest(io_path(acceptance_path).read_bytes()),
        before=proposal["before"],after=proposal["after"],rows=20,language="mul",runtime_and_notice_bindings=proposal["runtime_and_notice_bindings"])
    save(LOG/"stage-receipt-v4.json",audit)
    print(json.dumps({key:audit[key] for key in ("status","proposal_sha256","source_manifest_sha256","source_entry_notice_sha256","master_sha256","acceptance_sha256","rows","language")},indent=2))

if __name__ == "__main__":
    main()
