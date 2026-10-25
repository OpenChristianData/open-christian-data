from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable

from lxml import etree
import pytest

from build.tei import imitation_of_christ_oracle as oracle_module
from build.tei.imitation_of_christ_oracle import (
    _assert_loaded_paths,
    _oracle,
    _repository_import_closure,
    _verify_git_authority,
)
from build.tei.imitation_of_christ_reconstruction import _convert, _producer_closure
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SLUG = "thomas-a-kempis_the-imitation-of-christ_william-benham"
SOURCE_ROOT = ROOT / "raw/standard_ebooks" / SOURCE_SLUG
RETAINED_MANIFEST = (
    ROOT
    / "sources/standard-ebooks"
    / SOURCE_SLUG
    / "imitation-of-christ.source-manifest.json"
)
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/imitation-of-christ.source-manifest.json"
MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}
TEI = {"t": "http://www.tei-c.org/ns/1.0", "xml": "http://www.w3.org/XML/1998/namespace"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture(scope="module")
def kempis_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


def test_runtime_fixture_preserves_retained_authorities_and_only_updates_shared_runtime_closures() -> None:
    raw = RETAINED_MANIFEST.read_bytes()
    assert _sha(raw) == "a667dffbc5880dc1dc8996bb62d39e915bc8c7f5073b4219162f88ae03fe7c14"
    expected = json.loads(raw)
    policy_path = next(item["path"] for item in expected["authorities"]
                       if item["name"] == "validation-policy")
    policy = json.loads((ROOT / policy_path).read_bytes())
    expected["validator"]["import_closure_sha256"] = oracle_module._closure(
        ROOT, forbidden=tuple(policy["forbidden_import_prefixes"]))[0]
    profile = next(item for item in expected["authorities"]
                   if item["name"] == "reconstruction-profile")
    original_profile = (ROOT / profile["path"]).read_bytes()
    assert _sha(original_profile) == "984ae67084ecede2e29d59ae60d1961bd03ab8bf2a82eacd47f72628ed44afa2"
    expected_profile = json.loads(original_profile)
    expected_profile["producer_import_closure_sha256"] = _producer_closure(ROOT)[0]
    runtime_profile = MANIFEST.with_name("imitation-of-christ.reconstruction-profile.json")
    runtime_bytes = runtime_profile.read_bytes()
    assert json.loads(runtime_bytes) == expected_profile
    profile.update(path=runtime_profile.relative_to(ROOT).as_posix(),
                   bytes=len(runtime_bytes), sha256=_sha(runtime_bytes))
    assert json.loads(MANIFEST.read_bytes()) == expected


@pytest.fixture(scope="module")
def kempis_candidate(
    tmp_path_factory: pytest.TempPathFactory,
    kempis_manifest: SourceManifest,
) -> CandidatePackage:
    return reconstruct(
        kempis_manifest,
        tmp_path_factory.mktemp("kempis-candidate"),
        _convert,
    )


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _copy(tmp_path: Path, candidate: CandidatePackage, label: str) -> Path:
    destination = tmp_path / label
    shutil.copytree(candidate.path, destination)
    return destination


def _json_mutation(path: Path, name: str, mutate: Callable[[dict[str, object]], None]) -> None:
    record = json.loads((path / name).read_bytes())
    mutate(record)
    _reseal(path, name, _canonical(record))


def _tei_mutation(path: Path, mutate: Callable[[etree._Element], None]) -> None:
    tree = etree.fromstring((path / "content.tei.xml").read_bytes())
    mutate(tree)
    _reseal(
        path,
        "content.tei.xml",
        etree.tostring(tree, encoding="utf-8", xml_declaration=True, pretty_print=True),
    )


def test_manifest_binds_exact_clean_retained_authority(
    kempis_manifest: SourceManifest,
) -> None:
    kempis_manifest.verify()
    profile = json.loads(kempis_manifest.authority_path("reconstruction-profile").read_bytes())
    scope = profile["source_scope"]
    primary = [
        item for item in kempis_manifest.record["authorities"] if item["role"] == "primary-source"
    ]
    logical = [item["path"].split(f"/{SOURCE_SLUG}/", 1)[1] for item in primary]
    assert scope == {
        "commit": "03503a97cf39c5b5eea3b7522335aaa337a4a633",
        "tree": "035df211de2de3a544e4b61252bf9bc3dfbe73a9",
        "member_count": 142,
        "bytes": 5_110_829,
        "member_set_sha256": "1e5a5f4eb690c01d8424bc8bdaeb9dfc7add41690339e7b67e767e5046f98021",
        "config_bytes": 1_197,
        "config_sha256": "702c05e37ca46fed4c9337fe2f664f4b79ac7e813f4602e19ec748d0494a4134",
    }
    assert len(primary) == 142
    assert sum(item["bytes"] for item in primary) == 5_110_829
    assert logical == sorted(logical)
    _verify_git_authority(SOURCE_ROOT, scope, logical)


@pytest.mark.slow
def test_exact_six_member_nonaccepted_candidate_passes_independent_oracle(
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    assert {item["name"] for item in kempis_candidate.manifest["members"]} | {
        "manifest.json"
    } == MEMBERS
    assert kempis_candidate.manifest["status"] == "nonaccepted"
    report = validate(kempis_manifest, kempis_candidate, _oracle)
    assert report.status == "pass"
    assert report.findings == ()
    assert report.candidate_sha256 == kempis_candidate.sha256
    assert report.attestation["oracle_id"] == "ocd-imitation-of-christ-source-to-tei-oracle"
    assert report.attestation["source_sha256"] == "151fc4cf570ccbe9c16d43d29ca090470772e85b8dd2f53847049efb2c2e3463"


@pytest.mark.slow
def test_accounting_structure_and_package_only_evidence_are_exact(
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    profile = json.loads(kempis_manifest.authority_path("reconstruction-profile").read_bytes())
    accountability = json.loads(kempis_candidate.member_bytes("source-accountability.json"))
    provenance = json.loads(kempis_candidate.member_bytes("provenance.json"))
    assert {
        "xml_member_count": accountability["xml_member_count"],
        "non_xml_member_count": accountability["non_xml_member_count"],
        "xml_observation_count": accountability["xml_observation_count"],
        "element_count": accountability["element_count"],
        "attribute_count": accountability["attribute_count"],
        "text_count": accountability["text_count"],
        "represented_count": accountability["represented_count"],
        "evidence_only_count": accountability["evidence_only_count"],
        "omitted_count": accountability["omitted_count"],
        "duplicate_count": accountability["duplicate_count"],
    } == {
        "xml_member_count": 135,
        "non_xml_member_count": 7,
        "xml_observation_count": 10_009,
        "element_count": 3_582,
        "attribute_count": 4_283,
        "text_count": 2_144,
        "represented_count": 6_651,
        "evidence_only_count": 3_358,
        "omitted_count": 0,
        "duplicate_count": 0,
    }
    counts = profile["feature_counts"]
    assert counts["spine_members"] == 126 and counts["toc_links"] == 126
    assert (counts["front_members"], counts["body_members"], counts["back_members"]) == (5, 118, 3)
    assert counts["sections"] == 131 and counts["top_level_sections"] == 126
    assert counts["headings"] == 125 and counts["hgroups"] == 4
    assert counts["bridgeheads"] == 115 and counts["paragraphs"] == 922
    assert counts["note_references"] == counts["note_bodies"] == counts["note_backlinks"] == 183
    assert (counts["content_list_items"], counts["note_list_items"]) == (4, 183)
    assert counts["verse_lines"] == [2, 2, 3]
    assert counts["inline_carriers"] == {
        "a": 383, "abbr": 34, "b": 5, "strong": 1, "i": 24,
        "em": 5, "span": 23, "time": 8, "br": 26, "img": 3,
    }
    assert counts["language_carriers"] == {"en-GB": 122, "en-US": 4, "la": 20, "it": 1, "fr": 1}
    assert len(provenance["spine"]) == len(provenance["toc"]) == 126
    assert len(provenance["landmarks"]) == 2
    assert len(provenance["image_members"]) == 7
    assert len(provenance["packaged_images"]) == 3
    assert len(provenance["svg_strings"]) == 14
    assert {kind: sum(item["kind"] == kind for item in provenance["svg_strings"]) for kind in ("title", "text", "desc")} == {"title": 5, "text": 8, "desc": 1}
    assert provenance["metadata_conflicts"] == profile["metadata_conflicts"]
    assert provenance["rights"] == profile["rights"]
    readme = kempis_candidate.member_bytes("README.source.md").decode("utf-8")
    for phrase in (
        "explicitly nonaccepted", "attribution dispute", "1874 dedication versus 1877 colophon",
        "Project Gutenberg #26222", "#1653", "other jurisdictions", "CC0 1.0",
        "not human textual acceptance",
    ):
        assert phrase in readme


@pytest.mark.slow
def test_tei_is_xsd_valid_and_preserves_exact_occurrence_carriers(
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    tei = etree.fromstring(kempis_candidate.member_bytes("content.tei.xml"))
    xsd = etree.XMLSchema(etree.parse(str(kempis_manifest.authority_path("tei-p5-xsd"))))
    assert xsd.validate(tei), xsd.error_log
    assert len(tei.xpath("/t:TEI/t:text/t:body/t:div", namespaces=TEI)) == 126
    assert len(tei.xpath("//t:div[@xml:id]", namespaces=TEI)) == 131
    assert len(tei.xpath("//t:ref[@type='note']", namespaces=TEI)) == 183
    assert len(tei.xpath("//t:item[starts-with(@xml:id,'note-')]", namespaces=TEI)) == 183
    assert len(tei.xpath("//t:ref[@type='backlink']", namespaces=TEI)) == 183
    assert [len(node.xpath("./t:l", namespaces=TEI)) for node in tei.xpath("//t:lg[@type='verse']", namespaces=TEI)] == [2, 2, 3]
    alternatives = tei.xpath("//t:figure[@type='source-img']/t:figDesc", namespaces=TEI)
    assert [" ".join("".join(node.itertext()).split()) for node in alternatives].count("") == 1
    assert [" ".join("".join(node.itertext()).split()) for node in alternatives].count("The Standard Ebooks logo.") == 2
    responsibilities = [
        [
            " ".join("".join(node.xpath("./t:resp", namespaces=TEI)[0].itertext()).split()),
            " ".join("".join(node.xpath("./t:name", namespaces=TEI)[0].itertext()).split()),
        ]
        for node in tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:respStmt", namespaces=TEI)
    ]
    assert responsibilities == [
        ["translator, annotator, and writer of preface", "William Benham"],
        ["annotator", "H. C. Beeching"],
    ]
    assert not tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc//t:editor", namespaces=TEI)


@pytest.mark.slow
def test_projection_dispositions_are_an_exact_candidate_source_binding_bijection(
    kempis_candidate: CandidatePackage,
) -> None:
    accountability = json.loads(kempis_candidate.member_bytes("source-accountability.json"))
    observations = accountability["observations"]
    source_bindings = {item["source_binding"] for item in observations}
    represented = {item["candidate_binding"] for item in observations if item["disposition"] == "represented"}
    evidence_only = {item["source_binding"] for item in observations if item["disposition"] == "evidence-only"}
    projected = [item["binding"] for item in accountability["projection_targets"]]
    assert len(source_bindings) == accountability["source_binding_count"] == 3_582
    assert len(represented) == accountability["represented_binding_count"] == 2_265
    assert len(evidence_only) == accountability["evidence_only_binding_count"] == 1_317
    assert len(projected) == len(set(projected)) == accountability["candidate_binding_count"] == 2_265
    assert represented == set(projected)
    assert represented.isdisjoint(evidence_only)
    assert represented | evidence_only == source_bindings
    assert _sha(_canonical(projected)) == accountability["candidate_binding_set_sha256"]
    labels = [item["disposition"] for item in observations]
    assert _sha(_canonical(labels)) == accountability["ordered_dispositions_sha256"]
    assert "readiness_disposition_digest" not in accountability


@pytest.mark.slow
def test_deterministic_in_process_and_fresh_process(
    tmp_path: Path,
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    again = reconstruct(kempis_manifest, tmp_path / "again", _convert)
    assert again.sha256 == kempis_candidate.sha256
    script = (
        "from pathlib import Path;from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct;"
        "from build.tei.imitation_of_christ_reconstruction import _convert;"
        "r=Path(sys.argv[1]).resolve();m=SourceManifest.load(r/sys.argv[2],repository_root=r);"
        "print(reconstruct(m,Path(sys.argv[3]),_convert).sha256)"
    )
    result = subprocess.run(
        [
            sys.executable, "-c", "import sys;" + script, str(ROOT),
            MANIFEST.relative_to(ROOT).as_posix(), str(tmp_path / "fresh"),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == kempis_candidate.sha256


def _accountability_omission(path: Path) -> None:
    _json_mutation(path, "source-accountability.json", lambda value: value["observations"].pop())


def _accountability_invention(path: Path) -> None:
    def mutate(value: dict[str, object]) -> None:
        invented = copy.deepcopy(value["observations"][0])
        invented["observation_id"] = "invented#00001"
        value["observations"].append(invented)
    _json_mutation(path, "source-accountability.json", mutate)


def _member_omission(path: Path) -> None:
    _json_mutation(path, "source-accountability.json", lambda value: value["source_members"].pop())


def _spine_reorder(path: Path) -> None:
    def mutate(value: dict[str, object]) -> None:
        value["spine"][0], value["spine"][1] = value["spine"][1], value["spine"][0]
    _json_mutation(path, "provenance.json", mutate)


def _toc_reorder(path: Path) -> None:
    def mutate(value: dict[str, object]) -> None:
        value["toc"][0], value["toc"][1] = value["toc"][1], value["toc"][0]
    _json_mutation(path, "provenance.json", mutate)


def _landmark_swap(path: Path) -> None:
    def mutate(value: dict[str, object]) -> None:
        value["landmarks"][0]["href"], value["landmarks"][1]["href"] = value["landmarks"][1]["href"], value["landmarks"][0]["href"]
    _json_mutation(path, "provenance.json", mutate)


def _image_member_omission(path: Path) -> None:
    _json_mutation(path, "provenance.json", lambda value: value["image_members"].pop())


def _css_continued_loss(path: Path) -> None:
    _json_mutation(path, "provenance.json", lambda value: value["css_semantics"]["continued"]["occurrence_bindings"].pop())


def _rights_conflation(path: Path) -> None:
    _json_mutation(path, "provenance.json", lambda value: value["rights"].update({"underlying_work": "CC0 1.0"}))


def _section_swap(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        nodes = tei.xpath("/t:TEI/t:text/t:body/t:div", namespaces=TEI)
        nodes[0].set("corresp", nodes[1].get("corresp"))
    _tei_mutation(path, mutate)


def _projection_carrier_omission(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        node = next(
            item
            for item in tei.xpath("//*[@corresp]")
            if len(item.get("corresp", "").split()) > 1
            and etree.QName(item).localname == "head"
        )
        bindings = node.get("corresp", "").split()
        node.set("corresp", " ".join(bindings[1:]))
    _tei_mutation(path, mutate)


def _projection_carrier_duplicate(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        nodes = [node for node in tei.xpath("//*[@corresp]") if node.get("corresp", "").split()]
        duplicate = nodes[0].get("corresp", "").split()[0]
        target = next(node for node in nodes[1:] if duplicate not in node.get("corresp", "").split())
        target.set("corresp", f"{target.get('corresp')} {duplicate}")
    _tei_mutation(path, mutate)


def _outside_source_binding(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        node = tei.xpath("/t:TEI/t:text/t:body/t:div", namespaces=TEI)[0]
        node.set("corresp", f"{node.get('corresp')} urn:ocd-source-observation:{'f' * 64}")
    _tei_mutation(path, mutate)


def _nested_section_move(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        nested = tei.xpath("//t:div[@xml:id='chapter-3-3-1']", namespaces=TEI)[0]
        destination = tei.xpath("//t:div[@xml:id='chapter-3-4']", namespaces=TEI)[0]
        nested.getparent().remove(nested)
        destination.append(nested)
    _tei_mutation(path, mutate)


def _paragraph_attachment_swap(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        first = tei.xpath("//t:div[@xml:id='chapter-1-1']//t:p", namespaces=TEI)[1]
        second = tei.xpath("//t:div[@xml:id='chapter-1-2']//t:p", namespaces=TEI)[1]
        first_binding, second_binding = first.get("corresp"), second.get("corresp")
        first.set("corresp", second_binding)
        second.set("corresp", first_binding)
    _tei_mutation(path, mutate)


def _identical_repeated_paragraph_section_swap(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        first = tei.xpath("//t:div[@xml:id='chapter-4-1']//t:p", namespaces=TEI)[1]
        second = tei.xpath("//t:div[@xml:id='chapter-4-2']//t:p", namespaces=TEI)[1]
        assert " ".join("".join(first.itertext()).split()) == " ".join("".join(second.itertext()).split()) == "The Voice of the Disciple."
        first_binding, second_binding = first.get("corresp"), second.get("corresp")
        first.set("corresp", second_binding)
        second.set("corresp", first_binding)
    _tei_mutation(path, mutate)


def _note_target_cross(path: Path) -> None:
    _tei_mutation(path, lambda tei: tei.xpath("//t:ref[@type='note']", namespaces=TEI)[0].set("target", "#note-2"))


def _note_body_cross(path: Path) -> None:
    _tei_mutation(path, lambda tei: tei.xpath("//t:item[@xml:id='note-1']", namespaces=TEI)[0].set(XML_ID, "note-crossed"))


def _note_backlink_cross(path: Path) -> None:
    _tei_mutation(path, lambda tei: tei.xpath("//t:ref[@type='backlink']", namespaces=TEI)[0].set("target", "#noteref-2"))


def _note_label_cross(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        tei.xpath("//t:ref[@type='note']", namespaces=TEI)[0].text = "2"
    _tei_mutation(path, mutate)


def _hgroup_loss(path: Path) -> None:
    _tei_mutation(path, lambda tei: tei.xpath("//t:head[@type='hgroup']", namespaces=TEI)[0].set("type", "lost"))


def _bridgehead_loss(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        node = tei.xpath("//*[contains(concat(' ',normalize-space(@rend),' '),' source-bridgehead ')]", namespaces=TEI)[0]
        node.set("rend", " ".join(token for token in node.get("rend", "").split() if token != "source-bridgehead"))
    _tei_mutation(path, mutate)


def _list_item_swap(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        node = next(item for item in tei.xpath("//t:list", namespaces=TEI) if len(item.xpath("./t:item", namespaces=TEI)) == 4)
        first, second = node[0], node[1]
        node.remove(second)
        node.insert(0, second)
        assert node[1] is first
    _tei_mutation(path, mutate)


def _verse_line_move(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        groups = tei.xpath("//t:lg[@type='verse']", namespaces=TEI)
        line = groups[0][-1]
        groups[0].remove(line)
        groups[1].append(line)
    _tei_mutation(path, mutate)


def _inline_same_count_swap(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        nodes = tei.xpath("//t:abbr[@type='source-abbr']", namespaces=TEI)
        first = nodes[0]
        second = next(node for node in nodes[1:] if "".join(node.itertext()) != "".join(first.itertext()))
        a, b = first.get("corresp"), second.get("corresp")
        first.set("corresp", b)
        second.set("corresp", a)
    _tei_mutation(path, mutate)


def _language_same_count_swap(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        first = tei.xpath("//*[@xml:lang='la']", namespaces=TEI)[0]
        second = tei.xpath("//*[@xml:lang='fr']", namespaces=TEI)[0]
        first.set(XML_LANG, "fr")
        second.set(XML_LANG, "la")
    _tei_mutation(path, mutate)


def _image_attachment_swap(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        figure = tei.xpath("//t:figure[@type='source-img']", namespaces=TEI)[0]
        figure.xpath("./t:graphic", namespaces=TEI)[0].set("url", "../images/invented.svg")
        figure.xpath("./t:figDesc", namespaces=TEI)[0].text = "Invented alternative"
    _tei_mutation(path, mutate)


def _continued_loss(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        node = tei.xpath("//t:p[contains(concat(' ',normalize-space(@rend),' '),' continued ')]", namespaces=TEI)[0]
        retained = [token for token in node.get("rend", "").split() if token != "continued"]
        if retained:
            node.set("rend", " ".join(retained))
        else:
            del node.attrib["rend"]
    _tei_mutation(path, mutate)


def _continued_relocation(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        source = tei.xpath("//t:p[contains(concat(' ',normalize-space(@rend),' '),' continued ')]", namespaces=TEI)[0]
        target = next(node for node in tei.xpath("//t:p", namespaces=TEI) if "continued" not in node.get("rend", "").split())
        retained = [token for token in source.get("rend", "").split() if token != "continued"]
        if retained:
            source.set("rend", " ".join(retained))
        else:
            del source.attrib["rend"]
        target.set("rend", f"{target.get('rend', '')} continued".strip())
    _tei_mutation(path, mutate)


def _eoc_loss(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        node = tei.xpath("//t:abbr[contains(concat(' ',normalize-space(@rend),' '),' eoc ')]", namespaces=TEI)[0]
        retained = [token for token in node.get("rend", "").split() if token != "eoc"]
        if retained:
            node.set("rend", " ".join(retained))
        else:
            del node.attrib["rend"]
    _tei_mutation(path, mutate)


def _eoc_relocation(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        source = tei.xpath("//t:abbr[contains(concat(' ',normalize-space(@rend),' '),' eoc ')]", namespaces=TEI)[0]
        target = next(node for node in tei.xpath("//t:abbr", namespaces=TEI) if "eoc" not in node.get("rend", "").split())
        retained = [token for token in source.get("rend", "").split() if token != "eoc"]
        if retained:
            source.set("rend", " ".join(retained))
        else:
            del source.attrib["rend"]
        target.set("rend", f"{target.get('rend', '')} eoc".strip())
    _tei_mutation(path, mutate)


def _role_invention(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:respStmt/t:resp", namespaces=TEI)[0].text = "editor"
    _tei_mutation(path, mutate)


def _definitive_1427_invention(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        bibliography = tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl", namespaces=TEI)[0]
        date = etree.Element("{http://www.tei-c.org/ns/1.0}date", {"when": "1427"})
        date.text = "Definitively written in 1427"
        bibliography.append(date)
    _tei_mutation(path, mutate)
    _reseal(
        path,
        "README.source.md",
        (path / "README.source.md").read_bytes() + b"\nThe work was definitively written in 1427.\n",
    )


def _worldwide_clearance_invention(path: Path) -> None:
    def mutate(tei: etree._Element) -> None:
        paragraph = tei.xpath(
            "/t:TEI/t:teiHeader/t:fileDesc/t:publicationStmt/t:availability/t:p",
            namespaces=TEI,
        )[0]
        paragraph.text = f"{paragraph.text} The work is public domain worldwide and cleared for publication."
    _tei_mutation(path, mutate)
    _reseal(
        path,
        "README.source.md",
        (path / "README.source.md").read_bytes()
        + b"\nThe work is public domain worldwide and cleared for publication.\n",
    )


MUTATIONS = [
    ("accountability-omission", _accountability_omission),
    ("accountability-invention", _accountability_invention),
    ("source-member-omission", _member_omission),
    ("spine-reorder", _spine_reorder),
    ("toc-reorder", _toc_reorder),
    ("landmark-swap", _landmark_swap),
    ("image-member-omission", _image_member_omission),
    ("css-continued-evidence-loss", _css_continued_loss),
    ("rights-conflation", _rights_conflation),
    ("same-count-section-swap", _section_swap),
    ("projection-carrier-omission", _projection_carrier_omission),
    ("projection-carrier-duplicate", _projection_carrier_duplicate),
    ("outside-source-binding", _outside_source_binding),
    ("nested-section-move", _nested_section_move),
    ("repeated-paragraph-attachment-swap", _paragraph_attachment_swap),
    ("identical-chapter-4-paragraph-section-swap", _identical_repeated_paragraph_section_swap),
    ("note-target-cross", _note_target_cross),
    ("note-body-cross", _note_body_cross),
    ("note-backlink-cross", _note_backlink_cross),
    ("note-label-cross", _note_label_cross),
    ("hgroup-loss", _hgroup_loss),
    ("bridgehead-loss", _bridgehead_loss),
    ("list-item-swap", _list_item_swap),
    ("verse-line-move", _verse_line_move),
    ("inline-same-count-swap", _inline_same_count_swap),
    ("language-same-count-swap", _language_same_count_swap),
    ("image-attachment-swap", _image_attachment_swap),
    ("continued-loss", _continued_loss),
    ("continued-relocation", _continued_relocation),
    ("eoc-loss", _eoc_loss),
    ("eoc-relocation", _eoc_relocation),
    ("retained-role-invention", _role_invention),
]


@pytest.mark.slow
@pytest.mark.parametrize(("label", "mutate"), MUTATIONS, ids=[item[0] for item in MUTATIONS])
def test_resealed_candidate_mutations_fail_closed(
    label: str,
    mutate: Callable[[Path], None],
    tmp_path: Path,
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    path = _copy(tmp_path, kempis_candidate, label)
    mutate(path)
    changed = CandidatePackage.load(path)
    with pytest.raises((ValueError, KeyError, etree.XMLSyntaxError)):
        validate(kempis_manifest, changed, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("definitive-1427", _definitive_1427_invention),
        ("worldwide-publication-clearance", _worldwide_clearance_invention),
    ],
)
def test_xsd_valid_coordinated_header_and_readme_inventions_fail_exact_surfaces(
    label: str,
    mutate: Callable[[Path], None],
    tmp_path: Path,
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    path = _copy(tmp_path, kempis_candidate, label)
    mutate(path)
    changed = CandidatePackage.load(path)
    tei = etree.fromstring(changed.member_bytes("content.tei.xml"))
    xsd = etree.XMLSchema(etree.parse(str(kempis_manifest.authority_path("tei-p5-xsd"))))
    assert xsd.validate(tei), xsd.error_log
    with pytest.raises(ValueError, match="complete allowed TEI header|complete package-only README"):
        validate(kempis_manifest, changed, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize("mutate", [_continued_relocation, _eoc_relocation], ids=["continued", "eoc"])
def test_css_relocations_are_xsd_valid_and_reach_semantic_attachment_check(
    mutate: Callable[[Path], None],
    tmp_path: Path,
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    path = _copy(tmp_path, kempis_candidate, f"semantic-{mutate.__name__}")
    mutate(path)
    changed = CandidatePackage.load(path)
    tei = etree.fromstring(changed.member_bytes("content.tei.xml"))
    xsd = etree.XMLSchema(etree.parse(str(kempis_manifest.authority_path("tei-p5-xsd"))))
    assert xsd.validate(tei), xsd.error_log
    with pytest.raises(ValueError, match="continued/eoc semantics"):
        validate(kempis_manifest, changed, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize("carrier_kind", ["identical-paragraph", "identical-inline-carrier"])
def test_coordinated_accountability_reseal_cannot_hide_identical_carrier_swap(
    carrier_kind: str,
    tmp_path: Path,
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    path = _copy(tmp_path, kempis_candidate, f"coordinated-{carrier_kind}")
    tei = etree.fromstring((path / "content.tei.xml").read_bytes())
    if carrier_kind == "identical-paragraph":
        first = tei.xpath("//t:div[@xml:id='chapter-4-1']//t:p", namespaces=TEI)[1]
        second = tei.xpath("//t:div[@xml:id='chapter-4-2']//t:p", namespaces=TEI)[1]
        assert " ".join("".join(first.itertext()).split()) == " ".join("".join(second.itertext()).split())
    else:
        grouped: dict[tuple[str, str], list[etree._Element]] = {}
        for node in tei.xpath("//t:a[@corresp] | //t:abbr[@corresp] | //t:hi[@corresp] | //t:seg[@corresp]", namespaces=TEI):
            key = (etree.QName(node).localname, " ".join("".join(node.itertext()).split()))
            grouped.setdefault(key, []).append(node)
        first, second = next(
            (nodes[0], nodes[1])
            for nodes in grouped.values()
            if len(nodes) > 1 and nodes[0].get("corresp") != nodes[1].get("corresp")
        )
    first_bindings = first.get("corresp", "").split()
    second_bindings = second.get("corresp", "").split()
    assert len(first_bindings) == len(second_bindings) and first_bindings
    first.set("corresp", " ".join(second_bindings))
    second.set("corresp", " ".join(first_bindings))
    _reseal(
        path,
        "content.tei.xml",
        etree.tostring(tei, encoding="utf-8", xml_declaration=True, pretty_print=True),
    )

    accountability = json.loads((path / "source-accountability.json").read_bytes())
    targets = {item["binding"]: item for item in accountability["projection_targets"]}
    observations = {item["source_binding"]: item for item in accountability["observations"]}
    remapping = dict(zip(first_bindings, second_bindings, strict=True)) | dict(
        zip(second_bindings, first_bindings, strict=True)
    )
    original_targets = {binding: copy.deepcopy(targets[binding]["targets"]) for binding in remapping}
    for binding, replacement in remapping.items():
        targets[binding]["targets"] = original_targets[replacement]
        observations[binding]["candidate_binding"] = replacement
    for semantic_name, records in accountability["semantic_bindings"].items():
        if not isinstance(records, list):
            continue
        changed_semantic = False
        for record in records:
            if isinstance(record, dict) and record.get("binding") in remapping:
                record["binding"] = remapping[record["binding"]]
                changed_semantic = True
        if changed_semantic:
            accountability["semantic_digests"][semantic_name] = _sha(_canonical(records))
    _reseal(path, "source-accountability.json", _canonical(accountability))
    with pytest.raises(ValueError):
        validate(kempis_manifest, CandidatePackage.load(path), _oracle)


@pytest.mark.slow
def test_coordinated_metadata_invention_still_fails_against_direct_source(
    tmp_path: Path,
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    path = _copy(tmp_path, kempis_candidate, "coordinated-metadata")
    _tei_mutation(
        path,
        lambda tei: setattr(
            tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:author", namespaces=TEI)[0],
            "text",
            "Invented Certain Author",
        ),
    )
    _json_mutation(
        path,
        "provenance.json",
        lambda value: value["metadata"].update({"popular_attribution": "Invented Certain Author"}),
    )
    with pytest.raises(ValueError):
        validate(kempis_manifest, CandidatePackage.load(path), _oracle)


class _AuthorityFacade:
    def __init__(self, manifest: SourceManifest, overrides: dict[str, Path]) -> None:
        self._manifest = manifest
        self._overrides = overrides
        self.repository_root = manifest.repository_root
        self.path = manifest.path
        self.sha256 = manifest.sha256
        self.record = manifest.record

    def verify(self) -> None:
        return None

    def authority_path(self, name: str) -> Path:
        return self._overrides.get(name, self._manifest.authority_path(name))


class _ResealedPolicyFacade(_AuthorityFacade):
    def __init__(self, manifest: SourceManifest, policy_path: Path) -> None:
        super().__init__(manifest, {"validation-policy": policy_path})
        record = json.loads(manifest.path.read_bytes())
        policy_bytes = policy_path.read_bytes()
        policy_authority = next(
            item for item in record["authorities"] if item["name"] == "validation-policy"
        )
        policy_authority.update(bytes=len(policy_bytes), sha256=_sha(policy_bytes))
        self.sha256 = _sha(_canonical(record))
        record["authorities"] = tuple(record["authorities"])
        self.record = record


@pytest.mark.slow
def test_policy_leaves_disposition_totals_to_accountability_authority(
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    policy = json.loads(kempis_manifest.authority_path("validation-policy").read_bytes())
    assert {
        "represented_observations",
        "evidence_only_observations",
    }.isdisjoint(policy["required_counts"])

    accountability = json.loads(kempis_candidate.member_bytes("source-accountability.json"))
    assert accountability["represented_count"] == 6_651
    assert accountability["evidence_only_count"] == 3_358
    schema = json.loads(
        kempis_manifest.authority_path("source-accountability-schema").read_bytes()
    )
    assert schema["properties"]["represented_count"]["const"] == 6_651
    assert schema["properties"]["evidence_only_count"]["const"] == 3_358


@pytest.mark.slow
@pytest.mark.parametrize(
    ("represented", "evidence_only"),
    [(6_690, 3_319), (0, 10_009)],
)
def test_coordinated_policy_manifest_reseal_cannot_reintroduce_disposition_counts(
    represented: int,
    evidence_only: int,
    tmp_path: Path,
    kempis_manifest: SourceManifest,
) -> None:
    policy = json.loads(kempis_manifest.authority_path("validation-policy").read_bytes())
    policy["required_counts"].update(
        represented_observations=represented,
        evidence_only_observations=evidence_only,
    )
    policy_path = tmp_path / "resealed-validation-policy.json"
    policy_path.write_bytes(_canonical(policy))
    facade = _ResealedPolicyFacade(kempis_manifest, policy_path)
    candidate = reconstruct(facade, tmp_path / "resealed-candidate", _convert)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="validation policy count shape drifted"):
        _oracle(facade, candidate)  # type: ignore[arg-type]


@pytest.mark.slow
@pytest.mark.parametrize("authority", ["local-source-config", "tei-p5-xsd"])
def test_wrong_config_or_xsd_authority_fails_closed(
    authority: str,
    tmp_path: Path,
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    wrong = tmp_path / ("wrong.json" if authority == "local-source-config" else "wrong.xsd")
    wrong.write_text(
        "{}\n" if authority == "local-source-config" else '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>\n',
        encoding="utf-8",
    )
    facade = _AuthorityFacade(kempis_manifest, {authority: wrong})
    with pytest.raises(ValueError):
        _oracle(facade, kempis_candidate)  # type: ignore[arg-type]


@pytest.mark.slow
def test_wrong_oracle_attestation_fails_closed(
    kempis_manifest: SourceManifest,
    kempis_candidate: CandidatePackage,
) -> None:
    def impostor(source: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
        return {"status": "pass", "findings": []}

    with pytest.raises(ValueError):
        validate(kempis_manifest, kempis_candidate, impostor)


@pytest.mark.slow
def test_wrong_commit_tree_and_dirty_source_fail_on_isolated_copy(
    tmp_path: Path,
    kempis_manifest: SourceManifest,
) -> None:
    copy_root = tmp_path / SOURCE_SLUG
    subprocess.run(
        ["git", "clone", "--quiet", "--no-local", str(SOURCE_ROOT), str(copy_root)],
        check=True,
        capture_output=True,
    )
    profile = json.loads(kempis_manifest.authority_path("reconstruction-profile").read_bytes())
    logical = [
        item["path"].split(f"/{SOURCE_SLUG}/", 1)[1]
        for item in kempis_manifest.record["authorities"]
        if item["role"] == "primary-source"
    ]
    (copy_root / "invented.txt").write_text("isolated mutation\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dirty retained checkout"):
        _verify_git_authority(copy_root, profile["source_scope"], logical)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "add", "invented.txt"],
        cwd=copy_root,
        check=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "isolated mutation"],
        cwd=copy_root,
        check=True,
        capture_output=True,
    )
    with pytest.raises(ValueError, match="wrong retained commit or tree"):
        _verify_git_authority(copy_root, profile["source_scope"], logical)


@pytest.mark.parametrize("mode", ["omission", "invention"])
def test_tracked_member_set_mutations_fail_even_with_clean_expected_revision(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    kempis_manifest: SourceManifest,
) -> None:
    profile = json.loads(kempis_manifest.authority_path("reconstruction-profile").read_bytes())
    logical = [
        item["path"].split(f"/{SOURCE_SLUG}/", 1)[1]
        for item in kempis_manifest.record["authorities"]
        if item["role"] == "primary-source"
    ]
    altered = logical[:-1] if mode == "omission" else [*logical, "invented.txt"]

    def fake_git(_root: Path, *args: str) -> bytes:
        command = args[0]
        if command == "rev-parse":
            return (
                profile["source_scope"]["tree"]
                if args[-1] == "HEAD^{tree}"
                else profile["source_scope"]["commit"]
            ).encode("ascii") + b"\n"
        if command == "status":
            return b""
        if command == "ls-files":
            return ("\0".join(altered) + "\0").encode("utf-8")
        raise AssertionError(args)

    monkeypatch.setattr(oracle_module, "_git_value", fake_git)
    with pytest.raises(ValueError, match="tracked-member omission or invention"):
        _verify_git_authority(SOURCE_ROOT, profile["source_scope"], logical)


def test_recursive_dependency_drift_and_forbidden_import_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "closure"
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    entry = package / "entry.py"
    dependency = package / "dependency.py"
    entry.write_text("from pkg import dependency\n", encoding="utf-8")
    dependency.write_text("VALUE = 1\n", encoding="utf-8")
    before = _repository_import_closure(root, entry, ())
    dependency.write_text("VALUE = 2\n", encoding="utf-8")
    after = _repository_import_closure(root, entry, ())
    assert before != after
    dependency.write_text("import forbidden.answers\n", encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden import"):
        _repository_import_closure(root, entry, ("forbidden",))


def test_runtime_editable_shadow_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ShadowManifest:
        pass

    monkeypatch.setattr(oracle_module, "SourceManifest", ShadowManifest)
    with pytest.raises(ValueError, match="contract classes are not source-backed|shadow"):
        _assert_loaded_paths(ROOT)
