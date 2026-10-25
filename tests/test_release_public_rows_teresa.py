"""Focused reversible Teresa public-boundary behavior and mutation checks."""

from copy import deepcopy
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release import public_rows as boundary

ITEM = boundary.TERESA_ITEM
ACCEPTANCE, MASTER = boundary.PG_ITEMS[ITEM]

def carrier(number='Saint', printed='St.'):
    return {'kind': 'segment',
            'attributes': {'source_annotations': boundary.TERESA_PRIVATE_ANNOTATION,
                           'number': number},
            'content': [{'kind': 'abbreviated-text', 'attributes': {},
                         'content': [{'kind': 'text', 'text': printed}]}]}

def rows():
    return [{'record_id': 'teresa-synthetic',
             'provenance': {'source_location': 'raw/gutenberg/8120/source.html'},
             'structure': [{'kind': 'paragraph', 'attributes': {},
                            'content': [carrier() for _ in range(528)]}]}]

def make(private=None):
    return boundary.public_rows_with_omissions(
        private or rows(), item_id=ITEM, acceptance_sha256=ACCEPTANCE, master_sha256=MASTER)

def restore(public, artifact):
    return boundary.restore_private_source_locations(
        public, artifact, item_id=ITEM, acceptance_sha256=ACCEPTANCE, master_sha256=MASTER)

def test_exact_abbreviation_expansions_are_public_and_reversible():
    private = rows()
    private[0]['structure'][0]['content'][0]['content'][0]['attributes'] = {'language': 'la'}
    public, receipt = make(private)
    children = public[0]['structure'][0]['content']
    assert len(children) == 528
    assert all(child['attributes'] == {'source_annotations': 'abbreviation-expansion',
                                       'number': 'Saint'} for child in children)
    assert children[0]['content'][0]['attributes'] == {'language': 'la'}
    assert all(child['content'] == carrier()['content'] for child in children[1:])
    assert not _scan(public, 'Teresa synthetic public')
    assert restore(public, receipt) == private

@pytest.mark.parametrize('mutation', ['count', 'kind', 'number', 'child', 'language', 'annotation'])
def test_private_carrier_must_match_exact_scope(mutation):
    private = rows()
    node = private[0]['structure'][0]['content'][0]
    if mutation == 'count':
        private[0]['structure'][0]['content'].pop()
    elif mutation == 'kind':
        node['kind'] = 'emphasis'
    elif mutation == 'number':
        node['attributes']['number'] = ''
    elif mutation == 'child':
        node['content'][0]['kind'] = 'text'
    elif mutation == 'language':
        node['content'][0]['attributes'] = {'language': 'xx'}
    else:
        node['attributes']['source_annotations'] = 'urn:ocd:unknown'
    with pytest.raises(PipelineError):
        make(private)

@pytest.mark.parametrize('mutation', ['expansion', 'printed', 'language', 'annotation', 'receipt_field', 'receipt_authority'])
def test_public_semantics_and_private_receipt_cannot_drift(mutation):
    public, receipt = make()
    public, receipt = deepcopy(public), deepcopy(receipt)
    node = public[0]['structure'][0]['content'][0]
    if mutation == 'expansion':
        node['attributes']['number'] = 'changed'
    elif mutation == 'printed':
        node['content'][0]['content'][0]['text'] = 'changed'
    elif mutation == 'language':
        node['content'][0]['attributes'] = {'language': 'es'}
    elif mutation == 'annotation':
        node['attributes']['source_annotations'] = 'other'
    elif mutation == 'receipt_field':
        receipt['omissions'][0]['fields'].pop()
    else:
        receipt['authority']['teresa_scope_evidence_sha256'] = '0' * 64
    with pytest.raises(PipelineError):
        restore(public, receipt)

def test_unpinned_authority_cannot_apply_teresa_route():
    with pytest.raises(PipelineError):
        boundary.public_rows_with_omissions(
            rows(), item_id=ITEM, acceptance_sha256='0' * 64, master_sha256=MASTER)
