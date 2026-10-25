"""Source-bound seven-division projection for the accepted LIB-040 Harmony."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection.categories.sermons import _accepted_context


PROFILE = 'ocd-lib040-harmony-seven-source-divisions-v1'
UNITS = ('i', 'ii', 'iii', 'I', 'II', 'III', 'IV')
SOURCE = 'raw/ccel/npnf1/npnf106.xml'
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bound_json(root: Path, reference: dict):
    path = io_path(root / reference['path'])
    raw = path.read_bytes()
    if _sha(raw) != reference['sha256'] or len(raw) != reference['bytes']:
        raise PipelineError('Harmony projection acceptance evidence binding differs')
    return json.loads(raw)


def _context(root: Path, acceptance_path: Path):
    context = _accepted_context(root, acceptance_path, expected_category='prose')
    accepted = context['accepted']
    identity = accepted['identity']
    if identity != {
        'work_id': 'augustine-harmony-of-gospels',
        'textual_form_id': 'augustine-harmony-of-gospels-ccel-npnf106-retained-en',
        'edition_id': 'augustine-harmony-of-gospels-ccel-npnf106-electronic',
        'acquisition_id': 'augustine-harmony-of-gospels-ccel-npnf106-acquired',
    }:
        raise PipelineError('Harmony projection identity differs')
    accounting_ref = accepted['source']['accounting']
    accounting = _bound_json(root, accounting_ref)
    if accounting.get('projection_profile') != PROFILE or accounting.get('projection_units') != list(UNITS):
        raise PipelineError('Harmony projection profile or units differ')
    if accounting.get('selected_root') != 'vi' or accounting.get('source', {}).get('source_path') != SOURCE:
        raise PipelineError('Harmony projection retained source identity differs')
    source_bytes = io_path(root / SOURCE).read_bytes()
    if _sha(source_bytes) != accounting['source_sha256']:
        raise PipelineError('Harmony projection retained source hash differs')
    source = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    source_roots = [node for node in source.iter('div1') if node.get('id') == 'vi']
    if len(source_roots) != 1:
        raise PipelineError('Harmony retained work root differs')
    source_root = source_roots[0]
    source_root_hash = _sha(etree.tostring(source_root, method='c14n'))
    if source_root_hash != accounting['source_root_c14n_sha256']:
        raise PipelineError('Harmony retained work root hash differs')
    source_units = list(source_root)
    if [(unit.tag, unit.get('id'), unit.get('n')) for unit in source_units] != [
        ('div2', f'vi.{part}', number) for part, number in zip(('i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii'), UNITS)
    ]:
        raise PipelineError('Harmony retained seven divisions differ')
    # The acceptance validator binds these technical sidecars; this profile
    # follows the chain to the independently oracle-checked family TEI.
    technical = _bound_json(root, accepted['technical']['accounting'])
    evidence = technical['evidence']
    inputs = io_path(root / accounting_ref['path']).parent / 'inputs'
    validation_bytes = io_path(inputs / 'validation.json').read_bytes()
    if _sha(validation_bytes) != evidence['family_validation_sha256']:
        raise PipelineError('Harmony family validation hash differs')
    validation = json.loads(validation_bytes)
    if technical.get('status') != 'pass' or validation.get('status') != 'pass' or validation.get('findings') != [] or validation.get('attestation', {}).get('oracle_id') != 'ocd-lib040-source-to-tei-oracle' or validation['attestation'].get('status') != 'pass':
        raise PipelineError('Harmony family source-led oracle evidence differs')
    if validation.get('candidate_sha256') != accounting['family_package_sha256'] or validation.get('source_manifest_sha256') != evidence['source_manifest_sha256']:
        raise PipelineError('Harmony family candidate or source manifest binding differs')
    family_path = inputs / 'family-content.tei.xml'
    family_bytes = io_path(family_path).read_bytes()
    if _sha(family_bytes) != evidence['family_tei_sha256']:
        raise PipelineError('Harmony oracle-checked family TEI hash differs')
    family = etree.fromstring(family_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    family_works = [node for node in family.iter(NS + 'div') if node.get(XML + 'id') == 'lib040-augustine-harmony-of-gospels']
    if len(family_works) != 1:
        raise PipelineError('Harmony family work division differs')
    family_units = list(family_works[0])[1:]
    if len(family_units) != len(UNITS):
        raise PipelineError('Harmony family unit count differs')
    family_hashes = [_sha(etree.tostring(unit, method='c14n')) for unit in family_units]
    return context, source_root_hash, family_hashes


def _projection_tree(context, source_root_hash, family_hashes):
    master_bytes = io_path(context['edition'].path).read_bytes()
    master = etree.fromstring(master_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    body = master.find(NS + 'text/' + NS + 'body')
    if body is None or len(body) != 1 or (body.text or '').strip() or any((node.tail or '').strip() for node in body):
        raise PipelineError('Harmony accepted master body differs')
    work = body[0]
    if work.tag != NS + 'div' or work.get('n') != 'vi' or work.get('type') != 'work' or work.get('subtype') != 'augustine-harmony-of-gospels' or (work.text or '').strip():
        raise PipelineError('Harmony accepted work division differs')
    children = list(work)
    if len(children) != 8 or children[0].tag != NS + 'head' or not ''.join(children[0].itertext()).strip():
        raise PipelineError('Harmony work heading or children differ')
    units = children[1:]
    if [(unit.tag, unit.get(XML + 'id'), unit.get('n')) for unit in units] != [
        (NS + 'div', f'lib040-npnf106-vi.{part}', number)
        for part, number in zip(('i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii'), UNITS)
    ] or [unit.get('type') for unit in units] != [None, None, None, 'Book', 'Book', 'Book', 'Book']:
        raise PipelineError('Harmony accepted seven divisions differ')
    if any((unit.tail or '').strip() for unit in children):
        raise PipelineError('Harmony work boundary text differs')
    # The work-level title is edition metadata; every source div2 is copied intact.
    copy = deepcopy(master)
    copy_body = copy.find(NS + 'text/' + NS + 'body')
    copy_body.remove(copy_body[0])
    for unit in units:
        copy_body.append(deepcopy(unit))
    unit_hashes = [_sha(etree.tostring(unit, method='c14n')) for unit in units]
    if unit_hashes != family_hashes:
        raise PipelineError('Harmony accepted units differ from oracle-checked family TEI')
    binding = {
        'profile': PROFILE,
        'accepted_master_sha256': _sha(master_bytes),
        'retained_work_root_c14n_sha256': source_root_hash,
        'work_head_c14n_sha256': _sha(etree.tostring(children[0], method='c14n')),
        'unit_numbers': list(UNITS),
        'unit_c14n_sha256': unit_hashes,
    }
    return etree.tostring(copy, encoding='utf-8', xml_declaration=True), binding


def _native_projection(context, synthetic: bytes):
    with tempfile.TemporaryDirectory(prefix='ocd-harmony-') as folder:
        path = Path(folder) / 'projection.tei.xml'
        path.write_bytes(synthetic)
        result = native_documents.project_document(
            path, identity=context['identity'], language=context['language'],
            representation_revision=context['representation_revision'],
            edition_title=context['edition_title'], _allow_acceptance_metadata=True,
            category='prose',
        )
        return result


def project(root: Path, *, acceptance_path: Path):
    """Project exactly the seven retained source divisions under accepted authority."""
    context, source_root_hash, family_hashes = _context(root, acceptance_path)
    synthetic, binding = _projection_tree(context, source_root_hash, family_hashes)
    result = _native_projection(context, synthetic)
    if len(result['rows']) != len(UNITS):
        raise PipelineError('Harmony projection row count differs')
    result['receipt']['scope'] = 'accepted LIB-040 Harmony seven retained source divisions'
    result['receipt']['authority'] = context['authority']
    result['receipt']['source_division_binding'] = binding
    return result


def verify(root: Path, *, acceptance_path: Path, rows, receipt):
    """Independently check accepted authority, source boundaries, rows and receipt."""
    try:
        context, source_root_hash, family_hashes = _context(root, acceptance_path)
        synthetic, binding = _projection_tree(context, source_root_hash, family_hashes)
        if not isinstance(receipt, dict):
            return ['Harmony projection receipt must be an object']
        errors = []
        if receipt.get('scope') != 'accepted LIB-040 Harmony seven retained source divisions':
            errors.append('Harmony projection scope differs')
        if receipt.get('authority') != context['authority']:
            errors.append('Harmony projection accepted authority differs')
        if receipt.get('source_division_binding') != binding:
            errors.append('Harmony projection source division binding differs')
        native_receipt = dict(receipt)
        for key in ('authority', 'source_division_binding'):
            native_receipt.pop(key, None)
        native_receipt['scope'] = native_documents.SCOPE
        with tempfile.TemporaryDirectory(prefix='ocd-harmony-verify-') as folder:
            path = Path(folder) / 'projection.tei.xml'
            path.write_bytes(synthetic)
            errors.extend(native_documents.verify_document(
                path, rows, native_receipt, identity=context['identity'],
                language=context['language'], representation_revision=context['representation_revision'],
                edition_title=context['edition_title'], _allow_acceptance_metadata=True, category='prose',
            ))
        if len(rows) != len(UNITS):
            errors.append('Harmony projection must contain seven rows')
        return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [f'Harmony projection verification failed: {exc}']
