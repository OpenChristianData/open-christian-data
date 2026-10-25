"""Check Satyrus' exact Book II headings and one-head display repair."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.npnf_ambrose_satyrus_title_v3_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ROOT = Path("\\\\?\\" + str(Path(__file__).resolve().parents[1]))
RETAINED_MANIFEST = Path("sources/structured-text/ambrose-of-milan-on-satyrus/npnf210-satyrus-title-v3.source-manifest.json")
MANIFEST = Path("tests/fixtures/reconstruction-runtime/npnf_ambrose_satyrus_title_v3_oracle.source-manifest.json")
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/npnf210-work-ambrose-of-milan-on-satyrus-title-v3-20260926")
OLD = Path("D:/Library/Open Christian Data/candidate-reviews/npnf210-work-ambrose-of-milan-on-satyrus-heading-repair-v2-20260926")
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _files(path: Path) -> dict[str, str]:
    return {member.name: _sha(member.read_bytes()) for member in sorted(path.iterdir()) if member.is_file()}


@pytest.fixture(scope="module")
def runtime_candidate(tmp_path_factory):
    from tests.runtime_candidate_baselines import current_runtime_baseline

    destination = tmp_path_factory.mktemp("ambrose-runtime") / "candidate"
    return current_runtime_baseline(
        root=ROOT, original_manifest=RETAINED_MANIFEST, runtime_manifest=MANIFEST,
        retained_package=PACKAGE / "package", retained_sha256="2011d829fdd44d74495ca1fa7cccf7a8c78b03b16b5fbd4ce6696f2793e79d2c",
        destination=destination,
    )


def test_exact_two_source_headings_and_only_display_change(runtime_candidate) -> None:
    manifest, candidate = runtime_candidate
    manifest.verify()
    assert _oracle(manifest, candidate)["status"] == "pass"
    old = etree.fromstring((OLD / "package/content.tei.xml").read_bytes())
    new = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    selector = "//tei:div[@xml:id='npnf-ambrose-iv.iii.iii']"
    old_chapter, new_chapter = old.xpath(selector, namespaces=NS)[0], new.xpath(selector, namespaces=NS)[0]
    assert old_chapter[0].tag == "{http://www.tei-c.org/ns/1.0}head"
    assert old_chapter[0].text == "Book II. On the Belief in the Resurrection."
    assert not new_chapter.xpath("./tei:head", namespaces=NS)
    explicit = new_chapter.xpath("./tei:ab[@type='source-heading']", namespaces=NS)
    assert [node.get(XML_ID) for node in explicit[:2]] == [
        "npnf-ambrose-iv.iii.iii-p0.1", "npnf-ambrose-iv.iii.iii-p0.2"
    ]
    assert " ".join(" ".join("".join(node.itertext()) for node in explicit[:2]).split()) == old_chapter[0].text
    source_title = old_chapter[0].text
    old_chapter.remove(old_chapter[0])
    assert etree.tostring(old.find("tei:text", NS), method="c14n") == etree.tostring(new.find("tei:text", NS), method="c14n")
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    chapter_row = next(row for row in accounting["crosswalk"] if row["source_xml_id"] == "iv.iii.iii")
    assert chapter_row["source_title_head"] is None
    assert any(item["source_attribute"] == "title" and item["source_value"] == source_title and item["method"] == "redundant-explicit-content" for item in chapter_row["attribute_dispositions"])


def test_clean_process_reproduces_exact_package(tmp_path: Path, runtime_candidate) -> None:
    destination = tmp_path / "candidate"
    process = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--repository-root", str(ROOT), "--manifest", MANIFEST.as_posix(), "--destination", str(destination)],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert json.loads(process.stdout)["status"] == "pass"
    assert _files(destination / "package") == _files(runtime_candidate[1].path)
    assert _sha((destination / "validation.json").read_bytes()) == _sha((runtime_candidate[1].path.parent / "validation.json").read_bytes())


def test_resealed_book_ii_heading_mutation_rejected(tmp_path: Path, runtime_candidate) -> None:
    target = tmp_path / "mutated"
    target.mkdir()
    for member in runtime_candidate[1].path.iterdir():
        (target / member.name).write_bytes(member.read_bytes())
    xml = target / "content.tei.xml"
    tree = etree.parse(str(xml))
    chapter = tree.xpath("//tei:div[@xml:id='npnf-ambrose-iv.iii.iii']/tei:ab[@type='source-heading'][1]", namespaces=NS)[0]
    chapter.text = (chapter.text or "") + " invented"
    xml.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False) + b"\n")
    package_manifest = target / "manifest.json"
    record = json.loads(package_manifest.read_bytes())
    member = next(item for item in record["members"] if item["name"] == "content.tei.xml")
    member["bytes"] = len(xml.read_bytes())
    member["sha256"] = _sha(xml.read_bytes())
    package_manifest.write_bytes((json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    manifest = runtime_candidate[0]
    with pytest.raises(ValueError, match="direct text|source-kind|crosswalk"):
        _oracle(manifest, CandidatePackage.load(target))
