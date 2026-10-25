"""Complete the installed Virgin Mary epistle as a private offline release."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256
import json

from lxml import html, etree

from build.tools.complete_puritan_private_release import read, save, sha, check
from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.install_accepted import _files
import ocd_kernel.projection.categories.prose as prose

ROOT = Path(__file__).resolve().parents[2]
WID = "pg77576-ignatius-virgin-mary"
WORK = ROOT / "library/works" / WID
EDITION = WORK / "forms/pg77576-ignatius-virgin-mary-english/editions/pg77576-ignatius-virgin-mary-pg77576-edition"
OLD = WORK / "integration/pg77576-html-v1/publication-v3/release-rehearsal"
LOG = ROOT / "reports/_logs/pg77576-ignatius-virgin-mary-private-release-20261003-v2"
JOURNAL = ROOT / ".tmp_audit/accepted-install-915f2d01de934227/operation.json"
SOURCE = ROOT / "raw/gutenberg/77576/html/pg77576-images.html"
NOTICE = ROOT / "data/structured-text/pg77576-ignatius-virgin-mary/README.md"
MASTER_SHA = "ad7b9d02f056797d62f1bc2b7b79867b769b106168108ad7285a654491117665"
ACCEPTANCE_SHA = "978cd563f2048cd03ef657df1dad8004cdc8391707e822c4c2125947b99ab220"
SOURCE_SHA = "ca58049f2ee7c62c8c34dffb6badfdb910ab698748f8decc9d9b978e7972e507"


def _main() -> None:
    if (WORK / "publication").exists():
        raise PipelineError("Fresh work-specific release required")
    installed = _files(WORK)
    journal = read(JOURNAL)
    # The handoff was updated after installation to record publication rehearsals.
    if journal["phase"] != "complete" or journal["work_id"] != WID or any(
        installed.get(path) != digest for path, digest in journal["after"].items()
        if path != "HANDOFF_20260930.md"
    ):
        raise PipelineError("Installed generation differs from complete journal")
    acceptance = EDITION / "acceptance.json"
    master = EDITION / "master.tei.xml"
    if sha(acceptance) != ACCEPTANCE_SHA or sha(master) != MASTER_SHA or sha(SOURCE) != SOURCE_SHA:
        raise PipelineError("Accepted or retained source authority changed")
    old = read(OLD / "selection.json")
    if old["items"][0]["item_id"] != WID or len(old["items"]) != 1:
        raise PipelineError("Retained rehearsal selection differs")
    prior = read(ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json")
    if prior["by_work"].get(WID, []):
        raise PipelineError("Prior release selection requires reconciliation")
    # Preserve the source's full license as human-visible text, rather than relying on the ZIP.
    doc = html.fromstring(SOURCE.read_bytes())
    heading = doc.xpath('//h2[@id="pg-footer-heading"]')
    if len(heading) != 1:
        raise PipelineError("Retained full-license heading differs")
    sections = [heading[0], *heading[0].itersiblings()]
    license_text = "\n\n".join(etree.tostring(node, method="text", encoding="unicode").strip() for node in sections)
    if not all(marker in license_text for marker in (
        "THE FULL PROJECT GUTENBERG", "1.E.1.", "1.E.6.",
        "Section 5. General Information About Project Gutenberg electronic works",
    )):
        raise PipelineError("Retained full license appears incomplete")
    addition = ("\n## Full retained Project Gutenberg License\n\n"
                "The following is the full license text carried in the retained eBook 77576 HTML.\n\n"
                "```text\n" + license_text + "\n```\n").encode("utf-8")
    addition_lf = addition.replace(b"\r\n", b"\n")
    current_notice = NOTICE.read_bytes()
    if current_notice.endswith(addition):
        base_notice = current_notice[:-len(addition)]
    elif current_notice.endswith(addition_lf):
        base_notice = current_notice[:-len(addition_lf)]
    else:
        base_notice = current_notice
    if sha256(base_notice).hexdigest() != old["items"][0]["public_notices"][0]["notice_sha256"]:
        raise PipelineError("Existing visible notice differs from retained source or prior attempt")
    NOTICE.write_bytes(base_notice.replace(b"\r\n", b"\n").rstrip() + b"\n" + addition_lf)
    notice = dict(old["items"][0]["public_notices"][0])
    notice["notice_sha256"] = sha(NOTICE)
    selection = dict(old)
    selection["release_id"] = "pg77576-ignatius-virgin-mary-private-offline-20261003-v2"
    selection["items"] = [{**old["items"][0], "public_notices": [notice]}]

    # The current prose entrypoint passes extended root spelling to a shared
    # containment check while resolved accepted paths use ordinary spelling.
    # Normalize only these two known equivalent paths, leaving all deep I/O
    # and the original containment check untouched.
    original_io_path = prose.io_path
    canonical = {str(ROOT), str(acceptance)}
    def ordinary_authority_paths(path: Path) -> Path:
        spelling = str(path)
        ordinary = spelling.removeprefix("\\\\?\\")
        return Path(ordinary) if ordinary in canonical else original_io_path(path)
    prose.io_path = ordinary_authority_paths
    outside = ROOT.parent / "EzraOCR" / "AGENTS.md"
    if ordinary_authority_paths(outside) != original_io_path(outside):
        raise PipelineError("Work-local path adapter changed an outside path")
    try:
        outside.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise PipelineError("Outside-path containment challenge failed")
    projection = project_accepted_prose(ROOT, acceptance_path=acceptance)
    errors = verify_accepted_prose(ROOT, acceptance_path=acceptance,
                                   rows=projection["rows"], receipt=projection["receipt"])
    rows = projection["rows"]
    chars = sum(len(row["text"]) for row in rows)
    if errors or len(rows) != 2 or projection["receipt"]["master_sha256"] != MASTER_SHA:
        raise PipelineError("Actual installed-master projection differs: " + str(errors))
    if sha(OLD / "public/data/prose/train.jsonl") != sha(
        WORK / "integration/pg77576-html-v1/publication-v3/rows.jsonl"
    ):
        raise PipelineError("Retained rehearsal/publication row disagreement")
    bindings = {(Path("library/works") / WID / path).as_posix(): digest
                for path, digest in installed.items()}
    inputs = [
        JOURNAL, SOURCE, ROOT / "raw/gutenberg/77576/pg77576-h.zip",
        ROOT / "raw/gutenberg/77576/acquisition-receipt.json", NOTICE,
        ROOT / notice["source_path"], OLD / "selection.json", OLD / "rehearsal-index.json",
        ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json",
        ROOT / "build/tools/report_release_stats.py", ROOT / "build/tools/check_release_reader.py",
        Path(__file__), ROOT / "build/tools/complete_puritan_private_release.py",
        ROOT / "ocd_kernel/projection/categories/prose.py", ROOT / "ocd_kernel/projection/envelope.py",
        ROOT / "ocd_kernel/projection/categories/sermons.py",
        ROOT / "ocd_kernel/projection/categories/native_documents.py",
        ROOT / "ocd_kernel/projection/scripture_authority.py",
        ROOT / "ocd_kernel/projection/scripture_targets.py",
    ]
    for folder in ("ocd_kernel/release", "ocd_kernel/library", "ocd_kernel/tei"):
        inputs.extend((ROOT / folder).rglob("*.py"))
    inputs.extend((ROOT / "schemas/v2").rglob("*.json"))
    bindings.update({path.relative_to(ROOT).as_posix(): sha(path) for path in inputs})
    check(bindings)
    save(LOG / "selection.json", selection)
    save(LOG / "input-bindings-before.json", bindings)
    save(LOG / "actual-master-projection.json", projection)
    save(LOG / "prior-attempts.json", dict(status="preserved-failures", attempts=[
        dict(stage="install-journal comparison", error="post-install handoff changed; all other 32 journal files match"),
        dict(stage="current projection", error="extended root spelling differed from ordinary accepted acquisition spelling"),
        dict(stage="sandbox report creation", error="WinError 5 on durable reports junction; host context required"),
        dict(stage="v1 assembly", error="public notice required LF-only UTF-8 Markdown; source-bound full license was retained"),
    ]))
    save(LOG / "installation-and-prior-release-reconciliation.json", dict(
        status="pass", installed_files=len(installed), install_journal=str(JOURNAL.relative_to(ROOT)),
        journal_files=len(journal["after"]), post_install_handoff_updated=True,
        prior_index_selections=[], retained_rehearsal_rows=2,
        source_sha256=SOURCE_SHA, master_sha256=MASTER_SHA, acceptance_sha256=ACCEPTANCE_SHA,
        full_license_text_sha256=sha(NOTICE), projection_errors=errors,
        human_acceptance="not-recorded", rights_clearance="unresolved"))

    destination = LOG / "release"
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
            raise PipelineError(name + " failed: " + json.dumps(result))
        gates[name] = sha(LOG / (name + ".json"))
        print(name + ": PASS", flush=True)
    total = read(LOG / "statistics.json")["total"]
    if total["records"] != 2 or total["text_characters"] != chars:
        raise PipelineError("Released counts differ from actual-master projection")
    card = (destination / "public/README.md").read_text(encoding="utf-8")
    if NOTICE.read_text(encoding="utf-8").rstrip() not in card:
        raise PipelineError("Release omits complete human-visible license and attribution")
    check(bindings)
    if _files(WORK) != installed:
        raise PipelineError("Installed work changed before completion")
    files = _files(destination)
    completion = dict(status="pass", checked_at=datetime.now(timezone.utc).isoformat(),
        work_id=WID, rows=2, text_characters=chars, accepted_master_sha256=MASTER_SHA,
        acceptance_sha256=ACCEPTANCE_SHA, input_bindings=bindings,
        preserved_work_files=installed, release_file_bindings=files, gates=gates,
        selection_path=(LOG / "selection.json").relative_to(ROOT).as_posix(),
        selection_sha256=sha(LOG / "selection.json"), release_path=str(destination.resolve()),
        private_offline=True, publication_performed=False, human_acceptance="not-recorded",
        print_collation="not-performed", rights_clearance="unresolved",
        final_public_release_selection="unresolved", reconstruction_performed=False,
        reinstall_performed=False)
    save(LOG / "completion.json", completion)
    save(WORK / "publication/completion.json", (LOG / "completion.json").read_bytes())
    save(WORK / "publication/selection.json", (LOG / "selection.json").read_bytes())
    save(WORK / "publication/README.md", (
        "# The Epistle of Ignatius to the Virgin Mary: private offline release\n\n"
        f"The unchanged accepted electronic witness passes actual-master projection, assembly, "
        f"independent verification, statistics and both offline readers: 2 rows and {chars:,} "
        "text characters. The public dataset card includes source attribution and the full "
        "retained Project Gutenberg License.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind this release. "
        "Human acceptance, print collation, rights clearance and public publication remain separate.\n"
    ).encode())
    expected = dict(installed)
    expected.update({"publication/" + name: sha(WORK / "publication" / name)
                     for name in ("completion.json", "selection.json", "README.md")})
    if _files(WORK) != expected or _files(destination) != files:
        raise PipelineError("Final delivery envelope differs")
    check(bindings)
    save(LOG / "final-audit.json", dict(status="pass", input_binding_count=len(bindings),
        canonical_files=expected, release_file_count=len(files), all_release_files_match=True,
        canonical_completion_byte_identical=sha(WORK / "publication/completion.json") == sha(LOG / "completion.json"),
        canonical_selection_byte_identical=sha(WORK / "publication/selection.json") == sha(LOG / "selection.json"),
        rows=2, text_characters=chars, publication_performed=False))
    print(json.dumps(dict(status="pass", rows=2, text_characters=chars,
                          installed_files=len(installed), release_files=len(files))), flush=True)


def main() -> None:
    original_io_path = prose.io_path
    try:
        _main()
    finally:
        prose.io_path = original_io_path


if __name__ == "__main__":
    main()
