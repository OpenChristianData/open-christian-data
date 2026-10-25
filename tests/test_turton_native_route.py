"""Turton PG 42460 source roles use the accepted native prose path."""

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import prose
from ocd_kernel.projection.categories.sermons import _accepted_context


ROOT = Path.cwd()
ACCEPTANCE = ROOT / (
    'library/works/turton-truth-of-christianity-1919/forms/'
    'turton-truth-of-christianity-1919-gutenberg-retained-en/editions/'
    'turton-truth-of-christianity-1919-gutenberg-electronic/acceptance.json'
)
ACCEPTANCE_SHA = 'c2df2729129610c060ac9bb014f06b7434c192b96303aa265ecce15b55ce4fdc'
MASTER_SHA = '172e6f53424b51ce3c432f4707ff8aa8c48b879f57b92bde2b616dfcd68feb4d'
ACQUISITION_SHA = '4b83ab7b4337821a8be4cc405f76142ef1ac0a5797dbdfede266cb984a8dd28f'


def test_turton_real_accepted_native_dispatch_and_independent_check():
    assert hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest() == ACCEPTANCE_SHA
    result = prose.project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
    rows, receipt = result['rows'], result['receipt']
    assert len(rows) == 11
    assert receipt['mapping_version'] == 'ocd-prose-native-v3'
    assert receipt['authority']['master']['sha256'] == MASTER_SHA
    assert [row['locator']['text_part'] for row in rows] == ['front'] * 5 + ['body'] * 3 + ['back'] * 3
    assert [row['structure'][0]['attributes'].get('type') for row in rows] == [
        'project_gutenberg_header', 'opening_transcribers_note', 'press_and_title_page',
        'preface', 'contents', 'part', 'part', 'part', 'indexes_and_printer',
        'terminal_transcribers_notes', 'project_gutenberg_footer',
    ]
    assert '*** START OF THE PROJECT GUTENBERG EBOOK 42460 ***' in rows[0]['text']
    assert '*** END OF THE PROJECT GUTENBERG EBOOK 42460 ***' in rows[-1]['text']
    assert not prose.verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE, rows=rows, receipt=receipt)

    changed = deepcopy(rows)
    changed[0]['text'] = changed[0]['text'].replace('START', 'FALSE')
    assert prose.verify_accepted_prose(
        ROOT, acceptance_path=ACCEPTANCE, rows=changed, receipt=receipt
    )


def test_turton_route_rejects_authority_drift_and_wrong_identity():
    context = _accepted_context(ROOT, ACCEPTANCE, expected_category='prose')
    assert context['authority']['acceptance']['sha256'] == ACCEPTANCE_SHA
    assert context['authority']['master']['sha256'] == MASTER_SHA
    assert context['authority']['acquisition']['sha256'] == ACQUISITION_SHA
    assert prose._turton_accepted_native(ROOT, context)
    for key in ('acceptance', 'master', 'acquisition'):
        changed = {**context, 'authority': deepcopy(context['authority'])}
        changed['authority'][key]['sha256'] = '0' * 64
        with pytest.raises(PipelineError, match='Turton accepted identity, authority, or profile differs'):
            prose._turton_accepted_native(ROOT, changed)
    changed = {**context, 'accepted': deepcopy(context['accepted'])}
    changed['accepted']['identity']['acquisition_id'] = 'wrong-acquisition'
    with pytest.raises(PipelineError, match='Turton accepted identity, authority, or profile differs'):
        prose._turton_accepted_native(ROOT, changed)
    changed = {**context, 'identity': dict(context['identity'])}
    changed['identity']['work_id'] = 'unrelated-work'
    assert not prose._turton_accepted_native(ROOT, changed)
