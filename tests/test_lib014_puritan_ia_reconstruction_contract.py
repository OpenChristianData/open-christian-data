from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from jsonschema import Draft202012Validator
from lxml import etree
import pytest

from ocd_kernel.reconstruction.contract import CandidatePackage, validate


ROOT = Path(__file__).resolve().parents[1]
RAW = Path("D:/Library/Open Christian Data/raw/ia")
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCES = {
    "brooks-precious-remedies": (
        "brooks_precious_remedies.txt",
        360_630,
        "dd9e5a0bd0b875939b3dc2bd5f848b84988a99c53ce8451f3222c34c58547cdb",
        8_526,
    ),
    "burroughs-rare-jewel-contentment": (
        "burroughs_rare_jewel.txt",
        454_509,
        "fed949f533923e8d4291df1b7eb04644fbe59f743cb732e67dbc8768f26c59d6",
        8_212,
    ),
    "gurnall-complete-armour": (
        "gurnall_complete_armour.txt",
        4_672_135,
        "aa145a5411d1f87b35cde03407e9c4db4cc0a003a550821c3a9c73d54be2c4fa",
        57_974,
    ),
    "sibbes-bruised-reed": (
        "sibbes_bruised_reed.txt",
        251_397,
        "b98f1e3819cfa3ee8c5c9e34fe24d5c9b3960ff94b5e4539cb0f9c06221ab52e",
        7_171,
    ),
}


def _manifest(work_id: str) -> Path:
    return ROOT / "tests/fixtures/reconstruction-runtime" / f"lib014-{work_id}.source-manifest.json"


def test_runtime_fixtures_preserve_retained_records_and_only_update_runtime_bindings() -> None:
    from build.tei import lib014_puritan_ia_oracle as oracle
    from build.tei import lib014_puritan_ia_reconstruction as producer

    retained_sha256 = {
        "brooks-precious-remedies": "50674e8b7041f5bd27c8f623a5a0100bc25bef0533e20fd7e3961401a14a711a",
        "burroughs-rare-jewel-contentment": "eeb2fe5b7c82eb30a26e99ddbe08e2dd401ba1eed7156c3da17648975760d0f1",
        "gurnall-complete-armour": "9ff4e8ec7d51367d31c8d3c6eacf354f999532819ea8bbdd7be3622a001ceb98",
        "sibbes-bruised-reed": "8ad3a3db9e17ae25d1ef9f03463106fa7d3ac34df8bf72454fed90aee080af2f",
    }
    assert set(retained_sha256) == set(SOURCES)
    for work_id, digest in retained_sha256.items():
        raw = (ROOT / "sources" / work_id / "LIB-014.source-manifest.json").read_bytes()
        assert _sha(raw) == digest
        expected = json.loads(raw)
        for name, module in (("converter", producer), ("validator", oracle)):
            expected[name]["implementation_sha256"] = _sha(Path(module.__file__).read_bytes())
        expected["producer_import_closure_sha256"] = producer._closure_digest(ROOT, Path(producer.__file__))
        expected["validator"]["import_closure_sha256"] = oracle._closure_digest(ROOT, Path(oracle.__file__))
        assert json.loads(_manifest(work_id).read_bytes()) == expected


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_exact_external_witness_identity_and_complete_direct_file_census(
    work_id: str,
) -> None:
    from build.tei.lib014_puritan_ia_reconstruction import inspect_witness

    filename, byte_count, digest, line_count = SOURCES[work_id]
    witness = inspect_witness(work_id, RAW / filename)
    assert witness.byte_count == byte_count
    assert witness.sha256 == digest
    assert witness.line_count == line_count
    assert witness.content.count(b"\n") == line_count
    assert witness.content.count(b"\r") == 0
    assert witness.content.endswith(b"\n")
    manifest = json.loads(_manifest(work_id).read_bytes())
    primary = [
        item for item in manifest["authorities"] if item["role"] == "primary-source"
    ]
    assert primary == [
        {
            "name": "retained-source",
            "path": f"raw/ia/{filename}",
            "role": "primary-source",
            "bytes": byte_count,
            "sha256": digest,
        }
    ]


@pytest.mark.parametrize("mutation", ["byte", "omission", "duplication", "reordering"])
def test_source_identity_mutations_fail_closed(mutation: str, tmp_path: Path) -> None:
    from build.tei.lib014_puritan_ia_reconstruction import inspect_witness

    work_id = "brooks-precious-remedies"
    content = bytearray((RAW / SOURCES[work_id][0]).read_bytes())
    if mutation == "byte":
        content[100] ^= 1
    else:
        records = bytes(content).splitlines(keepends=True)
        if mutation == "omission":
            records.pop(100)
        elif mutation == "duplication":
            records.insert(100, records[100])
        else:
            records[100], records[101] = records[101], records[100]
        content = bytearray(b"".join(records))
    path = tmp_path / "mutated.txt"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        inspect_witness(work_id, path)


@pytest.mark.slow
@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_candidate_is_lossless_dual_schema_valid_oracle_accepted_and_nonaccepted(
    work_id: str, tmp_path: Path
) -> None:
    from build.tei.lib014_puritan_ia_oracle import _compiled_schema, _oracle
    from build.tei.lib014_puritan_ia_reconstruction import (
        build_candidate,
        load_source_manifest,
    )

    filename, byte_count, digest, line_count = SOURCES[work_id]
    manifest = load_source_manifest(
        _manifest(work_id), repository_root=ROOT, witness_path=RAW / filename
    )
    candidate = build_candidate(manifest, tmp_path / "candidate")
    report = validate(manifest, candidate, _oracle)  # type: ignore[arg-type]
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    Draft202012Validator(
        json.loads(
            (
                ROOT / "sources" / work_id / "LIB-014.source-accountability.schema.json"
            ).read_bytes()
        )
    ).validate(accountability)
    tree = etree.ElementTree(
        etree.fromstring(candidate.member_bytes("content.tei.xml"))
    )
    _compiled_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd").assertValid(tree)
    assert report.status == "pass"
    assert report.findings == ()
    assert report.attestation["source_sha256"] == digest
    assert candidate.manifest["status"] == "nonaccepted"
    assert accountability["source_bytes"] == byte_count
    assert (
        accountability["physical_lines"]
        == accountability["represented_lines"]
        == line_count
    )
    assert accountability["omitted_lines"] == accountability["duplicated_lines"] == 0
    assert accountability["excluded_members"] == []
    assert len(accountability["crosswalk"]) == line_count
    assert accountability["crosswalk"][0]["byte_start"] == 0
    assert accountability["crosswalk"][-1]["byte_end"] == byte_count
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["candidate_status"] == "nonaccepted"
    assert provenance["publication_authorized"] is False
    assert provenance["technical_validation_is_human_acceptance"] is False


def test_sibbes_google_wrapper_and_attribution_readme_are_retained() -> None:
    profile = json.loads(
        (ROOT / "sources/sibbes-bruised-reed/LIB-014.source-profile.json").read_bytes()
    )
    readme = (ROOT / "sources/sibbes-bruised-reed/LIB-014.README.source.md").read_text(
        encoding="utf-8"
    )
    source_lines = (
        (RAW / "sibbes_bruised_reed.txt").read_text(encoding="utf-8").splitlines()
    )
    assert profile["source"]["digitization_wrapper_lines"] == 48
    assert "Maintain attribution" in "\n".join(source_lines[:48])
    assert "maintain Google attribution/watermark" in readme
    assert "publication is unauthorized" in readme


def test_oracle_has_no_producer_dependency() -> None:
    source = (ROOT / "build/tei/lib014_puritan_ia_oracle.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imports = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]
    assert "build.tei.lib014_puritan_ia_reconstruction" not in imports
    assert "_convert" not in source


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member["bytes"] = len(content)
    member["sha256"] = hashlib.sha256(content).hexdigest()
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


@pytest.fixture(scope="module")
def mutation_bundle(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[object, CandidatePackage]:
    from build.tei.lib014_puritan_ia_reconstruction import (
        build_candidate,
        load_source_manifest,
    )

    work_id = "brooks-precious-remedies"
    root = tmp_path_factory.mktemp("lib014-mutation")
    manifest = load_source_manifest(
        _manifest(work_id), repository_root=ROOT, witness_path=RAW / SOURCES[work_id][0]
    )
    return manifest, build_candidate(manifest, root / "candidate")


def _closure_mirror(tmp_path: Path, work_id: str) -> Path:
    mirror = tmp_path / f"lib014-closure-{work_id}"
    source_dir = ROOT / "sources" / work_id
    mirror_source_dir = mirror / "sources" / work_id
    mirror_source_dir.mkdir(parents=True)
    for path in source_dir.glob("LIB-014.*"):
        shutil.copy2(path, mirror_source_dir / path.name)
    shutil.copy2(_manifest(work_id), mirror_source_dir / "LIB-014.source-manifest.json")
    for relative in (
        "build/__init__.py",
        "build/tei/__init__.py",
        "build/tei/lib014_puritan_ia_reconstruction.py",
        "build/tei/lib014_puritan_ia_oracle.py",
        "ocd_kernel/__init__.py",
        "ocd_kernel/lib/__init__.py",
        "ocd_kernel/lib/path_io.py",
        "ocd_kernel/lib/storage_topology.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    ):
        destination = mirror / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    shutil.copytree(
        ROOT / "ocd_kernel/tei/vendor/xsd",
        mirror / "ocd_kernel/tei/vendor/xsd",
    )
    return mirror


def _load_closure_manifest(mirror: Path, work_id: str) -> object:
    from build.tei.lib014_puritan_ia_reconstruction import load_source_manifest

    return load_source_manifest(
        mirror / "sources" / work_id / "LIB-014.source-manifest.json",
        repository_root=mirror,
        witness_path=RAW / SOURCES[work_id][0],
    )


def _closure_manifest(tmp_path: Path, work_id: str) -> tuple[Path, object]:
    mirror = _closure_mirror(tmp_path, work_id)
    return mirror, _load_closure_manifest(mirror, work_id)


def _mutated_closure_manifest(
    tmp_path: Path, target: str, mutation: str
) -> tuple[Path, object]:
    from build.tei.lib014_puritan_ia_oracle import _closure as oracle_closure
    from build.tei.lib014_puritan_ia_reconstruction import _closure as producer_closure

    work_id = "brooks-precious-remedies"
    mirror = _closure_mirror(tmp_path, work_id)
    contract_path = mirror / "ocd_kernel/reconstruction/contract.py"
    if mutation == "resealed":
        contract_path.write_bytes(
            contract_path.read_bytes() + b"\n# coordinated closure reseal\n"
        )
    producer_records = producer_closure(
        mirror, mirror / "build/tei/lib014_puritan_ia_reconstruction.py"
    )
    oracle_records = oracle_closure(
        mirror, mirror / "build/tei/lib014_puritan_ia_oracle.py"
    )
    if mutation == "incomplete":
        digest = _sha(
            _canonical(
                (producer_records if target == "producer" else oracle_records)[:-1]
            )
        )
    elif mutation == "forged":
        digest = "0" * 64
    else:
        digest = _sha(
            _canonical(producer_records if target == "producer" else oracle_records)
        )
    manifest_path = mirror / "sources" / work_id / "LIB-014.source-manifest.json"
    record = json.loads(manifest_path.read_bytes())
    if mutation == "resealed":
        record["producer_import_closure_sha256"] = _sha(_canonical(producer_records))
        record["validator"]["import_closure_sha256"] = _sha(_canonical(oracle_records))
    elif target == "producer":
        record["producer_import_closure_sha256"] = digest
    else:
        record["validator"]["import_closure_sha256"] = digest
    manifest_path.write_bytes(_canonical(record))
    return mirror, _load_closure_manifest(mirror, work_id)


def test_producer_and_oracle_closures_are_complete_and_pinned(
    tmp_path: Path,
) -> None:
    from build.tei.lib014_puritan_ia_oracle import _closure as oracle_closure
    from build.tei.lib014_puritan_ia_reconstruction import (
        _closure as producer_closure,
        _closure_digest,
        _verify_closure,
    )
    from build.tei.lib014_puritan_ia_oracle import _verify_closures

    mirror, manifest = _closure_manifest(tmp_path, "brooks-precious-remedies")
    producer_records = producer_closure(
        mirror, mirror / "build/tei/lib014_puritan_ia_reconstruction.py"
    )
    oracle_records = oracle_closure(
        mirror, mirror / "build/tei/lib014_puritan_ia_oracle.py"
    )
    expected_common = {
        "ocd_kernel/__init__.py",
        "ocd_kernel/lib/__init__.py",
        "ocd_kernel/lib/path_io.py",
        "ocd_kernel/lib/storage_topology.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
    }
    assert {item["path"] for item in producer_records} == expected_common | {
        "build/tei/lib014_puritan_ia_reconstruction.py"
    }
    assert {item["path"] for item in oracle_records} == expected_common | {
        "build/tei/lib014_puritan_ia_oracle.py"
    }
    producer_digest = _sha(_canonical(producer_records))
    oracle_digest = _sha(_canonical(oracle_records))
    assert producer_digest == manifest.record["producer_import_closure_sha256"]
    assert oracle_digest == manifest.record["validator"]["import_closure_sha256"]
    assert (
        _closure_digest(
            mirror, mirror / "build/tei/lib014_puritan_ia_reconstruction.py"
        )
        == producer_digest
    )
    assert _verify_closure(manifest) == producer_digest
    assert _verify_closures(
        manifest, manifest.record["converter"], manifest.record["validator"]
    ) == (producer_digest, oracle_digest)


@pytest.mark.parametrize("target", ["producer", "oracle"])
@pytest.mark.parametrize("mutation", ["incomplete", "forged", "resealed"])
def test_coordinated_import_closure_attacks_are_rejected(
    tmp_path: Path, target: str, mutation: str
) -> None:
    from build.tei.lib014_puritan_ia_oracle import _verify_closures
    from build.tei.lib014_puritan_ia_reconstruction import _verify_closure

    _, manifest = _mutated_closure_manifest(tmp_path, target, mutation)
    if target == "producer" and mutation != "resealed":
        with pytest.raises(ValueError, match="producer import closure drifted"):
            _verify_closure(manifest)
    elif target == "oracle" and mutation != "resealed":
        _verify_closure(manifest)
    else:
        with pytest.raises(ValueError, match="shared contract closure drifted"):
            _verify_closure(manifest)
    with pytest.raises(ValueError):
        _verify_closures(
            manifest, manifest.record["converter"], manifest.record["validator"]
        )


@pytest.mark.parametrize("target", ["producer", "oracle"])
@pytest.mark.parametrize("mutation", ["dynamic", "escaping"])
def test_import_closure_rejects_dynamic_or_escaping_imports(
    tmp_path: Path, target: str, mutation: str
) -> None:
    from build.tei.lib014_puritan_ia_oracle import _closure as oracle_closure
    from build.tei.lib014_puritan_ia_reconstruction import _closure as producer_closure

    mirror = _closure_mirror(tmp_path, "brooks-precious-remedies")
    if target == "producer":
        path = mirror / "build/tei/lib014_puritan_ia_reconstruction.py"
        closure = producer_closure
    else:
        path = mirror / "build/tei/lib014_puritan_ia_oracle.py"
        closure = oracle_closure
    content = path.read_bytes()
    if mutation == "dynamic":
        content += b"\nimport importlib\nimportlib.import_module('build')\n"
    else:
        content += b"\nfrom ....outside import value\n"
    path.write_bytes(content)
    with pytest.raises(ValueError, match="dynamic|escapes"):
        closure(mirror, path)


@pytest.mark.slow
@pytest.mark.parametrize("mutation", ["no-op", "content"])
def test_shared_contract_mutations_fail_before_candidate_oracle_acceptance(
    tmp_path: Path,
    mutation: str,
    mutation_bundle: tuple[object, CandidatePackage],
) -> None:
    from build.tei.lib014_puritan_ia_oracle import _oracle
    from build.tei.lib014_puritan_ia_reconstruction import (
        _convert,
        _verify_closure,
    )

    mirror = _closure_mirror(tmp_path, "brooks-precious-remedies")
    contract_path = mirror / "ocd_kernel/reconstruction/contract.py"
    original = contract_path.read_bytes()
    if mutation == "no-op":
        mutated = original + b"\n# no-op closure mutation\n"
    else:
        mutated = original.replace(
            b"Small authority-bound reconstruction seam.",
            b"Changed authority-bound reconstruction seam.",
            1,
        )
    assert mutated != original
    contract_path.write_bytes(mutated)
    manifest = _load_closure_manifest(mirror, "brooks-precious-remedies")
    with pytest.raises(ValueError, match="shared contract closure drifted"):
        _verify_closure(manifest)
    with pytest.raises(ValueError, match="shared contract closure drifted"):
        _convert(manifest)
    _, candidate = mutation_bundle
    with pytest.raises(ValueError, match="shared contract closure drifted"):
        _oracle(manifest, candidate)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "reordering",
        "text",
        "work-scope",
        "candidate-metadata",
        "provenance",
        "manifest",
        "unresolved",
        "accountability",
        "readme",
    ],
)
def test_independent_oracle_rejects_resealed_packet_mutations(
    mutation: str, tmp_path: Path, mutation_bundle: tuple[object, CandidatePackage]
) -> None:
    from build.tei.lib014_puritan_ia_oracle import _oracle

    manifest, candidate = mutation_bundle
    path = tmp_path / mutation
    shutil.copytree(candidate.path, path)
    if mutation in {
        "omission",
        "duplication",
        "reordering",
        "text",
        "work-scope",
        "candidate-metadata",
    }:
        root = etree.fromstring((path / "content.tei.xml").read_bytes())
        lines = root.xpath("./tei:text/tei:body/tei:div/tei:ab", namespaces=NS)
        if mutation == "omission":
            lines[100].getparent().remove(lines[100])
        elif mutation == "duplication":
            duplicate = copy.deepcopy(lines[100])
            duplicate.set(XML_ID, "invented-duplicate")
            lines[100].addnext(duplicate)
        elif mutation == "reordering":
            parent = lines[100].getparent()
            parent.remove(lines[100])
            parent.insert(102, lines[100])
        elif mutation == "text":
            lines[100].text = (lines[100].text or "") + " invented"
        elif mutation == "work-scope":
            root.xpath("./tei:text/tei:body/tei:div", namespaces=NS)[0].set(
                XML_ID, "another-work"
            )
        else:
            root.xpath(
                "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS
            )[0].text = "Accepted edition"
        mutated = _reseal(
            path,
            "content.tei.xml",
            etree.tostring(
                root, encoding="UTF-8", xml_declaration=True, pretty_print=False
            ),
        )
    elif mutation == "provenance":
        value = json.loads((path / "provenance.json").read_bytes())
        value["publication_authorized"] = True
        mutated = _reseal(path, "provenance.json", _canonical(value))
    elif mutation == "manifest":
        value = json.loads((path / "manifest.json").read_bytes())
        value["source_manifest"]["sha256"] = "0" * 64
        (path / "manifest.json").write_bytes(_canonical(value))
        mutated = CandidatePackage.load(path)
    elif mutation == "unresolved":
        lines = (path / "unresolved.jsonl").read_bytes().splitlines()
        value = json.loads(lines[0])
        value["detail"] = "resolved"
        lines[0] = _canonical(value).rstrip(b"\n")
        mutated = _reseal(path, "unresolved.jsonl", b"\n".join(lines) + b"\n")
    elif mutation == "accountability":
        value = json.loads((path / "source-accountability.json").read_bytes())
        value["crosswalk"][100]["target"] = "#wrong"
        value["crosswalk_sha256"] = hashlib.sha256(
            _canonical(value["crosswalk"])
        ).hexdigest()
        mutated = _reseal(path, "source-accountability.json", _canonical(value))
    else:
        mutated = _reseal(
            path,
            "README.source.md",
            (path / "README.source.md").read_bytes() + b"\nAccepted.\n",
        )
    with pytest.raises(ValueError):
        validate(manifest, mutated, _oracle)  # type: ignore[arg-type]


@pytest.mark.slow
@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_oracle_rejects_coupled_source_id_reseal(work_id: str, tmp_path: Path) -> None:
    mirror = _closure_mirror(tmp_path, work_id)

    manifest_path = mirror / "sources" / work_id / "LIB-014.source-manifest.json"
    manifest_record = json.loads(manifest_path.read_bytes())
    manifest_record["source_id"] = f"rebound-{work_id}"
    manifest_path.write_bytes(_canonical(manifest_record))
    candidate_path = tmp_path / "candidate"
    mirror_environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(mirror), str(ROOT))),
    }
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "build.tei.lib014_puritan_ia_reconstruction",
            "--repository-root",
            str(mirror),
            "--manifest",
            str(manifest_path),
            "--witness",
            str(RAW / SOURCES[work_id][0]),
            "--output",
            str(candidate_path),
        ],
        cwd=mirror,
        env=mirror_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    validation = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            (
                "import sys; "
                "from build.tei.lib014_puritan_ia_oracle import _oracle; "
                "from build.tei.lib014_puritan_ia_reconstruction import load_source_manifest; "
                "from ocd_kernel.reconstruction.contract import CandidatePackage, validate; "
                "manifest=load_source_manifest(sys.argv[1],repository_root=sys.argv[2],witness_path=sys.argv[3]); "
                "candidate=CandidatePackage.load(sys.argv[4]); "
                "validate(manifest,candidate,_oracle)"
            ),
            str(manifest_path),
            str(mirror),
            str(RAW / SOURCES[work_id][0]),
            str(candidate_path),
        ],
        cwd=mirror,
        env=mirror_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert validation.returncode != 0
    assert "source manifest source_id drift" in validation.stderr


@pytest.mark.slow
@pytest.mark.parametrize(
    ("authority_name", "logical_path"),
    [
        (
            "candidate-package-schema",
            "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
        ),
        ("tei-p5-xsd", "ocd_kernel/tei/vendor/xsd/tei_all.xsd"),
        ("tei-p5-xsd-teix", "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"),
        ("tei-p5-xsd-xml", "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd"),
    ],
)
def test_oracle_rejects_coupled_reseal_of_shared_authority(
    authority_name: str,
    logical_path: str,
    tmp_path: Path,
) -> None:
    from build.tei.lib014_puritan_ia_oracle import _oracle
    from build.tei.lib014_puritan_ia_reconstruction import (
        build_candidate,
        load_source_manifest,
    )

    work_id = "brooks-precious-remedies"
    baseline_manifest = load_source_manifest(
        _manifest(work_id),
        repository_root=ROOT,
        witness_path=RAW / SOURCES[work_id][0],
    )
    candidate_path = tmp_path / "candidate"
    build_candidate(baseline_manifest, candidate_path)
    mirror = _closure_mirror(tmp_path, work_id)

    authority_path = mirror / logical_path
    original = authority_path.read_bytes()
    suffix = (
        b" "
        if authority_path.suffix == ".json"
        else b"\n<!-- coupled reseal probe -->\n"
    )
    mutated_content = original + suffix
    authority_path.write_bytes(mutated_content)

    manifest_path = mirror / "sources" / work_id / "LIB-014.source-manifest.json"
    manifest_record = json.loads(manifest_path.read_bytes())
    authority = next(
        item
        for item in manifest_record["authorities"]
        if item["name"] == authority_name
    )
    authority["bytes"] = len(mutated_content)
    authority["sha256"] = hashlib.sha256(mutated_content).hexdigest()
    if authority_name == "candidate-package-schema":
        manifest_record["package_schema"]["sha256"] = authority["sha256"]
    manifest_path.write_bytes(_canonical(manifest_record))

    manifest = load_source_manifest(
        manifest_path,
        repository_root=mirror,
        witness_path=RAW / SOURCES[work_id][0],
    )
    candidate_record = json.loads((candidate_path / "manifest.json").read_bytes())
    candidate_record["source_manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    candidate_record["package_schema"] = manifest_record["package_schema"]
    (candidate_path / "manifest.json").write_bytes(_canonical(candidate_record))
    candidate = CandidatePackage.load(candidate_path)
    with pytest.raises(ValueError, match="exact authority binding drift"):
        _oracle(manifest, candidate)


@pytest.mark.slow
@pytest.mark.parametrize("work_id", tuple(SOURCES))
def test_fresh_process_different_cwd_complete_packages_are_byte_identical(
    work_id: str, tmp_path: Path
) -> None:
    filename = SOURCES[work_id][0]
    outputs = [tmp_path / "first", tmp_path / "second"]
    for output, cwd in zip(outputs, [ROOT, tmp_path], strict=True):
        subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "build.tei.lib014_puritan_ia_reconstruction",
                "--repository-root",
                str(ROOT),
                "--manifest",
                str(_manifest(work_id)),
                "--witness",
                str(RAW / filename),
                "--output",
                str(output),
            ],
            cwd=cwd,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            check=True,
            capture_output=True,
            text=True,
        )
    expected = [
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    ]
    assert (
        sorted(path.name for path in outputs[0].iterdir())
        == sorted(path.name for path in outputs[1].iterdir())
        == expected
    )
    for name in expected:
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()


def test_cached_schema_still_validates_and_schema_drift_is_checked_fresh(tmp_path):
    from build.tei import lib014_puritan_ia_oracle as oracle

    work_id = "brooks-precious-remedies"
    mirror, manifest = _closure_manifest(tmp_path, work_id)
    xsd = mirror / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
    schema = oracle._compiled_schema(xsd)
    assert schema is oracle._compiled_schema(xsd)
    with pytest.raises(etree.DocumentInvalid):
        schema.assertValid(etree.ElementTree(etree.Element("not-tei")))
    for name in ("tei-p5-xsd", "tei-p5-xsd-teix", "tei-p5-xsd-xml"):
        path = manifest.authority_path(name)
        original = path.read_bytes()
        metadata = path.stat()
        changed = bytearray(original)
        changed[-1] ^= 1
        try:
            path.write_bytes(changed)
            os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
            with pytest.raises(ValueError, match="exact authority binding drift"):
                oracle._verify_local_authorities(manifest, work_id)
        finally:
            path.write_bytes(original)
            os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
