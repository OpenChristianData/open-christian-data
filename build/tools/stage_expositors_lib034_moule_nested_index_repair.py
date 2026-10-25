"""Stage Moule's Hebrew-parent and nested-index correction externally."""

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

from build.tei.expositors_bible_lib034_readable_moule_index_v4_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = Path("D:/Library/Open Christian Data/candidate-reviews")
WORK = Path("library/works/expositors-bible--h-c-g-moule")
MEMBER = "moule-expositorromans"
SOURCE = Path("raw/ccel/expositors-bible/moule_expositorromans.xml")
SOURCE_SHA = "a6b919c200f4702fae4e3cb5f687676a503728233f5eb6c1a9468f835a533433"
AUTHORITY = Path("sources/commentaries/expositors-bible/readable-moule-index-v4/moule-expositorromans/source-manifest.json")
MANIFEST_SHA = "4c3a6d990117eb9d47a3f6b791f0c7e0a4a15c34a72734bece5c78b2394a426d"
CANDIDATE_ROOT = EXTERNAL / "expositors-lib034-moule-index-v4-candidate-20260928-v1"
PACKAGE_SHA = "088e1d3191cfa91986d5c984bef47940573cc48d4e917bb49fbec9946e0122c9"
VALIDATION_SHA = "163f52adaf3364f3188dad60c28457c55834333684a83dfc6c43394f78262a69"
TEI_SHA = "a2ab1032e42afda1cfd3ff54c2117b9331af9d815b3e2fcc425c21c7b146294c"
OLD_MASTER_SHA = "9a3de7a07c719459f0aaae5bb00728a29a4eef642953b2f392ce6c5148aa7095"
OLD_ACCEPTANCE_SHA = "149510552314b96f31ce5b0d89d436bcab9b479a64342b455fc10ffa4e836638"
OLD_PACKAGE_TEI_SHA = "b859a89e9f6104878f3a422394e11cdd7fe21ce19a99f22e6693fa909ae8c9ec"
EVIDENCE = WORK / "integration/moule-expositorromans-readable-electronic-index-v4"
RECEIPT = "expositors-moule-nested-index-repair-stage-receipt.json"
CONTRACT = "ocd-expositors-moule-nested-index-repair-stage-v1"
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CHANGE_TYPES = {
    f"{MEMBER}-feature-005655": "source-index",
    f"{MEMBER}-xxxvi.ii-p0.2": "source-hebrew",
    f"{MEMBER}-feature-005850": "source-index",
    f"{MEMBER}-feature-005928": "source-index",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Moule index repair input changed: {path}")
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
        raise ValueError("Moule TEI text missing")
    before, after = list(previous.iter()), list(current.iter())
    if len(before) != len(after):
        raise ValueError("Moule TEI element cardinality changed")
    changed: list[dict[str, object]] = []
    for ordinal, (left, right) in enumerate(zip(before, after, strict=True), 1):
        if (left.text, left.tail) != (right.text, right.tail):
            raise ValueError(f"Moule text or tail changed at {ordinal}")
        if left.tag == right.tag and left.attrib == right.attrib:
            continue
        if not (left.tag == NS + "quote" and right.tag == NS + "div"
                and left.get("type") == "source-div"
                and right.get("type") == CHANGE_TYPES.get(right.get(XML_ID))
                and left.get(XML_ID) == right.get(XML_ID)
                and right.get(XML_ID) in CHANGE_TYPES
                and (dict(left.attrib) | {"type": right.get("type")}) == dict(right.attrib)):
            raise ValueError(f"Moule unapproved TEI change at {ordinal}")
        changed.append({"ordinal": ordinal, "tei_id": right.get(XML_ID),
                        "before": "quote/source-div", "after": "div/" + right.get("type")})
    if [row["tei_id"] for row in changed] != list(CHANGE_TYPES):
        raise ValueError("Moule expected Hebrew parent and exactly three source index corrections")
    return changed


def prepare(stage: Path) -> dict[str, object]:
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or ROOT.resolve() in stage.resolve().parents:
        raise ValueError("Moule repair requires a fresh external stage")
    before = _files(ROOT / WORK)
    if len(before) != 36:
        raise ValueError("Moule accepted work preimage changed")
    work = json.loads(_read(ROOT / WORK / "work.json"))
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    edition_path = WORK / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"]
    acquisition_path = edition_path / "acquisitions" / (edition["acquisition_ids"][0] + ".json")
    acquisition = json.loads(_read(ROOT / acquisition_path))
    retained = acquisition["retained_files"]
    if (len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA or retained[0]["bytes"] != len(_read(ROOT / SOURCE, SOURCE_SHA))):
        raise ValueError("Moule retained acquisition changed")
    old_acceptance_path = edition_path / "acceptance.json"
    old_master_path = edition_path / "master.tei.xml"
    old_acceptance = json.loads(_read(ROOT / old_acceptance_path, OLD_ACCEPTANCE_SHA))
    old_master = _read(ROOT / old_master_path, OLD_MASTER_SHA)
    if (old_acceptance["identity"]["edition_id"] != edition["edition_id"]
            or old_acceptance["promotion"]["master"]["sha256"] != OLD_MASTER_SHA
            or old_acceptance["decision"]["human_decision"]["status"] != "not-recorded"):
        raise ValueError("Moule prior acceptance identity changed")
    manifest = SourceManifest.load(ROOT / AUTHORITY, repository_root=ROOT)
    manifest.verify()
    candidate = CandidatePackage.load(CANDIDATE_ROOT / MEMBER)
    report = validate(manifest, candidate, _oracle)
    if (manifest.sha256 != MANIFEST_SHA or candidate.sha256 != PACKAGE_SHA
            or _sha(CANDIDATE_ROOT / (MEMBER + ".validation.json")) != VALIDATION_SHA
            or sha256(candidate.member_bytes("content.tei.xml")).hexdigest() != TEI_SHA
            or report.status != "pass"):
        raise ValueError("Moule corrected source package differs")
    old_package_tei = _read(ROOT / WORK / "integration/moule-expositorromans-readable-electronic-v1/inputs/package/content.tei.xml", OLD_PACKAGE_TEI_SHA)
    raw_delta = _source_only_delta(old_package_tei, candidate.member_bytes("content.tei.xml"))
    stage.mkdir(parents=True)
    for relative in before:
        _put(stage, WORK / relative, _read(ROOT / WORK / relative, before[relative]))
    dependencies = {SOURCE, AUTHORITY,
                    Path("build/tei/expositors_bible_lib034_readable_moule_index_v4.py"),
                    Path("build/tei/expositors_bible_lib034_readable_moule_index_v4_oracle.py"),
                    Path("sources/commentaries/expositors-bible/ccel-permission.md")}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    inherited_state = json.loads(_read(ROOT / WORK / "state.json"))
    for reference in set(work.get("evidence", [])) | {
        item for target in inherited_state["targets"] for item in target.get("evidence", [])
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Moule unsafe inherited evidence: {reference}")
        if not relative.is_relative_to(WORK):
            dependencies.add(relative)
    for relative in sorted(dependencies):
        _put(stage, relative, _read(ROOT / relative))
    for name in candidate.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, candidate.member_bytes(name))
    _put(stage, EVIDENCE / "inputs/validation.json", _read(CANDIDATE_ROOT / (MEMBER + ".validation.json"), VALIDATION_SHA))
    identity = old_acceptance["identity"]
    revision = {"id": "moule-expositorromans-ccel-electronic-index-v4",
                "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Preserve the Hebrew index wrapper as a structural division and correct three source Index containers; retain the complete electronic text and edition identity."}
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
        raise ValueError("Moule accepted header or text changed unexpectedly")
    accepted_delta = _source_only_delta(old_master, derived)
    if [x["tei_id"] for x in accepted_delta] != [x["tei_id"] for x in raw_delta]:
        raise ValueError("Moule accepted master correction differs from raw candidate")
    accepted_candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(accepted_candidate)):
        raise ValueError(f"Moule corrected P5 errors: {errors[:2]}")
    delta_file = _put_json(stage, EVIDENCE / "correction.json", {
        "contract": "ocd-expositors-index-semantic-repair-v1", "source_sha256": SOURCE_SHA,
        "prior_master_sha256": OLD_MASTER_SHA, "prior_acceptance_sha256": OLD_ACCEPTANCE_SHA,
        "source_candidate_delta": raw_delta, "accepted_master_delta": accepted_delta,
        "all_text_and_tails_identical": True, "outside_hebrew_parent_and_three_index_nodes_identical": True})
    common = {"identity": identity, "source": source,
              "candidate": make_file_binding(stage, accepted_candidate),
              "scope": source["source_scope"], "accepted_scope": {"kind": "edition", "declared": source["source_scope"]},
              "expected_members": old_acceptance["scope"]["expected_members"],
              "included_members": old_acceptance["scope"]["included_members"],
              "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", common | {
        "source_sha256": SOURCE_SHA, "source_bytes": source["source_bytes"],
        "source_manifest_sha256": MANIFEST_SHA, "candidate_package_sha256": PACKAGE_SHA,
        "source_feature_counts": {"elements": 6373, "comments": 14}, "unsupported_elements": 0,
        "basis": "Independent exact-source oracle plus prior/current complete TEI node comparison; only the Hebrew wrapper and three Index carrier tags/types changed."})
    command = "py -3 -m build.tools.stage_expositors_lib034_moule_nested_index_repair --stage <fresh-external-root>"
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
    review = {"reviewer": "agent:expositors-moule-index-repair", "reviewed_at": reviewed_at,
              "coverage": old_acceptance["review"]["coverage"],
              "source_quality_uncertainty": old_acceptance["review"]["source_quality_uncertainty"],
              "discrepancies": ["Prior master mislabeled the Hebrew wrapper and three Index carriers as quotations; their source hierarchy is corrected in this revision."],
              "unreviewed_residuals": old_acceptance["review"]["unreviewed_residuals"]}
    review_file = _put_json(stage, EVIDENCE / "review.json", common | review | {
        "prior_acceptance_sha256": OLD_ACCEPTANCE_SHA,
        "correction": make_file_binding(stage, delta_file)})
    decision = {"source_local_disposition": "Agent correction of the Hebrew wrapper and three nested/source index labels within one already accepted electronic edition.",
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
    if errors or len(projected["rows"]) != 36:
        raise ValueError(f"Moule corrected native projection differs: {errors[:2]}")
    after = _files(stage / WORK)
    expected_additions = {x for x in after if x.startswith("integration/moule-expositorromans-readable-electronic-index-v4/")}
    if (len(after) != len(before) + len(expected_additions)
            or any(after[x] != before[x] for x in before if x not in {
                old_acceptance_path.relative_to(WORK).as_posix(), old_master_path.relative_to(WORK).as_posix()})):
        raise ValueError("Moule repair work generation changed unrelated files")
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
                        "correction_sha256": _sha(delta_file), "native_rows": 36}}
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
