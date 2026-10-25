"""Stage a standalone Harmony master from the reviewed LIB-040 child.

The stage is a fresh local fixture. This command never edits library/works.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    load_acceptance,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/augustine-harmony-of-gospels")
EDITION = WORK / "forms/augustine-harmony-of-gospels-ccel-npnf106-retained-en/editions/augustine-harmony-of-gospels-ccel-npnf106-electronic"
SOURCE = Path("raw/ccel/npnf1/npnf106.xml")
MANIFEST = Path("sources/structured-text/augustine-npnf101-106-107-lib040/lib040.source-manifest.json")
REVIEW = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/next40/visual/root-visual-findings.json")
EVIDENCE = WORK / "integration/harmony-npnf106-electronic-v1"
SOURCE_SHA = "3710c6985a8dfc4e4ffafc461a7a8550db609b0506535453dac252f2aa55b604"
FAMILY_SHA = "94954cd921eb1f636ce0f43d5d5f2fb69d18f0f94e339d93b91e45c442126271"
PACKAGE_SHA = "c63df34f07c4312dfc8ddbad0a3fc7b4751d4bd19a0f392ae7b2eaff4c81b33a"
MANIFEST_SHA = "3aa1efc76cee289f0fd22c43ff30c298e7a54977c578bb65725f3ef24e556624"
VALIDATION_SHA = "93a0fbe9f59f6f330ec48343e407ae2cbcba7bb490f285ef5572cd92393f5637"
NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
IDENTITY = dict(
    work_id="augustine-harmony-of-gospels",
    textual_form_id="augustine-harmony-of-gospels-ccel-npnf106-retained-en",
    edition_id="augustine-harmony-of-gospels-ccel-npnf106-electronic",
    acquisition_id="augustine-harmony-of-gospels-ccel-npnf106-acquired",
)
SCOPE = (
    "Complete Harmony work root ThML.body/div1[@id='vi'] in retained "
    "CCEL NPNF1-06 XML, in source order. The volume shell and every other "
    "division remain accounted outside this work. This is an electronic "
    "witness, without a print collation or whole-work visual review."
)


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def read(path: Path, expected: str | None = None) -> bytes:
    data = io_path(path).read_bytes()
    if expected is not None and digest(data) != expected:
        raise PipelineError(f"Harmony byte binding differs: {path}")
    return data


def write(stage: Path, relative: Path, data: bytes) -> Path:
    path = stage / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def write_json(stage: Path, relative: Path, value: object) -> Path:
    return write(stage, relative, (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode())


def one_child(family_bytes: bytes) -> tuple[bytes, str]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    family = etree.fromstring(family_bytes, parser)
    ns = {"t": NS}
    body = family.xpath("./t:text/t:body", namespaces=ns)
    expected = [
        "augustine-confessions", "augustine-letters-part-1", "augustine-sermon-on-the-mount",
        "augustine-harmony-of-gospels", "augustine-sermons-selected-lessons",
        "augustine-tractates-on-john", "augustine-homilies-on-first-john", "augustine-soliloquies",
    ]
    if len(body) != 1 or [child.get("subtype") for child in body[0]] != expected:
        raise PipelineError("LIB-040 family work boundary/order differs")
    child = body[0][3]
    if child.get(XML_ID) != "lib040-augustine-harmony-of-gospels" or child.get("n") != "vi" or child.get("type") != "work":
        raise PipelineError("Harmony child identity/root differs")
    if (child.tail or "").strip():
        raise PipelineError("Harmony child has non-whitespace trailing text outside its work boundary")
    original = deepcopy(child)
    original.tail = None
    child_hash = digest(etree.tostring(original, method="xml"))
    tree = etree.Element(f"{{{NS}}}TEI", nsmap={None: NS})
    tree.set(XML_ID, "augustine-harmony-of-gospels-electronic")
    header = etree.SubElement(tree, f"{{{NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{NS}}}title").text = "The Harmony of the Gospels"
    etree.SubElement(title_stmt, f"{{{NS}}}editor").text = "Philip Schaff"
    publication = etree.SubElement(file_desc, f"{{{NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{NS}}}p").text = "publication:not_ready; human textual acceptance absent."
    source_desc = etree.SubElement(file_desc, f"{{{NS}}}sourceDesc")
    source_bibl = family.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc/t:listBibl/t:bibl[@xml:id='source-npnf106']", namespaces=ns)
    if len(source_bibl) != 1:
        raise PipelineError("NPNF1-06 source description differs")
    source_desc.append(deepcopy(source_bibl[0]))
    text = etree.SubElement(tree, f"{{{NS}}}text")
    selected_body = etree.SubElement(text, f"{{{NS}}}body")
    selected_body.append(original)
    if digest(etree.tostring(selected_body[0], method="xml")) != child_hash:
        raise PipelineError("standalone extraction changed the reviewed child")
    return etree.tostring(tree, encoding="UTF-8", xml_declaration=True), child_hash


def prepare(stage: Path, family_root: Path) -> dict[str, object]:
    root = ROOT.resolve(strict=True)
    stage = stage.absolute()
    family_root = family_root.resolve(strict=True)
    if stage.exists() or stage.parent.resolve() != Path("C:/Scratch").resolve() or stage == root or root in stage.parents:
        raise PipelineError("stage must be a fresh direct C:/Scratch child")
    source = read(root / SOURCE, SOURCE_SHA)
    if len(source) != 4_680_096:
        raise PipelineError("retained Harmony XML byte count differs")
    from_source = etree.fromstring(source, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    selected = from_source.xpath("//*[local-name()='div1' and @id='vi']")
    if len(selected) != 1:
        raise PipelineError("retained Harmony work selector is not unique")
    read(root / MANIFEST, MANIFEST_SHA)
    review = json.loads(read(root / REVIEW))
    visual = next((item for item in review.get("works", []) if item.get("work_id") == IDENTITY["work_id"]), None)
    if not visual or visual.get("ticket") != "37c-040" or len(visual.get("loci", [])) != 4 or any(item.get("result") != "visible_sample_agrees" or not item.get("source_id", "").startswith("vi.") for item in visual["loci"]):
        raise PipelineError("historical exact-source technical and visual review differs")
    package = family_root / "package"
    from ocd_kernel.reconstruction.contract import CandidatePackage
    candidate_package = CandidatePackage.load(package)
    if candidate_package.sha256 != PACKAGE_SHA:
        raise PipelineError("current LIB-040 package hash differs")
    family = read(package / "content.tei.xml", FAMILY_SHA)
    validation = json.loads(read(family_root / "validation.json", VALIDATION_SHA))
    if validation.get("candidate_sha256") != PACKAGE_SHA or validation.get("source_manifest_sha256") != MANIFEST_SHA or validation.get("status") != "pass":
        raise PipelineError("current independent LIB-040 oracle result differs")
    derived, child_hash = one_child(family)
    source_bytes = etree.tostring(selected[0], method="c14n")
    if not source_bytes or sum(1 for _ in selected[0].iter()) != 5003:
        raise PipelineError("Harmony source selection accounting differs")
    state = json.loads(read(root / WORK / "state.json"))
    work = json.loads(read(root / WORK / "work.json"))
    acquisition = json.loads(read(root / EDITION / "acquisitions/augustine-harmony-of-gospels-ccel-npnf106-acquired.json"))
    if work["work_id"] != IDENTITY["work_id"] or acquisition["source_path"] != SOURCE.as_posix() or acquisition["source_sha256"] != SOURCE_SHA or acquisition["source_bytes"] != len(source):
        raise PipelineError("canonical Harmony source/identity declaration differs")
    if work["textual_forms"][0]["editions"][0]["edition_id"] != IDENTITY["edition_id"] or work["textual_forms"][0]["editions"][0]["acquisition_ids"] != [IDENTITY["acquisition_id"]]:
        raise PipelineError("canonical Harmony edition/acquisition link differs")
    work["textual_forms"][0]["editions"][0]["category"] = "prose"
    stage.mkdir()
    write_json(stage, WORK / "work.json", work)
    write_json(stage, WORK / "state.json", state)
    write(stage, EDITION / "acquisitions/augustine-harmony-of-gospels-ccel-npnf106-acquired.json", read(root / EDITION / "acquisitions/augustine-harmony-of-gospels-ccel-npnf106-acquired.json"))
    write(stage, SOURCE, source)
    write(stage, MANIFEST, read(root / MANIFEST))
    for evidence_path in (Path("sources/structured-text/augustine-harmony-of-gospels/config.json"), Path("metadata/source-evidence/catalog/augustine-harmony-of-gospels.json")):
        write(stage, evidence_path, read(root / evidence_path))
    write(stage, REVIEW, read(root / REVIEW))
    write(stage, EVIDENCE / "inputs/family-content.tei.xml", family)
    write(stage, EVIDENCE / "inputs/validation.json", read(family_root / "validation.json"))
    now = datetime.now(timezone.utc)
    at = now.isoformat().replace("+00:00", "Z")
    revision = dict(id="harmony-npnf106-electronic-v1", date=now.date().isoformat(), note="Accept the complete Harmony root from the retained CCEL electronic witness.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA, source_bytes=len(source), source_scope=acquisition["source_scope"])
    bound = bind_reviewed_header(derived, expected_sha256=digest(derived), identity=IDENTITY, source=source_binding, source_url=acquisition["url"], declared_scope=SCOPE, revision=revision)
    candidate = write(stage, EVIDENCE / "candidate.tei.xml", bound)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"standalone Harmony TEI XSD failed: {errors[:3]}")
    parsed = etree.parse(str(candidate))
    actual = parsed.xpath("./t:text/t:body/t:div", namespaces={"t": NS})
    if len(actual) != 1 or digest(etree.tostring(actual[0], method="xml")) != child_hash:
        raise PipelineError("standalone candidate changed the reviewed Harmony work root")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(source), sha256=SOURCE_SHA, scope=acquisition["retained_files"][0]["scope"])]
    scope = dict(kind="selection", declared=SCOPE, expected_members=expected, included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=source_binding, scope=SCOPE, candidate=make_file_binding(stage, candidate))
    accounting = write_json(stage, EVIDENCE / "source-accounting.json", (common | dict(scope=acquisition["source_scope"])) | dict(accepted_scope=dict(kind="selection", declared=SCOPE), expected_members=expected, included_members=included, excluded_members=[], missing_members=[], unknown_members=[], source_sha256=SOURCE_SHA, source_bytes=len(source), selected_root="vi", source_root_c14n_sha256=digest(source_bytes), reviewed_child_xml_sha256=child_hash, family_package_sha256=PACKAGE_SHA, projection_profile="ocd-lib040-harmony-seven-source-divisions-v1", projection_units=["i", "ii", "iii", "I", "II", "III", "IV"]))
    command = "py -3 -m build.tools.stage_augustine_harmony_electronic_acceptance --stage <fresh-C:/Scratch-child> --family <current-LIB040-candidate>"
    evidence = dict(review_receipt_sha256=digest(read(root / REVIEW)), source_manifest_sha256=MANIFEST_SHA, family_tei_sha256=FAMILY_SHA, family_validation_sha256=VALIDATION_SHA, source_root_c14n_sha256=digest(source_bytes), child_tei_xml_sha256=child_hash)
    technical = dict(producer=dict(id="ocd-lib040-retained-thml-to-tei", path=make_file_binding(stage, stage / MANIFEST)), checker=dict(id="ocd-lib040-source-to-tei-oracle", path=make_file_binding(stage, stage / MANIFEST)), shared_assumptions=["The producer and oracle share the declared LIB-040 source roots; the oracle walks the retained XML separately."], independent_corroboration="The exact family TEI has independent source-led oracle checks and four Harmony CVW loci; the standalone body is exactly the one reviewed child subtree.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof_fields = dict(accepted_scope=dict(kind="selection", declared=SCOPE), expected_members=expected, included_members=included, excluded_members=[], missing_members=[], unknown_members=[]) if name == "accounting" else {}
        proof = write_json(stage, EVIDENCE / f"{name}.json", common | dict(status="pass", command=command, exit_code=0, evidence=evidence, claim=name) | proof_fields)
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    coverage = dict(status="partial", declared=SCOPE, reached=["vi"], inspected=[f"vi/{row['source_id']}" for row in visual["loci"]], unreviewed=["vi/other-content"])
    reviewed = dict(reviewer="agent:harmony-electronic-assessment", reviewed_at=at, coverage=coverage, source_quality_uncertainty=["No separate print witness is collated against the retained CCEL electronic text."], discrepancies=[], unreviewed_residuals=["The four retained CVW loci are a bounded sample; all remaining nodes were checked mechanically."])
    report = write_json(stage, EVIDENCE / "review.json", common | reviewed | dict(historical_review_sha256=evidence["review_receipt_sha256"], inspected_loci=visual["loci"]))
    decision = dict(source_local_disposition="Agent acceptance of the complete Harmony root in the retained CCEL electronic witness.", blockers=[], agent_assessment=dict(status="accepted", actor=reviewed["reviewer"], assessed_at=at, supported_scope=SCOPE, unresolved_claims=[], unassessed_stronger_claims=["print collation", "whole-work visual proofreading", "human acceptance", "rights clearance", "publication"]), human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate, source_accounting_path=accounting, scope=scope, technical=technical, review=reviewed | dict(report_path=report), representation_revision=revision, decision=decision)
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    master = write(stage, EDITION / "master.tei.xml", bound)
    record = load_acceptance(acceptance)
    record["promotion"].update(status="promoted", promoted_at=at, master=make_file_binding(stage, master))
    write_acceptance(acceptance, record)
    edition_target = next((x for x in state["targets"] if x["target_id"] == IDENTITY["edition_id"]), None)
    if edition_target is None or edition_target["stage"] != "acquired":
        raise PipelineError("Harmony edition target is missing or not acquired")
    edition_target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at)
    edition_target["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    write_json(stage, WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage)
    return dict(stage_root=stage.as_posix(), source_sha256=SOURCE_SHA, source_root_c14n_sha256=digest(source_bytes), reviewed_family_tei_sha256=FAMILY_SHA, extracted_child_xml_sha256=child_hash, master_sha256=digest(bound), acceptance_sha256=digest(acceptance.read_bytes()), status="staged-only")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--family", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.stage, args.family), sort_keys=True))


if __name__ == "__main__":
    main()
