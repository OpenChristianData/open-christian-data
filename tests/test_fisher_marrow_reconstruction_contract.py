from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei import fisher_marrow_oracle as oracle_module
from build.tei.fisher_marrow_oracle import (
    _closure_digest,
    _direct_title_page_identity,
    _exact_false_header_authority,
    _independent_lines,
    _oracle,
    _repository_import_closure,
    _speaker_observations_from_authority,
)
from build.tei.fisher_marrow_reconstruction import _convert, _false_header_authority
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-fisher-marrow-of-modern-divinity.source-manifest.json'
SOURCE = ROOT / "raw/internet-archive/fisher-marrow/marrowmoderndiv00bostgoog_djvu.txt"
MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}
TEI = {"tei": "http://www.tei-c.org/ns/1.0", "xml": "http://www.w3.org/XML/1998/namespace"}


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture(scope="module")
def fisher_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="module")
def fisher_candidate(tmp_path_factory: pytest.TempPathFactory, fisher_manifest: SourceManifest) -> CandidatePackage:
    return reconstruct(fisher_manifest, tmp_path_factory.mktemp("fisher-candidate"), _convert)


def _reseal_member(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _mutated_copy(tmp_path: Path, candidate: CandidatePackage, label: str) -> Path:
    destination = tmp_path / label
    shutil.copytree(candidate.path, destination)
    return destination


def test_manifest_binds_exact_complete_retained_witness(fisher_manifest: SourceManifest) -> None:
    source = fisher_manifest.record["authorities"][0]
    assert source == {
        "name": "retained-fisher-ocr",
        "path": "raw/internet-archive/fisher-marrow/marrowmoderndiv00bostgoog_djvu.txt",
        "role": "primary-source",
        "bytes": 1087403,
        "sha256": "14b46f1a400f8e2c8ec7612019a7769dac46daf31e10f7d6b68212351ff46dd3",
    }
    raw = SOURCE.read_bytes()
    assert len(raw) == source["bytes"]
    assert _sha(raw) == source["sha256"]
    assert raw.count(b"\n") == 22945
    assert len(raw.split(b"\n")) == 22946


def test_complete_candidate_validates_and_stays_nonaccepted(
    fisher_manifest: SourceManifest, fisher_candidate: CandidatePackage
) -> None:
    assert set(fisher_candidate.member_names) == MEMBERS
    assert fisher_candidate.manifest["status"] == "nonaccepted"
    report = validate(fisher_manifest, fisher_candidate, _oracle)
    assert report.status == "pass"
    accountability = json.loads(fisher_candidate.member_bytes("source-accountability.json"))
    assert {
        "lines": accountability["line_count"],
        "represented": accountability["represented_count"],
        "evidence_only": accountability["evidence_only_count"],
        "excluded": accountability["excluded_count"],
        "omitted": accountability["omitted_count"],
        "duplicated": accountability["duplicate_count"],
        "page_candidates": accountability["page_marker_candidate_count"],
        "false_headers": accountability["false_running_header_content_count"],
        "speakers": accountability["high_confidence_speaker_count"],
        "section_speakers": accountability["section_boundary_speaker_count"],
        "rejected_speaker_like": accountability["rejected_paragraph_continuation_speaker_like_count"],
    } == {
        "lines": 22946,
        "represented": 22946,
        "evidence_only": 0,
        "excluded": 0,
        "omitted": 0,
        "duplicated": 0,
        "page_candidates": 170,
        "false_headers": 16,
        "speakers": 455,
        "section_speakers": 24,
        "rejected_speaker_like": 9,
    }


def test_tei_uses_title_page_identity_and_preserves_required_regions(fisher_candidate: CandidatePackage) -> None:
    root = etree.fromstring(fisher_candidate.member_bytes("content.tei.xml"))
    def text(path: str) -> str:
        matches = root.xpath(path, namespaces=TEI)
        assert len(matches) == 1
        return matches[0].text or ""

    assert text("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:pubPlace") == "London"
    assert text("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:publisher") == "Thomas Tegg and Son"
    assert text("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:date") == "1837"
    assert text("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name") == "The Rev. Thomas Boston (notes)"
    header = etree.tostring(root.find("{http://www.tei-c.org/ns/1.0}teiHeader"), encoding="unicode")
    assert "J. and D. Collie" not in header and "1828" not in header
    required = {
        "fisher-region-recommendations": ("front", 242, 538),
        "fisher-region-part-two-front": ("body", 16577, 16775),
        "fisher-region-part-two": ("body", 16776, 21185),
        "fisher-region-appendix": ("back", 21186, 22946),
    }
    for identifier, (part, start, end) in required.items():
        nodes = root.xpath(f"./tei:text/tei:{part}/tei:div[@xml:id=$identifier]", identifier=identifier, namespaces=TEI)
        assert len(nodes) == 1
        ids = [value for value in nodes[0].xpath(".//@xml:id", namespaces=TEI) if value.startswith("fisher-line-")]
        assert ids == [f"fisher-line-{line:05d}" for line in range(start, end + 1)]
    false_headers = [1656, 3155, 4579, 7146, 7602, 13507, 14521, 15798, 17422, 17645, 17725, 18094, 18676, 19162, 21145, 21276]
    for line in false_headers:
        node = root.xpath("//*[@xml:id=$identifier]", identifier=f"fisher-line-{line:05d}", namespaces=TEI)[0]
        assert node.get("ana") == "#substantive-content #not-a-running-header"
    assert len(root.xpath("//tei:text//tei:sp", namespaces=TEI)) == 455
    section_speakers = root.xpath("//tei:text//tei:sp[contains(@ana, 'section-boundary-speaker')]", namespaces=TEI)
    assert len(section_speakers) == 24
    for line in (1301, 1363, 2058):
        wrapper = root.xpath("//*[@xml:id=$identifier]", identifier=f"fisher-line-{line:05d}", namespaces=TEI)[0]
        assert etree.QName(wrapper).localname == "div"
        assert [etree.QName(child).localname for child in wrapper[:2]] == ["head", "sp"]
    for line in (2899, 3080, 6290, 9115, 15083, 15957, 16997, 19112, 19687):
        node = root.xpath("//*[@xml:id=$identifier]", identifier=f"fisher-line-{line:05d}", namespaces=TEI)[0]
        assert etree.QName(node).localname != "sp"
    readme = fisher_candidate.member_bytes("README.source.md")
    assert b"retain the Google watermark and Google Book Search attribution" in readme
    assert b"do not remove it" in readme


def test_fresh_process_complete_packages_are_byte_identical(tmp_path: Path) -> None:
    script = (
        "from pathlib import Path; import hashlib,sys; "
        "from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct; "
        "from build.tei.fisher_marrow_reconstruction import _convert; "
        "r=Path(sys.argv[1]); m=SourceManifest.load(r/'tests/fixtures/reconstruction-runtime/puritan-fisher-marrow-of-modern-divinity.source-manifest.json',repository_root=r); "
        "c=reconstruct(m,Path(sys.argv[2]),_convert); "
        "print('|'.join(n+':'+hashlib.sha256(c.member_bytes(n)).hexdigest() for n in c.member_names))"
    )
    outputs = []
    for ordinal in (1, 2):
        completed = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), str(tmp_path / f"fresh-{ordinal}")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(completed.stdout.strip())
    assert outputs[0] == outputs[1]


def test_oracle_import_closure_is_transitive_and_producer_independent(fisher_manifest: SourceManifest) -> None:
    policy = json.loads(fisher_manifest.authority_path("validation-policy").read_bytes())
    assert _closure_digest(ROOT, policy) == fisher_manifest.record["validator"]["import_closure_sha256"]
    source = Path(oracle_module.__file__).read_text(encoding="utf-8")
    for forbidden in policy["forbidden_import_prefixes"]:
        assert f"import {forbidden}" not in source
        assert f"from {forbidden}" not in source
    assert "retained_source_landmarks" not in source


def test_recursive_closure_contains_real_helpers_and_detects_helper_drift(
    fisher_manifest: SourceManifest, tmp_path: Path
) -> None:
    policy = json.loads(fisher_manifest.authority_path("validation-policy").read_bytes())
    forbidden = tuple(policy["forbidden_import_prefixes"])
    records = _repository_import_closure(ROOT, Path(oracle_module.__file__), forbidden)
    paths = {item["path"] for item in records}
    assert {
        "build/tei/fisher_marrow_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/tei/validate.py",
    } <= paths
    synthetic = tmp_path / "closure-project"
    package = synthetic / "pkg"
    package.mkdir(parents=True)
    entry = synthetic / "entry.py"
    initializer = package / "__init__.py"
    module = package / "module.py"
    helper = package / "helper.py"
    entry.write_text("import pkg.module\nVALUE = pkg.module.VALUE\n", encoding="utf-8")
    initializer.write_text("from . import helper\n", encoding="utf-8")
    module.write_text("VALUE = 1\n", encoding="utf-8")
    helper.write_text("VALUE = 1\n", encoding="utf-8")
    first_records = _repository_import_closure(synthetic, entry, ())
    assert {item["path"] for item in first_records} == {
        "entry.py", "pkg/__init__.py", "pkg/helper.py", "pkg/module.py"
    }
    first = _sha(_canonical(first_records))
    initializer.write_text("from . import helper\nINITIALIZER = True\n", encoding="utf-8")
    after_initializer = _sha(_canonical(_repository_import_closure(synthetic, entry, ())))
    assert first != after_initializer
    helper.write_text("VALUE = 2\n", encoding="utf-8")
    after_helper = _sha(_canonical(_repository_import_closure(synthetic, entry, ())))
    assert after_initializer != after_helper


def test_metadata_cannot_be_invented_by_coordinating_profile_and_policy(
    fisher_manifest: SourceManifest,
) -> None:
    raw = SOURCE.read_bytes()
    profile = json.loads(fisher_manifest.authority_path("reconstruction-profile").read_bytes())
    policy = json.loads(fisher_manifest.authority_path("validation-policy").read_bytes())
    assert _direct_title_page_identity(raw, profile, policy)["publisher"] == "Thomas Tegg and Son"
    changed_profile = copy.deepcopy(profile)
    changed_policy = copy.deepcopy(policy)
    changed_profile["witness_identity"]["publisher"] = "Invented Publisher"
    changed_policy["tei_header"]["publisher"] = "Invented Publisher"
    # Recomputed digests model resealed authority bytes; direct retained-source
    # derivation still rejects the coordinated invention.
    assert _sha(_canonical(changed_profile)) != _sha(_canonical(profile))
    assert _sha(_canonical(changed_policy)) != _sha(_canonical(policy))
    with pytest.raises(ValueError, match="invented independently"):
        _direct_title_page_identity(raw, changed_profile, changed_policy)


@pytest.mark.parametrize(
    "values",
    [
        [str(item) for item in range(16)],
        [float(item) for item in range(16)],
        [True, *range(1, 16)],
        [0, *range(1, 16)],
        [*range(1, 16), 22947],
        [*range(1, 16), 15],
        list(range(1, 16)),
        [1656, 3155, 4579, 7146, 7602, 13507, 14521, 15798, 17422, 17645, 17725, 18094, 18676, 19162, 21145, 21277],
    ],
)
def test_false_header_profile_census_fails_closed(values: list[object], fisher_manifest: SourceManifest) -> None:
    profile = json.loads(fisher_manifest.authority_path("reconstruction-profile").read_bytes())
    landmarks = copy.deepcopy(profile["landmarks"])
    landmarks["false_running_header_lines"] = values
    with pytest.raises(ValueError):
        _false_header_authority({"false_running_header_lines": values})
    with pytest.raises(ValueError):
        _exact_false_header_authority(landmarks, _independent_lines(SOURCE.read_bytes()))


def test_same_count_speaker_swap_cannot_be_resealed(fisher_manifest: SourceManifest) -> None:
    profile = json.loads(fisher_manifest.authority_path("reconstruction-profile").read_bytes())
    changed = copy.deepcopy(profile)
    authority = changed["speaker_observation_authority"]
    accepted = authority["ordered_line_numbers"]
    rejected = authority["rejected_paragraph_continuation_line_numbers"]
    accepted[accepted.index(1297)] = 3080
    accepted.sort()
    rejected[rejected.index(3080)] = 1297
    rejected.sort()
    authority["ordered_line_numbers_sha256"] = _sha(
        json.dumps(accepted, separators=(",", ":")).encode("utf-8")
    )
    assert len(accepted) == 455 and len(set(accepted)) == 455
    assert len(rejected) == 9 and len(set(rejected)) == 9
    with pytest.raises(ValueError, match="reviewed authority|authority digest"):
        _speaker_observations_from_authority(_independent_lines(SOURCE.read_bytes()), changed)


class _PassingSchema:
    error_log = type("Log", (), {"last_error": None})()

    @staticmethod
    def validate(document: object) -> bool:
        return True


@pytest.mark.parametrize(
    "mutation",
    ["omission", "duplication", "reorder", "misattachment", "invention", "wrong-source", "wrong-identity", "lost-uncertainty", "speaker-omission", "speaker-invention", "ordinary-dialogue-boundary-shift", "section-dialogue-boundary-shift"],
)
def test_independent_oracle_rejects_fidelity_mutations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fisher_manifest: SourceManifest,
    fisher_candidate: CandidatePackage,
    mutation: str,
) -> None:
    # The baseline test runs the real vendored XSD and 22,946-entry JSON schema.
    # Mutation tests retain all source/accounting checks while avoiding eight
    # redundant schema compilations.
    monkeypatch.setattr(oracle_module, "compiled_schema", lambda: _PassingSchema())
    path = _mutated_copy(tmp_path, fisher_candidate, mutation)
    if mutation in {"wrong-source"}:
        provenance = json.loads((path / "provenance.json").read_bytes())
        provenance["authorities"]["retained-fisher-ocr"]["sha256"] = "0" * 64
        mutated = _reseal_member(path, "provenance.json", _canonical(provenance))
    else:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
        root = etree.fromstring((path / "content.tei.xml").read_bytes(), parser)
        by_id = lambda line: root.xpath("//*[@xml:id=$value]", value=f"fisher-line-{line:05d}", namespaces=TEI)[0]
        if mutation == "omission":
            node = by_id(1000)
            node.getparent().remove(node)
        elif mutation == "duplication":
            node = by_id(1000)
            node.addnext(copy.deepcopy(node))
        elif mutation == "reorder":
            first, second = by_id(1000), by_id(1001)
            assert first.getparent() is second.getparent()
            parent = first.getparent()
            index = parent.index(first)
            parent.remove(second)
            parent.insert(index, second)
        elif mutation == "misattachment":
            node = by_id(1000)
            appendix = root.xpath("//*[@xml:id='fisher-region-appendix']", namespaces=TEI)[0]
            node.getparent().remove(node)
            appendix[0].append(node)
        elif mutation == "invention":
            by_id(1000).text = (by_id(1000).text or "") + " INVENTED"
        elif mutation == "wrong-identity":
            root.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:pubPlace", namespaces=TEI)[0].text = "Edinburgh"
        elif mutation == "lost-uncertainty":
            node = by_id(883)
            node.text = (node.text or "").replace("§", "")
        elif mutation == "speaker-omission":
            node = by_id(1301)
            replacement = etree.Element("{http://www.tei-c.org/ns/1.0}head")
            replacement.set("{http://www.w3.org/XML/1998/namespace}id", "fisher-line-01301")
            replacement.set("type", "source-heading")
            replacement.text = (node[0].text or "") + (node[1][0].text or "") + (node[1][1].text or "")
            parent = node.getparent()
            position = parent.index(node)
            continuations = list(node)[2:]
            for continuation in continuations:
                node.remove(continuation)
            parent.replace(node, replacement)
            for offset, continuation in enumerate(continuations, start=1):
                parent.insert(position + offset, continuation)
        elif mutation == "speaker-invention":
            node = by_id(3080)
            value = node.text or ""
            prefix, body = value.split(" ", 1)
            replacement = etree.Element("{http://www.tei-c.org/ns/1.0}sp")
            replacement.set("{http://www.w3.org/XML/1998/namespace}id", "fisher-line-03080")
            replacement.set("ana", "#source-dialogue-line")
            speaker = etree.SubElement(replacement, "{http://www.tei-c.org/ns/1.0}speaker")
            speaker.text = prefix + " "
            paragraph = etree.SubElement(replacement, "{http://www.tei-c.org/ns/1.0}p")
            paragraph.text = body
            node.getparent().replace(node, replacement)
        elif mutation == "ordinary-dialogue-boundary-shift":
            node = by_id(1297)
            speaker, paragraph = node[0], node[1]
            body = paragraph.text or ""
            split = body.find(" ") + 1
            assert split > 0
            speaker.text = (speaker.text or "") + body[:split]
            paragraph.text = body[split:]
        elif mutation == "section-dialogue-boundary-shift":
            node = by_id(1301)
            heading, speaker = node[0], node[1][0]
            prefix = heading.text or ""
            assert prefix
            heading.text = prefix[:-1]
            speaker.text = prefix[-1] + (speaker.text or "")
        mutated = _reseal_member(path, "content.tei.xml", etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    with pytest.raises(ValueError):
        _oracle(fisher_manifest, mutated)
