from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from threading import Thread
from types import SimpleNamespace

import pytest

import cvw_app.launch_windows as launcher
import cvw_app.serving_identity as serving_identity
from cvw_app.review_contract import ReviewContractError
from cvw_app.review_service import ReviewHTTPServer, make_server
from cvw_app.session_observability import SessionRecorder
from cvw_app.serving_identity import ServingIdentity, ServingIdentityError, local_members, loaded_origins
from cvw_app.tests.test_launch_windows import _built_frontend, _symlink_or_skip


def inputs(tmp_path):
    repo = tmp_path / "input-repo"
    repo.mkdir()
    catalog = repo / "catalog.json"
    catalog.write_text('{"works":[]}', encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    return dict(catalog_path=catalog, candidate_dirs=[candidate], repository_root=repo,
                static_root=_built_frontend(tmp_path), candidate_preflight=lambda paths: (SimpleNamespace(roots={}), ()))


def fake_server(**overrides):
    values = dict(server_address=("127.0.0.1", 43822), serve_forever=lambda: None, shutdown=lambda: None, server_close=lambda: None)
    values.update(overrides)
    return SimpleNamespace(**values)


def tree_bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("destination", ["repo", "candidate", "static", "library", "implementation", "catalog-target"])
def test_diagnostic_rejection_precedes_all_output_writes(tmp_path, monkeypatch, destination):
    args = inputs(tmp_path)
    implementation = tmp_path / "implementation"
    implementation.mkdir()
    monkeypatch.setattr(launcher, "_IMPLEMENTATION_ROOT", implementation)
    library = tmp_path / "library"
    (library / "raw").mkdir(parents=True)
    (args["repository_root"] / ".ocd-storage.json").write_text(json.dumps({"library_root": str(library)}))
    out = {"repo": args["repository_root"] / "data" / "new", "candidate": args["candidate_dirs"][0] / "new",
           "static": args["static_root"] / "new", "library": library / "raw" / "new",
           "implementation": implementation / ".scratch" / "new", "catalog-target": args["catalog_path"]}[destination]
    before = tree_bytes(tmp_path)
    membership = sorted(str(path) for path in tmp_path.rglob("*"))
    with pytest.raises(launcher.LaunchError, match="protected"):
        launcher.launch(**args, session_output=out, output=lambda line: None)
    assert tree_bytes(tmp_path) == before
    assert sorted(str(path) for path in tmp_path.rglob("*")) == membership


@pytest.mark.parametrize("bad", [{"host": "0.0.0.0"}, {"port": -1}, {"readiness_timeout": 0}])
def test_invalid_launch_options_never_initialize_diagnostics(tmp_path, bad):
    args = inputs(tmp_path)
    out = tmp_path / "output"
    before = tree_bytes(tmp_path)
    with pytest.raises(launcher.LaunchError):
        launcher.launch(**args, **bad, session_output=out, output=lambda line: None)
    assert not out.exists()
    assert tree_bytes(tmp_path) == before


def test_windows_alias_and_existing_output_target_are_protected(tmp_path):
    protected = tmp_path / "inputs"
    protected.mkdir()
    (protected / "keep").write_bytes(b"source")
    alias = tmp_path / "alias"
    _symlink_or_skip(alias, protected, target_is_directory=True)
    try:
        with pytest.raises(launcher.LaunchError, match="protected"):
            launcher.validate_session_output(alias / "new" / "deeper", "session", {protected})
    finally:
        if alias.is_symlink():
            alias.unlink()
        else:
            alias.rmdir()
    out = tmp_path / "output"
    out.mkdir()
    target = out / "session.events.jsonl"
    os.link(protected / "keep", target)
    with pytest.raises(launcher.LaunchError, match="already exists"):
        launcher.validate_session_output(out, "session", {protected})
    assert (protected / "keep").read_bytes() == b"source"


def test_initial_unusable_output_is_strict(tmp_path, monkeypatch):
    args = inputs(tmp_path)
    original = Path.open
    def failed(path, *values, **kwargs):
        if ".receipt.json.tmp-" in path.name:
            raise PermissionError("initial output denied")
        return original(path, *values, **kwargs)
    monkeypatch.setattr(Path, "open", failed)
    with pytest.raises(launcher.LaunchError, match="session output is unavailable"):
        launcher.launch(**args, session_output=tmp_path / "output", output=lambda line: None,
                        server_factory=lambda *a, **k: pytest.fail("must not bind"))
    assert not list((tmp_path / "output").glob("*.tmp-*"))


@pytest.mark.parametrize("failure", ["write", "replace", "serialize"])
def test_atomic_receipt_preserves_last_good_snapshot(tmp_path, monkeypatch, failure, capsys):
    recorder = SessionRecorder("atomic", tmp_path)
    before = {"session": {"session_id": "atomic", "state": "old"}}
    recorder.write_receipt(before)
    if failure == "replace":
        monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("sharing violation")))
    elif failure == "write":
        original = Path.open
        def failed(path, *a, **kw):
            if ".tmp-" in path.name:
                raise OSError("disk full")
            return original(path, *a, **kw)
        monkeypatch.setattr(Path, "open", failed)
    after = {"session": {"session_id": "atomic", "state": object() if failure == "serialize" else "new"}}
    if failure == "serialize":
        with pytest.raises(TypeError):
            recorder.write_receipt(after)
    else:
        recorder.write_receipt(after)
        assert recorder.health.degraded
    assert json.loads(recorder.receipt_path.read_text()) == before
    assert not list(tmp_path.glob("*.tmp-*"))


def test_concurrent_receipt_readers_observe_complete_same_session(tmp_path):
    recorder = SessionRecorder("concurrent", tmp_path)
    recorder.write_receipt({"session_id": "concurrent", "sequence": 0, "payload": "0" * 3000})
    observations, read_errors = [], []
    def read():
        for _ in range(800):
            try:
                value = json.loads(recorder.receipt_path.read_text())
            except PermissionError:
                # Windows may refuse an open while replacement owns the name;
                # retry the read, never treat a refused open as partial JSON.
                continue
            except Exception as error:
                read_errors.append(error)
                return
            observations.append(value)
            if len(observations) == 80:
                return
    reader = Thread(target=read)
    reader.start()
    for number in range(1, 25):
        recorder.write_receipt({"session_id": "concurrent", "sequence": number, "payload": str(number) * 3000})
    reader.join(timeout=3)
    assert not reader.is_alive()
    assert not read_errors
    assert len(observations) == 80
    assert all(value["session_id"] == "concurrent" and value["payload"] == str(value["sequence"]) * 3000 for value in observations)
    assert not list(tmp_path.glob("*.tmp-*"))


def raw_get(server, path):
    with socket.create_connection(server.server_address, timeout=3) as connection:
        connection.sendall(f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())
        parts = []
        while part := connection.recv(65536):
            parts.append(part)
    response = b"".join(parts)
    headers, body = response.split(b"\r\n\r\n", 1)
    fields = dict(line.split(b": ", 1) for line in headers.split(b"\r\n")[1:])
    assert response.count(b"HTTP/1.0 ") == 1
    assert len(body) == int(fields[b"Content-Length"])
    return headers.split(b"\r\n")[0], fields, json.loads(body)


@pytest.mark.parametrize("permanent", [False, True])
@pytest.mark.parametrize("contract_failure", [False, True])
def test_launch_loopback_survives_diagnostics_failure_once_or_permanently(tmp_path, monkeypatch, capsys, permanent, contract_failure):
    args = inputs(tmp_path)
    def catalog():
        if contract_failure:
            raise ReviewContractError("original contract failure")
        return {"works": []}
    args["candidate_preflight"] = lambda paths: (SimpleNamespace(roots={}, catalog=catalog), ())
    captured = {}
    active_failure = [False]
    count = [0]
    original_open = Path.open
    def sometimes_failed(path, *a, **kw):
        if active_failure[0] and (path.name.endswith("events.jsonl") or ".receipt.json.tmp-" in path.name):
            count[0] += 1
            if permanent or count[0] == 1:
                raise OSError("diagnostic disk full")
        return original_open(path, *a, **kw)
    monkeypatch.setattr(Path, "open", sometimes_failed)
    def factory(*a, **kw):
        server = make_server(*a, **kw)
        captured["server"] = server
        return server
    def browser(url):
        active_failure[0] = True
        captured["first"] = raw_get(captured["server"], "/api/review/v1/works")
        captured["second"] = raw_get(captured["server"], "/api/review/v1/session")
        captured["server"].shutdown()
        return False
    lines = []
    launcher.launch(**args, server_factory=factory, browser_open=browser, session_output=tmp_path / "output", output=lines.append)
    status, headers, body = captured["first"]
    request_id = headers[b"X-CVW-Request-ID"].decode()
    assert status.split()[1] == (b"422" if contract_failure else b"200")
    if contract_failure:
        assert body["error"]["message"] == "original contract failure"
        assert body["error"]["request_id"] == request_id
    else:
        assert body == {"works": []}
    diagnostics = capsys.readouterr().err
    assert diagnostics.count("CVW_DIAGNOSTICS_DEGRADED") == 1
    assert request_id in diagnostics
    session = captured["second"][2]["session"]
    assert "startup_snapshot" not in captured["second"][2]
    assert str(tmp_path) not in json.dumps(session)
    snapshot = json.loads(next(line.removeprefix("CVW_STARTUP_SNAPSHOT ") for line in lines if line.startswith("CVW_STARTUP_SNAPSHOT ")))
    assert session["implementation_sha256"] == snapshot["implementation_sha256"]
    assert snapshot["loaded_module_origin_check"] == "pass"
    assert snapshot["import_root_pinned_before_cvw_import"] is False
    assert "unproven" in snapshot["import_identity_limitation"]
    assert all(row["resolved_path"].startswith(str(launcher._IMPLEMENTATION_ROOT)) for row in snapshot["loaded_cvw_modules"])
    assert captured["server"].socket.fileno() == -1
    final = json.loads(next(line.removeprefix("CVW_SESSION_FINAL ") for line in lines if line.startswith("CVW_SESSION_FINAL ")))
    assert final["state"] == "stopped"
    assert final["phases"]["shutdown"]["outcome"] == "completed"


def identity_fixture(tmp_path):
    root = tmp_path / "implementation"
    actual = Path(launcher.__file__).resolve().parents[1]
    for name in local_members(actual):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(actual / name, path)
    return root, _built_frontend(tmp_path)


@pytest.mark.parametrize("member", ["cvw_app/review_renderers.py", "cvw_app/review_contract.py", "ocd_kernel/reconstruction/contract.py", "schemas/v2/work.schema.json", "schemas/v2/acquisition.schema.json", "assets/app.js", "assets/app.css"])
def test_portable_manifest_detects_every_distinct_serving_class(tmp_path, member):
    root, static = identity_fixture(tmp_path)
    identity = ServingIdentity(root, static, runtime={})
    moved = tmp_path / "moved"
    shutil.copytree(root, moved)
    assert ServingIdentity(moved, static, runtime={}).sha256 == identity.sha256
    base = static if member.startswith("assets/") else root
    path = base / member
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n# changed" if path.suffix == ".py" else "\n/* changed */")
    assert ServingIdentity(root, static, runtime={}).sha256 != identity.sha256
    with pytest.raises(ServingIdentityError, match="relaunch"):
        identity.verify()


def test_missing_identity_member_fails_explicitly(tmp_path):
    root, static = identity_fixture(tmp_path)
    (root / "cvw_app/review_renderers.py").unlink()
    with pytest.raises(ServingIdentityError, match="missing"):
        ServingIdentity(root, static, runtime={})


@pytest.mark.parametrize("mutation", ["new-module", "new-initializer", "cvw-shadow", "missing", "same-size-mtime"])
def test_sealed_closure_rejects_membership_and_byte_drift_without_reparsing(tmp_path, monkeypatch, mutation):
    root, static = identity_fixture(tmp_path)
    identity = ServingIdentity(root, static, runtime={})
    monkeypatch.setattr(serving_identity.ast, "parse", lambda *a, **k: pytest.fail("request reparsed source"))
    identity.verify()
    path = root / "cvw_app/review_renderers.py"
    if mutation == "new-module":
        (root / "cvw_app/new_renderer.py").write_text("VALUE = 1", encoding="utf-8")
    elif mutation in {"new-initializer", "cvw-shadow"}:
        package = root / ("ocd_kernel/new_namespace" if mutation == "new-initializer" else "cvw_app/review_renderers")
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
    elif mutation == "missing":
        path.unlink()
    else:
        previous = path.stat()
        payload = bytearray(path.read_bytes())
        payload[-1] ^= 1
        path.write_bytes(payload)
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    with pytest.raises(ServingIdentityError, match="relaunch"):
        identity.verify()


@pytest.mark.parametrize("contract_failure", [False, True])
def test_identity_drift_during_response_generation_still_returns_one_refusal(tmp_path, contract_failure):
    root, static = identity_fixture(tmp_path)
    identity = ServingIdentity(root, static, runtime={})
    def catalog():
        (static / "assets/app.css").write_text("changed during request", encoding="utf-8")
        if contract_failure:
            raise ReviewContractError("contract failed during drift")
        return {"works": []}
    server = ReviewHTTPServer(("127.0.0.1", 0), SimpleNamespace(catalog=catalog), static, serving_identity=identity)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, body = raw_get(server, "/api/review/v1/works")
        assert b"503" in status
        assert body["error"]["code"] == "implementation-drift"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_service_refuses_drift_before_emitting_a_session_or_asset(tmp_path):
    root, static = identity_fixture(tmp_path)
    identity = ServingIdentity(root, static, runtime={})
    application = SimpleNamespace(stage_bytes=lambda *a, **k: (b'{}', 'application/pdf'))
    server = ReviewHTTPServer(("127.0.0.1", 0), application, static, serving_identity=identity)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (static / "assets/app.css").write_text("changed", encoding="utf-8")
        for path in ("/api/review/v1/session", "/review", "/assets/app.css",
                     "/api/review/v1/works/example/stages/source/bytes?expected_artifact=source&expected_version=v1"):
            status, _, body = raw_get(server, path)
            assert b"503" in status
            assert body["error"]["code"] == "implementation-drift"
            assert "relaunch" in body["error"]["message"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_package_shadow_initializer_is_in_startup_import_closure(tmp_path):
    root, static = identity_fixture(tmp_path)
    shadow = root / "cvw_app/native_images"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("VALUE = 1", encoding="utf-8")
    assert "cvw_app/native_images/__init__.py" in ServingIdentity(root, static, runtime={}).manifest["backend"]


def test_loaded_namespace_outside_root_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "cvw_app.ambiguous", SimpleNamespace(__file__=None, __path__=[str(tmp_path)]))
    with pytest.raises(ServingIdentityError, match="namespace outside"):
        loaded_origins(launcher._IMPLEMENTATION_ROOT)


def test_direct_external_launcher_pins_import_root_before_import(tmp_path):
    competitor = tmp_path / "competitor"
    (competitor / "cvw_app").mkdir(parents=True)
    (competitor / "cvw_app/review_service.py").write_text("raise RuntimeError('wrong service')")
    script = """import runpy, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
target = sys.argv[2]
sys.argv = [target, '--help']
try:
    runpy.run_path(target, run_name='__main__')
except SystemExit as error:
    assert error.code == 0
root = Path(target).resolve().parents[1]
assert all(Path(p).resolve().is_relative_to(root) for p in sys.modules['cvw_app'].__path__)
assert Path(sys.modules['cvw_app.review_service'].__file__).resolve().is_relative_to(root)
"""
    result = subprocess.run([sys.executable, "-c", script, str(competitor), str(Path(launcher.__file__).resolve())], check=True, capture_output=True, text=True)
    assert "--repository-root" in result.stdout


def test_external_launcher_keeps_shared_dependencies_beside_competing_packages(tmp_path):
    shared = tmp_path / "site-packages"
    for package in ("cvw_app", "ocd_kernel"):
        directory = shared / package
        directory.mkdir(parents=True)
        (directory / "__init__.py").write_text("raise RuntimeError('wrong package')", encoding="utf-8")
    (shared / "cvw_dependency_probe.py").write_text("VALUE = 'available'", encoding="utf-8")
    script = """import runpy, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
entry = runpy.run_path(sys.argv[2], run_name='cvw_protected_launcher')
import cvw_dependency_probe
assert cvw_dependency_probe.VALUE == 'available'
root = Path(sys.argv[2]).resolve().parents[1]
for name in ('cvw_app', 'ocd_kernel'):
    assert all(Path(path).resolve().is_relative_to(root) for path in sys.modules[name].__path__)
entry['loaded_origins'](root)
"""
    subprocess.run([sys.executable, "-c", script, str(shared), str(Path(launcher.__file__).resolve())],
                   check=True, capture_output=True, text=True)


@pytest.mark.parametrize("outcome", ["accepted", "returned_false", "exception"])
def test_browser_dispatch_truth_and_phase_timing_without_persistence(tmp_path, outcome):
    args = inputs(tmp_path)
    lines = []
    now = [0.0]
    def clock():
        now[0] += 0.01
        return now[0]
    def browser(url):
        if outcome == "exception":
            raise OSError("no browser")
        return outcome == "accepted"
    launcher.launch(**args, server_factory=lambda *a, **kw: fake_server(), readiness_wait=lambda *a, **kw: None,
                    browser_open=browser, output=lines.append, clock=clock)
    final = json.loads(next(line.removeprefix("CVW_SESSION_FINAL ") for line in lines if line.startswith("CVW_SESSION_FINAL ")))
    assert final["browser_dispatch"] == outcome
    assert final["state"] == "stopped"
    assert final["time_to_ready_ms"] < final["process_lifetime_ms"], final
    assert set(final["phases"]) == {"resolve_inputs", "candidate_validation", "identity", "bind", "thread_start", "readiness", "browser_dispatch", "shutdown"}, final["phases"]
    assert all(row["elapsed_ms"] == 10 and row["started_at_utc"].endswith("Z") for row in final["phases"].values()), final["phases"]
    assert not list(tmp_path.rglob("*.receipt.json"))


@pytest.mark.parametrize("phase_name", ["thread_start", "readiness", "shutdown"])
def test_failure_attribution_and_cleanup_preserve_primary(tmp_path, monkeypatch, phase_name):
    args = inputs(tmp_path)
    lines, closed = [], []
    if phase_name == "thread_start":
        monkeypatch.setattr(Thread, "start", lambda self: (_ for _ in ()).throw(RuntimeError("thread start failed")))
    def ready(*a, **kw):
        if phase_name == "readiness":
            raise launcher.LaunchError("primary readiness failure")
    def close():
        closed.append(True)
        raise OSError("cleanup failure")
    with pytest.raises((RuntimeError, launcher.LaunchError), match={"thread_start": "thread start failed", "readiness": "primary readiness failure", "shutdown": "shutdown failed"}[phase_name]):
        launcher.launch(**args, server_factory=lambda *a, **kw: fake_server(server_close=close), readiness_wait=ready,
                        browser_open=lambda url: True, output=lines.append)
    final = json.loads(next(line.removeprefix("CVW_SESSION_FINAL ") for line in lines if line.startswith("CVW_SESSION_FINAL ")))
    assert closed == [True]
    assert final["failed_phase"] == phase_name
    assert final["phases"][phase_name]["outcome"] == "failed"
    assert final["phases"]["shutdown"]["errors"] == ["server_close: cleanup failure"]
    if phase_name == "thread_start":
        assert "readiness" not in final["phases"]
    if phase_name != "shutdown":
        assert "browser_dispatch" not in final["phases"]


@pytest.mark.parametrize("permanent", [False, True])
def test_service_sink_failure_does_not_append_another_http_response(tmp_path, capsys, permanent):
    attempts = []
    def sink(event, **fields):
        attempts.append(fields)
        if permanent or len(attempts) == 1:
            raise OSError("sink unavailable")
    def catalog():
        raise ReviewContractError("primary contract error")
    static = _built_frontend(tmp_path)
    server = ReviewHTTPServer(("127.0.0.1", 0), SimpleNamespace(catalog=catalog), static, event_sink=sink)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path, expected in (("/api/review/v1/works", b"422"), ("/api/review/v1/session", b"200")):
            status, headers, body = raw_get(server, path)
            assert status.split()[1] == expected
            assert headers[b"X-CVW-Request-ID"].decode() == attempts[-1]["request_id"]
            if expected == b"422":
                assert body["error"]["message"] == "primary contract error"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert capsys.readouterr().err.count("CVW_DIAGNOSTICS_DEGRADED") == 1
    assert server.socket.fileno() == -1


def test_interrupted_temp_write_and_failed_cleanup_preserve_receipt(tmp_path, monkeypatch, capsys):
    recorder = SessionRecorder("interrupted", tmp_path)
    original = {"session_id": "interrupted", "state": "old"}
    recorder.write_receipt(original)
    original_open, original_unlink = Path.open, Path.unlink
    class InterruptedWriter:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, value):
            self.stream.write(value[:5])
            raise OSError("interrupted write")
    def partial(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return InterruptedWriter(stream) if ".tmp-" in path.name else stream
    def cleanup_failed(path, *args, **kwargs):
        if ".tmp-" in path.name:
            raise PermissionError("temp cleanup denied")
        return original_unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", partial)
        patch.setattr(Path, "unlink", cleanup_failed)
        recorder.write_receipt({"session_id": "interrupted", "state": "new"})
    assert json.loads(recorder.receipt_path.read_text()) == original
    assert recorder.health.degraded
    assert capsys.readouterr().err.count("CVW_DIAGNOSTICS_DEGRADED") == 1
    leftovers = list(tmp_path.glob("*.tmp-*"))
    assert len(leftovers) == 1
    for temporary in leftovers:
        temporary.unlink()


def test_shutdown_timeout_is_attributed_and_socket_close_is_attempted(tmp_path, monkeypatch):
    args = inputs(tmp_path)
    calls, lines = [], []
    class HungThread:
        def __init__(self, **kwargs):
            return
        def start(self):
            return
        def join(self, timeout=None):
            if timeout is None:
                raise KeyboardInterrupt()
            calls.append(("join", timeout))
        def is_alive(self):
            return True
    monkeypatch.setattr(launcher, "Thread", HungThread)
    server = fake_server(shutdown=lambda: calls.append("shutdown"), server_close=lambda: calls.append("close"))
    with pytest.raises(launcher.LaunchError, match="shutdown timeout"):
        launcher.launch(**args, server_factory=lambda *a, **kw: server, readiness_wait=lambda *a, **kw: None,
                        browser_open=lambda url: True, output=lines.append)
    final = json.loads(next(line.removeprefix("CVW_SESSION_FINAL ") for line in lines if line.startswith("CVW_SESSION_FINAL ")))
    assert final["state"] == "shutdown-failed"
    assert final["failed_phase"] == "shutdown"
    assert calls == ["shutdown", "close", ("join", 2)]
    assert final["phases"]["shutdown"]["outcome"] == "failed"


def test_public_descriptor_omits_local_exception_paths(tmp_path):
    server = ReviewHTTPServer(("127.0.0.1", 0), SimpleNamespace(), tmp_path)
    try:
        server.session_descriptor["session"].update(error_message=str(tmp_path), phases={"identity": {"message": str(tmp_path), "outcome": "failed", "elapsed_ms": 2}})
        public = server.public_session_descriptor()
        assert str(tmp_path) not in json.dumps(public)
        assert public["session"]["phases"]["identity"]["outcome"] == "failed"
    finally:
        server.server_close()



def test_runpy_external_entry_returns_pinned_callable_without_starting_server(tmp_path):
    script = """import runpy, sys
from pathlib import Path
entry = runpy.run_path(sys.argv[1], run_name='cvw_protected_launcher')
assert entry['_IMPORT_ROOT_PINNED'] is True
assert callable(entry['launch'])
root = Path(sys.argv[1]).resolve().parents[1]
assert all(Path(path).resolve().is_relative_to(root) for path in sys.modules['cvw_app'].__path__)
assert Path(sys.modules['cvw_app.launch_windows'].__file__).resolve().is_relative_to(root)
print('CVW_PINNED_CALLABLE')
"""
    result = subprocess.run([sys.executable, "-c", script, str(Path(launcher.__file__).resolve())], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "CVW_PINNED_CALLABLE"


def test_startup_snapshot_observes_separate_source_manifest_dependencies(tmp_path):
    from ocd_kernel.reconstruction.contract import SourceManifest

    args = inputs(tmp_path)
    repo = args["repository_root"]
    source = repo / "source.xml"
    source.write_bytes(b"<source>Retained text.</source>")
    dependencies = {
        "converter": ("implementation_path", "converter.py", b"# converter implementation\n"),
        "validator": ("implementation_path", "validator.py", b"# validation implementation\n"),
        "package_schema": ("path", "package-schema.json", b'{"type":"object"}\n'),
    }
    record = {
        "contract": "ocd-source-manifest-v1",
        "authorities": [{"name": "source", "path": source.name,
                         "bytes": source.stat().st_size,
                         "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
    }
    for section, (field, filename, content) in dependencies.items():
        (repo / filename).write_bytes(content)
        record[section] = {field: filename,
                           "sha256" if section == "package_schema" else "implementation_sha256": hashlib.sha256(content).hexdigest()}
        if section != "package_schema":
            record[section].update(callable="fixture:run", import_closure_sha256="a" * 64)
    manifest_path = repo / "source-manifest.json"
    manifest_path.write_text(json.dumps(record), encoding="utf-8")
    # These are valid SourceManifest inputs, intentionally absent from authorities.
    source_manifest = SourceManifest.load(manifest_path, repository_root=repo)
    assert [item["path"] for item in record["authorities"]] == [source.name]
    binding = launcher.CandidatePreflight(
        path=args["candidate_dirs"][0], work_ids=("fixture",), source_id="fixture",
        source_manifest_path=manifest_path.name, source_manifest_sha256=source_manifest.sha256,
        candidate_sha256="b" * 64, validation_report_sha256="c" * 64, validation_status="pass",
    )
    args["candidate_preflight"] = lambda paths: (SimpleNamespace(roots={}), (binding,))
    output_dir = tmp_path / "session-output"
    launcher.launch(**args, session_output=output_dir,
                    server_factory=lambda *a, **kw: fake_server(),
                    readiness_wait=lambda *a, **kw: None,
                    browser_open=lambda url: False, output=lambda line: None)
    receipt = json.loads(next(output_dir.glob("*.receipt.json")).read_text(encoding="utf-8"))
    snapshot = receipt["startup_snapshot"]
    for _, filename, content in dependencies.values():
        physical = str((repo / filename).resolve())
        assert snapshot["protected_input_identities"][physical] == {
            "byte_length": len(content), "sha256": hashlib.sha256(content).hexdigest(),
        }
        assert physical in snapshot["protected_input_identities"]["protected_roots"]
