"""Build exact work-local LIB062 manifests from six retained source packets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tei.lib062_json_catechisms_oracle import repository_import_closure
from build.tei.lib062_six_catechisms_reconstruction import WORK_IDS
from ocd_kernel.reconstruction.contract import SourceManifest


ROOT = Path(__file__).resolve().parents[2]
CONVERTER = "build/tei/lib062_six_catechisms_reconstruction.py"
VALIDATOR = "build/tei/lib062_six_catechisms_oracle.py"
PACKAGE_SCHEMA = "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
XSD = "ocd_kernel/tei/vendor/xsd/tei_all.xsd"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _binding(path: str, *, name: str, role: str) -> dict[str, object]:
    content = (ROOT / path).read_bytes()
    return {"bytes": len(content), "name": name, "path": path, "role": role, "sha256": _sha(content)}


def prepare(work_id: str) -> tuple[Path, Path, Path]:
    if work_id not in WORK_IDS:
        raise ValueError(f"outside six exact LIB062 source packets: {work_id}")
    directory = ROOT / "sources" / work_id
    packet_path = f"sources/{work_id}/LIB-062.packet.json"
    packet_bytes = (ROOT / packet_path).read_bytes()
    packet = json.loads(packet_bytes)
    if packet.get("work_id") != work_id or packet.get("contract") != "ocd-lib062-source-packet-v1":
        raise ValueError(f"source packet identity differs: {work_id}")
    authority = packet["authority"]
    source_bytes = (ROOT / authority["path"]).read_bytes()
    if _sha(source_bytes) != authority["raw_sha256"] or len(source_bytes) != authority["raw_bytes"]:
        raise ValueError(f"retained source differs from packet: {work_id}")
    profile_path = directory / f"{work_id}.reconstruction-profile.json"
    policy_path = directory / f"{work_id}.validation-policy.json"
    manifest_path = directory / f"{work_id}.source-manifest.json"
    profile = {
        "contract": f"ocd-lib062-{work_id}-profile-v1", "work_id": work_id,
        "authority_path": authority["path"], "authority_raw_sha256": authority["raw_sha256"],
        "authority_normalized_utf8_sha256": authority["normalized_utf8_sha256"],
        "packet_path": packet_path, "packet_sha256": _sha(packet_bytes),
        "profile": packet["profile"], "structural_policy": packet["structural_policy"],
        "accountability_contract": packet["accountability_contract"],
        "adjacent_witnesses": packet["adjacent_witnesses"],
    }
    policy = {
        "contract": f"ocd-lib062-{work_id}-validation-policy-v1",
        "policy_id": f"lib062-{work_id}-standard-package-v1", "version": 1,
        "candidate_status": "nonaccepted",
        "required_package_members": ["manifest.json", "content.tei.xml", "source-accountability.json",
                                     "provenance.json", "unresolved.jsonl", "README.source.md"],
        "checks": ["literal-retained-source-byte-binding", "packet-and-adjacent-witness-binding",
                   "complete-accountability-crosswalk", "tei-p5-xsd", "candidate-package-integrity",
                   "mutation-rejection", "fresh-process-determinism", "producer-independent-oracle",
                   "workcatalog-exact-id-and-catalog-claim-lineage"],
        "forbidden_oracle_imports": ["build.tei.lib062_six_catechisms_reconstruction"],
    }
    profile_path.write_bytes(_canonical(profile))
    policy_path.write_bytes(_canonical(policy))
    census = packet["retained_member_census"]
    closure = _sha(_canonical(repository_import_closure(ROOT, ROOT / VALIDATOR)))
    manifest = {
        "contract": "ocd-source-manifest-v1", "work_id": work_id,
        "source_id": f"lib062-{work_id}-retained-json",
        "source_selection": {"authority": "retained-json", "json_pointer": "",
                             "selection": "the complete retained Creeds.json member; no adjacent witnesses are declared"},
        "authorities": [
            _binding(authority["path"], name="retained-json", role="primary-source"),
            _binding(packet_path, name="source-packet", role="source-packet"),
            _binding(f"sources/{work_id}/LIB-062.README.md", name="rights-readme", role="rights-evidence"),
            _binding(census["path"], name="retained-member-census", role="retained-member-census"),
            _binding(profile_path.relative_to(ROOT).as_posix(), name="reconstruction-profile", role="complete-source-feature-profile"),
            _binding(policy_path.relative_to(ROOT).as_posix(), name="validation-policy", role="independent-validation-policy"),
            _binding(PACKAGE_SCHEMA, name="candidate-package-schema", role="candidate-package-schema"),
            _binding(XSD, name="tei-p5-xsd", role="tei-validation-schema"),
        ],
        "converter": {"callable": "convert", "id": "ocd-lib062-six-catechisms-to-tei",
                      "implementation_path": CONVERTER, "implementation_sha256": _sha((ROOT / CONVERTER).read_bytes()),
                      "version": "1"},
        "validator": {"callable": "oracle", "id": "ocd-lib062-six-catechisms-independent-oracle",
                      "implementation_path": VALIDATOR, "implementation_sha256": _sha((ROOT / VALIDATOR).read_bytes()),
                      "import_closure_sha256": closure, "version": "1"},
        "package_schema": {"path": PACKAGE_SCHEMA, "sha256": _sha((ROOT / PACKAGE_SCHEMA).read_bytes())},
    }
    manifest_path.write_bytes(_canonical(manifest))
    SourceManifest.load(manifest_path, repository_root=ROOT)
    return profile_path, policy_path, manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, choices=sorted(WORK_IDS))
    args = parser.parse_args()
    for path in prepare(args.work):
        print(path.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
