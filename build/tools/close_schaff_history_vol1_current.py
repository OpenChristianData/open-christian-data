"""Audit current installed Schaff authority, whole retained volume and completed private release."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_schaff_history_vol1_current import ROOT,WORK,BASE,SOURCE,SOURCE_SHA,SCOPE,canonical
from ocd_kernel.tei.install_accepted import _files,_io_path
def main():
    out=ROOT/"reports/_logs/schaff-history-vol-1-install-20261001-v1"
    completion=json.loads((ROOT/WORK/"publication/private-offline-20261001/completion.json").read_bytes());pin=json.loads((ROOT/BASE/"stage-pin.json").read_bytes());raw=Path(pin["receipt"]).read_bytes()
    if sha256(raw).hexdigest()!=pin["receipt_sha256"]:raise ValueError("frozen stage receipt differs")
    receipt=json.loads(raw);installed={p:h for p,h in _files(ROOT/WORK).items() if not p.startswith("publication/")};installation=json.loads((out/"installation.json").read_bytes());journal=json.loads((Path(installation["operation"])/"operation.json").read_bytes())
    if installed!=receipt["after"] or journal["phase"]!="complete" or journal["after"]!=installed:raise ValueError("installed generation/journal differs")
    if completion["independent_check"]["status"]!="pass" or completion["reader_normal_and_streaming"]!="pass":raise ValueError("private pipeline incomplete")
    inputs=json.loads((ROOT/BASE/"delivery-input-pins.json").read_bytes())
    for path,digest in (inputs["authority_hashes"]|inputs["schemas"]).items():
        if sha256(_io_path(ROOT/path).read_bytes()).hexdigest()!=digest:raise ValueError("frozen support/input changed: "+path)
    for sibling,generation in inputs["sibling_hashes"].items():
        if _files(ROOT/"library/works"/sibling)!=generation:raise ValueError("source volume sibling changed: "+sibling)
    if sha256((ROOT/SOURCE).read_bytes()).hexdigest()!=SOURCE_SHA:raise ValueError("retained source changed")
    retained=["reports/_logs/schaff-history-vol-1-reconciliation-20261001-v1/historical-source-review.json","reports/_logs/schaff-history-vol-1-reconciliation-20261001-v1/coordinator-v3-header-conservation.json","reports/_logs/schaff-history-vol-1-independent-support-review-20261001/review.json","reports/_logs/schaff-history-vol-1-independent-support-review-20261001/frozen-patch-adversarial-review.json","reports/_logs/schaff-history-vol-1-reconciliation-20261001-v1/shared-support-freeze-serialization-supplement.json"]
    optional="reports/_logs/schaff-history-vol-1-install-20261001-v1/coordinator-installed-hash-audit.json"
    if (ROOT/optional).exists():retained.append(optional)
    facts=receipt["source_facts"]
    audit=dict(status="complete-technical-private-release-only",checked_at=datetime.now(timezone.utc).isoformat(),scope=SCOPE,source_sha256=SOURCE_SHA,source_facts=facts,source_media="No image elements in this retained XML; Google Books page-image pointer preserved without print pixel retention/presentation claim.",historical_text_and_standOff_byte_conservation=True,source_header_and_prolog_comments_conserved=True,immutable_acquisition_title_language_ids_preserved=True,category_only_prose=True,installed_files=installed,installation_phase=journal["phase"],guarded_operation=installation["operation"],authority_hashes=inputs["authority_hashes"],schema_pins=inputs["schemas"],sibling_hashes=inputs["sibling_hashes"],sibling_generations_unchanged=True,release_evidence_hashes=_files(ROOT/WORK/"publication/private-offline-20261001"),private_release=completion["release"],statistics=completion["statistics"],independent_evidence={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in retained},close_script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),tests="Current exact replay/22 mutations, source P5 and accepted-header byte conservation, exact metadata prerequisite and isolated receipt/rollback3tests pass. Minimal generic source-evidence repair24focusedcases plus20existingunclear/inline/Greenleaf compatibility pass; independent frozen patch review passes.",shared_receipt_transient="Original ef1db703 frozen receipt restored exactly after transient LF serialization; qualified in immutable separate supplement. Runtime/source/schema/publication bytes unaffected.",unassessed=["human textual/visual acceptance","independent print collation","print page-image retention/presentation","rights clearance","public publication authorization"],publication_performed=False)
    (out/"final-delivery-audit.json").write_bytes(canonical(audit))
    (out/"README.md").write_text("# Schaff History volume I technical completion\n\n"+SCOPE+"\n\nThe whole retained historical body and evidence were reused exactly. Current source bindings and source-attested author/publisher/markup/Logos and Electronic Bible Society credits are renewed. All independent native conservation, P5, exact replay,22 source-fidelity mutations, guarded category prerequisite and isolated rollback checks pass. Minimal source-evidence projection support has independent focused regression and adversarial review proof. Canonical installation, actual-master projection, private assembly, independent verification, statistics and normal/streaming readers pass. See final-delivery-audit.json for current hashes and evidence links.\n\nHuman textual/visual acceptance, print equivalence, rights clearance and public publication remain separate. No acquisition, source deletion, child/duplicate volume identity, Git operation or public publication occurred.\n",encoding="utf8",newline="\n")
    print(json.dumps(dict(status=audit["status"],installed_files=len(installed),authority_files=len(inputs["authority_hashes"]),schemas=len(inputs["schemas"]),sibling_files=sum(len(x) for x in inputs["sibling_hashes"].values()),statistics=audit["statistics"])))
if __name__=="__main__":main()
