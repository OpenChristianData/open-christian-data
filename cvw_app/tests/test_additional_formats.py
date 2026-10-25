import json
import hashlib
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from cvw_app.review_contract import _source_presentation, ReviewApplication, ReviewContractError
from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY, render_exact_text, render_xml_reader
from cvw_app.renderer_nodes import _nodes_text, RendererError
from cvw_app.pdf_pages import pdf_page_count, pdf_preview
from cvw_app.sword_members import declared_module_context, render_sword_members


def test_known_source_formats_are_not_misclassified_as_plain_text():
    assert _source_presentation(Path('book.tei'))[:2] == ('application/xml', 'xml-reader')
    for suffix in ['tar', 'zdt', 'zdx', 'czs', 'czv', 'czz']:
        assert _source_presentation(Path('source.' + suffix))[:2] == ('application/octet-stream', 'unsupported-binary')
    assert _source_presentation(Path('._usfm'))[:2] == ('application/octet-stream','unsupported-binary')


@pytest.mark.parametrize('media_type',['application/zip','application/gzip'])
def test_archive_handoff_preserves_identity_and_rejects_byte_drift(tmp_path,media_type):
    path=tmp_path/'archive';payload=b'Exact archive bytes';path.write_bytes(payload)
    digest=hashlib.sha256(payload).hexdigest()
    artifact=dict(id='archive',version='v1',sha256=digest,media_type=media_type)
    app=SimpleNamespace(_work=lambda slug:None,_resolve=lambda *args:SimpleNamespace(readable=True,artifact=artifact,path=path))
    assert ReviewApplication.stage_bytes(app,'work','source','archive','v1',digest)==(payload,media_type)
    with pytest.raises(ReviewContractError,match='sha256'):
        ReviewApplication.stage_bytes(app,'work','source','archive','v1','0'*64)
    path.write_bytes(b'Changed bytes')
    with pytest.raises(ReviewContractError,match='sha256'):
        ReviewApplication.stage_bytes(app,'work','source','archive','v1',digest)


def test_dictionary_lines_preserve_duplicate_entries_and_selectable_line_numbers():
    rows = [dict(term='Abel', definitions=['vanity; breath']), dict(term='Abel', definitions=['a city; mourning'])]
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render('exact-text', 'application/x-ndjson', '\n'.join(json.dumps(r) for r in rows))
    assert supported
    assert [r['location'] for r in rendered['outline']] == ['line-1', 'line-2']
    assert rendered['contexts']['line-1']['text'] == 'Abel vanity; breath'
    assert _nodes_text(rendered['nodes']) == 'Abel vanity; breath Abel a city; mourning'
    unexpected = '{"term":"Aaron","unknown":"Do not omit this"}'
    assert _nodes_text(render_exact_text('application/x-ndjson', unexpected)['nodes']) == unexpected


def test_hymn_csv_preserves_multiline_text_and_discloses_metadata():
    exact='Title,Full text,Author name\r\nAmen,"First line\nSecond line",Anonymous\r\n'
    nodes=render_exact_text('text/csv',exact)['nodes']
    assert [(n['type'],n['text']) for n in nodes] == [('heading','Amen'),('preformatted','First line\nSecond line'),('details','Hymn details')]
    assert nodes[-1]['children'][0]['text'] == 'Author name: Anonymous'


def test_retained_hymnary_quoting_reuses_the_existing_source_preserving_reader():
    from cvw_app.hymnary_csv import read_rows as viewer_rows
    from build.tei.hymnary_csv import read_rows as producer_rows

    content=b'Title,"Full text",Author\n"A","Verf\\soehner\r\nSay ""Hope,\\" now",Anon\n'
    assert [[field.value for field in row.fields] for row in viewer_rows(content)] == [[field.value for field in row.fields] for row in producer_rows(content)]
    nodes=render_exact_text('text/csv',content.decode())['nodes']
    assert nodes[1]['text']=='Verf\\soehner\r\nSay "Hope,\\" now'


def test_toml_quotes_keep_metadata_and_unknown_fields_available():
    exact='[[commentary]]\nquote="The actual quotation."\nsource_title="Letter 2"\nsource_url=""\nnumber=2\n'
    nodes=render_exact_text('application/toml',exact)['nodes']
    assert [(n['type'],n['text']) for n in nodes] == [('heading','Letter 2'),('paragraph','The actual quotation.'),('details','Source details')]
    assert 'Number: 2' in _nodes_text(nodes)


def test_transcribed_toml_separates_quotes_from_metadata():
    from cvw_app.tei_renderer import render_tei
    xml='<TEI><text><body><div type="source-member" subtype="commentary"><head>Letter.toml</head><div type="commentary-record"><list type="toml-object"><item n="quote"><label>quote</label><seg>Read this.</seg></item><item n="source_title"><label>source_title</label><seg>Letter 2</seg></item><item n="source_url"><label>source_url</label><seg>Source identity</seg></item></list></div></div></body></text></TEI>'
    nodes=render_tei('application/tei+xml',xml)['nodes']
    assert [(n['type'],n['text']) for n in nodes[:2]]==[('heading','Letter 2'),('paragraph','Read this.')]
    assert nodes[2]['type']=='details' and 'Source identity' in _nodes_text(nodes[2]['children'])


def test_usfm_chapters_keep_verse_numbers_and_unknown_markers():
    exact='\\id GEN\n\\c 1\n\\v 1 In the beginning.\n\\unknown Preserve this.\n'
    rendered=render_exact_text('text/x-usfm',exact)
    assert rendered['outline'][0]['label'] == 'Chapter 1'
    assert '1 In the beginning.' in _nodes_text(rendered['nodes'])
    assert '\\unknown Preserve this.' in _nodes_text(rendered['nodes'])


@pytest.mark.parametrize(('xml','visible'),[
    ('<TEI><text><body><head>Book</head><p>Read this.</p></body></text></TEI>','Read this.'),
    ('<article><front><article-title>Title</article-title></front><body><sec><title>Opening</title><p>Text <italic>here</italic>.</p></sec></body></article>','Text here.'),
    ('<DjVuXML><BODY><OBJECT><LINE><WORD>Two</WORD><WORD>words.</WORD></LINE></OBJECT></BODY></DjVuXML>','Two words.'),
    ('<ETS><EEBO><TEXT><P>Retained <GAP DISP="[...]"/> text.</P></TEXT></EEBO></ETS>','Retained [...] text.'),
    ('<mediawiki><siteinfo>Metadata</siteinfo><page><title>Chapter</title><revision><text>Original wiki text</text></revision></page></mediawiki>','Original wiki text'),
])
def test_known_xml_vocabularies_have_reading_views(xml,visible):
    rendered=render_xml_reader('application/xml',xml)
    assert visible in _nodes_text(rendered['nodes'])
    assert rendered['kind'] != 'exact-text'


def test_entity_bearing_xml_remains_exact_and_inert():
    xml='<!DOCTYPE article [<!ENTITY secret SYSTEM "file:///secret">]><article><body>&secret;</body></article>'
    assert render_xml_reader('application/xml',xml)['kind']=='exact-text'


def test_legacy_tei_picture_declarations_are_inert_and_never_resolve_text_entities():
    from cvw_app.xml_books import legacy_tei_book

    xml='<!DOCTYPE TEI.2 [<!ENTITY picture SYSTEM "portrait.jpg" NDATA jpeg>]><TEI.2><text><body><div1 id="opening"><head>Opening</head><p>Read this.</p></div1></body></text></TEI.2>'
    rendered=legacy_tei_book(xml)
    assert 'Read this.' in _nodes_text(rendered['nodes'])
    assert legacy_tei_book('<!DOCTYPE TEI.2 [<!ENTITY secret SYSTEM "file:///secret">]><TEI.2><text><body><p>&secret;</p></body></text></TEI.2>') is None


def test_jats_tei_keeps_paragraph_runs_together_and_metadata_out_of_prose():
    from cvw_app.tei_renderer import render_tei

    xml='<TEI><text><body><div type="jats:article"><div type="jats:front"><div type="jats:journal-id"><div type="jats:text-run"><p>Metadata</p></div></div></div><div type="jats:body"><div type="jats:p"><div type="jats:text-run"><p>Read </p></div><div type="jats:bold"><div type="jats:text-run"><p>this</p></div></div><div type="jats:text-run"><p>.</p></div></div></div></div></body></text></TEI>'
    assert _nodes_text(render_tei('application/tei+xml',xml)['nodes'])=='Read this.'


def test_jats_native_paragraph_runs_preserve_mixed_text_and_emphasis():
    from cvw_app.tei_renderer import render_tei
    xml='<TEI><text><body><div type="jats:article"><div type="jats:front"><div type="jats:journal-id"><div type="jats:text-run"><p>Metadata</p></div></div></div><div type="jats:body"><div type="jats:p"><p>Read <hi rend="jats:italic">this</hi> carefully.</p></div></div></div></body></text></TEI>'
    r=render_tei('application/tei+xml',xml)
    assert _nodes_text(r['nodes'])=='Read this carefully.'
    assert any('italic' in run['marks'] for node in r['nodes'] for run in node.get('inline',[]))


def test_pdf_previews_page_bounds_and_existing_segment_navigation():
    import pymupdf

    with pymupdf.open() as document:
        for text in ['First page', 'Second page']:
            document.new_page().insert_text((30,40),text)
        payload=document.tobytes()
    assert pdf_page_count(payload)==2
    image=pdf_preview(payload,2)
    assert image.startswith(b'\x89PNG\r\n\x1a\n')
    with pytest.raises(RendererError):
        pdf_preview(payload,3)
    rendered,supported=DEFAULT_RENDERER_REGISTRY.render('pdf-native','application/pdf',payload)
    assert supported and [r['label'] for r in rendered['outline']]==['Page 1','Page 2']
    assert len(rendered['_pages'])==2


def test_current_sword_bindings_require_the_complete_declared_member_set():
    manifest=SimpleNamespace(record={'source_id':'daily-light-installed-review-copy'},sha256='a'*64)
    def artifact(name):
        return dict(name='label',path=name,root='approved',bytes=1,sha256='b'*64)
    with pytest.raises(RendererError,match='incomplete'):
        declared_module_context('daily-light',manifest,[artifact('daily.dat')])
    context=declared_module_context('daily-light',manifest,[artifact('daily.dat'),artifact('daily.idx')])
    assert {m['name'] for m in context['members']} == {'daily.dat','daily.idx'}
    assert context['source_set_sha256']==manifest.sha256


def test_daily_light_entries_have_bounded_independent_contexts():
    first=b'01.01\r\n<i>Morning</i>: First reading.\r\n'
    second=b'01.02\r\n<i>Evening</i>: Second reading.\r\n'
    context={'daily.dat':first+second,'daily.idx':bytes(6)+struct.pack('<IH',0,len(first))+struct.pack('<IH',len(first),len(second)),
             '__selected_name__':b'daily.dat','__source_set_sha256__':b'a'*64}
    rendered=render_sword_members('application/octet-stream',context)
    assert len(rendered['outline'])==2
    assert 'First reading.' in rendered['contexts']['entry-1']['text']
    assert 'Second reading.' not in rendered['contexts']['entry-1']['text']
    with pytest.raises(RendererError,match='invalid'):
        render_sword_members('application/octet-stream',{**context,'daily.idx':context['daily.idx'][:-1]})


def test_dictionary_native_ids_are_selectable_without_merging_entry_contexts():
    from cvw_app.tei_renderer import render_tei
    xml='<TEI><text><body><entryFree xml:id="first"><form><orth>First</orth></form><def>One definition.</def></entryFree><entryFree xml:id="last"><form><orth>Last</orth></form><def>Final definition.</def></entryFree></body></text></TEI>'
    rendered=render_tei('application/tei+xml',xml)
    assert [(r['location'],r['label']) for r in rendered['outline']]==[('first','First'),('last','Last')]
    assert rendered['contexts']['first']['text']=='First One definition.'


def test_generic_source_owner_collection_preserves_first_seen_identity():
    from xml.etree import ElementTree
    from cvw_app.tei_renderer import _render_tei_root
    root=ElementTree.fromstring('<TEI><text><body><unknown><a>First</a><b> last</b></unknown></body></text></TEI>')
    observed=[]
    _render_tei_root(root,_on_body_node=lambda element,node,sources,**kwargs:observed.append(sources))
    assert observed
    assert all(len(sources)==len(set(sources)) for sources in observed)


def test_sword_reading_text_keeps_reference_words_without_machine_annotations():
    from cvw_app.review_renderers import _sword_zld_fragment
    payload=b'<entryFree n="AARON"><def>See <ref target="Exod.6.20">Exodus 6:20</ref>.</def></entryFree>\x00'
    assert _sword_zld_fragment(payload,1,include_targets=False)==('AARON','See Exodus 6:20.')
    assert 'target:Exod.6.20' in _sword_zld_fragment(payload,1)[1]


def test_legacy_tei_extension_uses_the_inert_xml_reader():
    xml='<!DOCTYPE TEI.2 [<!ENTITY unused "literal">]><TEI.2><text><body><div1 id="a"><head>Opening</head><p>Read this.</p></div1></body></text></TEI.2>'
    media,kind,_=_source_presentation(Path('source.tei'))
    rendered,supported=DEFAULT_RENDERER_REGISTRY.render(kind,media,xml)
    assert supported and 'Read this.' in _nodes_text(rendered['nodes'])


def test_djvu_words_use_the_canonical_whitespace_projection():
    rendered=render_xml_reader('application/xml','<DjVuXML><OBJECT><LINE><WORD> Two  </WORD><WORD> words. </WORD></LINE></OBJECT></DjVuXML>')
    assert rendered['nodes'][1]['text']=='Two words.'


def test_tei_usfm_reads_actual_verse_text_without_duplicated_accounting_notes():
    from cvw_app.tei_renderer import render_tei
    xml='<TEI><text><body><div type="book" n="GEN" xml:id="gen"><ab type="usfm-id">GEN</ab><div type="chapter" n="1" xml:id="c1"><ab type="verse" n="1">Actual <hi>verse</hi>.</ab><note type="source-usfm-raw">\\v 1 Actual verse.</note></div></div></body></text></TEI>'
    rendered=render_tei('application/tei+xml',xml)
    assert '1 Actual verse.' in _nodes_text(rendered['nodes'])
    assert '\\v 1' not in _nodes_text(rendered['nodes'])
    assert rendered['contexts']['c1']['text'].count('Actual verse.')==1
    assert any(n['type']=='details' for n in rendered['nodes'])


def test_tei_usfm_multiple_witnesses_have_distinct_native_navigation():
    from cvw_app.tei_renderer import render_tei
    body='<body><div type="book" n="GEN"><ab type="usfm-id">GEN</ab><div type="chapter" n="1"><ab type="verse" n="1">{}</ab></div></div></body>'
    xml='<TEI><text><group><text n="US" xml:id="us">'+body.format('US wording.')+'</text><text n="Cth" xml:id="cth">'+body.format('Commonwealth wording.')+'</text></group></text></TEI>'
    r=render_tei('application/tei+xml',xml)
    assert len({e['location'] for e in r['outline']})==len(r['outline'])
    assert 'US wording.' in r['contexts']['us']['text']
    assert 'Commonwealth wording.' not in r['contexts']['us']['text']


def test_raw_usfm_tei_keeps_unknown_source_markers():
    from cvw_app.tei_renderer import render_tei
    xml='<TEI><text><body><div type="book" n="GEN" xml:id="gen"><ab type="usfm-source-line">\\c 1</ab><ab type="usfm-source-line">\\v 1 Literal verse.</ab><ab type="usfm-source-line">\\unknown Keep this.</ab></div></body></text></TEI>'
    r=render_tei('application/tei+xml',xml)
    assert '1 Literal verse.' in _nodes_text(r['nodes']) and '\\unknown Keep this.' in _nodes_text(r['nodes'])


def test_native_day_and_sword_slots_have_bounded_passages():
    from cvw_app.tei_renderer import render_tei
    for unit in ['<div type="day" n="{}" xml:id="{}"><p>{}</p></div>','<ab type="sword-slot" n="{}" xml:id="{}">{}</ab>']:
        xml='<TEI><text><body>'+unit.format('01.01','first','First reading.')+unit.format('01.02','last','Last reading.')+'</body></text></TEI>'
        r=render_tei('application/tei+xml',xml)
        assert [e['location'] for e in r['outline']]==['first','last']
        assert 'First reading.' in r['contexts']['first']['text'] and 'Last reading.' not in r['contexts']['first']['text']


def test_native_hymn_records_keep_line_breaks_controls_and_metadata_disclosure():
    from cvw_app.tei_renderer import render_tei
    xml='<TEI><text><body><div type="hymn-record" xml:id="h1"><head>First hymn</head><ab type="hymn-text">Line one<lb/>Line two<g ref="#control">[source control U+0008]</g></ab><list type="source-metadata"><item><label>Author: </label><seg>A name</seg></item></list></div></body></text></TEI>'
    r=render_tei('application/tei+xml',xml)
    assert r['nodes'][1]['text']=='Line one\nLine two[source control U+0008]'
    assert r['nodes'][2]['type']=='details' and 'Author: A name' in _nodes_text(r['nodes'][2]['children'])


def test_source_chapter_labels_show_their_value_without_usfm_commands():
    r=render_exact_text('text/x-usfm','\\c 1\n\\cl I.\n\\v 1 Actual verse.\n')
    assert 'I.' in _nodes_text(r['nodes']) and '\\cl' not in _nodes_text(r['nodes'])


def test_wiki_templates_are_disclosed_separately_from_retained_book_pages():
    xml='<mediawiki><page><title>Template:Support</title><ns>10</ns><revision><text>{{source code}}</text></revision></page><page><title>Page:Book/1</title><ns>104</ns><revision><text>Actual retained page</text></revision></page></mediawiki>'
    r=render_xml_reader('application/xml',xml)
    assert r['outline']==[dict(location='page-2',label='Page:Book/1',level=2)]
    assert r['nodes'][1]['text']=='Actual retained page'
    assert r['nodes'][2]['type']=='details' and '{{source code}}' in _nodes_text(r['nodes'][2]['children'])


def test_legacy_gutenberg_style_metadata_is_disclosed_outside_the_book():
    from cvw_app.xml_books import legacy_tei_book
    r=legacy_tei_book('<TEI.2><pgExtensions><pgStyleSheet>.css { style: data }</pgStyleSheet></pgExtensions><text><body><p>Actual book.</p></body></text></TEI.2>')
    assert _nodes_text([n for n in r['nodes'] if n['type']!='details'])=='Actual book.'
    assert r['nodes'][-1]['type']=='details' and '.css' in _nodes_text(r['nodes'][-1]['children'])


def test_untitled_toml_quotations_use_the_explicit_collection_citation():
    from cvw_app.tei_renderer import render_tei
    xml='<TEI><text><body><div type="source-member" subtype="commentary"><head>./1 Corinthians/Psalms 94_11.toml</head><ab type="source-directory">1 Corinthians</ab><div type="commentary-record"><list type="toml-object"><item n="quote"><label>quote</label><seg>Actual quotation.</seg></item><item n="append_to_author_name"><label>append_to_author_name</label><seg> 3:18-23</seg></item></list></div></div></body></text></TEI>'
    r=render_tei('application/tei+xml',xml)
    assert r['nodes'][0]['text']=='1 Corinthians 3:18-23'
    assert r['nodes'][1]['text']=='Actual quotation.'
    assert r['nodes'][2]['type']=='details' and 'Psalms 94_11.toml' in _nodes_text(r['nodes'][2]['children'])


def test_ebible_site_arrows_do_not_replace_the_first_reading_section():
    r,_=DEFAULT_RENDERER_REGISTRY.render('sanitized-html','text/html','<ul class="tnav"><li>^<ul><li>&lt;</li></ul></li></ul><h1>Book title</h1><p>Actual book.</p><ul><li>Real list item</li></ul>')
    assert _nodes_text(r['nodes']).startswith('Book title Actual book.')
    assert 'Real list item' in _nodes_text(r['nodes']) and '^' not in _nodes_text(r['nodes'])
