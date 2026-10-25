"""Challenge the NPNF103 work-local source-node oracle with a resealed omission."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.npnf103_work_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage, validate
from tests.npnf_work_runtime_baselines import current_work_baseline


ROOT = Path(__file__).resolve().parents[1]
WORK_ID = "augustine-faith-things-not-seen"
MANIFEST = ROOT / "sources/structured-text/augustine-npnf103-works-v2" / WORK_ID / "source-manifest.json"
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/augustine-npnf103-works-v2-20260926") / WORK_ID / "package"
TEI = "http://www.tei-c.org/ns/1.0"


def test_resealed_work_paragraph_omission_is_rejected(tmp_path: Path) -> None:
    cases = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-npnf103104.json").read_bytes())
    case = next(row for row in cases if row["work_id"] == WORK_ID)
    manifest, original = current_work_baseline(ROOT, case, tmp_path / "current")
    from build.tools.reconstruct_candidate import _bound_callable
    bound_oracle = _bound_callable(manifest.repository_root, manifest.record["validator"], role="validator")
    assert validate(manifest, original, bound_oracle).status == "pass"
    target = tmp_path / "package"
    shutil.copytree(original.path, target)
    content = target / "content.tei.xml"
    tree = etree.parse(str(content), etree.XMLParser(resolve_entities=False, no_network=True))
    paragraph = tree.find(f".//{{{TEI}}}body//{{{TEI}}}p")
    assert paragraph is not None
    paragraph.getparent().remove(paragraph)
    content.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True))
    package_manifest = target / "manifest.json"
    record = json.loads(package_manifest.read_bytes())
    member = next(item for item in record["members"] if item["name"] == "content.tei.xml")
    member.update(bytes=content.stat().st_size, sha256=sha256(content.read_bytes()).hexdigest())
    package_manifest.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")) + "\n", encoding="utf-8")
    mutated = CandidatePackage.load(target)
    with pytest.raises(ValueError, match="omission|invention|source-kind|direct text"):
        _oracle(manifest, mutated)
