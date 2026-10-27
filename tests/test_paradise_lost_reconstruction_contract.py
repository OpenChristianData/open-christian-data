from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

import build.tei.paradise_lost_oracle as oracle_module
from build.tei.paradise_lost_oracle import _closure, _oracle
from build.tei.paradise_lost_reconstruction import _convert
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/paradise-lost.source-manifest.json'
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"t": TEI, "xml": XML}
EXPECTED_MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _norm(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


@pytest.fixture(scope="module")
def paradise_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    destination = tmp_path_factory.mktemp("paradise-lost") / "candidate"
    candidate = reconstruct(source, destination, _convert)
    report = validate(source, candidate, _oracle)
    return source, candidate, report


def _reseal_member(
    candidate: CandidatePackage,
    destination: Path,
    member_name: str,
    content: bytes,
) -> CandidatePackage:
    shutil.copytree(candidate.path, destination)
    (destination / member_name).write_bytes(content)
    manifest = json.loads((destination / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    member["bytes"] = len(content)
    member["sha256"] = _sha(content)
    (destination / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(destination)


def _reseal_manifest(
    candidate: CandidatePackage,
    destination: Path,
    mutate,
) -> CandidatePackage:
    shutil.copytree(candidate.path, destination)
    manifest = json.loads((destination / "manifest.json").read_bytes())
    mutate(manifest)
    (destination / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(destination)


def test_complete_nonaccepted_candidate_preserves_source_floor(paradise_candidate) -> None:
    source, candidate, report = paradise_candidate
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert set(candidate.member_names) == EXPECTED_MEMBERS
    assert candidate.manifest["status"] == "nonaccepted"
    assert report.status == "pass"
    assert accountability["observation_count"] == 55_544
    assert accountability["represented_count"] == 10_847
    assert accountability["evidence_only_count"] == 44_697
    assert len(accountability["source_members"]) == 33
    assert sum(item["bytes"] for item in accountability["source_members"]) == 3_747_043
    assert len({item["source_address"] for item in accountability["observations"]}) == 55_544
    assert len(tei.xpath("//t:div[@xml:id]", namespaces=NS)) == 40
    assert len(tei.xpath("//t:div[starts-with(@xml:id,'book-')]", namespaces=NS)) == 12
    assert len(tei.xpath("//t:div[starts-with(@xml:id,'argument-')]", namespaces=NS)) == 12
    assert len(tei.xpath("//t:div[starts-with(@xml:id,'poem-')]", namespaces=NS)) == 12
    assert len(tei.xpath("//t:lg[@type='stanza']", namespaces=NS)) == 400
    assert len(tei.xpath("//t:l", namespaces=NS)) == 10_568
    assert len(tei.xpath("//t:lb", namespaces=NS)) == 17
    assert len(tei.xpath("//t:ref", namespaces=NS)) == 14
    assert len(tei.xpath("//t:figure", namespaces=NS)) == 3
    assert len(tei.xpath("//t:abbr[@rend='eoc']", namespaces=NS)) == 1
    assert provenance["status"] == "nonaccepted"
    assert provenance["retained_commit"] == "057e75b8eb8bef94ee2d7d84276e7e4e6a5878fc"
    assert provenance["retained_tree"] == "e9d7860cd6d0ece2bdc4648ccf7ee63281509bec"
    assert source.record["source_id"] == "standard-ebooks-paradise-lost-retained-checkout"


def test_repeated_lines_remain_distinct_source_occurrences(paradise_candidate) -> None:
    _, candidate, _ = paradise_candidate
    bindings = json.loads(candidate.member_bytes("source-accountability.json"))["semantic_bindings"]
    lines = [line for group in bindings["verse_groups"] for stanza in group["stanzas"] for line in stanza["lines"]]
    counts = Counter(item["value"] for item in lines)
    repeated = {value: count for value, count in counts.items() if count > 1}
    assert repeated == {
        "Frequenting, sent from hearts contrite, in sign": 2,
        "Thrones, Dominations, Princedoms, Virtues, Powers,": 2,
    }
    for value in repeated:
        rows = [item for item in lines if item["value"] == value]
        assert len({item["path"] for item in rows}) == 2
        assert len({item["corresp"] for item in rows}) == 2


@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "invention",
        "reorder",
        "repeated-address-swap",
        "target-swap",
        "uniform-reason",
        "scope-collapse",
        "toc-swap",
        "image-string-swap",
        "line-binding-swap",
    ],
)
def test_oracle_rejects_resealed_accountability_attacks(
    paradise_candidate, tmp_path: Path, mutation: str
) -> None:
    source, candidate, _ = paradise_candidate
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    observations = accountability["observations"]
    if mutation == "omission":
        observations.pop(100)
        observations.append(deepcopy(observations[-1]))
    elif mutation == "duplication":
        observations[200] = deepcopy(observations[199])
    elif mutation == "invention":
        observations[300]["value"] = "invented Paradise Lost source value"
        observations[300]["value_sha256"] = _sha(observations[300]["value"].encode())
    elif mutation == "reorder":
        observations[400], observations[401] = observations[401], observations[400]
    elif mutation == "repeated-address-swap":
        rows = [item for item in observations if item["value"] == "Thrones, Dominations, Princedoms, Virtues, Powers,"]
        assert len(rows) == 2
        rows[0]["source_address"], rows[1]["source_address"] = rows[1]["source_address"], rows[0]["source_address"]
    elif mutation == "target-swap":
        rows = [item for item in observations if item["disposition"] == "represented" and item["target"].startswith("tei:#")]
        rows[0]["target"], rows[-1]["target"] = rows[-1]["target"], rows[0]["target"]
    elif mutation == "uniform-reason":
        for item in observations:
            if item["disposition"] == "evidence-only":
                item["reason"] = "one-uniform-wrong-reason"
    elif mutation == "scope-collapse":
        represented = next(item for item in observations if item["disposition"] == "represented")
        evidence = next(item for item in observations if item["disposition"] == "evidence-only")
        represented["disposition"] = "evidence-only"
        evidence["disposition"] = "represented"
        accountability["ordered_dispositions_sha256"] = _sha(_canonical([item["disposition"] for item in observations]))
    elif mutation == "toc-swap":
        toc = accountability["semantic_bindings"]["toc"]
        toc[0]["target"], toc[1]["target"] = toc[1]["target"], toc[0]["target"]
    elif mutation == "image-string-swap":
        rows = accountability["semantic_bindings"]["image_strings"]
        rows[0]["value"], rows[1]["value"] = rows[1]["value"], rows[0]["value"]
    elif mutation == "line-binding-swap":
        groups = accountability["semantic_bindings"]["verse_groups"]
        first = groups[0]["stanzas"][0]["lines"]
        second = groups[0]["stanzas"][1]["lines"]
        first[0], second[0] = second[0], first[0]
    mutated = _reseal_member(candidate, tmp_path / mutation, "source-accountability.json", _canonical(accountability))
    with pytest.raises(ValueError):
        _oracle(source, mutated)


@pytest.mark.parametrize(
    "mutation",
    [
        "line-omission",
        "line-duplication",
        "line-invention",
        "line-corresp-swap",
        "repeated-line-corresp-swap",
        "line-moved-between-stanzas",
        "book-reorder",
        "front-body-misplacement",
        "heading-invention",
        "link-target-invention",
        "image-url-invention",
        "date-invention",
        "language-swap",
        "abbr-rendition-invention",
        "rights-conflation",
    ],
)
def test_oracle_rejects_resealed_tei_attacks(
    paradise_candidate, tmp_path: Path, mutation: str
) -> None:
    source, candidate, _ = paradise_candidate
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    lines = tei.xpath("//t:l", namespaces=NS)
    if mutation == "line-omission":
        lines[0].getparent().remove(lines[0])
    elif mutation == "line-duplication":
        lines[0].addnext(deepcopy(lines[0]))
    elif mutation == "line-invention":
        lines[0].text = "Invented line"
    elif mutation == "line-corresp-swap":
        lines[0].set("corresp", lines[1].get("corresp"))
        lines[1].set("corresp", "#pl-source-invented")
    elif mutation == "repeated-line-corresp-swap":
        values = Counter(_norm(line) for line in lines)
        value = next(text for text, count in values.items() if count > 1)
        pair = [line for line in lines if _norm(line) == value]
        pair[0].set("corresp", pair[1].get("corresp"))
        pair[1].set("corresp", "#pl-source-repeated-relocation")
    elif mutation == "line-moved-between-stanzas":
        stanzas = [node for node in tei.xpath("//t:lg[@type='stanza']", namespaces=NS) if len(node.xpath("./t:l", namespaces=NS))]
        line = stanzas[0].xpath("./t:l", namespaces=NS)[0]
        stanzas[0].remove(line)
        stanzas[1].insert(0, line)
    elif mutation == "book-reorder":
        body = tei.xpath("/t:TEI/t:text/t:body", namespaces=NS)[0]
        books = body.xpath("./t:div", namespaces=NS)
        body.remove(books[0])
        body.insert(1, books[0])
    elif mutation == "front-body-misplacement":
        front = tei.xpath("/t:TEI/t:text/t:front", namespaces=NS)[0]
        body = tei.xpath("/t:TEI/t:text/t:body", namespaces=NS)[0]
        book = body.xpath("./t:div", namespaces=NS)[0]
        body.remove(book)
        front.append(book)
    elif mutation == "heading-invention":
        tei.xpath("//t:head", namespaces=NS)[0].text = "Invented heading"
    elif mutation == "link-target-invention":
        tei.xpath("//t:ref", namespaces=NS)[0].set("target", "https://example.invalid/invented")
    elif mutation == "image-url-invention":
        tei.xpath("//t:graphic", namespaces=NS)[0].set("url", "invented.svg")
    elif mutation == "date-invention":
        tei.xpath("//t:date[@when]", namespaces=NS)[0].set("when", "2099-01-01")
    elif mutation == "language-swap":
        tei.xpath("//t:div[@xml:lang]", namespaces=NS)[0].set(f"{{{XML}}}lang", "en-GB")
    elif mutation == "abbr-rendition-invention":
        tei.xpath("//t:abbr", namespaces=NS)[0].set("rend", "invented")
    elif mutation == "rights-conflation":
        availability = tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:publicationStmt/t:availability", namespaces=NS)[0]
        availability.xpath("./t:p", namespaces=NS)[0].text = "Worldwide public domain and accepted for publication."
    content = etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    mutated = _reseal_member(candidate, tmp_path / mutation, "content.tei.xml", content)
    with pytest.raises(ValueError):
        _oracle(source, mutated)


@pytest.mark.parametrize(
    "mutation",
    [
        "appended-definitive-1667-date",
        "appended-worldwide-clearance-authority",
        "appended-selected-reading-division",
    ],
)
def test_oracle_rejects_resealed_xsd_valid_additive_tei_inventions(
    paradise_candidate, tmp_path: Path, mutation: str
) -> None:
    source, candidate, _ = paradise_candidate
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    namespace = f"{{{TEI}}}"
    if mutation == "appended-definitive-1667-date":
        bibl = tei.xpath(
            "/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl", namespaces=NS
        )[0]
        date = etree.SubElement(bibl, f"{namespace}date", when="1667")
        date.text = "1667 (definitive publication date)"
    elif mutation == "appended-worldwide-clearance-authority":
        publication = tei.xpath(
            "/t:TEI/t:teiHeader/t:fileDesc/t:publicationStmt", namespaces=NS
        )[0]
        authority = etree.SubElement(publication, f"{namespace}authority")
        authority.text = (
            "Worldwide public-domain clearance and publication authorization."
        )
    elif mutation == "appended-selected-reading-division":
        body = tei.xpath("/t:TEI/t:text/t:body", namespaces=NS)[0]
        selected = etree.SubElement(body, f"{namespace}div", type="selected-reading")
        paragraph = etree.SubElement(selected, f"{namespace}p")
        paragraph.text = "Definitive normalized reading."
    xsd = compiled_tei_schema(source.authority_path("tei-p5-xsd"))
    assert xsd.validate(etree.ElementTree(tei))
    content = etree.tostring(
        tei, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )
    mutated = _reseal_member(
        candidate,
        tmp_path / mutation,
        "content.tei.xml",
        content,
    )
    with pytest.raises(ValueError, match="complete TEI projection"):
        _oracle(source, mutated)


@pytest.mark.parametrize("mutation", ["commit", "metadata", "rights", "closure"])
def test_oracle_rejects_resealed_provenance_attacks(
    paradise_candidate, tmp_path: Path, mutation: str
) -> None:
    source, candidate, _ = paradise_candidate
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if mutation == "commit":
        provenance["retained_commit"] = "0" * 40
    elif mutation == "metadata":
        provenance["metadata_claims"]["opf"]["languages"] = ["invented"]
    elif mutation == "rights":
        provenance["rights"]["underlying_text_and_artwork"] = "worldwide cleared"
    else:
        provenance["producer_import_closure_sha256"] = "0" * 64
    mutated = _reseal_member(candidate, tmp_path / mutation, "provenance.json", _canonical(provenance))
    with pytest.raises(ValueError):
        _oracle(source, mutated)


def test_oracle_rejects_coordinated_metadata_invention(paradise_candidate, tmp_path: Path) -> None:
    source, candidate, _ = paradise_candidate
    destination = tmp_path / "coordinated-metadata"
    shutil.copytree(candidate.path, destination)
    accountability = json.loads((destination / "source-accountability.json").read_bytes())
    provenance = json.loads((destination / "provenance.json").read_bytes())
    accountability["semantic_bindings"]["metadata_claims"]["opf"]["languages"] = ["invented"]
    provenance["metadata_claims"]["opf"]["languages"] = ["invented"]
    for name, value in (("source-accountability.json", _canonical(accountability)), ("provenance.json", _canonical(provenance))):
        (destination / name).write_bytes(value)
    manifest = json.loads((destination / "manifest.json").read_bytes())
    for member in manifest["members"]:
        content = (destination / member["name"]).read_bytes()
        member["bytes"], member["sha256"] = len(content), _sha(content)
    (destination / "manifest.json").write_bytes(_canonical(manifest))
    mutated = CandidatePackage.load(destination)
    with pytest.raises(ValueError):
        _oracle(source, mutated)


def test_oracle_rejects_readme_worldwide_clearance_conflation(paradise_candidate, tmp_path: Path) -> None:
    source, candidate, _ = paradise_candidate
    content = candidate.member_bytes("README.source.md").replace(
        b"other jurisdictions remain uncertain",
        b"all jurisdictions are cleared",
    )
    mutated = _reseal_member(candidate, tmp_path / "readme-rights", "README.source.md", content)
    with pytest.raises(ValueError):
        _oracle(source, mutated)


def test_oracle_rejects_unresolved_boundary_omission(paradise_candidate, tmp_path: Path) -> None:
    source, candidate, _ = paradise_candidate
    content = b"\n".join(candidate.member_bytes("unresolved.jsonl").splitlines()[:-1]) + b"\n"
    mutated = _reseal_member(candidate, tmp_path / "unresolved", "unresolved.jsonl", content)
    with pytest.raises(ValueError):
        _oracle(source, mutated)


@pytest.mark.parametrize("mutation", ["accepted", "converter", "source-manifest"])
def test_oracle_rejects_candidate_manifest_authority_attacks(
    paradise_candidate, tmp_path: Path, mutation: str
) -> None:
    source, candidate, _ = paradise_candidate

    def mutate(manifest: dict[str, object]) -> None:
        if mutation == "accepted":
            manifest["status"] = "accepted"
        elif mutation == "converter":
            manifest["converter"]["id"] = "invented-converter"
        else:
            manifest["source_manifest"]["sha256"] = "0" * 64

    mutated = _reseal_manifest(candidate, tmp_path / mutation, mutate)
    with pytest.raises(ValueError):
        _oracle(source, mutated)


def test_oracle_rejects_wrong_actual_git_evidence(
    paradise_candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, candidate, _ = paradise_candidate
    actual = oracle_module._git_evidence(
        ROOT / "raw/standard_ebooks/john-milton_paradise-lost"
    )
    wrong = dict(actual)
    wrong["tree"] = "0" * 40
    monkeypatch.setattr(oracle_module, "_git_evidence", lambda _: wrong)
    with pytest.raises(ValueError, match="Git authority"):
        _oracle(source, candidate)


def test_oracle_rejects_recursive_closure_drift(
    paradise_candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, candidate, _ = paradise_candidate
    monkeypatch.setattr(oracle_module, "_closure", lambda *_: ("0" * 64, []))
    with pytest.raises(ValueError, match="closure"):
        _oracle(source, candidate)


def test_oracle_closure_is_independent_and_forbids_incumbent_answers() -> None:
    digest, members = _closure(ROOT)
    assert len(digest) == 64
    imported = {str(item["path"]).removesuffix(".py").replace("/", ".") for item in members}
    forbidden = (
        "build.tei.paradise_lost_reconstruction",
        "build.tei.se_to_tei",
        "build.reconstruction",
        "build.parsers.standard_ebooks",
        "ocd_kernel.reconstruction.case_declaration",
        "ocd_kernel.reconstruction.persistence",
        "ocd_kernel.reconstruction.wave",
    )
    assert not any(name.startswith(forbidden) for name in imported)


def test_runtime_rejects_editable_contract_shadow_subprocess(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow"
    package = shadow / "ocd_kernel/reconstruction"
    package.mkdir(parents=True)
    (shadow / "ocd_kernel/__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "contract.py").write_text("class SourceManifest: pass\n", encoding="utf-8")
    script = (
        "from pathlib import Path\n"
        "import build.tei.paradise_lost_reconstruction as module\n"
        f"module._runtime_paths(Path({str(ROOT)!r}))\n"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(shadow) + os.pathsep + str(ROOT)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=shadow,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "editable/import-shadow contract" in completed.stderr


def test_candidate_is_byte_identical_across_fresh_processes(tmp_path: Path) -> None:
    outputs = []
    for number in (1, 2):
        destination = tmp_path / f"fresh-{number}"
        script = (
            "from pathlib import Path\n"
            "from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct\n"
            "from build.tei.paradise_lost_reconstruction import _convert\n"
            f"root=Path({str(ROOT)!r})\n"
            f"source=SourceManifest.load(Path({str(MANIFEST)!r}),repository_root=root)\n"
            f"candidate=reconstruct(source,Path({str(destination)!r}),_convert)\n"
            "print(candidate.sha256)\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.append(
            (
                completed.stdout.strip(),
                {item.name: item.read_bytes() for item in destination.iterdir()},
            )
        )
    assert outputs[0] == outputs[1]
