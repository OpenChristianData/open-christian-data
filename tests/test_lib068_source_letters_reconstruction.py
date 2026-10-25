from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate

ROOT = Path(__file__).resolve().parents[1]
NS = {"t": "http://www.tei-c.org/ns/1.0"}
RUNTIME_MANIFESTS = {
    "newman-apologia-pro-vita-sua": (
        "96f40195fb09c8767a445ed862e670c6658819f69683f40e5f46c45f022d75ae",
        ROOT / "tests/fixtures/reconstruction-runtime/newman-lib068.source-manifest.json",
    ),
    "donne-devotions-upon-emergent-occasions": (
        "99dded2c8e17b37b2c8ce0f0eb19ca4bc87fe1a152deda4605030f3e32b0bbce",
        ROOT / "tests/fixtures/reconstruction-runtime/donne-lib068.source-manifest.json",
    ),
}


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "build/tei" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("work", RUNTIME_MANIFESTS)
def test_runtime_fixture_preserves_retained_authorities_and_only_updates_closure(work):
    original = ROOT / "sources/structured-text" / work / "LIB-068.source-manifest.json"
    raw = original.read_bytes()
    original_sha256, fixture = RUNTIME_MANIFESTS[work]
    assert hashlib.sha256(raw).hexdigest() == original_sha256
    expected = json.loads(raw)
    checker = load("lib068_source_local_oracle")
    expected["validator"]["import_closure_sha256"] = checker._closure(ROOT)
    assert json.loads(fixture.read_bytes()) == expected


@pytest.fixture(scope="module", params=["newman-apologia-pro-vita-sua", "donne-devotions-upon-emergent-occasions"])
def bundle(request, tmp_path_factory):
    producer = load("lib068_source_local")
    checker = load("lib068_source_local_oracle")
    work = request.param
    manifest = SourceManifest.load(RUNTIME_MANIFESTS[work][1], repository_root=ROOT)
    dest = tmp_path_factory.mktemp("literary")
    candidate = reconstruct(manifest, dest / "candidate", producer._convert)
    report = validate(manifest, candidate, checker._oracle)
    assert report.status == "pass"
    return producer, checker, manifest, candidate, work


def test_real_candidate_validates_and_reproduces(bundle, tmp_path):
    producer, checker, manifest, candidate, work = bundle
    second = reconstruct(manifest, tmp_path / "second", producer._convert)
    assert candidate.sha256 == second.sha256
    assert validate(manifest, second, checker._oracle).status == "pass"
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    if work.startswith("newman"):
        assert len(root.xpath('.//t:div[@type="chapter"]', namespaces=NS)) == 5
        assert len(root.xpath('.//t:div[@type="contents"]//t:div[@type="chapter"]', namespaces=NS)) == 0
    else:
        assert len(root.xpath('.//t:div[@type="station"]', namespaces=NS)) == 23
        for station in root.xpath('.//t:div[@type="station"]', namespaces=NS):
            assert [n.get("type") for n in station.findall("t:div", NS)][:3] == ["meditation", "expostulation", "prayer"]


def test_fresh_process_candidate_is_byte_identical_and_validates(bundle, tmp_path):
    _producer, _checker, manifest, candidate, _work = bundle
    script = (
        "import sys;from pathlib import Path;"
        "from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct,validate;"
        "from build.tei.lib068_source_local import _convert;"
        "from build.tei.lib068_source_local_oracle import _oracle;"
        "r=Path(sys.argv[1]);m=SourceManifest.load(Path(sys.argv[2]),repository_root=r);"
        "c=reconstruct(m,Path(sys.argv[3]),_convert);"
        "assert validate(m,c,_oracle).status=='pass';print(c.sha256)"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script, str(ROOT), str(manifest.path), str(tmp_path / "fresh")],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    assert completed.stdout.strip() == candidate.sha256


@pytest.mark.parametrize("mutation", ["flatten", "move-heading", "move-paragraph", "merge-paragraphs", "omit-line", "invent-text", "lose-emphasis", "wrong-note-target", "wrong-note-id", "invent-emphasis", "shift-emphasis", "split-paragraph", "duplicate-line", "wrong-division-type"])
def test_actual_structure_mutations_rejected(bundle, mutation):
    _, checker, manifest, candidate, work = bundle
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    original = list(root.itertext())
    if mutation == "flatten":
        div = root.xpath('.//t:div[@type="chapter" or @type="meditation"]', namespaces=NS)[0]
        parent = div.getparent(); index = parent.index(div); parent.remove(div)
        for child in reversed(list(div)):
            div.remove(child); parent.insert(index, child)
    elif mutation == "move-heading":
        divs = root.xpath('.//t:div[@type="chapter" or @type="meditation"]', namespaces=NS)
        head = divs[0].find("t:head", NS); divs[0].remove(head); divs[1].insert(0, head)
    elif mutation == "move-paragraph":
        divs = root.xpath('.//t:div[@type="chapter" or @type="meditation"]', namespaces=NS)
        paragraph = divs[0].find("t:p", NS); divs[0].remove(paragraph); divs[1].append(paragraph)
    elif mutation == "merge-paragraphs":
        parent = root.xpath('./t:text/t:body//t:div[count(t:p) > 1]', namespaces=NS)[0]
        paragraphs = parent.findall("t:p", NS)
        first, second = paragraphs[:2]
        for child in list(second): second.remove(child); first.append(child)
        parent.remove(second)
    elif mutation == "omit-line":
        leaf = root.xpath('.//t:seg[@n="1617"]', namespaces=NS)[0]; leaf.getparent().remove(leaf)
    elif mutation == "lose-emphasis":
        etree.strip_tags(root, "{http://www.tei-c.org/ns/1.0}hi")
        assert "".join(root.itertext()) == "".join(original)
    elif mutation == "wrong-note-target":
        root.xpath('.//t:ref[@type="source-note-reference"]', namespaces=NS)[0].set("target", "#unrelated-note")
        assert list(root.itertext()) == original
    elif mutation == "wrong-note-id":
        root.xpath('.//t:note[@type="source-footnote"]', namespaces=NS)[0].set("{http://www.w3.org/XML/1998/namespace}id", "unrelated-note")
        assert list(root.itertext()) == original
    elif mutation == "invent-emphasis":
        leaf = root.xpath('.//t:seg[@n="1"]', namespaces=NS)[0]
        text = leaf.text; leaf.text = None
        etree.SubElement(leaf, "{http://www.tei-c.org/ns/1.0}hi", rend="source-underscore").text = text
        assert "".join(root.itertext()) == "".join(original)
    elif mutation == "shift-emphasis":
        hi = root.xpath('.//t:hi', namespaces=NS)[0]
        assert hi.text.startswith("_")
        if hi.getprevious() is None:
            hi.getparent().text = (hi.getparent().text or "") + "_"
        else:
            hi.getprevious().tail = (hi.getprevious().tail or "") + "_"
        hi.text = hi.text[1:]
        assert "".join(root.itertext()) == "".join(original)
    elif mutation == "split-paragraph":
        paragraph = root.xpath('./t:text/t:body//t:p[count(t:seg)>1]', namespaces=NS)[0]
        second = etree.Element(paragraph.tag)
        leaf = paragraph[-1]; paragraph.remove(leaf); second.append(leaf)
        paragraph.addnext(second)
        assert "".join(root.itertext()) == "".join(original)
    elif mutation == "duplicate-line":
        leaf = root.xpath('.//t:seg[@n="1617"]', namespaces=NS)[0]
        leaf.addnext(deepcopy(leaf))
    elif mutation == "wrong-division-type":
        root.xpath('.//t:div[@type="chapter" or @type="station"]', namespaces=NS)[0].set("type", "unrelated-division")
        assert list(root.itertext()) == original
    else:
        root.xpath('./t:text/t:body//t:p', namespaces=NS)[0].text = "invented"
    if mutation in {"flatten", "move-heading", "move-paragraph", "merge-paragraphs"}:
        assert sorted(root.itertext()) == sorted(original)
    class Changed:
        def member_bytes(self, name):
            assert name == "content.tei.xml"
            return etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    spec = checker._SPECS[work]
    lines = checker._source_lines(manifest.authority_path("retained-text").read_bytes(), spec)
    with pytest.raises(ValueError, match="LIB-068 (literary|readable|source|invented|inline|letter|embedded|normalized source-line|duplicate source-line)"):
        checker._verify_tei(Changed(), work, spec, profile["identity"], lines, profile)


@pytest.mark.parametrize("mutation", ["remove-opener", "wrong-signature-role", "move-document", "swap-recipient", "change-letter-text"])
def test_source_document_relationship_mutations_rejected(bundle, mutation):
    _, checker, manifest, candidate, work = bundle
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    letters = root.xpath('.//t:floatingText[@type="source-letter"]', namespaces=NS)
    if mutation == "remove-opener":
        opener = letters[0].find("t:body/t:opener", NS)
        opener.tag = "{http://www.tei-c.org/ns/1.0}p"
    elif mutation == "wrong-signature-role":
        root.xpath('.//t:floatingText//t:signed', namespaces=NS)[0].tag = "{http://www.tei-c.org/ns/1.0}salute"
    elif mutation == "move-document":
        letters[0].getparent().remove(letters[0]); letters[-1].getparent().append(letters[0])
    elif mutation == "swap-recipient":
        closers = root.xpath('.//t:floatingText[@type="source-letter"]/t:body/t:closer', namespaces=NS)
        first, second = closers[:2]
        a, b = first[-1], second[-1]
        first.remove(a); second.remove(b); first.append(b); second.append(a)
    else:
        letters[0].xpath('.//t:seg[@type="source-line"]', namespaces=NS)[0].text += " altered"
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    spec = checker._SPECS[work]
    lines = checker._source_lines(manifest.authority_path("retained-text").read_bytes(), spec)
    class Changed:
        def member_bytes(self, name):
            return etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with pytest.raises(ValueError, match="LIB-068"):
        checker._verify_tei(Changed(), work, spec, profile["identity"], lines, profile)


@pytest.mark.parametrize("mutation", ["blank-anchor", "shift-station", "overlap-heading", "missing-literal-marker"])
def test_source_discovery_rejects_coordinated_profile_mutation(mutation):
    producer, checker = load("lib068_source_local"), load("lib068_source_local_oracle")
    work = "donne-devotions-upon-emergent-occasions"
    profile = json.loads((ROOT / "sources/structured-text" / work / "LIB-068.reconstruction-profile.json").read_bytes())
    spec = producer._SPECS[work]
    lines = producer._source_lines((ROOT / spec.path).read_bytes(), spec)
    station = next(row for row in profile["literary_sections"] if row["kind"] == "station")
    if mutation == "blank-anchor":
        station.update(line=1609, anchor="")
    elif mutation == "shift-station":
        station.update(line=1614, anchor=lines[1613])
    elif mutation == "overlap-heading":
        station["head_end"] = 1617
    else:
        profile["literal_numeric_markers"] = []

    class Changed:
        def member_bytes(self, name):
            return content

    with pytest.raises(ValueError, match="LIB-068"):
        content = producer._tei(work, spec, profile, lines)
        checker._verify_tei(Changed(), work, checker._SPECS[work], profile["identity"], lines, profile)


def test_source_year_remains_literal(bundle):
    _, _, _, candidate, work = bundle
    if work.startswith("donne-"):
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
        line = root.xpath('.//t:seg[@n="815"]', namespaces=NS)[0]
        assert "[1656]" in "".join(line.itertext())
        assert not line.xpath('.//t:ref[contains(text(), "1656")]', namespaces=NS)


@pytest.mark.parametrize("mutation", ["stanza-kind", "block-attachment", "source-relationship"])
def test_resealed_special_relationship_mutations_rejected(bundle, tmp_path, mutation):
    _, checker, source, candidate, work = bundle
    destination = tmp_path / "resealed-special"
    shutil.copytree(candidate.path, destination)
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    wording = "".join(tree.itertext())
    if mutation == "stanza-kind":
        tree.xpath('.//t:lg[@type="stanza"]', namespaces=NS)[0].set("type", "paragraph")
    elif mutation == "block-attachment":
        quote = tree.xpath('.//t:quote[@type="source-verse"]', namespaces=NS)[0]
        # Change the declared source relationship without losing a single word.
        quote.set("n", str(int(quote.get("n")) + 1))
    elif work.startswith("newman-"):
        cells = tree.xpath('.//t:table[@type="calendar"]/t:row/t:cell', namespaces=NS)
        assert {cell.get("role") for cell in cells} == {"day", "observance"}
        cells[0].set("role", "observance")
    else:
        figure = tree.xpath('.//t:figure[@type="source-illustration-placeholder"]', namespaces=NS)[0]
        figure.set("corresp", "#unrelated-source-line")
    assert "".join(tree.itertext()) == wording
    content = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    (destination / "content.tei.xml").write_bytes(content)
    package_manifest_path = destination / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_bytes())
    member = next(item for item in package_manifest["members"] if item["name"] == "content.tei.xml")
    member.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    package_manifest_path.write_bytes(checker._canonical(package_manifest))
    resealed = CandidatePackage.load(destination)
    resealed.verify_integrity()
    with pytest.raises(ValueError, match="LIB-068"):
        checker._oracle(source, resealed)
