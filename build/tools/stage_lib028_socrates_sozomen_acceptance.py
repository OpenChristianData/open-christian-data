"""Stage two separately selected, oracle-checked LIB-028 CCEL histories."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

from build.tei.lib028_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
NS = "{http://www.tei-c.org/ns/1.0}"
SOURCE = Path("raw/ccel/schaff/npnf202.xml")
SOURCE_SHA = "0139e8dcea6d40c3b1a5e046f3d45bdf6d1b30c503461d7f29f60309b4f2015c"
SOURCE_BYTES = 3_292_641
MANIFEST = Path("sources/structured-text/eusebius-ecclesiastical-history/lib028.source-manifest.json")
MANIFEST_SHA = "668c5c81f64162ddfc24948597b40e9dd723464cce9143290826a555640cb988"
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/lib028-church-history-native-screen-20260928-v1")
PACKAGE_SHA = "151f28bde81be7f3e8f31ef6c583c223534a406571f55dfe5d576f81dac18517"
CONTRACT = "ocd-lib028-npnf202-two-selected-ccel-stage-v1"
ROUTES = {
    "socrates-ecclesiastical-history": {
        "source_id": "ii", "selector": "ThML.body/div1[2]", "features": 6375,
        "title": "The Ecclesiastical History of Socrates Scholasticus.",
        "issue": "37c-289-socrates-ecclesiastical-history.md",
    },
    "sozomen-ecclesiastical-history": {
        "source_id": "iii", "selector": "ThML.body/div1[3]", "features": 6030,
        "title": "The Ecclesiastical History of Sozomen.",
        "issue": "37c-291-sozomen-ecclesiastical-history.md",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"LIB-028 source or evidence changed: {path}")
    return content


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, (json.dumps(value, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":")) + "\n").encode("utf-8"))


def _node_sha(node: etree._Element) -> str:
    """Hash expanded names, all attributes, text, tails, and ordered children."""
    def record(element: etree._Element) -> dict:
        return {"tag": element.tag if isinstance(element.tag, str) else type(element).__name__,
                "attributes": sorted(element.attrib.items()), "text": element.text,
                "tail": element.tail, "children": [record(child) for child in element]}

    value = json.dumps(record(node), sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")
    return sha256(value).hexdigest()


def _selected_candidate(original: bytes, work_id: str, route: dict,
                        crosswalk: dict) -> tuple[bytes, str]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    tree = etree.fromstring(original, parser)
    body = tree.find(f"{NS}text/{NS}body")
    if body is None or len(body) != 5:
        raise ValueError("LIB-028 original five-work TEI body differs")
    selected = [node for node in body if node.get("subtype") == work_id]
    if len(selected) != 1 or selected[0][0].text != route["title"]:
        raise ValueError(f"LIB-028 {work_id} original work selection differs")
    candidate_node = copy.deepcopy(selected[0])
    candidate_node.tail = None
    candidate_sha = _node_sha(candidate_node)
    source_tree = etree.fromstring(_read(ROOT / SOURCE, SOURCE_SHA),
                                   etree.XMLParser(resolve_entities=False, no_network=True,
                                                   remove_comments=False, huge_tree=True))
    source_body = source_tree.find("ThML.body")
    source_roots = [node for node in source_body if node.tag == "div1"]
    if ([node.get("id") for node in source_roots] != ["i", "ii", "iii", "iv", "v"]
            or len([node for node in source_roots if node.get("id") == route["source_id"]]) != 1):
        raise ValueError("LIB-028 NPNF202 source sibling order differs")
    source_node = next(node for node in source_roots if node.get("id") == route["source_id"])
    roots = [row for row in crosswalk["crosswalk"] if row.get("work_id") == work_id]
    children: dict[str, list[dict]] = {}
    for row in crosswalk["crosswalk"]:
        parent = row.get("parent_feature_id")
        if parent is not None:
            children.setdefault(parent, []).append(row)
    selected_rows = []
    pending = list(roots)
    while pending:
        row = pending.pop()
        selected_rows.append(row)
        pending.extend(children.get(row["feature_id"], []))
    bindings = [row for row in crosswalk["work_bindings"] if row["work_id"] == work_id]
    if (source_node.get("title") != route["title"]
            or len(list(source_node.iter())) != route["features"]
            or len(roots) != 1 or len(selected_rows) != route["features"] or len(bindings) != 1
            or bindings[0]["feature_count"] != route["features"]
            or bindings[0]["source_member"] != SOURCE.as_posix()
            or bindings[0]["source_root_id"] != route["source_id"]
            or bindings[0]["source_root_selector"] != route["selector"]):
        raise ValueError(f"LIB-028 {work_id} exact source/crosswalk census differs")
    for node in list(body):
        if node is not selected[0]:
            body.remove(node)
    header = tree.find(f"{NS}teiHeader")
    title_stmt = header.find(f"{NS}fileDesc/{NS}titleStmt")
    source_desc = header.find(f"{NS}fileDesc/{NS}sourceDesc")
    if title_stmt is None or source_desc is None:
        raise ValueError("LIB-028 source header differs")
    electronic = title_stmt.findall(f"{NS}title")
    matching = [node for node in electronic if node.get("n") == "npnf202"]
    if len(electronic) != 3 or len(matching) != 1:
        raise ValueError("LIB-028 three electronic volume titles differ")
    for title in electronic:
        if title is not matching[0]:
            title_stmt.remove(title)
    label = matching[0].attrib.pop("n")
    work_title = etree.Element(f"{NS}title", type="retained-work-title")
    work_title.text = route["title"]
    title_stmt.insert(0, work_title)
    lists = source_desc.findall(f"{NS}listBibl")
    if len(lists) != 1 or len(lists[0]) != 3:
        raise ValueError("LIB-028 source bibliography list differs")
    volume = [node for node in lists[0] if node.get("{http://www.w3.org/XML/1998/namespace}id") == "source-npnf202"]
    if len(volume) != 1:
        raise ValueError("LIB-028 NPNF202 bibliography differs")
    source_desc.insert(source_desc.index(lists[0]), volume[0])
    source_desc.remove(lists[0])
    label_bibl = etree.SubElement(source_desc, f"{NS}bibl")
    note = etree.SubElement(label_bibl, f"{NS}note", type="retained-electronic-title-source-label")
    note.set("n", label)
    note.text = f"Electronic volume title source @n: {label}"
    derived = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    reparsed = etree.fromstring(derived, parser)
    selected_now = reparsed.find(f"{NS}text/{NS}body/{NS}div")
    if selected_now is None or len(reparsed.find(f"{NS}text/{NS}body")) != 1:
        raise ValueError(f"LIB-028 {work_id} derived selection differs")
    selected_now.tail = None
    if _node_sha(selected_now) != candidate_sha:
        raise ValueError(f"LIB-028 {work_id} selected TEI node changed")
    return derived, candidate_sha


def prepare(work_id: str, stage: Path) -> dict[str, object]:
    route = ROUTES[work_id]
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or ROOT.resolve() in stage.resolve().parents:
        raise ValueError("LIB-028 work stage requires a fresh external root")
    if len(_read(ROOT / SOURCE, SOURCE_SHA)) != SOURCE_BYTES:
        raise ValueError("LIB-028 NPNF202 source length changed")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(PACKAGE)
    report = validate(manifest, package, _oracle)
    if manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA or report.status != "pass":
        raise ValueError("LIB-028 source-bound family candidate differs")
    binding_path = Path("sources/structured-text") / work_id / "lib028.work-binding.json"
    binding = json.loads(_read(ROOT / binding_path))
    if (binding["work_id"] != work_id or binding["source_member"] != SOURCE.as_posix()
            or binding["source_sha256"] != SOURCE_SHA
            or binding["source_root_id"] != route["source_id"]
            or binding["source_root_selector"] != route["selector"]
            or binding["disposition"] != "complete-subtree-represented"):
        raise ValueError(f"LIB-028 {work_id} work binding differs")
    original = package.member_bytes("content.tei.xml")
    crosswalk = json.loads(package.member_bytes("source-accountability.json"))
    selected, selected_node_sha = _selected_candidate(original, work_id, route, crosswalk)
    work_path = Path("library/works") / work_id
    before = _files(ROOT / work_path)
    work = json.loads(_read(ROOT / work_path / "work.json"))
    state = json.loads(_read(ROOT / work_path / "state.json"))
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                "edition_id": edition["edition_id"], "acquisition_id": edition["acquisition_ids"][0]}
    edition_path = work_path / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
    acquisition_path = edition_path / "acquisitions" / f"{identity['acquisition_id']}.json"
    acquisition = json.loads(_read(ROOT / acquisition_path))
    retained = acquisition["retained_files"]
    if (len(before) != 3 or edition.get("category") is not None or len(retained) != 1
            or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA or retained[0]["bytes"] != SOURCE_BYTES
            or acquisition["url"] != "https://www.ccel.org/ccel/schaff/npnf202.xml"
            or any((ROOT / edition_path / name).exists() for name in ("acceptance.json", "master.tei.xml"))):
        raise ValueError(f"LIB-028 {work_id} acquired edition differs")
    targets = [item for item in state["targets"] if item["target_type"] == "edition"
               and item["target_id"] == identity["edition_id"]]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError(f"LIB-028 {work_id} edition is not uniquely acquired")
    stage.mkdir(parents=True)
    for relative, digest in before.items():
        _put(stage, work_path / relative, _read(ROOT / work_path / relative, digest))
    dependencies = {MANIFEST, binding_path,
                    Path("plans/2026-08-31-sample-first-library-verification/issues") / route["issue"],
                    Path(manifest.record["converter"]["implementation_path"]),
                    Path(manifest.record["validator"]["implementation_path"])}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    for ref in set(work.get("evidence", [])) | {
        value for target in state["targets"] for value in target.get("evidence", [])
    }:
        relative = Path(ref.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe LIB-028 inherited evidence: {ref}")
        if not relative.is_relative_to(work_path):
            dependencies.add(relative)
    for relative in sorted(dependencies):
        _put(stage, relative, _read(ROOT / relative))
    evidence = work_path / "integration" / f"{work_id}-lib028-npnf202-selected-v1"
    for member in package.member_names:
        _put(stage, evidence / "inputs/package" / member, package.member_bytes(member))
    _json(stage, evidence / "inputs/validation.json", {
        "status": report.status, "candidate_sha256": package.sha256,
        "source_manifest_sha256": manifest.sha256, "report_sha256": report.sha256,
        "attestation": dict(report.attestation), "findings": list(report.findings)})
    updated_work = json.loads(json.dumps(work))
    updated_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    validate_identity_update(work, updated_work)
    _json(stage, work_path / "work.json", updated_work)
    load_work(_io_path(stage / work_path / "work.json"))
    selected_scope = (f"Complete source-native ThML.body/div1[@id='{route['source_id']}'] "
                      f"({route['title']}) only from NPNF2-02; the title page, sibling history "
                      "and volume indexes remain outside this accepted constituent selection.")
    acquired_scope = retained[0]["scope"]
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
                      "source_bytes": SOURCE_BYTES, "source_scope": acquired_scope}
    revision = {"id": f"{work_id}-lib028-npnf202-selected-v1",
                "date": datetime.now(timezone.utc).date().isoformat(),
                "note": f"Represent only retained NPNF2-02 root {route['source_id']} for {route['title']}; contributor and print claims remain review-bound."}
    derived = bind_reviewed_header(selected, expected_sha256=sha256(selected).hexdigest(),
                                   identity=identity, source=source_binding,
                                   source_url=acquisition["url"], declared_scope=selected_scope,
                                   revision=revision,
                                   historical_source_description={"pointers": [], "sha256": []})
    credit = b'<bibl xmlns="http://www.tei-c.org/ns/1.0"><note type="source-credit">sourced via CCEL.org</note></bibl>'
    if derived.count(b"</sourceDesc>") != 1:
        raise ValueError(f"LIB-028 {work_id} reviewed header differs")
    derived = derived.replace(b"</sourceDesc>", credit + b"</sourceDesc>", 1)
    final_tree = etree.fromstring(derived, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    final_node = final_tree.find(f"{NS}text/{NS}body/{NS}div")
    if final_node is None or len(final_tree.find(f"{NS}text/{NS}body")) != 1:
        raise ValueError(f"LIB-028 {work_id} accepted source selection differs")
    final_node.tail = None
    if _node_sha(final_node) != selected_node_sha:
        raise ValueError(f"LIB-028 {work_id} accepted source node changed")
    candidate_path = _put(stage, evidence / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate_path)):
        raise ValueError(f"LIB-028 {work_id} P5 errors: {errors[:2]}")
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": SOURCE_BYTES,
                 "sha256": SOURCE_SHA, "scope": selected_scope}]
    acceptance_scope = {"kind": "selection", "declared": selected_scope,
                        "expected_members": expected, "included_members": included,
                        "excluded_members": []}
    common = {"identity": identity, "source": source_binding,
              "candidate": make_file_binding(stage, candidate_path), "scope": selected_scope,
              "accepted_scope": {"kind": "selection", "declared": selected_scope},
              "expected_members": expected, "included_members": included,
              "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = _json(stage, evidence / "source-accounting.json", common | {
        "scope": acquired_scope, "source_sha256": SOURCE_SHA, "source_bytes": SOURCE_BYTES,
        "source_manifest_sha256": manifest.sha256, "candidate_package_sha256": package.sha256,
        "selected_root_id": route["source_id"], "selected_root_title": route["title"],
        "selected_feature_count": route["features"], "selected_tei_node_sha256": selected_node_sha,
        "excluded_top_level_div1_ids": ["i", "iii", "iv", "v"] if route["source_id"] == "ii" else ["i", "ii", "iv", "v"],
        "unsupported_elements": 0,
        "basis": "Current five-work independent source oracle plus exact per-work source/crosswalk census and canonical selected TEI node equality, P5 and native prose."})
    command = "py -3 -m build.tools.stage_lib028_socrates_sozomen_acceptance --stage-root <fresh-external-root>"
    technical = {"producer": {"id": manifest.record["converter"]["id"]},
                 "checker": {"id": manifest.record["validator"]["id"]},
                 "shared_assumptions": ["The selected work is drawn from the same verified five-work candidate; selection is independently checked against the retained root and work crosswalk."],
                 "independent_corroboration": "Current source oracle, full selected feature census, canonical selected TEI equality, P5, and stock native prose."}
    for label in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _json(stage, evidence / (label + ".json"), common | {
            "status": "pass", "command": command, "exit_code": 0, "claim": label,
            "candidate_package_sha256": package.sha256, "source_manifest_sha256": manifest.sha256,
            "oracle_report_sha256": report.sha256, "selected_tei_node_sha256": selected_node_sha})
        technical[label] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    reviewed_at = _now()
    review = {"reviewer": "agent:lib028-npnf202-selected-stage", "reviewed_at": reviewed_at,
              "coverage": {"status": "partial", "declared": selected_scope,
                           "reached": [f"{SOURCE.as_posix()}#{route['source_id']}"],
                           "inspected": [f"{SOURCE.as_posix()}#{route['source_id']}"],
                           "unreviewed": [f"{SOURCE.as_posix()}#{route['source_id']}-complete-visual-proofreading"]},
              "source_quality_uncertainty": ["Prior bounded CVW source/TEI loci were inspected; complete proofreading and print collation were not performed."],
              "discrepancies": [],
              "unreviewed_residuals": ["Full human review, contributor confirmation, rights and publication remain unresolved."]}
    review_file = _json(stage, evidence / "review.json", common | review | {
        "selected_root_id": route["source_id"], "work_binding": binding_path.as_posix()})
    decision = {"source_local_disposition": f"Agent technical acceptance of only retained NPNF2-02 root {route['source_id']} for {work_id}; sibling anthology material excluded.",
                "blockers": [], "human_decision": {"status": "not-recorded"},
                "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                                     "assessed_at": reviewed_at, "supported_scope": selected_scope,
                                     "unresolved_claims": [], "unassessed_stronger_claims": [
                                         "sibling anthology material", "work-specific contributor confirmation",
                                         "complete proofreading", "human review", "rights clearance", "publication"]}}
    acceptance = build_acceptance_record(stage, identity=identity, candidate_path=candidate_path,
                                         source_accounting_path=accounting, scope=acceptance_scope,
                                         technical=technical, review=review | {"report_path": review_file},
                                         representation_revision=revision, decision=decision)
    acceptance_path = stage / edition_path / "acceptance.json"
    write_acceptance(_io_path(acceptance_path), acceptance)
    master_path = _put(stage, edition_path / "master.tei.xml", derived)
    acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                   master=make_file_binding(stage, master_path))
    write_acceptance(_io_path(acceptance_path), acceptance)
    target = targets[0]
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    target["evidence"].extend([master_path.relative_to(stage).as_posix(),
                               acceptance_path.relative_to(stage).as_posix()])
    _json(stage, work_path / "state.json", state)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / work_path / "state.json"), root=_io_path(stage))
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"LIB-028 {work_id} accepted native projection differs: {errors[:2]}")
    after = _files(stage / work_path)
    dependencies_map = {key: value for key, value in _files(stage).items()
                        if not key.startswith(work_path.as_posix() + "/") and key != "stage-receipt.json"}
    receipt = {"contract": CONTRACT, "status": "staged-only", "installation": "not-performed",
               "rights": "not-assessed", "canonical_root": ROOT.as_posix(),
               "stage_root": stage.as_posix(), "dependencies": dependencies_map,
               "work": {"work_id": work_id, "work_path": work_path.as_posix(),
                        "before": before, "after": after, "source_path": SOURCE.as_posix(),
                        "source_sha256": SOURCE_SHA, "source_manifest_sha256": manifest.sha256,
                        "candidate_package_sha256": package.sha256,
                        "selected_root_id": route["source_id"],
                        "selected_feature_count": route["features"],
                        "selected_tei_node_sha256": selected_node_sha,
                        "new_master_sha256": sha256(derived).hexdigest(),
                        "new_acceptance_sha256": sha256(_read(acceptance_path)).hexdigest(),
                        "native_rows": 1}}
    _json(stage, Path("stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-root", required=True, type=Path)
    args = parser.parse_args()
    stage_root = args.stage_root.absolute()
    if stage_root.exists() or not stage_root.parent.is_dir():
        raise ValueError("LIB-028 batch requires a fresh external parent")
    stage_root.mkdir()
    output = {}
    for work_id in ROUTES:
        receipt = prepare(work_id, stage_root / work_id)
        output[work_id] = {"before": len(receipt["work"]["before"]),
                           "after": len(receipt["work"]["after"]),
                           "master_sha256": receipt["work"]["new_master_sha256"]}
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
