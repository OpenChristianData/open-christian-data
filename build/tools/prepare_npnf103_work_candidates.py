"""Create and validate one nonaccepted candidate for each source-attested NPNF103 work."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei import npnf103_reconstruction as aggregate
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("sources/structured-text/augustine-npnf103-works")
SOURCE = Path(aggregate.SOURCE_PATH)
AGGREGATE = Path("D:/Library/Open Christian Data/candidate-reviews/37c-061-npnf103-20260913-r1")
BATCH = Path("plans/2026-09-22-source-preflight/augustine-npnf103-work-candidates-v2-20260926.json")
SIDECARS = Path("plans/2026-09-22-source-preflight/augustine-npnf103-sixteen-sidecar-batch-20260926.json")


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _binding(path: Path, role: str, name: str) -> dict:
    data = Path(_io_path(ROOT / path)).read_bytes()
    return {"name": name, "path": path.as_posix(), "role": role,
            "bytes": len(data), "sha256": _sha(data)}


def prepare(destination: Path) -> dict:
    if BATCH.exists() or not destination.is_dir():
        raise ValueError("fresh candidate batch receipt and existing destination required")
    aggregate_package = CandidatePackage.load(AGGREGATE / "package")
    aggregate_validation = json.loads((AGGREGATE / "validation.json").read_bytes())
    if aggregate_validation.get("status") != "pass" or aggregate_validation.get("candidate_sha256") != aggregate_package.sha256:
        raise ValueError("retained aggregate candidate is not validated")
    tree = aggregate._parse(ROOT / SOURCE)
    _top, selected = aggregate._structure(tree)
    aggregate_doc = etree.fromstring(aggregate_package.member_bytes("content.tei.xml"),
                                    etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    body = aggregate_doc.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
    if body is None or len(body) != 16:
        raise ValueError("aggregate candidate lacks sixteen work divs")
    entries = json.loads((ROOT / SIDECARS).read_bytes())["entries"]
    if len(entries) != 16 or {x["work_id"] for x in entries} != {work for _, work in aggregate.ASSIGNED}:
        raise ValueError("dated acquisition index differs from sixteen assigned works")
    by_id = {entry["work_id"]: entry for entry in entries}
    policy = {"contract": "ocd-npnf103-work-policy-v1", "status": "nonaccepted",
              "source_selection": "One exact direct div2 work root; shared volume matter stays in the acquired source and aggregate accounting.",
              "closure_inputs": ["build/tei/npnf103_work_oracle.py", "build/tei/npnf103_oracle.py",
                                 "ocd_kernel/reconstruction/contract.py"]}
    policy_path = HOME / "validation-policy.json"
    (ROOT / policy_path).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / policy_path).write_bytes(_json(policy))
    closure_sha = _sha(_json([{"path": rel, "sha256": _sha((ROOT / rel).read_bytes())}
                             for rel in policy["closure_inputs"]]))
    converter = Path("build/tei/npnf103_work_reconstruction.py")
    validator = Path("build/tei/npnf103_work_oracle.py")
    schema = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
    xsd = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    results = []
    offset = 0
    for index, ((scope, work_id), node) in enumerate(zip(aggregate.ASSIGNED, selected, strict=True)):
        entry = by_id[work_id]
        if (node.get("id") != scope or entry["containing_source"]["locator"] != f"{SOURCE.as_posix()}#{scope}"):
            raise ValueError(f"source/acquisition locator differs: {work_id}")
        work_rel = Path("library/works") / work_id / "work.json"
        work = json.loads(Path(_io_path(ROOT / work_rel)).read_bytes())
        editions = [(form, edition) for form in work["textual_forms"] for edition in form["editions"]
                    if edition["edition_id"] == entry["edition_id"]]
        if len(editions) != 1 or entry["acquisition_id"] not in editions[0][1]["acquisition_ids"]:
            raise ValueError(f"current edition/acquisition identity differs: {work_id}")
        form = editions[0][0]
        acquisition_rel = (Path("library/works") / work_id / "forms" / form["textual_form_id"]
                           / "editions" / entry["edition_id"] / "acquisitions"
                           / f"{entry['acquisition_id']}.json")
        acquisition = json.loads(Path(_io_path(ROOT / acquisition_rel)).read_bytes())
        if acquisition["source_sha256"] != aggregate.SOURCE_SHA256:
            raise ValueError(f"acquisition source differs: {work_id}")
        count = len(list(node.iter()))
        profile = {
            "contract": "ocd-npnf103-work-profile-v1", "work_id": work_id,
            "edition_id": entry["edition_id"], "acquisition_id": entry["acquisition_id"],
            "acquisition_path": acquisition_rel.as_posix(),
            "acquisition_sha256": _sha(Path(_io_path(ROOT / acquisition_rel)).read_bytes()),
            "work_sha256": _sha(Path(_io_path(ROOT / work_rel)).read_bytes()),
            "div2_id": scope, "source_title": node.get("title"),
            "feature_offset": offset, "feature_count": count,
            "source_div2_c14n_sha256": _sha(etree.tostring(node, method="c14n")),
            "aggregate_tei_div_c14n_sha256": _sha(etree.tostring(body[index], method="c14n")),
            "aggregate_candidate_root": AGGREGATE.as_posix(),
            "aggregate_candidate_sha256": aggregate_package.sha256,
            "aggregate_validation_sha256": _sha((AGGREGATE / "validation.json").read_bytes()),
        }
        local = HOME / work_id
        (ROOT / local).mkdir(parents=True, exist_ok=False)
        profile_rel = local / "reconstruction-profile.json"
        (ROOT / profile_rel).write_bytes(_json(profile))
        authorities = [
            _binding(SOURCE, "primary-source", "retained-thml"),
            _binding(profile_rel, "complete-source-feature-profile", "reconstruction-profile"),
            _binding(policy_path, "independent-validation-policy", "validation-policy"),
            _binding(xsd, "tei-validation-schema", "tei-p5-xsd"),
            _binding(schema, "candidate-package-schema", "candidate-package-schema"),
            _binding(Path("build/tei/npnf103_reconstruction.py"), "aggregate-work-mapper", "aggregate-mapper"),
            _binding(Path("build/tei/npnf103_oracle.py"), "aggregate-source-oracle", "aggregate-oracle"),
        ]
        manifest_rel = local / "source-manifest.json"
        manifest = {
            "contract": "ocd-source-manifest-v1", "source_id": f"{work_id}-npnf103-div2-v1",
            "authorities": authorities,
            "converter": {"id": "ocd-npnf103-work-div2-to-tei", "version": "1", "callable": "_convert",
                          "implementation_path": converter.as_posix(), "implementation_sha256": _sha((ROOT / converter).read_bytes())},
            "validator": {"id": "ocd-npnf103-work-div2-source-oracle", "version": "1", "callable": "_oracle",
                          "implementation_path": validator.as_posix(), "implementation_sha256": _sha((ROOT / validator).read_bytes()),
                          "import_closure_sha256": closure_sha},
            "package_schema": {"path": schema.as_posix(), "sha256": _sha((ROOT / schema).read_bytes())},
        }
        (ROOT / manifest_rel).write_bytes(_json(manifest))
        SourceManifest.load(ROOT / manifest_rel, repository_root=ROOT)
        results.append({"work_id": work_id, "div2_id": scope, "manifest_path": manifest_rel.as_posix(),
                        "manifest_sha256": _sha((ROOT / manifest_rel).read_bytes()),
                        "profile_path": profile_rel.as_posix(), "profile_sha256": _sha((ROOT / profile_rel).read_bytes()),
                        "feature_count": count, "source_div2_c14n_sha256": profile["source_div2_c14n_sha256"],
                        "acquisition_path": acquisition_rel.as_posix(), "acquisition_sha256": profile["acquisition_sha256"],
                        "candidate_root": (destination / work_id).as_posix()})
        offset += count
    if offset != 12832:
        raise ValueError("sixteen work features do not sum to aggregate source census")
    receipt = {"contract": "ocd-npnf103-work-candidate-batch-v1", "status": "prepared",
               "source_sha256": aggregate.SOURCE_SHA256,
               "aggregate_candidate_sha256": aggregate_package.sha256,
               "aggregate_validation_sha256": _sha((AGGREGATE / "validation.json").read_bytes()),
               "work_count": 16, "feature_count": offset, "works": results,
               "canonical_install": "none"}
    (ROOT / BATCH).write_bytes(_json(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    receipt = prepare(args.destination)
    print(json.dumps({"work_count": receipt["work_count"], "feature_count": receipt["feature_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
