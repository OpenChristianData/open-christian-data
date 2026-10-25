"""Independent complete-work boundary and actual grouped-volume source oracle."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.contract import _canonical, _runtime_binding, _validation_authority_bindings
from build.tei.maclaren_retained_native_oracle import check as check_raw_volume

ROOT = Path(__file__).resolve().parents[2]
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
MEMBERS = tuple('maclaren-expositorpsalms'+str(i) for i in (1, 2, 3))
TITLE = "The Expositor's Bible: The Psalms"
STATUS = 'Nonaccepted complete authored work reconstructed from three already acquired CCEL electronic volumes. Human review, print collation, rights and publication remain separate.'
IMPORTS = tuple('''build/__init__.py build/tei/__init__.py build/tei/maclaren_psalms_complete_oracle.py build/tei/maclaren_retained_native_oracle.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py'''.split())

def fields(node):
    return [(n.tag, dict(n.attrib), n.text, n.tail, len(n)) for n in node.iter()]

def closure(extra_import=None):
    script = '''import importlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True);sys.path.insert(0,str(root));before=set(sys.modules)
importlib.import_module(sys.argv[2])
if len(sys.argv)>3:importlib.import_module(sys.argv[3])
print(json.dumps(sorted({Path(m.__file__).resolve().relative_to(root).as_posix() for n,m in sys.modules.copy().items() if n not in before and getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(root)})))'''
    args = [sys.executable, '-I', '-B', '-c', script, str(ROOT), 'build.tei.maclaren_psalms_complete_oracle']
    if extra_import:
        args.append(extra_import)
    observed = json.loads(subprocess.run(args, check=True, capture_output=True, text=True).stdout)
    if tuple(observed) != IMPORTS:
        raise ValueError('Maclaren Psalms independent import inventory differs: '+repr(observed))
    return sha256(_canonical([dict(path=p, sha256=sha256((ROOT/p).read_bytes()).hexdigest()) for p in observed])).hexdigest()

def check(source: SourceManifest, candidate: CandidatePackage):
    source.verify(); candidate.verify_integrity()
    if candidate.manifest['status'] != 'nonaccepted' or candidate.manifest['converter'] != source.record['converter']:
        raise ValueError('Aggregate candidate converter/status differs')
    profile = json.loads(source.authority_path('complete-profile').read_bytes())
    policy = json.loads(source.authority_path('complete-policy').read_bytes())
    expected_policy = dict(contract='ocd-maclaren-psalms-complete-policy-v1', ordered_members=list(MEMBERS),
        work_count=1, acquired_volume_count=3, full_native_source_inverse=True, full_group_envelope=True,
        exact_metadata=True, new_acquisition=False, oracle_imports=list(IMPORTS))
    if policy != expected_policy or profile['ordered_members'] != list(MEMBERS) or profile['complete_works'] != 1 or profile['source_volumes'] != 3:
        raise ValueError('Complete-work policy or denominator differs')
    raw_tei = candidate.member_bytes('content.tei.xml'); root = ET.fromstring(raw_tei)
    expected = ET.Element(NS+'TEI', {XML+'id': 'maclaren-psalms-complete-work'})
    header = ET.SubElement(expected, NS+'teiHeader'); fd = ET.SubElement(header, NS+'fileDesc'); ts = ET.SubElement(fd, NS+'titleStmt')
    ET.SubElement(ts, NS+'title').text = TITLE
    packages = []
    component_roots = []
    volume_reports = []
    expected_rows = []
    for ordinal, member in enumerate(MEMBERS, 1):
        raw = source.authority_path(member+'-raw').read_bytes()
        primary = ET.fromstring(raw)
        literal_title = primary.findtext('.//DC.Title')
        if literal_title != TITLE+', Volume '+('I','II','III')[ordinal-1]:
            raise ValueError('Primary complete-work title/order boundary differs')
        package = CandidatePackage.load(source.authority_path(member+'-manifest').parent); package.verify_integrity()
        packages.append(package); component_roots.append(ET.fromstring(package.member_bytes('content.tei.xml')))
        row = profile['volumes'][ordinal-1]
        expected_row = dict(member_id=member, raw_sha256=sha256(raw).hexdigest(), raw_bytes=len(raw),
            raw_elements=sum(1 for n in primary.iter()), package_sha256=package.sha256, title=literal_title)
        expected_rows.append(expected_row)
        if row != expected_row:
            raise ValueError('Source-derived complete volume profile differs')
    if profile != dict(contract='ocd-maclaren-psalms-complete-profile-v1', complete_works=1,
        source_volumes=3, ordered_members=list(MEMBERS), title=TITLE, volumes=expected_rows):
        raise ValueError('Exact complete-work profile differs')
    for role in ('author','editor'):
        values = [r.findtext(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt/'+NS+role) for r in component_roots]
        if not values[0] or len(set(values)) != 1:
            raise ValueError('Primary complete-work common authorship differs')
        ET.SubElement(ts, NS+role).text = values[0]
    pub = ET.SubElement(fd, NS+'publicationStmt'); ET.SubElement(pub, NS+'p').text = STATUS
    desc = ET.SubElement(fd, NS+'sourceDesc'); records = ET.SubElement(desc, NS+'listBibl')
    actual_group = root.find(NS+'text/'+NS+'group')
    if actual_group is None or len(actual_group) != 3:
        raise ValueError('One complete work must contain exactly three source volumes')
    text = ET.SubElement(expected, NS+'text', {XML+'lang': 'en'}); group = ET.SubElement(text, NS+'group', {XML+'id':'maclaren-psalms-source-volumes'})
    with TemporaryDirectory(prefix='ocd-maclaren-psalms-actual-') as temporary:
        for member, component, package, actual in zip(MEMBERS, component_roots, packages, actual_group, strict=True):
            record = ET.SubElement(records, NS+'listBibl', {XML+'id': member+'-source-records'})
            ET.SubElement(record, NS+'head').text = component.findtext(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt/'+NS+'title')
            for node in component.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc'):
                record.append(deepcopy(node))
            volume = deepcopy(component.find(NS+'text')); volume.set(XML+'id', member); group.append(volume)
            stripped = deepcopy(actual)
            if stripped.get(XML+'id') != member:
                raise ValueError('Source volume identity/order differs')
            del stripped.attrib[XML+'id']
            if fields(stripped) != fields(component.find(NS+'text')):
                raise ValueError('Serialized aggregate actual source-volume fields differ')
            # Feed ACTUAL grouped volume fields to the existing independent raw
            # source oracle, retaining only the pinned source-local header/meta.
            extracted = deepcopy(component); extracted.remove(extracted.find(NS+'text')); extracted.append(stripped)
            destination = Path(temporary)/member; destination.mkdir()
            for name in package.member_names:
                (destination/name).write_bytes(package.member_bytes(name))
            (destination/'content.tei.xml').write_bytes(ET.tostring(extracted, encoding='utf-8', xml_declaration=True))
            volume_reports.append(check_raw_volume(member, destination))
    if fields(root) != fields(expected):
        raise ValueError('Complete grouped envelope/header/source-record fields or placement differ')
    etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd'))).assertValid(etree.fromstring(raw_tei))
    ids = [n.get(XML+'id') for n in root.iter() if n.get(XML+'id')]
    if len(ids) != len(set(ids)):
        raise ValueError('Complete work duplicate identities')
    for ref in root.iter(NS+'ref'):
        target = ref.get('target','')
        if target.startswith('#') and target[1:] not in ids:
            raise ValueError('Complete work local reference closure differs')
    expected_account = dict(contract='ocd-maclaren-psalms-complete-accounting-v1', complete_works=1,
        source_volumes=3, ordered_members=list(MEMBERS), profile=profile,
        volume_accounting=[json.loads(p.member_bytes('source-accountability.json')) for p in packages],
        grouping='Each entire source text retained once in volume order; no invented Psalm regrouping or shared matter duplication.')
    if json.loads(candidate.member_bytes('source-accountability.json')) != expected_account:
        raise ValueError('Exact aggregate source accounting differs')
    expected_provenance = dict(status='nonaccepted', work_id='expositors-bible--alexander-maclaren', complete_work=TITLE,
        source_profile=profile, converter=dict(source.record['converter']), source_manifest_sha256=source.sha256,
        human_acceptance='not_recorded', rights='unresolved', publication='not_ready')
    if json.loads(candidate.member_bytes('provenance.json')) != expected_provenance:
        raise ValueError('Complete-work source/recipe provenance differs')
    if candidate.member_bytes('README.source.md') != source.authority_path('complete-readme').read_bytes():
        raise ValueError('Complete human-visible source attribution differs')
    if candidate.member_bytes('unresolved.jsonl') != _canonical(dict(id='maclaren-psalms-complete-human-rights-print',status='unresolved',detail=STATUS)):
        raise ValueError('Complete-work uncertainty record differs')
    return dict(status='pass', complete_works=1, acquired_volumes=3, p5='pass',
        actual_serialized_group_fields_and_source_inverse='pass', volume_reports=volume_reports)

def oracle(source: SourceManifest, candidate: CandidatePackage):
    findings = check(source,candidate)
    result = dict(status='pass', oracle_id=oracle.oracle_id, oracle_version=oracle.oracle_version,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), import_closure_sha256=closure(),
        runtime=_runtime_binding(), source_manifest_sha256=source.sha256, candidate_sha256=candidate.sha256,
        **_validation_authority_bindings(source), findings=[json.dumps(findings,sort_keys=True)])
    result['result_sha256'] = sha256(_canonical(result)).hexdigest()
    return result

oracle.oracle_id = 'ocd-maclaren-psalms-complete-independent-oracle'
oracle.oracle_version = '1'
