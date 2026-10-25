"""Exercise the new Rutherford converter and independent reader on a small source."""
from hashlib import sha256
import json
from types import SimpleNamespace

from lxml import etree
import pytest

from build.tei.rutherford_pg42557_reconstruction import _convert
from build.tei.rutherford_pg42557_oracle import _oracle


@pytest.fixture
def packet(tmp_path):
    letters = ''.join(f'<h2 id="letter-{n}">I. Letter {n}</h2><p id="p-{n}">Words <i>emphasized</i> <a href="#letter-{n}">here</a>.</p>' for n in range(1, 366))
    raw = ('<html><body><header><h1>Letters</h1></header>'
           '<span class="pagenum"><a id="Page_710"></a><br/><a id="Page_711"></a></span>'
           + letters + '<table><tr><td>Cell</td></tr></table><img src="front.jpg" alt="Portrait"/>'
           '<footer id="license">Provider notice</footer></body></html>').encode()
    files = {'retained-source': raw, 'profile': json.dumps({'source_sha256': sha256(raw).hexdigest()}).encode(), 'readme': b'Digital source credit',
             'tei-validation-schema': b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="http://www.tei-c.org/ns/1.0" elementFormDefault="qualified"><xs:element name="TEI"><xs:complexType><xs:sequence><xs:any minOccurs="0" maxOccurs="unbounded" processContents="skip"/></xs:sequence><xs:anyAttribute processContents="skip"/></xs:complexType></xs:element></xs:schema>'}
    paths = {}
    for name, content in files.items():
        path = tmp_path / name
        path.write_bytes(content)
        paths[name] = path
    roles = ['complete-source-feature-profile', 'candidate-package-schema', 'primary-source', 'tei-validation-schema', 'independent-validation-policy']
    manifest = SimpleNamespace(authority_path=lambda role: paths[role], sha256='a' * 64,
                               record={'authorities': [{'role': role, 'sha256': 'b' * 64} for role in roles]})
    content = _convert(manifest)['content.tei.xml']
    return manifest, content


def candidate(content):
    return SimpleNamespace(member_bytes=lambda name: content, sha256=sha256(content).hexdigest())


def test_complete_source_relationships_pass_independent_reader(packet):
    manifest, content = packet
    assert _oracle(manifest, candidate(content))['findings'] == []
    assert _oracle(manifest, candidate(content))['status'] == 'pass'


@pytest.mark.parametrize('mutation', ['word', 'heading', 'link', 'table'])
def test_independent_reader_catches_changed_source_relationships(packet, mutation):
    manifest, content = packet
    tree = etree.fromstring(content)
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    if mutation == 'word':
        tree.xpath('//t:p[@rend="source-p"]', namespaces=ns)[0].text = 'Changed wording '
    elif mutation == 'heading':
        tree.xpath('//t:head', namespaces=ns)[1].text = 'Changed heading'
    elif mutation == 'link':
        tree.xpath('//t:ref', namespaces=ns)[0].set('target', '#wrong-letter')
    else:
        tree.xpath('//t:cell', namespaces=ns)[0].text = 'Changed table cell'
    assert _oracle(manifest, candidate(etree.tostring(tree)))['status'] == 'fail'


def test_converter_rejects_changed_source_hash(packet):
    manifest, _ = packet
    manifest.authority_path('retained-source').write_bytes(b'<html><body>Different source</body></html>')
    with pytest.raises(ValueError, match='differs from the bound profile'):
        _convert(manifest)
