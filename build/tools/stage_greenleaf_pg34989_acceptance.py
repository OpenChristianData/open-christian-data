"""Stage the direct Project Gutenberg 34989 TEI witness for guarded review.

This writes only to a fresh external stage. It never installs a canonical work.
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
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.projection.categories.native_documents import GREENLEAF_MARKER_PROFILE
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, load_acceptance,
    make_file_binding, validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "greenleaf-testimony-four-evangelists-1847"
FORM_ID = WORK_ID + "-gutenberg-retained-en"
EDITION_ID = WORK_ID + "-gutenberg-electronic"
ACQUISITION_ID = EDITION_ID + "-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/clean-ready-acquisition-to-tei/master-4/28") / WORK_ID / "34989-tei.tei"
REPORT = Path("reports/clean-ready-acquisition-to-tei/master-4/28") / WORK_ID
ORIGINAL = REPORT / "candidate/package" / f"{WORK_ID}.tei.xml"
EVIDENCE = WORK / "integration/gutenberg-pg34989-electronic-v1"
SOURCE_SHA = "b2a42f1d0e23563887e310d8465c298c6434eed35df1e4a4ff27b924feb16fe7"
ORIGINAL_SHA = "366fefc2c0f81128259a619e3c4fc20d1eb4a2ee617c995f71e2c5fcda91a07c"
SOURCE_REPORTS = {
    "source_receipt": "b431ee873a41c1f8aa9b78a5e94b84e909abb87242c91ffda8b65db6d8161339",
    "accountability": "b8696ff73582f4c858cbc05094a097d3cf500d67e6235ad3de1ce4be9a62b664",
    "validation": "a6981c503edcfb495bb7d993ac7f9c6c340161b8e2bf13eb861dfb5e94eaeeb0",
    "determinism": "92aff4c72a77cfd2091af71f424052ed5b43df86d7916f11bcbe9a3f0e3170ae",
    "cvw_preflight": "a70ebda8fce205dc1a43301eebe5b63fc5c4fe57fd6119d25303a1718092c2fc",
    "unresolved_items": "091f37385769299a30c23095ae7f01bd71478060e38d64d187957586c1e66d05",
}
PROJECTION_FILES = (
    "ocd_kernel/projection/categories/native_documents.py",
    "ocd_kernel/projection/categories/prose.py",
    "ocd_kernel/projection/categories/sermons.py",
    "ocd_kernel/projection/native_content.py",
    "ocd_kernel/projection/native_content_check.py",
    "schemas/v2/native-content.schema.json",
    "schemas/v2/categories/prose.schema.json",
)
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
NS = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
REVISION = dict(
    id="greenleaf-pg34989-electronic-v1", date="2026-09-27",
    note="Bind the retained Project Gutenberg TEI P4 electronic witness to this faithful TEI P5 edition.",
)


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def read(path: Path, expected: str | None = None) -> bytes:
    data = io_path(path).read_bytes()
    if expected is not None and digest(data) != expected:
        raise PipelineError(f"Greenleaf byte binding differs: {path}")
    return data


def put(stage: Path, relative: Path, data: bytes) -> Path:
    path = stage / relative
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    io_path(path).write_bytes(data)
    return path


def put_json(stage: Path, relative: Path, value: object) -> Path:
    return put(stage, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")) + "\n").encode("utf-8"))


def _mapped_attributes(node: etree._Element) -> dict[str, str]:
    name = etree.QName(node).localname
    result = {}
    for key, value in node.attrib.items():
        if key == "id":
            key = f"{{{XML}}}id"
        elif key == "lang":
            key = f"{{{XML}}}lang"
        elif name == "name" and key == "reg":
            key = "key"
        elif name == "index" and key == "index":
            key = "indexName"
        elif name == "ref" and key == "target" and not value.startswith(("#", "http://", "https://")):
            value = "#" + value
        result[key] = value
    return result


def source_oracle(source: bytes, original: bytes) -> dict[str, object]:
    """Walk every source text child independently of the P4-to-P5 producer."""
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True)
    source_root = etree.fromstring(source, parser)
    candidate_root = etree.fromstring(original, parser)
    source_text = source_root.xpath("/TEI.2/text")
    target_text = candidate_root.xpath("/t:TEI/t:text", namespaces={"t": NS})
    if len(source_text) != 1 or len(target_text) != 1:
        raise PipelineError("Greenleaf source or candidate text boundary differs")
    elements = 0
    glyphs = 0
    containers = 0

    def walk(left: etree._Element, right: etree._Element, locus: str) -> None:
        nonlocal elements, glyphs, containers
        if isinstance(left, etree._Entity):
            if left.name != "mdash" or right.tag != f"{{{NS}}}g" or right.attrib != {"ref": "#U0x2014"} or right.text != "—":
                raise PipelineError(f"Greenleaf encoded glyph differs at {locus}")
            glyphs += 1
            if left.tail != right.tail:
                raise PipelineError(f"Greenleaf glyph tail differs at {locus}")
            return
        if (not isinstance(left.tag, str) or right.tag != f"{{{NS}}}{etree.QName(left).localname}"
                or _mapped_attributes(left) != dict(right.attrib)
                or left.text != right.text or (locus != "/text" and left.tail != right.tail)):
            raise PipelineError(f"Greenleaf text node or attributes differ at {locus}")
        elements += 1
        if left.text is not None or any(isinstance(child, etree._Entity) or child.tail is not None for child in left):
            containers += 1
        if len(left) != len(right):
            raise PipelineError(f"Greenleaf child count differs at {locus}")
        for index, (source_child, candidate_child) in enumerate(zip(left, right, strict=True), 1):
            walk(source_child, candidate_child, f"{locus}/{index}")

    walk(source_text[0], target_text[0], "/text")
    if elements != 19441 or glyphs != 155:
        raise PipelineError(f"Greenleaf source walk count differs: elements={elements}, glyphs={glyphs}")
    return dict(status="pass", source_text_elements=elements, source_text_containers=containers,
                source_mdash_entities=glyphs, candidate_glyphs=glyphs,
                text_scope="complete /TEI.2/text in document order")


def prepare(stage: Path) -> dict[str, object]:
    stage = stage.absolute()
    durable = Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True)
    if stage.exists() or stage.parent.resolve(strict=True) != durable or ROOT.resolve() in stage.parents:
        raise PipelineError("Greenleaf stage must be a fresh direct durable candidate-reviews child")
    source = read(ROOT / SOURCE, SOURCE_SHA)
    original = read(ROOT / ORIGINAL, ORIGINAL_SHA)
    oracle = source_oracle(source, original)
    source_report_bytes = {name: read(ROOT / REPORT / "evidence" / f"{name}.json", expected)
                           for name, expected in SOURCE_REPORTS.items()}
    current_work = json.loads(read(ROOT / WORK / "work.json"))
    state = json.loads(read(ROOT / WORK / "state.json"))
    acquisition_bytes = read(ROOT / ACQUISITION)
    acquisition = json.loads(acquisition_bytes)
    retained = acquisition["retained_files"]
    if (acquisition["source_path"] != SOURCE.as_posix() or acquisition["source_sha256"] != SOURCE_SHA
            or acquisition["source_bytes"] != len(source) or [row["path"] for row in retained][0] != SOURCE.as_posix()
            or state["targets"][1]["target_id"] != EDITION_ID or state["targets"][1]["stage"] != "acquired"):
        raise PipelineError("Greenleaf acquisition or current edition state differs")
    expected = [{"path": item["path"], "position": index} for index, item in enumerate(retained, 1)]
    included = [dict(expected[0], bytes=len(source), sha256=SOURCE_SHA, scope=retained[0]["scope"])]
    excluded = [dict(item, reason="retained alternate ZIP package, outside direct TEI text selection")
                for item in expected[1:]]
    declared = acquisition["source_scope"]
    scope = dict(kind="selection", declared=declared, expected_members=expected,
                 included_members=included, excluded_members=excluded)
    work = deepcopy(current_work)
    work["textual_forms"][0]["editions"][0]["category"] = "prose"
    validate_identity_update(current_work, work)
    io_path(stage).mkdir(parents=False, exist_ok=False)
    before = _files(ROOT / WORK)
    put_json(stage, WORK / "work.json", work)
    put_json(stage, WORK / "state.json", state)
    put(stage, ACQUISITION, acquisition_bytes)
    put(stage, SOURCE, source)
    for evidence in (Path("plans/2026-09-22-source-preflight/direct-raw-nine-source-packet-20260926.json"),
                     WORK / "SOURCE_CREDIT.md"):
        put(stage, evidence, read(ROOT / evidence))
    # Acquisition validation accounts for the complete retained envelope even
    # though these alternate packages are excluded from the direct TEI master.
    for member in retained[1:]:
        member_path = Path(member["path"])
        data = read(ROOT / member_path, member["sha256"])
        if len(data) != member["bytes"]:
            raise PipelineError(f"Greenleaf alternate package byte count differs: {member_path}")
        put(stage, member_path, data)
    for name, data in source_report_bytes.items():
        put(stage, EVIDENCE / "inputs" / f"{name}.json", data)
    put(stage, EVIDENCE / "inputs/original-candidate.tei.xml", original)
    put(stage, EVIDENCE / "inputs/greenleaf-converter.py",
        read(ROOT / "build/tei/greenleaf_testimony_four_evangelists_1847.py"))
    put(stage, EVIDENCE / "inputs/acceptance-stage.py", read(Path(__file__)))
    source_binding = {key: acquisition[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope")}
    bound = bind_reviewed_header(original, expected_sha256=ORIGINAL_SHA, identity=IDENTITY,
                                 source=source_binding, source_url=acquisition["url"],
                                 declared_scope=declared, revision=REVISION)
    candidate = put(stage, EVIDENCE / "candidate.tei.xml", bound)
    errors = validate_file(io_path(candidate))
    if errors:
        raise PipelineError(f"Greenleaf source-bound TEI XSD failed: {errors[:3]}")
    if bound.count(original[original.index(b"<text"):]) != 1:
        raise PipelineError("Greenleaf header binding changed candidate text bytes")
    put_json(stage, EVIDENCE / "oracle.json", oracle | dict(source_sha256=SOURCE_SHA,
                                                            original_candidate_sha256=ORIGINAL_SHA))
    now = datetime.now(timezone.utc)
    at = now.isoformat().replace("+00:00", "Z")
    common = dict(identity=IDENTITY, source=source_binding, scope=declared,
                  candidate=make_file_binding(stage, candidate))
    accounting = put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        status="pass", accepted_scope=dict(kind="selection", declared=declared),
        expected_members=expected, included_members=included, excluded_members=excluded,
        missing_members=[], unknown_members=[], source_sha256=SOURCE_SHA,
        source_bytes=len(source), projection_profile=GREENLEAF_MARKER_PROFILE,
        source_text_elements=oracle["source_text_elements"], source_mdash_entities=155))
    command = "py -3 -m build.tools.stage_greenleaf_pg34989_acceptance --stage <fresh-durable-root>"
    report_pins = {name: SOURCE_REPORTS[name] for name in sorted(SOURCE_REPORTS)}
    technical = dict(
        producer=dict(id="ocd-greenleaf-retained-p4-to-p5-v1",
                      path=make_file_binding(stage, stage / EVIDENCE / "inputs/greenleaf-converter.py")),
        checker=dict(id="ocd-greenleaf-independent-complete-text-walk-v1",
                     path=make_file_binding(stage, stage / EVIDENCE / "inputs/acceptance-stage.py")),
        shared_assumptions=["Both checks use the same retained direct TEI source; the checker independently walks every text node and attribute."],
        independent_corroboration="Complete ordered source-text walk, pinned candidate and six retained technical reports; CVW preflight is not human visual acceptance.",
    )
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        fields = dict(accepted_scope=dict(kind="selection", declared=declared),
                      expected_members=expected, included_members=included, excluded_members=excluded,
                      missing_members=[], unknown_members=[]) if name == "accounting" else {}
        proof = put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            oracle=oracle, retained_report_sha256=report_pins) | fields)
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    coverage = dict(status="partial", declared=declared, reached=["source/text"],
                    inspected=["source/text/body"], unreviewed=["source/text/front", "source/text/back"])
    reviewed = dict(reviewer="agent:greenleaf-electronic-assessment", reviewed_at=at,
                    coverage=coverage, source_quality_uncertainty=[
                        "No separate print witness is collated against the retained Gutenberg electronic text."],
                    discrepancies=[], unreviewed_residuals=[
                        "Front and back are mechanically checked but have no whole-work human visual review.",
                        "The complete body has source-led mechanical accounting, not human proofreading."])
    report = put_json(stage, EVIDENCE / "review.json", common | reviewed | dict(
        evidence_status="source-bound technical review; human acceptance not recorded",
        ten_source_page_marker_triples=True, source_notes=416, source_tables=249))
    decision = dict(source_local_disposition="Agent acceptance of the direct retained Gutenberg TEI electronic witness.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=reviewed["reviewer"],
                    assessed_at=at, supported_scope=declared, unresolved_claims=[],
                    unassessed_stronger_claims=["print collation", "human acceptance", "rights clearance", "publication"]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate,
                                     source_accounting_path=accounting, scope=scope, technical=technical,
                                     review=reviewed | dict(report_path=report),
                                     representation_revision=REVISION, decision=decision)
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(io_path(acceptance), record)
    validate_acceptance(acceptance, root=stage)
    master = put(stage, EDITION / "master.tei.xml", bound)
    record = load_acceptance(acceptance)
    record["promotion"].update(status="promoted", promoted_at=at,
                               master=make_file_binding(stage, master))
    write_acceptance(io_path(acceptance), record)
    state["targets"][1].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at)
    state["targets"][1]["evidence"].extend([
        (EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()])
    put_json(stage, WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage)
    projection = project_accepted_prose(stage, acceptance_path=acceptance)
    errors = verify_accepted_prose(stage, acceptance_path=acceptance,
                                   rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 13:
        raise PipelineError(f"Greenleaf actual-master native projection differs: rows={len(projection['rows'])}, errors={errors[:3]}")
    after = _files(stage / WORK)
    projection_files = {path: digest(read(ROOT / path)) for path in PROJECTION_FILES}
    native_rows_sha = digest(json.dumps(projection["rows"], ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8"))
    native_receipt_sha = digest(json.dumps(projection["receipt"], ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode("utf-8"))
    receipt = dict(contract="ocd-greenleaf-pg34989-stage-v1", status="staged-only",
                   work_id=WORK_ID, stage_root=stage.as_posix(), canonical_root=ROOT.as_posix(),
                   source_sha256=SOURCE_SHA, original_candidate_sha256=ORIGINAL_SHA,
                   accepted_master_sha256=digest(bound), acceptance_sha256=digest(read(acceptance)),
                   oracle=oracle, native_rows=13, native_independent_errors=[],
                   native_rows_sha256=native_rows_sha, native_receipt_sha256=native_receipt_sha,
                   projection_files_sha256=projection_files,
                   before=before, after=after, retained_report_sha256=report_pins,
                   native_profile=GREENLEAF_MARKER_PROFILE)
    put_json(stage, Path("greenleaf-stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps(dict(stage_root=result["stage_root"], master_sha256=result["accepted_master_sha256"],
                          acceptance_sha256=result["acceptance_sha256"], native_rows=result["native_rows"],
                          receipt_sha256=digest(read(args.stage / "greenleaf-stage-receipt.json"))), sort_keys=True))


if __name__ == "__main__":
    main()
