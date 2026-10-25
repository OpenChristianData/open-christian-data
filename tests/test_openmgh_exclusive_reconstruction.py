"""Focused source-fidelity challenges for the exclusive openMGH child route."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tei.openmgh_exclusive_oracle import _oracle
from build.tei.openmgh_exclusive_reconstruction import _convert
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_MANIFEST = ROOT / "sources/openmgh-exclusive/anulus-et-baculus-verses/source-manifest.json"
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/openmgh-exclusive-anulus-et-baculus.current.source-manifest.json"
RUNTIME_SHA = "814055d5a862e7f0cc15a2abdd7c1e6e570f98d091e8a1db83cd5e43c9d2a1f7"
TEI = "http://www.tei-c.org/ns/1.0"


def _mutated(
    original: CandidatePackage, destination: Path, altered_xml: bytes
) -> CandidatePackage:
    destination.mkdir()
    for name in original.member_names:
        (destination / name).write_bytes(original.member_bytes(name))
    (destination / "content.tei.xml").write_bytes(altered_xml)
    manifest_path = destination / "manifest.json"
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    for member in record["members"]:
        if member["name"] == "content.tei.xml":
            member["bytes"] = len(altered_xml)
            member["sha256"] = hashlib.sha256(altered_xml).hexdigest()
    manifest_path.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return CandidatePackage.load(destination)


def test_exclusive_route_rejects_missing_line_and_neighbor_work(tmp_path: Path) -> None:
    source_manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    original = reconstruct(source_manifest, tmp_path / "base", _convert)
    assert validate(source_manifest, original, _oracle).status == "pass"
    root = etree.fromstring(original.member_bytes("content.tei.xml"))
    line = root.find(f".//{{{TEI}}}lb")
    assert line is not None
    line.getparent().remove(line)
    missing_line = _mutated(
        original,
        tmp_path / "missing",
        etree.tostring(root, encoding="UTF-8", xml_declaration=True),
    )
    with pytest.raises(ValueError, match="candidate work body differs"):
        validate(source_manifest, missing_line, _oracle)
    wrong_root = etree.fromstring(original.member_bytes("content.tei.xml"))
    body = wrong_root.find(f"{{{TEI}}}text/{{{TEI}}}body")
    assert body is not None
    source_root = etree.fromstring(
        source_manifest.authority_path("extracted-xml").read_bytes()
    )
    volume = source_root.find(f"{{{TEI}}}text/{{{TEI}}}body/{{{TEI}}}div")
    assert volume is not None and len(volume) > 1
    body.remove(body[0])
    body.append(deepcopy(volume[-2]))
    wrong_work = _mutated(
        original,
        tmp_path / "neighbor",
        etree.tostring(wrong_root, encoding="UTF-8", xml_declaration=True),
    )
    with pytest.raises(ValueError, match="candidate work body differs"):
        validate(source_manifest, wrong_work, _oracle)


def test_current_oracle_fixture_preserves_complete_original_source_record():
    original_raw = ORIGINAL_MANIFEST.read_bytes()
    assert hashlib.sha256(original_raw).hexdigest() == "cedd45192b99dfb55873860557f8ba3581e6417e9a924e04ed92feb4af60465d"
    original = json.loads(original_raw)
    raw = MANIFEST.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RUNTIME_SHA
    current = json.loads(raw)
    restored = deepcopy(current)
    restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
    assert restored == original
