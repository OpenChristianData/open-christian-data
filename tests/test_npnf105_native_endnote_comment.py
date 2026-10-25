"""Source-attested NPNF105 endnote comment projection contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document, verify_document


OPEN = '<!-- <a href="#_edn1609" name="_ednref1609" id="xiv.iv-p1.3">  -->'
CLOSE = '<!-- </a> -->'
SEGMENT = f'<seg xml:id="npnf105-xiv.iv-p1.2" rend="MsoEndnoteReference"> {OPEN}[1609]{CLOSE}</seg>'
DOCUMENT = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt>'
    '<title>Proceedings of Pelagius</title></titleStmt><publicationStmt><p>Private</p>'
    '</publicationStmt><sourceDesc><p>Retained CCEL XML</p></sourceDesc></fileDesc>'
    '</teiHeader><text><body><div><p>Before ' + SEGMENT + ' after.</p></div></body></text></TEI>'
)
CONTEXT = dict(
    identity={'work_id': 'augustine-proceedings-of-pelagius',
              'textual_form_id': 'form', 'edition_id': 'edition'},
    language='en', representation_revision='source-comment-regression',
    edition_title='Proceedings of Pelagius', category='prose',
    _allow_acceptance_metadata=True,
)


def test_source_endnote_anchor_comments_keep_visible_marker_and_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / 'proceedings.xml'
    path.write_text(DOCUMENT, encoding='utf-8')
    result = project_document(path, **CONTEXT)
    assert '[1609]' in result['rows'][0]['text']
    assert 'href=' not in result['rows'][0]['text']
    comments = result['receipt']['source_comments']
    assert [item['disposition'] for item in comments] == ['source-endnote-anchor-marker'] * 2
    assert [item['tail'] for item in comments] == ['[1609]', '']
    assert verify_document(path, result['rows'], result['receipt'], **CONTEXT) == []

    altered = deepcopy(result['receipt'])
    altered['source_comments'][0]['tail'] = '[1608]'
    assert verify_document(path, result['rows'], altered, **CONTEXT)
    changed_rows = deepcopy(result['rows'])
    changed_rows[0]['text'] = changed_rows[0]['text'].replace('[1609]', '[1608]')
    assert verify_document(path, changed_rows, result['receipt'], **CONTEXT)

    mutations = (
        DOCUMENT.replace('#_edn1609', '#_edn1608'),
        DOCUMENT.replace('[1609]', '[1608]'),
        DOCUMENT.replace(CLOSE, '<!-- </b> -->'),
        DOCUMENT.replace('npnf105-xiv.iv-p1.2', 'npnf105-xiv.iv-p1.4'),
        DOCUMENT.replace(CLOSE + '</seg>', CLOSE + 'X</seg>'),
        DOCUMENT.replace(CLOSE, ''),
    )
    for mutated in mutations:
        path.write_text(mutated, encoding='utf-8')
        with pytest.raises(PipelineError, match='source endnote marker|source comment location'):
            project_document(path, **CONTEXT)
        assert verify_document(path, result['rows'], result['receipt'], **CONTEXT)
