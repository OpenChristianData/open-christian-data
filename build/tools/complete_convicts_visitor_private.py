"""Bounded current-schema private closeout for the unchanged N18328 master."""
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
from ocd_kernel.projection.categories.liturgies import project_accepted_liturgies, verify_accepted_liturgies
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files

ROOT = Path(__file__).resolve().parents[2]
WID = "convicts-visitor"
WORK = Path("library/works") / WID
EDITION = WORK / "forms/convicts-visitor-tcp-retained/editions/convicts-visitor-tcp-electronic"
HISTORY = WORK / "publication/offline-release-rehearsal-20260930"
POSTINSTALL = Path("plans/2026-09-22-source-preflight/convicts-visitor-n18328-postinstall-verification-20260930.json")
MANIFEST = Path("sources/convicts-visitor/n18328.source-manifest.accepted-v1.json")
LOG = ROOT / "reports/_logs/convicts-visitor-private-release-20261002-v1"
MASTER_HASH = "0d5bc4e091da8b10b26b815a420718ef082d51a3f41c25cde7d8d6b53b26eeef"
ACCEPTANCE_HASH = "3b2ada04e8adfaca0921e6fa4cfe93621e92a3cd63d406054ebf3019f369c76c"


def read(path: Path):
    return json.loads(io_path(path).read_bytes())


def sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def save(path: Path, value) -> None:
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with io_path(path).open("xb") as handle:
        handle.write(raw)


def check(bindings: dict[str, str]) -> None:
    for path, expected in bindings.items():
        if sha(ROOT / path) != expected:
            raise PipelineError(f"Bound input changed: {path}")


def prepare() -> None:
    if LOG.exists() or (ROOT / WORK / "publication/completion.json").exists():
        raise PipelineError("Fresh Convicts closeout paths required")
    before = _files(ROOT / WORK)
    installed = read(ROOT / POSTINSTALL)["operation"]["live_files"]
    if len(installed) != 24 or any(before.get(p) != d for p, d in installed.items()):
        raise PipelineError("The original 24-file installation differs")
    if sha(ROOT / EDITION / "master.tei.xml") != MASTER_HASH or sha(ROOT / EDITION / "acceptance.json") != ACCEPTANCE_HASH:
        raise PipelineError("Accepted master or acceptance differs")
    acceptance = validate_acceptance(ROOT / EDITION / "acceptance.json", root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    if acceptance["identity"] != dict(work_id=WID, textual_form_id="convicts-visitor-tcp-retained", edition_id="convicts-visitor-tcp-electronic", acquisition_id="convicts-visitor-tcp-acquired"):
        raise PipelineError("Exact retained identities differ")
    journal_path = Path(read(ROOT / POSTINSTALL)["operation"]["path"])
    journal = read(journal_path)
    if journal["phase"] != "complete" or journal["after"] != installed:
        raise PipelineError("Historical complete install journal differs")
    bindings = {(WORK / p).as_posix():d for p, d in before.items()}
    for p in (POSTINSTALL, MANIFEST, journal_path.relative_to(ROOT)):
        bindings[p.as_posix()] = sha(ROOT / p)
    for entry in read(ROOT / MANIFEST)["authorities"]:
        if sha(ROOT / entry["path"]) != entry["sha256"] or io_path(ROOT / entry["path"]).stat().st_size != entry["bytes"]:
            raise PipelineError(f"Historical source authority changed: {entry['path']}")
        bindings[entry["path"]] = entry["sha256"]
    old_files = read(ROOT / HISTORY / "files.sha256.json")
    if _files(ROOT / HISTORY / "release-evidence") != old_files or len(old_files) != 7:
        raise PipelineError("Historical seven-file release differs")
    index = read(ROOT / HISTORY / "rehearsal-index.json")
    old_receipt = read(ROOT / HISTORY / "release-evidence/internal/projection-receipts/convicts-visitor.json")
    if index["authority"]["master_sha256"] != MASTER_HASH or index["authority"]["acceptance_sha256"] != ACCEPTANCE_HASH:
        raise PipelineError("Historical rehearsal authority differs")
    for name in ("independent-verification.json", "reader-proof.json"):
        if read(ROOT / HISTORY / name)["status"] != "pass":
            raise PipelineError(f"Historical failed gate: {name}")
    selection = read(ROOT / HISTORY / "selection.json")
    selection["release_id"] = "convicts-visitor-private-offline-20261002-v1"
    notices = selection["items"][0]["public_notices"]
    visible = notice_texts_for_item(ROOT, selection["items"][0], ROOT / EDITION / "acceptance.json")
    for notice in notices:
        for p, key in ((notice["source_path"], "source_sha256"), (notice["notice_path"], "notice_sha256")):
            if sha(ROOT / p) != notice[key]:
                raise PipelineError("Existing paired notice differs")
            bindings[p] = notice[key]
    for folder in ("ocd_kernel/release", "ocd_kernel/projection", "ocd_kernel/library", "ocd_kernel/tei"):
        for path in (ROOT / folder).rglob("*.py"):
            bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (ROOT / "schemas/v2").rglob("*.json"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (Path(__file__), ROOT / "build/tools/report_release_stats.py", ROOT / "build/tools/check_release_reader.py"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    projection = project_accepted_liturgies(ROOT, acceptance_path=EDITION / "acceptance.json")
    errors = verify_accepted_liturgies(ROOT, acceptance_path=EDITION / "acceptance.json", rows=projection["rows"], receipt=projection["receipt"])
    if errors:
        raise PipelineError(f"Actual-master independent projection failed: {errors}")
    old_rows = [json.loads(line) for line in io_path(ROOT / HISTORY / "release-evidence/public/data/liturgies/train.jsonl").read_text(encoding="utf-8").splitlines()]
    # Current public metadata can add fields; source text/structure/order must remain exact.
    for old, new in zip(old_rows, projection["rows"], strict=True):
        for key in ("text", "structure", "front_matter", "record_id", "sequence"):
            if old.get(key) != new.get(key):
                raise PipelineError(f"Current projection changes historical source carrier {key}")
    check(bindings)
    save(LOG / "projection.json", projection)
    save(LOG / "actual-master-independent-check.json", dict(status="pass", errors=errors, master_sha256=MASTER_HASH))
    save(LOG / "selection.json", selection)
    reconciliation = dict(status="pass", checked_at=datetime.now(timezone.utc).isoformat(), original_installation=installed,
        preserved_work_files=before, historical_release_files=old_files, historical_gate_status="pass; dated schema bindings",
        old_schema_bindings={k:old_receipt[k] for k in ("policy_sha256", "common_schema_sha256", "native_schema_sha256")},
        current_schema_bindings={k:projection["receipt"][k] for k in ("policy_sha256", "common_schema_sha256", "native_schema_sha256")},
        historical_row_text_structure_order_unchanged=True, notice_texts=visible,
        source_candidate_master_preserved=True, reconstruction_performed=False, reinstall_performed=False,
        source_manifest_closure_qualification="Historical reconstruction closures remain dated; no replay or acceptance reseal is performed.",
        friction_log_disposition="Existing schema-bound historical-proof observations apply; no novel source-to-TEI repair identified.")
    save(LOG / "source-install-and-prior-release-reconciliation.json", reconciliation)
    for path in (LOG / "projection.json", LOG / "actual-master-independent-check.json", LOG / "selection.json", LOG / "source-install-and-prior-release-reconciliation.json"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    save(LOG / "input-bindings-before.json", bindings)
    save(LOG / "publication-preparation.json", dict(status="pass", rows=len(projection["rows"]), text_characters=sum(len(row["text"]) for row in projection["rows"]), public_notices=notices, preserved_work_files=before, original_installation=installed))
    print(json.dumps(dict(status="pass", rows=len(projection["rows"]), text_characters=sum(len(row["text"]) for row in projection["rows"]))), flush=True)


def release() -> None:
    bindings = read(LOG / "input-bindings-before.json")
    prep = read(LOG / "publication-preparation.json")
    selection = read(LOG / "selection.json")
    check(bindings)
    if _files(ROOT / WORK) != prep["preserved_work_files"]:
        raise PipelineError("Preserved work generation changed")
    destination = (LOG / "release").resolve()
    if destination.exists() or destination.drive.upper() != "D:" or str(destination).startswith("\\\\?\\"):
        raise PipelineError("Fresh ordinary physical D: path required")
    gates = {}
    for name, operation in (
        ("assembly", lambda: assemble_release_v2(ROOT, destination, selection=selection)),
        ("independent-verification", lambda: verify_release_v2(ROOT, destination, selection=selection)),
        ("statistics", lambda: release_statistics(ROOT, destination, selection)),
        ("readers", lambda: check_reader(ROOT, destination, selection)),
    ):
        print(name + ": START", flush=True)
        result = operation()
        save(LOG / (name + ".json"), result)
        if result["status"] != "pass":
            raise PipelineError(f"Convicts release {name} failed: {result}")
        gates[name] = dict(status="pass", path=(LOG / (name + ".json")).relative_to(ROOT).as_posix(), sha256=sha(LOG / (name + ".json")))
        print(name + ": PASS", flush=True)
    stats = read(LOG / "statistics.json")
    if stats["total"]["records"] != prep["rows"] or stats["total"]["text_characters"] != prep["text_characters"]:
        raise PipelineError("Final counts differ from actual-master projection")
    check(bindings)
    if _files(ROOT / WORK) != prep["preserved_work_files"]:
        raise PipelineError("Original work files changed")
    card = (destination / "public/README.md").read_text(encoding="utf-8")
    for notice in prep["public_notices"]:
        if io_path(ROOT / notice["notice_path"]).read_text(encoding="utf-8").rstrip() not in card:
            raise PipelineError("Visible source/data credits missing")
    files = _files(destination)
    if len(files) != 7:
        raise PipelineError("Exact seven-file release required")
    completion = dict(contract="ocd-convicts-visitor-private-offline-completion-v1", status="pass", checked_at=datetime.now(timezone.utc).isoformat(),
        work_id=WID, textual_form_id="convicts-visitor-tcp-retained", edition_id="convicts-visitor-tcp-electronic",
        rows=prep["rows"], text_characters=prep["text_characters"], uncompressed_bytes=stats["total"]["uncompressed_bytes"],
        master_sha256=MASTER_HASH, acceptance_sha256=ACCEPTANCE_HASH, input_bindings=bindings, preserved_work_files=prep["preserved_work_files"],
        original_installation=prep["original_installation"], release_file_bindings=files, public_notices=prep["public_notices"], gates=gates,
        selection_path=(LOG / "selection.json").relative_to(ROOT).as_posix(), selection_sha256=sha(LOG / "selection.json"), release_path=str(destination),
        private_offline=True, human_acceptance="not-recorded", page_image_collation="not-performed", rights_clearance="unresolved",
        public_schema_profile_adoption="unresolved", final_public_release_selection="unresolved", publication_performed=False,
        reconstruction_performed=False, reinstall_performed=False, accepted_generation_unchanged=True,
        warning="No explicit source response pointers; speaker labels and source order are preserved.")
    save(LOG / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", io_path(LOG / "completion.json").read_bytes())
    save(ROOT / WORK / "publication/selection.json", io_path(LOG / "selection.json").read_bytes())
    readme = ("# The Convict's Visitor — private offline completion\n\n"
        f"The unchanged accepted TCP N18328 master passes current-schema actual-master projection, private assembly, independent verification, statistics and both offline readers: {prep['rows']} complete offices, {prep['text_characters']:,} text characters. All 24 original installed files and the September 30 rehearsal remain unchanged. Existing paired TCP credits appear in the release README.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind the exact retained edition. Current detailed evidence and final audit are in `reports/_logs/convicts-visitor-private-release-20261002-v1/`. The older rehearsal used dated schemas and remains historical evidence.\n\n"
        "The offices preserve 115 ordered speeches and source labels without invented response links; title page, preface and shared opening occur once. Human acceptance, print-image collation, final rights disposition, public profile adoption and public publication remain separate and unresolved or unperformed. No reconstruction, reinstall, acquisition or publication occurred.\n").encode()
    save(ROOT / WORK / "publication/README.md", readme)
    expected = {**prep["preserved_work_files"], **{"publication/" + n:sha(ROOT / WORK / "publication" / n) for n in ("completion.json", "selection.json", "README.md")}}
    if _files(ROOT / WORK) != expected:
        raise PipelineError("Final work envelope differs")
    check(bindings)
    for path, digest in files.items():
        if sha(destination / path) != digest:
            raise PipelineError("Release changed at final audit")
    audit = dict(status="pass", checked_at=datetime.now(timezone.utc).isoformat(), completion_sha256=sha(LOG / "completion.json"),
        selection_sha256=sha(LOG / "selection.json"), input_binding_count=len(bindings), all_input_bindings_match=True,
        original_installation_unchanged=True, historical_rehearsal_unchanged=True, all_seven_release_files_match=True,
        canonical_completion_byte_identical=sha(ROOT / WORK / "publication/completion.json") == sha(LOG / "completion.json"),
        canonical_selection_byte_identical=sha(ROOT / WORK / "publication/selection.json") == sha(LOG / "selection.json"),
        canonical_files=expected, gates=gates, rows=prep["rows"], text_characters=prep["text_characters"], publication_performed=False)
    if not audit["canonical_completion_byte_identical"] or not audit["canonical_selection_byte_identical"]:
        raise PipelineError("Canonical completion/selection differs")
    save(LOG / "final-audit.json", audit)
    save(LOG / "README.md", ("# Convicts Visitor current private closeout\n\nCurrent [completion](completion.json) and [final audit](final-audit.json) preserve the full accepted installed generation and historical rehearsal. The four saved current gates pass; both readers retain all three records and their values/order. Paired credits are reused unchanged. Human acceptance, rights, print collation, public profile adoption and public publication remain unresolved or unperformed.\n").encode())
    print(json.dumps(dict(status="pass", completion_sha256=sha(LOG / "completion.json"), final_audit_sha256=sha(LOG / "final-audit.json"))), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "release"))
    phase = parser.parse_args().phase
    try:
        {"prepare":prepare, "release":release}[phase]()
    except (PipelineError, OSError, ValueError, ImportError) as exc:
        if not (LOG / (phase + "-failure.json")).exists():
            save(LOG / (phase + "-failure.json"), dict(status="fail", phase=phase, error=str(exc), publication_performed=False))
        raise


if __name__ == "__main__":
    main()
