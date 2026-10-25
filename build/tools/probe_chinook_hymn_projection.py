"""Freeze a work-local mapping proposal and metadata-only staging successor."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import shutil

from build.tools.prepare_chinook_current import ROOT, STAGE, LOG, WORK, EDITION, WID, EID, FID, digest, save
from build.tools.prepare_chinook_notices import SOURCE_NOTICE, DATA_NOTICE
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library._common import io_path
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.chinook_hymns import project_chinook_document, verify_chinook_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files

STAGE_V3 = ROOT / ".tmp_audit/chinook-acceptance-20261002-v3"

def main() -> None:
    if STAGE_V3.exists():
        raise ValueError("New metadata/projection stage required")
    receipt = json.loads((LOG / "stage-receipt.json").read_bytes())
    if _files(ROOT / WORK) != receipt["before"] or _files(STAGE / WORK) != receipt["after"]:
        raise ValueError("Canonical preimage or prior immutable stage changed")
    shutil.copytree(io_path(STAGE), io_path(STAGE_V3))
    old_work = json.loads((ROOT / WORK / "work.json").read_bytes())
    work = copy.deepcopy(old_work)
    edition = work["textual_forms"][0]["editions"][0]
    if edition["edition_id"] != EID or "category" in edition or "language" in edition:
        raise ValueError("Edition metadata preimage differs")
    edition.update(category="hymns", language="mul")
    validate_identity_update(old_work,work)
    save(STAGE_V3 / WORK / "work.json",work)
    load_work(STAGE_V3 / WORK / "work.json")
    for path in (SOURCE_NOTICE,DATA_NOTICE):
        io_path((STAGE_V3/path).parent).mkdir(parents=True,exist_ok=True)
        shutil.copy2(io_path(ROOT/path),io_path(STAGE_V3/path))
    accepted = validate_acceptance(STAGE_V3 / EDITION / "acceptance.json",root=STAGE_V3)
    validate_state(STAGE_V3 / WORK / "state.json",root=STAGE_V3)
    metadata = dict(retained_path=STAGE_V3 / "raw/gutenberg/33105/html/pg33105-images.html",
        identity=dict(work_id=WID,textual_form_id=FID,edition_id=EID),language="mul",
        representation_revision=accepted["representation_revision"]["id"],edition_title=edition["title"])
    result = project_chinook_document(STAGE_V3 / EDITION / "master.tei.xml",**metadata)
    if errors := verify_chinook_document(STAGE_V3 / EDITION / "master.tei.xml",result["rows"],result["receipt"],**metadata):
        raise ValueError(f"Independent source projection errors: {errors}")
    save(LOG / "staged-projection-v2.json",result)
    proposal = dict(contract="ocd-chinook-paired-hymn-adapter-proposal-v1",status="proposal-not-dispatched",work_id=WID,
        stage_root=str(STAGE_V3),original_stage_receipt_sha256=digest((LOG/"stage-receipt.json").read_bytes()),
        before=receipt["before"],after=_files(STAGE_V3 / WORK),
        metadata_before_sha256=receipt["before"]["work.json"],metadata_after_sha256=digest((STAGE_V3/WORK/"work.json").read_bytes()),
        metadata_change="Only this edition gains category hymns and language mul, meaning source-attested multiple languages. No identity, acquisition, source or body changes.",
        language_code_evidence=dict(url="https://www.loc.gov/standards/iso639-2/php/code_list.php",code="mul",label="Multiple languages",verified_at_utc="2026-10-02",source_basis="Title Chinook Jargon, paired English translation sections, and No.20 source statement In four languages"),
        proposed_dispatch=["Exact work ID l744-pg33105-chinook-hymns in project_accepted_hymns calls project_chinook_document with the same metadata keys as the existing L741 adapter.",
            "Same exact work ID in verify_accepted_hymns calls verify_chinook_document after removing authority from receipt, as the existing L741 route does."],
        adapter_path="ocd_kernel/projection/categories/chinook_hymns.py",adapter_sha256=digest((ROOT/"ocd_kernel/projection/categories/chinook_hymns.py").read_bytes()),
        test_path="tests/test_chinook_hymns_projection.py",test_sha256=digest((ROOT/"tests/test_chinook_hymns_projection.py").read_bytes()),
        rows=20,sections=40,stanzas=195,text_characters=sum(len(row["text"]) for row in result["rows"]),
        source_observer="html5lib direct source-child traversal; no producer traversal called. Shared row-envelope constructor and receipt builder are acknowledged; master body is independently byte-pinned.",
        test_result="13 passed; lyric/translation/section/order/number/tune/first-line/omission/invention/source/master mutations and producer-disabled observer.",
        prior_environmental_test_failure="Initial unique configured sandbox basetemp was unreadable (WinError5) for two tmp_path setups; eleven tests passed. Neither temp directory nor fixture files were created. Tests now inject exact altered input bytes without temporary I/O; all thirteen pass.",
        source_prayers_excluded=True,interlinear_tables_preserved_in_master=142,
        suggested_friction_entry="PG33105: generic hymns route cannot read the faithful complete HTML-derived master; source-specific 20 numbered hymn/translation paired sections fit existing sections schema. Keep the 142 interlinear tables in the complete master outside the hymn-row selection. Validate independent source boundaries and exact work dispatch; avoid code-inferred language tagging.",
        shared_dispatch_applied=False,canonical_install=False,public_publication=False,human_acceptance="not-recorded",rights="unresolved")
    save(LOG / "adapter-proposal-v2.json",proposal)
    print(json.dumps({key:proposal[key] for key in ("status","stage_root","rows","sections","stanzas","text_characters","metadata_after_sha256","adapter_sha256")},indent=2))

if __name__ == "__main__":
    main()
