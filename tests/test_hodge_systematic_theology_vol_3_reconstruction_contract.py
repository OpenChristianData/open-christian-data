from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.hodge_systematic_theology_vol_3_oracle import _oracle
from build.tei.hodge_systematic_theology_vol_3_reconstruction import _convert
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sources/structured-text/hodge-systematic-theology-vol-3/hodge-systematic-theology-vol-3.source-manifest.json"


def test_volume_three_exact_source_manifest_and_nonaccepted_candidate(tmp_path: Path) -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    raw = source.authority_path("retained-hodge-vol-3").read_bytes()
    assert len(raw) == 3_102_428
    assert hashlib.sha256(raw).hexdigest() == "aeb92566e8ce5019f6f43c56585538c67bafcea177d9d6f1df286006f24dda54"
    candidate = reconstruct(source, tmp_path / "candidate", _convert)
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["root_ids_in_order"] == ["i", "ii", "iii", "iv", "v"]
    mutated_path = tmp_path / "mutated"
    shutil.copytree(candidate.path, mutated_path)
    mutated_tree = etree.parse(str(mutated_path / "content.tei.xml"))
    mutated_body = mutated_tree.find(".//{http://www.tei-c.org/ns/1.0}body")
    mutated_body.remove(mutated_body[-1])
    mutated_tree.write(str(mutated_path / "content.tei.xml"), encoding="utf-8", xml_declaration=True)
    package_manifest = json.loads((mutated_path / "manifest.json").read_bytes())
    member = next(row for row in package_manifest["members"] if row["name"] == "content.tei.xml")
    mutated_bytes = (mutated_path / "content.tei.xml").read_bytes()
    member.update(bytes=len(mutated_bytes), sha256=hashlib.sha256(mutated_bytes).hexdigest())
    (mutated_path / "manifest.json").write_text(json.dumps(package_manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="omitted or invented"):
        _oracle(source, CandidatePackage.load(mutated_path))
    report = validate(source, candidate, _oracle)
    assert candidate.manifest["status"] == "nonaccepted"
    assert report.status == "pass"
