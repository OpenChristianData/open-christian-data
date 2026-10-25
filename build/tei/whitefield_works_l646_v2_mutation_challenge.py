"""Challenge the independent L646 v2 oracle with bounded TEI mutations."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Callable

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

XML = "http://www.w3.org/XML/1998/namespace"
TEI = "http://www.tei-c.org/ns/1.0"
ORACLE_PATH = Path("build/tei/whitefield_works_l646_v2_oracle.py")


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class _MutatedCandidate:
    def __init__(self, source: CandidatePackage, members: dict[str, bytes]) -> None:
        self._source = source
        self._members = members
        self.sha256 = _sha(
            _canonical(
                {
                    "base_candidate_sha256": source.sha256,
                    "mutated_members": {
                        name: _sha(content) for name, content in sorted(members.items())
                    },
                }
            )
        )

    def member_bytes(self, name: str) -> bytes:
        return self._members.get(name, self._source.member_bytes(name))


def _load_oracle(root: Path):
    path = root / ORACLE_PATH
    digest = _sha(path.read_bytes())
    spec = importlib.util.spec_from_file_location(
        f"_whitefield_l646_mutation_oracle_{digest}", path
    )
    if spec is None or spec.loader is None:
        raise ValueError("bound L646 oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _serialize_mutation(
    candidate: CandidatePackage, mutate: Callable[[etree._Element], None]
) -> tuple[dict[str, bytes], str]:
    original = candidate.member_bytes("content.tei.xml")
    root = etree.fromstring(original)
    mutate(root)
    mutated_tei = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    account["candidate_tei_sha256"] = _sha(mutated_tei)
    members = {
        "content.tei.xml": mutated_tei,
        "source-accountability.json": _canonical(account),
    }
    return members, _sha(mutated_tei)


def _mutate_body_text(root: etree._Element) -> None:
    volume = root.xpath(
        "./tei:text/tei:body/tei:div[@type='source-volume'][@n='I']",
        namespaces={"tei": TEI},
    )[0]
    node = next(
        element
        for element in volume.iter()
        if element.text and element.text.strip()
    )
    text = node.text
    index = next(position for position, char in enumerate(text) if not char.isspace())
    replacement = "X" if text[index] != "X" else "Y"
    node.text = text[:index] + replacement + text[index + 1 :]


def _mutate_image_bytes(root: etree._Element) -> None:
    import base64

    binary = root.xpath(
        "./tei:text/tei:body/tei:div[@type='source-volume'][@n='I']//tei:binaryObject",
        namespaces={"tei": TEI},
    )[0]
    raw = bytearray(base64.b64decode(binary.text or "", validate=True))
    raw[0] ^= 1
    binary.text = base64.b64encode(raw).decode("ascii")


def _mutate_source_id(root: etree._Element) -> None:
    anchor = root.xpath(
        ".//*[@xml:id='v1-project-gutenberg-license']",
        namespaces={"xml": XML},
    )[0]
    anchor.set(f"{{{XML}}}id", "v1-project-gutenberg-license-mutated")


def _mutate_image_uri(root: etree._Element) -> None:
    reference = root.xpath(
        ".//tei:ref[@xml:id='v1-id-2187863942301718133']",
        namespaces={"tei": TEI, "xml": XML},
    )[0]
    reference.set("target", "images/frontispiece.jpg")


def _mutate_volume_order(root: etree._Element) -> None:
    volumes = root.xpath(
        "./tei:text/tei:body/tei:div[@type='source-volume']",
        namespaces={"tei": TEI},
    )
    parent = volumes[0].getparent()
    parent.insert(parent.index(volumes[0]), volumes[1])


def run(
    *, manifest_path: str, candidate_path: str, repository_root: str
) -> dict[str, object]:
    root = Path(repository_root).resolve(strict=True)
    manifest = SourceManifest.load(root / manifest_path, repository_root=root)
    candidate = CandidatePackage.load(candidate_path)
    oracle = _load_oracle(root)
    cases: tuple[tuple[str, Callable[[etree._Element], None], str], ...] = (
        ("visible-body-text", _mutate_body_text, "source body text mismatch"),
        (
            "embedded-image-bytes",
            _mutate_image_bytes,
            "source image bytes/hash mismatch",
        ),
        ("source-id-carrier", _mutate_source_id, "source id mapping mismatch"),
        ("image-link-target", _mutate_image_uri, "unresolved source image link"),
        ("source-volume-order", _mutate_volume_order, "ordered volume boundary failed"),
    )
    outcomes: list[dict[str, str]] = []
    for name, mutation, expected_error in cases:
        members, mutated_sha = _serialize_mutation(candidate, mutation)
        mutant = _MutatedCandidate(candidate, members)
        try:
            oracle._oracle(manifest, mutant)
        except ValueError as error:
            if expected_error not in str(error):
                raise ValueError(
                    f"{name} mutation failed for an unexpected reason: {error}"
                ) from error
            outcomes.append(
                {
                    "mutation": name,
                    "outcome": "rejected",
                    "expected_oracle_check": expected_error,
                    "observed_rejection": str(error),
                    "mutated_tei_sha256": mutated_sha,
                }
            )
        else:
            raise ValueError(f"oracle accepted the {name} mutation")
    return {
        "contract": "ocd-whitefield-l646-mutation-challenge-v2",
        "status": "pass",
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "oracle_id": oracle.ORACLE_ID,
        "oracle_version": oracle.ORACLE_VERSION,
        "mutation_count": len(outcomes),
        "outcomes": outcomes,
        "candidate_and_source_files_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--output")
    arguments = parser.parse_args()
    result = _canonical(run(
        manifest_path=arguments.manifest,
        candidate_path=arguments.candidate,
        repository_root=arguments.repository_root,
    ))
    if arguments.output:
        Path(arguments.output).write_bytes(result)
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    main()
