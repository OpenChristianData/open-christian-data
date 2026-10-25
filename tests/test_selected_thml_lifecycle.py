"""Fixture-only acceptance and offline release for two work-selection shapes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
from lxml import etree

from build.tei.selected_thml import _convert
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.selected_thml_check import check_selected_thml
from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate
from ocd_kernel.tei.acceptance import build_acceptance_record, write_acceptance, validate_acceptance, promote_accepted_master
from ocd_kernel.tei.writer import tei_el
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from tests import test_tei_acceptance as evidence


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def _fixture(tmp_path, shape, monkeypatch):
    root = tmp_path / 'f'
    root.mkdir()
    extra = '<div1 id="b" title="Second"><p>Other work.</p></div1>' if shape == 'anthology' else '<div1 id="b" title="Index"><p>Index entry.</p></div1>'
    credit = '<div1 id="c" title="Credits"><p id="credit">Fixture shared credit.</p></div1>' if shape == 'anthology' else ''
    raw = ('<ThML><ThML.head><generalInfo>Fixture only.</generalInfo><DC.Title>Fixture source</DC.Title></ThML.head><ThML.body>' + credit + '<div1 id="a" title="First"><h2 id="heading">First</h2><p id="p1">Text <i>with emphasis</i> and a <note n="1" place="foot">note.</note></p></div1>' + extra + '</ThML.body></ThML>').encode()
    source = root / 'retained/source.xml'
    source.parent.mkdir(); source.write_bytes(raw)
    units = [dict(native_id='a', title='First', role='body')]
    dependencies = []
    if shape == 'anthology':
        dependencies = [dict(native_id='credit', text_sha256=hashlib.sha256(b'Fixture shared credit.').hexdigest(), purpose='source-credit')]
    else:
        units.append(dict(native_id='b', title='Index', role='back'))
    selection = dict(selection_id='fixture-selection', work_id='first', member_path='retained/source.xml', units=units, dependencies=dependencies)
    work = dict(schema_version='2.0', work_id='first', title='First', creators=[dict(name='Fixture Author',role='author')], evidence=['retained/source.xml#'+n for n in ['a'] + (['credit'] if dependencies else ['b'])], textual_forms=[dict(textual_form_id='english', language='en', editions=[dict(edition_id='edition',title='First',category='prose',language='en',acquisition_ids=['acquired'],containing_source=dict(title='Fixture source',locator='retained/source.xml',evidence=['retained/source.xml']))])])
    member = dict(path='retained/source.xml',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),media_type='application/xml')
    acquisition = dict(schema_version='2.0',acquisition_id='acquired',edition_id='edition',provider='Fixture',url='https://example.test/source',retained_files=[member],source_path=member['path'],source_bytes=member['bytes'],source_sha256=member['sha256'],source_scope='Selected fixture work and declared context',source_selection=selection)
    work_path = root/'library/works/first/work.json'
    acq_path = root/'library/works/first/forms/english/editions/edition/acquisitions/acquired.json'
    _write(work_path,work);_write(acq_path,acquisition)
    _write(work_path.with_name('state.json'),dict(schema_version='2.0',work_id='first',targets=[dict(target_id='edition',target_type='edition',stage='review',updated_at='2026-09-11T00:00:00Z',evidence=['candidate.xml'])]))
    paths = {'work':work_path,'acquisition':acq_path,'retained-source':source}
    manifest = SimpleNamespace(repository_root=root,verify=lambda:None,authority_path=paths.__getitem__)
    produced = _convert(manifest)
    assert produced == _convert(manifest)
    candidate = root/'candidate.xml'
    tree = etree.fromstring(produced['content.tei.xml'])
    assert len(tree.findall('.//{http://www.tei-c.org/ns/1.0}body/{http://www.tei-c.org/ns/1.0}div/{http://www.tei-c.org/ns/1.0}head')) == 1
    header = tree[0]
    header.find('.//{http://www.tei-c.org/ns/1.0}bibl').append(tei_el('idno',{'type':'representation_revision'},text='fixture-v1'))
    revision = tei_el('revisionDesc');revision.append(tei_el('change',{'xml:id':'fixture-v1','when':'2026-09-11'},text='Fixture-only selection lifecycle.'));header.append(revision)
    candidate.write_bytes(etree.tostring(tree,encoding='utf-8',xml_declaration=True))
    check_selected_thml(root,acquisition,work,candidate)
    identity = dict(work_id='first',textual_form_id='english',edition_id='edition',acquisition_id='acquired')
    monkeypatch.setattr(evidence,'_identity',lambda: identity)
    monkeypatch.setattr(evidence,'_coverage',lambda declared:dict(status='partial',declared=declared,reached=['a'],inspected=['a/head'],unreviewed=['a/body']))
    scope = dict(kind='work',declared=acquisition['source_scope'],expected_members=[dict(path=member['path'],position=1)],included_members=[dict(path=member['path'],position=1,bytes=member['bytes'],sha256=member['sha256'],scope=acquisition['source_scope'])],excluded_members=[])
    source_facts = {key:acquisition[key] for key in ('source_path','source_bytes','source_sha256','source_scope')}
    accounting,technical,review = evidence._prepare_evidence(root,candidate,scope=scope,source_facts=source_facts)
    decision = evidence._decision();decision['agent_assessment']['supported_scope']=scope['declared']
    record = build_acceptance_record(root,identity=identity,candidate_path=candidate,source_accounting_path=accounting,scope=scope,technical=technical,review=review,representation_revision=dict(id='fixture-v1',date='2026-09-11',note='Fixture-only selection lifecycle.'),decision=decision)
    accepted = acq_path.parent.parent/'acceptance.json';write_acceptance(accepted,record)
    return root,accepted,acquisition,work,candidate


def _load_module_from_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _authority(root, relative, name, role):
    content = (root / relative).read_bytes()
    return dict(path=relative, name=name, role=role, bytes=len(content), sha256=hashlib.sha256(content).hexdigest())


def test_public_source_manifest_reconstructs_and_validates_selected_work(tmp_path, monkeypatch):
    root, _, _, _, _ = _fixture(tmp_path, 'anthology', monkeypatch)
    checkout = Path(__file__).resolve().parents[1]
    converter_path = 'build/tei/selected_thml.py'
    validator_path = 'build/tei/selected_thml_oracle.py'
    package_schema_path = 'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'
    xsd_path = 'ocd_kernel/tei/vendor/xsd/tei_all.xsd'

    converter_copy = root / converter_path
    validator_copy = root / validator_path
    for relative in (converter_path, validator_path, package_schema_path, xsd_path):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checkout / relative, target)
    converter = _load_module_from_path('fixture_selected_thml', converter_copy)
    oracle = _load_module_from_path('fixture_selected_thml_oracle', validator_copy)
    for relative in oracle.CLOSURE:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checkout / relative, target)

    profile_path = 'sources/selection/profile.json'
    policy_path = 'sources/selection/policy.json'
    for relative, value in ((profile_path, {'contract': 'selected-thml-profile-v1'}),
                            (policy_path, {'contract': 'selected-thml-check-v1'})):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')

    authorities = [
        _authority(root, 'retained/source.xml', 'retained-source', 'primary-source'),
        _authority(root, 'library/works/first/work.json', 'work', 'work-identity-config'),
        _authority(root, 'library/works/first/forms/english/editions/edition/acquisitions/acquired.json', 'acquisition', 'acquisition-selection-authority'),
        _authority(root, profile_path, 'profile', 'complete-source-feature-profile'),
        _authority(root, policy_path, 'policy', 'independent-validation-policy'),
        _authority(root, xsd_path, 'tei-schema', 'tei-validation-schema'),
        _authority(root, package_schema_path, 'package-schema', 'candidate-package-schema'),
    ]
    authorities.extend(
        _authority(root, relative, f'closure-{index}', 'implementation-dependency')
        for index, relative in enumerate(oracle.CLOSURE)
    )
    package_schema = {'path': package_schema_path, 'sha256': hashlib.sha256((root / package_schema_path).read_bytes()).hexdigest()}
    manifest_record = {
        'contract': 'ocd-source-manifest-v1',
        'source_id': 'fixture-selected-thml',
        'work_id': 'first',
        'authorities': authorities,
        'converter': {
            'id': converter._convert.converter_id,
            'version': converter._convert.converter_version,
            'callable': '_convert',
            'implementation_path': converter_path,
            'implementation_sha256': hashlib.sha256(converter_copy.read_bytes()).hexdigest(),
        },
        'validator': {
            'id': oracle._oracle.oracle_id,
            'version': oracle._oracle.oracle_version,
            'callable': '_oracle',
            'implementation_path': validator_path,
            'implementation_sha256': hashlib.sha256(validator_copy.read_bytes()).hexdigest(),
            'import_closure_sha256': oracle.closure_digest(root),
        },
        'package_schema': package_schema,
    }
    manifest_path = root / 'sources/selection/selected.source-manifest.json'
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_record, sort_keys=True) + '\n', encoding='utf-8')

    manifest = SourceManifest.load(manifest_path, repository_root=root)
    candidate = reconstruct(manifest, tmp_path / 'selected-candidate-package', converter._convert)
    report = validate(manifest, candidate, oracle._oracle)

    assert report.status == 'pass'
    assert report.candidate_sha256 == candidate.sha256
    assert report.source_manifest_sha256 == manifest.sha256


@pytest.mark.parametrize('shape',['whole-member','anthology'])
def test_fixture_selection_acceptance_and_independent_offline_release(tmp_path,shape,monkeypatch):
    root,accepted,acquisition,work,candidate = _fixture(tmp_path,shape,monkeypatch)
    assert validate_acceptance(accepted,root=root)['promotion']['status']=='pending'
    promoted = promote_accepted_master(root,acceptance_path=accepted,destination=tmp_path/'p')
    selection = dict(schema_version='2.0',release_id='selection-fixture',items=[dict(item_id='first',category='prose',acceptance_path=promoted.acceptance_path.relative_to(promoted.destination_root).as_posix())])
    release = tmp_path/'release'
    from tests.release_rights_fixture import authorize_release_fixture
    authorize_release_fixture(promoted.destination_root, selection['items'][0])
    report = assemble_release_v2(promoted.destination_root,release,selection=selection)
    assert report['status']=='pass', report
    assert verify_release_v2(promoted.destination_root,release,selection=selection)==dict(status='pass',errors=[])
    rows = [json.loads(line) for line in (release/report['configurations'][0]['path']).read_bytes().splitlines()]
    # Header credits do not become extra literary rows.
    assert len(rows)==len(acquisition['source_selection']['units'])
    assert 'Fixture shared credit.' not in '\n'.join(row.get('text','') for row in rows)


@pytest.mark.parametrize('change',['text','note-attachment','credit','selection-binding','sibling'])
def test_independent_checker_rejects_candidate_corruption(tmp_path,monkeypatch,change):
    root,accepted,acquisition,work,candidate = _fixture(tmp_path,'anthology',monkeypatch)
    tree = etree.parse(str(candidate)); ns={'t':'http://www.tei-c.org/ns/1.0'}
    if change=='text':tree.xpath('//t:text//t:p',namespaces=ns)[0].text='Corruption'
    elif change=='note-attachment':
        note=tree.xpath('//t:text//t:note',namespaces=ns)[0];note.getparent().remove(note)
    elif change=='credit':
        note=tree.xpath('//t:note[@type="source-credit"]',namespaces=ns)[0];note.getparent().remove(note)
    elif change=='selection-binding':tree.xpath('//t:idno[@type="source_selection_sha256"]',namespaces=ns)[0].text='0'*64
    else:tree.xpath('//t:body/t:div/t:head',namespaces=ns)[0].text='Second'
    tree.write(str(candidate),encoding='utf-8')
    with pytest.raises(PipelineError):check_selected_thml(root,acquisition,work,candidate)


def test_acceptance_rejects_resealed_but_unfaithful_selected_candidate(tmp_path,monkeypatch):
    from ocd_kernel.tei.acceptance import make_file_binding
    root,accepted,acquisition,work,candidate = _fixture(tmp_path,'anthology',monkeypatch)
    candidate.write_bytes(candidate.read_bytes().replace(b'with emphasis',b'changed wording'))
    binding = make_file_binding(root,candidate)
    record = json.loads(accepted.read_bytes())
    record['technical']['candidate'] = binding
    record['promotion']['master'].update(bytes=binding['bytes'],sha256=binding['sha256'])
    for name in ('validation','accounting','fidelity','reproducibility','schema','closure'):
        proof = record['technical'][name]
        path = root / proof['path']
        document = json.loads(path.read_bytes()); document['candidate'] = binding
        _write(path,document); proof.update(make_file_binding(root,path))
    review_path = root / record['review']['report']['path']
    review = json.loads(review_path.read_bytes());review['candidate']=binding
    _write(review_path,review);record['review']['report']=make_file_binding(root,review_path)
    _write(accepted,record)
    with pytest.raises(PipelineError,match='selected ThML text or tail differs'):
        validate_acceptance(accepted,root=root)
