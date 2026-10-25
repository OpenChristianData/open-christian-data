from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei import calvins_institutes_oracle as oracle_module
from build.tei.calvins_institutes_oracle import (
    _closure_digest,
    _independent_model,
    _oracle,
    _paragraphs,
    _repository_import_closure,
    _runtime_paths,
    _scan_records,
    _verify_tei,
)
from build.tei.calvins_institutes_reconstruction import _convert
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.slow
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/calvins-institutes.source-manifest.json"
VOLUMES = (ROOT / "raw/gutenberg/pg45001.txt", ROOT / "raw/gutenberg/pg64392.txt")
MEMBERS = {"manifest.json", "content.tei.xml", "source-accountability.json", "provenance.json", "unresolved.jsonl", "README.source.md"}
NS = {"tei": "http://www.tei-c.org/ns/1.0", "xml": "http://www.w3.org/XML/1998/namespace"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.fixture(scope="module")
def calvin_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="module")
def source_model(calvin_manifest: SourceManifest) -> tuple[list[list[dict[str, object]]], dict[str, object], dict[str, object]]:
    blocks = []
    for volume, name in ((1, "retained-volume-1"), (2, "retained-volume-2")):
        authority = next(item for item in calvin_manifest.record["authorities"] if item["name"] == name)
        rows = _scan_records(volume, str(authority["path"]), calvin_manifest.authority_path(name).read_bytes())
        blocks.append(_paragraphs(rows))
    policy = json.loads(calvin_manifest.authority_path("validation-policy").read_bytes())
    return blocks, _independent_model(blocks), policy


@pytest.fixture(scope="module")
def calvin_candidate(tmp_path_factory: pytest.TempPathFactory, calvin_manifest: SourceManifest) -> CandidatePackage:
    return reconstruct(calvin_manifest, tmp_path_factory.mktemp("calvin-candidate"), _convert)


def _copy(tmp_path: Path, candidate: CandidatePackage, label: str) -> Path:
    destination = tmp_path / label
    shutil.copytree(candidate.path, destination)
    return destination


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def test_manifest_binds_exact_two_volume_retained_authority(calvin_manifest: SourceManifest) -> None:
    primary = [item for item in calvin_manifest.record["authorities"] if item["role"] == "primary-source"]
    assert primary == [
        {"bytes": 1925337, "name": "retained-volume-1", "path": "raw/gutenberg/pg45001.txt", "role": "primary-source", "sha256": "a989a8661fedc4e999ae4b5ba749a40e7e9e4d441e88f08ff97ce9d75623746c"},
        {"bytes": 2134850, "name": "retained-volume-2", "path": "raw/gutenberg/pg64392.txt", "role": "primary-source", "sha256": "3d79335bbb231773d1cbf849f4f7dd67e52f8773091416ba765da3ade0fefb31"},
    ]
    assert [(len(path.read_bytes()), len(path.read_bytes().splitlines()), _sha(path.read_bytes())) for path in VOLUMES] == [
        (1925337, 31174, primary[0]["sha256"]),
        (2134850, 38723, primary[1]["sha256"]),
    ]
    profile = json.loads(calvin_manifest.authority_path("reconstruction-profile").read_bytes())
    assert profile["source_scope"]["bytes"] == 4060187
    assert profile["source_scope"]["physical_lines"] == 69897
    assert not any(key.startswith("reviewed_") for key in profile)
    assert not any(key.startswith("reviewed_") for key in profile["source_scope"])


def test_complete_candidate_validates_and_is_explicitly_nonaccepted(calvin_manifest: SourceManifest, calvin_candidate: CandidatePackage) -> None:
    assert set(calvin_candidate.member_names) == MEMBERS
    assert calvin_candidate.manifest["status"] == "nonaccepted"
    report = validate(calvin_manifest, calvin_candidate, _oracle)
    assert report.status == "pass"
    accountability = json.loads(calvin_candidate.member_bytes("source-accountability.json"))
    assert accountability["physical_line_count"] == 69897
    assert accountability["represented_line_count"] + accountability["evidence_only_line_count"] == 69897
    assert accountability["omitted_line_count"] == accountability["duplicate_line_count"] == 0
    assert accountability["required_counts"] == {
        "argument_blocks": 65, "chapter_body_blocks": 1314, "chapters": 80, "emphasis_carriers": 578,
        "front_blocks": 89, "logical_books": 4, "physical_book_headings": 5,
        "principal_index_blocks": 203, "principal_index_lines": 467,
        "scripture_index_blocks": 838, "scripture_index_lines": 4949,
        "volume_1_anchors": 2016, "volume_1_chapters": 48, "volume_1_notes": 2016,
        "volume_2_anchors": 1489, "volume_2_chapters": 32, "volume_2_notes": 1490,
    }


def test_semantic_tei_preserves_corrected_whole_source_floor(calvin_candidate: CandidatePackage) -> None:
    root = etree.fromstring(calvin_candidate.member_bytes("content.tei.xml"))
    assert [(node.get("n"), node.get("part")) for node in root.xpath("//tei:div[@type='book']", namespaces=NS)] == [("1", "N"), ("2", "N"), ("3", "I"), ("3", "F"), ("4", "N")]
    assert len(root.xpath("//tei:div[@type='chapter']", namespaces=NS)) == 80
    assert len(root.xpath("//tei:div[@type='argument']/*[@type='book-argument']", namespaces=NS)) == 65
    assert len(root.xpath("//*[@type='chapter-body']", namespaces=NS)) == 1314
    assert len(root.xpath("//tei:ref[@type='note']", namespaces=NS)) == 3505
    assert len(root.xpath("//tei:note[@place='end']", namespaces=NS)) == 3506
    assert len(root.xpath("//tei:ref[@target='#calvin-v2-note-1473']", namespaces=NS)) == 0
    assert len(root.xpath("//*[@xml:id='calvin-v2-note-1473']", namespaces=NS)) == 1
    assert len(root.xpath("//tei:hi[@rend='underscore' and @ana='#source-emphasis']", namespaces=NS)) == 578
    assert len(root.xpath("//tei:div[@subtype='principal-matters']/*[@type='principal-matters-index-heading' or @type='principal-matters-index-entry']", namespaces=NS)) == 203
    assert len(root.xpath("//tei:div[@subtype='scripture']/*[@type='scripture-index-heading' or @type='scripture-index-entry' or @type='transcriber-note']", namespaces=NS)) == 838
    readme = calvin_candidate.member_bytes("README.source.md")
    for phrase in (b"https://www.gutenberg.org/ebooks/45001", b"https://www.gutenberg.org/ebooks/64392", b"https://www.gutenberg.org/license/", b"wrapper and full-license text are retained as evidence", b"does not claim unconditional availability"):
        assert phrase in readme


def test_scripture_index_rows_have_independent_source_line_carriers(
    calvin_candidate: CandidatePackage,
    source_model: tuple[list[list[dict[str, object]]], dict[str, object], dict[str, object]],
) -> None:
    blocks, _, _ = source_model
    expected = next(
        block
        for volume_blocks in blocks
        for block in volume_blocks
        if block["id"] == "calvin-v2-block-9551"
    )
    root = etree.fromstring(calvin_candidate.member_bytes("content.tei.xml"))
    wrapper = root.xpath("//*[@xml:id='calvin-v2-block-9551']", namespaces=NS)[0]
    assert etree.QName(wrapper).localname == "div"
    table = wrapper.xpath("./tei:table[@type='scripture-index-table']", namespaces=NS)[0]
    assert table.get("rows") == "3"
    assert table.get("cols") == "4"
    rows = table.xpath("./tei:row", namespaces=NS)
    assert [row.get("n") for row in rows] == ["38338", "38339", "38340"]
    assert [row.xpath("./tei:cell/@xml:id", namespaces=NS) for row in rows] == [
        [f"{line_id}-{column}" for column in ("chapter", "verse", "volume", "page")]
        for line_id in expected["line_ids"]
    ]
    assert [row.xpath("./tei:cell[1]/tei:lb/@xml:id", namespaces=NS) for row in rows] == [
        [line_id] for line_id in expected["line_ids"]
    ]
    column_slices = ((0, 34), (34, 40), (40, 44), (44, None))
    assert [
        ["".join(cell.itertext()) for cell in row.xpath("./tei:cell", namespaces=NS)]
        for row in rows
    ] == [
        [str(line["text"])[start:end] for start, end in column_slices]
        for line in expected["lines"]
    ]


def test_oracle_rejects_appended_worldwide_rights_certainty_in_readme(
    tmp_path: Path,
    calvin_manifest: SourceManifest,
    calvin_candidate: CandidatePackage,
) -> None:
    path = _copy(tmp_path, calvin_candidate, "readme-worldwide-rights-invention")
    invented = (
        (path / "README.source.md").read_bytes()
        + b"\nThe work is certainly public domain worldwide and publication is authorized.\n"
    )
    mutated = _reseal(path, "README.source.md", invented)
    with pytest.raises(ValueError, match="README"):
        validate(calvin_manifest, mutated, _oracle)


def test_oracle_rejects_resolved_worldwide_rights_in_unresolved_ledger(
    tmp_path: Path,
    calvin_manifest: SourceManifest,
    calvin_candidate: CandidatePackage,
) -> None:
    path = _copy(tmp_path, calvin_candidate, "resolved-worldwide-rights-invention")
    records = [
        json.loads(line)
        for line in (path / "unresolved.jsonl").read_bytes().splitlines()
        if line
    ]
    rights = next(
        item
        for item in records
        if item["id"] == "calvin-rights-jurisdiction-and-terms"
    )
    rights.update(
        status="resolved",
        detail="Worldwide public-domain status and publication authorization are certain.",
    )
    mutated = _reseal(
        path,
        "unresolved.jsonl",
        b"".join(_canonical(item) for item in records),
    )
    with pytest.raises(ValueError, match="unresolved"):
        validate(calvin_manifest, mutated, _oracle)


def test_oracle_rejects_coordinated_readme_and_unresolved_rights_invention(
    tmp_path: Path,
    calvin_manifest: SourceManifest,
    calvin_candidate: CandidatePackage,
) -> None:
    path = _copy(tmp_path, calvin_candidate, "coordinated-worldwide-rights-invention")
    records = [
        json.loads(line)
        for line in (path / "unresolved.jsonl").read_bytes().splitlines()
        if line
    ]
    rights = next(
        item
        for item in records
        if item["id"] == "calvin-rights-jurisdiction-and-terms"
    )
    rights.update(
        status="resolved",
        detail="Worldwide public-domain status and publication authorization are certain.",
    )
    mutated = _reseal(
        path,
        "unresolved.jsonl",
        b"".join(_canonical(item) for item in records),
    )
    invented_readme = (
        path / "README.source.md"
    ).read_bytes() + b"\nWorldwide public-domain status and publication authorization are certain.\n"
    mutated = _reseal(path, "README.source.md", invented_readme)
    with pytest.raises(ValueError, match="README|unresolved"):
        validate(calvin_manifest, mutated, _oracle)


def test_oracle_rejects_candidate_source_set_digest_contradiction(
    tmp_path: Path,
    calvin_manifest: SourceManifest,
    calvin_candidate: CandidatePackage,
) -> None:
    path = _copy(tmp_path, calvin_candidate, "source-set-digest-contradiction")
    invented_digest = "0" * 64
    root = etree.fromstring((path / "content.tei.xml").read_bytes())
    source_set = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='sha256']",
        namespaces=NS,
    )[0]
    source_set.text = invented_digest
    _reseal(
        path,
        "content.tei.xml",
        etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        ),
    )
    provenance = json.loads((path / "provenance.json").read_bytes())
    provenance["source_member_set_sha256"] = invented_digest
    mutated = _reseal(path, "provenance.json", _canonical(provenance))
    with pytest.raises(ValueError, match="source-set|provenance"):
        validate(calvin_manifest, mutated, _oracle)


def test_fresh_process_complete_packages_are_byte_identical(tmp_path: Path) -> None:
    script = (
        "from pathlib import Path;import hashlib,sys;"
        "from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct;"
        "from build.tei.calvins_institutes_reconstruction import _convert;"
        "r=Path(sys.argv[1]);m=SourceManifest.load(r/'tests/fixtures/reconstruction-runtime/calvins-institutes.source-manifest.json',repository_root=r);"
        "c=reconstruct(m,Path(sys.argv[2]),_convert);"
        "print('|'.join(n+':'+hashlib.sha256(c.member_bytes(n)).hexdigest() for n in c.member_names))"
    )
    outputs = []
    for ordinal in (1, 2):
        completed = subprocess.run([sys.executable, "-c", script, str(ROOT), str(tmp_path / f"fresh-{ordinal}")], cwd=ROOT, check=True, capture_output=True, text=True)
        outputs.append(completed.stdout.strip())
    assert outputs[0] == outputs[1]


def test_oracle_closure_is_recursive_repo_local_and_producer_independent(calvin_manifest: SourceManifest) -> None:
    policy = json.loads(calvin_manifest.authority_path("validation-policy").read_bytes())
    assert _closure_digest(ROOT, policy) == calvin_manifest.record["validator"]["import_closure_sha256"]
    paths = {item["path"] for item in _repository_import_closure(ROOT, Path(oracle_module.__file__), tuple(policy["forbidden_import_prefixes"]))}
    assert {"build/tei/calvins_institutes_oracle.py", "ocd_kernel/reconstruction/contract.py", "ocd_kernel/tei/validate.py"} <= paths
    source = Path(oracle_module.__file__).read_text(encoding="utf-8")
    for forbidden in policy["forbidden_import_prefixes"]:
        assert f"import {forbidden}" not in source
        assert f"from {forbidden}" not in source


def test_recursive_closure_rejects_forbidden_import_and_runtime_shadow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = tmp_path / "entry.py"
    entry.write_text("import build.tei.calvins_institutes_reconstruction\n", encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden import"):
        _repository_import_closure(tmp_path, entry, ("build.tei.calvins_institutes_reconstruction",))
    module = sys.modules["ocd_kernel.reconstruction.contract"]
    original = module.__file__
    monkeypatch.setattr(module, "__file__", str(tmp_path / "site-packages/ocd_kernel/reconstruction/contract.py"))
    with pytest.raises(ValueError, match="outside repository|shadowed"):
        _runtime_paths(ROOT)
    monkeypatch.setattr(module, "__file__", original)


class _PassingSchema:
    error_log = type("Log", (), {"last_error": None})()

    @staticmethod
    def validate(document: object) -> bool:
        return True


@pytest.mark.parametrize(
    "mutation",
    ["omitted-block", "reordered-argument", "book-swap", "volume-boundary", "heading-to-prose", "principal-index-swap", "scripture-index-row-swap", "scripture-index-cell-swap", "note-1473-drop", "crossed-note-target", "emphasis-type", "rights-conflation"],
)
def test_independent_oracle_rejects_structure_attachment_index_emphasis_and_rights_mutations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    calvin_candidate: CandidatePackage,
    source_model: tuple[list[list[dict[str, object]]], dict[str, object], dict[str, object]],
    mutation: str,
) -> None:
    monkeypatch.setattr(oracle_module, "compiled_schema", lambda: _PassingSchema())
    blocks, model, policy = source_model
    path = _copy(tmp_path, calvin_candidate, mutation)
    root = etree.fromstring((path / "content.tei.xml").read_bytes())
    source_set_sha256 = root.xpath(
        "string(./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='sha256'])",
        namespaces=NS,
    )
    if mutation == "omitted-block":
        node = root.xpath("//*[@xml:id=$value]", value=model["body_blocks"][100]["id"], namespaces=NS)[0]
        node.getparent().remove(node)
    elif mutation == "reordered-argument":
        nodes = root.xpath("//tei:div[@type='argument']/*[@type='book-argument']", namespaces=NS)[:2]
        parent = nodes[0].getparent()
        assert parent is nodes[1].getparent()
        parent.remove(nodes[1])
        parent.insert(parent.index(nodes[0]), nodes[1])
    elif mutation == "book-swap":
        first, second = root.xpath("//tei:div[@type='book']", namespaces=NS)[:2]
        first.set("n", "2")
        second.set("n", "1")
    elif mutation == "volume-boundary":
        root.xpath("//tei:milestone[@unit='physical-volume']", namespaces=NS)[1].set("n", "1")
    elif mutation == "heading-to-prose":
        node = root.xpath("//*[@type='chapter-heading']", namespaces=NS)[0]
        node.set("type", "chapter-body")
    elif mutation == "principal-index-swap":
        nodes = root.xpath("//tei:div[@subtype='principal-matters']/*[@type='principal-matters-index-entry']", namespaces=NS)[:2]
        parent = nodes[0].getparent()
        parent.remove(nodes[1])
        parent.insert(parent.index(nodes[0]), nodes[1])
    elif mutation == "scripture-index-row-swap":
        nodes = root.xpath("//*[@xml:id='calvin-v2-block-9551']/tei:table/tei:row", namespaces=NS)[:2]
        parent = nodes[0].getparent()
        parent.remove(nodes[1])
        parent.insert(parent.index(nodes[0]), nodes[1])
    elif mutation == "scripture-index-cell-swap":
        nodes = root.xpath("//*[@xml:id='calvin-v2-block-9551']/tei:table/tei:row[2]/tei:cell", namespaces=NS)[:2]
        parent = nodes[0].getparent()
        parent.remove(nodes[1])
        parent.insert(parent.index(nodes[0]), nodes[1])
    elif mutation == "note-1473-drop":
        node = root.xpath("//*[@xml:id='calvin-v2-note-1473']", namespaces=NS)[0]
        node.getparent().remove(node)
    elif mutation == "crossed-note-target":
        root.xpath("//tei:ref[@type='note']", namespaces=NS)[0].set("target", "#calvin-v1-note-0002")
    elif mutation == "emphasis-type":
        root.xpath("//tei:hi[@rend='underscore']", namespaces=NS)[0].set("rend", "italic")
    elif mutation == "rights-conflation":
        root.xpath("./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability", namespaces=NS)[0].set("status", "free")
    mutated = _reseal(path, "content.tei.xml", etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    with pytest.raises(ValueError):
        _verify_tei(mutated, blocks, model, policy, source_set_sha256)


def test_exact_inventory_digests_reject_same_count_location_swaps(source_model: tuple[list[list[dict[str, object]]], dict[str, object], dict[str, object]]) -> None:
    _, model, _ = source_model
    changed = copy.deepcopy(model["emphasis"])
    changed[0]["block_id"], changed[1]["block_id"] = changed[1]["block_id"], changed[0]["block_id"]
    assert len(changed) == 578
    assert _sha(_canonical(changed)) != _sha(_canonical(model["emphasis"]))
    pairs = copy.deepcopy(model["pairs"])
    pairs[0]["note"], pairs[1]["note"] = pairs[1]["note"], pairs[0]["note"]
    assert len(pairs) == 3506
    assert _sha(_canonical(pairs)) != _sha(_canonical(model["pairs"]))


@pytest.mark.parametrize(
    "mutation",
    [
        "volume-wrapper-identity-swap",
        "chapter-wrapper-identity-swap",
        "chapter-parent-escape",
        "note-label-swap",
        "note-parent-escape",
        "volume-milestone-position",
        "header-role-invention",
        "invented-worldwide-certainty",
    ],
)
def test_oracle_rejects_xsd_valid_same_count_identity_parent_and_rights_attacks(
    tmp_path: Path,
    calvin_candidate: CandidatePackage,
    source_model: tuple[list[list[dict[str, object]]], dict[str, object], dict[str, object]],
    mutation: str,
) -> None:
    blocks, model, policy = source_model
    path = _copy(tmp_path, calvin_candidate, f"focused-{mutation}")
    root = etree.fromstring((path / "content.tei.xml").read_bytes())
    source_set_sha256 = root.xpath(
        "string(./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='sha256'])",
        namespaces=NS,
    )
    before = {
        "volumes": len(root.xpath("./tei:text/tei:group/tei:text", namespaces=NS)),
        "books": len(root.xpath("//tei:div[@type='book']", namespaces=NS)),
        "chapters": len(root.xpath("//tei:div[@type='chapter']", namespaces=NS)),
        "notes": len(root.xpath("//tei:note[@place='end']", namespaces=NS)),
        "milestones": len(root.xpath("//tei:milestone[@unit='physical-volume']", namespaces=NS)),
    }
    if mutation == "volume-wrapper-identity-swap":
        first, second = root.xpath("./tei:text/tei:group/tei:text", namespaces=NS)
        first_id, first_n = first.get(XML_ID), first.get("n")
        first.set(XML_ID, second.get(XML_ID))
        first.set("n", second.get("n"))
        second.set(XML_ID, first_id)
        second.set("n", first_n)
    elif mutation == "chapter-wrapper-identity-swap":
        first, second = root.xpath("//tei:div[@type='chapter']", namespaces=NS)[:2]
        first_id, first_n = first.get(XML_ID), first.get("n")
        first.set(XML_ID, second.get(XML_ID))
        first.set("n", second.get("n"))
        second.set(XML_ID, first_id)
        second.set("n", first_n)
    elif mutation == "chapter-parent-escape":
        chapter = root.xpath("//tei:div[@type='book'][1]/tei:div[@type='chapter'][1]", namespaces=NS)[0]
        wrong_book = root.xpath("//tei:div[@type='book'][2]", namespaces=NS)[0]
        wrong_book.append(chapter)
    elif mutation == "note-label-swap":
        first, second = root.xpath("//tei:note[@place='end']", namespaces=NS)[:2]
        first_n = first.get("n")
        first.set("n", second.get("n"))
        second.set("n", first_n)
    elif mutation == "note-parent-escape":
        containers = root.xpath("//tei:div[@subtype='chapter-endnotes']", namespaces=NS)
        note = containers[0].xpath("./tei:note", namespaces=NS)[0]
        containers[1].append(note)
    elif mutation == "volume-milestone-position":
        milestone = root.xpath("//tei:milestone[@unit='physical-volume']", namespaces=NS)[0]
        milestone.getparent().append(milestone)
    elif mutation == "header-role-invention":
        author = root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", namespaces=NS)[0]
        translator = root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name", namespaces=NS)[0]
        author.text, translator.text = "John Allen (asserted author)", "Jean Calvin (asserted translator)"
    elif mutation == "invented-worldwide-certainty":
        paragraph = root.xpath("./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability/tei:p", namespaces=NS)[0]
        paragraph.text = "The work is certainly public domain worldwide and authorized for publication."
    after = {
        "volumes": len(root.xpath("./tei:text/tei:group/tei:text", namespaces=NS)),
        "books": len(root.xpath("//tei:div[@type='book']", namespaces=NS)),
        "chapters": len(root.xpath("//tei:div[@type='chapter']", namespaces=NS)),
        "notes": len(root.xpath("//tei:note[@place='end']", namespaces=NS)),
        "milestones": len(root.xpath("//tei:milestone[@unit='physical-volume']", namespaces=NS)),
    }
    assert after == before
    assert oracle_module.compiled_schema().validate(etree.ElementTree(root))
    mutated = _reseal(path, "content.tei.xml", etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    with pytest.raises(ValueError):
        _verify_tei(mutated, blocks, model, policy, source_set_sha256)
