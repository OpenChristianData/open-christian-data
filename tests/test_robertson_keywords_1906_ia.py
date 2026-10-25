"""Source-derived baseline and semantic mutations for Robertson's IA candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.robertson_keywords_1906_ia import _convert, _scan_map
from build.tei import robertson_keywords_1906_ia_oracle as oracle
from build.tei.robertson_keywords_1906_ia_oracle import _source_set, check as _check
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.reconstruction import contract

ROOT = Path(__file__).resolve().parents[1]
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MANIFEST = ROOT / "sources/structured-text/robertson-keywords-1906/source-manifest-text-review-20261011-v4.json"


@pytest.fixture(scope="module", autouse=True)
def historical_work_identity():
    """Replay the source's original work record without replacing live metadata."""
    manifest_raw = MANIFEST.read_bytes()
    record = json.loads(manifest_raw)
    authority = next(row for row in record["authorities"]
                     if row["name"] == "canonical-work-identity")
    relative = "library/works/robertson-keywords-in-the-teaching-of-jesus/work.json"
    assert authority["path"] == relative
    frozen = ROOT / "tests/fixtures/reconstruction-runtime/authorities/robertson-keywords-original-bound-work.json"
    raw = frozen.read_bytes()
    assert len(raw) == authority["bytes"]
    assert hashlib.sha256(raw).hexdigest() == authority["sha256"] == "3152a2760ed58989fef0c158dcba8e477140bdfa4efac7b03e0dfd7de572a1df"
    current = ROOT / relative
    current_raw = current.read_bytes()
    original_io = contract.io_path
    original_resolver = oracle.resolve_repo_path
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(contract, "io_path", lambda path:
                      frozen if Path(path) == current else original_io(path))
        patch.setattr(oracle, "resolve_repo_path", lambda root, path:
                      frozen if Path(root) == ROOT and path == relative
                      else original_resolver(root, path))
        yield
    assert current.read_bytes() == current_raw
    assert MANIFEST.read_bytes() == manifest_raw


def check(root, content, account):
    return _check(root, content, account, source_manifest=json.loads(MANIFEST.read_bytes()))


@pytest.fixture(scope="module")
def source_manifest() -> SourceManifest:
    return SourceManifest.load(
        MANIFEST,
        repository_root=ROOT,
    )


@pytest.fixture(scope="module")
def pair(source_manifest: SourceManifest) -> tuple[bytes, bytes]:
    output = _convert(source_manifest)
    return output["content.tei.xml"], output["source-accountability.json"]


def parse(data: bytes) -> etree._Element:
    return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))


def test_complete_source_baseline(pair):
    content, account = pair
    assert check(ROOT, content, account) == {
        "pages": 136, "paragraphs": 1178, "lines": 3877}
    root = parse(content)
    assert [len(root.findall(f".//{{{TEI}}}{section}/{{{TEI}}}div/{{{TEI}}}div"))
            for section in ("front", "body", "back")] == [14, 111, 11]
    assert [node.get("type") for node in root.findall(
        f"./{{{TEI}}}text/{{{TEI}}}back/{{{TEI}}}div")] == [
            "scripture-index", "topical-index", "bibliography", "appended-material"]
    rows = json.loads(account)["pages"]
    account_record = json.loads(account)
    assert account_record["work_id"] == "robertson-keywords-in-the-teaching-of-jesus"
    assert account_record["textual_form_id"] == "keywords-english"
    assert account_record["edition_id"] == "keywords-1906-abps"
    assert account_record["acquisition_id"] == "keywords-1906-ia-keywordsinteachi01robe"
    assert rows[0]["leaf"] == 1 and rows[-1]["leaf"] == 136
    assert rows[132]["group"] == "appended-material"
    assert root.xpath("//*[@xml:id='leaf-0134']")
    assert len(root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title",
                          namespaces={"tei": TEI})) == 1
    assert root.xpath("count(./tei:text/tei:body/tei:div)",
                      namespaces={"tei": TEI}) == 7
    assert len(root.xpath(".//tei:div[@type='contents-table']/tei:list/tei:item",
                          namespaces={"tei": TEI})) == 7
    assert len(root.xpath(".//tei:note[@place='margin' and @type='heading']",
                          namespaces={"tei": TEI})) == 71
    assert len(root.xpath(".//tei:div[@type='source-column']",
                          namespaces={"tei": TEI})) == 14
    assert root.xpath("string(//*[@xml:id='leaf-0134']/tei:note[@n='library-and-preservation-marks-p134'])",
                      namespaces={"tei": TEI}).startswith("MAY 21 1906")
    assert root.xpath("//*[@xml:id='leaf-0126-p003-col2']") == []


@pytest.mark.parametrize("mutation,reason", [
    ("omit_page", "page order"),
    ("duplicate_page", "page order"),
    ("swap_pages", "page order"),
    ("change_wording", "scan-grounded OCR transformation"),
    ("change_facs", "scan page binding"),
    ("move_back_matter", "page order"),
    ("change_chapter", "section groups"),
    ("change_heading", "paragraph role"),
])
def test_oracle_rejects_readable_tei_mutations(pair, mutation, reason):
    content, account = pair
    tree = parse(content)
    pages = tree.xpath("//*[@xml:id='leaf-0131']")
    assert len(pages) == 1
    page = pages[0]
    if mutation == "omit_page":
        page.getparent().remove(page)
    elif mutation == "duplicate_page":
        clone = etree.fromstring(etree.tostring(page))
        for node in clone.iter():
            if node.get(XML_ID):
                node.set(XML_ID, node.get(XML_ID) + "-copy")
        page.addnext(clone)
    elif mutation == "swap_pages":
        following = page.getnext()
        assert following is not None
        page.addprevious(following)
    elif mutation == "change_wording":
        line = page.find(f".//{{{TEI}}}lb")
        assert line is not None and line.tail
        line.tail += " invented"
    elif mutation == "change_facs":
        page.find(f"{{{TEI}}}pb").set("facs", "scan.pdf#page=999")
    elif mutation == "move_back_matter":
        scripture = tree.find(f"./{{{TEI}}}text/{{{TEI}}}back/{{{TEI}}}div")
        scripture.append(page)
    elif mutation == "change_heading":
        head = page.find(f".//{{{TEI}}}head")
        assert head is not None
        head.tag = f"{{{TEI}}}p"
    elif mutation == "change_chapter":
        chapter = tree.find(f"./{{{TEI}}}text/{{{TEI}}}body/{{{TEI}}}div")
        chapter.set("n", "VIII")
    with pytest.raises(ValueError, match=reason):
        check(ROOT, etree.tostring(tree, encoding="UTF-8"), account)


def test_oracle_rejects_accounting_change(pair):
    content, account = pair
    record = json.loads(account)
    record["pages"][-1]["group"] = "bibliography"
    with pytest.raises(ValueError, match="page accounting"):
        check(ROOT, content, json.dumps(record).encode("utf-8"))


def test_oracle_rejects_identity_relink(pair):
    content, account = pair
    record = json.loads(account)
    record["acquisition_id"] = "another-acquisition"
    with pytest.raises(ValueError, match="source accountability identity"):
        check(ROOT, content, json.dumps(record).encode("utf-8"))


def test_oracle_rejects_correction_map_rebinding(pair):
    content, account = pair
    record = json.loads(account)
    record["scan_collation"]["map_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="scan map and exact OCR carrier accounting"):
        check(ROOT, content, json.dumps(record).encode("utf-8"))


def test_oracle_rejects_changed_scan_corrected_reading(pair):
    content, account = pair
    tree = parse(content)
    correction = json.loads(
        (ROOT / "sources/structured-text/robertson-keywords-1906/scan-corrections.v1.json")
        .read_bytes()
    )["replacements"][0]
    page_id = f"leaf-{correction['page_ordinal']:04d}-p{correction['paragraph']:03d}"
    paragraph = tree.xpath(f"//*[@xml:id='{page_id}']")[0]
    line = paragraph.find(f".//{{{TEI}}}lb")
    assert line is not None and line.tail and correction["scan_reading"] in line.tail
    line.tail = line.tail.replace(correction["scan_reading"], "X. T. ", 1)
    with pytest.raises(ValueError, match="scan-grounded OCR transformation"):
        check(ROOT, etree.tostring(tree, encoding="UTF-8"), account)


@pytest.mark.parametrize("mutation", ["omit", "duplicate"])
def test_oracle_rejects_marginal_heading_mutations(pair, mutation):
    content, account = pair
    tree = parse(content)
    page = tree.xpath("//*[@xml:id='leaf-0016']")[0]
    note = page.find(f"{{{TEI}}}note[@n='margin-heading-p16-god-is-the-father']")
    assert note is not None
    if mutation == "omit":
        page.remove(note)
    else:
        page.append(etree.fromstring(etree.tostring(note)))
    with pytest.raises(ValueError, match="scan-grounded marginal heading at 16"):
        check(ROOT, etree.tostring(tree, encoding="UTF-8"), account)


def test_oracle_rejects_contents_row_change(pair):
    content, account = pair
    tree = parse(content)
    title = tree.xpath("//*[@xml:id='leaf-0013']//tei:seg[@type='title']",
                       namespaces={"tei": TEI})[0]
    title.text = "Invented title"
    with pytest.raises(ValueError, match="contents row reading"):
        check(ROOT, etree.tostring(tree, encoding="UTF-8"), account)


def test_oracle_rejects_column_paragraph_placement_change(pair):
    content, account = pair
    tree = parse(content)
    paragraph = tree.xpath("//*[@xml:id='leaf-0126-p003-col1']")[0]
    paragraph.getparent().remove(paragraph)
    with pytest.raises(ValueError, match="column paragraph identity at 126:3:1"):
        check(ROOT, etree.tostring(tree, encoding="UTF-8"), account)


def test_oracle_rejects_omitted_nonliterary_disposition(pair):
    content, account = pair
    tree = parse(content)
    page = tree.xpath("//*[@xml:id='leaf-0001']")[0]
    note = page.find(f"{{{TEI}}}note[@n='cover-library-shelfmark-p1']")
    assert note is not None
    page.remove(note)
    with pytest.raises(ValueError, match="nonliterary source disposition at 1"):
        check(ROOT, etree.tostring(tree, encoding="UTF-8"), account)



def test_empty_source_line_is_preserved(pair):
    content, account = pair
    tree = parse(content)
    paragraph = tree.xpath("//*[@xml:id='leaf-0002-p002']")
    assert len(paragraph) == 1
    line = paragraph[0].find(f"{{{TEI}}}lb")
    assert line is not None and line.tail is None
    wrapper = paragraph[0].getparent()
    wrapper.getparent().remove(wrapper)
    with pytest.raises(ValueError, match="paragraph identity"):
        check(ROOT, etree.tostring(tree, encoding="UTF-8"), account)


def test_generated_tei_matches_bound_p5_schema(pair):
    content, _ = pair
    schema = etree.XMLSchema(etree.parse(str(
        ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")))
    assert schema.validate(etree.ElementTree(parse(content))), schema.error_log.last_error




def test_one_primary_source_binding_uses_direct_digest():
    scan = {"name": "scan", "path": "raw/scan.pdf", "bytes": 1,
            "sha256": "a" * 64, "role": "primary-source"}
    ocr = {"name": "ocr", "path": "raw/ocr.xml", "bytes": 2,
           "sha256": "b" * 64, "role": "ocr-witness"}
    manifest = type("Manifest", (), {"record": {"authorities": (ocr, scan)}})()
    assert _source_set(manifest) == "a" * 64


@pytest.mark.parametrize('mutation', ['remove-marker', 'corrupt-reading'])
def test_coherently_rebound_map_cannot_bypass_scan_review(tmp_path, monkeypatch, source_manifest, pair, mutation):
    record = json.loads(MANIFEST.read_bytes())
    authority = next(a for a in record['authorities'] if a['name'] == 'scan-grounded-correction-map')
    mapping = json.loads(source_manifest.authority_path('scan-grounded-correction-map').read_bytes())
    if mutation == 'remove-marker':
        del mapping['text_review']
    else:
        mapping['marginal_headings'][16]['scan_reading'] = 'Christ damaged heading'
    raw = json.dumps(mapping, ensure_ascii=False).encode()
    target = tmp_path / 'mutated-map.json'
    target.write_bytes(raw)
    authority.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    class Bound:
        def __init__(self): self.record = record
        def authority_path(self, name):
            return target if name == 'scan-grounded-correction-map' else source_manifest.authority_path(name)
    with pytest.raises(ValueError, match='reviewed|independently'):
        _scan_map(Bound(), [])
    original_resolver = oracle.resolve_repo_path
    monkeypatch.setattr(oracle, 'resolve_repo_path', lambda root, path:
                        target if path == authority['path'] else original_resolver(root, path))
    with pytest.raises(ValueError, match='reviewed|independently'):
        oracle.check(ROOT, *pair, source_manifest=record)


def test_multiple_primary_source_binding_uses_sorted_member_set_digest():
    first = {"name": "first", "path": "raw/a.pdf", "bytes": 1,
             "sha256": "a" * 64, "role": "primary-source"}
    second = {"name": "second", "path": "raw/z.pdf", "bytes": 2,
              "sha256": "b" * 64, "role": "primary-source"}
    ocr = {"name": "ocr", "path": "raw/ocr.xml", "bytes": 3,
           "sha256": "c" * 64, "role": "ocr-witness"}
    manifest = type("Manifest", (), {"record": {
        "authorities": (second, ocr, first)}})()
    canonical = (
        b'{"contract":"ocd-source-member-set-v1","members":['
        b'{"bytes":1,"name":"first","path":"raw/a.pdf","sha256":"' +
        b"a" * 64 +
        b'"},{"bytes":2,"name":"second","path":"raw/z.pdf","sha256":"' +
        b"b" * 64 +
        b'"}]}\n'
    )
    assert _source_set(manifest) == hashlib.sha256(canonical).hexdigest()
