"""Bounded L811 acceptance/stage/installation route; execution is coordinator-held.

The source package, source oracle, source runtime and reviewed header are
immutable. Imports perform no preparation. After explicit coordinator release,
the CLI prepares an external accepted generation or preflights/installs exactly
the reviewed generation. Canonical installation remains coordinator-owned.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import subprocess
import sys
from uuid import uuid4

from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ocd_kernel.lib.path_io import io_path, resolve_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header

LOG = Path('reports/_logs/eusebius-l811-existing-install-20261004-v1')
HOME = Path('sources/manifest-acquisitions/eusebius-l811-retained-install-20261004-v1')
WORK_ID = 'eusebius-commentarii-in-psalmos'
FORM = 'pta-english'  # Stable opaque identifier, not a current language claim.
EDITION = 'pta-ef861ab3-commentarii-psalmos'
ACQUISITION = 'pta-l811-retained-ef861ab3'
WORK = Path('library/works') / WORK_ID
ED = WORK / 'forms' / FORM / 'editions' / EDITION
ACQ = ED / 'acquisitions' / (ACQUISITION + '.json')
DESCRIPTOR = WORK / 'integration/pta-l811-three-tome-v5/source-member-set.json'
LANE = WORK / 'integration/l811-retained-complete-20261004-v1'
LIBRARY = Path('D:/Library/Open Christian Data')
FIXTURE = ROOT / '.tmp_audit/eusebius-l811-install-fixture-20261004-v1'
STAGE = ROOT / LOG / 'accepted-stage-v1'
FIXTURE_STAGE = ROOT / LOG / 'accepted-fixture-stage-v1'
FIXTURE_MARKER = '.l811-accepted-install-fixture.json'
CAPTURE = LOG / 'accepted-execution-imports-v1.json'
READER_APPLICATION = LOG / 'root-reader-application-v1.json'
READER_APPLICATION_SHA = 'b18b2f8135f7815768f4269d03640c0e44fa9d83643be56ce2430819242acd00'
READER_PROSE = Path('ocd_kernel/projection/categories/prose.py')
READER_PROSE_SHA = 'ddffaa51e17a091c3cd2a15948e0d6b0494c122f44ff9c7495062fcc44cf3993'
BOOTSTRAP_STAGE = ROOT / LOG / 'acceptance-bootstrap-stage-v1'
HEADER_RECEIPT = LOG / 'accepted-header-proposal-v1/proposal-receipt.json'
HEADER_RECEIPT_SHA = '2c8f9287e043c992b10595382b93436887e1a3d05204372d0360b91f8d285203'
HEADER_REVIEW = Path('reports/_logs/current-root-installed-20261003-v1/root-pending-three-header-review-20261004-v1.json')
HEADER_REVIEW_SHA = 'ee859e90ec06a006de3577093525ab16490d01345e62feb2ed069fee7c717b34'
MASTER_PROPOSAL = LOG / 'accepted-header-proposal-v1/accepted-representation.tei.xml'
MASTER_SHA = 'b67b84fe42425800cabcd99f923e26d866b34f4123e37d65dca8e0922577acae'
PACKAGE = Path('D:/Library/Open Christian Data/candidate-reviews/eusebius-l811-retained-repair-20261004-v1/strict-final-v1/package')
PACKAGE_SHA = '37e6b998c4bc6111b0ebc0b06d2a2738e0e28fd6c35139119563828a299f38aa'
SOURCE_SHA = '4f18d2b0b33a67a7c2583df9ee8b8b595a2d0d256d1561eeaa8ebca4afc39f31'
TEI_SHA = '29d0845997301ec67aef8625d5014b402ffe552590296db2ca65742944db0697'
BODY_SUFFIX_SHA = '218ff581b6c87f336eeb8a28fea7d9673d5856fb9674110e72841af45e4cd9bc'
PROOF = LOG / 'source-completion-packet-v1.json'
PROOF_SHA = 'e5e84b7ed987c22d2cd5a5752c2dd7e9e2b628fa6f7e7f0b0d412900f71754fe'
ROOT_REVIEW = LOG / 'root-final-source-review-v1.json'
ROOT_REVIEW_SHA = 'a3b0e22ff267418563d8cc75fd83265fa16023375fee5a98213b639201ed511d'
IDENTITY_PROPOSAL = LOG / 'stable-greek-identity-proposal-v2.json'
IDENTITY_SHA = 'f0e1bd7ed9ab190e46a9423ff9bd99d5f7c6d7721cfb36e55c86877086216c24'
EVIDENCE_PROPOSAL = LOG / 'completed-source-evidence-routing-proposal-v3.json'
EVIDENCE_SHA = '9abfab33d4f7fa335fbdd72c0b146cb0b49a1e6518a30bf7ebba2a98b58537de'
NS = 'http://www.tei-c.org/ns/1.0'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
SCOPE = ('One complete retained electronic Commentarii in Psalmos authored work, '
         'ordered PTA Tomes I-III at ef861ab391ea35c5d85b41dd8d7ba2bf65530b21. '
         'All Greek source Psalm labels Ps_1 through Ps_150, German prefaces, '
         'additional source sections, apparatus, witnesses and administration are '
         'retained. Source I/II are draft and explicitly work in progress; III is '
         'approved. Completeness describes these exact digital witnesses, not a '
         'finished printed critical edition or Hebrew Bible numbering. Human '
         'review, rights and publication remain separate.')
REVISION = dict(id='eusebius-l811-retained-complete-20261004-v1', date='2026-10-04',
                note='Agent acceptance of the complete retained three-tome electronic Commentarii in Psalmos; exact reviewed text preserved, Greek source identity bound, source draft and URI qualifications retained.')
EXECUTION_RELEASED = True  # Exact integrated reader approved; execution follows coordinator window release.
CREDIT_APPEND = ('\n\nCurrent reconstruction evidence is recorded in integration/l811-retained-complete-20261004-v1/README.source.md and current-source-assignment.json. The stable ID pta-english is an opaque historical identifier; current factual metadata identifies Greek text with retained German prefaces. All three exact digital tomes are retained; source I/II explicitly remain work in progress and source III is approved. Greek Psalm labels and ambiguous URI/witness literals are preserved without Hebrew Bible normalization. The original five-file generation and historical proposals remain exact dated lineage evidence. Agent acceptance, when recorded, is in forms/pta-english/editions/pta-ef861ab3-commentarii-psalmos/acceptance.json; a completed guarded operation journal records installation. Original PTA attribution and CC BY-SA 4.0 conditions remain applicable. Human review, local-jurisdiction rights and publication remain separate.\n').encode('utf-8')
ORIGINAL_FILES = {
    'SOURCE_CREDIT.md': '9562abaab2f30a91f57b9d7224d608f76b37e9416bbae80d9970d8e6b91b45ab',
    'state.json': '61c769b92f392660e742cac9996b75610eb0eca459c9b14db7c6469e683870de',
    'work.json': '457c36e1119888321eeb140ce7926441e24a094c467bc7a2e9656a94b544f8d2',
    DESCRIPTOR.relative_to(WORK).as_posix(): 'edc49a81cc88d745e0aefa9d101945938eef1bbcf9006afaa85975af7c4c54cc',
    ACQ.relative_to(WORK).as_posix(): '3d4c2b5aebde505b6f6fda0c7d96a01c22e8d6170f2624e2390b6a432f01aaeb',
}
SOURCE_PROCESS_ONLY = [Path('build/tei/eusebius_l811_retained_repair.py'),
                       Path('build/tei/eusebius_l811_source_oracle.py'),
                       Path('build/tei/eusebius_l811_runtime.py'),
                       Path('build/tools/prove_eusebius_l811_retained.py'),
                       Path('build/tei/pta_l811_three_tome.py'),
                       Path('build/tei/pta_l811_three_tome_oracle.py')]
SOURCE_PROCESS_ONLY += [LOG / 'retained-authorities' / p
                        for p in [Path('build/tei/pta_l811_three_tome.py'),
                                  Path('build/tei/pta_l811_three_tome_oracle.py')]]


def enc(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')) + '\n').encode('utf-8')


def read(path):
    return json.loads(io_path(path).read_bytes())


def digest(path):
    return sha256(io_path(path).read_bytes()).hexdigest()


def insist(condition, reason):
    if not condition:
        raise PipelineError(reason)


def write(root, path, data):
    target=io_path(root/path)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(data)
    return root/path


def dump(root, path, value):
    return write(root,path,enc(value))


def copy(root, stage, path):
    return write(stage,path,io_path(root/path).read_bytes())


def identity():
    return dict(work_id=WORK_ID, textual_form_id=FORM, edition_id=EDITION,
                acquisition_id=ACQUISITION)


def reviewed_revision():
    for path,pin in [(HEADER_RECEIPT,HEADER_RECEIPT_SHA),(HEADER_REVIEW,HEADER_REVIEW_SHA),
                     (MASTER_PROPOSAL,MASTER_SHA)]:
        insist(digest(ROOT/path)==pin,'Frozen reviewed L811 header authority differs')
    receipt=read(ROOT/HEADER_RECEIPT);review=read(ROOT/HEADER_REVIEW)
    insist(receipt['status']=='pass' and receipt['revision']==REVISION
           and receipt['master']['sha256']==MASTER_SHA and not receipt['p5_errors']
           and receipt['exact_full_source_tei_byte_inverse']
           and receipt['body_text_suffix_bytes_unchanged'],'Exact header proposal proof differs')
    rows=[row for row in review['works'] if row['identity']==identity()]
    insist(review['status']=='pass' and review['source_helpers_absent'] is True
           and len(rows)==1 and rows[0]['master_sha256']==MASTER_SHA
           and rows[0]['source_sha256']==TEI_SHA and rows[0]['p5']=='pass'
           and rows[0]['full_source_byte_inverse'] and rows[0]['complete_text_bytes_unchanged'],
           'Root actual accepted-header review differs')
    return dict(REVISION)


def reviewed_reader():
    insist(isinstance(READER_APPLICATION_SHA,str) and len(READER_APPLICATION_SHA)==64,
           'L811 reader application has not been coordinator-bound')
    insist(digest(ROOT/READER_APPLICATION)==READER_APPLICATION_SHA
           and digest(ROOT/READER_PROSE)==READER_PROSE_SHA,
           'Exact reviewed applied L811 reader generation differs')
    return dict(path=READER_APPLICATION.as_posix(),sha256=READER_APPLICATION_SHA)


def projection_gate(root, acceptance):
    from ocd_kernel.projection.categories.prose import project_accepted_prose,verify_accepted_prose
    result=project_accepted_prose(root,acceptance_path=acceptance)
    errors=verify_accepted_prose(root,acceptance_path=acceptance,rows=result['rows'],receipt=result['receipt'])
    insist(not errors,'Actual maintained L811 reader verification failed: '+str(errors))
    return dict(status='pass',rows=len(result['rows']),receipt_sha256=sha256(enc(result['receipt'])).hexdigest())


def dependency_paths(bootstrap=False):
    from ocd_kernel.reconstruction.contract import SourceManifest
    source=SourceManifest.load(ROOT/HOME/'source-manifest.json',repository_root=ROOT)
    paths={Path(row['path']) for row in source.record['authorities']}
    paths.update({HOME/'source-manifest.json',PROOF,ROOT_REVIEW,IDENTITY_PROPOSAL,EVIDENCE_PROPOSAL,
                  HEADER_RECEIPT,HEADER_REVIEW,MASTER_PROPOSAL,READER_APPLICATION,READER_PROSE,Path(__file__).relative_to(ROOT),
                  Path('build/tools/capture_eusebius_l811_acceptance.py'),
                  Path('build/tools/prove_eusebius_l811_install.py')})
    paths.update(LOG/'retained-canonical-five'/relative for relative in ORIGINAL_FILES)
    old_state=read(ROOT/LOG/'retained-canonical-five/state.json')
    paths.update(Path(p) for target in old_state['targets'] for p in target['evidence'])
    # The work/credit/state being deliberately updated are preimages, not frozen
    # live dependencies. Their exact snapshots remain frozen independently.
    paths.difference_update({WORK/'work.json',WORK/'state.json',WORK/'SOURCE_CREDIT.md'})
    for directory,pattern in [('schemas/v2','*.json'),('ocd_kernel/reconstruction/schemas','*.json'),
                              ('ocd_kernel/tei/vendor/xsd','*.xsd')]:
        paths.update(p.relative_to(ROOT) for p in (ROOT/directory).rglob(pattern))
    if bootstrap:
        root=resolve_path(ROOT,strict=True);library=resolve_path(LIBRARY,strict=True)
        for module in sys.modules.copy().values():
            filename=getattr(module,'__file__',None)
            if not filename:continue
            physical=resolve_path(Path(filename),strict=True)
            if physical.is_relative_to(root):paths.add(physical.relative_to(root))
            elif physical.is_relative_to(library):
                relative=physical.relative_to(library)
                insist(relative.parts[0] in {'raw','reports','exports'}
                       and resolve_path(ROOT/relative,strict=True)==physical,'Physical Library execution alias differs')
                paths.add(relative)
    else:
        paths.add(CAPTURE);capture=read(ROOT/CAPTURE)
        insist(capture['status']=='pass' and capture['identity']==identity(),'Actual accepted capture differs')
        paths.update(Path(row['path']) for row in capture['first_party_files'])
    return paths


def original_five(root=ROOT):
    """Exact current preimages and durable original snapshots, not a census."""
    from ocd_kernel.tei.install_accepted import _files
    insist(_files(root / WORK) == ORIGINAL_FILES, 'Exact original L811 five-file generation differs')
    for relative, pin in ORIGINAL_FILES.items():
        insist(digest(root / WORK / relative) == pin
               and digest(ROOT / LOG / 'retained-canonical-five' / relative) == pin,
               'L811 original/snapshot differs: ' + relative)
    return dict(ORIGINAL_FILES)


def records():
    original_five()
    for path, pin in [(IDENTITY_PROPOSAL, IDENTITY_SHA), (EVIDENCE_PROPOSAL, EVIDENCE_SHA),
                      (PROOF, PROOF_SHA), (ROOT_REVIEW, ROOT_REVIEW_SHA),
                      (HOME / 'source-manifest.json', SOURCE_SHA),
                      (PACKAGE / 'manifest.json', PACKAGE_SHA)]:
        insist(digest(ROOT / path if not path.is_absolute() else path) == pin,
               'Frozen L811 authority differs: ' + path.as_posix())
    old = read(ROOT / WORK / 'work.json')
    proposed = deepcopy(read(ROOT / EVIDENCE_PROPOSAL)['work_after'])
    reverted = deepcopy(proposed)
    expected = [('language', 'grc', 'en'),
                ('title', 'PTA Greek critical text with retained German prefaces', 'PTA English text')]
    for key, after, before in expected:
        insist(reverted['textual_forms'][0][key] == after
               and old['textual_forms'][0][key] == before, 'Exact form correction differs')
        reverted['textual_forms'][0][key] = before
    edition = reverted['textual_forms'][0]['editions'][0]
    for key, after in [('language', 'grc'),
                       ('title', 'Commentarii in Psalmos, retained PTA Greek Tomes I-III')]:
        insist(edition[key] == after, 'Exact edition correction differs')
        edition[key] = old['textual_forms'][0]['editions'][0][key]
    insist(edition.pop('category', None) == 'prose' and 'category' not in old['textual_forms'][0]['editions'][0],
           'Exact newly declared prose category differs')
    reverted['evidence'] = old['evidence']
    insist(reverted == old, 'L811 metadata changes exceed five factual fields and evidence routing')
    for locator in proposed['evidence']:
        insist(io_path(ROOT / locator).is_file(), 'Current evidence does not resolve: ' + locator)
    acquisition = read(ROOT / ACQ)
    insist(acquisition['acquisition_id'] == ACQUISITION
           and acquisition['edition_id'] == EDITION
           and acquisition['source_path'] == DESCRIPTOR.as_posix()
           and acquisition['source_sha256'] == ORIGINAL_FILES[DESCRIPTOR.relative_to(WORK).as_posix()]
           and acquisition['source_bytes'] == 1604
           and acquisition['source_kind'] == 'retained-member-set', 'Existing member-set binding differs')
    return proposed, acquisition


def validate_metadata(stage_root):
    """Maintained schemas plus exact authorized existing-work metadata delta."""
    from ocd_kernel.library.identities import validate_record
    from ocd_kernel.library.acquisitions import validate_acquisition
    from ocd_kernel.library.state import validate_state
    proposed, acquisition = records()
    work_path = stage_root / WORK / 'work.json'
    insist(read(work_path) == proposed, 'Staged work differs from reviewed five fields/evidence')
    validate_record('work', proposed, context='L811 exact stable Greek metadata correction')
    insist(io_path(stage_root / ACQ).read_bytes() == io_path(ROOT / ACQ).read_bytes()
           and io_path(stage_root / DESCRIPTOR).read_bytes() == io_path(ROOT / DESCRIPTOR).read_bytes(),
           'Existing acquisition or member descriptor bytes changed')
    validate_acquisition(stage_root / ACQ, root=stage_root)
    validate_state(stage_root / WORK / 'state.json', root=stage_root)
    insist(io_path(stage_root / WORK / 'SOURCE_CREDIT.md').read_bytes()
           == io_path(ROOT / LOG / 'retained-canonical-five/SOURCE_CREDIT.md').read_bytes() + CREDIT_APPEND,
           'Credit differs from exact original prefix and declared qualification append')
    for relative, pin in ORIGINAL_FILES.items():
        insist(digest(stage_root / LANE / 'inputs/retained-canonical-five' / relative) == pin,
               'Staged original five-file snapshot differs: ' + relative)
    return proposed, acquisition


def proposed_state(at, reason):
    """Pure proposed value: preserve acquisition target and all old edition fields."""
    stamp = datetime.fromisoformat(at.replace('Z', '+00:00'))
    insist(stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0,
           'Stage timestamp must be exact aware UTC')
    from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON
    insist(reason == PROMOTED_MASTER_REASON, 'State reason must be maintained promotion reason')
    original = read(ROOT / WORK / 'state.json')
    result = deepcopy(original)
    targets = [t for t in result['targets']
               if t['target_type'] == 'edition' and t['target_id'] == EDITION]
    insist(len(targets) == 1 and targets[0]['stage'] == 'review', 'Exact review state preimage differs')
    target = targets[0]
    target.update(stage='accepted', updated_at=at, reason=reason)
    for reference in [(ED / 'master.tei.xml').as_posix(), (ED / 'acceptance.json').as_posix()]:
        if reference not in target['evidence']:
            target['evidence'].append(reference)
    insist(result['targets'][0] == original['targets'][0], 'Acquisition state changed')
    return result


def bound(original, acquisition, revision):
    """Pure header derivation for separately released proposal generation."""
    insist(revision == REVISION and sha256(original).hexdigest() == TEI_SHA,
           'Frozen source or proposed fixed revision differs')
    tree = etree.fromstring(original, etree.XMLParser(resolve_entities=False, no_network=True))
    header = tree.find('{%s}teiHeader' % NS)
    historical = dict(pointers=header.xpath('.//t:sourceDesc//t:ptr/@target', namespaces={'t': NS}),
                      sha256=header.xpath('.//t:idno[@type="sha256"]/text()', namespaces={'t': NS}))
    source = {k: acquisition[k] for k in ['source_path', 'source_sha256', 'source_bytes', 'source_kind']}
    result = bind_reviewed_header(original, expected_sha256=TEI_SHA, identity=identity(),
                                 source=source, source_url=acquisition['url'],
                                 declared_scope=SCOPE, revision=revision,
                                 historical_source_description=historical)
    inverse_header(result, original, acquisition, revision)
    return result


def inverse_header(actual, original, acquisition, revision):
    """Remove only one binding bibl and one change; recover the entire source bytes."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(actual, parser)
    old = etree.fromstring(original, parser)
    ns = {'t': NS}
    binding = root.xpath('./t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl[@type="ocd-acceptance-binding"]', namespaces=ns)
    change = root.xpath('./t:teiHeader/t:revisionDesc/t:change[@xml:id=$id]', id=revision['id'], namespaces=ns)
    insist(len(binding) == 1 and len(change) == 1, 'Unique proposed binding/change missing')
    insist(change[0].get('when') == revision['date'] and change[0].text == revision['note']
           and change[0].tail is None and binding[0].tail is None, 'Exact revision fields differ')
    restored = actual
    for opening, closing in [(b'<bibl xmlns="http://www.tei-c.org/ns/1.0" type="ocd-acceptance-binding">', b'</bibl>'),
                             (b'<change xmlns="http://www.tei-c.org/ns/1.0" xml:id="' + revision['id'].encode() + b'"', b'</change>')]:
        insist(restored.count(opening) == 1, 'Unique literal acceptance insertion differs')
        start = restored.index(opening)
        end = restored.index(closing, start) + len(closing)
        restored = restored[:start] + restored[end:]
    insist(restored == original, 'Full header/body inverse differs from immutable reviewed candidate')
    insist(actual.split(b'</teiHeader>', 1)[1] == original.split(b'</teiHeader>', 1)[1],
           'Accepted header changed any reviewed text/body/suffix byte')
    insist(sha256(actual.split(b'</teiHeader>', 1)[1]).hexdigest() == BODY_SUFFIX_SHA,
           'Actual immutable complete text/body/suffix pin differs')
    old_changes = old.xpath('./t:teiHeader/t:revisionDesc/t:change', namespaces=ns)
    insist(len(old_changes) == 9, 'Original nine source revision changes differ')
    # File-based maintained facts/P5 validation follows the separately released
    # header proposal. No source availability or source draft status is rewritten.
    return True


def admitted_source_command(output):
    return [sys.executable, '-I', '-B', str(ROOT / 'build/tools/prove_eusebius_l811_retained.py'),
            '--package', PACKAGE.as_posix(), '--output', str(output)]


def source_gate(output, process_path):
    """Reserved for released preparation: source execution is a separate child."""
    insist(EXECUTION_RELEASED, 'L811 execution remains coordinator-held')
    insist(not io_path(output).exists() and not io_path(process_path).exists(), 'Preserve previous source process evidence')
    cmd = admitted_source_command(output)
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    process = dict(command=cmd, cwd=ROOT.as_posix(), exit_code=result.returncode,
                   stdout=result.stdout, stderr=result.stderr)
    io_path(process_path).parent.mkdir(parents=True, exist_ok=True)
    io_path(process_path).write_bytes(enc(process))  # Before result assertions.
    insist(result.returncode == 0, 'Fresh isolated source gate failed; process evidence retained')
    check = json.loads(result.stdout)
    insist(check == dict(status='pass', source_tomes=3, complete_works=1,
                         actual_nodes=63218, attributes=57271, tei_sha256=TEI_SHA,
                         full_old_byte_inverse=True), 'Fresh isolated whole-source result differs')
    return read(output), process


def allowed_paths():
    paths = set(ORIGINAL_FILES)
    paths.update(p.relative_to(WORK).as_posix() for p in [ED / 'master.tei.xml', ED / 'acceptance.json'])
    paths.add((LANE / 'candidate.tei.xml').relative_to(WORK).as_posix())
    names = ['manifest.json', 'content.tei.xml', 'provenance.json',
             'source-accountability.json', 'README.source.md', 'unresolved.jsonl']
    paths.update((LANE / 'inputs/package' / n).relative_to(WORK).as_posix() for n in names)
    paths.update((LANE / 'inputs/retained-canonical-five' / n).relative_to(WORK).as_posix() for n in ORIGINAL_FILES)
    paths.update((LANE / n).relative_to(WORK).as_posix() for n in [
        'README.source.md', 'identity-proposal.json', 'evidence-routing-proposal.json',
        'root-source-review.json', 'current-source-assignment.json', 'source-review.json',
        'validation.json', 'accounting.json', 'fidelity.json', 'reproducibility.json',
        'schema.json', 'closure.json', 'review.json', 'source-accounting.json'])
    return paths


def source_binding(acquisition):
    return {key: acquisition[key] for key in
            ('source_path','source_sha256','source_bytes','source_scope','source_kind')}


def assignment(work, acquisition, at):
    return dict(contract='ocd-l811-current-source-assignment-v1', status='root-reviewed-source-assignment',
                identity=identity(), work_title=work['title'], declared_scope=SCOPE,
                source=source_binding(acquisition), reviewed_source_packet_sha256=ROOT_REVIEW_SHA,
                reviewed_header_sha256=MASTER_SHA, metadata_proposal_sha256=EVIDENCE_SHA,
                original_five=ORIGINAL_FILES, source_tomes=3, complete_authored_works=1,
                stage_review_at=at, rights_and_publication='not authorized by this record')


def prepare(stage, bootstrap=False):
    """Fresh external generation; bootstrap is never installable."""
    insist(EXECUTION_RELEASED, 'L811 execution remains coordinator-held')
    from ocd_kernel.reconstruction import SourceManifest, CandidatePackage
    from ocd_kernel.tei.validate import validate_file
    from ocd_kernel.tei.acceptance import (build_acceptance_record, make_file_binding,
        write_acceptance, validate_acceptance, PROMOTED_MASTER_REASON)
    from ocd_kernel.tei.install_accepted import _files, _validate_promoted_tree, _validate_state_transition
    stage=resolve_path(stage,strict=False)
    insist(stage==resolve_path(BOOTSTRAP_STAGE if bootstrap else STAGE,strict=False)
           and not io_path(stage).exists(), 'Exact fresh L811 external stage required')
    work,acquisition=records();revision=reviewed_revision();reader=reviewed_reader()
    fresh,process=source_gate(stage.parent/(stage.name+'-source-readback.json'),
                              stage.parent/(stage.name+'-source-process.json'))
    source=SourceManifest.load(ROOT/HOME/'source-manifest.json',repository_root=ROOT)
    package=CandidatePackage.load(PACKAGE)
    insist(package.sha256==PACKAGE_SHA and digest(package.path/'content.tei.xml')==TEI_SHA,
           'Current frozen source package differs')
    io_path(stage).mkdir(parents=True)
    # Maintained acquisition/scope validation reads actual source members while
    # building acceptance, so those exact authorities must exist beforehand.
    for authority in source.record['authorities']:
        copy(ROOT,stage,Path(authority['path']))
    copy(ROOT,stage,HOME/'source-manifest.json')
    for relative in ORIGINAL_FILES:
        copy(ROOT,stage,WORK/relative)
        copy(ROOT,stage,LOG/'retained-canonical-five'/relative)
        write(stage,LANE/'inputs/retained-canonical-five'/relative,
              io_path(ROOT/LOG/'retained-canonical-five'/relative).read_bytes())
    for name in package.member_names:
        write(stage,LANE/'inputs/package'/name,package.member_bytes(name))
    for name,path in [('README.source.md',HOME/'README.source.md'),('identity-proposal.json',IDENTITY_PROPOSAL),
                      ('evidence-routing-proposal.json',EVIDENCE_PROPOSAL),('root-source-review.json',ROOT_REVIEW),
                      ('source-review.json',PROOF)]:
        write(stage,LANE/name,io_path(ROOT/path).read_bytes())
    at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    dump(stage,WORK/'work.json',work)
    dump(stage,LANE/'current-source-assignment.json',assignment(work,acquisition,at))
    master=bound(package.member_bytes('content.tei.xml'),acquisition,revision)
    insist(master==io_path(ROOT/MASTER_PROPOSAL).read_bytes() and sha256(master).hexdigest()==MASTER_SHA,
           'Exact reviewed accepted master recomputation differs')
    candidate=write(stage,LANE/'candidate.tei.xml',master)
    insist(not (errors:=validate_file(candidate)), 'Actual accepted header P5 fails: '+str(errors))
    expected=[dict(path=row['path'],position=position) for position,row in enumerate(acquisition['retained_files'],1)]
    included=[dict(path=row['path'],position=position,bytes=row['bytes'],sha256=row['sha256'],scope=row['scope'])
              for position,row in enumerate(acquisition['retained_files'],1)]
    # This is a completed source subprocess, not the unfinished prepare CLI.
    command=subprocess.list2cmdline(process['command'])
    source_exit=process['exit_code']
    common=dict(identity=identity(),source=source_binding(acquisition),candidate=make_file_binding(stage,candidate),
                scope=SCOPE,accepted_scope=dict(kind='work',declared=SCOPE),
                expected_members=expected,included_members=included,excluded_members=[],missing_members=[],unknown_members=[],
                source_manifest_sha256=source.sha256,candidate_package_sha256=package.sha256,
                source_proof_sha256=PROOF_SHA,root_source_review_sha256=ROOT_REVIEW_SHA,
                representation_revision=revision,staged_at=at)
    source_accounting=dump(stage,LANE/'source-accounting.json',common|dict(
        scope=acquisition['source_scope'],source_sha256=acquisition['source_sha256'],
        source_bytes=acquisition['source_bytes'],current_source_check=fresh,current_source_process=process))
    technical=dict(producer=dict(id='ocd-l811-reviewed-header-and-stable-metadata-install'),
        checker=dict(id=source.record['validator']['id']),
        shared_assumptions=['Reviewed source repair grammar and namespace conventions; acceptance binding and schemas are maintained contracts. Native row serialization/schema are shared; independent node observation uses stdlib ET versus producer lxml.'],
        independent_corroboration='Fresh isolated complete actual three-tome source and original-document inverse; reviewed finite source challenges and two exact six-member replays. Exact accepted header full-source byte inverse and complete text byte conservation. Maintained accepted native reader is separately projected and independently verified.')
    for name in ('validation','accounting','fidelity','reproducibility','schema','closure'):
        path=dump(stage,LANE/(name+'.json'),common|dict(status='pass',command=command,exit_code=source_exit,claim=name,
            current_source_check=fresh,current_source_process=process, source_proof=make_file_binding(stage,stage/LANE/'source-review.json'),
            source_converter=dict(source.record['converter']),header_binding_implementation_sha256=digest(Path(__file__)),
            command_scope='Actual completed isolated source process; header byte inverse and P5 below are in-process assertions, not a completed outer prepare CLI.',
            in_process_assertions=['Exact reviewed accepted header recomputation and full original candidate byte inverse',
                                   'Complete reviewed text/body/suffix byte conservation','Actual accepted header P5 validation'],
            exact_accepted_header_inverse=True,complete_text_bytes_unchanged=True))
        technical[name]=dict(path=path,status='pass',command=command,exit_code=source_exit)
    coverage=['Complete three-tome retained digital work, all literal Ps_1 through Ps_150 labels and additional sections',
              'All 63218 raw-source carriers and57271 attributes, whole source hierarchy/mixed text/attachments and three source headers',
              'Apparatus, lemma, variant readings, witnesses, German prefaces and located administration',
              'Source quality draft/draft/approved, work-in-progress I/II and qualified literal URI contexts',
              'Exact accepted ordered header and full source-document inverse; unchanged complete text/body bytes',
              'Five current metadata facts, resolving evidence pointers, unchanged stable IDs/acquisition/descriptor and original five-file lineage']
    review=dict(reviewer='agent:eusebius-l811-complete-retained-source-review',reviewed_at=at,
        coverage=dict(status='complete',declared=SCOPE,reached=coverage,inspected=coverage,unreviewed=[]),
        source_quality_uncertainty=['Completeness is exact scoped electronic witness coverage, not a finished printed critical edition.',
            'Source I/II explicitly work in progress; III approved; source labels remain Greek-source literals.',
            'Unbound witness/reference literals remain qualified; no fabricated anchors, URI base or Hebrew-number inference.'],
        discrepancies=['One source @wit trailing space restored; three complete source administration branches added from exact retained XML.',
            'Legacy English metadata is corrected to Greek with German prefaces; opaque stable IDs retained.'],
        unreviewed_residuals=['Human/printed critical collation, local-jurisdiction rights clearance and publication; the native row is a labeled critical inventory, not a preferred reading.'])
    review_path=dump(stage,LANE/'review.json',common|review)
    decision=dict(source_local_disposition='Agent accepts the exact complete retained three-tome electronic work and the bounded source-backed repairs; source quality and literal reference limits remain visible.',blockers=[],
        agent_assessment=dict(status='accepted',actor=review['reviewer'],assessed_at=at,supported_scope=SCOPE,
            unresolved_claims=[],unassessed_stronger_claims=['human acceptance','finished printed critical edition','Hebrew Psalm normalization','local-jurisdiction rights clearance','publication']),
        human_decision=dict(status='not-recorded'))
    record=build_acceptance_record(stage,identity=identity(),candidate_path=candidate,
        source_accounting_path=source_accounting,
        scope=dict(kind='work',declared=SCOPE,expected_members=expected,included_members=included,excluded_members=[]),
        technical=technical,review=review|dict(report_path=review_path),representation_revision=revision,decision=decision)
    master_path=write(stage,ED/'master.tei.xml',master)
    record['promotion']=dict(record['promotion'])|dict(status='promoted',promoted_at=at,master=make_file_binding(stage,master_path))
    write_acceptance(stage/ED/'acceptance.json',record)
    write(stage,WORK/'SOURCE_CREDIT.md',io_path(ROOT/LOG/'retained-canonical-five/SOURCE_CREDIT.md').read_bytes()+CREDIT_APPEND)
    dump(stage,WORK/'state.json',proposed_state(at,PROMOTED_MASTER_REASON))
    for path in sorted(dependency_paths(bootstrap)):
        if not io_path(stage/path).exists():copy(ROOT,stage,path)
    validate_metadata(stage);validate_acceptance(stage/ED/'acceptance.json',root=stage)
    _validate_promoted_tree(stage,stage/WORK,work_id=WORK_ID)
    _validate_state_transition(ROOT/WORK,stage/WORK,existed=True,replacement=False,
        accepted_evidence_by_edition={EDITION:((ED/'master.tei.xml').as_posix(),(ED/'acceptance.json').as_posix())})
    gate=projection_gate(stage,stage/ED/'acceptance.json')
    # Reader modules may load lazily; capture their paths after actual execution.
    dependencies=dependency_paths(bootstrap)
    for path in sorted(dependencies):
        if not io_path(stage/path).exists():copy(ROOT,stage,path)
    receipt=dict(contract='ocd-l811-accepted-stage-v1',status='staged-only',identity=identity(),work_id=WORK_ID,
        complete_works=1,source_tomes=3,target_root=resolve_path(ROOT,strict=True).as_posix(),stage_path=stage.as_posix(),
        staged_at=at,revision=revision,before=ORIGINAL_FILES,after=_files(stage/WORK),
        source_manifest_sha256=source.sha256,package_sha256=package.sha256,source_proof_sha256=PROOF_SHA,
        master_sha256=digest(master_path),acceptance_sha256=digest(stage/ED/'acceptance.json'),
        projection_gate=gate,reader_application=reader,bootstrap=bootstrap,dependency_files={p.as_posix():digest(ROOT/p) for p in sorted(dependencies)},
        acceptance_capture_sha256=None if bootstrap else digest(ROOT/CAPTURE))
    insist(set(receipt['after'])==allowed_paths() and len(receipt['after'])==33,'Exact33 L811 generation fence differs')
    dump(stage,Path('stage-receipt.json'),receipt)
    if not bootstrap:closed_execution_gate(receipt)
    return dict(status='staged-only',stage_path=stage.as_posix(),receipt_sha256=digest(stage/'stage-receipt.json'),
                after_files=33,master_sha256=MASTER_SHA,bootstrap=bootstrap,installable=not bootstrap)


def preflight(stage,pin,root=ROOT):
    insist(EXECUTION_RELEASED,'L811 execution remains coordinator-held')
    from ocd_kernel.reconstruction import CandidatePackage
    from ocd_kernel.tei.acceptance import validate_acceptance,PROMOTED_MASTER_REASON
    from ocd_kernel.tei.install_accepted import _files
    insist(isinstance(pin,str) and len(pin)==64 and all(c in '0123456789abcdef' for c in pin)
           and digest(Path(stage)/'stage-receipt.json')==pin,'Immutable reviewed stage receipt differs')
    receipt=read(Path(stage)/'stage-receipt.json');root,stage=task_roots(root,stage,receipt)
    insist(receipt['contract']=='ocd-l811-accepted-stage-v1' and receipt['status']=='staged-only'
           and receipt['identity']==identity() and receipt['work_id']==WORK_ID and receipt['complete_works']==1
           and receipt['source_tomes']==3 and receipt['bootstrap'] is False,'Exact installable L811 stage scope differs')
    insist(receipt['reader_application']==reviewed_reader(),'Exact stage reader application binding differs')
    original_five(root)
    insist(receipt['before']==ORIGINAL_FILES and set(receipt['after'])==allowed_paths() and len(receipt['after'])==33
           and _files(stage/WORK)==receipt['after'],'Exact frozen stage33 generation differs')
    insist(receipt['dependency_files']=={p.as_posix():digest(ROOT/p) for p in sorted(dependency_paths())},
           'Exact observed/authority dependency set differs')
    for path,pin_value in receipt['dependency_files'].items():
        insist(digest(stage/path)==pin_value,'Staged dependency bytes differ: '+path)
    frozen=CandidatePackage.load(PACKAGE);retained=CandidatePackage.load(stage/LANE/'inputs/package')
    insist(frozen.sha256==retained.sha256==receipt['package_sha256']==PACKAGE_SHA
           and all(frozen.member_bytes(name)==retained.member_bytes(name) for name in frozen.member_names)
           and receipt['source_manifest_sha256']==SOURCE_SHA and receipt['source_proof_sha256']==PROOF_SHA,
           'Exact six-member source/proof package differs')
    tag=uuid4().hex
    source_gate(ROOT/LOG/('preflight-source-'+tag+'.json'),ROOT/LOG/('preflight-source-process-'+tag+'.json'))
    work,acquisition=validate_metadata(stage);revision=reviewed_revision()
    master=bound(frozen.member_bytes('content.tei.xml'),acquisition,revision)
    insist(receipt['revision']==revision and digest(stage/ED/'master.tei.xml')==receipt['master_sha256']==MASTER_SHA
           and io_path(stage/ED/'master.tei.xml').read_bytes()==master==io_path(stage/LANE/'candidate.tei.xml').read_bytes()
           and digest(stage/ED/'acceptance.json')==receipt['acceptance_sha256'],'Exact accepted header/body/acceptance differs')
    insist(read(stage/WORK/'state.json')==proposed_state(receipt['staged_at'],PROMOTED_MASTER_REASON)
           and read(stage/LANE/'current-source-assignment.json')==assignment(work,acquisition,receipt['staged_at']),
           'Exact preserved state/reason/current assignment differs')
    for name,path in [('README.source.md',HOME/'README.source.md'),('identity-proposal.json',IDENTITY_PROPOSAL),
                      ('evidence-routing-proposal.json',EVIDENCE_PROPOSAL),('root-source-review.json',ROOT_REVIEW),('source-review.json',PROOF)]:
        insist(io_path(stage/LANE/name).read_bytes()==io_path(ROOT/path).read_bytes(),'Staged authority evidence differs: '+name)
    accepted=validate_acceptance(stage/ED/'acceptance.json',root=stage)
    insist(accepted['representation_revision']==revision and accepted['promotion']['status']=='promoted',
           'Actual acceptance revision/status differs')
    insist(projection_gate(stage,stage/ED/'acceptance.json')==receipt['projection_gate'],'Current maintained reader differs')
    closed_execution_gate(receipt)
    return receipt


def acceptance_execution_policy(capture, dependency_files):
    """Captured execution rows alone admit code; authority pins do not admit imports."""
    insist(capture['status'] == 'pass' and capture['identity'] == identity(), 'Actual accepted execution capture differs')
    forbidden = {resolve_path(ROOT / p, strict=False) for p in SOURCE_PROCESS_ONLY}
    allowed = {}
    for row in capture['first_party_files']:
        relative = Path(row['path'])
        insist(not relative.is_absolute() and '..' not in relative.parts,
               'Executed first-party row must be a canonical relative path')
        p = resolve_path(ROOT / row['path'], strict=True)
        canonical = resolve_path(ROOT, strict=True)
        library = resolve_path(LIBRARY, strict=True)
        insist(p.is_relative_to(canonical) or p.is_relative_to(library),
               'Executed first-party path outside checkout/physical Library')
        if p.is_relative_to(library):
            insist(p.relative_to(library).parts[0] in {'raw', 'reports', 'exports'},
                   'Executed physical Library path has no canonical junction alias')
        insist(p not in forbidden and dependency_files.get(row['path']) == row['sha256']
               and digest(p) == row['sha256'] and io_path(p).stat().st_size == row['bytes'],
               'Executed path excluded or dependency pin differs: ' + row['path'])
        insist(p not in allowed, 'Duplicate physical acceptance execution path')
        allowed[p] = row['sha256']
    external = {}
    for row in capture['external_runtime_files']:
        p = resolve_path(Path(row['path']), strict=True)
        insist(not p.is_relative_to(resolve_path(ROOT, strict=True))
               and not p.is_relative_to(resolve_path(LIBRARY, strict=True)),
               'First-party path mislabeled external runtime')
        insist(p not in external and digest(p) == row['sha256']
               and io_path(p).stat().st_size == row['bytes'],
               'External runtime changed or physical duplicate: ' + row['path'])
        external[p] = row['sha256']
    executable = resolve_path(Path(sys.executable), strict=True)
    insist(resolve_path(Path(capture['python_executable']), strict=True) == executable
           and executable in external, 'Exact captured Python executable missing or changed')
    return allowed, external


def closed_execution_gate(receipt):
    """Check all captured files (loaded or not) and every actual module/executable."""
    insist(digest(ROOT / CAPTURE) == receipt['acceptance_capture_sha256'],
           'Immutable accepted execution capture changed')
    capture = read(ROOT / CAPTURE)
    for relative, pin in receipt['dependency_files'].items():
        insist(digest(ROOT / relative) == pin, 'Frozen dependency changed: ' + relative)
    allowed, external = acceptance_execution_policy(capture, receipt['dependency_files'])
    root = resolve_path(ROOT, strict=True)
    library = resolve_path(LIBRARY, strict=True)
    observed = {}
    for module in sys.modules.copy().values():
        filename = getattr(module, '__file__', None)
        if not filename:
            continue
        p = resolve_path(Path(filename), strict=True)
        first_party = p.is_relative_to(root) or p.is_relative_to(library)
        expected = allowed if first_party else external
        insist(p in expected and digest(p) == expected[p],
               'Unadmitted or changed actual acceptance execution path: ' + p.as_posix())
        observed[p.as_posix()] = expected[p]
    executable = resolve_path(Path(sys.executable), strict=True)
    insist(executable in external and digest(executable) == external[executable],
           'Actual acceptance executable changed')
    return dict(first_party_admitted=len(allowed), external_admitted=len(external),
                actual_observed=observed, python_executable=executable.as_posix())


def task_roots(root, stage, receipt):
    """Only exact canonical or task fixture roots, with two-way containment guards."""
    canonical = resolve_path(ROOT, strict=True)
    fixture = resolve_path(FIXTURE, strict=False)
    actual_root = resolve_path(Path(root), strict=True)
    insist(actual_root in {canonical, fixture}, 'Arbitrary install root rejected')
    actual_stage = resolve_path(Path(stage), strict=True)
    insist(actual_stage != actual_root and not actual_stage.is_relative_to(actual_root)
           and not actual_root.is_relative_to(actual_stage), 'Stage/root containment collision')
    expected_stage = resolve_path(STAGE if actual_root == canonical else FIXTURE_STAGE, strict=True)
    insist(actual_stage == expected_stage, 'Only exact frozen task stage is permitted')
    if actual_root == fixture:
        marker = read(actual_root / FIXTURE_MARKER)
        insist(marker == dict(contract='ocd-l811-accepted-install-fixture-v1',
                              work_id=WORK_ID, root=fixture.as_posix()),
               'Exact task fixture marker missing or changed')
    insist(receipt['target_root'] == actual_root.as_posix()
           and receipt['stage_path'] == actual_stage.as_posix(),
           'Immutable receipt root/stage bindings differ')
    target = resolve_path(actual_root / WORK, strict=True)
    source = resolve_path(actual_stage / WORK, strict=True)
    insist(target == actual_root / WORK and source == actual_stage / WORK
           and target.is_relative_to(actual_root) and source.is_relative_to(actual_stage)
           and not target.is_relative_to(source) and not source.is_relative_to(target),
           'Work/source physical paths escape task roots or collide')
    return actual_root, actual_stage


def commit_reviewed_generation(root, stage, receipt, *, expected_receipt_sha256,
                               fail_at=None):
    """Exact existing-work delta under both locks and maintained commit journal."""
    from contextlib import ExitStack
    from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
    from ocd_kernel.tei.install_accepted import (_files, _commit_generation,
                                               _validate_promoted_tree, _validate_state_transition)
    insist(EXECUTION_RELEASED, 'L811 execution remains coordinator-held')
    insist(sha256(enc(receipt)).hexdigest() == expected_receipt_sha256,
           'Immutable reviewed stage receipt differs')
    root, stage = task_roots(root, stage, receipt)
    insist(receipt['before'] == ORIGINAL_FILES
           and set(receipt['after']) == allowed_paths(), 'Exact L811 transaction fence differs')
    source = stage / WORK
    target = root / WORK
    insist(_files(source) == receipt['after'], 'Entire staged generation differs')
    with ExitStack() as locks:
        for lock_target in sorted({target, source}, key=lambda p: p.as_posix()):
            locks.enter_context(acquire_jsonl_lock(lock_target))
        insist(preflight(stage,expected_receipt_sha256,root)==receipt,
               'Immutable exact preflight differs under target/source locks')
        insist(_files(target) == ORIGINAL_FILES, 'Canonical five-file preimages changed')
        work, acquisition = validate_metadata(stage)
        insist(_files(source) == receipt['after'], 'Stage changed under held locks')
        original = io_path(PACKAGE / 'content.tei.xml').read_bytes()
        insist(io_path(stage / ED / 'master.tei.xml').read_bytes() == bound(original, acquisition, REVISION),
               'Whole accepted header/body recomputation differs')
        new_records = _validate_promoted_tree(stage, source, work_id=WORK_ID)
        insist(len(new_records) == 1 and new_records[0]['identity'] == identity(),
               'Exactly one approved stable edition acceptance required')
        accepted_evidence = {EDITION: ((ED / 'master.tei.xml').as_posix(),
                                       (ED / 'acceptance.json').as_posix())}
        _validate_state_transition(target, source, existed=True, replacement=False,
                                   accepted_evidence_by_edition=accepted_evidence)
        closed_execution_gate(receipt);observed={}
        expected_state=read(source/'state.json')
        expected_credit=io_path(source/'SOURCE_CREDIT.md').read_bytes()
        expected_master=io_path(stage/ED/'master.tei.xml').read_bytes()
        def checkpoint(label):
            if fail_at is not None:
                fail_at(label)
            if label=='after-new-live':
                closed_execution_gate(receipt)
            if label=='after-validated':
                from ocd_kernel.tei.acceptance import validate_acceptance
                from ocd_kernel.library.state import validate_state
                insist(_files(target)==receipt['after'] and _files(source)==receipt['after'],
                       'Entire installed/source generation differs after validation')
                accepted=validate_acceptance(root/ED/'acceptance.json',root=root)
                validate_state(target/'state.json',root=root)
                insist(read(target/'work.json')==work and read(target/'state.json')==expected_state
                       and io_path(target/'SOURCE_CREDIT.md').read_bytes()==expected_credit
                       and io_path(root/ED/'master.tei.xml').read_bytes()==expected_master
                       and accepted['representation_revision']==receipt['revision']
                       and digest(root/ACQ)==ORIGINAL_FILES[ACQ.relative_to(WORK).as_posix()]
                       and digest(root/DESCRIPTOR)==ORIGINAL_FILES[DESCRIPTOR.relative_to(WORK).as_posix()],
                       'Installed exact metadata/state/header/acquisition conservation differs')
                inverse_header(expected_master,original,acquisition,receipt['revision'])
                insist(projection_gate(root,root/ED/'acceptance.json')==receipt['projection_gate'],
                       'Installed actual maintained native reader differs')
                observed.update(closed_execution_gate(receipt))
        result=_commit_generation(root, target, source, work_id=WORK_ID,
                                  before=ORIGINAL_FILES, after=receipt['after'],
                                  existed=True, replacement=False,
                                  operation_kind='l811-reviewed-stable-metadata-initial-acceptance',
                                  result_status='installed-and-validated', accepted_editions=1,
                                  fail_at=checkpoint)
        return result|dict(executed_runtime=observed,late_execution_gate='pass',
                           exact_source_and_header_conservation=True)


def install(stage,pin,root=ROOT,fail_at=None):
    receipt=preflight(stage,pin,root)
    return commit_reviewed_generation(root,stage,receipt,expected_receipt_sha256=pin,fail_at=fail_at)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','preflight','install'])
    parser.add_argument('stage',type=Path)
    parser.add_argument('--receipt-sha256')
    parser.add_argument('--bootstrap',action='store_true')
    args=parser.parse_args()
    if args.action=='prepare':result=prepare(args.stage,args.bootstrap)
    elif args.action=='preflight':result=preflight(args.stage,args.receipt_sha256)
    else:result=install(args.stage,args.receipt_sha256)
    print(enc({k:v for k,v in result.items() if k not in
               ('after','before','dependency_files','installed_files','previous_files','executed_runtime')}).decode(),end='')
