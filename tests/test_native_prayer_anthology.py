"""A prayer anthology retains native units without invented petition/response roles."""
from __future__ import annotations
import copy
from pathlib import Path

from ocd_kernel.projection.categories.prayers import (
    _uses_native_anthology, project_prayers_document, verify_prayers_document,
)

CONTEXT = dict(identity={'work_id':'anthology','textual_form_id':'english','edition_id':'witness'},
               language='en', representation_revision='r1', edition_title='Retained anthology')


def anthology(tmp_path: Path) -> Path:
    path=tmp_path/'anthology.xml'
    path.write_text('''<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="source-book"><teiHeader><fileDesc>
<titleStmt><title>Prayer collection</title></titleStmt><publicationStmt><p>Private rehearsal.</p></publicationStmt>
<sourceDesc><p>Retained witness.</p></sourceDesc></fileDesc></teiHeader><text>
<front><div type="title-page"><head>Prayer collection</head></div></front>
<body><div type="section"><head>Morning</head><p>Opening prayer.</p>
<lg type="verse"><l>First line</l><l>Second line</l></lg>
<table><row><cell><p>Column one</p></cell><cell><p>Column two</p></cell></row></table>
<fw type="page-number">[7]</fw></div></body>
<back><div type="appendix"><p>Closing note.</p></div></back>
</text></TEI>''',encoding='utf-8')
    return path


def test_anthology_routes_by_source_structure_and_checks_exact_content(tmp_path):
    path=anthology(tmp_path)
    assert _uses_native_anthology(path)
    projection=project_prayers_document(path,**CONTEXT)
    rows,receipt=projection['rows'],projection['receipt']
    assert [r['locator']['text_part'] for r in rows]==['front','body','back']
    assert [r['category'] for r in rows]==['prayers']*3
    assert all('divisions' not in r for r in rows)
    assert rows[1]['structure'][0]['kind']=='division'
    assert 'First line' in rows[1]['text'] and 'Column two' in rows[1]['text']
    assert '[7]' not in rows[1]['text']
    assert verify_prayers_document(path,rows,receipt,**CONTEXT)==[]
    altered=copy.deepcopy(rows)
    altered[1]['structure'][0]['content'].pop()
    assert verify_prayers_document(path,altered,receipt,**CONTEXT)


def test_bounded_liturgical_prayer_stays_on_its_profile():
    path=Path(__file__).resolve().parent/'fixtures/library-pipeline/categories/prayers/collects.tei.xml'
    assert not _uses_native_anthology(path)
