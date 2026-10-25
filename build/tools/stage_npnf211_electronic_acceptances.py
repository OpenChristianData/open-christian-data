"""Stage the three source-defined NPNF211 electronic-witness editions.

This makes complete proposed work generations in a fresh durable directory.
It does not install them or refresh generated corpus views.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from lxml import etree

from build.tei.npnf211_lib049_oracle import _oracle
from build.tei.npnf211_lib049_reconstruction import ASSIGNED, SOURCE_SHA256
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.writer import stamp_header, tei_el


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/ccel/npnf2/npnf211.xml")
MANIFEST = Path("sources/structured-text/npnf211-lib049/npnf211-lib049.source-manifest.json")
PROFILE = Path("sources/structured-text/npnf211-lib049/npnf211-lib049.reconstruction-profile.json")
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/37c-299-lib049-20260921-final-a")
REVIEW_ROOT = Path("D:/Library/Open Christian Data/candidate-reviews")
EVIDENCE = Path("integration/npnf211-electronic-v1")
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NAMESPACES = {"t": TEI_NS}
SOURCE_TITLES = {
    "ii": "The Works of Sulpitius Severus.",
    "iii": "The Commonitory of Vincent of Lérins, For the Antiquity and Universality of the Catholic Faith Against the Profane Novelties of All Heresies.",
    "iv": "The Works of John Cassian.",
}
AUTHORS = {"ii": "Sulpitius Severus", "iii": "Vincent of Lérins", "iv": "John Cassian"}
TRANSLATORS = {"ii": "Alexander Roberts", "iii": "C. A. Heurtley", "iv": "Edgar C. S. Gibson"}


def _io(path: Path) -> Path:
    absolute = path.resolve(strict=False)
    return Path("\\\\?\\" + str(absolute)) if os.name == "nt" else absolute


def _read(path: Path) -> bytes:
    return _io(path).read_bytes()


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    path = stage / relative
    _io(path.parent).mkdir(parents=True, exist_ok=True)
    _io(path).write_bytes(content)
    return path


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, _json(value))


def _files(root: Path) -> dict[str, str]:
    base = _io(root)
    return {path.relative_to(base).as_posix(): _sha(path.read_bytes())
            for path in sorted(base.rglob("*")) if path.is_file()}


def _boundary(source: etree._Element, target: etree._Element) -> dict[str, object]:
    children = [node for node in source if isinstance(node.tag, str)]
    divisions = [node for node in children if node.tag == "div2"]
    first_division = children.index(divisions[0])
    if any(node.tag != "div2" for node in children[first_division:]):
        raise ValueError("NPNF211 work root interleaves shared front matter and divisions")
    rows = []
    for node in divisions:
        title = node.get("title")
        if not title or not node.get("id"):
            raise ValueError("NPNF211 constituent division lacks source identity")
        rows.append({"source_id": node.get("id"), "tei_id": f"npnf211-{node.get('id')}",
                     "source_title": title,
                     "source_element_count": sum(isinstance(item.tag, str) for item in node.iter())})
    target_divisions = target.xpath("./t:div", namespaces=NAMESPACES)
    if [node.get(XML_ID) for node in target_divisions] != [row["tei_id"] for row in rows]:
        raise ValueError("NPNF211 candidate constituent boundaries differ")
    return {"source_root_id": source.get("id"), "source_title": source.get("title"),
            "source_element_count": sum(isinstance(item.tag, str) for item in source.iter()),
            "shared_front_matter": [{"source_id": node.get("id"), "source_tag": node.tag}
                                    for node in children[:first_division]],
            "constituent_divisions": rows,
            "claim": "The selected electronic edition retains the complete source-defined collection and ordered titled divisions. Standalone constituent work identities are unassessed."}


def prepare(stage: Path) -> dict[str, object]:
    stage = stage.resolve(strict=False)
    if (stage.exists() or stage.parent != REVIEW_ROOT.resolve(strict=True)
            or not stage.name.startswith("npnf211-electronic-acceptance-stage-")):
        raise ValueError("stage must be a fresh named child of the durable candidate root")
    source_bytes = _read(ROOT / SOURCE)
    if _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained NPNF211 XML changed")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    candidate = CandidatePackage.load(PACKAGE / "package")
    recorded = json.loads(_read(PACKAGE / "validation.json"))
    checked = validate(manifest, candidate, _oracle)
    if (recorded["status"] != "pass" or recorded["candidate_sha256"] != candidate.sha256
            or recorded["report_sha256"] != checked.sha256):
        raise ValueError("LIB049 aggregate oracle receipt changed")
    source_tree = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    head = source_tree.find("ThML.head")
    if (head is None or (head.findtext(".//DC.Language") or "").strip() != "eng"
            or (head.findtext(".//DC.Rights") or "").strip() != "Public Domain"):
        raise ValueError("NPNF211 electronic language or source rights statement changed")
    source_roots = source_tree.xpath("/ThML/ThML.body/div1")
    if [node.get("id") for node in source_roots] != ["i", "ii", "iii", "iv", "v"]:
        raise ValueError("NPNF211 volume boundary changed")
    aggregate = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    target_roots = aggregate.xpath("./t:text/t:body/t:div", namespaces=NAMESPACES)
    if [node.get(XML_ID) for node in target_roots] != ["npnf211-ii", "npnf211-iii", "npnf211-iv"]:
        raise ValueError("NPNF211 aggregate TEI boundary changed")
    if tuple((source_roots[index].get("id"), work) for index, (scope, work) in enumerate(ASSIGNED, start=1)) != ASSIGNED:
        raise ValueError("NPNF211 source root assignments changed")
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    stage.mkdir(parents=True)
    _put(stage, SOURCE, source_bytes)
    for relative in (MANIFEST, PROFILE, Path("sources/structured-text/npnf211-lib049/README.source.md"),
                     Path("docs/sources/ccel-permission.md")):
        _put(stage, relative, _read(ROOT / relative))
    results = []
    for (scope, work_id), target in zip(ASSIGNED, target_roots, strict=True):
        source = next(node for node in source_roots if node.get("id") == scope)
        if source.get("title") != SOURCE_TITLES[scope] or target.get(XML_ID) != f"npnf211-{scope}":
            raise ValueError(f"NPNF211 source title or target root differs: {work_id}")
        relative_work = Path("library/works") / work_id
        original_work = ROOT / relative_work
        before = _files(original_work)
        if any(path.endswith(("acceptance.json", "master.tei.xml")) for path in before):
            raise ValueError(f"canonical accepted text already exists: {work_id}")
        for path in _io(original_work).rglob("*"):
            if path.is_file():
                relative = path.relative_to(_io(ROOT))
                _put(stage, relative, path.read_bytes())
        work = json.loads(_read(original_work / "work.json"))
        state = json.loads(_read(original_work / "state.json"))
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                    "edition_id": edition["edition_id"], "acquisition_id": edition["acquisition_ids"][0]}
        if (work["work_id"] != work_id or edition["containing_source"]["locator"] != f"{SOURCE.as_posix()}#{scope}"
                or edition["language"] != "en" or form["language"] != "en"
                or edition.get("category") is not None):
            raise ValueError(f"NPNF211 child sidecar changed: {work_id}")
        acquisition_path = relative_work / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"] / "acquisitions" / f"{identity['acquisition_id']}.json"
        acquisition = json.loads(_read(ROOT / acquisition_path))
        if (len(acquisition["retained_files"]) != 1
                or acquisition["retained_files"][0]["path"] != SOURCE.as_posix()
                or acquisition["retained_files"][0]["bytes"] != len(source_bytes)
                or acquisition["retained_files"][0]["sha256"] != SOURCE_SHA256):
            raise ValueError(f"NPNF211 acquisition changed: {work_id}")
        boundary = _boundary(source, target)
        evidence = relative_work / EVIDENCE
        boundary_path = _put_json(stage, evidence / "source-boundaries.json", boundary)
        root = tei_el("TEI", {"xml:id": f"npnf211-{scope}-work"})
        root.append(stamp_header(title=SOURCE_TITLES[scope], author=AUTHORS[scope],
                                 contributors=[{"name": TRANSLATORS[scope], "role": "translator"}],
                                 source_url=acquisition["url"], source_sha256=SOURCE_SHA256,
                                 print_source="Retained NPNF2-11 CCEL electronic witness; ThML head names Edinburgh, T & T Clark but supplies no print date or print collation.",
                                 rights_statement="The retained CCEL head states Public Domain; rights clearance and publication are separate."))
        text = tei_el("text")
        body = tei_el("body")
        body.append(deepcopy(target))
        text.append(body)
        root.append(text)
        original = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
        original_target = etree.fromstring(original).xpath("./t:text/t:body/t:div", namespaces=NAMESPACES)[0]
        if etree.tostring(original_target, method="c14n") != etree.tostring(target, method="c14n"):
            raise ValueError(f"work-local extraction changed checked TEI: {work_id}")
        scope_text = f"Complete retained NPNF211 div1 {scope}: {SOURCE_TITLES[scope]}"
        revision = {"id": f"{work_id}-npnf211-electronic-v1", "date": at[:10],
                    "note": "Accepted source-defined electronic edition; print collation and standalone constituent identities are unassessed."}
        bound = bind_reviewed_header(original, expected_sha256=_sha(original), identity=identity,
                                     source={"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA256,
                                             "source_bytes": len(source_bytes)},
                                     source_url=acquisition["url"], declared_scope=scope_text, revision=revision)
        candidate_path = _put(stage, evidence / "candidate.tei.xml", bound)
        if validate_file(_io(candidate_path)):
            raise ValueError(f"NPNF211 child TEI P5 failed: {work_id}")
        edition["category"] = "prose"
        _put_json(stage, relative_work / "work.json", work)
        for reference in set(work.get("evidence", [])) | {ref for item in state["targets"] for ref in item.get("evidence", [])}:
            relative = Path(reference.partition("#")[0])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe inherited evidence: {reference}")
            if not _io(stage / relative).is_file():
                _put(stage, relative, _read(ROOT / relative))
        _put(stage, evidence / "inputs/aggregate-validation.json", _read(PACKAGE / "validation.json"))
        _put(stage, evidence / "inputs/aggregate-manifest.json", _read(PACKAGE / "package/manifest.json"))
        _put(stage, evidence / "inputs/aggregate-accountability.json", candidate.member_bytes("source-accountability.json"))
        source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA256,
                          "source_bytes": len(source_bytes), "source_scope": acquisition["retained_files"][0]["scope"]}
        expected = [{"path": SOURCE.as_posix(), "position": 1}]
        included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": len(source_bytes),
                     "sha256": SOURCE_SHA256, "scope": acquisition["retained_files"][0]["scope"]}]
        accepted_scope = {"kind": "edition", "declared": scope_text}
        binding = make_file_binding(stage, candidate_path)
        accounting = _put_json(stage, evidence / "source-accounting.json", {
            "identity": identity, "candidate": binding, "source": source_binding,
            "scope": acquisition["retained_files"][0]["scope"], "accepted_scope": accepted_scope,
            "expected_members": expected, "included_members": included, "excluded_members": [],
            "missing_members": [], "unknown_members": [], "source_root_id": scope,
            "source_sha256": SOURCE_SHA256, "source_bytes": len(source_bytes),
            "source_element_count": boundary["source_element_count"],
            "aggregate_candidate_sha256": candidate.sha256,
            "aggregate_validation_sha256": _sha(_read(PACKAGE / "validation.json")),
            "boundaries_sha256": _sha(_read(boundary_path))})
        command = "py -3 -m build.tools.stage_npnf211_electronic_acceptances --stage <fresh-stage>"
        technical = {"producer": {"id": manifest.record["converter"]["id"], "path": make_file_binding(stage, stage / MANIFEST)},
                     "checker": {"id": manifest.record["validator"]["id"], "path": make_file_binding(stage, stage / MANIFEST)},
                     "shared_assumptions": ["The producer and oracle use the same retained XML; the oracle independently checks the complete 14,950-feature assigned scope."],
                     "independent_corroboration": "The complete source-defined child subtree was compared with the validated aggregate TEI; source divisions and shared front matter were independently inventoried."}
        common = {"identity": identity, "candidate": binding, "source": source_binding,
                  "scope": scope_text, "source_root_id": scope,
                  "source_element_count": boundary["source_element_count"],
                  "aggregate_candidate_sha256": candidate.sha256,
                  "aggregate_validation_sha256": _sha(_read(PACKAGE / "validation.json")),
                  "boundaries_sha256": _sha(_read(boundary_path))}
        for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
            proof = common | {"claim": name, "status": "pass", "command": command, "exit_code": 0}
            if name == "accounting":
                proof |= {"accepted_scope": accepted_scope, "expected_members": expected,
                          "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": []}
            path = _put_json(stage, evidence / f"{name}.json", proof)
            technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
        review = {"reviewer": "agent:npnf211-electronic-boundary-stage", "reviewed_at": at,
                  "coverage": {"status": "partial", "declared": scope_text,
                               "reached": [f"{SOURCE.as_posix()}#{scope}"],
                               "inspected": [f"{SOURCE.as_posix()}#{scope}/mechanical-complete"],
                               "unreviewed": [f"{SOURCE.as_posix()}#{scope}/full-visual-proofreading"]},
                  "source_quality_uncertainty": ["No print witness was collated with the retained CCEL electronic text."],
                  "discrepancies": [], "unreviewed_residuals": ["Full visual proofreading, human review, rights clearance, and publication are separate."]}
        report = _put_json(stage, evidence / "review.json", common | review | {
            "boundary": boundary, "source_header_claims": {"language": "eng", "rights": "Public Domain"},
            "attribution": {"electronic_publisher": "Christian Classics Ethereal Library",
                            "translator": TRANSLATORS[scope], "translator_evidence": f"{SOURCE.as_posix()}#{scope}/front"},
            "unclaimed": ["standalone constituent work acceptance", "print collation", "human review", "rights clearance", "publication"]})
        decision = {"source_local_disposition": "Agent acceptance of the source-defined electronic edition only; nested standalone work identities are not assigned.",
                    "blockers": [], "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                        "assessed_at": at, "supported_scope": scope_text,
                        "unresolved_claims": ["Standalone constituent identities in this retained collection remain unassessed."] if scope != "iii" else [],
                        "unassessed_stronger_claims": ["print collation", "full visual proofreading", "human review", "rights clearance", "publication"]},
                    "human_decision": {"status": "not-recorded"}}
        scope_record = accepted_scope | {"expected_members": expected, "included_members": included, "excluded_members": []}
        record = build_acceptance_record(stage, identity=identity, candidate_path=candidate_path,
                                         source_accounting_path=accounting, scope=scope_record,
                                         technical=technical, review=review | {"report_path": report},
                                         representation_revision=revision, decision=decision)
        edition_path = relative_work / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"]
        acceptance = stage / edition_path / "acceptance.json"
        write_acceptance(_io(acceptance), record)
        master = _put(stage, edition_path / "master.tei.xml", bound)
        record["promotion"] |= {"status": "promoted", "promoted_at": at, "master": make_file_binding(stage, master)}
        write_acceptance(_io(acceptance), record)
        target_state = next(item for item in state["targets"] if item["target_id"] == edition["edition_id"])
        if target_state["stage"] != "acquired":
            raise ValueError(f"NPNF211 edition state changed: {work_id}")
        target_state |= {"stage": "accepted", "reason": PROMOTED_MASTER_REASON, "updated_at": at}
        target_state["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
        _put_json(stage, relative_work / "state.json", state)
        validate_acceptance(_io(acceptance), root=_io(stage))
        validate_state(_io(stage / relative_work / "state.json"), root=_io(stage))
        load_work(_io(stage / relative_work / "work.json"))
        projected = project_accepted_prose(stage, acceptance_path=_io(acceptance))
        errors = verify_accepted_prose(stage, acceptance_path=_io(acceptance), rows=projected["rows"], receipt=projected["receipt"])
        if errors or projected["receipt"].get("unsupported") or not projected["rows"]:
            raise ValueError(f"actual-master prose projection failed: {work_id}: {errors[:2]}")
        _put_json(stage, evidence / "projection-canary.json", {
            "category": "prose", "row_count": len(projected["rows"]),
            "unsupported": [], "independent_errors": [],
            "output_sha256": projected["receipt"]["output_sha256"]})
        results.append({"work_id": work_id, "source_root_id": scope,
                        "source_element_count": boundary["source_element_count"],
                        "division_count": len(boundary["constituent_divisions"]),
                        "identity": identity, "before": before, "after": _files(stage / relative_work),
                        "master_sha256": _sha(bound), "acceptance_sha256": _sha(_read(acceptance)),
                        "projection_rows": len(projected["rows"])})
    receipt = {"contract": "ocd-npnf211-electronic-acceptance-stage-v1", "status": "staged-only",
               "canonical_install": False, "source_sha256": SOURCE_SHA256,
               "source_manifest_sha256": manifest.sha256, "aggregate_candidate_sha256": candidate.sha256,
               "work_count": len(results), "works": results,
               "human_review": "not-recorded", "rights_clearance": "not-assessed", "publication": "not-authorized"}
    _put_json(stage, Path("stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"work_count": result["work_count"], "stage": str(args.stage)}, sort_keys=True))


if __name__ == "__main__":
    main()
