"""Cataloging stays bound to existing leads and visible through their readers."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from build.tools.build_public_acquisition_list import current_snapshot, project, render
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import load_acquisition_leads
from ocd_kernel.library.cataloging import FIELDS, MARKER, load_note, note_path, render_note
from ocd_kernel.library.records import lookup_library_record, render_library_record
from tests.test_acquisition_leads import research_root


def fixture(tmp_path):
    root = research_root(tmp_path)
    lead = load_acquisition_leads(root/'library/acquisition-leads.jsonl', root=root)[0]
    fields = dict.fromkeys(FIELDS, '')
    fields.update(title='Existing claim', identifiers=lead['lead_id'], work_scope='Named work',
                  author='Recorded author', researcher='Existing research')
    path = root/note_path(lead['lead_id'])
    path.parent.mkdir()
    path.write_text(render_note(lead, fields, [lead['evidence']]), encoding='utf-8')
    return root, lead, fields, path


def test_note_roundtrip_preserves_blanks_and_template_labels(tmp_path):
    root, lead, fields, path = fixture(tmp_path)
    assert load_note(root, lead)['fields'] == fields
    assert fields['publication'] == ''
    template = (Path(__file__).resolve().parents[1]/'docs/examples/information-templates.md').read_text(encoding='utf-8')
    example = template.split('```text\n',1)[1].split('```',1)[0]
    labels = {line.partition(':')[0] for line in example.splitlines() if ':' in line}
    assert labels == set(FIELDS.values())
    assert not any(line.rstrip()!=line for line in path.read_text(encoding='utf-8').splitlines())


@pytest.mark.parametrize('mutation', ['lead','source','duplicate','missing','extent'])
def test_invalid_cataloging_fails_closed(tmp_path, mutation):
    root, lead, fields, path = fixture(tmp_path)
    if mutation == 'lead':
        lead = deepcopy(lead)
        lead['acquisition_intent'] = 'Changed after cataloging'
    elif mutation == 'source':
        (root/'research/MANIFEST.md').write_text('Changed evidence',encoding='utf-8')
    else:
        text = path.read_text(encoding='utf-8')
        if mutation == 'duplicate':
            text = text.replace(MARKER, '\n**Title:** Another title\n'+MARKER)
        elif mutation == 'missing':
            text = text.replace('**Original language:**\n', '')
        else:
            text = text.replace('"line_start": 9', '"line_start": 99999')
        path.write_text(text,encoding='utf-8')
    with pytest.raises(PipelineError):
        load_note(root,lead)


def test_lookup_exposes_cataloging_without_changing_queue(tmp_path):
    root, lead, fields, path = fixture(tmp_path)
    queue = root/'library/acquisition-leads.jsonl'
    before = queue.read_bytes()
    result = lookup_library_record(root, {'kind':'research_lead','namespace':'research','id':lead['lead_id']})
    selected = result['sections']['research']['data']['leads']
    assert selected[0]['cataloging']['fields'] == fields
    assert 'Cataloging: '+note_path(lead['lead_id']) in render_library_record(result)
    assert queue.read_bytes() == before


def test_public_projection_includes_cataloging_but_not_private_evidence(tmp_path):
    root, lead, fields, path = fixture(tmp_path)
    shutil.copytree(Path(__file__).resolve().parents[1]/'tests/fixtures/library-pipeline',root,dirs_exist_ok=True)
    state_path = next((root/'library/works').glob('*/state.json'))
    state = json.loads(state_path.read_text())
    state['targets'][0]['stage']='acquired'
    state_path.write_text(json.dumps(state),encoding='utf-8')
    value = project(current_snapshot(root),'now')
    row = next(item for item in value['research_leads'] if item['lead_id']==lead['lead_id'])
    assert row['cataloging']['author'] == 'Recorded author'
    assert row['cataloging']['publication'] == ''
    assert 'evidence' not in row['cataloging'] and 'sha256' not in json.dumps(row)
    assert 'cataloging-'+lead['lead_id'] in render(value)
    path.write_text(render_note(lead,{**fields,'source':'https://user:password@example.org/source',
                                     'primary_evidence':'reports/private/receipt.json'},[lead['evidence']]),encoding='utf-8')
    row = next(item for item in project(current_snapshot(root),'now')['research_leads'] if item['lead_id']==lead['lead_id'])
    assert row['cataloging']['source'] == row['cataloging']['primary_evidence'] == ''


def test_stale_relationship_does_not_hide_independently_bound_cataloging(tmp_path, monkeypatch):
    from ocd_kernel.library import record_connections
    root, lead, fields, path = fixture(tmp_path)
    def stale(*args):
        raise PipelineError('stale evidence: unrelated work record')
    monkeypatch.setattr(record_connections, '_relationships', stale)
    record = lookup_library_record(root, {'kind':'research_lead','namespace':'research','id':lead['lead_id']})
    assert record['sections']['research']['data']['leads'][0]['cataloging']['fields'] == fields
    assert any(item['code']=='stale' and 'unrelated' in item['message'] for item in record['diagnostics'])
    assert record['sections']['research']['data']['relationships'] == []


def test_missing_note_is_backward_compatible_and_topics_keep_no_invented_title(tmp_path):
    root, lead, fields, path = fixture(tmp_path)
    path.unlink()
    assert load_note(root,lead) is None
    record = lookup_library_record(root, {'kind':'research_lead','namespace':'research','id':lead['lead_id']})
    assert record['sections']['research']['data']['leads'][0]['lead_id'] == lead['lead_id']
    assert not any(item['path'] == note_path(lead['lead_id']) for item in record['diagnostics'])
    fields.update(title='',work_scope='Research area: hymn collections')
    path.write_text(render_note(lead,fields,[lead['evidence']]),encoding='utf-8')
    assert load_note(root,lead)['fields']['title'] == ''


def test_library_view_binds_cataloging_note_bytes(tmp_path):
    from ocd_kernel.library.views import _build_snapshot
    root, lead, fields, path = fixture(tmp_path)
    shutil.copytree(Path(__file__).resolve().parents[1]/'tests/fixtures/library-pipeline',root,dirs_exist_ok=True)
    first = _build_snapshot(root)
    row = next(item for item in first['queue']['research_leads'] if item['lead_id']==lead['lead_id'])
    assert row['cataloging']['fields']['author']=='Recorded author'
    path.write_text(render_note(lead,{**fields,'publication':'A newly evidenced imprint'},[lead['evidence']]),encoding='utf-8')
    second = _build_snapshot(root)
    assert first['queue']['freshness']['input_sha256'] != second['queue']['freshness']['input_sha256']
