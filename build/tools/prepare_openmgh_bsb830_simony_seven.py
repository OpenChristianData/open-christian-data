"""Prepare seven source-partitioned bsb830 poetry candidates outside checkout."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from build.tei import openmgh_bsb830_simony_seven as source
from build.tei.openmgh_bsb830_simony_seven_oracle import check
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "ocd-openmgh-bsb830-simony-seven-direct-v1"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def prepare(destination: Path) -> dict:
    destination = destination.absolute()
    if _io_path(destination).exists() or not _io_path(destination.parent).is_dir() or ROOT in destination.parents:
        raise ValueError("fresh external bsb830 simony candidate destination required")
    source_bytes = _io_path(ROOT / source.SOURCE).read_bytes()
    if (_sha(source_bytes) != source.SOURCE_SHA
            or _sha(_io_path(ROOT / source.PACKAGE).read_bytes()) != source.PACKAGE_SHA
            or _sha(_io_path(ROOT / source.ACQUISITION_RECEIPT).read_bytes()) != source.ACQUISITION_RECEIPT_SHA):
        raise ValueError("bsb830 source/package/receipt changed")
    prepared = []
    for work_id in source.SELECTED:
        work = Path("library/works") / work_id
        work_path, state_path = ROOT / work / "work.json", ROOT / work / "state.json"
        work_bytes = _io_path(work_path).read_bytes()
        state_bytes = _io_path(state_path).read_bytes()
        work_data = json.loads(work_bytes)
        form = work_data["textual_forms"][0]
        edition = form["editions"][0]
        acquisition = work / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"] / "acquisitions" / (edition["acquisition_ids"][0] + ".json")
        acquisition_bytes = _io_path(ROOT / acquisition).read_bytes()
        acquisition_data = json.loads(acquisition_bytes)
        retained = {item["path"]: item["sha256"] for item in acquisition_data["retained_files"]}
        if (acquisition_data["source_path"] != source.SOURCE.as_posix()
                or acquisition_data["source_sha256"] != source.SOURCE_SHA
                or retained != {source.SOURCE.as_posix(): source.SOURCE_SHA,
                                source.PACKAGE.as_posix(): source.PACKAGE_SHA}):
            raise ValueError(f"bsb830 acquisition authority changed: {work_id}")
        content, producer = source.convert(work_id)
        oracle = check(work_id, content)
        if (producer["candidate_sha256"] != oracle["candidate_sha256"]
                or producer["selected_c14n_sha256"] != oracle["selection_c14n_sha256"]):
            raise ValueError(f"bsb830 source producer and oracle disagree: {work_id}")
        prepared.append((work_id, work, work_bytes, state_bytes, acquisition, acquisition_bytes,
                         work_data, content, producer, oracle))
    _io_path(destination).mkdir(parents=True)
    rows = []
    for (work_id, work, work_bytes, state_bytes, acquisition, acquisition_bytes,
         work_data, content, producer, oracle) in prepared:
        candidate = destination / work_id / "candidate.tei.xml"
        _io_path(candidate).parent.mkdir(parents=True)
        _io_path(candidate).write_bytes(content)
        if errors := validate_file(_io_path(candidate)):
            raise ValueError(f"bsb830 simony P5 XSD failed: {work_id}: {errors[:3]}")
        form = work_data["textual_forms"][0]
        edition = form["editions"][0]
        identity = dict(work_id=work_id, textual_form_id=form["textual_form_id"], edition_id=edition["edition_id"])
        revision = work_id + "-openmgh-bsb830-v1"
        projected = project_document(_io_path(candidate), identity=identity, language="la",
                                     representation_revision=revision, edition_title=edition["title"],
                                     _allow_acceptance_metadata=True, category="poetry")
        errors = verify_document(_io_path(candidate), projected["rows"], projected["receipt"],
                                 identity=identity, language="la", representation_revision=revision,
                                 edition_title=edition["title"], _allow_acceptance_metadata=True,
                                 category="poetry")
        if errors or len(projected["rows"]) != 1:
            raise ValueError(f"bsb830 simony native poetry failed: {work_id}: {errors[:3]}")
        rows.append(dict(work_id=work_id, work_path=(work / "work.json").as_posix(),
                         work_sha256=_sha(work_bytes), state_path=(work / "state.json").as_posix(),
                         state_sha256=_sha(state_bytes), acquisition_path=acquisition.as_posix(),
                         acquisition_sha256=_sha(acquisition_bytes),
                         acquisition_receipt_path=source.ACQUISITION_RECEIPT.as_posix(),
                         acquisition_receipt_sha256=source.ACQUISITION_RECEIPT_SHA,
                         source_path=source.SOURCE.as_posix(), source_sha256=source.SOURCE_SHA,
                         source_bytes=len(source_bytes), package_path=source.PACKAGE.as_posix(),
                         package_sha256=source.PACKAGE_SHA, candidate_path=candidate.as_posix(),
                         candidate_sha256=_sha(content), producer=producer, oracle=oracle,
                         category="poetry", language="la", tei_xsd="pass", native_projection_rows=1,
                         native_verify="pass"))
    result = dict(contract=CONTRACT, status="nonaccepted", source_path=source.SOURCE.as_posix(),
                  source_sha256=source.SOURCE_SHA, package_path=source.PACKAGE.as_posix(),
                  package_sha256=source.PACKAGE_SHA,
                  package_disposition="acquisition package only; extracted XML is text authority",
                  source_division_ordinal=25, source_division_child_count=480,
                  shared_heading_child_indexes=[0, 1, 2, 3],
                  selected_work_count=7, selected_child_range=[4, 479],
                  selected_works=rows, canonical_install="not-performed")
    _io_path(destination / "receipt.json").write_bytes(_json(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    result = prepare(parser.parse_args().destination)
    print(json.dumps(dict(works=len(result["selected_works"]), status=result["status"]), sort_keys=True))


if __name__ == "__main__":
    main()
