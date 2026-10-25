"""Independent closed inverse of the declared generated-scaffolding aliases.

Does not import the producer. Full original source-oracle checks are applied to
the inverse tree by the caller, after exact conservation of the frozen mapping.
"""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import calvins_institutes_oracle as original_source_oracle
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

NS = 'http://www.tei-c.org/ns/1.0'
ID = '{http://www.w3.org/XML/1998/namespace}id'
ORACLE_ID='ocd-calvin-complete-independent-native-envelope-oracle'
ORACLE_VERSION='1'


def expected_header(volume=None):
    # Independent fixed bibliographic policy, grounded in the retained mapper's
    # separately source-checked title/translator/imprint/conflict evidence.
    e = lambda name: etree.Element('{'+NS+'}'+name)
    head=e('teiHeader');desc=e('fileDesc');head.append(desc)
    title=e('titleStmt');desc.append(title)
    item=e('title');item.text='Institutes of the Christian Religion'+('' if volume is None else ', Volume '+str(volume));title.append(item)
    item=e('author');item.text='John Calvin';title.append(item)
    resp=e('respStmt');title.append(resp)
    item=e('resp');item.text='Translation from Latin, collated with the author’s last French edition';resp.append(item)
    item=e('name');item.text='John Allen';resp.append(item)
    pub=e('publicationStmt');desc.append(pub);item=e('p');item.text='Retained source reconstruction for technical review; no publication authorization.';pub.append(item)
    source=e('sourceDesc');desc.append(source);bibl=e('bibl');source.append(bibl)
    for name, value in [('title','Sixth American Edition, Revised and Corrected, in Two Volumes'),('publisher','Presbyterian Board of Publication'),('pubPlace','Philadelphia'),('note',
        'Project Gutenberg retained electronic witnesses 45001 and 64392. Volume I title-page year 1813 and the appended S. T. Livermore Scripture-index year 1852 are retained source labels; their relation remains unresolved. United States public-domain claims, jurisdiction warning, and Gutenberg license and trademark terms are distinct; worldwide status remains unresolved.'+('' if volume is None else ' Physical volume '+str(volume)+'; original text-envelope n='+str(volume)+'.'))]:
        item=e(name);item.text=value;bibl.append(item)
    return head


def compare_tree(a, b, label):
    if a.tag!=b.tag or dict(a.attrib)!=dict(b.attrib) or a.text!=b.text or a.tail!=b.tail or len(a)!=len(b):
        raise ValueError(label+' exact tags/attributes/text/tails/hierarchy differ')
    for ordinal,(x,y) in enumerate(zip(a,b,strict=True)):
        compare_tree(x,y,label+'/'+str(ordinal))


def inverse_and_compare(payload, original_payload, inventory_payload):
    parse = lambda b: etree.fromstring(b, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    root, original = parse(payload), parse(original_payload)
    inventory = json.loads(inventory_payload)
    if inventory.get('contract') != 'ocd-calvin-reversible-native-envelope-v1' or inventory.get('original_tei_sha256') != sha256(original_payload).hexdigest():
        raise ValueError('inverse mapping original authority mismatch')
    if root.tag != '{'+NS+'}teiCorpus' or dict(root.attrib) != dict(original.attrib) or [x.tag for x in root] != ['{'+NS+'}'+x for x in ['teiHeader', 'TEI', 'TEI']] or root.text is not None or root.tail is not None:
        raise ValueError('physical corpus envelope mismatch')
    compare_tree(root[0],expected_header(),'source-backed corpus header')
    if not isinstance(inventory.get('physical_volumes'),list) or len(inventory['physical_volumes'])!=2:
        raise ValueError('physical volume inventory must contain exactly two entries')
    originals = original.findall('{'+NS+'}text/{'+NS+'}group/{'+NS+'}text')
    indexed = {}
    for change in inventory['aliases']:
        key = (change['volume'], tuple(change['body_child_path']))
        if key in indexed:
            raise ValueError('duplicate alias position')
        indexed[key] = change
    consumed = set()
    for volume, member in enumerate(list(root)[1:], 1):
        if dict(member.attrib) != {ID: 'calvin-physical-volume-'+str(volume)} or [x.tag for x in member] != ['{'+NS+'}'+x for x in ['teiHeader','text']] or member.text is not None or member.tail is not None:
            raise ValueError('physical member order or identity mismatch')
        compare_tree(member[0],expected_header(volume),'source-backed volume header '+str(volume))
        text = member[1]
        if dict(text.attrib) != {ID: 'calvin-volume-'+str(volume)} or len(text) != 1 or text[0].tag != '{'+NS+'}body' or text.text != originals[volume-1].text or text.tail != originals[volume-1].tail:
            raise ValueError('physical text envelope mismatch')
        body = deepcopy(text[0])
        def restore(node, path):
            key = (volume, tuple(path))
            change = indexed.get(key)
            name = etree.QName(node).localname
            if change is not None:
                if node.tag != '{'+NS+'}'+change['new_tag'] or dict(node.attrib) != change['new_attributes']:
                    raise ValueError('reversible alias changed at '+str(key))
                old = change['old_attributes']
                old_tag = change['old_tag']
                expected = dict(old)
                new_tag = old_tag
                if old_tag == 'ab':
                    if 'type' not in old or set(old) - {ID, 'type'}:
                        raise ValueError('invalid inverse block original shape')
                    expected['subtype'] = expected['type']
                    expected['type'] = 'source-whitespace' if not ''.join(node.itertext()).strip() else 'source-block'
                elif old_tag == 'c':
                    if old != {'type': 'emphasis-delimiter'} or node.text != '_' or len(node):
                        raise ValueError('literal underscore inverse mismatch')
                    new_tag = 'seg'
                elif old_tag == 'div':
                    if old.get('type') != 'book' or old.get('part') not in {'I', 'F', 'N'} or 'ana' in old:
                        raise ValueError('book part inverse mismatch')
                    expected['ana'] = 'source-part:'+expected.pop('part')
                elif old_tag == 'table':
                    if old.get('cols') != '4' or old.get('rows') != str(len(node)) or 'ana' in old:
                        raise ValueError('table dimension inverse mismatch')
                    expected['ana'] = 'source-rows:'+expected.pop('rows')+' source-cols:'+expected.pop('cols')
                elif old_tag == 'row':
                    if old.get('role') != 'data' or 'ana' in old:
                        raise ValueError('row role inverse mismatch')
                    expected['ana'] = 'source-role:'+expected.pop('role')
                else:
                    raise ValueError('undeclared inverse alias kind')
                if expected != dict(node.attrib) or new_tag != name:
                    raise ValueError('inverse alias formula mismatch')
                node.tag = '{'+NS+'}'+old_tag
                node.attrib.clear()
                node.attrib.update(old)
                consumed.add(key)
            for ordinal, child in enumerate(node):
                restore(child, path+[ordinal])
        restore(body, [])
        source_body = originals[volume-1][0]
        def compare(a, b, position=()):
            if a.tag != b.tag or dict(a.attrib) != dict(b.attrib) or a.text != b.text or a.tail != b.tail or len(a) != len(b):
                raise ValueError('complete original body differs at '+str((volume, position)))
            for ordinal, (x, y) in enumerate(zip(a, b, strict=True)):
                compare(x, y, position+(ordinal,))
        compare(body, source_body)
        actual = sha256(etree.tostring(source_body, method='c14n', exclusive=True)).hexdigest()
        if inventory['physical_volumes'][volume-1] != {'volume': volume, 'source_body_sha256': actual}:
            raise ValueError('original body fingerprint mismatch')
        originals[volume-1].replace(source_body, body)
    if consumed != set(indexed):
        raise ValueError('unused inverse alias evidence')
    return etree.tostring(original, encoding='UTF-8', xml_declaration=True)


def closure_sha(root):
    policy={'forbidden_import_prefixes':['build.tei.calvin_institutes_complete_native','build.tei.calvins_institutes_reconstruction']}
    return original_source_oracle._closure_digest(root,policy,Path(__file__).resolve())


def check(manifest, payload, inventory):
    manifest.verify()
    baseline_manifest=SourceManifest.load(manifest.authority_path('baseline-source-manifest'),repository_root=manifest.repository_root)
    baseline=CandidatePackage.load(manifest.authority_path('baseline-package-manifest').parent)
    baseline.verify_integrity()
    profile=json.loads(manifest.authority_path('profile').read_bytes())
    if baseline.sha256!=profile['baseline_package_sha256'] or sha256(baseline.member_bytes('content.tei.xml')).hexdigest()!=profile['baseline_tei_sha256']:
        raise ValueError('sealed complete source mapping binding differs')
    member_set=json.loads(manifest.authority_path('primary-source').read_bytes())
    expected_members=profile['retained_members']
    if member_set.get('contract')!='ocd-retained-source-member-set-v1' or member_set.get('members')!=expected_members or member_set.get('scope')!=profile['source_scope'] or member_set.get('acquisition_id')!=profile['acquisition_id'] or member_set.get('edition_id')!=profile['edition_id']:
        raise ValueError('physical source member-set association differs')
    for position,name in enumerate(('retained-volume-1','retained-volume-2'),1):
        a=original_source_oracle._authority(baseline_manifest,name)
        expected=expected_members[position-1]
        if {k:a[k] for k in ('path','bytes','sha256')}!={k:expected[k] for k in ('path','bytes','sha256')} or expected['position']!=position:
            raise ValueError('full source pair/order differs from independently reviewed source mapping')
    restored=inverse_and_compare(payload,baseline.member_bytes('content.tei.xml'),inventory)
    class IndependentInversePackage:
        manifest=baseline.manifest
        sha256=baseline.sha256
        def verify_integrity(self):baseline.verify_integrity()
        def member_bytes(self,name):return restored if name=='content.tei.xml' else baseline.member_bytes(name)
    # The old independent oracle retains every original shape, source, byte,
    # line, note, index, rights, accounting and runtime check. None are removed.
    original_source_oracle._oracle(baseline_manifest,IndependentInversePackage())
    return dict(source_lines=69897,source_bytes=4060187,physical_volumes=2,logical_books=4,chapters=80,
        notes=3506,attached_reference_occurrences=3505,tables=769,rows=3972,cells=15888,
        underscore_delimiters=1156,aliases=len(json.loads(inventory)['aliases']),source_sha256=sha256(manifest.authority_path('primary-source').read_bytes()).hexdigest())


def _oracle(manifest,candidate):
    manifest.verify();candidate.verify_integrity()
    baseline=CandidatePackage.load(manifest.authority_path('baseline-package-manifest').parent)
    accounting=json.loads(candidate.member_bytes('source-accountability.json'))
    inventory=accounting.pop('native_envelope')
    encode=lambda x:(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
    if encode(accounting)!=baseline.member_bytes('source-accountability.json'):
        raise ValueError('complete original line/accountability evidence differs')
    check(manifest,candidate.member_bytes('content.tei.xml'),encode(inventory))
    expected=dict(contract='ocd-calvin-complete-native-provenance-v1',status='nonaccepted',baseline_package_sha256=baseline.sha256,
        baseline_tei_sha256=sha256(baseline.member_bytes('content.tei.xml')).hexdigest(),converter=dict(manifest.record['converter']),
        authorities={a['name']:{k:a[k] for k in ('path','role','bytes','sha256')} for a in manifest.record['authorities']},
        source_interpretation='none; exact reversible aliases of generated scaffolding; complete source text retained')
    if candidate.member_bytes('provenance.json')!=encode(expected) or candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes() or candidate.member_bytes('unresolved.jsonl')!=baseline.member_bytes('unresolved.jsonl'):
        raise ValueError('new envelope provenance/rights/questions differ')
    facts=MechanicalFacts(validator_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),validator_import_closure_sha256=closure_sha(manifest.repository_root),source_sha256=sha256(manifest.authority_path('primary-source').read_bytes()).hexdigest(),profile_sha256=sha256(manifest.authority_path('profile').read_bytes()).hexdigest(),package_schema_sha256=manifest.record['package_schema']['sha256'],xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path('validation-policy').read_bytes()).hexdigest(),findings=())
    return verify_mechanical_facts(manifest,candidate,facts=facts).as_record()


_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
