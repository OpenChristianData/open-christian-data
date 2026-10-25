"""Pinned inputs and optional projection reuse from a previous private build.

Reused rows always undergo fresh independent authority verification. No payload
cache or cached checker approval is maintained here.
"""
from __future__ import annotations

import hashlib
import json
import platform
from fnmatch import fnmatchcase
from importlib.metadata import version
from pathlib import Path

from ocd_kernel.library._common import PipelineError, canonical_bytes, io_path, io_glob, inspection_read_phase
from ocd_kernel.lib.storage_topology import resolve_repo_path

CONTRACT = "ocd-release-build-v1"
MANIFEST = "internal/build-manifest.json"
READER = "internal/checks/reader-check.json"
READY = "internal/checks/build-ready.json"


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with io_path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _json(path: Path) -> dict:
    # Read actual bytes, outside the library inspection cache.
    from ocd_kernel.library._common import _reject_duplicate_keys
    value = json.loads(io_path(path).read_bytes(), object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(value, dict):
        raise PipelineError(f"build record is not an object: {path}")
    return value


def _shared_paths(root: Path):
    runtime_root = Path(__file__).resolve().parents[2]
    static = {".py", ".json", ".toml", ".yaml", ".yml", ".csv", ".rng", ".xsd"}
    for folder, suffixes in (("ocd_kernel", static),
                             ("build", static), ("schemas", {".json", ".rng", ".xsd"})):
        for path in sorted((runtime_root / folder).rglob("*")):
            if path.is_file() and path.suffix in suffixes and "__pycache__" not in path.parts:
                yield "runtime", path.relative_to(runtime_root).as_posix(), path
    for folder in ("sources", "metadata"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and path.suffix in {".json", ".py", ".toml", ".yaml", ".yml", ".rng", ".xsd"}:
                yield "library", path.relative_to(root).as_posix(), path
    storage = root / ".ocd-storage.json"
    if storage.exists():
        yield "library", ".ocd-storage.json", storage


def _catalog_inventory(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix()
                  for pattern in ("*/work.json", "*/forms/*/editions/*/acceptance.json")
                  for path in io_glob(root / "library/works", pattern))


def _support_paths(root: Path, work_id: str) -> list[Path]:
    # Validators also consume images and extensionless assets in work authority.
    return sorted(path for path in (root / "library/works" / work_id).rglob("*")
                  if path.is_file() and "__pycache__" not in path.parts)


def _runtime() -> dict:
    return {"python": platform.python_version(), **{name: version(name)
            for name in ("pyarrow", "datasets", "lxml", "jsonschema", "referencing")}}


def capture_inputs(root: Path, selection: dict, profile_path: Path, *, _derivation: dict | None = None,
                   _catalog: list[str] | None = None) -> dict:
    """Pin current inputs; an ephemeral derivation may come from this build's resolver."""
    catalog = _catalog if _catalog is not None else _catalog_inventory(root)
    if _derivation is None:
        from .profile import resolve_publication_profile
        with inspection_read_phase():
            resolved, _derivation = resolve_publication_profile(
                root, profile_path=profile_path, release_id=selection["release_id"])
        if resolved != selection:
            raise PipelineError("publication profile/current library differs from pinned selection")
    derivation = _derivation
    shared = [{"scope": scope, "path": reference, "sha256": _digest(path)}
              for scope, reference, path in _shared_paths(root)]
    # The resolver just hashed actual files in a new read phase; never consume
    # a previous run's derivation receipt as a current input snapshot.
    bindings = derivation["item_bindings"]
    work_bindings = derivation["work_bindings"]
    known = {entry["path"]: entry["sha256"] for group in bindings + work_bindings for entry in group["files"]}
    # Current validators can use versioned integration supplements directly,
    # without a path from the historical acceptance. Bind those static records.
    support = {}
    for selected in selection["items"]:
        if "exclude_reason" in selected:
            continue
        work_id = selected["work_id"]
        if work_id not in support:
            support[work_id] = []
            for path in _support_paths(root, work_id):
                reference = path.relative_to(root).as_posix()
                digest = known[reference] if reference in known else _digest(path)
                support[work_id].append({"path": reference, "sha256": digest})
    if _catalog_inventory(root) != catalog:
        raise PipelineError("release inputs changed during profile resolution: catalog inventory")
    return {"profile": derivation["profile"], "inventory": derivation["inventory"],
            "pending_private": derivation.get("pending_private", []),
            "shared": shared, "item_bindings": bindings, "work_bindings": work_bindings,
            "support": support, "catalog_files": catalog, "runtime": _runtime()}


def check_inputs(root: Path, selection: dict, inputs: dict) -> None:
    """Rehash unique pinned bytes and inventories without reparsing rights proofs."""
    item_ids = [item["item_id"] for item in selection["items"]]
    bindings = inputs["item_bindings"]
    work_ids = [work["work_id"] for work in inputs["inventory"]]
    catalog_works = sorted(Path(path).parts[2] for path in inputs["catalog_files"] if path.endswith("/work.json"))
    selected_works = {item["work_id"] for item in selection["items"] if "exclude_reason" not in item}
    if (sorted(entry["item_id"] for entry in bindings) != sorted(item_ids)
            or sorted(entry["work_id"] for entry in inputs["work_bindings"]) != sorted(work_ids)
            or sorted(work_ids) != catalog_works or set(inputs["support"]) != selected_works):
        raise PipelineError("incomplete pinned input bindings for selected items/work inventory")
    for work in inputs["work_bindings"]:
        prefix = f"library/works/{work['work_id']}/"
        if not {prefix + "work.json", prefix + "state.json"} <= {entry["path"] for entry in work["files"]}:
            raise PipelineError(f"incomplete pinned work authority: {work['work_id']}")
    by_item = {entry["item_id"]: entry for entry in bindings}
    for item in selection["items"]:
        acceptance = item["acceptance_path"]
        core = {acceptance, str(Path(acceptance).with_name("master.tei.xml")).replace("\\", "/"),
                f"library/works/{item['work_id']}/work.json", f"library/works/{item['work_id']}/state.json"}
        if not core <= {entry["path"] for entry in by_item[item["item_id"]]["files"]}:
            raise PipelineError(f"incomplete pinned item authority: {item['item_id']}")
    runtime_root = Path(__file__).resolve().parents[2]
    shared = list(_shared_paths(root))
    if ([(scope, reference) for scope, reference, _ in shared] !=
            [(entry["scope"], entry["path"]) for entry in inputs["shared"]]):
        raise PipelineError("release inputs changed during build: shared file inventory")
    if _catalog_inventory(root) != inputs["catalog_files"] or _runtime() != inputs["runtime"]:
        raise PipelineError("release inputs changed during build: catalog inventory/runtime")
    for work_id, records in inputs["support"].items():
        if [path.relative_to(root).as_posix() for path in _support_paths(root, work_id)] != [entry["path"] for entry in records]:
            raise PipelineError(f"release inputs changed during build: {work_id} file inventory")
    expected = {}
    records = [inputs["profile"]] + [entry for group in inputs["item_bindings"] + inputs["work_bindings"] for entry in group["files"]]
    records += [entry for group in inputs["support"].values() for entry in group]
    scoped = [("library", entry) for entry in records] + [(entry["scope"], entry) for entry in inputs["shared"]]
    for scope, entry in scoped:
        key = (scope, entry["path"])
        if key in expected and expected[key] != entry["sha256"]:
            raise PipelineError(f"inconsistent pinned input: {key}")
        expected[key] = entry["sha256"]
    for (scope, reference), digest in expected.items():
        path = runtime_root / reference if scope == "runtime" else resolve_repo_path(root, reference)
        if _digest(path) != digest:
            raise PipelineError(f"release inputs changed during build: {reference}")
    for group in inputs["item_bindings"]:
        for discovery in group.get("discovery", []):
            path = resolve_repo_path(root, discovery["path"])
            try:
                members = sorted(member.name for member in io_path(path).iterdir()
                                 if fnmatchcase(member.name, discovery["pattern"]))
            except FileNotFoundError:
                members = []
            if discovery["health"] != "valid" or members != discovery["members"]:
                raise PipelineError(f"release inputs changed during build: {discovery['path']} membership")


def item_fingerprint(inputs: dict, selected: dict) -> str:
    binding = next((item for item in inputs["item_bindings"]
                    if item["item_id"] == selected["item_id"]), None)
    if binding is None:
        raise PipelineError(f"missing pinned item inputs: {selected['item_id']}")
    decision = {key: value for key, value in selected.items() if key != "exclude_reason"}
    return hashlib.sha256(canonical_bytes({"binding": binding, "selection": decision,
        "support": inputs["support"].get(selected.get("work_id"), [])})).hexdigest()


def check_ranges(directory: Path, report: dict, manifest: dict) -> None:
    """Validate contiguous actual byte ranges, including private receipt files."""
    if manifest.get("contract") != CONTRACT:
        raise PipelineError("unsupported build manifest")
    if manifest.get("selection_sha256") != report["selection_sha256"]:
        raise PipelineError("build manifest selection differs")
    from .public_allowlist import _configurations, public_files

    categories = {config["category"] for config in _configurations(report["configurations"])}
    expected = [item for item in report["items"] if item["status"] in {"included", "warned"}]
    ranges = manifest["items"]
    if [item["item_id"] for item in ranges] != [item["item_id"] for item in expected]:
        raise PipelineError("build ranges differ from included items")
    offsets: dict[str, int] = {}
    for item, saved in zip(expected, ranges, strict=True):
        category = item["category"]
        if category not in categories:
            raise PipelineError("build item has unsafe or undeclared category")
        path = directory / f"public/data/{category}/train.jsonl"
        if item["receipt_path"] != f"internal/projection-receipts/{item['item_id']}.json":
            raise PipelineError("unsafe build item receipt path")
        begin, end = saved["begin"], saved["end"]
        if (type(begin) is not int or type(end) is not int or begin != offsets.get(category, 0)
                or end <= begin or saved["row_count"] != item["row_count"]):
            raise PipelineError(f"invalid build item range: {item['item_id']}")
        digest = hashlib.sha256()
        lines = 0
        with path.open("rb") as stream:
            stream.seek(begin)
            remaining = end - begin
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise PipelineError("truncated build item range")
                digest.update(chunk)
                lines += chunk.count(b"\n")
                remaining -= len(chunk)
        if digest.hexdigest() != saved["sha256"] or lines != item["row_count"]:
            raise PipelineError(f"build item range digest/count differs: {item['item_id']}")
        if _digest(directory / item["receipt_path"]) != saved["receipt_sha256"]:
            raise PipelineError("build item receipt differs")
        transform = directory / f"internal/public-row-transforms/{item['item_id']}.json"
        if saved.get("transform_sha256") != (_digest(transform) if transform.exists() else None):
            raise PipelineError("build item transform differs")
        offsets[category] = end
    for config in report["configurations"]:
        if offsets.get(config["category"], 0) != (directory / config["path"]).stat().st_size:
            raise PipelineError("build ranges do not account for category bytes")


def check_ready(directory: Path) -> None:
    from .public_allowlist import _configurations, public_files

    actual_files = public_files(directory)
    ready = _json(directory / READY)
    if ready.get("contract") != CONTRACT or ready.get("status") != "pass":
        raise PipelineError("candidate is not ready")
    report = _json(directory / "internal/release-report.json")
    independent = _json(directory / "internal/checks/independent-check.json")
    if report.get("status") != "pass" or report.get("accounting", {}).get("failed") != 0:
        raise PipelineError("ready evidence contains failed items")
    if independent != {"status": "pass", "errors": []}:
        raise PipelineError("candidate independent check did not pass")
    configurations = _configurations(report["configurations"])
    required = {MANIFEST, READER, "internal/release-report.json", "internal/release-selection.json",
                "internal/checks/independent-check.json", "public/README.md"}
    required.update(config["path"] for config in configurations)
    required.update(config["typed_companion"]["path"] for config in configurations if "typed_companion" in config)
    expected = actual_files - {READY}
    if not required <= expected:
        raise PipelineError("ready evidence is missing required files")
    if set(ready.get("files", {})) != expected:
        raise PipelineError("ready evidence file inventory differs")
    for path in expected:
        if ready.get("files", {}).get(path) != _digest(directory / path):
            raise PipelineError(f"ready evidence changed: {path}")
    proof = _json(directory / READER)
    if proof.get("status") not in {"pass", "reader-only-pass"}:
        raise PipelineError("candidate reader check did not pass")
    if proof.get("release_report_sha256") != _digest(directory / "internal/release-report.json"):
        raise PipelineError("candidate reader check refers to different report")
    expected_readers = [{"category": config["category"], "rows": config["row_count"],
                         "normal_and_streaming": "pass", "all_original_values_and_order_preserved": True}
                        for config in configurations]
    if proof.get("configurations") != expected_readers:
        raise PipelineError("candidate reader inventory/counts differ")


class PreviousCandidate:
    """Read a prior ready candidate without copying or changing its payloads."""
    def __init__(self, directory: Path, inputs: dict):
        from .public_allowlist import public_files, _configurations
        from .verify import _schema_diagnostics
        from .selection import validate_release_selection

        self.directory = Path(directory)
        public_files(self.directory)  # Reject all private/public links before reading.
        check_ready(self.directory)
        self.manifest = _json(self.directory / MANIFEST)
        self.report = _json(self.directory / "internal/release-report.json")
        shape = _schema_diagnostics(self.report, schema_name="release-report.schema.json", label="previous release report")
        if shape:
            raise PipelineError("invalid previous release report: " + "; ".join(shape))
        selection = validate_release_selection(_json(self.directory / "internal/release-selection.json"))
        if (self.report["selection_sha256"] != hashlib.sha256(canonical_bytes(selection)).hexdigest()
                or [item["item_id"] for item in self.report["items"]] != [item["item_id"] for item in selection["items"]]):
            raise PipelineError("previous report differs from its selection")
        _configurations(self.report["configurations"])
        check_ranges(self.directory, self.report, self.manifest)
        prior_inputs = self.manifest["inputs"]
        self.compatible = (prior_inputs["shared"] == inputs["shared"]
                           and prior_inputs["runtime"] == inputs["runtime"])
        self.items = {item["item_id"]: item for item in self.manifest["items"]}

    def read_item(self, selected: dict, inputs: dict):
        from .streaming import MAX_JSONL_ROW_BYTES

        saved = self.items.get(selected["item_id"])
        if (not self.compatible or saved is None
                or saved["input_fingerprint"] != item_fingerprint(inputs, selected)):
            return None
        rows = []
        path = self.directory / f"public/data/{selected['category']}/train.jsonl"
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            stream.seek(saved["begin"])
            while stream.tell() < saved["end"]:
                line = stream.readline(min(saved["end"] - stream.tell(), MAX_JSONL_ROW_BYTES + 1))
                if len(line) > MAX_JSONL_ROW_BYTES:
                    raise PipelineError("previous candidate row exceeds bounded row limit")
                digest.update(line)
                row = json.loads(line)
                if canonical_bytes(row) != line:
                    raise PipelineError("previous candidate range is not canonical")
                rows.append(row)
        if digest.hexdigest() != saved["sha256"] or len(rows) != saved["row_count"]:
            raise PipelineError("previous candidate item changed during reuse")
        receipt_path = self.directory / f"internal/projection-receipts/{selected['item_id']}.json"
        transform_path = self.directory / f"internal/public-row-transforms/{selected['item_id']}.json"
        if _digest(receipt_path) != saved["receipt_sha256"]:
            raise PipelineError("previous receipt changed during reuse")
        receipt = _json(receipt_path)
        transform = _json(transform_path) if transform_path.exists() else None
        if saved.get("transform_sha256") != (_digest(transform_path) if transform_path.exists() else None):
            raise PipelineError("previous transform changed during reuse")
        return rows, receipt, transform
