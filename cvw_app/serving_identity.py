"""Portable serving-byte identity and private, at-launch import provenance.

Local source imports are discovered without executing them. This is a bounded
manifest, not a build system: dynamic local imports must be declared as roots.
Disk drift is rejected; static replies additionally bind the bytes actually read.
The local threat model excludes hostile concurrent filesystem/Python mutation.
"""

from __future__ import annotations

from ocd_kernel.lib.path_io import io_path, resolve_path, io_glob, io_rglob

import ast
import ctypes
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import zlib



MANIFEST_CONTRACT = "ocd-cvw-serving-implementation-v1"
BACKEND_ROOTS = (
    "cvw_app/launch_windows.py", "cvw_app/session_observability.py",
    "cvw_app/review_service.py", "cvw_app/review_contract.py",
    "cvw_app/review_renderers.py", "cvw_app/serving_identity.py",
)
RUNTIME_DISTRIBUTIONS = ("jsonschema", "attrs", "jsonschema-specifications", "referencing", "rpds-py")
LIBRARY_SCHEMA_MEMBERS = ("schemas/v2/work.schema.json", "schemas/v2/acquisition.schema.json")


class ServingIdentityError(RuntimeError):
    """The declared implementation is missing, ambiguous, or has drifted."""


def digest_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def file_identity(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    length = 0
    with io_path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            length += len(chunk)
            digest.update(chunk)
    return {"byte_length": length, "sha256": digest.hexdigest()}


def local_members(root: Path) -> tuple[str, ...]:
    """Include required roots, future CVW modules, and their local import closure."""
    pending = list(BACKEND_ROOTS)
    pending.extend(path.relative_to(root).as_posix() for path in io_glob(root / "cvw_app", "*.py"))
    found: set[str] = set()
    while pending:
        name = pending.pop()
        if name in found:
            continue
        path = root / name
        if not io_path(path).is_file() or not resolve_path(path).is_relative_to(root):
            raise ServingIdentityError(f"implementation member missing or outside root: {name}; relaunch after repair")
        found.add(name)
        module = name.removesuffix(".py").replace("/", ".")
        package = module.removesuffix(".__init__") if name.endswith("/__init__.py") else module.rpartition(".")[0]
        imports: set[str] = set()
        for node in ast.walk(ast.parse(io_path(path).read_text(encoding="utf-8-sig"), filename=name)):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = importlib.util.resolve_name("." * node.level + (node.module or ""), package) if node.level else (node.module or "")
                imports.add(base)
                for alias in node.names:
                    child = base + "." + alias.name
                    if (io_path(root / (child.replace(".", "/") + ".py"))).is_file() or (io_path(root / child.replace(".", "/") / "__init__.py")).is_file():
                        imports.add(child)
        for imported in imports:
            if imported.split(".")[0] not in {"cvw_app", "ocd_kernel"}:
                continue
            parts = imported.split(".")
            for index in range(1, len(parts) + 1):
                relative = "/".join(parts[:index])
                source = relative + ".py"
                initializer = relative + "/__init__.py"
                # Python prefers a regular package over a same-named module.
                # Seal the initializer that the interpreter will actually load.
                if (io_path(root / initializer)).is_file():
                    pending.append(initializer)
                elif (io_path(root / source)).is_file():
                    pending.append(source)
                elif not (io_path(root / relative)).is_dir():
                    raise ServingIdentityError(f"local import implementation member missing: {imported}")
    # Declared-library validation reads these files beside the imported kernel.
    for name in LIBRARY_SCHEMA_MEMBERS:
        path = root / name
        if not io_path(path).is_file() or not resolve_path(path).is_relative_to(root):
            raise ServingIdentityError(f"implementation resource missing or outside root: {name}; relaunch after repair")
        found.add(name)
    return tuple(sorted(found))


def runtime_identity() -> dict[str, object]:
    versions = {name: importlib.metadata.version(name) for name in RUNTIME_DISTRIBUTIONS}
    runtime: dict[str, object] = {
        "python": platform.python_version(), "implementation": platform.python_implementation(),
        "platform": sys.platform, "machine": platform.machine(),
        "zlib": zlib.ZLIB_RUNTIME_VERSION, "distributions": versions,
    }
    # Image slices can load Pillow before manifest sealing; record its real codec
    # versions rather than pretending a transform label identifies encoder bytes.
    if "PIL" in sys.modules:
        from PIL import features
        versions["Pillow"] = importlib.metadata.version("Pillow")
        runtime["image_codecs"] = {name: features.version(name) for name in features.get_supported()}
    return runtime


def process_started_at_utc(fallback: str) -> tuple[str, str]:
    """Read the supported Windows process creation time, not a later observation."""
    if sys.platform != "win32":
        return fallback, "launcher entry; OS process creation unavailable on this platform"
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(kernel.GetCurrentProcess(), ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)):
        raise ctypes.WinError(ctypes.get_last_error())
    ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
    timestamp = datetime.fromtimestamp((ticks - 116444736000000000) / 10000000, tz=timezone.utc)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"), "OS process creation"


def loaded_origins(root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    concrete: list[dict[str, object]] = []
    namespaces: list[dict[str, object]] = []
    for name, module in sorted(sys.modules.copy().items()):
        if name.split(".")[0] not in {"cvw_app", "ocd_kernel"}:
            continue
        filename = getattr(module, "__file__", None)
        entries = [resolve_path(Path(value)) for value in getattr(module, "__path__", ())]
        if any(not path.is_relative_to(root) for path in entries):
            raise ServingIdentityError(f"loaded namespace outside intended import root: {name}")
        if filename is None:
            if not entries:
                raise ServingIdentityError(f"loaded namespace has no origin: {name}")
            namespaces.append({"package": name, "file": None, "path_entries": [str(path) for path in entries]})
        else:
            path = resolve_path(Path(filename), strict=True)
            if not path.is_relative_to(root):
                raise ServingIdentityError(f"loaded module outside intended import root: {name}")
            concrete.append({"module": name, "resolved_path": str(path), **file_identity(path)})
    for item in namespaces:
        item["concrete_imported_modules"] = [Path(str(row["resolved_path"])).relative_to(root).as_posix() for row in concrete if str(row["module"]).startswith(str(item["package"]) + ".")]
    return concrete, namespaces


class ServingIdentity:
    def __init__(self, root: Path, static_root: Path, *, runtime: Mapping[str, object] | None = None) -> None:
        self.root = resolve_path(root, strict=True)
        self.static_root = resolve_path(static_root, strict=True)
        self.runtime = dict(runtime) if runtime is not None else runtime_identity()
        self._members = local_members(self.root)
        self._membership = self._python_membership()
        self.manifest = self._manifest()
        self.sha256 = digest_json(self.manifest)

    def _python_membership(self) -> tuple[str, ...]:
        # A new module/initializer can alter local import resolution without
        # changing an existing member. Inventory names, but hash only the sealed
        # import closure. Never reparse unchanged source on the request path.
        paths = list(io_rglob(self.root / "cvw_app", "*.py"))
        paths.extend(io_rglob(self.root / "ocd_kernel", "*.py"))
        return tuple(sorted(path.relative_to(self.root).as_posix() for path in paths))

    def _manifest(self) -> dict[str, object]:
        if self._python_membership() != self._membership:
            raise ServingIdentityError("local implementation membership changed; relaunch CVW")
        backend: dict[str, object] = {}
        for name in self._members:
            path = self.root / name
            if not resolve_path(path).is_relative_to(self.root):
                raise ServingIdentityError("implementation member resolves outside root; relaunch CVW")
            backend[name] = file_identity(path)
        frontend_paths = [self.static_root / "review.html"]
        if not (io_path(self.static_root / "assets")).is_dir():
            raise ServingIdentityError("built assets missing; relaunch after repair")
        frontend_paths.extend(path for path in io_rglob(self.static_root / "assets", "*") if io_path(path).is_file())
        frontend: dict[str, object] = {}
        for path in sorted(frontend_paths):
            if not resolve_path(path).is_relative_to(self.static_root):
                raise ServingIdentityError("built asset resolves outside static root")
            frontend[path.relative_to(self.static_root).as_posix()] = file_identity(path)
        return {"contract": MANIFEST_CONTRACT, "backend": backend, "frontend": frontend, "runtime": self.runtime}

    def verify(self) -> None:
        try:
            if self._manifest() != self.manifest:
                raise ServingIdentityError("serving implementation changed; relaunch CVW")
        except OSError as error:
            raise ServingIdentityError("serving implementation unavailable; relaunch CVW") from error

    def verify_static_bytes(self, relative: str, body: bytes) -> None:
        expected = self.manifest["frontend"].get(relative)
        if expected != {"byte_length": len(body), "sha256": hashlib.sha256(body).hexdigest()}:
            raise ServingIdentityError("served asset changed; relaunch CVW")

    def startup_snapshot(self, *, started_at: str, pinned: bool, protected_inputs: Mapping[str, object]) -> dict[str, object]:
        concrete, namespaces = loaded_origins(self.root)
        backend = self.manifest["backend"]
        process_start, process_start_scope = process_started_at_utc(started_at)
        snapshot = {
            "renderer_sha256": backend["cvw_app/review_renderers.py"]["sha256"],
            "renderer_modules_sha256": digest_json({name: value for name,value in backend.items() if name.startswith("cvw_app/") and ("render" in name or "tei_inline" in name or "text_decoding" in name)}),
            "service_sha256": backend["cvw_app/review_service.py"]["sha256"],
            "review_contract_sha256": backend["cvw_app/review_contract.py"]["sha256"],
            "launcher_sha256": backend["cvw_app/launch_windows.py"]["sha256"],
            "built_frontend_asset_hashes": self.manifest["frontend"],
            "executable_identity": {"path": sys.executable, "version": sys.version, **file_identity(Path(sys.executable))},
            "pid": os.getpid(), "process_started_at_utc": process_start,
            "process_start_time_scope": process_start_scope, "launcher_started_at_utc": started_at,
            "protected_input_identities": dict(protected_inputs),
            "implementation_import_closure_sha256": digest_json(backend),
            "implementation_sha256": self.sha256, "implementation_manifest": self.manifest,
            "intended_import_root": str(self.root), "import_root_pinned_before_cvw_import": pinned,
            "import_identity_limitation": None if pinned else "Programmatic import: pre-import root pinning is unproven. Use the protected external entrypoint for at-launch visual provenance.",
            "loaded_module_origin_check": "pass", "loaded_cvw_modules": concrete,
            "namespace_packages": namespaces,
        }
        snapshot["snapshot_sha256"] = digest_json(snapshot)
        return snapshot
