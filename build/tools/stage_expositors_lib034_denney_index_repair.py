"""Stage a two-edition, source-bound Denney index correction externally."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from lxml import etree

from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.commentary import project_accepted_commentary, verify_accepted_commentary
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

from build.tei.expositors_bible_lib034_readable_denney_index_v2_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = Path("D:/Library/Open Christian Data/candidate-reviews")
WORK = Path("library/works/expositors-bible--james-denney")
CANDIDATES = EXTERNAL / "expositors-lib034-denney-index-v2-candidates-20260928-v1"
RECEIPT = "expositors-denney-index-repair-stage-receipt.json"
CONTRACT = "ocd-expositors-denney-index-repair-stage-v1"
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
ROWS = {
    "denney-expositor2cor": {
        "source": "raw/ccel/expositors-bible/denney_expositor2cor.xml",
        "source_sha": "afdf1cb907eb7d79f2f20582dd8d5e96a84614c253bb193903cc1cac76d16bc7",
        "manifest_sha": "0ce5c2f6948913300f4383699eece424959b79a88ed3a6dda2f93237c2000768",
        "package_sha": "11b6a169332282a835ee8ad857a88c54d1270c130ea2cfcb6477c4cf2e467305",
        "validation_sha": "90ee3669a3143b919592f7df3f93889fa4a43098ae72e3fdf5f6d2d05660b755",
        "tei_sha": "bae65225413d50bf7dcb972a33f113e86da9cab231162d862e552ba86fdf91dc",
        "old_package_tei_sha": "c9f2e2b712442c5e2053ea654e0446cbe3dec50abf2062e19cc84652a6fcde53",
        "old_master_sha": "1fcaefdd2163056f55188d912c4e2a1cd1f7f44b9fe7ece87a8b9af492279e98",
        "old_acceptance_sha": "2db8cfe791f764641e65fb483940dff07e28db2bec71dad10d5789b6f050efb8",
        "index_ids": ["denney-expositor2cor-feature-002108", "denney-expositor2cor-feature-002146"],
        "elements": 2536, "comments": 10, "native_rows": 31,
    },
    "denney-expositorthess": {
        "source": "raw/ccel/expositors-bible/denney_expositorthess.xml",
        "source_sha": "47417f9447e9558951594ba2bd35eb5958be1293041e83b1af6e990ee8d2fffc",
        "manifest_sha": "588ecd6f443c91bd68184057fa06b7b0e550592fea96a71e28998af5f2ecaf84",
        "package_sha": "14f52661dff4adb24bbcb2bf3f2dd4d4ddf091e3ba66d36aadc4d589eb1bd352",
        "validation_sha": "a2623c9cb058ca1db6d452738d80dbc9c7fa05ed2de9b7581f209a89cdfd3781",
        "tei_sha": "7f242e09c538136933fbf6008821d7785b528c7943bdf7df0f78fd82cec7f706",
        "old_package_tei_sha": "f00cc63222f2aa7c94fd5cdfc2c4cc838cdf402fbbc0c3b3a373c438498d0a5a",
        "old_master_sha": "597d04fdfd0ba3ef92f8f49dc4a360688467c7c926d165be470446697ad18e5c",
        "old_acceptance_sha": "94f85eed09fcd2ba80eda8bffb149b65b6e196958558ac2181cc30b5b70ee4ba",
        "index_ids": ["denney-expositorthess-feature-001201", "denney-expositorthess-feature-001234"],
        "elements": 1576, "comments": 10, "native_rows": 4,
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Denney input changed: {path}")
    return content


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    path = stage / relative
    _io_path(path).parent.mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(content)
    return path


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, (json.dumps(value, sort_keys=True, ensure_ascii=False,
                                            separators=(",", ":")) + "\n").encode("utf-8"))


def _source_only_delta(old: bytes, new: bytes, index_ids: list[str]) -> list[dict[str, object]]:
    previous = etree.fromstring(old).find(NS + "text")
    current = etree.fromstring(new).find(NS + "text")
    if previous is None or current is None:
        raise ValueError("Denney TEI text missing")
    before, after = list(previous.iter()), list(current.iter())
    if len(before) != len(after):
        raise ValueError("Denney TEI element cardinality changed")
    changed = []
    for ordinal, (left, right) in enumerate(zip(before, after, strict=True), 1):
        if (left.text, left.tail) != (right.text, right.tail):
            raise ValueError(f"Denney text or tail changed at {ordinal}")
        if left.tag == right.tag and left.attrib == right.attrib:
            continue
        if not (left.tag == NS + "quote" and right.tag == NS + "div"
                and left.get("type") == "source-div" and right.get("type") == "source-index"
                and left.get(XML_ID) == right.get(XML_ID) and right.get(XML_ID) in index_ids
                and set(left.attrib) == set(right.attrib)):
            raise ValueError(f"Denney unapproved TEI change at {ordinal}")
        changed.append({"ordinal": ordinal, "tei_id": right.get(XML_ID),
                        "before": "quote/source-div", "after": "div/source-index"})
    if [row["tei_id"] for row in changed] != index_ids:
        raise ValueError("Denney expected exactly the two source indexes")
    return changed


def _edition_path(work: dict, member: str) -> Path:
    forms = [x for x in work["textual_forms"] if member in x["textual_form_id"]]
    if len(forms) != 1 or len(forms[0]["editions"]) != 1:
        raise ValueError(f"Denney edition identity changed: {member}")
    form, edition = forms[0], forms[0]["editions"][0]
    if len(edition["acquisition_ids"]) != 1 or edition["category"] != "commentary":
        raise ValueError(f"Denney accepted identity changed: {member}")
    return WORK / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"]


def prepare(stage: Path) -> dict[str, object]:
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or ROOT.resolve() in stage.resolve().parents:
        raise ValueError("Denney repair requires a fresh external stage")
    before = _files(ROOT / WORK)
    if len(before) != 69:
        raise ValueError("Denney accepted work preimage changed")
    work = json.loads(_read(ROOT / WORK / "work.json"))
    state = json.loads(_read(ROOT / WORK / "state.json"))
    if work["work_id"] != WORK.name or len(work["textual_forms"]) != 2:
        raise ValueError("Denney work boundary changed")
    stage.mkdir(parents=True)
    for relative, digest in before.items():
        _put(stage, WORK / relative, _read(ROOT / WORK / relative, digest))
    dependencies = {
        Path("sources/commentaries/expositors-bible/ccel-permission.md"),
        Path("build/tei/expositors_bible_lib034_readable_denney_index_v2.py"),
        Path("build/tei/expositors_bible_lib034_readable_denney_index_v2_oracle.py"),
    }
    for reference in set(work.get("evidence", [])) | {
        item for target in state["targets"] for item in target.get("evidence", [])
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Denney unsafe inherited evidence: {reference}")
        if not relative.is_relative_to(WORK):
            dependencies.add(relative)
    dependencies.update(Path(detail["source"]) for detail in ROWS.values())
    for relative in sorted(dependencies):
        _put(stage, relative, _read(ROOT / relative))
    editions = {}
    for member, detail in ROWS.items():
        source_path = Path(detail["source"])
        source = _read(ROOT / source_path, detail["source_sha"])
        manifest_path = Path("sources/commentaries/expositors-bible/readable-denney-index-v5") / member / "source-manifest.json"
        manifest = SourceManifest.load(ROOT / manifest_path, repository_root=ROOT)
        manifest.verify()
        candidate = CandidatePackage.load(CANDIDATES / member)
        report = validate(manifest, candidate, _oracle)
        validation = _read(CANDIDATES / (member + ".validation.json"), detail["validation_sha"])
        if (manifest.sha256 != detail["manifest_sha"] or candidate.sha256 != detail["package_sha"]
                or sha256(candidate.member_bytes("content.tei.xml")).hexdigest() != detail["tei_sha"]
                or report.status != "pass" or json.loads(validation)["report_sha256"] != report.sha256):
            raise ValueError(f"Denney corrected source package differs: {member}")
        edition_path = _edition_path(work, member)
        acquisition_name = work["textual_forms"][0]["editions"][0]["acquisition_ids"][0]
        for form in work["textual_forms"]:
            if member in form["textual_form_id"]:
                acquisition_name = form["editions"][0]["acquisition_ids"][0]
        acquisition = json.loads(_read(ROOT / edition_path / "acquisitions" / (acquisition_name + ".json")))
        retained = acquisition["retained_files"]
        if (len(retained) != 1 or retained[0]["path"] != source_path.as_posix()
                or retained[0]["sha256"] != detail["source_sha"] or retained[0]["bytes"] != len(source)):
            raise ValueError(f"Denney retained acquisition differs: {member}")
        old_acceptance_path = edition_path / "acceptance.json"
        old_master_path = edition_path / "master.tei.xml"
        old_acceptance = json.loads(_read(ROOT / old_acceptance_path, detail["old_acceptance_sha"]))
        old_master = _read(ROOT / old_master_path, detail["old_master_sha"])
        if (old_acceptance["identity"]["edition_id"] != edition_path.name
                or old_acceptance["promotion"]["master"]["sha256"] != detail["old_master_sha"]
                or old_acceptance["decision"]["human_decision"]["status"] != "not-recorded"):
            raise ValueError(f"Denney prior acceptance differs: {member}")
        old_package = _read(ROOT / WORK / "integration" / (member + "-readable-electronic-v1")
                            / "inputs/package/content.tei.xml", detail["old_package_tei_sha"])
        raw_candidate = candidate.member_bytes("content.tei.xml")
        raw_delta = _source_only_delta(old_package, raw_candidate, detail["index_ids"])
        dependencies.update({source_path, manifest_path})
        dependencies.update(Path(row["path"]) for row in manifest.record["authorities"])
        for relative in sorted({source_path, manifest_path} | {
            Path(row["path"]) for row in manifest.record["authorities"]
        }):
            _put(stage, relative, _read(ROOT / relative))
        evidence = WORK / "integration" / (member + "-readable-electronic-index-v2")
        for name in candidate.member_names:
            _put(stage, evidence / "inputs/package" / name, candidate.member_bytes(name))
        _put(stage, evidence / "inputs/validation.json", validation)
        revision = {"id": member + "-ccel-electronic-index-v2",
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "note": "Correct two source Index containers from quotation to index divisions; retain the complete electronic text and edition identity."}
        binding = {"source_path": source_path.as_posix(), "source_sha256": detail["source_sha"],
                   "source_bytes": len(source), "source_scope": retained[0]["scope"]}
        derived = bind_reviewed_header(raw_candidate, expected_sha256=detail["tei_sha"],
                                       identity=old_acceptance["identity"], source=binding,
                                       source_url=acquisition["url"], declared_scope=binding["source_scope"],
                                       revision=revision)
        derived, count = re.subn(rb"(<sourceDesc>)<p>(Retained CCEL ThML electronic witness by [^<]+)</p>(<bibl)",
                                 rb"\1<bibl><title>\2</title></bibl>\3", derived)
        if count != 1 or derived.split(b"</teiHeader>", 1)[1] != raw_candidate.split(b"</teiHeader>", 1)[1]:
            raise ValueError(f"Denney accepted header or text differs: {member}")
        accepted_delta = _source_only_delta(old_master, derived, detail["index_ids"])
        if [row["tei_id"] for row in accepted_delta] != [row["tei_id"] for row in raw_delta]:
            raise ValueError(f"Denney raw/accepted corrections differ: {member}")
        candidate_path = _put(stage, evidence / "candidate.tei.xml", derived)
        if errors := validate_file(_io_path(candidate_path)):
            raise ValueError(f"Denney corrected P5 errors: {member}: {errors[:2]}")
        correction = _put_json(stage, evidence / "correction.json", {
            "contract": "ocd-expositors-index-semantic-repair-v1", "source_sha256": detail["source_sha"],
            "prior_master_sha256": detail["old_master_sha"],
            "prior_acceptance_sha256": detail["old_acceptance_sha"],
            "source_candidate_delta": raw_delta, "accepted_master_delta": accepted_delta,
            "all_text_and_tails_identical": True, "outside_two_index_nodes_identical": True})
        common = {"identity": old_acceptance["identity"], "source": binding,
                  "candidate": make_file_binding(stage, candidate_path),
                  "scope": binding["source_scope"],
                  "accepted_scope": {"kind": "edition", "declared": binding["source_scope"]},
                  "expected_members": old_acceptance["scope"]["expected_members"],
                  "included_members": old_acceptance["scope"]["included_members"],
                  "excluded_members": [], "missing_members": [], "unknown_members": []}
        accounting = _put_json(stage, evidence / "source-accounting.json", common | {
            "source_sha256": detail["source_sha"], "source_bytes": len(source),
            "source_manifest_sha256": detail["manifest_sha"], "candidate_package_sha256": detail["package_sha"],
            "source_feature_counts": {"elements": detail["elements"], "comments": detail["comments"]},
            "unsupported_elements": 0,
            "basis": "Independent exact-source oracle and complete prior/current TEI node comparison; only two Index container tags/types changed."})
        command = "py -3 -m build.tools.stage_expositors_lib034_denney_index_repair --stage <fresh-external-root>"
        technical = {"producer": {"id": manifest.record["converter"]["id"]},
                     "checker": {"id": manifest.record["validator"]["id"]},
                     "shared_assumptions": ["Producer and checker parse the same retained CCEL XML."],
                     "independent_corroboration": "Exact source oracle, full prior/current TEI delta, P5 and native verifier."}
        for label in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
            proof = _put_json(stage, evidence / (label + ".json"), common | {
                "status": "pass", "command": command, "exit_code": 0, "claim": label,
                "candidate_package_sha256": detail["package_sha"],
                "source_manifest_sha256": detail["manifest_sha"],
                "validation_sha256": detail["validation_sha"], "correction_sha256": _sha(correction)})
            technical[label] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
        reviewed_at = _now()
        review = {"reviewer": "agent:expositors-denney-index-repair", "reviewed_at": reviewed_at,
                  "coverage": old_acceptance["review"]["coverage"],
                  "source_quality_uncertainty": old_acceptance["review"]["source_quality_uncertainty"],
                  "discrepancies": list(dict.fromkeys(old_acceptance["review"]["discrepancies"] +
                    ["Prior master mislabeled two source index containers as quotations; corrected in this revision."])),
                  "unreviewed_residuals": old_acceptance["review"]["unreviewed_residuals"]}
        review_file = _put_json(stage, evidence / "review.json", common | review | {
            "prior_acceptance_sha256": detail["old_acceptance_sha"],
            "correction": make_file_binding(stage, correction)})
        decision = {"source_local_disposition": "Agent correction of two index labels within an already accepted electronic edition.",
                    "blockers": [], "human_decision": {"status": "not-recorded"},
                    "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                        "assessed_at": reviewed_at, "supported_scope": binding["source_scope"],
                        "unresolved_claims": [],
                        "unassessed_stronger_claims": old_acceptance["decision"]["agent_assessment"]["unassessed_stronger_claims"]}}
        acceptance = build_acceptance_record(stage, identity=old_acceptance["identity"],
            candidate_path=candidate_path, source_accounting_path=accounting,
            scope=old_acceptance["scope"], technical=technical,
            review=review | {"report_path": review_file}, representation_revision=revision, decision=decision)
        acceptance_path = stage / old_acceptance_path
        write_acceptance(_io_path(acceptance_path), acceptance)
        master_path = _put(stage, old_master_path, derived)
        acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                        master=make_file_binding(stage, master_path))
        write_acceptance(_io_path(acceptance_path), acceptance)
        validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
        projection = project_accepted_commentary(_io_path(stage), acceptance_path=_io_path(acceptance_path))
        errors = verify_accepted_commentary(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                            rows=projection["rows"], receipt=projection["receipt"])
        if errors or len(projection["rows"]) != detail["native_rows"]:
            raise ValueError(f"Denney corrected native projection differs: {member}: {errors[:2]}")
        editions[member] = {"source_path": detail["source"], "source_sha256": detail["source_sha"],
            "prior_master_sha256": detail["old_master_sha"],
            "prior_acceptance_sha256": detail["old_acceptance_sha"],
            "new_master_sha256": _sha(master_path), "new_acceptance_sha256": _sha(acceptance_path),
            "source_manifest_sha256": detail["manifest_sha"], "candidate_package_sha256": detail["package_sha"],
            "correction_sha256": _sha(correction), "native_rows": detail["native_rows"],
            "acceptance_path": old_acceptance_path.relative_to(WORK).as_posix(),
            "master_path": old_master_path.relative_to(WORK).as_posix(),
            "evidence_prefix": evidence.relative_to(WORK).as_posix() + "/", "index_ids": detail["index_ids"]}
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    for relative in sorted(dependencies):
        _put(stage, relative, _read(ROOT / relative))
    after = _files(stage / WORK)
    changed = {row[p] for row in editions.values() for p in ("acceptance_path", "master_path")}
    additions = {key for key in after if any(key.startswith(row["evidence_prefix"]) for row in editions.values())}
    if (len(after) != len(before) + len(additions)
            or any(after[key] != before[key] for key in before if key not in changed)):
        raise ValueError("Denney repair changed unrelated accepted files")
    dependencies_map = {key: digest for key, digest in _files(stage).items()
                        if not key.startswith(WORK.as_posix() + "/") and key != RECEIPT}
    receipt = {"contract": CONTRACT, "status": "staged-only", "installation": "not-performed",
               "rights": "not-assessed", "canonical_root": ROOT.as_posix(), "stage_root": stage.as_posix(),
               "dependencies": dependencies_map,
               "work": {"work_id": WORK.name, "work_path": WORK.as_posix(), "before": before,
                        "after": after, "editions": editions}}
    _put_json(stage, Path(RECEIPT), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    receipt = prepare(args.stage)
    print(json.dumps({"status": receipt["status"], "work_id": receipt["work"]["work_id"],
                      "before": len(receipt["work"]["before"]), "after": len(receipt["work"]["after"]),
                      "editions": len(receipt["work"]["editions"])}, sort_keys=True))


if __name__ == "__main__":
    main()
