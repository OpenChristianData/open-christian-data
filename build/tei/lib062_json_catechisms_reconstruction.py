"""Build the nonaccepted LIB-062 JSON catechism candidate payload.

This module deliberately does not import the independent oracle.  The caller runs
``lib062_json_catechisms_oracle`` after this producer has written an unsealed
payload.  Only the oracle may add the final validation evidence and seal the
package manifest.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import stat
from pathlib import Path
from typing import Iterable, Mapping

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
PACKET_NAME = "LIB-062.packet.json"
README_NAME = "LIB-062.README.md"
TERMS_DISPOSITION = (
    "README grants Unlicense to this non-exception member; retain provider link "
    "and attribution artifact"
)
PACKET_KEYS = {
    "accountability_contract",
    "adjacent_witnesses",
    "authority",
    "contract",
    "primary_metadata",
    "profile",
    "retained_member_census",
    "structural_policy",
    "terms_evidence",
    "work_id",
}
PRIMARY_METADATA_KEYS = {"Authors", "SourceAttribution", "SourceUrl", "Title", "Year"}
PROFILE_KEYS = {
    "accountable_leaf_count",
    "data_record_count",
    "metadata_keys",
    "proof_group_count",
    "proofless_record_count",
    "question_with_proofs_count",
    "recursive_key_counts",
    "reference_count",
    "row_key_shapes",
    "subquestion_count",
}
ACCOUNTABILITY_CONTRACT = {
    "duplicate_leaf_count": 0,
    "leaf_model": "every scalar plus every explicit empty dict or list; metadata array elements are distinct leaves",
    "omitted_leaf_count": 0,
    "require_every_recursive_key": True,
    "require_every_scalar_leaf": True,
    "schema_equivalent": "oracle-enforced exact JSON-pointer/value/TEI-target crosswalk",
}
STRUCTURAL_GROUPING = "preserve only source-exposed nested structures; do not invent Lord days, sections, or parts"
STRUCTURAL_ORDERING = "Data array order and every nested array order are authoritative; Number and Id values are verbatim labels"
EXPECTED_PROTECTED_DIRECTORIES = (
    (
        "raw/Creeds.json/creeds",
        43,
        4_463_130,
        "74a6e844648d6df7e473807314655e7346c16f4e8ed260d8eeb55651228bf8bd",
    ),
    (
        "raw/TheologAI/data/historical-documents",
        17,
        2_429_217,
        "73eb804933153ec6a5da2b667477169ddff7ef42af9bebbcb1dab88e97ca09f3",
    ),
)
WORKS = (
    ("1695-baptist-catechism", "1695_baptist_catechism.json"),
    ("catechism-for-young-children", "catechism_for_young_children.json"),
    (
        "exposition-of-the-assemblies-catechism",
        "exposition_of_the_assemblies_catechism.json",
    ),
    ("heidelberg-catechism", "heidelberg_catechism.json"),
    ("keachs-catechism", "keachs_catechism.json"),
    ("matthew-henrys-scripture-catechism", "matthew_henrys_scripture_catechism.json"),
    ("puritan-catechism", "puritan_catechism.json"),
    ("shorter-catechism-explained", "shorter_catechism_explained.json"),
    ("westminster-larger-catechism", "westminster_larger_catechism.json"),
)
EXPECTED_PACKET_FILES = tuple(
    f"sources/{work_id}/{PACKET_NAME}" for work_id, _ in WORKS
)
PRODUCER_EVIDENCE_FILES = (
    "evidence/producer-import-closure.json",
    "evidence/retained-member-census.json",
    "evidence/review-state.json",
    "evidence/source-bindings.json",
)
PRODUCER_STAGE_FILES = frozenset(
    {"README.source.md", *PRODUCER_EVIDENCE_FILES}
    | {f"tei/{work_id}.tei.xml" for work_id, _ in WORKS}
    | {f"source-accounting/{work_id}.json" for work_id, _ in WORKS}
    | {f"validation/{work_id}.producer-validation.json" for work_id, _ in WORKS}
)
EXPECTED_CANDIDATE_DIRECTORIES = frozenset(
    {"tei", "source-accounting", "validation", "evidence"}
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _canonical_value(value: object) -> object:
    return json.loads(_canonical(value))


def _json_equal(left: object, right: object) -> bool:
    """Type- and order-aware recursive equality for JSON-domain values."""

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        assert isinstance(right, dict)
        return list(left) == list(right) and all(
            _json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        assert isinstance(right, list)
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _normalized_utf8(content: bytes) -> bytes:
    text = content.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _is_reparse(path: Path) -> bool:
    """Return whether *path* itself is a symlink, junction, or reparse point."""

    details = path.lstat()
    attributes = getattr(details, "st_file_attributes", 0)
    is_junction = getattr(path, "is_junction", lambda: False)
    return path.is_symlink() or is_junction() or bool(attributes & 0x400)


def _lexical_is_reparse(path: Path) -> bool:
    """Inspect the exact lexical path without following a dangling reparse entry."""

    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(details, "st_file_attributes", 0)
    is_junction = getattr(path, "is_junction", lambda: False)
    return path.is_symlink() or is_junction() or bool(attributes & 0x400)


def _regular_bytes(path: Path, label: str) -> bytes:
    try:
        details = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"{label} is missing or a broken link") from exc
    if _is_reparse(path) or not stat.S_ISREG(details.st_mode):
        raise ValueError(f"{label} must be a non-reparse regular file")
    return path.read_bytes()


def _candidate_inventory(
    root: Path, expected_files: frozenset[str]
) -> list[dict[str, object]]:
    if _is_reparse(root) or not root.is_dir():
        raise ValueError("candidate root must be a non-reparse directory")
    observed_directories: set[str] = set()
    observed_files: dict[str, bytes] = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            relative = path.relative_to(root).as_posix()
            try:
                details = path.lstat()
            except FileNotFoundError as exc:
                raise ValueError(
                    f"candidate contains broken entry: {relative}"
                ) from exc
            if _is_reparse(path):
                raise ValueError(f"candidate contains reparse entry: {relative}")
            if stat.S_ISDIR(details.st_mode):
                observed_directories.add(relative)
                pending.append(path)
            elif stat.S_ISREG(details.st_mode):
                observed_files[relative] = path.read_bytes()
            else:
                raise ValueError(f"candidate contains non-regular entry: {relative}")
    if observed_directories != EXPECTED_CANDIDATE_DIRECTORIES:
        raise ValueError("candidate directory set drift")
    if set(observed_files) != expected_files:
        raise ValueError("candidate producer-stage file set drift")
    return [
        {
            "path": relative,
            "bytes": len(observed_files[relative]),
            "sha256": _sha(observed_files[relative]),
        }
        for relative in sorted(observed_files)
    ]


def _safe_destination(repository_root: Path, destination: Path) -> Path:
    root = repository_root.resolve(strict=True)
    if _lexical_is_reparse(destination):
        raise ValueError(
            "candidate destination must not be a symlink, junction, or reparse point"
        )
    output = destination.resolve(strict=False)
    try:
        output.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("LIB-062 candidate must be outside the repository")
    for logical_surface in ("raw", "reports", "exports"):
        durable_root = resolve_repo_path(root, logical_surface).parent.resolve(
            strict=True
        )
        try:
            output.relative_to(durable_root)
        except ValueError:
            pass
        else:
            raise ValueError(
                "LIB-062 candidate must be outside every durable library surface"
            )
    for ancestor in (output, *output.parents):
        if (ancestor / ".git").exists():
            raise ValueError(
                "LIB-062 candidate must be outside every Git repository or worktree"
            )
    if not output.parent.is_dir():
        raise ValueError("candidate parent must already exist")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("candidate destination must be absent or empty")
    return output


def _module_file(root: Path, module: str) -> Path | None:
    candidate = root.joinpath(*module.split("."))
    py_file = candidate.with_suffix(".py")
    if py_file.is_file():
        return py_file
    initializer = candidate / "__init__.py"
    return initializer if initializer.is_file() else None


def repository_import_closure(root: Path, entry: Path) -> list[dict[str, object]]:
    """Return a deterministic recursive local-import closure and reject runtime loaders."""

    root = root.resolve(strict=True)
    pending = [entry.resolve(strict=True)]
    observed: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in observed:
            continue
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("closure entry is outside repository") from exc
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in {
                    "eval",
                    "exec",
                    "__import__",
                    "import_module",
                    "exec_module",
                }:
                    raise ValueError("dynamic import or execution is forbidden")
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            for module in modules:
                target = _module_file(root, module)
                if target is not None:
                    pending.append(target.resolve(strict=True))
                    parts = module.split(".")
                    for length in range(1, len(parts)):
                        init = root.joinpath(*parts[:length], "__init__.py")
                        if init.is_file():
                            pending.append(init.resolve(strict=True))
        observed.add(path)
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": len(path.read_bytes()),
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(observed, key=lambda item: item.relative_to(root).as_posix())
    ]


def _closure_digest(records: Iterable[Mapping[str, object]]) -> str:
    return _sha(_canonical(list(records)))


def _element(
    parent: etree._Element,
    name: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    child = etree.SubElement(parent, f"{{{TEI_NS}}}{name}")
    for key, value in (attributes or {}).items():
        child.set(XML_ID if key == "xml:id" else key, value)
    child.text = text
    return child


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _accountable_leaves(value: object, pointer: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        if not value:
            return [(pointer, {})]
        result: list[tuple[str, object]] = []
        for key, item in value.items():
            result.extend(_accountable_leaves(item, f"{pointer}/{_pointer_token(key)}"))
        return result
    if isinstance(value, list):
        if not value:
            return [(pointer, [])]
        result = []
        for index, item in enumerate(value):
            result.extend(_accountable_leaves(item, f"{pointer}/{index}"))
        return result
    return [(pointer, value)]


def _keys(value: object, counts: dict[str, int]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            counts[key] = counts.get(key, 0) + 1
            _keys(item, counts)
    elif isinstance(value, list):
        for item in value:
            _keys(item, counts)


def _expected_structural_policy(source: Mapping[str, object]) -> dict[str, object]:
    rows = source["Data"]
    assert isinstance(rows, list)
    preserve = ["Number", "Question", "Answer"]
    if any("QuestionWithProofs" in row for row in rows):
        preserve.append("QuestionWithProofs when present")
    if any("AnswerWithProofs" in row for row in rows):
        preserve.append("AnswerWithProofs when present")
    if any("SubQuestions" in row for row in rows):
        preserve.extend(
            [
                "SubQuestions/Number",
                "SubQuestions/Question",
                "SubQuestions/Answer",
                "explicit empty SubQuestions arrays",
            ]
        )
    elif any("Proofs" in row for row in rows):
        preserve.extend(
            ["Proofs/Id", "Proofs/References", "explicit empty Proofs arrays"]
        )
    return {
        "grouping": STRUCTURAL_GROUPING,
        "ordering": STRUCTURAL_ORDERING,
        "preserve": preserve,
    }


def _expected_profile(source: Mapping[str, object]) -> dict[str, object]:
    rows = source["Data"]
    assert isinstance(rows, list)
    key_counts: dict[str, int] = {}
    _keys(source, key_counts)
    proofs = [proof for row in rows for proof in row.get("Proofs", [])]
    return {
        "accountable_leaf_count": len(_accountable_leaves(source)),
        "data_record_count": len(rows),
        "metadata_keys": list(source["Metadata"]),
        "proof_group_count": len(proofs),
        "proofless_record_count": sum("Proofs" not in row for row in rows),
        "question_with_proofs_count": sum("QuestionWithProofs" in row for row in rows),
        "recursive_key_counts": key_counts,
        "reference_count": sum(len(proof["References"]) for proof in proofs),
        "row_key_shapes": [
            list(shape) for shape in sorted({tuple(row) for row in rows})
        ],
        "subquestion_count": sum(len(row.get("SubQuestions", [])) for row in rows),
    }


def _validate_packet_semantics(
    packet: Mapping[str, object], source: Mapping[str, object], work_id: str
) -> None:
    if set(packet) != PACKET_KEYS:
        raise ValueError(f"{work_id} packet key set drift")
    primary = packet.get("primary_metadata")
    if not isinstance(primary, Mapping) or set(primary) != PRIMARY_METADATA_KEYS:
        raise ValueError(f"{work_id} primary metadata key set drift")
    metadata = source["Metadata"]
    assert isinstance(metadata, Mapping)
    expected_primary = {key: metadata[key] for key in PRIMARY_METADATA_KEYS}
    if not _json_equal(dict(primary), _canonical_value(expected_primary)):
        raise ValueError(f"{work_id} primary metadata drift")
    accountability = packet.get("accountability_contract")
    if not isinstance(accountability, Mapping) or not _json_equal(
        dict(accountability), _canonical_value(ACCOUNTABILITY_CONTRACT)
    ):
        raise ValueError(f"{work_id} accountability contract drift")
    structural = packet.get("structural_policy")
    if not isinstance(structural, Mapping) or not _json_equal(
        dict(structural), _canonical_value(_expected_structural_policy(source))
    ):
        raise ValueError(f"{work_id} structural policy drift")
    profile = packet.get("profile")
    if not isinstance(profile, Mapping) or set(profile) != PROFILE_KEYS:
        raise ValueError(f"{work_id} profile key set drift")
    if not _json_equal(dict(profile), _canonical_value(_expected_profile(source))):
        raise ValueError(f"{work_id} profile census drift")
    census_binding = packet.get("retained_member_census")
    if not isinstance(census_binding, Mapping) or set(census_binding) != {
        "path",
        "bytes",
        "sha256",
    }:
        raise ValueError(f"{work_id} retained-member census binding key set drift")


def _source_and_packet(
    repository_root: Path,
    work_id: str,
    census_indexes: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object], bytes]:
    packet_path = repository_root / "sources" / work_id / PACKET_NAME
    packet = _strict_json(packet_path.read_bytes(), f"{work_id} packet")
    if set(packet) != PACKET_KEYS:
        raise ValueError(f"{work_id} packet key set drift")
    if not _json_equal(
        packet.get("contract"), "ocd-lib062-source-packet-v1"
    ) or not _json_equal(packet.get("work_id"), work_id):
        raise ValueError(f"{work_id} packet identity drift")
    authority = packet.get("authority")
    if not isinstance(authority, dict) or not isinstance(authority.get("path"), str):
        raise ValueError(f"{work_id} authority binding is invalid")
    if set(authority) != {
        "disposition",
        "path",
        "raw_bytes",
        "raw_sha256",
        "normalized_utf8_bytes",
        "normalized_utf8_sha256",
    }:
        raise ValueError(f"{work_id} authority key set drift")
    authority_rows = census_indexes["authorities"]
    assert isinstance(authority_rows, Mapping)
    census_authority = authority_rows.get(work_id)
    if not isinstance(census_authority, Mapping):
        raise ValueError(f"{work_id} has no unique included-authority census row")
    if not _json_equal(
        [
            authority.get("path"),
            authority.get("raw_bytes"),
            authority.get("raw_sha256"),
            authority.get("disposition"),
        ],
        [
            census_authority.get("path"),
            census_authority.get("bytes"),
            census_authority.get("raw_sha256"),
            "included in full as sole authority",
        ],
    ):
        raise ValueError(f"{work_id} authority does not match retained-member census")
    source_path = resolve_repo_path(repository_root, authority["path"])
    content = _regular_bytes(source_path, f"{work_id} retained authority")
    if not _json_equal(authority.get("raw_bytes"), len(content)) or not _json_equal(
        authority.get("raw_sha256"), _sha(content)
    ):
        raise ValueError(f"{work_id} raw source drift")
    normalized = _normalized_utf8(content)
    if not _json_equal(
        authority.get("normalized_utf8_bytes"), len(normalized)
    ) or not _json_equal(authority.get("normalized_utf8_sha256"), _sha(normalized)):
        raise ValueError(f"{work_id} normalized source drift")
    source = _strict_json(content, f"{work_id} retained source")
    _validate_packet_semantics(packet, source, work_id)
    terms = packet.get("terms_evidence")
    if not isinstance(terms, dict) or not isinstance(terms.get("path"), str):
        raise ValueError(f"{work_id} terms binding is invalid")
    if set(terms) != {"disposition", "path", "raw_bytes", "raw_sha256"}:
        raise ValueError(f"{work_id} terms evidence key set drift")
    census_terms = census_indexes["terms"]
    if not isinstance(census_terms, Mapping) or not _json_equal(
        [
            census_terms.get("disposition"),
            terms.get("disposition"),
            terms.get("path"),
            terms.get("raw_bytes"),
            terms.get("raw_sha256"),
        ],
        [
            "included-terms-evidence",
            TERMS_DISPOSITION,
            census_terms.get("path"),
            census_terms.get("bytes"),
            census_terms.get("raw_sha256"),
        ],
    ):
        raise ValueError(
            f"{work_id} terms evidence does not match retained-member census"
        )
    terms_content = _regular_bytes(
        resolve_repo_path(repository_root, terms["path"]), f"{work_id} terms evidence"
    )
    if not _json_equal(terms.get("raw_bytes"), len(terms_content)) or not _json_equal(
        terms.get("raw_sha256"), _sha(terms_content)
    ):
        raise ValueError(f"{work_id} terms evidence drift")
    adjacent = packet.get("adjacent_witnesses")
    if not isinstance(adjacent, list):
        raise ValueError(f"{work_id} adjacent witness census invalid")
    witness_rows = census_indexes["witnesses"]
    assert isinstance(witness_rows, Mapping)
    expected_witnesses = witness_rows.get(work_id, [])
    if not isinstance(expected_witnesses, list) or len(adjacent) != len(
        expected_witnesses
    ):
        raise ValueError(f"{work_id} adjacent witness census cardinality drift")
    for witness, census_witness in zip(adjacent, expected_witnesses, strict=True):
        if not isinstance(witness, dict) or not isinstance(witness.get("path"), str):
            raise ValueError(f"{work_id} adjacent witness binding invalid")
        if set(witness) != {
            "disposition",
            "path",
            "raw_bytes",
            "raw_sha256",
            "normalized_utf8_bytes",
            "normalized_utf8_sha256",
        }:
            raise ValueError(f"{work_id} adjacent witness key set drift")
        if (
            not isinstance(census_witness, Mapping)
            or census_witness.get("related_work_id") != work_id
        ):
            raise ValueError(f"{work_id} adjacent witness related identity drift")
        if not _json_equal(
            [
                witness.get("path"),
                witness.get("raw_bytes"),
                witness.get("raw_sha256"),
                witness.get("disposition"),
            ],
            [
                census_witness.get("path"),
                census_witness.get("bytes"),
                census_witness.get("raw_sha256"),
                census_witness.get("disposition"),
            ],
        ):
            raise ValueError(
                f"{work_id} adjacent witness does not match retained-member census"
            )
        witness_content = _regular_bytes(
            resolve_repo_path(repository_root, witness["path"]),
            f"{work_id} adjacent witness",
        )
        witness_normalized = _normalized_utf8(witness_content)
        if not _json_equal(
            [
                len(witness_content),
                _sha(witness_content),
                len(witness_normalized),
                _sha(witness_normalized),
            ],
            [
                witness.get("raw_bytes"),
                witness.get("raw_sha256"),
                witness.get("normalized_utf8_bytes"),
                witness.get("normalized_utf8_sha256"),
            ],
        ):
            raise ValueError(f"{work_id} adjacent witness drift")
    return packet, source, content


def _retained_member_census(
    repository_root: Path,
) -> tuple[dict[str, object], bytes, dict[str, object]]:
    logical = "sources/1695-baptist-catechism/LIB-062.retained-member-census.json"
    content = resolve_repo_path(repository_root, logical).read_bytes()
    census = _strict_json(content, "LIB-062 retained-member census")
    if set(census) != {
        "contract",
        "member_count",
        "members",
        "protected_directories",
        "terms_evidence",
        "ticket",
    }:
        raise ValueError("retained-member census key set drift")
    if (
        not _json_equal(census.get("contract"), "ocd-lib062-retained-member-census-v1")
        or not _json_equal(census.get("ticket"), "LIB-062")
        or not _json_equal(census.get("member_count"), 61)
    ):
        raise ValueError("retained-member census identity drift")
    expected_members = census.get("members")
    if (
        not isinstance(expected_members, list)
        or len(expected_members) != 61
        or [item.get("path") for item in expected_members if isinstance(item, dict)]
        != sorted(
            item.get("path") for item in expected_members if isinstance(item, dict)
        )
    ):
        raise ValueError("retained-member census order drift")
    for member in expected_members:
        if not isinstance(member, dict):
            raise ValueError("retained-member census member envelope drift")
        disposition = member.get("disposition")
        keys = {"path", "bytes", "raw_sha256", "disposition"}
        if disposition == "included-authority":
            keys.add("work_id")
        elif disposition == "excluded-adjacent-witness-no-human-source-choice":
            keys.add("related_work_id")
        elif disposition not in {
            "included-terms-evidence",
            "excluded-outside-LIB-062-assigned-scope",
            "excluded-unrelated-to-LIB-062-assigned-scope",
        }:
            raise ValueError("retained-member census disposition drift")
        if set(member) != keys:
            raise ValueError("retained-member census member envelope drift")
    protected = census.get("protected_directories")
    expected_protected = [
        {"path": path, "file_count": count, "bytes": size, "manifest_sha256": digest}
        for path, count, size, digest in EXPECTED_PROTECTED_DIRECTORIES
    ]
    if (
        not isinstance(protected, list)
        or any(
            not isinstance(item, dict)
            or set(item) != {"path", "file_count", "bytes", "manifest_sha256"}
            for item in protected
        )
        or not _json_equal(protected, _canonical_value(expected_protected))
    ):
        raise ValueError("retained-member protected-directory envelope drift")
    terms_envelope = census.get("terms_evidence")
    if (
        not isinstance(terms_envelope, dict)
        or set(terms_envelope) != {"path", "bytes", "raw_sha256"}
        or terms_envelope.get("path") != "raw/Creeds.json/README.md"
    ):
        raise ValueError("retained-member terms envelope drift")
    observed: list[dict[str, object]] = []
    work_by_name = {filename: work_id for work_id, filename in WORKS}
    for logical_root in (
        "raw/Creeds.json/creeds",
        "raw/TheologAI/data/historical-documents",
    ):
        physical_root = resolve_repo_path(repository_root, logical_root)
        entries = sorted(physical_root.iterdir(), key=lambda item: item.name)
        for path in entries:
            raw = _regular_bytes(
                path, f"protected census member {logical_root}/{path.name}"
            )
            member_logical = f"{logical_root}/{path.name}"
            member = {
                "path": member_logical,
                "bytes": len(raw),
                "raw_sha256": _sha(raw),
            }
            if logical_root.endswith("creeds"):
                if path.name in work_by_name:
                    member.update(
                        disposition="included-authority",
                        work_id=work_by_name[path.name],
                    )
                else:
                    member["disposition"] = "excluded-outside-LIB-062-assigned-scope"
            elif path.name in {
                "heidelberg-catechism.json",
                "westminster-larger-catechism.json",
            }:
                member.update(
                    disposition="excluded-adjacent-witness-no-human-source-choice",
                    related_work_id=path.stem,
                )
            else:
                member["disposition"] = "excluded-unrelated-to-LIB-062-assigned-scope"
            observed.append(member)
    terms_path = resolve_repo_path(repository_root, "raw/Creeds.json/README.md")
    terms_content = _regular_bytes(terms_path, "protected terms evidence")
    observed.append(
        {
            "path": "raw/Creeds.json/README.md",
            "bytes": len(terms_content),
            "raw_sha256": _sha(terms_content),
            "disposition": "included-terms-evidence",
        }
    )
    observed.sort(key=lambda item: str(item["path"]))
    if not _json_equal(_canonical_value(observed), expected_members):
        raise ValueError("retained-member census differs from protected storage")
    for directory in protected:
        logical_root = directory["path"]
        rows = [
            item
            for item in observed
            if str(item["path"]).startswith(f"{logical_root}/")
        ]
        manifest_bytes = "\n".join(
            f"{str(item['path'])[len(logical_root) + 1 :]}\t{item['bytes']}\t{item['raw_sha256']}"
            for item in rows
        ).encode("utf-8")
        if not _json_equal(
            [len(rows), sum(int(item["bytes"]) for item in rows), _sha(manifest_bytes)],
            [directory["file_count"], directory["bytes"], directory["manifest_sha256"]],
        ):
            raise ValueError(f"protected directory inventory drift: {logical_root}")
    binding = terms_envelope
    if not isinstance(binding, dict) or not _json_equal(
        [binding.get("bytes"), binding.get("raw_sha256")],
        [len(terms_content), _sha(terms_content)],
    ):
        raise ValueError("retained terms inventory drift")
    authorities: dict[str, dict[str, object]] = {}
    witnesses: dict[str, list[dict[str, object]]] = {
        work_id: [] for work_id, _ in WORKS
    }
    terms_rows: list[dict[str, object]] = []
    for row in observed:
        disposition = row["disposition"]
        if disposition == "included-authority":
            work_id = str(row.get("work_id"))
            if work_id in authorities:
                raise ValueError(f"duplicate included-authority census row: {work_id}")
            authorities[work_id] = row
        elif disposition == "included-terms-evidence":
            terms_rows.append(row)
        elif disposition == "excluded-adjacent-witness-no-human-source-choice":
            related = str(row.get("related_work_id"))
            if related not in witnesses:
                raise ValueError(f"unknown adjacent witness related work: {related}")
            witnesses[related].append(row)
    if set(authorities) != {work_id for work_id, _ in WORKS} or len(terms_rows) != 1:
        raise ValueError("retained-member disposition index drift")
    for rows in witnesses.values():
        rows.sort(key=lambda item: str(item["path"]))
    if {work_id: len(rows) for work_id, rows in witnesses.items()} != {
        work_id: int(
            work_id in {"heidelberg-catechism", "westminster-larger-catechism"}
        )
        for work_id, _ in WORKS
    }:
        raise ValueError("retained-member adjacent witness index drift")
    return (
        census,
        content,
        {"authorities": authorities, "terms": terms_rows[0], "witnesses": witnesses},
    )


def _assert_model(
    packet: Mapping[str, object], source: Mapping[str, object], work_id: str
) -> None:
    profile = packet.get("profile")
    if not isinstance(profile, Mapping):
        raise ValueError(f"{work_id} profile is invalid")
    if (
        list(source) != ["Metadata", "Data"]
        or not isinstance(source["Metadata"], dict)
        or not isinstance(source["Data"], list)
    ):
        raise ValueError(f"{work_id} top-level source shape drift")
    metadata = source["Metadata"]
    rows = source["Data"]
    if not _json_equal(list(metadata), profile.get("metadata_keys")) or not _json_equal(
        len(rows), profile.get("data_record_count")
    ):
        raise ValueError(f"{work_id} metadata or record census drift")
    row_shapes = sorted({tuple(row) for row in rows})
    expected_shapes = sorted(
        tuple(shape) for shape in profile.get("row_key_shapes", [])
    )
    if not _json_equal(_canonical_value(row_shapes), _canonical_value(expected_shapes)):
        raise ValueError(f"{work_id} row-key shape drift")
    subquestions = [sub for row in rows for sub in row.get("SubQuestions", [])]
    proofs = [proof for row in rows for proof in row.get("Proofs", [])]
    references = [ref for proof in proofs for ref in proof.get("References", [])]
    observed = {
        "subquestion_count": len(subquestions),
        "proof_group_count": len(proofs),
        "reference_count": len(references),
        "question_with_proofs_count": sum("QuestionWithProofs" in row for row in rows),
        "proofless_record_count": sum("Proofs" not in row for row in rows),
    }
    for key, value in observed.items():
        if not _json_equal(profile.get(key), value):
            raise ValueError(f"{work_id} {key} drift")
    key_counts: dict[str, int] = {}
    _keys(source, key_counts)
    if not _json_equal(
        profile.get("recursive_key_counts"), _canonical_value(key_counts)
    ):
        raise ValueError(f"{work_id} recursive key census drift")


def _build_tei(
    work_id: str, packet: Mapping[str, object], source: Mapping[str, object]
) -> tuple[bytes, dict[str, object]]:
    metadata = source["Metadata"]
    rows = source["Data"]
    assert isinstance(metadata, dict) and isinstance(rows, list)
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(XML_ID, f"lib062-{work_id}")
    header = _element(root, "teiHeader")
    file_desc = _element(header, "fileDesc")
    title_stmt = _element(file_desc, "titleStmt")
    _element(title_stmt, "title", text=str(metadata["Title"]))
    for author in metadata["Authors"]:
        _element(title_stmt, "author", text=str(author))
    publication = _element(file_desc, "publicationStmt")
    _element(publication, "publisher", text="Open Christian Data")
    availability = _element(publication, "availability", {"status": "restricted"})
    _element(
        availability,
        "p",
        text="Nonaccepted reconstruction candidate; publication is not ready or authorized.",
    )
    source_desc = _element(file_desc, "sourceDesc")
    id_prefix = f"lib062-{work_id}"
    bibl = _element(source_desc, "bibl", {"xml:id": f"{id_prefix}-source"})
    _element(bibl, "title", text=str(metadata["Title"]))
    authority = packet["authority"]
    assert isinstance(authority, Mapping)
    _element(bibl, "ptr", {"target": str(authority["path"])})
    _element(bibl, "idno", {"type": "sha256-raw"}, str(authority["raw_sha256"]))
    _element(
        bibl,
        "idno",
        {"type": "sha256-universal-newline-utf8"},
        str(authority["normalized_utf8_sha256"]),
    )
    metadata_list = _element(source_desc, "list", {"type": "source-metadata"})
    crosswalk: list[dict[str, object]] = []
    for position, (key, value) in enumerate(metadata.items(), start=1):
        target_id = f"{id_prefix}-metadata-{position:02d}"
        _element(
            metadata_list,
            "item",
            {"xml:id": target_id, "n": key},
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        )
        for pointer, leaf_value in _accountable_leaves(
            value, f"/Metadata/{_pointer_token(key)}"
        ):
            crosswalk.append(
                {
                    "pointer": pointer,
                    "value": leaf_value,
                    "disposition": "represented",
                    "tei_target": f"#{target_id}",
                }
            )
    encoding = _element(header, "encodingDesc")
    _element(
        encoding,
        "p",
        text="Source row order, verbatim labels, question and answer strings, nested subquestions, proof markers, and reference strings are preserved without modernization or invented grouping.",
    )
    text = _element(root, "text")
    body = _element(text, "body")
    corpus = _element(body, "div", {"type": "catechism", "xml:id": f"{id_prefix}-body"})
    for row_ordinal, row in enumerate(rows, start=1):
        row_id = f"{id_prefix}-row-{row_ordinal:04d}"
        unit = _element(
            corpus,
            "div",
            {"type": "question-unit", "xml:id": row_id, "n": str(row["Number"])},
        )
        label_id = f"{row_id}-number"
        _element(
            unit,
            "label",
            {"xml:id": label_id, "type": "source-number"},
            str(row["Number"]),
        )
        crosswalk.append(
            {
                "pointer": f"/Data/{row_ordinal - 1}/Number",
                "value": row["Number"],
                "disposition": "represented",
                "tei_target": f"#{label_id}",
            }
        )
        for key, kind in (
            ("Question", "question"),
            ("QuestionWithProofs", "question-with-proofs"),
            ("Answer", "answer"),
            ("AnswerWithProofs", "answer-with-proofs"),
        ):
            if key in row:
                target_id = f"{row_id}-{kind}"
                _element(
                    unit, "p", {"xml:id": target_id, "ana": f"#{kind}"}, str(row[key])
                )
                crosswalk.append(
                    {
                        "pointer": f"/Data/{row_ordinal - 1}/{key}",
                        "value": row[key],
                        "disposition": "represented",
                        "tei_target": f"#{target_id}",
                    }
                )
        if "SubQuestions" in row:
            if not row["SubQuestions"]:
                target_id = f"{row_id}-subquestions-empty"
                _element(
                    unit,
                    "note",
                    {
                        "xml:id": target_id,
                        "type": "source-empty-array",
                        "n": "SubQuestions",
                    },
                )
                crosswalk.append(
                    {
                        "pointer": f"/Data/{row_ordinal - 1}/SubQuestions",
                        "value": [],
                        "disposition": "represented",
                        "tei_target": f"#{target_id}",
                    }
                )
                continue
            sub_list = _element(
                unit,
                "list",
                {"type": "subquestions", "xml:id": f"{row_id}-subquestions"},
            )
            for sub_ordinal, sub in enumerate(row["SubQuestions"], start=1):
                sub_id = f"{row_id}-sub-{sub_ordinal:04d}"
                item = _element(
                    sub_list, "item", {"xml:id": sub_id, "n": str(sub["Number"])}
                )
                for key, tag, kind in (
                    ("Number", "label", "number"),
                    ("Question", "p", "question"),
                    ("Answer", "p", "answer"),
                ):
                    target_id = f"{sub_id}-{kind}"
                    attributes = (
                        {"xml:id": target_id, "type": "subquestion-number"}
                        if tag == "label"
                        else {"xml:id": target_id, "ana": f"#subquestion-{kind}"}
                    )
                    _element(item, tag, attributes, str(sub[key]))
                    crosswalk.append(
                        {
                            "pointer": f"/Data/{row_ordinal - 1}/SubQuestions/{sub_ordinal - 1}/{key}",
                            "value": sub[key],
                            "disposition": "represented",
                            "tei_target": f"#{target_id}",
                        }
                    )
        if "Proofs" in row:
            if not row["Proofs"]:
                target_id = f"{row_id}-proofs-empty"
                _element(
                    unit,
                    "note",
                    {"xml:id": target_id, "type": "source-empty-array", "n": "Proofs"},
                )
                crosswalk.append(
                    {
                        "pointer": f"/Data/{row_ordinal - 1}/Proofs",
                        "value": [],
                        "disposition": "represented",
                        "tei_target": f"#{target_id}",
                    }
                )
                continue
            proof_list = _element(
                unit, "list", {"type": "proofs", "xml:id": f"{row_id}-proofs"}
            )
            for proof_ordinal, proof in enumerate(row["Proofs"], start=1):
                proof_id = f"{row_id}-proof-{proof_ordinal:03d}"
                item = _element(
                    proof_list, "item", {"xml:id": proof_id, "n": str(proof["Id"])}
                )
                marker_id = f"{proof_id}-id"
                _element(
                    item,
                    "label",
                    {"xml:id": marker_id, "type": "proof-id"},
                    str(proof["Id"]),
                )
                crosswalk.append(
                    {
                        "pointer": f"/Data/{row_ordinal - 1}/Proofs/{proof_ordinal - 1}/Id",
                        "value": proof["Id"],
                        "disposition": "represented",
                        "tei_target": f"#{marker_id}",
                    }
                )
                refs = _element(item, "listBibl", {"type": "source-references"})
                for ref_ordinal, reference in enumerate(proof["References"], start=1):
                    target_id = f"{proof_id}-ref-{ref_ordinal:03d}"
                    bibl_ref = _element(refs, "bibl", {"xml:id": target_id})
                    _element(bibl_ref, "ref", {"type": "scripture"}, str(reference))
                    crosswalk.append(
                        {
                            "pointer": f"/Data/{row_ordinal - 1}/Proofs/{proof_ordinal - 1}/References/{ref_ordinal - 1}",
                            "value": reference,
                            "disposition": "represented",
                            "tei_target": f"#{target_id}",
                        }
                    )
    key_counts: dict[str, int] = {}
    _keys(source, key_counts)
    accounting = {
        "contract": "ocd-lib062-source-accountability-v1",
        "work_id": work_id,
        "source_member_disposition": "included in full as sole authority",
        "top_level_keys": ["Metadata", "Data"],
        "recursive_key_counts": key_counts,
        "data_record_count": len(rows),
        "represented_leaf_count": len(crosswalk),
        "omitted_leaf_count": 0,
        "duplicate_leaf_count": 0,
        "crosswalk": crosswalk,
    }
    expected_leaf_count = packet["profile"]["accountable_leaf_count"]
    if not _json_equal(len(crosswalk), expected_leaf_count) or {
        item["pointer"] for item in crosswalk
    } != {pointer for pointer, _ in _accountable_leaves(source)}:
        raise ValueError(f"{work_id} complete accountable leaf model drift")
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    ), accounting


def _schema(repository_root: Path) -> etree.XMLSchema:
    path = repository_root / "ocd_kernel" / "tei" / "vendor" / "xsd" / "tei_all.xsd"
    return etree.XMLSchema(etree.parse(str(path)))


def reconstruct(repository_root: Path, destination: Path) -> Path:
    repository_root = repository_root.resolve(strict=True)
    output = _safe_destination(repository_root, destination)
    output.mkdir(exist_ok=True)
    (output / "tei").mkdir()
    (output / "source-accounting").mkdir()
    (output / "validation").mkdir()
    (output / "evidence").mkdir()
    schema = _schema(repository_root)
    _, census_bytes, census_indexes = _retained_member_census(repository_root)
    source_records: list[dict[str, object]] = []
    for work_id, _ in WORKS:
        packet, source, content = _source_and_packet(
            repository_root, work_id, census_indexes
        )
        census_binding = packet.get("retained_member_census")
        if not isinstance(census_binding, dict) or not _json_equal(
            census_binding,
            _canonical_value(
                {
                    "path": "sources/1695-baptist-catechism/LIB-062.retained-member-census.json",
                    "bytes": len(census_bytes),
                    "sha256": _sha(census_bytes),
                }
            ),
        ):
            raise ValueError(f"{work_id} retained-member census binding drift")
        _assert_model(packet, source, work_id)
        tei_bytes, accounting = _build_tei(work_id, packet, source)
        document = etree.fromstring(tei_bytes)
        if not schema.validate(etree.ElementTree(document)):
            raise ValueError(f"{work_id} TEI P5 failure: {schema.error_log.last_error}")
        tei_name = f"tei/{work_id}.tei.xml"
        accounting_name = f"source-accounting/{work_id}.json"
        (output / tei_name).write_bytes(tei_bytes)
        (output / accounting_name).write_bytes(_canonical(accounting))
        report = {
            "contract": "ocd-lib062-producer-validation-v1",
            "status": "pass",
            "work_id": work_id,
            "tei_p5": "pass",
            "structural_policy": "pass",
            "source_accounting": "pass",
            "source_raw_sha256": _sha(content),
            "tei_sha256": _sha(tei_bytes),
            "accounting_sha256": _sha(_canonical(accounting)),
        }
        (output / "validation" / f"{work_id}.producer-validation.json").write_bytes(
            _canonical(report)
        )
        source_records.append(
            {
                "work_id": work_id,
                "packet_sha256": _sha(
                    (repository_root / "sources" / work_id / PACKET_NAME).read_bytes()
                ),
                "source_raw_sha256": _sha(content),
                "source_normalized_utf8_sha256": _sha(_normalized_utf8(content)),
            }
        )
    readmes = [
        _normalized_utf8(
            _regular_bytes(
                repository_root / "sources" / work_id / README_NAME,
                f"{work_id} source-local attribution README",
            )
        )
        for work_id, _ in WORKS
    ]
    (output / "README.source.md").write_bytes(
        b"# LIB-062 source attribution bundle\n\n" + b"\n\n---\n\n".join(readmes)
    )
    closure = repository_import_closure(repository_root, Path(__file__))
    (output / "evidence" / "producer-import-closure.json").write_bytes(
        _canonical(
            {
                "contract": "ocd-lib062-import-closure-v1",
                "entry": "build/tei/lib062_json_catechisms_reconstruction.py",
                "sha256": _closure_digest(closure),
                "members": closure,
            }
        )
    )
    (output / "evidence" / "review-state.json").write_bytes(
        _canonical(
            {
                "contract": "ocd-lib062-review-state-v1",
                "ticket": "LIB-062",
                "technical_acceptance": "not_claimed",
                "human_acceptance": "not_performed",
                "publication": "not_ready",
                "works": [work_id for work_id, _ in WORKS],
                "unresolved": [
                    "Human textual, edition, identity, and rights review remains outstanding.",
                    "TheologAI Heidelberg and Westminster Larger files are adjacent excluded witnesses; no source choice or conflation was made.",
                    "The producer and oracle independently rederive retained bytes but duplicate specification and disposition constants; agreement proves reproducibility and implementation cross-checking, not independent confirmation of the specification.",
                ],
            }
        )
    )
    (output / "evidence" / "source-bindings.json").write_bytes(
        _canonical(
            {"contract": "ocd-lib062-source-bindings-v1", "sources": source_records}
        )
    )
    (output / "evidence" / "retained-member-census.json").write_bytes(census_bytes)
    _candidate_inventory(output, PRODUCER_STAGE_FILES)
    return output


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    reconstruct(args.repository_root, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
