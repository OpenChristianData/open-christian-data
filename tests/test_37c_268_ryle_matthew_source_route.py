from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import pytest
from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path('tests/fixtures/reconstruction-runtime/ryle_expository_thoughts_matthew_lib055_oracle.source-manifest.json')
SOURCE_PATH = "raw/ccel/ryle/matthew.xml"
SOURCE_BYTES = 763_304
SOURCE_SHA256 = "47639fe6d02e31d674fb055b1558d912bdf2747c5e2f8fa342b5df3b2d827a24"
WORK_ID = "ryle-expository-thoughts-matthew"
FOCUS_SELECTOR = "div1[@id='xiv']/div2[@id='xiv.v']"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS, "xml": XML_NS}
EXPECTED_DIV1_IDS = (
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "vii",
    "viii",
    "ix",
    "x",
    "xi",
    "xii",
    "xiii",
    "xiv",
    "xv",
    "xvi",
    "xvii",
    "xviii",
    "xix",
    "xx",
    "xxi",
    "xxii",
    "xxiii",
    "xxiv",
    "xxv",
    "xxvi",
    "xxvii",
    "xxviii",
    "xxix",
)


def _load_bound_module(manifest: SourceManifest, role: str):
    binding = manifest.record[role]
    path = ROOT / str(binding["implementation_path"])
    assert (
        hashlib.sha256(path.read_bytes()).hexdigest()
        == binding["implementation_sha256"]
    )
    module_name = f"_test_37c268_{role}_{binding['implementation_sha256']}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def route():
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    producer = _load_bound_module(manifest, "converter")
    oracle = _load_bound_module(manifest, "validator")
    return manifest, producer, oracle


@pytest.fixture(scope="module")
def mapped(route):
    manifest, producer, _oracle = route
    return producer._convert(manifest)


def _tree(data: bytes) -> etree._Element:
    return etree.fromstring(data)


def _changed(root: etree._Element) -> bytes:
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


class _InMemoryPackage:
    """CandidatePackage-shaped test value; it never writes candidate files."""

    def __init__(self, manifest, members):
        self.manifest = manifest
        self._members = dict(members)
        self._manifest_bytes = _canonical(manifest)
        self.sha256 = hashlib.sha256(self._manifest_bytes).hexdigest()

    @property
    def member_names(self):
        return tuple(sorted(set(self._members) | {"manifest.json"}))

    def member_bytes(self, name):
        self.verify_integrity()
        if name == "manifest.json":
            return self._manifest_bytes
        return self._members[name]

    def verify_integrity(self):
        assert set(self._members) == {
            "README.source.md",
            "content.tei.xml",
            "provenance.json",
            "source-accountability.json",
            "unresolved.jsonl",
        }
        expected_members = [
            {
                "name": name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in sorted(self._members.items())
        ]
        assert self.manifest["members"] == expected_members
        assert hashlib.sha256(self._manifest_bytes).hexdigest() == self.sha256


def _in_memory_package(
    manifest: SourceManifest, members: dict[str, bytes]
) -> _InMemoryPackage:
    manifest_path = manifest.path.relative_to(manifest.repository_root).as_posix()
    record = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": manifest.record["source_id"],
        "source_manifest": {"path": manifest_path, "sha256": manifest.sha256},
        "converter": _plain(manifest.record["converter"]),
        "package_schema": _plain(manifest.record["package_schema"]),
        "members": [
            {
                "name": name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in sorted(members.items())
        ],
    }
    schema_path = manifest.authority_path("package-schema")
    schema = json.loads(schema_path.read_bytes())
    assert list(Draft202012Validator(schema).iter_errors(record)) == []
    return _InMemoryPackage(record, members)


def test_manifest_binds_exact_member_owner_scope_and_unsettled_claims(route):
    manifest, _producer, oracle = route
    record = manifest.record
    source = ROOT / SOURCE_PATH
    raw = source.read_bytes()
    primary = [
        row for row in record["authorities"] if row.get("role") == "primary-source"
    ]

    assert record["ticket"] == "37c-268"
    assert record["owner_route"] == "LIB-055"
    assert record["work_id"] == WORK_ID
    assert len(primary) == 1
    assert primary[0]["path"] == SOURCE_PATH
    assert primary[0]["bytes"] == SOURCE_BYTES == len(raw)
    assert primary[0]["sha256"] == SOURCE_SHA256 == hashlib.sha256(raw).hexdigest()
    assert tuple(record["scope"]["member_order"]) == (SOURCE_PATH,)
    assert (
        record["scope"]["selector"] == "ThML[1] (complete retained document envelope)"
    )
    assert record["scope"]["focus_selector"] == FOCUS_SELECTOR
    assert record["scope"]["focus_carrier"]["source_parent_id"] == "xiv"
    assert record["scope"]["focus_carrier"]["source_parent_title"] == "Matthew 13"
    assert record["scope"]["focus_carrier"]["source_id"] == "xiv.v"
    assert record["scope"]["known_source_gap"]["passage"] == "Matthew 14:1-21"
    assert record["scope"]["known_source_gap"]["source_native_carrier_present"] is False
    assert all(
        record["identity"][field] is None
        for field in (
            "textual_form",
            "edition",
            "parts",
            "witness_claim",
            "translator",
            "original_publication_year",
        )
    )
    assert record["identity"]["unresolved"]
    assert (
        oracle._import_closure_sha256(ROOT)
        == record["validator"]["import_closure_sha256"]
    )

    owner_ticket = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/tickets/library/055-reconstruct-and-review-ccel-puritan-works-cohort-2.md"
    ).read_text(encoding="utf-8")
    work_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md"
    ).read_text(encoding="utf-8")
    source_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md"
    ).read_text(encoding="utf-8")
    assert f"`{WORK_ID}` — Expository Thoughts on the Gospels: Matthew" in owner_ticket
    assert (
        f"| `{WORK_ID}` | Expository Thoughts on the Gospels: Matthew | LIB-055 | 1 | none |"
        in work_map
    )
    assert (
        f"| `{WORK_ID}` | `sha256:{SOURCE_SHA256}` | LIB-055 | current-claim |"
        in source_map
    )


def test_independent_envelope_censuses_match_complete_profile(route):
    manifest, producer, oracle = route
    raw = (ROOT / SOURCE_PATH).read_bytes()
    producer_tree = producer._parse(raw)
    oracle_tree = oracle._read(raw)
    profile = json.loads(manifest.authority_path("feature-profile").read_bytes())

    producer_facts = producer._measure(producer_tree)
    oracle_facts = oracle._source_facts(oracle_tree)
    assert producer_facts == profile["document"]
    assert oracle_facts == profile["document"]
    assert producer_facts == oracle_facts
    assert producer_facts["element_count"] == 2703
    assert producer_facts["attribute_count"] == 5412
    assert (
        producer_facts["source_id_count"]
        == producer_facts["unique_source_id_count"]
        == 1911
    )
    assert producer_facts["comment_count"] == 11
    assert (
        producer_facts["shell"]["doctype"]["public_id"]
        == "-//CCEL/DTD Theological Markup Language//EN"
    )
    assert len(producer_facts["shell"]["before_root_nodes"]) == 2
    assert profile["raw_prolog"]["bytes_before_root"] == 315
    assert (
        profile["raw_prolog"]["sha256"]
        == "e27a029b2c9bfabfb72a9cf82ffd82c3591bdcd8e38e5decab729c145efc637b"
    )


def test_in_memory_route_maps_full_order_and_preserves_the_matthew_13_parent(
    route, mapped
):
    manifest, _producer, oracle = route
    assert set(mapped) == {
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
    assert (
        oracle.validate_tei_bytes(manifest, mapped["content.tei.xml"])["status"]
        == "pass"
    )

    root = _tree(mapped["content.tei.xml"])
    body = root.find("./tei:text/tei:body", NS)
    assert body is not None
    divisions = body.findall("./tei:div[@type='source-div1']", NS)
    assert tuple(item.get(f"{{{XML_NS}}}id") for item in divisions) == EXPECTED_DIV1_IDS
    assert tuple(item.get("n") for item in divisions)[1:28] == tuple(
        [f"Matthew {number}" for number in range(1, 14)]
        + [f"Matthew {number}" for number in range(15, 29)]
    )
    parent = root.find("./tei:text/tei:body/tei:div[@xml:id='xiv']", NS)
    nested = root.find(
        "./tei:text/tei:body/tei:div[@xml:id='xiv']/tei:div[@xml:id='xiv.v']", NS
    )
    assert parent is not None and parent.get("n") == "Matthew 13"
    assert nested is not None and nested.getparent() is parent
    assert nested.get("n") == "Matthew 14:22-36"
    assert (
        nested.find(".//tei:anchor[@type='scripture-commentary-marker']", NS)
        is not None
    )
    assert root.find(".//tei:div[@n='Matthew 14']", NS) is None
    assert root.find(".//tei:div[@n='Matthew 14:1-21']", NS) is None
    gap = root.find(".//tei:note[@type='source-gap'][@n='Matthew 14:1-21']", NS)
    assert gap is not None and "No source-native carrier" in (gap.text or "")
    assert len(root.findall(".//tei:ref[@type='scripture']", NS)) == 464
    assert (
        len(root.findall(".//tei:anchor[@type='scripture-commentary-marker']", NS))
        == 93
    )
    assert len(root.findall(".//tei:anchor[@type='index-insertion']", NS)) == 2
    assert len(root.xpath(".//tei:ref[contains(@target, '#')]", namespaces=NS)) == 557
    assert b"sourced via CCEL.org" in mapped["README.source.md"]

    accounting = json.loads(mapped["source-accountability.json"])
    assert accounting["source_member"] == {
        "path": SOURCE_PATH,
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
    }
    assert len(accounting["elements"]) == 2703
    assert len(accounting["comments"]) == 11
    assert accounting["source_envelope"]["shell"]["doctype"]["declaration"].startswith(
        "<!DOCTYPE ThML PUBLIC"
    )
    assert accounting["source_envelope"]["raw_prolog"]["bytes_before_root"] == 315
    assert accounting["dispositions"]["matthew_14_1_21"].startswith(
        "No source-native carrier"
    )


def test_independent_package_oracle_passes_in_memory_without_candidate_packaging(
    route, mapped
):
    manifest, _producer, oracle = route
    package = _in_memory_package(manifest, mapped)
    result = oracle._oracle(manifest, package)
    assert result["status"] == "pass"
    assert result["oracle_id"] == manifest.record["validator"]["id"]
    assert result["source_sha256"] == SOURCE_SHA256
    assert result["findings"] == []


def test_independent_package_oracle_rejects_gap_accountability_mutation(route, mapped):
    manifest, _producer, oracle = route
    changed = dict(mapped)
    accounting = json.loads(changed["source-accountability.json"])
    accounting["dispositions"]["matthew_14_1_21"] = "silently restored"
    changed["source-accountability.json"] = _canonical(accounting)
    package = _in_memory_package(manifest, changed)
    with pytest.raises(ValueError, match="gap or exclusion disposition differs"):
        oracle._oracle(manifest, package)


def _mutated_tei(mapped: dict[str, bytes], mutation: str) -> bytes:
    root = _tree(mapped["content.tei.xml"])
    body = root.find("./tei:text/tei:body", NS)
    assert body is not None
    top = body.findall("./tei:div[@type='source-div1']", NS)
    nested = root.find(
        "./tei:text/tei:body/tei:div[@xml:id='xiv']/tei:div[@xml:id='xiv.v']", NS
    )
    assert nested is not None

    if mutation == "omit-div1":
        body.remove(top[2])
    elif mutation == "duplicate-div1":
        body.insert(2, deepcopy(top[1]))
    elif mutation == "reorder-div1":
        body.remove(top[1])
        body.insert(2, top[1])
    elif mutation == "omit-xiv-v":
        nested.getparent().remove(nested)
    elif mutation == "reparent-xiv-v":
        nested.getparent().remove(nested)
        body.insert(1, nested)
    elif mutation == "invent-matthew-14":
        made = etree.Element(
            f"{{{TEI_NS}}}div",
            {
                f"{{{XML_NS}}}id": "invented-xiv",
                "type": "source-div1",
                "n": "Matthew 14",
            },
        )
        body.insert(14, made)
    elif mutation == "nested-wording":
        paragraph = nested.find(".//tei:p", NS)
        assert paragraph is not None
        paragraph.text = (paragraph.text or "") + " mutation"
    elif mutation == "heading":
        heading = root.find(".//tei:head", NS)
        assert heading is not None
        heading.text = (heading.text or "") + " mutation"
    elif mutation == "link-target":
        link = root.xpath(
            ".//tei:ref[@target and not(@type='scripture')]", namespaces=NS
        )[0]
        assert link is not None
        link.set("target", link.get("target", "") + "#not-source-id")
    elif mutation == "scripture-target":
        ref = root.find(".//tei:ref[@type='scripture']", NS)
        assert ref is not None
        ref.set("target", ref.get("target", "") + ".mutated")
    elif mutation == "commentary-marker":
        marker = root.find(".//tei:anchor[@type='scripture-commentary-marker']", NS)
        assert marker is not None and marker.getparent() is not None
        marker.getparent().remove(marker)
    elif mutation == "index-marker":
        marker = root.find(".//tei:anchor[@type='index-insertion']", NS)
        assert marker is not None and marker.getparent() is not None
        marker.getparent().remove(marker)
    elif mutation == "body-comment":
        comment = root.xpath(".//tei:body//comment()", namespaces=NS)[0]
        comment.getparent().remove(comment)
    elif mutation == "metadata":
        title = root.find("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", NS)
        assert title is not None
        title.text = "Invented source title"
    elif mutation == "gap-statement":
        gap = root.find(".//tei:note[@type='source-gap']", NS)
        assert gap is not None
        gap.text = "Matthew 14 has been restored from another witness."
    else:
        raise AssertionError(f"unknown mutation {mutation}")
    return _changed(root)


@pytest.mark.parametrize(
    "mutation",
    (
        "omit-div1",
        "duplicate-div1",
        "reorder-div1",
        "omit-xiv-v",
        "reparent-xiv-v",
        "invent-matthew-14",
        "nested-wording",
        "heading",
        "link-target",
        "scripture-target",
        "commentary-marker",
        "index-marker",
        "body-comment",
        "metadata",
        "gap-statement",
    ),
)
def test_independent_oracle_rejects_source_meaning_mutations(route, mapped, mutation):
    manifest, _producer, oracle = route
    changed = _mutated_tei(mapped, mutation)
    assert changed != mapped["content.tei.xml"]
    with pytest.raises(
        ValueError, match="candidate TEI differs|candidate TEI is malformed"
    ):
        oracle.validate_tei_bytes(manifest, changed)


def test_independent_oracle_rejects_substituted_source_bytes_without_touching_raw(
    route, mapped, tmp_path
):
    manifest, _producer, oracle = route
    raw = (ROOT / SOURCE_PATH).read_bytes()
    changed = bytearray(raw)
    changed[100] ^= 1
    alternate = tmp_path / "substituted-matthew.xml"
    alternate.write_bytes(changed)

    class AlternateMember:
        record = manifest.record
        path = manifest.path
        repository_root = manifest.repository_root

        def verify(self):
            return None

        def authority_path(self, name):
            if name == "source-member":
                return alternate
            return manifest.authority_path(name)

    with pytest.raises(ValueError, match="retained source bytes differ"):
        oracle.validate_tei_bytes(AlternateMember(), mapped["content.tei.xml"])
