from __future__ import annotations

from collections.abc import Iterator
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.lib.pytest_candidate_clone import (
    candidate_package_fingerprint,
    clone_candidate_package,
)
from build.tei.npnf_ambrose_oracle import _closure_digest, _closure_paths, _oracle
from build.tei.npnf_ambrose_reconstruction import ASSIGNED, _convert
from build.tools.count_dataset_records import collect_work_catalog
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)
from ocd_kernel.reconstruction.decision import load_verified_review


pytestmark = [
    pytest.mark.slow,
    pytest.mark.xdist_group(name="npnf-ambrose-reconstruction"),
]


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "raw/ccel/npnf2/npnf210.xml"
RETAINED_MANIFEST = (
    ROOT
    / "sources/structured-text/ambrose-npnf210"
    / "npnf-ambrose.source-manifest.json"
)
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/npnf-ambrose.source-manifest.json"
SOURCE_SHA256 = "c6f1a9d66653852d8b743c84a613c72c521dfb1b05602f0a2eff400c17665ee8"
EXPECTED_COUNTS = {
    "div1": 1,
    "div2": 23,
    "div3": 51,
    "div4": 296,
    "h1": 2,
    "h2": 14,
    "h3": 69,
    "h4": 296,
    "hr": 18,
    "i": 902,
    "note": 3782,
    "p": 7251,
    "pb": 463,
    "scripRef": 3307,
    "span": 646,
    "sup": 1,
}
TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = {"tei": TEI_NS}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
EXPECTED_CLOSURE = (
    "build/__init__.py",
    "build/tei/__init__.py",
    "build/tei/npnf_ambrose_oracle.py",
    "ocd_kernel/__init__.py",
    "ocd_kernel/lib/__init__.py",
    "ocd_kernel/lib/path_io.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/reconstruction/__init__.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/tei/__init__.py",
    "ocd_kernel/tei/normalization.py",
    "ocd_kernel/tei/projection_profile.py",
    "ocd_kernel/tei/validate.py",
)
SOURCE_ID = "ccel-npnf210-ambrose-retained-xml"
GOVERNED_LF_PATHS = (
    "sources/structured-text/ambrose-npnf210/npnf-ambrose.source-manifest.json",
    "sources/structured-text/ambrose-npnf210/README.md",
    "sources/structured-text/ambrose-npnf210/npnf-ambrose.reconstruction-profile.json",
    "sources/structured-text/ambrose-npnf210/npnf-ambrose.validation-policy.json",
    "sources/structured-text/ambrose-npnf210/npnf-ambrose.source-accountability.schema.json",
    "build/tei/npnf_ambrose_reconstruction.py",
    "build/tei/npnf_ambrose_oracle.py",
)
GOVERNED_CRLF_PATHS = (
    "sources/structured-text/ambrose-of-milan-concerning-repentance/config.json",
    "sources/structured-text/ambrose-of-milan-concerning-virgins/config.json",
    "sources/structured-text/ambrose-of-milan-concerning-widows/config.json",
    "sources/structured-text/ambrose-of-milan-exposition-of-christian-faith/config.json",
    "sources/structured-text/ambrose-of-milan-letters/config.json",
    "sources/structured-text/ambrose-of-milan-on-duties-of-clergy/config.json",
    "sources/structured-text/ambrose-of-milan-on-holy-spirit/config.json",
    "sources/structured-text/ambrose-of-milan-on-mysteries/config.json",
    "sources/structured-text/ambrose-of-milan-on-satyrus/config.json",
    "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
)


EXACT_BYTE_CONFIG_PATHS = frozenset(GOVERNED_CRLF_PATHS[:-1])


def _assert_effective_checkout_eol(relative: str, expected: str) -> None:
    relative_bytes = relative.encode("utf-8")
    output = subprocess.run(
        ["git", "check-attr", "-z", "text", "eol", "--", relative],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert output.split(b"\0") == [
        relative_bytes,
        b"text",
        b"unset" if relative in EXACT_BYTE_CONFIG_PATHS else b"set",
        relative_bytes,
        b"eol",
        b"unspecified" if relative in EXACT_BYTE_CONFIG_PATHS else expected.encode("ascii"),
        b"",
    ]


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def test_runtime_fixture_preserves_retained_authorities_and_only_updates_storage_closure() -> None:
    raw = RETAINED_MANIFEST.read_bytes()
    assert _sha(raw) == "aa813a1d02f13b7a706c08010bf5d779728998d2dec7fe4568159c8c792ade09"
    expected = json.loads(raw)
    policy_path = next(item["path"] for item in expected["authorities"]
                       if item["name"] == "validation-policy")
    policy = json.loads((ROOT / policy_path).read_bytes())
    expected["validator"]["import_closure_sha256"] = _closure_digest(ROOT, policy)
    assert json.loads(MANIFEST.read_bytes()) == expected


def test_manifest_bound_text_materializes_portably() -> None:
    manifest = json.loads(MANIFEST.read_bytes())
    authority_bindings = {
        item["path"]: (item["bytes"], item["sha256"])
        for item in manifest["authorities"]
    }
    implementation_bindings = {
        manifest["converter"]["implementation_path"]: manifest["converter"][
            "implementation_sha256"
        ],
        manifest["validator"]["implementation_path"]: manifest["validator"][
            "implementation_sha256"
        ],
    }

    for relative in GOVERNED_LF_PATHS:
        _assert_effective_checkout_eol(relative, "lf")
        payload = (ROOT / relative).read_bytes()
        assert b"\r\n" not in payload
        if relative in authority_bindings:
            expected_bytes, expected_sha256 = authority_bindings[relative]
            assert len(payload) == expected_bytes
            assert _sha(payload) == expected_sha256
        if relative in implementation_bindings:
            assert _sha(payload) == implementation_bindings[relative]

    for relative in GOVERNED_CRLF_PATHS:
        _assert_effective_checkout_eol(relative, "crlf")
        payload = (ROOT / relative).read_bytes()
        if relative.startswith("sources/structured-text/ambrose-of-milan-"):
            # Exact-byte config authorities use -text; eol does not transform
            # them. Check both checkout modes against the bound live bytes.
            for autocrlf in ("true", "false"):
                materialized = subprocess.run(
                    ["git", "-c", f"core.autocrlf={autocrlf}", "cat-file",
                     "--filters", f"HEAD:{relative}"],
                    cwd=ROOT, check=True, capture_output=True,
                ).stdout
                assert materialized == payload
        else:
            assert b"\r\n" in payload
            assert b"\n" not in payload.replace(b"\r\n", b"")
        if relative in authority_bindings:
            expected_bytes, expected_sha256 = authority_bindings[relative]
            assert len(payload) == expected_bytes
            assert _sha(payload) == expected_sha256


def _reseal(path: Path, member_name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (path / member_name).read_bytes()
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _write_tree(path: Path, tree: etree._ElementTree) -> None:
    path.write_bytes(
        etree.tostring(
            tree,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
    )


def _clone_for_mutation(
    candidate: CandidatePackage,
    target: Path,
    *,
    mutable_members: tuple[str, ...],
) -> Path:
    package_members = set(candidate.member_names)
    mutable = set(mutable_members)
    if not mutable or not mutable <= package_members:
        raise AssertionError(f"invalid mutable candidate members: {sorted(mutable)}")
    clone_candidate_package(
        candidate.path,
        target,
        hardlink_members=tuple(sorted(package_members - mutable)),
    )
    for member in mutable:
        assert not (candidate.path / member).samefile(target / member)
    return target


@pytest.fixture(scope="module")
def verified_candidate(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[SourceManifest, CandidatePackage]]:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(
        source,
        tmp_path_factory.mktemp("npnf_ambrose-candidate") / "candidate",
        _convert,
    )
    report = validate(source, candidate, _oracle)
    assert report.status == "pass"
    baseline = candidate_package_fingerprint(candidate.path)
    yield source, candidate
    assert candidate_package_fingerprint(candidate.path) == baseline


@pytest.fixture(scope="module")
def verified_review_evidence(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
) -> tuple[SourceManifest, CandidatePackage, Path]:
    source, candidate = verified_candidate
    validation = validate(source, candidate, _oracle)
    record = {
        "contract": "ocd-validation-report-v1",
        "status": validation.status,
        "candidate_sha256": validation.candidate_sha256,
        "source_manifest_sha256": validation.source_manifest_sha256,
        "attestation": dict(validation.attestation),
        "findings": list(validation.findings),
    }
    assert hashlib.sha256(_canonical(record)).hexdigest() == validation.sha256
    validation_path = candidate.path.parent / "validation.json"
    validation_path.write_bytes(
        _canonical({**record, "report_sha256": validation.sha256})
    )
    return source, candidate, validation_path


@pytest.fixture(scope="module")
def runtime_catalog_discovery():
    from build.tools import count_dataset_records

    selection = MANIFEST.relative_to(ROOT).as_posix()
    original_rglob = Path.rglob

    def selected_paths(sources_root, selections):
        assert sources_root == ROOT / "sources"
        assert tuple(selections) == (selection,)
        return sources_root, None

    def selected_discovery(path, pattern):
        if path == ROOT / "sources" and pattern in {"*.source-manifest.json", "source-manifest.json"}:
            return iter((MANIFEST,))
        return original_rglob(path, pattern)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(count_dataset_records, "_resolve_source_manifest_allowlist", selected_paths)
        patch.setattr(Path, "rglob", selected_discovery)
        yield


@pytest.fixture(scope="module")
def catalog_with_evidence(
    verified_review_evidence: tuple[SourceManifest, CandidatePackage, Path],
    runtime_catalog_discovery,
):
    _, candidate, validation_path = verified_review_evidence
    evidence = {
        (SOURCE_ID, work_id): (candidate.path, validation_path)
        for _, work_id in ASSIGNED
    }
    return (
        collect_work_catalog(
            ROOT / "data",
            reconstruction_evidence=evidence,
            source_manifest_allowlist=[MANIFEST.relative_to(ROOT).as_posix()],
            data_resource_allowlist=[
                f"data/structured-text/{work_id}.json" for _, work_id in ASSIGNED
            ],
        ),
        candidate,
        validation_path,
    )


def test_retained_npnf210_authority_and_nine_work_scope_are_exact() -> None:
    content = SOURCE.read_bytes()
    tree = etree.fromstring(
        content,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )
    selected = [tree.xpath(f"//*[@id='{scope}']")[0] for scope, _ in ASSIGNED]
    features = [node for division in selected for node in division.iter()]
    observed_counts = {
        tag: sum(node.tag == tag for node in features) for tag in EXPECTED_COUNTS
    }

    assert len(content) == 3_837_030
    assert _sha(content) == SOURCE_SHA256
    assert [node.get("id") for node in selected] == [scope for scope, _ in ASSIGNED]
    assert len(features) == 17_122
    assert sum(len(node.attrib) for node in features) == 44_159
    assert sum(node.text is not None for node in features) == 12_757
    assert sum(node.tail is not None for node in features) == 12_555
    assert (
        sum(len((node.text or "") + (node.tail or "")) for node in features)
        == 2_206_439
    )
    assert observed_counts == EXPECTED_COUNTS
    assert not any(
        isinstance(node, (etree._Comment, etree._ProcessingInstruction))
        for node in features
    )


def test_candidate_is_complete_nonaccepted_and_preserves_credit_uncertainty(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
) -> None:
    _, candidate = verified_candidate
    assert candidate.member_names == (
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    )
    assert candidate.manifest["status"] == "nonaccepted"
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["assigned_work_count"] == 9
    assert accountability["feature_count"] == 17_122
    assert accountability["omitted_feature_count"] == 0
    assert len(accountability["top_level_division_accounting"]) == 6
    assert len(accountability["direct_div2_accounting"]) == 32
    assert len(accountability["crosswalk"]) == 17_122
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert all(work["human_review"] == "required" for work in provenance["works"])
    assert all(work["accepted_ir"] == "not_accepted" for work in provenance["works"])
    assert all(work["publication"] == "not_ready" for work in provenance["works"])
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").decode().splitlines()
    ]
    assert len(unresolved) == 3
    assert {row["id"] for row in unresolved} == {
        "npnf-ambrose-work-specific-translator-allocation",
        "npnf-ambrose-edition-witness-and-print-collation",
        "npnf-ambrose-rights-human-acceptance-and-publication",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "reorder",
        "invention",
        "root-attribute",
        "root-id",
        "text-attribute",
        "body-text",
        "direct-text",
        "tail-text",
        "reference-attribute",
        "page-break-attribute",
        "note-attribute",
        "heading-type",
        "milestone-unit",
        "header-title",
        "header-author",
        "header-rights",
        "header-source",
        "invented-front",
        "invented-back",
        "invented-group",
        "invented-standOff",
        "nested-namespace",
        "comment",
        "processing-instruction",
    ],
)
def test_independent_oracle_rejects_resealed_tei_structure_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate = verified_candidate
    target = tmp_path / mutation
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=("content.tei.xml", "manifest.json"),
    )
    xml_path = target / "content.tei.xml"
    tree = etree.parse(str(xml_path), etree.XMLParser(remove_comments=False))
    root = tree.getroot()
    text = root.find(f"{{{TEI_NS}}}text")
    assert text is not None
    body = text.find(f"{{{TEI_NS}}}body")
    assert body is not None
    if mutation == "omission":
        node = body.xpath(".//tei:p", namespaces=TEI)[0]
        node.getparent().remove(node)
    elif mutation == "duplication":
        node = body.xpath(".//tei:p", namespaces=TEI)[0]
        duplicate = etree.fromstring(etree.tostring(node))
        for ordinal, descendant in enumerate(duplicate.iter(), start=1):
            if descendant.get(XML_ID):
                descendant.set(XML_ID, f"npnf_ambrose-invented-{ordinal}")
        node.getparent().append(duplicate)
    elif mutation == "reorder":
        first, second = list(body)[:2]
        body.remove(second)
        body.insert(0, second)
        assert list(body)[1] is first
    elif mutation == "invention":
        invented = etree.SubElement(body, f"{{{TEI_NS}}}div")
        invented.set(XML_ID, "npnf_ambrose-invented")
    elif mutation == "root-attribute":
        root.set("type", "invented")
    elif mutation == "root-id":
        root.set(XML_ID, "npnf-ambrose-invented-root")
    elif mutation == "text-attribute":
        text.set("type", "invented")
    elif mutation == "body-text":
        body.text = "invented direct text"
    elif mutation == "direct-text":
        node = body.xpath(".//tei:p[normalize-space(text())]", namespaces=TEI)[0]
        node.text = (node.text or "") + " invented"
    elif mutation == "tail-text":
        node = body.xpath(
            ".//tei:hi[string-length(following-sibling::text()[1]) > 0]", namespaces=TEI
        )[0]
        node.tail = (node.tail or "") + " invented"
    elif mutation == "reference-attribute":
        node = body.xpath(".//tei:ref[@cRef]", namespaces=TEI)[0]
        node.set("cRef", "invented")
    elif mutation == "page-break-attribute":
        node = body.xpath(".//tei:pb[@facs]", namespaces=TEI)[0]
        node.set("facs", "#invented")
    elif mutation == "note-attribute":
        node = body.xpath(".//tei:note[@place]", namespaces=TEI)[0]
        node.set("place", "margin")
    elif mutation == "heading-type":
        node = body.xpath(".//tei:ab[starts-with(@type, 'source-h')]", namespaces=TEI)[
            0
        ]
        node.set("type", "source-h9")
    elif mutation == "milestone-unit":
        node = body.xpath(".//tei:milestone", namespaces=TEI)[0]
        node.set("unit", "invented")
    elif mutation == "header-title":
        root.xpath("./tei:teiHeader//tei:title", namespaces=TEI)[0].text = "Invented"
    elif mutation == "header-author":
        root.xpath("./tei:teiHeader//tei:author", namespaces=TEI)[0].text = "Invented"
    elif mutation == "header-rights":
        root.xpath("./tei:teiHeader//tei:availability/tei:p", namespaces=TEI)[
            0
        ].text = "Ready"
    elif mutation == "header-source":
        root.xpath("./tei:teiHeader//tei:ptr", namespaces=TEI)[0].set(
            "target", "https://example.invalid"
        )
    elif mutation in {"invented-front", "invented-back", "invented-group"}:
        local = mutation.removeprefix("invented-")
        etree.SubElement(text, f"{{{TEI_NS}}}{local}")
    elif mutation == "invented-standOff":
        etree.SubElement(root, f"{{{TEI_NS}}}standOff")
    elif mutation == "nested-namespace":
        node = body.xpath(".//tei:p", namespaces=TEI)[0]
        node.append(
            etree.Element("{urn:invented}invented", nsmap={"x": "urn:invented"})
        )
    elif mutation == "comment":
        body.append(etree.Comment("invented"))
    else:
        body.append(etree.ProcessingInstruction("invented", "value"))
    _write_tree(xml_path, tree)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError):
        _oracle(source, mutated)


@pytest.mark.parametrize(
    ("mutation", "replacement"),
    [
        ("declaration", b'<?xml version="1.0" encoding="UTF-8"?>'),
        (
            "standalone",
            b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>",
        ),
        (
            "standalone-no",
            b"<?xml version='1.0' encoding='UTF-8' standalone='no'?>",
        ),
        ("utf8-alias", b"<?xml version='1.0' encoding='UTF8'?>"),
        ("encoding-case", b"<?xml version='1.0' encoding='utf-8'?>"),
        (
            "doctype",
            b"<?xml version='1.0' encoding='UTF-8'?>\n<!DOCTYPE TEI>",
        ),
        (
            "leading-pi",
            b"<?xml version='1.0' encoding='UTF-8'?>\n<?invented value?>",
        ),
        (
            "leading-comment",
            b"<?xml version='1.0' encoding='UTF-8'?>\n<!--invented-->",
        ),
    ],
)
def test_independent_oracle_rejects_resealed_document_shell_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
    tmp_path: Path,
    mutation: str,
    replacement: bytes,
) -> None:
    source, candidate = verified_candidate
    target = tmp_path / mutation
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=("content.tei.xml", "manifest.json"),
    )
    xml_path = target / "content.tei.xml"
    content = xml_path.read_bytes()
    declaration, rest = content.split(b"\n", 1)
    assert declaration == b"<?xml version='1.0' encoding='UTF-8'?>"
    xml_path.write_bytes(replacement + b"\n" + rest)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="prolog|well-formed|sibling"):
        _oracle(source, mutated)


@pytest.mark.parametrize("suffix", [b"<!--invented-->", b"<?invented value?>"])
def test_independent_oracle_rejects_resealed_post_root_nodes(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
    tmp_path: Path,
    suffix: bytes,
) -> None:
    source, candidate = verified_candidate
    target = tmp_path / ("post-comment" if suffix.startswith(b"<!--") else "post-pi")
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=("content.tei.xml", "manifest.json"),
    )
    xml_path = target / "content.tei.xml"
    xml_path.write_bytes(xml_path.read_bytes() + suffix)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="sibling"):
        _oracle(source, mutated)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("blank-line-before-root", "TEI document prolog/root boundary drift"),
        ("two-spaces-before-root", "TEI document prolog/root boundary drift"),
        ("extra-final-newline", "TEI document terminal root boundary drift"),
        ("trailing-space-after-root", "TEI document terminal root boundary drift"),
        (
            "redundant-descendant-default-namespace",
            "TEI namespace declaration drift",
        ),
    ],
)
def test_independent_oracle_rejects_resealed_lexical_shell_and_namespace_drift(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
    tmp_path: Path,
    mutation: str,
    expected_error: str,
) -> None:
    source, candidate = verified_candidate
    target = tmp_path / mutation
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=("content.tei.xml", "manifest.json"),
    )
    xml_path = target / "content.tei.xml"
    content = xml_path.read_bytes()
    declaration = b"<?xml version='1.0' encoding='UTF-8'?>\n"
    assert content.startswith(declaration + b"<TEI ")
    assert content.endswith(b"</TEI>")

    if mutation == "blank-line-before-root":
        content = declaration + b"\n" + content[len(declaration) :]
    elif mutation == "two-spaces-before-root":
        content = declaration + b"  " + content[len(declaration) :]
    elif mutation == "extra-final-newline":
        content += b"\n"
    elif mutation == "trailing-space-after-root":
        content += b" "
    else:
        original = b'<p xml:id="npnf-ambrose-'
        replacement = b'<p xmlns="http://www.tei-c.org/ns/1.0" xml:id="npnf-ambrose-'
        assert content.count(original) > 0
        content = content.replace(original, replacement, 1)

    xml_path.write_bytes(content)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match=f"^{expected_error}$"):
        _oracle(source, mutated)


@pytest.mark.parametrize(
    ("member_name", "mutation"),
    [
        ("README.source.md", "\nHuman review: accepted. Publication: ready.\n"),
        ("provenance.json", "rights"),
        ("provenance.json", "work-source-title"),
        ("provenance.json", "edition-title"),
        ("source-accountability.json", "source-selector"),
        ("unresolved.jsonl", ""),
        ("unresolved.jsonl", "stale-evidence"),
    ],
)
def test_independent_oracle_rejects_resealed_evidence_drift(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
    tmp_path: Path,
    member_name: str,
    mutation: str | None,
) -> None:
    source, candidate = verified_candidate
    target = tmp_path / member_name.replace(".", "-")
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=(member_name, "manifest.json"),
    )
    path = target / member_name
    if member_name == "README.source.md":
        path.write_text(path.read_text(encoding="utf-8") + mutation, encoding="utf-8")
    elif member_name == "provenance.json":
        value = json.loads(path.read_bytes())
        if mutation == "rights":
            value["rights"]["publication_state"] = "ready"
        elif mutation == "work-source-title":
            value["works"][0]["source_title"] = "Invented Source Title"
        else:
            value["edition"]["title"] = "Invented Edition"
        path.write_bytes(_canonical(value))
    elif member_name == "source-accountability.json":
        value = json.loads(path.read_bytes())
        value["crosswalk"][0]["source_selector"] = "invented"
        path.write_bytes(_canonical(value))
    elif mutation == "stale-evidence":
        values = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]
        values[0]["evidence"] = "Stale evidence"
        path.write_bytes(b"".join(_canonical(value) for value in values))
    else:
        path.write_text(mutation, encoding="utf-8")
    mutated = _reseal(target, member_name)
    with pytest.raises(ValueError):
        _oracle(source, mutated)


def test_oracle_runtime_closure_and_source_local_authorities_are_exact() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    observed = tuple(
        path.relative_to(ROOT).as_posix() for path in _closure_paths(ROOT, policy)
    )
    assert observed == EXPECTED_CLOSURE
    assert (
        _closure_digest(ROOT, policy)
        == source.record["validator"]["import_closure_sha256"]
    )
    for authority in source.record["authorities"]:
        content = source.authority_path(authority["name"]).read_bytes()
        assert authority["bytes"] == len(content)
        assert authority["sha256"] == _sha(content)
    oracle_source = (ROOT / "build/tei/npnf_ambrose_oracle.py").read_text(
        encoding="utf-8"
    )
    for forbidden in policy["forbidden_oracle_imports"]:
        assert f"import {forbidden}" not in oracle_source
        assert f"from {forbidden}" not in oracle_source


@pytest.mark.parametrize(
    "mutation",
    ["source-manifest", "converter", "package-schema", "member-hash"],
)
def test_candidate_binding_and_closure_drift_fail_closed(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate = verified_candidate
    target = tmp_path / mutation
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=("manifest.json",),
    )
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if mutation == "source-manifest":
        manifest["source_manifest"]["sha256"] = "0" * 64
    elif mutation == "converter":
        manifest["converter"]["id"] = "invented-converter"
    elif mutation == "package-schema":
        manifest["package_schema"]["sha256"] = "0" * 64
    else:
        manifest["members"][0]["sha256"] = "0" * 64
    manifest_path.write_bytes(_canonical(manifest))
    with pytest.raises(ValueError):
        mutated = CandidatePackage.load(target)
        _oracle(source, mutated)


def test_current_candidate_is_byte_identical_to_one_fresh_process_rebuild(
    verified_candidate: tuple[SourceManifest, CandidatePackage],
    tmp_path: Path,
) -> None:
    _, current_candidate = verified_candidate
    current = current_candidate.path
    external_cwd = tmp_path / "external-cwd"
    external_cwd.mkdir()
    rebuilt = external_cwd / "candidate"
    code = (
        "from pathlib import Path; import sys; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.npnf_ambrose_reconstruction import _convert; "
        f"r=Path({str(ROOT)!r}); "
        f"s=SourceManifest.load(r/{str(MANIFEST.relative_to(ROOT))!r},repository_root=r); "
        "reconstruct(s,Path(sys.argv[1]),_convert)"
    )
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "23"
    environment["PYTHONPATH"] = (
        str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    )
    subprocess.run(
        [sys.executable, "-c", code, str(rebuilt)],
        cwd=external_cwd,
        env=environment,
        check=True,
        timeout=300,
    )
    current_members = {
        path.relative_to(current).as_posix(): path.read_bytes()
        for path in sorted(current.rglob("*"))
        if path.is_file()
    }
    rebuilt_members = {
        path.relative_to(rebuilt).as_posix(): path.read_bytes()
        for path in sorted(rebuilt.rglob("*"))
        if path.is_file()
    }
    assert current_members == rebuilt_members


def test_runtime_remains_source_local_and_has_no_campaign_or_shared_family_layer() -> (
    None
):
    for path in (
        ROOT / "build/tei/npnf_ambrose_reconstruction.py",
        ROOT / "build/tei/npnf_ambrose_oracle.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "build.reconstruction" not in source
        assert "case_declaration" not in source
        assert "reconstruction.persistence" not in source
        assert "reconstruction.wave" not in source


def test_all_nine_ambrose_live_routes_are_verified_and_nonaccepted(
    catalog_with_evidence,
) -> None:
    catalog, candidate, validation_path = catalog_with_evidence
    by_id = {work["work_id"]: work for work in catalog.works}
    assert catalog.summary["work_units"] == len(ASSIGNED)
    assert set(by_id) == {work_id for _, work_id in ASSIGNED}
    assert candidate.path.is_dir()
    assert validation_path.is_file()
    for _, work_id in ASSIGNED:
        state = by_id[work_id]["reconstruction_state"]
        assert state["retained_source"] == "manifest_bound"
        assert state["tei_candidate"] == "verified"
        assert state["validation"] == "verified"
        assert state["human_review"] == "required"
        assert state["accepted_ir"] == "not_accepted"
        assert state["publication"] == "not_ready"
        routes = [route for route in state["routes"] if route["source_id"] == SOURCE_ID]
        assert len(routes) == 1
        assert routes[0]["association"] == "source_hash+exact_id"
        assert routes[0]["scope"] == "work"
        assert routes[0]["candidate_verification"] == "verified"
        assert routes[0]["validation_verification"] == "verified"


def test_catalog_rejects_unused_ambrose_runtime_evidence(runtime_catalog_discovery) -> None:
    with pytest.raises(ValueError, match="does not bind"):
        collect_work_catalog(
            ROOT / "data",
            source_manifest_allowlist=[MANIFEST.relative_to(ROOT).as_posix()],
            data_resource_allowlist=[
                f"data/structured-text/{work_id}.json" for _, work_id in ASSIGNED
            ],
            reconstruction_evidence={
                (SOURCE_ID, "not-an-assigned-work"): (
                    Path("missing-candidate"),
                    Path("missing-validation"),
                )
            },
        )


def test_current_lib044_candidate_and_validation_sidecar_bind(
    verified_review_evidence: tuple[SourceManifest, CandidatePackage, Path],
) -> None:
    source, candidate, validation_path = verified_review_evidence
    review = load_verified_review(
        source,
        candidate_path=candidate.path,
        validation_path=validation_path,
    )
    assert review.candidate_sha256 == candidate.sha256
    assert review.validation.status == "pass"
    assert {item.name for item in candidate.path.parent.iterdir()} == {
        "candidate",
        "validation.json",
    }
