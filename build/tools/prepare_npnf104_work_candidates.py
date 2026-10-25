"""Prepare exact NPNF104 work-local manifests from the validated aggregate."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei import npnf104_lib038_reconstruction as aggregate
from build.tei.npnf104_work_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("sources/structured-text/augustine-npnf104-works")
SOURCE = Path(aggregate.SOURCE_PATH)
AGGREGATE = Path("D:/Library/Open Christian Data/candidate-reviews/augustine-npnf104-aggregate-20260927")
BATCH = Path("plans/2026-09-22-source-preflight/augustine-npnf104-work-candidates-20260927.json")


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _binding(path: Path, role: str, name: str) -> dict:
    content = Path(_io_path(ROOT / path)).read_bytes()
    return {"name": name, "path": path.as_posix(), "role": role,
            "bytes": len(content), "sha256": _sha(content)}


def prepare(destination: Path) -> dict:
    if (ROOT / BATCH).exists() or (ROOT / HOME).exists() or not destination.is_dir():
        raise ValueError("fresh NPNF104 work evidence and existing destination required")
    aggregate_package = CandidatePackage.load(AGGREGATE / "package")
    validation_bytes = (AGGREGATE / "validation.json").read_bytes()
    aggregate_validation = json.loads(validation_bytes)
    if aggregate_validation.get("status") != "pass" or aggregate_validation.get("candidate_sha256") != aggregate_package.sha256:
        raise ValueError("current aggregate candidate is not validated")
    source_bytes = Path(_io_path(ROOT / SOURCE)).read_bytes()
    if _sha(source_bytes) != aggregate.SOURCE_SHA256:
        raise ValueError("retained NPNF104 source changed")
    _top, selected = aggregate._structure(aggregate._parse(ROOT / SOURCE))
    aggregate_doc = etree.fromstring(aggregate_package.member_bytes("content.tei.xml"), etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    body = aggregate_doc.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
    if body is None or len(body) != 10:
        raise ValueError("aggregate lacks exactly ten work divisions")
    policy = {"contract": "ocd-npnf104-work-policy-v1", "status": "nonaccepted",
              "source_selection": "One exact direct div2 root; shared volume matter remains in retained source and aggregate accounting.",
              "closure_inputs": ["build/tei/npnf104_work_oracle.py", "build/tei/npnf104_lib038_oracle.py",
                                 "ocd_kernel/reconstruction/contract.py"]}
    policy_path = HOME / "validation-policy.json"
    (ROOT / policy_path).parent.mkdir(parents=True, exist_ok=False)
    (ROOT / policy_path).write_bytes(_json(policy))
    closure_sha = _sha(_json([{"path": rel, "sha256": _sha((ROOT / rel).read_bytes())}
                             for rel in policy["closure_inputs"]]))
    converter = Path("build/tei/npnf104_work_reconstruction.py")
    validator = Path("build/tei/npnf104_work_oracle.py")
    schema = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
    xsd = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    results: list[dict] = []
    offset = 0
    for index, ((scope, work_id), node) in enumerate(zip(aggregate.ASSIGNED, selected, strict=True)):
        if node.get("id") != scope:
            raise ValueError(f"NPNF104 source root changed: {work_id}")
        work_rel = Path("library/works") / work_id / "work.json"
        state_rel = Path("library/works") / work_id / "state.json"
        work = json.loads(Path(_io_path(ROOT / work_rel)).read_bytes())
        state = json.loads(Path(_io_path(ROOT / state_rel)).read_bytes())
        editions = [(form, edition) for form in work["textual_forms"] for edition in form["editions"]]
        if work["work_id"] != work_id or len(editions) != 1:
            raise ValueError(f"NPNF104 work identity changed: {work_id}")
        form, edition = editions[0]
        if edition["containing_source"]["locator"] != f"{SOURCE.as_posix()}#{scope}" or len(edition["acquisition_ids"]) != 1:
            raise ValueError(f"NPNF104 source selector changed: {work_id}")
        acquisition_id = edition["acquisition_ids"][0]
        acquisition_rel = (Path("library/works") / work_id / "forms" / form["textual_form_id"]
                           / "editions" / edition["edition_id"] / "acquisitions" / f"{acquisition_id}.json")
        acquisition_bytes = Path(_io_path(ROOT / acquisition_rel)).read_bytes()
        acquisition = json.loads(acquisition_bytes)
        if acquisition["source_sha256"] != aggregate.SOURCE_SHA256 or any(t["stage"] == "accepted" for t in state["targets"]):
            raise ValueError(f"NPNF104 acquisition or acceptance state changed: {work_id}")
        count = sum(isinstance(item.tag, str) for item in node.iter())
        profile = {"contract": "ocd-npnf104-work-profile-v1", "work_id": work_id,
                   "edition_id": edition["edition_id"], "acquisition_id": acquisition_id,
                   "acquisition_path": acquisition_rel.as_posix(), "acquisition_sha256": _sha(acquisition_bytes),
                   "work_sha256": _sha(Path(_io_path(ROOT / work_rel)).read_bytes()),
                   "div2_id": scope, "source_title": node.get("title"),
                   "feature_offset": offset, "feature_count": count,
                   "source_div2_c14n_sha256": _sha(etree.tostring(node, method="c14n")),
                   "aggregate_tei_div_c14n_sha256": _sha(etree.tostring(body[index], method="c14n")),
                   "aggregate_candidate_root": AGGREGATE.as_posix(),
                   "aggregate_candidate_sha256": aggregate_package.sha256,
                   "aggregate_validation_sha256": _sha(validation_bytes)}
        local = HOME / work_id
        (ROOT / local).mkdir(parents=True, exist_ok=False)
        profile_rel = local / "reconstruction-profile.json"
        (ROOT / profile_rel).write_bytes(_json(profile))
        authorities = [_binding(SOURCE, "primary-source", "retained-thml"),
                       _binding(profile_rel, "complete-source-feature-profile", "reconstruction-profile"),
                       _binding(policy_path, "independent-validation-policy", "validation-policy"),
                       _binding(xsd, "tei-validation-schema", "tei-p5-xsd"),
                       _binding(schema, "candidate-package-schema", "candidate-package-schema"),
                       _binding(Path("build/tei/npnf104_lib038_reconstruction.py"), "aggregate-work-mapper", "aggregate-mapper"),
                       _binding(Path("build/tei/npnf104_lib038_oracle.py"), "aggregate-source-oracle", "aggregate-oracle")]
        manifest_rel = local / "source-manifest.json"
        manifest = {"contract": "ocd-source-manifest-v1", "source_id": f"{work_id}-npnf104-div2-v1",
                    "authorities": authorities,
                    "converter": {"id": "ocd-npnf104-work-div2-to-tei", "version": "1", "callable": "_convert",
                                  "implementation_path": converter.as_posix(), "implementation_sha256": _sha((ROOT / converter).read_bytes())},
                    "validator": {"id": "ocd-npnf104-work-div2-source-oracle", "version": "1", "callable": "_oracle",
                                  "implementation_path": validator.as_posix(), "implementation_sha256": _sha((ROOT / validator).read_bytes()),
                                  "import_closure_sha256": closure_sha},
                    "package_schema": {"path": schema.as_posix(), "sha256": _sha((ROOT / schema).read_bytes())}}
        (ROOT / manifest_rel).write_bytes(_json(manifest))
        SourceManifest.load(ROOT / manifest_rel, repository_root=ROOT)
        results.append({"work_id": work_id, "div2_id": scope, "manifest_path": manifest_rel.as_posix(),
                        "manifest_sha256": _sha((ROOT / manifest_rel).read_bytes()),
                        "profile_path": profile_rel.as_posix(), "profile_sha256": _sha((ROOT / profile_rel).read_bytes()),
                        "feature_count": count, "source_div2_c14n_sha256": profile["source_div2_c14n_sha256"],
                        "acquisition_path": acquisition_rel.as_posix(), "acquisition_sha256": profile["acquisition_sha256"],
                        "candidate_root": (destination / work_id).as_posix()})
        offset += count
    if offset != 11999:
        raise ValueError("ten work features do not match aggregate source census")
    receipt = {"contract": "ocd-npnf104-work-candidate-batch-v1", "version": 1, "status": "prepared",
               "source_sha256": aggregate.SOURCE_SHA256, "aggregate_candidate_sha256": aggregate_package.sha256,
               "aggregate_validation_sha256": _sha(validation_bytes), "work_count": 10,
               "feature_count": offset, "works": results, "canonical_install": "none"}
    (ROOT / BATCH).write_bytes(_json(receipt))
    return receipt


def finalize() -> dict:
    batch_path = ROOT / BATCH
    batch = json.loads(batch_path.read_bytes())
    if batch.get("status") != "prepared" or batch.get("work_count") != 10:
        raise ValueError("NPNF104 candidate batch is not ready for finalization")
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
            raise ValueError(f"NPNF104 work candidate validation differs: {item['work_id']}")
        item["candidate_sha256"] = package.sha256
        item["candidate_tei_sha256"] = _sha(package.member_bytes("content.tei.xml"))
        item["validation_sha256"] = _sha(validation_bytes)
        item["output_file_sha256"] = {
            **{f"package/{name}": _sha(package.member_bytes(name)) for name in package.member_names},
            "validation.json": _sha(validation_bytes),
        }
    batch["status"] = "validated-nonaccepted"
    batch["validated_candidate_count"] = 10
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
