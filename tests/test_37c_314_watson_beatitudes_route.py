from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path

from lxml import etree
import pytest

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ROOT = Path(__file__).resolve().parents[1]
ROUTE_DIR = ROOT / "sources/structured-text/watson-beatitudes"
MANIFEST_PATH = ROOT / 'tests/fixtures/reconstruction-runtime/watson-beatitudes.source-manifest.json'
SOURCE_PATH = ROOT / "raw/ccel/watson/beatitudes.xml"
SOURCE_SHA256 = "d85ea8ded5de4feff3b2a9156bece9c471ffec3045eb8dc300b2784f5753f837"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"t": TEI_NS, "xml": XML_NS}


def _load_route_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def route():
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    producer = _load_route_module(
        "w314_watson_beatitudes_reconstruction",
        ROUTE_DIR / "watson_beatitudes_reconstruction.py",
    )
    oracle = _load_route_module(
        "w314_watson_beatitudes_oracle",
        ROUTE_DIR / "watson_beatitudes_oracle.py",
    )
    shared_tag_map = dict(producer._selected_thml.TAGS)
    members = producer._convert(manifest)
    assert producer._selected_thml.TAGS == shared_tag_map
    return manifest, producer, oracle, members


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _parse_tei(members: dict[str, bytes]):
    return etree.fromstring(
        members["content.tei.xml"],
        etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
    )


def test_source_manifest_binds_exact_retained_member_and_full_selector(route) -> None:
    manifest, producer, oracle, _members = route
    acquisition_path = manifest.authority_path("acquisition")
    acquisition = json.loads(acquisition_path.read_bytes())
    source = SOURCE_PATH.read_bytes()

    assert len(source) == 1_120_523
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA256
    assert acquisition["source_selection"]["selection_id"] == (
        "watson-beatitudes-all-direct-div1-route-envelope-v1"
    )
    assert [unit["native_id"] for unit in acquisition["source_selection"]["units"]] == [
        "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
        "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix",
        "xx", "xxi", "xxii", "xxiii", "xxiv", "xxv",
    ]
    assert manifest.record["validator"]["import_closure_sha256"] == oracle._closure_digest(ROOT)
    assert manifest.record["validator"]["implementation_path"].endswith(
        "watson_beatitudes_oracle.py"
    )
    converter_binding = manifest.record["converter"]
    validator_binding = manifest.record["validator"]
    assert producer._convert.__name__ == converter_binding["callable"]
    assert producer._convert.converter_id == converter_binding["id"]
    assert producer._convert.converter_version == converter_binding["version"]
    assert Path(inspect.getsourcefile(producer._convert)).resolve().samefile(
        ROOT / converter_binding["implementation_path"]
    )
    assert oracle._oracle.__name__ == validator_binding["callable"]
    assert oracle._oracle.oracle_id == validator_binding["id"]
    assert oracle._oracle.oracle_version == validator_binding["version"]
    assert Path(inspect.getsourcefile(oracle._oracle)).resolve().samefile(
        ROOT / validator_binding["implementation_path"]
    )


def test_work_local_producer_and_oracle_cover_all_source_features(route) -> None:
    manifest, producer, oracle, members = route
    audit = oracle._audit_members(manifest, members)
    tei = _parse_tei(members)
    account = json.loads(members["source-accountability.json"])

    assert set(members) == {
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
    assert audit["source_sha256"] == SOURCE_SHA256
    assert audit["source_carrier_count"] == 25
    assert audit["selected_feature_count"] == 4953
    assert audit["selected_feature_counts"]["scripCom"] == 13
    assert audit["selected_feature_counts"]["ol"] == 1
    assert len(account["features"]) == 4953
    assert len({feature["source_path"] for feature in account["features"]}) == 4953
    assert len(tei.xpath("//t:milestone[@unit='scripCom']", namespaces=NS)) == 13
    assert compiled_schema().validate(tei), str(compiled_schema().error_log)
    assert dict(producer._selected_thml.TAGS).get("scripCom") is None
    assert dict(producer._selected_thml.TAGS).get("ol") is None

    markers = tei.xpath("//t:milestone[@unit='scripCom']", namespaces=NS)
    assert all(
        marker.get("type") == "Commentary"
        and marker.get("n")
        and marker.get("corresp", "").startswith("Bible:")
        and len(marker) == 0
        for marker in markers
    )
    ordered_lists = tei.xpath("//t:list[@type='ordered']", namespaces=NS)
    assert len(ordered_lists) == 1
    assert [etree.QName(child).localname for child in ordered_lists[0]] == ["item", "item"]


def test_in_memory_production_is_byte_deterministic(route) -> None:
    manifest, producer, _oracle, members = route
    assert producer._convert(manifest) == members
    assert hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest() == SOURCE_SHA256


@pytest.mark.parametrize("mutation", ["feature-ledger", "scripcom-target", "ordered-list"])
def test_independent_oracle_rejects_source_derived_mutations(route, mutation: str) -> None:
    manifest, _producer, oracle, original = route
    changed = copy.copy(original)

    if mutation == "feature-ledger":
        account = json.loads(changed["source-accountability.json"])
        account["features"] = [
            row for row in account["features"] if row["source_tag"] != "scripCom"
        ]
        changed["source-accountability.json"] = _json_bytes(account)
    elif mutation == "scripcom-target":
        tei = _parse_tei(changed)
        tei.xpath("//t:milestone[@unit='scripCom']", namespaces=NS)[0].set(
            "corresp", "Bible:Matt.5.999"
        )
        changed["content.tei.xml"] = etree.tostring(
            tei, encoding="utf-8", xml_declaration=True
        )
    else:
        tei = _parse_tei(changed)
        ordered = tei.xpath("//t:list[@type='ordered']", namespaces=NS)[0]
        children = list(ordered)
        for child in children:
            ordered.remove(child)
        for child in reversed(children):
            ordered.append(child)
        changed["content.tei.xml"] = etree.tostring(
            tei, encoding="utf-8", xml_declaration=True
        )

    with pytest.raises(ValueError):
        oracle._audit_members(manifest, changed)
