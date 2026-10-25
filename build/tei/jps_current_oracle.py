"""Independent complete source oracle with strictly bounded header/book-label renewal."""
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from xml.sax.saxutils import escape
from lxml import etree
from build.tei.jps_oracle import check_content

ORACLE_ID = 'ocd-jps-independent-complete-retained-current-v1'
ORACLE_VERSION = '1'
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'

def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode()

def closure_sha(root):
    paths = ['build/tei/jps_current_oracle.py', 'build/tei/jps_oracle.py', 'ocd_kernel/reconstruction/contract.py',
             'ocd_kernel/reconstruction/verifier.py', 'ocd_kernel/reconstruction/__init__.py']
    return sha256(canonical([dict(path=p, sha256=sha256((root/p).read_bytes()).hexdigest()) for p in sorted(paths)])).hexdigest()

def fingerprint(node):
    return node.tag, tuple(node.attrib.items()), node.text, node.tail, tuple(fingerprint(c) for c in node)

def check(manifest, raw):
    manifest.verify()
    profile = json.loads(manifest.authority_path('profile').read_bytes())
    source = manifest.authority_path('retained-text').read_bytes()
    original = manifest.authority_path('historical-native-candidate').read_bytes()
    doc = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    if doc.tag != NS+'TEI' or dict(doc.attrib) != {XML+'id': 'jps'} or [n.tag for n in doc] != [NS+'teiHeader', NS+'text']:
        raise ValueError('Complete JPS namespace/envelope differs')
    if fingerprint(doc[0]) != fingerprint(etree.fromstring(profile['header_xml'].encode())):
        raise ValueError('Current qualified header differs')
    books = doc.findall(NS+'text/'+NS+'body/'+NS+'div')
    source_books = json.loads(source)['books']
    if len(books) != 39 or len(profile['book_label_revisions']) != 39:
        raise ValueError('Complete book cardinality differs')
    restored = raw
    for index, (book, expected) in enumerate(zip(books, source_books), 1):
        name = expected['name']
        row = dict(source_pointer=f'/books/{index-1}/name', old_n=str(index), source_name=name, id=f'jps-b{index}')
        if profile['book_label_revisions'][index-1] != row or dict(book.attrib) != {'type':'book', 'n':name, XML+'id':row['id']}:
            raise ValueError('Literal source-backed book label/identity differs')
        new = f'<div type="book" n="{escape(name, {chr(34): "&quot;"})}" xml:id="{row["id"]}">'.encode()
        old = f'<div type="book" n="{index}" xml:id="{row["id"]}">'.encode()
        if restored.count(new) != 1:
            raise ValueError('Exact book label serialization differs')
        restored = restored.replace(new, old)
    start = restored.index(b'<teiHeader'); end = restored.index(b'</teiHeader>') + len(b'</teiHeader>')
    old_start = original.index(b'<teiHeader>'); old_end = original.index(b'</teiHeader>') + len(b'</teiHeader>')
    restored = restored[:start] + original[old_start:old_end] + restored[end:]
    if restored != original:
        raise ValueError('Restoring only header and 39 labels does not recover exact whole historical TEI')
    facts = check_content(source, restored, manifest.authority_path('historical-accountability').read_bytes())
    etree.XMLSchema(etree.parse(str(manifest.authority_path('tei-p5-xsd')))).assertValid(doc)
    return dict(status='pass', source_counts=facts, books=39, chapters=929, verses=23213, empty_text=19,
                literal_book_labels=39, exact_original_byte_restoration=True, p5='pass',
                independent_source_mapping='Original independent JPS oracle verifies full JSON/TEI/ledger after strictly checked source-label and header restoration. Producer not imported.')

def _oracle(manifest, candidate):
    candidate.verify_integrity()
    profile = json.loads(manifest.authority_path('profile').read_bytes())
    if candidate.manifest['source_manifest']['sha256'] != manifest.sha256 or manifest.record['validator']['import_closure_sha256'] != closure_sha(manifest.repository_root):
        raise ValueError('Current source manifest/closure differs')
    check(manifest, candidate.member_bytes('content.tei.xml'))
    if candidate.member_bytes('source-accountability.json') != manifest.authority_path('historical-accountability').read_bytes():
        raise ValueError('Full source accounting differs')
    if candidate.member_bytes('README.source.md') != manifest.authority_path('source-readme').read_bytes() or [json.loads(x) for x in candidate.member_bytes('unresolved.jsonl').splitlines()] != profile['questions']:
        raise ValueError('Visible credit/unresolved ledger differs')
    provenance = json.loads(candidate.member_bytes('provenance.json'))
    if provenance != dict(work_id='jps', scope=profile['scope'], source_manifest_sha256=manifest.sha256,
            historical_candidate_sha256=sha256(manifest.authority_path('historical-native-candidate').read_bytes()).hexdigest(),
            book_label_revisions=profile['book_label_revisions'], status='nonaccepted'):
        raise ValueError('Provenance differs')
    result = dict(status='pass', oracle_id=ORACLE_ID, oracle_version=ORACLE_VERSION,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), import_closure_sha256=closure_sha(manifest.repository_root),
        runtime=f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})',
        source_manifest_sha256=manifest.sha256, candidate_sha256=candidate.sha256,
        profile_sha256=sha256(manifest.authority_path('profile').read_bytes()).hexdigest(),
        package_schema_sha256=manifest.record['package_schema']['sha256'], source_sha256=profile['source_sha256'],
        xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),
        policy_sha256=sha256(manifest.authority_path('validation-policy').read_bytes()).hexdigest(), findings=[])
    result['result_sha256'] = sha256(canonical(result)).hexdigest()
    return result

_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
