"""Prepare three same-header illustrated DocSouth continuation candidates."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from build.tei import docsouth_tei2_illustrated as source
from build.tei.docsouth_tei2_illustrated_oracle import check
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "ocd-docsouth-tei2-illustrated-continuation-direct-v1"
SELECTIONS = {
    "henry-mcneal-turner-african-letters",
    "lucius-henry-holsey-autobiography-sermons-addresses-essays",
    "william-h-heard-from-slavery-to-bishopric",
}


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def prepare(destination: Path) -> dict:
    destination = destination.absolute()
    if _io_path(destination).exists() or not _io_path(destination.parent).is_dir() or ROOT in destination.parents:
        raise ValueError("fresh external DocSouth direct destination required")
    inventory = json.loads(_io_path(source.INVENTORY).read_bytes())
    if _sha(_io_path(source.INVENTORY).read_bytes()) != source.INVENTORY_SHA:
        raise ValueError("DocSouth exact source inventory changed")
    entries = {item["work_id"]: item for item in inventory["works"]}
    if not SELECTIONS <= entries.keys():
        raise ValueError("DocSouth nested-quote work is absent from fixed inventory")
    prepared = []
    for work_id in sorted(SELECTIONS):
        entry = entries[work_id]
        work_bytes = _io_path(ROOT / entry["work_path"]).read_bytes()
        if _sha(work_bytes) != entry["work_sha256"] or entry["accepted_master_present"]:
            raise ValueError(f"DocSouth current work preimage changed: {work_id}")
        work = json.loads(work_bytes)
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        acquisition_path = (Path("library/works") / work_id / "forms" / form["textual_form_id"]
                            / "editions" / edition["edition_id"] / "acquisitions"
                            / (edition["acquisition_ids"][0] + ".json"))
        acquisition_bytes = _io_path(ROOT / acquisition_path).read_bytes()
        acquisition = json.loads(acquisition_bytes)
        if (acquisition.get("source_path") != entry["source_path"]
                or acquisition.get("source_sha256") != entry["source_sha256"]
                or acquisition.get("source_bytes") != entry["source_bytes"]
                or len(acquisition.get("retained_files", [])) != entry["element_counts"]["figure"] + 1
                or acquisition["retained_files"][0]["path"] != entry["source_path"]
                or acquisition["retained_files"][0]["sha256"] != entry["source_sha256"]):
            raise ValueError(f"DocSouth acquisition does not bind exact XML: {work_id}")
        content, producer = source.convert(work_id, selections=SELECTIONS)
        oracle = check(ROOT / entry["source_path"], entry["source_sha256"], content,
                       ROOT / entry["acquisition_receipt_path"])
        if (producer["candidate_sha256"] != oracle["candidate_sha256"]
                or producer["source_rights_text_sha256"] != oracle["electronic_rights_text_sha256"]
                or producer["source_body_text_sha256"] != oracle["body_text_sha256"]):
            raise ValueError(f"DocSouth converter and independent oracle disagree: {work_id}")
        prepared.append((work_id, entry, work, acquisition_path, acquisition_bytes, content, producer, oracle))
    _io_path(destination).mkdir(parents=True)
    results = []
    for work_id, entry, work, acquisition_path, acquisition_bytes, content, producer, oracle in prepared:
        candidate_path = destination / work_id / "candidate.tei.xml"
        _io_path(candidate_path).parent.mkdir(parents=True)
        _io_path(candidate_path).write_bytes(content)
        if errors := validate_file(_io_path(candidate_path)):
            raise ValueError(f"DocSouth P5 XSD failed for {work_id}: {errors[:3]}")
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = dict(work_id=work_id, textual_form_id=form["textual_form_id"], edition_id=edition["edition_id"])
        revision = work_id + "-docsouth-tei2-v1"
        projected = project_document(_io_path(candidate_path), identity=identity, language="en",
                                     representation_revision=revision, edition_title=edition["title"],
                                     _allow_acceptance_metadata=True, category="prose")
        errors = verify_document(_io_path(candidate_path), projected["rows"], projected["receipt"],
                                 identity=identity, language="en", representation_revision=revision,
                                 edition_title=edition["title"], _allow_acceptance_metadata=True,
                                 category="prose")
        if errors or not projected["rows"]:
            raise ValueError(f"DocSouth native prose verification failed for {work_id}: {errors[:3]}")
        results.append(dict(work_id=work_id, work_path=entry["work_path"], work_sha256=entry["work_sha256"],
                            state_path=entry["state_path"], state_sha256=entry["state_sha256"],
                            acquisition_path=acquisition_path.as_posix(), acquisition_sha256=_sha(acquisition_bytes),
                            acquisition_receipt_path=entry["acquisition_receipt_path"],
                            acquisition_receipt_sha256=_sha(_io_path(ROOT / entry["acquisition_receipt_path"]).read_bytes()),
                            source_path=entry["source_path"], source_sha256=entry["source_sha256"],
                            source_bytes=entry["source_bytes"], candidate_path=candidate_path.as_posix(),
                            candidate_sha256=_sha(content), producer=producer, oracle=oracle,
                            category="prose", language="en", tei_xsd="pass",
                            native_projection_rows=len(projected["rows"]), native_verify="pass"))
    receipt = dict(contract=CONTRACT, status="nonaccepted", source_inventory=source.INVENTORY.relative_to(ROOT).as_posix(),
                   source_inventory_sha256=source.INVENTORY_SHA, selected_works=results,
                   excluded_work_count=27 - len(results), excluded_work_policy="outside the three-work same-header illustrated continuation; no source material extracted",
                   canonical_install="not-performed")
    _io_path(destination / "receipt.json").write_bytes(_json(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    result = prepare(parser.parse_args().destination)
    print(json.dumps(dict(works=len(result["selected_works"]), status=result["status"]), sort_keys=True))


if __name__ == "__main__":
    main()
