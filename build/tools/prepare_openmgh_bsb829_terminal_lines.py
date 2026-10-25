"""Prepare two source-complete bsb829 terminal-line candidates without installation."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.openmgh_bsb829_terminal_lines_oracle import check
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
PRIOR_PLAN = Path("sources/openmgh-bsb829-flat-slices/stage-plan.json")
PRIOR_PLAN_SHA = "d059fcb476c7de305242f8118db97c513475b20a64d07a34a533e003c4bf62d0"
PLAN = Path("sources/openmgh-bsb829-terminal-lines/selection-plan.json")
PLAN_SHA = "767c904145c7ddfa232852897a22257928b3eacf5b73b518e9b9adcf9b70ae8c"
SIDE_HOME = Path("sources/openmgh-bsb829-terminal-lines")
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"existing evidence differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _declared(work: dict) -> list[str]:
    editions = [edition for form in work["textual_forms"] for edition in form["editions"]]
    if len(editions) != 1:
        raise ValueError(f"ambiguous edition: {work['work_id']}")
    locators = editions[0]["containing_source"]["locator"].split("; ")
    if any(not locator.startswith(SOURCE.as_posix() + "#") for locator in locators):
        raise ValueError(f"source locator differs: {work['work_id']}")
    return [locator.split("#", 1)[1] for locator in locators]


def _source() -> tuple[bytes, etree._Element, list[etree._Element], dict]:
    for relative, expected in ((SOURCE, SOURCE_SHA), (BATCH, BATCH_SHA),
                               (RECEIPT, RECEIPT_SHA),
                               (PRIOR_PLAN, PRIOR_PLAN_SHA), (PLAN, PLAN_SHA)):
        if _sha(ROOT / relative) != expected:
            raise ValueError(f"frozen source or plan differs: {relative}")
    source = Path(_io_path(ROOT / SOURCE)).read_bytes()
    root = etree.fromstring(source, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    if root.getroottree().docinfo.doctype:
        raise ValueError("source DOCTYPE is forbidden")
    body = root.find(f"{TEI}text/{TEI}body")
    if body is None or len(body) != 1 or body[0].get("type") != "volume":
        raise ValueError("source volume envelope differs")
    divisions = list(body[0])
    if len(divisions) != 21:
        raise ValueError("source division inventory differs")
    plan = json.loads((ROOT / PLAN).read_bytes())
    if (plan.get("contract") != "ocd-openmgh-bsb829-terminal-lines-selection-v1"
            or plan.get("source_sha256") != SOURCE_SHA
            or plan.get("frozen_batch_sha256") != BATCH_SHA
            or plan.get("prior_held_plan_sha256") != PRIOR_PLAN_SHA
            or {item["work_id"] for item in plan.get("works", [])} != {
                "beno-letter-to-roman-church-fathers",
                "bruno-of-segni-letter-to-st-george-brothers",
            }):
        raise ValueError("two-work selection plan differs")
    return source, root, divisions, plan


def _select(divisions: list[etree._Element], entry: dict) -> etree._Element:
    div = divisions[entry["division"] - 1]
    if len(div) != 1 or div[0].tag != f"{TEI}ab":
        raise ValueError("source flat container differs")
    ab = div[0]
    children = list(ab)
    start = entry["first_child_index"]
    line = entry["last_line_child_index"]
    end = entry["last_selected_child_index"]
    following = entry["next_line_child_index"]
    if not (0 <= start <= line < end < following == end + 1 < len(children)):
        raise ValueError("terminal-line child indexes differ")
    for index, identifier in ((start, entry["first_id"]),
                              (line, entry["last_line_id"]),
                              (following, entry["next_line_id"])):
        if children[index].tag != f"{TEI}lb" or children[index].get(XML_ID) != identifier:
            raise ValueError("source line marker differs")
    if any(child.tag == f"{TEI}lb" for child in children[line + 1:following]):
        raise ValueError("extra line marker inside terminal line")
    selected = etree.Element(f"{TEI}ab", attrib=dict(ab.attrib))
    for child in children[start:following]:
        selected.append(deepcopy(child))
    word_ids = {node.get(XML_ID) for node in selected.iter() if node.tag == f"{TEI}w"}
    if not set(entry["terminal_word_ids"]) <= word_ids:
        raise ValueError("terminal source word parts differ")
    return selected


def _candidate(source_root: etree._Element, selected: etree._Element, work: dict) -> bytes:
    output = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    output.set(XML_ID, f"ocd-{work['work_id']}-bsb829-terminal-lines-electronic-v1")
    description = etree.SubElement(etree.SubElement(output, f"{TEI}teiHeader"), f"{TEI}fileDesc")
    etree.SubElement(etree.SubElement(description, f"{TEI}titleStmt"), f"{TEI}title").text = work["title"]
    original = source_root.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original is None:
        raise ValueError("source file description absent")
    publication = original.find(f"{TEI}publicationStmt")
    bibliography = original.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError("source publication or bibliography absent")
    description.append(deepcopy(publication))
    etree.SubElement(description, f"{TEI}sourceDesc").append(deepcopy(bibliography))
    body = etree.SubElement(etree.SubElement(output, f"{TEI}text"), f"{TEI}body")
    etree.SubElement(body, f"{TEI}div", type="work", n=work["title"]).append(selected)
    return etree.tostring(output, encoding="UTF-8", xml_declaration=True)


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("contract") != "ocd-openmgh-bsb829-terminal-lines-profile-v1":
        raise ValueError("terminal-line profile differs")
    source = source_manifest.authority_path("extracted-xml").read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError("extracted XML differs")
    root = etree.fromstring(source, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    divisions = list(root.find(f"{TEI}text/{TEI}body")[0])
    selected = _select(divisions, profile)
    if sha256(etree.tostring(selected, method="c14n", with_comments=True)).hexdigest() != profile["selection_c14n_sha256"]:
        raise ValueError("profile selection fingerprint differs")
    work = json.loads(source_manifest.authority_path("work-sidecar").read_bytes())
    if (work.get("work_id") != profile["work_id"]
            or _declared(work) != profile["declared_locator_ids"]):
        raise ValueError("work identity or declared source locators differ")
    candidate = _candidate(root, selected, work)
    if sha256(candidate).hexdigest() != profile["candidate_sha256"]:
        raise ValueError("direct candidate differs")
    accountability = {key: profile[key] for key in (
        "work_id", "edition_id", "acquisition_id", "source_path", "source_sha256",
        "division", "first_id", "last_line_id", "next_line_id", "first_child_index",
        "last_line_child_index", "last_selected_child_index", "next_line_child_index",
        "terminal_word_ids", "declared_locator_ids", "scope_note", "selection_c14n_sha256",
        "selection_plan_sha256",
    )}
    accountability["contract"] = "ocd-openmgh-bsb829-terminal-lines-accounting-v1"
    accountability["zip_disposition"] = "Retained acquisition package only; extracted XML is text authority."
    provenance = {
        "contract": "ocd-openmgh-bsb829-terminal-lines-provenance-v1",
        "status": "nonaccepted", "work_id": profile["work_id"],
        "edition_id": profile["edition_id"], "acquisition_id": profile["acquisition_id"],
        "source_path": profile["source_path"], "source_sha256": profile["source_sha256"],
        "canonical_ir_written": False, "publication": "not-ready",
    }
    unresolved = [
        {"status": "unresolved", "item": "Close visual comparison and print collation are not performed."},
        {"status": "unresolved", "item": "Human acceptance, rights clearance, and publication are separate."},
    ]
    readme = (
        f"# {profile['work_title']} — openMGH bsb829 terminal-line candidate\n\n"
        f"Text source: {profile['source_path']} (SHA-256 {profile['source_sha256']}).\n"
        f"Division {profile['division']}, {profile['first_id']} through the complete final "
        f"line {profile['last_line_id']}; next line {profile['next_line_id']} is outside. "
        f"{profile['scope_note']}\n"
        "The electronic publication statement and print bibliography are retained. "
        "Monumenta Germaniae Historica and the Bavarian State Library request derivative attribution. "
        "Rights and publication decisions remain separate.\n"
    ).encode()
    return {
        "content.tei.xml": candidate,
        "source-accountability.json": _json(accountability),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = "ocd-openmgh-bsb829-terminal-lines-to-tei"
_convert.converter_version = "1"


def prepare(destination: Path) -> dict:
    destination = destination.resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError("candidate destination must be outside the repository")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("candidate destination must be fresh")
    source, source_root, divisions, plan = _source()
    prior = json.loads((ROOT / PRIOR_PLAN).read_bytes())
    held = {item["work_id"] for item in prior["held"]}
    if held != {item["work_id"] for item in plan["works"]}:
        raise ValueError("prior held identity set changed")
    rows = []
    for entry in sorted(plan["works"], key=lambda item: item["work_id"]):
        work_id = entry["work_id"]
        work_path = ROOT / "library/works" / work_id / "work.json"
        work = json.loads(Path(_io_path(work_path)).read_bytes())
        declared = _declared(work)
        if (work["work_id"] != work_id or entry["first_id"] not in declared
                or entry["last_line_id"] not in declared
                or entry["next_line_id"] not in declared and entry["division"] == 15):
            raise ValueError(f"declared locator boundary differs: {work_id}")
        selected = _select(divisions, entry)
        candidate = _candidate(source_root, selected, work)
        observed = check(source, candidate, division=entry["division"],
                         first_id=entry["first_id"], last_line_id=entry["last_line_id"],
                         next_line_id=entry["next_line_id"])
        if any(observed[key] != entry[key] for key in (
            "first_child_index", "last_line_child_index",
            "last_selected_child_index", "next_line_child_index"
        )):
            raise ValueError("independent source child boundaries differ")
        path = destination / work_id / "candidate.tei.xml"
        _write_once(path, candidate)
        if errors := validate_file(Path(_io_path(path))):
            raise ValueError(f"TEI P5 XSD failed for {work_id}: {errors[:3]}")
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                    "edition_id": edition["edition_id"]}
        revision = f"{work_id}-bsb829-terminal-lines-v1"
        projected = project_document(path, identity=identity, language="la",
                                     representation_revision=revision,
                                     edition_title=edition["title"],
                                     _allow_acceptance_metadata=True, category="prose")
        errors = verify_document(path, projected["rows"], projected["receipt"],
                                 identity=identity, language="la",
                                 representation_revision=revision,
                                 edition_title=edition["title"],
                                 _allow_acceptance_metadata=True, category="prose")
        if errors or len(projected["rows"]) != 1:
            raise ValueError(f"independent native prose projection failed for {work_id}: {errors[:3]}")
        rows.append({
            "work_id": work_id, "work_sidecar_path": work_path.relative_to(ROOT).as_posix(),
            "work_sidecar_sha256": _sha(work_path),
            "declared_locator_ids": declared,
            "division": entry["division"],
            "first_id": entry["first_id"], "last_line_id": entry["last_line_id"],
            "next_line_id": entry["next_line_id"],
            "first_child_index": entry["first_child_index"],
            "last_line_child_index": entry["last_line_child_index"],
            "last_selected_child_index": entry["last_selected_child_index"],
            "next_line_child_index": entry["next_line_child_index"],
            "terminal_word_ids": entry["terminal_word_ids"],
            "scope_note": entry["scope_note"],
            "selection_c14n_sha256": observed["selection_c14n_sha256"],
            "candidate_path": path.as_posix(), "candidate_sha256": sha256(candidate).hexdigest(),
            "source_oracle": observed, "xsd_status": "pass",
            "native_prose_projection_rows": 1,
            "native_prose_independent_check": "pass",
        })
    result = {
        "contract": "ocd-openmgh-bsb829-terminal-lines-candidates-v1",
        "status": "nonaccepted", "source_path": SOURCE.as_posix(),
        "source_sha256": SOURCE_SHA, "frozen_batch_sha256": BATCH_SHA,
        "prior_held_plan_sha256": PRIOR_PLAN_SHA, "selection_plan": PLAN.as_posix(),
        "selection_plan_sha256": PLAN_SHA, "candidates": rows,
        "canonical_install": "not-performed",
    }
    _write_once(destination / "receipt.json", _json(result))
    return result


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
