from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from lxml import etree

import pytest

from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)
from build.tei.naves_topical_bible_reconstruction import _source_paths


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = (
    ROOT / 'tests/fixtures/reconstruction-runtime/naves_topical_bible_oracle.source-manifest.json'
)
RAW_ROOT = Path("D:/Library/Open Christian Data/raw/naves_topical")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mirror(tmp_path: Path) -> tuple[Path, object, object]:
    mirror = tmp_path / "external-mirror"
    relatives = [
        SOURCE_MANIFEST.relative_to(ROOT),
        Path("sources/naves-topical-bible"),
        Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"),
        Path("ocd_kernel/tei/vendor/xsd"),
        Path("build/__init__.py"),
        Path("build/tei/__init__.py"),
        Path("build/tei/naves_topical_bible_reconstruction.py"),
        Path("build/tei/naves_topical_bible_oracle.py"),
        Path("ocd_kernel/__init__.py"),
        Path("ocd_kernel/reconstruction/__init__.py"),
        Path("ocd_kernel/reconstruction/contract.py"),
        Path("ocd_kernel/lib/__init__.py"),
        Path("ocd_kernel/lib/path_io.py"),
        Path("ocd_kernel/lib/storage_topology.py"),
    ]
    for relative in relatives:
        target = mirror / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.is_dir():
            shutil.copytree(ROOT / relative, target)
        else:
            shutil.copy2(ROOT / relative, target)
    shutil.copytree(RAW_ROOT, mirror / "raw/naves_topical")
    producer = _load(
        mirror / "build/tei/naves_topical_bible_reconstruction.py",
        "naves_mirror_producer",
    )
    oracle = _load(
        mirror / "build/tei/naves_topical_bible_oracle.py",
        "naves_mirror_oracle",
    )
    return mirror, producer._convert, oracle._oracle


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _reseal_member(destination: Path, name: str, content: bytes) -> CandidatePackage:
    (destination / name).write_bytes(content)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for member in manifest["members"]:
        if member["name"] == name:
            member["bytes"] = len(content)
            member["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(destination)


def _reseal_source_authority(
    mirror: Path, authority_name: str, content: bytes
) -> SourceManifest:
    manifest_path = mirror / SOURCE_MANIFEST.relative_to(ROOT)
    manifest = json.loads(manifest_path.read_bytes())
    authority = next(
        item for item in manifest["authorities"] if item["name"] == authority_name
    )
    target = mirror / authority["path"]
    target.write_bytes(content)
    authority["bytes"] = len(content)
    authority["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_bytes(_canonical(manifest))
    return SourceManifest.load(manifest_path, repository_root=mirror)


def _reseal_source_manifest(
    mirror: Path, manifest: dict[str, object]
) -> SourceManifest:
    manifest_path = mirror / SOURCE_MANIFEST.relative_to(ROOT)
    manifest_path.write_bytes(_canonical(manifest))
    return SourceManifest.load(manifest_path, repository_root=mirror)


def test_naves_source_paths_keep_manifest_logical_paths_across_raw_junctions() -> None:
    source = SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)
    paths = _source_paths(source)
    assert set(paths) == {
        "dict-zdt",
        "dict-zdx",
        "dict-dat",
        "dict-idx",
        "nave-conf",
        "nave-archive",
    }


def test_naves_public_contract_preserves_complete_source_and_is_deterministic(
    tmp_path: Path,
) -> None:
    mirror, convert, oracle = _mirror(tmp_path)
    source_path = mirror / SOURCE_MANIFEST.relative_to(ROOT)
    source = SourceManifest.load(source_path, repository_root=mirror)
    destination = tmp_path / "candidate"
    candidate = reconstruct(source, destination, convert)
    report = validate(source, candidate, oracle)

    assert report.status == "pass"
    assert candidate.manifest["status"] == "nonaccepted"
    assert candidate.manifest["source_id"] == "crosswire-nave-sword-v3"
    assert candidate.member_names == (
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    )

    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    assert len(root.xpath(".//tei:entryFree", namespaces=ns)) == 5_322
    assert (
        len(root.xpath(".//tei:form[@type='dictionary-key']/tei:orth", namespaces=ns))
        == 5_322
    )
    assert len(root.xpath(".//tei:ref[@type='osisRef']", namespaces=ns)) == 77_935
    assert len(root.xpath(".//tei:ref[not(@type)]", namespaces=ns)) == 4_368

    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["binary_census"]["index_entries"] == 5_322
    assert accountability["binary_census"]["compressed_blocks"] == 178
    assert accountability["binary_census"]["payload_bytes"] == 4_572_516
    assert accountability["binary_census"]["payload_body_bytes"] == 4_567_194
    assert accountability["binary_census"]["terminal_nul_count"] == 5_322
    assert accountability["binary_census"]["allocation_padding_bytes"] == 182_272
    assert accountability["transformation_source_set"]["sha256"] == (
        "8c5cf1cc42248214ba0d9e0fda51c99925b9a06760a71dd2a33a5750e09afc6d"
    )
    assert accountability["observation_counts"] == {
        "dictionary_keys": 5_322,
        "readable_payload_bodies": 5_322,
        "terminal_nuls_disposed": 5_322,
        "represented": 10_644,
        "structural_controls": 27_500,
        "disposed": 5_322,
        "unexplained": 0,
        "duplicate": 0,
    }
    assert all(row["terminal_nul_bytes"] == 1 for row in accountability["crosswalk"])
    assert all(
        block["allocation_padding_bytes"] == 1_024 for block in accountability["blocks"]
    )
    case_differences = [
        (
            node.find("tei:form/tei:orth", namespaces=ns).text,
            node.get("n"),
        )
        for node in root.xpath(".//tei:entryFree", namespaces=ns)
        if node.find("tei:form/tei:orth", namespaces=ns).text != node.get("n")
    ]
    assert case_differences == [
        ("ANGEL (A SPIRIT)", "ANGEL (a spirit)"),
        ("ANGEL (HOLY TRINITY)", "ANGEL (Holy Trinity)"),
        ("MINISTER, CHRISTIAN", "MINISTER, Christian"),
        ("MINISTER, CIVIL", "MINISTER, Civil"),
        ("TONGUES (THE GIFT)", "TONGUES (the gift)"),
    ]

    script = (
        "from pathlib import Path; import sys; sys.path.insert(0, sys.argv[2]); "
        "from build.tei.naves_topical_bible_reconstruction import _convert; "
        "from ocd_kernel.reconstruction import SourceManifest, reconstruct; "
        f"s=SourceManifest.load(Path(sys.argv[2]) / Path(r'{SOURCE_MANIFEST.relative_to(ROOT)}'), "
        "repository_root=Path(sys.argv[2])); "
        "reconstruct(s, Path(sys.argv[1]), _convert)"
    )
    fresh = tmp_path / "fresh"
    subprocess.run(
        [sys.executable, "-c", script, str(fresh), str(mirror)],
        check=True,
        cwd=tmp_path,
    )
    for name in candidate.member_names:
        assert (destination / name).read_bytes() == (fresh / name).read_bytes(), name


def test_naves_oracle_rejects_candidate_fidelity_and_boundary_drift(
    tmp_path: Path,
) -> None:
    mirror, convert, oracle = _mirror(tmp_path)
    source = SourceManifest.load(
        mirror / SOURCE_MANIFEST.relative_to(ROOT), repository_root=mirror
    )
    original = reconstruct(source, tmp_path / "original", convert)
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}

    def mutated_tei(kind: str) -> bytes:
        root = etree.fromstring(original.member_bytes("content.tei.xml"))
        body = root.find(".//tei:body", namespaces=ns)
        assert body is not None
        entries = body.findall("tei:entryFree", namespaces=ns)
        assert len(entries) == 5_322
        if kind == "omission":
            body.remove(entries[0])
        elif kind == "duplication":
            body.insert(1, etree.fromstring(etree.tostring(entries[0])))
        elif kind == "reordering":
            body.remove(entries[0])
            body.insert(1, entries[0])
        elif kind == "invention":
            etree.SubElement(
                entries[0], "{http://www.tei-c.org/ns/1.0}note"
            ).text = "invented"
        elif kind == "text":
            definition = entries[0].find("tei:def", namespaces=ns)
            assert definition is not None and definition.text is not None
            definition.text = definition.text.replace("\n", "\nALTERED", 1)
        elif kind == "metadata":
            title = root.find(".//tei:title", namespaces=ns)
            assert title is not None
            title.text = "Altered Nave title"
        elif kind == "dictionary-key":
            orth = entries[0].find("tei:form/tei:orth", namespaces=ns)
            assert orth is not None
            orth.text = "INVENTED KEY"
        else:
            raise AssertionError(kind)
        return etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        )

    for mutation in (
        "omission",
        "duplication",
        "reordering",
        "invention",
        "text",
        "metadata",
        "dictionary-key",
    ):
        destination = tmp_path / f"candidate-{mutation}"
        shutil.copytree(original.path, destination)
        candidate = _reseal_member(
            destination, "content.tei.xml", mutated_tei(mutation)
        )
        with pytest.raises(ValueError, match="Nave candidate"):
            validate(source, candidate, oracle)

    provenance_path = tmp_path / "candidate-provenance"
    shutil.copytree(original.path, provenance_path)
    provenance = json.loads((provenance_path / "provenance.json").read_bytes())
    provenance["candidate_boundary"]["publication"] = "ready"
    provenance_candidate = _reseal_member(
        provenance_path, "provenance.json", _canonical(provenance)
    )
    with pytest.raises(ValueError, match="provenance"):
        validate(source, provenance_candidate, oracle)

    crosswalk_path = tmp_path / "candidate-crosswalk"
    shutil.copytree(original.path, crosswalk_path)
    accountability = json.loads(
        (crosswalk_path / "source-accountability.json").read_bytes()
    )
    accountability["crosswalk"][0]["dictionary_key"] = "INVENTED KEY"
    crosswalk_candidate = _reseal_member(
        crosswalk_path, "source-accountability.json", _canonical(accountability)
    )
    with pytest.raises(ValueError, match="crosswalk|accountability"):
        validate(source, crosswalk_candidate, oracle)

    disposal_path = tmp_path / "candidate-terminal-nul-disposal"
    shutil.copytree(original.path, disposal_path)
    accountability = json.loads(
        (disposal_path / "source-accountability.json").read_bytes()
    )
    accountability["crosswalk"][0]["terminal_nul_disposition"] = "represented"
    accountability["observation_counts"]["terminal_nuls_disposed"] -= 1
    disposal_candidate = _reseal_member(
        disposal_path, "source-accountability.json", _canonical(accountability)
    )
    with pytest.raises(ValueError, match="crosswalk|accountability"):
        validate(source, disposal_candidate, oracle)

    padding_path = tmp_path / "candidate-allocation-padding"
    shutil.copytree(original.path, padding_path)
    accountability = json.loads(
        (padding_path / "source-accountability.json").read_bytes()
    )
    accountability["blocks"][0]["allocation_padding_bytes"] = 0
    accountability["binary_census"]["allocation_padding_bytes"] -= 1_024
    padding_candidate = _reseal_member(
        padding_path, "source-accountability.json", _canonical(accountability)
    )
    with pytest.raises(ValueError, match="crosswalk|accountability"):
        validate(source, padding_candidate, oracle)

    unresolved_path = tmp_path / "candidate-unresolved"
    shutil.copytree(original.path, unresolved_path)
    unresolved_candidate = _reseal_member(unresolved_path, "unresolved.jsonl", b"")
    with pytest.raises(ValueError, match="unresolved"):
        validate(source, unresolved_candidate, oracle)

    manifest_path = tmp_path / "candidate-manifest"
    shutil.copytree(original.path, manifest_path)
    manifest = json.loads((manifest_path / "manifest.json").read_bytes())
    manifest["unexpected"] = "manifest drift"
    (manifest_path / "manifest.json").write_bytes(_canonical(manifest))
    manifest_candidate = CandidatePackage.load(manifest_path)
    with pytest.raises(ValueError, match="candidate-package schema"):
        validate(source, manifest_candidate, oracle)


def test_naves_rejects_source_scope_drift_at_producer_validator_and_oracle(
    tmp_path: Path,
) -> None:
    mirror, convert, oracle = _mirror(tmp_path)
    manifest_path = mirror / SOURCE_MANIFEST.relative_to(ROOT)
    source = SourceManifest.load(manifest_path, repository_root=mirror)
    candidate = reconstruct(source, tmp_path / "candidate", convert)
    manifest = json.loads(manifest_path.read_bytes())
    manifest["retained_file_census"][5]["disposition"] = "second-witness"
    manifest_path.write_bytes(_canonical(manifest))
    drifted = SourceManifest.load(manifest_path, repository_root=mirror)
    with pytest.raises(ValueError, match="scope"):
        reconstruct(drifted, tmp_path / "drifted", convert)
    with pytest.raises(ValueError, match="candidate source manifest binding mismatch"):
        validate(drifted, candidate, oracle)
    # Public validation rejects the stale package first; call the oracle directly
    # to exercise its independent source-scope guard.
    with pytest.raises(ValueError, match="scope"):
        oracle(drifted, candidate)


@pytest.mark.parametrize(
    ("authority", "mutation", "message"),
    [
        ("dict-idx", "truncate", "truncated|misaligned"),
        ("dict-zdt", "compressed", "decompression failed"),
        ("dict-idx", "offset", "separator|coverage|offset"),
    ],
)
def test_naves_rejects_truncated_malformed_and_index_mismatch_sources(
    tmp_path: Path, authority: str, mutation: str, message: str
) -> None:
    mirror, convert, _ = _mirror(tmp_path)
    manifest = json.loads((mirror / SOURCE_MANIFEST.relative_to(ROOT)).read_bytes())
    record = next(item for item in manifest["authorities"] if item["name"] == authority)
    original = (mirror / record["path"]).read_bytes()
    if mutation == "truncate":
        changed = original[:-1]
    elif mutation == "compressed":
        changed = b"\x00" + original[1:]
    elif mutation == "offset":
        changed = b"\x01\x00\x00\x00" + original[4:]
    else:
        raise AssertionError(mutation)
    source = _reseal_source_authority(mirror, authority, changed)
    with pytest.raises(ValueError, match=message):
        reconstruct(source, tmp_path / "candidate", convert)


def test_naves_oracle_is_structurally_independent_of_producer_and_legacy_parser() -> (
    None
):
    oracle_path = ROOT / "build/tei/naves_topical_bible_oracle.py"
    text = oracle_path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "build.tei.naves_topical_bible_reconstruction" not in imported
    assert "build.parsers.naves_topical" not in imported
    assert "naves_topical_bible_reconstruction" not in text
    assert "build.parsers.naves_topical" not in text
    assert "_convert" not in text
    assert "import zipfile" not in text
    assert "struct.unpack" not in text
    assert "etree.fromstring(payload" not in text
    assert "xml.etree" in text


@pytest.mark.parametrize(
    "payload",
    [
        b"<entryFree n='A'><def>A</def></entryFree>",
        b"<entryFree n='A'><def>A</def></entryFree>\x00\x00",
        b"<entryFree n='A'><def>A\x00</def></entryFree>\x00",
        b"<entryFree n='A'><def>A</def></entryFree>\x01",
    ],
)
def test_naves_producer_and_oracle_reject_terminal_nul_envelope_drift(
    payload: bytes,
) -> None:
    producer = _load(
        ROOT / "build/tei/naves_topical_bible_reconstruction.py",
        f"naves_terminal_producer_{hashlib.sha256(payload).hexdigest()}",
    )
    oracle = _load(
        ROOT / "build/tei/naves_topical_bible_oracle.py",
        f"naves_terminal_oracle_{hashlib.sha256(payload).hexdigest()}",
    )
    with pytest.raises(ValueError, match="terminal NUL|terminal-NUL"):
        producer._split_payload(payload, 1)
    with pytest.raises(ValueError, match="terminal NUL|terminal-NUL"):
        oracle._split_payload(payload, 1)


def test_naves_producer_rejects_archive_metadata_drift_with_same_payloads(
    tmp_path: Path,
) -> None:
    mirror, convert, _ = _mirror(tmp_path)
    archive_path = mirror / "raw/naves_topical/Nave.zip"
    with zipfile.ZipFile(archive_path) as archive:
        members = [(info.filename, archive.read(info)) for info in archive.infolist()]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            info = zipfile.ZipInfo(name, date_time=(2021, 3, 11, 10, 26, 30))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    source = _reseal_source_authority(mirror, "nave-archive", stream.getvalue())
    with pytest.raises(ValueError, match="archive|Nave.zip|metadata"):
        reconstruct(source, tmp_path / "candidate", convert)


@pytest.mark.parametrize(
    ("authority", "mutation"),
    [
        ("reconstruction-profile", "json-field"),
        ("validation-policy", "json-field"),
        ("source-accountability-schema", "json-field"),
        ("source-attribution-readme", "bytes"),
        ("tei-p5-xsd-teix", "bytes"),
        ("tei-p5-xsd-xml", "bytes"),
    ],
)
def test_naves_oracle_rejects_resealed_local_and_schema_authorities(
    tmp_path: Path, authority: str, mutation: str
) -> None:
    mirror, convert, oracle = _mirror(tmp_path)
    manifest = json.loads((mirror / SOURCE_MANIFEST.relative_to(ROOT)).read_bytes())
    record = next(item for item in manifest["authorities"] if item["name"] == authority)
    original = (mirror / record["path"]).read_bytes()
    if mutation == "json-field":
        changed = json.loads(original)
        changed["resealed_untrusted_field"] = authority
        content = _canonical(changed)
    else:
        content = (
            original + b"\n<!-- resealed authority drift -->\n"
            if authority.startswith("tei-")
            else original + b"\nRESEALED\n"
        )
    source = _reseal_source_authority(mirror, authority, content)
    candidate = reconstruct(source, tmp_path / "candidate", convert)
    with pytest.raises(ValueError, match="authority|profile|policy|schema|README"):
        validate(source, candidate, oracle)


def test_naves_oracle_rejects_resealed_authority_role_drift(tmp_path: Path) -> None:
    mirror, convert, oracle = _mirror(tmp_path)
    manifest_path = mirror / SOURCE_MANIFEST.relative_to(ROOT)
    manifest = json.loads(manifest_path.read_bytes())
    record = next(
        item for item in manifest["authorities"] if item["name"] == "dict-zdt"
    )
    record["role"] = "primary-source-tampered"
    source = _reseal_source_manifest(mirror, manifest)
    candidate = reconstruct(source, tmp_path / "candidate", convert)
    with pytest.raises(ValueError, match="authority"):
        validate(source, candidate, oracle)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("converter.version", "999"),
        ("package_schema.sha256", "0" * 64),
    ],
)
def test_naves_oracle_rejects_complete_candidate_manifest_semantic_drift(
    tmp_path: Path, field: str, value: str
) -> None:
    mirror, convert, oracle = _mirror(tmp_path)
    source = SourceManifest.load(
        mirror / SOURCE_MANIFEST.relative_to(ROOT), repository_root=mirror
    )
    destination = tmp_path / "candidate"
    reconstruct(source, destination, convert)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    parent, child = field.split(".")
    manifest[parent][child] = value
    manifest_path.write_bytes(_canonical(manifest))
    candidate = CandidatePackage.load(destination)
    with pytest.raises(ValueError, match="manifest"):
        validate(source, candidate, oracle)


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("package_schema", "sha256"),
        ("converter", "implementation_sha256"),
        ("validator", "implementation_sha256"),
        ("validator", "import_closure_sha256"),
    ],
)
def test_naves_oracle_rejects_resealed_stale_schema_and_code_pins(
    tmp_path: Path, section: str, field: str
) -> None:
    mirror, convert, oracle = _mirror(tmp_path)
    manifest_path = mirror / SOURCE_MANIFEST.relative_to(ROOT)
    manifest = json.loads(manifest_path.read_bytes())
    manifest[section][field] = "0" * 64
    if field != "import_closure_sha256":
        with pytest.raises(ValueError, match="authority drifted"):
            _reseal_source_manifest(mirror, manifest)
        return
    drifted = _reseal_source_manifest(mirror, manifest)
    candidate = reconstruct(drifted, tmp_path / "candidate", convert)
    with pytest.raises(ValueError, match="pin drifted"):
        validate(drifted, candidate, oracle)
