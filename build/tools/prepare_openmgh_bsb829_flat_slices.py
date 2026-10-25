"""Reconstruct ten projection-closed line-bounded bsb829 letters."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.openmgh_bsb829_flat_slices_oracle import check as oracle_check
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000829/tei/bsb00000829.xml")
SOURCE_SHA = "cb35385e4e4ba87f80a002452a527527866322af7ccea7f23f366735e46df989"
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb829-inspected-batch-20260926.json")
BATCH_SHA = "6623a27ea9998fbd9fad1379eafa3fc6b58d887ad00b8b42b92f5441e86cf947"
RECEIPT = Path("raw/openmgh/bsb00000829/acquisition-receipt.json")
RECEIPT_SHA = "61fdd88b8536cdda2338f9f2e684188c0eae00c0ed8eb827c3187c0b3cdb4f4c"
SIDE_HOME = Path("sources/openmgh-bsb829-flat-slices")
PLAN = SIDE_HOME / "stage-plan.json"
PLAN_SHA = "d059fcb476c7de305242f8118db97c513475b20a64d07a34a533e003c4bf62d0"
REVIEW_PLAN = SIDE_HOME / "selection-plan.json"
REVIEW_PLAN_SHA = "463ace336a34fad8842f5eb96a7ad48e4860103623e87dd30f894b2f87e0f4d8"
PROBE = Path("plans/2026-09-22-source-preflight/openmgh-bsb829-flat-projection-probe-20260926.json")
PROBE_SHA = "79d55323c4c324f3e51d32a21b0e18f97474c1208539fa3d4ffa773dd80070fd"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_once(path: Path, content: bytes) -> None:
    target = Path(_io_path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError(f"existing evidence differs: {path}")
        return
    target.write_bytes(content)


def _declared(work: dict) -> list[str]:
    editions = [edition for form in work["textual_forms"] for edition in form["editions"]]
    if len(editions) != 1:
        raise ValueError(f"work edition is ambiguous: {work['work_id']}")
    values = editions[0]["containing_source"]["locator"].split("; ")
    if not 2 <= len(values) <= 4 or any(not value.startswith(SOURCE.as_posix() + "#")
                                             for value in values):
        raise ValueError(f"declared source locators changed: {work['work_id']}")
    return [value.split("#", 1)[1] for value in values]


def _source() -> tuple[bytes, etree._Element, list[etree._Element], dict]:
    for path, expected in ((SOURCE, SOURCE_SHA), (BATCH, BATCH_SHA),
                           (RECEIPT, RECEIPT_SHA), (PLAN, PLAN_SHA),
                           (REVIEW_PLAN, REVIEW_PLAN_SHA), (PROBE, PROBE_SHA)):
        if _sha(ROOT / path) != expected:
            raise ValueError(f"frozen source, plan, or receipt changed: {path}")
    content = Path(_io_path(ROOT / SOURCE)).read_bytes()
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_comments=False, huge_tree=True)
    root = etree.fromstring(content, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("source DOCTYPE is forbidden")
    body = root.find(f"{TEI}text/{TEI}body")
    if body is None or len(body) != 1 or body[0].get("type") != "volume":
        raise ValueError("source volume envelope changed")
    divisions = list(body[0])
    if (len(divisions) != 21 or any(len(divisions[index - 1]) != 1
                                   or divisions[index - 1][0].tag != f"{TEI}ab"
                                   for index in (6, 15))):
        raise ValueError("source flat-division envelope changed")
    plan = json.loads(Path(_io_path(ROOT / PLAN)).read_bytes())
    if (plan.get("contract") != "ocd-openmgh-bsb829-flat-slices-stage-plan-v1"
            or plan.get("source_sha256") != SOURCE_SHA
            or plan.get("frozen_batch_sha256") != BATCH_SHA
            or plan.get("review_plan_sha256") != REVIEW_PLAN_SHA
            or plan.get("projection_probe_sha256") != PROBE_SHA
            or len(plan.get("works", [])) != 10 or len(plan.get("held", [])) != 2):
        raise ValueError("flat selection plan changed")
    return content, root, divisions, plan


def _slice(divisions: list[etree._Element], entry: dict) -> tuple[etree._Element, int, int]:
    ordinal = entry["division"]
    if ordinal not in (6, 15):
        raise ValueError("flat selection is outside the reviewed divisions")
    div = divisions[ordinal - 1]
    if len(div) != 1 or div[0].tag != f"{TEI}ab":
        raise ValueError("flat source container changed")
    ab = div[0]
    children = list(ab)
    positions = {}
    for index, child in enumerate(children):
        identifier = child.get(XML_ID)
        if identifier:
            if identifier in positions:
                raise ValueError(f"repeated source locator: {identifier}")
            positions[identifier] = index
    first, last = entry["first_id"], entry["last_id"]
    if first not in positions or last not in positions:
        raise ValueError("flat endpoint missing")
    start, end = positions[first], positions[last]
    if start > end or children[start].tag != f"{TEI}lb" or children[end].tag != f"{TEI}lb":
        raise ValueError("flat span endpoints are not ordered line breaks")
    selected = etree.Element(f"{TEI}ab", attrib=dict(ab.attrib))
    for child in children[start:end + 1]:
        selected.append(deepcopy(child))
    if (selected.text or not len(selected)
            or selected[0].get(XML_ID) != first
            or selected[-1].get(XML_ID) != last):
        raise ValueError("flat source slice changed")
    return selected, start, end


def _candidate(root: etree._Element, selected: etree._Element, work: dict) -> bytes:
    output = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    output.set(XML_ID, f"ocd-{work['work_id']}-bsb829-flat-slices-electronic-v1")
    file_desc = etree.SubElement(etree.SubElement(output, f"{TEI}teiHeader"), f"{TEI}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{TEI}titleStmt")
    etree.SubElement(title_stmt, f"{TEI}title").text = work["title"]
    original = root.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original is None:
        raise ValueError("source header missing")
    publication = original.find(f"{TEI}publicationStmt")
    bibliography = original.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError("source license or bibliography missing")
    file_desc.append(deepcopy(publication))
    etree.SubElement(file_desc, f"{TEI}sourceDesc").append(deepcopy(bibliography))
    body = etree.SubElement(etree.SubElement(output, f"{TEI}text"), f"{TEI}body")
    etree.SubElement(body, f"{TEI}div", type="work", n=work["title"]).append(deepcopy(selected))
    return etree.tostring(output, encoding="UTF-8", xml_declaration=True)


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("contract") != "ocd-openmgh-bsb829-flat-slices-profile-v1":
        raise ValueError("flat profile changed")
    source = source_manifest.authority_path("extracted-xml").read_bytes()
    root = etree.fromstring(source, etree.XMLParser(resolve_entities=False, no_network=True,
                                                     huge_tree=True))
    divisions = list(root.find(f"{TEI}text/{TEI}body")[0])
    entry = {key: profile[key] for key in ("division", "first_id", "last_id")}
    selected, start, end = _slice(divisions, entry)
    if (start != profile["first_child_index"] or end != profile["last_child_index"]
            or sha256(etree.tostring(selected, method="c14n", with_comments=True)).hexdigest()
               != profile["selection_c14n_sha256"]):
        raise ValueError("source span or profile changed")
    work = json.loads(source_manifest.authority_path("work-sidecar").read_bytes())
    if work.get("work_id") != profile["work_id"] or _declared(work) != profile["declared_locator_ids"]:
        raise ValueError("work or declared locators changed")
    candidate = _candidate(root, selected, work)
    accountability = {key: profile[key] for key in (
        "work_id", "edition_id", "acquisition_id", "source_path", "source_sha256",
        "division", "first_id", "last_id", "first_child_index", "last_child_index",
        "declared_locator_ids", "scope_note", "selection_c14n_sha256",
        "shared_matter_disposition", "unassigned_fragment_disposition")}
    accountability["contract"] = "ocd-openmgh-bsb829-flat-slices-accounting-v1"
    accountability["selection_plan_sha256"] = profile["selection_plan_sha256"]
    accountability["review_plan_sha256"] = profile["review_plan_sha256"]
    accountability["projection_probe_sha256"] = profile["projection_probe_sha256"]
    accountability["zip_disposition"] = "Retained acquisition package only; not text authority."
    provenance = {"contract": "ocd-openmgh-bsb829-flat-slices-provenance-v1",
                  "status": "nonaccepted", "work_id": profile["work_id"],
                  "edition_id": profile["edition_id"], "acquisition_id": profile["acquisition_id"],
                  "source_path": profile["source_path"], "source_sha256": profile["source_sha256"],
                  "canonical_ir_written": False, "publication": "not-ready"}
    unresolved = [{"status": "unresolved", "item": "Close visual comparison and print collation are not performed."},
                  {"status": "unresolved", "item": "Human acceptance, rights clearance, and publication are separate."}]
    readme = (f"# {profile['work_title']} — openMGH bsb829 line-bounded candidate\n\n"
              f"Text source: {profile['source_path']} (SHA-256 {profile['source_sha256']}).\n"
              f"Division {profile['division']}, exact lines {profile['first_id']}–{profile['last_id']}. "
              f"{profile['scope_note']}\n"
              "The electronic publication statement and print bibliography are retained. "
              "Monumenta Germaniae Historica and the Bavarian State Library request derivative attribution. "
              "Rights and publication decisions remain separate.\n").encode()
    return {"content.tei.xml": candidate, "source-accountability.json": _json(accountability),
            "provenance.json": _json(provenance),
            "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
            "README.source.md": readme}


_convert.converter_id = "ocd-openmgh-bsb829-flat-slices-to-tei"
_convert.converter_version = "1"


def prepare(destination: Path) -> dict:
    destination = destination.resolve()
    if ROOT == destination or ROOT in destination.parents:
        raise ValueError("candidate destination must be external")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("candidate destination must be fresh")
    source, root, divisions, plan = _source()
    batch = json.loads(Path(_io_path(ROOT / BATCH)).read_bytes())
    entries = sorted(plan["works"], key=lambda item: item["work_id"])
    if (len({entry["work_id"] for entry in entries}) != 10
            or {entry["division"] for entry in entries} != {6, 15}
            or sum(entry["division"] == 6 for entry in entries) != 7):
        raise ValueError("reviewed flat selection inventory changed")
    selections = []
    for entry in entries:
        work_id = entry["work_id"]
        if work_id not in batch["holds"]:
            raise ValueError(f"work is not a frozen hold: {work_id}")
        work_path = ROOT / "library/works" / work_id / "work.json"
        work = json.loads(Path(_io_path(work_path)).read_bytes())
        declared = _declared(work)
        if entry["first_id"] not in declared or entry["last_id"] not in declared:
            raise ValueError(f"selected endpoints absent from declared locators: {work_id}")
        selected, start, end = _slice(divisions, entry)
        selections.append((entry, work, work_path, declared, selected, start, end))
    for i, left in enumerate(selections):
        for right in selections[i + 1:]:
            if left[0]["division"] == right[0]["division"] and max(left[5], right[5]) <= min(left[6], right[6]):
                raise ValueError("two flat work selections overlap")
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    for entry, work, work_path, declared, selected, start, end in selections:
        work_id = entry["work_id"]
        candidate = _candidate(root, selected, work)
        oracle = oracle_check(source, candidate, division=entry["division"],
                              first_id=entry["first_id"], last_id=entry["last_id"])
        path = destination / work_id / "candidate.tei.xml"
        _write_once(path, candidate)
        if errors := validate_file(Path(_io_path(path))):
            raise ValueError(f"TEI P5 XSD failed: {work_id} {errors[:3]}")
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                    "edition_id": edition["edition_id"]}
        revision = f"{work_id}-bsb829-flat-slices-v1"
        projection = project_document(path, identity=identity, language="la",
                                      representation_revision=revision,
                                      edition_title=edition["title"],
                                      _allow_acceptance_metadata=True, category="prose")
        errors = verify_document(path, projection["rows"], projection["receipt"],
                                 identity=identity, language="la", representation_revision=revision,
                                 edition_title=edition["title"], _allow_acceptance_metadata=True,
                                 category="prose")
        if errors or len(projection["rows"]) != 1:
            raise ValueError(f"native prose projection failed: {work_id} {errors[:3]}")
        shared = ("The Gesta collection heading and separately numbered III, VIII, and XI sections remain in the retained XML."
                  if entry["division"] == 6 else
                  "The Bruno letter collection heading and three sibling letters remain in the retained XML.")
        boundary = {"contract": "ocd-openmgh-bsb829-flat-slices-boundary-v1",
                    "work_id": work_id, "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
                    "division": entry["division"], "native_type": "line-span",
                    "first_id": entry["first_id"], "last_id": entry["last_id"],
                    "first_child_index": start, "last_child_index": end,
                    "declared_locator_ids": declared, "scope_note": entry["scope_note"],
                    "selection_c14n_sha256": oracle["selection_c14n_sha256"],
                    "shared_matter_disposition": shared,
                    "unassigned_fragment_disposition": "The unfinished division-18 text and separately titled division-19 response remain outside this letter and held.",
                    "opening": " ".join(" ".join(selected.itertext()).split())[:120],
                    "closing": " ".join(" ".join(selected.itertext()).split())[-120:]}
        sidecar = ROOT / SIDE_HOME / work_id / "boundary-review.json"
        _write_once(sidecar, _json(boundary))
        rows.append({"work_id": work_id, "work_sidecar_path": work_path.relative_to(ROOT).as_posix(),
                     "work_sidecar_sha256": _sha(work_path),
                     "boundary_path": sidecar.relative_to(ROOT).as_posix(),
                     "boundary_sha256": _sha(sidecar), "candidate_path": path.as_posix(),
                     "candidate_sha256": sha256(candidate).hexdigest(), "oracle": oracle,
                     "xsd_status": "pass", "native_prose_projection_rows": 1,
                     "native_prose_independent_check": "pass", "division": entry["division"],
                     "first_id": entry["first_id"], "last_id": entry["last_id"]})
    receipt = {"contract": "ocd-openmgh-bsb829-flat-slices-candidates-v1",
               "status": "nonaccepted", "source_path": SOURCE.as_posix(),
               "source_sha256": SOURCE_SHA, "frozen_inspection_receipt": BATCH.as_posix(),
               "frozen_inspection_receipt_sha256": BATCH_SHA,
               "acquisition_receipt": RECEIPT.as_posix(),
               "acquisition_receipt_sha256": RECEIPT_SHA,
               "selection_plan": PLAN.as_posix(), "selection_plan_sha256": PLAN_SHA,
               "review_plan_sha256": REVIEW_PLAN_SHA,
               "projection_probe_sha256": PROBE_SHA,
               "held_source_word_links": plan["held"],
               "candidates": rows, "acceptance_stage": "not-prepared",
               "canonical_install": "not-performed"}
    _write_once(destination / "receipt.json", _json(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.destination)
    print(json.dumps({"candidate_count": len(result["candidates"]),
                      "receipt": str(args.destination / "receipt.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
