"""Stage Edwards's Greek-parent and nested-index correction externally."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from lxml import etree

from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.commentary import (
    project_accepted_commentary,
    verify_accepted_commentary,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

from build.tei.expositors_bible_lib035_readable_edwards_index_v2_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = Path("D:/Library/Open Christian Data/candidate-reviews")
WORK = Path("library/works/expositors-bible--thomas-charles-edwards")
MEMBER = "edwards-tc-expositorheb"
SOURCE = Path("raw/ccel/expositors-bible/edwards_tc_expositorheb.xml")
SOURCE_SHA = "6da565a2393cb74c75f98589650072f05e0f9780855b5472fe6954810f926fb3"
AUTHORITY = Path("sources/commentaries/expositors-bible/readable-edwards-index-v2/edwards-tc-expositorheb/source-manifest.json")
MANIFEST_SHA = "e3dc4b8dae5603629f272377d040e0e2a17fc5ae801f2bc3f9f875f308d10d7e"
CANDIDATE_ROOT = EXTERNAL / "expositors-lib035-edwards-index-v2-candidate-20260928-v2"
PACKAGE_SHA = "6a3bdb51ae48093fe11d970bb93a3f0b5b07d30e59423403049ecf075267ae74"
VALIDATION_SHA = "6337d753b7eeac87a1b594933bed12dae2017efa86dde5de7f80b6856d5981de"
TEI_SHA = "6deabdb3cd24394cce666a30c254c3afe5d5dea28a98d6678342c80031ade7b4"
OLD_MASTER_SHA = "95774d47608c93d2666a19d434b1015a6900f720925deaf2071d6baf4a49c90d"
OLD_ACCEPTANCE_SHA = "8e171071198d6ffc7f3ac31676a7a1d5e263fddf3e06803b86ae373eeb2fa517"
OLD_PACKAGE_TEI_SHA = "5803b5be8b32c86fed6619af847464bda245a796a9ca2a4dc7a3478c51672512"
EVIDENCE = WORK / "integration/edwards-tc-expositorheb-readable-electronic-index-v2"
RECEIPT = "expositors-edwards-nested-index-repair-stage-receipt.json"
CONTRACT = "ocd-expositors-edwards-nested-index-repair-stage-v1"
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CHANGE_TYPES = {
    f"{MEMBER}-xxii.i-p0.2": "source-greek",
    f"{MEMBER}-feature-002857": "source-index",
    f"{MEMBER}-feature-003310": "source-index",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Edwards index repair input changed: {path}")
    return content


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    path = stage / relative
    _io_path(path).parent.mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(content)
    return path


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, (json.dumps(value, sort_keys=True, ensure_ascii=False,
                                            separators=(",", ":")) + "\n").encode("utf-8"))


def _source_only_delta(old: bytes, new: bytes) -> list[dict[str, object]]:
    previous = etree.fromstring(old).find(NS + "text")
    current = etree.fromstring(new).find(NS + "text")
    if previous is None or current is None:
        raise ValueError("Edwards TEI text missing")
    before, after = list(previous.iter()), list(current.iter())
    if len(before) != len(after):
        raise ValueError("Edwards TEI element cardinality changed")
    changed: list[dict[str, object]] = []
    for ordinal, (left, right) in enumerate(zip(before, after, strict=True), 1):
        if (left.text, left.tail) != (right.text, right.tail):
            raise ValueError(f"Edwards text or tail changed at {ordinal}")
        if left.tag == right.tag and left.attrib == right.attrib:
            continue
        if not (left.tag == NS + "quote" and right.tag == NS + "div"
                and left.get("type") == "source-div"
                and right.get("type") == CHANGE_TYPES.get(right.get(XML_ID))
                and left.get(XML_ID) == right.get(XML_ID)
                and right.get(XML_ID) in CHANGE_TYPES
                and set(left.attrib) == set(right.attrib)):
            raise ValueError(f"Edwards unapproved TEI change at {ordinal}")
        changed.append({"ordinal": ordinal, "tei_id": right.get(XML_ID),
                        "before": "quote/source-div", "after": "div/" + right.get("type")})
    if [row["tei_id"] for row in changed] != list(CHANGE_TYPES):
        raise ValueError("Edwards expected Greek parent and exactly two source index corrections")
    return changed


def prepare(stage: Path) -> dict[str, object]:
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or ROOT.resolve() in stage.resolve().parents:
        raise ValueError("Edwards repair requires a fresh external stage")
    before = _files(ROOT / WORK)
    if len(before) != 23:
        raise ValueError("Edwards accepted work preimage changed")
    work = json.loads(_read(ROOT / WORK / "work.json"))
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    edition_path = WORK / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"]
    acquisition_path = edition_path / "acquisitions" / (edition["acquisition_ids"][0] + ".json")
    acquisition = json.loads(_read(ROOT / acquisition_path))
    retained = acquisition["retained_files"]
    if (len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA or retained[0]["bytes"] != len(_read(ROOT / SOURCE, SOURCE_SHA))):
        raise ValueError("Edwards retained acquisition changed")
    old_acceptance_path = edition_path / "acceptance.json"
    old_master_path = edition_path / "master.tei.xml"
    old_acceptance = json.loads(_read(ROOT / old_acceptance_path, OLD_ACCEPTANCE_SHA))
    old_master = _read(ROOT / old_master_path, OLD_MASTER_SHA)
    if (old_acceptance["identity"]["edition_id"] != edition["edition_id"]
            or old_acceptance["promotion"]["master"]["sha256"] != OLD_MASTER_SHA
            or old_acceptance["decision"]["human_decision"]["status"] != "not-recorded"):
        raise ValueError("Edwards prior acceptance identity changed")
    manifest = SourceManifest.load(ROOT / AUTHORITY, repository_root=ROOT)
    manifest.verify()
    candidate = CandidatePackage.load(CANDIDATE_ROOT / MEMBER)
    report = validate(manifest, candidate, _oracle)
    if (manifest.sha256 != MANIFEST_SHA or candidate.sha256 != PACKAGE_SHA
            or _sha(CANDIDATE_ROOT / (MEMBER + ".validation.json")) != VALIDATION_SHA
            or sha256(candidate.member_bytes("content.tei.xml")).hexdigest() != TEI_SHA
            or report.status != "pass"):
        raise ValueError("Edwards corrected source package differs")
    old_package_tei = _read(ROOT / WORK / "integration/edwards-tc-expositorheb-readable-electronic-v1/inputs/package/content.tei.xml", OLD_PACKAGE_TEI_SHA)
    raw_delta = _source_only_delta(old_package_tei, candidate.member_bytes("content.tei.xml"))
    stage.mkdir(parents=True)
    for relative in before:
        _put(stage, WORK / relative, _read(ROOT / WORK / relative, before[relative]))
    dependencies = {SOURCE, AUTHORITY,
                    Path("build/tei/expositors_bible_lib035_readable_edwards_index_v2.py"),
                    Path("build/tei/expositors_bible_lib035_readable_edwards_index_v2_oracle.py"),
                    Path("sources/commentaries/expositors-bible/ccel-permission.md")}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    inherited_state = json.loads(_read(ROOT / WORK / "state.json"))
    for reference in set(work.get("evidence", [])) | {
        item for target in inherited_state["targets"] for item in target.get("evidence", [])
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Edwards unsafe inherited evidence: {reference}")
        if not relative.is_relative_to(WORK):
            dependencies.add(relative)
    for relative in sorted(dependencies):
        _put(stage, relative, _read(ROOT / relative))
    for name in candidate.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, candidate.member_bytes(name))
    _put(stage, EVIDENCE / "inputs/validation.json", _read(CANDIDATE_ROOT / (MEMBER + ".validation.json"), VALIDATION_SHA))
    identity = old_acceptance["identity"]
    revision = {"id": "edwards-tc-expositorheb-ccel-electronic-index-v2",
                "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Preserve the Greek index wrapper as a structural division and correct two source Index containers; retain the complete electronic text and edition identity."}
    source = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
              "source_bytes": len(_read(ROOT / SOURCE, SOURCE_SHA)),
              "source_scope": retained[0]["scope"]}
    raw_candidate = candidate.member_bytes("content.tei.xml")
    derived = bind_reviewed_header(raw_candidate, expected_sha256=TEI_SHA, identity=identity,
                                   source=source, source_url=acquisition["url"],
                                   declared_scope=source["source_scope"], revision=revision)
    derived, count = re.subn(rb"(<sourceDesc>)<p>(Retained CCEL ThML electronic witness by [^<]+)</p>(<bibl)",
                             rb"\1<bibl><title>\2</title></bibl>\3", derived)
    if count != 1 or derived.split(b"</teiHeader>", 1)[1] != raw_candidate.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Edwards accepted header or text changed unexpectedly")
    accepted_delta = _source_only_delta(old_master, derived)
    if [x["tei_id"] for x in accepted_delta] != [x["tei_id"] for x in raw_delta]:
        raise ValueError("Edwards accepted master correction differs from raw candidate")
    accepted_candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(accepted_candidate)):
        raise ValueError(f"Edwards corrected P5 errors: {errors[:2]}")
    delta_file = _put_json(stage, EVIDENCE / "correction.json", {
        "contract": "ocd-expositors-index-semantic-repair-v1", "source_sha256": SOURCE_SHA,
        "prior_master_sha256": OLD_MASTER_SHA, "prior_acceptance_sha256": OLD_ACCEPTANCE_SHA,
        "source_candidate_delta": raw_delta, "accepted_master_delta": accepted_delta,
        "all_text_and_tails_identical": True, "outside_greek_parent_and_two_index_nodes_identical": True})
    common = {"identity": identity, "source": source,
              "candidate": make_file_binding(stage, accepted_candidate),
              "scope": source["source_scope"], "accepted_scope": {"kind": "edition", "declared": source["source_scope"]},
              "expected_members": old_acceptance["scope"]["expected_members"],
              "included_members": old_acceptance["scope"]["included_members"],
              "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", common | {
        "source_sha256": SOURCE_SHA, "source_bytes": source["source_bytes"],
        "source_manifest_sha256": MANIFEST_SHA, "candidate_package_sha256": PACKAGE_SHA,
        "source_feature_counts": {"elements": 3646, "comments": 10}, "unsupported_elements": 0,
        "basis": "Independent exact-source oracle plus prior/current complete TEI node comparison; only the Greek wrapper and two Index carrier tags/types changed."})
    command = "py -3 -m build.tools.stage_expositors_lib035_edwards_index_repair --stage <fresh-external-root>"
    technical = {"producer": {"id": manifest.record["converter"]["id"]},
                 "checker": {"id": manifest.record["validator"]["id"]},
                 "shared_assumptions": ["Producer and checker parse the same retained CCEL XML."],
                 "independent_corroboration": "Exact source oracle, full prior/current TEI node delta, P5 and native verifier."}
    for label in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, EVIDENCE / (label + ".json"), common | {
            "status": "pass", "command": command, "exit_code": 0, "claim": label,
            "candidate_package_sha256": PACKAGE_SHA, "source_manifest_sha256": MANIFEST_SHA,
            "validation_sha256": VALIDATION_SHA, "correction_sha256": _sha(delta_file)})
        technical[label] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    reviewed_at = _now()
    review = {"reviewer": "agent:expositors-edwards-index-repair", "reviewed_at": reviewed_at,
              "coverage": old_acceptance["review"]["coverage"],
              "source_quality_uncertainty": old_acceptance["review"]["source_quality_uncertainty"],
              "discrepancies": ["Prior master mislabeled the Greek wrapper and two Index carriers as quotations; their source hierarchy is corrected in this revision."],
              "unreviewed_residuals": old_acceptance["review"]["unreviewed_residuals"]}
    review_file = _put_json(stage, EVIDENCE / "review.json", common | review | {
        "prior_acceptance_sha256": OLD_ACCEPTANCE_SHA,
        "correction": make_file_binding(stage, delta_file)})
    decision = {"source_local_disposition": "Agent correction of the Greek wrapper and two nested/source index labels within one already accepted electronic edition.",
                "blockers": [], "human_decision": {"status": "not-recorded"},
                "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                                     "assessed_at": reviewed_at, "supported_scope": source["source_scope"],
                                     "unresolved_claims": [],
                                     "unassessed_stronger_claims": old_acceptance["decision"]["agent_assessment"]["unassessed_stronger_claims"]}}
    acceptance = build_acceptance_record(stage, identity=identity, candidate_path=accepted_candidate,
                                         source_accounting_path=accounting, scope=old_acceptance["scope"],
                                         technical=technical, review=review | {"report_path": review_file},
                                         representation_revision=revision, decision=decision)
    acceptance_path = stage / old_acceptance_path
    write_acceptance(_io_path(acceptance_path), acceptance)
    master_path = _put(stage, old_master_path, derived)
    acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                   master=make_file_binding(stage, master_path))
    write_acceptance(_io_path(acceptance_path), acceptance)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_commentary(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_commentary(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                         rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 21:
        raise ValueError(f"Edwards corrected native projection differs: {errors[:2]}")
    after = _files(stage / WORK)
    expected_additions = {x for x in after if x.startswith("integration/edwards-tc-expositorheb-readable-electronic-index-v2/")}
    if (len(after) != len(before) + len(expected_additions)
            or any(after[x] != before[x] for x in before if x not in {
                old_acceptance_path.relative_to(WORK).as_posix(), old_master_path.relative_to(WORK).as_posix()})):
        raise ValueError("Edwards repair work generation changed unrelated files")
    dependencies_map = {k: v for k, v in _files(stage).items()
                        if not k.startswith(WORK.as_posix() + "/") and k != RECEIPT}
    receipt = {"contract": CONTRACT, "status": "staged-only", "installation": "not-performed",
               "rights": "not-assessed", "canonical_root": ROOT.as_posix(), "stage_root": stage.as_posix(),
               "dependencies": dependencies_map,
               "work": {"work_id": WORK.name, "work_path": WORK.as_posix(),
                        "before": before, "after": after, "source_path": SOURCE.as_posix(),
                        "source_sha256": SOURCE_SHA, "prior_master_sha256": OLD_MASTER_SHA,
                        "prior_acceptance_sha256": OLD_ACCEPTANCE_SHA,
                        "new_master_sha256": _sha(master_path),
                        "new_acceptance_sha256": _sha(acceptance_path),
                        "source_manifest_sha256": MANIFEST_SHA,
                        "candidate_package_sha256": PACKAGE_SHA,
                        "correction_sha256": _sha(delta_file), "native_rows": 21}}
    _put_json(stage, Path(RECEIPT), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"status": result["status"], "work_id": result["work"]["work_id"],
                      "before": len(result["work"]["before"]), "after": len(result["work"]["after"]),
                      "master_sha256": result["work"]["new_master_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
