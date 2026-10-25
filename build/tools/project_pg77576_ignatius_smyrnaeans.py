"""Project the installed PG77576 Smyrnaeans master without publishing it."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document,
    verify_accepted_document,
)
from ocd_kernel.tei.acceptance import validate_acceptance


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "pg77576-ignatius-smyrnaeans"
FORM_ID = "pg77576-ignatius-smyrnaeans-english"
EDITION_ID = "pg77576-ignatius-smyrnaeans-pg77576-edition"
ACQUISITION_ID = "pg77576-ignatius-smyrnaeans-pg77576-acquisition"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
MASTER = EDITION / "master.tei.xml"
ACCEPTANCE = EDITION / "acceptance.json"
STATE = WORK / "state.json"
SOURCE = Path("raw/gutenberg/77576/html/pg77576-images.html")
MANIFEST = WORK / "integration/pg77576-html-v1/source-manifest.json"
PACKAGE = WORK / "integration/pg77576-html-v1/candidate/package"
VALIDATION = WORK / "integration/pg77576-html-v1/candidate/validation.json"
TECHNICAL = WORK / "integration/pg77576-html-v1/technical-receipt.json"
INDEPENDENT_REVIEW = Path(
    "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/"
    "PG77576_IGNATIUS_SMYRNAEANS_INDEPENDENT_REREVIEW_20260930.md"
)
OWNER_CLOSEOUT = Path(
    "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/"
    "PG77576_IGNATIUS_SMYRNAEANS_OWNER_CLOSEOUT_20260930.md"
)
CVW_REVIEW = Path(
    "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/"
    "PG77576_IGNATIUS_SMYRNAEANS_CVW_VISUAL_REVIEW_20260930.md"
)
PUBLICATION = EDITION / "publication"
ROWS = PUBLICATION / "prose.jsonl"
RECEIPT = PUBLICATION / "projection-receipt.json"
CORRESPONDENCE = PUBLICATION / "independent-correspondence.json"
SOURCE_CREDIT = PUBLICATION / "SOURCE_CREDIT.md"
SOURCE_NOTE = Path("sources/gutenberg") / WORK_ID / "README.source.md"
PUBLIC_NOTICE = Path("data/structured-text") / WORK_ID / "README.md"

SOURCE_SHA256 = "ca58049f2ee7c62c8c34dffb6badfdb910ab698748f8decc9d9b978e7972e507"
MANIFEST_SHA256 = "9dfd5797e5542e5cbc40846f78bd074972cb839ffebc21c645e9088fbe65357d"
PACKAGE_SHA256 = "ef06cc0d1a11bdd3543cfe37d01a8757d5e59a4e4499de6c56684cad16c1480c"
CANDIDATE_SHA256 = "5625f555de9fa9be4333adbeb60473488d3af3bb814277a0d7b687247e2bab75"
VALIDATION_SHA256 = "a02e4b269ed67155ceb63483dd1f215b01016c30c8193cf4a2f447199112db4d"
VALIDATION_REPORT_SHA256 = "4e09d04a58b594cf54b5b899779be6943d81fdf314cd090628d8a63f3e8f7838"
TECHNICAL_SHA256 = "8d8b42c9c525583e4b855454903c0208872175e776f69e0c640d194afaa91cad"
MASTER_SHA256 = "20dcfa973d9c717e45bef7668287a6e988f9a3e9ddde7b7e8a5bc4b10d26fc9c"
ACCEPTANCE_SHA256 = "53da3076403cb21d71fca3fd22b70469e16be671919ddd1cd873b4db331e9488"
PREVIOUS_SOURCE_CREDIT_SHA256 = "383149268775ddd6b0d339e2690b2a80341dabdd1a96914cfae99c2becc66cda"
PREVIOUS_CORRESPONDENCE_SHA256 = "86ee33349a3f9bf05f887c6ca777565f603b375aa16ea8116ede03096057e3c3"
PREVIOUS_CURRENT_SOURCE_CREDIT_SHA256 = "c2650c677df3e9d1450ca441eef1107c85b9311de383d3ab5ce72e9c29bd1aa8"
PREVIOUS_CURRENT_SOURCE_NOTE_SHA256 = "a7eb0ef6348f4d3a390a5601d7dfb11da8a8fa9387766ea4efb6fb71442b7884"
PREVIOUS_CURRENT_CORRESPONDENCE_SHA256 = "10c6334b6727885ce6f2fc80f81affd4550e4acd774a73bd938fbc24725407a9"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(_json_bytes(row) for row in rows)


def _source_credit() -> bytes:
    return (
        "# Source and attribution — Ignatius to the Smyrnaeans\n\n"
        "This edition represents the source-titled *Epistle of Ignatius to the Smyrnaeans* "
        "in [Project Gutenberg eBook 77576](https://www.gutenberg.org/ebooks/77576), "
        "using the retained extracted HTML text at `raw/gutenberg/77576/html/pg77576-images.html`. "
        "The ZIP is the acquisition package; the extracted HTML is the text source. The selected "
        "HTML body interval is `[729,799)`, including the Shorter and Longer readings and their "
        "linked endnotes.\n\n"
        "The Project Gutenberg eBook page identifies the volume as *The Writings of the Apostolic "
        "Fathers*, originally published in Edinburgh by T. & T. Clark in 1870. The retained title page "
        "names Alexander Roberts and James Donaldson as editors and lists Roberts, Donaldson, and "
        "Frederick Crombie as translators of the volume. Its preface says the volume was translated by "
        "the Editors except for the *Similitudes of Hermas*, translated by Crombie. This places the "
        "Smyrnaeans translation under Roberts and Donaldson collectively, but the source does not say "
        "which editor translated this epistle. The Project Gutenberg HTML header foregrounds Crombie "
        "as translator while the catalog lists all three volume translators. The catalog credits David King and "
        "the Online Proofreading Team and says the file was produced from images made available by "
        "the Internet Archive.\n\n"
        "The catalog reports the eBook as public domain in the United States. That statement does "
        "not establish rights in every jurisdiction or resolve the status of this electronic "
        "transcription and translation. Project Gutenberg's [license](https://www.gutenberg.org/policy/license) "
        "and [terms of use](https://www.gutenberg.org/policy/terms_of_use.html) describe additional "
        "conditions when its name remains associated with a redistributed or transformed eBook, "
        "including access to the original format. The intended release treatment has not been "
        "cleared. The corresponding human-readable public notice is at `" + PUBLIC_NOTICE.as_posix() + "`.\n\n"
        "No print collation, jurisdiction-specific rights decision, human verification, or "
        "publication authorization is recorded here. This source note prepares attribution and "
        "rights review; it is not a rights clearance or publication approval.\n"
    ).encode("utf-8")


def _source_note() -> bytes:
    return (
        "# Source and rights preparation — Ignatius to the Smyrnaeans\n\n"
        f"The text is reconstructed from the retained extracted HTML for [Project Gutenberg eBook 77576]"
        f"(https://www.gutenberg.org/ebooks/77576): `{SOURCE.as_posix()}`. The ZIP is the acquisition "
        "package; this HTML file is the textual source. The selected body interval is `[729,799)`, "
        "including both the Shorter and Longer readings and their linked notes.\n\n"
        "The eBook page identifies the volume as *The Writings of the Apostolic Fathers*, first "
        "published in Edinburgh by T. & T. Clark in 1870. The retained title page names Alexander "
        "Roberts and James Donaldson as editors and lists Roberts, Donaldson, and Frederick Crombie as "
        "volume translators. The preface says the volume was translated by the Editors except for the "
        "*Similitudes of Hermas*, translated by Crombie. Accordingly, Roberts and Donaldson are the "
        "supported collective translator attribution for Smyrnaeans, but the source does not identify "
        "which editor translated this epistle. The Project Gutenberg HTML header foregrounds Crombie, "
        "while its catalog lists all three translators. The catalog credits David King and the Online Proofreading Team and says the text was produced "
        "from images made available by the Internet Archive.\n\n"
        f"The selected release notice is `data/structured-text/{WORK_ID}/README.md`. It carries the "
        "eBook's Project Gutenberg license notice, a direct link to the full license, and a link to "
        "the original electronic formats. The eBook page reports public-domain status in the United "
        "States; that is not a jurisdiction-specific clearance for this translation, electronic "
        "transcription, or reconstructed text. No rights clearance, full print collation, human "
        "verification, or publication authorization is recorded. This note prepares attribution and "
        "rights review and does not authorize publication.\n"
    ).encode("utf-8")


def _public_notice() -> bytes:
    return (
        "This eBook is for the use of anyone anywhere in the United States and most other parts of the world "
        "at no cost and with almost no restrictions whatsoever. You may copy it, give it away or re-use it under "
        "the terms of the [Project Gutenberg License](https://www.gutenberg.org/policy/license) included with "
        "this eBook or online at [www.gutenberg.org](https://www.gutenberg.org). If you are not located in the "
        "United States, you'll have to check the laws of the country where you are located before using this ebook.\n\n"
        "Original electronic formats: [Project Gutenberg eBook 77576](https://www.gutenberg.org/ebooks/77576).\n"
    ).encode("utf-8")


def _read_repo(root: Path, relative: Path) -> bytes:
    path = resolve_repo_path(root, relative.as_posix()) if relative.as_posix().startswith("raw/") else root / relative
    return path.read_bytes()


def _walk_notes(value: Any):
    if isinstance(value, dict):
        if value.get("kind") == "note":
            yield value
        for child in value.values():
            yield from _walk_notes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_notes(child)


def verify_rows(rows: object, receipt: dict[str, Any], *, root: Path = ROOT) -> list[str]:
    """Independently check native rows against the accepted TEI master."""
    if not isinstance(rows, list):
        return ["projection rows must be a list"]
    errors = verify_accepted_document(
        root,
        acceptance_path=root / ACCEPTANCE,
        rows=rows,
        receipt=receipt,
        category="prose",
    )
    return errors


def prepare(root: Path = ROOT) -> dict[str, Any]:
    """Verify canonical authority and derive actual-master rows without writing."""
    root = root.resolve(strict=True)
    work_path = root / WORK
    edition_path = root / EDITION
    source_bytes = _read_repo(root, SOURCE)
    master_bytes = (root / MASTER).read_bytes()
    acceptance_bytes = (root / ACCEPTANCE).read_bytes()
    state_bytes = (root / STATE).read_bytes()
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    accepted = validate_acceptance(root / ACCEPTANCE, root=root)
    state = validate_state(root / STATE, root=root)
    work = load_work(root / WORK / "work.json")

    pinned = {
        "source": _sha(source_bytes) == SOURCE_SHA256,
        "manifest": _file_sha(root / MANIFEST) == MANIFEST_SHA256,
        "package": _file_sha(root / PACKAGE / "manifest.json") == PACKAGE_SHA256,
        "candidate": _file_sha(root / PACKAGE / "content.tei.xml") == CANDIDATE_SHA256,
        "validation": _file_sha(root / VALIDATION) == VALIDATION_SHA256,
        "technical": _file_sha(root / TECHNICAL) == TECHNICAL_SHA256,
        "master": _sha(master_bytes) == MASTER_SHA256,
        "acceptance": _sha(acceptance_bytes) == ACCEPTANCE_SHA256,
    }
    if not all(pinned.values()):
        raise PipelineError(f"projection input binding differs: {[key for key, ok in pinned.items() if not ok]}")
    validation = json.loads((root / VALIDATION).read_bytes())
    if validation.get("status") != "pass" or validation.get("report_sha256") != VALIDATION_REPORT_SHA256:
        raise PipelineError("accepted candidate source-oracle report differs")
    if (acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != SOURCE_SHA256
            or acquisition.get("source_bytes") != len(source_bytes)
            or len(acquisition.get("retained_files", [])) != 3):
        raise PipelineError("acquisition source or member inventory differs")
    if (accepted.get("identity") != {
            "work_id": WORK_ID,
            "textual_form_id": FORM_ID,
            "edition_id": EDITION_ID,
            "acquisition_id": ACQUISITION_ID,
        }
            or accepted.get("promotion", {}).get("status") != "promoted"
            or accepted.get("promotion", {}).get("master", {}).get("sha256") != MASTER_SHA256):
        raise PipelineError("accepted work identity or promotion binding differs")
    if accepted.get("source", {}).get("source_sha256") != SOURCE_SHA256:
        raise PipelineError("acceptance does not bind retained HTML")
    if work["work_id"] != WORK_ID:
        raise PipelineError("work sidecar identity differs")
    targets = [
        target for target in state["targets"]
        if target.get("target_type") == "edition" and target.get("target_id") == EDITION_ID
    ]
    if len(targets) != 1 or targets[0].get("stage") != "accepted":
        raise PipelineError("canonical edition state is not accepted")

    candidate = (root / PACKAGE / "content.tei.xml").read_bytes()
    boundary = b"</teiHeader>"
    if (candidate.count(boundary) != 1 or master_bytes.count(boundary) != 1
            or candidate.split(boundary, 1)[1] != master_bytes.split(boundary, 1)[1]):
        raise PipelineError("installed master text differs from the reviewed candidate body")

    projection = project_accepted_document(root, acceptance_path=root / ACCEPTANCE, category="prose")
    rows = projection["rows"]
    native_receipt = projection["receipt"]
    errors = verify_rows(rows, native_receipt, root=root)
    if errors:
        raise PipelineError(f"actual-master row verification failed: {errors[:3]}")
    if len(rows) != 2 or [row["locator"].get("text_part") for row in rows] != ["body", "back"]:
        raise PipelineError("public prose row boundaries differ")
    body_text = rows[0].get("text", "")
    if (body_text.count("Shorter.") != 14 or body_text.count("Longer.") != 14
            or "Chap. i.—Thanks to God for your faith." not in body_text
            or "Chap.Chapter" in body_text or "i.one—" in body_text):
        raise PipelineError("public readable text does not preserve the paired readings and abbreviation choices")
    notes = list(_walk_notes(rows[1].get("structure", [])))
    note_numbers = [note.get("attributes", {}).get("number") for note in notes]
    expected_numbers = [str(number) for number in range(1230, 1318)]
    if note_numbers != expected_numbers:
        raise PipelineError("public structured endnote sequence differs")
    if rows[1].get("text") != "" or not any("Notes and page markers remain in structure" in warning
                                               for warning in native_receipt.get("warnings", [])):
        raise PipelineError("empty back-matter text lacks its explicit structured-note warning")
    if len(rows[0].get("source_references", [])) != 176 or len(rows[1].get("source_references", [])) != 88:
        raise PipelineError("projected source-reference census differs")

    return {
        "root": root,
        "rows": rows,
        "native_receipt": native_receipt,
        "errors": errors,
        "source_bytes": source_bytes,
        "master_bytes": master_bytes,
        "acceptance_bytes": acceptance_bytes,
        "state_bytes": state_bytes,
        "candidate_bytes": candidate,
        "validation_report_sha256": validation["report_sha256"],
        "note_numbers": note_numbers,
        "review_bindings": {
            "independent_review_sha256": _file_sha(root / INDEPENDENT_REVIEW),
            "owner_closeout_sha256": _file_sha(root / OWNER_CLOSEOUT),
            "cvw_review_sha256": _file_sha(root / CVW_REVIEW),
        },
    }


def run(root: Path = ROOT) -> dict[str, Any]:
    """Write deterministic per-edition prose rows and their private checks."""
    prepared = prepare(root)
    rows_bytes = _jsonl_bytes(prepared["rows"])
    credit_bytes = _source_credit()
    source_note_bytes = _source_note()
    public_notice_bytes = _public_notice()
    receipt_bytes = _json_bytes(prepared["native_receipt"])
    correspondence = {
        "contract": "ocd-pg77576-smyrnaeans-independent-correspondence-v1",
        "status": "pass",
        "errors": prepared["errors"],
        "method": (
            "The retained-source oracle passed the bound HTML-to-TEI reconstruction; the native prose "
            "projector read the actual accepted master; verify_accepted_document independently observed "
            "the master and all rows. The reviewed body bytes are identical from candidate through master."
        ),
        "source_sha256": _sha(prepared["source_bytes"]),
        "source_candidate_sha256": CANDIDATE_SHA256,
        "source_manifest_sha256": MANIFEST_SHA256,
        "source_validation_report_sha256": prepared["validation_report_sha256"],
        "technical_receipt_sha256": TECHNICAL_SHA256,
        "actual_master_sha256": _sha(prepared["master_bytes"]),
        "acceptance_sha256": _sha(prepared["acceptance_bytes"]),
        "state_sha256": _sha(prepared["state_bytes"]),
        "rows_sha256": _sha(rows_bytes),
        "native_projection_receipt_sha256": _sha(receipt_bytes),
        "source_credit_sha256": _sha(credit_bytes),
        "source_note_path": SOURCE_NOTE.as_posix(),
        "source_note_sha256": _sha(source_note_bytes),
        "public_notice_path": PUBLIC_NOTICE.as_posix(),
        "public_notice_sha256": _sha(public_notice_bytes),
        "row_count": len(prepared["rows"]),
        "body_row_count": 1,
        "structured_endnote_count": len(prepared["note_numbers"]),
        "endnote_numbers": prepared["note_numbers"],
        "source_reference_counts": [len(row["source_references"]) for row in prepared["rows"]],
        "empty_readable_text_rows": [
            {"sequence": prepared["rows"][1]["sequence"], "locator": prepared["rows"][1]["locator"],
             "note": "The 88 endnotes are retained in native structure; the generic readable-text renderer omits note text by contract."}
        ],
        "review_bindings": prepared["review_bindings"],
        "holds": ["human verification", "rights clearance", "publication authorization"],
    }
    outputs = {
        ROWS: rows_bytes,
        RECEIPT: receipt_bytes,
        CORRESPONDENCE: _json_bytes(correspondence),
        SOURCE_CREDIT: credit_bytes,
        SOURCE_NOTE: source_note_bytes,
        PUBLIC_NOTICE: public_notice_bytes,
    }
    publication = (prepared["root"] / PUBLICATION)
    publication.mkdir(parents=True, exist_ok=True)
    for relative, content in outputs.items():
        path = prepared["root"] / relative
        if path.exists() and path.read_bytes() != content:
            previous_hashes = {
                SOURCE_CREDIT: {PREVIOUS_SOURCE_CREDIT_SHA256, PREVIOUS_CURRENT_SOURCE_CREDIT_SHA256},
                SOURCE_NOTE: {PREVIOUS_CURRENT_SOURCE_NOTE_SHA256},
                CORRESPONDENCE: {PREVIOUS_CORRESPONDENCE_SHA256, PREVIOUS_CURRENT_CORRESPONDENCE_SHA256},
            }
            previous_matches = relative in previous_hashes and _file_sha(path) in previous_hashes[relative]
            if not previous_matches:
                raise PipelineError(f"existing publication artifact differs: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {
        "status": "projected-not-authorized-for-publication",
        "work_id": WORK_ID,
        "row_count": len(prepared["rows"]),
        "rows_sha256": _sha(rows_bytes),
        "projection_receipt_sha256": _sha(receipt_bytes),
        "master_sha256": _sha(prepared["master_bytes"]),
        "acceptance_sha256": _sha(prepared["acceptance_bytes"]),
        "rights": "not-cleared",
        "source_note_sha256": _sha(source_note_bytes),
        "public_notice_sha256": _sha(public_notice_bytes),
        "publication_authorization": "not-recorded",
        "artifacts": {relative.as_posix(): _sha(content) for relative, content in outputs.items()},
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
