"""Retained-source fidelity challenges for the 1860 Peter Jones selection."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.peter_jones_1860_oracle_v2 import _oracle
from build.tei.peter_jones_1860_reconstruction_v2 import _convert
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate
from ocd_kernel.tei.validate import compiled_schema


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/peter_jones_1860_oracle_v2.source-manifest.json'
TEI = "http://www.tei-c.org/ns/1.0"


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _mutated(source: CandidatePackage, destination: Path, change) -> CandidatePackage:
    shutil.copytree(source.path, destination)
    content = destination / "content.tei.xml"
    tree = etree.fromstring(content.read_bytes())
    change(tree)
    assert compiled_schema().validate(tree), "mutation must remain valid TEI P5"
    content.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True))
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for member in manifest["members"]:
        raw = (destination / member["name"]).read_bytes()
        member["bytes"] = len(raw)
        member["sha256"] = sha256(raw).hexdigest()
    manifest_path.write_bytes(_json(manifest))
    return CandidatePackage.load(destination)


def _child_body(tree: etree._Element) -> etree._Element:
    return tree.find(f"{{{TEI}}}text/{{{TEI}}}body")


def test_source_oracle_rejects_p5_valid_scope_and_content_mutations(tmp_path: Path) -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    baseline = reconstruct(manifest, tmp_path / "baseline", _convert)
    assert validate(manifest, baseline, _oracle).status == "pass"

    def omit_child(tree: etree._Element) -> None:
        body = _child_body(tree)
        body.remove(body[1])

    def swap_children(tree: etree._Element) -> None:
        body = _child_body(tree)
        first, second = body[0], body[1]
        body.remove(second)
        body.insert(0, second)

    def omit_leaf_milestone(tree: etree._Element) -> None:
        page = next(node for node in tree.iter(f"{{{TEI}}}pb") if node.get("n") == "100")
        page.getparent().remove(page)

    def omit_blank_status(tree: etree._Element) -> None:
        gap = next(tree.iter(f"{{{TEI}}}gap"))
        gap.getparent().remove(gap)

    def change_edition(tree: etree._Element) -> None:
        desc = tree.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}sourceDesc/{{{TEI}}}p")
        desc.text = desc.text.replace("Anson Green, 1860", "Anson Green, 1861")

    def retarget_link(tree: etree._Element) -> None:
        reference = next(tree.iter(f"{{{TEI}}}ref"))
        reference.set("target", "#peter-jones-1860-component-2")

    def omit_source_word(tree: etree._Element) -> None:
        paragraph = next(node for node in tree.iter(f"{{{TEI}}}p") if node.text and "Burlington Bay" in node.text)
        paragraph.text = paragraph.text.replace("Burlington Bay", "Burlington")

    for label, change, reason in (
        ("omit-child", omit_child, "front/child partition"),
        ("swap-children", swap_children, "child identity/order"),
        ("omit-page", omit_leaf_milestone, "Page coverage/order"),
        ("omit-blank-status", omit_blank_status, "blank Page status"),
        ("change-edition", change_edition, "edition metadata"),
        ("omit-word", omit_source_word, "Page text mismatch"),
        ("retarget-link", retarget_link, "link target/order"),
    ):
        altered = _mutated(baseline, tmp_path / label, change)
        with pytest.raises(ValueError, match=reason):
            _oracle(manifest, altered)


def test_fresh_process_reproduces_package_bytes(tmp_path: Path) -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    baseline = reconstruct(manifest, tmp_path / "baseline", _convert)
    destination = tmp_path / "fresh-process"
    command = [
        sys.executable, "-B", "-c",
        "from pathlib import Path; from build.tei.peter_jones_1860_reconstruction_v2 import _convert; "
        "from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct; "
        f"root=Path({str(ROOT)!r}); "
        f"manifest=SourceManifest.load(Path({str(MANIFEST)!r}),repository_root=root); "
        f"reconstruct(manifest,Path({str(destination)!r}),_convert)",
    ]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    for name in baseline.member_names:
        assert (baseline.path / name).read_bytes() == (destination / name).read_bytes(), name
    assert validate(manifest, CandidatePackage.load(destination), _oracle).status == "pass"
