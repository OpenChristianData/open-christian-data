from lxml import etree
from hashlib import sha256
from pathlib import Path
from build.tei.calvin_commentaries_reconstruction import _selector
from build.tei.calvin_commentaries_oracle import _selector as independent_selector


def test_named_xpath_ordinals_count_only_siblings_with_the_same_tag():
    root = etree.fromstring(b'<ThML><ThML.head><print/><electronicEdInfo><title/><publisher/><bkgID>opaque</bkgID><bkgID>second</bkgID></electronicEdInfo></ThML.head></ThML>')
    for node in root.iter():
        selector = _selector(node)
        assert root.xpath(selector) == [node]
        assert independent_selector(node) == selector


def test_actual_retained_catalogue_identifier_has_a_resolvable_selector():
    raw = (Path(__file__).resolve().parents[1] / 'raw/ccel/calvin-commentaries/commentaries.xml').read_bytes()
    assert sha256(raw).hexdigest() == 'd5167554c4c40ac2ba320e9ec75afd2565001e0f5f84b0245832b7bfa183b08f'
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    node, = root.xpath('/ThML/ThML.head/electronicEdInfo/bkgID')
    assert root.xpath(_selector(node)) == [node]
    assert root.xpath(independent_selector(node)) == [node]
