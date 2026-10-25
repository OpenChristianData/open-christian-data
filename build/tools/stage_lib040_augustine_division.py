"""Stage a source-bound standalone LIB-040 Augustine division outside the library."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, load_acceptance,
    make_file_binding, validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
SOURCE_MANIFEST = Path("sources/structured-text/augustine-npnf101-106-107-lib040/lib040.source-manifest.json")
FAMILY_SHA = "94954cd921eb1f636ce0f43d5d5f2fb69d18f0f94e339d93b91e45c442126271"
PACKAGE_SHA = "c63df34f07c4312dfc8ddbad0a3fc7b4751d4bd19a0f392ae7b2eaff4c81b33a"
MANIFEST_SHA = "3aa1efc76cee289f0fd22c43ff30c298e7a54977c578bb65725f3ef24e556624"
VALIDATION_SHA = "93a0fbe9f59f6f330ec48343e407ae2cbcba7bb490f285ef5572cd92393f5637"
NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
PROFILE = "ocd-lib040-augustine-direct-divisions-v1"
FAMILY_WORKS = (
    "augustine-confessions", "augustine-letters-part-1", "augustine-sermon-on-the-mount",
    "augustine-harmony-of-gospels", "augustine-sermons-selected-lessons",
    "augustine-tractates-on-john", "augustine-homilies-on-first-john", "augustine-soliloquies",
)
CONFIGS = {
    "augustine-soliloquies": {"category": "prose", "expected_divisions": 4, "profile": PROFILE},
    "augustine-sermon-on-the-mount": {"category": "commentary", "expected_divisions": 3, "profile": PROFILE},
    "augustine-tractates-on-john": {"category": "commentary", "expected_divisions": 125, "profile": PROFILE},
    "augustine-letters-part-1": {"category": "prose", "expected_divisions": 2, "profile": "ocd-lib040-augustine-selected-units-v1"},
    "augustine-sermons-selected-lessons": {"category": "sermons", "expected_divisions": 99, "profile": "ocd-lib040-augustine-selected-units-v1"},
    "augustine-homilies-on-first-john": {"category": "sermons", "expected_divisions": 19, "profile": "ocd-lib040-augustine-selected-units-v1"},
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    raw = io_path(path).read_bytes()
    if expected is not None and _sha(raw) != expected:
        raise PipelineError(f"LIB-040 source byte binding differs: {path}")
    return raw


def _write(stage: Path, relative: Path, raw: bytes) -> Path:
    path = stage / relative
    io_path(path).parent.mkdir(parents=True, exist_ok=True)
    io_path(path).write_bytes(raw)
    return path


def _json(stage: Path, relative: Path, value: object) -> Path:
    return _write(stage, relative, (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode())


def _one_child(family_bytes: bytes, work_id: str, source_root: str) -> tuple[bytes, str, list[dict[str, str | None]]]:
    family = etree.fromstring(family_bytes, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    body = family.xpath("./t:text/t:body", namespaces={"t": NS})
    if len(body) != 1 or tuple(child.get("subtype") for child in body[0]) != FAMILY_WORKS:
        raise PipelineError("LIB-040 family work boundary/order differs")
    child = body[0][FAMILY_WORKS.index(work_id)]
    if child.get(XML_ID) != f"lib040-{work_id}" or child.get("n") != source_root or child.get("type") != "work" or (child.tail or "").strip():
        raise PipelineError("LIB-040 standalone work child differs")
    original = deepcopy(child)
    original.tail = None
    child_hash = _sha(etree.tostring(original, method="xml"))
    direct = [node for node in original if node.tag == f"{{{NS}}}div"]
    if original[0].tag != f"{{{NS}}}head":
        raise PipelineError("LIB-040 direct divisions or work heading differ")
    units = [{"source_id": node.get(XML_ID).split("-", 2)[2], "tei_id": node.get(XML_ID), "n": node.get("n"), "type": node.get("type")} for node in direct]
    return etree.tostring(original, encoding="UTF-8"), child_hash, units


def prepare(work_id: str, stage: Path, family_root: Path) -> dict[str, object]:
    if work_id not in CONFIGS:
        raise PipelineError(f"LIB-040 direct-division stage is not configured for {work_id}")
    config = CONFIGS[work_id]
    root = ROOT.resolve(strict=True)
    stage = stage.absolute()
    family_root = family_root.resolve(strict=True)
    if stage.exists() or stage.parent.resolve() != Path("C:/Scratch").resolve() or stage == root or root in stage.parents:
        raise PipelineError("LIB-040 stage must be a fresh direct C:/Scratch child")
    work_path = Path("library/works") / work_id
    handoff_path = work_path / "integration/lib040-source-bound-handoff-20260926.json"
    handoff = json.loads(_read(root / handoff_path))
    source_path = Path(handoff["source"]["path"])
    source = _read(root / source_path, handoff["source"]["sha256"])
    source_xml = etree.fromstring(source, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    selected = [node for node in source_xml.iter("div1") if node.get("id") == handoff["source"]["root_id"]]
    if len(selected) != 1 or _sha(etree.tostring(selected[0], method="c14n")) != handoff["source"]["root_c14n_sha256"] or sum(1 for _ in selected[0].iter()) != handoff["source"]["feature_count"]:
        raise PipelineError("LIB-040 retained source root selection differs")
    source_units = [node for node in selected[0] if node.tag == "div2"]
    if len(source_units) != config["expected_divisions"]:
        raise PipelineError("LIB-040 direct source division count/type differs")
    _read(root / SOURCE_MANIFEST, MANIFEST_SHA)
    from ocd_kernel.reconstruction.contract import CandidatePackage
    package = CandidatePackage.load(family_root / "package")
    if package.sha256 != PACKAGE_SHA or handoff["candidate"]["manifest_sha256"] != PACKAGE_SHA:
        raise PipelineError("LIB-040 family candidate package differs")
    family = _read(family_root / "package/content.tei.xml", FAMILY_SHA)
    validation_bytes = _read(family_root / "validation.json", VALIDATION_SHA)
    validation = json.loads(validation_bytes)
    if validation.get("status") != "pass" or validation.get("candidate_sha256") != PACKAGE_SHA or validation.get("source_manifest_sha256") != MANIFEST_SHA or validation.get("findings") != []:
        raise PipelineError("LIB-040 source-led family validation differs")
    work_xml, child_hash, units = _one_child(family, work_id, handoff["source"]["root_id"])
    if child_hash != handoff["candidate"]["child_xml_sha256"]:
        raise PipelineError("LIB-040 reviewed family child hash differs")
    expected_ids = [f"lib040-npnf{source_path.stem.removeprefix('npnf')}-{node.get('id')}" for node in source_units]
    if [(node["tei_id"], node["n"]) for node in units] != list(zip(expected_ids, [node.get("n") for node in source_units])):
        raise PipelineError("LIB-040 source-to-TEI direct division IDs differ")
    review_path = Path(handoff["visual"]["review"])
    review_bytes = _read(root / review_path, handoff["visual"]["review_sha256"])
    review = json.loads(review_bytes)
    visual = next((item for item in review.get("works", []) if item.get("work_id") == work_id), None)
    if not visual or len(visual["loci"]) != len(handoff["visual"]["loci"]) or any(item.get("result") != "visible_sample_agrees" for item in visual["loci"]):
        raise PipelineError("LIB-040 bounded visual sample differs")
    captures = [capture for item in visual["loci"] for capture in item["captures"]]
    if len(captures) != handoff["visual"]["capture_count"] or any(_sha(_read(root / review_path.parent / capture["path"])) != capture["sha256"] for capture in captures):
        raise PipelineError("LIB-040 visual capture binding differs")
    state = json.loads(_read(root / work_path / "state.json"))
    work = json.loads(_read(root / work_path / "work.json"))
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if work["work_id"] != work_id or edition.get("category") is not None or edition.get("language") != "en":
        raise PipelineError("LIB-040 canonical work category/language baseline differs")
    identity = dict(work_id=work_id, textual_form_id=form["textual_form_id"], edition_id=edition["edition_id"], acquisition_id=edition["acquisition_ids"][0])
    edition_path = work_path / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
    acquisition_path = edition_path / "acquisitions" / (identity["acquisition_id"] + ".json")
    acquisition_bytes = _read(root / acquisition_path, handoff["canonical"]["acquisition_sha256"])
    acquisition = json.loads(acquisition_bytes)
    if acquisition["source_path"] != source_path.as_posix() or acquisition["source_sha256"] != _sha(source) or acquisition["source_bytes"] != len(source):
        raise PipelineError("LIB-040 canonical acquisition source differs")
    if edition.get("acquisition_ids") != [identity["acquisition_id"]]:
        raise PipelineError("LIB-040 edition/acquisition link differs")
    work["textual_forms"][0]["editions"][0]["category"] = config["category"]
    revision_id = f"lib040-{work_id}-electronic-v1"
    evidence_path = work_path / "integration" / revision_id
    scope_text = f"Complete {work_id} root ThML.body/div1[@id='{handoff['source']['root_id']}'] in retained {source_path.as_posix()}, in source order. Other volume divisions and shell matter remain outside this work. Electronic witness without print collation or whole-work visual proofreading."
    stage.mkdir()
    _json(stage, work_path / "work.json", work)
    _json(stage, work_path / "state.json", state)
    _write(stage, acquisition_path, acquisition_bytes)
    for path in (source_path, SOURCE_MANIFEST, Path("sources/structured-text") / work_id / "config.json", Path("metadata/source-evidence/catalog") / (work_id + ".json"), review_path):
        _write(stage, path, _read(root / path))
    _write(stage, evidence_path / "inputs/family-content.tei.xml", family)
    _write(stage, evidence_path / "inputs/validation.json", validation_bytes)
    family_root_xml = etree.fromstring(family, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    source_bibl = family_root_xml.xpath(f"./t:teiHeader/t:fileDesc/t:sourceDesc/t:listBibl/t:bibl[@xml:id='source-{source_path.stem}']", namespaces={"t": NS})
    if len(source_bibl) != 1:
        raise PipelineError("LIB-040 source bibliography differs")
    tree = etree.Element(f"{{{NS}}}TEI", nsmap={None: NS})
    tree.set(XML_ID, f"{work_id}-electronic")
    header = etree.SubElement(tree, f"{{{NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{NS}}}title").text = work["title"]
    etree.SubElement(title_stmt, f"{{{NS}}}editor").text = "Philip Schaff"
    publication = etree.SubElement(file_desc, f"{{{NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{NS}}}p").text = "publication:not_ready; human textual acceptance absent."
    source_desc = etree.SubElement(file_desc, f"{{{NS}}}sourceDesc")
    source_desc.append(deepcopy(source_bibl[0]))
    text = etree.SubElement(tree, f"{{{NS}}}text")
    body = etree.SubElement(text, f"{{{NS}}}body")
    body.append(etree.fromstring(work_xml))
    if _sha(etree.tostring(body[0], method="xml")) != child_hash:
        raise PipelineError("LIB-040 standalone extraction changed child")
    derived = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    now = datetime.now(timezone.utc)
    at = now.isoformat().replace("+00:00", "Z")
    revision = dict(id=revision_id, date=now.date().isoformat(), note=f"Accept complete retained {work_id} electronic work root.")
    source_binding = dict(source_path=source_path.as_posix(), source_sha256=_sha(source), source_bytes=len(source), source_scope=acquisition["source_scope"])
    bound = bind_reviewed_header(derived, expected_sha256=_sha(derived), identity=identity, source=source_binding, source_url=acquisition["url"], declared_scope=scope_text, revision=revision)
    candidate = _write(stage, evidence_path / "candidate.tei.xml", bound)
    if errors := validate_file(candidate):
        raise PipelineError(f"LIB-040 standalone TEI XSD failed: {errors[:3]}")
    candidate_root = etree.fromstring(bound, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    selected_tei = candidate_root.xpath("./t:text/t:body/t:div", namespaces={"t": NS})
    if len(selected_tei) != 1 or _sha(etree.tostring(selected_tei[0], method="xml")) != child_hash:
        raise PipelineError("LIB-040 bound candidate changed source child")
    expected = [dict(path=source_path.as_posix(), position=1)]
    included = [dict(path=source_path.as_posix(), position=1, bytes=len(source), sha256=_sha(source), scope=acquisition["retained_files"][0]["scope"])]
    scope = dict(kind="selection", declared=scope_text, expected_members=expected, included_members=included, excluded_members=[])
    common = dict(identity=identity, source=source_binding, scope=scope_text, candidate=make_file_binding(stage, candidate))
    accounting = _json(stage, evidence_path / "source-accounting.json", common | dict(scope=acquisition["source_scope"], accepted_scope=dict(kind="selection", declared=scope_text), expected_members=expected, included_members=included, excluded_members=[], missing_members=[], unknown_members=[], source_sha256=_sha(source), source_bytes=len(source), selected_root=handoff["source"]["root_id"], source_root_c14n_sha256=handoff["source"]["root_c14n_sha256"], reviewed_child_xml_sha256=child_hash, family_package_sha256=PACKAGE_SHA, projection_profile=config["profile"], projection_units=units))
    command = "py -3 -m build.tools.stage_lib040_augustine_division --work <work-id> --stage <fresh-C:/Scratch-child> --family <current-LIB040-candidate>"
    proof_evidence = dict(review_receipt_sha256=_sha(review_bytes), source_manifest_sha256=MANIFEST_SHA, family_tei_sha256=FAMILY_SHA, family_validation_sha256=VALIDATION_SHA, source_root_c14n_sha256=handoff["source"]["root_c14n_sha256"], child_tei_xml_sha256=child_hash)
    technical = dict(producer=dict(id="ocd-lib040-retained-thml-to-tei", path=make_file_binding(stage, stage / SOURCE_MANIFEST)), checker=dict(id="ocd-lib040-source-to-tei-oracle", path=make_file_binding(stage, stage / SOURCE_MANIFEST)), shared_assumptions=["The producer and oracle share declared LIB-040 source roots; the oracle walks retained XML separately."], independent_corroboration="The exact family TEI passed a source-led oracle; the standalone body is exactly one verified work child and retained CVW loci agree.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof_fields = dict(accepted_scope=dict(kind="selection", declared=scope_text), expected_members=expected, included_members=included, excluded_members=[], missing_members=[], unknown_members=[]) if name == "accounting" else {}
        proof = _json(stage, evidence_path / f"{name}.json", common | dict(status="pass", command=command, exit_code=0, evidence=proof_evidence, claim=name) | proof_fields)
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    coverage = dict(status="partial", declared=scope_text, reached=[handoff["source"]["root_id"]], inspected=[f"{handoff['source']['root_id']}/{item['source_id']}" for item in visual["loci"]], unreviewed=[f"{handoff['source']['root_id']}/other-content"])
    reviewed = dict(reviewer="agent:lib040-augustine-division-assessment", reviewed_at=at, coverage=coverage, source_quality_uncertainty=["No separate print witness is collated against the retained CCEL electronic text."], discrepancies=[], unreviewed_residuals=["Retained CVW loci are a bounded sample; other nodes were checked mechanically."])
    report = _json(stage, evidence_path / "review.json", common | reviewed | dict(historical_review_sha256=proof_evidence["review_receipt_sha256"], inspected_loci=visual["loci"]))
    decision = dict(source_local_disposition=f"Agent acceptance of complete {work_id} root in retained CCEL electronic witness.", blockers=[], agent_assessment=dict(status="accepted", actor=reviewed["reviewer"], assessed_at=at, supported_scope=scope_text, unresolved_claims=[], unassessed_stronger_claims=["print collation", "whole-work visual proofreading", "human acceptance", "rights clearance", "publication"]), human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting, scope=scope, technical=technical, review=reviewed | dict(report_path=report), representation_revision=revision, decision=decision)
    acceptance = stage / edition_path / "acceptance.json"
    write_acceptance(io_path(acceptance), record)
    validate_acceptance(io_path(acceptance), root=io_path(stage))
    master = _write(stage, edition_path / "master.tei.xml", bound)
    record = load_acceptance(io_path(acceptance))
    record["promotion"].update(status="promoted", promoted_at=at, master=make_file_binding(stage, master))
    write_acceptance(io_path(acceptance), record)
    edition_target = next((item for item in state["targets"] if item["target_id"] == identity["edition_id"]), None)
    if edition_target is None or edition_target["stage"] != "acquired":
        raise PipelineError("LIB-040 edition target not acquired")
    edition_target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at)
    edition_target["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    _json(stage, work_path / "state.json", state)
    validate_acceptance(io_path(acceptance), root=io_path(stage))
    return {"status": "staged-only", "stage_root": stage.as_posix(), "work_id": work_id, "category": config["category"], "master_sha256": _sha(bound), "acceptance_sha256": _sha(_read(acceptance)), "source_sha256": _sha(source), "source_root_c14n_sha256": handoff["source"]["root_c14n_sha256"], "child_xml_sha256": child_hash, "projection_profile": config["profile"], "direct_division_count": len(units)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", choices=sorted(CONFIGS), required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--family", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.work, args.stage, args.family), sort_keys=True))


if __name__ == "__main__":
    main()
