"""Exercise each Phase A ThML route through the public reconstruction contract."""

import os
import hashlib
import json
from pathlib import Path
import shutil

import pytest
from lxml import etree

from build.tei.selected_thml import _convert
from build.tei.selected_thml_oracle import _oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
if os.name == "nt":
    # Keep deeply nested retained evidence addressable under Windows MAX_PATH.
    ROOT = Path("\\\\?\\" + str(ROOT))
ROUTES = (
    (
        "augustine-spirit-and-letter",
        "tests/fixtures/reconstruction-runtime/augustine-spirit-and-letter.source-manifest.json",
    ),
    (
        "john-owen-conscience",
        "tests/fixtures/reconstruction-runtime/john-owen-conscience.source-manifest.json",
    ),
)


@pytest.mark.parametrize(("work_id", "manifest_path"), ROUTES)
def test_selected_thml_route_reconstructs_and_validates(
    tmp_path: Path, work_id: str, manifest_path: str
) -> None:
    source_manifest = SourceManifest.load(
        ROOT / manifest_path, repository_root=ROOT
    )

    candidate = reconstruct(
        source_manifest,
        tmp_path / work_id,
        _convert,
    )
    report = validate(source_manifest, candidate, _oracle)

    assert candidate.manifest["status"] == "nonaccepted"
    assert report.status == "pass"
    assert report.source_manifest_sha256 == source_manifest.sha256
    assert report.candidate_sha256 == candidate.sha256


@pytest.mark.parametrize(("work_id", "manifest_path"), ROUTES)
def test_selected_thml_oracle_rejects_resealed_wording(
    tmp_path: Path, work_id: str, manifest_path: str
) -> None:
    source = SourceManifest.load(ROOT / manifest_path, repository_root=ROOT)
    baseline = reconstruct(source, tmp_path / work_id, _convert)
    mutated_path = tmp_path / "mutated"
    shutil.copytree(baseline.path, mutated_path)
    content_path = mutated_path / "content.tei.xml"
    content = content_path.read_bytes()
    document = etree.fromstring(content)
    body = document.find("{http://www.tei-c.org/ns/1.0}text")
    node = next(node for node in body.iter() if node.text and node.text.strip())
    node.text = "Invented wording. " + node.text
    changed = etree.tostring(document, encoding="UTF-8", xml_declaration=True)
    content_path.write_bytes(changed)
    package_manifest_path = mutated_path / "manifest.json"
    record = json.loads(package_manifest_path.read_bytes())
    member = next(row for row in record["members"] if row["name"] == "content.tei.xml")
    member.update(bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest())
    package_manifest_path.write_bytes(
        (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )
    with pytest.raises(PipelineError, match="selected ThML source division title differs"):
        validate(source, CandidatePackage.load(mutated_path), _oracle)
