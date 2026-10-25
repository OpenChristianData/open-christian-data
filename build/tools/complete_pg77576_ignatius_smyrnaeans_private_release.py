"""Freeze the accepted Smyrnaeans electronic witness as a private offline release."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json

from lxml import etree, html

from build.tools.check_release_reader import check_reader
from build.tools.complete_puritan_private_release import check, read, save, sha
from build.tools.report_release_stats import release_statistics
from build.tools.project_pg77576_ignatius_smyrnaeans import (
    ACCEPTANCE, ACCEPTANCE_SHA256, MASTER, MASTER_SHA256, SOURCE,
    SOURCE_SHA256, WORK, WORK_ID, prepare, verify_rows,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.install_accepted import _files
import ocd_kernel.projection.categories.prose as prose


ROOT = Path(__file__).resolve().parents[2]
WORK_HOME = ROOT / WORK
REHEARSAL = ROOT / WORK / "forms/pg77576-ignatius-smyrnaeans-english/editions/pg77576-ignatius-smyrnaeans-pg77576-edition/publication/release-rehearsal"
JOURNAL = ROOT / ".tmp_audit/accepted-install-736f9d2475df4064/operation.json"
NOTICE = ROOT / "data/structured-text/pg77576-ignatius-smyrnaeans/README.md"
LOG = ROOT / "reports/_logs/pg77576-ignatius-smyrnaeans-private-release-20261003-v1"
LICENSE_SHA256 = "9df13869f294cf8b9625debae7b80846b71ebd015287cc3971435f98f0cae046"


def run() -> dict:
    if (WORK_HOME / "publication").exists() or LOG.exists():
        raise PipelineError("Fresh Smyrnaeans release destination required")
    installed = _files(WORK_HOME)
    journal = read(JOURNAL)
    if journal["phase"] != "complete" or journal["work_id"] != WORK_ID or any(
        installed.get(path) != digest for path, digest in journal["after"].items()
        if path != "HANDOFF_20260930.md"
    ):
        raise PipelineError("Installed files differ from the completed journal")
    if (sha(ROOT / MASTER), sha(ROOT / ACCEPTANCE), sha(ROOT / SOURCE)) != (
        MASTER_SHA256, ACCEPTANCE_SHA256, SOURCE_SHA256
    ):
        raise PipelineError("Accepted master, acceptance, or retained HTML differs")
    old = read(REHEARSAL / "selection.json")
    if len(old["items"]) != 1 or old["items"][0]["item_id"] != WORK_ID:
        raise PipelineError("Retained Smyrnaeans rehearsal selection differs")
    prior = read(ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json")
    if prior["by_work"].get(WORK_ID, []):
        raise PipelineError("Earlier canonical release selection requires reconciliation")

    document = html.fromstring((ROOT / SOURCE).read_bytes())
    headings = document.xpath('//h2[@id="pg-footer-heading"]')
    if len(headings) != 1:
        raise PipelineError("Retained Project Gutenberg footer heading differs")
    license_text = "\n\n".join(
        etree.tostring(node, method="text", encoding="unicode").strip()
        for node in [headings[0], *headings[0].itersiblings()]
    ).replace("\r\n", "\n")
    if len(license_text) != 17072 or sha256(license_text.encode()).hexdigest() != LICENSE_SHA256:
        raise PipelineError("Full retained Project Gutenberg License differs")
    base_notice = NOTICE.read_bytes()
    credit = (
        "# Source credit and retained license\n\n"
        "This text is the *Epistle of Ignatius to the Smyrnaeans* from "
        "[Project Gutenberg eBook 77576](https://www.gutenberg.org/ebooks/77576), "
        "*The Writings of the Apostolic Fathers* (T. & T. Clark, Edinburgh, 1870). "
        "The retained title page names Alexander Roberts and James Donaldson as editors "
        "and lists Roberts, Donaldson, and Frederick Crombie as translators of the volume. "
        "The preface attributes the volume translation to the editors except for the "
        "*Similitudes of Hermas*, translated by Crombie. Roberts and Donaldson are therefore "
        "the supported collective translator attribution for this epistle; the source does "
        "not identify which editor translated it. The Gutenberg HTML header foregrounds "
        "Crombie, while its catalog lists all three volume translators. The catalog credits "
        "David King and the Online Proofreading Team and says the electronic text was produced "
        "from images made available by the Internet Archive. The extracted retained HTML is "
        "the textual source; the retained ZIP is the acquisition package.\n\n"
        "The Gutenberg catalog reports public-domain status in the United States. Rights for "
        "this translation, electronic transcription, and reconstruction have not been cleared "
        "for every jurisdiction. Human verification, print collation, and public publication "
        "authorization are separate.\n\n"
        "## Full retained Project Gutenberg License\n\n"
        "The following is the complete license text carried in the retained eBook 77576 HTML.\n\n"
        "```text\n" + license_text + "\n```\n"
    )
    if sha256(base_notice).hexdigest() == old["items"][0]["public_notices"][0]["notice_sha256"]:
        NOTICE.write_bytes(base_notice.replace(b"\r\n", b"\n").rstrip() + b"\n\n" + credit.encode())
    elif not base_notice.endswith(b"\n\n" + credit.encode()):
        raise PipelineError("Existing visible notice differs from rehearsal or this release")
    notice = dict(old["items"][0]["public_notices"][0])
    notice["notice_sha256"] = sha(NOTICE)
    selection = {**old, "release_id": "pg77576-ignatius-smyrnaeans-private-offline-20261003-v1",
                 "items": [{**old["items"][0], "public_notices": [notice]}]}

    # Normalize only the equivalent root and acceptance spellings passed by the
    # prose entrypoint; retain its original containment check for every path.
    original_io_path = prose.io_path
    canonical = {str(ROOT), str(ROOT / ACCEPTANCE)}
    def ordinary_authority_paths(path: Path) -> Path:
        ordinary = str(path).removeprefix("\\\\?\\")
        return Path(ordinary) if ordinary in canonical else original_io_path(path)
    outside = ROOT.parent / "EzraOCR" / "AGENTS.md"
    if ordinary_authority_paths(outside) != original_io_path(outside):
        raise PipelineError("Outside-path adapter challenge failed")
    try:
        outside.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise PipelineError("Outside path unexpectedly passed containment")
    prose.io_path = ordinary_authority_paths
    try:
        projection = prepare(ROOT)
        rows = projection["rows"]
        errors = verify_rows(rows, projection["native_receipt"], root=ROOT)
        if errors or len(rows) != 2:
            raise PipelineError(f"Actual-master projection differs: {errors}")
        characters = sum(len(row["text"]) for row in rows)
        if [json.loads(line) for line in (REHEARSAL / "public/data/prose/train.jsonl").read_text(encoding="utf-8").splitlines()] != rows:
            raise PipelineError("Retained rehearsal differs from current accepted master")
        bindings = {(WORK / path).as_posix(): digest for path, digest in installed.items()}
        inputs = [JOURNAL, ROOT / SOURCE, ROOT / "raw/gutenberg/77576/pg77576-h.zip",
                  ROOT / "raw/gutenberg/77576/acquisition-receipt.json", NOTICE,
                  ROOT / notice["source_path"], REHEARSAL / "selection.json",
                  REHEARSAL / "rehearsal-index.json",
                  ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json",
                  Path(__file__), ROOT / "build/tools/project_pg77576_ignatius_smyrnaeans.py",
                  ROOT / "build/tools/report_release_stats.py", ROOT / "build/tools/check_release_reader.py"]
        for folder in ("ocd_kernel/release", "ocd_kernel/library", "ocd_kernel/tei"):
            inputs.extend((ROOT / folder).rglob("*.py"))
        inputs.extend(ROOT / "ocd_kernel/projection" / path for path in (
            "categories/prose.py", "categories/sermons.py", "categories/native_documents.py",
            "envelope.py", "scripture_authority.py", "scripture_targets.py",
        ))
        inputs.extend((ROOT / "schemas/v2").rglob("*.json"))
        bindings.update({path.relative_to(ROOT).as_posix(): sha(path) for path in inputs})
        check(bindings)
        save(LOG / "selection.json", selection)
        save(LOG / "input-bindings-before.json", bindings)
        save(LOG / "actual-master-projection.json", {"rows": rows, "receipt": projection["native_receipt"], "errors": errors})
        save(LOG / "attribution-and-license.json", {
            "status": "pass", "source_sha256": SOURCE_SHA256,
            "full_license_text_characters": len(license_text),
            "full_license_text_sha256": LICENSE_SHA256,
            "visible_notice_path": NOTICE.relative_to(ROOT).as_posix(),
            "visible_notice_sha256": sha(NOTICE),
            "source_note_sha256": notice["source_sha256"],
        })
        save(LOG / "installation-and-prior-release-reconciliation.json", {
            "status": "pass", "installed_files": len(installed),
            "install_journal": JOURNAL.relative_to(ROOT).as_posix(),
            "journal_files": len(journal["after"]),
            "post_install_handoff_updated": True,
            "post_install_handoff_exception": "HANDOFF_20260930.md was updated after the completed acceptance installation; every other journal-bound file matches its installed hash",
            "prior_index_selections": [], "retained_rehearsal_rows": 2,
            "source_sha256": SOURCE_SHA256, "master_sha256": MASTER_SHA256,
            "acceptance_sha256": ACCEPTANCE_SHA256,
            "human_acceptance": "not-recorded", "rights_clearance": "unresolved",
        })
        save(LOG / "prior-attempts.json", {"status": "preserved-failures", "attempts": [
            {"stage": "license extraction preflight", "error": "Retained HTML CRLF needed normalization to the bound 17,072-character text"},
            {"stage": "sandbox report creation", "error": "WinError 5 on the durable reports junction; approved host context required"},
        ]})
        release = LOG / "release"
        gate_hashes = {}
        for name, operation in (
            ("assembly", lambda: assemble_release_v2(ROOT, release, selection=selection)),
            ("independent-verification", lambda: verify_release_v2(ROOT, release, selection=selection)),
            ("statistics", lambda: release_statistics(ROOT, release, selection)),
            ("readers", lambda: check_reader(ROOT, release, selection)),
        ):
            print(name + ": START", flush=True)
            result = operation()
            save(LOG / (name + ".json"), result)
            if result["status"] != "pass":
                raise PipelineError(name + " failed: " + json.dumps(result))
            gate_hashes[name] = sha(LOG / (name + ".json"))
            print(name + ": PASS", flush=True)
        total = read(LOG / "statistics.json")["total"]
        if total["records"] != 2 or total["text_characters"] != characters:
            raise PipelineError("Released statistics differ from current projection")
        card = (release / "public/README.md").read_text(encoding="utf-8")
        if NOTICE.read_text(encoding="utf-8").rstrip() not in card:
            raise PipelineError("Public card omits full visible notice")
        check(bindings)
        if _files(WORK_HOME) != installed:
            raise PipelineError("Installed work changed before completion")
        files = _files(release)
        completion = {
            "status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(),
            "work_id": WORK_ID, "rows": 2, "text_characters": characters,
            "accepted_master_sha256": MASTER_SHA256, "acceptance_sha256": ACCEPTANCE_SHA256,
            "input_bindings": bindings, "preserved_work_files": installed,
            "release_file_bindings": files, "gates": gate_hashes,
            "selection_path": (LOG / "selection.json").relative_to(ROOT).as_posix(),
            "selection_sha256": sha(LOG / "selection.json"),
            "release_path": str(release.resolve()), "private_offline": True,
            "publication_performed": False, "human_acceptance": "not-recorded",
            "print_collation": "not-performed", "rights_clearance": "unresolved",
            "final_public_release_selection": "unresolved", "reconstruction_performed": False,
            "reinstall_performed": False,
        }
        save(LOG / "completion.json", completion)
        save(WORK_HOME / "publication/completion.json", (LOG / "completion.json").read_bytes())
        save(WORK_HOME / "publication/selection.json", (LOG / "selection.json").read_bytes())
        save(WORK_HOME / "publication/README.md", (
            "# The Epistle of Ignatius to the Smyrnaeans: private offline release\n\n"
            f"The unchanged accepted electronic witness passes actual-master projection, assembly, "
            f"independent verification, statistics, and both offline readers: 2 rows and "
            f"{characters:,} text characters. The public dataset card carries the detailed source "
            "credit and complete retained Project Gutenberg License.\n\n"
            "[Completion](completion.json) and [selection](selection.json) bind this release. "
            "Human acceptance, print collation, rights clearance, and public publication remain separate.\n"
        ).encode())
        expected = dict(installed)
        expected.update({"publication/" + name: sha(WORK_HOME / "publication" / name)
                         for name in ("completion.json", "selection.json", "README.md")})
        if _files(WORK_HOME) != expected or _files(release) != files:
            raise PipelineError("Final delivery envelope differs")
        check(bindings)
        save(LOG / "final-audit.json", {"status": "pass", "input_binding_count": len(bindings),
             "canonical_files": expected, "release_file_count": len(files),
             "canonical_completion_byte_identical": sha(WORK_HOME / "publication/completion.json") == sha(LOG / "completion.json"),
             "canonical_selection_byte_identical": sha(WORK_HOME / "publication/selection.json") == sha(LOG / "selection.json"),
             "rows": 2, "text_characters": characters, "publication_performed": False})
        return {"status": "pass", "rows": 2, "text_characters": characters,
                "installed_files": len(installed), "release_files": len(files)}
    finally:
        prose.io_path = original_io_path


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True), flush=True)
