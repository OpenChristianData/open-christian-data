from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import re

from lxml import etree
import pytest

from build.lib.pytest_candidate_clone import (
    candidate_package_fingerprint,
    clone_candidate_package,
)
from build.tei.bcp_1662_oracle import _oracle
from build.tei.bcp_1662_reconstruction import _convert
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/bcp-1662.source-manifest.json"
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


@pytest.fixture(scope="session")
def bcp_source_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="session")
def bcp_candidate(tmp_path_factory: pytest.TempPathFactory, bcp_source_manifest: SourceManifest) -> CandidatePackage:
    destination = tmp_path_factory.mktemp("bcp-1662-candidate") / "package"
    return reconstruct(bcp_source_manifest, destination, _convert)


def _reseal(path: Path, member_name: str, content: bytes) -> CandidatePackage:
    (path / member_name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    for member in manifest["members"]:
        if member["name"] == member_name:
            member["bytes"] = len(content)
            member["sha256"] = hashlib.sha256(content).hexdigest()
            break
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _remove_exact_mutation_copy(destination: Path, expected_parent: Path) -> None:
    if not os.path.lexists(destination):
        return
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if destination.is_symlink() or is_junction(destination):
        raise AssertionError(f"refusing to remove reparse mutation copy: {destination}")
    parent = expected_parent.resolve(strict=True)
    resolved = destination.resolve(strict=True)
    if resolved == parent or resolved.parent != parent:
        raise AssertionError(f"mutation copy is not an exact child: {resolved}")
    shutil.rmtree(resolved)
    if os.path.lexists(destination):
        raise AssertionError(f"mutation copy cleanup failed: {destination}")


@contextmanager
def _mutated_copy(
    tmp_path: Path, candidate: CandidatePackage, mutable_member: str
) -> Iterator[Path]:
    destination = tmp_path / "candidate-mutation-copy"
    mutable_members = {"manifest.json", mutable_member}
    package_members = set(candidate.member_names)
    if mutable_member not in package_members:
        raise AssertionError(f"unknown mutable candidate member: {mutable_member}")
    try:
        clone_candidate_package(
            candidate.path,
            destination,
            hardlink_members=tuple(sorted(package_members - mutable_members)),
        )
        for member in mutable_members:
            assert not (candidate.path / member).samefile(destination / member)
        yield destination
    finally:
        _remove_exact_mutation_copy(destination, tmp_path)


@pytest.fixture()
def bcp_candidate_integrity(
    bcp_candidate: CandidatePackage,
) -> Iterator[None]:
    before = candidate_package_fingerprint(bcp_candidate.path)
    yield
    assert candidate_package_fingerprint(bcp_candidate.path) == before


def test_manifest_binds_exact_retained_scope(bcp_source_manifest: SourceManifest) -> None:
    record = bcp_source_manifest.record
    assert record["source_bundle"] == {
        "members": 25,
        "bytes": 733674,
        "sha256": "5369fab47e2b5f221f7bcfef844a866b44d650925fd833e5693a0da14c0346f6",
    }
    assert len(record["source_members"]) == 25
    assert sum(member["bytes"] for member in record["source_members"]) == 733674
    assert len(record["failed_acquisitions"]) == 5
    assert {item["http_status"] for item in record["failed_acquisitions"]} == {404}
    assert record["expression_scope"]["status"] == "partial"


def test_complete_candidate_and_independent_oracle(
    bcp_source_manifest: SourceManifest, bcp_candidate: CandidatePackage
) -> None:
    assert set(bcp_candidate.member_names) == {
        "manifest.json", "content.tei.xml", "source-accountability.json",
        "provenance.json", "unresolved.jsonl", "README.source.md",
    }
    accountability = json.loads(bcp_candidate.member_bytes("source-accountability.json"))
    assert accountability["observation_counts"] == {
        "total": 17106, "elements": 7152, "attributes": 5086, "text": 4868,
    }
    assert accountability["image_alt_counts"] == {"text_bearing": 603, "navigation": 184}
    derived_markers = sum(item["semantic_role"] == "alternative-marker" for item in accountability["crosswalk"])
    broad = re.compile(r"\b(?:either|or this|or else|or the following|another)\b", re.IGNORECASE)
    derived_recall = sum(item["kind"] == "text" and item["name"] is None and broad.search(item["value"]) is not None for item in accountability["crosswalk"])
    assert accountability["alternative_counts"] == {"genuine": derived_markers, "legacy_recall": derived_recall}
    assert accountability["comment_count"] == 4
    assert len(accountability["crosswalk"]) == 17106
    report = validate(bcp_source_manifest, bcp_candidate, _oracle)
    assert report.status == "pass"
    assert report.attestation["findings"] == ()


def test_image_alternatives_are_source_filename_anchored_and_comments_are_evidence_only(
    bcp_candidate: CandidatePackage,
) -> None:
    accountability = json.loads(bcp_candidate.member_bytes("source-accountability.json"))
    by_member_start: dict[tuple[str, int], list[dict[str, object]]] = {}
    for item in accountability["crosswalk"]:
        by_member_start.setdefault((item["member"], item["byte_start"]), []).append(item)
    text_images = 0
    navigation = 0
    for siblings in by_member_start.values():
        image = next((item for item in siblings if item["kind"] == "element" and item["name"] == "img"), None)
        if image is None:
            continue
        attrs = {item["name"]: item["value"] for item in siblings if item["kind"] == "attribute"}
        assert "src" in attrs and "alt" in attrs
        if "/buttons/" in attrs["src"].lower():
            navigation += 1
            assert image["disposition"] == "evidence-only"
        else:
            text_images += 1
            assert image["semantic_role"] == "image-alternative"
            assert image["disposition"] == "represented"
    assert (text_images, navigation) == (603, 184)
    comments = [item for item in accountability["crosswalk"] if item["reason_code"] == "html-comment-edition-evidence"]
    assert len(comments) == 4 and all(item["tei_selector"] is None for item in comments)
    tei_text = "".join(etree.fromstring(bcp_candidate.member_bytes("content.tei.xml")).itertext())
    assert all(item["value"] not in tei_text for item in comments)


def test_readable_semantic_structure_and_joined_drop_caps(bcp_candidate: CandidatePackage) -> None:
    root = etree.fromstring(bcp_candidate.member_bytes("content.tei.xml"))
    assert len(root.xpath("//tei:text/tei:body/tei:div[@n]", namespaces=TEI_NS)) == 25
    assert len(root.xpath("//tei:div[@type='observance']", namespaces=TEI_NS)) == 90
    assert len(root.xpath("//tei:div[@type='collect']", namespaces=TEI_NS)) == 85
    speeches = root.xpath("//tei:sp", namespaces=TEI_NS)
    assert all("".join(speech.find(f"{{{TEI_NS['tei']}}}p").itertext()).strip() for speech in speeches)
    assert not root.xpath("//tei:sp[@who='#bcp-role-all']", namespaces=TEI_NS)
    cross_block = root.xpath("//tei:sp[tei:p[@xml:id]]", namespaces={**TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"})
    cross_labels = Counter(" ".join("".join(speech.find(f"{{{TEI_NS['tei']}}}speaker").itertext()).split()) for speech in cross_block)
    assert {label: cross_labels[label] for label in (
        "The Bishop.", "The Bishop", "The Archbishop.", "Catechist", "Question",
    )} == {
        "The Bishop.": 15, "The Bishop": 1, "The Archbishop.": 7,
        "Catechist": 2, "Question": 4,
    }
    same_block_prayer = [
        speech for speech in speeches
        if " ".join("".join(speech.find(f"{{{TEI_NS['tei']}}}speaker").itertext()).split()) == "The Bishop."
        and " ".join("".join(speech.find(f"{{{TEI_NS['tei']}}}p").itertext()).split()) == "Let us pray."
        and speech.find(f"{{{TEI_NS['tei']}}}p").get(XML_ID) is None
    ]
    assert len(same_block_prayer) == 1
    formerly_misattached = {
        "bcp-block-f12b54f9f64b31c3cad97def": 2,
        "bcp-block-e87da341e4cbffe44b1ada5d": 8,
        "bcp-block-aa708413a959bd00574b4ac6": 10,
        "bcp-block-8df275f0bb03311d05231602": 6,
        "bcp-block-ec3bed9b132c5e8f68eac355": 18,
        "bcp-block-5c77c7d5c8b002aacbe0d3ef": 8,
        "bcp-block-27432e7e07c514b6b7df6bb0": 2,
    }
    xml = {"xml": "http://www.w3.org/XML/1998/namespace", **TEI_NS}
    for identifier, expected in formerly_misattached.items():
        block = root.xpath(f"//tei:div[@xml:id='{identifier}']", namespaces=xml)[0]
        assert len(block.xpath("./tei:sp", namespaces=TEI_NS)) == expected
        assert not block.xpath("./tei:sp/tei:p//tei:sp | ./tei:sp/tei:p//tei:speaker", namespaces=TEI_NS)
    for container in root.xpath("//tei:sp/tei:speaker | //tei:sp/tei:p", namespaces=TEI_NS):
        assert all(node.get(XML_ID) or node.get("corresp") for node in container.xpath(".//*[text()]"))
    morning_all = root.xpath("//tei:div[@n='daily__morning.html']//tei:div[contains(string(.), 'O ALL ye Works')]", namespaces=TEI_NS)
    assert morning_all and not morning_all[0].xpath(".//tei:sp", namespaces=TEI_NS)
    terminal_rubric = root.xpath("//tei:div[@n='occasions__commination.html']//tei:div[contains(string(.), 'after the Minister.')]", namespaces=TEI_NS)
    assert terminal_rubric and not terminal_rubric[0].xpath(".//tei:sp", namespaces=TEI_NS)
    assert root.xpath("count(//tei:seg[@type='drop-cap'])", namespaces=TEI_NS) == 603
    body_text = "".join(root.xpath("//tei:text/tei:body", namespaces=TEI_NS)[0].itertext())
    assert "ALMIGHTY" in body_text
    assert "A LMIGHTY" not in body_text
    alternative_nodes = root.xpath("//tei:div[@type='alternative-marker']", namespaces=TEI_NS)
    assert alternative_nodes
    assert all(node.get("corresp") and all(value.startswith("#") for value in node.get("corresp").split()) for node in alternative_nodes)


def test_readable_tei_preserves_inline_source_word_boundaries(bcp_candidate: CandidatePackage) -> None:
    root = etree.fromstring(bcp_candidate.member_bytes("content.tei.xml"))
    communion = root.xpath("//tei:div[@n='communion__index.html']", namespaces=TEI_NS)[0]
    text = "".join(communion.itertext())
    assert "Upon Christmas Day, and seven days after." in text
    assert "UponChristmas Day" not in text


def test_profile_is_the_declarative_speaker_block_and_heading_authority() -> None:
    profile = json.loads((ROOT / "sources/structured-text/bcp-1662/bcp-1662.reconstruction-profile.json").read_bytes())
    assert [item["canonical"] for item in profile["speaker_model"]["inline_roles"]] == [
        "Answer", "Minister", "Priest", "People", "Bishop", "Question",
    ]
    standalone = profile["speaker_model"]["standalone_roles"]
    assert any(item["canonical"] == "Archbishop" and item["block_forms"] == ["The Archbishop."] for item in standalone)
    assert any(item["canonical"] == "Catechist" and item["block_forms"] == ["Catechist"] for item in standalone)
    assert any(item["canonical"] == "Question" and "Question" in item["block_forms"] for item in standalone)
    non_roles = {item["form"] for item in profile["speaker_model"]["non_roles"] if "form" in item}
    assert non_roles == {"ALL", "terminal Minister."}
    assert profile["block_policy"]["start_elements"] == ["center", "h2", "h3", "hr"]
    assert profile["heading_model"]["model"] == "flat-source-anchored"


def test_two_clean_processes_are_byte_deterministic(tmp_path: Path) -> None:
    script = (
        "from pathlib import Path; import sys; "
        "from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct; "
        "from build.tei.bcp_1662_reconstruction import _convert; "
        "r=Path(sys.argv[1]).resolve(); "
        "m=SourceManifest.load(r/'tests/fixtures/reconstruction-runtime/bcp-1662.source-manifest.json',repository_root=r); "
        "c=reconstruct(m,Path(sys.argv[2]),_convert); print(c.sha256)"
    )
    outputs = []
    for index in range(2):
        destination = tmp_path / f"process-{index}"
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script, str(ROOT), str(destination)],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        outputs.append((completed.stdout.strip(), {item.name: item.read_bytes() for item in destination.iterdir()}))
    assert outputs[0] == outputs[1]


def _mutate_xml(content: bytes, label: str) -> bytes:
    root = etree.fromstring(content)
    if label == "drop-cap":
        node = root.xpath("//tei:seg[@type='drop-cap' and text()]", namespaces=TEI_NS)[0]
        node.text = "Invented"
    elif label == "comment-leak":
        node = root.xpath("//tei:seg[@type='source-text']", namespaces=TEI_NS)[0]
        node.text = "The sentence about the collect from Trinity 21 is new in the 1992 edition."
    elif label == "speaker":
        root.xpath("//tei:sp/tei:speaker", namespaces=TEI_NS)[0].text = "Invented."
    elif label == "multi-speaker-merge":
        block = next(node for node in root.xpath("//tei:div[count(tei:sp) > 1]", namespaces=TEI_NS))
        first, second = block.xpath("./tei:sp", namespaces=TEI_NS)[:2]
        destination = first.find(f"{{{TEI_NS['tei']}}}p")
        for source in second:
            for child in list(source):
                destination.append(child)
        block.remove(second)
    elif label == "multi-speaker-order":
        block = next(node for node in root.xpath("//tei:div[count(tei:sp) > 1]", namespaces=TEI_NS))
        first, second = block.xpath("./tei:sp", namespaces=TEI_NS)[:2]
        index = block.index(first)
        block.remove(second)
        block.insert(index, second)
    elif label == "speaker-anchor":
        continuation = root.xpath("//tei:sp//tei:seg[@type='source-continuation']", namespaces=TEI_NS)[0]
        continuation.attrib.pop("corresp")
    elif label == "empty-cross-utterance":
        utterance = root.xpath("//tei:sp/tei:p[@xml:id]", namespaces={**TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"})[0]
        utterance.text = None
        for child in list(utterance):
            utterance.remove(child)
    elif label == "unanchored-cross-utterance":
        utterance = root.xpath("//tei:sp/tei:p[@xml:id]", namespaces={**TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"})[0]
        anchored = utterance.xpath(".//*[@xml:id and text()]", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})[0]
        anchored.attrib.pop(XML_ID)
    elif label == "moved-following-block":
        utterances = root.xpath("//tei:sp/tei:p[@xml:id]", namespaces={**TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"})[:2]
        left, right = utterances
        left_parent, right_parent = left.getparent(), right.getparent()
        left_parent.remove(left)
        right_parent.remove(right)
        left_parent.append(right)
        right_parent.append(left)
    elif label == "all-role-invention":
        root.xpath("//tei:sp", namespaces=TEI_NS)[0].set("who", "#bcp-role-all")
    elif label == "terminal-rubric-invention":
        rubric = root.xpath("//tei:div[@n='occasions__commination.html']//tei:div[contains(string(.), 'after the Minister.')]", namespaces=TEI_NS)[0]
        source = rubric[0]
        rubric.remove(source)
        speech = etree.SubElement(rubric, f"{{{TEI_NS['tei']}}}sp", who="#bcp-role-minister")
        etree.SubElement(speech, f"{{{TEI_NS['tei']}}}speaker").text = "Minister."
        utterance = etree.SubElement(speech, f"{{{TEI_NS['tei']}}}p")
        utterance.text = source.text
        for child in list(source):
            source.remove(child)
            utterance.append(child)
    elif label in {"omitted-bishop", "omitted-unpunctuated-question"}:
        expected = "The Bishop." if label == "omitted-bishop" else "Question"
        speech = next(
            node for node in root.xpath("//tei:sp[tei:p[@xml:id]]", namespaces={**TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"})
            if " ".join("".join(node.find(f"{{{TEI_NS['tei']}}}speaker").itertext()).split()) == expected
        )
        wrapper, speaker, utterance = speech.getparent(), speech[0], speech[1]
        position = wrapper.index(speech)
        replacement = etree.Element(f"{{{TEI_NS['tei']}}}ab", type="source-block")
        replacement.set(XML_ID, utterance.get(XML_ID))
        for container in (speaker, utterance):
            for child in list(container):
                container.remove(child)
                replacement.append(child)
        wrapper.remove(speech)
        wrapper.insert(position, replacement)
    elif label in {"misclassified-archbishop", "misclassified-catechist"}:
        expected = "The Archbishop." if label == "misclassified-archbishop" else "Catechist"
        speech = next(
            node for node in root.xpath("//tei:sp[tei:p[@xml:id]]", namespaces={**TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"})
            if " ".join("".join(node.find(f"{{{TEI_NS['tei']}}}speaker").itertext()).split()) == expected
        )
        speech.set("who", "#bcp-role-bishop")
    elif label == "cross-block-order":
        wrapper = next(node for node in root.xpath("//tei:div[tei:sp[tei:p[@xml:id]] and count(tei:sp) > 1]", namespaces={**TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"}))
        first, second = wrapper.xpath("./tei:sp", namespaces=TEI_NS)[:2]
        wrapper.remove(second)
        wrapper.insert(wrapper.index(first), second)
    elif label == "block":
        root.xpath("//tei:div[@type='source-block']", namespaces=TEI_NS)[0].set("type", "invented-block")
    elif label == "alternative":
        root.xpath("//tei:div[@type='alternative-marker']", namespaces=TEI_NS)[0].set("corresp", "#invented-reading")
    elif label == "extra-marker":
        node = root.xpath("//tei:div[@type='source-block']", namespaces=TEI_NS)[0]
        node.set("type", "alternative-marker")
        node.set("corresp", "#invented-reading")
    elif label == "removed-marker":
        node = root.xpath("//tei:div[@type='alternative-marker']", namespaces=TEI_NS)[0]
        node.set("type", "source-block")
        node.attrib.pop("corresp")
    elif label == "punctuation":
        node = next(node for node in root.xpath("//tei:seg[@type='source-text' and text()]", namespaces=TEI_NS) if any(mark in (node.text or "") for mark in ".,:;") )
        node.text = node.text[:-1]
    elif label == "heading":
        root.xpath("//tei:div[@type='observance']/tei:head//tei:seg[text()]", namespaces=TEI_NS)[0].text = "Invented heading"
    elif label == "order":
        member = next(node for node in root.xpath("//tei:body/tei:div[@n]", namespaces=TEI_NS) if len(node.xpath("./tei:div", namespaces=TEI_NS)) > 2)
        blocks = member.xpath("./tei:div", namespaces=TEI_NS)
        first, second = blocks[0], blocks[1]
        first_index, second_index = member.index(first), member.index(second)
        member.remove(second)
        member.insert(first_index, second)
        member.remove(first)
        member.insert(second_index, first)
    elif label == "structure":
        block = root.xpath("//tei:div[@type='source-block']", namespaces=TEI_NS)[0]
        child = block[0]
        block.remove(child)
        wrapper = etree.SubElement(block, f"{{{TEI_NS['tei']}}}hi", rend="invented")
        wrapper.append(child)
    elif label == "metadata":
        root.xpath("//tei:titleStmt/tei:title", namespaces=TEI_NS)[0].text = "Invented title"
    elif label == "omission":
        node = root.xpath("//tei:anchor[@xml:id]", namespaces={**TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"})[0]
        node.getparent().remove(node)
    elif label == "duplication":
        stream = root.xpath("//tei:div[@type='source-block']/tei:ab", namespaces=TEI_NS)[0]
        duplicate = deepcopy(stream[0])
        duplicate.set(XML_ID, "bcp-observation-aaaaaaaaaaaaaaaaaaaaaaaa")
        stream.append(duplicate)
    elif label == "invention":
        stream = root.xpath("//tei:div[@type='source-block']/tei:ab", namespaces=TEI_NS)[0]
        invented = etree.SubElement(stream, f"{{{TEI_NS['tei']}}}seg", type="invented")
        invented.text = "Invented reading"
    else:
        raise AssertionError(label)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


@pytest.mark.parametrize(
    "label",
    [
        "drop-cap", "comment-leak", "speaker", "multi-speaker-merge", "multi-speaker-order", "speaker-anchor",
        "empty-cross-utterance", "unanchored-cross-utterance", "moved-following-block", "all-role-invention",
        "terminal-rubric-invention", "omitted-bishop", "misclassified-archbishop", "misclassified-catechist",
        "omitted-unpunctuated-question", "cross-block-order", "block", "alternative", "extra-marker",
        "removed-marker", "punctuation", "heading", "order", "structure", "metadata", "omission",
        "duplication", "invention",
    ],
)
def test_oracle_rejects_tei_mutations(
    tmp_path: Path, bcp_source_manifest: SourceManifest, bcp_candidate: CandidatePackage,
    bcp_candidate_integrity: None, label: str,
) -> None:
    with _mutated_copy(tmp_path, bcp_candidate, "content.tei.xml") as path:
        mutated = _reseal(path, "content.tei.xml", _mutate_xml((path / "content.tei.xml").read_bytes(), label))
        with pytest.raises(ValueError):
            _oracle(bcp_source_manifest, mutated)


@pytest.mark.parametrize("label", ["wrong-parser", "wrong-source"])
def test_oracle_rejects_accountability_mutations(
    tmp_path: Path, bcp_source_manifest: SourceManifest, bcp_candidate: CandidatePackage,
    bcp_candidate_integrity: None, label: str,
) -> None:
    with _mutated_copy(tmp_path, bcp_candidate, "source-accountability.json") as path:
        accountability = json.loads((path / "source-accountability.json").read_bytes())
        if label == "wrong-parser":
            accountability["parser"]["observation_fingerprint_sha256"] = "0" * 64
        else:
            accountability["crosswalk"][0]["value"] = "invented-source-element"
        mutated = _reseal(path, "source-accountability.json", _canonical(accountability))
        with pytest.raises(ValueError):
            _oracle(bcp_source_manifest, mutated)


@pytest.mark.parametrize("label", ["rights", "failed-acquisition"])
def test_oracle_rejects_provenance_mutations(
    tmp_path: Path, bcp_source_manifest: SourceManifest, bcp_candidate: CandidatePackage,
    bcp_candidate_integrity: None, label: str,
) -> None:
    with _mutated_copy(tmp_path, bcp_candidate, "provenance.json") as path:
        provenance = json.loads((path / "provenance.json").read_bytes())
        if label == "rights":
            provenance["rights"]["publication_authorized"] = True
        else:
            provenance["failed_acquisitions"].pop()
        mutated = _reseal(path, "provenance.json", _canonical(provenance))
        with pytest.raises(ValueError):
            _oracle(bcp_source_manifest, mutated)


def test_mutation_clone_attempted_content_overwrite_is_isolated(
    tmp_path: Path,
    bcp_candidate: CandidatePackage,
    bcp_candidate_integrity: None,
) -> None:
    original = bcp_candidate.member_bytes("content.tei.xml")
    clone_path: Path
    with _mutated_copy(tmp_path, bcp_candidate, "content.tei.xml") as path:
        clone_path = path
        (path / "content.tei.xml").write_bytes(b"dangerous attempted overwrite\n")

        assert bcp_candidate.member_bytes("content.tei.xml") == original
    assert not clone_path.exists()


def test_exact_mutation_cleanup_rejects_and_preserves_simulated_dangling_reparse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "candidate-mutation-copy"
    destination.write_bytes(b"preserve simulated reparse entry\n")
    destination_absolute = Path(os.path.abspath(destination))
    real_exists = Path.exists
    real_isjunction = getattr(os.path, "isjunction", lambda _path: False)

    def simulated_dangling_exists(path: Path) -> bool:
        if Path(os.path.abspath(path)) == destination_absolute:
            return False
        return real_exists(path)

    def simulated_junction(path: object) -> bool:
        if Path(os.path.abspath(path)) == destination_absolute:
            return True
        return real_isjunction(path)

    monkeypatch.setattr(Path, "exists", simulated_dangling_exists)
    monkeypatch.setattr(os.path, "isjunction", simulated_junction, raising=False)

    with pytest.raises(AssertionError, match="reparse"):
        _remove_exact_mutation_copy(destination, tmp_path)

    assert os.path.lexists(destination)
    assert destination.read_bytes() == b"preserve simulated reparse entry\n"
    monkeypatch.undo()
    destination.unlink()
    assert not os.path.lexists(destination)


def test_oracle_closure_is_transitive_and_excludes_producer(
    bcp_source_manifest: SourceManifest, bcp_candidate: CandidatePackage,
) -> None:
    result = _oracle(bcp_source_manifest, bcp_candidate)
    assert result["import_closure_sha256"] == bcp_source_manifest.record["validator"]["import_closure_sha256"]
    oracle_text = (ROOT / "build/tei/bcp_1662_oracle.py").read_text(encoding="utf-8")
    assert "bcp_1662_reconstruction" not in oracle_text
    assert "build.reconstruction" not in "\n".join(
        line for line in oracle_text.splitlines() if line.startswith(("import ", "from "))
    )


def test_oracle_rejects_subprocess_repo_dependency_shadow(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    reconstruction = shadow / "ocd_kernel" / "reconstruction"
    tei = shadow / "ocd_kernel" / "tei"
    lib = shadow / "ocd_kernel" / "lib"
    reconstruction.mkdir(parents=True)
    tei.mkdir(parents=True)
    lib.mkdir(parents=True)
    for package in (shadow / "ocd_kernel", reconstruction, tei, lib):
        (package / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(ROOT / "ocd_kernel/reconstruction/contract.py", reconstruction / "contract.py")
    shutil.copy2(ROOT / "ocd_kernel/tei/validate.py", tei / "validate.py")
    shutil.copy2(ROOT / "ocd_kernel/lib/storage_topology.py", lib / "storage_topology.py")
    shutil.copy2(ROOT / "ocd_kernel/lib/path_io.py", lib / "path_io.py")
    script = (
        "from pathlib import Path; import sys; "
        "root=Path(sys.argv[1]).resolve(); sys.path.insert(1,str(root)); "
        "from build.tei.bcp_1662_oracle import _runtime_repo_provenance; "
        "_runtime_repo_provenance(root)"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script, str(ROOT)],
        cwd=shadow, capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "outside the repository" in completed.stderr or "shadow path" in completed.stderr
