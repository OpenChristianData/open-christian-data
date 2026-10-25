"""Apply only the pinned prose prerequisite, then use the shared guarded installer."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_schaff_history_vol3_current import ROOT, WORK_ID, WORK, EDITION, TITLE, SOURCE_SHA, canonical
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
        raise PipelineError("exact Schaff History volume III metadata preimage differs")
    expected["textual_forms"][0]["editions"][0]["category"] = "prose"
    if revised != expected:
        raise PipelineError("metadata exceeds exact one-field prose prerequisite")
    validate_identity_update(original, revised)


def install(root, promoted, receipt_sha, evidence, *, fail_at=None):
    root = root.resolve(strict=True)
    promoted = promoted.resolve(strict=True)
    stage_bytes = (promoted / "stage-receipt.json").read_bytes()
    if sha256(stage_bytes).hexdigest() != receipt_sha:
        raise PipelineError("frozen Schaff History volume III stage receipt differs")
    receipt = json.loads(stage_bytes)
    if {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in receipt["schema_pins"]} != receipt["schema_pins"]:
        raise PipelineError("frozen stage schema differs")
    if (receipt["work_id"] != WORK_ID or receipt["source_sha256"] != SOURCE_SHA
            or receipt["category"] != "prose" or receipt["language"] != "en"
            or receipt["status"] != "pass" or receipt["rows"] != 6
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
    (evidence / "metadata-prerequisite.json").write_bytes(canonical(dict(status="pinned",
        changed_fields=["textual_forms[0].editions[0].category"], before_sha256=sha256(original_bytes).hexdigest(),
        after_sha256=sha256(revised_bytes).hexdigest(), rationale="One complete retained prose volume with opening context, thirteen main divisions including ten chapters, both appendices and all seven integral indexes; one existing identity and unchanged source text/evidence.")))
    temporary = root / WORK / ".schaff-history-vol-3-metadata.tmp"
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
    args = parser.parse_args()
    print(json.dumps(install(ROOT, args.promoted, args.receipt_sha256, args.evidence)))


if __name__ == "__main__":
    main()
