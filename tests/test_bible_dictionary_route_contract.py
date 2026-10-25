"""Exercise each LIB-021 dictionary through the public reconstruction contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import sys
from types import ModuleType

import pytest

from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_RELATIVE = Path("tests/fixtures/reconstruction-runtime")
DURABLE_RAW = Path(r"D:\Library\Open Christian Data\raw\bible_dictionaries")
WORK_IDS = (
    "eastons-bible-dictionary",
    "hitchcocks-bible-names-dictionary",
    "smiths-bible-dictionary",
)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _load_module(root: Path, relative_path: str, module_name: str) -> ModuleType:
    path = root / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def validation_mirror(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not DURABLE_RAW.is_dir():
        pytest.fail(f"canonical retained raw source is unavailable: {DURABLE_RAW}")
    mirror = tmp_path_factory.mktemp("lib021-route-contract")
    for work_id in WORK_IDS:
        source_dir = ROOT / "sources" / work_id
        mirror_dir = mirror / "sources" / work_id
        for path in source_dir.iterdir():
            if path.is_file() and path.name != "witnesses.json":
                _copy_file(path, mirror_dir / path.name)
    for work_id in WORK_IDS:
        for suffix in ("source-manifest.json", "reconstruction-profile.json"):
            relative = RUNTIME_RELATIVE / f"lib021-{work_id}.{suffix}"
            _copy_file(ROOT / relative, mirror / relative)
    for relative in (
        "build/tei/bible_dictionaries_reconstruction.py",
        "build/tei/bible_dictionaries_oracle.py",
        "ocd_kernel/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    ):
        _copy_file(ROOT / relative, mirror / relative)
    shutil.copytree(
        ROOT / "ocd_kernel/tei/vendor/xsd",
        mirror / "ocd_kernel/tei/vendor/xsd",
    )
    mirror_raw = mirror / "raw/bible_dictionaries"
    for path in DURABLE_RAW.iterdir():
        if path.is_file():
            _copy_file(path, mirror_raw / path.name)
    return mirror


@pytest.mark.parametrize("work_id", WORK_IDS, ids=WORK_IDS)
def test_dictionary_route_reconstructs_and_validates(
    work_id: str,
    validation_mirror: Path,
    tmp_path: Path,
) -> None:
    manifest = SourceManifest.load(
        validation_mirror / RUNTIME_RELATIVE / f"lib021-{work_id}.source-manifest.json",
        repository_root=validation_mirror,
    )
    converter = _load_module(
        validation_mirror,
        "build/tei/bible_dictionaries_reconstruction.py",
        f"_lib021_route_converter_{work_id}",
    )._convert
    oracle = _load_module(
        validation_mirror,
        "build/tei/bible_dictionaries_oracle.py",
        f"_lib021_route_oracle_{work_id}",
    )._oracle

    candidate = reconstruct(manifest, tmp_path / work_id, converter)
    report = validate(manifest, candidate, oracle)

    assert candidate.manifest["status"] == "nonaccepted"
    assert report.status == "pass"
