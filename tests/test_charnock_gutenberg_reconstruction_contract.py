from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest
from lxml import etree

from build.tei.charnock_gutenberg_oracle import _oracle
from build.tei.charnock_gutenberg_reconstruction import _convert
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)
from ocd_kernel.tei.validate import compiled_schema


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tests/fixtures/reconstruction-runtime"
SOURCE_SHA = "7edb772fb0147fe69e884b4b7f1feb71d96525f86e5be8c9a8e3eefa33626888"
WORKS = {
    "charnock-existence-attributes-vol-1": (33, 30307),
    "charnock-existence-attributes-vol-2": (30308, 56434),
}
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _runtime_manifest_path(work_id: str) -> Path:
    return RUNTIME / f"{work_id}.source-manifest.json"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _reseal_member(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


@pytest.mark.parametrize("work_id", sorted(WORKS))
def test_catalog_source_manifest_binds_exact_volume_config(work_id: str) -> None:
    from build.tools.count_dataset_records import _manifest_config_ids

    manifest_path = (
        ROOT
        / "sources"
        / "structured-text"
        / work_id
        / f"{work_id}.source-manifest.json"
    )
    manifest = json.loads(manifest_path.read_bytes())
    config_authorities = [
        item
        for item in manifest["authorities"]
        if item["path"] == f"sources/structured-text/{work_id}/config.json"
    ]
    assert len(config_authorities) == 1
    authority = config_authorities[0]
    assert authority["name"] == "source-config"
    assert authority["role"] == "source-identity-and-rights-config"
    config_path = ROOT / str(authority["path"])
    config = json.loads(config_path.read_bytes())
    assert config["resource_id"] == work_id
    assert authority["bytes"] == config_path.stat().st_size
    assert authority["sha256"] == _sha(config_path.read_bytes())
    assert _manifest_config_ids(manifest, ROOT) == {work_id}


@pytest.fixture(scope="module")
def charnock_v1_candidate(tmp_path_factory: pytest.TempPathFactory) -> CandidatePackage:
    work_id = "charnock-existence-attributes-vol-1"
    manifest = SourceManifest.load(
        _runtime_manifest_path(work_id),
        repository_root=ROOT,
    )
    return reconstruct(manifest, tmp_path_factory.mktemp("charnock-v1"), _convert)


def _copy_candidate(
    tmp_path: Path, candidate: CandidatePackage, label: str
) -> CandidatePackage:
    destination = tmp_path / label
    shutil.copytree(candidate.path, destination)
    return CandidatePackage.load(destination)


@pytest.mark.parametrize("work_id,body_range", WORKS.items())
def test_exact_shared_witness_partition_reconstructs_and_validates(
    tmp_path: Path, work_id: str, body_range: tuple[int, int]
) -> None:
    manifest_path = _runtime_manifest_path(work_id)
    manifest = SourceManifest.load(manifest_path, repository_root=ROOT)
    source = manifest.authority_path("retained-source").read_bytes()
    assert (len(source), len(source.splitlines()), _sha(source)) == (
        3949934,
        62798,
        SOURCE_SHA,
    )
    candidate = reconstruct(manifest, tmp_path / work_id, _convert)
    report = validate(manifest, candidate, _oracle)
    assert report.status == "pass"
    assert candidate.manifest["status"] == "nonaccepted"
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["work_id"] == work_id
    assert accountability["body_line_range"] == list(body_range)
    assert accountability["shared_apparatus_line_range"] == [56435, 62447]
    assert accountability["physical_line_count"] == 62798
    assert (
        accountability["represented_line_count"]
        + accountability["evidence_only_line_count"]
        == 62798
    )
    assert (
        accountability["omitted_line_count"]
        == accountability["duplicate_line_count"]
        == 0
    )
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert root.xpath("string(//tei:idno[@type='work-id'])", namespaces=NS) == work_id
    assert root.xpath("string(//tei:idno[@type='sha256'])", namespaces=NS) == SOURCE_SHA
    assert len(root.xpath("//tei:div[@type='shared-apparatus']", namespaces=NS)) == 1
    assert b"publication:not_ready" in candidate.member_bytes("README.source.md")


def test_distinct_work_routes_do_not_cross_label_volume_bodies(tmp_path: Path) -> None:
    bodies: dict[str, list[int]] = {}
    for work_id in WORKS:
        manifest = SourceManifest.load(
            _runtime_manifest_path(work_id),
            repository_root=ROOT,
        )
        candidate = reconstruct(manifest, tmp_path / work_id, _convert)
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
        bodies[work_id] = [
            int(json.loads(node.text)["line"])
            for node in root.xpath(
                "//tei:div[@type='volume-body']/tei:div[@type='complete-xml-node-transcription']/tei:ab",
                namespaces=NS,
            )
        ]
    assert bodies["charnock-existence-attributes-vol-1"] == list(range(33, 30308))
    assert bodies["charnock-existence-attributes-vol-2"] == list(range(30308, 56435))
    assert set(bodies["charnock-existence-attributes-vol-1"]).isdisjoint(
        bodies["charnock-existence-attributes-vol-2"]
    )


@pytest.mark.parametrize(
    "mutation",
    ["omission", "reordering", "invention", "cross-volume", "metadata", "rights"],
)
def test_oracle_rejects_fidelity_identity_and_rights_mutations(
    tmp_path: Path, charnock_v1_candidate: CandidatePackage, mutation: str
) -> None:
    work_id = "charnock-existence-attributes-vol-1"
    manifest = SourceManifest.load(
        _runtime_manifest_path(work_id),
        repository_root=ROOT,
    )
    candidate = _copy_candidate(tmp_path, charnock_v1_candidate, mutation)
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    nodes = root.xpath(
        "//tei:div[@type='volume-body']/tei:div[@type='complete-xml-node-transcription']/tei:ab",
        namespaces=NS,
    )
    if mutation == "omission":
        nodes[99].getparent().remove(nodes[99])
    elif mutation == "reordering":
        parent = nodes[99].getparent()
        parent.remove(nodes[100])
        parent.insert(parent.index(nodes[99]), nodes[100])
    elif mutation == "invention":
        nodes[99].text = (nodes[99].text or "") + " invented"
    elif mutation == "cross-volume":
        nodes[99].set("n", "40000")
    elif mutation == "metadata":
        root.xpath("//tei:author", namespaces=NS)[0].text = "Invented Author"
    elif mutation == "rights":
        root.xpath("//tei:publicationStmt/tei:p", namespaces=NS)[
            0
        ].text = "Worldwide publication is authorized."
    mutated = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with pytest.raises(ValueError, match="line|TEI|identity"):
        validate(
            manifest,
            _reseal_member(candidate.path, "content.tei.xml", mutated),
            _oracle,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "native-paragraph-flattening",
        "discourse-wrong-parent",
        "note-attachment-swap",
        "page-marker-location",
        "italic-rendition-removal",
    ],
)
def test_oracle_rejects_native_structure_and_attachment_mutations(
    tmp_path: Path, charnock_v1_candidate: CandidatePackage, mutation: str
) -> None:
    """Meaningful native mutations must fail after candidate resealing.

    These mutations retain the exact source-line ledger and visible wording;
    the independent native projection checks must therefore enforce paragraph
    shape, discourse ownership, footnote attachment, and exact page anchors.
    """

    work_id = "charnock-existence-attributes-vol-1"
    manifest = SourceManifest.load(
        _runtime_manifest_path(work_id),
        repository_root=ROOT,
    )
    candidate = _copy_candidate(tmp_path, charnock_v1_candidate, mutation)
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    if mutation == "native-paragraph-flattening":
        paragraph = root.xpath(
            "//tei:div[@type='discourse'][1]/tei:p[1]", namespaces=NS
        )[0]
        paragraph.tag = f"{{{NS['tei']}}}ab"
    elif mutation == "discourse-wrong-parent":
        discourses = root.xpath(
            "//tei:div[@type='readable-transcription'][1]/tei:div[@type='discourse']",
            namespaces=NS,
        )
        moved = discourses[0].xpath("./tei:p[1]", namespaces=NS)[0]
        discourses[0].remove(moved)
        discourses[1].append(moved)
    elif mutation == "note-attachment-swap":
        notes = root.xpath(
            "//tei:div[@type='footnotes']/tei:note[@xml:id='charnock-shared-v1-note-6'] | "
            "//tei:div[@type='footnotes']/tei:note[@xml:id='charnock-shared-v1-note-7']",
            namespaces=NS,
        )
        assert [node.get("n") for node in notes] == ["6", "7"]
        first, second = notes
        first_text, second_text = first.text, second.text
        first.text, second.text = second_text, first_text
        first_children, second_children = list(first), list(second)
        for child in first_children:
            first.remove(child)
        for child in second_children:
            second.remove(child)
        for child in second_children:
            first.append(child)
        for child in first_children:
            second.append(child)
    elif mutation == "page-marker-location":
        marker = root.xpath(
            "//tei:div[@type='readable-transcription'][1]//tei:milestone[@unit='page' and @n='a23'][1]",
            namespaces=NS,
        )[0]
        assert marker.get("n") == "a23"
        marker.set("n", "a24")
    else:
        italic = root.xpath(
            "//tei:div[@type='readable-transcription'][1]//tei:hi[@rend='italic'][1]",
            namespaces=NS,
        )[0]
        assert italic.get("rend") == "italic"
        italic.attrib.pop("rend")
    mutated = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with pytest.raises(ValueError, match="Charnock|TEI|native|footnote|page"):
        validate(
            manifest,
            _reseal_member(candidate.path, "content.tei.xml", mutated),
            _oracle,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "manifest-source-id",
        "manifest-package-schema",
        "manifest-noncanonical",
        "tei-xml-id",
        "tei-title",
        "tei-gutenberg-id",
        "tei-shared-heading",
        "accountability-reason",
        "accountability-selector",
        "accountability-source-sha",
        "provenance-contract",
        "unresolved-detail",
    ],
)
def test_oracle_rejects_resealed_identity_accounting_and_evidence_bypasses(
    tmp_path: Path, charnock_v1_candidate: CandidatePackage, mutation: str
) -> None:
    work_id = "charnock-existence-attributes-vol-1"
    manifest = SourceManifest.load(
        _runtime_manifest_path(work_id),
        repository_root=ROOT,
    )
    candidate = _copy_candidate(tmp_path, charnock_v1_candidate, mutation)
    if mutation.startswith("manifest-"):
        record = json.loads(candidate.member_bytes("manifest.json"))
        if mutation == "manifest-source-id":
            record["source_id"] = "invented-source-id"
            content = _canonical(record)
        elif mutation == "manifest-package-schema":
            record["package_schema"]["sha256"] = "0" * 64
            content = _canonical(record)
        else:
            content = (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode(
                "utf-8"
            )
        (candidate.path / "manifest.json").write_bytes(content)
        mutated = CandidatePackage.load(candidate.path)
    elif mutation.startswith("tei-"):
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
        if mutation == "tei-xml-id":
            root.xpath(
                "//tei:div[@type='volume-body']/tei:div[@type='complete-xml-node-transcription']/tei:ab",
                namespaces=NS,
            )[0].set(
                "{http://www.w3.org/XML/1998/namespace}id", "invented-id"
            )
        elif mutation == "tei-title":
            root.xpath("//tei:titleStmt/tei:title", namespaces=NS)[
                0
            ].text = "Invented Title"
        elif mutation == "tei-gutenberg-id":
            root.xpath("//tei:idno[@type='gutenberg']", namespaces=NS)[0].text = "99999"
        else:
            root.xpath("//tei:div[@type='shared-apparatus']/tei:head", namespaces=NS)[
                0
            ].text = "Invented shared heading"
        content = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
        mutated = _reseal_member(candidate.path, "content.tei.xml", content)
    elif mutation.startswith("accountability-"):
        record = json.loads(candidate.member_bytes("source-accountability.json"))
        if mutation == "accountability-reason":
            record["lines"][0]["reason"] = "invented reason"
        elif mutation == "accountability-selector":
            represented = next(
                item for item in record["lines"] if item["disposition"] == "represented"
            )
            represented["tei_selector"] = "#invented-selector"
        else:
            record["source_member"]["sha256"] = "0" * 64
        mutated = _reseal_member(
            candidate.path, "source-accountability.json", _canonical(record)
        )
    elif mutation == "provenance-contract":
        record = json.loads(candidate.member_bytes("provenance.json"))
        record["contract"] = "invented-contract"
        mutated = _reseal_member(candidate.path, "provenance.json", _canonical(record))
    else:
        records = [
            json.loads(line)
            for line in candidate.member_bytes("unresolved.jsonl").splitlines()
            if line
        ]
        records[0]["detail"] = "invented unresolved detail"
        mutated = _reseal_member(
            candidate.path,
            "unresolved.jsonl",
            b"".join(_canonical(item) for item in records),
        )
    with pytest.raises(ValueError):
        validate(manifest, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    [
        "accountability-contract",
        "accountability-extra",
        "accountability-line-extra",
        "provenance-runtime",
        "provenance-negative-shared",
        "provenance-extra",
        "unresolved-blank-line",
        "unresolved-whitespace",
        "unresolved-no-final-newline",
        "manifest-extra",
        "manifest-member-order",
        "tei-volume-n",
        "tei-ab-type",
        "tei-xml-space",
        "tei-root-lang",
        "tei-extra-idno",
        "tei-extra-author",
        "tei-extra-div",
        "tei-extra-title",
        "tei-ab-tail",
    ],
)
def test_oracle_rejects_adjacent_closed_shape_bypasses(
    tmp_path: Path, charnock_v1_candidate: CandidatePackage, mutation: str
) -> None:
    work_id = "charnock-existence-attributes-vol-1"
    manifest = SourceManifest.load(
        _runtime_manifest_path(work_id),
        repository_root=ROOT,
    )
    candidate = _copy_candidate(tmp_path, charnock_v1_candidate, mutation)
    if mutation.startswith("manifest-"):
        record = json.loads(candidate.member_bytes("manifest.json"))
        if mutation == "manifest-extra":
            record["extra"] = True
        else:
            record["members"][0], record["members"][1] = (
                record["members"][1],
                record["members"][0],
            )
        (candidate.path / "manifest.json").write_bytes(_canonical(record))
        mutated = CandidatePackage.load(candidate.path)
    elif mutation.startswith("accountability-"):
        record = json.loads(candidate.member_bytes("source-accountability.json"))
        if mutation == "accountability-contract":
            record["contract"] = "invented-contract"
        elif mutation == "accountability-extra":
            record["extra"] = True
        else:
            record["lines"][0]["extra"] = True
        mutated = _reseal_member(
            candidate.path, "source-accountability.json", _canonical(record)
        )
    elif mutation.startswith("provenance-"):
        record = json.loads(candidate.member_bytes("provenance.json"))
        if mutation == "provenance-runtime":
            record["runtime"] = "invented runtime"
        elif mutation == "provenance-negative-shared":
            record["shared_apparatus_disposition"] = (
                "This apparatus is not explicitly shared."
            )
        else:
            record["extra"] = True
        mutated = _reseal_member(candidate.path, "provenance.json", _canonical(record))
    elif mutation.startswith("unresolved-"):
        content = candidate.member_bytes("unresolved.jsonl")
        if mutation == "unresolved-blank-line":
            content = b"\n" + content
        elif mutation == "unresolved-whitespace":
            content = content.replace(b"{", b"{ ", 1)
        else:
            content = content.removesuffix(b"\n")
        mutated = _reseal_member(candidate.path, "unresolved.jsonl", content)
    else:
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
        body_div = root.xpath("//tei:div[@type='volume-body']", namespaces=NS)[0]
        first_ab = body_div.xpath(
            "./tei:div[@type='complete-xml-node-transcription']/tei:ab",
            namespaces=NS,
        )[0]
        if mutation == "tei-volume-n":
            body_div.set("n", "2")
        elif mutation == "tei-ab-type":
            first_ab.set("type", "invented-type")
        elif mutation == "tei-xml-space":
            first_ab.set("{http://www.w3.org/XML/1998/namespace}space", "default")
        elif mutation == "tei-root-lang":
            root.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
        elif mutation == "tei-extra-idno":
            bibl = root.xpath("//tei:sourceDesc/tei:bibl", namespaces=NS)[0]
            etree.SubElement(
                bibl, "{http://www.tei-c.org/ns/1.0}idno", type="extra"
            ).text = "invented"
        elif mutation == "tei-extra-author":
            title_stmt = root.xpath("//tei:titleStmt", namespaces=NS)[0]
            etree.SubElement(
                title_stmt, "{http://www.tei-c.org/ns/1.0}author"
            ).text = "Invented Author"
        elif mutation == "tei-extra-div":
            body = root.xpath("//tei:text/tei:body", namespaces=NS)[0]
            extra = etree.SubElement(
                body, "{http://www.tei-c.org/ns/1.0}div", type="extra"
            )
            etree.SubElement(
                extra, "{http://www.tei-c.org/ns/1.0}p"
            ).text = "Invented division"
        elif mutation == "tei-extra-title":
            etree.SubElement(
                root, "{http://www.tei-c.org/ns/1.0}title"
            ).text = "Invented title"
        else:
            first_ab.tail = "invented tail"
        content = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
        if mutation in {"tei-extra-title", "tei-ab-tail"}:
            assert not compiled_schema().validate(etree.ElementTree(root))
        mutated = _reseal_member(candidate.path, "content.tei.xml", content)
    with pytest.raises(ValueError):
        validate(manifest, mutated, _oracle)
