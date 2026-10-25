"""Apply only the pinned prose prerequisite, then use the shared guarded installer."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_aquinas_four_current import ROOT, WORK_ID, WORK, EDITION, TITLE, SOURCE_SHA, canonical
from ocd_kernel.library._common import io_path, PipelineError
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, install_accepted_work


def metadata_change(original, revised):
    expected = json.loads(canonical(original))
    if (original["work_id"] != WORK_ID or original["title"] != TITLE
            or original["textual_forms"][0]["language"] != "en"
            or original["textual_forms"][0]["editions"][0]["language"] != "en"
            or "category" in original["textual_forms"][0]["editions"][0]):
        raise PipelineError("exact Aquinas four-component witness collection metadata preimage differs")
    expected["textual_forms"][0]["editions"][0]["category"] = "prose"
    if revised != expected:
        raise PipelineError("metadata exceeds exact one-field prose prerequisite")
    validate_identity_update(original, revised)


def install(root, promoted, receipt_sha, evidence, *, fail_at=None, runtime_supplement=None, supplement_sha=None):
    root = root.resolve(strict=True)
    promoted = promoted.resolve(strict=True)
    stage_bytes = (promoted / "stage-receipt.json").read_bytes()
    if sha256(stage_bytes).hexdigest() != receipt_sha:
        raise PipelineError("frozen Aquinas four-component witness collection stage receipt differs")
    receipt = json.loads(stage_bytes)
    current_schemas = {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in receipt["schema_pins"]}
    current_runtime = {p:sha256((ROOT/p).read_bytes()).hexdigest() for p in receipt["runtime_pins"]}
    if runtime_supplement is None:
        if current_schemas != receipt["schema_pins"] or current_runtime != receipt["runtime_pins"]:
            raise PipelineError("frozen stage dependency differs; exact reviewed supplement required")
    else:
        from build.tools.check_aquinas_four_current_runtime import validate_closed_pins, EXTRA, REVIEWS, STAGE_SHA
        raw_supplement = io_path(runtime_supplement).read_bytes()
        if not supplement_sha or sha256(raw_supplement).hexdigest() != supplement_sha or receipt_sha != STAGE_SHA:
            raise PipelineError("exact reviewed current supplement binding differs")
        supplement = json.loads(raw_supplement)
        validate_closed_pins(receipt, current_runtime, current_schemas)
        if (supplement["status"] != "pass" or supplement["original_stage_sha256"] != receipt_sha
                or supplement["before"] != receipt["before"] or supplement["after"] != receipt["after"]
                or supplement["runtime_pins"] != current_runtime or supplement["schema_pins"] != current_schemas
                or supplement["extra_reviewed_closure"] != EXTRA or supplement["coordinator_reviews"] != REVIEWS
                or not supplement["producer_disabled"] or supplement["errors"] or supplement["rows"] != 4
                or not supplement["saved_projection"]["byte_identical"] or supplement["projection_repeated"]):
            raise PipelineError("closed current supplement scope or check differs")
        for path, expected in EXTRA.items() | REVIEWS.items():
            if sha256(io_path(ROOT/path).read_bytes()).hexdigest() != expected:
                raise PipelineError("reviewed current closure differs: " + path)
        saved = supplement["saved_projection"]
        original_projection = promoted / WORK / "integration/aquinas-four-current-v1/stage-projection.json"
        if (sha256(io_path(ROOT/saved["path"]).read_bytes()).hexdigest() != saved["sha256"]
                or saved["sha256"] != sha256(io_path(original_projection).read_bytes()).hexdigest()
                or supplement["master_sha256"] != receipt["master_sha256"]
                or supplement["acceptance_sha256"] != sha256(io_path(promoted/EDITION/"acceptance.json").read_bytes()).hexdigest()):
            raise PipelineError("saved current rows or accepted generation differs")
    if (receipt["work_id"] != WORK_ID or receipt["source_sha256"] != SOURCE_SHA
            or receipt["category"] != "prose" or receipt["language"] != "en"
            or receipt["status"] != "pass" or receipt["rows"] != 4
            or _files(root / WORK) != receipt["before"]
            or _files(promoted / WORK) != receipt["after"]):
        raise PipelineError("work/scope/stage generation changed")
    original_bytes = io_path(root / WORK / "work.json").read_bytes()
    revised_bytes = io_path(promoted / WORK / "work.json").read_bytes()
    metadata_change(json.loads(original_bytes), json.loads(revised_bytes))
    for path, digest in receipt["before"].items():
        if path not in {"work.json", "state.json"} and receipt["after"].get(path) != digest:
            raise PipelineError("staged existing authority differs: " + path)
    acceptance = validate_acceptance(promoted / EDITION / "acceptance.json", root=promoted)
    if acceptance["source"]["source_sha256"] != SOURCE_SHA:
        raise PipelineError("accepted source differs")
    candidate_path = Path(acceptance["technical"]["candidate"]["path"])
    if io_path(promoted / EDITION / "master.tei.xml").read_bytes() != io_path(promoted / candidate_path).read_bytes():
        raise PipelineError("promoted master differs from reviewed candidate")
    evidence.mkdir(parents=True, exist_ok=False)
    (evidence / "original-work.json").write_bytes(original_bytes)
    (evidence / "staged-receipt.json").write_bytes(stage_bytes)
    if runtime_supplement is not None:
        (evidence / "current-runtime-supplement.json").write_bytes(raw_supplement)
    (evidence / "metadata-prerequisite.json").write_bytes(canonical(dict(status="pinned",
        changed_fields=["textual_forms[0].editions[0].category"], before_sha256=sha256(original_bytes).hexdigest(),
        after_sha256=sha256(revised_bytes).hexdigest(), rationale="Exactly four retained electronic components of the existing partial English Summa witness, complete own contextual matter and question/article text; only the source-backed prose category prerequisite. All existing IDs/titles/language/acquisition/member-set/credit remain unchanged.")))
    temporary = root / WORK / ".aquinas-summa-theologica-four-parts-metadata.tmp"
    if temporary.exists():
        raise FileExistsError(temporary)
    if _files(root / WORK) != receipt["before"]:
        raise PipelineError("work changed before metadata prerequisite")
    temporary.write_bytes(revised_bytes)
    temporary.replace(root / WORK / "work.json")
    try:
        result = install_accepted_work(root, promoted, work_id=WORK_ID, fail_at=fail_at)
    except Exception:
        if (not io_path(root / EDITION / "master.tei.xml").exists()
                and io_path(root / WORK / "work.json").read_bytes() == revised_bytes):
            temporary.write_bytes(original_bytes)
            temporary.replace(root / WORK / "work.json")
            if _files(root / WORK) != receipt["before"]:
                raise PipelineError("failed install did not restore exact original generation")
            (evidence / "metadata-rollback.json").write_bytes(canonical(dict(status="rolled-back", exact_original_generation=True)))
        raise
    if _files(root / WORK) != receipt["after"]:
        raise PipelineError("installed frozen generation differs")
    (evidence / "installation.json").write_bytes(canonical(result))
    (evidence / "installed-audit.json").write_bytes(canonical(dict(status="pass", files=receipt["after"],
        master_sha256=receipt["master_sha256"], exact_one_field_metadata=True,
        acquisition_preserved=True, title_language_ids_preserved=True)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promoted", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--runtime-supplement", type=Path)
    parser.add_argument("--supplement-sha256")
    args = parser.parse_args()
    log=ROOT/"reports/_logs/aquinas-four-current-reconciliation-20261002-v1"
    replay=json.loads((log/"exact-accepted-byte-replay.json").read_bytes())
    rollback=json.loads((log/"rollback-proof.json").read_bytes())
    notices=json.loads((log/"notice-preflight.json").read_bytes())
    staged=json.loads((args.promoted/"stage-receipt.json").read_bytes())
    if (replay["status"]!="pass" or not replay["exact_bytes"] or replay["accepted_master_sha256"]!=staged["master_sha256"]
        or rollback["status"]!="pass" or rollback["frozen_receipt_sha256"]!=args.receipt_sha256
        or rollback["observed"]["new_live_all_hashes"]!=staged["after"] or rollback["original_restoration"]!=staged["before"]
        or notices["status"]!="pass" or notices["notice_count"]<1 or notices["item"]["item_id"]!=WORK_ID):
        raise PipelineError("exact bound replay/rollback/visible notice prerequisite differs")
    print(json.dumps(install(ROOT, args.promoted, args.receipt_sha256, args.evidence,
                             runtime_supplement=args.runtime_supplement, supplement_sha=args.supplement_sha256)))


if __name__ == "__main__":
    main()
