"""Exact accepted Chronicles source marker and reversible public boundary."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection import native_content, native_content_check
from ocd_kernel.projection.categories.commentary import (
    project_accepted_commentary, verify_accepted_commentary)
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import (
    BENNETT_ITEM, public_rows_with_omissions, restore_private_source_locations)
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / (
    'library/works/expositors-bible--w-h-bennett/forms/'
    'expositors-bible--w-h-bennett--bennett-expositor10--retained-en/editions/'
    'expositors-bible--w-h-bennett--bennett-expositor10--ccel-electronic/acceptance.json')
MASTER_SHA = '687ada6bf687e9727f2e95d76b8d66d96d1a9af7a2f04a20fe906cfd01a3e523'
LICENSE = 'Public domain (United States); identified historical text and apparatus only'


@pytest.fixture(scope='module')
def real_projection():
    assert sha256(ACCEPTANCE.with_name('master.tei.xml').read_bytes()).hexdigest() == MASTER_SHA
    with cached_edition_lookups():
        result = project_accepted_commentary(ROOT, acceptance_path=ACCEPTANCE)
        assert verify_accepted_commentary(
            ROOT, acceptance_path=ACCEPTANCE, rows=result['rows'],
            receipt=result['receipt']) == []
    return result


def _markers(value):
    if isinstance(value, dict):
        if value.get('attributes', {}).get('unit') == 'source-colgroup':
            yield value
        for child in value.values():
            yield from _markers(child)
    elif isinstance(value, list):
        for child in value:
            yield from _markers(child)


def test_bennett_accepted_table_marker_and_text(real_projection):
    rows = real_projection['rows']
    assert len(rows) == 7
    assert sum(len(row['text']) for row in rows) == 733159
    markers = [marker for row in rows for marker in _markers(row['structure'])]
    assert len(markers) == 1
    assert markers[0]['kind'] == 'source-marker'
    assert markers[0]['attributes']['number'] == '2'
    assert markers[0]['attributes']['unit'] == 'source-colgroup'


def test_bennett_marker_rejects_changed_span_and_generic_scope():
    root = etree.fromstring(ACCEPTANCE.with_name('master.tei.xml').read_bytes())
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    markers = root.xpath('//t:milestone[@unit="source-colgroup"]', namespaces=ns)
    assert len(markers) == 1
    table = markers[0].getparent()
    fragment = etree.tostring(table, with_tail=False)
    _, readable = native_content_check.observe_content(
        fragment, source_profile=native_content.BENNETT_CHRONICLES_PROFILE)
    assert readable
    with pytest.raises(ValueError, match='Bennett source column group differs'):
        native_content_check.observe_content(
            fragment.replace(b'urn:ccel:source-attribute:span:2',
                             b'urn:ccel:source-attribute:span:3'),
            source_profile=native_content.BENNETT_CHRONICLES_PROFILE)
    with pytest.raises(ValueError, match='unsupported native milestone unit'):
        native_content_check.observe_content(fragment)
    with pytest.raises(PipelineError, match='unsupported native milestone unit'):
        native_content.project_content(
            ET.fromstring(fragment))


def test_bennett_public_transform_exact_inverse_and_tamper(real_projection):
    raw = [dict(row, license=LICENSE) for row in real_projection['rows']]
    private, _ = compose_work_metadata(ROOT, raw, real_projection['receipt'])
    acceptance_sha = sha256(ACCEPTANCE.read_bytes()).hexdigest()
    public, artifact = public_rows_with_omissions(
        private, item_id=BENNETT_ITEM, acceptance_sha256=acceptance_sha,
        master_sha256=MASTER_SHA)
    assert artifact is not None
    assert sum(len(row['text']) for row in public) == 733159
    assert [row['text'] for row in public] == [row['text'] for row in private]
    assert not _scan(public, BENNETT_ITEM)
    public_json = json.dumps(public, ensure_ascii=False)
    assert 'urn:ccel:source-attribute:' not in public_json
    assert 'source-class-' not in public_json
    assert 'font-size:' not in public_json
    assert 'margin-bottom:' not in public_json
    assert restore_private_source_locations(
        public, artifact, item_id=BENNETT_ITEM,
        acceptance_sha256=acceptance_sha, master_sha256=MASTER_SHA) == private
    incomplete = deepcopy(artifact)
    incomplete['omissions'][0]['fields'].pop()
    with pytest.raises(PipelineError):
        restore_private_source_locations(
            public, incomplete, item_id=BENNETT_ITEM,
            acceptance_sha256=acceptance_sha, master_sha256=MASTER_SHA)
    with pytest.raises(PipelineError):
        restore_private_source_locations(
            public, artifact, item_id=BENNETT_ITEM,
            acceptance_sha256='0' * 64, master_sha256=MASTER_SHA)
