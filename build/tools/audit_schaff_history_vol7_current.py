"""Freeze current inputs or close the complete HCC7 private delivery without reruns."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_schaff_history_vol7_current import ROOT,WORK,BASE,SOURCE,SOURCE_SHA,SCOPE,canonical
from ocd_kernel.tei.install_accepted import _files,_io_path

OUT=ROOT/"reports/_logs/schaff-history-vol-7-install-20261001-v1"
PUBLICATION=WORK/"publication/private-offline-20261001"

def digest(path):return sha256(_io_path(path).read_bytes()).hexdigest()

def freeze():
    own=[f"build/tei/schaff_history_vol7_current_{suffix}.py" for suffix in ("reconstruction","oracle")]
    own += [f"build/tools/{prefix}_schaff_history_vol7_current.py" for prefix in ("prepare","run","package","stage","install","freeze","release","audit")]
    own += ["tests/test_schaff_history_vol7_current_install.py"]
    own += ["reports/_logs/schaff-history-vol-7-reconciliation-20261001-v1/source-preflight.json", "reports/_logs/schaff-history-vol-7-reconciliation-20261001-v1/source-mapping-review.json"]
    own += [p.relative_to(ROOT).as_posix() for p in (ROOT/BASE).iterdir() if p.is_file() and p.name!="delivery-input-pins.json"]
    own += [SOURCE.as_posix(),"data/prose/schaff-history-vol-7/README.md","docs/sources/ccel-permission.md","ocd_kernel/projection/source_projection_evidence.py","ocd_kernel/projection/native_content.py","ocd_kernel/projection/native_content_check.py","ocd_kernel/projection/categories/native_documents.py","ocd_kernel/projection/categories/prose.py","ocd_kernel/release/assemble.py","ocd_kernel/release/verify.py","ocd_kernel/release/notices.py","build/tools/check_release_reader.py","build/tools/report_release_stats.py","ocd_kernel/tei/vendor/xsd/tei_all.xsd","build/tei/schaff_history_vol7_reconstruction.py","build/tei/schaff_history_vol7_oracle.py"]
    manifest=json.loads((ROOT/BASE/"source-manifest.json").read_bytes());own += [a["path"] for a in manifest["authorities"]]
    schemas={p.relative_to(ROOT).as_posix():digest(p) for p in sorted((ROOT/"schemas/v2").rglob("*.json"))}
    # Volumes V and VI have separately authorized active owners. Do not freeze its
    # changing canonical generation as though this work owns that operation.
    siblings={"schaff-history-vol-"+str(number):_files(ROOT/"library/works"/("schaff-history-vol-"+str(number))) for number in (1,2,3,4,8)}
    record=dict(checked_at=datetime.now(timezone.utc).isoformat(),authority_hashes={p:digest(ROOT/p) for p in sorted(set(own))},schemas=schemas,sibling_hashes=siblings,active_peer_exception="Schaff volume V is owned by Gregory and volume VI by Nancy; their active generations are excluded from stable sibling freezing and no file in either work is written by this route.")
    (ROOT/BASE/"delivery-input-pins.json").write_bytes(canonical(record));print(json.dumps(dict(status="frozen",authority_files=len(record["authority_hashes"]),schemas=len(schemas),sibling_files=sum(map(len,siblings.values())))))

def close():
    completion=json.loads((ROOT/PUBLICATION/"completion.json").read_bytes());pin=json.loads((ROOT/BASE/"stage-pin.json").read_bytes());raw=Path(pin["receipt"]).read_bytes()
    if sha256(raw).hexdigest()!=pin["receipt_sha256"]:raise ValueError("frozen stage receipt differs")
    receipt=json.loads(raw);installed={p:h for p,h in _files(ROOT/WORK).items() if not p.startswith("publication/")}
    installation=json.loads((OUT/"installation.json").read_bytes());journal=json.loads((Path(installation["operation"])/"operation.json").read_bytes())
    if installed!=receipt["after"] or journal["phase"]!="complete" or journal["after"]!=installed:raise ValueError("installed generation/journal differs")
    if completion["independent_check"]["status"]!="pass" or completion["reader_normal_and_streaming"]!="pass":raise ValueError("private release incomplete")
    inputs=json.loads((ROOT/BASE/"delivery-input-pins.json").read_bytes())
    for p,h in (inputs["authority_hashes"]|inputs["schemas"]).items():
        if digest(ROOT/p)!=h:raise ValueError("current input differs: "+p)
    for sibling,files in inputs["sibling_hashes"].items():
        if _files(ROOT/"library/works"/sibling)!=files:raise ValueError("sibling changed: "+sibling)
    if digest(ROOT/SOURCE)!=SOURCE_SHA:raise ValueError("retained source differs")
    source_review="reports/_logs/schaff-history-vol-7-coordinator-source-review-20261001/review.json"
    if not (ROOT/source_review).is_file():raise ValueError("coordinator source review absent")
    independent={source_review:digest(ROOT/source_review)}
    for directory in ("schaff-history-vol-7-install-20261001-v1","schaff-history-vol-7-coordinator-source-review-20261001"):
        p="reports/_logs/"+directory+"/coordinator-installed-hash-audit.json"
        if (ROOT/p).is_file():independent[p]=digest(ROOT/p)
    report=dict(status="complete-technical-private-release-only",checked_at=datetime.now(timezone.utc).isoformat(),scope=SCOPE,source_sha256=SOURCE_SHA,source_facts=receipt["source_facts"],source_media="No image elements occur in the retained XML; independent print-pixel collation is unclaimed.",native_reconstruction=True,source_header_and_prolog_comments_conserved=True,immutable_acquisition_title_language_ids_preserved=True,category_only_prose=True,installed_files=installed,installation_phase=journal["phase"],guarded_operation=installation["operation"],authority_hashes=inputs["authority_hashes"],schema_pins=inputs["schemas"],sibling_hashes=inputs["sibling_hashes"],active_peer_exception=inputs["active_peer_exception"],release_evidence_hashes=_files(ROOT/PUBLICATION),private_release=completion["release"],statistics=completion["statistics"],independent_evidence=independent,tests="Complete source-native oracle/P5, byte-exact fresh package and accepted-header replay, 29 source-faithfulness mutations, exact category prerequisite and isolated receipt/rollback tests pass. Shared helper compatibility proof remains its separate dated evidence.",unassessed=["human textual/visual acceptance","independent print collation","rights clearance","public publication authorization"],publication_performed=False)
    (OUT/"final-delivery-audit.json").write_bytes(canonical(report))
    (OUT/"README.md").write_text("# Schaff History volume VII technical completion\n\n"+SCOPE+"\n\nThe historical escaped XML-line route is preserved as history. The complete native reconstruction passes an independently traversed source oracle, source-grounded coordinator comparison, TEI P5, fresh-process exact replay, 29 meaningful mutations, pinned category-only prerequisite and isolated guarded rollback. Actual-master projection, private assembly, independent verification, statistics and normal/streaming readers pass. See final-delivery-audit.json for current bindings.\n\nVisible source/data notices carry the literal author, publisher, transcriber, markup and edition-history credits and CCEL formatting restrictions. Empty source rights are explicit. Human/visual acceptance, independent print equivalence, rights clearance and publication remain separate. No new acquisition or public publication occurred.\n",encoding="utf8",newline="\n")
    print(json.dumps(dict(status=report["status"],installed_files=len(installed),authority_files=len(inputs["authority_hashes"]),schemas=len(inputs["schemas"]),sibling_files=sum(map(len,inputs["sibling_hashes"].values())),statistics=report["statistics"])))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--freeze",action="store_true");args=parser.parse_args()
    freeze() if args.freeze else close()

if __name__=="__main__":main()
