"""Stage exact Chadwick and Newman electronic witnesses for sidecar review.

The existing catalog identities are preserved. Each source file gets its own
edition and acquisition so that separate books, imprints, and OCR files are not
silently merged into a historical print edition. This command never installs.
"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file, write_json
from ocd_kernel.library.identities import load_work, validate_identity_update, validate_record
from ocd_kernel.library.state import load_state
from ocd_kernel.tei.install_accepted import _io_path


CONTRACT = "ocd-two-lookup-volume-sidecar-stage-v1"
CHADWICK = "expositors-bible--g-a-chadwick"
NEWMAN = "newman-parochial-sermons"
BEFORE = {
    CHADWICK: (
        "b9bddb64fcc42b828a5168bff2aa2106261efce0cbd6386f62a0ba7a0609f6d1",
        "3ddf9e29af8b7c701050aae41a6d09ac32e63f3969a14a1d8772821ad68d642b",
    ),
    NEWMAN: (
        "7e7a5d7b6c3964195da7327f04d4c39603a57960269405b70a77817a1ebfeb61",
        "910dfada480bc059ae9933c16bb10957af28f2bff5c52c95b5fbf1949fee7885",
    ),
}
SOURCES = (
    (CHADWICK, "mark", "raw/ccel/expositors-bible/chadwick_mark.xml", 912510,
     "1bbe36d072f96184a6d6c46a13d0b0b4e6c395f02efd5e769dc87e2d6fcf4bf2",
     "The Expositor's Bible: The Gospel According to St. Mark", "https://www.ccel.org/ccel/chadwick/mark.html"),
    (CHADWICK, "exodus", "raw/ccel/expositors-bible/chadwick_expositor2.xml", 980151,
     "aa254cd88c1d64f9e5210288079a289dc57fc634410488662e0e721da8874c61",
     "The Expositor's Bible: The Book of Exodus", "https://www.ccel.org/ccel/chadwick/expositor2.html"),
    (NEWMAN, "ia-01", "raw/gutenberg/sermons/newman/parochialplainse01newmuoft_djvu.txt", 620835,
     "df2855e040bebdb69540fb873382ad6d71154fd69092d9abf4b8f0931378bfb1", "Nominal volume I IA OCR", "https://archive.org/details/parochialplainse01newmuoft"),
    (NEWMAN, "ia-02", "raw/gutenberg/sermons/newman/parochialplainse02newmuoft_djvu.txt", 396998,
     "329555c165fd89d7e29e920263357b9e9ece0b105494ed924121b33fd8163470", "Nominal volume II IA OCR; also contains volume-I material", "https://archive.org/details/parochialplainse02newmuoft"),
    (NEWMAN, "ia-03", "raw/gutenberg/sermons/newman/parochialplainse03newmuoft_djvu.txt", 728348,
     "e6a85ffbb420fd2aedac30ec1794d1bbf70bc3add594a646a56c11492177ef81", "Nominal volume III IA OCR; retained title page says 1870", "https://archive.org/details/parochialplainse03newmuoft"),
    (NEWMAN, "ia-04", "raw/gutenberg/sermons/newman/parochialplainse04newmuoft_djvu.txt", 619880,
     "19325e2b48c6047e6aa3d49c4e140f30f81e86cb2f82a867a9e715e83eb2972e", "Nominal volume IV IA OCR", "https://archive.org/details/parochialplainse04newmuoft"),
    (NEWMAN, "ia-05", "raw/gutenberg/sermons/newman/parochialplainse05newmuoft_djvu.txt", 628785,
     "c9406956bc17714081ec1b62582f81180d7db80363e8d2ddcb0428ac71dd68ec", "Nominal volume V IA OCR", "https://archive.org/details/parochialplainse05newmuoft"),
    (NEWMAN, "ia-06", "raw/gutenberg/sermons/newman/parochialplainse06newmuoft_djvu.txt", 655060,
     "bde36cfa8522a832ec0ac7c802d8e6562877caa1f01d96a73d140128bc6ff64c", "Nominal volume VI IA OCR", "https://archive.org/details/parochialplainse06newmuoft"),
    (NEWMAN, "pg-07", "raw/gutenberg/sermons/newman/pg24256.txt", 386616,
     "713da47f79c97a5b188bd50a43a97a9a419d72c5ee92605b1e3d5effcb86b789", "Project Gutenberg volume VII; retained title page says 1891", "https://www.gutenberg.org/ebooks/24256"),
    (NEWMAN, "pg-08", "raw/gutenberg/sermons/newman/pg24284.txt", 406274,
     "b172c4f0379098ac1fdca2fbc27b08fb830c4eea5ce43d39d0263887b7fa3f53", "Project Gutenberg volume VIII; retained title page says 1891", "https://www.gutenberg.org/ebooks/24284"),
)


def _source_rows(root: Path) -> list[dict[str, object]]:
    rows = []
    for wid, label, relative, expected_size, expected_hash, title, url in SOURCES:
        path = resolve_repo_path(root, relative)
        if not path.is_file() or path.stat().st_size != expected_size or sha256_file(path) != expected_hash:
            raise PipelineError(f"retained source missing or changed: {relative}")
        rows.append({"work_id": wid, "label": label, "path": relative, "bytes": expected_size,
                     "sha256": expected_hash, "title": title, "url": url})
    newman_dir = resolve_repo_path(root, "raw/gutenberg/sermons/newman")
    expected_names = {Path(row["path"]).name for row in rows if row["work_id"] == NEWMAN}
    actual_names = {path.name for path in newman_dir.iterdir() if path.is_file()}
    if actual_names != expected_names:
        raise PipelineError(f"Newman retained directory member set differs: {sorted(actual_names ^ expected_names)}")
    return rows


def _credit_document(wid: str, rows: list[dict[str, object]]) -> str:
    if wid == CHADWICK:
        lines = [
            "# Source and credit — G. A. Chadwick",
            "",
            "The retained electronic text sources are these two CCEL ThML XML files:",
            "",
            *(f"- {row['path']} — SHA-256 {row['sha256']}" for row in rows),
            "",
            "Sourced via CCEL.org. The source headers name G. A. Chadwick and",
            "series editor William Robertson Nicoll. The source-local CCEL permission",
            "note requests this attribution convention in the dataset README or card.",
            "",
            "Mark and Exodus are separate books in the older combined catalog identity.",
            "Source accounting does not establish reconstruction, rights, or publication.",
        ]
    else:
        lines = [
            "# Source and credit — Newman, Parochial and Plain Sermons",
            "",
            "The exact retained text sources are six Internet Archive OCR files and two",
            "Project Gutenberg electronic texts:",
            "",
            *(f"- {row['path']} — SHA-256 {row['sha256']}" for row in rows),
            "",
            "The Gutenberg volumes VII and VIII credit Al Haines for preparing the e-text.",
            "They include the Project Gutenberg License; consult the retained files and",
            "https://www.gutenberg.org/license before redistributing Gutenberg material.",
            "The Internet Archive files are uncorrected OCR retained for source work;",
            "they are not approved public text. The nominal volume-II file also includes",
            "volume-I material. The legacy config's unified 1868 edition claim is not adopted.",
            "",
            "This notice records provenance and attribution, not publication clearance.",
        ]
    return "\n".join(lines) + "\n"


def stage(root: Path, destination: Path) -> dict[str, object]:
    root = root.resolve()
    if destination.exists():
        raise PipelineError(f"stage destination already exists: {destination}")
    rows = _source_rows(root)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    proposed: list[tuple[str, dict[str, object] | str, str | None]] = []
    packet = {"contract": CONTRACT, "sources": rows, "before": BEFORE,
              "evidence": ["sources/commentaries/expositors-bible/mark.source-manifest.json",
                           "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-259.md"]}
    packet_rel = "plans/2026-09-22-source-preflight/two-lookup-volume-sidecar-packet-v2-20260926.json"
    packet_path = root / packet_rel
    if packet_path.exists():
        raise PipelineError(f"packet already exists: {packet_path}")
    for wid in (CHADWICK, NEWMAN):
        work_rel = f"library/works/{wid}/work.json"
        state_rel = f"library/works/{wid}/state.json"
        work_path = root / work_rel
        state_path = root / state_rel
        if (sha256_file(work_path), sha256_file(state_path)) != BEFORE[wid]:
            raise PipelineError(f"{wid} work or state changed since lookup review")
        work = load_work(work_path)
        state = load_state(state_path)
        if work["textual_forms"] or state["targets"]:
            raise PipelineError(f"{wid} is no longer identity-only")
        new_work = copy.deepcopy(work)
        new_state = copy.deepcopy(state)
        forms: dict[str, dict[str, object]] = {}
        credit_rel = f"library/works/{wid}/SOURCE_CREDIT.md"
        if resolve_repo_path(root, credit_rel).exists():
            raise PipelineError(f"source credit already exists: {credit_rel}")
        for row in (item for item in rows if item["work_id"] == wid):
            label = str(row["label"])
            source_rel = str(row["path"])
            if wid == CHADWICK:
                form_id = "chadwick-expositors-retained-english"
                provider = "Christian Classics Ethereal Library"
                media_type = "application/xml"
                route = "born-digital"
                warning = "Mark and Exodus are distinct books inside the older combined Chadwick catalog identity; this source-bound electronic edition does not establish a single combined print edition or accepted TEI."
            else:
                is_ia = label.startswith("ia-")
                form_id = "newman-parochial-ia-ocr-english" if is_ia else "newman-parochial-gutenberg-english"
                provider = "Internet Archive" if is_ia else "Project Gutenberg"
                media_type = "text/plain"
                route = "ocr" if is_ia else "born-digital"
                warning = ("Uncorrected Internet Archive OCR is retained evidence only; correction and source-bound review are required before public text release."
                           if is_ia else "Project Gutenberg text is a separate 1891 electronic witness; original print and redistribution rights require review.")
            edition_id = f"{wid}-{label}-retained-electronic"
            acquisition_id = f"{wid}-{label}-acquired"
            edition_dir = f"library/works/{wid}/forms/{form_id}/editions/{edition_id}"
            acq_rel = f"{edition_dir}/acquisitions/{acquisition_id}.json"
            if resolve_repo_path(root, acq_rel).exists():
                raise PipelineError(f"acquisition already exists: {acq_rel}")
            scope = (f"Complete retained electronic file {source_rel}. {row['title']}. "
                     "This records exact source bytes only; volume/sermon selection, print-edition equivalence, correction, TEI acceptance, rights, and publication remain unverified.")
            if label == "ia-02":
                scope += " The file includes volume-I material before its volume-II title page; filename is not a clean volume boundary."
            if wid == NEWMAN:
                scope += " The legacy config's unified 1868 edition claim is not adopted."
            retained = {"path": source_rel, "bytes": row["bytes"], "sha256": row["sha256"],
                        "media_type": media_type, "scope": scope}
            acquisition = {"schema_version": "2.0", "acquisition_id": acquisition_id,
                           "edition_id": edition_id, "provider": provider, "url": row["url"],
                           "route": route, "retained_files": [retained], "source_path": source_rel,
                           "source_bytes": row["bytes"], "source_sha256": row["sha256"],
                           "source_scope": scope, "warnings": [warning]}
            validate_record("acquisition", acquisition, context=acq_rel)
            proposed.append((acq_rel, acquisition, None))
            form = forms.setdefault(form_id, {"textual_form_id": form_id, "language": "en", "editions": []})
            form["editions"].append({"edition_id": edition_id, "title": str(row["title"]),
                                     "language": "en", "acquisition_ids": [acquisition_id]})
            evidence = [packet_rel, source_rel, credit_rel, acq_rel]
            for target_id, kind in ((acquisition_id, "acquisition"), (edition_id, "edition")):
                new_state["targets"].append({"target_id": target_id, "target_type": kind,
                                             "stage": "acquired", "updated_at": now, "evidence": evidence})
            if source_rel not in new_work["evidence"]:
                new_work["evidence"].append(source_rel)
        new_work["textual_forms"] = list(forms.values())
        new_work["evidence"].append(packet_rel)
        new_work["evidence"].append(credit_rel)
        validate_identity_update(work, new_work)
        validate_record("work", new_work, context=wid)
        validate_record("state", new_state, context=wid)
        proposed.extend([(work_rel, new_work, BEFORE[wid][0]), (state_rel, new_state, BEFORE[wid][1])])
        proposed.append((credit_rel, _credit_document(wid, [item for item in rows if item["work_id"] == wid]), None))
    write_json(packet_path, packet)
    _io_path(destination).mkdir(parents=True)
    files = []
    for relative, document, before_hash in proposed:
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(document, str):
            target.write_text(document, encoding="utf-8")
        else:
            write_json(target, document)
        files.append({"path": relative, "before_sha256": before_hash,
                      "proposed_sha256": sha256_file(target)})
    receipt = {"contract": CONTRACT, "packet_path": packet_rel,
               "packet_sha256": sha256_file(packet_path), "sources": len(rows),
               "files": sorted(files, key=lambda item: item["path"])}
    write_json(_io_path(destination / "receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = stage(args.repository_root, args.destination)
    print(json.dumps({"destination": str(args.destination), "sources": result["sources"],
                      "files": len(result["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
