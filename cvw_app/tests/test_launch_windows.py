from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import cvw_app.launch_windows as launch_windows
from cvw_app.launch_windows import (
    LaunchPaths,
    LaunchError,
    build_argument_parser,
    launch,
    preflight_candidate_session,
    resolve_launch_paths,
    wait_for_ready,
)
from cvw_app.review_contract import ReviewContractError
from ocd_kernel.library._common import io_path


def test_read_phase_still_rejects_member_link_escape(tmp_path):
    from ocd_kernel.lib.storage_topology import storage_read_phase
    from ocd_kernel.reconstruction.contract import _contained

    repo = tmp_path / "repo"
    library = tmp_path / "library"
    raw = library / "raw"
    outside = tmp_path / "outside"
    for directory in (repo, raw, outside):
        directory.mkdir(parents=True)
    (repo / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(library)}), encoding="utf-8"
    )
    source = raw / "source.txt"
    source.write_text("inside", encoding="utf-8")
    (outside / "source.txt").write_text("outside", encoding="utf-8")
    with storage_read_phase():
        assert _contained(repo, "raw/source.txt", "source") == source
        _symlink_or_skip(raw / "escape", outside, target_is_directory=True)
        with pytest.raises(ValueError, match="escapes configured storage boundary"):
            _contained(repo, "raw/escape/source.txt", "source")
        source.unlink()
        with pytest.raises(OSError):
            _contained(repo, "raw/source.txt", "source")


def _fake_preflight(paths: object) -> tuple[object, tuple[()]]:
    return object(), ()


def test_large_input_snapshot_hashes_every_file_fresh_with_bounded_workers(tmp_path, monkeypatch):
    from collections import Counter
    from threading import Lock, get_ident

    repo = tmp_path / "repo"
    repo.mkdir()
    members = [repo / f"source-{index}.txt" for index in range(512)]
    for member in members:
        member.write_text("source", encoding="utf-8")
    catalog = repo / "catalog.json"
    catalog.write_text("{}", encoding="utf-8")
    manifest = repo / "source-manifest.json"
    manifest.write_text(json.dumps({
        "authorities": [{"path": member.name} for member in members],
        "converter": {"implementation_path": members[0].name},
        "validator": {"implementation_path": members[0].name},
        "package_schema": {"path": members[0].name},
    }), encoding="utf-8")
    preflight = (SimpleNamespace(source_manifest_path=manifest.name,
        source_manifest_sha256=launch_windows.sha256_file(manifest)),)
    application = SimpleNamespace(roots={})
    paths = LaunchPaths(repo, catalog, (), repo)
    file_identity = launch_windows.file_identity
    checked = Counter()
    threads = set()
    lock = Lock()

    def observed(path):
        if path.name.startswith("source-") and path.suffix == ".txt":
            with lock:
                checked[path.name] += 1
                threads.add(get_ident())
        return file_identity(path)

    monkeypatch.setattr(launch_windows, "file_identity", observed)
    _, first = launch_windows._protected_inputs(paths, application, preflight)
    assert checked == Counter({member.name: 1 for member in members})
    assert 1 < len(threads) <= 4
    members[-1].write_text("SOURCE", encoding="utf-8")
    _, second = launch_windows._protected_inputs(paths, application, preflight)
    assert first[str(members[-1])]["sha256"] != second[str(members[-1])]["sha256"]
    assert checked == Counter({member.name: 2 for member in members})


def test_preflight_read_phase_ends_when_validation_rejects(tmp_path, monkeypatch):
    from ocd_kernel.lib import storage_topology

    def reject(*args, **kwargs):
        assert storage_topology._read_roots.get() is not None
        raise ValueError("source verification rejected")

    monkeypatch.setattr(launch_windows.ReviewApplication, "from_declared_library", reject)
    with pytest.raises(LaunchError, match="source verification rejected"):
        preflight_candidate_session(LaunchPaths(tmp_path, None, (), tmp_path))
    assert storage_topology._read_roots.get() is None


def _built_frontend(tmp_path: Path, *, document: str | None = None) -> Path:
    static_root = tmp_path / "dist"
    assets = static_root / "assets"
    assets.mkdir(parents=True)
    (static_root / "review.html").write_text(
        document
        or '<div id="review-root"></div><script type="module" src="/assets/app.js"></script>'
        '<link rel="stylesheet" href="/assets/app.css">',
        encoding="utf-8",
    )
    (assets / "app.js").write_text("console.log('built');", encoding="utf-8")
    (assets / "app.css").write_text("#review-root { display: block; }", encoding="utf-8")
    return static_root


def test_declared_library_preflight_never_calls_catalog(tmp_path, monkeypatch):
    application = SimpleNamespace(candidate_session_bindings=lambda: ())
    def reject_catalog(*args, **kwargs):
        raise AssertionError('catalog must not be read')
    monkeypatch.setattr(launch_windows.ReviewApplication, 'from_work_catalog', reject_catalog)
    monkeypatch.setattr(launch_windows.ReviewApplication, 'from_declared_library', lambda *args, **kwargs: application)
    loaded, bindings = preflight_candidate_session(LaunchPaths(tmp_path, None, (), tmp_path))
    assert loaded is application
    assert bindings == ()


def test_declared_library_and_catalog_are_mutually_exclusive(tmp_path):
    with pytest.raises(LaunchError, match='not both'):
        resolve_launch_paths(tmp_path / 'catalog.json', [], repository_root=tmp_path, declared_library=True)
    assert build_argument_parser().parse_args(['--declared-library']).declared_library


def test_candidate_session_preflight_reports_each_exact_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate"
    (candidate / "package").mkdir(parents=True)
    catalog = tmp_path / "work_catalog.json"
    catalog.write_text('{"works":[]}', encoding="utf-8")
    static_root = _built_frontend(tmp_path)
    candidate_sha = "a" * 64
    report_sha = "b" * 64
    source_sha = "c" * 64
    application = SimpleNamespace(
        candidate_session_bindings=lambda: (
            SimpleNamespace(
                path=candidate,
                work_ids=("one", "two"),
                source_id="source-one",
                source_manifest_path="sources/one.json",
                source_manifest_sha256=source_sha,
                candidate_sha256=candidate_sha,
                validation_report_sha256=report_sha,
                validation_status="pass",
            ),
        )
    )
    monkeypatch.setattr(
        launch_windows.ReviewApplication,
        "from_work_catalog",
        classmethod(lambda cls, *args, **kwargs: application),
    )
    loaded, summaries = preflight_candidate_session(
        LaunchPaths(tmp_path, catalog, (candidate,), static_root)
    )

    assert loaded is application
    assert len(summaries) == 1
    assert summaries[0].path == candidate
    assert summaries[0].work_ids == ("one", "two")
    assert summaries[0].source_id == "source-one"
    assert summaries[0].source_manifest_path == "sources/one.json"
    assert summaries[0].source_manifest_sha256 == source_sha
    assert summaries[0].candidate_sha256 == candidate_sha
    assert summaries[0].validation_status == "pass"
    assert summaries[0].validation_report_sha256 == report_sha


def test_candidate_session_preflight_preserves_path_specific_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "bad-candidate"
    candidate.mkdir()
    catalog = tmp_path / "work_catalog.json"
    catalog.write_text('{"works":[]}', encoding="utf-8")
    static_root = _built_frontend(tmp_path)
    monkeypatch.setattr(
        launch_windows.ReviewApplication,
        "from_work_catalog",
        classmethod(
            lambda cls, *args, **kwargs: (_ for _ in ()).throw(
                ReviewContractError(f"candidate directory 1 ({candidate}) is invalid: stale manifest")
            )
        ),
    )

    with pytest.raises(LaunchError, match="bad-candidate.*stale manifest"):
        preflight_candidate_session(
            LaunchPaths(tmp_path, catalog, (candidate,), static_root)
        )


def test_protected_inputs_hash_long_work_authority_paths(tmp_path: Path) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    work_id = "arnulf-long-path-fixture"
    work_root = repository_root / "library" / "works" / work_id
    work_content = b'{"work_id":"arnulf-long-path-fixture"}\n'
    work_path = work_root / "work.json"
    io_path(work_path).parent.mkdir(parents=True, exist_ok=True)
    io_path(work_path).write_bytes(work_content)
    acquisition_path = (
        work_root
        / "forms"
        / ("f" * 48)
        / "editions"
        / ("e" * 48)
        / "acquisitions"
        / ("a" * 48 + ".json")
    )
    acquisition_content = b'{"acquisition_id":"long"}\n'
    io_path(acquisition_path).parent.mkdir(parents=True, exist_ok=True)
    io_path(acquisition_path).write_bytes(acquisition_content)
    manifest_path = repository_root / "source-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "authorities": [
                    {"path": acquisition_path.relative_to(repository_root).as_posix()}
                ],
                "converter": {"implementation_path": "converter.py"},
                "validator": {"implementation_path": "validator.py"},
                "package_schema": {"path": "schema.json"},
            }
        ),
        encoding="utf-8",
    )
    (repository_root / "converter.py").write_text("", encoding="utf-8")
    (repository_root / "validator.py").write_text("", encoding="utf-8")
    (repository_root / "schema.json").write_text("{}", encoding="utf-8")
    source_hash = launch_windows.sha256_file(manifest_path)
    application = SimpleNamespace(
        candidate_session_bindings=lambda: (SimpleNamespace(work_ids=(work_id,)),),
        roots={},
    )
    paths = LaunchPaths(repository_root, None, (), repository_root)
    preflight = (
        SimpleNamespace(
            source_manifest_path="source-manifest.json",
            source_manifest_sha256=source_hash,
        ),
    )

    roots, identities = launch_windows._protected_inputs(paths, application, preflight)

    acquisition_identity = str(io_path(acquisition_path).resolve(strict=True))
    assert Path(acquisition_identity) in roots
    assert identities[acquisition_identity] == launch_windows.file_identity(acquisition_path)


def test_launcher_defaults_to_declared_library_and_accepts_repeated_candidates(
    tmp_path: Path,
) -> None:
    parser = build_argument_parser()
    args = parser.parse_args(
        ["--candidate-dir", "candidate-one", "--candidate-dir", "candidate-two"]
    )

    assert args.catalog is None
    assert args.candidate_dir == [Path("candidate-one"), Path("candidate-two")]
    assert args.host == "127.0.0.1"
    assert args.port == 0

    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('invalid historical catalog must not be read', encoding="utf-8")
    candidates = [tmp_path / "candidate-one", tmp_path / "candidate-two"]
    for candidate in candidates:
        candidate.mkdir()
    paths = resolve_launch_paths(
        None,
        candidates,
        static_root=_built_frontend(tmp_path),
        repository_root=repo,
    )

    assert paths.catalog_path is None
    assert paths.candidate_dirs == tuple(path.resolve() for path in candidates)


def test_launcher_emits_session_receipt_and_actual_origin_for_ephemeral_port(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"works":[]}', encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    output: list[str] = []
    captured: dict[str, object] = {}

    class FakeServer:
        server_address = ("127.0.0.1", 43821)

        def serve_forever(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

        def server_close(self) -> None:
            return None

    def server_factory(*args: object, **kwargs: object) -> FakeServer:
        captured.update(kwargs)
        return FakeServer()

    url = launch(
        catalog,
        [candidate],
        static_root=_built_frontend(tmp_path),
        repository_root=repo,
        port=0,
        session_output=tmp_path / "session-output",
        session_id_factory=lambda: "session-ephemeral",
        server_factory=server_factory,
        readiness_wait=lambda *args, **kwargs: None,
        browser_open=lambda url: False,
        output=output.append,
        candidate_preflight=_fake_preflight,  # type: ignore[arg-type]
    )

    assert url == "http://127.0.0.1:43821/review"
    assert captured["port"] == 0
    descriptor = captured["session_descriptor"]
    assert isinstance(descriptor, dict)
    assert descriptor["session"]["port"] is None  # type: ignore[index]
    ready_lines = [line for line in output if line.startswith("CVW_SESSION_READY ")]
    assert len(ready_lines) == 1
    ready = json.loads(ready_lines[0].removeprefix("CVW_SESSION_READY "))
    assert ready["session_id"] == "session-ephemeral"
    assert ready["port"] == 43821
    assert ready["origin"] == "http://127.0.0.1:43821"

    receipt = next((tmp_path / "session-output").glob("*.receipt.json"))
    receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt_value["session"]["state"] == "stopped"
    events = next((tmp_path / "session-output").glob("*.events.jsonl"))
    event_names = [json.loads(line)["event"] for line in events.read_text(encoding="utf-8").splitlines()]
    assert {"session_start", "preflight_complete", "bound", "ready", "shutdown"} <= set(event_names)


def test_launcher_rejects_missing_built_frontend_and_protected_candidate(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"works":[]}', encoding="utf-8")
    protected = repo / "data" / "candidate"
    protected.mkdir(parents=True)

    with pytest.raises(LaunchError, match="built frontend|review.html"):
        resolve_launch_paths(
            catalog,
            [tmp_path / "candidate"],
            static_root=tmp_path / "missing-dist",
            repository_root=repo,
        )

    with pytest.raises(LaunchError, match="protected repository path"):
        resolve_launch_paths(
            catalog,
            [protected],
            static_root=_built_frontend(tmp_path),
            repository_root=repo,
        )


def test_launcher_rejects_a_frontend_bundle_older_than_its_source(tmp_path: Path) -> None:
    app_root = tmp_path / "cvw_app"
    static_root = _built_frontend(app_root)
    source = app_root / "src" / "review" / "App.tsx"
    source.parent.mkdir(parents=True)
    source.write_text("export const changed = true;", encoding="utf-8")
    entrypoint = static_root / "review.html"
    entrypoint_time = entrypoint.stat().st_mtime
    os.utime(source, (entrypoint_time + 2, entrypoint_time + 2))

    with pytest.raises(LaunchError, match="built frontend is stale"):
        launch_windows._validate_built_frontend(static_root)


@pytest.mark.parametrize("protected_name", ["raw", "reports", "exports"])
def test_launcher_rejects_candidate_under_configured_external_data_root(
    tmp_path: Path,
    protected_name: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    library = tmp_path / "library"
    candidate = library / protected_name / "candidate"
    candidate.mkdir(parents=True)
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"works":[]}', encoding="utf-8")
    (repo / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(library)}),
        encoding="utf-8",
    )

    with pytest.raises(LaunchError, match="protected repository path"):
        resolve_launch_paths(
            catalog,
            [candidate],
            static_root=_built_frontend(tmp_path),
            repository_root=repo,
        )


def test_protected_inputs_resolves_retained_raw_authority_through_storage_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ocd_kernel.lib import storage_topology

    repo = tmp_path / "repo"
    library = tmp_path / "library"
    candidate = tmp_path / "candidate"
    for path in (repo / "sources", repo / "build", repo / "schemas", candidate):
        path.mkdir(parents=True, exist_ok=True)
    raw_authority = library / "raw" / "docsouth" / "route" / "source.xml"
    raw_authority.parent.mkdir(parents=True)
    raw_authority.write_text("retained source", encoding="utf-8")
    (repo / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(library)}),
        encoding="utf-8",
    )
    (repo / "build" / "converter.py").write_text("pass\n", encoding="utf-8")
    (repo / "build" / "validator.py").write_text("pass\n", encoding="utf-8")
    (repo / "schemas" / "package.json").write_text("{}", encoding="utf-8")
    manifest_path = repo / "sources" / "route.json"
    manifest_path.write_text(
        json.dumps(
            {
                "authorities": [{"path": "raw/docsouth/route/source.xml"}],
                "converter": {"implementation_path": "build/converter.py"},
                "validator": {"implementation_path": "build/validator.py"},
                "package_schema": {"path": "schemas/package.json"},
            }
        ),
        encoding="utf-8",
    )
    preflight = launch_windows.CandidatePreflight(
        path=candidate,
        work_ids=("route-work",),
        source_id="route-source",
        source_manifest_path="sources/route.json",
        source_manifest_sha256=launch_windows.sha256_file(manifest_path),
        candidate_sha256="a" * 64,
        validation_report_sha256="b" * 64,
        validation_status="pass",
    )
    application = SimpleNamespace(candidate_session_bindings=lambda: ())

    root_reads = []
    read_root = storage_topology._library_root

    def observed_root(root):
        root_reads.append(root)
        return read_root(root)

    monkeypatch.setattr(storage_topology, "_library_root", observed_root)
    protected, identities = launch_windows._protected_inputs(
        LaunchPaths(repo, None, (candidate,), tmp_path),
        application,  # type: ignore[arg-type]
        (preflight,),
    )

    assert raw_authority.resolve() in protected
    assert str(raw_authority.resolve()) in identities
    assert identities[str(raw_authority.resolve())] == launch_windows.file_identity(raw_authority)
    assert root_reads.count(repo.resolve()) == 1
    assert storage_topology._read_roots.get() is None
    raw_authority.unlink()
    with pytest.raises(LaunchError, match="source authority is unavailable"):
        launch_windows._protected_inputs(
            LaunchPaths(repo, None, (candidate,), tmp_path), application, (preflight,)
        )
    assert root_reads.count(repo.resolve()) == 2
    assert storage_topology._read_roots.get() is None


def test_launcher_rejects_ipv6_until_it_has_an_ipv6_server_canary(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"works":[]}', encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    with pytest.raises(LaunchError, match="loopback.*127.0.0.1.*localhost"):
        launch(
            catalog,
            [candidate],
            static_root=_built_frontend(tmp_path),
            repository_root=repo,
            host="::1",
            candidate_preflight=_fake_preflight,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("reference", "message", "has_local_js"),
    [
        ('<script type="module" src="/assets/missing.js"></script>', "missing", True),
        ('<script type="module" src="/../outside.js"></script>', "escapes", True),
        ('<link rel="stylesheet" href="/assets/missing.css">', "missing", True),
        ('<script type="module" src="https://cdn.example/app.js"></script>', "resolve inside static root", True),
        ('<link rel="stylesheet" href="//cdn.example/app.css">', "resolve inside static root", True),
        ('<script type="module" src="//cdn.example/app.js"></script>', "resolve inside static root", True),
        ('<link rel="stylesheet" href="/assets/app.css">', "no local JavaScript bundle", False),
    ],
)
def test_launcher_validates_every_local_built_asset_reference(
    tmp_path: Path,
    reference: str,
    message: str,
    has_local_js: bool,
) -> None:
    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"works":[]}', encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    document = '<div id="review-root"></div>'
    if has_local_js:
        document += '<script type="module" src="/assets/app.js"></script>'
    document += reference

    with pytest.raises(LaunchError, match=message):
        resolve_launch_paths(
            catalog,
            [candidate],
            static_root=_built_frontend(
                tmp_path,
                document=document,
            ),
            repository_root=repo,
        )


def test_launcher_accepts_contained_local_javascript_and_css_assets(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"works":[]}', encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    paths = resolve_launch_paths(
        catalog,
        [candidate],
        static_root=_built_frontend(tmp_path),
        repository_root=repo,
    )

    assert paths.static_root == (tmp_path / "dist").resolve()


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
        return
    except (OSError, NotImplementedError) as symlink_error:
        if not target_is_directory:
            pytest.skip(
                "this Windows host cannot create the safe symlink fixture: "
                f"{symlink_error}"
            )
        try:
            subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as junction_error:
            pytest.skip(
                "this Windows host cannot create the safe junction fixture: "
                f"{junction_error}"
            )


def test_launcher_rejects_candidate_package_symlink_outside_outer_root(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"works":[]}', encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    outside = tmp_path / "outside-package"
    outside.mkdir()
    _symlink_or_skip(candidate / "package", outside, target_is_directory=True)
    (candidate / "validation.json").write_text("{}", encoding="utf-8")

    with pytest.raises(LaunchError, match="package.*outside candidate"):
        resolve_launch_paths(
            catalog,
            [candidate],
            static_root=_built_frontend(tmp_path),
            repository_root=repo,
        )


def test_launcher_rejects_validation_symlink_into_protected_root(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"works":[]}', encoding="utf-8")
    protected = repo / "data"
    protected.mkdir()
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "package").mkdir()
    _symlink_or_skip(candidate / "validation.json", protected, target_is_directory=True)

    with pytest.raises(LaunchError, match="protected repository path"):
        resolve_launch_paths(
            catalog,
            [candidate],
            static_root=_built_frontend(tmp_path),
            repository_root=repo,
        )


@pytest.mark.parametrize("name", ["validation.json", "text-quality.json"])
def test_launcher_rejects_validation_symlink_outside_outer_root(
    tmp_path: Path, name: str,
) -> None:
    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"works":[]}', encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "package").mkdir()
    outside = tmp_path / "outside-validation"
    outside.mkdir()
    _symlink_or_skip(candidate / name, outside, target_is_directory=True)

    with pytest.raises(LaunchError, match=name + ".*outside candidate"):
        resolve_launch_paths(
            catalog,
            [candidate],
            static_root=_built_frontend(tmp_path),
            repository_root=repo,
        )


def test_launcher_opens_browser_only_after_readiness(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"works":[]}', encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    events: list[object] = []

    class FakeServer:
        server_address = ("127.0.0.1", 43210)

        def serve_forever(self) -> None:
            events.append("serve")

        def shutdown(self) -> None:
            events.append("shutdown")

        def server_close(self) -> None:
            events.append("close")

    def server_factory(*args: object, **kwargs: object) -> FakeServer:
        events.append(("server", args, kwargs))
        return FakeServer()

    def ready(url: str, **kwargs: object) -> None:
        events.append(("ready", url))

    def browser(url: str) -> bool:
        events.append(("browser", url))
        return True

    launch(
        catalog,
        [candidate],
        static_root=_built_frontend(tmp_path),
        repository_root=repo,
        server_factory=server_factory,
        readiness_wait=ready,
        browser_open=browser,
        candidate_preflight=_fake_preflight,  # type: ignore[arg-type]
    )

    ready_index = next(index for index, event in enumerate(events) if isinstance(event, tuple) and event[0] == "ready")
    browser_index = next(index for index, event in enumerate(events) if isinstance(event, tuple) and event[0] == "browser")
    assert ready_index < browser_index
    assert events[browser_index][1] == "http://127.0.0.1:43210/review"  # type: ignore[index]


def test_launcher_reports_readiness_failure_with_manual_url(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"works":[]}', encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    def ready(url: str, **kwargs: object) -> None:
        raise LaunchError(f"service did not become ready at {url}")

    with pytest.raises(LaunchError, match="service did not become ready.*127.0.0.1"):
        launch(
            catalog,
            [candidate],
            static_root=_built_frontend(tmp_path),
            repository_root=repo,
            server_factory=lambda *args, **kwargs: SimpleNamespace(
                server_address=("127.0.0.1", 43211),
                serve_forever=lambda: None,
                shutdown=lambda: None,
                server_close=lambda: None,
            ),
            readiness_wait=ready,
            browser_open=lambda url: pytest.fail("browser must not open before readiness"),
            candidate_preflight=_fake_preflight,  # type: ignore[arg-type]
        )


def test_launcher_reports_browser_exception_with_manual_url(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    catalog = repo / "reports" / "publish" / "work_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"works":[]}', encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    output: list[str] = []

    def browser(url: str) -> bool:
        raise OSError("no registered browser")

    launch(
        catalog,
        [candidate],
        static_root=_built_frontend(tmp_path),
        repository_root=repo,
        server_factory=lambda *args, **kwargs: SimpleNamespace(
            server_address=("127.0.0.1", 43212),
            serve_forever=lambda: None,
            shutdown=lambda: None,
            server_close=lambda: None,
        ),
        readiness_wait=lambda *args, **kwargs: None,
        browser_open=browser,
        output=output.append,
        candidate_preflight=_fake_preflight,  # type: ignore[arg-type]
    )

    assert any(
        "no registered browser" in message
        and "http://127.0.0.1:43212/review" in message
        and "manually" in message
        for message in output
    )


@pytest.mark.parametrize(
    "ready_body",
    [b'<div id="review-root"></div>', b"<div id='review-root'></div>"],
)
def test_wait_for_ready_retries_until_built_entrypoint_is_reachable(
    ready_body: bytes,
) -> None:
    class Response:
        def __init__(self, status: int, body: bytes) -> None:
            self.status = status
            self._body = body

        def read(self, limit: int) -> bytes:
            assert limit == 4096
            return self._body

        def close(self) -> None:
            return None

    responses = iter(
        [
            Response(503, b"not ready"),
            Response(200, ready_body),
        ]
    )
    now = [0.0]
    calls: list[tuple[str, float]] = []

    def opener(url: str, timeout: float) -> Response:
        calls.append((url, timeout))
        return next(responses)

    def sleeper(seconds: float) -> None:
        now[0] += seconds

    wait_for_ready(
        "http://127.0.0.1:8766/review",
        timeout=1,
        poll_interval=0.1,
        opener=opener,
        sleeper=sleeper,
        clock=lambda: now[0],
    )

    assert len(calls) == 2
