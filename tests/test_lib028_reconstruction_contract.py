from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest
from jsonschema import ValidationError

from build.tei.lib028_oracle import _closure_digest, _closure_paths
from build.tei.lib028_reconstruction import ASSIGNED, EXPECTED_CENSUS, SOURCES
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


pytestmark = [
    pytest.mark.slow,
    pytest.mark.xdist_group(name="lib028-reconstruction"),
]

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_REL = Path('tests/fixtures/reconstruction-runtime/puritan-eusebius-ecclesiastical-history.source-manifest.json')
RETAINED_ROOT = Path(r"D:\Library\Open Christian Data\raw\ccel\schaff")
TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = {"tei": TEI_NS}
GOVERNED_LF_PATHS = (
    'sources/structured-text/eusebius-ecclesiastical-history/lib028.source-manifest.json',
    "sources/structured-text/eusebius-ecclesiastical-history/README.md",
    "sources/structured-text/eusebius-ecclesiastical-history/lib028-source-attribution.md",
    "sources/structured-text/eusebius-ecclesiastical-history/lib028-retained-source-set.json",
    "sources/structured-text/eusebius-ecclesiastical-history/lib028-provenance.md",
    "sources/structured-text/eusebius-ecclesiastical-history/lib028-unresolved.jsonl",
    "sources/structured-text/eusebius-ecclesiastical-history/lib028.work-binding.json",
    "sources/structured-text/eusebius-life-of-constantine/lib028.work-binding.json",
    "sources/structured-text/socrates-ecclesiastical-history/lib028.work-binding.json",
    "sources/structured-text/sozomen-ecclesiastical-history/lib028.work-binding.json",
    "sources/structured-text/theodoret-ecclesiastical-history/lib028.work-binding.json",
    "sources/structured-text/eusebius-ecclesiastical-history/lib028.reconstruction-profile.json",
    "sources/structured-text/eusebius-ecclesiastical-history/lib028.validation-policy.json",
    "sources/structured-text/eusebius-ecclesiastical-history/lib028.source-accountability.schema.json",
    "sources/structured-text/eusebius-ecclesiastical-history/lib028-tei-xsd-closure.json",
    "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    "build/tei/lib028_reconstruction.py",
    "build/tei/lib028_oracle.py",
)
GOVERNED_CRLF_PATHS = (
    "docs/sources/ccel-permission.md",
    "sources/structured-text/eusebius-ecclesiastical-history/config.json",
    "sources/structured-text/eusebius-life-of-constantine/config.json",
    "sources/structured-text/socrates-ecclesiastical-history/config.json",
    "sources/structured-text/sozomen-ecclesiastical-history/config.json",
    "sources/structured-text/theodoret-ecclesiastical-history/config.json",
    "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
)


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
        b"set",
        relative_bytes,
        b"eol",
        expected.encode("ascii"),
        b"",
    ]


def test_manifest_bound_text_materializes_portably() -> None:
    manifest = json.loads((ROOT / 'sources/structured-text/eusebius-ecclesiastical-history/lib028.source-manifest.json').read_bytes())
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
        assert b"\r\n" in payload
        assert b"\n" not in payload.replace(b"\r\n", b"")
        if relative in authority_bindings:
            expected_bytes, expected_sha256 = authority_bindings[relative]
            assert len(payload) == expected_bytes
            assert _sha(payload) == expected_sha256


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _runtime_root(path: Path) -> Path:
    root = path / "runtime-root"
    record = json.loads((ROOT / MANIFEST_REL).read_bytes())
    repo_paths = {
        Path(item["path"])
        for item in record["authorities"]
        if item["role"] != "primary-source"
    }
    repo_paths.update(
        {
            MANIFEST_REL,
            Path(record["converter"]["implementation_path"]),
            Path(record["validator"]["implementation_path"]),
        }
    )
    policy = json.loads(
        (
            ROOT
            / "sources/structured-text/eusebius-ecclesiastical-history/lib028.validation-policy.json"
        ).read_bytes()
    )
    repo_paths.update(path.relative_to(ROOT) for path in _closure_paths(ROOT, policy))
    closure = json.loads(
        (
            ROOT
            / "sources/structured-text/eusebius-ecclesiastical-history/lib028-tei-xsd-closure.json"
        ).read_bytes()
    )
    repo_paths.update(Path(item["path"]) for item in closure["members"])
    repo_paths.update(
        Path(item["path"]) for item in closure["producer_runtime"]["members"]
    )
    for relative in sorted(repo_paths):
        _link_or_copy(ROOT / relative, root / relative)
    for key, relative, _size, _digest in SOURCES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RETAINED_ROOT / f"{key}.xml", target)
    return root


def _load_callable(path: Path, module_name: str, callable_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, callable_name)


def _reseal(path: Path, member_name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (path / member_name).read_bytes()
    record = next(item for item in manifest["members"] if item["name"] == member_name)
    record.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _resealed_authority_mutation(
    runtime: Path,
    candidate: CandidatePackage,
    target_root: Path,
    case: str,
) -> tuple[SourceManifest, CandidatePackage]:
    shutil.copytree(runtime, target_root)
    manifest_path = target_root / MANIFEST_REL
    manifest = json.loads(manifest_path.read_bytes())
    if case == "manifest-identity":
        manifest["source_id"] = "invented-source-id"
    else:
        authority_name = {
            "profile": "reconstruction-profile",
            "policy": "validation-policy",
            "accountability-schema": "source-accountability-schema",
        }[case]
        authority = next(
            item for item in manifest["authorities"] if item["name"] == authority_name
        )
        path = target_root / authority["path"]
        value = json.loads(path.read_bytes())
        if case == "profile":
            value["assigned_census"]["elements"] = 1
        elif case == "policy":
            value["tei_topology"]["root_attributes"]["xml:id"] = "invented"
        else:
            value["properties"]["feature_count"]["const"] = 1
        path.write_bytes(_canonical(value))
        content = path.read_bytes()
        authority.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    mutated_source = SourceManifest.load(manifest_path, repository_root=target_root)
    candidate_path = target_root.parent / f"candidate-{case}"
    shutil.copytree(candidate.path, candidate_path)
    candidate_manifest_path = candidate_path / "manifest.json"
    candidate_manifest = json.loads(candidate_manifest_path.read_bytes())
    candidate_manifest["source_id"] = manifest["source_id"]
    candidate_manifest["source_manifest"]["sha256"] = mutated_source.sha256
    candidate_manifest_path.write_bytes(_canonical(candidate_manifest))
    return mutated_source, CandidatePackage.load(candidate_path)


def _resealed_review_attack(
    runtime: Path,
    candidate: CandidatePackage,
    target_root: Path,
    case: str,
) -> tuple[SourceManifest, CandidatePackage]:
    shutil.copytree(runtime, target_root)
    manifest_path = target_root / MANIFEST_REL
    manifest = json.loads(manifest_path.read_bytes())

    authority_name: str | None = None
    if case == "retained-source-set":
        authority_name = "retained-source-set"
        authority_path = target_root / next(
            item["path"]
            for item in manifest["authorities"]
            if item["name"] == authority_name
        )
        value = json.loads(authority_path.read_bytes())
        value["unaccounted_members"] = 1
        authority_path.write_bytes(_canonical(value))
    elif case == "work-binding-root":
        authority_name = "eusebius-history-binding"
        authority_path = target_root / next(
            item["path"]
            for item in manifest["authorities"]
            if item["name"] == authority_name
        )
        value = json.loads(authority_path.read_bytes())
        value["source_root_id"] = "iv"
        value["source_root_selector"] = "ThML.body/div1[4]"
        authority_path.write_bytes(_canonical(value))
    elif case == "metadata-contributor":
        authority_name = "eusebius-history-config"
        authority_path = target_root / next(
            item["path"]
            for item in manifest["authorities"]
            if item["name"] == authority_name
        )
        value = json.loads(authority_path.read_bytes())
        value["contributors"][0] = "Invented Contributor (translator, 1890)"
        authority_path.write_bytes(
            json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        )
    elif case in {"attribution-authority", "provenance-authority"}:
        authority_name = {
            "attribution-authority": "source-attribution",
            "provenance-authority": "source-local-provenance",
        }[case]
        authority_path = target_root / next(
            item["path"]
            for item in manifest["authorities"]
            if item["name"] == authority_name
        )
        authority_path.write_bytes(
            authority_path.read_bytes() + b"\nInvented authority.\n"
        )
    elif case == "unresolved-authority":
        authority_name = "source-local-unresolved"
        authority_path = target_root / next(
            item["path"]
            for item in manifest["authorities"]
            if item["name"] == authority_name
        )
        records = [
            json.loads(line) for line in authority_path.read_bytes().splitlines()
        ]
        records[0]["scope"] = "invented-scope"
        authority_path.write_bytes(b"".join(_canonical(item) for item in records))
    elif case == "coordinated-source-identity":
        manifest["source_id"] = "invented-source-id"

    if authority_name is not None:
        authority = next(
            item for item in manifest["authorities"] if item["name"] == authority_name
        )
        content = (target_root / authority["path"]).read_bytes()
        authority.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    mutated_source = SourceManifest.load(manifest_path, repository_root=target_root)

    candidate_path = target_root.parent / f"candidate-{case}"
    shutil.copytree(candidate.path, candidate_path)
    candidate_manifest_path = candidate_path / "manifest.json"
    candidate_manifest = json.loads(candidate_manifest_path.read_bytes())
    candidate_manifest["source_manifest"]["sha256"] = mutated_source.sha256
    if case in {"candidate-source-id", "coordinated-source-identity"}:
        candidate_manifest["source_id"] = "invented-source-id"
    if case == "coordinated-source-identity":
        provenance_path = candidate_path / "provenance.json"
        provenance = json.loads(provenance_path.read_bytes())
        provenance["source_id"] = "invented-source-id"
        provenance_path.write_bytes(_canonical(provenance))
        provenance_record = next(
            item
            for item in candidate_manifest["members"]
            if item["name"] == "provenance.json"
        )
        content = provenance_path.read_bytes()
        provenance_record.update(bytes=len(content), sha256=_sha(content))
    candidate_manifest_path.write_bytes(_canonical(candidate_manifest))
    return mutated_source, CandidatePackage.load(candidate_path)


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.mktemp("lib028-authorities")
    runtime = _runtime_root(base)
    source = SourceManifest.load(runtime / MANIFEST_REL, repository_root=runtime)
    runtime_convert = _load_callable(
        runtime / "build/tei/lib028_reconstruction.py",
        "lib028_runtime_producer",
        "_convert",
    )
    runtime_oracle = _load_callable(
        runtime / "build/tei/lib028_oracle.py", "lib028_runtime_oracle", "_oracle"
    )
    candidate = reconstruct(source, base / "candidate", runtime_convert)
    report = validate(source, candidate, runtime_oracle)
    assert report.status == "pass"
    return runtime, source, candidate, runtime_convert, runtime_oracle


def test_exact_three_members_five_bindings_and_frozen_routes() -> None:
    assert ASSIGNED == (
        ("npnf201", "iii", "eusebius-ecclesiastical-history"),
        ("npnf201", "iv", "eusebius-life-of-constantine"),
        ("npnf202", "ii", "socrates-ecclesiastical-history"),
        ("npnf202", "iii", "sozomen-ecclesiastical-history"),
        ("npnf203", "iv", "theodoret-ecclesiastical-history"),
    )
    for key, _path, size, digest in SOURCES:
        content = (RETAINED_ROOT / f"{key}.xml").read_bytes()
        assert (len(content), _sha(content)) == (size, digest)
    work_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md"
    ).read_text(encoding="utf-8")
    source_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md"
    ).read_text(encoding="utf-8")
    for key, source_id, work_id in ASSIGNED:
        digest = next(item[3] for item in SOURCES if item[0] == key)
        assert work_map.count(f"| `{work_id}` |") == 1
        assert f"| `{work_id}` |" in work_map
        assert (
            f"| `{work_id}` | `sha256:{digest}` | LIB-028 | current-claim |"
            in source_map
        )
        binding = json.loads(
            (
                ROOT / f"sources/structured-text/{work_id}/lib028.work-binding.json"
            ).read_bytes()
        )
        assert (binding["source_root_id"], binding["work_id"]) == (source_id, work_id)


def test_candidate_is_p5_valid_and_every_crosswalk_field_is_independently_verified(
    verified_candidate,
) -> None:
    _runtime, source, candidate, _runtime_convert, runtime_oracle = verified_candidate
    tree = etree.parse(str(candidate.path / "content.tei.xml"))
    schema = etree.XMLSchema(etree.parse(str(source.authority_path("tei-p5-xsd"))))
    schema.assertValid(tree)
    assert validate(source, candidate, runtime_oracle).status == "pass"
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["assigned_census"] == EXPECTED_CENSUS
    assert accountability["feature_count"] == 53_258
    assert accountability["attribute_count"] == 101_789
    assert len(accountability["work_bindings"]) == 5
    assert all(
        row["attribute_dispositions"] is not None for row in accountability["crosswalk"]
    )
    assert b"Open Christian Data" not in candidate.member_bytes("content.tei.xml")


@pytest.mark.parametrize(
    ("member_name", "mutation"),
    [
        ("content.tei.xml", "tei-text"),
        ("content.tei.xml", "tei-metadata"),
        ("source-accountability.json", "crosswalk-row"),
        ("source-accountability.json", "attribute-disposition"),
        ("provenance.json", "candidate-identity"),
    ],
)
def test_oracle_rejects_fully_resealed_candidate_mutations(
    verified_candidate, tmp_path: Path, member_name: str, mutation: str
) -> None:
    _runtime, source, candidate, _runtime_convert, runtime_oracle = verified_candidate
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    member = target / member_name
    if mutation.startswith("tei-"):
        tree = etree.parse(str(member))
        if mutation == "tei-text":
            node = tree.xpath("/tei:TEI/tei:text/tei:body/tei:div", namespaces=TEI)[0]
            node.text = (node.text or "") + "invented"
        else:
            title = tree.xpath("/tei:TEI/tei:teiHeader//tei:title", namespaces=TEI)[0]
            title.text = "Invented title"
        member.write_bytes(
            etree.tostring(
                tree, encoding="UTF-8", xml_declaration=True, pretty_print=False
            )
        )
    else:
        value = json.loads(member.read_bytes())
        if mutation == "crosswalk-row":
            value["crosswalk"][0]["source_selector"] = "wrong"
        elif mutation == "attribute-disposition":
            value["crosswalk"][0]["attribute_dispositions"][0]["destination"] = "@n"
        else:
            value["source_id"] = "invented-source"
        member.write_bytes(_canonical(value))
    mutated = _reseal(target, member_name)
    with pytest.raises(ValueError):
        runtime_oracle(source, mutated)


def test_manifest_profile_policy_schema_and_source_drift_are_fail_closed(
    verified_candidate, tmp_path: Path
) -> None:
    runtime, source, _candidate, _runtime_convert, _runtime_oracle = verified_candidate
    cases = {
        "reconstruction-profile": b"\n",
        "validation-policy": b"\n",
        "source-accountability-schema": b"\n",
        "retained-npnf201": b"\n",
    }
    for authority, suffix in cases.items():
        isolated = tmp_path / authority
        shutil.copytree(runtime, isolated)
        copied = SourceManifest.load(isolated / MANIFEST_REL, repository_root=isolated)
        target = copied.authority_path(authority)
        target.write_bytes(target.read_bytes() + suffix)
        with pytest.raises(ValueError, match="authority bytes drifted"):
            copied.verify()
    manifest = json.loads((runtime / MANIFEST_REL).read_bytes())
    manifest["source_id"] = "invented-source-id"
    path = tmp_path / "manifest-identity.json"
    path.write_bytes(_canonical(manifest))
    with pytest.raises(ValueError, match="outside repository root"):
        SourceManifest.load(path, repository_root=runtime)


@pytest.mark.parametrize(
    "case", ["manifest-identity", "profile", "policy", "accountability-schema"]
)
def test_oracle_rejects_fully_resealed_manifest_profile_and_schema_mutations(
    verified_candidate, tmp_path: Path, case: str
) -> None:
    runtime, _source, candidate, _runtime_convert, runtime_oracle = verified_candidate
    mutated_source, mutated_candidate = _resealed_authority_mutation(
        runtime, candidate, tmp_path / f"runtime-{case}", case
    )
    expected = (
        (ValueError, ValidationError) if case == "accountability-schema" else ValueError
    )
    with pytest.raises(expected):
        runtime_oracle(mutated_source, mutated_candidate)


@pytest.mark.parametrize(
    "case",
    [
        "retained-source-set",
        "work-binding-root",
        "metadata-contributor",
        "attribution-authority",
        "provenance-authority",
        "unresolved-authority",
        "candidate-source-id",
        "coordinated-source-identity",
    ],
)
def test_oracle_and_validate_reject_all_reviewed_coordinated_reseals(
    verified_candidate, tmp_path: Path, case: str
) -> None:
    runtime, _source, candidate, _runtime_convert, _runtime_oracle = verified_candidate
    mutated_source, mutated_candidate = _resealed_review_attack(
        runtime, candidate, tmp_path / f"runtime-{case}", case
    )
    mutated_oracle = _load_callable(
        mutated_source.repository_root / "build/tei/lib028_oracle.py",
        f"lib028_resealed_oracle_{case.replace('-', '_')}",
        "_oracle",
    )
    with pytest.raises(ValueError):
        mutated_oracle(mutated_source, mutated_candidate)
    with pytest.raises(ValueError):
        validate(mutated_source, mutated_candidate, mutated_oracle)


def test_oracle_closure_excludes_producer_and_matches_manifest(
    verified_candidate,
) -> None:
    runtime, source, _candidate, _runtime_convert, _runtime_oracle = verified_candidate
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    paths = {
        path.relative_to(runtime).as_posix() for path in _closure_paths(runtime, policy)
    }
    assert "build/tei/lib028_oracle.py" in paths
    assert "build/tei/lib028_reconstruction.py" not in paths
    assert (
        _closure_digest(runtime, policy)
        == source.record["validator"]["import_closure_sha256"]
    )


def test_fresh_process_different_cwd_and_hash_seed_package_determinism(
    verified_candidate, tmp_path: Path
) -> None:
    runtime, _source, candidate, _runtime_convert, _runtime_oracle = verified_candidate
    script = (
        "import sys;"
        "from pathlib import Path;"
        f"r=Path({str(runtime)!r});"
        "sys.path.insert(0,str(r));"
        "import importlib.util;"
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct;"
        "s=importlib.util.spec_from_file_location('lib028_subprocess_producer',r/'build/tei/lib028_reconstruction.py');"
        "m0=importlib.util.module_from_spec(s);s.loader.exec_module(m0);"
        f"m=SourceManifest.load(r/Path({MANIFEST_REL.as_posix()!r}),repository_root=r);"
        "reconstruct(m,Path(sys.argv[1]),m0._convert);"
        "outside=[];"
        "[(outside.append((n,getattr(v,'__file__',None)))) for n,v in sys.modules.items() "
        "if (n=='ocd_kernel' or n.startswith('ocd_kernel.') or n=='build' or n.startswith('build.')) "
        "and getattr(v,'__file__',None) and not Path(v.__file__).resolve().is_relative_to(r)];"
        "assert not outside,outside"
    )
    produced = []
    for seed, cwd_name in (
        ("1", "cwd-a"),
        ("987654", "cwd-b"),
        ("314159", "cwd-c"),
    ):
        cwd = tmp_path / cwd_name
        cwd.mkdir()
        output = tmp_path / f"candidate-{seed}"
        env = dict(os.environ, PYTHONHASHSEED=seed)
        env.pop("PYTHONPATH", None)
        subprocess.run(
            [sys.executable, "-I", "-c", script, str(output)],
            cwd=cwd,
            env=env,
            check=True,
        )
        produced.append(CandidatePackage.load(output))
    expected = {path.name: path.read_bytes() for path in candidate.path.iterdir()}
    for regenerated in produced:
        assert {
            path.name: path.read_bytes() for path in regenerated.path.iterdir()
        } == expected


def test_candidate_destination_rejects_protected_repository_boundaries(
    verified_candidate,
) -> None:
    runtime, source, _candidate, runtime_convert, _runtime_oracle = verified_candidate
    for protected in ("raw", "data", "ir", "reports", "exports"):
        with pytest.raises(ValueError, match="outside the repository"):
            reconstruct(
                source, runtime / protected / "lib028-candidate", runtime_convert
            )
