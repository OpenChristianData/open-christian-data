"""Finish one unchanged accepted TCP work as a private offline release."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from build.tei import baxter_christian_directory_oracle
from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files

ROOT = Path(__file__).resolve().parents[2]
WID = "baxter-christian-directory"
WORK = Path("library/works") / WID
EDITION = WORK / "forms/tcp-english/editions/a26892"
INTEGRATION = WORK / "integration/reviewed-tcp-v1"
MANIFEST = Path("sources/structured-text") / WID / (WID + ".source-manifest.json")
INDEX = Path("reports/_logs/retained-release-selection-index-20261002-v2/index.json")
LOG = ROOT / "reports/_logs/baxter-christian-directory-private-release-20261002-v1"
DATA_NOTICE = Path("data/prose") / WID / "README.md"
SOURCE_NOTICE = Path("sources/publication-tcp") / WID / "README.source.md"
PINS = {
    "work.json": "ba9eed8e62ed32fee488bf39dff807107e87aed6a08d69fa916953918cefad9d",
    "state.json": "848ad5feb729a8ba3c37c4344abadd5cf17f534e78b886cf3964804602ac2559",
    "forms/tcp-english/editions/a26892/master.tei.xml": "f25ac3bbfa10d2c7802641c49c3b1d72034712ce08a625f501bb825903b7b978",
    "forms/tcp-english/editions/a26892/acceptance.json": "872495240b74b5d04f2c75ed3dfde3d0748c0a7233507b10e020a3975f8e8c75",
}


def read(path: Path):
    return json.loads(io_path(path).read_bytes())


def sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def save(path: Path, value) -> None:
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    content = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with io_path(path).open("xb") as handle:
        handle.write(content)


def check(bindings: dict[str, str]) -> None:
    for path, expected in bindings.items():
        if sha(ROOT / path) != expected:
            raise PipelineError(f"Bound input changed: {path}")


def preflight() -> None:
    if LOG.exists() or io_path(ROOT / WORK / "publication").exists():
        raise PipelineError("Fresh Baxter report and publication pointer paths required")
    before = _files(ROOT / WORK)
    if len(before) != 24 or any(before.get(path) != expected for path, expected in PINS.items()):
        raise PipelineError("Installed Baxter generation differs from reviewed scan")
    acceptance = validate_acceptance(ROOT / EDITION / "acceptance.json", root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    if acceptance["identity"] != dict(work_id=WID, textual_form_id="tcp-english", edition_id="a26892", acquisition_id="a26892-tei"):
        raise PipelineError("Exact installed TCP identities differ")
    manifest = read(ROOT / MANIFEST)
    bindings = {(WORK / path).as_posix(): digest for path, digest in before.items()}
    bindings[MANIFEST.as_posix()] = sha(ROOT / MANIFEST)
    for entry in manifest["authorities"]:
        path = ROOT / entry["path"]
        if sha(path) != entry["sha256"] or io_path(path).stat().st_size != entry["bytes"]:
            raise PipelineError(f"Retained authority drift: {entry['path']}")
        bindings[entry["path"]] = entry["sha256"]
    for entry in (manifest["converter"], manifest["validator"]):
        if sha(ROOT / entry["implementation_path"]) != entry["implementation_sha256"]:
            raise PipelineError("Historical implementation bytes changed")
        bindings[entry["implementation_path"]] = entry["implementation_sha256"]
    source = io_path(ROOT / acceptance["source"]["source_path"]).read_bytes()
    original = io_path(ROOT / INTEGRATION / "original-package/content.tei.xml").read_bytes()
    candidate = io_path(ROOT / INTEGRATION / "candidate.tei.xml").read_bytes()
    master = io_path(ROOT / EDITION / "master.tei.xml").read_bytes()
    if source != original or candidate != master or source.split(b"</teiHeader>", 1)[1] != master.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Retained complete TEI or installed candidate conservation differs")
    reproduction = read(ROOT / INTEGRATION / "reproducibility.json")
    for path, digest in reproduction["historical_screenshots"].items():
        if sha(ROOT / path) != digest:
            raise PipelineError(f"Historical bounded visual evidence changed: {path}")
        bindings[path] = digest
    history = []
    indexed = read(ROOT / INDEX)["by_work"][WID]
    if len(indexed) != 8:
        raise PipelineError("Reviewed historical selection set changed")
    bindings[INDEX.as_posix()] = sha(ROOT / INDEX)
    for entry in indexed:
        selection_path = Path(entry["selection_path"])
        if sha(ROOT / selection_path) != entry["selection_sha256"]:
            raise PipelineError(f"Historical selection changed: {selection_path}")
        selected = read(ROOT / selection_path)
        report_path = selection_path.parent / "release-report.json"
        report = read(ROOT / report_path)
        matching = [item for item in report["items"] if item["acceptance_path"] == (EDITION / "acceptance.json").as_posix()]
        if len(matching) != 1 or matching[0]["row_count"] != 8 or matching[0]["status"] != "warned":
            raise PipelineError("Historical group no longer accounts for the exact eight-row Baxter item")
        receipt_path = selection_path.parent.parent / matching[0]["receipt_path"]
        if not io_path(ROOT / receipt_path).is_file():
            if report["status"] != "fail" or "historical-r2-readback" not in selection_path.parts:
                raise PipelineError(f"Passing historical group receipt is absent: {receipt_path}")
            for path in (selection_path, report_path):
                bindings[path.as_posix()] = sha(ROOT / path)
            history.append(dict(selection_path=selection_path.as_posix(), selection_sha256=entry["selection_sha256"],
                release_report_path=report_path.as_posix(), release_report_sha256=sha(ROOT / report_path),
                release_status="fail", item=matching[0], projection_receipt_path=receipt_path.as_posix(),
                declared_projection_receipt_exists=False, reuse_status="incomplete-non-reusable",
                qualification="Failed r2 readback retains selection/report metadata but lacks its declared Baxter projection receipt; no source, projection, verification, statistics or reader success is inferred.",
                original_selection_items=len(selected["items"])))
            continue
        receipt = read(ROOT / receipt_path)
        for authority in receipt["authority"].values():
            if sha(ROOT / authority["path"]) != authority["sha256"]:
                raise PipelineError("Historical projection's installed authority changed")
        schema_comparison = {}
        for key, path in (
            ("common_schema_sha256", "schemas/v2/public-row.schema.json"),
            ("schema_sha256", "schemas/v2/categories/prose.schema.json"),
            ("native_content_schema_sha256", "schemas/v2/native-content.schema.json"),
        ):
            current = sha(ROOT / path)
            schema_comparison[key] = dict(historical=receipt[key], current=current, matches=receipt[key] == current)
        for path in (selection_path, report_path, receipt_path):
            bindings[path.as_posix()] = sha(ROOT / path)
        history.append(dict(selection_path=selection_path.as_posix(), selection_sha256=entry["selection_sha256"],
            release_report_path=report_path.as_posix(), release_report_sha256=sha(ROOT / report_path),
            release_status=report["status"], item=matching[0], projection_receipt_path=receipt_path.as_posix(),
            projection_receipt_sha256=sha(ROOT / receipt_path), schema_comparison=schema_comparison,
            historical_receipt_independent_check=receipt["independent_check"],
            original_selection_items=len(selected["items"])))
    if sum(item["release_status"] == "pass" for item in history) != 7:
        raise PipelineError("Reviewed seven passing groups and failed r2 classification changed")
    current_closure = baxter_christian_directory_oracle._closure_digest()
    proof = dict(status="pass", checked_at=datetime.now(timezone.utc).isoformat(), work_id=WID,
        preserved_installation=before, bindings=bindings, historical_groups=history,
        complete_retained_source_equals_original_package=True, installed_candidate_equals_master=True,
        complete_text_suffix_byte_identical=True, historical_import_closure=manifest["validator"]["import_closure_sha256"],
        current_import_closure=current_closure,
        closure_qualification="Historical oracle closure is dated. No reconstruction, oracle rerun, acceptance reseal or source-manifest rewrite is performed.",
        install_evidence="Canonical 24-file accepted generation and all acceptance-bound technical receipts match. This is preserved legacy installation evidence, not a newly rehearsed guarded install.",
        reuse_decision="Reuse unchanged source/body and acceptance proof. Historical groups are dated because native/prose schema bindings changed; no group readers or current attribution proof is inferred. Fresh actual-master projection and one-work offline gates are required.",
        ownership="Sole Baxter Christian Directory owner assigned by coordinator; current docs and live team scan found no competing owner.",
        human_acceptance="not-recorded", rights_clearance="unresolved", publication_performed=False)
    check(bindings)
    if _files(ROOT / WORK) != before:
        raise PipelineError("Installed work changed during preflight")
    save(LOG / "source-install-and-prior-release-reconciliation.json", proof)
    save(LOG / "initial-preflight-failure.json", dict(status="failed-attempt-preserved", phase="preflight", terminal_exit_code=1,
        error="FileNotFoundError: failed historical r2 readback's declared Baxter projection receipt is absent.",
        missing_path="reports/_logs/asv-existing-release-reconciliation-20261002-v1/historical-r2-readback/internal/projection-receipts/baxter-christian-directory--a26892.json",
        canonical_mutations_before_failure=[], projection_or_release_gate_run=False,
        bounded_resolution="Coordinator authorized classifying the failed incomplete r2 group as non-reusable while requiring exact receipt bindings for all seven passing native groups."))
    print(json.dumps(dict(status="pass", installed_files=len(before), historical_groups=len(history), source_reconstruction_performed=False)), flush=True)


def prepare() -> None:
    proof = read(LOG / "source-install-and-prior-release-reconciliation.json")
    check(proof["bindings"])
    if _files(ROOT / WORK) != proof["preserved_installation"]:
        raise PipelineError("Original installed generation changed")
    if any(io_path(path).exists() for path in (ROOT / DATA_NOTICE, ROOT / SOURCE_NOTICE, LOG / "projection.json")):
        raise PipelineError("Fresh projection and paired notice destinations required")
    projection = project_accepted_prose(ROOT, acceptance_path=ROOT / EDITION / "acceptance.json")
    errors = verify_accepted_prose(ROOT, acceptance_path=ROOT / EDITION / "acceptance.json", rows=projection["rows"], receipt=projection["receipt"])
    save(LOG / "projection.json", projection)
    if errors or len(projection["rows"]) != 8:
        save(LOG / "projection-failure.json", dict(status="fail", errors=errors, rows=len(projection["rows"])))
        raise PipelineError(f"Baxter current actual-master projection failed: {errors}")
    visible = (
        "# Richard Baxter, A Christian Directory — source credit\n\n"
        "This private offline snapshot represents the complete retained Text Creation Partnership "
        "electronic edition, EEBO-TCP A26892, of Richard Baxter's A Christian Directory, London, 1673. "
        "Credit: Text Creation Partnership and the original source. "
        "[Michigan item record](https://name.umdl.umich.edu/A26892.0001.001); "
        "[official TCP edition](https://github.com/textcreationpartnership/A26892).\n\n"
        "TCP makes its keyboarded and encoded Phase I edition available under the "
        "[CC0 1.0 Universal Public Domain Dedication](https://creativecommons.org/publicdomain/zero/1.0/). "
        "The Michigan item record's waiver does not extend to page images or supplementary files. "
        "No page images or supplementary binaries are included here. TCP respectfully requests credit "
        "and attribution to the original source; this notice supplies those credits. The retained full "
        "CC0 license and acquisition evidence remain preserved. This source-layer statement is not an "
        "independent rights clearance for every component or intended use.\n\n"
        "The accepted master preserves the complete retained TEI header, front matter, body and back "
        "matter, including its explicit transcription gaps and source glyph markers. The source reports "
        "transcription from 629 page images and a film lacking the portrait; no missing text or portrait "
        "is reconstructed. Eight structured prose records preserve the electronic witness's source "
        "organization. Notes and page markers remain in structure and are omitted from flattened "
        "readable text under the stated projection policy.\n\n"
        "Agent technical acceptance and private offline verification remain separate from human "
        "textual or visual acceptance, page-image collation, final rights clearance and public "
        "publication authorization. Human acceptance and final rights clearance are unrecorded or "
        "unresolved. This snapshot has not been published.\n"
    )
    source_note = (
        "# Publication-facing TCP source notice — A Christian Directory\n\n"
        f"The paired human-visible credit is `{DATA_NOTICE.as_posix()}`.\n\n"
        "The bound historical source README, installed source notice, accepted master, acceptance "
        "and complete retained CC0 license remain unchanged. This paired notice delivers the retained "
        "TCP attribution request to the exact selected data folder; it does not enlarge a rights grant "
        "or authorize publication.\n\n" + visible
    )
    save(ROOT / DATA_NOTICE, visible.encode())
    save(ROOT / SOURCE_NOTICE, source_note.encode())
    notice = dict(source_path=SOURCE_NOTICE.as_posix(), source_sha256=sha(ROOT / SOURCE_NOTICE),
        notice_path=DATA_NOTICE.as_posix(), notice_sha256=sha(ROOT / DATA_NOTICE))
    selection = dict(schema_version="2.0", release_id=WID + "-private-offline-20261002-v1", items=[dict(
        item_id=WID, category="prose", acceptance_path=(EDITION / "acceptance.json").as_posix(), public_notices=[notice])])
    if notice_texts_for_item(ROOT, selection["items"][0], ROOT / EDITION / "acceptance.json") != [visible]:
        raise PipelineError("Exact paired notice check failed")
    bindings = {**proof["bindings"], SOURCE_NOTICE.as_posix():notice["source_sha256"], DATA_NOTICE.as_posix():notice["notice_sha256"]}
    for folder in ("ocd_kernel/release", "ocd_kernel/projection", "ocd_kernel/library", "ocd_kernel/tei"):
        for path in (ROOT / folder).rglob("*.py"):
            bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (ROOT / "schemas/v2").rglob("*.json"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (Path(__file__), ROOT / "build/tools/report_release_stats.py", ROOT / "build/tools/check_release_reader.py",
                 LOG / "projection.json", LOG / "source-install-and-prior-release-reconciliation.json"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    save(LOG / "selection.json", selection)
    save(LOG / "input-bindings-before.json", bindings)
    save(LOG / "publication-preparation.json", dict(status="pass", rows=len(projection["rows"]),
        text_characters=sum(len(row["text"]) for row in projection["rows"]), notice=notice,
        independent_actual_master_errors=errors, preserved_installation=proof["preserved_installation"],
        newly_created_notice_preimages={DATA_NOTICE.as_posix():None, SOURCE_NOTICE.as_posix():None}, publication_performed=False))
    print(json.dumps(dict(status="pass", rows=len(projection["rows"]), text_characters=sum(len(row["text"]) for row in projection["rows"]))), flush=True)


def release() -> None:
    bindings = read(LOG / "input-bindings-before.json")
    preparation = read(LOG / "publication-preparation.json")
    selection = read(LOG / "selection.json")
    check(bindings)
    if _files(ROOT / WORK) != preparation["preserved_installation"] or (ROOT / WORK / "publication").exists():
        raise PipelineError("Accepted generation or publication pointers changed")
    destination = (LOG / "release").resolve()
    if destination.exists() or destination.drive.upper() != "D:" or str(destination).startswith("\\\\?\\"):
        raise PipelineError("Fresh ordinary physical D: release path required")
    operations = (
        ("assembly", lambda: assemble_release_v2(ROOT, destination, selection=selection)),
        ("independent-verification", lambda: verify_release_v2(ROOT, destination, selection=selection)),
        ("statistics", lambda: release_statistics(ROOT, destination, selection)),
        ("readers", lambda: check_reader(ROOT, destination, selection)),
    )
    gates = {}
    for name, operation in operations:
        result = operation()
        save(LOG / (name + ".json"), result)
        if result["status"] != "pass":
            raise PipelineError(f"Baxter private release {name} failed: {result}")
        gates[name] = dict(status="pass", receipt_sha256=sha(LOG / (name + ".json")))
        print(name + ": PASS", flush=True)
    stats = read(LOG / "statistics.json")
    if stats["total"]["records"] != preparation["rows"] or stats["total"]["text_characters"] != preparation["text_characters"]:
        raise PipelineError("Final row/text counts differ from actual-master projection")
    check(bindings)
    if _files(ROOT / WORK) != preparation["preserved_installation"]:
        raise PipelineError("Preserved installed generation drifted")
    notice = io_path(ROOT / DATA_NOTICE).read_text(encoding="utf-8")
    if notice.rstrip() not in (destination / "public/README.md").read_text(encoding="utf-8"):
        raise PipelineError("Visible data notice missing from release")
    files = {path.relative_to(destination).as_posix():sha(path) for path in destination.rglob("*") if path.is_file()}
    if len(files) != 7:
        raise PipelineError("One-work release file envelope differs")
    completion = dict(contract="ocd-baxter-christian-directory-private-offline-completion-v1", status="pass",
        checked_at=datetime.now(timezone.utc).isoformat(), work_id=WID, edition_id="a26892",
        rows=preparation["rows"], text_characters=preparation["text_characters"], uncompressed_bytes=stats["total"]["uncompressed_bytes"],
        master_sha256=sha(ROOT / EDITION / "master.tei.xml"), acceptance_sha256=sha(ROOT / EDITION / "acceptance.json"),
        preserved_installation=preparation["preserved_installation"], input_bindings=bindings, release_file_bindings=files,
        notice=preparation["notice"], gates=gates, selection_sha256=sha(LOG / "selection.json"),
        prior_release_reconciliation_sha256=sha(LOG / "source-install-and-prior-release-reconciliation.json"),
        release_path=str(destination), private_offline=True, human_acceptance="not-recorded",
        page_image_collation="not-performed", rights_clearance="unresolved", publication_performed=False,
        reconstruction_performed=False, accepted_generation_unchanged=True)
    save(LOG / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", io_path(LOG / "completion.json").read_bytes())
    save(ROOT / WORK / "publication/selection.json", io_path(LOG / "selection.json").read_bytes())
    readme = (
        "# Baxter, A Christian Directory — private offline completion\n\n"
        f"The unchanged accepted TCP A26892 master passes current actual-master projection, independent "
        f"verification, private assembly, statistics and normal/streaming readers: {preparation['rows']} "
        f"structured prose records, {preparation['text_characters']:,} text characters. All 24 original "
        "installed files and retained source authorities remain unchanged.\n\n"
        "[Completion](completion.json) binds the exact selected edition, paired visible TCP credits, "
        "current inputs, four gate receipts and all seven release files. The original external "
        "selection is also retained as [selection.json](selection.json). Detailed evidence and the "
        "dated seven successful historical group releases plus failed r2 are reconciled in "
        "`reports/_logs/baxter-christian-directory-private-release-20261002-v1/`. Historical source "
        "oracle closure and older release schema bindings remain dated; no reconstruction or acceptance "
        "reseal was performed.\n\n"
        "Source transcription gaps, the absent portrait, and bounded prior visual coverage remain "
        "qualified. Human acceptance, page-image collation, final rights clearance and public "
        "publication remain separate and unresolved or unperformed.\n"
    ).encode()
    save(ROOT / WORK / "publication/README.md", readme)
    expected = {**preparation["preserved_installation"], **{
        "publication/" + name:sha(ROOT / WORK / "publication" / name) for name in ("completion.json", "selection.json", "README.md")}}
    if _files(ROOT / WORK) != expected or sha(ROOT / WORK / "publication/completion.json") != sha(LOG / "completion.json"):
        raise PipelineError("Canonical completion or final work generation differs")
    check(bindings)
    for name, digest in files.items():
        if sha(destination / name) != digest:
            raise PipelineError("Release file changed at closeout")
    audit = dict(status="pass", checked_at=datetime.now(timezone.utc).isoformat(), completion_sha256=sha(LOG / "completion.json"),
        selection_sha256=sha(LOG / "selection.json"), canonical_files=expected, all_input_bindings_match=True,
        preserved_installation_unchanged=True, all_release_files_match=True, canonical_completion_selection_byte_identical=True,
        rows=preparation["rows"], text_characters=preparation["text_characters"], publication_performed=False)
    save(LOG / "final-audit.json", audit)
    print(json.dumps(dict(status="pass", rows=preparation["rows"], text_characters=preparation["text_characters"],
        completion_sha256=sha(LOG / "completion.json"), final_audit_sha256=sha(LOG / "final-audit.json"))), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("preflight", "prepare", "release"))
    phase = parser.parse_args().phase
    try:
        {"preflight":preflight, "prepare":prepare, "release":release}[phase]()
    except (PipelineError, OSError, ValueError, ImportError) as exc:
        if LOG.exists() and not (LOG / (phase + "-failure.json")).exists():
            save(LOG / (phase + "-failure.json"), dict(status="fail", phase=phase, error=str(exc), publication_performed=False))
        raise


if __name__ == "__main__":
    main()
