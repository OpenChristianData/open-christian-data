"""Focused LIB-089 Westminster source, blocker, reconstruction, and oracle tests."""

from __future__ import annotations

import json
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest
from lxml import etree, html

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate
from build.tei.lib089_westminster_standards_reconstruction import _convert, _producer_closure
from build.tei.lib089_westminster_standards_oracle import _oracle, _closure


ROOT = Path(__file__).resolve().parents[1]
PUBLICK_BLOCKER = (
    ROOT
    / "sources/doctrinal-documents/directory-for-publick-worship/LIB-089.blocker.json"
)
DURABLE_RAW = Path(r"D:/Library/Open Christian Data/raw/westminster-standard-org")
PRODUCER_PATH = ROOT / "build/tei/lib089_westminster_standards_reconstruction.py"
RUNTIME_ROOT = ROOT / "tests/fixtures/reconstruction-runtime"
RUNTIME_BINDINGS = {
    "directory-for-family-worship": "558e0d6d68d54ced1dea9b2462f8bf1946cd6c937698f3fb17e6fba4811abc1b",
    "solemn-league-and-covenant": "54595805211178d1ea87e88dca489f331fb349103aaca4c1ee096ad7eb8b72b1",
    "directory-for-publick-worship": "415dfe2c793512f6cd4014d77e72464b07a6deb0eee71e0fb2f504f6d9ef3d24",
}
SOURCE_PINS = {
    "directory-for-family-worship": (
        63_341,
        "b18780153306e2966aac28f5c677b6c47588dc0eec4123e393dcd4687aba1640",
    ),
    "form-of-church-government": (
        92_499,
        "d5b31994e9ce43e7828ff65f3ac758e8974b0396d6ba03f991c785b8d92a3ac4",
    ),
    "solemn-league-and-covenant": (
        66_315,
        "824dfd79c68a13d137ad6f7f7575e8af5c856287087c9694a3100f2c45b4cc5d",
    ),
    "sum-of-saving-knowledge": (
        135_684,
        "6aa4907f6994d61ce3afeeea9b063cabf667b087185bc1cf7f7fd71fc19fee83",
    ),
}


@pytest.fixture(params=["directory-for-family-worship", "solemn-league-and-covenant", "directory-for-publick-worship"])
def family_candidate(tmp_path: Path, request: pytest.FixtureRequest):
    slug = request.param
    source = SourceManifest.load(
        RUNTIME_ROOT / f"lib089-{slug}.source-manifest.json",
        repository_root=ROOT,
    )
    return source, reconstruct(source, tmp_path / "candidate", _convert)


@pytest.mark.parametrize("slug", RUNTIME_BINDINGS)
def test_runtime_fixture_preserves_complete_record_except_declared_closures(slug: str) -> None:
    original = ROOT / "sources/doctrinal-documents" / slug / f"{slug}.source-manifest.json"
    content = original.read_bytes()
    assert _sha(content) == RUNTIME_BINDINGS[slug]
    expected = json.loads(content)
    expected["producer_import_closure_sha256"] = _producer_closure(ROOT)
    expected["validator"]["import_closure_sha256"] = _closure(ROOT)
    runtime = RUNTIME_ROOT / f"lib089-{slug}.source-manifest.json"
    assert json.loads(runtime.read_bytes()) == expected
    SourceManifest.load(runtime, repository_root=ROOT)


def test_family_conversion_preserves_source_paths_and_numbered_sections(family_candidate) -> None:
    source, candidate = family_candidate
    assert validate(source, candidate, _oracle).status == "pass"
    # Independently locate the work by its title, rather than the producer's
    # class selector or profile. Check every recorded path against a fresh parse.
    document = html.document_fromstring(source.authority_path("retained-html").read_bytes())
    headings = document.xpath('//h1')
    if source.record["work_id"] == "directory-for-publick-worship":
        tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
        ns = {"t": "http://www.tei-c.org/ns/1.0"}
        assert len(tei.xpath('//t:body/t:div', namespaces=ns)) == 5
        assert len(tei.xpath('//t:head', namespaces=ns)) == 19
        assert tei.xpath('string(//t:revisionDesc/t:change/@when)', namespaces=ns) == "2026-09-11"
        assert ["".join(n.itertext()).strip() for n in tei.xpath('//t:titleStmt/t:title|//t:head[@type="html-h1"]', namespaces=ns)] == [n.text_content().strip() for n in headings]
        return
    expected_headings = [
        "The Directory for Family Worship", "I.", "II.", "III.", "IV.",
        "V.", "VI.", "VII.", "VIII.", "IX.", "X.", "XI.", "XII.", "XIII.", "XIV.",
    ]
    if source.record["work_id"] == "solemn-league-and-covenant":
        expected_headings = ["The Solemn League and Covenant", "THE SOLEMN LEAGUE AND COVENANT", "I.", "II.", "III.", "IV.", "V.", "VI."]
    assert [node.text_content().strip() for node in headings] == expected_headings
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    assert ["".join(n.itertext()).strip() for n in tei.xpath('//t:titleStmt/t:title|//t:head[@type="html-h1"]', namespaces=ns)] == [n.text_content().strip() for n in headings]
    records = json.loads(candidate.member_bytes("source-accountability.json"))["source_events"]
    assert len(records) == (47 if source.record["work_id"] == "directory-for-family-worship" else 73)
    assert len({row["source_xpath"] for row in records}) == len(records)
    for row in records:
        original = document.xpath(row["source_xpath"])
        projected = tei.xpath('//*[@xml:id=$identifier]', identifier=row["tei_xml_id"])
        assert len(original) == len(projected) == 1
        assert "".join(original[0].itertext()) == "".join(projected[0].itertext())


@pytest.mark.parametrize("mutation", ["omit", "reorder", "invent", "wrong-path", "duplicate", "metadata", "source-digest", "revision-date", "source-url", "extra-metadata", "link-target"])
def test_family_oracle_rejects_resealed_semantic_mutations(family_candidate, mutation: str) -> None:
    source, candidate = family_candidate
    assert validate(source, candidate, _oracle).status == "pass"
    name = "content.tei.xml"
    if mutation == "wrong-path":
        name = "source-accountability.json"
        value = json.loads(candidate.member_bytes(name))
        value["source_events"][1]["source_xpath"] = value["source_events"][0]["source_xpath"]
        content = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    else:
        tree = etree.fromstring(candidate.member_bytes(name))
        paragraphs = tree.xpath('//t:body//t:p', namespaces={"t": "http://www.tei-c.org/ns/1.0"})
        node = paragraphs[0]
        if mutation == "omit":
            node.getparent().remove(node)
        elif mutation == "duplicate":
            duplicate = etree.fromstring(etree.tostring(node))
            duplicate.set("{http://www.w3.org/XML/1998/namespace}id", "invented-duplicate-id")
            node.getparent().append(duplicate)
        elif mutation == "metadata":
            tree.xpath('//t:titleStmt/t:title', namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0].text = "Wrong work title"
        elif mutation == "source-digest":
            tree.xpath('//t:sourceDesc//t:idno', namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0].text = "0" * 64
        elif mutation == "revision-date":
            tree.xpath('//t:revisionDesc/t:change', namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0].set("when", "1900-01-01")
        elif mutation == "source-url":
            tree.xpath('//t:sourceDesc//t:ptr', namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0].set("target", "https://example.invalid/wrong-source")
        elif mutation == "link-target":
            refs = tree.xpath('//t:body//t:ref', namespaces={"t": "http://www.tei-c.org/ns/1.0"})
            if not refs:
                pytest.skip(f"{source.record['work_id']} has no body ref target to mutate")
            refs[0].set("target", "#wrong-destination")
        elif mutation == "extra-metadata":
            statement = tree.xpath('//t:titleStmt', namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0]
            etree.SubElement(statement, '{http://www.tei-c.org/ns/1.0}author').text = "Invented attribution"
        elif mutation == "reorder":
            body_nodes = tree.xpath('//t:body//*', namespaces={"t": "http://www.tei-c.org/ns/1.0"})
            parent = next((element for element in body_nodes if len(element) > 1), None)
            assert parent is not None, "the retained body must contain an ordered carrier with at least two children"
            parent.append(parent[0])
        else:
            node.text = (node.text or "") + " Invented source sentence."
        content = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    (candidate.path / name).write_bytes(content)
    manifest_path = candidate.path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    row = next(r for r in manifest["members"] if r["name"] == name)
    row.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    altered = CandidatePackage.load(candidate.path)
    with pytest.raises(ValueError, match="LIB-089"):
        validate(source, altered, _oracle)


def _strict_json(path: Path) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
    )
    assert isinstance(value, dict)
    return value


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_four_durable_sources_match_exact_pins_and_producer_seam_exists() -> None:
    for slug, (expected_bytes, expected_sha256) in SOURCE_PINS.items():
        source = DURABLE_RAW / f"{slug}.html"
        content = source.read_bytes()
        assert len(content) == expected_bytes
        assert _sha(content) == expected_sha256

    producer = _load_module(PRODUCER_PATH, "_lib089_producer_red")
    assert producer.CONVERTER_ID == "ocd-lib089-westminster-retained-html-to-tei"
    assert producer.CONVERTER_VERSION == "1"
    assert callable(producer._convert)


def test_publick_worship_strict_blocker_is_exact() -> None:
    blocker = _strict_json(PUBLICK_BLOCKER)
    assert blocker == {
        "contract": "ocd-lib089-source-blocker-v1",
        "ticket_id": "LIB-089",
        "work_id": "directory-for-publick-worship",
        "title": "The Directory for the Publick Worship of God",
        "frozen_source_claim": {
            "logical_path": "raw/westminster-standard-org/directory-for-publick-worship.html",
            "sha256": "354006b984ea249e06be9c5a4f9f13fcee64a269cc016df2097e929430fc7df3",
            "bytes": None,
            "claim_status": "unverified-current-claim",
        },
        "durable_raw": {
            "library_root": "D:/Library/Open Christian Data",
            "present": False,
            "verified_on": "2026-08-31",
        },
        "known_attempts": [
            {
                "url": "https://thewestminsterstandard.org/directory-for-the-publick-worship-of-god/",
                "result": "HTTP 403 on both recorded pinning attempts",
            },
            {
                "url": "https://www.reformed.org/documents/wcf_standards/p369-direct_pub_worship.html",
                "result": "redirected to reformed.org and returned HTTP 404",
            },
            {
                "url": "http://www.reformed.org/documents/wcf_standards/p369-direct_pub_worship.html",
                "result": "redirected to reformed.org and returned HTTP 404",
            },
            {
                "url": "https://www.puritannica.com/front/demo/wk/StandardsWestminster/DirectoryPublicWorship/0000-0000.html",
                "result": "DNS resolution failure: No such host is known",
            },
        ],
        "network_acquisition_performed_for_lib089": False,
        "source_manifest": None,
        "candidate": None,
        "validation": None,
        "acceptance_status": "nonaccepted",
        "publication": False,
        "blocker": (
            "The frozen hash claim cannot be verified because no retained source bytes "
            "are present, and the recorded canonical and alternative-witness routes did "
            "not yield a suitable retained witness."
        ),
        "owner": "source-evidence-maintainer",
        "next_action": (
            "Retain a politely acquired canonical response or a complete edition-matched "
            "alternative witness without bypassing access controls; then hash-pin it and "
            "compare its identity and complete text before creating any manifest or candidate."
        ),
        "reopening_condition": (
            "A complete locally retained witness exists whose bytes match the frozen claim, "
            "or whose different hash is independently shown to be an edition-matched source "
            "and is explicitly re-pinned by authorized campaign maintenance."
        ),
        "unresolved": [
            "source-byte identity",
            "edition and witness identity",
            "rights and source terms",
            "editorial structure and readings",
            "human textual acceptance",
        ],
    }
    assert not (
        Path(r"D:/Library/Open Christian Data")
        / blocker["frozen_source_claim"]["logical_path"]  # type: ignore[index]
    ).exists()
