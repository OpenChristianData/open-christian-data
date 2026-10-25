"""Read-only evidence checks for the pinned real two-category native pilot."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.release.selection import validate_release_selection

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-028'
NS = '{http://www.tei-c.org/ns/1.0}'
pytestmark = pytest.mark.requires_local_artifacts


def test_real_pilot_accounts_for_complete_source_units_and_unchanged_masters():
    selection = validate_release_selection(json.loads((EVIDENCE/'04-native-pilot-selection.json').read_text(encoding='utf-8')))
    preflight = json.loads((EVIDENCE/'05-native-pilot-preflight.json').read_text(encoding='utf-8'))
    release = resolve_repo_path(ROOT, 'exports/releases/'+selection['release_id'])
    try:
        report = json.loads((release/'internal/release-report.json').read_text(encoding='utf-8'))
    except (FileNotFoundError, PermissionError):
        pytest.skip('Pinned durable pilot is absent or unavailable to this account; host proof is required.')
    assert report['status'] == 'pass'
    assert report['accounting'] == {'requested': 2, 'included': 0, 'warned': 2, 'failed': 0, 'excluded': 0}
    assert {item['category'] for item in selection['items']} == {'prose', 'sermons'}
    contexts = {item['work_id']: item for item in preflight['selected_evidence']}
    for item in report['items']:
        bound = contexts[item['item_id']]['authority']['master']
        source_path = ROOT/bound['path']
        source_bytes = source_path.read_bytes()
        assert hashlib.sha256(source_bytes).hexdigest() == bound['sha256']
        source = ET.fromstring(source_bytes).find(NS+'text')
        config = next(config for config in report['configurations'] if config['category'] == item['category'])
        public_bytes = (release/config['path']).read_bytes()
        assert hashlib.sha256(public_bytes).hexdigest() == config['sha256']
        rows = [json.loads(line) for line in public_bytes.splitlines()]
        source_units = list(source.find(NS+'body')) if item['category'] == 'sermons' else [unit for part in source for unit in part]
        assert len(rows) == len(source_units) == item['row_count']
        for row, unit in zip(rows, source_units):
            assert row['content_format'] == 'ocd-native-content-v1'
            assert row['structure'][0]['attributes'].get('type') == unit.get('type')
            # Count actual native paragraph, list, verse and note carriers,
            # independently of the producer and its correspondence checker.
            mapping = {'p': 'paragraph', 'list': 'list', 'lg': 'verse-group', 'l': 'verse-line', 'note': 'note', 'g': 'glyph', 'gap': 'gap'}
            pending = list(row['structure'])
            observed = []
            while pending:
                node = pending.pop()
                observed.append(node['kind'])
                pending.extend(node.get('content', []))
            for tag, kind in mapping.items():
                assert observed.count(kind) == sum(1 for _ in unit.iter(NS+tag))
        if item['category'] == 'sermons':
            assert rows[0]['front_matter'][0]['structure']['kind'] == 'front-matter'
            assert rows[0]['primary_passage'] == 'ROMANS VI. 23.'
