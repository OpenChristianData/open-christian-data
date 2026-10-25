"""Prepare existing Strong II header/metadata only; no canonical installation.

The retained source proof runs in a separate admitted process. This helper never
imports its producer or oracle and never changes the reviewed readable text.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lxml import etree
from ocd_kernel.lib.path_io import io_path, resolve_path
from ocd_kernel.library.identities import validate_record
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

LOG = Path('reports/_logs/strong-complete-work-preflight-20261004-v1')
SOURCE = Path('sources/strong-systematic-theology-vol-2/current-retained-20261004-v1')
PACKAGE = Path('D:/Library/Open Christian Data/candidate-reviews/strong-vol2-current-20261004-v1/strict-baseline/package')
WORK_ID = 'strong-systematic-theology-vol-2'
FORM = WORK_ID + '-english'
EDITION = WORK_ID + '-retained-electronic-witness'
ACQUISITION = WORK_ID + '-retained-source'
WORK = Path('library/works') / WORK_ID
EDITION_PATH = WORK / 'forms' / FORM / 'editions' / EDITION
ACQUISITION_PATH = EDITION_PATH / 'acquisitions' / (ACQUISITION + '.json')
EVIDENCE = WORK / 'integration/strong-vol2-current-20261004-v1'
N = '{http://www.tei-c.org/ns/1.0}'
REVISION = {'id': 'strong-vol2-accepted-retained-20261004-v1', 'date': '2026-10-04',
            'note': 'Agent-reviewed retained Volume II electronic witness of one authored three-volume Systematic Theology. Complete reviewed text and original source administration are conserved. Human review, print collation, rights and publication remain separate.'}
OLD_STATUS = 'Nonaccepted reconstruction candidate; publication:not_ready.'
NEW_STATUS = 'Agent-accepted retained Volume II electronic witness of one authored three-volume work. Human verification: not_recorded; print collation: not_recorded; rights: unresolved; publication: not_ready.'
SCOPE = ('Complete retained Volume II book region, Doctrine of Man, Parts IV through VI, of one authored three-volume Systematic Theology; Judson Press, Philadelphia, 1907, as stated in this electronic witness. This selection does not claim the complete authored three-volume work or a uniform printing with accepted Volumes I and III. All 34,523 raw physical records are accounted for: 30,162 represented nonblank book lines, 3,985 internal blanks, and 376 provider-envelope records. Provider credits and the complete license envelope remain human-visible in README.source.md and exact source accounting. Literal underscore punctuation and source line layout remain retained, without inferred print styling. Historical candidate publication assertion retained as source administration: "' + OLD_STATUS + '"')
PINS = {
    (LOG / 'source-proof-final-v1.json').as_posix(): '223049b2ebd9ef41eed73256dba9d753a8c21d25de85794e81b01d52670eb26e',
    (LOG / 'root-static-implementation-review-v3.json').as_posix(): '446483564a0ede40ed87ea5eece1f9524f376c3fa3f87d8e480bd533ab334667',
    (SOURCE / 'source-manifest.json').as_posix(): '3b79f2be6a0465dade86a0863fee66434766bc7839838f11fe0ff4dbaf171a8c',
}

def raw(root, path):
    return io_path(root / path).read_bytes()

def enc(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')

def sha(value):
    return sha256(value).hexdigest()

def identity():
    return dict(work_id=WORK_ID, textual_form_id=FORM, edition_id=EDITION, acquisition_id=ACQUISITION)

def fields(node):
    return [(part.tag, dict(part.attrib), part.text, part.tail, len(part)) for part in node.iter()]

def assert_sources(root=ROOT):
    for relative, expected in PINS.items():
        if sha(raw(root, relative)) != expected:
            raise ValueError('Reviewed Strong II source pin drifted: ' + relative)
    proof = json.loads(raw(root, LOG / 'source-proof-final-v1.json'))
    if proof['status'] != 'pass' or proof['work_id'] != WORK_ID or proof['challenge_denominator']['total'] != 37:
        raise ValueError('Strong II finite reviewed source proof differs')
    package = proof['packages']['strict-baseline']['members']
    if {p.name for p in io_path(PACKAGE).iterdir() if p.is_file()} != set(package):
        raise ValueError('Strong II reviewed six-member package differs')
    for name, binding in package.items():
        content = io_path(PACKAGE / name).read_bytes()
        if sha(content) != binding['sha256'] or len(content) != binding['bytes']:
            raise ValueError('Strong II reviewed source package drifted: ' + name)
    for binding in proof['source_contracts'].values():
        if sha(io_path(Path(binding['path'])).read_bytes()) != binding['sha256']:
            raise ValueError('Strong II source contract drifted: ' + binding['path'])
    return proof

def metadata(root=ROOT, *, at=None):
    if at is None:
        at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    assert_sources(root)
    work = json.loads(raw(root, WORK / 'work.json'))
    acquisition = json.loads(raw(root, ACQUISITION_PATH))
    state = json.loads(raw(root, WORK / 'state.json'))
    if work['work_id'] != WORK_ID or acquisition['acquisition_id'] != ACQUISITION or acquisition['edition_id'] != EDITION:
        raise ValueError('Existing Strong II catalog identity differs')
    work = deepcopy(work)
    editions = [e for f in work['textual_forms'] if f['textual_form_id'] == FORM for e in f['editions'] if e['edition_id'] == EDITION]
    if len(editions) != 1:
        raise ValueError('Existing Strong II edition is not unique')
    edition = editions[0]
    if edition.get('category') not in (None, 'prose'):
        raise ValueError('Existing Strong II category conflicts')
    edition['category'] = 'prose'
    target = [t for t in state['targets'] if t['target_id'] == EDITION and t['target_type'] == 'edition']
    if len(target) != 1 or target[0]['stage'] != 'acquired':
        raise ValueError('Existing Strong II acquired edition preimage differs')
    target[0].update(stage='accepted', updated_at=at, reason=PROMOTED_MASTER_REASON)
    target[0]['evidence'] += [(EDITION_PATH / 'master.tei.xml').as_posix(), (EDITION_PATH / 'acceptance.json').as_posix(), (EVIDENCE / 'source-proof-final-v1.json').as_posix()]
    for kind, value in (('work', work), ('acquisition', acquisition), ('state', state)):
        validate_record(kind, value, context='Existing Strong II proposed ' + kind)
    return work, acquisition, state

def bound_header(root=ROOT):
    proof = assert_sources(root)
    original = io_path(PACKAGE / 'content.tei.xml').read_bytes()
    acquisition = json.loads(raw(root, ACQUISITION_PATH))
    members = acquisition['retained_files']
    if len(members) != 1 or members[0]['path'] != 'raw/gutenberg/pg44555.txt':
        raise ValueError('Strong II exact original acquired witness differs')
    member = members[0]
    source = dict(source_path=member['path'], source_sha256=member['sha256'], source_bytes=member['bytes'], source_scope=member['scope'])
    if len(raw(root, member['path'])) != member['bytes'] or sha(raw(root, member['path'])) != member['sha256']:
        raise ValueError('Strong II raw witness drifted')
    bound = bind_reviewed_header(original, expected_sha256=proof['packages']['strict-baseline']['members']['content.tei.xml']['sha256'], identity=identity(), source=source, source_url=acquisition['url'], declared_scope=SCOPE, revision=REVISION, historical_source_description={'pointers': [], 'sha256': []})
    if bound.count(OLD_STATUS.encode()) != 2:
        raise ValueError('Strong II original and administrative status bindings differ')
    publication = b'<publicationStmt><p>' + OLD_STATUS.encode() + b'</p></publicationStmt>'
    replacement = b'<publicationStmt><p>' + NEW_STATUS.encode() + b'</p></publicationStmt>'
    if bound.count(publication) != 1:
        raise ValueError('Strong II publication statement exact preimage differs')
    bound = bound.replace(publication, replacement, 1)
    tree = etree.fromstring(bound)
    old_tree = etree.fromstring(original)
    binding = tree.find(N+'teiHeader').find(N+'fileDesc').find(N+'sourceDesc')[-1]
    revision = tree.find(N+'teiHeader').find(N+'revisionDesc')
    bibl_bytes = etree.tostring(binding, with_tail=False)
    revision_bytes = etree.tostring(revision, with_tail=False)
    restored = bound.replace(bibl_bytes, b'', 1).replace(revision_bytes, b'', 1).replace(replacement, publication, 1)
    if restored != original:
        raise ValueError('Strong II whole original header/document byte inverse failed')
    if bound.split(b'</teiHeader>', 1)[1] != original.split(b'</teiHeader>', 1)[1] or fields(tree.find(N+'text')) != fields(old_tree.find(N+'text')):
        raise ValueError('Strong II accepted header changed actual complete text')
    expected = dict(identity(), source_sha256=source['source_sha256'], source_bytes=str(source['source_bytes']), representation_revision=REVISION['id'], sha256=source['source_sha256'])
    actual = {node.get('type'): node.text for node in binding.iter(N+'idno')}
    if actual != expected or list(actual) != list(expected):
        raise ValueError('Strong II ordered header identity differs')
    delta = dict(status='header-only-proposal-not-installed', source_tei_sha256=sha(original), bound_tei_sha256=sha(bound), identity=identity(), source=source, declared_scope=SCOPE, representation_revision=REVISION, ordered_binding_fields=list(expected), original_header_document_byte_inverse=True, complete_text_bytes_unchanged=True, complete_text_fields_unchanged=True, original_publication_assertion=OLD_STATUS, new_publication_statement=NEW_STATUS, historical_publication_assertion_location='teiHeader/fileDesc/sourceDesc/bibl[@type="ocd-acceptance-binding"]/note[@type="source-scope"]', human_verification='not_recorded', rights='unresolved', publication='not_ready')
    return bound, delta

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--draft', type=Path, required=True)
    args = parser.parse_args()
    draft = resolve_path(args.draft)
    if draft.exists() or draft.parent != resolve_path(ROOT / LOG) or not draft.name.startswith('acceptance-header-draft-'):
        raise ValueError('Fresh exact Strong II task-local draft required')
    bound, delta = bound_header()
    work, acquisition, state = metadata()
    io_path(draft).mkdir()
    candidate = draft / 'candidate.tei.xml'
    io_path(candidate).write_bytes(bound)
    errors = validate_file(candidate)
    if errors:
        raise ValueError('Strong II bound header P5 failed: ' + str(errors))
    delta['p5'] = 'pass'
    for name, value in (('header-delta.json', delta), ('work.json', work), ('acquisition.json', acquisition), ('state.json', state)):
        io_path(draft / name).write_bytes(enc(value))
    print(json.dumps({'status': 'proposal-only', 'directory': draft.as_posix(), 'files': {p.name: sha(p.read_bytes()) for p in io_path(draft).iterdir() if p.is_file()}}, sort_keys=True))

if __name__ == '__main__':
    main()
