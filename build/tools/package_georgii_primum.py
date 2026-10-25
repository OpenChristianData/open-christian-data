"""Bind clean-process replay and source-feature mutations for the first Georgius epitaph."""
from __future__ import annotations
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei.georgii_primum_oracle import check
from build.tools import prepare_georgii_primum as parts
from ocd_kernel.reconstruction import CandidatePackage
from ocd_kernel.tei.install_accepted import _files, _io_path

HOME = parts.SIDE_HOME / parts.WORK_ID
TEI = "{http://www.tei-c.org/ns/1.0}"
def _sha(p): return sha256(_io_path(p).read_bytes()).hexdigest()

def challenge(source: bytes, candidate: bytes) -> dict:
    baseline=check(source,candidate)
    findings=[]
    names=("collection-heading","source-wording","omit-line","line-order","line-number-attribute","physical-id","text-attachment","closing-wording","sibling-inclusion","duplicate-line")
    for name in names:
        root=etree.fromstring(candidate,etree.XMLParser(resolve_entities=False,no_network=True))
        ab=root.find(f"{TEI}text/{TEI}body")[0][0]
        before=etree.tostring(ab,method="c14n")
        if name=="collection-heading":ab[0].tail=ab[0].tail.replace("TRIPLEX","SIMPLEX")
        elif name=="source-wording":ab[1].tail=ab[1].tail.replace("Quis mea","Quae mea")
        elif name=="omit-line":ab.remove(ab[3])
        elif name=="line-order":
            node=ab[2];ab.remove(node);ab.append(node)
        elif name=="line-number-attribute":ab[3].set("n","99")
        elif name=="physical-id":ab[3].set("{http://www.w3.org/XML/1998/namespace}id","invented-line-id")
        elif name=="text-attachment":ab[3].text,ab[3].tail=ab[3].tail,None
        elif name=="closing-wording":ab[-1].tail=ab[-1].tail.replace("fuerit.","erit.")
        elif name=="sibling-inclusion":
            source_root=etree.fromstring(source,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
            node=source_root.xpath("//*[@xml:id='bsb00000720_00271_17']")[0];ab.append(deepcopy(node))
        else:
            duplicate=deepcopy(ab[1]);duplicate.set("{http://www.w3.org/XML/1998/namespace}id","invented-duplicate-line");ab.append(duplicate)
        if etree.tostring(ab,method="c14n")==before:raise ValueError(f"mutation did not change source carrier: {name}")
        changed=etree.tostring(root)
        try:check(source,changed)
        except ValueError as error:
            if "complete first-epitaph carrier trees differ" not in str(error):raise ValueError(f"unexpected mutation rejection {name}: {error}") from error
            findings.append(dict(mutation=name,status="rejected",reason=str(error),candidate_sha256=sha256(changed).hexdigest()))
        else:raise ValueError(f"mutation escaped oracle: {name}")
    return dict(baseline=baseline,mutations=findings)

def run(original: Path, replay: Path, receipt: Path) -> dict:
    if receipt.exists(): raise ValueError("fresh receipt required")
    a,b=CandidatePackage.load(original/"package"),CandidatePackage.load(replay/"package")
    if a.sha256!=b.sha256 or _files(original/"package")!=_files(replay/"package"): raise ValueError("clean process package replay differs")
    for package in (original,replay):
        validation=json.loads(_io_path(package/"validation.json").read_bytes())
        if validation["status"]!="pass" or validation["findings"]: raise ValueError("package validation failed")
    home=parts.ROOT/HOME;profile=json.loads((home/"reconstruction-profile.json").read_bytes())
    proof=challenge(_io_path(parts.ROOT/parts.SOURCE).read_bytes(),a.member_bytes("content.tei.xml"))
    proof["clean_process_mirrors"]=[json.loads((p/"mirror-provenance.json").read_bytes()) for p in (original,replay)]
    proof.update(replay_package_sha256=b.sha256,replay_members=_files(replay/"package"),replay_root=replay.as_posix())
    manifest=HOME/"source-manifest.json"; profile_rel=HOME/"reconstruction-profile.json"; boundary=HOME/"boundary-review.json"
    result=dict(contract="ocd-georgii-primum-packages-v1",source_sha256=parts.SOURCE_SHA,frozen_batch_path=parts.BATCH.as_posix(),frozen_batch_sha256=parts.BATCH_SHA,challenge=proof,works=[dict(work_id=parts.WORK_ID,category="poetry",language="la",manifest_path=manifest.as_posix(),manifest_sha256=_sha(parts.ROOT/manifest),profile_path=profile_rel.as_posix(),profile_sha256=_sha(parts.ROOT/profile_rel),boundary_path=boundary.as_posix(),boundary_sha256=_sha(parts.ROOT/boundary),acquisition_path=profile["acquisition_path"],acquisition_sha256=profile["acquisition_sha256"],work_sidecar_sha256=_sha(parts.ROOT/"library/works"/parts.WORK_ID/"work.json"),package_root=original.as_posix(),package_sha256=a.sha256,validation_sha256=_sha(original/"validation.json"),candidate_tei_sha256=_sha(original/"package/content.tei.xml"))])
    receipt.parent.mkdir(parents=True,exist_ok=True);receipt.write_bytes(parts._json(result));return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("original",type=Path);p.add_argument("replay",type=Path);p.add_argument("receipt",type=Path);a=p.parse_args();r=run(a.original,a.replay,a.receipt);print(json.dumps(dict(package_sha256=r["works"][0]["package_sha256"],mutations=len(r["challenge"]["mutations"]))))
if __name__=="__main__": main()
