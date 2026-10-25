"""Focused public-gate checks for the unapplied Beatitudes closure successor."""
import importlib.util
import json
import os
from hashlib import sha256
from pathlib import Path
import shutil
import sys

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError, io_path

ROOT = Path(__file__).resolve().parents[1]
WORK = Path('library/works/watson-beatitudes')
EDITION = WORK/'forms/watson-beatitudes-route-source-form/editions/watson-beatitudes-retained-thml-route'
PROPOSAL = ROOT/'reports/_logs/watson-beatitudes-downstream-preflight-20261002-v1/closure-successor-proposal'
PACKAGE = WORK/'integration/ccel-thml-closure-rebind-v3/current-candidate/package'
SOURCE = Path('raw/ccel/watson/beatitudes.xml')

def digest(raw):
    return sha256(raw).hexdigest()

@pytest.fixture
def current(tmp_path_factory):
    location = os.environ.get('OCD_BEATITUDES_CLOSURE_FIXTURE')
    if not location or not Path(location).is_dir():
        pytest.skip('Configured retained Beatitudes closure fixture unavailable')
    base = Path(location)
    mirror = tmp_path_factory.mktemp('b')/'s'
    shutil.copytree(io_path(base), io_path(mirror))
    module_name = 'owned_beatitudes_proposal_test'
    spec = importlib.util.spec_from_file_location(module_name, io_path(PROPOSAL/'acceptance.after.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    module.SCHEMA_PATH = mirror/'schemas/v2/acceptance.schema.json'
    yield mirror, module
    # Each mutation stays in its private pytest mirror, never the frozen fixture.
    sys.modules.pop(module_name, None)

def validate(current):
    root, module = current
    return module.validate_acceptance(root/EDITION/'acceptance.json', root=root)

def test_current_v3_public_acceptance_preserves_decision_and_master(current):
    root, _ = current
    old = json.loads((root/EDITION/'acceptance.json').read_bytes())
    accepted = validate(current)
    assert accepted['promotion'] == old['promotion']
    assert accepted['decision'] == old['decision']
    assert digest((root/EDITION/'master.tei.xml').read_bytes()) == '07b0070649c6a6b8e6ebbfd300834299dc2d64cc3684e2198fc42dadb82b0aef'

def test_current_closure_mutation_rejects_at_public_gate(current):
    root, _ = current
    path = root/'ocd_kernel/library/acquisitions.py'
    path.write_bytes(path.read_bytes()+b'\n# mutated closure\n')
    with pytest.raises(PipelineError, match='source authority closure is invalid'):
        validate(current)

def test_source_bytes_mutation_rejects_at_public_gate(current):
    root, _ = current
    path = root/SOURCE
    path.write_bytes(path.read_bytes()+b'x')
    with pytest.raises(PipelineError) as caught:
        validate(current)
    assert any(s in str(caught.value).lower() for s in ['source', 'retained', 'hash', 'bytes'])

def test_package_integrity_mutation_rejects_at_public_gate(current):
    root, _ = current
    path = root/PACKAGE/'provenance.json'
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(PipelineError, match='independent oracle rejected'):
        validate(current)

def test_old_v2_closure_still_fails_not_silently_admitted(current):
    root, module = current
    manifest = root/module.BEATITUDES_ACCEPTANCE_MANIFEST
    old = (root/'sources/structured-text/watson-beatitudes/watson-beatitudes.source-manifest-v2.json').read_bytes()
    manifest.write_bytes(old)
    module.BEATITUDES_ACCEPTANCE_MANIFEST_SHA = digest(old)
    with pytest.raises(PipelineError, match='source authority closure is invalid'):
        validate(current)

def test_manifest_substitution_fails_exact_manifest_guard(current):
    root, module = current
    path = root/module.BEATITUDES_ACCEPTANCE_MANIFEST
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(PipelineError, match='source manifest differs'):
        validate(current)

def test_wrong_oracle_provenance_fails(current):
    _, module = current
    original = module._beatitudes_oracle()
    def wrong(*args):
        return original(*args)
    wrong.oracle_id = 'unbound-oracle'
    wrong.oracle_version = '1'
    module._beatitudes_oracle = lambda: wrong
    with pytest.raises(PipelineError, match='independent oracle rejected'):
        validate(current)

@pytest.mark.parametrize('mutation', ['wording', 'hierarchy', 'ordered_attribute'])
def test_resealed_semantic_payload_mutations_fail_independent_source_walk(current, mutation):
    root, module = current
    path = root/PACKAGE/'content.tei.xml'
    tree = etree.fromstring(path.read_bytes())
    ns = {'t':'http://www.tei-c.org/ns/1.0'}
    p = tree.xpath('/t:TEI/t:text//t:p', namespaces=ns)[0]
    if mutation == 'wording':
        p.text = (p.text or '')+' INVENTED'
    elif mutation == 'hierarchy':
        parent = p.getparent()
        parent.remove(p)
    else:
        p.set('rend', 'invented-source-style')
    changed = etree.tostring(tree, xml_declaration=True, encoding='utf-8')
    assert changed != path.read_bytes()
    path.write_bytes(changed)
    manifest = root/PACKAGE/'manifest.json'
    package = json.loads(manifest.read_bytes())
    member = next(x for x in package['members'] if x['name']=='content.tei.xml')
    member.update(bytes=len(changed), sha256=digest(changed))
    raw = (json.dumps(package,ensure_ascii=False,separators=(',',':'),sort_keys=True)+'\n').encode('utf-8')
    manifest.write_bytes(raw)
    module.BEATITUDES_ACCEPTANCE_PACKAGE_SHA = digest(raw)
    # Correctly resealed integrity plus bound hash passes its earlier gates;
    # the literal source traversal must identify this semantic corruption.
    with pytest.raises(PipelineError, match='independent oracle rejected') as caught:
        validate(current)
    assert isinstance(caught.value.__cause__, ValueError)
    assert not any(word in str(caught.value.__cause__) for word in ['bytes drifted','manifest differs','binding mismatch'])

def test_undeclared_selection_fails_exact_acquisition_binding(current):
    root, _ = current
    path = root/EDITION/'acquisitions/watson-beatitudes-retained-source.json'
    record = json.loads(path.read_bytes())
    record['source_selection']['selection_id'] = 'unbound-selection'
    path.write_text(json.dumps(record),encoding='utf-8')
    with pytest.raises(PipelineError):
        validate(current)
