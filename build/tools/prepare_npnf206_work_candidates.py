"""Prepare exact NPNF206 treatise candidates from the current LIB-048 aggregate."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei import npnf2_lib048_reconstruction as aggregate
from build.tei.npnf206_work_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("sources/structured-text/jerome-npnf206-works")
SOURCE = Path(aggregate.SOURCES[0][1])
SOURCE_SHA256 = aggregate.SOURCES[0][3]
AGGREGATE = Path("D:/Library/Open Christian Data/candidate-reviews/jerome-npnf206-aggregate-20260927")
BATCH = Path("plans/2026-09-22-source-preflight/jerome-npnf206-treatise-candidates-20260927.json")
AGGREGATE_MANIFEST = Path("sources/structured-text/npnf2-lib048/npnf2-lib048.source-manifest.json")
AGGREGATE_POLICY = Path("sources/structured-text/npnf2-lib048/npnf2-lib048.validation-policy.json")
WORKS = tuple((scope, work) for key, scope, work in aggregate.ASSIGNED
              if key == "npnf206" and scope.startswith("vi."))


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _binding(path: Path, role: str, name: str) -> dict:
    content = Path(_io_path(ROOT / path)).read_bytes()
    return {"name": name, "path": path.as_posix(), "role": role,
            "bytes": len(content), "sha256": _sha(content)}


def prepare(destination: Path) -> dict:
    if (ROOT / BATCH).exists() or (ROOT / HOME).exists() or not destination.is_dir():
        raise ValueError("fresh NPNF206 work evidence and existing external destination required")
    aggregate_manifest = SourceManifest.load(ROOT / AGGREGATE_MANIFEST, repository_root=ROOT)
    aggregate_manifest.verify()
    aggregate_package = CandidatePackage.load(AGGREGATE / "package")
    validation_bytes = (AGGREGATE / "validation.json").read_bytes()
    aggregate_validation = json.loads(validation_bytes)
    if (aggregate_validation.get("status") != "pass" or aggregate_validation.get("findings")
            or aggregate_validation.get("source_manifest_sha256") != aggregate_manifest.sha256
            or aggregate_validation.get("candidate_sha256") != aggregate_package.sha256):
        raise ValueError("current LIB-048 aggregate candidate is not validated")
    source_bytes = Path(_io_path(ROOT / SOURCE)).read_bytes()
    if _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained NPNF206 source changed")
    tree = aggregate._parse(Path(_io_path(ROOT / SOURCE)))
    v = tree.xpath("//*[@id='v']")
    vi = tree.xpath("//*[@id='vi']")
    if (len(v) != 1 or len(vi) != 1 or v[0].tag != "div1" or vi[0].tag != "div1"
            or len(v[0]) != 150 or any(child.tag != "div2" for child in v[0])
            or len(vi[0]) != 9 or any(child.tag != "div2" for child in vi[0])):
        raise ValueError("NPNF206 letter or treatise volume boundaries changed")
    selected = [v[0], *list(vi[0])]
    if [node.get("id") for node in selected] != ["v", *[scope for scope, _ in WORKS]]:
        raise ValueError("NPNF206 assigned source selector order changed")
    aggregate_doc = etree.fromstring(aggregate_package.member_bytes("content.tei.xml"),
                                     etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    body = aggregate_doc.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
    if body is None or len(body) != 15:
        raise ValueError("LIB-048 aggregate lacks fifteen work divisions")
    policy = {
        "contract": "ocd-npnf206-treatise-policy-v1", "status": "nonaccepted",
        "source_selection": "One exact vi div2 treatise. The 150 individually identified Letters are held as constituents; shared volume matter remains outside work masters.",
        "closure_inputs": ["build/tei/npnf206_work_oracle.py", "build/tei/npnf2_lib048_oracle.py",
                           "ocd_kernel/reconstruction/contract.py"],
    }
    policy_path = HOME / "validation-policy.json"
    (ROOT / policy_path).parent.mkdir(parents=True, exist_ok=False)
    (ROOT / policy_path).write_bytes(_json(policy))
    closure_sha = _sha(_json([{"path": rel, "sha256": _sha((ROOT / rel).read_bytes())}
                             for rel in policy["closure_inputs"]]))
    converter = Path("build/tei/npnf206_work_reconstruction.py")
    validator = Path("build/tei/npnf206_work_oracle.py")
    schema = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
    xsd = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    results = []
    offset = len(list(v[0].iter()))
    for index, (scope, work_id) in enumerate(WORKS, start=1):
        node = selected[index]
        work_rel = Path("library/works") / work_id / "work.json"
        state_rel = Path("library/works") / work_id / "state.json"
        work_bytes = Path(_io_path(ROOT / work_rel)).read_bytes()
        work = json.loads(work_bytes)
        state = json.loads(Path(_io_path(ROOT / state_rel)).read_bytes())
        editions = [(form, edition) for form in work["textual_forms"] for edition in form["editions"]]
        if work["work_id"] != work_id or len(editions) != 1:
            raise ValueError(f"NPNF206 work identity changed: {work_id}")
        form, edition = editions[0]
        if (edition["containing_source"]["locator"] != f"{SOURCE.as_posix()}#{scope}"
                or len(edition["acquisition_ids"]) != 1):
            raise ValueError(f"NPNF206 source selector changed: {work_id}")
        acquisition_id = edition["acquisition_ids"][0]
        acquisition_rel = (Path("library/works") / work_id / "forms" / form["textual_form_id"]
                           / "editions" / edition["edition_id"] / "acquisitions" / f"{acquisition_id}.json")
        acquisition_bytes = Path(_io_path(ROOT / acquisition_rel)).read_bytes()
        acquisition = json.loads(acquisition_bytes)
        if (acquisition["source_sha256"] != SOURCE_SHA256
                or any(t["stage"] == "accepted" for t in state["targets"])):
            raise ValueError(f"NPNF206 acquisition or acceptance state changed: {work_id}")
        count = len(list(node.iter()))
        profile = {
            "contract": "ocd-npnf206-treatise-profile-v1", "work_id": work_id,
            "edition_id": edition["edition_id"], "acquisition_id": acquisition_id,
            "acquisition_path": acquisition_rel.as_posix(), "acquisition_sha256": _sha(acquisition_bytes),
            "work_sha256": _sha(work_bytes), "div2_id": scope, "source_title": node.get("title"),
            "feature_offset": offset, "feature_count": count,
            "source_div2_c14n_sha256": _sha(etree.tostring(node, method="c14n")),
            "aggregate_tei_div_c14n_sha256": _sha(etree.tostring(body[index], method="c14n")),
            "aggregate_candidate_root": AGGREGATE.as_posix(),
            "aggregate_candidate_sha256": aggregate_package.sha256,
            "aggregate_validation_sha256": _sha(validation_bytes),
        }
        local = HOME / work_id
        (ROOT / local).mkdir(parents=True, exist_ok=False)
        profile_rel = local / "reconstruction-profile.json"
        (ROOT / profile_rel).write_bytes(_json(profile))
        authorities = [
            _binding(SOURCE, "primary-source", "retained-thml"),
            _binding(profile_rel, "complete-source-feature-profile", "reconstruction-profile"),
            _binding(policy_path, "independent-validation-policy", "validation-policy"),
            _binding(AGGREGATE_POLICY, "aggregate-validation-policy", "aggregate-validation-policy"),
            _binding(xsd, "tei-validation-schema", "tei-p5-xsd"),
            _binding(schema, "candidate-package-schema", "candidate-package-schema"),
            _binding(Path("build/tei/npnf2_lib048_reconstruction.py"), "aggregate-work-mapper", "aggregate-mapper"),
            _binding(Path("build/tei/npnf2_lib048_oracle.py"), "aggregate-source-oracle", "aggregate-oracle"),
        ]
        manifest_rel = local / "source-manifest.json"
        manifest = {
            "contract": "ocd-source-manifest-v1", "source_id": f"{work_id}-npnf206-div2-v1",
            "authorities": authorities,
            "converter": {"id": "ocd-npnf206-treatise-div2-to-tei", "version": "1", "callable": "_convert",
                          "implementation_path": converter.as_posix(), "implementation_sha256": _sha((ROOT / converter).read_bytes())},
            "validator": {"id": "ocd-npnf206-treatise-div2-source-oracle", "version": "1", "callable": "_oracle",
                          "implementation_path": validator.as_posix(), "implementation_sha256": _sha((ROOT / validator).read_bytes()),
                          "import_closure_sha256": closure_sha},
            "package_schema": {"path": schema.as_posix(), "sha256": _sha((ROOT / schema).read_bytes())},
        }
        (ROOT / manifest_rel).write_bytes(_json(manifest))
        SourceManifest.load(ROOT / manifest_rel, repository_root=ROOT)
        results.append({
            "work_id": work_id, "div2_id": scope, "manifest_path": manifest_rel.as_posix(),
            "manifest_sha256": _sha((ROOT / manifest_rel).read_bytes()),
            "profile_path": profile_rel.as_posix(), "profile_sha256": _sha((ROOT / profile_rel).read_bytes()),
            "feature_count": count, "source_div2_c14n_sha256": profile["source_div2_c14n_sha256"],
            "acquisition_path": acquisition_rel.as_posix(), "acquisition_sha256": profile["acquisition_sha256"],
            "candidate_root": (destination / work_id).as_posix(),
        })
        offset += count
    if offset != 19031:
        raise ValueError("NPNF206 selected source census differs")
    receipt = {
        "contract": "ocd-npnf206-treatise-candidate-batch-v1", "version": 1, "status": "prepared",
        "source_sha256": SOURCE_SHA256, "aggregate_candidate_sha256": aggregate_package.sha256,
        "aggregate_validation_sha256": _sha(validation_bytes), "work_count": 9,
        "feature_count": offset - len(list(v[0].iter())), "works": results,
        "held_collection": {"work_id": "jerome-letters", "source_root_id": "v",
                            "constituent_div2_count": 150,
                            "reason": "Individually numbered and titled letters require constituent work identities; no sole collection master accepted."},
        "shared_source_disposition": "Volume front matter, treatise wrapper, prefaces, and indexes remain in retained source and complete aggregate accounting.",
        "canonical_install": "none",
    }
    (ROOT / BATCH).write_bytes(_json(receipt))
    return receipt


def finalize() -> dict:
    batch_path = ROOT / BATCH
    batch = json.loads(batch_path.read_bytes())
    if batch.get("status") != "prepared" or batch.get("work_count") != 9:
        raise ValueError("NPNF206 candidate batch not ready")
    for item in batch["works"]:
        manifest = SourceManifest.load(ROOT / item["manifest_path"], repository_root=ROOT)
        candidate_root = Path(item["candidate_root"])
        package = CandidatePackage.load(candidate_root / "package")
        validation_bytes = (candidate_root / "validation.json").read_bytes()
        validation = json.loads(validation_bytes)
        checked = validate(manifest, package, _oracle)
        if (checked.status != "pass" or checked.findings or validation.get("status") != "pass"
                or validation.get("report_sha256") != checked.sha256
                or validation.get("candidate_sha256") != package.sha256):
            raise ValueError(f"NPNF206 treatise candidate validation differs: {item['work_id']}")
        item["candidate_sha256"] = package.sha256
        item["candidate_tei_sha256"] = _sha(package.member_bytes("content.tei.xml"))
        item["validation_sha256"] = _sha(validation_bytes)
        item["output_file_sha256"] = {
            **{f"package/{name}": _sha(package.member_bytes(name)) for name in package.member_names},
            "validation.json": _sha(validation_bytes),
        }
    batch["status"] = "validated-nonaccepted"
    batch["validated_candidate_count"] = 9
    batch_path.write_bytes(_json(batch))
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize == (args.destination is not None):
        parser.error("choose exactly one of --destination and --finalize")
    result = finalize() if args.finalize else prepare(args.destination)
    print(json.dumps({"work_count": result["work_count"], "feature_count": result["feature_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
