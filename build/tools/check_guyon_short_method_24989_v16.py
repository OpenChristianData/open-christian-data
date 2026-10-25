from pathlib import Path
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
import copy
import hashlib
import importlib.util
import json
import shutil
import sys
from lxml import etree

ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT))
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

BASE = Path(r'D:\Library\Open Christian Data\candidate-reviews\guyon-pg24989-envelope-v16-candidate-20261003-v1\package')
REPLAY = Path(r'D:\Library\Open Christian Data\candidate-reviews\guyon-pg24989-envelope-v16-replay-20261003-v1\package')
HISTORICAL = Path(r'D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925\held-pg-24989-hierarchy-v12-20260928-luna\package')
MANIFEST = ROOT / 'sources/manifest-acquisitions/guyon-short-method-pg24989-v16/source-manifest.json'
ORACLE = ROOT / 'build/tei/guyon_short_method_24989_v16_oracle.py'
NS = {'t': 'http://www.tei-c.org/ns/1.0', 'xml': 'http://www.w3.org/XML/1998/namespace'}
T = '{' + NS['t'] + '}'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
def sha(data): return hashlib.sha256(data).hexdigest()
def canonical(value): return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
def one(tree, xpath):
    values = tree.xpath(xpath, namespaces=NS)
    if not values: raise AssertionError('Required observed source feature absent: ' + xpath)
    return values[0]
def new_element(name, **attributes): return etree.Element(T + name, **attributes)
source = SourceManifest.load(MANIFEST, repository_root=ROOT)
spec = importlib.util.spec_from_file_location('_guyon_v16_challenge_oracle', ORACLE)
assert spec is not None and spec.loader is not None
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
baseline = CandidatePackage.load(BASE)
replay = CandidatePackage.load(REPLAY)
baseline_result = observer._oracle(source, baseline)
pair = []
for name in baseline.member_names:
    left, right = baseline.member_bytes(name), replay.member_bytes(name)
    assert left == right, 'Clean replay mismatch: ' + name
    pair.append({'name': name, 'bytes': len(left), 'sha256': sha(left), 'exact_equal': True})
assert (BASE.parent / 'validation.json').read_bytes() == (REPLAY.parent / 'validation.json').read_bytes()
current_tree = etree.fromstring(baseline.member_bytes('content.tei.xml'))
historical_tree = etree.fromstring((HISTORICAL / 'content.tei.xml').read_bytes())
current_text = etree.tostring(current_tree.find(T + 'text'), method='c14n')
historical_text = etree.tostring(historical_tree.find(T + 'text'), method='c14n')
assert current_text == historical_text, 'Historical complete body changed'

def body_text(tree, account, files):
    node = one(tree, './t:text/t:body//t:p[text()]')
    node.text = (node.text or '') + ' MUTATED'
def heading_text(tree, account, files):
    node = one(tree, './t:text/t:body//t:head[text()]')
    node.text = (node.text or '') + ' MUTATED'
def heading_id(tree, account, files):
    one(tree, './t:text/t:body//t:div[@type="source-section"]').set(XML_ID, 'mutated-heading-id')
def heading_role(tree, account, files):
    one(tree, './t:text/t:body//t:div[@type="source-section"]').set('subtype', 'h6')
def link_target(tree, account, files):
    one(tree, './t:text/t:body//t:ref[@target]').set('target', 'https://example.invalid/mutated')
def footnote_attachment(tree, account, files):
    node = one(tree, './t:text/t:body//t:ref[@xml:id="fna.1"]')
    assert node.get('target') == '#fn.1'
    assert tree.xpath('./t:text/t:body//*[@xml:id="fn.2"]', namespaces=NS)
    node.set('target', '#fn.2')
def table_span(tree, account, files):
    one(tree, './t:text/t:body//t:cell').set('cols', '99')
def carrier_id(tree, account, files):
    one(tree, './t:text/t:body//t:p[@xml:id]').set(XML_ID, 'mutated-carrier-id')
def carrier_tail(tree, account, files):
    node = one(tree, './t:text/t:body//t:ab[@type="source-tail-text"]')
    node.text = (node.text or '') + ' MUTATED'
def source_style(tree, account, files):
    node = one(tree, './t:text/t:body//*[@rend]')
    node.set('rend', 'mutated-source-style')
def invented_body(tree, account, files):
    node = new_element('div', type='source-carrier', n='invented', **{XML_ID: 'source-carrier-invented'})
    etree.SubElement(node, T + 'p').text = 'Invented body prose'
    one(tree, './t:text/t:body/t:div').append(node)
def body_order(tree, account, files):
    node = one(tree, './t:text/t:body/t:div')
    assert len(node) > 1
    node.insert(0, node[1])
def title_identity(tree, account, files):
    one(tree, './t:teiHeader/t:fileDesc/t:titleStmt/t:title').text = 'Invented second work'
def opening_source(tree, account, files):
    one(tree, './t:teiHeader/t:fileDesc/t:sourceDesc/t:p').text += ' Invented source claim'
def invented_source(tree, account, files):
    node = new_element('p'); node.text = 'Invented source prose'
    one(tree, './t:teiHeader/t:fileDesc/t:sourceDesc').append(node)
def metadata_paragraph_text(tree, account, files):
    one(tree, './t:teiHeader/t:fileDesc/t:sourceDesc/t:p[t:seg[@type="source-head-metadata"]]').text = 'Invented metadata prose'
def head_value(name, attribute):
    def mutate(tree, account, files):
        rows = account['head_envelope']['children']
        row = next(r for r in rows if [ 'name', name ] in r['attributes'] or [ 'property', name ] in r['attributes'] or (name == 'isFormatOf' and ['rel', 'dcterms.isFormatOf'] in r['attributes']))
        pair = next(a for a in row['attributes'] if a[0] == attribute)
        pair[1] += '/mutated' if pair[1].startswith(('https://', 'http://')) else ' MUTATED'
        field = one(tree, './t:teiHeader/t:fileDesc/t:sourceDesc/t:p/t:seg[@n="' + str(row['position']) + '"]/t:seg[@type="source-head-attribute" and @n="' + attribute + '"]')
        if len(field):
            field[0].set('target', pair[1]); field[0].text = pair[1]
        else: field.text = attribute + '=' + pair[1]
    return mutate
def head_omit(tree, account, files): account['head_envelope']['children'].pop(0)
def head_order(tree, account, files):
    rows = account['head_envelope']['children']; rows[0], rows[1] = rows[1], rows[0]
def head_extra_key(tree, account, files): account['head_envelope']['children'][0]['rights_cleared'] = True
def head_root_key(tree, account, files): account['head_envelope']['ownership'] = 'invented'
def stylesheet_text(tree, account, files):
    next(r for r in account['head_envelope']['children'] if r['tag'] == 'style')['text'] += ' MUTATED'
def stylesheet_disposition(tree, account, files):
    next(r for r in account['head_envelope']['children'] if r['tag'] == 'style')['disposition'] = 'discarded without accounting'
def head_uri(tree, account, files):
    one(tree, './t:teiHeader/t:fileDesc/t:sourceDesc/t:p/t:seg[@type="source-head-metadata"]//t:ref').set('target', 'https://example.invalid/mutated')
def cover_wording(tree, account, files):
    account['head_envelope']['support']['visual_observation']['visible_source_text'][1]['text'] = 'Invented creator'
    one(tree, './t:teiHeader/t:fileDesc/t:sourceDesc/t:p/t:seg[@type="source-support-observation"]/t:seg[@n="2"]').text = 'cover creator line: Invented creator'
def cover_omit(tree, account, files): account['head_envelope']['support'].pop('visual_observation')
def cover_receipt(tree, account, files): account['head_envelope']['support']['visual_observation']['receipt_sha256'] = '0' * 64
def cover_binary(tree, account, files): account['head_envelope']['support']['sha256'] = '0' * 64
def cover_role(tree, account, files): account['head_envelope']['support']['role'] = 'invented body illustration'
def cover_duplicate(tree, account, files):
    description = one(tree, './t:teiHeader/t:fileDesc/t:sourceDesc')
    description.append(copy.deepcopy(description[-1]))
def publication_invention(tree, account, files):
    one(tree, './t:teiHeader/t:fileDesc/t:publicationStmt/t:p').text = 'Human accepted and rights cleared for publication.'
def header_invention(tree, account, files):
    statement = new_element('notesStmt')
    note = etree.SubElement(statement, T + 'note')
    note.text = 'Human accepted and rights cleared for publication.'
    one(tree, './t:teiHeader/t:fileDesc').insert(2, statement)
def empty_title_disposition(tree, account, files): account['empty_html_attribute_dispositions'][0]['value'] = 'Invented tooltip'
def mapping_version(tree, account, files): account['mapping'] = 'One top-level titled work. Guyon v13 stale mapping.'
def provenance_status(tree, account, files):
    value = json.loads(files['provenance.json']); value['rights_clearance'] = 'cleared'; files['provenance.json'] = canonical(value)
def notice_text(tree, account, files): files['README.source.md'] += b'\nInvented clearance statement.\n'
def unresolved_omit(tree, account, files): files['unresolved.jsonl'] = b''
cases = [
    ('body-text', body_text, 'source carrier text mutation'),
    ('heading-text', heading_text, 'source heading text/order mutation'),
    ('heading-id', heading_id, 'source heading identity mutation'),
    ('heading-role', heading_role, 'source heading hierarchy mutation'),
    ('link-target', link_target, 'source link target mutation'),
    ('footnote-existing-wrong-referent', footnote_attachment, 'source link target mutation'),
    ('table-span', table_span, 'source table span mutation'),
    ('carrier-id', carrier_id, 'source ID mutation'),
    ('carrier-tail', carrier_tail, 'source nonwhite tail text mutation'),
    ('source-style', source_style, 'mutation'),
    ('invented-body', invented_body, 'source child count/invention mutation'),
    ('body-order', body_order, 'mutation'),
    ('title-identity', title_identity, 'candidate title/contributor role mismatch'),
    ('source-opening', opening_source, 'Guyon original source description opening differs'),
    ('invented-source-paragraph', invented_source, 'Guyon complete source description carrier set differs'),
    ('invented-metadata-prose', metadata_paragraph_text, 'Guyon readable metadata paragraph envelope differs'),
    ('head-dc-title', head_value('dc.title', 'content'), 'Guyon head ledger source identity/attributes/text differs'),
    ('head-dc-creator', head_value('dc.creator', 'content'), 'Guyon head ledger source identity/attributes/text differs'),
    ('head-dc-rights', head_value('dc.rights', 'content'), 'Guyon head ledger source identity/attributes/text differs'),
    ('head-dc-language', head_value('dc.language', 'content'), 'Guyon head ledger source identity/attributes/text differs'),
    ('head-dcterms-source', head_value('dcterms.source', 'content'), 'Guyon head ledger source identity/attributes/text differs'),
    ('head-og-image', head_value('og:image', 'content'), 'Guyon head ledger source identity/attributes/text differs'),
    ('head-omission', head_omit, 'Guyon head accounting contract/count differs'),
    ('head-order', head_order, 'Guyon head ledger source identity/attributes/text differs'),
    ('head-invented-row-rights', head_extra_key, 'Guyon head ledger fields omitted or invented'),
    ('head-invented-root-ownership', head_root_key, 'Guyon head accounting fields omitted or invented'),
    ('stylesheet-source-text', stylesheet_text, 'Guyon head ledger source identity/attributes/text differs'),
    ('stylesheet-disposition', stylesheet_disposition, 'Guyon stylesheet disposition differs'),
    ('head-uri-target', head_uri, 'Guyon source metadata URI target differs'),
    ('cover-creator-wording', cover_wording, 'Guyon readable cover observation text/order differs'),
    ('cover-observation-omission', cover_omit, 'Guyon retained binary support omitted or changed'),
    ('cover-observation-receipt', cover_receipt, 'Guyon retained binary support omitted or changed'),
    ('cover-binary-identity', cover_binary, 'Guyon retained binary support omitted or changed'),
    ('cover-invented-placement', cover_role, 'Guyon retained binary support omitted or changed'),
    ('cover-duplicate', cover_duplicate, 'Guyon complete source description carrier set differs'),
    ('publication-status-invention', publication_invention, 'Guyon candidate publication status invented or altered'),
    ('header-status-invention', header_invention, 'Guyon header description invented or altered'),
    ('empty-title-invention', empty_title_disposition, 'candidate source accounting mismatch'),
    ('stale-mapping', mapping_version, 'candidate source accounting mismatch'),
    ('provenance-rights-invention', provenance_status, 'candidate source notice or provenance mismatch'),
    ('notice-invention', notice_text, 'candidate source notice or provenance mismatch'),
    ('unresolved-omission', unresolved_omit, 'candidate unresolved status mismatch'),
]
results = []
harness_errors = []
with TemporaryDirectory(prefix='ocd-guyon-v16-semantic-') as temporary:
    for label, mutate, intended_reason in cases:
        destination = Path(temporary) / label
        destination.mkdir()
        files = {name: baseline.member_bytes(name) for name in baseline.member_names}
        tree = etree.fromstring(files['content.tei.xml'])
        account = json.loads(files['source-accountability.json'])
        mutate(tree, account, files)
        files['content.tei.xml'] = etree.tostring(tree, encoding='UTF-8', xml_declaration=True)
        account['tei_sha256'] = sha(files['content.tei.xml'])
        files['source-accountability.json'] = canonical(account)
        inventory = json.loads(files['manifest.json'])
        for member in inventory['members']:
            data = files[member['name']]
            member.update(bytes=len(data), sha256=sha(data))
        files['manifest.json'] = canonical(inventory)
        changed = [name for name, data in files.items() if data != baseline.member_bytes(name)]
        assert changed and 'manifest.json' in changed, label + ' did not alter/reseal bytes'
        for name, data in files.items(): (destination / name).write_bytes(data)
        mutated = CandidatePackage.load(destination)
        mutated.verify_integrity()
        schema = observer.compiled_schema()
        if not schema.validate(tree):
            harness_errors.append({'case': label, 'error': 'Mutant must be P5-valid before semantic oracle check', 'schema_findings': str(schema.error_log[:2])})
            continue
        try:
            observer._oracle(source, mutated)
        except ValueError as error:
            reason = str(error)
            if intended_reason not in reason:
                harness_errors.append({'case': label, 'error': 'Unexpected oracle reason', 'actual': reason, 'expected': intended_reason})
                continue
            assert 'bytes drifted' not in reason, 'Integrity-only rejection is not semantic proof'
            results.append({'case': label, 'status': 'pass', 'package_integrity_pass': True, 'candidate_manifest_sha256': mutated.sha256, 'changed_members': changed, 'rejection': reason, 'expected_reason': intended_reason})
        else: harness_errors.append({'case': label, 'error': 'Oracle accepted deliberate semantic damage'})
if harness_errors:
    print(json.dumps({'status': 'fail', 'passed_cases': len(results), 'harness_errors': harness_errors}, ensure_ascii=True, indent=2))
    raise AssertionError('Semantic matrix has unresolved failures; no pass receipt written')
record = {'contract': 'ocd-guyon-v16-clean-replay-and-semantic-challenges-v1', 'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'pass', 'source_manifest_sha256': sha(MANIFEST.read_bytes()), 'oracle_sha256': sha(ORACLE.read_bytes()), 'baseline_candidate_sha256': baseline.sha256, 'baseline_oracle_result': baseline_result, 'baseline_path': str(BASE), 'replay_path': str(REPLAY), 'clean_replay_members': pair, 'validation_sidecar_exact_equal': True, 'validation_sidecar_sha256': sha((BASE.parent / 'validation.json').read_bytes()), 'historical_body_c14n_sha256': sha(current_text), 'historical_body_exact_c14n_equal': True, 'mutation_count': len(results), 'mutations': results, 'source_bytes_changed': False, 'canonical_library_changed': False, 'method': 'Each case changed source-relevant candidate content and resealed member lengths/hashes; CandidatePackage integrity passed before independent semantic oracle rejection. Temporary mutation packages removed by TemporaryDirectory.'}
p = ROOT / 'plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/GUYON_PG24989_V16_REPLAY_AND_SEMANTIC_CHALLENGES_20261003.json'
assert not p.exists(), 'Refuse overwrite'
record['challenge_tool_path'] = Path(__file__).resolve().relative_to(ROOT).as_posix()
record['challenge_tool_sha256'] = sha(Path(__file__).read_bytes())
record['predecessor_harness_failures'] = ['Sandbox could not read host-generated D: packages; exact authorized host execution used.', 'p[text()] selected mixed content with direct .text=None; mutation now explicitly changes direct text.', 'First tail mutation placed nonwhite text outside a block and correctly failed P5; corrected case changes the real source-tail-text ab and requires every mutant to pass P5 before semantic rejection.']
with p.open('xb') as handle: handle.write((json.dumps(record, ensure_ascii=True, indent=2) + '\n').encode('utf-8'))
print('PASS', len(results), 'semantic mutations; six-file exact clean replay; historical full body unchanged')
print('RECEIPT', str(p.relative_to(ROOT)), sha(p.read_bytes()))
