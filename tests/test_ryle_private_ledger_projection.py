"""Ryle source-ledger exclusion and private receipt mutation checks."""
import copy

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document, verify_document


def test_ryle_source_ledger_is_private_and_missing_or_changed_ledger_fails(tmp_path):
    carriers = ''.join(
        f'<ab xml:id="ryle-holiness-source-feature-{number:05d}" '
        f'type="source-element" subtype="p" n="{number}" '
        'corresp="urn:source-xpath:%2FThML%5B1%5D%2Fp%5B1%5D">'
        '<seg type="direct-text"/><seg type="tail-text"/>'
        '<seg type="source-attributes">[]</seg></ab>'
        for number in range(1, 5699)
    )
    ledger = (
        '<div xml:id="ryle-holiness-source-ledger" type="source-accountability">'
        '<head>Complete retained source element ledger</head>' + carriers + '</div>'
    )
    document = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>Holiness</title></titleStmt>'
        '<publicationStmt><p>Private</p></publicationStmt>'
        '<sourceDesc><p>Retained CCEL source</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body><div><p>Public text.</p></div></body><back>' + ledger + '</back></text></TEI>'
    )
    path = tmp_path / 'ryle.xml'
    path.write_text(document, encoding='utf-8')
    context = dict(
        identity={'work_id': 'ryle-holiness', 'textual_form_id': 'ryle-holiness-english',
                  'edition_id': 'ryle-holiness-retained-electronic-witness'},
        language='en', representation_revision='test', edition_title='Holiness',
        category='prose', _allow_acceptance_metadata=True,
    )
    result = project_document(path, **context)
    assert len(result['rows']) == 1
    assert result['rows'][0]['text'] == 'Public text.'
    assert 'source-feature' not in str(result['rows'])
    private = [item for item in result['receipt']['inventory']
               if item['role'] == 'source-generator-only']
    assert len(private) == 1 + 1 + 5698 * 4
    assert verify_document(path, result['rows'], result['receipt'], **context) == []

    altered = copy.deepcopy(result['receipt'])
    carrier = next(item for item in altered['inventory']
                   if item['attributes'].get('{http://www.w3.org/XML/1998/namespace}id')
                   == 'ryle-holiness-source-feature-00001')
    carrier['attributes']['corresp'] = 'urn:source-xpath:changed'
    assert verify_document(path, result['rows'], altered, **context)

    path.write_text(document.replace('type="source-accountability"', 'type="changed"'), encoding='utf-8')
    with pytest.raises(PipelineError, match='private source ledger envelope'):
        project_document(path, **context)
    assert verify_document(path, result['rows'], result['receipt'], **context)

    path.write_text(document.replace(ledger, ''), encoding='utf-8')
    with pytest.raises(PipelineError, match='private source ledger is missing'):
        project_document(path, **context)
    assert verify_document(path, result['rows'], result['receipt'], **context)
