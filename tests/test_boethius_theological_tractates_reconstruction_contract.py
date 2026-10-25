from __future__ import annotations

from collections import Counter
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

from jsonschema import Draft202012Validator
from lxml import etree
import pytest

from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    prepare_review,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
RETAINED_SOURCE = Path(
    "D:/Library/Open Christian Data/raw/ccel/boethius/tracts.xml"
)
SOURCE_RELATIVE = Path("raw/ccel/boethius/tracts.xml")
SOURCE_DIR_RELATIVE = Path(
    "sources/structured-text/boethius-theological-tractates"
)
MANIFEST_RELATIVE = SOURCE_DIR_RELATIVE / (
    "boethius-theological-tractates.source-manifest.json"
)
SOURCE_SHA256 = "406487abffb39f63934771ce3b4d23b69ce4488d6bc1ccc6a6cad5b4b1e01de8"
TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
EXPECTED_DIV1 = ["i", "ii", "iii", "iv", "v"]
EXPECTED_DIV2 = ["iv.i", "iv.ii", "iv.iii", "iv.iv", "iv.v"]
EXPECTED_COUNTS = {
    "b": 3,
    "div1": 1,
    "div2": 5,
    "h2": 1,
    "h3": 1,
    "i": 188,
    "note": 59,
    "p": 297,
    "pb": 64,
    "scripRef": 1,
    "span": 60,
    "sup": 1,
    "sync": 88,
    "unclear": 9,
}
EXPECTED_MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_repository_mirror(destination: Path) -> Path:
    paths = [
        Path("build/__init__.py"),
        Path("build/tei/__init__.py"),
        Path("build/tei/boethius_theological_tractates_reconstruction.py"),
        Path("build/tei/boethius_theological_tractates_oracle.py"),
        Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"),
    ]
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    shutil.copytree(ROOT / "ocd_kernel/tei/vendor/xsd", destination / "ocd_kernel/tei/vendor/xsd")
    shutil.copytree(ROOT / SOURCE_DIR_RELATIVE, destination / SOURCE_DIR_RELATIVE)
    source_target = destination / SOURCE_RELATIVE
    source_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RETAINED_SOURCE, source_target)
    return destination


@pytest.fixture(scope="module")
def boethius_package(tmp_path_factory: pytest.TempPathFactory):
    mirror = _copy_repository_mirror(tmp_path_factory.mktemp("boethius-mirror"))
    producer = _load_module(
        mirror / "build/tei/boethius_theological_tractates_reconstruction.py",
        "boethius_producer_under_test",
    )
    oracle = _load_module(
        mirror / "build/tei/boethius_theological_tractates_oracle.py",
        "boethius_oracle_under_test",
    )
    source = SourceManifest.load(mirror / MANIFEST_RELATIVE, repository_root=mirror)
    candidate = reconstruct(
        source,
        tmp_path_factory.mktemp("boethius-candidate") / "candidate",
        producer._convert,
    )
    report = validate(source, candidate, oracle._oracle)
    return mirror, producer, oracle, source, candidate, report


def _resealed_copy(candidate: CandidatePackage, destination: Path) -> Path:
    shutil.copytree(candidate.path, destination)
    return destination


def _reseal(path: Path, name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    record = json.loads(manifest_path.read_bytes())
    content = (path / name).read_bytes()
    member = next(item for item in record["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(record))
    return CandidatePackage.load(path)


def _write_tei(path: Path, root: etree._Element) -> None:
    path.write_bytes(
        etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
    )


def test_pinned_source_identity_scope_and_census_are_exact() -> None:
    content = RETAINED_SOURCE.read_bytes()
    tree = etree.fromstring(
        content,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            remove_pis=False,
            huge_tree=True,
        ),
    )
    body = tree.find("ThML.body")
    assert body is not None
    divisions = [node for node in body if node.tag == "div1"]
    selected = tree.xpath("./ThML.body/div1[@id='iv']")
    assert len(content) == 162_005
    assert _sha(content) == SOURCE_SHA256
    assert [node.get("id") for node in divisions] == EXPECTED_DIV1
    assert len(selected) == 1
    assert [node.get("id") for node in selected[0] if node.tag == "div2"] == EXPECTED_DIV2
    features = [node for node in selected[0].iter() if isinstance(node.tag, str)]
    assert len(features) == 778
    assert Counter(node.tag for node in features) == EXPECTED_COUNTS
    assert sum(len(node.attrib) for node in features) == 1_208
    assert _sha("".join(selected[0].itertext()).encode("utf-8")) == (
        "a9d1e8b78b3b301d0087159173b6c56ec49ddf2162b9dd4d5c6b92cec8365328"
    )


def test_exact_candidate_passes_independent_oracle_and_direct_schemas(
    boethius_package,
) -> None:
    _, _, oracle, source, candidate, report = boethius_package
    assert set(candidate.member_names) == EXPECTED_MEMBERS
    assert candidate.manifest["status"] == "nonaccepted"
    assert report.status == "pass"
    assert "boethius_theological_tractates_reconstruction" not in (
        Path(oracle.__file__).read_text(encoding="utf-8")
    )

    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    schema = json.loads(source.authority_path("source-accountability-schema").read_bytes())
    Draft202012Validator(schema).validate(accountability)
    compiled = etree.XMLSchema(etree.parse(str(source.authority_path("tei-p5-xsd"))))
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert compiled.validate(etree.ElementTree(tei)), compiled.error_log

    review = prepare_review(source, candidate, report)
    assert review.candidate_sha256 == candidate.sha256
    assert review.source_manifest.authority_path("retained-thml").samefile(
        source.repository_root / SOURCE_RELATIVE
    )


def test_candidate_preserves_all_five_tractates_and_every_source_observation(
    boethius_package,
) -> None:
    mirror, _, _, _, candidate, _ = boethius_package
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    source = (mirror / SOURCE_RELATIVE).read_bytes()
    rows = accountability["crosswalk"]

    assert accountability["feature_count"] == 778
    assert accountability["attribute_count"] == 1_208
    assert accountability["feature_counts"] == EXPECTED_COUNTS
    assert accountability["omitted_feature_count"] == 0
    assert accountability["duplicate_feature_count"] == 0
    assert accountability["invented_feature_count"] == 0
    assert [item["div1_id"] for item in accountability["division_accounting"]] == EXPECTED_DIV1
    assert [item["div1_id"] for item in accountability["division_accounting"] if item["disposition"] == "excluded-sibling-work"] == ["i", "ii", "iii", "v"]
    assert [item["div2_id"] for item in accountability["tractate_accounting"]] == EXPECTED_DIV2
    assert len(rows) == 778
    assert len({item["feature_id"] for item in rows}) == 778
    assert [item["source_byte_start"] for item in rows] == sorted(
        item["source_byte_start"] for item in rows
    )
    for item in rows:
        observed = source[item["source_byte_start"] : item["source_byte_end"]]
        assert len(observed) == item["source_byte_count"]
        assert _sha(observed) == item["source_bytes_sha256"]

    assert provenance["status"] == "nonaccepted"
    assert provenance["work"]["resource_id"] == "boethius-theological-tractates"
    assert provenance["work"]["title"] == "The Theological Tractates"
    assert provenance["work"]["author"] == "Boethius"
    assert provenance["work"]["contributors"] == [
        "H.F. Stewart (translator, 1918)",
        "E.K. Rand (translator, 1918)",
    ]
    assert provenance["scope"] == {"div1_id": "iv", "div2_ids": EXPECTED_DIV2}
    assert provenance["canonical_data_written"] is False
    assert provenance["canonical_ir_written"] is False
    assert provenance["human_acceptance"] == "absent"
    assert provenance["publication"] == "not_ready"


@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "reorder",
        "invention",
        "text",
        "crosswalk",
        "metadata",
        "provenance",
        "evidence",
    ],
)
def test_independent_oracle_rejects_resealed_candidate_drift(
    boethius_package,
    tmp_path: Path,
    mutation: str,
) -> None:
    _, _, oracle, source, candidate, _ = boethius_package
    target = _resealed_copy(candidate, tmp_path / mutation)
    if mutation in {"omission", "duplication", "reorder", "invention", "text"}:
        name = "content.tei.xml"
        tei = etree.fromstring((target / name).read_bytes())
        tractates = tei.xpath("./tei:text/tei:body/tei:div/tei:div", namespaces=NS)
        if mutation == "omission":
            tractates[0].getparent().remove(tractates[0])
        elif mutation == "duplication":
            duplicate = copy.deepcopy(tractates[0])
            duplicate.set(XML_ID, "boethius-invented-duplicate")
            tractates[0].getparent().append(duplicate)
        elif mutation == "reorder":
            parent = tractates[0].getparent()
            parent.remove(tractates[1])
            parent.insert(0, tractates[1])
        elif mutation == "invention":
            invented = etree.SubElement(tractates[0], f"{{{TEI_NS}}}p")
            invented.set(XML_ID, "boethius-invented")
            invented.text = "Invented text"
        else:
            paragraph = tei.xpath(".//tei:p[text()]", namespaces=NS)[0]
            paragraph.text = "Invented " + (paragraph.text or "")
        _write_tei(target / name, tei)
    elif mutation == "crosswalk":
        name = "source-accountability.json"
        record = json.loads((target / name).read_bytes())
        record["crosswalk"][20], record["crosswalk"][21] = (
            record["crosswalk"][21],
            record["crosswalk"][20],
        )
        (target / name).write_bytes(_canonical(record))
    elif mutation == "metadata":
        name = "provenance.json"
        record = json.loads((target / name).read_bytes())
        record["work"]["title"] = "Invented title"
        (target / name).write_bytes(_canonical(record))
    elif mutation == "provenance":
        name = "provenance.json"
        record = json.loads((target / name).read_bytes())
        record["publication"] = "ready"
        (target / name).write_bytes(_canonical(record))
    else:
        name = "README.source.md"
        (target / name).write_bytes(
            (target / name).read_bytes().replace(b"sourced via CCEL.org", b"source omitted")
        )
    mutated = _reseal(target, name)
    with pytest.raises(ValueError):
        validate(source, mutated, oracle._oracle)


def test_manifest_rejects_source_config_profile_policy_schema_and_source_drift(
    tmp_path: Path,
) -> None:
    authorities = (
        "local-source-config",
        "reconstruction-profile",
        "validation-policy",
        "source-accountability-schema",
        "retained-thml",
    )
    for index, authority in enumerate(authorities):
        changed = _copy_repository_mirror(tmp_path / str(index))
        record = json.loads((changed / MANIFEST_RELATIVE).read_bytes())
        item = next(value for value in record["authorities"] if value["name"] == authority)
        path = changed / item["path"]
        path.write_bytes(path.read_bytes() + b"\n")
        with pytest.raises(ValueError, match="authority bytes drifted"):
            SourceManifest.load(changed / MANIFEST_RELATIVE, repository_root=changed)


def test_candidate_is_byte_identical_in_fresh_processes_and_different_cwds(
    boethius_package,
    tmp_path: Path,
) -> None:
    mirror, _, _, _, _, _ = boethius_package
    first = tmp_path / "first"
    second = tmp_path / "second"
    other_cwd = tmp_path / "different-cwd"
    other_cwd.mkdir()
    code = (
        "from pathlib import Path;"
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct;"
        "from build.tei.boethius_theological_tractates_reconstruction import _convert;"
        "import sys;"
        "r=Path(sys.argv[1]);"
        f"s=SourceManifest.load(r/{MANIFEST_RELATIVE.as_posix()!r},repository_root=r);"
        "reconstruct(s,Path(sys.argv[2]),_convert)"
    )
    environments = []
    for seed in ("17", "90210"):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join([str(mirror), str(ROOT)])
        environment["PYTHONHASHSEED"] = seed
        environments.append(environment)
    subprocess.run(
        [sys.executable, "-B", "-c", code, str(mirror), str(first)],
        cwd=mirror,
        env=environments[0],
        check=True,
        timeout=60,
    )
    subprocess.run(
        [sys.executable, "-B", "-c", code, str(mirror), str(second)],
        cwd=other_cwd,
        env=environments[1],
        check=True,
        timeout=60,
    )
    first_members = {
        path.name: path.read_bytes() for path in first.iterdir() if path.is_file()
    }
    second_members = {
        path.name: path.read_bytes() for path in second.iterdir() if path.is_file()
    }
    assert first_members == second_members
