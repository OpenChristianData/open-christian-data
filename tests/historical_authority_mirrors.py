"""Exact retained authorities for four historical reconstruction test owners.

Only pytest mirrors are written. Raw witnesses continue to use the repository's
configured library. Unexpected source/code drift is rejected, never repinned.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

from ocd_kernel.lib.storage_topology import resolve_repo_path
from tests.vendored_schema_mirrors import copy_vendored_schema_imports


CASES = {
    "moody-v2": {
        "manifest": "sources/manifest-acquisitions/moody-prevailing-prayer-pg61883-v2/source-manifest.json",
        "sha256": "e19272848a7ea966abe9126f396de2d76416e90877663e40762163b7d4e01645",
        "eol_supports": ("sources/manifest-acquisitions/moody-prevailing-prayer-pg61883-v2/profile.json",
                         "sources/manifest-acquisitions/moody-prevailing-prayer-pg61883-v2/policy.json"),
        "closure_paths": ("ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/__init__.py"),
    },
    "apostolic": {
        "manifest": "sources/apostolic-tradition/apostolic-tradition.source-manifest.json",
        "sha256": "2d4f58910dc1152bedabbca6a17d19044f0806636c30bdcf488920ac23e98576",
        "eol_supports": (),
        "closure_paths": (),
    },
    "davis": {
        "manifest": "sources/structured-text/davis-beginners-grammar-1923/source-manifest.json",
        "sha256": "7014fe2ce260f5070b0cf7508eb778864a11417e1d0a12b76ac6fd1bdac55559",
        "eol_supports": ("sources/structured-text/davis-beginners-grammar-1923/reconstruction-profile.json",
                         "sources/structured-text/davis-beginners-grammar-1923/validation-policy.json",
                         "build/tei/davis_l332_ia_oracle.py"),
        "closure_paths": ("ocd_kernel/lib/storage_topology.py", "ocd_kernel/reconstruction/contract.py",
                          "ocd_kernel/reconstruction/verifier.py"),
    },
    "methodius": {
        "manifest": "sources/manifest-acquisitions/methodius-symposium-first1kgreek/source-manifest.json",
        "sha256": "05667a3ff4984dbb4d36d2b3ea51f8116a1278e4477ece427e62d00d8e86c75c",
        "eol_supports": ("sources/manifest-acquisitions/methodius-symposium-first1kgreek/README.source.md",),
        "closure_paths": (),
    },
}
DAVIS_VALIDATOR_SHA = "19e88135eb291d98e1b466dacd178eaab04e5ceb68f4328aa3c97b90cb4079f7"
DAVIS_CLOSURE_SHA = "c45218d8e2442fbd5662d23bfcd0eaebcde2486779b18e4d7489901a12bf8c24"


def _canonical(record: object) -> bytes:
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def retained_preimage(raw: bytes, digest: str, size: int | None, *, allow_eol: bool) -> bytes:
    candidates = [raw]
    if allow_eol:
        lf = raw.replace(b"\r\n", b"\n")
        candidates.extend((lf, lf.replace(b"\n", b"\r\n")))
    for candidate in candidates:
        if sha256(candidate).hexdigest() == digest and (size is None or len(candidate) == size):
            return candidate
    raise ValueError("Retained authority differs from its complete original SHA and byte count")


def prepare_historical_mirror(repository_root: Path, destination: Path, key: str) -> tuple[Path, Path]:
    case = CASES[key]
    original_path = repository_root / case["manifest"]
    original = original_path.read_bytes()
    assert sha256(original).hexdigest() == case["sha256"]
    record = json.loads(original)
    runtime = deepcopy(record)
    if key == "davis":
        runtime["validator"].update(implementation_sha256=DAVIS_VALIDATOR_SHA,
                                    import_closure_sha256=DAVIS_CLOSURE_SHA)
    destination.mkdir(parents=True, exist_ok=False)
    # Only raw/reports/exports use this library; all mirrored metadata stays local.
    library = resolve_repo_path(repository_root, "raw").parent
    (destination / ".ocd-storage.json").write_bytes(_canonical({"library_root": str(library)}))
    bindings = list(runtime["authorities"])
    bindings.extend({"path": runtime[role]["implementation_path"],
                     "sha256": runtime[role]["implementation_sha256"]}
                    for role in ("converter", "validator"))
    bindings.append(runtime["package_schema"])
    written: dict[str, bytes] = {}
    for binding in bindings:
        relative = binding["path"]
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Historical authority path must stay repository-relative")
        if path.parts[0] in {"raw", "reports", "exports"}:
            continue  # SourceManifest.verify checks the actual read-only configured witness.
        raw = (repository_root / path).read_bytes()
        if key == "apostolic" and relative == "library/works/apostolic-tradition/work.json":
            raw = (repository_root / "tests/fixtures/historical-authority-mirrors/apostolic-tradition.work.json").read_bytes()
        content = retained_preimage(raw, binding["sha256"], binding.get("bytes"),
                                    allow_eol=relative in case["eol_supports"])
        if relative in written and written[relative] != content:
            raise ValueError("Historical bindings disagree on authority bytes")
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        written[relative] = content
    for relative in case["closure_paths"]:
        content = (repository_root / relative).read_bytes()
        if relative in written:
            assert written[relative] == content
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    copy_vendored_schema_imports(repository_root, destination)
    manifest_path = destination / case["manifest"]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(original if key != "davis" else _canonical(runtime))
    assert original_path.read_bytes() == original
    assert record == json.loads(original_path.read_bytes())
    if key != "davis":
        assert manifest_path.read_bytes() == original
    else:
        expected = deepcopy(record)
        expected["validator"].update(implementation_sha256=DAVIS_VALIDATOR_SHA,
                                     import_closure_sha256=DAVIS_CLOSURE_SHA)
        assert json.loads(manifest_path.read_bytes()) == expected
        (manifest_path.parent / "original-source-manifest.json").write_bytes(original)
        paths = (runtime["validator"]["implementation_path"],) + case["closure_paths"]
        closure = _canonical([{"path": p, "sha256": sha256((destination / p).read_bytes()).hexdigest()}
                              for p in paths])
        assert sha256(closure).hexdigest() == DAVIS_CLOSURE_SHA
    return destination, manifest_path


def bound_callable(root: Path, binding: object, role: str):
    path = root / binding["implementation_path"]
    digest = sha256(path.read_bytes()).hexdigest()
    assert digest == binding["implementation_sha256"]
    name = "_ocd_historical_test_" + role + "_" + digest
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    assert Path(module.__file__).samefile(path)
    return getattr(module, binding["callable"])
