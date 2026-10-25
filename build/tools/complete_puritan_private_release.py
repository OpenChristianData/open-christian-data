"""Private closeout of the unchanged accepted Puritan Catechism electronic witness."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.catechisms import project_accepted_catechisms, verify_accepted_catechisms
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files

ROOT = Path(__file__).resolve().parents[2]
WID = "puritan-catechism"
FID = WID + "-retained-electronic"
EID = WID + "-creeds-json"
WORK = Path("library/works") / WID
EDITION = WORK / "forms" / FID / "editions" / EID
MANIFEST = Path("sources") / WID / (WID + ".source-manifest.json")
JOURNAL = Path(".tmp_audit/accepted-install-331c3277c179488b/operation.json")
STAGE = Path("reports/runs/creeds-json-lib062-remaining-stage-20260926-r3") / WID
LOG = ROOT / "reports/_logs/puritan-catechism-private-release-20261002-v2"
SOURCE_NOTE = Path("sources/catechisms") / WID / "README.source.md"
DATA_NOTE = Path("data/catechisms") / WID / "README.md"
MASTER_HASH = "32cb3c410436371e4145afe91ed46634afa205917b4e7fb0e16daf943b75e0a5"
ACCEPTANCE_HASH = "a8f45e6d977aaf924e51023e76d92d13762c688799edaf466bc2b1444d6c3284"


def read(path: Path):
    return json.loads(io_path(path).read_bytes())


def sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def save(path: Path, value) -> None:
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if io_path(path).exists():
        if io_path(path).read_bytes() == raw:
            return
        raise PipelineError(f"Existing evidence differs: {path}")
    with io_path(path).open("xb") as handle:
        handle.write(raw)


def check(bindings: dict[str, str]) -> None:
    for path, digest in bindings.items():
        if sha(ROOT / path) != digest:
            raise PipelineError(f"Bound input changed: {path}")


def prepare() -> None:
    if (LOG / "publication-preparation.json").exists() or (ROOT / WORK / "publication").exists():
        raise PipelineError("Fresh work-local closeout required")
    for path, digest in ((SOURCE_NOTE, "b7141d0054bb47fcfd1b523437084bb964b4a5f7d9a3c6be413ba912b06f3178"),
                         (DATA_NOTE, "ad645388838de7005359fb6076fcf322602a4708386842c4c823ca5e136ae321")):
        if io_path(ROOT / path).exists() and sha(ROOT / path) != digest:
            raise PipelineError(f"Pre-existing task notice differs: {path}")
    before = _files(ROOT / WORK)
    journal = read(ROOT / JOURNAL)
    if len(before) != 22 or journal["phase"] != "complete" or journal["work_id"] != WID or journal["after"] != before:
        raise PipelineError("Current installation does not match complete 22-file journal")
    if sha(ROOT / EDITION / "master.tei.xml") != MASTER_HASH or sha(ROOT / EDITION / "acceptance.json") != ACCEPTANCE_HASH:
        raise PipelineError("Accepted master or acceptance differs")
    acceptance = validate_acceptance(ROOT / EDITION / "acceptance.json", root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    if acceptance["identity"] != dict(work_id=WID, textual_form_id=FID, edition_id=EID, acquisition_id=WID + "-creeds-json-member"):
        raise PipelineError("Accepted identity differs")
    stage_receipt = STAGE / "final-stage-receipt.json"
    if sha(ROOT / stage_receipt) != read(ROOT / "build/tools/creeds_json_lib062_remaining_receipts.json")[WID]:
        raise PipelineError("Pinned historical stage receipt differs")
    stage = read(ROOT / stage_receipt)
    if stage["after"] != before or stage["master_sha256"] != MASTER_HASH:
        raise PipelineError("Historical staged generation differs from installed generation")
    bindings = {(WORK / path).as_posix():digest for path, digest in before.items()}
    evidence = (JOURNAL, MANIFEST, stage_receipt, Path("build/tools/creeds_json_four_catechisms_routes.json"),
        Path("build/tools/creeds_json_lib062_remaining_receipts.json"), Path("raw/Creeds.json/README.md"),
        Path("plans/2026-09-22-source-preflight/creeds-json-lib062-remaining-stage-handoff-20260926.md"),
        Path("plans/2026-09-22-source-preflight/started-works-offline-rehearsal-20260930/selection.json"),
        Path("reports/_logs/retained-release-selection-index-20261002-v2/index.json"))
    for path in evidence:
        bindings[path.as_posix()] = sha(ROOT / path)
    for authority in read(ROOT / MANIFEST)["authorities"]:
        path = ROOT / authority["path"]
        if sha(path) != authority["sha256"] or io_path(path).stat().st_size != authority["bytes"]:
            raise PipelineError(f"Retained source authority differs: {authority['path']}")
        bindings[authority["path"]] = authority["sha256"]
    if sha(ROOT / "raw/Creeds.json/README.md") != stage["provider_rights"]["provider_readme_sha256"]:
        raise PipelineError("Retained provider rights evidence differs")
    old_selection = read(ROOT / evidence[-2])
    if any(item.get("work_id", item["item_id"]) == WID for item in old_selection["items"]):
        raise PipelineError("Historical rehearsal unexpectedly includes this work")
    index = read(ROOT / evidence[-1])
    if index["by_work"].get(WID, []):
        raise PipelineError("Prior release selections require reconciliation")
    source = read(ROOT / acceptance["source"]["source_path"])
    master = io_path(ROOT / EDITION / "master.tei.xml").read_bytes()
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    tree = etree.fromstring(master, parser)
    ns = {"t":"http://www.tei-c.org/ns/1.0"}
    units = tree.xpath("./t:text/t:body/t:div[@type='catechism']/t:div[@type='question-unit']", namespaces=ns)
    if len(units) != 82 or len(source["Data"]) != 82:
        raise PipelineError("Complete source question inventory differs")
    for ordinal, (original, unit) in enumerate(zip(source["Data"], units, strict=True), 1):
        if original["Number"] != ordinal or unit.get("n") != str(original["Number"]):
            raise PipelineError(f"Source label differs at {ordinal}")
        expected = {"Number", "Question", "Answer"} | ({"AnswerWithProofs", "Proofs"} if "Proofs" in original else set())
        if set(original) != expected:
            raise PipelineError(f"Source fields differ at {ordinal}")
        for role, key in (("question", "Question"), ("answer", "Answer"), ("answer-with-proofs", "AnswerWithProofs")):
            actual = unit.xpath("./t:p[@ana='#" + role + "']", namespaces=ns)
            if len(actual) != (1 if key in original else 0) or (actual and (list(actual[0]) or (actual[0].text or "") != original[key])):
                raise PipelineError(f"Source field {key} differs at {ordinal}")
        actual_proofs = unit.xpath("./t:list[@type='proofs']/t:item", namespaces=ns)
        if len(actual_proofs) != len(original.get("Proofs", [])):
            raise PipelineError(f"Proof count differs at {ordinal}")
        for actual, original_proof in zip(actual_proofs, original.get("Proofs", []), strict=True):
            if (actual.get("n") != str(original_proof["Id"])
                    or actual.xpath("./t:label/text()", namespaces=ns) != [str(original_proof["Id"])]
                    or actual.xpath("./t:listBibl/t:bibl/t:ref/text()", namespaces=ns) != original_proof["References"]):
                raise PipelineError(f"Proof attachment/order differs at {ordinal}")
    projection = project_accepted_catechisms(ROOT, acceptance_path=ROOT / EDITION / "acceptance.json")
    errors = verify_accepted_catechisms(ROOT, acceptance_path=ROOT / EDITION / "acceptance.json", rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 82 or projection["receipt"]["retained_metadata"] != source["Metadata"]:
        raise PipelineError(f"Current independent projection failed: {errors}")
    for row, original in zip(projection["rows"], source["Data"], strict=True):
        proofs = [{"id": item["Id"], "references": [{"raw": value, "osis": [value]} for value in item["References"]]} for item in original.get("Proofs", [])]
        if (row["question"] != original["Question"] or row["answer"] != original["Answer"]
                or row["answer_with_proofs"] != original.get("AnswerWithProofs") or row["proofs"] != proofs
                or row["item_id"] != str(original["Number"]) or row["sort_key"] != original["Number"]):
            raise PipelineError("Projected source fields/relationships differ")
    if (sum(len(row["proofs"]) for row in projection["rows"]) != 197
            or sum(len(item["references"]) for row in projection["rows"] for item in row["proofs"]) != 247
            or sum("Proofs" not in row for row in source["Data"]) != 10):
        raise PipelineError("Complete proof/reference/absent-field accounting differs")
    for folder in ("ocd_kernel/release", "ocd_kernel/projection", "ocd_kernel/library", "ocd_kernel/tei"):
        for path in (ROOT / folder).rglob("*.py"):
            bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (ROOT / "schemas/v2").rglob("*.json"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (Path(__file__), ROOT / "build/tools/report_release_stats.py", ROOT / "build/tools/check_release_reader.py", ROOT / "build/tei/lib062_six_catechisms_oracle.py"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    check(bindings)
    if _files(ROOT / WORK) != before:
        raise PipelineError("Installed work changed during preflight")
    save(LOG / "projection.json", projection)
    save(LOG / "actual-master-independent-check.json", dict(status="pass", errors=errors, source_questions=82,
        source_field_order_unchanged=True, proof_count=197, reference_count=247, absent_proof_fields=10, complete_metadata_typed_values_preserved=True, master_sha256=MASTER_HASH))
    note = ("# Puritan Catechism — source credits\n\n"
        "This electronic witness comes from [NonlinearFruit/Creeds.json](https://github.com/NonlinearFruit/Creeds.json), member `creeds/puritan_catechism.json`. Its 82 numbered questions and answers remain in source order. All 197 ordered proofs and 247 references are preserved. Ten source rows omit proof fields; those absences remain explicit. Source metadata is retained with its original typed values in the accepted electronic witness; it lists Charles Spurgeon, 1855, London, England, and English. These are the provider's metadata claims.\n\n"
        "The retained provider README applies the [Unlicense](https://unlicense.org/) to material outside its eight listed copyright exceptions. This member is not a listed exception, and its metadata says Public Domain. Those statements describe retained source evidence; they do not establish worldwide rights clearance or the status of a historical print witness.\n\n"
        "This private offline preparation does not establish human acceptance, historical print collation, translation provenance, final rights clearance, or public publication authorization. No new source was downloaded.\n").encode()
    source_note = ("# Puritan Catechism electronic source attribution\n\n"
        f"The human-visible source credits for this exact retained electronic member belong at `{DATA_NOTE.as_posix()}` and are bound into its private release README.\n\n"
        "Retained authority: `raw/Creeds.json/creeds/puritan_catechism.json`; provider rights evidence: `raw/Creeds.json/README.md`. Existing LIB-062 source notice, package, source-accounting, accepted master and installation remain unchanged. Shared LIB-062 census is read-only support evidence, not another assigned work. Human review, historical lineage, rights clearance and public publication remain separate.\n").encode()
    save(ROOT / DATA_NOTE, note)
    save(ROOT / SOURCE_NOTE, source_note)
    notices = [dict(source_path=SOURCE_NOTE.as_posix(), source_sha256=sha(ROOT / SOURCE_NOTE), notice_path=DATA_NOTE.as_posix(), notice_sha256=sha(ROOT / DATA_NOTE))]
    selection = dict(schema_version="2.0", release_id=WID + "-private-offline-20261002-v2", items=[dict(item_id=WID,
        category="catechisms", acceptance_path=(EDITION / "acceptance.json").as_posix(), public_notices=notices)])
    visible = notice_texts_for_item(ROOT, selection["items"][0], ROOT / EDITION / "acceptance.json")
    save(LOG / "selection.json", selection)
    save(LOG / "source-install-and-prior-release-reconciliation.json", dict(status="pass", installed_files=before,
        journal_path=JOURNAL.as_posix(), stage_receipt_path=stage_receipt.as_posix(), source_authorities_match=True,
        selected_review_patterns=["RP-04", "RP-06", "RP-08", "RP-13", "RP-14"], source_rows=82,
        prior_selection_index_matches=[], historical_rehearsal_includes_work=False, historical_source_closures="dated evidence; no replay or blind reseal",
        full_source_qa_and_metadata_current_check=True, proof_attachment_and_order_verified=True, checker_independence="Current profile uses separate producer/checker traversals. Additional source-first Q&A/proof comparisons traverse actual TEI carriers independently; shared JSON decoding remains an explicit assumption.", shared_source_census="read-only retained support authority", visible_notice_texts=visible,
        reconstruction_performed=False, reinstall_performed=False, friction_log_disposition="No novel repair or failure identified."))
    for path in (ROOT / SOURCE_NOTE, ROOT / DATA_NOTE, LOG / "projection.json", LOG / "selection.json",
        LOG / "actual-master-independent-check.json", LOG / "source-install-and-prior-release-reconciliation.json"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    save(LOG / "input-bindings-before.json", bindings)
    prep = dict(status="pass", rows=82, text_characters=sum(len(row["text"]) for row in projection["rows"]),
        preserved_work_files=before, public_notices=notices, projection_sha256=sha(LOG / "projection.json"))
    save(LOG / "publication-preparation.json", prep)
    print(json.dumps(prep), flush=True)


def release() -> None:
    bindings = read(LOG / "input-bindings-before.json")
    prep = read(LOG / "publication-preparation.json")
    selection = read(LOG / "selection.json")
    check(bindings)
    if _files(ROOT / WORK) != prep["preserved_work_files"]:
        raise PipelineError("Installed generation changed")
    destination = (LOG / "release").resolve()
    if destination.exists() or destination.drive.upper() != "D:" or str(destination).startswith("\\\\?\\") or len(str(destination / "public/data/catechisms/train.jsonl")) >= 260:
        raise PipelineError("Fresh bounded ordinary physical D: release path required")
    gates = {}
    for name, operation in (("assembly", lambda:assemble_release_v2(ROOT, destination, selection=selection)),
        ("independent-verification", lambda:verify_release_v2(ROOT, destination, selection=selection)),
        ("statistics", lambda:release_statistics(ROOT, destination, selection)), ("readers", lambda:check_reader(ROOT, destination, selection))):
        print(name + ": START", flush=True)
        result = operation()
        save(LOG / (name + ".json"), result)
        if result["status"] != "pass":
            raise PipelineError(f"Puritan Catechism release gate failed: {name}: {result}")
        gates[name] = dict(status="pass", path=(LOG / (name + ".json")).relative_to(ROOT).as_posix(), sha256=sha(LOG / (name + ".json")))
        print(name + ": PASS", flush=True)
    stats = read(LOG / "statistics.json")
    if stats["total"]["records"] != 82 or stats["total"]["text_characters"] != prep["text_characters"]:
        raise PipelineError("Final counts differ from saved actual-master projection")
    files = _files(destination)
    if len(files) != 7:
        raise PipelineError("Expected seven release files")
    card = (destination / "public/README.md").read_text(encoding="utf-8")
    if io_path(ROOT / DATA_NOTE).read_text(encoding="utf-8").rstrip() not in card:
        raise PipelineError("Visible paired data notice missing")
    check(bindings)
    if _files(ROOT / WORK) != prep["preserved_work_files"]:
        raise PipelineError("Installed generation changed before completion")
    completion = dict(contract="ocd-puritan-private-offline-completion-v1", status="pass", checked_at=datetime.now(timezone.utc).isoformat(),
        work_id=WID, textual_form_id=FID, edition_id=EID, master_sha256=MASTER_HASH, acceptance_sha256=ACCEPTANCE_HASH,
        rows=82, text_characters=prep["text_characters"], uncompressed_bytes=stats["total"]["uncompressed_bytes"], input_bindings=bindings,
        preserved_work_files=prep["preserved_work_files"], release_file_bindings=files, gates=gates, public_notices=prep["public_notices"],
        selection_path=(LOG / "selection.json").relative_to(ROOT).as_posix(), selection_sha256=sha(LOG / "selection.json"), release_path=str(destination),
        private_offline=True, human_acceptance="not-recorded", print_collation="not-performed", rights_clearance="unresolved",
        historical_print_and_translation_lineage="unresolved", final_public_release_selection="unresolved", publication_performed=False,
        reconstruction_performed=False, reinstall_performed=False, accepted_generation_unchanged=True)
    save(LOG / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", io_path(LOG / "completion.json").read_bytes())
    save(ROOT / WORK / "publication/selection.json", io_path(LOG / "selection.json").read_bytes())
    save(ROOT / WORK / "publication/README.md", ("# Puritan Catechism private offline completion\n\n"
        f"The unchanged accepted retained Creeds.json electronic witness passes current actual-master projection, private assembly, independent verification, statistics and both readers: 82 Q&A records and {prep['text_characters']:,} text characters. The complete original 22-file installation remains unchanged. Paired visible source/data credits appear in the release README.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind this exact edition. Detailed current evidence is `reports/_logs/puritan-catechism-private-release-20261002-v2/`, including its final binding audit. The preserved v1 assembly failure was resolved by using the maintained single-edition selection shape. Historical reconstruction receipts remain dated evidence; no reconstruction or reinstall occurred.\n\n"
        "All source metadata values remain retained; no stronger historical print identity is inferred. Human acceptance, historical print collation and translation lineage, final rights clearance, public release selection and publication remain unresolved or unperformed. No acquisition or publication occurred.\n").encode())
    expected = {**prep["preserved_work_files"], **{"publication/" + name:sha(ROOT / WORK / "publication" / name) for name in ("completion.json", "selection.json", "README.md")}}
    if _files(ROOT / WORK) != expected:
        raise PipelineError("Final work envelope differs")
    check(bindings)
    if _files(destination) != files:
        raise PipelineError("Release changed during final audit")
    audit = dict(status="pass", checked_at=datetime.now(timezone.utc).isoformat(), completion_sha256=sha(LOG / "completion.json"),
        selection_sha256=sha(LOG / "selection.json"), input_binding_count=len(bindings), all_input_bindings_match=True,
        all_22_installed_files_unchanged=True, all_seven_release_files_match=True, canonical_files=expected, gates=gates,
        canonical_completion_byte_identical=sha(ROOT / WORK / "publication/completion.json") == sha(LOG / "completion.json"),
        canonical_selection_byte_identical=sha(ROOT / WORK / "publication/selection.json") == sha(LOG / "selection.json"),
        rows=82, text_characters=prep["text_characters"], publication_performed=False)
    if not audit["canonical_completion_byte_identical"] or not audit["canonical_selection_byte_identical"]:
        raise PipelineError("Canonical pointers differ")
    save(LOG / "final-audit.json", audit)
    save(LOG / "README.md", ("# Puritan Catechism private closeout evidence\n\n"
        "Current [completion](completion.json) and [final audit](final-audit.json) bind all 22 unchanged installed files, exact retained source and historical stage/install evidence, current projection, paired visible credits, four passing release gates and seven release files. Both offline readers preserve the complete 82 Q&A records. Human acceptance, print collation, historical lineage, rights clearance and public publication remain separate and unresolved or unperformed.\n").encode())
    print(json.dumps(dict(status="pass", completion_sha256=sha(LOG / "completion.json"), final_audit_sha256=sha(LOG / "final-audit.json"))), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "release"))
    phase = parser.parse_args().phase
    try:
        {"prepare":prepare, "release":release}[phase]()
    except (PipelineError, OSError, ValueError, ImportError, KeyError) as exc:
        if not (LOG / (phase + "-failure.json")).exists():
            save(LOG / (phase + "-failure.json"), dict(status="fail", phase=phase, error=str(exc), publication_performed=False))
        raise


if __name__ == "__main__":
    main()
