"""Independent attack and fidelity cases for the bounded text-only XML reader."""
import hashlib

import pytest
from lxml import etree

from build.lib import text_xml_reader as reader
from build.lib.text_lint import lint_xml_file


@pytest.mark.parametrize(("encoding", "content"), [
    ("utf-8", "café"), ("utf-16", "漢字"), ("windows-1252", "café"),
    ("utf-32", "漢字"), ("shift_jis", "漢字"),
])
def test_plain_xml_preserves_existing_encoding_support(encoding, content):
    text = f'<?xml version="1.0" encoding="{encoding}"?><d>{content}</d>'
    raw = text.encode(encoding)
    expected = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, huge_tree=True))
    root, _ = reader.read_text_xml(raw)
    assert root.text == expected.text == content


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32", "shift_jis", "windows-1252"])
def test_encoding_transcode_cannot_hide_external_declarations(encoding):
    text = (f'<?xml version="1.0" encoding="{encoding}"?>'
            '<!DOCTYPE d [<!ENTITY secret SYSTEM "file:///reader-sentinel.txt">]><d>safe</d>')
    with pytest.raises(ValueError, match="external text entities"):
        reader.read_text_xml(text.encode(encoding))


def test_inspection_decode_does_not_legitimize_mismatched_encoding_bytes():
    raw = b'<?xml version="1.0" encoding="utf-16"?><d>safe</d>'
    with pytest.raises(ValueError):
        reader.read_text_xml(raw)


@pytest.mark.parametrize("encoding", ["rot13", "bz2_codec", "base64_codec"])
def test_nontext_python_codecs_are_named_xml_input_failures(encoding):
    raw = f'<?xml version="1.0" encoding="{encoding}"?><d>safe</d>'.encode()
    with pytest.raises(ValueError):
        reader.read_text_xml(raw)


@pytest.mark.parametrize("declaration", [
    '<!ENTITY secret SYSTEM "file:///reader-sentinel.txt">',
    '<!ENTITY secret SYSTEM "https://example.invalid/reader-sentinel">',
    '<!ENTITY secret PUBLIC "public-id" "reader-sentinel.txt">',
    '<!ENTITY % parameter "text">',
    '<!ENTITY % parameter SYSTEM "file:///reader-sentinel.dtd">%parameter;',
])
def test_external_text_and_active_parameter_entities_fail_before_resolution(monkeypatch, declaration):
    attempted = []
    monkeypatch.setattr(reader._DenyExternal, "resolve", lambda *args: attempted.append(args))
    with pytest.raises(ValueError, match="external text entities|parameter"):
        reader.read_text_xml(f"<!DOCTYPE d [{declaration}]><d>safe</d>".encode())
    assert attempted == []


def test_unreferenced_external_parameters_are_evidenced_without_resolution(monkeypatch):
    attempted = []
    monkeypatch.setattr(reader._DenyExternal, "resolve", lambda *args: attempted.append(args))
    raw = (b'<!DOCTYPE d SYSTEM "file:///reader-sentinel.dtd" ['
           b'<!ENTITY % external SYSTEM "./extEntities.dtf">'
           b'<!ENTITY % internal PUBLIC "source-identifier" "./intEntities.dtf">'
           b'<!-- %external; is inert inside this comment -->]><d>safe</d>')
    root, evidence = reader.read_text_xml(raw)
    assert root.text == "safe"
    assert evidence["inert_parameter_declarations"] == [
        {"name": "external", "system_id": "./extEntities.dtf", "public_id": None},
        {"name": "internal", "system_id": "./intEntities.dtf", "public_id": "source-identifier"},
    ]
    assert attempted == []


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32", "shift_jis"])
def test_unknown_parameter_references_are_not_hidden_by_external_doctype(encoding):
    text = (f'<?xml version="1.0" encoding="{encoding}"?>'
            '<!DOCTYPE d SYSTEM "file:///reader-sentinel.dtd" [%missing;]><d>safe</d>')
    with pytest.raises(ValueError):
        reader.read_text_xml(text.encode(encoding))


def test_parameter_reference_split_across_inspection_chunks_is_rejected():
    prefix = b'<!DOCTYPE d [<!ENTITY % parameter SYSTEM "file:///reader-sentinel.dtd">'
    raw = prefix + b" " * (16384 - len(prefix) - 3) + b"%parameter;]><d>safe</d>"
    assert raw[16381:16385] == b"%par"
    with pytest.raises(ValueError, match="parameter|skipped"):
        reader.read_text_xml(raw)


def test_external_doctype_and_unparsed_media_are_inert(monkeypatch):
    attempted = []
    monkeypatch.setattr(reader._DenyExternal, "resolve", lambda *args: attempted.append(args))
    raw = (b'<!DOCTYPE d SYSTEM "file:///reader-sentinel.dtd" ['
           b'<!NOTATION png SYSTEM "image/png">'
           b'<!ENTITY image SYSTEM "file:///reader-sentinel.png" NDATA png>]>'
           b'<d image="image">safe</d>')
    root, evidence = reader.read_text_xml(raw)
    assert root.text == "safe"
    assert evidence["external_subset"] == "file:///reader-sentinel.dtd"
    assert evidence["unparsed_entities"] == 1
    assert attempted == []


def test_available_external_subset_cannot_supply_text_or_default_attributes(tmp_path, monkeypatch):
    subset = tmp_path / "available.dtd"
    subset_bytes = (b'<!ELEMENT d (#PCDATA)><!ATTLIST d injected CDATA "invented-default">'
                    b'<!ENTITY invented "invented-external-text">')
    subset.write_bytes(subset_bytes)
    uri = subset.as_uri()
    ignored = []
    original = reader._InertSubset.resolve

    def observe_empty_subset(self, url, public_id, context):
        ignored.append(url)
        return original(self, url, public_id, context)

    def reject_other_resolution(*args):
        pytest.fail("Unexpected external resolution outside the inventoried inert subset")

    monkeypatch.setattr(reader._InertSubset, "resolve", observe_empty_subset)
    monkeypatch.setattr(reader._DenyExternal, "resolve", reject_other_resolution)
    prefix = f'<!DOCTYPE d SYSTEM "{uri}">'.encode()
    root, evidence = reader.read_text_xml(prefix + b"<d>safe</d>")
    assert root.text == "safe"
    assert root.attrib == {}
    assert evidence["external_subset"] == uri
    assert ignored and set(ignored) == {uri}
    with pytest.raises(ValueError):
        reader.read_text_xml(prefix + b"<d>before&invented;after</d>")
    assert subset.read_bytes() == subset_bytes


@pytest.mark.parametrize("declaration", [
    '<!ENTITY secret SYSTEM "{uri}">',
    '<!ENTITY % parameter SYSTEM "{uri}">%parameter;',
])
def test_same_uri_as_inert_subset_cannot_authorize_external_entity_use(tmp_path, declaration):
    subset = tmp_path / "same-uri.dtd"
    subset.write_bytes(b'<!ENTITY invented "external-text">')
    uri = subset.as_uri()
    raw = (f'<!DOCTYPE d SYSTEM "{uri}" [{declaration.format(uri=uri)}]>'
           '<d>safe</d>').encode()
    with pytest.raises(ValueError, match="external text entities|parameter"):
        reader.read_text_xml(raw)


@pytest.mark.parametrize("raw", [
    b'<!DOCTYPE d SYSTEM "file:///reader-sentinel.dtd"><d>before&unknown;after</d>',
    b'<!DOCTYPE d [<!NOTATION png SYSTEM "image/png"><!ENTITY image SYSTEM "image.png" NDATA png>]><d>&image;</d>',
    b'<!DOCTYPE d [<!ENTITY a "&a;">]><d>&a;</d>',
    b'<!DOCTYPE d [<!ENTITY a "&b;"><!ENTITY b "&a;">]><d>&a;</d>',
])
def test_unavailable_or_cyclic_entity_text_never_silently_disappears(raw):
    with pytest.raises(ValueError):
        reader.read_text_xml(raw)


def test_markup_entities_preserve_text_tails_and_resolvable_locators(tmp_path):
    raw = (b'<!DOCTYPE TEI [<!ENTITY bad "&#xfffd;">'
           b'<!ENTITY markup "<hi>&bad;</hi><!--ignored-->&bad;<?pi ignored?>&bad;">]>'
           b'<TEI><text><body><p>&bad;&markup;&bad;</p></body></text></TEI>')
    path = tmp_path / "source.xml"
    path.write_bytes(raw)
    report = lint_xml_file(path)
    tree = reader.read_text_xml(raw)[0].getroottree()
    assert report["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert report["coverage"]["characters"] == 5
    assert len(report["observations"]) == 5
    assert sum(len(o["text"]) for o in report["observations"]) == 5
    for observation in report["observations"]:
        locator = observation["locator"]
        if locator.endswith("/following-text()"):
            node, = tree.xpath(locator.removesuffix("/following-text()"))
            value = node.tail
        else:
            value, = tree.xpath(locator)
        assert value[observation["start"]:observation["end"]] == "\ufffd"
        assert observation["region"] == "body"
    assert "expanded XML tree" in report["coverage"]["limits"]
    assert path.read_bytes() == raw


def test_duplicate_xml_ids_do_not_collapse_character_coverage(tmp_path):
    raw = ('<TEI><text><body><p xml:id="duplicate">first\ufffd</p>'
           '<p xml:id="duplicate">second\u200b</p></body></text></TEI>').encode()
    path = tmp_path / "duplicate-ids.xml"
    path.write_bytes(raw)
    with pytest.raises(etree.XMLSyntaxError):
        etree.fromstring(raw, etree.XMLParser(collect_ids=True))
    report = lint_xml_file(path)
    tree = reader.read_text_xml(raw)[0].getroottree()
    assert report["coverage"]["characters"] == 13
    assert report["coverage"]["units"] == 2
    assert len(report["observations"]) == 2
    assert len({o["locator"] for o in report["observations"]}) == 2
    assert {o["text"] for o in report["observations"]} == {"\ufffd", "\u200b"}
    for observation in report["observations"]:
        value, = tree.xpath(observation["locator"])
        assert value[observation["start"]:observation["end"]] == observation["text"]
    assert "ID uniqueness" in report["coverage"]["limits"]
    assert path.read_bytes() == raw


def test_numeric_ampersand_references_cannot_evade_expansion_graph_limit(monkeypatch):
    monkeypatch.setattr(reader, "MAX_ENTITY_CHARACTERS", 64)
    raw = (b'<!DOCTYPE d [<!ENTITY a "1234567890">'
           b'<!ENTITY b "&#38;a;&#38;a;&#38;a;&#38;a;&#38;a;&#38;a;&#38;a;">]><d>&b;</d>')
    with pytest.raises(ValueError, match="expansion budget"):
        reader.read_text_xml(raw)


def test_repeated_body_entities_retain_libxml_amplification_limit():
    raw = (b'<!DOCTYPE d [<!ENTITY a "' + b"x" * 1024 + b'">]><d>'
           + b"&a;" * 1000 + b"</d>")
    with pytest.raises(ValueError, match="amplification|loop|expansion"):
        reader.read_text_xml(raw)


def test_dtd_tree_depth_limit_remains_active():
    raw = b"<!DOCTYPE d><d>" + b"<p>" * 300 + b"text" + b"</p>" * 300 + b"</d>"
    with pytest.raises(ValueError, match="depth"):
        reader.read_text_xml(raw)


def test_fake_declarations_inside_comments_do_not_trigger_dependency_rejection():
    root, evidence = reader.read_text_xml(
        b'<!-- <!DOCTYPE d [<!ENTITY x SYSTEM "file:///sentinel">]> --><d>text</d>')
    assert root.text == "text"
    assert evidence["doctype"] is None
