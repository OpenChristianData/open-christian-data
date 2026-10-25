"""Focused technical contract tests for 37c-316 Watson."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/watson-divine-contentment.source-manifest.json'
PRODUCER = ROOT / "build/tei/watson_divine_contentment_reconstruction.py"
ORACLE = ROOT / "build/tei/watson_divine_contentment_oracle.py"
EXPECTED_CARRIERS = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix"]


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_candidate(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "build/tools/reconstruct_candidate.py"),
            "--manifest",
            MANIFEST.relative_to(ROOT).as_posix(),
            "--destination",
            str(destination),
            "--repository-root",
            str(ROOT),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return destination


def _load_oracle():
    spec = importlib.util.spec_from_file_location("watson_37c_316_oracle", ORACLE)
    if spec is None or spec.loader is None:
        raise AssertionError("oracle module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reseal(package: Path) -> None:
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    for member in manifest["members"]:
        path = package / member["name"]
        member["bytes"] = path.stat().st_size
        member["sha256"] = _sha(path)
    (package / "manifest.json").write_bytes(_canonical(manifest))


def _mutate_bound_tei(path: Path) -> None:
    original = b"The Art of Divine Contentment"
    replacement = b"The Art of Divine Discontent"
    content = path.read_bytes()
    assert content.count(original) >= 2
    path.write_bytes(content.replace(original, replacement, 2))


@pytest.fixture(scope="module")
def candidate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    external = Path(__import__("os").environ.get("OCD_37C316_CANDIDATE", ""))
    if external.is_dir() and (external / "package").is_dir():
        return external
    return _run_candidate(tmp_path_factory.mktemp("watson-candidate") / "candidate")


def test_complete_present_source_envelope_and_candidate(candidate: Path) -> None:
    source_manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(candidate / "package")
    accountability = json.loads(package.member_bytes("source-accountability.json"))
    assert source_manifest.record["work_id"] == "watson-divine-contentment"
    assert accountability["feature_census"]["elements"] == 1319
    assert accountability["feature_census"]["attributes"] == 2569
    assert len(accountability["features"]) == 1319
    assert [row["native_id"] for row in accountability["source_envelope"]] == EXPECTED_CARRIERS
    assert accountability["source_completeness_gap"]["absent_native_ids"] == ["ix", "x"]
    assert json.loads((candidate / "validation.json").read_text(encoding="utf-8"))["status"] == "pass"


def test_independent_oracle_rejects_content_and_accounting_mutations(candidate: Path, tmp_path: Path) -> None:
    source_manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    oracle = _load_oracle()
    for member_name, mutate in (
        (
            "content.tei.xml",
            _mutate_bound_tei,
        ),
        (
            "source-accountability.json",
            lambda path: path.write_bytes(
                _canonical(
                    {
                        **json.loads(path.read_text(encoding="utf-8")),
                        "features": json.loads(path.read_text(encoding="utf-8"))["features"][1:],
                    }
                )
            ),
        ),
    ):
        mutated = tmp_path / member_name.replace(".", "-") / "package"
        shutil.copytree(candidate / "package", mutated)
        mutate(mutated / member_name)
        _reseal(mutated)
        with pytest.raises(ValueError):
            oracle._oracle(source_manifest, CandidatePackage.load(mutated))


def test_fresh_process_candidates_are_byte_identical(tmp_path: Path) -> None:
    first = _run_candidate(tmp_path / "first" / "candidate")
    second = _run_candidate(tmp_path / "second" / "candidate")
    first_package = first / "package"
    second_package = second / "package"
    assert sorted(path.name for path in first_package.iterdir()) == sorted(path.name for path in second_package.iterdir())
    for path in sorted(first_package.iterdir()):
        assert path.read_bytes() == (second_package / path.name).read_bytes(), path.name
    assert (first / "validation.json").read_bytes() == (second / "validation.json").read_bytes()
