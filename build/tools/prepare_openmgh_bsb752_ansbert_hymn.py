"""Prepare one exact, nonaccepted Ansbert hymn candidate from extracted bsb752 XML."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from build.tei.openmgh_bsb752_ansbert_hymn_oracle import check
from build.tools import prepare_openmgh_bsb752_nested as source
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "ymnus-de-sancto-ansberto"
CONTRACT = "ocd-openmgh-bsb752-ansbert-hymn-direct-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def prepare(destination: Path) -> dict:
    destination = destination.absolute()
    if _io_path(destination).exists() or not _io_path(destination.parent).is_dir() or ROOT in destination.parents:
        raise ValueError("fresh external Ansbert direct-candidate root required")
    source_bytes, source_tree, source_works = source._source()
    work_path = Path("library/works") / WORK_ID / "work.json"
    work = json.loads(_io_path(ROOT / work_path).read_bytes())
    forms = work.get("textual_forms", [])
    if len(forms) != 1 or len(forms[0].get("editions", [])) != 1:
        raise ValueError("Ansbert work/form/edition identity ambiguous")
    form, edition = forms[0], forms[0]["editions"][0]
    if len(edition.get("acquisition_ids", [])) != 1:
        raise ValueError("Ansbert acquisition identity ambiguous")
    acquisition_path = (work_path.parent / "forms" / form["textual_form_id"] / "editions" /
                        edition["edition_id"] / "acquisitions" /
                        f"{edition['acquisition_ids'][0]}.json")
    acquisition = json.loads(_io_path(ROOT / acquisition_path).read_bytes())
    retained = acquisition.get("retained_files", [])
    if (acquisition.get("source_path") != source.SOURCE.as_posix()
            or acquisition.get("source_sha256") != source.SOURCE_SHA
            or len(retained) != 2
            or {file["path"] for file in retained} != {source.SOURCE.as_posix(), source.PACKAGE.as_posix()}):
        raise ValueError("Ansbert acquisition XML/package binding differs")
    state = json.loads(_io_path(ROOT / work_path.parent / "state.json").read_bytes())
    if len([target for target in state["targets"] if target["target_type"] == "edition"
            and target["target_id"] == edition["edition_id"] and target["stage"] == "acquired"]) != 1:
        raise ValueError("Ansbert edition is not uniquely acquired")
    if _io_path(ROOT / work_path.parent / "forms" / form["textual_form_id"] / "editions" /
                edition["edition_id"] / "master.tei.xml").exists():
        raise ValueError("Ansbert master already exists")
    candidate = source._candidate(source_tree, [source_works[19][2]], work)
    oracle = check(source_bytes, candidate, work, acquisition)
    _io_path(destination).mkdir(parents=True)
    candidate_path = destination / "candidate.tei.xml"
    _io_path(candidate_path).write_bytes(candidate)
    if errors := validate_file(_io_path(candidate_path)):
        raise ValueError(f"Ansbert candidate TEI P5 failed: {errors[:3]}")
    identity = {"work_id": WORK_ID, "textual_form_id": form["textual_form_id"],
                "edition_id": edition["edition_id"]}
    revision = f"{WORK_ID}-bsb752-hymn-v1"
    projected = project_document(_io_path(candidate_path), identity=identity, language="la",
                                 representation_revision=revision, edition_title=edition["title"],
                                 _allow_acceptance_metadata=True, category="poetry")
    errors = verify_document(_io_path(candidate_path), projected["rows"], projected["receipt"],
                             identity=identity, language="la", representation_revision=revision,
                             edition_title=edition["title"], _allow_acceptance_metadata=True,
                             category="poetry")
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"Ansbert native poetry projection failed: {errors[:3]}")
    receipt = {
        "contract": CONTRACT, "status": "nonaccepted", "work_id": WORK_ID,
        "source_path": source.SOURCE.as_posix(), "source_sha256": source.SOURCE_SHA,
        "package_path": source.PACKAGE.as_posix(), "package_sha256": source.PACKAGE_SHA,
        "acquisition_receipt_path": source.ACQUISITION_RECEIPT.as_posix(),
        "acquisition_receipt_sha256": source.ACQUISITION_RECEIPT_SHA,
        "work_path": work_path.as_posix(), "work_sha256": _sha(ROOT / work_path),
        "acquisition_path": acquisition_path.as_posix(),
        "acquisition_sha256": _sha(ROOT / acquisition_path),
        "candidate_path": candidate_path.as_posix(),
        "candidate_sha256": sha256(candidate).hexdigest(), "oracle": oracle,
        "tei_xsd": "pass", "native_poetry_rows": 1, "native_verify": "pass",
        "excluded_carrier_parts": [0, 1], "canonical_install": "not-performed",
    }
    _io_path(destination / "receipt.json").write_bytes(source._json(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    result = prepare(parser.parse_args().destination)
    print(json.dumps({"work_id": WORK_ID, "candidate_sha256": result["candidate_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
