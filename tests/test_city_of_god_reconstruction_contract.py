from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate
from build.tei.city_of_god_reconstruction import _closure as _producer_closure, _convert
from build.tei.city_of_god_oracle import _body_checks, _closure, _enforce_forbidden_claims, _expected_header, _expected_tei, _header_projection, _oracle, _recursive_projection


ROOT = Path(__file__).resolve().parents[1]
TEI = "http://www.tei-c.org/ns/1.0"
MANIFESTS = {
    "dods-1871": ROOT / "tests/fixtures/reconstruction-runtime/city-of-god-dods-1871.source-manifest.json",
    "npnf-1887": ROOT / "tests/fixtures/reconstruction-runtime/city-of-god-npnf-1887.source-manifest.json",
}
RAW_AUTHORITIES = (
    ROOT / "raw/standard_ebooks/augustine-of-hippo_the-city-of-god_marcus-dods_george-wilson_j-j-smith",
    ROOT / "raw/ccel/npnf1/npnf102.xml",
    ROOT / "raw/internet-archive/city-of-god/1871-v1-toronto/scan.pdf",
    ROOT / "raw/internet-archive/city-of-god/1871-v2-princeton/scan.pdf",
    ROOT / "raw/internet-archive/city-of-god/1887-npnf-v2-claremont/scan.pdf",
)
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not all(path.exists() for path in RAW_AUTHORITIES), reason="raw City of God authorities not downloaded"),
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.fixture(scope="session")
def packages(tmp_path_factory: pytest.TempPathFactory):
    destination = tmp_path_factory.mktemp("city-successors")
    result = {}
    for edition, path in MANIFESTS.items():
        manifest = SourceManifest.load(path, repository_root=ROOT)
        package = reconstruct(manifest, destination / edition, _convert)
        report = validate(manifest, package, _oracle)
        result[edition] = (manifest, package, report)
    return result


def test_two_manifests_produce_separate_valid_nonaccepted_packages(packages):
    dods = packages["dods-1871"]
    npnf = packages["npnf-1887"]
    assert dods[2].status == npnf[2].status == "pass"
    assert dods[1].sha256 != npnf[1].sha256
    assert dods[1].manifest["status"] == npnf[1].manifest["status"] == "nonaccepted"
    assert dods[1].member_names == npnf[1].member_names == (
        "README.source.md", "content.tei.xml", "manifest.json", "provenance.json", "source-accountability.json", "unresolved.jsonl"
    )


@pytest.mark.parametrize("edition", ["dods-1871", "npnf-1887"])
def test_complete_accounting_and_structure(packages, edition):
    _, package, _ = packages[edition]
    account = json.loads(package.member_bytes("source-accountability.json"))
    assert len(account["observations"]) == 58_815 + 88_276
    assert account["standard_observation_count"] == 58_815
    assert account["ccel_observation_count"] == 88_276
    assert account["print_inventory"]["print_member_count"] == 15
    assert account["print_inventory"]["print_bytes"] == 237_821_801
    assert account["print_inventory"]["print_chunk_count"] == 3635
    assert account["print_inventory"]["print_chunks_sha256"] == "4944191abf59b71c62715eb6f3171f356762e3d78c71c1480ba555f3e14f488f"
    assert account["semantic_units"] == {"books": 22, "chapters": 661, "prefaces": 4, "aligned_units": 665}
    assert account["variants"] == {"lexical": 1533, "orthographic": 2390}
    assert len(account["print_decisions"]) == 5
    assert account["crop_evidence"]["count"] == 14
    root = etree.fromstring(package.member_bytes("content.tei.xml"))
    _body_checks(root, edition, ROOT)


@pytest.mark.parametrize("edition", ["dods-1871", "npnf-1887"])
def test_converter_is_deterministic_in_memory(packages, edition):
    manifest = packages[edition][0]
    first = _convert(manifest)
    second = _convert(manifest)
    assert first == second


def _mutated_root(packages, edition: str) -> etree._Element:
    return etree.fromstring(packages[edition][1].member_bytes("content.tei.xml"))


def _resealed_tei_package(package: CandidatePackage, destination: Path, root: etree._Element) -> CandidatePackage:
    destination.mkdir()
    for name in package.member_names:
        (destination / name).write_bytes(package.member_bytes(name))
    tei = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    (destination / "content.tei.xml").write_bytes(tei)
    manifest = json.loads((destination / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == "content.tei.xml")
    member.update({"bytes": len(tei), "sha256": _sha(tei)})
    (destination / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(destination)


def _resealed_member_package(package: CandidatePackage, destination: Path, name: str, content: bytes) -> CandidatePackage:
    destination.mkdir()
    for member_name in package.member_names:
        (destination / member_name).write_bytes(content if member_name == name else package.member_bytes(member_name))
    manifest = json.loads((destination / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update({"bytes": len(content), "sha256": _sha(content)})
    (destination / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(destination)


@pytest.mark.parametrize(
    ("edition", "mutation"),
    [
        ("dods-1871", "book-swap"),
        ("dods-1871", "volume-move"),
        ("dods-1871", "continued-move"),
        ("dods-1871", "note-label"),
        ("npnf-1887", "page-label"),
        ("npnf-1887", "extra-division"),
        ("npnf-1887", "schaff-loss"),
    ],
)
def test_same_count_hierarchy_and_carrier_attacks_are_rejected(packages, edition, mutation):
    root = _mutated_root(packages, edition)
    ns = {"tei": TEI}
    body = root.find(f".//{{{TEI}}}body")
    assert body is not None
    if mutation == "book-swap":
        books = body.xpath(".//tei:div[@type='book']", namespaces=ns)
        books[0].set("n", "2"); books[1].set("n", "1")
    elif mutation == "volume-move":
        marker = body.xpath(".//tei:milestone", namespaces=ns)[1]
        marker.getparent().remove(marker); body.insert(0, marker)
    elif mutation == "continued-move":
        carriers = body.xpath(".//*[@rend='continued']")
        carriers[0].attrib.pop("rend"); body.xpath(".//tei:p[not(@rend)]", namespaces=ns)[0].set("rend", "continued")
    elif mutation == "note-label":
        notes = body.xpath(".//tei:note", namespaces=ns); notes[0].set("n", notes[1].get("n")); notes[1].set("n", "wrong")
    elif mutation == "page-label":
        pages = body.xpath(".//tei:pb", namespaces=ns); pages[0].set("n", pages[1].get("n")); pages[1].set("n", "wrong")
    elif mutation == "extra-division":
        etree.SubElement(body, f"{{{TEI}}}div", type="selected-reading")
    else:
        preface = body.xpath("./tei:div[@type='preface'][1]", namespaces=ns)[0]
        preface.getparent().remove(preface)
    with pytest.raises(ValueError):
        _body_checks(root, edition, ROOT)


def test_complete_header_rejects_metadata_and_rights_invention(packages):
    profile = json.loads((ROOT / "sources/city-of-god/city-of-god.reconstruction-profile.json").read_bytes())
    for edition in MANIFESTS:
        root = _mutated_root(packages, edition)
        header = root.find(f"{{{TEI}}}teiHeader")
        availability = header.find(f".//{{{TEI}}}availability")
        etree.SubElement(availability, f"{{{TEI}}}p").text = "Definitively public domain worldwide and cleared for publication."
        assert _header_projection(root) != _expected_header(edition, profile)


@pytest.mark.parametrize("mutation", ["body-invention", "note-invention", "chapter-swap", "ref-target", "inline-rendition"])
def test_complete_recursive_projection_rejects_coordinated_resealed_mutations(packages, tmp_path, mutation):
    manifest, package, _ = packages["dods-1871"]
    root = _mutated_root(packages, "dods-1871")
    ns = {"tei": TEI}
    body = root.find(f".//{{{TEI}}}body")
    if mutation == "body-invention":
        invented = etree.SubElement(body, f"{{{TEI}}}div", type="selected-reading", n="invented")
        etree.SubElement(invented, f"{{{TEI}}}p").text = "invented but schema-valid body text"
    elif mutation == "note-invention":
        chapter = body.xpath(".//tei:div[@type='chapter'][1]", namespaces=ns)[0]
        etree.SubElement(chapter, f"{{{TEI}}}note", place="end", n="invented").text = "invented note"
    elif mutation == "chapter-swap":
        book = body.xpath(".//tei:div[@type='book'][1]", namespaces=ns)[0]
        chapters = book.xpath("./tei:div[@type='chapter']", namespaces=ns)
        first_index = book.index(chapters[0]); book.remove(chapters[0]); book.insert(book.index(chapters[1]) + 1, chapters[0])
        assert book.index(chapters[0]) != first_index
    elif mutation == "ref-target":
        body.xpath(".//tei:ref[@target][1]", namespaces=ns)[0].set("target", "invented:target")
    else:
        body.xpath(".//tei:hi[@rend][1]", namespaces=ns)[0].set("rend", "bold")
    expected = _expected_tei(ROOT, "dods-1871", json.loads((ROOT / "sources/city-of-god/city-of-god.reconstruction-profile.json").read_bytes()))
    assert _recursive_projection(root) != _recursive_projection(expected)
    mutated = _resealed_tei_package(package, tmp_path / mutation, root)
    with pytest.raises(ValueError, match="complete recursive TEI projection drifted"):
        _oracle(manifest, mutated)


@pytest.mark.parametrize(
    "source",
    [
        "exec('pass')",
        "eval('1')",
        "__import__('math')",
        "import importlib\nimportlib.import_module('math')",
        "from importlib import import_module as load\nload('math')",
        "import importlib\ngetattr(importlib, 'import_module')('math')",
        "loader.exec_module(None)",
        "import builtins\nbuiltins.exec('pass')",
        "import builtins as b\nb.eval('1')",
        "import builtins as b\nb.compile('pass', '<mutation>', 'exec')",
        "import builtins as b\nb.__import__('math')",
    ],
)
@pytest.mark.parametrize("target", ["oracle", "producer"])
def test_policy_closure_rejects_dynamic_execution_bypasses(monkeypatch, source, target):
    policy = json.loads((ROOT / "sources/city-of-god/city-of-god.validation-policy.json").read_bytes())
    forbidden = tuple(policy["forbidden_runtime_import_prefixes"])
    original_read_text = Path.read_text
    target_path = (ROOT / "build/tei" / f"city_of_god_{target if target == 'oracle' else 'reconstruction'}.py").resolve()

    def dynamic(path: Path, *args, **kwargs):
        text = original_read_text(path, *args, **kwargs)
        return text + "\n" + source + "\n" if path.resolve() == target_path else text

    monkeypatch.setattr(Path, "read_text", dynamic)
    with pytest.raises(ValueError, match="dynamic"):
        (_closure(ROOT, forbidden) if target == "oracle" else _producer_closure(ROOT, forbidden))


def test_policy_closure_rejects_forbidden_import_and_runtime_shadow(monkeypatch, tmp_path):
    policy = json.loads((ROOT / "sources/city-of-god/city-of-god.validation-policy.json").read_bytes())
    forbidden = tuple(policy["forbidden_runtime_import_prefixes"])
    original_read_text = Path.read_text
    oracle_path = (ROOT / "build/tei/city_of_god_oracle.py").resolve()

    def forbidden_import(path: Path, *args, **kwargs):
        text = original_read_text(path, *args, **kwargs)
        return text + "\nimport build.reconstruction.city_of_god.city_candidates\n" if path.resolve() == oracle_path else text

    monkeypatch.setattr(Path, "read_text", forbidden_import)
    with pytest.raises(ValueError, match="forbidden runtime import"):
        _closure(ROOT, forbidden)
    monkeypatch.setattr(Path, "read_text", original_read_text)
    module = importlib.import_module("build.tei.city_of_god_oracle")
    shadow = tmp_path / "city_of_god_oracle.py"; shadow.write_text("# shadow\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(shadow))
    with pytest.raises(ValueError, match="shadow"):
        _closure(ROOT, forbidden)


def test_direct_recursive_closures_exclude_package_initializers_and_bind_contract(monkeypatch):
    policy = json.loads((ROOT / "sources/city-of-god/city-of-god.validation-policy.json").read_bytes())
    forbidden = tuple(policy["forbidden_runtime_import_prefixes"])
    oracle_digest, oracle_records = _closure(ROOT, forbidden)
    producer_digest, producer_records = _producer_closure(ROOT, forbidden)
    shared = {"ocd_kernel/reconstruction/contract.py", "ocd_kernel/lib/path_io.py", "ocd_kernel/lib/storage_topology.py"}
    assert {item["path"] for item in oracle_records} == {"build/tei/city_of_god_oracle.py", *shared}
    assert {item["path"] for item in producer_records} == {"build/tei/city_of_god_reconstruction.py", *shared}
    assert all(not str(item["path"]).endswith("/__init__.py") for item in oracle_records + producer_records)
    assert oracle_digest == _sha(_canonical(oracle_records))
    assert producer_digest == _sha(_canonical(producer_records))

    original_read_text = Path.read_text
    oracle_path = (ROOT / "build/tei/city_of_god_oracle.py").resolve()

    def unrelated_initializer_drift(path: Path, *args, **kwargs):
        text = original_read_text(path, *args, **kwargs)
        return text + "\n# unrelated external initializer drift\n" if path.name == "__init__.py" else text

    monkeypatch.setattr(Path, "read_text", unrelated_initializer_drift)
    assert _closure(ROOT, forbidden) == (oracle_digest, oracle_records)
    assert _producer_closure(ROOT, forbidden) == (producer_digest, producer_records)

    def added_direct_dependency(path: Path, *args, **kwargs):
        text = original_read_text(path, *args, **kwargs)
        return text + "\nfrom build.tei.city_of_god_reconstruction import _convert\n" if path.resolve() == oracle_path else text

    monkeypatch.setattr(Path, "read_text", added_direct_dependency)
    expanded_digest, expanded_records = _closure(ROOT, forbidden)
    assert expanded_digest != oracle_digest
    assert "build/tei/city_of_god_reconstruction.py" in {item["path"] for item in expanded_records}


def test_direct_closures_ignore_unrelated_preloaded_forbidden_module():
    policy = json.loads((ROOT / "sources/city-of-god/city-of-god.validation-policy.json").read_bytes())
    forbidden = tuple(policy["forbidden_runtime_import_prefixes"])
    oracle_closure = _closure(ROOT, forbidden)
    producer_closure = _producer_closure(ROOT, forbidden)

    preloaded = importlib.import_module("cvw_app.review_contract")
    assert preloaded.__name__.startswith("cvw_app.")
    assert _closure(ROOT, forbidden) == oracle_closure
    assert _producer_closure(ROOT, forbidden) == producer_closure


def test_manifest_binds_complete_direct_authorities():
    required = {
        "reconstruction-profile",
        "validation-policy",
        "source-accountability-schema",
        "tei-p5-xsd",
        "candidate-package-schema",
    }
    for path in MANIFESTS.values():
        record = json.loads(path.read_bytes())
        names = {item["name"] for item in record["authorities"]}
        assert required <= names
        for item in record["authorities"]:
            authority = ROOT / item["path"]
            assert authority.stat().st_size == item["bytes"]
            assert _sha(authority.read_bytes()) == item["sha256"]


def test_coordinated_producer_closure_reseal_is_rejected(packages, tmp_path):
    manifest, package, _ = packages["dods-1871"]
    provenance = json.loads(package.member_bytes("provenance.json"))
    invented = [{"path": "build/tei/invented.py", "bytes": 0, "sha256": _sha(b"")}]
    provenance["producer_closure"] = invented
    provenance["producer_closure_sha256"] = _sha(_canonical(invented))
    mutated = _resealed_member_package(package, tmp_path / "closure-reseal", "provenance.json", _canonical(provenance))
    with pytest.raises(ValueError, match="provenance, closure"):
        _oracle(manifest, mutated)


def test_forbidden_claim_policy_rejects_coordinated_readme_reseal(packages, tmp_path):
    package = packages["dods-1871"][1]
    content = package.member_bytes("README.source.md") + b"\nThis candidate is canonical and cleared for publication.\n"
    mutated = _resealed_member_package(package, tmp_path / "claim", "README.source.md", content)
    policy = json.loads((ROOT / "sources/city-of-god/city-of-god.validation-policy.json").read_bytes())
    with pytest.raises(ValueError, match="forbidden"):
        _enforce_forbidden_claims(mutated, tuple(policy["forbidden_claims"]))


def test_runtime_imports_have_no_incumbent_city_or_acceptance_dependency():
    producer = importlib.import_module("build.tei.city_of_god_reconstruction")
    oracle = importlib.import_module("build.tei.city_of_god_oracle")
    for module in (producer, oracle):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "build.reconstruction.city_of_god" not in source
        assert "cvw_app" not in source
        assert "current-master" not in source
        assert "reports/" not in source


def test_source_authority_and_manifest_drift_are_rejected(tmp_path):
    source = MANIFESTS["dods-1871"]
    copy = tmp_path / source.name
    record = json.loads(source.read_bytes())
    record["converter"]["implementation_sha256"] = "0" * 64
    copy.write_bytes(_canonical(record))
    with pytest.raises(ValueError):
        SourceManifest.load(copy, repository_root=ROOT)
