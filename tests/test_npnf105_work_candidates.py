"""Challenge NPNF105 source fidelity with valid, resealed candidate losses."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.npnf105_work_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage, validate
from tests.npnf_work_runtime_baselines import current_work_baseline


ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "sources/structured-text/augustine-npnf105-works"
CANDIDATES = Path("D:/Library/Open Christian Data/candidate-reviews/augustine-npnf105-works-20260927")
TEI = "{http://www.tei-c.org/ns/1.0}"


def _reseal(package: Path, content: bytes) -> CandidatePackage:
    target = package / "content.tei.xml"
    target.write_bytes(content)
    manifest = package / "manifest.json"
    record = json.loads(manifest.read_bytes())
    member = next(item for item in record["members"] if item["name"] == "content.tei.xml")
    member.update(bytes=len(content), sha256=sha256(content).hexdigest())
    manifest.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")) + "\n", encoding="utf-8")
    return CandidatePackage.load(package)


@pytest.mark.parametrize("work_id,removed_kind", [
    ("augustine-grace-and-free-will", "paragraph"),
    ("augustine-proceedings-of-pelagius", "source comment"),
])
def test_resealed_source_feature_omission_is_rejected(tmp_path: Path, work_id: str,
                                                     removed_kind: str) -> None:
    cases = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-npnf-work-late.json").read_bytes())
    case = next(row for row in cases if row["work_id"] == work_id)
    manifest, original = current_work_baseline(ROOT, case, tmp_path / "current")
    from build.tools.reconstruct_candidate import _bound_callable
    bound_oracle = _bound_callable(manifest.repository_root, manifest.record["validator"], role="validator")
    assert validate(manifest, original, bound_oracle).status == "pass"
    package = tmp_path / "package"
    shutil.copytree(original.path, package)
    tree = etree.fromstring((package / "content.tei.xml").read_bytes(),
                            etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False))
    if removed_kind == "paragraph":
        target = tree.find(f".//{TEI}body//{TEI}p")
    else:
        target = tree.xpath("//comment()")[0]
    assert target is not None
    target.getparent().remove(target)
    mutated = _reseal(package, etree.tostring(tree, encoding="UTF-8", xml_declaration=True))
    with pytest.raises(ValueError, match="child count|text differs|comment differs"):
        _oracle(manifest, mutated)
