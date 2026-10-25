"""Bind clean-process replay and source-feature mutations for York tractate IV."""
from __future__ import annotations
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei.openmgh_bsb830_york_four_oracle import check
from build.tools import prepare_openmgh_bsb830_york_four as parts
from ocd_kernel.reconstruction import CandidatePackage
from ocd_kernel.tei.install_accepted import _files, _io_path

HOME = parts.SIDE_HOME / parts.WORK_ID
TEI = "{http://www.tei-c.org/ns/1.0}"
def _sha(p): return sha256(_io_path(p).read_bytes()).hexdigest()

def challenge(source: bytes, candidate: bytes) -> dict:
    bound = dict(first_id="bsb00000830_00671_6",last_id="bsb00000830_00688_27",part_ordinal=4)
    baseline = check(source,candidate,**bound)
    failures=[]
    for name in ("breakoff-dots","invention","omit-line","word-link","inline-attachment","duplicate-word","sibling-inclusion"):
        root=etree.fromstring(candidate,etree.XMLParser(resolve_entities=False,no_network=True))
        part=root.find(f"{TEI}text/{TEI}body")[0][0]; ab=part[0]
        if name=="breakoff-dots": ab[-1].tail=ab[-1].tail.replace("......",".")
        elif name=="invention": ab[-1].tail += "Invented completion."
        elif name=="omit-line":
            node=ab.find(f"{TEI}lb"); ab.remove(node)
        elif name=="word-link": ab.find(f"{TEI}w").set("corresp","#outside")
        elif name=="inline-attachment":
            node=ab.find(f"{TEI}hi");ab.remove(node);ab.append(node)
        elif name=="duplicate-word":
            duplicate=deepcopy(ab.find(f"{TEI}w")); duplicate.set("{http://www.w3.org/XML/1998/namespace}id","invented-duplicate");ab.append(duplicate)
        else:
            source_root=etree.fromstring(source,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
            parent=source_root.xpath("//tei:div[@type='work'][@n='Tract. Eboracenses']",namespaces={"tei":TEI[1:-1]})[0]
            root.find(f"{TEI}text/{TEI}body")[0].append(deepcopy(parent[5]))
        altered=etree.tostring(root)
        if altered==candidate: raise ValueError(f"mutation did not change candidate: {name}")
        try: check(source,altered,**bound)
        except ValueError as error:
            expected="candidate is not one separately addressable work" if name=="sibling-inclusion" else "complete source and candidate part trees differ"
            if expected not in str(error): raise ValueError(f"mutation rejected for unexpected reason: {name}: {error}") from error
            failures.append(dict(mutation=name,status="rejected",reason=str(error),candidate_sha256=sha256(altered).hexdigest()))
        else: raise ValueError(f"mutation escaped oracle: {name}")
    return dict(baseline=baseline,mutations=failures)

def run(original: Path, replay: Path, receipt: Path) -> dict:
    if receipt.exists(): raise ValueError("fresh receipt required")
    a,b=CandidatePackage.load(original/"package"),CandidatePackage.load(replay/"package")
    if a.sha256!=b.sha256 or _files(original/"package")!=_files(replay/"package"): raise ValueError("clean process package replay differs")
    for package in (original,replay):
        validation=json.loads(_io_path(package/"validation.json").read_bytes())
        if validation["status"]!="pass" or validation["findings"]: raise ValueError("package validation failed")
    home=parts.ROOT/HOME;profile=json.loads((home/"reconstruction-profile.json").read_bytes())
    proof=challenge(_io_path(parts.ROOT/parts.SOURCE).read_bytes(),a.member_bytes("content.tei.xml"))
    proof.update(replay_package_sha256=b.sha256,replay_members=_files(replay/"package"),replay_root=replay.as_posix())
    manifest=HOME/"source-manifest.json"; profile_rel=HOME/"reconstruction-profile.json"; boundary=HOME/"boundary-review.json"
    result=dict(contract="ocd-openmgh-bsb830-york-four-packages-v1",source_sha256=parts.SOURCE_SHA,frozen_batch_path=parts.BATCH.as_posix(),frozen_batch_sha256=parts.BATCH_SHA,challenge=proof,works=[dict(work_id=parts.WORK_ID,category="prose",language="la",manifest_path=manifest.as_posix(),manifest_sha256=_sha(parts.ROOT/manifest),profile_path=profile_rel.as_posix(),profile_sha256=_sha(parts.ROOT/profile_rel),boundary_path=boundary.as_posix(),boundary_sha256=_sha(parts.ROOT/boundary),acquisition_path=profile["acquisition_path"],acquisition_sha256=profile["acquisition_sha256"],work_sidecar_sha256=_sha(parts.ROOT/"library/works"/parts.WORK_ID/"work.json"),package_root=original.as_posix(),package_sha256=a.sha256,validation_sha256=_sha(original/"validation.json"),candidate_tei_sha256=_sha(original/"package/content.tei.xml"))])
    receipt.parent.mkdir(parents=True,exist_ok=True);receipt.write_bytes(parts._json(result));return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("original",type=Path);p.add_argument("replay",type=Path);p.add_argument("receipt",type=Path);a=p.parse_args();r=run(a.original,a.replay,a.receipt);print(json.dumps(dict(package_sha256=r["works"][0]["package_sha256"],mutations=len(r["challenge"]["mutations"]))))
if __name__=="__main__": main()
