"""Contract and mutation tests for the complete retained Adam Clarke witness."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.helloao_adam_clarke_oracle import _oracle
from build.tei.helloao_adam_clarke_reconstruction import _convert
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
RETAINED_MANIFEST = ROOT / "sources/commentaries/adam-clarke/adam-clarke.source-manifest.json"
SOURCE_MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/adam-clarke.source-manifest.json"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

BOOKS_ROOT_KEYS = ("commentary", "books")
PROFILES_ROOT_KEYS = ("commentary", "profiles")
COMMENTARY_KEYS = (
    "id",
    "name",
    "website",
    "licenseUrl",
    "licenseNotes",
    "englishName",
    "language",
    "textDirection",
    "sha256",
    "availableFormats",
    "listOfBooksApiLink",
    "listOfProfilesApiLink",
    "numberOfBooks",
    "totalNumberOfChapters",
    "totalNumberOfVerses",
    "totalNumberOfProfiles",
    "languageName",
    "languageEnglishName",
)
BOOK_KEYS = (
    "id",
    "commentaryId",
    "name",
    "commonName",
    "introduction",
    "order",
    "numberOfChapters",
    "sha256",
    "firstChapterNumber",
    "firstChapterApiLink",
    "lastChapterNumber",
    "lastChapterApiLink",
    "totalNumberOfVerses",
)
CHAPTER_ENVELOPE_KEYS = (
    "commentary",
    "book",
    "chapter",
    "thisChapterLink",
    "nextChapterApiLink",
    "previousChapterApiLink",
    "numberOfVerses",
)
CHAPTER_KEYS_WITH_INTRODUCTION = ("number", "content", "introduction")
CHAPTER_KEYS_WITHOUT_INTRODUCTION = ("number", "content")
OCCURRENCE_KEYS = ("type", "number", "content")
RUNTIME_ORACLE_CLOSURE = (
    "build/__init__.py",
    "build/tei/__init__.py",
    "build/tei/helloao_adam_clarke_oracle.py",
    "ocd_kernel/__init__.py",
    "ocd_kernel/lib/__init__.py",
    "ocd_kernel/lib/path_io.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/reconstruction/__init__.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/tei/__init__.py",
    "ocd_kernel/tei/normalization.py",
    "ocd_kernel/tei/projection_profile.py",
    "ocd_kernel/tei/validate.py",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def test_runtime_fixture_preserves_retained_inputs_and_only_updates_storage_dependencies():
    from build.tei import helloao_adam_clarke_oracle as oracle_module

    raw = RETAINED_MANIFEST.read_bytes()
    assert _sha(raw) == "3d19421ee017b2801169352fc8f4fe1412492ab67b5041ab67828481d3412a3c"
    expected = json.loads(raw)
    policy_path = next(item["path"] for item in expected["authorities"]
                       if item["name"] == "validation-policy")
    policy = json.loads((ROOT / policy_path).read_bytes())
    expected["validator"]["implementation_sha256"] = _sha(Path(oracle_module.__file__).read_bytes())
    expected["validator"]["import_closure_sha256"] = oracle_module._closure_digest(ROOT, policy)

    assert json.loads(SOURCE_MANIFEST.read_bytes()) == expected


@pytest.fixture(scope="session")
def adam_clarke_resealed_source_base(
    adam_clarke_source: SourceManifest, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """Build one isolated authority tree reused through hard-linked source variants."""

    target = tmp_path_factory.mktemp("lib078-source-base") / "repo"
    target.mkdir()
    manifest_relative = SOURCE_MANIFEST.relative_to(ROOT)
    manifest_target = target / manifest_relative
    manifest_target.parent.mkdir(parents=True)
    shutil.copy2(SOURCE_MANIFEST, manifest_target)
    for authority in adam_clarke_source.record["authorities"]:
        relative = Path(authority["path"])
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = resolve_repo_path(ROOT, relative.as_posix())
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
    implementation_paths = {
        Path("build/tei/helloao_adam_clarke_reconstruction.py"),
        *(Path(item) for item in RUNTIME_ORACLE_CLOSURE),
    }
    for relative in sorted(implementation_paths):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(ROOT / relative, destination)
        except OSError:
            shutil.copy2(ROOT / relative, destination)
    return target


def _replace_json(path: Path, value: dict[str, object]) -> bytes:
    content = _canonical(value)
    path.unlink()
    path.write_bytes(content)
    return content


def _replace_source_json_same_size(path: Path, value: dict[str, object]) -> bytes:
    expected_size = path.stat().st_size
    content = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=False
    ).encode("utf-8")
    if len(content) > expected_size:
        raise AssertionError(
            f"source mutation grew {path} by {len(content) - expected_size} bytes"
        )
    content += b" " * (expected_size - len(content))
    path.unlink()
    path.write_bytes(content)
    return content


def _resealed_source_variant(base: Path, target: Path, mutation: str) -> SourceManifest:
    shutil.copytree(base, target, copy_function=os.link)
    manifest_relative = SOURCE_MANIFEST.relative_to(ROOT)
    manifest_path = target / manifest_relative
    manifest = json.loads(manifest_path.read_bytes())
    raw_prefix = Path("raw/helloao_local/api/c/adam-clarke")
    chapter_paths = sorted((target / raw_prefix).glob("*/*.json"))
    changed: dict[str, bytes] = {}

    if mutation in {"correction-ledger-direction", "correction-receipt-path"}:
        relative = Path(
            "review/corrections/commentaries/adam-clarke/2-john.jsonl"
            if mutation == "correction-ledger-direction"
            else "review/writer-manifests/apply_correction_clarke_2_john.json"
        )
        path = target / relative
        record = json.loads(path.read_bytes())
        if mutation == "correction-ledger-direction":
            record["after_text"] = "had"
        else:
            record["allowed_field_paths"] = [
                "/data/*/layers/commentary_text/source_raw"
            ]
        changed[relative.as_posix()] = _replace_json(path, record)
    elif mutation in {"commentary-extra", "book-renamed-sha256"}:
        paths = [
            target / raw_prefix / "books.json",
            target / raw_prefix / "profiles.json",
        ]
        paths.extend(chapter_paths)
        for path in paths:
            record = json.loads(path.read_bytes())
            if mutation == "commentary-extra":
                record["commentary"]["website"] = record["commentary"]["website"][:-6]
                record["commentary"]["x"] = 0
            elif path.name != "profiles.json":
                books = (
                    record["books"] if path.name == "books.json" else [record["book"]]
                )
                for book in books:
                    book["sha25x"] = book.pop("sha256")
            changed[path.relative_to(target).as_posix()] = (
                _replace_source_json_same_size(path, record)
            )
    else:
        path = chapter_paths[0]
        record = json.loads(path.read_bytes())
        if mutation == "envelope-missing-key":
            record.pop("nextChapterApiLink")
        elif mutation == "envelope-drifted-count":
            record["numberOfVerses"] += 1
        elif mutation == "chapter-reordered-keys":
            chapter = record["chapter"]
            record["chapter"] = {
                "content": chapter["content"],
                "number": chapter["number"],
                **(
                    {"introduction": chapter["introduction"]}
                    if "introduction" in chapter
                    else {}
                ),
            }
        else:
            raise AssertionError(f"unknown source mutation {mutation}")
        changed[path.relative_to(target).as_posix()] = _replace_source_json_same_size(
            path, record
        )

    for authority in manifest["authorities"]:
        content = changed.get(authority["path"])
        if content is not None:
            authority["bytes"] = len(content)
            authority["sha256"] = _sha(content)
    _replace_json(manifest_path, manifest)
    return SourceManifest.load(manifest_path, repository_root=target)


@pytest.fixture(scope="session")
def adam_clarke_source() -> SourceManifest:
    return SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="session")
def adam_clarke_candidate(
    adam_clarke_source: SourceManifest, tmp_path_factory: pytest.TempPathFactory
):
    destination = tmp_path_factory.mktemp("lib078") / "candidate"
    candidate = reconstruct(adam_clarke_source, destination, _convert)
    report = validate(adam_clarke_source, candidate, _oracle)
    return candidate, report


def _resealed_copy(candidate: CandidatePackage, target: Path) -> Path:
    shutil.copytree(candidate.path, target)
    return target


def _reseal(target: Path, member_name: str) -> CandidatePackage:
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (target / member_name).read_bytes()
    for member in manifest["members"]:
        if member["name"] == member_name:
            member["bytes"] = len(content)
            member["sha256"] = _sha(content)
            break
    else:
        raise AssertionError(f"candidate manifest lacks {member_name}")
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(target)


def _write_tei(target: Path, root: etree._Element) -> CandidatePackage:
    name = "content.tei.xml"
    (target / name).write_bytes(
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    )
    return _reseal(target, name)


def _write_tei_document(target: Path, root: etree._Element) -> CandidatePackage:
    name = "content.tei.xml"
    (target / name).write_bytes(
        etree.tostring(
            root.getroottree(),
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        )
    )
    return _reseal(target, name)


def test_adam_clarke_manifest_binds_every_retained_member(
    adam_clarke_source: SourceManifest,
) -> None:
    authorities = adam_clarke_source.record["authorities"]
    primary = [item for item in authorities if item["role"] == "primary-source"]
    assert len(primary) == 856
    assert sum(item["bytes"] for item in primary) == 28_421_263
    paths = [item["path"] for item in primary]
    assert len(paths) == len(set(paths))
    assert "raw/helloao_local/api/c/adam-clarke/books.json" in paths
    assert "raw/helloao_local/api/c/adam-clarke/profiles.json" in paths
    assert len([path for path in paths if path.count("/") == 6]) == 854
    for authority in primary:
        path = resolve_repo_path(ROOT, authority["path"])
        content = path.read_bytes()
        assert len(content) == authority["bytes"]
        assert _sha(content) == authority["sha256"]


def test_adam_clarke_catalog_lineage_binds_all_57_exact_current_claim_pairs(
    adam_clarke_source: SourceManifest,
) -> None:
    primary = [
        item
        for item in adam_clarke_source.record["authorities"]
        if item["role"] == "primary-source"
    ]
    retained_members = [
        {
            "name": item["name"],
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in sorted(primary, key=lambda value: (value["path"], value["name"]))
    ]
    retained_digest = _sha(
        _canonical(
            {"contract": "ocd-source-member-set-v1", "members": retained_members}
        )
    )
    lineage = adam_clarke_source.record["catalog_claim_lineage"]
    claims = lineage["claims"]
    assert lineage["contract"] == "ocd-catalog-claim-lineage-v1"
    assert lineage["work_id"] == "adam-clarke"
    assert lineage["retained_source_sha256"] == retained_digest
    assert lineage["claim_count"] == len(claims) == 57
    assert [claim["source_path"] for claim in claims] == sorted(
        claim["source_path"] for claim in claims
    )
    expected_pairs = {
        claim["source_path"]: claim["legacy_source_sha256"] for claim in claims
    }
    assert len(expected_pairs) == 57

    current_pairs: dict[str, str] = {}
    for path in sorted((ROOT / "data/commentaries/adam-clarke").glob("*.json")):
        if path.name == "_manifest.json":
            continue
        document = json.loads(path.read_bytes())
        source_hash = document["meta"]["provenance"]["source_hash"]
        assert source_hash.startswith("sha256:")
        current_pairs[f"commentaries/adam-clarke/{path.name}"] = (
            source_hash.removeprefix("sha256:")
        )
    assert current_pairs == expected_pairs


@pytest.mark.slow
def test_adam_clarke_candidate_is_complete_valid_nonaccepted_and_not_ready(
    adam_clarke_candidate,
) -> None:
    candidate, report = adam_clarke_candidate
    assert report.status == "pass"
    assert report.candidate_sha256 == candidate.sha256
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["member_count"] == 856
    assert accountability["included_member_count"] == 856
    assert accountability["excluded_member_count"] == 0
    assert accountability["total_bytes"] == 28_421_263
    assert accountability["census"] == {
        "books": 57,
        "chapters": 854,
        "commentary_occurrences": 13_318,
        "book_introductions": 57,
        "chapter_introductions_present": 831,
        "chapter_introductions_absent": 23,
        "profiles": 0,
    }
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["status"] == "nonaccepted"
    assert provenance["accepted_ir"] == "not_accepted"
    assert provenance["publication"] == "not_ready"
    assert provenance["human_decision"] is None


@pytest.mark.slow
def test_adam_clarke_retains_hath_while_binding_separate_canonical_has_correction(
    adam_clarke_source: SourceManifest, adam_clarke_candidate
) -> None:
    candidate, _ = adam_clarke_candidate
    authorities = {
        item["name"]: item for item in adam_clarke_source.record["authorities"]
    }
    ledger_authority = authorities["canonical-editorial-correction-ledger"]
    receipt_authority = authorities["canonical-editorial-correction-writer-receipt"]
    ledger_bytes = (ROOT / ledger_authority["path"]).read_bytes()
    receipt_bytes = (ROOT / receipt_authority["path"]).read_bytes()
    assert len(ledger_bytes) == ledger_authority["bytes"] == 729
    assert _sha(ledger_bytes) == ledger_authority["sha256"]
    assert len(receipt_bytes) == receipt_authority["bytes"] == 906
    assert _sha(receipt_bytes) == receipt_authority["sha256"]
    ledger_rows = ledger_bytes.splitlines()
    assert len(ledger_rows) == 1
    ledger = json.loads(ledger_rows[0])
    receipt = json.loads(receipt_bytes)
    assert ledger["correction_id"] == "correction_13dda1f028ab491e"
    assert ledger["before_text"] == "hath"
    assert ledger["after_text"] == "has"
    assert ledger["status"] == "applied"
    assert receipt["run_id"] == ledger["applier_run_id"]
    assert receipt["allowed_field_paths"] == ["/data/*/layers/commentary_text/display"]

    retained = json.loads(
        resolve_repo_path(
            ROOT, "raw/helloao_local/api/c/adam-clarke/2JN/1.json"
        ).read_bytes()
    )
    retained_text = retained["chapter"]["content"][8]["content"][0]
    assert retained["chapter"]["content"][8]["number"] == 9
    assert retained_text.count("hath not God") == 1
    assert "has not God" not in retained_text
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    tei_text = tree.xpath(
        "string(//tei:div[@xml:id='commentary-2JN-001-0009']/tei:p)",
        namespaces={"tei": TEI_NS, "xml": XML_NS},
    )
    assert tei_text == retained_text

    canonical = json.loads(
        (ROOT / "data/commentaries/adam-clarke/2-john.json").read_bytes()
    )
    entry = next(
        item
        for item in canonical["data"]
        if item["entry_id"] == "adam-clarke.2John.1.9"
    )
    layers = entry["layers"]["commentary_text"]
    assert "has not God" in entry["commentary_text"]
    assert "has not God" in layers["display"]
    for layer in ("source_raw", "normalised", "structured"):
        assert "hath not God" in layers[layer]
        assert "has not God" not in layers[layer]

    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    boundary = accountability["canonical_editorial_correction_boundary"]
    assert provenance["canonical_editorial_correction_boundary"] == boundary
    assert boundary["retained_reading"] == "hath"
    assert boundary["canonical_display_reading"] == "has"
    assert boundary["disposition"] == (
        "separate-display-layer-editorial-correction-not-applied-to-retained-source-tei"
    )
    assert provenance["status"] == "nonaccepted"
    assert provenance["accepted_ir"] == "not_accepted"
    assert provenance["publication"] == "not_ready"


@pytest.mark.slow
def test_adam_clarke_candidate_accounts_for_every_retained_source_field(
    adam_clarke_source: SourceManifest, adam_clarke_candidate
) -> None:
    candidate, _ = adam_clarke_candidate
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    accounting = accountability["source_field_accounting"]
    retained_root = resolve_repo_path(ROOT, "raw/helloao_local/api/c/adam-clarke")
    books_record = json.loads((retained_root / "books.json").read_bytes())
    profiles_record = json.loads((retained_root / "profiles.json").read_bytes())
    chapter_paths = [
        retained_root / book["id"] / f"{number}.json"
        for book in books_record["books"]
        for number in range(1, book["numberOfChapters"] + 1)
    ]
    chapter_records = [json.loads(path.read_bytes()) for path in chapter_paths]

    expected_shapes = [
        {
            "object": "books-envelope",
            "instances": 1,
            "key_orders": [{"keys": list(BOOKS_ROOT_KEYS), "instances": 1}],
        },
        {
            "object": "profiles-envelope",
            "instances": 1,
            "key_orders": [{"keys": list(PROFILES_ROOT_KEYS), "instances": 1}],
        },
        {
            "object": "commentary",
            "instances": 856,
            "key_orders": [{"keys": list(COMMENTARY_KEYS), "instances": 856}],
        },
        {
            "object": "book",
            "instances": 911,
            "key_orders": [{"keys": list(BOOK_KEYS), "instances": 911}],
        },
        {
            "object": "chapter-envelope",
            "instances": 854,
            "key_orders": [{"keys": list(CHAPTER_ENVELOPE_KEYS), "instances": 854}],
        },
        {
            "object": "chapter",
            "instances": 854,
            "key_orders": [
                {"keys": list(CHAPTER_KEYS_WITH_INTRODUCTION), "instances": 831},
                {"keys": list(CHAPTER_KEYS_WITHOUT_INTRODUCTION), "instances": 23},
            ],
        },
        {
            "object": "commentary-occurrence",
            "instances": 13_318,
            "key_orders": [{"keys": list(OCCURRENCE_KEYS), "instances": 13_318}],
        },
    ]
    assert accounting["contract"] == (
        "ocd-helloao-adam-clarke-source-field-accounting-v1"
    )
    assert accounting["object_shapes"] == expected_shapes
    assert accounting["book_metadata"] == books_record["books"]
    assert accounting["profiles"] == profiles_record["profiles"] == []
    assert accounting["chapter_navigation"] == [
        {
            "path": path.relative_to(retained_root).as_posix(),
            "thisChapterLink": record["thisChapterLink"],
            "nextChapterApiLink": record["nextChapterApiLink"],
            "previousChapterApiLink": record["previousChapterApiLink"],
            "numberOfVerses": record["numberOfVerses"],
        }
        for path, record in zip(chapter_paths, chapter_records, strict=True)
    ]

    shape_keys = {
        "books-envelope": BOOKS_ROOT_KEYS,
        "profiles-envelope": PROFILES_ROOT_KEYS,
        "commentary": COMMENTARY_KEYS,
        "book": BOOK_KEYS,
        "chapter-envelope": CHAPTER_ENVELOPE_KEYS,
        "chapter": CHAPTER_KEYS_WITH_INTRODUCTION,
        "commentary-occurrence": OCCURRENCE_KEYS,
    }
    dispositions = accounting["field_dispositions"]
    assert [(item["object"], item["field"]) for item in dispositions] == [
        (object_name, field)
        for object_name, keys in shape_keys.items()
        for field in keys
    ]
    assert all(
        set(item) == {"object", "field", "disposition", "evidence"}
        and item["disposition"]
        in {
            "preserved-in-accountability",
            "preserved-in-accountability-and-recomputed",
            "projected-exactly-to-tei",
            "verified-exact-repetition",
        }
        and isinstance(item["evidence"], str)
        and item["evidence"]
        for item in dispositions
    )
    assert [book["sha256"] for book in accounting["book_metadata"]] == [
        book["sha256"] for book in books_record["books"]
    ]


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    [
        "envelope-missing-key",
        "commentary-extra",
        "book-renamed-sha256",
        "chapter-reordered-keys",
        "envelope-drifted-count",
    ],
)
def test_adam_clarke_rejects_fully_resealed_source_field_drift(
    adam_clarke_resealed_source_base: Path, tmp_path: Path, mutation: str
) -> None:
    source = _resealed_source_variant(
        adam_clarke_resealed_source_base, tmp_path / mutation, mutation
    )
    converter_path = (
        source.repository_root / source.record["converter"]["implementation_path"]
    )
    converter_namespace: dict[str, object] = {
        "__file__": str(converter_path),
        "__name__": f"_lib078_source_mutation_{mutation.replace('-', '_')}",
    }
    exec(
        compile(converter_path.read_bytes(), str(converter_path), "exec"),
        converter_namespace,
    )
    with pytest.raises(ValueError, match="source field|key order|field accounting"):
        reconstruct(
            source,
            tmp_path / f"{mutation}-candidate",
            converter_namespace["_convert"],
        )


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation", ["correction-ledger-direction", "correction-receipt-path"]
)
def test_adam_clarke_rejects_resealed_canonical_correction_boundary_drift(
    adam_clarke_resealed_source_base: Path, tmp_path: Path, mutation: str
) -> None:
    source = _resealed_source_variant(
        adam_clarke_resealed_source_base, tmp_path / mutation, mutation
    )
    converter_path = (
        source.repository_root / source.record["converter"]["implementation_path"]
    )
    converter_namespace: dict[str, object] = {
        "__file__": str(converter_path),
        "__name__": f"_lib078_correction_mutation_{mutation.replace('-', '_')}",
    }
    exec(
        compile(converter_path.read_bytes(), str(converter_path), "exec"),
        converter_namespace,
    )
    with pytest.raises(ValueError, match="correction ledger|correction writer"):
        reconstruct(
            source,
            tmp_path / f"{mutation}-candidate",
            converter_namespace["_convert"],
        )


@pytest.mark.slow
def test_adam_clarke_retained_scope_anomalies_are_preserved(
    adam_clarke_candidate,
) -> None:
    candidate, _ = adam_clarke_candidate
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"tei": TEI_NS, "xml": XML_NS}
    books = root.xpath("tei:text/tei:body/tei:div[@type='book']/@n", namespaces=ns)
    assert len(books) == 57
    assert set(books).isdisjoint(
        {"DEU", "JDG", "PSA", "PRO", "ECC", "JER", "JOL", "MAL", "MAT"}
    )
    chapters_with_intros = root.xpath(
        "count(tei:text/tei:body/tei:div/tei:div[@type='chapter'][tei:div[@type='chapter-introduction']])",
        namespaces=ns,
    )
    assert chapters_with_intros == 831
    second_samuel_14 = root.xpath(
        "tei:text/tei:body/tei:div[@n='2SA']/tei:div[@type='chapter'][@n='14']",
        namespaces=ns,
    )[0]
    verse_numbers = [
        int(item)
        for item in second_samuel_14.xpath(
            "tei:div[@type='commentary-occurrence']/@n", namespaces=ns
        )
    ]
    assert verse_numbers.count(27) == 2
    assert verse_numbers[-2:] == [30, 27]
    verse_27_texts = second_samuel_14.xpath(
        "tei:div[@type='commentary-occurrence'][@n='27']/tei:p/text()",
        namespaces=ns,
    )
    assert len(verse_27_texts) == 2
    assert verse_27_texts[0] != verse_27_texts[1]
    assert "Unto Absalom there were born" in verse_27_texts[0]
    assert "Absalom had a daughter" in verse_27_texts[1]


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    [
        "omit-occurrence",
        "reorder-occurrences",
        "merge-duplicate",
        "invent-range",
        "inject-bsb",
        "text-direction",
    ],
)
def test_adam_clarke_oracle_rejects_textual_and_structural_mutations(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = adam_clarke_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    ns = {"tei": TEI_NS}
    if mutation == "text-direction":
        note = root.xpath(
            "tei:teiHeader/tei:fileDesc/tei:notesStmt/tei:note[@type='text-direction']",
            namespaces=ns,
        )[0]
        note.text = "ltr"
    else:
        chapter = root.xpath(
            "tei:text/tei:body/tei:div[@n='2SA']/tei:div[@type='chapter'][@n='14']",
            namespaces=ns,
        )[0]
        occurrences = chapter.xpath(
            "tei:div[@type='commentary-occurrence']", namespaces=ns
        )
        if mutation == "omit-occurrence":
            chapter.remove(occurrences[0])
        elif mutation == "reorder-occurrences":
            first_index = chapter.index(occurrences[0])
            chapter.remove(occurrences[1])
            chapter.insert(first_index, occurrences[1])
        elif mutation == "merge-duplicate":
            duplicate = chapter.xpath(
                "tei:div[@type='commentary-occurrence'][@n='27']", namespaces=ns
            )
            chapter.remove(duplicate[1])
            duplicate[0].find(f"{{{TEI_NS}}}p").text += (
                duplicate[1].find(f"{{{TEI_NS}}}p").text
            )
        elif mutation == "invent-range":
            occurrences[0].set("n", "2-4")
        else:
            occurrences[0].find(f"{{{TEI_NS}}}p").text += " Invented BSB verse text."
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(adam_clarke_source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    [
        "doctype-insertion",
        "xml-declaration-omission",
        "standalone-yes",
        "standalone-no",
    ],
)
def test_adam_clarke_oracle_rejects_document_prolog_drift(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = adam_clarke_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    xml_path = target / "content.tei.xml"
    content = xml_path.read_bytes()
    prolog = b"<?xml version='1.0' encoding='UTF-8'?>\n"
    assert content.startswith(prolog + b"<TEI ")
    body = content.removeprefix(prolog)
    if mutation == "doctype-insertion":
        content = prolog + b"<!DOCTYPE TEI>\n" + body
    elif mutation == "xml-declaration-omission":
        content = body
    elif mutation == "standalone-yes":
        content = b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + body
    else:
        content = b"<?xml version='1.0' encoding='UTF-8' standalone='no'?>\n" + body
    xml_path.write_bytes(content)
    parsed = etree.parse(
        str(xml_path),
        etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False),
    )
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(parsed), schema.error_log.last_error
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="TEI document prolog drift"):
        validate(adam_clarke_source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize("location", ["root", "body", "reserved-xml"])
def test_adam_clarke_oracle_rejects_unexpected_namespace_declarations(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    tmp_path: Path,
    location: str,
) -> None:
    candidate, _ = adam_clarke_candidate
    target = _resealed_copy(candidate, tmp_path / f"namespace-{location}")
    xml_path = target / "content.tei.xml"
    if location == "reserved-xml":
        content = xml_path.read_bytes().replace(
            b'<TEI xmlns="http://www.tei-c.org/ns/1.0">',
            b'<TEI xmlns="http://www.tei-c.org/ns/1.0" '
            b'xmlns:xml="http://www.w3.org/XML/1998/namespace">',
            1,
        )
        xml_path.write_bytes(content)
        mutated = _reseal(target, "content.tei.xml")
    else:
        root = etree.fromstring(xml_path.read_bytes())
        if location == "root":
            replacement = etree.Element(
                root.tag,
                dict(root.attrib),
                nsmap={None: TEI_NS, "invented": "urn:ocd:invented"},
            )
            replacement.text = root.text
            replacement.tail = root.tail
            for child in list(root):
                replacement.append(child)
            root = replacement
        else:
            body = root.find(f".//{{{TEI_NS}}}body")
            assert body is not None
            replacement = etree.Element(
                body.tag,
                dict(body.attrib),
                nsmap={"invented": "urn:ocd:invented-body"},
            )
            replacement.text = body.text
            replacement.tail = body.tail
            for child in list(body):
                replacement.append(child)
            parent = body.getparent()
            assert parent is not None
            parent.replace(body, replacement)
        mutated = _write_tei(target, root)
    parsed = etree.parse(str(target / "content.tei.xml"))
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(parsed), schema.error_log.last_error
    with pytest.raises(ValueError, match="namespace declarations drifted"):
        validate(adam_clarke_source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("node_kind", "position"),
    [
        ("comment", "before"),
        ("comment", "after"),
        ("processing-instruction", "before"),
        ("processing-instruction", "after"),
    ],
)
def test_adam_clarke_oracle_rejects_document_level_nodes(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    tmp_path: Path,
    node_kind: str,
    position: str,
) -> None:
    candidate, _ = adam_clarke_candidate
    target = _resealed_copy(candidate, tmp_path / f"document-{node_kind}-{position}")
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    node = (
        etree.Comment("Invented document-level comment")
        if node_kind == "comment"
        else etree.ProcessingInstruction("invented", "document-metadata")
    )
    if position == "before":
        root.addprevious(node)
    else:
        root.addnext(node)
    mutated = _write_tei_document(target, root)
    with pytest.raises(ValueError, match="document-level node"):
        validate(adam_clarke_source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    [
        "extra-author",
        "extra-publisher",
        "encoding-desc",
        "profile-desc",
        "revision-desc",
        "header-comment",
        "header-processing-instruction",
        "header-tail",
    ],
)
def test_adam_clarke_oracle_rejects_complete_header_tree_drift(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = adam_clarke_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    header = root.find(f"{{{TEI_NS}}}teiHeader")
    assert header is not None
    if mutation == "extra-author":
        title_stmt = header.find(f".//{{{TEI_NS}}}titleStmt")
        assert title_stmt is not None
        etree.SubElement(title_stmt, f"{{{TEI_NS}}}author").text = "Invented Coauthor"
    elif mutation == "extra-publisher":
        publication = header.find(f".//{{{TEI_NS}}}publicationStmt")
        assert publication is not None
        etree.SubElement(
            publication, f"{{{TEI_NS}}}publisher"
        ).text = "Invented Publisher"
    elif mutation == "encoding-desc":
        encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
        etree.SubElement(encoding, f"{{{TEI_NS}}}p").text = "Invented encoding metadata"
    elif mutation == "profile-desc":
        profile = etree.SubElement(header, f"{{{TEI_NS}}}profileDesc")
        language = etree.SubElement(profile, f"{{{TEI_NS}}}langUsage")
        etree.SubElement(language, f"{{{TEI_NS}}}language", ident="en").text = "English"
    elif mutation == "revision-desc":
        revision = etree.SubElement(header, f"{{{TEI_NS}}}revisionDesc")
        etree.SubElement(revision, f"{{{TEI_NS}}}change").text = "Invented change"
    elif mutation == "header-comment":
        header.append(etree.Comment("Invented header comment"))
    elif mutation == "header-processing-instruction":
        header.append(etree.ProcessingInstruction("invented", "header-metadata"))
    else:
        publisher = header.find(f".//{{{TEI_NS}}}publisher")
        assert publisher is not None
        publisher.tail = " "
    mutated = _write_tei(target, root)
    parsed = etree.parse(str(target / "content.tei.xml"))
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(parsed), schema.error_log.last_error
    expected_error = (
        "TEI exact document bytes drifted"
        if mutation == "header-tail"
        else "TEI header tree drifted"
    )
    with pytest.raises(ValueError, match=expected_error):
        validate(adam_clarke_source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    [
        "nested-seg",
        "nested-tail",
        "comment",
        "processing-instruction",
        "invented-note",
    ],
)
def test_adam_clarke_oracle_rejects_complete_recursive_body_drift(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = adam_clarke_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    paragraph = root.find(
        f".//{{{TEI_NS}}}div[@type='commentary-occurrence']/{{{TEI_NS}}}p"
    )
    assert paragraph is not None
    if mutation in {"nested-seg", "nested-tail"}:
        segment = etree.SubElement(paragraph, f"{{{TEI_NS}}}seg")
        segment.text = "Invented nested text"
        if mutation == "nested-tail":
            segment.tail = "Invented tail text"
    elif mutation == "comment":
        paragraph.append(etree.Comment("Invented body comment"))
    elif mutation == "processing-instruction":
        paragraph.append(etree.ProcessingInstruction("invented", "body-metadata"))
    else:
        etree.SubElement(
            paragraph, f"{{{TEI_NS}}}note", type="editorial"
        ).text = "Invented optional element"
    mutated = _write_tei(target, root)
    parsed = etree.parse(str(target / "content.tei.xml"))
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(parsed), schema.error_log.last_error
    with pytest.raises(ValueError, match="TEI body tree drifted"):
        validate(adam_clarke_source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation", ["false-complete", "rights", "merge-witness", "invent-year"]
)
def test_adam_clarke_oracle_rejects_scope_metadata_rights_and_identity_mutations(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = adam_clarke_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    name = "provenance.json"
    provenance = json.loads((target / name).read_bytes())
    if mutation == "false-complete":
        provenance["scope"]["canonical_bible_complete"] = True
        provenance["scope"]["missing_canonical_books"] = []
    elif mutation == "rights":
        provenance["rights"]["retained_mark"] = "CC0 1.0"
    elif mutation == "merge-witness":
        provenance["alternate_witness"]["merged"] = True
    else:
        provenance["identity"]["original_publication_year"] = 1810
    (target / name).write_bytes(_canonical(provenance))
    mutated = _reseal(target, name)
    with pytest.raises(ValueError):
        validate(adam_clarke_source, mutated, _oracle)


@pytest.mark.slow
def test_adam_clarke_oracle_rejects_member_accounting_omission(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    tmp_path: Path,
) -> None:
    candidate, _ = adam_clarke_candidate
    target = _resealed_copy(candidate, tmp_path / "member-omission")
    name = "source-accountability.json"
    accountability = json.loads((target / name).read_bytes())
    accountability["members"] = accountability["members"][:-1]
    (target / name).write_bytes(_canonical(accountability))
    mutated = _reseal(target, name)
    with pytest.raises(ValueError):
        validate(adam_clarke_source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "reorder", "unexpected-member-field", "unexpected-root-field"],
)
def test_adam_clarke_oracle_rejects_complete_accountability_record_drift(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = adam_clarke_candidate
    target = _resealed_copy(candidate, tmp_path / f"accountability-{mutation}")
    name = "source-accountability.json"
    accountability = json.loads((target / name).read_bytes())
    if mutation == "duplicate":
        accountability["members"].insert(1, accountability["members"][0])
    elif mutation == "reorder":
        accountability["members"][0], accountability["members"][1] = (
            accountability["members"][1],
            accountability["members"][0],
        )
    elif mutation == "unexpected-member-field":
        accountability["members"][0]["invented"] = True
    else:
        accountability["invented"] = "unexpected evidence"
    (target / name).write_bytes(_canonical(accountability))
    mutated = _reseal(target, name)
    with pytest.raises(ValueError, match="source accountability"):
        validate(adam_clarke_source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation",
    [
        "field-question",
        "field-evidence",
        "field-consequence",
        "field-escalation",
        "unexpected-field",
        "omission",
        "duplicate",
        "reorder",
    ],
)
def test_adam_clarke_oracle_rejects_complete_unresolved_record_drift(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = adam_clarke_candidate
    target = _resealed_copy(candidate, tmp_path / f"unresolved-{mutation}")
    name = "unresolved.jsonl"
    records = [
        json.loads(line)
        for line in (target / name).read_text(encoding="utf-8").splitlines()
    ]
    if mutation.startswith("field-"):
        field = mutation.removeprefix("field-")
        records[0][field] = "Invented evidence value"
    elif mutation == "unexpected-field":
        records[0]["invented"] = "unexpected evidence"
    elif mutation == "omission":
        records.pop(1)
    elif mutation == "duplicate":
        records.insert(1, records[0])
    else:
        records[0], records[1] = records[1], records[0]
    (target / name).write_bytes(b"".join(_canonical(record) for record in records))
    mutated = _reseal(target, name)
    with pytest.raises(ValueError, match="unresolved evidence drift"):
        validate(adam_clarke_source, mutated, _oracle)


@pytest.mark.slow
@pytest.mark.parametrize(
    "mutation", ["omission", "duplicate", "reorder", "unexpected-content"]
)
def test_adam_clarke_oracle_rejects_exact_readme_byte_drift(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = adam_clarke_candidate
    target = _resealed_copy(candidate, tmp_path / f"readme-{mutation}")
    name = "README.source.md"
    content = (target / name).read_text(encoding="utf-8")
    if mutation == "omission":
        content = content.replace(
            ": `books.json`, `profiles.json`, and 854 chapter files in 57 book directories.",
            ".",
            1,
        )
    elif mutation == "duplicate":
        sentence = "PDM contains no attribution request, but HelloAO is identified as the retained API provider."
        content = content.replace(sentence, sentence + " " + sentence, 1)
    elif mutation == "reorder":
        first = "Edition identity, the rights-description drift, and retained `textDirection: rtl` anomaly remain localized questions."
        second = "Accepted IR is `not_accepted`; publication is `not_ready`."
        content = content.replace(first + " " + second, second + " " + first, 1)
    else:
        content += "\nInvented review assertion.\n"
    (target / name).write_text(content, encoding="utf-8")
    mutated = _reseal(target, name)
    with pytest.raises(ValueError, match="source README drift"):
        validate(adam_clarke_source, mutated, _oracle)


@pytest.mark.slow
def test_adam_clarke_oracle_is_independent_of_producer_and_legacy_parser(
    adam_clarke_source: SourceManifest,
    adam_clarke_candidate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, report = adam_clarke_candidate
    oracle_source = (ROOT / "build/tei/helloao_adam_clarke_oracle.py").read_text(
        encoding="utf-8"
    )
    assert "helloao_adam_clarke_reconstruction" not in oracle_source
    assert "helloao_commentary" not in oracle_source
    assert oracle_source.count('"data/commentaries/adam-clarke/2-john.json"') == 1

    canonical_root = (ROOT / "data/commentaries/adam-clarke").resolve()
    original_read_bytes = Path.read_bytes
    attempted_canonical_reads: list[Path] = []

    def guarded_read_bytes(path: Path) -> bytes:
        resolved = path.resolve()
        if resolved.is_relative_to(canonical_root):
            attempted_canonical_reads.append(resolved)
            raise AssertionError(
                f"independent source oracle read canonical display data: {resolved}"
            )
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    rerun = validate(adam_clarke_source, candidate, _oracle)
    assert rerun.status == "pass"
    assert attempted_canonical_reads == []
    assert len(report.attestation["import_closure_sha256"]) == 64


@pytest.mark.slow
def test_adam_clarke_oracle_attests_the_actual_runtime_first_party_import_closure(
    adam_clarke_candidate,
) -> None:
    _, report = adam_clarke_candidate
    code = (
        "import json,sys; from pathlib import Path; "
        f"root=Path({str(ROOT)!r}).resolve(); "
        "import build.tei.helloao_adam_clarke_oracle; "
        "records=[]; "
        "[(records.append((name,Path(module.__file__).resolve().relative_to(root).as_posix())) "
        "if getattr(module,'__file__',None) and Path(module.__file__).resolve().is_relative_to(root) "
        "and Path(module.__file__).suffix == '.py' else None) "
        "for name,module in sorted(sys.modules.items())]; "
        "print(json.dumps(records))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    runtime_records = json.loads(completed.stdout)
    runtime_paths = tuple(path for _, path in runtime_records)
    assert runtime_paths == RUNTIME_ORACLE_CLOSURE
    expected_records = [
        {"path": path, "sha256": _sha((ROOT / path).read_bytes())}
        for path in sorted(runtime_paths)
    ]
    assert report.attestation["import_closure_sha256"] == _sha(
        _canonical(expected_records)
    )
    assert "ocd_kernel/reconstruction/__init__.py" in runtime_paths
    assert "build/tei/helloao_adam_clarke_reconstruction.py" not in runtime_paths


@pytest.mark.slow
def test_adam_clarke_candidate_is_byte_identical_across_fresh_processes(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    code = (
        "from pathlib import Path; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.helloao_adam_clarke_reconstruction import _convert; "
        f"r=Path({str(ROOT)!r}); "
        f"s=SourceManifest.load(r/{str(SOURCE_MANIFEST.relative_to(ROOT))!r},repository_root=r); "
        "reconstruct(s,Path(__import__('sys').argv[1]),_convert)"
    )
    for destination in (first, second):
        subprocess.run(
            [sys.executable, "-c", code, str(destination)],
            cwd=ROOT,
            check=True,
            timeout=120,
        )
    first_members = {path.name: path.read_bytes() for path in sorted(first.iterdir())}
    second_members = {path.name: path.read_bytes() for path in sorted(second.iterdir())}
    assert first_members == second_members


@pytest.mark.slow
def test_adam_clarke_runtime_has_no_campaign_or_shared_family_abstractions(
    adam_clarke_candidate,
) -> None:
    _, _ = adam_clarke_candidate
    for path in (
        ROOT / "build/tei/helloao_adam_clarke_reconstruction.py",
        ROOT / "build/tei/helloao_adam_clarke_oracle.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "build.reconstruction" not in source
        assert "case_declaration" not in source
        assert "reconstruction.persistence" not in source
        assert "reconstruction.wave" not in source
