"""Contract and mutation tests for the complete retained Jamieson-Fausset-Brown witness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.helloao_jamieson_fausset_brown_oracle import _oracle
from build.tei.helloao_jamieson_fausset_brown_reconstruction import _convert
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = (
    ROOT
    / "tests/fixtures/reconstruction-runtime/jamieson-fausset-brown.source-manifest.json"
)
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MOJIBAKE_SIGNATURES = ("\u00c3&brvbr", "\u00c5\u201c", "\u00c3\u2020", "\u00c2\u00a3")
EXPECTED_TEI_PROLOG = b"<?xml version='1.0' encoding='UTF-8'?>\n"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


@pytest.fixture(scope="session")
def jamieson_fausset_brown_source() -> SourceManifest:
    return SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="session")
def jamieson_fausset_brown_candidate(
    jamieson_fausset_brown_source: SourceManifest,
    tmp_path_factory: pytest.TempPathFactory,
):
    destination = tmp_path_factory.mktemp("lib079") / "candidate"
    candidate = reconstruct(jamieson_fausset_brown_source, destination, _convert)
    report = validate(jamieson_fausset_brown_source, candidate, _oracle)
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


def _assert_tei_p5_valid_document(content: bytes) -> None:
    document = etree.fromstring(
        content,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            huge_tree=True,
            remove_comments=False,
        ),
    ).getroottree()
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    assert schema.validate(document), schema.error_log.last_error


def test_jamieson_fausset_brown_manifest_binds_every_retained_member(
    jamieson_fausset_brown_source: SourceManifest,
) -> None:
    authorities = jamieson_fausset_brown_source.record["authorities"]
    primary = [item for item in authorities if item["role"] == "primary-source"]
    assert len(primary) == 1_189
    assert sum(item["bytes"] for item in primary) == 22_377_675
    paths = [item["path"] for item in primary]
    assert len(paths) == len(set(paths))
    assert "raw/helloao_local/api/c/jamieson-fausset-brown/books.json" in paths
    assert "raw/helloao_local/api/c/jamieson-fausset-brown/profiles.json" in paths
    assert len([path for path in paths if path.count("/") == 6]) == 1_187
    assert "raw/helloao_local/api/c/jamieson-fausset-brown/MRK/15.json" not in paths
    assert "raw/helloao_local/api/c/jamieson-fausset-brown/MRK/16.json" in paths
    assert "raw/helloao_local/api/c/jamieson-fausset-brown/PSA/146.json" not in paths
    assert "raw/helloao_local/api/c/jamieson-fausset-brown/PSA/147.json" in paths
    for authority in primary:
        path = ROOT / authority["path"]
        content = path.read_bytes()
        assert len(content) == authority["bytes"]
        assert _sha(content) == authority["sha256"]


def test_jamieson_fausset_brown_candidate_is_complete_valid_nonaccepted_and_not_ready(
    jamieson_fausset_brown_candidate,
) -> None:
    candidate, report = jamieson_fausset_brown_candidate
    assert report.status == "pass"
    assert report.candidate_sha256 == candidate.sha256
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["member_count"] == 1_189
    assert accountability["included_member_count"] == 1_189
    assert accountability["excluded_member_count"] == 0
    assert accountability["total_bytes"] == 22_377_675
    assert accountability["census"] == {
        "books": 66,
        "chapters": 1187,
        "commentary_occurrences": 17_056,
        "book_introductions": 66,
        "chapter_introductions_present": 1178,
        "chapter_introductions_absent": 9,
        "introduction_only_chapters": 101,
        "profiles": 0,
    }
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["status"] == "nonaccepted"
    assert provenance["accepted_ir"] == "not_accepted"
    assert provenance["human_review"] == "required"
    assert provenance["publication"] == "not_ready"
    assert provenance["human_decision"] is None
    mojibake = accountability["retained_mojibake"]
    assert mojibake["sequence_count"] == 539
    assert mojibake["carrier_count"] == 374
    assert mojibake["source_member_count"] == 229
    assert mojibake["affected_carriers"] == {
        "book-introduction": {"sequence_count": 85, "carrier_count": 33},
        "chapter-introduction": {"sequence_count": 53, "carrier_count": 39},
        "commentary-occurrence": {"sequence_count": 401, "carrier_count": 302},
    }
    assert provenance["source_anomalies"]["retained_mojibake"] == mojibake
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
    ]
    localized = unresolved[-1]
    assert localized["id"] == (
        "jamieson-fausset-brown-localized-suspected-mojibake-readings"
    )
    assert localized["evidence"]["census"] == mojibake
    assert (
        "source or correction authority" in localized["evidence"]["authority_boundary"]
    )
    assert "silently corrected" in localized["consequence"]
    readme = candidate.member_bytes("README.source.md").decode("utf-8")
    assert "exactly 539 suspected mojibake sequences" in readme
    assert "374 retained semantic text carriers across 229 source members" in readme
    assert "exact source or correction authority" in readme


def test_jamieson_fausset_brown_candidate_has_exact_canonical_xml_prolog(
    jamieson_fausset_brown_candidate,
) -> None:
    candidate, _ = jamieson_fausset_brown_candidate
    content = candidate.member_bytes("content.tei.xml")
    assert content.startswith(EXPECTED_TEI_PROLOG + b"<TEI ")


@pytest.mark.parametrize(
    ("mutation", "tei_p5_valid"),
    [
        ("declaration-omitted", True),
        ("standalone-yes", True),
        ("standalone-no", True),
        ("encoding-alias", True),
        ("encoding-case", True),
        ("declaration-order", False),
        ("pre-root-comment", True),
        ("pre-root-processing-instruction", True),
        ("doctype", True),
        ("post-root-comment", True),
        ("post-root-processing-instruction", True),
    ],
)
def test_jamieson_fausset_brown_oracle_rejects_resealed_document_shell_drift(
    jamieson_fausset_brown_source: SourceManifest,
    jamieson_fausset_brown_candidate,
    tmp_path: Path,
    mutation: str,
    tei_p5_valid: bool,
) -> None:
    candidate, _ = jamieson_fausset_brown_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    content_path = target / "content.tei.xml"
    content = content_path.read_bytes()
    assert content.startswith(EXPECTED_TEI_PROLOG)
    body = content.removeprefix(EXPECTED_TEI_PROLOG)
    if mutation == "declaration-omitted":
        content = body
    elif mutation == "standalone-yes":
        content = b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + body
    elif mutation == "standalone-no":
        content = b"<?xml version='1.0' encoding='UTF-8' standalone='no'?>\n" + body
    elif mutation == "encoding-alias":
        content = b"<?xml version='1.0' encoding='UTF8'?>\n" + body
    elif mutation == "encoding-case":
        content = b"<?xml version='1.0' encoding='utf-8'?>\n" + body
    elif mutation == "declaration-order":
        content = b"<?xml version='1.0' standalone='no' encoding='UTF-8'?>\n" + body
    elif mutation == "pre-root-comment":
        content = EXPECTED_TEI_PROLOG + b"<!-- invented -->\n" + body
    elif mutation == "pre-root-processing-instruction":
        content = EXPECTED_TEI_PROLOG + b"<?invented value?>\n" + body
    elif mutation == "doctype":
        content = EXPECTED_TEI_PROLOG + b"<!DOCTYPE TEI>\n" + body
    elif mutation == "post-root-comment":
        content = EXPECTED_TEI_PROLOG + body + b"<!-- invented -->\n"
    else:
        content = EXPECTED_TEI_PROLOG + body + b"<?invented value?>\n"
    if tei_p5_valid:
        _assert_tei_p5_valid_document(content)
    else:
        # XML 1.0 fixes pseudo-attribute order, so a genuine wrong-order
        # declaration cannot itself be well formed, unlike every other mutant.
        with pytest.raises(etree.XMLSyntaxError):
            _assert_tei_p5_valid_document(content)
    content_path.write_bytes(content)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="document prolog|document-level"):
        validate(jamieson_fausset_brown_source, mutated, _oracle)


def test_jamieson_fausset_brown_retained_scope_anomalies_are_preserved(
    jamieson_fausset_brown_candidate,
) -> None:
    candidate, _ = jamieson_fausset_brown_candidate
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"tei": TEI_NS, "xml": XML_NS}
    books = root.xpath("tei:text/tei:body/tei:div[@type='book']/@n", namespaces=ns)
    assert len(books) == 66
    chapters_with_intros = root.xpath(
        "count(tei:text/tei:body/tei:div/tei:div[@type='chapter'][tei:div[@type='chapter-introduction']])",
        namespaces=ns,
    )
    assert chapters_with_intros == 1178
    intro_only = root.xpath(
        "count(tei:text/tei:body/tei:div/tei:div[@type='chapter'][tei:div[@type='chapter-introduction'] and not(tei:div[@type='commentary-occurrence'])])",
        namespaces=ns,
    )
    assert intro_only == 101
    mark_numbers = root.xpath(
        "tei:text/tei:body/tei:div[@n='MRK']/tei:div[@type='chapter']/@n",
        namespaces=ns,
    )
    psalm_numbers = root.xpath(
        "tei:text/tei:body/tei:div[@n='PSA']/tei:div[@type='chapter']/@n",
        namespaces=ns,
    )
    assert "15" not in mark_numbers and "16" in mark_numbers
    assert "146" not in psalm_numbers and "147" in psalm_numbers
    hebrews_13 = root.xpath(
        "tei:text/tei:body/tei:div[@n='HEB']/tei:div[@type='chapter'][@n='13']",
        namespaces=ns,
    )[0]
    verse_numbers = [
        int(item)
        for item in hebrews_13.xpath(
            "tei:div[@type='commentary-occurrence']/@n", namespaces=ns
        )
    ]
    assert verse_numbers.count(7) == 2
    assert verse_numbers[:2] == [7, 3]
    verse_7_texts = [
        "".join(occurrence.itertext())
        for occurrence in hebrews_13.xpath(
            "tei:div[@type='commentary-occurrence'][@n='7']",
            namespaces=ns,
        )
    ]
    assert len(verse_7_texts) == 2
    assert verse_7_texts[0] != verse_7_texts[1]
    assert "Two manifestations" in verse_7_texts[0]
    assert "have the rule" in verse_7_texts[1]

    retained_text_carriers = root.xpath(
        "tei:text/tei:body/tei:div/tei:div[@type='book-introduction']/tei:p/text()"
        " | tei:text/tei:body/tei:div/tei:div[@type='chapter']/"
        "tei:div[@type='chapter-introduction']/tei:p/text()"
        " | tei:text/tei:body/tei:div/tei:div[@type='chapter']/"
        "tei:div[@type='commentary-occurrence']/tei:p/text()",
        namespaces=ns,
    )
    assert (
        sum(
            text.count(signature)
            for text in retained_text_carriers
            for signature in MOJIBAKE_SIGNATURES
        )
        == 539
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "omit-occurrence",
        "duplicate-occurrence",
        "reorder-occurrences",
        "merge-duplicate",
        "invent-range",
        "inject-bsb",
        "text-direction",
        "invent-absent-introduction",
    ],
)
def test_jamieson_fausset_brown_oracle_rejects_textual_and_structural_mutations(
    jamieson_fausset_brown_source: SourceManifest,
    jamieson_fausset_brown_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = jamieson_fausset_brown_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    ns = {"tei": TEI_NS}
    if mutation == "text-direction":
        note = root.xpath(
            "tei:teiHeader/tei:fileDesc/tei:notesStmt/tei:note[@type='text-direction']",
            namespaces=ns,
        )[0]
        note.text = "ltr"
    elif mutation == "invent-absent-introduction":
        chapter = root.xpath(
            "tei:text/tei:body/tei:div[@n='2SA']/tei:div[@type='chapter'][@n='24']",
            namespaces=ns,
        )[0]
        intro = etree.Element(f"{{{TEI_NS}}}div")
        intro.set("type", "chapter-introduction")
        intro.set(f"{{{XML_NS}}}id", "chapter-intro-2SA-024")
        paragraph = etree.SubElement(intro, f"{{{TEI_NS}}}p")
        paragraph.text = ""
        chapter.insert(0, intro)
    else:
        chapter = root.xpath(
            "tei:text/tei:body/tei:div[@n='HEB']/tei:div[@type='chapter'][@n='13']",
            namespaces=ns,
        )[0]
        occurrences = chapter.xpath(
            "tei:div[@type='commentary-occurrence']", namespaces=ns
        )
        if mutation == "omit-occurrence":
            chapter.remove(occurrences[0])
        elif mutation == "duplicate-occurrence":
            duplicate = etree.fromstring(etree.tostring(occurrences[0]))
            duplicate.set(f"{{{XML_NS}}}id", "commentary-HEB-013-invented")
            chapter.append(duplicate)
        elif mutation == "reorder-occurrences":
            first_index = chapter.index(occurrences[0])
            chapter.remove(occurrences[1])
            chapter.insert(first_index, occurrences[1])
        elif mutation == "merge-duplicate":
            duplicate = chapter.xpath(
                "tei:div[@type='commentary-occurrence'][@n='7']", namespaces=ns
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
        validate(jamieson_fausset_brown_source, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation", ["erase-retained-gaps", "rights", "invent-author", "invent-year"]
)
def test_jamieson_fausset_brown_oracle_rejects_scope_metadata_rights_and_identity_mutations(
    jamieson_fausset_brown_source: SourceManifest,
    jamieson_fausset_brown_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = jamieson_fausset_brown_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    name = "provenance.json"
    provenance = json.loads((target / name).read_bytes())
    if mutation == "erase-retained-gaps":
        provenance["scope"]["retained_chapter_gaps"] = {}
    elif mutation == "rights":
        provenance["rights"]["retained_mark"] = "CC0 1.0"
    elif mutation == "invent-author":
        provenance["identity"]["author"] = (
            "Robert Jamieson, A. R. Fausset, and David Brown"
        )
    else:
        provenance["identity"]["original_publication_year"] = 1871
    (target / name).write_bytes(_canonical(provenance))
    mutated = _reseal(target, name)
    with pytest.raises(ValueError):
        validate(jamieson_fausset_brown_source, mutated, _oracle)


def test_jamieson_fausset_brown_oracle_rejects_member_accounting_omission(
    jamieson_fausset_brown_source: SourceManifest,
    jamieson_fausset_brown_candidate,
    tmp_path: Path,
) -> None:
    candidate, _ = jamieson_fausset_brown_candidate
    target = _resealed_copy(candidate, tmp_path / "member-omission")
    name = "source-accountability.json"
    accountability = json.loads((target / name).read_bytes())
    accountability["members"] = accountability["members"][:-1]
    (target / name).write_bytes(_canonical(accountability))
    mutated = _reseal(target, name)
    with pytest.raises(ValueError):
        validate(jamieson_fausset_brown_source, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation", ["hash-swap", "path-hash-pair-swap", "wrong-source", "stale-config"]
)
def test_jamieson_fausset_brown_rejects_source_lineage_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest = json.loads(SOURCE_MANIFEST.read_bytes())
    isolated_root = tmp_path / "repository"
    try:
        closure_paths = {
            item["path"] for item in manifest["authorities"]
        } | {
            manifest["converter"]["implementation_path"],
            manifest["validator"]["implementation_path"],
            manifest["package_schema"]["path"],
            "raw/helloao_local/api/c/adam-clarke/books.json",
        }
        for relative in sorted(closure_paths):
            source = ROOT / relative
            target = isolated_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

        converter_path = isolated_root / manifest["converter"]["implementation_path"]
        converter_namespace: dict[str, object] = {
            "__file__": str(converter_path),
            "__name__": f"_lib079_lineage_{mutation.replace('-', '_')}",
        }
        exec(
            compile(converter_path.read_bytes(), str(converter_path), "exec"),
            converter_namespace,
        )
        isolated_convert = converter_namespace["_convert"]

        primary = [
            item
            for item in manifest["authorities"]
            if item["role"] == "primary-source"
        ]
        if mutation == "hash-swap":
            primary[0]["sha256"], primary[1]["sha256"] = (
                primary[1]["sha256"],
                primary[0]["sha256"],
            )
            expected = f"{primary[0]['name']} authority bytes drifted"
        elif mutation == "path-hash-pair-swap":
            for key in ("path", "bytes", "sha256"):
                primary[0][key], primary[1][key] = primary[1][key], primary[0][key]
            expected = "Jamieson-Fausset-Brown catalog lineage is stale"
        elif mutation == "wrong-source":
            replacement = ROOT / "raw/helloao_local/api/c/adam-clarke/books.json"
            primary[0]["path"] = replacement.relative_to(ROOT).as_posix()
            primary[0]["bytes"] = replacement.stat().st_size
            primary[0]["sha256"] = _sha(replacement.read_bytes())
            expected = "Jamieson-Fausset-Brown primary-source authority is malformed"
        else:
            config = next(
                item
                for item in manifest["authorities"]
                if item["name"] == "source-config"
            )
            config["sha256"] = "0" * 64
            expected = "source-config authority bytes drifted"
        path = isolated_root / f"{mutation}.source-manifest.json"
        path.write_bytes(_canonical(manifest))
        with pytest.raises(ValueError) as exc_info:
            mutated = SourceManifest.load(path, repository_root=isolated_root)
            reconstruct(mutated, tmp_path / f"candidate-{mutation}", isolated_convert)
        assert str(exc_info.value) == expected
    finally:
        if isolated_root.exists():
            shutil.rmtree(isolated_root)


@pytest.mark.parametrize(
    "mutation", ["drop-book-field", "drop-envelope", "null-introduction"]
)
def test_jamieson_fausset_brown_oracle_rejects_metadata_and_intro_state_mutations(
    jamieson_fausset_brown_source: SourceManifest,
    jamieson_fausset_brown_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = jamieson_fausset_brown_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    name = "source-accountability.json"
    accountability = json.loads((target / name).read_bytes())
    if mutation == "drop-book-field":
        del accountability["retained_books"][0]["sha256"]
    elif mutation == "drop-envelope":
        accountability["chapter_envelopes"] = accountability["chapter_envelopes"][:-1]
    else:
        accountability["census"]["chapter_introductions_absent"] = 8
    (target / name).write_bytes(_canonical(accountability))
    mutated = _reseal(target, name)
    with pytest.raises(ValueError):
        validate(jamieson_fausset_brown_source, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    [
        "question",
        "evidence",
        "consequence",
        "escalation",
        "mojibake-count",
        "mojibake-scope",
        "mojibake-omission",
    ],
)
def test_jamieson_fausset_brown_oracle_rejects_resealed_unresolved_evidence_mutations(
    jamieson_fausset_brown_source: SourceManifest,
    jamieson_fausset_brown_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = jamieson_fausset_brown_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    name = "unresolved.jsonl"
    unresolved = [
        json.loads(line) for line in (target / name).read_bytes().splitlines()
    ]
    if mutation == "question":
        unresolved[0]["question"] = "False resealed question"
    elif mutation == "evidence":
        unresolved[0]["evidence"] = ["false-resealed-evidence"]
    elif mutation == "consequence":
        unresolved[0]["consequence"] = "False resealed consequence"
    elif mutation == "escalation":
        unresolved[0]["escalation"] = "false-resealed-escalation"
    elif mutation == "mojibake-count":
        unresolved[-1]["evidence"]["census"]["sequence_count"] = 538
    elif mutation == "mojibake-scope":
        unresolved[-1]["evidence"]["census"]["affected_carriers"][
            "commentary-occurrence"
        ]["carrier_count"] = 301
    else:
        unresolved.pop()
    (target / name).write_bytes(b"".join(_canonical(item) for item in unresolved))
    mutated = _reseal(target, name)
    with pytest.raises(ValueError):
        validate(jamieson_fausset_brown_source, mutated, _oracle)


def test_jamieson_fausset_brown_oracle_is_independent_of_producer_and_legacy_parser(
    jamieson_fausset_brown_candidate,
) -> None:
    _, report = jamieson_fausset_brown_candidate
    oracle_source = (
        ROOT / "build/tei/helloao_jamieson_fausset_brown_oracle.py"
    ).read_text(encoding="utf-8")
    assert "helloao_jamieson_fausset_brown_reconstruction" not in oracle_source
    assert "helloao_commentary" not in oracle_source
    assert "data/commentaries/jamieson-fausset-brown" not in oracle_source
    assert len(report.attestation["import_closure_sha256"]) == 64


def test_jamieson_fausset_brown_candidate_is_byte_identical_across_fresh_processes(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    code = (
        "from pathlib import Path; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.helloao_jamieson_fausset_brown_reconstruction import _convert; "
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


def test_jamieson_fausset_brown_runtime_has_no_campaign_or_shared_family_abstractions(
    jamieson_fausset_brown_candidate,
) -> None:
    _, _ = jamieson_fausset_brown_candidate
    for path in (
        ROOT / "build/tei/helloao_jamieson_fausset_brown_reconstruction.py",
        ROOT / "build/tei/helloao_jamieson_fausset_brown_oracle.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "build.reconstruction" not in source
        assert "case_declaration" not in source
        assert "reconstruction.persistence" not in source
        assert "reconstruction.wave" not in source


def test_jamieson_fausset_brown_structure_inventory_preserves_sections_and_paragraphs(
    jamieson_fausset_brown_candidate,
) -> None:
    candidate, _ = jamieson_fausset_brown_candidate
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"tei": TEI_NS}
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    structure = accountability["meaningful_structure"]
    assert structure["carrier_count"] == 5
    assert structure["rendered_carrier_count"] == 5
    assert structure["heading_span_count"] == 6
    assert structure["paragraph_policy"] == {
        "contract": "ocd-source-paragraph-segmentation-v1",
        "delimiter": "\n\n",
        "mode": "split-every-exact-double-newline",
        "carrier_total_count": 18_300,
        "carrier_count_with_delimiter": 17_771,
        "delimiter_count": 42_598,
    }
    occurrence = root.xpath(
        "tei:text/tei:body/tei:div[@n='MAT']/tei:div[@type='chapter'][@n='8']"
        "/tei:div[@type='commentary-occurrence']",
        namespaces=ns,
    )[4]
    assert occurrence.xpath(
        "tei:div[@type='commentary-section']/tei:head/text()", namespaces=ns
    ) == [
        "II. The Procrastinating or Entangled Disciple (Mat 8:21-22).",
        "III. The Irresolute or Wavering Disciple (Luk 9:61-62)",
    ]
    source = json.loads(
        (ROOT / "raw/helloao_local/api/c/jamieson-fausset-brown/MAT/8.json").read_bytes()
    )
    source_text = source["chapter"]["content"][4]["content"][0]
    assert "".join(occurrence.itertext()) == source_text
    book_intro = root.xpath(
        "tei:text/tei:body/tei:div[@n='LUK']/tei:div[@type='book-introduction']",
        namespaces=ns,
    )[0]
    books = json.loads(
        (ROOT / "raw/helloao_local/api/c/jamieson-fausset-brown/books.json").read_bytes()
    )
    book_text = next(item["introduction"] for item in books["books"] if item["id"] == "LUK")
    # A terminal separator closes the last paragraph; it adds no empty paragraph.
    expected_parts = max(1, book_text.count("\n\n") + int(not book_text.endswith("\n\n")))
    assert len(book_intro.xpath("tei:p", namespaces=ns)) == expected_parts
    assert "".join(book_intro.itertext()) == book_text


def test_jamieson_fausset_brown_oracle_rejects_nested_content_in_plain_carrier(
    jamieson_fausset_brown_source: SourceManifest,
    jamieson_fausset_brown_candidate,
    tmp_path: Path,
) -> None:
    candidate, _ = jamieson_fausset_brown_candidate
    target = _resealed_copy(candidate, tmp_path / "nested-plain-carrier")
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    ns = {"tei": TEI_NS}
    occurrence = root.xpath(
        "tei:text/tei:body/tei:div[@n='GEN']/tei:div[@type='chapter'][@n='1']"
        "/tei:div[@type='commentary-occurrence']",
        namespaces=ns,
    )[0]
    paragraph = occurrence.find(f"{{{TEI_NS}}}p")
    assert paragraph is not None
    etree.SubElement(paragraph, f"{{{TEI_NS}}}hi").text = "Invented nested content"
    content = EXPECTED_TEI_PROLOG + etree.tostring(
        root, encoding="UTF-8", xml_declaration=False
    )
    (target / "content.tei.xml").write_bytes(content)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="unaccounted descendants"):
        validate(jamieson_fausset_brown_source, mutated, _oracle)


def test_jamieson_fausset_brown_oracle_rejects_missing_structured_section(
    jamieson_fausset_brown_source: SourceManifest,
    jamieson_fausset_brown_candidate,
    tmp_path: Path,
) -> None:
    candidate, _ = jamieson_fausset_brown_candidate
    target = _resealed_copy(candidate, tmp_path / "missing-structured-section")
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    ns = {"tei": TEI_NS}
    occurrence = root.xpath(
        "tei:text/tei:body/tei:div[@n='MAT']/tei:div[@type='chapter'][@n='8']"
        "/tei:div[@type='commentary-occurrence']",
        namespaces=ns,
    )[4]
    sections = occurrence.xpath("tei:div[@type='commentary-section']", namespaces=ns)
    assert len(sections) == 2
    occurrence.remove(sections[-1])
    content = EXPECTED_TEI_PROLOG + etree.tostring(
        root, encoding="UTF-8", xml_declaration=False
    )
    (target / "content.tei.xml").write_bytes(content)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="omitted section"):
        validate(jamieson_fausset_brown_source, mutated, _oracle)
