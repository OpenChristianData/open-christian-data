"""Guard the source-attested boundary of the A22076 first examination."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys

import pytest
from pathlib import Path
from xml.etree import ElementTree as ET

from build.tei.anne_a22076_first_v1 import _convert
from build.tei.anne_a22076_first_oracle_v1 import _oracle
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/anne_a22076_first_oracle_v1.source-manifest.json'
TEI = "{http://www.tei-c.org/ns/1.0}"


def test_first_work_is_complete_and_trailing_preface_is_accounted_outside_work() -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    source = ET.fromstring(manifest.authority_path("retained-tei-p5").read_bytes())
    first, second = list(source.find(f"{TEI}text/{TEI}group"))

    package = _convert(manifest)
    result = ET.fromstring(package["content.tei.xml"])
    text = result.find(TEI + "text")
    assert text is not None
    assert len(result) == 2
    assert ET.tostring(text) == ET.tostring(first)
    assert len(list(text.iter(TEI + "pb"))) == 118
    assert text.find(f"{TEI}body/{TEI}trailer") is not None
    assert text.find(f"{TEI}back/{TEI}div[@type='appendix']") is not None
    assert all(page.get("facs") != "tcp:384:60" for page in text.iter(TEI + "pb"))
    assert any(page.get("facs") == "tcp:384:60" for page in second.iter(TEI + "pb"))

    accounting = json.loads(package["source-accountability.json"])
    assert accounting["included"]["selector"] == "/TEI/text/group/text[1]"
    assert accounting["excluded"]["selector"] == "/TEI/text/group/text[2]"
    assert accounting["excluded"]["physical_placement"] == "unverified"


def _assert_current_candidate_validates_and_rejects_resealed_first_work_wording(tmp_path) -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(manifest, tmp_path / "original", _convert)
    assert validate(manifest, candidate, _oracle).status == "pass"
    changed = tmp_path / "changed"
    shutil.copytree(candidate.path, changed)
    path = changed / "content.tei.xml"
    tree = ET.fromstring(path.read_bytes())
    paragraph = next(node for node in tree.find(TEI + "text").iter() if node.text and node.text.strip())
    paragraph.text += " INVENTED WORDING"
    content = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
    path.write_bytes(content)
    package = json.loads((changed / "manifest.json").read_bytes())
    member = next(item for item in package["members"] if item["name"] == path.name)
    member.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    (changed / "manifest.json").write_bytes((json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    altered = CandidatePackage.load(changed)
    attestation = _oracle(manifest, altered)
    assert attestation["status"] == "fail"
    assert any("candidate first text differs" in finding for finding in attestation["findings"])
    with pytest.raises(ValueError, match="candidate validation failed"):
        validate(manifest, altered, _oracle)


def test_current_candidate_validates_and_rejects_resealed_first_work_wording(tmp_path) -> None:
    # The frozen ElementTree profile uses the CLI's fresh serializer context.
    script = (
        "from pathlib import Path; import runpy, sys; "
        "scope = runpy.run_path(sys.argv[1]); "
        "scope['_assert_current_candidate_validates_and_rejects_resealed_first_work_wording'](Path(sys.argv[2]))"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(Path(__file__).resolve()), str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
