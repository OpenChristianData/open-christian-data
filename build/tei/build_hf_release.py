"""Assemble an explicitly selected accepted TEI release for offline review."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from build.lib.paths import REPO_ROOT
from build.tei.check_ledger import check_receipt
from build.tei.project_hf import GENERATOR, project_file
from ocd_kernel.lib.git_artifact import repository_revision
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.decision import catalog_decision
from ocd_kernel.tei.projection_profile import PROFILE_ID


SELECTION_CONTRACT = "ocd-tei-hf-release-selection-v1"
MANIFEST_CONTRACT = "ocd-tei-hf-release-manifest-v1"
TOP_LEVEL_KEYS = frozenset(
    {
        "contract",
        "release_id",
        "config_name",
        "split",
        "language",
        "license_id",
        "release_timestamp",
        "publication",
        "items",
    }
)
PUBLICATION_KEYS = frozenset(
    {"authorized_by", "authorized_at", "attribution_reviewed", "rationale"}
)
ITEM_KEYS = frozenset(
    {
        "work_id",
        "rendering_id",
        "source_manifest_path",
        "candidate_path",
        "validation_path",
        "attribution_text",
    }
)
ID_PATTERN = re.compile(r"\A[a-z0-9][a-z0-9_-]*\Z")
UTC_TIMESTAMP_PATTERN = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z"
)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_strict_json(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        content = path.read_bytes()
        text = content.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"could not read selection as strict UTF-8: {exc}") from exc
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ValueError(f"selection is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("selection must be a JSON object")
    return value, content


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], name: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        raise ValueError(f"{name} has missing or unknown fields: missing={missing}, unknown={unknown}")


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    if value != value.strip():
        raise ValueError(f"{name} must not have leading or trailing whitespace")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError(f"{name} must be a single-line string")
    return value


def _identifier(value: object, name: str) -> str:
    result = _nonempty(value, name)
    if ID_PATTERN.fullmatch(result) is None:
        raise ValueError(f"{name} is not a lowercase safe identifier")
    return result


def _timestamp(value: object, name: str) -> str:
    result = _nonempty(value, name)
    if UTC_TIMESTAMP_PATTERN.fullmatch(result) is None:
        raise ValueError(f"{name} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(result[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 UTC timestamp ending in Z") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{name} must be an ISO-8601 UTC timestamp ending in Z")
    return result


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _resolve_source_manifest(raw: str, repository_root: Path) -> Path:
    supplied = Path(raw)
    if supplied.is_absolute():
        raise ValueError("source_manifest_path must be repository-relative")
    resolved = (repository_root / supplied).resolve(strict=True)
    try:
        resolved.relative_to(repository_root)
    except ValueError as exc:
        raise ValueError("source_manifest_path escapes repository root") from exc
    if not resolved.is_file():
        raise ValueError("source_manifest_path must name a file")
    return resolved


def _resolve_evidence(raw: str, name: str, *, directory: bool) -> Path:
    supplied = Path(raw)
    if not supplied.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    path = supplied.resolve(strict=True)
    if directory and not path.is_dir():
        raise ValueError(f"{name} must name a directory")
    if not directory and not path.is_file():
        raise ValueError(f"{name} must name a file")
    return path


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _protected_resolved_roots(repository_root: Path) -> tuple[Path, ...]:
    protected: list[Path] = []
    for name in ("data", "ir", "raw", "reports", "exports"):
        path = repository_root / name
        if path.exists():
            protected.append(path.resolve(strict=True))
    return tuple(protected)


def _destination_path(
    destination: Path,
    repository_root: Path,
    repository_lexical_root: Path,
) -> Path:
    if destination.exists():
        raise ValueError("destination must not exist")
    lexical = _lexical_absolute(destination)
    if _is_within(lexical, repository_lexical_root):
        raise ValueError("destination must be lexically outside repository root")
    parent = destination.parent.resolve(strict=True)
    resolved = parent / destination.name
    if _is_within(resolved, repository_root):
        raise ValueError("destination must be outside repository root")
    if any(_is_within(resolved, protected) for protected in _protected_resolved_roots(repository_root)):
        raise ValueError("destination must be outside protected canonical storage")
    return resolved


def _tei_version(repository_root: Path) -> str:
    path = repository_root / "ocd_kernel" / "tei" / "vendor" / "VERSION.txt"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"TEI P5 Version ([0-9]+(?:\.[0-9]+)+)", text)
    if match is None:
        raise ValueError("could not identify vendored TEI version")
    return match.group(1)


def _jsonl_rows(path: Path) -> int:
    count = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            raise ValueError(f"projected JSONL has a blank line at {line_number}")
        value = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(value, dict):
            raise ValueError(f"projected JSONL row {line_number} is not an object")
        count += 1
    if count == 0:
        raise ValueError("projected JSONL must contain at least one row")
    return count


def _public_file(path: Path, root: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256_bytes(content),
        "bytes": len(content),
    }


def _captured_candidate_tei(candidate: CandidatePackage) -> bytes:
    content = candidate.member_bytes("content.tei.xml")
    members = candidate.manifest.get("members")
    if not isinstance(members, (tuple, list)):
        raise ValueError("candidate member inventory is invalid")
    matches = [
        member
        for member in members
        if isinstance(member, Mapping) and member.get("name") == "content.tei.xml"
    ]
    if len(matches) != 1:
        raise ValueError("candidate content.tei.xml member binding is missing or ambiguous")
    binding = matches[0]
    if binding.get("bytes") != len(content) or binding.get("sha256") != _sha256_bytes(content):
        raise ValueError("captured content.tei.xml bytes do not match candidate member binding")
    return content


def _readme(selection: Mapping[str, object], items: list[dict[str, object]]) -> bytes:
    lines = [
        "---",
        f"license: {json.dumps(selection['license_id'], ensure_ascii=False)}",
        "language:",
        f"- {json.dumps(selection['language'], ensure_ascii=False)}",
        "configs:",
        f"- config_name: {json.dumps(selection['config_name'], ensure_ascii=False)}",
        "  data_files:",
        f"  - split: {json.dumps(selection['split'], ensure_ascii=False)}",
        '    path: "data/*.jsonl"',
        "---",
        "",
        f"# {selection['release_id']}",
        "",
        "This is an offline release candidate. The staged TEI files are the accepted",
        "text artifacts; the JSONL files are lossy clean-text projections with",
        "independently checked loss receipts.",
        "",
        f"Config: `{selection['config_name']}`. Split: `{selection['split']}`.",
        f"License declaration: `{selection['license_id']}`. Attribution reviewed: `true`.",
        "",
        "| Work | Rendering | Attribution |",
        "|---|---|---|",
    ]
    for item in items:
        attribution = str(item["attribution_text"]).replace("|", "\\|")
        lines.append(
            f"| `{item['work_id']}` | `{item['rendering_id']}` | {attribution} |"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _validated_selection(raw: dict[str, object]) -> dict[str, object]:
    _exact_keys(raw, TOP_LEVEL_KEYS, "selection")
    if raw["contract"] != SELECTION_CONTRACT:
        raise ValueError("selection contract mismatch")
    publication = raw["publication"]
    if not isinstance(publication, dict):
        raise ValueError("publication must be an object")
    _exact_keys(publication, PUBLICATION_KEYS, "publication")
    if publication["authorized_by"] != "project-maintainer":
        raise ValueError("publication authorized_by must be project-maintainer")
    if publication["attribution_reviewed"] is not True:
        raise ValueError("publication attribution_reviewed must be true")
    validated_publication = {
        "authorized_by": "project-maintainer",
        "authorized_at": _timestamp(publication["authorized_at"], "publication.authorized_at"),
        "attribution_reviewed": True,
        "rationale": _nonempty(publication["rationale"], "publication.rationale"),
    }
    items = raw["items"]
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a nonempty array")
    validated_items: list[dict[str, str]] = []
    identities: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{index}] must be an object")
        _exact_keys(item, ITEM_KEYS, f"items[{index}]")
        validated = {
            "work_id": _identifier(item["work_id"], f"items[{index}].work_id"),
            "rendering_id": _identifier(
                item["rendering_id"], f"items[{index}].rendering_id"
            ),
            "source_manifest_path": _nonempty(
                item["source_manifest_path"], f"items[{index}].source_manifest_path"
            ),
            "candidate_path": _nonempty(
                item["candidate_path"], f"items[{index}].candidate_path"
            ),
            "validation_path": _nonempty(
                item["validation_path"], f"items[{index}].validation_path"
            ),
            "attribution_text": _nonempty(
                item["attribution_text"], f"items[{index}].attribution_text"
            ),
        }
        identity = (validated["work_id"], validated["rendering_id"])
        if identity in identities:
            raise ValueError("duplicate work_id/rendering_id selection")
        identities.add(identity)
        validated_items.append(validated)
    return {
        "contract": SELECTION_CONTRACT,
        "release_id": _identifier(raw["release_id"], "release_id"),
        "config_name": _identifier(raw["config_name"], "config_name"),
        "split": _identifier(raw["split"], "split"),
        "language": _nonempty(raw["language"], "language"),
        "license_id": _nonempty(raw["license_id"], "license_id"),
        "release_timestamp": _timestamp(raw["release_timestamp"], "release_timestamp"),
        "publication": validated_publication,
        "items": validated_items,
    }


def build_release(
    selection_path: str | Path,
    destination: str | Path,
    *,
    repository_root: str | Path = REPO_ROOT,
) -> dict[str, object]:
    """Build one fresh offline release and return its public manifest."""

    repository_lexical_root = _lexical_absolute(Path(repository_root))
    root = Path(repository_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repository_root must be a directory")
    selection_file = Path(selection_path).resolve(strict=True)
    raw_selection, selection_bytes = _load_strict_json(selection_file)
    selection = _validated_selection(raw_selection)
    if selection["language"] != "en" or selection["license_id"] != "cc0-1.0":
        raise ValueError("v1 release profile requires language en and license_id cc0-1.0")
    target = _destination_path(Path(destination), root, repository_lexical_root)
    revision = repository_revision(root)
    tei_version = _tei_version(root)

    prepared_items: list[dict[str, object]] = []
    evidence_paths: set[Path] = set()
    selected_items = selection["items"]
    assert isinstance(selected_items, list)
    for item in selected_items:
        assert isinstance(item, dict)
        work_id = str(item["work_id"])
        rendering_id = str(item["rendering_id"])
        source_path = _resolve_source_manifest(str(item["source_manifest_path"]), root)
        candidate_path = _resolve_evidence(
            str(item["candidate_path"]), "candidate_path", directory=True
        )
        validation_path = _resolve_evidence(
            str(item["validation_path"]), "validation_path", directory=False
        )
        for evidence_path in (candidate_path, validation_path):
            if evidence_path in evidence_paths:
                raise ValueError("candidate or validation evidence is selected more than once")
            evidence_paths.add(evidence_path)
        try:
            target.relative_to(candidate_path)
        except ValueError:
            pass
        else:
            raise ValueError("destination and candidate evidence paths overlap")

        source = SourceManifest.load(source_path, repository_root=root)
        source_id = source.record.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source manifest must declare a scalar source_id")
        manifest_work_id = source.record.get("work_id")
        if not isinstance(manifest_work_id, str) or manifest_work_id != work_id:
            raise ValueError("source manifest must declare the exact selected scalar work_id")
        candidate = CandidatePackage.load(candidate_path)
        if candidate.manifest.get("source_id") != source_id:
            raise ValueError("candidate source identity does not match source manifest")
        for field, selected in (("work_id", work_id), ("rendering_id", rendering_id)):
            candidate_value = candidate.manifest.get(field)
            if candidate_value is not None and candidate_value != selected:
                raise ValueError(f"candidate manifest {field} does not match selection")

        decision = catalog_decision(
            source_path,
            repository_root=root,
            source_id=source_id,
            work_id=work_id,
            candidate_path=candidate_path,
            validation_path=validation_path,
        )
        if decision is None or decision.get("disposition") != "accepted":
            raise ValueError("selected candidate does not have a verified accepted decision")
        if decision.get("candidate_sha256") != candidate.sha256:
            raise ValueError("accepted decision candidate digest mismatch")
        decision_path = decision.get("path")
        if not isinstance(decision_path, str) or not decision_path or Path(decision_path).is_absolute():
            raise ValueError("accepted decision path must be repository-relative")
        prepared_items.append(
            {
                "selection": item,
                "work_id": work_id,
                "rendering_id": rendering_id,
                "source_path": source_path,
                "source_id": source_id,
                "source_sha256": _digest(source.sha256, "source manifest sha256"),
                "candidate_source_id": candidate.manifest.get("source_id"),
                "candidate_sha256": _digest(candidate.sha256, "candidate manifest sha256"),
                "tei_bytes": _captured_candidate_tei(candidate),
                "validation_file_sha256": _sha256_path(validation_path),
                "validation_report_sha256": _digest(
                    decision.get("validation_sha256"), "validation report sha256"
                ),
                "decision_path": decision_path,
                "decision_sha256": _digest(decision.get("sha256"), "decision sha256"),
            }
        )

    temp = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=os.fspath(target.parent))
    ).resolve(strict=True)
    try:
        for directory in ("tei", "data", "receipts"):
            (temp / directory).mkdir()
        manifest_items: list[dict[str, object]] = []
        for prepared in prepared_items:
            item = prepared["selection"]
            assert isinstance(item, dict)
            work_id = str(prepared["work_id"])
            rendering_id = str(prepared["rendering_id"])
            basename = f"{work_id}.{rendering_id}"
            tei_path = temp / "tei" / f"{basename}.tei.xml"
            jsonl_path = temp / "data" / f"{basename}.jsonl"
            receipt_path = temp / "receipts" / f"{basename}.jsonl.loss.json"
            tei_bytes = prepared["tei_bytes"]
            assert isinstance(tei_bytes, bytes)
            tei_path.write_bytes(tei_bytes)
            project_file(
                tei_path,
                jsonl_path,
                receipt_path=receipt_path,
                repo_root=temp,
                generated_at=str(selection["release_timestamp"]),
                language=str(selection["language"]),
                license_id=str(selection["license_id"]),
            )
            receipt_errors = check_receipt(receipt_path, repo_root=temp)
            if receipt_errors:
                raise ValueError(f"loss receipt check failed: {receipt_errors}")

            tei_public = _public_file(tei_path, temp)
            tei_public["source_member"] = "content.tei.xml"
            jsonl_public = _public_file(jsonl_path, temp)
            jsonl_public["rows"] = _jsonl_rows(jsonl_path)
            receipt_public = _public_file(receipt_path, temp)
            receipt_public["check"] = {"status": "pass", "errors": []}
            manifest_items.append(
                {
                    "work_id": work_id,
                    "rendering_id": rendering_id,
                    "attribution_text": item["attribution_text"],
                    "source": {
                        "source_id": prepared["source_id"],
                        "work_id": work_id,
                        "manifest_path": Path(prepared["source_path"])
                        .relative_to(root)
                        .as_posix(),
                        "manifest_sha256": prepared["source_sha256"],
                    },
                    "candidate": {
                        "manifest_sha256": prepared["candidate_sha256"],
                        "source_id": prepared["candidate_source_id"],
                    },
                    "validation": {
                        "file_sha256": prepared["validation_file_sha256"],
                        "report_sha256": prepared["validation_report_sha256"],
                    },
                    "decision": {
                        "path": prepared["decision_path"],
                        "sha256": prepared["decision_sha256"],
                        "disposition": "accepted",
                    },
                    "tei": tei_public,
                    "jsonl": jsonl_public,
                    "receipt": receipt_public,
                }
            )

        manifest_items.sort(key=lambda value: (str(value["work_id"]), str(value["rendering_id"])))
        manifest: dict[str, object] = {
            "contract": MANIFEST_CONTRACT,
            "release_id": selection["release_id"],
            "release_timestamp": selection["release_timestamp"],
            "selection_sha256": _sha256_bytes(selection_bytes),
            "repository_revision": revision,
            "config_name": selection["config_name"],
            "split": selection["split"],
            "language": selection["language"],
            "license_id": selection["license_id"],
            "publication": selection["publication"],
            "tooling": {
                "projector": GENERATOR,
                "projection_profile": PROFILE_ID,
                "tei_version": tei_version,
            },
            "items": manifest_items,
        }
        (temp / "README.md").write_bytes(_readme(selection, manifest_items))
        (temp / "release-manifest.json").write_bytes(_canonical_json(manifest))
        if target.exists() or target.is_symlink():
            raise ValueError("destination appeared during assembly")
        os.rename(temp, target)
        return manifest
    except BaseException:
        if temp.exists():
            shutil.rmtree(temp)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--repository-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build_release(
        args.selection,
        args.destination,
        repository_root=args.repository_root,
    )
    print(args.destination / "release-manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
