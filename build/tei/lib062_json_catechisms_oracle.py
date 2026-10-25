"""Independent retained-byte oracle and package sealer for LIB-062."""

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
WORK_IDS = (
    "1695-baptist-catechism",
    "catechism-for-young-children",
    "exposition-of-the-assemblies-catechism",
    "heidelberg-catechism",
    "keachs-catechism",
    "matthew-henrys-scripture-catechism",
    "puritan-catechism",
    "shorter-catechism-explained",
    "westminster-larger-catechism",
)
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
EXPECTED_DIRECTORIES = frozenset({"tei", "source-accounting", "validation", "evidence"})
PRODUCER_EVIDENCE_FILES = frozenset(
    {
        "evidence/producer-import-closure.json",
        "evidence/retained-member-census.json",
        "evidence/review-state.json",
        "evidence/source-bindings.json",
    }
)
PRODUCER_STAGE_FILES = frozenset(
    {"README.source.md", *PRODUCER_EVIDENCE_FILES}
    | {f"tei/{work_id}.tei.xml" for work_id in WORK_IDS}
    | {f"source-accounting/{work_id}.json" for work_id in WORK_IDS}
    | {f"validation/{work_id}.producer-validation.json" for work_id in WORK_IDS}
)
PRE_RESULT_FILES = PRODUCER_STAGE_FILES | {"evidence/oracle-import-closure.json"}
SEALED_MEMBER_FILES = PRE_RESULT_FILES | {"evidence/oracle-result.json"}
PACKAGE_FILES = SEALED_MEMBER_FILES | {"manifest.json"}
REVIEW_LIMITATIONS = [
    "Human textual, edition, identity, and rights review remains outstanding.",
    "TheologAI Heidelberg and Westminster Larger files are adjacent excluded witnesses; no source choice or conflation was made.",
    "The producer and oracle independently rederive retained bytes but duplicate specification and disposition constants; agreement proves reproducibility and implementation cross-checking, not independent confirmation of the specification.",
]


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
        raise ValueError(f"{label} must be an object")
    return value


def _normalized_utf8(content: bytes) -> bytes:
    return (
        content.decode("utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .encode("utf-8")
    )


def _is_reparse(path: Path) -> bool:
    details = path.lstat()
    attributes = getattr(details, "st_file_attributes", 0)
    is_junction = getattr(path, "is_junction", lambda: False)
    return path.is_symlink() or is_junction() or bool(attributes & 0x400)


def _lexical_is_reparse(path: Path) -> bool:
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


def _guard_candidate_destination(repository_root: Path, candidate_root: Path) -> Path:
    """Pure oracle-local safety check for an already-populated candidate."""

    root = repository_root.resolve(strict=True)
    if _lexical_is_reparse(candidate_root):
        raise ValueError("oracle candidate must be a non-reparse directory")
    candidate = candidate_root.resolve(strict=True)
    if _is_reparse(candidate) or not candidate.is_dir():
        raise ValueError("oracle candidate must be a non-reparse directory")
    forbidden_roots = [root]
    for logical_surface in ("raw", "reports", "exports"):
        forbidden_roots.append(
            resolve_repo_path(root, logical_surface).parent.resolve(strict=True)
        )
    for forbidden in forbidden_roots:
        try:
            candidate.relative_to(forbidden)
        except ValueError:
            continue
        if forbidden == root:
            raise ValueError("oracle candidate must be outside the repository")
        raise ValueError(
            "oracle candidate must be outside every durable library surface"
        )
    for ancestor in (candidate, *candidate.parents):
        git_marker = ancestor / ".git"
        if git_marker.exists() or git_marker.is_symlink():
            raise ValueError(
                "oracle candidate must be outside every Git repository or worktree"
            )
    return candidate


def _module_file(root: Path, module: str) -> Path | None:
    stem = root.joinpath(*module.split("."))
    file = stem.with_suffix(".py")
    if file.is_file():
        return file
    initializer = stem / "__init__.py"
    return initializer if initializer.is_file() else None


def repository_import_closure(root: Path, entry: Path) -> list[dict[str, object]]:
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
            raise ValueError("closure path outside repository") from exc
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    callable_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    callable_name = node.func.attr
                else:
                    callable_name = ""
                if callable_name in {
                    "eval",
                    "exec",
                    "__import__",
                    "import_module",
                    "exec_module",
                }:
                    raise ValueError("dynamic import or execution is forbidden")
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            for module in modules:
                target = _module_file(root, module)
                if target is not None:
                    pending.append(target.resolve(strict=True))
                    parts = module.split(".")
                    for length in range(1, len(parts)):
                        initializer = root.joinpath(*parts[:length], "__init__.py")
                        if initializer.is_file():
                            pending.append(initializer.resolve(strict=True))
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


def _expected_tei(
    work_id: str, packet: Mapping[str, object], source: Mapping[str, object]
) -> bytes:
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
    for position, (key, value) in enumerate(metadata.items(), start=1):
        _element(
            metadata_list,
            "item",
            {"xml:id": f"{id_prefix}-metadata-{position:02d}", "n": key},
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
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
        _element(
            unit,
            "label",
            {"xml:id": f"{row_id}-number", "type": "source-number"},
            str(row["Number"]),
        )
        for key, kind in (
            ("Question", "question"),
            ("QuestionWithProofs", "question-with-proofs"),
            ("Answer", "answer"),
            ("AnswerWithProofs", "answer-with-proofs"),
        ):
            if key in row:
                _element(
                    unit,
                    "p",
                    {"xml:id": f"{row_id}-{kind}", "ana": f"#{kind}"},
                    str(row[key]),
                )
        if "SubQuestions" in row:
            if not row["SubQuestions"]:
                _element(
                    unit,
                    "note",
                    {
                        "xml:id": f"{row_id}-subquestions-empty",
                        "type": "source-empty-array",
                        "n": "SubQuestions",
                    },
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
                _element(
                    item,
                    "label",
                    {"xml:id": f"{sub_id}-number", "type": "subquestion-number"},
                    str(sub["Number"]),
                )
                _element(
                    item,
                    "p",
                    {"xml:id": f"{sub_id}-question", "ana": "#subquestion-question"},
                    str(sub["Question"]),
                )
                _element(
                    item,
                    "p",
                    {"xml:id": f"{sub_id}-answer", "ana": "#subquestion-answer"},
                    str(sub["Answer"]),
                )
        if "Proofs" in row:
            if not row["Proofs"]:
                _element(
                    unit,
                    "note",
                    {
                        "xml:id": f"{row_id}-proofs-empty",
                        "type": "source-empty-array",
                        "n": "Proofs",
                    },
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
                _element(
                    item,
                    "label",
                    {"xml:id": f"{proof_id}-id", "type": "proof-id"},
                    str(proof["Id"]),
                )
                refs = _element(item, "listBibl", {"type": "source-references"})
                for ref_ordinal, reference in enumerate(proof["References"], start=1):
                    bibl_ref = _element(
                        refs, "bibl", {"xml:id": f"{proof_id}-ref-{ref_ordinal:03d}"}
                    )
                    _element(bibl_ref, "ref", {"type": "scripture"}, str(reference))
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _ordered_leaves(value: object, pointer: str) -> list[tuple[str, object]]:
    if isinstance(value, dict):
        if not value:
            return [(pointer, {})]
        result: list[tuple[str, object]] = []
        for key, item in value.items():
            token = key.replace("~", "~0").replace("/", "~1")
            result.extend(_ordered_leaves(item, f"{pointer}/{token}"))
        return result
    if isinstance(value, list):
        if not value:
            return [(pointer, [])]
        result = []
        for index, item in enumerate(value):
            result.extend(_ordered_leaves(item, f"{pointer}/{index}"))
        return result
    return [(pointer, value)]


def _expected_crosswalk(
    work_id: str, source: Mapping[str, object]
) -> list[dict[str, object]]:
    """Independently derive the exact ordered accountability projection."""

    metadata = source["Metadata"]
    rows = source["Data"]
    assert isinstance(metadata, dict) and isinstance(rows, list)
    prefix = f"lib062-{work_id}"
    expected: list[dict[str, object]] = []
    for position, (key, value) in enumerate(metadata.items(), start=1):
        token = key.replace("~", "~0").replace("/", "~1")
        target = f"#{prefix}-metadata-{position:02d}"
        for pointer, leaf_value in _ordered_leaves(value, f"/Metadata/{token}"):
            expected.append(
                {
                    "pointer": pointer,
                    "value": leaf_value,
                    "disposition": "represented",
                    "tei_target": target,
                }
            )
    for row_ordinal, row in enumerate(rows, start=1):
        row_id = f"{prefix}-row-{row_ordinal:04d}"
        row_pointer = f"/Data/{row_ordinal - 1}"
        expected.append(
            {
                "pointer": f"{row_pointer}/Number",
                "value": row["Number"],
                "disposition": "represented",
                "tei_target": f"#{row_id}-number",
            }
        )
        for key, kind in (
            ("Question", "question"),
            ("QuestionWithProofs", "question-with-proofs"),
            ("Answer", "answer"),
            ("AnswerWithProofs", "answer-with-proofs"),
        ):
            if key in row:
                expected.append(
                    {
                        "pointer": f"{row_pointer}/{key}",
                        "value": row[key],
                        "disposition": "represented",
                        "tei_target": f"#{row_id}-{kind}",
                    }
                )
        if "SubQuestions" in row:
            if not row["SubQuestions"]:
                expected.append(
                    {
                        "pointer": f"{row_pointer}/SubQuestions",
                        "value": [],
                        "disposition": "represented",
                        "tei_target": f"#{row_id}-subquestions-empty",
                    }
                )
                continue
            for sub_ordinal, sub in enumerate(row["SubQuestions"], start=1):
                sub_id = f"{row_id}-sub-{sub_ordinal:04d}"
                for key, kind in (
                    ("Number", "number"),
                    ("Question", "question"),
                    ("Answer", "answer"),
                ):
                    expected.append(
                        {
                            "pointer": f"{row_pointer}/SubQuestions/{sub_ordinal - 1}/{key}",
                            "value": sub[key],
                            "disposition": "represented",
                            "tei_target": f"#{sub_id}-{kind}",
                        }
                    )
        if "Proofs" in row:
            if not row["Proofs"]:
                expected.append(
                    {
                        "pointer": f"{row_pointer}/Proofs",
                        "value": [],
                        "disposition": "represented",
                        "tei_target": f"#{row_id}-proofs-empty",
                    }
                )
                continue
            for proof_ordinal, proof in enumerate(row["Proofs"], start=1):
                proof_id = f"{row_id}-proof-{proof_ordinal:03d}"
                expected.append(
                    {
                        "pointer": f"{row_pointer}/Proofs/{proof_ordinal - 1}/Id",
                        "value": proof["Id"],
                        "disposition": "represented",
                        "tei_target": f"#{proof_id}-id",
                    }
                )
                for ref_ordinal, reference in enumerate(proof["References"], start=1):
                    expected.append(
                        {
                            "pointer": f"{row_pointer}/Proofs/{proof_ordinal - 1}/References/{ref_ordinal - 1}",
                            "value": reference,
                            "disposition": "represented",
                            "tei_target": f"#{proof_id}-ref-{ref_ordinal:03d}",
                        }
                    )
    return expected


def _resolve_pointer(source: object, pointer: str) -> object:
    current = source
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise ValueError(f"pointer traverses scalar: {pointer}")
    return current


def _expected_pointers(source: Mapping[str, object]) -> set[str]:
    pointers: set[str] = set()

    def visit(value: object, pointer: str) -> None:
        if isinstance(value, dict):
            if not value:
                pointers.add(pointer)
                return
            for key, item in value.items():
                token = key.replace("~", "~0").replace("/", "~1")
                visit(item, f"{pointer}/{token}")
        elif isinstance(value, list):
            if not value:
                pointers.add(pointer)
                return
            for index, item in enumerate(value):
                visit(item, f"{pointer}/{index}")
        else:
            pointers.add(pointer)

    visit(source, "")
    return pointers


def _key_counts(value: object, counts: dict[str, int]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            counts[key] = counts.get(key, 0) + 1
            _key_counts(item, counts)
    elif isinstance(value, list):
        for item in value:
            _key_counts(item, counts)


def _schema(repository_root: Path) -> etree.XMLSchema:
    return etree.XMLSchema(
        etree.parse(
            str(
                repository_root
                / "ocd_kernel"
                / "tei"
                / "vendor"
                / "xsd"
                / "tei_all.xsd"
            )
        )
    )


def _inventory(root: Path, expected_files: frozenset[str]) -> list[dict[str, object]]:
    """Enumerate every candidate entry and require one exact regular-file topology."""

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
    if observed_directories != EXPECTED_DIRECTORIES:
        raise ValueError("candidate directory set drift")
    if set(observed_files) != expected_files:
        raise ValueError("candidate file set drift")
    return [
        {
            "path": relative,
            "bytes": len(observed_files[relative]),
            "sha256": _sha(observed_files[relative]),
        }
        for relative in sorted(observed_files)
    ]


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
    _key_counts(source, key_counts)
    proofs = [proof for row in rows for proof in row.get("Proofs", [])]
    return {
        "accountable_leaf_count": len(_expected_pointers(source)),
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
    if not _json_equal(
        dict(primary),
        _canonical_value({key: metadata[key] for key in PRIMARY_METADATA_KEYS}),
    ):
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


def _verify_packet_and_source(
    repository_root: Path,
    work_id: str,
    census_indexes: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object], bytes]:
    if census_indexes is None:
        _, _, census_indexes = _retained_member_census(repository_root)
    packet_bytes = (
        repository_root / "sources" / work_id / "LIB-062.packet.json"
    ).read_bytes()
    packet = _strict_json(packet_bytes, f"{work_id} packet")
    if set(packet) != PACKET_KEYS:
        raise ValueError(f"{work_id} packet key set drift")
    if not _json_equal(
        packet.get("contract"), "ocd-lib062-source-packet-v1"
    ) or not _json_equal(packet.get("work_id"), work_id):
        raise ValueError(f"{work_id} packet identity drift")
    authority = packet.get("authority")
    if not isinstance(authority, dict) or not isinstance(authority.get("path"), str):
        raise ValueError(f"{work_id} authority invalid")
    _require_keys(
        authority,
        {
            "disposition",
            "path",
            "raw_bytes",
            "raw_sha256",
            "normalized_utf8_bytes",
            "normalized_utf8_sha256",
        },
        f"{work_id} authority",
    )
    authority_rows = census_indexes["authorities"]
    assert isinstance(authority_rows, Mapping)
    census_authority = authority_rows.get(work_id)
    if not isinstance(census_authority, Mapping) or not _json_equal(
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
    content = _regular_bytes(
        resolve_repo_path(repository_root, authority["path"]),
        f"{work_id} retained authority",
    )
    normalized = _normalized_utf8(content)
    if not _json_equal(
        [len(content), _sha(content), len(normalized), _sha(normalized)],
        [
            authority.get("raw_bytes"),
            authority.get("raw_sha256"),
            authority.get("normalized_utf8_bytes"),
            authority.get("normalized_utf8_sha256"),
        ],
    ):
        raise ValueError(f"{work_id} source hash drift")
    source = _strict_json(content, f"{work_id} source")
    if list(source) != ["Metadata", "Data"]:
        raise ValueError(f"{work_id} source top-level drift")
    _validate_packet_semantics(packet, source, work_id)
    terms = packet.get("terms_evidence")
    if not isinstance(terms, dict) or not isinstance(terms.get("path"), str):
        raise ValueError(f"{work_id} terms evidence invalid")
    _require_keys(
        terms,
        {"disposition", "path", "raw_bytes", "raw_sha256"},
        f"{work_id} terms evidence",
    )
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
    terms_bytes = _regular_bytes(
        resolve_repo_path(repository_root, terms["path"]), f"{work_id} terms evidence"
    )
    if not _json_equal(len(terms_bytes), terms.get("raw_bytes")) or not _json_equal(
        _sha(terms_bytes), terms.get("raw_sha256")
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
        if (
            not isinstance(witness, dict)
            or witness.get("disposition")
            != "excluded-adjacent-witness-no-human-source-choice"
        ):
            raise ValueError(f"{work_id} adjacent witness disposition drift")
        _require_keys(
            witness,
            {
                "disposition",
                "path",
                "raw_bytes",
                "raw_sha256",
                "normalized_utf8_bytes",
                "normalized_utf8_sha256",
            },
            f"{work_id} adjacent witness",
        )
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
        witness_bytes = _regular_bytes(
            resolve_repo_path(repository_root, str(witness["path"])),
            f"{work_id} adjacent witness",
        )
        witness_normalized = _normalized_utf8(witness_bytes)
        if not _json_equal(
            [
                len(witness_bytes),
                _sha(witness_bytes),
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
            raise ValueError(f"{work_id} adjacent witness hash drift")
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
    expected = census.get("members")
    if (
        not isinstance(expected, list)
        or len(expected) != 61
        or [item.get("path") for item in expected if isinstance(item, dict)]
        != sorted(item.get("path") for item in expected if isinstance(item, dict))
    ):
        raise ValueError("retained-member census order drift")
    for member in expected:
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
    authority_names = {
        "1695_baptist_catechism.json": "1695-baptist-catechism",
        "catechism_for_young_children.json": "catechism-for-young-children",
        "exposition_of_the_assemblies_catechism.json": "exposition-of-the-assemblies-catechism",
        "heidelberg_catechism.json": "heidelberg-catechism",
        "keachs_catechism.json": "keachs-catechism",
        "matthew_henrys_scripture_catechism.json": "matthew-henrys-scripture-catechism",
        "puritan_catechism.json": "puritan-catechism",
        "shorter_catechism_explained.json": "shorter-catechism-explained",
        "westminster_larger_catechism.json": "westminster-larger-catechism",
    }
    for logical_root in (
        "raw/Creeds.json/creeds",
        "raw/TheologAI/data/historical-documents",
    ):
        physical = resolve_repo_path(repository_root, logical_root)
        for path in sorted(physical.iterdir(), key=lambda item: item.name):
            raw = _regular_bytes(
                path, f"protected census member {logical_root}/{path.name}"
            )
            item: dict[str, object] = {
                "path": f"{logical_root}/{path.name}",
                "bytes": len(raw),
                "raw_sha256": _sha(raw),
            }
            if logical_root.endswith("creeds"):
                if path.name in authority_names:
                    item.update(
                        disposition="included-authority",
                        work_id=authority_names[path.name],
                    )
                else:
                    item["disposition"] = "excluded-outside-LIB-062-assigned-scope"
            elif path.name in {
                "heidelberg-catechism.json",
                "westminster-larger-catechism.json",
            }:
                item.update(
                    disposition="excluded-adjacent-witness-no-human-source-choice",
                    related_work_id=path.stem,
                )
            else:
                item["disposition"] = "excluded-unrelated-to-LIB-062-assigned-scope"
            observed.append(item)
    terms = _regular_bytes(
        resolve_repo_path(repository_root, "raw/Creeds.json/README.md"),
        "protected terms evidence",
    )
    observed.append(
        {
            "path": "raw/Creeds.json/README.md",
            "bytes": len(terms),
            "raw_sha256": _sha(terms),
            "disposition": "included-terms-evidence",
        }
    )
    observed.sort(key=lambda item: str(item["path"]))
    if not _json_equal(_canonical_value(observed), expected):
        raise ValueError("retained-member census differs from protected storage")
    for directory in protected:
        logical_root = directory["path"]
        rows = [
            item
            for item in observed
            if str(item["path"]).startswith(f"{logical_root}/")
        ]
        manifest = "\n".join(
            f"{str(item['path'])[len(logical_root) + 1 :]}\t{item['bytes']}\t{item['raw_sha256']}"
            for item in rows
        ).encode("utf-8")
        if not _json_equal(
            [len(rows), sum(int(item["bytes"]) for item in rows), _sha(manifest)],
            [directory["file_count"], directory["bytes"], directory["manifest_sha256"]],
        ):
            raise ValueError(f"protected directory inventory drift: {logical_root}")
    terms_binding = terms_envelope
    if not isinstance(terms_binding, dict) or not _json_equal(
        [terms_binding.get("bytes"), terms_binding.get("raw_sha256")],
        [len(terms), _sha(terms)],
    ):
        raise ValueError("retained terms inventory drift")
    authorities: dict[str, dict[str, object]] = {}
    witnesses: dict[str, list[dict[str, object]]] = {
        work_id: [] for work_id in WORK_IDS
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
    if set(authorities) != set(WORK_IDS) or len(terms_rows) != 1:
        raise ValueError("retained-member disposition index drift")
    for rows in witnesses.values():
        rows.sort(key=lambda item: str(item["path"]))
    if {work_id: len(rows) for work_id, rows in witnesses.items()} != {
        work_id: int(
            work_id in {"heidelberg-catechism", "westminster-larger-catechism"}
        )
        for work_id in WORK_IDS
    }:
        raise ValueError("retained-member adjacent witness index drift")
    return (
        census,
        content,
        {"authorities": authorities, "terms": terms_rows[0], "witnesses": witnesses},
    )


def _require_keys(record: Mapping[str, object], keys: set[str], label: str) -> None:
    if set(record) != keys:
        raise ValueError(f"{label} key set drift")


def _expected_readme(repository_root: Path) -> bytes:
    readmes = [
        _normalized_utf8(
            _regular_bytes(
                repository_root / "sources" / work_id / "LIB-062.README.md",
                f"{work_id} source-local attribution README",
            )
        )
        for work_id in WORK_IDS
    ]
    return b"# LIB-062 source attribution bundle\n\n" + b"\n\n---\n\n".join(readmes)


def _validate_closure_record(
    record: Mapping[str, object], expected_entry: str, label: str
) -> None:
    _require_keys(record, {"contract", "entry", "sha256", "members"}, label)
    members = record.get("members")
    if isinstance(members, list):
        paths: list[str] = []
        for member in members:
            if not isinstance(member, dict) or set(member) != {
                "path",
                "bytes",
                "sha256",
            }:
                raise ValueError(f"{label} member envelope drift")
            path = member.get("path")
            size = member.get("bytes")
            digest = member.get("sha256")
            if (
                not isinstance(path, str)
                or type(size) is not int
                or size < 0
                or not isinstance(digest, str)
                or len(digest) != 64
            ):
                raise ValueError(f"{label} member identity drift")
            paths.append(path)
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError(f"{label} member order drift")
    if (
        record.get("contract") != "ocd-lib062-import-closure-v1"
        or record.get("entry") != expected_entry
        or not isinstance(members, list)
        or not _json_equal(record.get("sha256"), _closure_digest(members))
    ):
        raise ValueError(f"{label} identity drift")


def _validate_manifest_package(candidate_root: Path) -> dict[str, object]:
    """Pure sealed-package validator used by both finalize and verify-only."""

    package_inventory = _inventory(candidate_root, PACKAGE_FILES)
    manifest_bytes = _regular_bytes(
        candidate_root / "manifest.json", "candidate manifest"
    )
    manifest = _strict_json(manifest_bytes, "candidate manifest")
    _require_keys(
        manifest,
        {
            "contract",
            "ticket",
            "status",
            "publication",
            "work_count",
            "tei_count",
            "member_count",
            "members",
        },
        "candidate manifest",
    )
    member_inventory = [
        item for item in package_inventory if item["path"] != "manifest.json"
    ]
    if manifest_bytes != _canonical(manifest):
        raise ValueError("candidate package add/remove/reformat drift")
    expected_manifest = {
        "contract": "ocd-lib062-candidate-package-v1",
        "ticket": "LIB-062",
        "status": "nonaccepted",
        "publication": "not_ready",
        "work_count": 9,
        "tei_count": 9,
        "member_count": 34,
        "members": member_inventory,
    }
    if not _json_equal(manifest, _canonical_value(expected_manifest)):
        raise ValueError("candidate manifest identity or member drift")

    producer_closure = _strict_json(
        _regular_bytes(
            candidate_root / "evidence/producer-import-closure.json", "producer closure"
        ),
        "producer closure",
    )
    oracle_closure = _strict_json(
        _regular_bytes(
            candidate_root / "evidence/oracle-import-closure.json", "oracle closure"
        ),
        "oracle closure",
    )
    _validate_closure_record(
        producer_closure,
        "build/tei/lib062_json_catechisms_reconstruction.py",
        "producer closure",
    )
    _validate_closure_record(
        oracle_closure,
        "build/tei/lib062_json_catechisms_oracle.py",
        "oracle closure",
    )
    result_bytes = _regular_bytes(
        candidate_root / "evidence/oracle-result.json", "oracle result"
    )
    result = _strict_json(result_bytes, "oracle result")
    _require_keys(
        result,
        {
            "contract",
            "status",
            "technical_acceptance",
            "human_acceptance",
            "publication",
            "work_count",
            "adjacent_witnesses",
            "producer_import_closure_sha256",
            "oracle_import_closure_sha256",
            "validated_payload_sha256",
            "findings",
        },
        "oracle result",
    )
    pre_result_inventory = [
        item
        for item in member_inventory
        if item["path"] != "evidence/oracle-result.json"
    ]
    expected_result = {
        "contract": "ocd-lib062-independent-oracle-result-v1",
        "status": "pass",
        "technical_acceptance": "not_claimed",
        "human_acceptance": "not_performed",
        "publication": "not_ready",
        "work_count": 9,
        "adjacent_witnesses": [
            {
                "work_id": "heidelberg-catechism",
                "disposition": "excluded-adjacent-witness-no-human-source-choice",
            },
            {
                "work_id": "westminster-larger-catechism",
                "disposition": "excluded-adjacent-witness-no-human-source-choice",
            },
        ],
        "producer_import_closure_sha256": producer_closure["sha256"],
        "oracle_import_closure_sha256": oracle_closure["sha256"],
        "validated_payload_sha256": _sha(_canonical(pre_result_inventory)),
        "findings": [],
    }
    if result_bytes != _canonical(result) or not _json_equal(
        result, _canonical_value(expected_result)
    ):
        raise ValueError("oracle result identity or validated payload drift")
    return manifest


def _executing_repository_root(repository_root: Path | None) -> Path:
    executing_root = Path(__file__).resolve(strict=True).parents[2]
    if (
        repository_root is not None
        and repository_root.resolve(strict=True) != executing_root
    ):
        raise ValueError(
            "verify-only repository root is not the executing oracle checkout"
        )
    return executing_root


def _validate_current_closures(repository_root: Path, candidate_root: Path) -> None:
    producer_record = _strict_json(
        (candidate_root / "evidence/producer-import-closure.json").read_bytes(),
        "producer closure",
    )
    oracle_record = _strict_json(
        (candidate_root / "evidence/oracle-import-closure.json").read_bytes(),
        "oracle closure",
    )
    _validate_closure_record(
        producer_record,
        "build/tei/lib062_json_catechisms_reconstruction.py",
        "producer closure",
    )
    _validate_closure_record(
        oracle_record,
        "build/tei/lib062_json_catechisms_oracle.py",
        "oracle closure",
    )
    current_producer = repository_import_closure(
        repository_root,
        repository_root / "build/tei/lib062_json_catechisms_reconstruction.py",
    )
    current_oracle = repository_import_closure(repository_root, Path(__file__))
    expected_producer_record = {
        "contract": "ocd-lib062-import-closure-v1",
        "entry": "build/tei/lib062_json_catechisms_reconstruction.py",
        "sha256": _closure_digest(current_producer),
        "members": current_producer,
    }
    if not _json_equal(producer_record, _canonical_value(expected_producer_record)):
        raise ValueError(
            "producer closure is not anchored to current executing checkout"
        )
    expected_oracle_record = {
        "contract": "ocd-lib062-import-closure-v1",
        "entry": "build/tei/lib062_json_catechisms_oracle.py",
        "sha256": _closure_digest(current_oracle),
        "members": current_oracle,
    }
    if not _json_equal(oracle_record, _canonical_value(expected_oracle_record)):
        raise ValueError("oracle closure is not anchored to current executing checkout")
    if "build/tei/lib062_json_catechisms_reconstruction.py" in {
        str(member["path"]) for member in current_oracle
    }:
        raise ValueError("oracle closure must exclude producer")


def finalize(repository_root: Path, candidate_root: Path) -> dict[str, object]:
    repository_root = repository_root.resolve(strict=True)
    candidate_root = _guard_candidate_destination(repository_root, candidate_root)
    _inventory(candidate_root, PRODUCER_STAGE_FILES)
    schema = _schema(repository_root)
    _, census_bytes, census_indexes = _retained_member_census(repository_root)
    if (
        candidate_root / "evidence/retained-member-census.json"
    ).read_bytes() != census_bytes:
        raise ValueError("candidate retained-member census drift")
    if (candidate_root / "README.source.md").read_bytes() != _expected_readme(
        repository_root
    ):
        raise ValueError("deterministic source attribution README drift")

    source_bindings = _strict_json(
        (candidate_root / "evidence/source-bindings.json").read_bytes(),
        "source bindings",
    )
    _require_keys(source_bindings, {"contract", "sources"}, "source bindings")
    if source_bindings.get("contract") != "ocd-lib062-source-bindings-v1":
        raise ValueError("source bindings contract drift")
    observed_bindings: list[dict[str, object]] = []
    for work_id in WORK_IDS:
        packet, source, source_bytes = _verify_packet_and_source(
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
        expected_tei = _expected_tei(work_id, packet, source)
        actual_tei = (candidate_root / "tei" / f"{work_id}.tei.xml").read_bytes()
        if actual_tei != expected_tei:
            raise ValueError(f"{work_id} complete TEI projection drift")
        document = etree.fromstring(actual_tei)
        if not schema.validate(etree.ElementTree(document)):
            raise ValueError(f"{work_id} TEI P5 failure: {schema.error_log.last_error}")

        accounting_path = candidate_root / "source-accounting" / f"{work_id}.json"
        accounting_bytes = accounting_path.read_bytes()
        accounting = _strict_json(accounting_bytes, f"{work_id} accounting")
        _require_keys(
            accounting,
            {
                "contract",
                "work_id",
                "source_member_disposition",
                "top_level_keys",
                "recursive_key_counts",
                "data_record_count",
                "represented_leaf_count",
                "omitted_leaf_count",
                "duplicate_leaf_count",
                "crosswalk",
            },
            f"{work_id} accounting",
        )
        crosswalk = accounting.get("crosswalk")
        if (
            not _json_equal(
                accounting.get("contract"), "ocd-lib062-source-accountability-v1"
            )
            or not _json_equal(accounting.get("work_id"), work_id)
            or not _json_equal(
                accounting.get("source_member_disposition"),
                "included in full as sole authority",
            )
            or not isinstance(crosswalk, list)
        ):
            raise ValueError(f"{work_id} accounting contract drift")
        if (
            not _json_equal(accounting.get("omitted_leaf_count"), 0)
            or not _json_equal(accounting.get("duplicate_leaf_count"), 0)
            or not _json_equal(accounting.get("represented_leaf_count"), len(crosswalk))
        ):
            raise ValueError(f"{work_id} accounting count drift")
        expected_crosswalk = _expected_crosswalk(work_id, source)
        if not _json_equal(crosswalk, _canonical_value(expected_crosswalk)):
            raise ValueError(f"{work_id} exact ordered accountability crosswalk drift")
        key_counts: dict[str, int] = {}
        _key_counts(source, key_counts)
        if (
            not _json_equal(
                accounting.get("recursive_key_counts"), _canonical_value(key_counts)
            )
            or not _json_equal(accounting.get("top_level_keys"), ["Metadata", "Data"])
            or not _json_equal(accounting.get("data_record_count"), len(source["Data"]))
        ):
            raise ValueError(f"{work_id} source accounting census drift")
        pointers: set[str] = set()
        target_ids = {node.get(XML_ID) for node in document.iter() if node.get(XML_ID)}
        for observation in crosswalk:
            if not isinstance(observation, dict):
                raise ValueError(f"{work_id} accounting observation drift")
            _require_keys(
                observation,
                {"pointer", "value", "disposition", "tei_target"},
                f"{work_id} accounting observation",
            )
            if not _json_equal(observation.get("disposition"), "represented"):
                raise ValueError(f"{work_id} accounting observation drift")
            pointer = observation.get("pointer")
            target = observation.get("tei_target")
            if (
                not isinstance(pointer, str)
                or pointer in pointers
                or not isinstance(target, str)
                or not target.startswith("#")
            ):
                raise ValueError(
                    f"{work_id} duplicate or invalid accountability attachment"
                )
            pointers.add(pointer)
            if not _json_equal(
                _resolve_pointer(source, pointer), observation.get("value")
            ):
                raise ValueError(f"{work_id} accountability value drift")
            if target[1:] not in target_ids:
                raise ValueError(f"{work_id} accountability target drift")
        expected_pointers = _expected_pointers(source)
        if pointers != expected_pointers or not _json_equal(
            len(crosswalk), len(expected_pointers)
        ):
            raise ValueError(f"{work_id} complete accountability pointer set drift")
        profile = packet.get("profile")
        rows = source["Data"]
        assert isinstance(rows, list)
        proofs = [proof for row in rows for proof in row.get("Proofs", [])]
        observed_profile = {
            "data_record_count": len(rows),
            "subquestion_count": sum(len(row.get("SubQuestions", [])) for row in rows),
            "proof_group_count": len(proofs),
            "reference_count": sum(len(proof["References"]) for proof in proofs),
            "question_with_proofs_count": sum(
                "QuestionWithProofs" in row for row in rows
            ),
            "proofless_record_count": sum("Proofs" not in row for row in rows),
            "recursive_key_counts": key_counts,
            "row_key_shapes": [
                list(shape) for shape in sorted({tuple(row) for row in rows})
            ],
            "metadata_keys": list(source["Metadata"]),
            "accountable_leaf_count": len(expected_pointers),
        }
        if (
            not isinstance(profile, dict)
            or set(profile) != set(observed_profile)
            or not _json_equal(profile, _canonical_value(observed_profile))
        ):
            raise ValueError(f"{work_id} profile census drift")

        report = _strict_json(
            (
                candidate_root / "validation" / f"{work_id}.producer-validation.json"
            ).read_bytes(),
            f"{work_id} producer report",
        )
        _require_keys(
            report,
            {
                "contract",
                "status",
                "work_id",
                "tei_p5",
                "structural_policy",
                "source_accounting",
                "source_raw_sha256",
                "tei_sha256",
                "accounting_sha256",
            },
            f"{work_id} producer report",
        )
        expected_report = {
            "contract": "ocd-lib062-producer-validation-v1",
            "status": "pass",
            "work_id": work_id,
            "tei_p5": "pass",
            "structural_policy": "pass",
            "source_accounting": "pass",
            "source_raw_sha256": _sha(source_bytes),
            "tei_sha256": _sha(actual_tei),
            "accounting_sha256": _sha(accounting_bytes),
        }
        if not _json_equal(report, _canonical_value(expected_report)):
            raise ValueError(f"{work_id} producer report stale")
        observed_bindings.append(
            {
                "work_id": work_id,
                "packet_sha256": _sha(
                    (
                        repository_root / "sources" / work_id / "LIB-062.packet.json"
                    ).read_bytes()
                ),
                "source_raw_sha256": _sha(source_bytes),
                "source_normalized_utf8_sha256": _sha(_normalized_utf8(source_bytes)),
            }
        )

    if not _json_equal(
        source_bindings,
        _canonical_value(
            {"contract": "ocd-lib062-source-bindings-v1", "sources": observed_bindings}
        ),
    ):
        raise ValueError("source bindings stale")
    review_state = _strict_json(
        (candidate_root / "evidence/review-state.json").read_bytes(), "review state"
    )
    expected_review_state = {
        "contract": "ocd-lib062-review-state-v1",
        "ticket": "LIB-062",
        "technical_acceptance": "not_claimed",
        "human_acceptance": "not_performed",
        "publication": "not_ready",
        "works": list(WORK_IDS),
        "unresolved": REVIEW_LIMITATIONS,
    }
    _require_keys(review_state, set(expected_review_state), "review state")
    if not _json_equal(review_state, _canonical_value(expected_review_state)):
        raise ValueError("review state drift")

    producer_closure_record = _strict_json(
        (candidate_root / "evidence/producer-import-closure.json").read_bytes(),
        "producer closure",
    )
    _validate_closure_record(
        producer_closure_record,
        "build/tei/lib062_json_catechisms_reconstruction.py",
        "producer closure",
    )
    producer_closure = repository_import_closure(
        repository_root,
        repository_root / "build/tei/lib062_json_catechisms_reconstruction.py",
    )
    if not _json_equal(
        producer_closure_record["members"], _canonical_value(producer_closure)
    ) or not _json_equal(
        producer_closure_record["sha256"], _closure_digest(producer_closure)
    ):
        raise ValueError("producer recursive import closure drift")

    oracle_closure = repository_import_closure(repository_root, Path(__file__))
    oracle_closure_record = {
        "contract": "ocd-lib062-import-closure-v1",
        "entry": "build/tei/lib062_json_catechisms_oracle.py",
        "sha256": _closure_digest(oracle_closure),
        "members": oracle_closure,
    }
    (candidate_root / "evidence/oracle-import-closure.json").write_bytes(
        _canonical(oracle_closure_record)
    )
    pre_result_members = _inventory(candidate_root, PRE_RESULT_FILES)
    result = {
        "contract": "ocd-lib062-independent-oracle-result-v1",
        "status": "pass",
        "technical_acceptance": "not_claimed",
        "human_acceptance": "not_performed",
        "publication": "not_ready",
        "work_count": 9,
        "adjacent_witnesses": [
            {
                "work_id": "heidelberg-catechism",
                "disposition": "excluded-adjacent-witness-no-human-source-choice",
            },
            {
                "work_id": "westminster-larger-catechism",
                "disposition": "excluded-adjacent-witness-no-human-source-choice",
            },
        ],
        "producer_import_closure_sha256": _closure_digest(producer_closure),
        "oracle_import_closure_sha256": _closure_digest(oracle_closure),
        "validated_payload_sha256": _sha(_canonical(pre_result_members)),
        "findings": [],
    }
    (candidate_root / "evidence/oracle-result.json").write_bytes(_canonical(result))
    members = _inventory(candidate_root, SEALED_MEMBER_FILES)
    manifest = {
        "contract": "ocd-lib062-candidate-package-v1",
        "ticket": "LIB-062",
        "status": "nonaccepted",
        "publication": "not_ready",
        "work_count": 9,
        "tei_count": 9,
        "member_count": 34,
        "members": members,
    }
    (candidate_root / "manifest.json").write_bytes(_canonical(manifest))
    return _validate_manifest_package(candidate_root)


def verify_sealed(
    candidate_root: Path, repository_root: Path | None = None
) -> dict[str, object]:
    if _lexical_is_reparse(candidate_root):
        raise ValueError(
            "verify-only candidate root must be a non-reparse lexical path"
        )
    resolved_candidate = candidate_root.resolve(strict=True)
    manifest = _validate_manifest_package(resolved_candidate)
    executing_root = _executing_repository_root(repository_root)
    _validate_current_closures(executing_root, resolved_candidate)
    return manifest


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify_sealed(args.candidate_root, args.repository_root)
    else:
        finalize(args.repository_root, args.candidate_root)
        verify_sealed(args.candidate_root, args.repository_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
