from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.gutenberg_evangelical_lib071_oracle import (
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.gutenberg_evangelical_lib071_reconstruction import _convert
from build.tools.count_dataset_records import (
    _manifest_config_ids,
    _manifest_primary_hashes,
    collect_work_catalog,
)
from tests.runtime_candidate_baselines import current_runtime_catalog

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


pytestmark = [pytest.mark.slow, pytest.mark.requires_local_artifacts]
ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "sources/structured-text/lib071-gutenberg-evangelical"
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/gutenberg-evangelical-lib071.source-manifest.json'
WORK_IDS = (
    "carey-enquiry",
    "drummond-greatest-thing",
    "drummond-natural-law",
    "machen-christianity-and-liberalism",
    "machen-what-is-faith",
    "murray-abide-in-christ",
    "murray-humility",
    "murray-with-christ-in-prayer",
    "pink-sovereignty-of-god",
    "smith-christians-secret-happy-life",
)
SOURCE_HASHES = (
    "6dc07e5606be5a0032d6583fa5b663a81ed0971a5d9d1f267cfc14959aa602c0",
    "12f442db074bfd81db981dfb7c423120e830feb2019b2c0db253692e23624048",
    "e13875abb98d6818ef2c9adbdce89a194368e082194881dcbf1e0c32a3c22333",
    "ab8fca3dcc41cf6dd1eaeca8cc216b9917bcb55e0221746746014f938105406c",
    "1d1f48d8db564f253eb3fa5ddb7080d4e004c52af27cad04ca105ac119d9e77f",
    "0f3ef0f87240731231446f8101004cb19ff78ccca9f16494d4d4c0108eaf4294",
    "17d03307933f5f9c64cebdc3d23702a0243b7c99dbfb3e24a3cbf9bbbb8145eb",
    "dde15194d62f849bfe832c8120bd80ecfdb714cdec716bb311ffd2213a647258",
    "61a7bb6a2d36b0ae74820a180742244c05bde7b274c3ea727fc84e9d0f0cca9b",
    "46b392a22d3dec23697e2d8c041b4214c55b6b3d2a604adc4625c797e6fffcdd",
)
TEI = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal(path: Path, member_name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    content = (path / member_name).read_bytes()
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


@pytest.fixture(scope="module")
def verified_candidate(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[SourceManifest, CandidatePackage, object]:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(
        source, tmp_path_factory.mktemp("lib071-candidate") / "candidate", _convert
    )
    validation = validate(source, candidate, _oracle)
    return source, candidate, validation


def test_exact_ten_source_authorities_and_complete_adjacent_census(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
) -> None:
    source, candidate, validation = verified_candidate
    assert validation.status == "pass"
    primary = [item for item in source.record["authorities"] if item["role"] == "primary-source"]
    assert len(primary) == 10
    assert tuple(item["sha256"] for item in primary) == SOURCE_HASHES
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    inventory = accountability["adjacent_retained_member_accounting"]
    assert len(inventory) == 49
    assert sum(row["disposition"].startswith("included") for row in inventory) == 10
    assert sum(row["disposition"].startswith("excluded") for row in inventory) == 39
    dispositions = {row["path"]: row["disposition"] for row in inventory}
    assert dispositions["raw/gutenberg/martinlutheronth00luthuoft_djvu.txt"] == (
        "excluded: alternate 1823 Edward Thomas Vaughan OCR witness for LIB-075 "
        "The Bondage of the Will; the frozen LIB-075 map binds the different "
        "Henry Cole Covenanter transcription"
    )
    assert dispositions["raw/gutenberg/pg48250.txt"] == (
        "excluded: currently unmapped retained Project Gutenberg witness for John "
        "Knox's The History of the Reformation of Religion in Scotland; no current "
        "WorkCatalog or frozen ticket-map assignment"
    )
    assert dispositions["raw/ia/machen_origin_pauls_religion.txt"] == (
        "excluded: unassigned retained OCR witness for J. Gresham Machen's The "
        "Origin of Paul's Religion; it is absent from the current WorkCatalog and "
        "frozen ticket maps"
    )
    assert accountability["total_line_count"] == 79_727
    assert accountability["omitted_line_count"] == 0
    assert accountability["duplicate_line_count"] == 0


def test_tei_has_one_exact_line_projection_for_every_retained_line(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
) -> None:
    _, candidate, _ = verified_candidate
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    texts = tree.xpath("/tei:TEI/tei:text/tei:group/tei:text", namespaces=TEI)
    assert tuple(text.get(XML_ID) for text in texts) == WORK_IDS
    assert len(tree.xpath("//tei:ab[@type='source-line']", namespaces=TEI)) == 79_727
    assert not tree.xpath("//comment() | //processing-instruction()")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    by_id = {item["work_id"]: item for item in provenance["works"]}
    assert "revised" in by_id["pink-sovereignty-of-god"]["witness_description"]
    assert "c.1883" in by_id["smith-christians-secret-happy-life"]["witness_description"]
    assert "does not establish an 1885 scan edition" in by_id["murray-with-christ-in-prayer"]["witness_description"]
    assert all(item["accepted_ir"] == "not_accepted" for item in provenance["works"])
    assert all(item["publication"] == "not_ready" for item in provenance["works"])


@pytest.mark.parametrize("mutation", ["omission", "duplication", "reorder", "invention"])
def test_independent_oracle_rejects_resealed_line_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = verified_candidate
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    xml_path = target / "content.tei.xml"
    tree = etree.parse(str(xml_path))
    division = tree.xpath("//tei:div[@type='retained-text-witness']", namespaces=TEI)[0]
    first, second = division[0], division[1]
    if mutation == "omission":
        division.remove(first)
    elif mutation == "duplication":
        duplicate = etree.fromstring(etree.tostring(first))
        duplicate.set(XML_ID, "invented-duplicate")
        division.append(duplicate)
    elif mutation == "reorder":
        division.remove(second)
        division.insert(0, second)
    else:
        invented = etree.SubElement(division, f"{{{TEI['tei']}}}ab", type="source-line", subtype="none", n="0")
        invented.set(XML_ID, "invented-line")
        invented.text = "invented"
    xml_path.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError):
        validate(source, mutated, _oracle)


@pytest.mark.parametrize("member", ["README.source.md", "provenance.json", "source-accountability.json", "unresolved.jsonl"])
def test_independent_oracle_rejects_resealed_evidence_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
    member: str,
) -> None:
    source, candidate, _ = verified_candidate
    target = tmp_path / member.replace(".", "-")
    shutil.copytree(candidate.path, target)
    path = target / member
    if member == "README.source.md":
        path.write_bytes(path.read_bytes() + b"\nPublication ready.\n")
    elif member == "unresolved.jsonl":
        path.write_bytes(b"")
    else:
        value = json.loads(path.read_bytes())
        if member == "provenance.json":
            value["rights"]["publication_state"] = "ready"
        else:
            value["works"][0]["omitted_line_count"] = 1
        path.write_bytes(_canonical(value))
    mutated = _reseal(target, member)
    with pytest.raises(ValueError):
        validate(source, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    [
        "provenance-title",
        "tei-bibl-title",
        "tei-publisher",
        "tei-invented-head",
        "tei-div-corresp",
        "tei-extra-bibl",
    ],
)
def test_independent_oracle_rejects_resealed_closed_tree_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    source, candidate, _ = verified_candidate
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    if mutation == "provenance-title":
        path = target / "provenance.json"
        value = json.loads(path.read_bytes())
        value["works"][0]["title"] = "Invented retained title"
        path.write_bytes(_canonical(value))
        member_name = "provenance.json"
    else:
        path = target / "content.tei.xml"
        tree = etree.parse(str(path))
        if mutation == "tei-bibl-title":
            tree.xpath("//tei:bibl/tei:title", namespaces=TEI)[0].text = (
                "Invented bibliographic title"
            )
        elif mutation == "tei-publisher":
            tree.xpath("//tei:publicationStmt/tei:publisher", namespaces=TEI)[
                0
            ].text = "Invented Publisher"
        elif mutation == "tei-invented-head":
            division = tree.xpath(
                "//tei:div[@type='retained-text-witness']", namespaces=TEI
            )[0]
            head = etree.Element(f"{{{TEI['tei']}}}head")
            head.text = "Invented source heading"
            division.insert(0, head)
        elif mutation == "tei-div-corresp":
            tree.xpath(
                "//tei:div[@type='retained-text-witness']", namespaces=TEI
            )[0].set("corresp", "#source-invented")
        else:
            source_list = tree.xpath("//tei:sourceDesc/tei:listBibl", namespaces=TEI)[
                0
            ]
            extra = etree.SubElement(
                source_list, f"{{{TEI['tei']}}}bibl", type="retained-witness"
            )
            extra.set(XML_ID, "source-invented")
            etree.SubElement(extra, f"{{{TEI['tei']}}}title").text = (
                "Invented witness"
            )
        path.write_bytes(
            etree.tostring(
                tree,
                encoding="UTF-8",
                xml_declaration=True,
                pretty_print=False,
            )
        )
        member_name = "content.tei.xml"
    mutated = _reseal(target, member_name)
    with pytest.raises(ValueError, match="LIB-071"):
        validate(source, mutated, _oracle)


def test_oracle_is_producer_independent_and_closure_pin_is_current() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    oracle_path = ROOT / "build/tei/gutenberg_evangelical_lib071_oracle.py"
    imports = ast.parse(oracle_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(imports)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(imports)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "build.tei.gutenberg_evangelical_lib071_reconstruction" not in imported
    assert "build.parsers.gutenberg_evangelical" not in imported
    assert _closure_digest(ROOT, policy) == source.record["validator"]["import_closure_sha256"]
    assert oracle_path.resolve() in _closure_paths(ROOT, policy)


def test_ticket_maps_and_catalog_identity_bindings_are_exact(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
) -> None:
    source, _, _ = verified_candidate
    work_map = (ROOT / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md").read_text(encoding="utf-8")
    source_map = (ROOT / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md").read_text(encoding="utf-8")
    for work_id, digest in zip(WORK_IDS, SOURCE_HASHES, strict=True):
        work_lines = [line for line in work_map.splitlines() if line.startswith(f"| `{work_id}` |")]
        source_lines = [line for line in source_map.splitlines() if line.startswith(f"| `{work_id}` |")]
        assert len(work_lines) == len(source_lines) == 1
        assert "| LIB-071 |" in work_lines[0]
        assert f"| `sha256:{digest}` | LIB-071 |" in source_lines[0]
    assert (
        "| `luther-bondage-of-the-will` | "
        "`sha256:5e3ce6432bd668596cca5b9ffbdfa8cb8c024dc9dbc4ab5ed109324e32e5400a` "
        "| LIB-075 | current-claim |"
    ) in source_map
    for unassigned_digest in (
        "88d0d05d54c3f1600d5bb9bb40311d1871226743171301f1af56fbde2c344da6",
        "757a79cf63817f796335c2b47c64a7a06f5c53afd8ebc6f91179f4c0adde1fc8",
        "47285642a2c52560c6319b5b6220dfab7d3cbd0cf53c5d1a757e3cc6e185d912",
    ):
        assert f"sha256:{unassigned_digest}" not in source_map
    assert _manifest_config_ids(source.record, ROOT) == set(WORK_IDS)
    assert _manifest_primary_hashes(source.record) == set(SOURCE_HASHES)


def test_global_work_catalog_binds_all_ten_verified_nonaccepted_routes(
    verified_candidate: tuple[SourceManifest, CandidatePackage, object],
    tmp_path: Path,
) -> None:
    source, candidate, validation = verified_candidate
    record = {
        "contract": "ocd-validation-report-v1",
        "status": validation.status,
        "candidate_sha256": validation.candidate_sha256,
        "source_manifest_sha256": validation.source_manifest_sha256,
        "attestation": dict(validation.attestation),
        "findings": list(validation.findings),
    }
    validation_path = tmp_path / "validation.json"
    validation_path.write_bytes(
        _canonical({**record, "report_sha256": validation.sha256})
    )
    evidence = {
        (str(source.record["source_id"]), work_id): (
            candidate.path,
            validation_path,
        )
        for work_id in WORK_IDS
    }
    catalog = current_runtime_catalog(
        root=ROOT, manifest=MANIFEST, work_ids=WORK_IDS, reconstruction_evidence=evidence)
    assert catalog.summary["work_units"] == len(WORK_IDS)
    by_id = {work["work_id"]: work for work in catalog.works}
    for work_id in WORK_IDS:
        state = by_id[work_id]["reconstruction_state"]
        routes = [
            route
            for route in state["routes"]
            if route["source_id"] == source.record["source_id"]
        ]
        assert len(routes) == 1
        assert routes[0]["association"] == "source_hash+exact_id"
        assert routes[0]["scope"] == "work"
        assert routes[0]["candidate_verification"] == "verified"
        assert routes[0]["validation_verification"] == "verified"
        assert state["tei_candidate"] == "verified"
        assert state["validation"] == "verified"
        assert state["human_review"] == "required"
        assert state["accepted_ir"] == "not_accepted"
        assert state["publication"] == "not_ready"


def test_two_fresh_processes_from_different_cwds_are_byte_identical(tmp_path: Path) -> None:
    script = (
        "from pathlib import Path; import hashlib,json,sys; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct,validate; "
        "from build.tei.gutenberg_evangelical_lib071_reconstruction import _convert; "
        "from build.tei.gutenberg_evangelical_lib071_oracle import _oracle; "
        "root=Path(sys.argv[1]); dest=Path(sys.argv[2]); "
        "s=SourceManifest.load(root/'tests/fixtures/reconstruction-runtime/gutenberg-evangelical-lib071.source-manifest.json',repository_root=root); "
        "c=reconstruct(s,dest,_convert); v=validate(s,c,_oracle); "
        "print(json.dumps({'candidate':c.sha256,'validation':v.sha256,'members':{n:hashlib.sha256(c.member_bytes(n)).hexdigest() for n in c.member_names}},sort_keys=True))"
    )
    results = []
    for ordinal, seed in enumerate(("17", "913"), 1):
        cwd = tmp_path / f"cwd-{ordinal}"
        cwd.mkdir()
        destination = tmp_path / f"candidate-{ordinal}"
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(ROOT)
        completed = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), str(destination)],
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        results.append(json.loads(completed.stdout.strip()))
    assert results[0] == results[1]
    for name in CandidatePackage.load(tmp_path / "candidate-1").member_names:
        assert (tmp_path / "candidate-1" / name).read_bytes() == (tmp_path / "candidate-2" / name).read_bytes()
