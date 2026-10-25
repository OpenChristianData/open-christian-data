"""Direct-text hymn blocks bind their explicit source element."""

import hashlib

import pytest

from cvw_app.bounded_tei_provenance import render_body_provenance
from cvw_app.renderer_nodes import MAX_PAGE_SCALARS, RendererError
from cvw_app.tei_renderer import render_tei


def render(tmp_path, body):
    payload = f"<TEI><text><body>{body}</body></text></TEI>".encode()
    master = tmp_path / "master.xml"
    master.write_bytes(payload)
    output, proof = render_body_provenance(
        master,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        master_member="master.xml",
    )
    assert output == render_tei("application/tei+xml", payload.decode())
    return payload, output, proof


def test_direct_hymn_text_keeps_whitespace_and_source_identity(tmp_path):
    payload, output, proof = render(
        tmp_path,
        '<ab type="hymn-text" xml:id="hymn" xml:space="preserve">'
        'First line\n  Second line</ab>' * 2,
    )
    assert [node["text"] for node in output["nodes"]] == [
        "First line\n  Second line",
        "First line\n  Second line",
    ]
    first, second = proof.nodes
    assert first.provenance.sources != second.provenance.sources
    assert len(first.provenance.sources) == len(second.provenance.sources) == 1
    assert payload[
        first.provenance.sources[0].locator.start:first.provenance.sources[0].locator.end
    ] == (
        b'<ab type="hymn-text" xml:id="hymn" xml:space="preserve">'
        b'First line\n  Second line</ab>'
    )


@pytest.mark.parametrize(
    "body",
    [
        '<ab type="hymn-text"><l>Line</l></ab>',
        '<ab type="hymn-text">Before<hi>inline</hi></ab>',
        '<ab type="hymn-text"><note>Note</note></ab>',
        '<ab type="hymn-text"><lb>Hidden</lb>Line</ab>',
        '<ab type="hymn-text"><lb><hi/></lb>Line</ab>',
        '<ab type="hymn-text"><lb xmlns="urn:foreign"/>Line</ab>',
        '<ab type="hymn-text"><pb/>Line</ab>',
        '<ab type="hymn-text"><gap/>Line</ab>',
    ],
)
def test_nonatomic_hymn_text_fails_closed(tmp_path, body):
    with pytest.raises(RendererError, match="hymn-text provenance requires"):
        render(tmp_path, body)


@pytest.mark.parametrize('namespace', ['', ' xmlns="http://www.tei-c.org/ns/1.0"'])
def test_hymn_line_markers_keep_breaks_and_distinct_source_owners(tmp_path, namespace):
    block = (
        f'<ab{namespace} type="hymn-text" xml:id="same" xml:space="preserve">'
        'First<lb xml:id="same"/>  Second<lb break="no"/>joined<lb/><lb/>End</ab>'
    )
    payload, output, proof = render(tmp_path, block * 2)
    assert [node['text'] for node in output['nodes']] == [
        'First\n  Secondjoined\n\nEnd'] * 2
    first, second = [node.provenance.sources for node in proof.nodes]
    assert set(first).isdisjoint(second)
    for sources in (first, second):
        assert [payload[s.locator.start:s.locator.end] for s in sources] == [
            block.encode(), b'<lb xml:id="same"/>', b'<lb break="no"/>', b'<lb/>', b'<lb/>']
    assert proof.pages == (proof.nodes,)


def test_empty_hymn_line_markers_have_no_invented_emission(tmp_path):
    _, _, proof = render(tmp_path, '<ab type="hymn-text"><lb/><lb break="no"/></ab><p>Base</p>')
    assert len(proof.nodes) == len(proof.emissions) == 1


def test_hymn_line_markers_keep_xml_formatting_normalization(tmp_path):
    _, output, _ = render(tmp_path, '<ab type="hymn-text">First\n  word<lb/>Next</ab>')
    assert output['nodes'][0]['text'] == 'First word\nNext'


def test_large_hymn_remains_atomic_with_same_page_owners(tmp_path):
    _, output, proof = render(
        tmp_path, '<ab type="hymn-text">' + 'word ' * MAX_PAGE_SCALARS + '<lb/>End</ab>')
    assert len(output['nodes']) == len(proof.nodes) == 1
    assert len(proof.nodes[0].provenance.sources) == 2
    assert proof.pages == (proof.nodes,)
