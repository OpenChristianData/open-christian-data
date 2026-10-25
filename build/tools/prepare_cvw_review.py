"""Prepare an unchanged, validated review copy of one installed accepted edition.

This does not reconstruct, accept, or publish text. The normal candidate runner
seals the copy; its oracle rechecks the existing acceptance and exact master bytes.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

from cvw_app.library_admission import _acquisition_primary_members
from ocd_kernel.lib.path_io import io_path
from ocd_kernel.reconstruction.contract import SourceManifest, _validation_authority_bindings
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.acceptance import validate_acceptance


IMPLEMENTATION = "build/tools/prepare_cvw_review.py"
IDENTITY = "ocd-accepted-master-review-copy"


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _binding(root: Path, relative: str, name: str, role: str) -> dict:
    # Resolve retained junctions through the same boundary as source manifests.
    from ocd_kernel.reconstruction.contract import _contained
    path = _contained(root, relative, name)
    payload = io_path(path).read_bytes()
    return dict(name=name, role=role, path=relative, bytes=len(payload), sha256=_sha(payload))


def _source_authorities(root: Path, acquisition: dict) -> list[dict]:
    selected = _acquisition_primary_members(acquisition)
    members = [item for item in acquisition["retained_files"] if (item["path"], item["bytes"], item["sha256"]) in selected]
    authorities = [_binding(root, item["path"], f"{index:02d} {Path(item['path']).name}", "primary-source")
                   for index, item in enumerate(members, 1)]
    if acquisition.get("source_kind") == "retained-member-set":
        authorities.append(_binding(root, acquisition["source_path"], "member-set", "retained-member-set"))
    return authorities


def _closure(root: Path) -> list[dict]:
    """Seal the local static import closure, including acceptance's lazy branches."""
    pending = [IMPLEMENTATION]
    found = set()
    while pending:
        name = pending.pop()
        if name in found:
            continue
        found.add(name)
        module = name.removesuffix(".py").replace("/", ".")
        package = module.removesuffix(".__init__") if name.endswith("/__init__.py") else module.rpartition(".")[0]
        imports = set()
        for node in ast.walk(ast.parse(io_path(root / name).read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = importlib.util.resolve_name("." * node.level + (node.module or ""), package) if node.level else (node.module or "")
                imports.add(base)
                imports.update(base + "." + alias.name for alias in node.names)
        for imported in imports:
            if imported.split(".")[0] not in {"ocd_kernel", "cvw_app", "build"}:
                continue
            parts = imported.split(".")
            for length in range(1, len(parts) + 1):
                relative = "/".join(parts[:length])
                for candidate in (relative + "/__init__.py", relative + ".py"):
                    if io_path(root / candidate).is_file():
                        pending.append(candidate)
                        break
    found.update(path.relative_to(root).as_posix() for path in (root / "schemas/v2").glob("*.json"))
    found.update(path.relative_to(root).as_posix() for path in (root / "ocd_kernel/schemas/v2").glob("*.json"))
    return [{"path": name, "sha256": _sha(io_path(root / name).read_bytes())} for name in sorted(found)]


def _convert(manifest: SourceManifest) -> dict[str, bytes]:
    manifest.verify()
    return {
        "content.tei.xml": io_path(manifest.authority_path("accepted-master")).read_bytes(),
        "README.source.md": (
            "# Review copy of an installed edition\n\n"
            "The TEI is byte-for-byte identical to the bound accepted master. "
            "The existing acceptance proof is revalidated; no new source-fidelity, "
            "acceptance, rights, or publication decision is made.\n"
        ).encode(),
        "provenance.json": _json({"contract": "ocd-accepted-master-review-copy-v1", "source_manifest_sha256": manifest.sha256,
            "acceptance": next(dict(item) for item in manifest.record["authorities"] if item["name"] == "acceptance-record")}),
        "source-accountability.json": _json({"scope": "Exact copy of the installed accepted master; existing source accounting remains authoritative.",
            "sources": [dict(item) for item in manifest.record["authorities"] if item["role"] == "primary-source"]}),
        "unresolved.jsonl": _json({"scope": "Existing acceptance limitations and rights decisions remain unchanged; see the bound acceptance record."}),
    }


_convert.converter_id = IDENTITY
_convert.converter_version = "1"


def _oracle(manifest: SourceManifest, candidate) -> dict:
    manifest.verify()
    root = manifest.repository_root
    closure = _sha(_json(_closure(root)))
    if closure != manifest.record["validator"]["import_closure_sha256"]:
        raise ValueError("accepted-master review validator import closure drifted")
    record = validate_acceptance(manifest.authority_path("acceptance-record"), root=root)
    if record["promotion"]["status"] != "promoted" or record["identity"]["work_id"] != manifest.record["work_id"]:
        raise ValueError("review copy must bind the installed promoted edition")
    acquisition_binding = next(item for item in manifest.record["authorities"] if item["name"] == "acquisition")
    if any(record["source"]["source_manifest"][key] != acquisition_binding[key] for key in ("path", "bytes", "sha256")):
        raise ValueError("review copy acquisition differs from the accepted edition")
    acquisition = json.loads(io_path(manifest.authority_path("acquisition")).read_bytes())
    actual_sources = [dict(item) for item in manifest.record["authorities"] if item["role"] in {"primary-source", "retained-member-set"}]
    if actual_sources != _source_authorities(root, acquisition):
        raise ValueError("review copy source members differ from the accepted acquisition")
    master = record["promotion"]["master"]
    authority = next(item for item in manifest.record["authorities"] if item["name"] == "accepted-master")
    if any(master[key] != authority[key] for key in ("path", "bytes", "sha256")):
        raise ValueError("review copy master differs from the accepted promotion")
    if candidate.member_bytes("content.tei.xml") != io_path(manifest.authority_path("accepted-master")).read_bytes():
        raise ValueError("review copy differs from the accepted master bytes")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(io_path(root / IMPLEMENTATION).read_bytes()),
        validator_import_closure_sha256=closure,
        **_validation_authority_bindings(manifest), findings=(),
    )
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


_oracle.oracle_id = IDENTITY
_oracle.oracle_version = "1"


def prepare(*, root: Path, acceptance: str, manifest_directory: str, destination: str) -> dict:
    root = root.resolve(strict=True)
    from ocd_kernel.reconstruction.contract import _contained
    record = validate_acceptance(_contained(root, acceptance, "acceptance"), root=root)
    identity = record["identity"]
    if record["promotion"]["status"] != "promoted":
        raise ValueError("review requires an installed promoted master")
    directory = Path(manifest_directory)
    # Session inputs must not overwrite source authority or accepted evidence.
    if directory.is_absolute() or ".." in directory.parts or directory.parts[:1] != (".tmp_audit",):
        raise ValueError("manifest directory must be a new repository-relative .tmp_audit child")
    parent = (root / directory.parent).resolve(strict=True)
    if not parent.is_relative_to(root / ".tmp_audit"):
        raise ValueError("manifest directory resolves outside task scratch")
    target = parent / directory.name
    target.mkdir(exist_ok=False)
    work = f"library/works/{identity['work_id']}/work.json"
    acquired = record["source"]["source_manifest"]["path"]
    acquisition = json.loads(io_path(_contained(root, acquired, "acquisition")).read_bytes())
    authorities = _source_authorities(root, acquisition)
    profile = directory.as_posix() + "/profile.json"
    (target / "profile.json").write_bytes(_json({"identity": identity, "scope": record["scope"], "operation": "unchanged accepted-master review copy"}))
    policy = directory.as_posix() + "/policy.json"
    closure = _closure(root)
    (target / "policy.json").write_bytes(_json({"contract": "ocd-accepted-master-review-policy-v1", "checks": ["current acceptance passes", "exact promoted master bytes", "exact acquired source membership"], "validator_closure": closure}))
    schema = "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
    for path, name, role in (
        (work, "work", "work-identity-config"), (acquired, "acquisition", "acquisition-selection-authority"),
        (acceptance, "acceptance-record", "existing-acceptance-proof"),
        (record["promotion"]["master"]["path"], "accepted-master", "accepted-master"),
        (profile, "profile", "complete-source-feature-profile"), (policy, "policy", "independent-validation-policy"),
        (schema, "package-schema", "candidate-package-schema"),
        ("ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-schema", "tei-validation-schema"),
    ):
        authorities.append(_binding(root, path, name, role))
    implementation_sha = _sha(io_path(root / IMPLEMENTATION).read_bytes())
    binding = dict(id=IDENTITY, version="1", implementation_path=IMPLEMENTATION, implementation_sha256=implementation_sha)
    manifest = dict(contract="ocd-source-manifest-v1", work_id=identity["work_id"], source_id=identity["work_id"] + "-installed-review-copy",
        authorities=authorities, converter=dict(binding, callable="_convert"),
        validator=dict(binding, callable="_oracle", import_closure_sha256=_sha(_json(closure))),
        package_schema=dict(path=schema, sha256=_sha(io_path(root / schema).read_bytes())))
    manifest_path = directory.as_posix() + "/source-manifest.json"
    (target / "source-manifest.json").write_bytes(_json(manifest))
    from build.tools.reconstruct_candidate import run
    return run(manifest=manifest_path, destination=destination, repository_root=str(root))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--acceptance", required=True)
    parser.add_argument("--manifest-directory", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(root=args.repository_root, acceptance=args.acceptance, manifest_directory=args.manifest_directory, destination=args.destination), indent=2))


if __name__ == "__main__":
    main()
