"""Private release closeout for the unchanged accepted PG11449 witness."""
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
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files

ROOT = Path(__file__).resolve().parents[2]
WID = "carey-enquiry"
WORK = Path("library/works") / WID
EDITION = WORK / "forms/carey-enquiry-retained-text/editions/carey-enquiry-pg11449-electronic-witness"
MANIFEST = Path("sources/structured-text/lib071-gutenberg-evangelical/work-bindings/carey-enquiry/37c-094-tables-v4.source-manifest.json")
JOURNAL = Path(".tmp_audit/accepted-install-8f24d4abc65148e1/operation.json")
HANDOFF = Path("plans/2026-09-22-source-preflight/carey-enquiry-grouped-text-native-hold-20260927.md")
SOURCE = Path("raw/gutenberg/pg11449.txt")
DATA_NOTICE = Path("data/prose/carey-enquiry/README.md")
LICENSE = Path("data/prose/carey-enquiry/PROJECT_GUTENBERG_LICENSE.txt")
SOURCE_NOTICE = Path("sources/publication-gutenberg/carey-enquiry/README.source.md")
LOG = ROOT / "reports/_logs/carey-enquiry-private-release-20261002-v2"
MASTER_HASH = "74ea4ce79d468922d968de2ee5fe11a541784b7646ad8185b79f3bcc12468c6f"
ACCEPTANCE_HASH = "82de0f67123ac73aad56adb8b3060a024792a0cb905dab4725044ab4466af133"
SOURCE_HASH = "6dc07e5606be5a0032d6583fa5b663a81ed0971a5d9d1f267cfc14959aa602c0"


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


def prepare() -> None:
    if LOG.exists() or io_path(ROOT / WORK / "publication").exists():
        raise PipelineError("Fresh Carey closeout paths required")
    if any(io_path(ROOT / p).exists() for p in (DATA_NOTICE, LICENSE, SOURCE_NOTICE)):
        raise PipelineError("Notice destination already exists; reconcile rather than overwrite")
    before = _files(ROOT / WORK)
    journal = read(ROOT / JOURNAL)
    if journal["phase"] != "complete" or journal["after"] != before or len(before) != 21:
        raise PipelineError("Exact historical 21-file installation differs")
    if sha(ROOT / EDITION / "master.tei.xml") != MASTER_HASH or sha(ROOT / EDITION / "acceptance.json") != ACCEPTANCE_HASH or sha(ROOT / SOURCE) != SOURCE_HASH:
        raise PipelineError("Accepted master, acceptance or source differs")
    acceptance = validate_acceptance(ROOT / EDITION / "acceptance.json", root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    if acceptance["identity"] != dict(work_id=WID, textual_form_id="carey-enquiry-retained-text", edition_id="carey-enquiry-pg11449-electronic-witness", acquisition_id="carey-enquiry-pg11449-acquired"):
        raise PipelineError("Exact source identities differ")
    if io_path(ROOT / EDITION / "master.tei.xml").read_bytes() != io_path(ROOT / WORK / "integration/carey-pg11449-grouped-tables-v1/candidate.tei.xml").read_bytes():
        raise PipelineError("Accepted master differs from installed candidate")
    bindings = {(WORK / p).as_posix():d for p, d in before.items()}
    for p in (MANIFEST, JOURNAL, HANDOFF):
        bindings[p.as_posix()] = sha(ROOT / p)
    for entry in read(ROOT / MANIFEST)["authorities"]:
        content = io_path(ROOT / entry["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != entry["sha256"] or len(content) != entry["bytes"]:
            raise PipelineError(f"Historical source authority changed: {entry['path']}")
        bindings[entry["path"]] = entry["sha256"]
    index_path = Path("reports/_logs/retained-release-selection-index-20261002-v2/index.json")
    observed_selections = read(ROOT / index_path).get("by_work", {}).get(WID, [])
    if observed_selections:
        raise PipelineError("Prior release selections found; reconcile before fresh assembly")
    projection = project_accepted_prose(ROOT, acceptance_path=ROOT / EDITION / "acceptance.json")
    errors = verify_accepted_prose(ROOT, acceptance_path=ROOT / EDITION / "acceptance.json", rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 1:
        raise PipelineError(f"Carey actual-master projection failed: {errors}")
    source = io_path(ROOT / SOURCE).read_bytes()
    start = source.index(b"START: FULL LICENSE")
    license_raw = source[start:]
    license_display = license_raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").strip()
    visible = (
        "# William Carey, An Enquiry — source credit\n\n"
        "This private offline snapshot represents the complete retained Project Gutenberg electronic "
        "text, eBook 11449, of William Carey's An Enquiry into the Obligations of Christians to Use Means "
        "for the Conversion of the Heathens. The retained electronic wrapper credits Michael Ciesielski, "
        "Robert Shimmin and PG Distributed Proofreaders. Credit: Project Gutenberg and those electronic "
        "text producers. [Project Gutenberg item](https://www.gutenberg.org/ebooks/11449).\n\n"
        "One structured prose record preserves the source order, retained wrapper, 2,073 source lines, "
        "blank-line carriers, source-located headings and four geographical tables. Table dimensions, "
        "row roles and cell positions remain represented. The selected electronic witness does not "
        "establish a particular print exemplar or an independent audit of provider corrections.\n\n"
        "The complete retained Project Gutenberg license follows below. The sibling "
        "PROJECT_GUTENBERG_LICENSE.txt preserves its original bytes; the selected record also retains "
        "the provider wrapper and license. These source terms and credits do not establish final "
        "jurisdictional rights clearance or public publication authorization. Human acceptance and "
        "print-image collation remain unrecorded or unperformed. No publication occurred.\n\n"
        "## Complete retained Project Gutenberg license\n\n" + license_display + "\n"
    )
    note = (
        "# Publication-facing source notice — Carey PG11449\n\n"
        f"The paired human-visible source credit and full retained license are `{DATA_NOTICE.as_posix()}`. "
        "The source, accepted master, historical source notice and install journal remain unchanged. "
        "This source-note successor supplies a data-folder deliverable without changing acceptance "
        "or expanding a rights grant. Credit is drawn directly from the retained eBook wrapper.\n\n"
        "Historical source-profile and master-header candidate/boundary wording remain dated evidence. "
        "Current acceptance and the exclusive retained-member manifest govern this one-work electronic "
        "scope. Stronger print identity, discourse hierarchy, table visual placement, provider correction "
        "audit, human acceptance and final rights/publication decisions remain unassessed.\n"
    )
    check(bindings)
    save(LOG / "projection.json", projection)
    save(LOG / "actual-master-independent-check.json", dict(status="pass", errors=errors, master_sha256=MASTER_HASH))
    save(ROOT / DATA_NOTICE, visible.encode())
    save(ROOT / SOURCE_NOTICE, note.encode())
    save(ROOT / LICENSE, license_raw)
    if io_path(ROOT / LICENSE).read_bytes() != source[start:]:
        raise PipelineError("Exact retained license artifact differs")
    notice = dict(source_path=SOURCE_NOTICE.as_posix(), source_sha256=sha(ROOT / SOURCE_NOTICE), notice_path=DATA_NOTICE.as_posix(), notice_sha256=sha(ROOT / DATA_NOTICE))
    selection = dict(schema_version="2.0", release_id="carey-enquiry-private-offline-20261002-v2", items=[dict(item_id=WID, category="prose", acceptance_path=(EDITION / "acceptance.json").as_posix(), public_notices=[notice])])
    if notice_texts_for_item(ROOT, selection["items"][0], ROOT / EDITION / "acceptance.json") != [visible]:
        raise PipelineError("Paired notice check failed")
    save(LOG / "selection.json", selection)
    save(LOG / "source-install-and-prior-release-reconciliation.json", dict(status="pass", checked_at=datetime.now(timezone.utc).isoformat(), preserved_installation=before,
        install_journal_path=JOURNAL.as_posix(), exact_installed_generation_matches_complete_journal=True, observed_release_selections=observed_selections,
        selection_discovery_scope="Retained host/sandbox selection index, work publication tree, and Carey-named report/export homes; no prior release found in these scopes. This is not a corpus-wide absence claim.",
        accepted_source_candidate_master_unchanged=True, historical_grouped_projection_hold="resolved by subsequent installed closed Carey profile",
        historical_header_profile_limits="Preserved as dated and unassessed stronger claims; no new acceptance or source decision is made.",
        retained_source_path=SOURCE.as_posix(), retained_source_sha256=SOURCE_HASH,
        license=dict(source_offset=start, bytes=len(license_raw), artifact_path=LICENSE.as_posix(), sha256=sha(ROOT / LICENSE), byte_identical_source_suffix=True, display_whitespace_only_normalization=True),
        reconstruction_performed=False, reinstall_performed=False, publication_performed=False))
    for folder in ("ocd_kernel/release", "ocd_kernel/projection", "ocd_kernel/library", "ocd_kernel/tei"):
        for path in (ROOT / folder).rglob("*.py"):
            bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (ROOT / "schemas/v2").rglob("*.json"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (Path(__file__), ROOT / "build/tools/report_release_stats.py", ROOT / "build/tools/check_release_reader.py", ROOT / DATA_NOTICE, ROOT / SOURCE_NOTICE, ROOT / LICENSE,
                 LOG / "projection.json", LOG / "actual-master-independent-check.json", LOG / "selection.json", LOG / "source-install-and-prior-release-reconciliation.json"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    save(LOG / "input-bindings-before.json", bindings)
    save(LOG / "publication-preparation.json", dict(status="pass", rows=len(projection["rows"]), text_characters=sum(len(row["text"]) for row in projection["rows"]), public_notices=[notice], preserved_installation=before))
    print(json.dumps(dict(status="pass", rows=len(projection["rows"]), text_characters=sum(len(row["text"]) for row in projection["rows"]), projection_sha256=sha(LOG / "projection.json"))), flush=True)


def release() -> None:
    bindings = read(LOG / "input-bindings-before.json")
    prep = read(LOG / "publication-preparation.json")
    selection = read(LOG / "selection.json")
    check(bindings)
    if _files(ROOT / WORK) != prep["preserved_installation"]:
        raise PipelineError("Preserved accepted installation changed")
    destination = (LOG / "release").resolve()
    if destination.exists() or destination.drive.upper() != "D:" or str(destination).startswith("\\\\?\\"):
        raise PipelineError("Fresh ordinary physical D: release path required")
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
            raise PipelineError(f"Carey private release {name} failed: {result}")
        gates[name] = dict(status="pass", path=(LOG / (name + ".json")).relative_to(ROOT).as_posix(), sha256=sha(LOG / (name + ".json")))
        print(name + ": PASS", flush=True)
    stats = read(LOG / "statistics.json")
    if stats["total"]["records"] != prep["rows"] or stats["total"]["text_characters"] != prep["text_characters"]:
        raise PipelineError("Final row/text counts differ")
    check(bindings)
    if _files(ROOT / WORK) != prep["preserved_installation"]:
        raise PipelineError("Original installed generation differs")
    notice = io_path(ROOT / DATA_NOTICE).read_text(encoding="utf-8")
    if notice.rstrip() not in (destination / "public/README.md").read_text(encoding="utf-8"):
        raise PipelineError("Complete credit/license notice missing from release")
    files = _files(destination)
    if len(files) != 7:
        raise PipelineError("Expected exactly seven release files")
    completion = dict(contract="ocd-carey-enquiry-private-offline-completion-v1", status="pass", checked_at=datetime.now(timezone.utc).isoformat(),
        work_id=WID, textual_form_id="carey-enquiry-retained-text", edition_id="carey-enquiry-pg11449-electronic-witness",
        rows=prep["rows"], text_characters=prep["text_characters"], uncompressed_bytes=stats["total"]["uncompressed_bytes"],
        master_sha256=MASTER_HASH, acceptance_sha256=ACCEPTANCE_HASH, preserved_installation=prep["preserved_installation"], input_bindings=bindings,
        release_file_bindings=files, public_notices=prep["public_notices"], gates=gates, selection_path=(LOG / "selection.json").relative_to(ROOT).as_posix(),
        selection_sha256=sha(LOG / "selection.json"), release_path=str(destination), private_offline=True,
        human_acceptance="not-recorded", print_image_collation="not-performed", table_visual_placement_review="not-performed-currently",
        provider_correction_audit="unassessed", rights_clearance="unresolved", final_public_release_selection="unresolved", publication_performed=False,
        reconstruction_performed=False, reinstall_performed=False, accepted_generation_unchanged=True)
    save(LOG / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", io_path(LOG / "completion.json").read_bytes())
    save(ROOT / WORK / "publication/selection.json", io_path(LOG / "selection.json").read_bytes())
    readme = ("# Carey, An Enquiry — private offline completion\n\n"
        f"The unchanged accepted PG11449 electronic master passes current actual-master projection, private assembly, independent verification, statistics and both readers: one complete structured prose record, {prep['text_characters']:,} text characters. All 21 installed files and the original source remain unchanged. Paired producer/Gutenberg credits and the complete retained license are visible in the release README.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind the exact edition; detailed evidence and final audit are in `reports/_logs/carey-enquiry-private-release-20261002-v2/`. The historical grouped-text hold was resolved by its existing installed profile. Dated header/source-profile candidate and boundary wording is preserved; current technical acceptance governs the exclusive retained electronic member.\n\n"
        "All four geographical tables retain dimensions, source row roles and cell positions. Stronger print/edition identity, visual table placement, provider correction audit, human acceptance, final rights and public publication remain unassessed or unresolved. No acquisition, reconstruction, reinstall or publication occurred.\n").encode()
    save(ROOT / WORK / "publication/README.md", readme)
    expected = {**prep["preserved_installation"], **{"publication/" + n:sha(ROOT / WORK / "publication" / n) for n in ("completion.json", "selection.json", "README.md")}}
    if _files(ROOT / WORK) != expected:
        raise PipelineError("Final work envelope differs")
    check(bindings)
    for path, digest in files.items():
        if sha(destination / path) != digest:
            raise PipelineError("Release changed at final audit")
    audit = dict(status="pass", checked_at=datetime.now(timezone.utc).isoformat(), completion_sha256=sha(LOG / "completion.json"),
        selection_sha256=sha(LOG / "selection.json"), input_binding_count=len(bindings), all_input_bindings_match=True,
        original_installation_unchanged=True, all_seven_release_files_match=True,
        canonical_completion_byte_identical=sha(ROOT / WORK / "publication/completion.json") == sha(LOG / "completion.json"),
        canonical_selection_byte_identical=sha(ROOT / WORK / "publication/selection.json") == sha(LOG / "selection.json"),
        canonical_files=expected, gates=gates, rows=prep["rows"], text_characters=prep["text_characters"], publication_performed=False)
    if not audit["canonical_completion_byte_identical"] or not audit["canonical_selection_byte_identical"]:
        raise PipelineError("Canonical completion or selection differs")
    save(LOG / "final-audit.json", audit)
    save(LOG / "README.md", ("# Carey Enquiry private closeout\n\nCurrent [completion](completion.json) and [final audit](final-audit.json) bind the unchanged accepted master and 21-file completed installation. Actual-master projection, current assembly/verifier/statistics and both readers pass. Paired visible Gutenberg/producer credits and the full retained license are delivered. Historical profile/header qualifications and stronger human/visual/print/rights/publication limits remain explicit.\n").encode())
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
