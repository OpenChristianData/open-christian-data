"""Resealed mutations proving the independent Leeser source oracle rejects loss."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from lxml import etree

from build.tei.leeser_tanakh_1853_oracle import oracle
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate


TEI = "http://www.tei-c.org/ns/1.0"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _reseal_mutation(source: Path, destination: Path, mutation: str) -> None:
    shutil.copytree(source, destination)
    package_manifest = json.loads((destination / "manifest.json").read_bytes())
    tei_path = destination / "content.tei.xml"
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    tree = etree.parse(str(tei_path), parser)
    ns = {"tei": TEI}
    if mutation == "drop-first-source-line":
        matches = tree.xpath("/tei:TEI/tei:text/tei:body/tei:div/tei:div[@type='book'][1]/tei:ab[@type='usfm-source-line'][1]", namespaces=ns)
        if len(matches) != 1:
            raise ValueError("mutation setup could not select one source-line carrier")
        matches[0].getparent().remove(matches[0])
    elif mutation == "relabel-first-book":
        matches = tree.xpath("/tei:TEI/tei:text/tei:body/tei:div/tei:div[@type='book'][1]", namespaces=ns)
        if len(matches) != 1:
            raise ValueError("mutation setup could not select one book boundary")
        matches[0].set("n", "EXO")
    else:
        raise ValueError(f"unknown mutation {mutation}")
    content = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    tei_path.write_bytes(content)
    for member in package_manifest["members"]:
        if member["name"] == "content.tei.xml":
            member["bytes"] = len(content)
            member["sha256"] = _sha(content)
            break
    else:
        raise ValueError("candidate manifest does not declare content.tei.xml")
    (destination / "manifest.json").write_bytes(_canonical(package_manifest))


def run(*, manifest_path: str, candidate_path: str, repository_root: str) -> dict[str, object]:
    root = Path(repository_root).resolve(strict=True)
    manifest = SourceManifest.load(manifest_path, repository_root=root)
    source_candidate = CandidatePackage.load(candidate_path)
    results = []
    with tempfile.TemporaryDirectory(prefix="l229-oracle-challenge-") as temporary:
        temp_root = Path(temporary)
        for mutation, expected in (
            ("drop-first-source-line", "omitted or duplicated source lines"),
            ("relabel-first-book", "book TEI identity mismatch"),
        ):
            mutated = temp_root / mutation
            _reseal_mutation(source_candidate.path, mutated, mutation)
            invalid = CandidatePackage.load(mutated)
            try:
                validate(manifest, invalid, oracle)
            except ValueError as error:
                message = str(error)
                if expected not in message:
                    raise ValueError(f"{mutation} failed for an unexpected reason: {message}") from error
                results.append({"mutation": mutation, "rejected": True, "reason": message})
            else:
                raise ValueError(f"oracle accepted resealed mutation: {mutation}")
    return {"contract": "ocd-englee-mutation-challenge-v1", "candidate_sha256": source_candidate.sha256, "results": results}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--repository-root", default=".")
    arguments = parser.parse_args()
    print(json.dumps(run(manifest_path=arguments.manifest, candidate_path=arguments.candidate, repository_root=arguments.repository_root), sort_keys=True))

