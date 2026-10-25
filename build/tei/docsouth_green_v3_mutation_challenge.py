"""Challenge the L763 Green v3 oracle with source-bound TEI mutations."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from build.tei.docsouth_green_exact_v3_oracle import _oracle
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate

TEI = "http://www.tei-c.org/ns/1.0"
T = "{" + TEI + "}"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _mutate_title(root: etree._Element, xpath: str) -> str:
    node = root.find(xpath)
    if node is None:
        raise ValueError(f"title mutation target is missing: {xpath}")
    before = " ".join("".join(node.itertext()).split())
    node.text = (node.text or "") + " MUTATION"
    return before


def _mutate_body(root: etree._Element) -> str:
    node = root.find(f".//{T}body//{T}p")
    if node is None:
        raise ValueError("body mutation target is missing")
    before = " ".join("".join(node.itertext()).split())
    node.text = (node.text or "") + " MUTATION"
    return before


def _remove_page_marker(root: etree._Element) -> str:
    node = root.find(f".//{T}pb")
    if node is None or node.getparent() is None:
        raise ValueError("page-marker mutation target is missing")
    identity = node.get("{{http://www.w3.org/XML/1998/namespace}}id") or node.get("n") or "unlabeled"
    node.getparent().remove(node)
    return identity


def _challenge_one(
    *,
    base_members: dict[str, bytes],
    manifest: SourceManifest,
    label: str,
    mutate,
    expected_finding: str,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="ocd-green-v3-mutation-") as temporary:
        package_dir = Path(temporary)
        members = dict(base_members)
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
        tree = etree.fromstring(members["content.tei.xml"], parser=parser)
        target = mutate(tree)
        members["content.tei.xml"] = etree.tostring(
            tree, encoding="UTF-8", xml_declaration=True, pretty_print=True
        )
        record = json.loads(members["manifest.json"])
        for member in record["members"]:
            if member["name"] == "content.tei.xml":
                member["bytes"] = len(members["content.tei.xml"])
                member["sha256"] = _sha(members["content.tei.xml"])
        members["manifest.json"] = _canonical(record)
        for name, content in members.items():
            (package_dir / name).write_bytes(content)
        candidate = CandidatePackage.load(package_dir)
        attestation = _oracle(manifest, candidate)
        if attestation["status"] != "fail" or expected_finding not in attestation["findings"]:
            raise AssertionError(
                f"{label} did not fail for {expected_finding}: {attestation}"
            )
        try:
            validate(manifest, candidate, _oracle)
        except ValueError as exc:
            rejection = str(exc)
        else:
            raise AssertionError(f"{label} mutation passed contract validation")
        if rejection != "candidate validation failed":
            raise AssertionError(f"{label} failed for an unexpected reason: {rejection}")
        return {
            "candidate_sha256": candidate.sha256,
            "expected_finding": expected_finding,
            "findings": list(attestation["findings"]),
            "label": label,
            "mutated_property": target,
            "rejection": rejection,
            "status": "rejected",
            "tei_sha256": _sha(members["content.tei.xml"]),
        }


def run(*, repository_root: Path, manifest_path: Path, package_path: Path, receipt_path: Path) -> dict[str, object]:
    root = repository_root.resolve(strict=True)
    manifest = SourceManifest.load(manifest_path, repository_root=root)
    baseline = CandidatePackage.load(package_path)
    report = validate(manifest, baseline, _oracle)
    base_members = {name: baseline.member_bytes(name) for name in baseline.member_names}
    mutations = [
        _challenge_one(
            base_members=base_members,
            manifest=manifest,
            label="electronic-edition-title",
            mutate=lambda tree: _mutate_title(
                tree, f"./{T}teiHeader/{T}fileDesc/{T}titleStmt/{T}title"
            ),
            expected_finding="candidate title inventory wording, role, type, count, or order differs",
        ),
        _challenge_one(
            base_members=base_members,
            manifest=manifest,
            label="printed-source-title-page",
            mutate=lambda tree: _mutate_title(
                tree,
                f"./{T}teiHeader/{T}fileDesc/{T}sourceDesc/{T}biblFull/{T}titleStmt/{T}title",
            ),
            expected_finding="candidate title inventory wording, role, type, count, or order differs",
        ),
        _challenge_one(
            base_members=base_members,
            manifest=manifest,
            label="body-text",
            mutate=_mutate_body,
            expected_finding="body text/order differs",
        ),
        _challenge_one(
            base_members=base_members,
            manifest=manifest,
            label="page-marker-omission",
            mutate=_remove_page_marker,
            expected_finding="page marker identity, label, or order differs",
        ),
    ]
    receipt = {
        "baseline_candidate_sha256": baseline.sha256,
        "baseline_validation_report_sha256": report.sha256,
        "contract": "ocd-docsouth-green-v3-mutation-challenge-v1",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mutations": mutations,
        "oracle_id": manifest.record["validator"]["id"],
        "oracle_implementation_sha256": manifest.record["validator"]["implementation_sha256"],
        "receipt_path": str(receipt_path),
        "source_manifest_sha256": manifest.sha256,
        "status": "pass",
        "validation_status": report.status,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open("xb") as stream:
        stream.write(_canonical(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate-package", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = run(
        repository_root=args.repository_root,
        manifest_path=args.manifest,
        package_path=args.candidate_package,
        receipt_path=args.receipt,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
