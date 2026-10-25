"""Small Windows launcher for the local, read-only Corpus Review Viewer."""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import importlib.machinery
import importlib.util
import os
from pathlib import Path
from pathlib import PurePosixPath
import sys
import time
from threading import Thread
from typing import Callable, Iterable, TextIO
from urllib.parse import unquote, urlsplit
import webbrowser
from urllib.request import urlopen

# Direct-file invocation is the supported external entrypoint. Pin before any
# CVW/kernel import; never repair already-loaded modules from another checkout.
_IMPLEMENTATION_ROOT = Path(__file__).resolve().parents[1]
_PROTECTED_ENTRYPOINT = __name__ in {"__main__", "cvw_protected_launcher"}
_IMPORT_ROOT_PINNED = _PROTECTED_ENTRYPOINT and not any(
    name == "cvw_app" or name.startswith("cvw_app.") for name in sys.modules
)
if _PROTECTED_ENTRYPOINT:
    sys.path.insert(0, str(_IMPLEMENTATION_ROOT))
    # Pin only our two packages. Removing a competing package's sys.path entry
    # can also remove unrelated dependencies installed in the same site-packages.
    # Existing modules remain untouched and must pass loaded_origins at launch.
    for _package in ("cvw_app", "ocd_kernel"):
        if _package not in sys.modules:
            _spec = importlib.machinery.PathFinder.find_spec(_package, [str(_IMPLEMENTATION_ROOT)])
            if _spec is None:
                raise ImportError(f"Missing local package: {_package}")
            _module = importlib.util.module_from_spec(_spec)
            _module.__path__ = [str(_IMPLEMENTATION_ROOT / _package)]
            sys.modules[_package] = _module
            if _spec.loader is not None:
                _spec.loader.exec_module(_module)
    sys.modules["cvw_app.launch_windows"] = sys.modules[__name__]

from ocd_kernel.lib.path_io import io_path, resolve_path, io_glob, io_rglob, io_iterdir  # noqa: E402 - pin imports to this checkout first

from ocd_kernel.lib.storage_topology import (
    EXTERNAL_DATA_ROOTS,
    StorageTopologyError,
    resolve_repo_path,
    storage_read_phase,
)
from cvw_app.review_contract import ReviewApplication, ReviewContractError
from cvw_app.review_service import ReviewHTTPServer, make_server
from cvw_app.session_observability import (
    SessionRecorder,
    make_session_descriptor,
    new_session_id,
    sha256_file,
    update_session_descriptor,
    utc_now_iso,
)
from cvw_app.serving_identity import (
    ServingIdentity, ServingIdentityError, file_identity, loaded_origins,
)

_IMPORTED_BYTES = {
    str(Path(module.__file__).resolve()): file_identity(Path(module.__file__))
    for name, module in sys.modules.copy().items()
    if name.split(".")[0] in {"cvw_app", "ocd_kernel"}
    and getattr(module, "__file__", None)
}


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 0
DEFAULT_READY_TIMEOUT = 15.0
DEFAULT_POLL_INTERVAL = 0.1
_PROTECTED_CANDIDATE_ROOTS = (
    "data",
    "ir",
    "raw",
    "reports",
    "exports",
    ".git",
    ".scratch",
    "graphify-out",
)


class LaunchError(RuntimeError):
    """Raised when the local viewer cannot be started safely."""


@dataclass(frozen=True)
class LaunchPaths:
    """Resolved read-only inputs for one launcher invocation."""

    repository_root: Path
    catalog_path: Path | None
    candidate_dirs: tuple[Path, ...]
    static_root: Path


@dataclass(frozen=True)
class CandidatePreflight:
    """Actionable identity summary for one explicit current-session candidate."""

    path: Path
    work_ids: tuple[str, ...]
    source_id: str
    source_manifest_path: str
    source_manifest_sha256: str
    candidate_sha256: str
    validation_report_sha256: str
    validation_status: str


def _existing_path(value: Path, label: str, *, directory: bool = False) -> Path:
    try:
        resolved = resolve_path(Path(value).expanduser(), strict=True)
    except (OSError, RuntimeError) as error:
        raise LaunchError(f"{label} is unavailable: {value} ({error})") from error
    if directory and not io_path(resolved).is_dir():
        raise LaunchError(f"{label} is not a directory: {resolved}")
    if not directory and not io_path(resolved).is_file():
        raise LaunchError(f"{label} is not a file: {resolved}")
    return resolved


def _validate_built_frontend(static_root: Path) -> Path:
    """Require the Vite production entrypoint, never a source-tree fallback."""

    root = _existing_path(static_root, "built frontend directory", directory=True)
    entrypoint = root / "review.html"
    if not io_path(entrypoint).is_file():
        raise LaunchError(
            f"built frontend is incomplete: expected {entrypoint}; run `npm run build` in cvw_app"
        )
    try:
        document = io_path(entrypoint).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise LaunchError(f"built frontend entrypoint is unreadable: {entrypoint} ({error})") from error
    if 'id="review-root"' not in document and "id='review-root'" not in document:
        raise LaunchError(f"built frontend entrypoint has no review root: {entrypoint}")
    if "/src/" in document or "src/review/" in document:
        raise LaunchError(
            f"built frontend entrypoint still references source modules: {entrypoint}; run `npm run build`"
        )
    assets = root / "assets"
    try:
        has_assets = io_path(assets).is_dir() and any(io_path(path).is_file() for path in io_iterdir(assets))
    except OSError as error:
        raise LaunchError(f"built frontend assets are unreadable: {assets} ({error})") from error
    if not has_assets:
        raise LaunchError(
            f"built frontend has no production assets under {assets}; run `npm run build` in cvw_app"
        )
    parser = _AssetReferenceParser()
    parser.feed(document)
    parser.close()
    if not any(kind == "JavaScript" for kind, _ in parser.references):
        raise LaunchError(
            f"built frontend entrypoint has no local JavaScript bundle reference: {entrypoint}"
        )
    for kind, reference in parser.references:
        _validate_local_asset_reference(root, kind, reference)
    source_root = root.parent / "src"
    if io_path(source_root).is_dir():
        build_inputs = [
            path
            for path in io_rglob(source_root, "*")
            if io_path(path).is_file() and path.suffix.lower() in {".ts", ".tsx", ".css"}
        ]
        build_inputs.extend(
            path
            for path in (
                root.parent / "review.html",
                root.parent / "vite.config.ts",
                root.parent / "package.json",
                root.parent / "package-lock.json",
                root.parent / "tsconfig.json",
            )
            if io_path(path).is_file()
        )
        try:
            newest_input = max(build_inputs, key=lambda path: io_path(path).stat().st_mtime)
            if io_path(newest_input).stat().st_mtime > io_path(entrypoint).stat().st_mtime:
                raise LaunchError(
                    "built frontend is stale: "
                    f"{newest_input} is newer than {entrypoint}; run `npm run build` in cvw_app"
                )
        except ValueError:
            pass
        except OSError as error:
            raise LaunchError(f"frontend build freshness could not be verified: {error}") from error
    return root


class _AssetReferenceParser(HTMLParser):
    """Collect local JavaScript and stylesheet references from the built entrypoint."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.casefold(): value for name, value in attrs}
        normalized_tag = tag.casefold()
        if normalized_tag == "script" and "src" in values:
            self.references.append(("JavaScript", values["src"] or ""))
        elif normalized_tag == "link" and "href" in values:
            rel = (values.get("rel") or "").casefold().split()
            if "stylesheet" in rel:
                self.references.append(("CSS", values["href"] or ""))


def _validate_local_asset_reference(static_root: Path, kind: str, reference: str) -> None:
    try:
        parsed = urlsplit(reference)
    except ValueError as error:
        raise LaunchError(
            f"built frontend {kind} asset reference is malformed: {reference} ({error})"
        ) from error
    if parsed.scheme or parsed.netloc:
        raise LaunchError(
            f"built frontend {kind} asset reference must resolve inside static root: {reference}"
        )
    decoded = unquote(parsed.path).replace("\\", "/")
    relative_text = decoded.lstrip("/")
    relative = PurePosixPath(relative_text)
    suffixes = {"JavaScript": {".js", ".mjs"}, "CSS": {".css"}}
    if relative.suffix.casefold() not in suffixes[kind]:
        raise LaunchError(
            f"built frontend {kind} reference is not a local {kind} asset: {reference}"
        )
    if not relative_text or relative.is_absolute() or ".." in relative.parts:
        raise LaunchError(
            f"built frontend {kind} asset reference escapes static root: {reference}"
        )
    resolved = resolve_path(static_root / Path(*relative.parts))
    if not resolved.is_relative_to(static_root):
        raise LaunchError(
            f"built frontend {kind} asset reference escapes static root: {reference}"
        )
    if not io_path(resolved).is_file():
        raise LaunchError(f"built frontend {kind} asset is missing: {resolved}")


def _reject_protected_candidate(candidate: Path, repository_root: Path) -> None:
    if candidate == repository_root:
        raise LaunchError(
            f"candidate directory must be outside the repository root: {candidate}"
        )
    protected = [
        resolve_path(repository_root / name)
        for name in _PROTECTED_CANDIDATE_ROOTS
    ]
    try:
        protected.extend(
            resolve_repo_path(repository_root, name)
            for name in sorted(EXTERNAL_DATA_ROOTS)
        )
    except StorageTopologyError as error:
        raise LaunchError(f"repository storage topology is invalid: {error}") from error
    protected.append(resolve_path(repository_root / "cvw_app" / "dist"))
    for root in protected:
        if candidate == root or candidate.is_relative_to(root):
            raise LaunchError(
                f"candidate directory is under a protected repository path: {candidate}"
            )


def _validate_candidate_children(candidate: Path, repository_root: Path) -> None:
    """Keep package and validation paths inside the explicit candidate root."""

    for name in ("package", "validation.json", "text-quality.json"):
        child = candidate / name
        try:
            resolved = resolve_path(child, strict=False)
        except (OSError, RuntimeError) as error:
            raise LaunchError(
                f"candidate {name} path cannot be resolved safely: {child} ({error})"
            ) from error
        _reject_protected_candidate(resolved, repository_root)
        if not resolved.is_relative_to(candidate):
            raise LaunchError(
                f"candidate {name} resolves outside candidate outer root: {child} -> {resolved}"
            )


def resolve_launch_paths(
    catalog_path: Path | None,
    candidate_dirs: Iterable[Path],
    *,
    static_root: Path | None = None,
    repository_root: Path | None = None,
    declared_library: bool = False,
) -> LaunchPaths:
    """Resolve and validate launcher inputs without copying or writing anything."""

    repo = _existing_path(
        repository_root or Path(__file__).resolve().parents[1],
        "repository root",
        directory=True,
    )
    if declared_library and catalog_path is not None:
        raise LaunchError("choose declared library or historical catalog, not both")
    catalog = None if catalog_path is None else _existing_path(
        catalog_path,
        "WorkCatalog",
    )
    frontend = _validate_built_frontend(
        static_root or Path(__file__).resolve().parent / "dist"
    )

    resolved_candidates: list[Path] = []
    seen: set[Path] = set()
    for index, value in enumerate(candidate_dirs, start=1):
        candidate = _existing_path(value, f"candidate directory {index}", directory=True)
        _reject_protected_candidate(candidate, repo)
        _validate_candidate_children(candidate, repo)
        if candidate in seen:
            raise LaunchError(f"candidate directory is duplicated: {candidate}")
        seen.add(candidate)
        resolved_candidates.append(candidate)
    if not resolved_candidates:
        raise LaunchError(
            "at least one explicit --candidate-dir is required; CVW never discovers or creates candidates"
        )

    return LaunchPaths(repo, catalog, tuple(resolved_candidates), frontend)


def preflight_candidate_session(
    paths: LaunchPaths,
) -> tuple[ReviewApplication, tuple[CandidatePreflight, ...]]:
    """Validate and summarize every explicit candidate before binding a socket."""

    try:
        with storage_read_phase():
            application = ReviewApplication.from_declared_library(
                paths.repository_root, paths.candidate_dirs,
            ) if paths.catalog_path is None else ReviewApplication.from_work_catalog(
                paths.catalog_path,
                paths.candidate_dirs,
                repository_root=paths.repository_root,
            )
    except (OSError, UnicodeDecodeError, ValueError, ReviewContractError) as error:
        raise LaunchError(f"CVW candidate-session preflight failed: {error}") from error

    bindings = application.candidate_session_bindings()
    if len(bindings) != len(paths.candidate_dirs):
        raise LaunchError(
            "CVW candidate-session preflight returned an incomplete candidate identity set"
        )
    summaries = [
        CandidatePreflight(
            path=binding.path,
            work_ids=binding.work_ids,
            source_id=binding.source_id,
            source_manifest_path=binding.source_manifest_path,
            source_manifest_sha256=binding.source_manifest_sha256,
            candidate_sha256=binding.candidate_sha256,
            validation_report_sha256=binding.validation_report_sha256,
            validation_status=binding.validation_status,
        )
        for binding in bindings
    ]
    return application, tuple(summaries)


def _response_status(response: object) -> int:
    status = getattr(response, "status", None)
    if status is None:
        getcode = getattr(response, "getcode", None)
        status = getcode() if callable(getcode) else None
    if not isinstance(status, int):
        raise LaunchError("readiness response did not include an HTTP status")
    return status


def wait_for_ready(
    url: str,
    *,
    timeout: float = DEFAULT_READY_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    opener: Callable[..., object] = urlopen,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Wait for a reachable built viewer entrypoint before opening a browser."""

    if timeout <= 0:
        raise LaunchError("readiness timeout must be greater than zero")
    if poll_interval < 0:
        raise LaunchError("readiness poll interval must not be negative")
    deadline = clock() + timeout
    last_error = "no response"
    while True:
        remaining = deadline - clock()
        if remaining < 0:
            raise LaunchError(
                f"service did not become ready at {url} within {timeout:g}s ({last_error}); "
                f"open the URL manually only after the service is running"
            )
        try:
            response = opener(url, timeout=max(0.1, min(1.0, remaining)))
            try:
                status = _response_status(response)
                body = response.read(4096)  # type: ignore[attr-defined]
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            if status == 200 and (
                b'id="review-root"' in body or b"id='review-root'" in body
            ):
                return
            last_error = f"HTTP {status} or missing review root"
        except (OSError, ValueError, LaunchError) as error:
            last_error = str(error)
        remaining = deadline - clock()
        if remaining <= 0:
            continue
        if poll_interval:
            sleeper(min(poll_interval, remaining))


def _viewer_url(host: str, port: int) -> str:
    display_host = "127.0.0.1" if host == "localhost" else host
    return f"http://{display_host}:{port}/review"


def _origin_url(host: str, port: int) -> str:
    display_host = "127.0.0.1" if host == "localhost" else host
    return f"http://{display_host}:{port}"


def _input_identity_batch(paths: Iterable[Path]) -> list[tuple[Path, Path, dict[str, object]]]:
    return [(path, resolve_path(path), file_identity(path)) for path in paths]


@storage_read_phase()
def _protected_inputs(paths: LaunchPaths, application: ReviewApplication, preflight: tuple[CandidatePreflight, ...]) -> tuple[set[Path], dict[str, object]]:
    """Resolve exact source authorities as well as both repository data planes."""
    roots = {paths.repository_root, _IMPLEMENTATION_ROOT, paths.static_root, *paths.candidate_dirs}
    for repo in (paths.repository_root, _IMPLEMENTATION_ROOT):
        roots.update(resolve_path(repo / name) for name in (*_PROTECTED_CANDIDATE_ROOTS, "schemas", "acceptance", "publication"))
        roots.update(resolve_repo_path(repo, name) for name in EXTERNAL_DATA_ROOTS)
    roots.update(resolve_path(Path(root)) for root in getattr(application, "roots", {}).values())
    files = {paths.catalog_path} if paths.catalog_path is not None else set()
    if paths.catalog_path is None:
        for binding in application.candidate_session_bindings():
            for work_id in binding.work_ids:
                work_root = paths.repository_root / "library/works" / work_id
                files.add(resolve_path(io_path(work_root / "work.json"), strict=True, preserve_prefix=True))
                files.update(
                    resolve_path(io_path(path), strict=True, preserve_prefix=True)
                    for path in io_glob(
                        work_root, "forms/*/editions/*/acquisitions/*.json"
                    )
                )
    files.update(repo / ".ocd-storage.json" for repo in (paths.repository_root, _IMPLEMENTATION_ROOT) if (io_path(repo / ".ocd-storage.json")).is_file())
    for candidate in paths.candidate_dirs:
        files.update(resolve_path(path) for path in io_rglob(candidate, "*") if io_path(path).is_file())
    for item in preflight:
        manifest = paths.repository_root / item.source_manifest_path
        if sha256_file(manifest) != item.source_manifest_sha256:
            raise LaunchError("source manifest changed after candidate validation")
        files.add(resolve_path(manifest))
        record = json.loads(io_path(manifest).read_text(encoding="utf-8"))
        input_paths = [authority["path"] for authority in record.get("authorities", [])]
        # SourceManifest.verify reads these bindings separately; they need not
        # also occur in authorities, but still require observed byte identities.
        input_paths.extend((
            record["converter"]["implementation_path"],
            record["validator"]["implementation_path"],
            record["package_schema"]["path"],
        ))
        for input_path in input_paths:
            relative = Path(input_path)
            if relative.is_absolute() or ".." in relative.parts:
                raise LaunchError("source authority must be repository-relative")
            try:
                authority_path = resolve_repo_path(
                    paths.repository_root, input_path, strict=True
                )
                files.add(io_path(authority_path))
            except (OSError, StorageTopologyError) as error:
                raise LaunchError(
                    f"source authority is unavailable: {input_path}"
                ) from error
    # Exact external authorities may be reached through a repository junction.
    roots.update(files)
    # Preserve explicit I/O identities while protecting their ordinary aliases.
    # Resolve once per file and hash the bytes only once for both spellings.
    identities = {}
    ordered = sorted(files)
    chunks = (ordered[start:start + 128] for start in range(0, len(ordered), 128))
    with (ThreadPoolExecutor(max_workers=4) if len(ordered) > 128 else nullcontext()) as executor:
        batches = executor.map(_input_identity_batch, chunks) if executor else map(_input_identity_batch, chunks)
        for batch in batches:
            for path, ordinary, identity in batch:
                roots.add(ordinary)
                identities[str(path)] = identity
                identities[str(ordinary)] = identity
    identities["repository_root"] = str(paths.repository_root)
    identities["protected_roots"] = sorted(str(root) for root in roots)
    return roots, identities


def validate_session_output(output: Path | None, session_id: str, roots: set[Path]) -> Path | None:
    """No writes; resolved existing parents cover absent descendants and aliases.

    Matches the shared destination policy's lexical AND physical containment
    rules. Session directories may contain previous sessions, so the candidate
    policy's empty-directory ownership requirement does not apply. Final output
    files must be new: this also refuses hard links and prior session collisions.
    Assumes a local operator, not hostile concurrent reparse-point replacement.
    """
    if output is None:
        return None
    requested = Path(os.path.abspath(output.expanduser()))
    resolved = resolve_path(requested, strict=False)
    for path in (requested, resolved):
        if any(path == root or path.is_relative_to(root) for root in roots):
            raise LaunchError("session output resolves inside protected input or implementation storage")
    if io_path(resolved).exists() and not io_path(resolved).is_dir():
        raise LaunchError("session output must be a directory")
    for suffix in ("events.jsonl", "receipt.json"):
        target = resolved / f"{session_id}.{suffix}"
        physical = resolve_path(target, strict=False)
        if any(physical == root or physical.is_relative_to(root) for root in roots):
            raise LaunchError("session output target resolves inside protected input")
        if os.path.lexists(io_path(target)):
            raise LaunchError("session output target already exists; choose a fresh session")
    return resolved


def launch(
    catalog_path: Path | None,
    candidate_dirs: Iterable[Path],
    *,
    static_root: Path | None = None,
    repository_root: Path | None = None,
    declared_library: bool = False,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    readiness_timeout: float = DEFAULT_READY_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    server_factory: Callable[..., ReviewHTTPServer] = make_server,
    readiness_wait: Callable[..., None] = wait_for_ready,
    browser_open: Callable[[str], bool] = webbrowser.open,
    output: Callable[[str], None] = print,
    candidate_preflight: Callable[[LaunchPaths], tuple[ReviewApplication, tuple[CandidatePreflight, ...]]] = preflight_candidate_session,
    session_output: Path | None = None,
    session_id_factory: Callable[[], str] = new_session_id,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Validate inputs, seal identity, serve, and report bounded lifecycle evidence.

    Phases are sequential elapsed intervals. time_to_ready_ms starts at launcher
    entry; browser dispatch and process lifetime are separate. Runtime evidence
    is printed even when no persistent diagnostics were requested.
    """
    started = clock()
    started_at = utc_now_iso()
    session_id = session_id_factory()
    recorder = SessionRecorder(session_id)
    descriptor = make_session_descriptor(session_id=session_id, host=host, requested_port=port,
        port=None, origin=None, pid=os.getpid(), state="starting")
    phases: dict[str, dict[str, object]] = {}
    server: ReviewHTTPServer | None = None
    thread: Thread | None = None
    thread_started = False
    primary_error: BaseException | None = None
    current_phase = "resolve_inputs"

    def publish(**fields: object) -> None:
        nonlocal descriptor
        descriptor = update_session_descriptor(descriptor, phases={name: dict(value) for name, value in phases.items()}, **fields)
        if server is not None:
            server.session_descriptor = descriptor
        recorder.write_receipt(descriptor)

    @contextmanager
    def phase(name: str):
        nonlocal current_phase
        current_phase = name
        beginning = clock()
        row: dict[str, object] = {"outcome": "entered", "started_at_utc": utc_now_iso()}
        phases[name] = row
        recorder.emit("phase_start", phase=name)
        try:
            yield row
        except BaseException as error:
            row.update(outcome="failed", error_type=type(error).__name__, message=str(error))
            raise
        else:
            row.setdefault("completed", True)
            if row["outcome"] == "entered":
                row["outcome"] = "completed"
        finally:
            row["elapsed_ms"] = max(0, round((clock() - beginning) * 1000))
            recorder.emit("phase_complete", phase=name, **row)
            publish()

    try:
        with phase("resolve_inputs"):
            if host not in {"127.0.0.1", "localhost"}:
                raise LaunchError("CVW must bind to loopback only (127.0.0.1 or localhost)")
            if not 0 <= port <= 65535:
                raise LaunchError("CVW port must be between 0 and 65535")
            if readiness_timeout <= 0 or poll_interval < 0:
                raise LaunchError("readiness timeout must be positive and poll interval nonnegative")
            paths = resolve_launch_paths(catalog_path, candidate_dirs, static_root=static_root, repository_root=repository_root, declared_library=declared_library)
        with phase("candidate_validation"):
            application, preflight = candidate_preflight(paths)
        # No output directory is created until source roots are known and every
        # launch input passed. Resolution/validation failures remain stdout-only.
        with phase("identity"):
            protected, input_identities = _protected_inputs(paths, application, preflight)
            approved_output = validate_session_output(session_output, session_id, protected)
            loaded_origins(_IMPLEMENTATION_ROOT)
            if any(file_identity(Path(path)) != identity for path, identity in _IMPORTED_BYTES.items()):
                raise LaunchError("loaded implementation changed since import; restart the launcher")
            identity = ServingIdentity(_IMPLEMENTATION_ROOT, paths.static_root)
            snapshot = identity.startup_snapshot(started_at=started_at, pinned=_IMPORT_ROOT_PINNED, protected_inputs=input_identities)
            recorder.startup_snapshot = snapshot
            publish(state="preflighted", catalog_sha256=sha256_file(paths.catalog_path) if paths.catalog_path else None,
                candidate_sha256=[item.candidate_sha256 for item in preflight],
                implementation_sha256=identity.sha256, implementation_contract=identity.manifest["contract"],
                startup_snapshot_sha256=snapshot["snapshot_sha256"],
                preflight_elapsed_ms=phases["candidate_validation"]["elapsed_ms"])
        try:
            recorder.initialize(approved_output, descriptor)
        except (OSError, ValueError) as error:
            raise LaunchError(f"CVW session output is unavailable: {error}") from error
        recorder.emit("preflight_complete", phase="candidate_validation", elapsed_ms=phases["candidate_validation"]["elapsed_ms"])
        output("CVW_STARTUP_SNAPSHOT " + json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
        output(f"CVW WorkCatalog: {paths.catalog_path}" if paths.catalog_path else "CVW identity: declared work and acquisition sidecars")
        output(f"CVW session: {session_id}")
        for label, path in recorder.paths().items():
            output(f"CVW session {label}: {path}")
        for item in preflight:
            output(f"Candidate: {item.path}; work(s): {', '.join(item.work_ids)}; source: {item.source_manifest_path}; source SHA-256: {item.source_manifest_sha256}; candidate SHA-256: {item.candidate_sha256}; validation: {item.validation_status} ({item.validation_report_sha256})")
        with phase("bind"):
            server = server_factory(paths.catalog_path, list(paths.candidate_dirs), static_root=paths.static_root,
                host=host, port=port, repository_root=paths.repository_root, application=application,
                session_descriptor=descriptor, event_sink=recorder.emit, serving_identity=identity)
            actual_port = int(server.server_address[1])
            url = _viewer_url(host, actual_port)
            recorder.origin = _origin_url(host, actual_port)
            publish(state="bound", port=actual_port, origin=recorder.origin)
            recorder.emit("bound", port=actual_port)
        serve_errors: list[BaseException] = []

        def serve() -> None:
            try:
                server.serve_forever()
            except BaseException as error:
                serve_errors.append(error)

        with phase("thread_start"):
            thread = Thread(target=serve, name="cvw-loopback", daemon=True)
            thread.start()
            thread_started = True
        with phase("readiness"):
            readiness_wait(url, timeout=readiness_timeout, poll_interval=poll_interval)
            if serve_errors:
                raise LaunchError(f"server thread failed: {serve_errors[0]}") from serve_errors[0]
            identity.verify()
        publish(state="ready", time_to_ready_ms=max(0, round((clock() - started) * 1000)), browser_dispatch="not_attempted")
        recorder.emit("ready", url=url, port=actual_port)
        output("CVW_SESSION_READY " + json.dumps(descriptor["session"], ensure_ascii=False, sort_keys=True))
        output(f"CVW is ready at {url}")
        with phase("browser_dispatch") as browser_phase:
            recorder.emit("browser_open_attempt", url=url)
            try:
                opened = browser_open(url)
            except (OSError, webbrowser.Error) as error:
                result = "exception"
                browser_phase.update(outcome="failed", error_type=type(error).__name__, message=str(error))
                output(f"The browser could not be opened automatically ({error}); open {url} manually.")
            else:
                result = "accepted" if opened else "returned_false"
                if not opened:
                    browser_phase.update(outcome="failed", message="browser returned false")
                    output(f"The browser could not be opened automatically; open {url} manually.")
            publish(browser_dispatch=result)
            recorder.emit("browser_open_result", outcome=result, url=url, meaning="dispatch only; pixels unverified")
        current_phase = "serving"
        thread.join()
        if serve_errors:
            raise LaunchError(f"server thread failed: {serve_errors[0]}") from serve_errors[0]
    except KeyboardInterrupt:
        publish(state="stopping")
        recorder.emit("shutdown_requested")
        output("Stopping CVW.")
    except BaseException as error:
        primary_error = error
        publish(state="failed", failed_phase=current_phase, error_code=f"{current_phase}-failed", error_message=str(error))
        recorder.emit("error", phase=current_phase, error_type=type(error).__name__, message=str(error))
        raise
    finally:
        cleanup_errors: list[str] = []
        if server is not None:
            with phase("shutdown") as shutdown_phase:
                recorder.emit("shutdown_start")
                if thread_started and thread is not None and thread.is_alive():
                    try:
                        server.shutdown()
                    except (OSError, RuntimeError) as error:
                        cleanup_errors.append(f"shutdown: {error}")
                try:
                    server.server_close()
                except (OSError, RuntimeError) as error:
                    cleanup_errors.append(f"server_close: {error}")
                if thread_started and thread is not None:
                    try:
                        thread.join(timeout=2)
                    except RuntimeError as error:
                        cleanup_errors.append(f"thread_join: {error}")
                    if thread.is_alive():
                        cleanup_errors.append("thread_join: shutdown timeout")
                if cleanup_errors:
                    shutdown_phase.update(outcome="failed", errors=cleanup_errors)
                    if primary_error is None:
                        publish(state="shutdown-failed", failed_phase="shutdown", error_code="shutdown-failed", error_message="; ".join(cleanup_errors))
                elif primary_error is None:
                    publish(state="stopped")
                recorder.emit("shutdown", state=descriptor["session"]["state"], errors=cleanup_errors)
        publish(process_lifetime_ms=max(0, round((clock() - started) * 1000)))
        output("CVW_SESSION_FINAL " + json.dumps(descriptor["session"], ensure_ascii=False, sort_keys=True))
        if cleanup_errors and primary_error is None:
            raise LaunchError("CVW shutdown failed: " + "; ".join(cleanup_errors))
    return url


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch the local Windows Corpus Review Viewer"
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        metavar="PATH",
        help="Explicit historical WorkCatalog path; omitted uses declared library sidecars",
    )
    parser.add_argument("--declared-library", action="store_true", help="Bind candidates through declared work/acquisition sidecars without WorkCatalog")
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="Validated current-session candidate directory; repeat for another work",
    )
    parser.add_argument(
        "--static-root",
        type=Path,
        default=None,
        metavar="PATH",
        help="Built cvw_app/dist directory (default: cvw_app/dist)",
    )
    parser.add_argument("--repository-root", type=Path, default=None, help="Explicit input repository authority (independent of implementation root)")
    parser.add_argument("--host", default=DEFAULT_HOST, choices=("127.0.0.1", "localhost"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--session-output",
        type=Path,
        default=None,
        metavar="PATH",
        help="Optional directory for this launch's JSONL events and receipt",
    )
    parser.add_argument("--ready-timeout", type=float, default=DEFAULT_READY_TIMEOUT, metavar="SECONDS")
    parser.add_argument("--ready-poll", type=float, default=DEFAULT_POLL_INTERVAL, metavar="SECONDS")
    return parser


def main(argv: list[str] | None = None, *, stderr: TextIO | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        launch(
            args.catalog,
            args.candidate_dir,
            static_root=args.static_root,
            repository_root=args.repository_root,
            declared_library=args.declared_library,
            host=args.host,
            port=args.port,
            session_output=args.session_output,
            readiness_timeout=args.ready_timeout,
            poll_interval=args.ready_poll,
        )
    except (LaunchError, ServingIdentityError, OSError, ValueError, ReviewContractError) as error:
        stream = stderr or sys.stderr
        print(f"cvw launch failed: {error}", file=stream)
        raise SystemExit(2)
    return 0


if __name__ == "__main__":
    main()
