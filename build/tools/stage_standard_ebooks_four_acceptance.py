"""Stage source-bound, work-local Standard Ebooks electronic acceptances."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.se_candidate_oracle import _oracle
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

ROOT = Path(__file__).resolve().parents[2]
BASE = Path("D:/Library/Open Christian Data/candidate-reviews")
CASES = {
    "orthodoxy": ("g-k-chesterton_orthodoxy", "orthodoxy", 16),
    "heretics": ("g-k-chesterton_heretics", "heretics", 26),
    "george-macdonald-unspoken-sermons": ("george-macdonald_unspoken-sermons", "unspoken-sermons", 49),
    "the-everlasting-man": ("g-k-chesterton_the-everlasting-man", "everlasting-man", 26),
}
CONTRACT = "ocd-standard-ebooks-four-current-spine-acceptance-stage-v1"
NS = {"opf": "http://www.idpf.org/2007/opf", "t": "http://www.tei-c.org/ns/1.0"}
CREDIT = b'<bibl xmlns="http://www.tei-c.org/ns/1.0"><note type="source-credit">Standard Ebooks electronic edition</note></bibl>'


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> bytes:
    return _io_path(path).read_bytes()


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, (json.dumps(value, sort_keys=True, ensure_ascii=False,
                                              separators=(",", ":")) + "\n").encode())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _spine(source_root: str) -> list[str]:
    opf = etree.fromstring(_read(ROOT / source_root / "src/epub/content.opf"),
                           parser=etree.XMLParser(resolve_entities=False, no_network=True))
    members = {item.get("id"): item.get("href") for item in opf.xpath("./opf:manifest/opf:item", namespaces=NS)}
    spine = [members[item.get("idref")] for item in opf.xpath("./opf:spine/opf:itemref", namespaces=NS)]
    if len(spine) != len(set(spine)) or any(not name.startswith("text/") or not name.endswith(".xhtml")
                                           or ".." in Path(name).parts for name in spine):
        raise ValueError("Standard Ebooks OPF spine is not unique XHTML")
    return [f"{source_root}/src/epub/{name}" for name in spine]


def prepare(work_id: str, stage: Path) -> dict:
    if work_id not in CASES:
        raise ValueError("unlisted Standard Ebooks work")
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or ROOT.resolve() in stage.resolve().parents:
        raise ValueError("requires fresh external stage")
    source_name, short, count = CASES[work_id]
    source_root = f"raw/standard_ebooks/{source_name}"
    manifest_rel = Path("sources/standard-ebooks") / source_name / f"{work_id}.source-manifest.json"
    manifest = SourceManifest.load(ROOT / manifest_rel, repository_root=ROOT)
    manifest.verify()
    package_root = BASE / f"{short}-current-20260928-v1"
    package = CandidatePackage.load(package_root / "package")
    report = validate(manifest, package, _oracle)
    saved_report = json.loads(_read(package_root / "validation.json"))
    if (report.status != "pass" or package.sha256 != saved_report["candidate_sha256"]
            or report.sha256 != saved_report["report_sha256"]):
        raise ValueError("current independent Standard Ebooks report differs")
    work_rel = Path("library/works") / work_id
    before = _files(ROOT / work_rel)
    work = json.loads(_read(ROOT / work_rel / "work.json"))
    state = json.loads(_read(ROOT / work_rel / "state.json"))
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                "edition_id": edition["edition_id"], "acquisition_id": edition["acquisition_ids"][0]}
    edition_rel = work_rel / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
    acquisition_rel = edition_rel / "acquisitions" / f"{identity['acquisition_id']}.json"
    acquisition = json.loads(_read(ROOT / acquisition_rel))
    retained = acquisition["retained_files"]
    spine = _spine(source_root)
    if (len(spine) != count or [item["path"] for item in retained] != spine
            or any(_sha(_read(ROOT / item["path"])) != item["sha256"]
                   or len(_read(ROOT / item["path"])) != item["bytes"] for item in retained)
            or acquisition["source_kind"] != "retained-member-set"
            or not acquisition["url"].startswith("https://github.com/standardebooks/")
            or edition.get("category") is not None or len(before) != 6
            or any(_io_path(ROOT / edition_rel / name).exists() for name in ("acceptance.json", "master.tei.xml"))):
        raise ValueError("source spine or acquired work boundary differs")
    if [item["stage"] for item in state["targets"] if item["target_type"] == "edition"] != ["acquired"]:
        raise ValueError("edition is not uniquely acquired")
    profile = json.loads(_read(ROOT / "sources/standard-ebooks" / source_name / "reconstruction-profile.json"))
    by_path = {item["path"]: item for item in profile["members"]}
    if ([path.removeprefix(source_root + "/") for path in spine] !=
            [item["path"].removeprefix(source_root + "/") for item in retained]
            or any(by_path[path.removeprefix(source_root + "/")]["disposition"] != "readable-text"
                   for path in spine)
            or {item["path"] for item in profile["members"] if item["disposition"] == "readable-text"}
            != {path.removeprefix(source_root + "/") for path in spine}):
        raise ValueError("profile source disposition or OPF spine differs")
    stage.mkdir()
    for relative, digest in before.items():
        content = _read(ROOT / work_rel / relative)
        if _sha(content) != digest:
            raise ValueError("live work changed during staging")
        _put(stage, work_rel / relative, content)
    dependencies = {manifest_rel, Path("sources/standard-ebooks") / source_name / "README.source.md"}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    for ref in work.get("evidence", []):
        relative = Path(ref.partition("#")[0])
        if not relative.is_relative_to(work_rel):
            dependencies.add(relative)
    for relative in sorted(dependencies):
        _put(stage, relative, _read(ROOT / relative))
    evidence = work_rel / "integration" / "current-standard-ebooks-spine-v1"
    for name in package.member_names:
        _put(stage, evidence / "inputs/package" / name, package.member_bytes(name))
    _put(stage, evidence / "inputs/validation.json", _read(package_root / "validation.json"))
    updated_work = json.loads(json.dumps(work))
    updated_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    validate_identity_update(work, updated_work)
    _json(stage, work_rel / "work.json", updated_work)
    load_work(_io_path(stage / work_rel / "work.json"))
    scope_text = (f"{count} retained Standard Ebooks XHTML text members in exact OPF spine order, "
                  f"represented by the unchanged {work_id} TEI text; other checkout files are hash-bound "
                  "support. No independent print-edition collation.")
    source = {key: acquisition[key] for key in ("source_kind", "source_path", "source_bytes", "source_sha256", "source_scope")}
    revision = {"id": f"{work_id}-standard-ebooks-current-spine-v1",
                "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Bound the current OPF-spine reconstruction to its acquired Standard Ebooks electronic edition."}
    original = package.member_bytes("content.tei.xml")
    root = etree.fromstring(original, etree.XMLParser(resolve_entities=False, no_network=True))
    pointers = root.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc//t:ptr/@target", namespaces=NS)
    hashes = root.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc//t:idno[@type='sha256']/text()", namespaces=NS)
    derived = bind_reviewed_header(original, expected_sha256=_sha(original), identity=identity,
                                   source=source, source_url=acquisition["url"], declared_scope=scope_text,
                                   revision=revision,
                                   historical_source_description={"pointers": pointers, "sha256": hashes})
    if derived.count(b"</sourceDesc>") != 1 or CREDIT in derived:
        raise ValueError("source description credit carrier changed")
    derived = derived.replace(b"</sourceDesc>", CREDIT + b"</sourceDesc>", 1)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Standard Ebooks source text changed")
    candidate = _put(stage, evidence / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Standard Ebooks P5 errors: {errors[:2]}")
    expected = [{"path": item["path"], "position": index} for index, item in enumerate(retained, 1)]
    included = [{key: item[key] for key in ("path", "bytes", "sha256", "scope")}
                | {"position": index} for index, item in enumerate(retained, 1)]
    acceptance_scope = {"kind": "edition", "declared": scope_text, "expected_members": expected,
                        "included_members": included, "excluded_members": []}
    common = {"identity": identity, "source": source, "candidate": make_file_binding(stage, candidate),
              "scope": scope_text, "accepted_scope": {"kind": "edition", "declared": scope_text},
              "expected_members": expected, "included_members": included, "excluded_members": [],
              "missing_members": [], "unknown_members": []}
    accounting = _json(stage, evidence / "source-accounting.json", common | {
        "scope": source["source_scope"],
        "source_manifest_sha256": manifest.sha256, "candidate_package_sha256": package.sha256,
        "opf_spine": spine, "support_count": len(profile["members"]) - count,
        "source_sha256": acquisition["source_sha256"], "source_bytes": acquisition["source_bytes"]})
    technical = {"producer": {"id": manifest.record["converter"]["id"]},
                 "checker": {"id": manifest.record["validator"]["id"]},
                 "shared_assumptions": ["Retained source and independent oracle use the same manifest-bound checkout."],
                 "independent_corroboration": "Current independent source oracle, exact OPF spine, P5, unchanged TEI text and native prose checker."}
    command = "py -3 -m build.tools.stage_standard_ebooks_four_acceptance --work-id " + work_id + " --stage <fresh-external-dir>"
    for label in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _json(stage, evidence / f"{label}.json", common | {
            "status": "pass", "command": command, "exit_code": 0, "claim": label,
            "oracle_report_sha256": report.sha256, "source_manifest_sha256": manifest.sha256,
            "candidate_package_sha256": package.sha256, "tei_text_byte_unchanged": True})
        technical[label] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    reviewed_at = _now()
    review = {"reviewer": "agent:standard-ebooks-four-current-spine-stage", "reviewed_at": reviewed_at,
              "coverage": {"status": "partial", "declared": scope_text, "reached": spine,
                           "inspected": spine, "unreviewed": ["complete-visual-proofreading"]},
              "source_quality_uncertainty": ["No independent print collation or complete visual proofreading."],
              "discrepancies": [], "unreviewed_residuals": ["Rights, human acceptance, and publication remain unresolved."]}
    review_path = _json(stage, evidence / "review.json", common | review)
    decision = {"source_local_disposition": "Current OPF-spine electronic edition technically accepted; source rights and human review remain open.",
                "blockers": [], "human_decision": {"status": "not-recorded"},
                "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": reviewed_at,
                                     "supported_scope": scope_text, "unresolved_claims": [],
                                     "unassessed_stronger_claims": ["print-edition fidelity", "metadata reconciliation",
                                                                   "human acceptance", "rights clearance", "publication"]}}
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                     source_accounting_path=accounting, scope=acceptance_scope,
                                     technical=technical, review=review | {"report_path": review_path},
                                     representation_revision=revision, decision=decision)
    acceptance = stage / edition_rel / "acceptance.json"
    write_acceptance(_io_path(acceptance), record)
    master = _put(stage, edition_rel / "master.tei.xml", derived)
    record["promotion"].update(status="promoted", promoted_at=_now(), master=make_file_binding(stage, master))
    write_acceptance(_io_path(acceptance), record)
    for target in state["targets"]:
        if target["target_type"] == "edition" and target["target_id"] == identity["edition_id"]:
            target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
            target["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    _json(stage, work_rel / "state.json", state)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / work_rel / "state.json"), root=_io_path(stage))
    projection = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance),
                                   rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != count:
        raise ValueError(f"accepted native prose projection differs: {errors[:2]}")
    after = _files(stage / work_rel)
    dependency_map = {key: value for key, value in _files(stage).items()
                      if not key.startswith(work_rel.as_posix() + "/") and key != "stage-receipt.json"}
    receipt = {"contract": CONTRACT, "status": "staged-only", "installation": "not-performed",
               "rights": "not-assessed", "canonical_root": ROOT.as_posix(), "stage_root": stage.as_posix(),
               "dependencies": dependency_map,
               "work": {"work_id": work_id, "work_path": work_rel.as_posix(), "before": before,
                        "after": after, "source_path": source_root, "source_manifest_sha256": manifest.sha256,
                        "candidate_package_sha256": package.sha256, "oracle_report_sha256": report.sha256,
                        "opf_spine_count": count, "new_master_sha256": _sha(derived),
                        "new_acceptance_sha256": _sha(_read(acceptance)), "native_rows": len(projection["rows"])}}
    _json(stage, Path("stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", required=True, choices=CASES)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.work_id, args.stage)
    print(json.dumps({"work_id": args.work_id, "before": len(result["work"]["before"]),
                      "after": len(result["work"]["after"]), "native_rows": result["work"]["native_rows"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
