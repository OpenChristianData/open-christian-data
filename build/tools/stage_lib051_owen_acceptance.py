"""Stage one noncanonical LIB-051 Owen work-local acceptance.

The stage is an immutable proposal under the durable library root. This module
has no canonical install or publication operation.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei.john_owen_lib050_oracle import _parse_source, _records, _verify_readable_transcription
from build.tools.prepare_owen_lib051_readable_candidates import MANIFEST, PROFILE
from ocd_kernel.projection.categories.lib051_owen import (
    PROFILE as READABLE_PROFILE, WORKS as READABLE_WORKS,
    FINAL_PROFILE, FINAL_WORKS,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = Path(r"D:\Library\Open Christian Data")
CANDIDATES = LIBRARY / "candidate-reviews/lib051-seven-readable-candidates-20260927-v1"
CHILDREN = READABLE_WORKS | {"john-owen-mortification"}
FINAL_CANDIDATES = LIBRARY / "candidate-reviews/lib051-final-three-readable-candidates-20260927-v1"
FINAL_CHILDREN = FINAL_WORKS
ELIGIBLE = CHILDREN | FINAL_CHILDREN
CODE_PATHS = (
    "build/tools/stage_lib051_owen_acceptance.py",
    "build/tools/install_lib051_owen_acceptance.py",
    "build/tools/install_lib051_owen_batch.py",
    "build/tools/prepare_owen_lib051_readable_candidates.py",
    "build/tei/john_owen_lib050_reconstruction.py",
    "build/tei/john_owen_lib050_oracle.py",
    "ocd_kernel/projection/categories/prose.py",
    "ocd_kernel/projection/categories/lib051_owen.py",
    "ocd_kernel/projection/categories/native_documents.py",
    "ocd_kernel/projection/native_content.py",
    "ocd_kernel/projection/native_content_check.py",
    "build/tei/john_owen_lib051_reconstruction.py",
    "schemas/v2/native-content.schema.json",
    "schemas/v2/categories/prose.schema.json",
)
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _source_boundary(row: dict[str, object]) -> tuple[bytes, list[dict[str, str | None]]]:
    source = Path(str(row["path"]))
    content = (ROOT / source).read_bytes()
    if len(content) != row["bytes"] or _sha(content) != row["sha256"]:
        raise PipelineError("LIB-051 retained source changed")
    root = etree.fromstring(content, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True,
    ))
    body = root.find("ThML.body")
    if root.tag != "ThML" or body is None:
        raise PipelineError("one complete LIB-051 ThML witness required")
    divisions = [node for node in body if isinstance(node.tag, str)]
    if not divisions or any(node.tag != "div1" for node in divisions):
        raise PipelineError("LIB-051 source top-level work divisions changed")
    if row["work_id"] == "john-owen-mortification" and (
            [node.get("title") for node in divisions] != ["Of the Mortification of Sin in Believers", "Indexes"]):
        raise PipelineError("Mortification source work/index boundary changed")
    return content, [{"source_id": node.get("id"), "title": node.get("title")}
                     for node in divisions]


def verify_original_source(work_id: str, source_bytes: bytes, original: bytes, *, member_id: str) -> int:
    """Recheck the readable body against the retained XML, independently of its receipt."""
    source = _parse_source(source_bytes)
    records = _records(source, member_id)
    candidate = etree.fromstring(original, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True,
    ))
    if candidate.tag != "{http://www.tei-c.org/ns/1.0}TEI" or candidate.get(
            "{http://www.w3.org/XML/1998/namespace}id") != work_id:
        raise PipelineError("LIB-051 readable candidate envelope differs")
    body = candidate.find("tei:text/tei:body", NS)
    if body is None or len(body) != 1:
        raise PipelineError("LIB-051 readable candidate body differs")
    _verify_readable_transcription(source, records, body, work_id)
    return len(records)


def _source_features(work_id: str, source_body: etree._Element,
                     original_tree: etree._Element) -> dict[str, object]:
    if work_id == "john-owen-glory":
        source_headings = list(source_body.iter("h4"))
        source_quotes = list(source_body.iter("blockquote"))
        headings = [node for node in original_tree.iter("{http://www.tei-c.org/ns/1.0}ab")
                    if node.get("subtype") == "h4"]
        quotes = [node for node in original_tree.iter("{http://www.tei-c.org/ns/1.0}quote")
                  if node.get("type") == "source-blockquote"]
        if (len(source_headings), len(source_quotes), len(headings), len(quotes)) != (6, 1, 6, 1):
            raise PipelineError("Glory heading or blockquote source feature boundary differs")
        return {"source_h4": 6, "source_blockquote": 1,
                "readable_h4": 6, "readable_blockquote": 1}
    if work_id == "john-owen-justification":
        passages = [node.get("passage") for node in source_body.iter("scripRef")
                    if node.get("osisRef") is None and "[" in (node.get("passage") or "")]
        expected = ["Ps. xxii. 8, [margin,] xxxvii. 5", "Chap. iii. [iv. v. x."]
        refs = [node for node in original_tree.iter("{http://www.tei-c.org/ns/1.0}ref")
                if node.get("n") in expected]
        if (sorted(passages) != sorted(expected) or len(refs) != 2
                or sorted(node.get("n") for node in refs) != sorted(expected)
                or any(node.get("target") is not None for node in refs)):
            raise PipelineError("Justification free-text passage boundary or noninvented target differs")
        return {"literal_only_passages": expected, "invented_targets": 0}
    if work_id == "john-owen-pneumatologia":
        source_foreign = list(source_body.iter("foreign"))
        readable_foreign = list(original_tree.iter("{http://www.tei-c.org/ns/1.0}foreign"))
        if (len(source_foreign) != 419 or len(readable_foreign) != 419
                or any(node.get("lang") != "LA" for node in source_foreign)
                or any(node.get("{http://www.w3.org/XML/1998/namespace}lang") != "LA"
                       for node in readable_foreign)):
            raise PipelineError("Pneumatologia retained Latin foreign span boundary differs")
        return {"source_foreign": 419, "readable_foreign": 419, "source_language": "LA"}
    return {}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _write(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _write_json(stage: Path, relative: Path, value: object) -> Path:
    return _write(stage, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _copy(stage: Path, source: Path, relative: Path) -> Path:
    content = source.read_bytes()
    target = _write(stage, relative, content)
    if target.read_bytes() != content:
        raise PipelineError(f"stage copy differs: {source}")
    return target


def _work_row(work_id: str) -> dict[str, object]:
    rows = _json(ROOT / PROFILE)["works"]
    matches = [row for row in rows if row["work_id"] == work_id and work_id in ELIGIBLE]
    if len(matches) != 1:
        raise PipelineError(f"not one eligible LIB-051 single-work witness: {work_id}")
    work = _json(ROOT / "library/works" / work_id / "work.json")
    forms = work.get("textual_forms", [])
    if len(forms) != 1 or len(forms[0].get("editions", [])) != 1:
        raise PipelineError("LIB-051 child form/edition is not unique")
    edition = forms[0]["editions"][0]
    acquisitions = edition.get("acquisition_ids", [])
    if len(acquisitions) != 1:
        raise PipelineError("LIB-051 child acquisition is not unique")
    return {"work_id": work_id, "form_id": forms[0]["textual_form_id"],
            "edition_id": edition["edition_id"], "acquisition_id": acquisitions[0],
            "source": {"path": matches[0]["path"], "sha256": matches[0]["sha256"]}}


def _structure_counts(value: object, counts: Counter[str]) -> None:
    if isinstance(value, dict):
        kind = value.get("kind")
        if isinstance(kind, str):
            counts[kind] += 1
        for child in value.values():
            _structure_counts(child, counts)
    elif isinstance(value, list):
        for child in value:
            _structure_counts(child, counts)


def prepare(work_id: str, stage: Path) -> dict[str, object]:
    row = _work_row(work_id)
    candidate_root, cohort = ((FINAL_CANDIDATES, FINAL_CHILDREN) if work_id in FINAL_CHILDREN
                              else (CANDIDATES, CHILDREN))
    stage = stage.resolve(strict=False)
    if stage.exists() or stage.parent != LIBRARY.resolve(strict=True) or not stage.name.startswith("l51-"):
        raise PipelineError("stage must be a fresh l51-prefixed direct child of the durable library root")
    identity = {
        "work_id": work_id,
        "textual_form_id": row["form_id"],
        "edition_id": row["edition_id"],
        "acquisition_id": row["acquisition_id"],
    }
    work = Path("library/works") / work_id
    edition = work / "forms" / row["form_id"] / "editions" / row["edition_id"]
    acquisition_path = edition / "acquisitions" / (row["acquisition_id"] + ".json")
    source = Path(row["source"]["path"])
    source_bytes = (ROOT / source).read_bytes()
    acquisition = _json(ROOT / acquisition_path)
    retained = acquisition["retained_files"]
    if (len(retained) != 1 or retained[0]["path"] != source.as_posix()
            or retained[0]["sha256"] != _sha(source_bytes)
            or retained[0]["bytes"] != len(source_bytes)
            or acquisition["source_sha256"] != _sha(source_bytes)
            or row["source"]["sha256"] != _sha(source_bytes)):
        raise PipelineError("acquisition, family receipt, and retained XML differ")
    xml = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    head, body = xml.find("ThML.head"), xml.find("ThML.body")
    if xml.tag != "ThML" or head is None or body is None:
        raise PipelineError("one complete ThML witness required")
    source_bytes, divisions = _source_boundary({"path": source.as_posix(), "bytes": len(source_bytes), "sha256": _sha(source_bytes), "work_id": work_id})
    source_title = head.findtext(".//DC.Title")
    source_author = head.findtext(".//DC.Creator[@sub='Author']")
    if head.findtext(".//DC.Language") != "eng" or not source_title or "Owen" not in (source_author or ""):
        raise PipelineError("retained Owen header does not support proposed identity")
    creator = "John Owen"
    manifest_path = MANIFEST
    manifest = SourceManifest.load(ROOT / manifest_path, repository_root=ROOT)
    manifest.verify()
    profile_sha = _sha((ROOT / PROFILE).read_bytes())
    child_receipt = _json(candidate_root / work_id / "receipt.json")
    original = (candidate_root / work_id / "candidate.tei.xml").read_bytes()
    candidate_receipt = _json(candidate_root / "receipt.json")
    if (child_receipt.get("contract") != "ocd-lib051-readable-work-candidate-v1"
            or child_receipt.get("status") != "validated-nonaccepted"
            or child_receipt.get("identity") != identity
            or child_receipt.get("source_sha256") != _sha(source_bytes)
            or child_receipt.get("tei_sha256") != _sha(original)
            or child_receipt.get("source_manifest_sha256") != manifest.sha256
            or child_receipt.get("projection_rows") != 1
            or len(candidate_receipt.get("work_ids", [])) != len(cohort)
            or set(candidate_receipt.get("work_ids", [])) != cohort
            or candidate_receipt.get("receipts", {}).get(work_id)
               != _sha((candidate_root / work_id / "receipt.json").read_bytes())):
        raise PipelineError("frozen LIB-051 readable candidate or source oracle binding differs")
    if child_receipt.get("top_level_divisions") != [
            {"id": division["source_id"], "title": division["title"]} for division in divisions]:
        raise PipelineError("LIB-051 direct source division inventory differs")
    member_id = source.stem
    source_nodes = verify_original_source(work_id, source_bytes, original, member_id=member_id)
    if child_receipt.get("source_nodes") != source_nodes:
        raise PipelineError("LIB-051 direct source oracle node count differs")
    original_tree = etree.fromstring(original)
    source_features = _source_features(work_id, body, original_tree)
    source_publisher = head.findtext(".//DC.Publisher")
    if original_tree.xpath("string(./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:publisher)", namespaces=NS) != (source_publisher or ""):
        raise PipelineError("TEI source attribution differs from retained electronic header")
    body_nodes = len(list(body.iter())) - 1

    work_record = _json(ROOT / work / "work.json")
    state = _json(ROOT / work / "state.json")
    form = work_record["textual_forms"][0]
    edition_record = form["editions"][0]
    if (work_record["work_id"] != work_id or form["textual_form_id"] != row["form_id"]
            or form["language"] != "en" or edition_record["language"] != "en"
            or edition_record["edition_id"] != row["edition_id"]
            or edition_record["acquisition_ids"] != [row["acquisition_id"]]
            or edition_record.get("category") is not None or work_record.get("creators")):
        raise PipelineError("canonical work metadata changed; review proposed delta")
    edition_record["category"] = "prose"
    work_record["creators"] = [{"name": creator, "role": "author", "evidence": [source.as_posix()]}]
    evidence = work / "integration" / f"lib051-{work_id}-electronic-v1"
    scope = f"Complete retained CCEL Owen electronic witness {source.as_posix()} (one acquired XML file)."
    source_binding = {"source_path": source.as_posix(), "source_sha256": _sha(source_bytes), "source_bytes": len(source_bytes), "source_scope": acquisition["source_scope"]}
    now = datetime.now(timezone.utc)
    at = now.isoformat().replace("+00:00", "Z")
    revision = {"id": f"{work_id}-ccel-electronic-v1", "date": now.date().isoformat(), "note": "Accept the complete retained CCEL Owen electronic witness."}
    bound = bind_reviewed_header(original, expected_sha256=_sha(original), identity=identity, source=source_binding, source_url=acquisition["url"], declared_scope=scope, revision=revision)
    if etree.tostring(original_tree.find("tei:text", NS), method="c14n") != etree.tostring(etree.fromstring(bound).find("tei:text", NS), method="c14n"):
        raise PipelineError("reviewed-header binding changed TEI text")

    stage.mkdir()
    _write_json(stage, work / "work.json", work_record)
    _write_json(stage, work / "state.json", state)
    for relative in (acquisition_path, source, manifest_path, PROFILE):
        _copy(stage, ROOT / relative, relative)
    inherited = set(work_record.get("evidence", []))
    for target in state["targets"]:
        inherited.update(target.get("evidence", []))
    for reference in sorted(inherited):
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts or not (ROOT / relative).is_file():
            raise PipelineError(f"inherited evidence cannot be resolved: {reference}")
        if not (stage / relative).is_file():
            _copy(stage, ROOT / relative, relative)
    original_path = _write(stage, evidence / "inputs/original.tei.xml", original)
    _copy(stage, candidate_root / work_id / "receipt.json", evidence / "inputs/child-receipt.json")
    _copy(stage, candidate_root / work_id / "source-accounting.json", evidence / "inputs/candidate-source-accounting.json")
    _copy(stage, candidate_root / "receipt.json", evidence / "inputs/candidate-batch-receipt.json")
    master_candidate = _write(stage, evidence / "candidate.tei.xml", bound)
    if errors := validate_file(master_candidate):
        raise PipelineError(f"staged TEI P5 failed: {errors[:3]}")
    expected = [{"path": source.as_posix(), "position": 1}]
    included = [{"path": source.as_posix(), "position": 1, "bytes": len(source_bytes), "sha256": _sha(source_bytes), "scope": retained[0]["scope"]}]
    accepted_scope = {"kind": "edition", "declared": scope, "expected_members": expected, "included_members": included, "excluded_members": []}
    common = {"identity": identity, "source": source_binding, "candidate": make_file_binding(stage, master_candidate)}
    accounting_data = {
        "identity": identity, "source": source_binding, "scope": source_binding["source_scope"],
        "accepted_scope": {"kind": "edition", "declared": scope}, "expected_members": expected,
        "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": [],
        "source_sha256": _sha(source_bytes), "source_bytes": len(source_bytes),
        "source_manifest_sha256": manifest.sha256, "profile_sha256": profile_sha,
        "candidate_receipt_sha256": _sha((candidate_root / "receipt.json").read_bytes()), "body_nodes": body_nodes,
        "source_path": source.as_posix(),
        "original_candidate": make_file_binding(stage, original_path),
        "source_url": acquisition["url"], "declared_scope": scope,
        "source_body_c14n_sha256": _sha(etree.tostring(body, method="c14n")),
        "readable_body_c14n_sha256": _sha(etree.tostring(original_tree.find("tei:text/tei:body", NS), method="c14n")),
        "source_features": source_features,
    }
    if work_id in READABLE_WORKS:
        accounting_data["projection_profile"] = READABLE_PROFILE
    elif work_id in FINAL_WORKS:
        accounting_data["projection_profile"] = FINAL_PROFILE
    accounting = _write_json(stage, evidence / "source-accounting.json", accounting_data)
    inputs = {"source_manifest_sha256": manifest.sha256, "profile_sha256": profile_sha,
              "candidate_receipt_sha256": _sha((candidate_root / "receipt.json").read_bytes()),
              "candidate_source_accounting_sha256": child_receipt["source_accounting_sha256"],
              "original_tei_sha256": _sha(original), "source_sha256": _sha(source_bytes)}
    metadata = _write_json(stage, evidence / "metadata.json", {
        "identity": identity, "source_header": {"DC.Title": source_title,
            "DC.Creator": source_author, "DC.Language": "eng", "DC.Type": head.findtext(".//DC.Type"),
            "DC.Publisher": source_publisher},
        "proposed_work": {"category": "prose", "language": "en", "creator": creator},
        "unclaimed": ["print edition", "original publication year", "transcription license", "public release rights"], **inputs,
    })
    command = f"py -3 -m build.tools.stage_lib051_owen_acceptance --work-id {work_id} --stage <fresh-l51-library-child>"
    technical = {"producer": {"id": manifest.record["converter"]["id"], "path": make_file_binding(stage, stage / manifest_path)},
                 "checker": {"id": manifest.record["validator"]["id"], "path": make_file_binding(stage, stage / manifest_path)},
                 "shared_assumptions": ["Producer and oracle share the one-file envelope and source-profile declaration; the oracle traverses retained XML independently and checks the actual TEI."],
                 "independent_corroboration": "Fresh source-led oracle, exact candidate binding, P5 validation, and stage-native projection independently corroborate the electronic witness."}
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = common | {"scope": scope, "status": "pass", "command": command, "exit_code": 0,
                          "claim": name, "inputs": inputs, "metadata_sha256": _sha(metadata.read_bytes())}
        if name == "accounting":
            proof |= {"accepted_scope": {"kind": "edition", "declared": scope}, "expected_members": expected,
                      "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": []}
        path = _write_json(stage, evidence / f"{name}.json", proof)
        technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
    review = {"reviewer": "agent:lib051-owen-electronic-witness-assessment", "reviewed_at": at,
              "coverage": {"status": "partial", "declared": scope,
                           "reached": ["retained ThML header", "complete top-level division and index boundary", "source-led independent oracle across all body nodes"],
                           "inspected": ["retained ThML header", "complete top-level division and index boundary", "source-led independent oracle across all body nodes"],
                           "unreviewed": ["close visual comparison", "print collation"]},
              "source_quality_uncertainty": ["No print witness was collated against the retained CCEL XML."],
              "discrepancies": [],
              "unreviewed_residuals": ["No CVW frame or whole-work visual proofreading is claimed; the complete body was checked mechanically."]}
    report = _write_json(stage, evidence / "review.json", common | {"scope": scope, **review,
        "top_level_divisions": [{"id": div["source_id"], "title": div["title"]} for div in divisions],
        "visual_frames": [], "source_document_copyright_notice": (
            "Copyright Christian Classics Ethereal Library"
            if b"Copyright Christian Classics Ethereal Library" in source_bytes else None
        ),
        "source_header_rights_claim": head.findtext(".//DC.Rights"),
    })
    decision = {"source_local_disposition": f"Agent acceptance of the complete retained CCEL {work_id} electronic witness.",
                "blockers": [], "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                  "assessed_at": at, "supported_scope": scope, "unresolved_claims": [],
                  "unassessed_stronger_claims": ["print edition identity and collation", "close visual proofreading",
                                                  "human acceptance", "public rights clearance", "publication"]},
                "human_decision": {"status": "not-recorded"}}
    record = build_acceptance_record(stage, identity=identity, candidate_path=master_candidate,
        source_accounting_path=accounting, scope=accepted_scope, technical=technical,
        review=review | {"report_path": report}, representation_revision=revision, decision=decision)
    acceptance = stage / edition / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    master = _write(stage, edition / "master.tei.xml", bound)
    record["promotion"] |= {"status": "promoted", "promoted_at": at, "master": make_file_binding(stage, master)}
    write_acceptance(acceptance, record)
    target = next((item for item in state["targets"] if item["target_id"] == row["edition_id"]), None)
    if target is None or target["stage"] != "acquired":
        raise PipelineError("edition target is no longer acquired")
    target |= {"stage": "accepted", "reason": PROMOTED_MASTER_REASON, "updated_at": at}
    target["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    _write_json(stage, work / "state.json", state)
    validate_acceptance(acceptance, root=stage)
    load_work(stage / work / "work.json")
    projection = project_accepted_prose(stage, acceptance_path=acceptance)
    problems = verify_accepted_prose(stage, acceptance_path=acceptance,
                                     rows=projection["rows"], receipt=projection["receipt"])
    counts: Counter[str] = Counter()
    for projected_row in projection["rows"]:
        _structure_counts(projected_row.get("structure"), counts)
    if problems or len(projection["rows"]) != 1 or projection["receipt"]["unsupported"] or not counts["division"]:
        raise PipelineError(f"native prose projection is unsupported or not independently verified: {problems[:3]}; {projection['receipt']['unsupported'][:3]}")
    canary = _write_json(stage, evidence / "projection-canary.json", {
        "category": "prose", "row_count": len(projection["rows"]), "structure_kinds": dict(counts),
        "source_inventory_count": len(projection["receipt"]["inventory"]),
        "unsupported": projection["receipt"]["unsupported"], "warnings": projection["receipt"]["warnings"],
        "independent_verifier_errors": problems,
    })
    result = {"contract": "ocd-lib051-owen-electronic-stage-v1", "status": "staged-only",
              "work_id": work_id, "stage_root": stage.as_posix(),
              "acceptance_path": acceptance.relative_to(stage).as_posix(),
              "acceptance_sha256": _sha(acceptance.read_bytes()), "master_sha256": _sha(master.read_bytes()),
              "source_sha256": _sha(source_bytes), "source_manifest_sha256": manifest.sha256,
              "profile_sha256": profile_sha, "candidate_receipt_sha256": _sha((candidate_root / "receipt.json").read_bytes()),
              "metadata_sha256": _sha(metadata.read_bytes()), "body_nodes": body_nodes,
              "source_features": source_features,
              "projection_category": "prose", "projection_rows": len(projection["rows"]),
              "projection_structure_kinds": dict(counts), "projection_source_inventory_count": len(projection["receipt"]["inventory"]),
              "projection_canary_sha256": _sha(canary.read_bytes()),
              "projection_independent_verifier_errors": problems, "visual_review": "not-performed",
              "rights_clearance": "not-assessed", "human_review": "not-recorded", "publication": "not-authorized",
              "code_sha256": {path: _sha((ROOT / path).read_bytes()) for path in CODE_PATHS}}
    _write_json(stage, Path("stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.work_id, args.stage), sort_keys=True))


if __name__ == "__main__":
    main()
