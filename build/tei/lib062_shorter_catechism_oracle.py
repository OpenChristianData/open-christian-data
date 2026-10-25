"""Independent source/TEI oracle for the retained shorter catechism JSON."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path
import platform
import sys
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    _validation_authority_bindings,
)
from ocd_kernel.tei.validate import compiled_schema


WORK_ID = "shorter-catechism-explained"
SOURCE_ID = "creeds-json-lib062-shorter-catechism-explained-retained-json"
ORACLE_ID = "ocd-creeds-json-lib062-shorter-catechism-explained-independent-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NS = {"tei": TEI_NS}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _runtime() -> str:
    return (
        f"{platform.python_implementation()} {platform.python_version()} "
        f"({Path(sys.executable).resolve(strict=True)})"
    )


def _strict_json(content: bytes, label: str) -> object:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    return json.loads(content.decode("utf-8"), object_pairs_hook=reject)


def _json_equal(left: object, right: object) -> bool:
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


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _accountable_leaves(value: object, pointer: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        if not value:
            return [(pointer, {})]
        result: list[tuple[str, object]] = []
        for key, child in value.items():
            result.extend(
                _accountable_leaves(child, f"{pointer}/{_pointer_token(key)}")
            )
        return result
    if isinstance(value, list):
        if not value:
            return [(pointer, [])]
        result = []
        for index, child in enumerate(value):
            result.extend(_accountable_leaves(child, f"{pointer}/{index}"))
        return result
    return [(pointer, value)]


def _key_counts(value: object, counts: dict[str, int]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            counts[key] = counts.get(key, 0) + 1
            _key_counts(child, counts)
    elif isinstance(value, list):
        for child in value:
            _key_counts(child, counts)


def _profile(source: Mapping[str, Any]) -> dict[str, object]:
    metadata = source["Metadata"]
    rows = source["Data"]
    proofs = [proof for row in rows for proof in row.get("Proofs", [])]
    counts: dict[str, int] = {}
    _key_counts(source, counts)
    return {
        "accountable_leaf_count": len(_accountable_leaves(source)),
        "data_record_count": len(rows),
        "metadata_keys": list(metadata),
        "proof_group_count": len(proofs),
        "proofless_record_count": sum("Proofs" not in row for row in rows),
        "question_with_proofs_count": sum("QuestionWithProofs" in row for row in rows),
        "recursive_key_counts": {key: counts[key] for key in sorted(counts)},
        "reference_count": sum(len(proof["References"]) for proof in proofs),
        "row_key_shapes": [list(shape) for shape in sorted({tuple(row) for row in rows})],
        "subquestion_count": sum(len(row.get("SubQuestions", [])) for row in rows),
    }


def _crosswalk(source: Mapping[str, Any]) -> list[dict[str, object]]:
    metadata = source["Metadata"]
    rows = source["Data"]
    result: list[dict[str, object]] = []

    def add(pointer: str, value: object, target: str) -> None:
        result.append(
            {
                "disposition": "represented",
                "pointer": pointer,
                "tei_target": target,
                "value": value,
            }
        )

    for position, (key, value) in enumerate(metadata.items(), start=1):
        target = f"#lib062-{WORK_ID}-metadata-{position:02d}"
        for pointer, leaf in _accountable_leaves(value, f"/Metadata/{_pointer_token(key)}"):
            add(pointer, leaf, target)
    for row_index, row in enumerate(rows):
        row_id = f"lib062-{WORK_ID}-row-{row_index + 1:04d}"
        add(f"/Data/{row_index}/Number", row["Number"], f"#{row_id}-number")
        for key, kind in (
            ("Question", "question"),
            ("QuestionWithProofs", "question-with-proofs"),
            ("Answer", "answer"),
            ("AnswerWithProofs", "answer-with-proofs"),
        ):
            if key in row:
                add(f"/Data/{row_index}/{key}", row[key], f"#{row_id}-{kind}")
        if "SubQuestions" in row:
            subs = row["SubQuestions"]
            if not subs:
                add(f"/Data/{row_index}/SubQuestions", subs, f"#{row_id}-subquestions-empty")
            else:
                for sub_index, sub in enumerate(subs):
                    sub_id = f"{row_id}-sub-{sub_index + 1:04d}"
                    for key, kind in (
                        ("Number", "number"),
                        ("Question", "question"),
                        ("Answer", "answer"),
                    ):
                        target = f"#{sub_id}-{kind}"
                        add(
                            f"/Data/{row_index}/SubQuestions/{sub_index}/{key}",
                            sub[key],
                            target,
                        )
        if "Proofs" in row:
            proofs = row["Proofs"]
            if not proofs:
                add(f"/Data/{row_index}/Proofs", proofs, f"#{row_id}-proofs-empty")
            else:
                for proof_index, proof in enumerate(proofs):
                    proof_id = f"{row_id}-proof-{proof_index + 1:03d}"
                    add(
                        f"/Data/{row_index}/Proofs/{proof_index}/Id",
                        proof["Id"],
                        f"#{proof_id}-id",
                    )
                    for ref_index, reference in enumerate(proof["References"]):
                        add(
                            f"/Data/{row_index}/Proofs/{proof_index}/References/{ref_index}",
                            reference,
                            f"#{proof_id}-ref-{ref_index + 1:03d}",
                        )
    return result


def _basic(
    node: etree._Element | None,
    *,
    tag: str,
    attributes: Mapping[str, str],
    text: str | None,
    location: str,
    findings: list[str],
) -> None:
    if node is None or node.tag != f"{{{TEI_NS}}}{tag}":
        findings.append(f"{location}: expected tei:{tag}")
        return
    if dict(node.attrib) != dict(attributes):
        findings.append(f"{location}: attributes differ")
    if node.text != text:
        findings.append(f"{location}: text differs")


def _check_source_and_tei(
    source: Mapping[str, Any],
    tei_bytes: bytes,
    profile: Mapping[str, Any],
    accountability: Mapping[str, Any],
    findings: list[str],
) -> None:
    try:
        root = etree.fromstring(tei_bytes)
    except (etree.XMLSyntaxError, ValueError) as error:
        findings.append(f"TEI is not parseable: {error}")
        return
    if not compiled_schema().validate(etree.ElementTree(root)):
        findings.extend(f"TEI P5: {error}" for error in compiled_schema().error_log)
    expected_profile = profile["profile"]
    observed_profile = _profile(source)
    if not _json_equal(observed_profile, expected_profile):
        findings.append("source profile census differs from bound profile")
    expected_crosswalk = _crosswalk(source)
    if not _json_equal(accountability.get("crosswalk"), expected_crosswalk):
        findings.append("source accountability crosswalk differs from independent source traversal")

    all_ids = [node.get(XML_ID) for node in root.iter() if node.get(XML_ID)]
    if len(all_ids) != len(set(all_ids)):
        findings.append("TEI xml:id values are duplicated")

    expected_root_id = f"lib062-{WORK_ID}"
    _basic(root, tag="TEI", attributes={XML_ID: expected_root_id}, text=None, location="TEI", findings=findings)
    title = source["Metadata"]["Title"]
    authors = source["Metadata"]["Authors"]
    title_nodes = root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS)
    if len(title_nodes) != 1 or title_nodes[0].text != str(title):
        findings.append("title statement differs from retained metadata")
    author_nodes = root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", namespaces=NS)
    if [node.text for node in author_nodes] != [str(value) for value in authors]:
        findings.append("author sequence differs from retained metadata")
    bibl = root.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl", namespaces=NS)
    if len(bibl) != 1:
        findings.append("source bibl is missing or duplicated")
    else:
        ptr = bibl[0].find(f"{{{TEI_NS}}}ptr")
        if ptr is None or ptr.get("target") != "raw/Creeds.json/creeds/shorter_catechism_explained.json":
            findings.append("source bibl path differs from retained source")
        raw_id = bibl[0].xpath("./tei:idno[@type='sha256-raw']", namespaces=NS)
        if len(raw_id) != 1 or raw_id[0].text != "90aea411d973c7c43af89df2520f8f08c57d97643f33a135c5473aa931479b7d":
            findings.append("source bibl raw digest differs from retained source")

    metadata_items = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:list[@type='source-metadata']/tei:item",
        namespaces=NS,
    )
    if len(metadata_items) != len(source["Metadata"]):
        findings.append("metadata item count differs from retained metadata")
    else:
        for (key, value), item in zip(source["Metadata"].items(), metadata_items, strict=True):
            if item.get("n") != key:
                findings.append(f"metadata key order differs at {key}")
            try:
                decoded = _strict_json((item.text or "").encode("utf-8"), f"metadata {key}")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                findings.append(f"metadata {key} is not encoded JSON: {error}")
            else:
                if not _json_equal(decoded, value):
                    findings.append(f"metadata value differs at {key}")

    corpus = root.xpath("./tei:text/tei:body/tei:div[@type='catechism']", namespaces=NS)
    rows = source["Data"]
    if len(corpus) != 1:
        findings.append("catechism body is missing or duplicated")
        return
    units = corpus[0].xpath("./tei:div[@type='question-unit']", namespaces=NS)
    if len(units) != len(rows):
        findings.append("question-unit count differs from retained Data")
    prefix = min(len(units), len(rows))
    for index in range(prefix):
        row = rows[index]
        unit = units[index]
        row_id = f"lib062-{WORK_ID}-row-{index + 1:04d}"
        _basic(
            unit,
            tag="div",
            attributes={XML_ID: row_id, "type": "question-unit", "n": str(row["Number"])},
            text=None,
            location=f"Data/{index}",
            findings=findings,
        )
        children = list(unit)
        cursor = 0

        def take(tag: str, attributes: Mapping[str, str], text: str | None, location: str) -> etree._Element | None:
            nonlocal cursor
            node = children[cursor] if cursor < len(children) else None
            _basic(node, tag=tag, attributes=attributes, text=text, location=location, findings=findings)
            cursor += 1
            return node

        take("label", {XML_ID: f"{row_id}-number", "type": "source-number"}, str(row["Number"]), f"Data/{index}/Number")
        take("p", {XML_ID: f"{row_id}-question", "ana": "#question"}, str(row["Question"]), f"Data/{index}/Question")
        take("p", {XML_ID: f"{row_id}-answer", "ana": "#answer"}, str(row["Answer"]), f"Data/{index}/Answer")
        subs = row["SubQuestions"]
        if not subs:
            take("note", {XML_ID: f"{row_id}-subquestions-empty", "type": "source-empty-array", "n": "SubQuestions"}, None, f"Data/{index}/SubQuestions")
        else:
            sublist = take("list", {XML_ID: f"{row_id}-subquestions", "type": "subquestions"}, None, f"Data/{index}/SubQuestions")
            if sublist is not None:
                items = sublist.xpath("./tei:item", namespaces=NS)
                if len(items) != len(subs):
                    findings.append(f"Data/{index}/SubQuestions item count differs")
                for sub_index, sub in enumerate(subs[: len(items)]):
                    sub_id = f"{row_id}-sub-{sub_index + 1:04d}"
                    item = items[sub_index]
                    _basic(item, tag="item", attributes={XML_ID: sub_id, "n": str(sub["Number"])}, text=None, location=f"Data/{index}/SubQuestions/{sub_index}", findings=findings)
                    item_children = list(item)
                    expected_children = (
                        ("label", {XML_ID: f"{sub_id}-number", "type": "subquestion-number"}, str(sub["Number"])),
                        ("p", {XML_ID: f"{sub_id}-question", "ana": "#subquestion-question"}, str(sub["Question"])),
                        ("p", {XML_ID: f"{sub_id}-answer", "ana": "#subquestion-answer"}, str(sub["Answer"])),
                    )
                    if len(item_children) != len(expected_children):
                        findings.append(f"Data/{index}/SubQuestions/{sub_index} child count differs")
                    for child, (tag, attrs, text) in zip(item_children, expected_children, strict=False):
                        _basic(child, tag=tag, attributes=attrs, text=text, location=f"Data/{index}/SubQuestions/{sub_index}", findings=findings)
        if cursor != len(children):
            findings.append(f"Data/{index} has unexpected TEI children")


def _module_file(root: Path, module: str) -> Path | None:
    stem = root.joinpath(*module.split("."))
    module_path = stem.with_suffix(".py")
    if module_path.is_file():
        return module_path
    initializer = stem / "__init__.py"
    return initializer if initializer.is_file() else None


def _repository_import_closure(root: Path, entry: Path) -> list[dict[str, object]]:
    pending = [entry.resolve(strict=True)]
    observed: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in observed:
            continue
        if not path.is_relative_to(root):
            raise ValueError("oracle import closure escapes repository")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if name in {"eval", "exec", "__import__", "import_module", "exec_module"}:
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
        {"path": path.relative_to(root).as_posix(), "bytes": len(path.read_bytes()), "sha256": _sha(path.read_bytes())}
        for path in sorted(observed, key=lambda item: item.relative_to(root).as_posix())
    ]


def _import_closure_sha256() -> str:
    root = Path(__file__).resolve(strict=True).parents[2]
    return _sha(_canonical(_repository_import_closure(root, Path(__file__))))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    findings: list[str] = []
    if source_manifest.record.get("source_id") != SOURCE_ID or source_manifest.record.get("work_id") != WORK_ID:
        findings.append("source manifest identity differs from ticket")
    authorities = source_manifest.record.get("authorities")
    primary = [item for item in authorities if item.get("role") == "primary-source"] if isinstance(authorities, tuple) else []
    if len(primary) != 1:
        findings.append("source manifest primary-source cardinality differs")
        source_bytes = b""
        source = {}
    else:
        authority = primary[0]
        source_path = source_manifest.repository_root / str(authority["path"])
        source_bytes = source_path.read_bytes()
        if len(source_bytes) != authority["bytes"] or _sha(source_bytes) != authority["sha256"]:
            findings.append("retained source bytes differ from manifest")
        try:
            loaded = _strict_json(source_bytes, "retained shorter catechism source")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            findings.append(f"retained source JSON is invalid: {error}")
            source = {}
        else:
            source = loaded if isinstance(loaded, dict) else {}
            if not isinstance(loaded, dict):
                findings.append("retained source is not an object")

    profile = _strict_json(source_manifest.authority_path("reconstruction-profile").read_bytes(), "reconstruction profile")
    if not isinstance(profile, dict):
        findings.append("reconstruction profile is not an object")
        profile = {"profile": {}}
    try:
        accountability_value = _strict_json(candidate.member_bytes("source-accountability.json"), "source accountability")
        provenance_value = _strict_json(candidate.member_bytes("provenance.json"), "provenance")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        findings.append(f"candidate JSON evidence is invalid: {error}")
        accountability_value, provenance_value = {}, {}
    accountability = accountability_value if isinstance(accountability_value, dict) else {}
    provenance = provenance_value if isinstance(provenance_value, dict) else {}
    tei_bytes = candidate.member_bytes("content.tei.xml")
    if source:
        _check_source_and_tei(source, tei_bytes, profile, accountability, findings)
    expected_source_member = (
        {
            "bytes": primary[0]["bytes"],
            "name": primary[0]["name"],
            "normalized_utf8_bytes": profile["source"]["normalized_utf8_bytes"],
            "normalized_utf8_sha256": profile["source"]["normalized_utf8_sha256"],
            "path": primary[0]["path"],
            "sha256": primary[0]["sha256"],
        }
        if primary and isinstance(profile.get("source"), dict)
        else None
    )
    if accountability.get("source_id") != SOURCE_ID or accountability.get("work_id") != WORK_ID:
        findings.append("accountability identity differs from source manifest")
    if expected_source_member is not None and not _json_equal(accountability.get("source_member"), expected_source_member):
        findings.append("accountability source member binding differs")
    if accountability.get("tei") != {"bytes": len(tei_bytes), "sha256": _sha(tei_bytes)}:
        findings.append("accountability TEI binding differs")
    if provenance.get("source_manifest_sha256") != source_manifest.sha256 or provenance.get("source_id") != SOURCE_ID:
        findings.append("provenance source-manifest binding differs")
    if provenance.get("ocr") != "not-used":
        findings.append("candidate provenance does not state OCR was not used")
    target_ids = {node.get(XML_ID) for node in etree.fromstring(tei_bytes).iter() if node.get(XML_ID)} if tei_bytes else set()
    crosswalk = accountability.get("crosswalk")
    if isinstance(crosswalk, list):
        for item in crosswalk:
            if isinstance(item, dict) and isinstance(item.get("tei_target"), str) and item["tei_target"].startswith("#") and item["tei_target"][1:] not in target_ids:
                findings.append(f"accountability target is absent: {item['tei_target']}")
                break
    bindings = _validation_authority_bindings(source_manifest)
    result: dict[str, object] = {
        "status": "pass" if not findings else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _import_closure_sha256(),
        "runtime": _runtime(),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        **bindings,
        "findings": sorted(set(findings)),
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
