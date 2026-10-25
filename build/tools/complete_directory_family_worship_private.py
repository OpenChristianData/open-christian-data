"""Reconcile one installed LIB-089 witness and verify a private offline release."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import html5lib
from lxml import etree

from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import _validate_acceptance_for_work
from ocd_kernel.tei.install_accepted import _files

ROOT=Path(__file__).resolve().parents[2]
WID="directory-for-family-worship"
WORK=Path("library/works")/WID
EDITION=WORK/"forms/directory-for-family-worship-retained-text/editions/directory-for-family-worship-retained-electronic-witness"
SOURCE=Path("raw/westminster-standard-org/directory-for-family-worship.html")
AUTHORITY=Path("sources/doctrinal-documents")/WID
SOURCE_NOTICE=Path("sources/publication-westminster")/WID/"README.source.md"
DATA_NOTICE=Path("data/prose")/WID/"README.md"
LOG=ROOT/"reports/_logs/directory-for-family-worship-private-release-20261002-v1"
JOURNAL=ROOT/".tmp_audit/accepted-install-dab46d5d4b6c41b2/operation.json"
T={"t":"http://www.tei-c.org/ns/1.0"}

def sha(content:bytes)->str:
    return hashlib.sha256(content).hexdigest()

def save(path:Path,value)->None:
    io_path(path.parent).mkdir(parents=True,exist_ok=True)
    content=value if isinstance(value,bytes) else (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
    io_path(path).write_bytes(content)

def normalized(value:str)->str:
    return re.sub(r"\s+"," ",value).strip()

def reconciliation():
    before=_files(ROOT/WORK)
    journal=json.loads(JOURNAL.read_bytes())
    if len(before)!=22 or journal["phase"]!="complete" or before!=journal["after"]:
        raise PipelineError("Original 22-file installation differs from complete journal")
    if before["work.json"]!="682bee9c9d854ed38d943c68a67acd3bfab0d4993faccb9085b6f7e1b0a2ad8e" or before["state.json"]!="bb82823f5c606c9fea2ea2d9878ee04ea472b2668fe957ccf7f824e79b3ddd5e":
        raise PipelineError("Original work/state authority changed")
    acceptance=_validate_acceptance_for_work(ROOT/EDITION/"acceptance.json",root=ROOT,work_id=WID)
    manifest_path=AUTHORITY/(WID+".source-manifest.json")
    manifest=json.loads((ROOT/manifest_path).read_bytes())
    bindings={manifest_path.as_posix():sha((ROOT/manifest_path).read_bytes())}
    for entry in manifest["authorities"]:
        raw=io_path(ROOT/entry["path"]).read_bytes()
        if sha(raw)!=entry["sha256"] or len(raw)!=entry["bytes"]:
            raise PipelineError(f"Bound source authority changed: {entry['path']}")
        bindings[entry["path"]]=entry["sha256"]
    for entry in (manifest["converter"],manifest["validator"]):
        if sha((ROOT/entry["implementation_path"]).read_bytes())!=entry["implementation_sha256"]:
            raise PipelineError("Bound historical implementation changed")
        bindings[entry["implementation_path"]]=entry["implementation_sha256"]
    master=io_path(ROOT/EDITION/"master.tei.xml").read_bytes()
    old=(ROOT/WORK/"integration/lib089-current-html-v1/inputs/package/content.tei.xml").read_bytes()
    if master.split(b"</teiHeader>",1)[1]!=old.split(b"</teiHeader>",1)[1]:
        raise PipelineError("Accepted header renewal changed the retained candidate body")
    source=(ROOT/SOURCE).read_bytes()
    html=html5lib.parse(source,treebuilder="etree",namespaceHTMLElements=False)
    carriers=[e for e in html.iter() if e.tag=="div" and "wpb_text_column" in e.get("class","").split()]
    policy=json.loads((ROOT/AUTHORITY/"validation-policy.json").read_bytes())
    tree=etree.fromstring(master,etree.XMLParser(resolve_entities=False,no_network=True))
    body=tree.xpath("./t:text/t:body",namespaces=T)[0]
    source_text=normalized("".join(carriers[0].itertext())) if carriers else ""
    headings=[normalized("".join(e.itertext())) for e in html.iter() if isinstance(e.tag,str) and re.fullmatch(r"h[1-6]",e.tag)]
    tei_headings=[normalized("".join(e.itertext())) for e in body.xpath(".//t:head",namespaces=T)]
    if len(carriers)!=2 or normalized("".join(carriers[1].itertext())) or source_text!=normalized("".join(body.itertext())) or headings!=policy["ordered_document_headings"] or tei_headings!=headings[1:]:
        raise PipelineError("Independent retained-source text, carrier, or heading boundaries differ")
    hits=[];mentions=[];unknown=[];count=0
    for relative in ("reports/_logs","exports/releases"):
        home=ROOT/relative
        if not home.exists():
            continue
        for path in io_path(home).rglob("*.json"):
            if path.name not in ("selection.json","release-selection.json"):
                continue
            count+=1
            try:
                raw=path.read_bytes()
            except OSError as exc:
                unknown.append(dict(path=str(path),error=str(exc)))
                continue
            if WID.encode() not in raw:
                continue
            record=json.loads(raw)
            matching=[item for item in record.get("items",[]) if item.get("work_id")==WID or ("/"+WID+"/") in item.get("acceptance_path","")]
            entry=dict(path=str(path),sha256=sha(raw),release_id=record.get("release_id"),items=matching)
            (hits if matching else mentions).append(entry)
    if hits or unknown:
        raise PipelineError(f"Prior release evidence requires reconciliation: {hits}; unreadable selections: {unknown}")
    if _files(ROOT/WORK)!=before:
        raise PipelineError("Work drifted during source reconciliation")
    return dict(status="pass",work_id=WID,installed_files=before,journal=str(JOURNAL),journal_sha256=sha(JOURNAL.read_bytes()),
        authority_bindings=bindings,source_text_sha256=sha(source_text.encode()),source_text_characters=len(source_text),
        source_carrier_count=2,represented_carriers=1,excluded_empty_carriers=1,ordered_headings=headings,
        source_observer="html5lib traversal independent of historical lxml producer/oracle; complete content-carrier text and ordered headings independently match the accepted readable body. Historical structure/fidelity proof is reused only with exact unchanged source, candidate-body and installed-evidence hashes.",
        historical_import_closures="Dated reproduction inputs are retained; no claim of rerunning the historical converter under current shared closure.",
        release_discovery=dict(selection_files_read=count,exact_membership_hits=hits,nonmember_mentions=mentions,unknown=unknown,
            qualification="Current search of explicit reports/_logs and exports/releases selection filenames; other evidence roots are not claimed absent."),
        human_review="not-recorded",print_identity="unverified",rights="unresolved"),acceptance

def main():
    if LOG.exists() or (ROOT/WORK/"publication").exists() or (ROOT/SOURCE_NOTICE).exists() or (ROOT/DATA_NOTICE).exists():
        raise PipelineError("Fresh work-local release and notice paths required")
    proof,accepted=reconciliation()
    LOG.mkdir(parents=True)
    save(LOG/"source-install-reconciliation.json",proof)
    visible=("# The Directory for Family Worship — source credit\n\n"
        "This private offline snapshot represents the retained electronic transcription provided by "
        "[The Westminster Standard](https://thewestminsterstandard.org/directory-for-family-worship/). "
        "The retained page credits TheWestminsterStandard as its page author. Its content includes the "
        "approving Assembly at Edinburgh act dated August 24, 1647, followed by sections I–XIV. "
        "A named printed edition has not been established or collated.\n\n"
        "The source page carries “© 2026 The Westminster Standard.” in its desktop footer and "
        "“© 2016 The Westminster Standard” in its mobile footer. These statements are preserved as "
        "provider rights evidence. The source configuration's Public Domain label for the historical "
        "work does not establish rights for this web transcription, page-local wrapper, or markup. "
        "No explicit grant for those layers is established by the retained evidence. Requested "
        "attribution and rights clearance remain unresolved; this credit does not grant permission.\n\n"
        "The complete populated source content carrier is preserved as one structured prose row, "
        "including its page-local wrapper, approving act, all fourteen numbered sections, and supported "
        "inline content. The second empty text-column shell is excluded explicitly. The page title is "
        "retained in the master header; navigation, scripts, styles, site footer, and other shell material "
        "remain retained source support outside the public row. Source spelling and wording are unchanged.\n\n"
        "Agent technical acceptance and offline checks are separate from human textual/visual review, "
        "print identity, rights clearance, and public publication. Those decisions remain unrecorded or "
        "unresolved. This snapshot was assembled privately and has not been published.\n")
    source_note=("# Publication-facing source notice — The Directory for Family Worship\n\n"
        f"The paired human-visible data notice is `{DATA_NOTICE.as_posix()}`.\n\n"
        "The historical bound source README and installed SOURCE_CREDIT.md remain unchanged. "
        "This publication-facing successor carries the existing provider credit and source-layer "
        "rights qualification to the selected data folder. It does not change source, master, acceptance, "
        "rights status, or publication authority.\n\n"+visible)
    save(ROOT/DATA_NOTICE,visible.encode())
    save(ROOT/SOURCE_NOTICE,source_note.encode())
    notice=dict(source_path=SOURCE_NOTICE.as_posix(),source_sha256=sha(source_note.encode()),notice_path=DATA_NOTICE.as_posix(),notice_sha256=sha(visible.encode()))
    selection=dict(schema_version="2.0",release_id="directory-for-family-worship-private-offline-20261002-v1",
        items=[dict(item_id=WID,category="prose",acceptance_path=(EDITION/"acceptance.json").as_posix(),public_notices=[notice])])
    if notice_texts_for_item(ROOT,selection["items"][0],ROOT/EDITION/"acceptance.json")!=[visible]:
        raise PipelineError("Paired visible notice differs")
    save(LOG/"notice-bindings.json",notice)
    output=project_accepted_prose(ROOT,acceptance_path=ROOT/EDITION/"acceptance.json")
    errors=verify_accepted_prose(ROOT,acceptance_path=ROOT/EDITION/"acceptance.json",rows=output["rows"],receipt=output["receipt"])
    if errors or len(output["rows"])!=1 or normalized(output["rows"][0]["text"])!=normalized("".join(etree.fromstring(io_path(ROOT/EDITION/"master.tei.xml").read_bytes()).xpath("./t:text/t:body",namespaces=T)[0].itertext())):
        raise PipelineError(f"Actual-master maintained projection differs: {errors}")
    save(LOG/"projection.json",output)
    inputs={**proof["authority_bindings"],**{(WORK/Path(p)).as_posix():h for p,h in proof["installed_files"].items()},
        SOURCE_NOTICE.as_posix():notice["source_sha256"],DATA_NOTICE.as_posix():notice["notice_sha256"]}
    for folder in ("ocd_kernel/release","ocd_kernel/projection","ocd_kernel/tei","ocd_kernel/library"):
        for path in (ROOT/folder).rglob("*.py"):
            inputs[path.relative_to(ROOT).as_posix()]=sha(path.read_bytes())
    for path in (ROOT/"schemas/v2").rglob("*.json"):
        inputs[path.relative_to(ROOT).as_posix()]=sha(path.read_bytes())
    for relative in ("build/tools/complete_directory_family_worship_private.py","build/tools/check_release_reader.py","build/tools/report_release_stats.py"):
        inputs[relative]=sha((ROOT/relative).read_bytes())
    save(LOG/"input-bindings-before.json",inputs)
    save(LOG/"selection.json",selection)
    release=LOG/"release"
    operations=(("assembly",lambda:assemble_release_v2(ROOT,release,selection=selection)),
        ("independent-verification",lambda:verify_release_v2(ROOT,release,selection=selection)),
        ("statistics",lambda:release_statistics(ROOT,release,selection)),("readers",lambda:check_reader(ROOT,release,selection)))
    for name,operation in operations:
        try:
            result=operation()
            if result["status"]!="pass":
                raise PipelineError(f"Failing {name} report: {result}")
        except (PipelineError,OSError,ValueError,ImportError) as exc:
            save(LOG/"guard-failure.json",dict(status="fail",gate=name,error=str(exc),publication_performed=False))
            raise
        save(LOG/(name+".json"),result)
        print(name+": pass",flush=True)
    for relative,expected in inputs.items():
        if sha(io_path(ROOT/relative).read_bytes())!=expected:
            raise PipelineError(f"Bound input drifted during gates: {relative}")
    if _files(ROOT/WORK)!=proof["installed_files"]:
        raise PipelineError("Original installation drifted during release gates")
    stats=json.loads((LOG/"statistics.json").read_bytes())
    if stats["total"]["records"]!=1 or stats["total"]["text_characters"]!=len(output["rows"][0]["text"]):
        raise PipelineError("Counted private release differs from actual-master projection")
    files={p.relative_to(release).as_posix():sha(p.read_bytes()) for p in release.rglob("*") if p.is_file()}
    completion=dict(contract="ocd-directory-family-worship-private-offline-completion-v1",status="pass",work_id=WID,
        edition_id=accepted["identity"]["edition_id"],checked_at=datetime.now(timezone.utc).isoformat(),
        master_sha256=accepted["promotion"]["master"]["sha256"],acceptance_sha256=sha(io_path(ROOT/EDITION/"acceptance.json").read_bytes()),
        rows=1,numbered_sections=14,text_characters=stats["total"]["text_characters"],release_path=str(release),
        private_offline=True,publication_performed=False,human_acceptance="not-recorded",rights_clearance="unresolved",print_identity="unverified",
        row_scope="Complete populated content carrier including approving act and I–XIV; page shell and empty carrier accounted as support/exclusions.",
        preserved_installation=proof["installed_files"],input_bindings=inputs,release_file_bindings=files,notice=notice,
        selection_sha256=sha((LOG/"selection.json").read_bytes()),
        gate_bindings={name:sha((LOG/(name+".json")).read_bytes()) for name,_ in operations})
    readme=("# Directory for Family Worship — private offline completion\n\n"
        "The unchanged accepted retained HTML witness and 22-file installation pass source/master "
        "reconciliation, actual-master projection, private assembly, independent verification, statistics, "
        "and normal/streaming readers. One structured prose row preserves the approving act and all "
        f"fourteen numbered sections ({completion['text_characters']:,} text characters).\n\n"
        f"[Completion receipt](completion.json) binds the installed generation, current runtime inputs, "
        f"paired visible notices, four release gates, and seven release files. Detailed receipts: "
        "`reports/_logs/directory-for-family-worship-private-release-20261002-v1/`.\n\n"
        "Human review, named print identity, provider-transcription and wrapper rights remain unresolved. "
        "No source/master/acceptance was rewritten; no public publication occurred.\n")
    save(ROOT/WORK/"publication/README.md",readme.encode())
    save(LOG/"completion.json",completion)
    save(ROOT/WORK/"publication/completion.json",completion)
    expected={**proof["installed_files"],"publication/README.md":sha(readme.encode()),"publication/completion.json":sha((LOG/"completion.json").read_bytes())}
    if _files(ROOT/WORK)!=expected:
        raise PipelineError("Final work generation differs from unchanged installation plus completion deliverables")
    audit=dict(status="pass",work_id=WID,completion_sha256=sha((LOG/"completion.json").read_bytes()),canonical_files=expected,
        input_bindings=inputs,release_file_bindings=files,gate_bindings=completion["gate_bindings"],source_install_reconciliation_sha256=sha((LOG/"source-install-reconciliation.json").read_bytes()),
        publication_performed=False,human_acceptance="not-recorded",rights_clearance="unresolved",print_identity="unverified")
    save(LOG/"final-audit.json",audit)
    save(ROOT/"plans/2026-08-31-library-pipeline-redesign/evidence/DIRECTORY_FAMILY_WORSHIP_PRIVATE_RELEASE_20261002.json",
        dict(status="private-offline-complete",work_id=WID,edition_id=completion["edition_id"],completion_path=(WORK/"publication/completion.json").as_posix(),completion_sha256=audit["completion_sha256"],
            audit_path="reports/_logs/directory-for-family-worship-private-release-20261002-v1/final-audit.json",audit_sha256=sha((LOG/"final-audit.json").read_bytes()),rows=1,numbered_sections=14,text_characters=completion["text_characters"],
            human_acceptance="not-recorded",rights_clearance="unresolved",print_identity="unverified",publication_performed=False))
    print(json.dumps(dict(status="pass",rows=1,text_characters=completion["text_characters"],completion_sha256=audit["completion_sha256"],inputs=len(inputs),release_files=len(files)),indent=2),flush=True)

if __name__=="__main__":
    main()
