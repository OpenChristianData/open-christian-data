"""Reading a selected work must not display an adjacent work in its place."""
from cvw_app.selected_reading import selected_reader_input
from cvw_app.review_renderers import render_xml_reader


def test_same_file_selections_render_distinct_work_and_shared_context():
    raw = '<ThML><ThML.body><div1 id="credits" title="Credits"><p id="c">Shared credit.</p></div1><div1 id="a" title="Alpha"><p>First text.</p></div1><div1 id="b" title="Beta"><p>Second text.</p></div1></ThML.body></ThML>'
    for native,title,own,other in [('a','Alpha','First text.','Second text.'),('b','Beta','Second text.','First text.')]:
        selection = dict(units=[dict(native_id=native,title=title)],dependencies=[dict(native_id='c')])
        projected = selected_reader_input(raw,'xml-reader',selection)
        rendered = str(render_xml_reader('application/xml',projected))
        assert own in rendered and other not in rendered
        assert 'Shared source credits (source-level attribution)' in rendered
        assert 'Shared credit.' in rendered
    assert 'Second text.' in raw and 'First text.' in raw


def test_tei_header_credits_are_readable_without_mutating_canonical_tei():
    raw = '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><sourceDesc><bibl><idno type="source_selection_sha256">digest</idno><note type="source-credit">Shared credit.</note></bibl></sourceDesc></fileDesc></teiHeader><text><body><div><head>Alpha</head><p>Text.</p></div></body></text></TEI>'
    projected = selected_reader_input(raw,'tei-reader',None)
    assert 'Shared source credits (source-level attribution)' in projected
    assert 'cvw-source-context' not in raw
