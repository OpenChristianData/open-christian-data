"""Current-schema private successor for unchanged accepted TCP A61580."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.selection import validate_release_selection, validate_work_cohort
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files

ROOT = Path(__file__).resolve().parents[2]
WID = "stillingfleet-origines-sacrae"
FID = WID + "-tcp-retained-en"
EID = WID + "-tcp-electronic"
WORK = Path("library/works") / WID
EDITION = WORK / "forms" / FID / "editions" / EID
INTEGRATION = WORK / "integration/stillingfleet-a61580-electronic-acceptance-20261001"
MANIFEST = INTEGRATION / "inputs/source-manifest-acceptance-20261001-v2.json"
JOURNAL = Path(".tmp_audit/accepted-install-e22813c568d64dc8/operation.json")
OLD = Path("reports/_logs/stillingfleet-origines-sacrae-offline-release-20261001")
LOG = ROOT / "reports/_logs/stillingfleet-origines-sacrae-current-private-release-20261002-v1"
MASTER = "2a5de165c4afff39efc022cd42077091d1ae9336661950d7fe6fe53744dfc926"
ACCEPTANCE = "bfe78d58be3c5791a9504d43ab1b53e13290b6332d0ed2992aacfa4ad79dd7be"


def read(path):
    return json.loads(io_path(path).read_bytes())


def sha(path):
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def save(path, value):
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with io_path(path).open("xb") as handle:
        handle.write(raw)


def check(bindings):
    for path, expected in bindings.items():
        if sha(ROOT / path) != expected:
            raise PipelineError(f"Bound input changed: {path}")


def prepare():
    if LOG.exists() or (ROOT / WORK / "publication").exists():
        raise PipelineError("Fresh successor/completion homes required")
    before = _files(ROOT / WORK)
    j = read(ROOT / JOURNAL)
    if len(before) != 31 or j["phase"] != "complete" or j["after"] != before:
        raise PipelineError("The complete installed 31-file generation differs")
    if sha(ROOT / EDITION / "master.tei.xml") != MASTER or sha(ROOT / EDITION / "acceptance.json") != ACCEPTANCE:
        raise PipelineError("Accepted master or acceptance changed")
    accepted = validate_acceptance(ROOT / EDITION / "acceptance.json", root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    if accepted["identity"] != dict(work_id=WID, textual_form_id=FID, edition_id=EID, acquisition_id=WID + "-tcp-acquired"):
        raise PipelineError("Accepted identity differs")
    bindings = {(WORK / p).as_posix():d for p, d in before.items()}
    for a in read(ROOT / MANIFEST)["authorities"]:
        if sha(ROOT / a["path"]) != a["sha256"] or io_path(ROOT / a["path"]).stat().st_size != a["bytes"]:
            raise PipelineError(f"Retained source authority differs: {a['path']}")
        bindings[a["path"]] = a["sha256"]
    old_files = read(ROOT / OLD / "release-file-hashes.json")
    if _files(ROOT / OLD / "release") != old_files or len(old_files) != 7 or _files(ROOT / OLD / "rebuild") != old_files:
        raise PipelineError("Historical seven-file release/rebuild differs")
    summary = read(ROOT / OLD / "summary.json")
    if summary["status"] != "pass" or summary["master_sha256"] != MASTER or summary["acceptance_sha256"] != ACCEPTANCE:
        raise PipelineError("Historical release authority differs")
    for name in ("independent-verification.json", "statistics.json", "reader-proof.json", "determinism.json"):
        if read(ROOT / OLD / name)["status"] != "pass":
            raise PipelineError(f"Historical receipt failed: {name}")
    for item in summary["checks"]:
        if item["exit_code"] != 0 or sha(Path(item["output_path"])) != item["sha256"]:
            raise PipelineError("Historical statistics/reader terminal binding differs")
    old_receipt = read(ROOT / OLD / "release/internal/projection-receipts/stillingfleet-origines-sacrae.json")
    selection = read(ROOT / OLD / "selection.json")
    selection["release_id"] = "stillingfleet-a61580-current-private-offline-20261002-v1"
    selection = validate_release_selection(selection)
    validate_work_cohort(ROOT, selection)
    notices = selection["items"][0]["public_notices"]
    visible = notice_texts_for_item(ROOT, selection["items"][0], ROOT / EDITION / "acceptance.json")
    for n in notices:
        for path, key in ((n["source_path"], "source_sha256"), (n["notice_path"], "notice_sha256")):
            if sha(ROOT / path) != n[key]:
                raise PipelineError("Existing paired source/data notice differs")
            bindings[path] = n[key]
    for path in io_path(ROOT / OLD).rglob("*"):
        if path.is_file():
            bindings[(OLD / path.relative_to(io_path(ROOT / OLD))).as_posix()] = sha(path)
    bindings[JOURNAL.as_posix()] = sha(ROOT / JOURNAL)
    for folder in ("ocd_kernel/release", "ocd_kernel/projection", "ocd_kernel/library", "ocd_kernel/tei"):
        for path in (ROOT / folder).rglob("*.py"):
            bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (ROOT / "schemas/v2").rglob("*.json"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (Path(__file__), ROOT / "build/tools/report_release_stats.py", ROOT / "build/tools/check_release_reader.py"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    projection = project_accepted_prose(ROOT, acceptance_path=ROOT / EDITION / "acceptance.json")
    errors = verify_accepted_prose(ROOT, acceptance_path=ROOT / EDITION / "acceptance.json", rows=projection["rows"], receipt=projection["receipt"])
    if errors:
        raise PipelineError(f"Current actual-master independent check failed: {errors}")
    old_rows = [json.loads(line) for line in io_path(ROOT / OLD / "release/public/data/prose/train.jsonl").read_text(encoding="utf-8").splitlines()]
    for old, new in zip(old_rows, projection["rows"], strict=True):
        if old != new:
            raise PipelineError("Current rows differ from complete historical source carriers")
    if len(projection["rows"]) != 8 or sum(len(row["text"]) for row in projection["rows"]) != 1419834:
        raise PipelineError("Complete historical native row counts differ")
    check(bindings)
    if _files(ROOT / WORK) != before:
        raise PipelineError("Installed generation changed during projection")
    save(LOG / "projection.json", projection)
    save(LOG / "selection.json", selection)
    save(LOG / "source-install-and-prior-release-reconciliation.json", dict(status="pass", old_release=OLD.as_posix(),
        old_release_files=old_files, original_installed_files=before, exact_current_rows_equal_historical_rows=True,
        old_schema_bindings={k:old_receipt[k] for k in ("schema_sha256", "common_schema_sha256", "native_content_schema_sha256")},
        current_schema_bindings={k:projection["receipt"][k] for k in ("schema_sha256", "common_schema_sha256", "native_content_schema_sha256")},
        historical_gates="passing dated schema-bound evidence; not counted as current", current_projection_errors=errors,
        visible_notice_texts=visible, source_candidate_master_preserved=True, reconstruction_performed=False, reinstall_performed=False,
        friction_log_disposition="Existing schema-drift observations apply; no new source-to-TEI failure or repair."))
    for name in ("projection.json", "selection.json", "source-install-and-prior-release-reconciliation.json"):
        bindings[(LOG / name).relative_to(ROOT).as_posix()] = sha(LOG / name)
    save(LOG / "input-bindings-before.json", bindings)
    save(LOG / "publication-preparation.json", dict(status="pass", rows=8, text_characters=1419834, preserved_work_files=before, public_notices=notices))
    print(json.dumps(dict(status="pass", rows=8, text_characters=1419834, projection_sha256=sha(LOG / "projection.json"))), flush=True)


def release():
    bindings = read(LOG / "input-bindings-before.json")
    prep = read(LOG / "publication-preparation.json")
    selection = read(LOG / "selection.json")
    check(bindings)
    if _files(ROOT / WORK) != prep["preserved_work_files"]:
        raise PipelineError("Installed generation changed")
    destination = (LOG / "release").resolve()
    if destination.exists() or destination.drive.upper() != "D:" or str(destination).startswith("\\\\?\\"):
        raise PipelineError("Fresh ordinary physical D: release path required")
    gates = {}
    for name, operation in (("assembly", lambda:assemble_release_v2(ROOT, destination, selection=selection)),
        ("independent-verification", lambda:verify_release_v2(ROOT, destination, selection=selection)),
        ("statistics", lambda:release_statistics(ROOT, destination, selection)), ("readers", lambda:check_reader(ROOT, destination, selection))):
        print(name + ": START", flush=True)
        result = operation()
        save(LOG / (name + ".json"), result)
        if result["status"] != "pass":
            raise PipelineError(f"Stillingfleet {name} failed: {result}")
        gates[name] = dict(status="pass", path=(LOG / (name + ".json")).relative_to(ROOT).as_posix(), sha256=sha(LOG / (name + ".json")))
        print(name + ": PASS", flush=True)
    stats = read(LOG / "statistics.json")
    if stats["total"]["records"] != 8 or stats["total"]["text_characters"] != 1419834:
        raise PipelineError("Current counts differ")
    check(bindings)
    if _files(ROOT / WORK) != prep["preserved_work_files"]:
        raise PipelineError("Original work changed")
    files = _files(destination)
    if len(files) != 7:
        raise PipelineError("Expected seven release files")
    card = (destination / "public/README.md").read_text(encoding="utf-8")
    for notice in prep["public_notices"]:
        if io_path(ROOT / notice["notice_path"]).read_text(encoding="utf-8").rstrip() not in card:
            raise PipelineError("Visible source/data credit missing")
    completion = dict(contract="ocd-stillingfleet-current-private-completion-v1", status="pass", checked_at=datetime.now(timezone.utc).isoformat(),
        work_id=WID, textual_form_id=FID, edition_id=EID, master_sha256=MASTER, acceptance_sha256=ACCEPTANCE,
        rows=8, text_characters=1419834, uncompressed_bytes=stats["total"]["uncompressed_bytes"], input_bindings=bindings,
        preserved_work_files=prep["preserved_work_files"], release_file_bindings=files, public_notices=prep["public_notices"], gates=gates,
        selection_path=(LOG / "selection.json").relative_to(ROOT).as_posix(), selection_sha256=sha(LOG / "selection.json"), release_path=str(destination),
        private_offline=True, human_acceptance="not-recorded", print_collation="not-performed", rights_clearance="unresolved",
        final_public_release_selection="unresolved", publication_performed=False, reconstruction_performed=False, reinstall_performed=False,
        source_limits=["All 1795 source-encoded gaps preserved; absent words not inferred.", "Commercial page images absent; transcription accuracy against images unverified."],
        release_warning="Notes and page markers remain in structure; readable text omits them.", historical_release_preserved=True)
    save(LOG / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", io_path(LOG / "completion.json").read_bytes())
    save(ROOT / WORK / "publication/selection.json", io_path(LOG / "selection.json").read_bytes())
    save(ROOT / WORK / "publication/README.md", ("# Origines Sacrae private offline completion\n\n"
        "The unchanged accepted TCP A61580 electronic master passes current actual-master projection, private assembly, independent verification, statistics and both offline readers: eight records / 1,419,834 text characters. All31 original installed files and the older seven-file release/rebuild remain unchanged. Paired TCP source/data credits are reused unchanged and appear in the release README.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind this exact edition. Current detailed evidence is `reports/_logs/stillingfleet-origines-sacrae-current-private-release-20261002-v1/`, including the final audit. The October1 release remains dated schema-bound evidence.\n\n"
        "All1,795 encoded gaps remain; absent wording was not inferred. Notes and page markers remain in structure while readable text omits them. Commercial print images are absent; image collation, human acceptance, final rights disposition, public release selection and publication remain unresolved or unperformed. No acquisition, reconstruction, reinstall or publication occurred.\n").encode())
    expected = {**prep["preserved_work_files"], **{"publication/" + name:sha(ROOT / WORK / "publication" / name) for name in ("completion.json", "selection.json", "README.md")}}
    if _files(ROOT / WORK) != expected or _files(destination) != files:
        raise PipelineError("Final work/release envelope changed")
    check(bindings)
    audit = dict(status="pass", checked_at=datetime.now(timezone.utc).isoformat(), completion_sha256=sha(LOG / "completion.json"),
        selection_sha256=sha(LOG / "selection.json"), input_binding_count=len(bindings), all_input_bindings_match=True,
        all_31_installed_files_unchanged=True, historical_release_and_rebuild_unchanged=True, all_seven_release_files_match=True,
        canonical_files=expected, gates=gates, rows=8, text_characters=1419834, publication_performed=False,
        canonical_completion_byte_identical=sha(ROOT / WORK / "publication/completion.json") == sha(LOG / "completion.json"),
        canonical_selection_byte_identical=sha(ROOT / WORK / "publication/selection.json") == sha(LOG / "selection.json"))
    if not audit["canonical_completion_byte_identical"] or not audit["canonical_selection_byte_identical"]:
        raise PipelineError("Canonical pointer copies differ")
    save(LOG / "final-audit.json", audit)
    save(LOG / "README.md", b"# Stillingfleet current private closeout\n\n[Completion](completion.json) and [final audit](final-audit.json) bind the unchanged accepted installation, retained source, paired TCP credits, historical release/rebuild, current projection, four current passing gates/readers and seven release files. Rights, human acceptance, print-image collation and public publication remain separate.\n")
    print(json.dumps(dict(status="pass", completion_sha256=sha(LOG / "completion.json"), final_audit_sha256=sha(LOG / "final-audit.json"))), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "release"))
    phase = parser.parse_args().phase
    try:
        {"prepare":prepare, "release":release}[phase]()
    except (PipelineError, OSError, ValueError, KeyError, ImportError) as exc:
        save(LOG / (phase + "-failure.json"), dict(status="fail", phase=phase, error=str(exc), publication_performed=False))
        raise


if __name__ == "__main__":
    main()
