"""Prepare nonaccepted TEI candidates from a pinned openMGH work-div manifest."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.openmgh_exact_work_div import TEI, XML_ID, check_candidate, parse_tei
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "ocd-openmgh-exact-work-div-direct-candidates-v1"


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _manifest(path: Path, root: Path) -> dict:
    manifest = _read(path)
    if (manifest.get("contract") != "ocd-openmgh-exact-work-div-batch-v1"
            or manifest.get("status") != "source-scoped-nonaccepted"
            or manifest.get("canonical_install") != "not-performed"):
        raise ValueError("unrecognized exact-source batch manifest")
    for field in ("source", "package", "acquisition_receipt", "source_inventory"):
        item = manifest[field]
        if _sha(root / item["path"]) != item["sha256"]:
            raise ValueError(f"pinned {field} changed")
    source_path = manifest["source"]["path"]
    if not (source_path.startswith("raw/openmgh/") and source_path.endswith(".xml")):
        raise ValueError("extracted XML source required")
    if not manifest["package"]["path"].endswith(".zip"):
        raise ValueError("original ZIP package required")
    return manifest


def _work(root: Path, entry: dict, manifest: dict) -> tuple[dict, dict]:
    work_path = root / entry["work_path"]
    acquired_path = root / entry["acquisition_path"]
    if _sha(work_path) != entry["work_sha256"] or _sha(acquired_path) != entry["acquisition_sha256"]:
        raise ValueError(f"work or acquisition preimage changed: {entry['work_id']}")
    work, acquisition = _read(work_path), _read(acquired_path)
    if work.get("work_id") != entry["work_id"] or len(work.get("textual_forms", [])) != 1:
        raise ValueError("work identity changed or ambiguous")
    form = work["textual_forms"][0]
    if len(form.get("editions", [])) != 1:
        raise ValueError("edition identity ambiguous")
    edition = form["editions"][0]
    if len(edition.get("acquisition_ids", [])) != 1:
        raise ValueError("acquisition identity ambiguous")
    retained = acquisition.get("retained_files", [])
    if (acquisition.get("source_path") != manifest["source"]["path"]
            or acquisition.get("source_sha256") != manifest["source"]["sha256"]
            or len(retained) != 2
            or [item.get("path") for item in retained]
               != [manifest["package"]["path"], manifest["source"]["path"]]):
        raise ValueError("source/package authority changed")
    return work, acquisition


def _candidate(source: etree._Element, manifest: dict, entry: dict, work: dict) -> bytes:
    ns = {"t": TEI[1:-1]}
    volumes = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != manifest["source"]["volume_child_count"]:
        raise ValueError("source volume changed")
    index = entry["source_work_div_index"]
    selected = list(volumes[0])[index]
    if (selected.tag != f"{TEI}div" or selected.get("type") != "work"
            or selected.get("n") != entry["source_work_div_n"]):
        raise ValueError("literal source work div changed")
    result = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    result.set(XML_ID, f"ocd-{work['work_id']}-openmgh-electronic-v1")
    file_desc = etree.SubElement(etree.SubElement(result, f"{TEI}teiHeader"), f"{TEI}fileDesc")
    etree.SubElement(etree.SubElement(file_desc, f"{TEI}titleStmt"), f"{TEI}title").text = work["title"]
    original = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original is None:
        raise ValueError("source header absent")
    publication = original.find(f"{TEI}publicationStmt")
    bibliography = original.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError("source rights or bibliography absent")
    file_desc.append(deepcopy(publication))
    etree.SubElement(file_desc, f"{TEI}sourceDesc").append(deepcopy(bibliography))
    etree.SubElement(etree.SubElement(result, f"{TEI}text"), f"{TEI}body").append(deepcopy(selected))
    return etree.tostring(result, encoding="UTF-8", xml_declaration=True)


def prepare(manifest_path: Path, destination: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    manifest_path = manifest_path.resolve(strict=True)
    destination = destination.absolute()
    if (root == destination or root in destination.parents
            or Path(_io_path(destination)).exists()):
        raise ValueError("fresh external destination required")
    manifest = _manifest(manifest_path, root)
    source_bytes = Path(_io_path(root / manifest["source"]["path"])).read_bytes()
    source = parse_tei(source_bytes)
    prepared = []
    for entry in manifest["works"]:
        work, acquisition = _work(root, entry, manifest)
        candidate = _candidate(source, manifest, entry, work)
        checked = check_candidate(source_bytes, candidate, manifest, entry, work, acquisition)
        prepared.append((entry, work, candidate, checked))
    Path(_io_path(destination)).mkdir(parents=True)
    results = []
    for entry, work, candidate, checked in prepared:
        candidate_path = destination / entry["work_id"] / "candidate.tei.xml"
        target = Path(_io_path(candidate_path))
        target.parent.mkdir(parents=True)
        target.write_bytes(candidate)
        if errors := validate_file(candidate_path):
            raise ValueError(f"TEI P5 XSD failed for {entry['work_id']}: {errors[:3]}")
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = {"work_id": entry["work_id"], "textual_form_id": form["textual_form_id"],
                    "edition_id": edition["edition_id"]}
        revision = f"{entry['work_id']}-openmgh-exact-work-div-v1"
        projection = project_document(candidate_path, identity=identity,
                                      language=entry["language"],
                                      representation_revision=revision,
                                      edition_title=edition["title"],
                                      _allow_acceptance_metadata=True,
                                      category=entry["category"])
        errors = verify_document(candidate_path, projection["rows"], projection["receipt"],
                                 identity=identity, language=entry["language"],
                                 representation_revision=revision,
                                 edition_title=edition["title"],
                                 _allow_acceptance_metadata=True,
                                 category=entry["category"])
        if errors or len(projection["rows"]) != 1:
            raise ValueError(f"native projection failed for {entry['work_id']}: {errors[:3]}")
        results.append({"work_id": entry["work_id"],
                        "source_work_div_index": entry["source_work_div_index"],
                        "candidate_path": candidate_path.as_posix(),
                        "candidate_sha256": sha256(candidate).hexdigest(),
                        "work_path": entry["work_path"], "work_sha256": entry["work_sha256"],
                        "acquisition_path": entry["acquisition_path"],
                        "acquisition_sha256": entry["acquisition_sha256"],
                        "independent_oracle": checked, "tei_xsd": "pass",
                        "native_projection_rows": 1, "native_projection_verify": "pass"})
    receipt = {"contract": CONTRACT, "status": "nonaccepted",
               "manifest_path": manifest_path.as_posix(),
               "manifest_sha256": _sha(manifest_path),
               "source": manifest["source"], "package": manifest["package"],
               "acquisition_receipt": manifest["acquisition_receipt"],
               "source_scope": "Every selected complete source work div, with all internal nodes and original order preserved.",
               "works": results, "canonical_install": "not-performed"}
    Path(_io_path(destination / "receipt.json")).write_bytes(_json(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    receipt = prepare(args.manifest, args.destination, root=args.root)
    print(json.dumps({"receipt": str(args.destination / "receipt.json"),
                      "works": len(receipt["works"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
