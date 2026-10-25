"""Bind ten NPNF105 direct-div1 works to separate source-local candidates."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei import npnf105_reconstruction as aggregate
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("sources/structured-text/augustine-npnf105-works")
SOURCE = Path("raw/ccel/npnf1/npnf105.xml")
SIDECARS = Path("plans/2026-09-22-source-preflight/augustine-npnf105-eleven-sidecar-packet-20260926.json")
BATCH = Path("plans/2026-09-22-source-preflight/augustine-npnf105-ten-work-candidates-20260927.json")
SELECTED = ("x", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx")
CONTENTS_CREDIT = {
    "x": "iii-p10", "xii": "iii-p19", "xiii": "iii-p24", "xiv": "iii-p28",
    "xv": "iii-p33", "xvi": "iii-p38", "xvii": "iii-p46",
}


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _binding(path: Path, role: str, name: str) -> dict:
    data = Path(_io_path(ROOT / path)).read_bytes()
    return {"name": name, "path": path.as_posix(), "role": role,
            "bytes": len(data), "sha256": _sha(data)}


def prepare(destination: Path) -> dict:
    if (ROOT / BATCH).exists() or not destination.is_dir():
        raise ValueError("fresh NPNF105 profile home and candidate destination required")
    if _sha((ROOT / SOURCE).read_bytes()) != aggregate.SOURCE_SHA256:
        raise ValueError("retained NPNF105 source changed")
    tree = aggregate._parse(ROOT / SOURCE)
    divisions = aggregate._source_divisions(tree)
    packet = json.loads((ROOT / SIDECARS).read_bytes())
    entries = {entry["work_id"]: entry for entry in packet["entries"]}
    if len(entries) != 11:
        raise ValueError("eleven acquired NPNF105 child records required")
    policy = {
        "contract": "ocd-npnf105-work-policy-v1", "status": "nonaccepted",
        "source_selection": "One complete direct div1 work root; shared volume matter and siblings stay in the retained XML.",
        "credit_evidence_ids": [*CONTENTS_CREDIT.values(), "iii-p74", "ix-p14"],
        "closure_inputs": ["build/tei/npnf105_work_oracle.py", "build/tei/npnf105_oracle.py",
                           "ocd_kernel/reconstruction/contract.py"],
    }
    policy_path = HOME / "validation-policy.json"
    (ROOT / policy_path).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / policy_path).write_bytes(_json(policy))
    closure_sha = _sha(_json([{"path": rel, "sha256": _sha((ROOT / rel).read_bytes())}
                             for rel in policy["closure_inputs"]]))
    converter = Path("build/tei/npnf105_work_reconstruction.py")
    validator = Path("build/tei/npnf105_work_oracle.py")
    schema = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
    xsd = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    results = []
    offset = 0
    for index, (scope, work_id) in enumerate(aggregate.ASSIGNED):
        node = divisions[9 + index]
        count = len([child for child in node.iter() if isinstance(child.tag, str)])
        if scope not in SELECTED:
            offset += count
            continue
        entry = entries[work_id]
        if node.get("id") != scope or entry["containing_source"]["locator"] != f"{SOURCE.as_posix()}#{scope}":
            raise ValueError(f"source and acquisition selector disagree: {work_id}")
        work_rel = Path("library/works") / work_id / "work.json"
        work = json.loads(Path(_io_path(ROOT / work_rel)).read_bytes())
        matches = [(form, edition) for form in work["textual_forms"] for edition in form["editions"]
                   if edition["edition_id"] == entry["edition_id"]]
        if len(matches) != 1 or entry["acquisition_id"] not in matches[0][1]["acquisition_ids"]:
            raise ValueError(f"work identity differs: {work_id}")
        form = matches[0][0]
        acquisition_rel = (Path("library/works") / work_id / "forms" / form["textual_form_id"]
                           / "editions" / entry["edition_id"] / "acquisitions"
                           / f"{entry['acquisition_id']}.json")
        acquisition = json.loads(Path(_io_path(ROOT / acquisition_rel)).read_bytes())
        if acquisition["source_sha256"] != aggregate.SOURCE_SHA256:
            raise ValueError(f"source acquisition digest differs: {work_id}")
        translator = "Robert Ernest Wallis" if scope in {"xviii", "xx"} else "Peter Holmes"
        evidence_id = CONTENTS_CREDIT.get(scope, "ix-p14")
        profile = {
            "contract": "ocd-npnf105-work-profile-v1", "work_id": work_id,
            "edition_id": entry["edition_id"], "acquisition_id": entry["acquisition_id"],
            "acquisition_path": acquisition_rel.as_posix(),
            "acquisition_sha256": _sha(Path(_io_path(ROOT / acquisition_rel)).read_bytes()),
            "work_sha256": _sha(Path(_io_path(ROOT / work_rel)).read_bytes()),
            "div1_id": scope, "source_title": node.get("title"),
            "feature_offset": offset, "feature_count": count,
            "source_div1_c14n_sha256": _sha(etree.tostring(node, method="c14n")),
            "translator": translator, "translator_evidence_id": evidence_id,
        }
        local = HOME / work_id
        (ROOT / local).mkdir(parents=True, exist_ok=True)
        profile_rel = local / "reconstruction-profile.json"
        if (ROOT / profile_rel).exists():
            raise ValueError(f"pre-existing NPNF105 work profile: {work_id}")
        (ROOT / profile_rel).write_bytes(_json(profile))
        authorities = [
            _binding(SOURCE, "primary-source", "retained-thml"),
            _binding(profile_rel, "complete-source-feature-profile", "reconstruction-profile"),
            _binding(policy_path, "independent-validation-policy", "validation-policy"),
            _binding(xsd, "tei-validation-schema", "tei-p5-xsd"),
            _binding(schema, "candidate-package-schema", "candidate-package-schema"),
            _binding(Path("build/tei/npnf105_reconstruction.py"), "aggregate-work-mapper", "aggregate-mapper"),
            _binding(Path("build/tei/npnf105_oracle.py"), "aggregate-source-oracle", "aggregate-oracle"),
        ]
        manifest_rel = local / "source-manifest.json"
        manifest = {
            "contract": "ocd-source-manifest-v1", "source_id": f"{work_id}-npnf105-div1-v1",
            "authorities": authorities,
            "converter": {"id": "ocd-npnf105-work-div1-to-tei", "version": "1", "callable": "_convert",
                          "implementation_path": converter.as_posix(), "implementation_sha256": _sha((ROOT / converter).read_bytes())},
            "validator": {"id": "ocd-npnf105-work-div1-source-oracle", "version": "1", "callable": "_oracle",
                          "implementation_path": validator.as_posix(), "implementation_sha256": _sha((ROOT / validator).read_bytes()),
                          "import_closure_sha256": closure_sha},
            "package_schema": {"path": schema.as_posix(), "sha256": _sha((ROOT / schema).read_bytes())},
        }
        (ROOT / manifest_rel).write_bytes(_json(manifest))
        SourceManifest.load(ROOT / manifest_rel, repository_root=ROOT)
        results.append({"work_id": work_id, "div1_id": scope, "manifest_path": manifest_rel.as_posix(),
                        "manifest_sha256": _sha((ROOT / manifest_rel).read_bytes()),
                        "profile_path": profile_rel.as_posix(), "profile_sha256": _sha((ROOT / profile_rel).read_bytes()),
                        "feature_count": count, "source_div1_c14n_sha256": profile["source_div1_c14n_sha256"],
                        "acquisition_path": acquisition_rel.as_posix(), "acquisition_sha256": profile["acquisition_sha256"],
                        "candidate_root": (destination / work_id).as_posix()})
        offset += count
    if len(results) != 10:
        raise ValueError("ten distinct child candidates required")
    receipt = {"contract": "ocd-npnf105-work-candidate-batch-v1", "status": "prepared",
               "source_sha256": aggregate.SOURCE_SHA256, "work_count": 10,
               "feature_count": sum(item["feature_count"] for item in results),
               "works": results, "canonical_install": "none"}
    (ROOT / BATCH).write_bytes(_json(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.destination)
    print(json.dumps({"work_count": result["work_count"], "feature_count": result["feature_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
