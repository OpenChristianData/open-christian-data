from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from cvw_app.materialize_runtime import (
    MATERIALIZATION_CONTRACT,
    MaterializationError,
    materialize_runtime,
)
from cvw_app.serving_identity import ServingIdentity, ServingIdentityError, local_members


def _runtime_source(tmp_path: Path) -> Path:
    """Create a small source root from the current governed closure."""

    actual = Path(__file__).resolve().parents[2]
    source = tmp_path / "implementation-source"
    for relative in local_members(actual):
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(actual / relative, destination)
    static = source / "cvw_app" / "dist"
    for relative in ("review.html",):
        destination = static / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(actual / "cvw_app" / "dist" / relative, destination)
    for source_asset in (actual / "cvw_app" / "dist" / "assets").rglob("*"):
        if source_asset.is_file():
            destination = static / "assets" / source_asset.relative_to(actual / "cvw_app" / "dist" / "assets")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_asset, destination)
    return source


def _launch_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    repository = tmp_path / "canonical-input"
    repository.mkdir()
    catalog = repository / "work_catalog.json"
    catalog.write_text('{"works":[]}', encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    return repository, catalog, candidate


@pytest.mark.parametrize('explicit', [False, True])
def test_materialized_declared_library_route_needs_no_catalog(tmp_path: Path, explicit: bool) -> None:
    source = _runtime_source(tmp_path)
    repository = tmp_path/'canonical-library'
    repository.mkdir()
    candidate = tmp_path/'explicit-candidate'
    candidate.mkdir()
    report = materialize_runtime(source, tmp_path/'declared-runtime', repository_root=repository,
                                 candidate_dirs=[candidate], declared_library=explicit)
    assert '--declared-library' in report.launch_command
    assert '--catalog' not in report.launch_command
    assert report.payload['launch']['catalog'] is None
    assert report.payload['launch']['declared_library'] is True
    probe = (
        "import runpy, sys\n"
        "from pathlib import Path\n"
        "entry = runpy.run_path(sys.argv[1], run_name='cvw_protected_launcher')\n"
        "args = entry['build_argument_parser']().parse_args(sys.argv[2:])\n"
        "paths = entry['resolve_launch_paths'](args.catalog, args.candidate_dir, "
        "static_root=args.static_root, repository_root=args.repository_root, declared_library=args.declared_library)\n"
        "assert paths.catalog_path is None\n"
        "assert paths.repository_root == Path(args.repository_root).resolve()\n"
        "from ocd_kernel.library.identities import validate_record\n"
        "validate_record('work', {'schema_version':'2.0','work_id':'runtime-book','title':'Runtime book',"
        "'evidence':['source.txt'],'textual_forms':[{'textual_form_id':'runtime-text','editions':["
        "{'edition_id':'runtime-edition','title':'Runtime edition'}]}]})\n"
        "validate_record('acquisition', {'schema_version':'2.0','acquisition_id':'runtime-acquisition',"
        "'edition_id':'runtime-edition','provider':'Runtime provider','url':'https://example.org/book',"
        "'retained_files':[{'path':'source.txt','bytes':1,'sha256':'a'*64,'media_type':'text/plain'}]})\n"
    )
    subprocess.run([sys.executable, '-c', probe, *report.launch_command[1:]],
                   check=True, capture_output=True, text=True)


def test_materialization_rejects_ambiguous_catalog_before_writing(tmp_path: Path) -> None:
    destination = tmp_path/'must-not-exist'
    with pytest.raises(MaterializationError, match='mutually exclusive'):
        materialize_runtime(tmp_path/'missing-source', destination,
                            catalog_path=tmp_path/'catalog.json', declared_library=True)
    assert not destination.exists()


def test_materialize_reports_equivalent_closure_and_preserves_input_paths(tmp_path: Path) -> None:
    source = _runtime_source(tmp_path)
    repository, catalog, candidate = _launch_inputs(tmp_path)
    destination = tmp_path / "materialized-runtime"

    report = materialize_runtime(
        source,
        destination,
        repository_root=repository,
        catalog_path=catalog,
        candidate_dirs=[candidate],
    )

    assert report.manifest_path == destination / "cvw-runtime-materialization.json"
    assert report.payload["contract"] == MATERIALIZATION_CONTRACT
    assert tuple(local_members(source)) == tuple(local_members(destination))
    assert report.payload["backend"]["import_closure_equivalent"] is True  # type: ignore[index]
    assert report.payload["frontend"]["member_set_equivalent"] is True  # type: ignore[index]
    assert report.payload["host_readability"]["status"] == "unproven"  # type: ignore[index]
    assert report.payload["launch"]["repository_root"] == str(repository)  # type: ignore[index]
    assert report.payload["launch"]["catalog"] == str(catalog)  # type: ignore[index]
    assert report.payload["launch"]["candidate_dirs"] == [str(candidate)]  # type: ignore[index]
    command = report.launch_command
    assert command[1] == str(destination / "cvw_app" / "launch_windows.py")
    assert command[command.index("--repository-root") + 1] == str(repository)
    assert command[command.index("--catalog") + 1] == str(catalog)
    assert command[command.index("--candidate-dir") + 1] == str(candidate)
    assert json.loads(report.manifest_path.read_text(encoding="utf-8")) == report.payload
    assert not (destination / "canonical-input").exists()
    assert not (destination / "candidate").exists()


def test_materialized_protected_launcher_is_an_external_entrypoint(tmp_path: Path) -> None:
    source = _runtime_source(tmp_path)
    repository, catalog, candidate = _launch_inputs(tmp_path)
    report = materialize_runtime(
        source,
        tmp_path / "materialized-runtime",
        repository_root=repository,
        catalog_path=catalog,
        candidate_dirs=[candidate],
    )

    result = subprocess.run(
        [*report.launch_command, "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--repository-root" in result.stdout
    assert str(report.destination_root / "cvw_app" / "launch_windows.py") in report.launch_command
    assert sys.executable == report.launch_command[0]

    probe = (
        "import runpy, sys\n"
        "from pathlib import Path\n"
        "entry = runpy.run_path(sys.argv[1], run_name='cvw_protected_launcher')\n"
        "paths = entry['resolve_launch_paths'](\n"
        "    Path(sys.argv[2]), [Path(sys.argv[3])],\n"
        "    static_root=Path(sys.argv[4]), repository_root=Path(sys.argv[5])\n"
        ")\n"
        "assert paths.repository_root == Path(sys.argv[5]).resolve()\n"
        "assert paths.catalog_path == Path(sys.argv[2]).resolve()\n"
        "assert paths.candidate_dirs == (Path(sys.argv[3]).resolve(),)\n"
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            probe,
            str(report.destination_root / "cvw_app" / "launch_windows.py"),
            str(catalog),
            str(candidate),
            str(report.destination_root / "cvw_app" / "dist"),
            str(repository),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_materialize_refuses_existing_destination_without_touching_it(tmp_path: Path) -> None:
    source = _runtime_source(tmp_path)
    destination = tmp_path / "existing-runtime"
    destination.mkdir()
    keep = destination / "keep.txt"
    keep.write_bytes(b"keep")

    with pytest.raises(MaterializationError, match="refusing to overwrite or delete"):
        materialize_runtime(source, destination)

    assert keep.read_bytes() == b"keep"


def test_materialize_rejects_frontend_stale_against_source_tree(tmp_path: Path) -> None:
    source = _runtime_source(tmp_path)
    source_input = source / "cvw_app" / "src" / "review" / "fresh.tsx"
    source_input.parent.mkdir(parents=True)
    source_input.write_text("export const fresh = true;\n", encoding="utf-8")
    future = time.time_ns() + 10_000_000_000
    os.utime(source_input, ns=(future, future))

    with pytest.raises(MaterializationError, match="stale"):
        materialize_runtime(source, tmp_path / "materialized-runtime")


def test_materialize_rejects_source_with_different_governing_contract(tmp_path: Path) -> None:
    source = _runtime_source(tmp_path)
    governing = source / "cvw_app" / "serving_identity.py"
    governing.write_bytes(governing.read_bytes() + b"\n# different checker\n")

    with pytest.raises(MaterializationError, match="governing implementation differs"):
        materialize_runtime(source, tmp_path / "materialized-runtime")


def test_materialized_runtime_is_independent_of_outside_additions(tmp_path: Path) -> None:
    source = _runtime_source(tmp_path)
    destination = tmp_path / "materialized-runtime"
    materialize_runtime(source, destination)

    source_identity = ServingIdentity(source, source / "cvw_app" / "dist", runtime={})
    destination_identity = ServingIdentity(
        destination, destination / "cvw_app" / "dist", runtime={}
    )
    source_identity.verify()
    destination_identity.verify()
    (source / "ocd_kernel" / "unrelated-outside-runtime.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    with pytest.raises(ServingIdentityError, match="relaunch"):
        source_identity.verify()
    destination_identity.verify()


def test_materialized_runtime_keeps_governed_drift_and_shadow_defenses(tmp_path: Path) -> None:
    source = _runtime_source(tmp_path)
    destination = tmp_path / "materialized-runtime"
    materialize_runtime(source, destination)

    identity = ServingIdentity(destination, destination / "cvw_app" / "dist", runtime={})
    identity.verify()
    with (destination / "cvw_app" / "review_renderers.py").open("ab") as stream:
        stream.write(b"\n# governed mutation\n")
    with pytest.raises(ServingIdentityError, match="relaunch"):
        identity.verify()

    second = tmp_path / "materialized-runtime-shadow"
    materialize_runtime(source, second)
    shadow_identity = ServingIdentity(second, second / "cvw_app" / "dist", runtime={})
    shadow_identity.verify()
    shadow = second / "cvw_app" / "review_renderers"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(ServingIdentityError, match="relaunch"):
        shadow_identity.verify()


def test_materialize_rejects_path_escape_and_symlinked_frontend(tmp_path: Path) -> None:
    source = _runtime_source(tmp_path)
    with pytest.raises(MaterializationError, match="source implementation root"):
        materialize_runtime(source, source / "nested-runtime")

    current_root_destination = Path(__file__).resolve().parents[2] / "cvw-materializer-gate-probe"
    with pytest.raises(MaterializationError, match="protected input root"):
        materialize_runtime(source, current_root_destination)
    assert not current_root_destination.exists()

    repository, _, candidate = _launch_inputs(tmp_path)
    with pytest.raises(MaterializationError, match="protected input root"):
        materialize_runtime(
            source,
            repository / "runtime",
            repository_root=repository,
            candidate_dirs=[candidate],
        )

    library = tmp_path / "configured-library"
    (library / "raw").mkdir(parents=True)
    (repository / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(library)}), encoding="utf-8"
    )
    configured_destination = library / "raw" / "cvw-materializer-gate-probe"
    with pytest.raises(MaterializationError, match="protected input root"):
        materialize_runtime(
            source,
            configured_destination,
            repository_root=repository,
            candidate_dirs=[candidate],
        )
    assert not configured_destination.exists()

    outside = tmp_path / "outside-static"
    outside.mkdir()
    link = source / "outside-static-link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"directory symlinks unavailable for this test: {error}")
    with pytest.raises(MaterializationError, match="inside the source implementation root"):
        materialize_runtime(source, tmp_path / "materialized-runtime", static_root=link)

    destination_link = source / "destination-link"
    try:
        os.symlink(outside, destination_link, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"directory symlinks unavailable for this test: {error}")
    with pytest.raises(MaterializationError, match="reparse point"):
        materialize_runtime(source, destination_link / "runtime")
