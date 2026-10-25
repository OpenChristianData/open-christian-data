"""Reseal and challenge source-bound L641 candidate invariants."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from woolman_37311_oracle import _oracle


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reseal(package_dir: Path, member_name: str, replacement: bytes) -> None:
    (package_dir / member_name).write_bytes(replacement)
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for member in manifest["members"]:
        if member["name"] == member_name:
            member["bytes"] = len(replacement)
            member["sha256"] = _sha(replacement)
            break
    else:
        raise ValueError(f"manifest does not declare {member_name}")
    manifest_path.write_bytes(_canonical(manifest))


def _reject(source: SourceManifest, package_dir: Path, case_id: str, member: str, mutate: Any) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"woolman-37311-{case_id}-") as temp:
        changed = Path(temp) / "package"
        shutil.copytree(package_dir, changed)
        old = (changed / member).read_bytes()
        new = mutate(old)
        _reseal(changed, member, new)
        candidate = CandidatePackage.load(changed)
        try:
            validate(source, candidate, _oracle)
        except ValueError as exc:
            return {"case_id": case_id, "mutated_member": member, "rejected": True, "reason": str(exc)}
        raise AssertionError(f"mutation unexpectedly passed: {case_id}")


def _rename_first_component(content: bytes) -> bytes:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(content, parser)
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    divisions = root.xpath("./tei:text/tei:body/tei:div", namespaces=ns)
    if not divisions or divisions[0].get("type") != "source-unit":
        raise ValueError("baseline lacks the expected direct source-unit divisions")
    divisions[0].set("n", divisions[0].get("n", "") + "-mutated")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)


def _change_identity(content: bytes) -> bytes:
    provenance = json.loads(content)
    provenance["work_id"] = "unbound-woolman-work"
    return _canonical(provenance)


def challenge(candidate_root: Path) -> dict[str, object]:
    source_path = ROOT / "sources/manifest-acquisitions/gutenberg-pg37311-woolman-v5/source-manifest.json"
    source = SourceManifest.load(source_path, repository_root=ROOT)
    package_dir = candidate_root / "package"
    package = CandidatePackage.load(package_dir)
    baseline = validate(source, package, _oracle)
    results = [
        _reject(source, package_dir, "source-unit-order-label", "content.tei.xml", _rename_first_component),
        _reject(source, package_dir, "work-identity-binding", "provenance.json", _change_identity),
    ]
    return {
        "contract": "ocd-l641-woolman-mutation-challenge-v1",
        "source_manifest_sha256": source.sha256,
        "candidate_sha256": package.sha256,
        "baseline_status": baseline.status,
        "baseline_findings": list(baseline.findings),
        "mutations": results,
        "status": "pass" if all(item["rejected"] for item in results) else "fail",
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: py -3 build/tei/woolman_37311_challenge.py <candidate-root>")
    print(json.dumps(challenge(Path(sys.argv[1]).resolve(strict=True)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
