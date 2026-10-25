"""Prove internal text expansion and explicit dependency refusals."""
import hashlib

from lxml import etree
import pytest

from build.lib.text_lint import lint_xml_file
from build.lib.reconstruction_text_screen import _screen
from build.lib.text_xml_reader import read_text_xml


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_internal_entities_expand_text_markup_and_tails_without_changing_source(tmp_path, encoding):
    raw = ('<?xml version="1.0" encoding="' + encoding + '"?>'
           '<!DOCTYPE TEI [<!ENTITY bad "&#xfffd;">'
           '<!ENTITY inline "<hi>&bad;</hi>&bad;">]>'
           '<TEI><text><body><p>&bad;&inline;</p></body></text></TEI>').encode(encoding)
    path = tmp_path / "entities.xml"
    path.write_bytes(raw)
    report = lint_xml_file(path)
    assert report["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() == raw
    assert report["coverage"]["characters"] == 3
    root, evidence = read_text_xml(raw)
    assert evidence["internal_entities"] == 2
    assert len(report["observations"]) == 3
    for observation in report["observations"]:
        locator = observation["locator"]
        if locator.endswith("/following-text()"):
            node, = root.xpath(locator.removesuffix("/following-text()"))
            assert node.tail == observation["text"]
        else:
            assert root.xpath(locator) == [observation["text"]]
        assert observation["region"] == "body"


def test_inert_external_doctype_is_not_loaded_and_dtd_defaults_are_outside_scope(tmp_path):
    raw = b'<!DOCTYPE TEI SYSTEM "file:///unavailable.dtd" [<!ATTLIST TEI title CDATA "extra">]><TEI>text</TEI>'
    root, evidence = read_text_xml(raw)
    assert etree.tostring(root) == b'<TEI>text</TEI>'
    assert evidence["external_subset"] == "file:///unavailable.dtd"
    assert evidence["external_retrieval"] == "disabled"
    path = tmp_path / "source.xml"
    path.write_bytes(raw)
    report = _screen(path, reference="source.xml", expected_sha256=hashlib.sha256(raw).hexdigest(), role="primary-source")
    assert report["status"] == "screened"
    assert report["coverage"]["xml_reader"] == evidence


def test_unparsed_image_declaration_is_accounted_without_retrieval():
    raw = b'<!DOCTYPE TEI [<!NOTATION jpg SYSTEM "image/jpeg"><!ENTITY image SYSTEM "missing.jpg" NDATA jpg>]><TEI><graphic entity="image"/>text</TEI>'
    root, evidence = read_text_xml(raw)
    assert root[0].tail == "text"
    assert evidence["unparsed_entities"] == 1
    with pytest.raises(ValueError):
        read_text_xml(raw.replace(b'/>text', b'/>&image;'))


@pytest.mark.parametrize("declaration,body", [
    ('<!ENTITY e SYSTEM "file:///private.txt">', '&e;'),
    ('<!ENTITY e SYSTEM "https://example.invalid/a">', 'unused'),
    ('<!ENTITY % e "<!ENTITY bad \'text\'>">%e;', '&bad;'),
    ('<!ENTITY % e SYSTEM "file:///extra.dtd">%e;', 'unused'),
    ('<!ENTITY e "&e;">', '&e;'),
    ('', '&undeclared;'),
])
def test_dependencies_cycles_and_unknown_entities_fail_closed(declaration, body):
    raw = f'<!DOCTYPE TEI SYSTEM "https://example.invalid/dtd" [{declaration}]><TEI>{body}</TEI>'.encode()
    with pytest.raises(ValueError):
        read_text_xml(raw)


def test_nested_expansion_is_bounded_before_full_tree_parse():
    declarations = ['<!ENTITY e0 "1234567890">']
    for number in range(1, 8):
        declarations.append(f'<!ENTITY e{number} "' + f'&e{number-1};' * 10 + '">')
    with pytest.raises(ValueError, match="budget exceeded"):
        read_text_xml(('<!DOCTYPE TEI [' + ''.join(declarations) + ']><TEI>&e7;</TEI>').encode())


def test_doctype_literal_in_comment_is_not_a_declaration():
    root, evidence = read_text_xml(b'<!-- <!DOCTYPE fake> --><TEI>text</TEI>')
    assert root.text == "text"
    assert evidence["doctype"] is None


def test_inert_external_parameter_declarations_are_bound_but_not_loaded():
    raw = b'<!DOCTYPE d [<!ENTITY % e SYSTEM "file:///missing.dtd">]><d>text</d>'
    root, evidence = read_text_xml(raw)
    assert root.text == "text"
    assert evidence["inert_parameter_declarations"] == [
        {"name": "e", "system_id": "file:///missing.dtd", "public_id": None}]
    with pytest.raises(ValueError, match="parameter entity references"):
        read_text_xml(raw.replace(b']>', b'%e;]>'))


@pytest.mark.parametrize("label", ["rot13", "rot_13", "bz2_codec", "base64_codec"])
def test_nontext_encoding_is_an_explicit_reader_gap(label):
    with pytest.raises(ValueError, match="Nontext XML inspection encoding"):
        read_text_xml(f'<?xml version="1.0" encoding="{label}"?><d/>'.encode())
