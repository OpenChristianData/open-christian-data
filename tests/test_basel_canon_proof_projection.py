"""Basel's source labels, conclusion, and unaligned proof groups remain faithful."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.creeds_json_canon_variants import project_units, verify_units, shape


def _fixture():
    root = Path(__file__).resolve().parents[1]
    source_path = 'raw/Creeds.json/creeds/first_confession_of_basel.json'
    source = (root / source_path).read_bytes()
    document = json.loads(source)
    context = {'work_id': 'first-confession-of-basel', 'source_bytes': source,
        'identity': {'work_id': 'first-confession-of-basel', 'textual_form_id': 'english', 'edition_id': 'retained-basel'},
        'accepted': {'representation_revision': {'id': 'retained-v1'}}, 'edition_title': 'Retained Basel',
        'source_url': 'https://example.org/basel', 'source_path': source_path, 'document': document}
    loci = {f'$/Data/{i}#item': f'article-{i}' for i in range(len(document['Data']))}
    crosswalk = {(f'$/Data/{i}', 'item'): f'article-{i}' for i in range(len(document['Data']))}
    return context, document, loci, crosswalk


def test_basel_preserves_all_source_units_and_proof_groups():
    context, document, loci, crosswalk = _fixture()
    rows = project_units(context, document, loci)
    assert len(rows) == 13
    assert [row['number'] for row in rows] == [unit['Article'] for unit in document['Data']]
    assert rows[-1]['locator']['text_part'] == 'back' and rows[-1]['unit_type'] == 'text'
    assert rows[3]['proofs'][0]['references'][0] == {
        'raw': '\n'.join(document['Data'][3]['ProofsWithScripture'][0]['References']),
        'osis': document['Data'][3]['Proofs'][0]['References']}
    assert rows[5]['proofs'][3]['references'][0]['osis'] == []
    assert rows[5]['proofs'][3]['references'][0]['raw']
    assert [row['content_with_proofs'] for row in rows] == [unit['ContentWithProofs'] for unit in document['Data']]
    assert verify_units(context, rows, crosswalk) == []


@pytest.mark.parametrize('field', ['raw', 'osis', 'number', 'content_with_proofs', 'conclusion'])
def test_basel_independent_check_rejects_changed_public_claim(field):
    context, document, loci, crosswalk = _fixture()
    rows = project_units(context, document, loci)
    if field in ('raw', 'osis'):
        rows[0]['proofs'][0]['references'][0][field] = 'invented' if field == 'raw' else ['Gen.9.9']
    elif field == 'conclusion':
        rows[-1]['locator']['text_part'] = 'body'
    else:
        rows[0][field] = 'invented'
    assert verify_units(context, rows, crosswalk)


def test_basel_rejects_source_proof_id_mismatch_and_source_substitution():
    context, document, loci, _ = _fixture()
    changed = deepcopy(document)
    changed['Data'][0]['ProofsWithScripture'][0]['Id'] = 9
    with pytest.raises(PipelineError, match='proof IDs'):
        shape(context['work_id'], changed)
    context['source_bytes'] += b' '
    with pytest.raises(PipelineError, match='source bytes'):
        project_units(context, document, loci)


def test_existing_canon_route_still_rejects_unexpected_proof_fields():
    route_path = Path(__file__).resolve().parents[1] / 'raw/Creeds.json/creeds/council_of_orange.json'
    document = json.loads(route_path.read_bytes())
    document['Data'][0]['Proofs'] = []
    with pytest.raises(PipelineError, match='unsupported fields'):
        shape('council-of-orange', document)


def test_basel_projection_does_not_expand_historical_install_authority():
    from build.tools.stage_creeds_json_canon_variants import ROUTES
    assert 'first-confession-of-basel' not in ROUTES
