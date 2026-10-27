from __future__ import annotations

import argparse
import configparser
import hashlib
import html
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ocd_kernel.lib.storage_topology import (
    StorageTopologyError,
    repository_relative_path,
    resolve_repo_path,
    storage_read_phase,
)
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.lib.path_io import io_path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
DEFAULT_JSON_OUT = REPO_ROOT / "reports" / "publish" / "work_catalog.json"
DEFAULT_MD_OUT = REPO_ROOT / "reports" / "publish" / "work_catalog.md"
DEFAULT_HTML_OUT = REPO_ROOT / "reports" / "publish" / "work_catalog.html"
NSH_REFERENCE_PREFIX = ("reference", "schaff", "encyclopedia", "1908-1914")
OFFICIAL_TITLE_REVIEW_RESOURCE_IDS = {
    "calvin",
    "matthew-henry-complete",
}

CATEGORY_LABELS = {
    "bible-text": "Bible Translations",
    "catechisms": "Catechisms",
    "church-fathers": "Church Fathers",
    "commentaries": "Commentaries",
    "devotionals": "Devotionals",
    "doctrinal-documents": "Doctrinal Documents",
    "hymns": "Hymns",
    "prayers": "Prayers",
    "reference": "Dictionaries and Encyclopedias",
    "sermons": "Sermons",
    "structured-text": "Books and Long-Form Works",
    "topical-reference": "Topical Bibles and Indexes",
}

METADATA_LABELS = {
    "id": "Resource ID",
    "title": "Title",
    "author": "Author",
    "contributors": "Contributors",
    "language": "Language",
    "tradition": "Tradition",
    "tradition_notes": "Tradition notes",
    "license": "Licence",
    "schema_type": "Schema type",
    "schema_version": "Schema version",
    "completeness": "Completeness",
    "original_publication_year": "Original publication year",
    "publication_year": "Publication year",
    "publication_date": "Publication date",
    "copyright_year": "Copyright year",
    "provenance.source_url": "Source URL",
    "provenance.source_format": "Source format",
    "provenance.source_edition": "Source edition",
    "provenance.download_date": "Download date",
    "provenance.source_hash": "Source hash",
    "provenance.processing_method": "Processing method",
    "provenance.processing_script_version": "Processing script version",
    "provenance.processing_date": "Processing date",
    "provenance.notes": "Provenance notes",
}

METADATA_FIELD_ORDER = [
    "id",
    "title",
    "author",
    "contributors",
    "language",
    "tradition",
    "original_publication_year",
    "publication_year",
    "publication_date",
    "copyright_year",
    "license",
    "completeness",
    "provenance.source_edition",
    "provenance.source_url",
    "provenance.source_format",
    "provenance.download_date",
    "provenance.processing_date",
    "provenance.processing_method",
    "provenance.processing_script_version",
    "provenance.notes",
    "schema_type",
    "schema_version",
    "provenance.source_hash",
]

PUBLICATION_META_FIELDS = (
    "publication_date",
    "publication_year",
    "published",
    "published_year",
    "original_publication_year",
    "copyright_year",
)

PUBLICATION_PROVENANCE_FIELDS = (
    "publication_date",
    "publication_year",
    "source_publication_date",
    "source_publication_year",
)


def _default_reconstruction_state() -> dict[str, Any]:
    return {
        "retained_source": "not_assessed",
        "tei_candidate": "not_started",
        "validation": "not_run",
        "human_review": "not_started",
        "accepted_ir": "not_accepted",
        "blocker": None,
        "publication": "not_ready",
        "routes": [],
    }


RECONSTRUCTION_STATE_FIELDS = (
    "retained_source",
    "tei_candidate",
    "validation",
    "human_review",
    "accepted_ir",
    "publication",
)
PARTIAL_COVERAGE_BLOCKER = (
    "partial source coverage cannot establish whole-work accepted IR"
)


def _ensure_reconstruction_state(state: dict[str, Any]) -> None:
    """Keep the state shape stable for callers that construct test works."""

    state.setdefault("accepted_ir", "not_accepted")
    state.setdefault("blocker", None)
    state.setdefault("routes", [])


def _reconstruction_state_counts(
    works: Iterable[Mapping[str, Any]],
    unassociated_manifests: Mapping[str, int],
) -> dict[str, Any]:
    works = list(works)
    for work in works:
        _ensure_reconstruction_state(work["reconstruction_state"])
    counts: dict[str, Any] = {
        field: dict(
            sorted(
                Counter(work["reconstruction_state"][field] for work in works).items()
            )
        )
        for field in RECONSTRUCTION_STATE_FIELDS
    }
    counts["routes"] = sum(
        len(work["reconstruction_state"]["routes"]) for work in works
    )
    counts["route_verification"] = dict(
        sorted(
            Counter(
                route["verification"]
                for work in works
                for route in work["reconstruction_state"]["routes"]
            ).items()
        )
    )
    manifest_verification = {
        route["manifest"]: route.get("manifest_verification", route["verification"])
        for work in works
        for route in work["reconstruction_state"]["routes"]
    }
    counts["manifest_verification"] = dict(
        sorted(Counter(manifest_verification.values()).items())
    )
    counts["blockers"] = dict(
        sorted(
            Counter(
                state["blocker"]
                for work in works
                for state in (work["reconstruction_state"],)
                if state.get("blocker")
            ).items()
        )
    )
    counts["partial_routes"] = sum(
        route["scope"] == "partial"
        for work in works
        for route in work["reconstruction_state"]["routes"]
    )
    counts["unassociated_manifests"] = dict(sorted(unassociated_manifests.items()))
    return counts


def _reconstruction_state_text(work: Mapping[str, Any]) -> str:
    state = work["reconstruction_state"]
    parts = [
        f"{field.replace('_', ' ')}: {str(state.get(field)).replace('_', ' ')}"
        for field in RECONSTRUCTION_STATE_FIELDS
    ]
    if state.get("blocker"):
        parts.append(f"blocker: {state['blocker']}")
    blocker_details = state.get("blocker_details")
    if isinstance(blocker_details, Mapping):
        parts.extend(
            (
                f"blocker owner: {blocker_details['owner']}",
                f"next action: {blocker_details['next_action']}",
                f"reopening condition: {blocker_details['reopening_condition']}",
            )
        )
    routes = state["routes"]
    route_text = ", ".join(
        (
            f"{route['source_id']} ({route['scope']}, {route['verification']})"
            + (f": {route['blocker']}" if route.get("blocker") else "")
        )
        for route in routes
    )
    parts.append(f"routes: {route_text or 'none'}")
    return "; ".join(parts)


def _normal_sha256(value: Any) -> str | None:
    text = _clean_str(value)
    if text is None:
        return None
    if text.casefold().startswith("sha256:"):
        text = text.split(":", 1)[1]
    return text.casefold()


def _manifest_primary_hashes(manifest: Mapping[str, Any]) -> set[str]:
    hashes: set[str] = set()
    for authority in manifest.get("authorities") or []:
        if (
            not isinstance(authority, Mapping)
            or authority.get("role") != "primary-source"
        ):
            continue
        digest = _normal_sha256(authority.get("sha256"))
        if digest is not None and _is_exact_sha256(digest):
            hashes.add(digest)
    return hashes


def _manifest_source_hashes(manifest: Mapping[str, Any]) -> set[str]:
    """Return individual and deterministic multi-member source bindings."""

    primary_members = [
        authority
        for authority in manifest.get("authorities") or []
        if isinstance(authority, Mapping) and authority.get("role") == "primary-source"
    ]
    hashes = _manifest_primary_hashes(manifest)
    if len(primary_members) <= 1:
        return hashes
    records = sorted(
        (
            {
                "name": authority.get("name"),
                "path": authority.get("path"),
                "bytes": authority.get("bytes"),
                "sha256": authority.get("sha256"),
            }
            for authority in primary_members
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    if any(
        not _is_exact_sha256(record["sha256"])
        or not isinstance(record["name"], str)
        or not isinstance(record["path"], str)
        or not isinstance(record["bytes"], int)
        for record in records
    ):
        return hashes
    canonical = (
        json.dumps(
            {"contract": "ocd-source-member-set-v1", "members": records},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    hashes.add(hashlib.sha256(canonical).hexdigest())
    return hashes


def _work_source_hashes(work: Mapping[str, Any]) -> set[str]:
    values = work.get("metadata_fields", {}).get("provenance.source_hash", [])
    return {
        digest
        for value in values
        if (digest := _normal_sha256(value)) is not None and _is_exact_sha256(digest)
    }


def _is_exact_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and bool(re.fullmatch(r"[0-9a-f]{64}", value.casefold()))
    )


def _append_audit_flag(work: dict[str, Any], flag: str) -> None:
    flags = set(work.get("audit_flags", []))
    flags.add(flag)
    work["audit_flags"] = sorted(flags)


def _normalized_remote(value: object) -> str | None:
    text = _clean_str(value)
    if text is None:
        return None
    normalized = text.strip().replace("\\", "/").rstrip("/")
    if normalized.casefold().endswith(".git"):
        normalized = normalized[:-4]
    return normalized.casefold()


def _resolved_retained_path(
    repository_root: Path, logical_path: str, label: str
) -> Path:
    try:
        return resolve_repo_path(repository_root, logical_path)
    except (IndexError, StorageTopologyError) as exc:
        raise ValueError(
            f"{label} is not a normalized repository path: {logical_path}"
        ) from exc


def _logical_retained_path(repository_root: Path, path: Path, label: str) -> str:
    try:
        return repository_relative_path(repository_root, path)
    except StorageTopologyError as exc:
        raise ValueError(
            f"{label} is outside configured repository storage: {path}"
        ) from exc


def _retained_files(path: Path) -> list[Path]:
    if path.is_symlink():
        return []
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    return sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and not candidate.is_symlink()
        and ".git" not in candidate.relative_to(path).parts
    )


def _sha256_retained_member(path: Path) -> str:
    with io_path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _config_retained_paths(
    config: Mapping[str, Any],
    *,
    repository_root: Path,
    git_witnesses: Mapping[str, tuple[str, Path]],
) -> dict[str, Path]:
    file_keys = {
        "source_file",
        "source_path",
        "raw_file",
        "input_file",
    }
    directory_keys = {
        "source_dir",
        "raw_dir",
        "input_dir",
    }
    file_values: list[str] = []
    directory_values: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key in file_keys and isinstance(item, str):
                    file_values.extend(
                        part.strip() for part in item.split(";") if part.strip()
                    )
                elif key in directory_keys and isinstance(item, str):
                    directory_values.extend(
                        part.strip() for part in item.split(";") if part.strip()
                    )
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(config)
    paths: dict[str, Path] = {}
    for value in [*file_values, *directory_values]:
        logical_path = value.replace("\\", "/")
        paths[logical_path] = _resolved_retained_path(
            repository_root, logical_path, "source config retained path"
        )
    remote = _normalized_remote(config.get("source_url"))
    if remote is not None and remote in git_witnesses:
        logical_path, physical_path = git_witnesses[remote]
        paths[logical_path] = physical_path
    return paths


def _config_work_identifiers(config: Mapping[str, Any]) -> set[str]:
    return {
        identifier
        for key in ("resource_id", "collection_id", "commentary_id", "work_id", "id")
        if (identifier := _clean_str(config.get(key))) is not None
    }


def _raw_git_witnesses(repository_root: Path) -> dict[str, tuple[str, Path]]:
    raw_root = _resolved_retained_path(repository_root, "raw", "retained raw root")
    matches: dict[str, tuple[str, Path]] = {}
    if not raw_root.is_dir():
        return matches
    config_paths = sorted(
        {*raw_root.glob("*/.git/config"), *raw_root.glob("*/*/.git/config")}
    )
    for config_path in config_paths:
        try:
            content = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(
                f"retained Git metadata is unreadable: {config_path}"
            ) from exc
        parser = configparser.ConfigParser(
            interpolation=None,
            strict=True,
            default_section="__ocd_disabled_git_defaults__",
        )
        try:
            parser.read_string(content)
        except configparser.Error as exc:
            raise ValueError(
                f"retained Git metadata is invalid: {config_path}"
            ) from exc
        checkout = config_path.parent.parent
        logical_checkout = _logical_retained_path(
            repository_root, checkout, "retained Git checkout"
        )
        for section in parser.sections():
            if re.fullmatch(r'remote\s+"[^"]+"', section, flags=re.IGNORECASE) is None:
                continue
            remote = _normalized_remote(parser.get(section, "url", fallback=None))
            if remote is None:
                continue
            existing = matches.get(remote)
            witness = (logical_checkout, checkout)
            if existing is not None and existing != witness:
                raise ValueError(f"retained Git remote {remote} has multiple checkouts")
            matches[remote] = witness
    return matches


def _inventory_witnesses(repository_root: Path) -> list[dict[str, Any]]:
    fixtures_root = repository_root / "tests" / "fixtures"
    witnesses: list[dict[str, Any]] = []
    if not fixtures_root.is_dir():
        return witnesses
    for evidence_path in sorted(
        fixtures_root.rglob("proof-selection-observations-v1.json")
    ):
        try:
            evidence = _load_json(evidence_path)
        except (OSError, UnicodeError) as exc:
            raise ValueError(
                f"retained witness evidence is unreadable: {evidence_path}"
            ) from exc
        if not isinstance(evidence, Mapping):
            raise ValueError(f"retained witness evidence is invalid: {evidence_path}")
        identity = evidence.get("source_identity")
        authority = evidence.get("retained_authority")
        if not isinstance(identity, Mapping) or not isinstance(authority, Mapping):
            raise ValueError(
                f"retained witness evidence lacks identity or authority: {evidence_path}"
            )
        work_id = _clean_str(identity.get("resource_id"))
        inventory_value = _clean_str(authority.get("inventory"))
        inventory_sha = _normal_sha256(authority.get("inventory_sha256"))
        member_count = authority.get("member_count")
        if (
            work_id is None
            or inventory_value is None
            or not _is_exact_sha256(inventory_sha)
            or not isinstance(member_count, int)
            or isinstance(member_count, bool)
            or member_count < 0
        ):
            raise ValueError(
                f"retained witness evidence has invalid authority fields: {evidence_path}"
            )
        inventory_path = _resolved_retained_path(
            repository_root, inventory_value, "retained inventory path"
        )
        verification = "verified"
        blocker: str | None = None
        if not inventory_path.is_file():
            verification = "blocked"
            blocker = "retained inventory is missing"
        else:
            try:
                observed_sha = hashlib.sha256(inventory_path.read_bytes()).hexdigest()
            except OSError:
                verification = "blocked"
                blocker = "retained inventory is unreadable"
            else:
                if observed_sha != inventory_sha:
                    verification = "blocked"
                    blocker = "retained inventory digest is stale"
        witnesses.append(
            {
                "work_id": work_id,
                "inventory_path": inventory_path,
                "inventory_logical_path": inventory_value,
                "evidence_path": evidence_path,
                "expected_member_count": member_count,
                "verification": verification,
                "blocker": blocker,
            }
        )
    return witnesses


def _inventory_members(
    inventory_path: Path, repository_root: Path
) -> list[tuple[str, str, bool]]:
    lines = inventory_path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "logical_path\tbyte_count\tsha256":
        raise ValueError(f"retained inventory {inventory_path} has an invalid header")
    members: list[tuple[str, str, bool]] = []
    for line in lines[1:]:
        fields = line.split("\t")
        if (
            len(fields) != 3
            or not fields[1].isdigit()
            or not _is_exact_sha256(fields[2])
        ):
            raise ValueError(f"retained inventory {inventory_path} has an invalid row")
        lexical, expected_bytes, digest = fields
        path = _resolved_retained_path(
            repository_root, lexical, "retained inventory member path"
        )
        try:
            current = path.read_bytes()
        except OSError:
            current = b""
            current_ok = False
        else:
            current_ok = (
                len(current) == int(expected_bytes)
                and hashlib.sha256(current).hexdigest() == digest
            )
        members.append((lexical, digest, current_ok))
    return members


@dataclass(frozen=True, slots=True)
class _RetainedWitnessConfigScope:
    config: Mapping[str, Any]
    work_ids: frozenset[str]
    primary_source_paths: frozenset[Path]


def _attach_scoped_retained_witness_gaps(
    works: list[dict[str, Any]],
    repository_root: Path,
    selected_configs: Mapping[Path, _RetainedWitnessConfigScope],
) -> None:
    """Check only target configs and primary files from selected manifests."""

    by_id = {str(work["work_id"]): work for work in works}
    descriptions: dict[tuple[str, str], dict[str, Any]] = {}
    for work in works:
        work["retained_witness_gaps"] = []

    for config_path, scope in sorted(selected_configs.items()):
        for retained_logical_path, retained_path in sorted(
            _config_retained_paths(
                scope.config,
                repository_root=repository_root,
                git_witnesses={},
            ).items()
        ):
            if retained_path.is_symlink():
                files: list[Path] = []
            elif retained_path.is_file():
                files = (
                    [retained_path]
                    if retained_path in scope.primary_source_paths
                    else []
                )
            elif retained_path.is_dir():
                files = sorted(
                    path
                    for path in scope.primary_source_paths
                    if path != retained_path
                    and path.is_relative_to(retained_path)
                    and path.is_file()
                    and not path.is_symlink()
                )
            else:
                files = []
            if not files:
                continue
            for work_id in scope.work_ids:
                work = by_id.get(work_id)
                if work is None:
                    continue
                parser_hashes = _work_source_hashes(work)
                members = [
                    (
                        _logical_retained_path(
                            repository_root, path, "selected retained config member"
                        ),
                        _sha256_retained_member(path),
                    )
                    for path in files
                ]
                missing = [
                    path for path, digest in members if digest not in parser_hashes
                ]
                descriptions[(work_id, retained_logical_path)] = {
                    "evidence": config_path.relative_to(
                        repository_root
                    ).as_posix(),
                    "retained_path": retained_logical_path,
                    "member_count": len(members),
                    "missing_from_parser_provenance": len(missing),
                    "missing_member_sample": missing[:3],
                    "verification": "verified",
                }

    for work_id, work in by_id.items():
        gaps = [
            value
            for (candidate_work_id, _), value in sorted(descriptions.items())
            if candidate_work_id == work_id
            and value["missing_from_parser_provenance"] > 0
        ]
        work["retained_witness_gaps"] = gaps
        if gaps:
            _append_audit_flag(
                work, "retained_source_witness_missing_from_parser_provenance"
            )


@storage_read_phase()
def _attach_retained_witness_gaps(
    works: list[dict[str, Any]],
    repository_root: Path,
    *,
    selected_configs: Mapping[Path, _RetainedWitnessConfigScope] | None = None,
) -> None:
    """Expose retained witnesses omitted from parser provenance without choosing authority."""

    if selected_configs is not None:
        _attach_scoped_retained_witness_gaps(
            works,
            repository_root,
            selected_configs,
        )
        return

    member_digests: dict[Path, str] = {}

    def retained_members(files: list[Path], label: str) -> list[tuple[str, str]]:
        # Check each declaration before reading; share hashes only within this audit.
        logical = [_logical_retained_path(repository_root, path, label) for path in files]
        missing = list(dict.fromkeys(path for path in files if path not in member_digests))
        if len(missing) > 128:
            with ThreadPoolExecutor(max_workers=4) as pool:
                for start in range(0, len(missing), 128):
                    batch = missing[start:start + 128]
                    member_digests.update(zip(batch, pool.map(_sha256_retained_member, batch), strict=True))
        else:
            member_digests.update((path, _sha256_retained_member(path)) for path in missing)
        return [(name, member_digests[path]) for name, path in zip(logical, files, strict=True)]

    by_id = {str(work["work_id"]): work for work in works}
    git_witnesses = _raw_git_witnesses(repository_root)
    descriptions: dict[tuple[str, str], dict[str, Any]] = {}
    sources_root = repository_root / "sources"
    if sources_root.is_dir():
        for config_path in sorted(sources_root.rglob("config.json")):
            try:
                config = _load_json(config_path)
            except (OSError, UnicodeError) as exc:
                raise ValueError(f"source config is unreadable: {config_path}") from exc
            if not isinstance(config, Mapping):
                raise ValueError(f"source config is invalid JSON object: {config_path}")
            work_ids = _config_work_identifiers(config)
            for retained_logical_path, retained_path in sorted(
                _config_retained_paths(
                    config,
                    repository_root=repository_root,
                    git_witnesses=git_witnesses,
                ).items()
            ):
                files = _retained_files(retained_path)
                if not files:
                    for work_id in work_ids & by_id.keys():
                        descriptions[(work_id, retained_logical_path)] = {
                            "evidence": config_path.relative_to(
                                repository_root
                            ).as_posix(),
                            "retained_path": retained_logical_path,
                            "member_count": 0,
                            "missing_from_parser_provenance": 0,
                            "missing_member_sample": [],
                            "verification": "blocked",
                            "blocker": "configured retained path is missing or is an unsupported link",
                        }
                    continue
                matching_work_ids = work_ids & by_id.keys()
                if not matching_work_ids:
                    continue
                members = retained_members(files, "retained config member")
                for work_id in matching_work_ids:
                    parser_hashes = _work_source_hashes(by_id[work_id])
                    missing = [
                        path for path, digest in members if digest not in parser_hashes
                    ]
                    descriptions[(work_id, retained_logical_path)] = {
                        "evidence": config_path.relative_to(repository_root).as_posix(),
                        "retained_path": retained_logical_path,
                        "member_count": len(members),
                        "missing_from_parser_provenance": len(missing),
                        "missing_member_sample": missing[:3],
                        "verification": "verified",
                    }
    witness_registry_path = sources_root / "witnesses" / "registry.json"
    if witness_registry_path.is_file():
        registry = _load_json(witness_registry_path)
        if not isinstance(registry, Mapping) or not isinstance(
            registry.get("witnesses"), list
        ):
            raise ValueError(
                f"retained witness registry is invalid: {witness_registry_path}"
            )
        for entry in registry["witnesses"]:
            if not isinstance(entry, Mapping):
                raise ValueError(
                    f"retained witness registry entry is invalid: {witness_registry_path}"
                )
            work_id = _clean_str(entry.get("related_resource_id"))
            local_path = _clean_str(entry.get("local_path"))
            if work_id not in by_id or local_path is None:
                continue
            logical_path = local_path.replace("\\", "/")
            retained_path = _resolved_retained_path(
                repository_root, logical_path, "retained witness registry path"
            )
            files = _retained_files(retained_path)
            if not files:
                descriptions[(work_id, logical_path)] = {
                    "evidence": witness_registry_path.relative_to(
                        repository_root
                    ).as_posix(),
                    "retained_path": logical_path,
                    "member_count": 0,
                    "missing_from_parser_provenance": 0,
                    "missing_member_sample": [],
                    "verification": "blocked",
                    "blocker": "registered retained path is missing or is an unsupported link",
                }
                continue
            parser_hashes = _work_source_hashes(by_id[work_id])
            members = retained_members(files, "retained registry member")
            missing = [path for path, digest in members if digest not in parser_hashes]
            descriptions[(work_id, logical_path)] = {
                "evidence": witness_registry_path.relative_to(
                    repository_root
                ).as_posix(),
                "retained_path": logical_path,
                "member_count": len(members),
                "missing_from_parser_provenance": len(missing),
                "missing_member_sample": missing[:3],
                "verification": "verified",
            }
    for witness in _inventory_witnesses(repository_root):
        work_id = witness["work_id"]
        inventory_path = witness["inventory_path"]
        evidence_path = witness["evidence_path"]
        if work_id not in by_id:
            continue
        assert isinstance(inventory_path, Path)
        assert isinstance(evidence_path, Path)
        inventory_logical_path = str(witness["inventory_logical_path"])
        expected_member_count = int(witness["expected_member_count"])
        if witness["verification"] != "verified":
            descriptions[(str(work_id), inventory_logical_path)] = {
                "evidence": evidence_path.relative_to(repository_root).as_posix(),
                "retained_path": inventory_logical_path,
                "member_count": expected_member_count,
                "missing_from_parser_provenance": expected_member_count,
                "missing_member_sample": [],
                "verification": "blocked",
                "blocker": str(witness["blocker"]),
            }
            continue
        parser_hashes = _work_source_hashes(by_id[work_id])
        members = _inventory_members(inventory_path, repository_root)
        missing = [path for path, digest, _ in members if digest not in parser_hashes]
        current = all(current_ok for _, _, current_ok in members)
        if len(members) != expected_member_count:
            current = False
        descriptions[(str(work_id), inventory_logical_path)] = {
            "evidence": evidence_path.relative_to(repository_root).as_posix(),
            "retained_path": inventory_logical_path,
            "member_count": len(members),
            "missing_from_parser_provenance": len(missing),
            "missing_member_sample": missing[:3],
            "verification": "verified" if current else "blocked",
        }
        if not current:
            descriptions[(str(work_id), inventory_logical_path)]["blocker"] = (
                "retained inventory member count or member bytes are stale"
            )
    for work_id, work in by_id.items():
        gaps = [
            value
            for (candidate_work_id, _), value in sorted(descriptions.items())
            if candidate_work_id == work_id
            and (
                value["missing_from_parser_provenance"] > 0
                or value["verification"] != "verified"
            )
        ]
        work["retained_witness_gaps"] = gaps
        if gaps:
            _append_audit_flag(
                work, "retained_source_witness_missing_from_parser_provenance"
            )


def _runtime_evidence_paths(
    evidence: Mapping[tuple[str, str], tuple[Path | str, Path | str]] | None,
    *,
    source_id: str,
    work_id: str,
) -> tuple[Path | None, Path | None]:
    """Resolve one caller-selected candidate/report pair without retaining it."""

    if evidence is None:
        return None, None
    pair = evidence.get((source_id, work_id))
    if pair is None:
        return None, None
    if not isinstance(pair, (tuple, list)) or len(pair) != 2:
        raise ValueError(
            f"reconstruction evidence for {(source_id, work_id)!r} must be a candidate/validation pair"
        )
    candidate_path, validation_path = pair
    if candidate_path is None or validation_path is None:
        raise ValueError(
            f"reconstruction evidence for {(source_id, work_id)!r} must include both paths"
        )
    try:
        return Path(candidate_path), Path(validation_path)
    except TypeError as exc:
        raise ValueError(
            f"reconstruction evidence for {(source_id, work_id)!r} has invalid paths"
        ) from exc


def _set_decision_state(
    state: dict[str, Any],
    *,
    disposition: str,
    scope: str,
    verified: bool,
) -> None:
    if not verified or scope != "work":
        state["accepted_ir"] = "not_accepted"
        if scope == "partial":
            state["blocker"] = state.get("blocker") or PARTIAL_COVERAGE_BLOCKER
        return
    state["human_review"] = disposition
    if disposition == "accepted":
        state["accepted_ir"] = "accepted"
    else:
        state["accepted_ir"] = "not_accepted"


def _derive_reconstruction_state(work: dict[str, Any]) -> None:
    """Derive one work state from its complete route set without order precedence."""

    previous = work["reconstruction_state"]
    routes = list(previous.get("routes", []))
    state = _default_reconstruction_state()
    state["routes"] = routes
    work["reconstruction_state"] = state

    verified_routes = [route for route in routes if route["verification"] == "verified"]
    complete_routes = [route for route in verified_routes if route["scope"] == "work"]
    partial_routes = [route for route in verified_routes if route["scope"] == "partial"]
    if complete_routes:
        state["retained_source"] = "manifest_bound"
        state["tei_candidate"] = "route_available"
        state["validation"] = "validator_available"
        state["human_review"] = "required"
    elif partial_routes:
        state["retained_source"] = "manifest_bound_partial"
        state["tei_candidate"] = "route_available_partial"
        state["validation"] = "validator_available_partial"
        state["human_review"] = "required"
        state["blocker"] = PARTIAL_COVERAGE_BLOCKER
    elif routes:
        state["retained_source"] = "manifest_unverified"
        state["tei_candidate"] = "blocked"
        state["validation"] = "blocked"
        state["human_review"] = "blocked"
        state["blocker"] = next(
            (str(route["blocker"]) for route in routes if route.get("blocker")),
            "no reconstruction route has verified exact source participation",
        )

    complete_evidence = [
        route
        for route in complete_routes
        if route.get("candidate_verification") == "verified"
    ]
    partial_evidence = [
        route
        for route in partial_routes
        if route.get("candidate_verification") == "partial"
    ]

    # A verified complete route is authoritative over partial alternatives.
    # Failures on another complete route remain material until an authority is
    # selected; failures on partial routes stay local to those partial routes.
    blocking_routes = complete_routes or routes
    blocked_evidence = [
        route
        for route in blocking_routes
        if route.get("candidate_verification") == "blocked"
        or (
            isinstance(route.get("decision"), Mapping)
            and route["decision"].get("verification") == "blocked"
        )
    ]
    if blocked_evidence:
        state["tei_candidate"] = "blocked"
        state["validation"] = "blocked"
        state["human_review"] = "blocked"
        state["accepted_ir"] = "not_accepted"
        state["blocker"] = next(
            (
                str(route["blocker"])
                for route in blocked_evidence
                if route.get("blocker")
            ),
            "supplied reconstruction evidence is invalid",
        )
        return
    if complete_evidence:
        state["tei_candidate"] = "verified"
        state["validation"] = "verified"
    elif partial_evidence and not complete_routes:
        state["tei_candidate"] = "partial"
        state["validation"] = "partial"

    blocker_routes = complete_routes or routes
    blockers = [
        route["decision"]
        for route in blocker_routes
        if isinstance(route.get("decision"), Mapping)
        and route["decision"].get("disposition") == "blocked"
    ]
    if blockers:
        if len(blockers) > 1:
            raise ValueError(
                f"work {work['work_id']} has multiple source-local blockers; "
                "an authoritative route must be selected"
            )
        blocker_details = blockers[0].get("blocker")
        if not isinstance(blocker_details, Mapping):
            raise ValueError(
                "verified blocked decision lacks structured blocker evidence"
            )
        state["tei_candidate"] = "blocked"
        state["validation"] = "blocked"
        state["human_review"] = "blocked"
        state["accepted_ir"] = "not_accepted"
        state["blocker"] = str(blocker_details["dependency"])
        state["blocker_details"] = dict(blocker_details)
        return

    decisions = [
        route["decision"]
        for route in complete_routes
        if isinstance(route.get("decision"), Mapping)
        and route["decision"].get("disposition")
        in {
            "accepted",
            "rejected",
            "needs-correction",
        }
    ]
    if len(decisions) > 1:
        raise ValueError(
            f"work {work['work_id']} has multiple source-local decisions; "
            "an authoritative route must be selected"
        )
    if decisions:
        _set_decision_state(
            state,
            disposition=str(decisions[0]["disposition"]),
            scope="work",
            verified=True,
        )


def _apply_candidate_validation_evidence(
    work: dict[str, Any],
    manifest_path: Path,
    repository_root: Path,
    *,
    scope: str,
    verified: bool,
    candidate_path: Path | None,
    validation_path: Path | None,
    route: dict[str, Any],
    verified_reviews: set[tuple[object, ...]] | None = None,
) -> None:
    """Bind optional candidate/report evidence before any decision is read."""

    supplied_any = candidate_path is not None or validation_path is not None
    if not supplied_any:
        return
    state = work["reconstruction_state"]
    if (candidate_path is None) != (validation_path is None):
        error = "candidate and validation evidence paths must be supplied together"
    elif not verified:
        return
    else:
        try:
            from ocd_kernel.reconstruction.decision import _jsonable, load_verified_review

            manifest = SourceManifest.load(
                manifest_path,
                repository_root=repository_root,
            )
            review_key = None
            if verified_reviews is not None:
                from ocd_kernel.reconstruction.contract import CandidatePackage
                from ocd_kernel.reconstruction.closure_verification import _call_validator_closure

                candidate = CandidatePackage.load(candidate_path)
                report = validation_path.read_bytes()
                try:
                    live_closure, _ = _call_validator_closure(
                        repository_root, manifest.record["validator"]["implementation_path"],
                        _jsonable(manifest.record), manifest_path=manifest_path,
                    )
                except (NotImplementedError, ImportError, ValueError):
                    # Fingerprinting is optional; the full verifier still runs.
                    pass
                else:
                    schema_root = repository_root / "ocd_kernel/tei/vendor/xsd"
                    schema_paths = [schema_root / name for name in
                                    ("tei_all.xsd", "tei_all_teix.xsd", "tei_all_xml.xsd")]
                    if all(path.is_file() for path in schema_paths):
                        schema_hashes = tuple(hashlib.sha256(path.read_bytes()).hexdigest()
                                              for path in schema_paths)
                        # The two imported XSDs must remain bound even on reuse.
                        review_key = (manifest_path, manifest.sha256, candidate.path,
                                      candidate.sha256, validation_path,
                                      hashlib.sha256(report).hexdigest(), live_closure,
                                      schema_hashes)
            if review_key is None or review_key not in verified_reviews:
                load_verified_review(
                    manifest,
                    candidate_path=candidate_path,
                    validation_path=validation_path,
                )
                if review_key is not None:
                    verified_reviews.add(review_key)
        except (OSError, ValueError) as exc:
            error = f"candidate or validation evidence is invalid: {exc}"
        else:
            if scope == "partial":
                state["tei_candidate"] = "partial"
                state["validation"] = "partial"
                route["candidate_verification"] = "partial"
                route["validation_verification"] = "partial"
            else:
                state["tei_candidate"] = "verified"
                state["validation"] = "verified"
                route["candidate_verification"] = "verified"
                route["validation_verification"] = "verified"
            state["human_review"] = "required"
            return
    route["blocker"] = error
    route["candidate_verification"] = "blocked"
    route["validation_verification"] = "blocked"
    state["tei_candidate"] = "blocked"
    state["validation"] = "blocked"
    state["human_review"] = "blocked"
    state["accepted_ir"] = "not_accepted"
    state["blocker"] = error


def _manifest_work_profile_ids(
    manifest: Mapping[str, Any], repo_root: Path,
) -> set[str]:
    """Use one byte-bound singular profile only when explicit identities are absent."""

    from ocd_kernel.library._common import safe_identifier
    from ocd_kernel.reconstruction.contract import _strict_json

    profiles = [
        authority for authority in manifest.get("authorities") or []
        if isinstance(authority, Mapping)
        and isinstance(authority.get("name"), str)
        and bool(authority["name"].strip())
        and authority.get("role") == "complete-source-feature-profile"
    ]
    if len(profiles) != 1:
        return set()
    authority = profiles[0]
    logical_path = authority.get("path")
    if not isinstance(logical_path, str):
        return set()
    relative = Path(logical_path)
    if (relative.is_absolute() or relative.drive or relative.suffix != ".json"
        or any(part in {"", ".", ".."} for part in logical_path.replace("\\", "/").split("/"))):
        return set()
    try:
        root = repo_root.resolve(strict=True)
        path = (root / relative).resolve(strict=True)
        path.relative_to(root)
        content = path.read_bytes()
        if (authority.get("bytes") != len(content)
            or authority.get("sha256") != hashlib.sha256(content).hexdigest()):
            return set()
        profile = _strict_json(content, "reconstruction work profile")
        work_id = profile.get("work_id")
        if "work_ids" in profile or not isinstance(work_id, str):
            return set()
        return {safe_identifier(work_id, field="reconstruction work profile identity")}
    except (OSError, RuntimeError, ValueError):
        # An unusable profile supplies no exact identity. Existing route binding
        # still rejects ambiguous hashes and accounts for blocked discovery.
        return set()


def _manifest_config_ids(
    manifest: Mapping[str, Any],
    repo_root: Path,
    *,
    config_records: dict[Path, Mapping[str, Any]] | None = None,
) -> set[str]:
    from ocd_kernel.library._common import safe_identifier

    declared: set[str] | None = None
    if "work_id" in manifest or "work_ids" in manifest:
        if "work_id" in manifest and "work_ids" in manifest:
            raise ValueError("source manifest has competing work identity declarations")
        if "work_id" in manifest and (not isinstance(manifest["work_id"], str) or not manifest["work_id"].strip()):
            raise ValueError("source manifest work_id is invalid")
        values = manifest.get("work_ids") if "work_ids" in manifest else [manifest["work_id"]]
        if not isinstance(values, (list, tuple)) or not values or any(not isinstance(value, str) for value in values):
            raise ValueError("source manifest work identities must be a nonempty sequence of strings")
        checked = [safe_identifier(value, field="source manifest work identity") for value in values]
        if len(set(checked)) != len(checked):
            raise ValueError("source manifest work identities are duplicated")
        declared = set(checked)
    identifiers: set[str] = set()
    for authority in manifest.get("authorities") or []:
        if not isinstance(authority, Mapping):
            continue
        authority_path = _clean_str(authority.get("path"))
        if authority_path is None or Path(authority_path).name != "config.json":
            continue
        try:
            config_path = repo_root / Path(authority_path)
            config = _load_json(config_path)
            if config_records is not None and isinstance(config, Mapping):
                config_records[config_path.resolve(strict=True)] = config
        except (OSError, UnicodeError):
            continue
        if not isinstance(config, Mapping):
            continue
        identifiers.update(_config_work_identifiers(config))
    # Historical singular work_id can name a reconstruction cohort rather than
    # a catalog work. Existing config identities remain authoritative there.
    if identifiers and "work_ids" not in manifest:
        return identifiers
    if declared is not None:
        if identifiers - declared:
            raise ValueError("source manifest declared work identities conflict with config identities")
        return declared
    # Explicit declarations/configs remain authoritative. A profile cannot
    # replace their identities or resolve a contradiction in their evidence.
    return identifiers or _manifest_work_profile_ids(manifest, repo_root)


def _selected_retained_witness_configs(
    manifest: Mapping[str, Any],
    config_records: Mapping[Path, Mapping[str, Any]],
    works: list[dict[str, Any]],
    target_work_ids: set[str],
    repository_root: Path,
) -> dict[Path, _RetainedWitnessConfigScope]:
    """Select one exact manifest config per evidence-bound catalog work."""

    work_by_id = {str(work["work_id"]): work for work in works}
    primary_authorities = [
        authority
        for authority in manifest.get("authorities") or []
        if isinstance(authority, Mapping)
        and authority.get("role") == "primary-source"
    ]
    selected: dict[Path, _RetainedWitnessConfigScope] = {}
    for target_work_id in sorted(target_work_ids & work_by_id.keys()):
        matching_records: list[tuple[Path, Mapping[str, Any], set[str]]] = []
        for config_path, config in config_records.items():
            config_identifiers = _config_work_identifiers(config)
            matched_work_ids = {
                str(work["work_id"])
                for work in works
                if config_identifiers
                & {
                    str(work["work_id"]),
                    *(str(value) for value in work.get("resource_ids", [])),
                }
            }
            if target_work_id not in matched_work_ids:
                continue
            if matched_work_ids - target_work_ids:
                raise ValueError(
                    "selected source config identity also binds an unselected WorkCatalog work: "
                    f"{config_path}"
                )
            matching_records.append((config_path, config, matched_work_ids))
        if len(matching_records) > 1:
            raise ValueError(
                "selected source config identity is ambiguous for WorkCatalog work "
                f"{target_work_id}"
            )
        if not matching_records:
            continue

        work_hashes = _work_source_hashes(work_by_id[target_work_id])
        primary_source_paths = {
            _resolved_retained_path(
                repository_root,
                authority_path,
                "selected primary source authority path",
            )
            for authority in primary_authorities
            if (authority_path := _clean_str(authority.get("path"))) is not None
            and _normal_sha256(authority.get("sha256")) in work_hashes
        }
        if len(primary_source_paths) > 1:
            raise ValueError(
                "selected WorkCatalog work has multiple matching primary source authorities: "
                f"{target_work_id}"
            )
        config_path, config, matched_work_ids = matching_records[0]
        selected[config_path] = _RetainedWitnessConfigScope(
            config=config,
            work_ids=frozenset(matched_work_ids),
            primary_source_paths=frozenset(primary_source_paths),
        )
    return selected


def _verify_catalog_claim_lineage(
    manifest: Mapping[str, Any],
    work: Mapping[str, Any],
    manifest_hashes: set[str],
    data_root: Path,
) -> bool:
    """Verify an explicit legacy-catalog claim bridge to retained authority.

    The bridge identifies stale derived-output claims already present in the
    ordinary WorkCatalog. It never promotes those hashes to reconstruction
    authority: the declared retained digest must still be one of the exact
    source-member or member-set digests verified by the source manifest.
    """

    lineage = manifest.get("catalog_claim_lineage")
    if lineage is None:
        return False
    if not isinstance(lineage, Mapping) or lineage.get("contract") != (
        "ocd-catalog-claim-lineage-v1"
    ):
        raise ValueError("catalog claim lineage contract is invalid")
    work_id = _clean_str(lineage.get("work_id"))
    if work_id != work.get("work_id"):
        raise ValueError("catalog claim lineage does not bind the exact work")
    retained_digest = _normal_sha256(lineage.get("retained_source_sha256"))
    if retained_digest is None or retained_digest not in manifest_hashes:
        raise ValueError(
            "catalog claim lineage retained digest is not verified by the source manifest"
        )
    claims = lineage.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("catalog claim lineage claims must be a nonempty list")
    if lineage.get("claim_count") != len(claims):
        raise ValueError("catalog claim lineage claim count is stale")

    observed_paths: list[str] = []
    observed_claims: list[tuple[str, str]] = []
    observed_hashes: set[str] = set()
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ValueError("catalog claim lineage claim is not an object")
        source_path = _clean_str(claim.get("source_path"))
        digest = _normal_sha256(claim.get("legacy_source_sha256"))
        if source_path is None:
            raise ValueError("catalog claim lineage source path is missing")
        lexical = Path(source_path)
        if (
            lexical.is_absolute()
            or ".." in lexical.parts
            or lexical.as_posix() != source_path
        ):
            raise ValueError("catalog claim lineage source path is not normalized")
        if digest is None or not _is_exact_sha256(digest):
            raise ValueError("catalog claim lineage legacy source hash is invalid")
        observed_paths.append(source_path)
        observed_claims.append((source_path, digest))
        observed_hashes.add(digest)

    expected_paths = sorted(str(path) for path in work.get("source_paths", []))
    if observed_paths != sorted(observed_paths) or len(set(observed_paths)) != len(
        observed_paths
    ):
        raise ValueError("catalog claim lineage source paths must be sorted and unique")
    expected_claims: list[tuple[str, str]] = []
    for source_path in expected_paths:
        resource = _load_json(data_root / Path(source_path))
        meta = resource.get("meta") if isinstance(resource, Mapping) else None
        provenance = meta.get("provenance") if isinstance(meta, Mapping) else None
        digest = (
            _normal_sha256(provenance.get("source_hash"))
            if isinstance(provenance, Mapping)
            else None
        )
        if digest is None or not _is_exact_sha256(digest):
            raise ValueError(
                "catalog claim lineage current WorkCatalog source hash is invalid"
            )
        expected_claims.append((source_path, digest))
    if (
        observed_claims != expected_claims
        or observed_hashes != _work_source_hashes(work)
    ):
        raise ValueError("catalog claim lineage does not exactly match current WorkCatalog claims")
    return True


def _attach_reconstruction_route(
    work: dict[str, Any],
    manifest: Mapping[str, Any],
    manifest_path: Path,
    sources_root: Path,
    *,
    association: str,
    scope: str,
    verified: bool,
    blocker: str | None,
    candidate_path: Path | None = None,
    validation_path: Path | None = None,
    provenance_gap: tuple[str, ...] = (),
    manifest_verified: bool | None = None,
    member: Mapping[str, Any] | None = None,
    verified_reviews: set[tuple[object, ...]] | None = None,
) -> None:
    state = work["reconstruction_state"]
    _ensure_reconstruction_state(state)
    source_id = _clean_str(
        manifest.get("source_id")
    ) or manifest_path.name.removesuffix(".source-manifest.json")
    route = {
        "association": association,
        "manifest": manifest_path.relative_to(sources_root.parent).as_posix(),
        "scope": scope,
        "source_id": source_id,
        "verification": "verified" if verified else "blocked",
    }
    if manifest_verified is not None and manifest_verified != verified:
        route["manifest_verification"] = "verified" if manifest_verified else "blocked"
    if blocker is not None:
        route["blocker"] = blocker
    if member is not None:
        route["member"] = dict(member)
    if provenance_gap:
        _append_audit_flag(
            work, "retained_source_witness_missing_from_parser_provenance"
        )
    if verified:
        if scope == "partial":
            if state["retained_source"] not in {
                "manifest_bound",
                "manifest_bound_partial",
            }:
                state["retained_source"] = "manifest_bound_partial"
                state["tei_candidate"] = "route_available_partial"
                state["validation"] = "validator_available_partial"
                state["human_review"] = "required"
            state["blocker"] = state.get("blocker") or (
                "partial source coverage cannot establish whole-work accepted IR"
            )
        else:
            state["retained_source"] = "manifest_bound"
            state["tei_candidate"] = "route_available"
            state["validation"] = "validator_available"
            state["human_review"] = "required"
    elif state["retained_source"] != "manifest_bound":
        if state["retained_source"] != "manifest_bound_partial":
            state["retained_source"] = "manifest_unverified"
            state["tei_candidate"] = "blocked"
            state["validation"] = "blocked"
            state["human_review"] = "blocked"
    if blocker is not None and state.get("blocker") is None:
        state["blocker"] = blocker
    _apply_candidate_validation_evidence(
        work,
        manifest_path,
        sources_root.parent,
        scope=scope,
        verified=verified,
        candidate_path=candidate_path,
        validation_path=validation_path,
        route=route,
        verified_reviews=verified_reviews,
    )
    if manifest.get("source_id") and work.get("work_id"):
        from ocd_kernel.reconstruction.decision import catalog_decision, decision_path

        expected_decision = decision_path(
            manifest_path,
            source_id=source_id,
            work_id=str(work["work_id"]),
        )
        if expected_decision.exists():
            try:
                decision = catalog_decision(
                    manifest_path,
                    repository_root=sources_root.parent,
                    source_id=source_id,
                    work_id=str(work["work_id"]),
                    candidate_path=candidate_path,
                    validation_path=validation_path,
                )
            except (OSError, ValueError) as exc:
                decision = None
                route["decision"] = {
                    "path": expected_decision.relative_to(
                        sources_root.parent
                    ).as_posix(),
                    "verification": "blocked",
                }
                route["blocker"] = f"source-local decision is invalid: {exc}"
                state["human_review"] = "blocked"
                state["accepted_ir"] = "not_accepted"
                state["blocker"] = route["blocker"]
            if decision is not None:
                route["decision"] = decision
    state["routes"].append(route)
    state["routes"].sort(
        key=lambda item: (item["manifest"], item["source_id"], item["association"])
    )
    _derive_reconstruction_state(work)


def _runtime_admission_work_id(value: object) -> str:
    """Validate the caller-supplied identity used for transient admission."""

    work_id = _clean_str(value)
    if (
        work_id is None
        or len(work_id) > 200
        or ".." in work_id
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", work_id) is None
    ):
        raise ValueError(
            "runtime source admission work_id must be a bounded path-free identifier"
        )
    return work_id


def _runtime_admission_work_ids(
    evidence: Mapping[tuple[str, str], tuple[Path | str, Path | str]] | None,
    source_id: str,
) -> list[str]:
    """Return explicit work identities offered for one source manifest."""

    if evidence is None:
        return []
    values: list[str] = []
    for key in evidence:
        if not isinstance(key, tuple) or len(key) != 2:
            raise ValueError("reconstruction evidence keys must be source/work pairs")
        candidate_source_id, work_id = key
        if candidate_source_id != source_id:
            continue
        normalized = _runtime_admission_work_id(work_id)
        if normalized in values:
            continue
        values.append(normalized)
    return sorted(values)


def _runtime_policy_identity(
    source_manifest: SourceManifest,
    manifest: Mapping[str, Any],
    manifest_path: Path,
    sources_root: Path,
    *,
    work_id: str,
) -> dict[str, Any]:
    """Derive a transient work identity from verified source-local authorities.

    This deliberately does not inspect candidate bytes or ordinary data rows. A
    source-only row is admitted only when the caller supplies an exact work ID
    and the manifest's independently maintained policy authority provides a
    complete identity. Equiano's identity-resolution sidecar is the authority
    for its abstract title and ordered physical members.
    """

    raw_work_id = manifest.get("work_id")
    if "work_id" in manifest and raw_work_id is not None:
        if not isinstance(raw_work_id, str) or not raw_work_id.strip():
            raise ValueError(
                "runtime source admission manifest work_id is invalid"
            )
    declared_work_id = _clean_str(raw_work_id)
    if declared_work_id is not None and declared_work_id != work_id:
        raise ValueError(
            "runtime source admission work_id does not match source manifest work_id"
        )

    authorities = manifest.get("authorities")
    if not isinstance(authorities, list):
        raise ValueError("runtime source admission authorities are invalid")
    policy_authorities = [
        authority
        for authority in authorities
        if isinstance(authority, Mapping)
        and authority.get("role") == "independent-validation-policy"
    ]
    if len(policy_authorities) != 1:
        raise ValueError(
            "runtime source admission requires exactly one independent-validation-policy authority"
        )
    policy_authority = policy_authorities[0]
    policy_name = _clean_str(policy_authority.get("name"))
    if policy_name is None:
        raise ValueError("runtime source admission policy authority name is missing")
    try:
        policy_record = json.loads(
            source_manifest.authority_path(policy_name).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("runtime source admission policy authority is unreadable") from exc
    if not isinstance(policy_record, Mapping):
        raise ValueError("runtime source admission policy authority is not an object")
    provenance = policy_record.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("runtime source admission policy provenance is missing")
    identity = provenance.get("identity")
    if not isinstance(identity, Mapping):
        raise ValueError("runtime source admission policy identity is missing")
    title = _clean_str(identity.get("title"))
    author = _clean_str(identity.get("author"))
    if title is None or author is None:
        raise ValueError(
            "runtime source admission policy identity requires title and author"
        )

    primary_authorities = [
        authority
        for authority in authorities
        if isinstance(authority, Mapping)
        and authority.get("role") == "primary-source"
    ]
    source = provenance.get("source")
    if not isinstance(source, Mapping) or len(primary_authorities) != 1:
        raise ValueError(
            "runtime source admission policy must bind one primary source"
        )
    policy_source_sha = _normal_sha256(source.get("sha256"))
    manifest_source_sha = _normal_sha256(primary_authorities[0].get("sha256"))
    if policy_source_sha is None or policy_source_sha != manifest_source_sha:
        raise ValueError(
            "runtime source admission policy source hash does not match the manifest"
        )
    policy_source_bytes = source.get("bytes")
    manifest_source_bytes = primary_authorities[0].get("bytes")
    if (
        isinstance(policy_source_bytes, bool)
        or not isinstance(policy_source_bytes, int)
        or policy_source_bytes < 0
        or isinstance(manifest_source_bytes, bool)
        or not isinstance(manifest_source_bytes, int)
        or manifest_source_bytes < 0
    ):
        raise ValueError(
            "runtime source admission policy source byte count is invalid"
        )
    if policy_source_bytes != manifest_source_bytes:
        raise ValueError(
            "runtime source admission policy source byte count does not match the manifest"
        )

    category_parts = manifest_path.relative_to(sources_root).parts
    if not category_parts:
        raise ValueError("runtime source admission manifest has no category")
    category = category_parts[0]
    date = _clean_str(identity.get("date")) or ""
    source_edition = _clean_str(identity.get("edition")) or date
    metadata_fields: dict[str, list[str]] = {
        "author": [author],
        "title": [title],
    }
    if source_edition:
        metadata_fields["provenance.source_edition"] = [source_edition]
    if date:
        metadata_fields["publication_date"] = [date]

    member: dict[str, Any] | None = None
    identity_resolution_authorities = [
        authority
        for authority in authorities
        if isinstance(authority, Mapping)
        and authority.get("role") == "source-identity-resolution-evidence"
    ]
    scope = "work"
    if identity_resolution_authorities:
        if len(identity_resolution_authorities) != 1:
            raise ValueError(
                "runtime source admission requires one identity-resolution authority"
            )
        resolution_name = _clean_str(identity_resolution_authorities[0].get("name"))
        if resolution_name is None:
            raise ValueError(
                "runtime source admission identity-resolution authority name is missing"
            )
        try:
            resolution_path = source_manifest.authority_path(resolution_name)
            resolution = json.loads(
                resolution_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "runtime source admission identity-resolution authority is unreadable"
            ) from exc
        if not isinstance(resolution, Mapping):
            raise ValueError(
                "runtime source admission identity-resolution authority is not an object"
            )
        if (
            resolution.get("contract") != "ocd-equiano-ecco-tcp-identity-resolution-v1"
            or resolution.get("status") != "resolved"
            or resolution.get("guessed_identity") is not False
            or resolution.get("composite_identity") is not False
            or resolution.get("canonical_write") is not False
        ):
            raise ValueError(
                "runtime source admission identity-resolution evidence is not resolved and non-composite"
            )
        abstract_title = _clean_str(resolution.get("abstract_work"))
        abstract_author = _clean_str(resolution.get("author"))
        parts = resolution.get("parts")
        if abstract_title is None or abstract_author is None or not isinstance(parts, list):
            raise ValueError(
                "runtime source admission identity-resolution evidence is incomplete"
            )
        if abstract_author != author:
            raise ValueError(
                "runtime source admission policy author does not match identity-resolution evidence"
            )
        part = identity.get("part")
        tcp_id = _clean_str(identity.get("tcp_id"))
        if isinstance(part, bool) or not isinstance(part, int) or tcp_id is None:
            raise ValueError(
                "runtime source admission policy physical-part identity is incomplete"
            )
        matching_parts = [
            item
            for item in parts
            if isinstance(item, Mapping)
            and item.get("part") == part
            and item.get("tcp_id") == tcp_id
        ]
        if len(matching_parts) != 1 or len(parts) < 2:
            raise ValueError(
                "runtime source admission identity-resolution part is ambiguous or incomplete"
            )
        expected_members = []
        for item in parts:
            if (
                not isinstance(item, Mapping)
                or isinstance(item.get("part"), bool)
                or not isinstance(item.get("part"), int)
                or _clean_str(item.get("tcp_id")) is None
            ):
                raise ValueError(
                    "runtime source admission identity-resolution members are incomplete"
                )
            expected_members.append(
                {"part": item["part"], "tcp_id": _clean_str(item["tcp_id"])}
            )
        if len({(item["part"], item["tcp_id"]) for item in expected_members}) != len(
            expected_members
        ):
            raise ValueError(
                "runtime source admission identity-resolution members are ambiguous"
            )
        expected_members.sort(key=lambda item: (item["part"], item["tcp_id"]))
        if tcp_id.casefold().replace(".", "-") not in str(
            manifest.get("source_id") or ""
        ).casefold():
            raise ValueError(
                "runtime source admission policy physical part does not match source_id"
            )
        policy_title = _clean_str(identity.get("title"))
        title = abstract_title
        metadata_fields["title"] = [title]
        scope = "partial"
        member = {
            "part": part,
            "tcp_id": tcp_id,
            "title": policy_title,
            "expected_members": expected_members,
            "identity_resolution": resolution_path.relative_to(
                sources_root.parent
            ).as_posix(),
        }

    return {
        "work_id": work_id,
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, category),
        "title": title,
        "author": author,
        "publication_date": date,
        "metadata_fields": {
            field: sorted(values) for field, values in sorted(metadata_fields.items())
        },
        "scope": scope,
        "member": member,
    }


def _append_runtime_admission_work(
    works: list[dict[str, Any]],
    identity: Mapping[str, Any],
    *,
    allow_existing_cohort: bool,
) -> dict[str, Any]:
    """Create or verify one transient source-only WorkCatalog row."""

    work_id = str(identity["work_id"])
    existing = next((work for work in works if work.get("work_id") == work_id), None)
    if existing is not None:
        if "runtime_source_admission" not in existing.get("audit_flags", []):
            raise ValueError(
                f"runtime source admission collides with existing WorkCatalog work {work_id}"
            )
        if not allow_existing_cohort:
            raise ValueError(
                "runtime source admission cannot merge another manifest for "
                f"WorkCatalog work {work_id} without an explicit physical-member cohort"
            )
        existing_routes = existing.get("reconstruction_state", {}).get("routes", [])
        if any(
            route.get("association") == "runtime_source_admission"
            and not isinstance(route.get("member"), Mapping)
            for route in existing_routes
            if isinstance(route, Mapping)
        ):
            raise ValueError(
                "runtime source admission cannot merge a generic manifest into "
                f"the physical-member cohort for WorkCatalog work {work_id}"
            )
        for field in ("category", "title", "author", "publication_date"):
            if existing.get(field) != identity.get(field):
                raise ValueError(
                    f"runtime source admission identity conflicts for WorkCatalog work {work_id}"
                )
        if existing.get("metadata_fields") != identity.get("metadata_fields"):
            raise ValueError(
                "runtime source admission metadata fields conflict for "
                f"WorkCatalog work {work_id}"
            )
        return existing

    work = {
        "work_id": work_id,
        "category": identity["category"],
        "category_label": identity["category_label"],
        "title": identity["title"],
        "author": identity["author"],
        "publication_date": identity["publication_date"],
        "author_count": 1,
        "schema_types": [],
        "resource_ids": [],
        "source_paths": [],
        "file_count": 0,
        "top_level_records": 0,
        "leaf_records": 0,
        "legacy_hf_export_records": 0,
        "hymn_summary": None,
        "metadata_fields": dict(identity["metadata_fields"]),
        "audit_flags": ["runtime_source_admission"],
        "retained_witness_gaps": [],
        "reconstruction_state": _default_reconstruction_state(),
    }
    works.append(work)
    return work


def _resolve_source_manifest_allowlist(
    sources_root: Path,
    selections: Iterable[str | Path],
) -> tuple[Path, tuple[Path, ...]]:
    """Resolve explicit repository-relative source manifests without scanning siblings.

    Versioned successors are accepted only when their exact paths are explicitly allowlisted.
    """

    values = list(selections)
    if not values:
        raise ValueError("source manifest allowlist must include at least one path")
    try:
        repository_root = sources_root.parent.resolve(strict=True)
        resolved_sources_root = sources_root.resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            "source manifest allowlist requires an existing repository sources/ directory"
        ) from exc
    if not resolved_sources_root.is_dir():
        raise ValueError(
            "source manifest allowlist requires an existing repository sources/ directory"
        )
    if not resolved_sources_root.is_relative_to(repository_root):
        raise ValueError("repository sources/ directory resolves outside the repository root")
    resolved: list[Path] = []
    seen: set[Path] = set()
    for selection in values:
        if not isinstance(selection, (str, Path)):
            raise ValueError(
                "source manifest allowlist entries must be repository-relative paths under sources/"
            )
        raw = str(selection)
        try:
            relative = Path(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "source manifest allowlist entries must be repository-relative paths under sources/"
            ) from exc
        relative_parts = raw.replace("\\", "/").split("/")
        if (
            not raw
            or relative.is_absolute()
            or relative.drive
            or any(part in {"", ".", ".."} for part in relative_parts)
            or relative_parts[0] != "sources"
        ):
            raise ValueError(
                "source manifest allowlist entries must be normalized repository-relative paths under sources/"
            )
        try:
            manifest_path = (repository_root / Path(*relative_parts)).resolve(
                strict=True
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(
                f"source manifest allowlist path is unavailable: {raw}"
            ) from exc
        try:
            manifest_path.relative_to(resolved_sources_root)
        except ValueError as exc:
            raise ValueError(
                f"source manifest allowlist path is outside the repository sources/ directory: {raw}"
            ) from exc
        if not manifest_path.is_file():
            raise ValueError(
                f"source manifest allowlist path is not a file: {raw}"
            )
        versioned_source_manifest = re.fullmatch(
            r".+\.source-manifest\.v[1-9]\d*\.json", manifest_path.name
        ) is not None
        if not (
            manifest_path.name.endswith(
                (".source-manifest.json", "-source-manifest.json")
            )
            or manifest_path.name == "source-manifest.json"
            or versioned_source_manifest
        ):
            raise ValueError(
                f"source manifest allowlist path does not name a source manifest: {raw}"
            )
        if manifest_path in seen:
            raise ValueError(
                f"source manifest allowlist contains a duplicate path: {raw}"
            )
        seen.add(manifest_path)
        resolved.append(manifest_path)
    return resolved_sources_root, tuple(sorted(resolved))


def _resolve_data_resource_allowlist(
    data_root: Path,
    selections: Iterable[str | Path],
) -> tuple[Path, tuple[Path, ...]]:
    """Resolve exact repository-relative data records without enumerating siblings."""

    values = list(selections)
    if not values:
        raise ValueError("data resource allowlist must include at least one path")
    try:
        repository_root = data_root.parent.resolve(strict=True)
        resolved_data_root = data_root.resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            "data resource allowlist requires an existing repository data/ directory"
        ) from exc
    if (
        data_root.name != "data"
        or not resolved_data_root.is_dir()
        or resolved_data_root.parent != repository_root
        or resolved_data_root.name != "data"
    ):
        raise ValueError(
            "data resource allowlist requires the repository-local data/ directory"
        )
    resolved: list[Path] = []
    seen: set[Path] = set()
    for selection in values:
        if not isinstance(selection, (str, Path)):
            raise ValueError(
                "data resource allowlist entries must be repository-relative JSON paths under data/"
            )
        raw = str(selection)
        try:
            relative = Path(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "data resource allowlist entries must be repository-relative JSON paths under data/"
            ) from exc
        relative_parts = raw.replace("\\", "/").split("/")
        if (
            not raw
            or relative.is_absolute()
            or relative.drive
            or any(part in {"", ".", ".."} for part in relative_parts)
            or relative_parts[0] != "data"
        ):
            raise ValueError(
                "data resource allowlist entries must be normalized repository-relative paths under data/"
            )
        candidate_path = repository_root / Path(*relative_parts)
        try:
            resolved_path = candidate_path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(
                f"data resource allowlist path is unavailable: {raw}"
            ) from exc
        try:
            resolved_path.relative_to(resolved_data_root)
        except ValueError as exc:
            raise ValueError(
                f"data resource allowlist path is outside repository data/: {raw}"
            ) from exc
        if candidate_path.is_symlink():
            raise ValueError(
                f"data resource allowlist path must not be a symlink: {raw}"
            )
        if not resolved_path.is_file() or resolved_path.suffix.casefold() != ".json":
            raise ValueError(
                f"data resource allowlist path must name a JSON file: {raw}"
            )
        if not _is_catalog_resource_path(resolved_path, resolved_data_root):
            raise ValueError(
                f"data resource allowlist path is excluded from the WorkCatalog: {raw}"
            )
        if resolved_path in seen:
            raise ValueError(
                f"data resource allowlist contains a duplicate path: {raw}"
            )
        seen.add(resolved_path)
        resolved.append(resolved_path)
    return resolved_data_root, tuple(sorted(resolved))


def _bind_reconstruction_routes(
    works: list[dict[str, Any]],
    sources_root: Path,
    data_root: Path,
    *,
    reconstruction_evidence: Mapping[tuple[str, str], tuple[Path | str, Path | str]]
    | None = None,
    manifest_paths: Iterable[Path] | None = None,
    retained_witness_scope: dict[Path, _RetainedWitnessConfigScope] | None = None,
) -> dict[str, int]:
    unassociated = Counter()
    verified_reviews: set[tuple[object, ...]] = set()
    evidence_uses: Counter[tuple[str, str]] = Counter()
    scoped_manifest_configs: list[
        tuple[str, Mapping[str, Any], dict[Path, Mapping[str, Any]]]
    ] = []
    scoped_mode = manifest_paths is not None
    if not sources_root.is_dir():
        if reconstruction_evidence:
            raise ValueError(
                "reconstruction evidence cannot bind without source manifests"
            )
        return {}
    selected_manifest_paths = manifest_paths
    if selected_manifest_paths is None:
        selected_manifest_paths = set(sources_root.rglob("*.source-manifest.json"))
        selected_manifest_paths.update(sources_root.rglob("source-manifest.json"))
    for manifest_path in sorted(selected_manifest_paths):
        try:
            content = manifest_path.read_bytes()
            decoded = content.decode("utf-8")
            loaded = json.loads(decoded)
        except OSError:
            manifest, blocker = {}, "source manifest is unavailable"
        except UnicodeDecodeError:
            manifest, blocker = {}, "source manifest is not UTF-8 JSON"
        except json.JSONDecodeError:
            manifest, blocker = {}, "source manifest is not valid JSON"
        else:
            if isinstance(loaded, Mapping):
                manifest, blocker = loaded, None
            else:
                manifest, blocker = {}, "source manifest must be a JSON object"
        if blocker is None:
            try:
                source_manifest_object = SourceManifest.load(
                    manifest_path, repository_root=sources_root.parent
                )
            except OSError:
                source_manifest_object = None
                verified, blocker = False, "manifest dependency unavailable"
            except ValueError as exc:
                source_manifest_object = None
                verified, blocker = False, str(exc)
            else:
                verified = True
        else:
            source_manifest_object = None
            verified = False
        manifest_primary_hashes = _manifest_primary_hashes(manifest)
        manifest_hashes = _manifest_source_hashes(manifest)
        hash_matches = [
            work for work in works if _work_source_hashes(work) & manifest_hashes
        ]
        expression_scope = manifest.get("expression_scope")
        declared_partial = (
            isinstance(expression_scope, Mapping)
            and expression_scope.get("status") == "partial"
        )
        manifest_source_id = _clean_str(
            manifest.get("source_id")
        ) or manifest_path.name.removesuffix(".source-manifest.json")

        manifest_config_records = (
            {}
            if retained_witness_scope is not None and verified
            else None
        )
        identifiers = sorted(
            _manifest_config_ids(
                manifest,
                sources_root.parent,
                config_records=manifest_config_records,
            )
        )
        scoped_target_work_ids = (
            {
                work_id
                for (source_id, work_id) in (reconstruction_evidence or {})
                if source_id == manifest_source_id
            }
            if scoped_mode
            else None
        )
        if manifest_config_records is not None:
            scoped_manifest_configs.append(
                (manifest_source_id, manifest, manifest_config_records)
            )
        if scoped_target_work_ids is not None and not scoped_target_work_ids:
            unassociated["verified" if verified else "blocked"] += 1
            continue
        historical_identity_exists = any(
            "runtime_source_admission" not in work.get("audit_flags", [])
            and any(
                identifier == work["work_id"] or identifier in work["resource_ids"]
                for identifier in identifiers
            )
            for work in works
        )
        runtime_declaration = (
            not hash_matches
            and not historical_identity_exists
            and "work_id" in manifest
            and "work_ids" not in manifest
            and _runtime_admission_work_ids(reconstruction_evidence, manifest_source_id)
            == [manifest["work_id"]]
        )
        if runtime_declaration:
            # Source-only admission has its own verified policy/cohort checks
            # below; it need not already exist in the historical data catalog.
            identifiers = []
        id_matches_by_identifier: list[tuple[str, list[dict[str, Any]]]] = []
        id_matches: list[dict[str, Any]] = []
        for identifier in identifiers:
            matches = [
                work
                for work in works
                if identifier == work["work_id"] or identifier in work["resource_ids"]
            ]
            id_matches_by_identifier.append((identifier, matches))
            for work in matches:
                if work not in id_matches:
                    id_matches.append(work)

        uses_declared_ids = "work_ids" in manifest or (
            "work_id" in manifest and identifiers == [manifest["work_id"]]
        )

        def reject_identity(reason: str) -> None:
            message = f"{reason}: {manifest_path}"
            if verified or scoped_mode:
                raise ValueError(message)
            unassociated["blocked"] += 1
            logging.getLogger(__name__).warning(
                "%s (source_id=%s; manifest verification blocked: %s)",
                message, manifest_source_id, blocker,
            )

        if not runtime_declaration and uses_declared_ids:
            if not hash_matches and not id_matches:
                # A declared-library work need not occur in historical data/.
                # Account for it without inventing a slug-based association.
                unassociated["verified" if verified else "blocked"] += 1
                continue
            if any(len(matches) != 1 for _, matches in id_matches_by_identifier):
                reject_identity("source manifest declared work identity does not bind exactly once")
                continue

        def scope_for(work: Mapping[str, Any], *, compare_hash_coverage: bool) -> str:
            work_hashes = _work_source_hashes(work)
            hash_scope_is_partial = (
                compare_hash_coverage
                and bool(work_hashes)
                and not work_hashes <= manifest_hashes
            )
            return "partial" if declared_partial or hash_scope_is_partial else "work"

        def evidence_for_key(
            key: tuple[str, str]
        ) -> tuple[Path | None, Path | None]:
            paths = _runtime_evidence_paths(
                reconstruction_evidence,
                source_id=key[0],
                work_id=key[1],
            )
            if paths != (None, None):
                evidence_uses[key] += 1
            return paths

        def evidence_for(work: Mapping[str, Any]) -> tuple[Path | None, Path | None]:
            if (
                manifest.get("source_id")
                == "internet-archive-fisher-marrow-1837-retained-ocr"
            ):
                key = (
                    "internet-archive-fisher-marrow-1837-retained-ocr",
                    "fisher-marrow-of-modern-divinity",
                )
                return evidence_for_key(key)
            else:
                key = (manifest_source_id, str(work["work_id"]))
                return evidence_for_key(key)

        def provenance_gap_for(work: Mapping[str, Any]) -> tuple[str, ...]:
            work_hashes = _work_source_hashes(work)
            if work_hashes & (manifest_hashes - manifest_primary_hashes):
                return ()
            return tuple(sorted(manifest_primary_hashes - work_hashes))

        def unverified_blocker(current: str | None) -> str:
            if current:
                return current
            return (
                "exact source hash participation is required for a fully verified route"
            )

        if hash_matches and id_matches:
            exact_id_matches: list[dict[str, Any]] = []
            for _identifier, matches_for_id in id_matches_by_identifier:
                if (
                    len(matches_for_id) == 1
                    and matches_for_id[0] not in exact_id_matches
                ):
                    exact_id_matches.append(matches_for_id[0])
            if exact_id_matches:
                overlapping_exact = [
                    work for work in hash_matches if work in exact_id_matches
                ]
                if 0 < len(overlapping_exact) < len(exact_id_matches):
                    reject_identity("source manifest has overlapping multi-work evidence")
                    continue
                id_match_ids = {id(work) for work in id_matches}
                exact_match_ids = {id(work) for work in exact_id_matches}
                overlapping_ids = {id(work) for work in overlapping_exact}
                if (
                    not overlapping_exact
                    or id_match_ids != exact_match_ids
                    or (overlapping_ids != exact_match_ids)
                ):
                    reject_identity(
                        "source manifest hash and exact-ID evidence does not identify the same "
                        "complete work set"
                    )
                    continue
                route_works = overlapping_exact
                if scoped_target_work_ids is not None:
                    catalog_target_ids = {
                        str(work["work_id"])
                        for work in works
                        if work["work_id"] in scoped_target_work_ids
                    }
                    matched_target_ids = {
                        str(work["work_id"])
                        for work in overlapping_exact
                        if work["work_id"] in scoped_target_work_ids
                    }
                    if catalog_target_ids - matched_target_ids:
                        raise ValueError(
                            "selected source manifest does not bind every explicit target work ID: "
                            f"{manifest_path}"
                        )
                    route_works = [
                        work
                        for work in overlapping_exact
                        if work["work_id"] in scoped_target_work_ids
                    ]
                for work in sorted(route_works, key=lambda item: str(item["work_id"])):
                    candidate_path, validation_path = evidence_for(work)
                    _attach_reconstruction_route(
                        work,
                        manifest,
                        manifest_path,
                        sources_root,
                        association="source_hash+exact_id",
                        scope=scope_for(work, compare_hash_coverage=True),
                        verified=verified,
                        blocker=blocker,
                        candidate_path=candidate_path,
                        validation_path=validation_path,
                        provenance_gap=provenance_gap_for(work),
                        manifest_verified=verified,
                        verified_reviews=verified_reviews,
                    )
                continue

        if hash_matches:
            if len(hash_matches) > 1:
                reject_identity("source manifest hash association is ambiguous")
                continue
            if (
                scoped_target_work_ids is not None
                and hash_matches[0]["work_id"] not in scoped_target_work_ids
            ):
                unassociated["verified" if verified else "blocked"] += 1
                continue
            candidate_path, validation_path = evidence_for(hash_matches[0])
            _attach_reconstruction_route(
                hash_matches[0],
                manifest,
                manifest_path,
                sources_root,
                association="source_hash",
                scope=scope_for(hash_matches[0], compare_hash_coverage=True),
                verified=verified,
                blocker=blocker,
                candidate_path=candidate_path,
                validation_path=validation_path,
                provenance_gap=provenance_gap_for(hash_matches[0]),
                manifest_verified=verified,
                verified_reviews=verified_reviews,
            )
            continue

        if id_matches:
            if manifest.get("catalog_claim_lineage") is not None:
                if len(id_matches) != 1:
                    raise ValueError(
                        "catalog claim lineage must identify exactly one WorkCatalog work: "
                        f"{manifest_path}"
                    )
                lineage_work = id_matches[0]
                if (
                    scoped_target_work_ids is not None
                    and lineage_work["work_id"] not in scoped_target_work_ids
                ):
                    unassociated["verified" if verified else "blocked"] += 1
                    continue
                _verify_catalog_claim_lineage(
                    manifest, lineage_work, manifest_hashes, data_root
                )
                candidate_path, validation_path = evidence_for(lineage_work)
                _attach_reconstruction_route(
                    lineage_work,
                    manifest,
                    manifest_path,
                    sources_root,
                    association="catalog_claim_lineage+exact_id",
                    scope=scope_for(lineage_work, compare_hash_coverage=False),
                    verified=verified,
                    blocker=blocker,
                    candidate_path=candidate_path,
                    validation_path=validation_path,
                    provenance_gap=provenance_gap_for(lineage_work),
                    manifest_verified=verified,
                    verified_reviews=verified_reviews,
                )
                continue
            for identifier, matches in id_matches_by_identifier:
                if len(matches) <= 1:
                    continue
                raise ValueError(
                    f"source manifest exact-ID association is ambiguous for {identifier!r}: "
                    f"{manifest_path}"
                )
            for work in id_matches:
                if (
                    scoped_target_work_ids is not None
                    and work["work_id"] not in scoped_target_work_ids
                ):
                    continue
                candidate_path, validation_path = evidence_for(work)
                _attach_reconstruction_route(
                    work,
                    manifest,
                    manifest_path,
                    sources_root,
                    association="exact_id",
                    scope=scope_for(work, compare_hash_coverage=False),
                    verified=False,
                    blocker=unverified_blocker(blocker),
                    candidate_path=candidate_path,
                    validation_path=validation_path,
                    provenance_gap=provenance_gap_for(work),
                    manifest_verified=verified,
                    verified_reviews=verified_reviews,
                )
            continue

        manifest_slug = _identity_slug(
            manifest_path.name.removesuffix(".source-manifest.json")
        )
        slug_matches = []
        for work in works:
            work_slugs = {
                _identity_slug(work["work_id"]),
                _identity_slug(work["title"]),
                *(_identity_slug(identifier) for identifier in work["resource_ids"]),
            }
            if manifest_slug in work_slugs:
                slug_matches.append(work)
        if len(slug_matches) > 1:
            raise ValueError(
                f"source manifest slug association is ambiguous for {manifest_slug!r}: "
                f"{manifest_path}"
            )
        if slug_matches:
            if (
                scoped_target_work_ids is not None
                and slug_matches[0]["work_id"] not in scoped_target_work_ids
            ):
                unassociated["verified" if verified else "blocked"] += 1
                continue
            candidate_path, validation_path = evidence_for(slug_matches[0])
            _attach_reconstruction_route(
                slug_matches[0],
                manifest,
                manifest_path,
                sources_root,
                association="slug",
                scope="partial" if declared_partial else "work",
                verified=False,
                blocker=unverified_blocker(blocker),
                candidate_path=candidate_path,
                validation_path=validation_path,
                provenance_gap=provenance_gap_for(slug_matches[0]),
                manifest_verified=verified,
                verified_reviews=verified_reviews,
            )
        else:
            admission_work_ids = _runtime_admission_work_ids(
                reconstruction_evidence, manifest_source_id
            )
            if len(admission_work_ids) > 1:
                raise ValueError(
                    "runtime source admission is ambiguous for source manifest: "
                    f"{manifest_path}"
                )
            if admission_work_ids:
                admission_work_id = admission_work_ids[0]
                candidate_path, validation_path = evidence_for_key(
                    (manifest_source_id, admission_work_id)
                )
                if (
                    verified
                    and source_manifest_object is not None
                    and candidate_path is not None
                    and validation_path is not None
                ):
                    identity = _runtime_policy_identity(
                        source_manifest_object,
                        manifest,
                        manifest_path,
                        sources_root,
                        work_id=admission_work_id,
                    )
                    member = identity.get("member")
                    admitted_work = _append_runtime_admission_work(
                        works,
                        identity,
                        allow_existing_cohort=isinstance(member, Mapping),
                    )
                    if member is not None:
                        expected_members = {
                            (item["part"], item["tcp_id"])
                            for item in member["expected_members"]
                        }
                        prior_members = [
                            route.get("member")
                            for route in admitted_work["reconstruction_state"].get(
                                "routes", []
                            )
                            if isinstance(route.get("member"), Mapping)
                        ]
                        if any(
                            {
                                (item["part"], item["tcp_id"])
                                for item in prior["expected_members"]
                            }
                            != expected_members
                            for prior in prior_members
                        ):
                            raise ValueError(
                                "runtime source admission identity-resolution member set conflicts for "
                                f"WorkCatalog work {admission_work_id}"
                            )
                        duplicate_member = any(
                            isinstance(route.get("member"), Mapping)
                            and route["member"].get("part") == member.get("part")
                            for route in admitted_work["reconstruction_state"].get(
                                "routes", []
                            )
                        )
                        if duplicate_member:
                            raise ValueError(
                                "runtime source admission physical part is duplicated for "
                                f"WorkCatalog work {admission_work_id}"
                            )
                    _attach_reconstruction_route(
                        admitted_work,
                        manifest,
                        manifest_path,
                        sources_root,
                        association="runtime_source_admission",
                        scope=(
                            "partial"
                            if declared_partial or identity["scope"] == "partial"
                            else "work"
                        ),
                        verified=verified,
                        blocker=blocker,
                        candidate_path=candidate_path,
                        validation_path=validation_path,
                        provenance_gap=(),
                        manifest_verified=verified,
                        member=member,
                        verified_reviews=verified_reviews,
                    )
                    continue
            unassociated["verified" if verified else "blocked"] += 1
    for work in works:
        runtime_routes = [
            route
            for route in work["reconstruction_state"].get("routes", [])
            if route.get("association") == "runtime_source_admission"
            and isinstance(route.get("member"), Mapping)
        ]
        if not runtime_routes:
            continue
        expected = {
            (item["part"], item["tcp_id"])
            for item in runtime_routes[0]["member"].get("expected_members", [])
        }
        observed = {
            (route["member"].get("part"), route["member"].get("tcp_id"))
            for route in runtime_routes
        }
        if observed != expected:
            raise ValueError(
                "runtime source admission cohort is missing an expected physical member for "
                f"WorkCatalog work {work['work_id']}"
            )
    supplied_evidence = set(reconstruction_evidence or {})
    unbound_evidence = sorted(supplied_evidence - set(evidence_uses))
    if unbound_evidence:
        raise ValueError(
            "reconstruction evidence does not bind an exact source/work route: "
            + ", ".join(
                f"{source_id}--{work_id}" for source_id, work_id in unbound_evidence
            )
        )
    multiply_bound = sorted(key for key, count in evidence_uses.items() if count != 1)
    if multiply_bound:
        raise ValueError(
            "reconstruction evidence binds more than one route: "
            + ", ".join(
                f"{source_id}--{work_id}" for source_id, work_id in multiply_bound
            )
        )
    if retained_witness_scope is not None:
        target_pairs = set(reconstruction_evidence or {})
        for source_id, manifest, config_records in scoped_manifest_configs:
            target_work_ids = {
                work_id
                for evidence_source_id, work_id in target_pairs
                if evidence_source_id == source_id
            }
            if not target_work_ids:
                continue
            selected_configs = _selected_retained_witness_configs(
                manifest,
                config_records,
                works,
                target_work_ids,
                sources_root.parent,
            )
            for config_path, scope in selected_configs.items():
                if config_path in retained_witness_scope:
                    raise ValueError(
                        "selected retained config is declared by multiple evidence-bound manifests: "
                        f"{config_path}"
                    )
                retained_witness_scope[config_path] = scope
    return dict(sorted(unassociated.items()))


@dataclass(frozen=True)
class WorkCatalog:
    summary: dict[str, Any]
    works: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "methodology": {
                "public_inventory_unit": (
                    "Recognized title-level work units: the title a reader, library, citation, "
                    "or source catalog would treat as the work present in the corpus. Exported "
                    "records, verses, dictionary entries, topics, Q&A pairs, chapters, and "
                    "quotations are subordinate units."
                ),
                "special_rules": [
                    "Files with the same category, title, and author are one work unit, even if split by volume.",
                    "Church Fathers verse-reference quotations are one source-collection unit, not one work per quoted author.",
                    "The historical-language lexicon is an auxiliary project tool, not a work or content category.",
                    "NSH OCR/reconciliation artifacts under data/reference/schaff/encyclopedia/1908-1914 are out of dataset-side public inventory scope.",
                    "Rows with missing or slug-derived titles are kept but flagged for bibliographic review.",
                ],
            },
            "summary": self.summary,
            "works": self.works,
        }


def catalog_identity_snapshot(catalog: WorkCatalog) -> dict[str, Any]:
    """Return the compact machine-readable identity surface for catalog consumers."""

    return {
        "identity": "work-catalog-identity-v1",
        "works": [
            {
                "author": work.get("author") or "",
                "category": work["category"],
                "category_label": work["category_label"],
                "file_count": work["file_count"],
                "resource_ids": work["resource_ids"],
                "schema_types": work["schema_types"],
                "source_paths": work["source_paths"],
                "title": work["title"],
                "work_id": work["work_id"],
            }
            for work in catalog.works
        ],
    }


def serialize_catalog_identity(catalog: WorkCatalog) -> bytes:
    """Serialize the compact identity surface deterministically with LF endings."""

    return (
        json.dumps(
            catalog_identity_snapshot(catalog),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _resource_paths(data_root: Path) -> Iterable[Path]:
    for path in sorted(data_root.rglob("*.json")):
        if _is_catalog_resource_path(path, data_root):
            yield path


def _is_catalog_resource_path(path: Path, data_root: Path) -> bool:
    try:
        rel_parts = path.relative_to(data_root).parts
    except ValueError:
        return False
    if not rel_parts:
        return False
    if rel_parts[0] in {"authors", "lexicon"}:
        return False
    if rel_parts[: len(NSH_REFERENCE_PREFIX)] == NSH_REFERENCE_PREFIX:
        return False
    if path.name.startswith("_") or path.name == "catalog.json":
        return False
    return path.suffix.casefold() == ".json"


def _clean_str(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _normal_key(value: Any) -> str:
    text = _clean_str(value)
    if text is None:
        return ""
    return " ".join(text.casefold().replace("_", " ").replace("-", " ").split())


def _identity_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "unknown"


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _clean_str(value)
        if text is not None:
            return text
    return None


def _data_payload(record: Mapping[str, Any]) -> Any:
    if "data" in record:
        return record.get("data")
    if "blocks" in record:
        return record.get("blocks")
    return None


def _top_level_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        return 1
    return 0


def _leaf_count(value: Any) -> int:
    if isinstance(value, list):
        primitive_text = sum(1 for item in value if _clean_str(item) is not None)
        return primitive_text + sum(
            _leaf_count(item) for item in value if isinstance(item, (dict, list))
        )
    if not isinstance(value, dict):
        return 0

    count = 0
    direct_text_keys = {
        "text",
        "commentary_text",
        "verse_text",
        "question",
        "answer",
        "quote",
        "term",
    }
    for key in direct_text_keys:
        if _clean_str(value.get(key)) is not None:
            count += 1
    for key, item in value.items():
        if (
            key not in direct_text_keys
            and isinstance(item, str)
            and key.endswith("_text")
            and _clean_str(item) is not None
        ):
            count += 1
    for child_key in (
        "data",
        "sections",
        "children",
        "units",
        "blocks",
        "entries",
        "subtopics",
        "content_blocks",
    ):
        child = value.get(child_key)
        if child is not None:
            count += _leaf_count(child)
    return count


def _legacy_hf_row_count(schema_type: str | None, payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return 0
    if schema_type == "structured_text":
        return _count_structured_text_blocks(payload)
    if schema_type == "doctrinal_document":
        return _count_doctrinal_document_leaves(payload)
    return 1


def _count_structured_text_blocks(data: Mapping[str, Any]) -> int:
    def walk(section: Mapping[str, Any]) -> int:
        count = len(section.get("content_blocks") or [])
        for child in section.get("children") or []:
            if isinstance(child, Mapping):
                count += walk(child)
        return count

    return sum(
        walk(section)
        for section in data.get("sections") or []
        if isinstance(section, Mapping)
    )


def _count_doctrinal_document_leaves(data: Mapping[str, Any]) -> int:
    def walk(unit: Mapping[str, Any]) -> int:
        children = unit.get("children") or []
        if children:
            return sum(walk(child) for child in children if isinstance(child, Mapping))
        return 1 if _clean_str(unit.get("content")) is not None else 0

    return sum(
        walk(unit) for unit in data.get("units") or [] if isinstance(unit, Mapping)
    )


def _metadata_fields(meta: Mapping[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, value in meta.items():
        if key == "provenance" and isinstance(value, Mapping):
            for subkey, subvalue in value.items():
                text = _serialise_metadata_value(subvalue)
                if text is not None:
                    fields[f"provenance.{subkey}"] = text
            continue
        text = _serialise_metadata_value(value)
        if text is not None:
            fields[key] = text
    return fields


def _serialise_metadata_value(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, list):
        items = [
            _serialise_metadata_value(item) or ""
            for item in value
            if item not in (None, "")
        ]
        items = [item for item in items if item]
        return ", ".join(items) if items else None
    if isinstance(value, Mapping):
        labelled = []
        for key, item in sorted(value.items()):
            text = _serialise_metadata_value(item)
            if text is not None:
                labelled.append(f"{key}: {text}")
        return "; ".join(labelled) if labelled else None
    return str(value)


def _publication_date_from_metas(
    category: str,
    metas: Iterable[Mapping[str, Any]],
    hymn_summary: Mapping[str, Any] | None,
) -> str:
    if category == "hymns" and hymn_summary is not None:
        year_range = hymn_summary.get("hymnal_year_range")
        if isinstance(year_range, str) and year_range:
            return f"Hymnal publication years {year_range}"

    explicit_values: list[str] = []
    source_edition_years: list[int] = []
    for meta in metas:
        for field in PUBLICATION_META_FIELDS:
            value = _metadata_text(meta.get(field))
            if value is not None and value not in explicit_values:
                explicit_values.append(value)
        provenance = (
            meta.get("provenance")
            if isinstance(meta.get("provenance"), Mapping)
            else {}
        )
        for field in PUBLICATION_PROVENANCE_FIELDS:
            value = _metadata_text(provenance.get(field))
            if value is not None and value not in explicit_values:
                explicit_values.append(value)
        source_edition = _clean_str(provenance.get("source_edition"))
        if source_edition is not None:
            source_edition_years.extend(_years_in_text(source_edition))
    if explicit_values:
        return _compact_values(explicit_values)
    if source_edition_years:
        return _format_years(source_edition_years)
    return ""


def _metadata_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (str, int, float, bool)):
        text = str(value).strip()
        return text if text else None
    return _serialise_metadata_value(value)


def _years_in_text(text: str) -> list[int]:
    years: list[int] = []
    for match in re.findall(r"\b(1[0-9]{3}|20[0-2][0-9])\b", text):
        year = int(match)
        if year <= 2026:
            years.append(year)
    return years


def _format_years(years: Iterable[int]) -> str:
    unique = sorted(set(years))
    if not unique:
        return ""
    if len(unique) == 1:
        return str(unique[0])
    return f"{unique[0]}-{unique[-1]}"


def _compact_values(values: Iterable[str]) -> str:
    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    if len(unique) <= 3:
        return "; ".join(unique)
    return f"{unique[0]}; {unique[1]}; {unique[2]}; +{len(unique) - 3} more"


def _hymn_summary(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, list):
        return None

    hymnal_years = [
        item.get("hymnal_year") for item in payload if isinstance(item, Mapping)
    ]
    hymnal_years = [year for year in hymnal_years if isinstance(year, int)]
    written_years = [
        item.get("year_written") for item in payload if isinstance(item, Mapping)
    ]
    written_years = [year for year in written_years if isinstance(year, int)]
    hymnal_titles = {
        title
        for item in payload
        if isinstance(item, Mapping)
        for title in [_clean_str(item.get("hymnal_title"))]
        if title is not None
    }
    languages = {
        language
        for item in payload
        if isinstance(item, Mapping)
        for language in [_clean_str(item.get("language"))]
        if language is not None
    }
    return {
        "hymn_entries": len(payload),
        "hymnal_year_known": len(hymnal_years),
        "hymnal_year_range": _format_years(hymnal_years),
        "year_written_known": len(written_years),
        "year_written_range": _format_years(written_years),
        "hymnal_titles": len(hymnal_titles),
        "languages": sorted(languages),
    }


def _combine_hymn_summaries(
    summaries: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    summaries = list(summaries)
    if not summaries:
        return None

    hymnal_years: list[int] = []
    written_years: list[int] = []
    languages: set[str] = set()
    for summary in summaries:
        hymnal_range = _clean_str(summary.get("hymnal_year_range"))
        if hymnal_range is not None:
            hymnal_years.extend(_years_in_text(hymnal_range))
        written_range = _clean_str(summary.get("year_written_range"))
        if written_range is not None:
            written_years.extend(_years_in_text(written_range))
        for language in summary.get("languages") or []:
            if isinstance(language, str):
                languages.add(language)

    return {
        "hymn_entries": sum(
            int(summary.get("hymn_entries") or 0) for summary in summaries
        ),
        "hymnal_year_known": sum(
            int(summary.get("hymnal_year_known") or 0) for summary in summaries
        ),
        "hymnal_year_range": _format_years(hymnal_years),
        "year_written_known": sum(
            int(summary.get("year_written_known") or 0) for summary in summaries
        ),
        "year_written_range": _format_years(written_years),
        "hymnal_titles": sum(
            int(summary.get("hymnal_titles") or 0) for summary in summaries
        ),
        "languages": sorted(languages),
    }


def _is_fixture_or_pipeline(record: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
    return "rendering_id" in record or meta.get("title") == "Fixture Work"


def _group_key(
    category: str, meta: Mapping[str, Any], path: Path
) -> tuple[str, str, str, str]:
    if category == "church-fathers":
        return (category, "church-fathers-quotations", "", "")
    title = _first_text(meta.get("title"))
    author = _first_text(meta.get("author"))
    if title is not None:
        return (category, _normal_key(title), _normal_key(author), "")
    resource_id = _first_text(meta.get("id"), path.stem) or path.stem
    return (category, "", "", resource_id)


def _public_title(
    category: str, metas: list[Mapping[str, Any]], fallback_id: str
) -> str:
    if category == "church-fathers":
        return "Church Fathers verse-reference quotations"
    for meta in metas:
        title = _clean_str(meta.get("title"))
        if title is not None:
            return title
    return fallback_id


def _public_author(category: str, authors: set[str]) -> str | None:
    if category == "church-fathers":
        return "Various authors"
    if not authors:
        return None
    if len(authors) == 1:
        return next(iter(authors))
    return "Various contributors"


def _audit_flags(
    category: str, title: str, author: str | None, metas: list[Mapping[str, Any]]
) -> list[str]:
    flags: set[str] = set()
    if category != "church-fathers":
        if not any(_clean_str(meta.get("title")) for meta in metas):
            flags.add("missing_title")
        if author is None:
            flags.add("missing_author")
    if title in {str(meta.get("id")) for meta in metas if meta.get("id")}:
        flags.add("title_looks_like_internal_id")
    if "missing_title" in flags or "title_looks_like_internal_id" in flags:
        flags.add("needs_bibliographic_review")
    if any(str(meta.get("id")) in OFFICIAL_TITLE_REVIEW_RESOURCE_IDS for meta in metas):
        flags.add("official_title_unconfirmed")
        flags.add("needs_bibliographic_review")
    if not any(
        _clean_str((meta.get("provenance") or {}).get("source_edition"))
        for meta in metas
    ):
        flags.add("missing_source_edition")
    return sorted(flags)


def collect_work_catalog(
    data_root: Path = DATA_ROOT,
    *,
    reconstruction_evidence: Mapping[tuple[str, str], tuple[Path | str, Path | str]]
    | None = None,
    source_manifest_allowlist: Iterable[str | Path] | None = None,
    data_resource_allowlist: Iterable[str | Path] | None = None,
) -> WorkCatalog:
    sources_root = data_root.parent / "sources"
    selected_manifest_paths = None
    selected_resource_paths = None
    if (source_manifest_allowlist is None) != (data_resource_allowlist is None):
        raise ValueError(
            "bounded WorkCatalog route binding requires both source manifest and data resource allowlists"
        )
    if source_manifest_allowlist is not None:
        data_root, selected_resource_paths = _resolve_data_resource_allowlist(
            data_root,
            data_resource_allowlist or (),
        )
        sources_root = data_root.parent / "sources"
        sources_root, selected_manifest_paths = _resolve_source_manifest_allowlist(
            sources_root,
            source_manifest_allowlist,
        )

    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    skipped = Counter()

    resource_paths = (
        selected_resource_paths
        if selected_resource_paths is not None
        else _resource_paths(data_root)
    )
    for path in resource_paths:
        raw = _load_json(path)
        if not isinstance(raw, Mapping):
            skipped["invalid_json_or_shape"] += 1
            continue
        meta = raw.get("meta") if isinstance(raw.get("meta"), Mapping) else {}
        if _is_fixture_or_pipeline(raw, meta):
            skipped["fixture_or_pipeline"] += 1
            continue

        rel = path.relative_to(data_root)
        category = (
            "topical-reference"
            if meta.get("schema_type") == "topical_reference"
            else rel.parts[0]
        )
        key = _group_key(category, meta, path)
        group = groups.setdefault(
            key,
            {
                "category": category,
                "paths": [],
                "metas": [],
                "metadata_fields": defaultdict(list),
                "resource_ids": set(),
                "authors": set(),
                "schema_types": set(),
                "hymn_summaries": [],
                "top_level_records": 0,
                "leaf_records": 0,
                "legacy_hf_export_records": 0,
            },
        )
        group["paths"].append(rel.as_posix())
        group["metas"].append(meta)
        resource_id = _clean_str(meta.get("id"))
        if resource_id is not None:
            group["resource_ids"].add(resource_id)
        author = _clean_str(meta.get("author"))
        if author is not None:
            group["authors"].add(author)
        schema_type = _clean_str(meta.get("schema_type"))
        if schema_type is not None:
            group["schema_types"].add(schema_type)
        payload = _data_payload(raw)
        group["top_level_records"] += _top_level_count(payload)
        group["leaf_records"] += _leaf_count(payload)
        group["legacy_hf_export_records"] += _legacy_hf_row_count(schema_type, payload)
        if category == "hymns":
            hymn_summary = _hymn_summary(payload)
            if hymn_summary is not None:
                group["hymn_summaries"].append(hymn_summary)
        for field, value in _metadata_fields(meta).items():
            if value not in group["metadata_fields"][field]:
                group["metadata_fields"][field].append(value)

    works: list[dict[str, Any]] = []
    for key, group in groups.items():
        category = group["category"]
        resource_ids = sorted(group["resource_ids"])
        fallback_id = resource_ids[0] if resource_ids else key[-1]
        work_id = (
            "church-fathers-quotations" if category == "church-fathers" else fallback_id
        )
        title = _public_title(category, group["metas"], fallback_id)
        author = _public_author(category, group["authors"])
        hymn_summary = _combine_hymn_summaries(group["hymn_summaries"])
        flags = _audit_flags(category, title, author, group["metas"])
        works.append(
            {
                "work_id": work_id,
                "category": category,
                "category_label": CATEGORY_LABELS.get(category, category),
                "title": title,
                "author": author,
                "publication_date": _publication_date_from_metas(
                    category, group["metas"], hymn_summary
                ),
                "author_count": len(group["authors"]),
                "schema_types": sorted(group["schema_types"]),
                "resource_ids": resource_ids,
                "source_paths": sorted(group["paths"]),
                "file_count": len(group["paths"]),
                "top_level_records": group["top_level_records"],
                "leaf_records": group["leaf_records"],
                "legacy_hf_export_records": group["legacy_hf_export_records"],
                "hymn_summary": hymn_summary,
                "metadata_fields": {
                    field: sorted(values)
                    for field, values in sorted(group["metadata_fields"].items())
                },
                "audit_flags": flags,
                "reconstruction_state": _default_reconstruction_state(),
            }
        )

    work_id_counts = Counter(work["work_id"] for work in works)
    for work in works:
        if work_id_counts[work["work_id"]] > 1:
            authority = work["author"] or work["title"]
            work["work_id"] = f"{work['work_id']}--{_identity_slug(authority)}"
    resolved_work_ids = [work["work_id"] for work in works]
    if len(resolved_work_ids) != len(set(resolved_work_ids)):
        raise ValueError("work catalog cannot derive unique work identities")

    runtime_evidence = dict(reconstruction_evidence or {})
    retained_witness_scope = (
        None if source_manifest_allowlist is None else {}
    )
    if retained_witness_scope is None:
        _attach_retained_witness_gaps(works, data_root.parent)
    unassociated_manifests = _bind_reconstruction_routes(
        works,
        sources_root,
        data_root,
        reconstruction_evidence=runtime_evidence,
        manifest_paths=selected_manifest_paths,
        retained_witness_scope=retained_witness_scope,
    )
    if retained_witness_scope is not None:
        _attach_retained_witness_gaps(
            works,
            data_root.parent,
            selected_configs=retained_witness_scope,
        )

    works.sort(
        key=lambda work: (work["category_label"], work["title"], work["work_id"])
    )
    category_counts = Counter(work["category"] for work in works)
    category_records = Counter()
    category_leaf_records = Counter()
    category_files = Counter()
    legacy_hf_records = Counter()
    for work in works:
        category = work["category"]
        category_records[category] += work["top_level_records"]
        category_leaf_records[category] += work["leaf_records"]
        category_files[category] += work["file_count"]
        for schema_type in work["schema_types"]:
            legacy_hf_records[schema_type] += work["legacy_hf_export_records"]
    work_authors = {
        work["author"]
        for work in works
        if isinstance(work.get("author"), str)
        and work["author"] not in {"Various authors", "Various contributors"}
    }
    source_author_labels: set[str] = set()
    for work in works:
        for value in work["metadata_fields"].get("author", []):
            if value not in {"Various authors", "Various contributors"}:
                source_author_labels.add(value)
    summary = {
        "work_units": len(works),
        "authors": len(work_authors),
        "source_author_labels": len(source_author_labels),
        "files": sum(work["file_count"] for work in works),
        "top_level_records": sum(work["top_level_records"] for work in works),
        "leaf_records": sum(work["leaf_records"] for work in works),
        "legacy_hf_export_records": sum(
            work["legacy_hf_export_records"] for work in works
        ),
        "legacy_hf_export_records_by_schema": {
            schema_type: legacy_hf_records[schema_type]
            for schema_type in sorted(legacy_hf_records)
        },
        "works_by_category": {
            category: category_counts[category] for category in sorted(category_counts)
        },
        "files_by_category": {
            category: category_files[category] for category in sorted(category_files)
        },
        "top_level_records_by_category": {
            category: category_records[category]
            for category in sorted(category_records)
        },
        "leaf_records_by_category": {
            category: category_leaf_records[category]
            for category in sorted(category_leaf_records)
        },
        "works_with_audit_flags": sum(1 for work in works if work["audit_flags"]),
        "works_with_retained_witness_gaps": sum(
            1 for work in works if work["retained_witness_gaps"]
        ),
        "reconstruction_state_counts": _reconstruction_state_counts(
            works, unassociated_manifests
        ),
        "skipped": dict(sorted(skipped.items())),
    }
    return WorkCatalog(summary=summary, works=works)


def render_catalog_markdown(catalog: WorkCatalog) -> str:
    payload = catalog.to_dict()
    summary = payload["summary"]
    lines = [
        "# Open Christian Data Work Catalog",
        "",
        "This catalog counts the public inventory by recognized title-level work units. Exported records are counted separately.",
        "",
        "## Summary",
        "",
        f"- Work units: {summary['work_units']}",
        f"- Authors: {summary['authors']}",
        f"- Source files: {summary['files']}",
        f"- Top-level export/source records: {summary['top_level_records']}",
        f"- Legacy HuggingFace JSONL rows: {summary['legacy_hf_export_records']}",
        f"- Leaf text units: {summary['leaf_records']}",
        f"- Work units with audit flags: {summary['works_with_audit_flags']}",
        (
            "- Work units with retained witnesses missing from parser provenance: "
            f"{summary['works_with_retained_witness_gaps']}"
        ),
        (
            "- Reconstruction: "
            f"{summary['reconstruction_state_counts']['retained_source'].get('manifest_bound', 0)} "
            "work units are fully manifest-bound; "
            f"{summary['reconstruction_state_counts']['retained_source'].get('manifest_bound_partial', 0)} "
            "are partially manifest-bound; "
            f"{summary['reconstruction_state_counts']['manifest_verification'].get('verified', 0)} "
            "manifests verify; "
            f"{summary['reconstruction_state_counts']['manifest_verification'].get('blocked', 0)} "
            "manifests are blocked; "
            f"{summary['reconstruction_state_counts']['routes']} routes are indexed"
        ),
        (
            "- Unassociated reconstruction manifests: "
            f"{sum(summary['reconstruction_state_counts']['unassociated_manifests'].values())}"
        ),
        "",
        "## Categories",
        "",
        "| Category | Work units |",
        "|---|---:|",
    ]
    for category, count in summary["works_by_category"].items():
        lines.append(f"| {CATEGORY_LABELS.get(category, category)} | {count} |")
    lines.extend(
        [
            "",
            "## Work Metadata Audit",
            "",
            "| Category | Title | Author | Publication date | Files | Records | Reconstruction | Audit flags |",
            "|---|---|---|---|---:|---:|---|---|",
        ]
    )
    for work in catalog.works:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(work["category_label"]),
                    _md_cell(work["title"]),
                    _md_cell(work.get("author") or ""),
                    _md_cell(work.get("publication_date") or ""),
                    str(work["file_count"]),
                    str(work["top_level_records"]),
                    _md_cell(_reconstruction_state_text(work)),
                    _md_cell(", ".join(work["audit_flags"])),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_catalog_html(catalog: WorkCatalog) -> str:
    summary = catalog.summary
    rows = []
    for work in catalog.works:
        flags = ", ".join(work["audit_flags"])
        rows.append(
            "<tr>"
            f"<td>{_h(work['category_label'])}</td>"
            f"<td>{_h(work['title'])}</td>"
            f"<td>{_h(work.get('author') or '')}</td>"
            f"<td>{_h(work.get('publication_date') or '')}</td>"
            f"<td>{work['file_count']}</td>"
            f"<td>{work['top_level_records']}</td>"
            f"<td>{work['leaf_records']}</td>"
            f"<td>{_h(_reconstruction_state_text(work))}</td>"
            f"<td>{_h(flags)}</td>"
            f"<td>{_render_metadata_details(work)}</td>"
            "</tr>"
        )
    hymn_panel = _render_hymn_panel(catalog.works)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Open Christian Data work catalog</title>"
        "<style>"
        "body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:24px;color:#1f2933;background:#fafafa}"
        "h1{font-size:28px;margin-bottom:8px} .summary{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0}"
        ".summary span{border:1px solid #c9d2dc;background:white;padding:8px 10px;border-radius:4px}"
        ".note{border-left:4px solid #577399;background:white;padding:12px 14px;margin:18px 0;max-width:980px}"
        "table{border-collapse:collapse;width:100%;background:white;font-size:14px}"
        "th,td{border:1px solid #d9e1e8;padding:7px;vertical-align:top;text-align:left}"
        "th{background:#edf2f7;position:sticky;top:0}"
        "dl.metadata{display:grid;grid-template-columns:minmax(150px,220px) minmax(260px,1fr);gap:4px 12px;margin:8px 0 0;max-width:780px}"
        "dl.metadata dt{font-weight:700;color:#334e68} dl.metadata dd{margin:0;overflow-wrap:anywhere}"
        "ul.compact{margin:0;padding-left:18px} .muted{color:#627d98}"
        "</style></head><body><main>"
        "<h1>Open Christian Data work catalog</h1>"
        "<p>Public inventory is counted by recognized title-level work units. Export rows and leaf text units are secondary technical counts.</p>"
        '<div class="summary">'
        f"<span>Work units: <strong>{summary['work_units']}</strong></span>"
        f"<span>Authors: <strong>{summary['authors']}</strong></span>"
        f"<span>Files: <strong>{summary['files']}</strong></span>"
        f"<span>Top-level records: <strong>{summary['top_level_records']}</strong></span>"
        f"<span>HF JSONL rows: <strong>{summary['legacy_hf_export_records']}</strong></span>"
        f"<span>Leaf text units: <strong>{summary['leaf_records']}</strong></span>"
        f"<span>Flagged works: <strong>{summary['works_with_audit_flags']}</strong></span>"
        f"<span>Retained witness gaps: <strong>{summary['works_with_retained_witness_gaps']}</strong></span>"
        f"<span>Fully manifest-bound works: <strong>{summary['reconstruction_state_counts']['retained_source'].get('manifest_bound', 0)}</strong></span>"
        f"<span>Partially manifest-bound works: <strong>{summary['reconstruction_state_counts']['retained_source'].get('manifest_bound_partial', 0)}</strong></span>"
        f"<span>Verified manifests: <strong>{summary['reconstruction_state_counts']['manifest_verification'].get('verified', 0)}</strong></span>"
        f"<span>Blocked manifests: <strong>{summary['reconstruction_state_counts']['manifest_verification'].get('blocked', 0)}</strong></span>"
        f"<span>Reconstruction routes: <strong>{summary['reconstruction_state_counts']['routes']}</strong></span>"
        f"<span>Unassociated reconstruction manifests: <strong>{sum(summary['reconstruction_state_counts']['unassociated_manifests'].values())}</strong></span>"
        "</div>"
        f"{hymn_panel}"
        "<table><thead><tr><th>Category</th><th>Title</th><th>Author</th><th>Publication date</th><th>Files</th><th>Records</th><th>Leaf units</th><th>Reconstruction</th><th>Audit flags</th><th>Metadata fields</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</main></body></html>\n"
    )


def _render_hymn_panel(works: Iterable[Mapping[str, Any]]) -> str:
    hymn_works = [
        work
        for work in works
        if work.get("category") == "hymns" and work.get("hymn_summary")
    ]
    if not hymn_works:
        return ""
    panels = []
    for work in hymn_works:
        summary = work["hymn_summary"]
        panels.append(
            '<div class="note">'
            f"<strong>Hymn collection coverage:</strong> {_h(work['title'])} contains "
            f"{_h(_format_number(summary['hymn_entries']))} hymn entries. "
            f"Hymnal publication years: {_h(summary.get('hymnal_year_range') or 'unknown')} "
            f"({_h(_format_number(summary.get('hymnal_year_known') or 0))} known). "
            f"Hymn-written years: {_h(summary.get('year_written_range') or 'unknown')} "
            f"({_h(_format_number(summary.get('year_written_known') or 0))} known). "
            f"Distinct hymnal titles: {_h(_format_number(summary.get('hymnal_titles') or 0))}. "
            "Hymns are reviewed as a collection here; individual hymn rows belong in a dedicated hymn view."
            "</div>"
        )
    return "".join(panels)


def _render_metadata_details(work: Mapping[str, Any]) -> str:
    rows = _metadata_display_rows(work)
    if not rows:
        return '<span class="muted">No metadata fields</span>'
    rendered = []
    for label, values in rows:
        rendered.append(
            f"<dt>{_h(label)}</dt><dd>{_render_metadata_values(values)}</dd>"
        )
    return (
        "<details><summary>View fields</summary>"
        f'<dl class="metadata">{"".join(rendered)}</dl>'
        "</details>"
    )


def _metadata_display_rows(work: Mapping[str, Any]) -> list[tuple[str, list[str]]]:
    fields = work["metadata_fields"]
    ordered_keys = [key for key in METADATA_FIELD_ORDER if key in fields]
    remaining_keys = sorted(key for key in fields if key not in ordered_keys)
    rows = []
    for key in ordered_keys + remaining_keys:
        label = METADATA_LABELS.get(key, _humanise_field_name(key))
        values = [str(value) for value in fields[key] if str(value)]
        if values:
            rows.append((label, _limit_values(values)))
    if work.get("resource_ids"):
        rows.append(
            (
                "Resource IDs in work unit",
                _limit_values([str(value) for value in work["resource_ids"]]),
            )
        )
    if work.get("source_paths"):
        rows.append(
            (
                "Source files",
                _limit_values([str(value) for value in work["source_paths"]]),
            )
        )
    for gap in work.get("retained_witness_gaps", []):
        rows.append(
            (
                "Retained witness provenance gap",
                [
                    (
                        f"{gap['retained_path']}: "
                        f"{gap['missing_from_parser_provenance']} of "
                        f"{gap['member_count']} retained members missing; "
                        f"evidence {gap['evidence']}; {gap['verification']}"
                    )
                ],
            )
        )
    return rows


def _render_metadata_values(values: list[str]) -> str:
    if len(values) == 1:
        return _h(values[0])
    return (
        '<ul class="compact">'
        + "".join(f"<li>{_h(value)}</li>" for value in values)
        + "</ul>"
    )


def _humanise_field_name(key: str) -> str:
    return key.replace("provenance.", "Provenance: ").replace("_", " ").capitalize()


def _format_number(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _limit_values(values: list[str], limit: int = 12) -> list[str]:
    if len(values) <= limit:
        return values
    return values[:limit] + [f"+ {len(values) - limit} more"]


def _h(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def write_outputs(
    catalog: WorkCatalog,
    json_out: Path,
    md_out: Path,
    html_out: Path,
    identity_out: Path | None = None,
) -> None:
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    html_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(
        json.dumps(catalog.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    md_out.write_text(render_catalog_markdown(catalog), encoding="utf-8", newline="\n")
    html_out.write_text(render_catalog_html(catalog), encoding="utf-8", newline="\n")
    if identity_out is not None:
        identity_out.parent.mkdir(parents=True, exist_ok=True)
        identity_out.write_bytes(serialize_catalog_identity(catalog))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Count OCD records and build an author/work-led catalog."
    )
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD_OUT)
    parser.add_argument("--html-out", type=Path, default=DEFAULT_HTML_OUT)
    parser.add_argument(
        "--identity-out",
        type=Path,
        help="Optional compact machine-readable catalog identity snapshot.",
    )
    parser.add_argument(
        "--reconstruction-evidence",
        action="append",
        nargs=4,
        metavar=("SOURCE_ID", "WORK_ID", "CANDIDATE_PATH", "VALIDATION_PATH"),
        help=(
            "Repeatable caller-selected source/work candidate and validation evidence pair; "
            "CANDIDATE_PATH is the flat candidate package directory (not its parent); "
            "paths are runtime inputs and are not retained as a registry. "
            "A source-only route is admitted only from a verified SourceManifest policy "
            "identity, and multi-part identities require explicit source-local member evidence."
        ),
    )
    parser.add_argument(
        "--source-manifest-allowlist",
        action="append",
        metavar="REPOSITORY_RELATIVE_PATH",
        help=(
            "Repeatable repository-relative path under sources/; when supplied, only these "
            "source manifests are opened for route binding. Absolute paths, traversal, "
            "duplicates, and paths outside sources/ are rejected."
        ),
    )
    parser.add_argument(
        "--data-resource-allowlist",
        action="append",
        metavar="REPOSITORY_RELATIVE_PATH",
        help=(
            "Repeatable repository-relative JSON path under data/; when route allowlists are "
            "supplied, only these catalog records are read. Pair with "
            "--source-manifest-allowlist. Absolute paths, traversal, duplicates, and paths "
            "outside data/ are rejected."
        ),
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the summary without writing reports.",
    )
    return parser


def historical_main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    reconstruction_evidence: dict[tuple[str, str], tuple[Path, Path]] = {}
    for source_id, work_id, candidate_path, validation_path in (
        args.reconstruction_evidence or []
    ):
        key = (source_id, work_id)
        if key in reconstruction_evidence:
            parser.error(
                f"reconstruction evidence was supplied more than once for {source_id}--{work_id}"
            )
        reconstruction_evidence[key] = (Path(candidate_path), Path(validation_path))
    if (args.source_manifest_allowlist is None) != (
        args.data_resource_allowlist is None
    ):
        parser.error(
            "bounded route binding requires both --source-manifest-allowlist and --data-resource-allowlist"
        )
    if args.source_manifest_allowlist is not None:
        try:
            _resolve_source_manifest_allowlist(
                args.data_root.parent / "sources",
                args.source_manifest_allowlist,
            )
            _resolve_data_resource_allowlist(
                args.data_root,
                args.data_resource_allowlist or (),
            )
        except ValueError as exc:
            parser.error(str(exc))
    catalog = collect_work_catalog(
        args.data_root,
        reconstruction_evidence=reconstruction_evidence,
        source_manifest_allowlist=args.source_manifest_allowlist,
        data_resource_allowlist=args.data_resource_allowlist,
    )
    if not args.no_write:
        write_outputs(
            catalog, args.json_out, args.md_out, args.html_out, args.identity_out
        )
    print(json.dumps(catalog.summary, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Count verified release rows; retain explicit historical catalog diagnostics."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if '--legacy-catalog' in arguments:
        arguments.remove('--legacy-catalog')
        return historical_main(arguments)
    from build.tools.report_release_stats import main as verified_main
    return verified_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
