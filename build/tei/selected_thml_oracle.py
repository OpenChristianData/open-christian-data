"""Candidate-contract adapter for the independent selected ThML checker."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.library.acquisitions import load_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.reconstruction.contract import _canonical, _validation_authority_bindings
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.selected_thml_check import check_selected_thml
from ocd_kernel.tei.validate import compiled_schema

CLOSURE = (
    'ocd_kernel/tei/selected_thml_check.py',
    'ocd_kernel/library/acquisitions.py',
    'ocd_kernel/library/identities.py',
    'ocd_kernel/library/_common.py',
    'ocd_kernel/lib/storage_topology.py',
    'ocd_kernel/reconstruction/contract.py',
    'ocd_kernel/reconstruction/verifier.py',
    'ocd_kernel/tei/validate.py',
    'schemas/v2/acquisition.schema.json',
    'schemas/v2/work.schema.json',
)


def closure_digest(root):
    rows = [
        dict(path=path, sha256=hashlib.sha256((root / path).read_bytes()).hexdigest())
        for path in CLOSURE
    ]
    return hashlib.sha256(_canonical(rows)).hexdigest()


def _read_json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'{label} is not valid UTF-8 JSON') from exc
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be a JSON object')
    return value


def _validate_expected_accounting(manifest, result: dict) -> None:
    try:
        expected_path = manifest.authority_path('source-accountability')
    except ValueError:
        # Existing selected-ThML fixture consumers have no extra work-local
        # source envelope authority; their raw source walk remains mandatory.
        return
    schema_path = manifest.authority_path('source-accountability-schema')
    expected = _read_json(expected_path.read_bytes(), 'source-accountability authority')
    schema = _read_json(schema_path.read_bytes(), 'source-accountability schema')
    errors = sorted(Draft202012Validator(schema).iter_errors(expected), key=str)
    if errors:
        raise ValueError(f'source-accountability schema failure: {errors[0].message}')
    retained_authority = next(
        item for item in manifest.record['authorities']
        if item['name'] == 'retained-source'
    )
    source_member = expected.get('source_member')
    if source_member != {
        'path': retained_authority['path'],
        'bytes': result['bytes_parsed'],
        'sha256': result['source_sha256'],
        'disposition': 'included as the sole retained source member',
    }:
        raise ValueError('source-accountability retained-member census differs')
    if expected.get('carrier_inventory') != result['source_envelope']:
        raise ValueError('source-accountability carrier inventory differs from retained source')
    if expected.get('body_node_sequence') != result['body_node_sequence']:
        raise ValueError('source-accountability body-node order differs from retained source')
    declared_shell = expected.get('document_shell', {})
    observed_shell = result['document_shell']
    shell_fields = (
        'xml_declaration', 'doctype', 'root_name', 'prolog', 'epilog',
        'comments_and_processing_instructions',
    )
    if any(declared_shell.get(key) != observed_shell.get(key) for key in shell_fields):
        raise ValueError('source-accountability document-shell inventory differs')
    observed_head = [
        {
            'position': row['position'],
            'tag': row['tag'],
            'attributes': row['attributes'],
            'text_sha256': hashlib.sha256(row['text'].encode('utf-8')).hexdigest(),
            'disposition': row['disposition'],
        }
        for row in observed_shell['head_children']
    ]
    if declared_shell.get('head_children') != observed_head:
        raise ValueError('source-accountability ThML-head inventory differs')
    if expected.get('selected_feature_count') != result['checked_elements']:
        raise ValueError('source-accountability selected feature count differs')
    feature_counts = dict(sorted(Counter(row['source_tag'] for row in result['features']).items()))
    if expected.get('selected_feature_counts') != feature_counts:
        raise ValueError('source-accountability selected feature census differs')
    if expected.get('selected_comment_count') != result['selected_comment_count']:
        raise ValueError('source-accountability selected comment count differs')
    if expected.get('document_comment_count') != result['source_comment_count']:
        raise ValueError('source-accountability document comment count differs')

    source = etree.parse(
        str(manifest.authority_path('retained-source')),
        etree.XMLParser(
            resolve_entities=False, no_network=True, recover=False,
            remove_comments=False, remove_pis=False,
        ),
    )
    for claim in expected.get('source_claims', []):
        matches = source.xpath(claim['source_path'])
        if len(matches) != 1:
            raise ValueError(f"source claim path is missing or ambiguous: {claim['source_path']}")
        source_text = ''.join(matches[0].itertext()).strip()
        if (
            claim.get('text_sha256')
            and hashlib.sha256(source_text.encode('utf-8')).hexdigest() != claim['text_sha256']
        ):
            raise ValueError(f"source claim text differs: {claim['source_path']}")
        normalized = ' '.join(source_text.split())
        if claim.get('text') is not None and normalized != ' '.join(claim['text'].split()):
            raise ValueError(f"source claim text differs: {claim['source_path']}")
        if claim.get('excerpt') and ' '.join(claim['excerpt'].split()) not in normalized:
            raise ValueError(f"source claim excerpt differs: {claim['source_path']}")


def _oracle(manifest, candidate):
    manifest.verify()
    acquisition = load_acquisition(manifest.authority_path('acquisition'))
    work = load_work(manifest.authority_path('work'))
    result = check_selected_thml(
        manifest.repository_root,
        acquisition,
        work,
        candidate.path / 'content.tei.xml',
    )

    tei_bytes = candidate.member_bytes('content.tei.xml')
    tei_tree = etree.fromstring(tei_bytes, etree.XMLParser(resolve_entities=False, no_network=True))
    schema = compiled_schema()
    if not schema.validate(tei_tree):
        raise ValueError(f'selected ThML TEI schema failed: {schema.error_log}')

    accountability = _read_json(
        candidate.member_bytes('source-accountability.json'),
        'candidate source-accountability member',
    )
    expected_accounting_fields = {
        'selection_sha256': result['selection_sha256'],
        'units': acquisition['source_selection']['units'],
        'features': result['features'],
        'source_envelope': result['source_envelope'],
        'body_node_sequence': result['body_node_sequence'],
        'document_shell': result['document_shell'],
    }
    for key, expected in expected_accounting_fields.items():
        if accountability.get(key) != expected:
            raise ValueError(f'selected ThML candidate accounting differs: {key}')
    _validate_expected_accounting(manifest, result)

    profile = _read_json(manifest.authority_path('profile').read_bytes(), 'selected-ThML profile')
    expected_questions = profile.get('candidate_questions', [])
    unresolved_lines = candidate.member_bytes('unresolved.jsonl').splitlines()
    unresolved = [
        _read_json(line, 'candidate unresolved item')
        for line in unresolved_lines
    ]
    if unresolved != expected_questions:
        raise ValueError('selected ThML unresolved questions differ from bound profile')

    readme = candidate.member_bytes('README.source.md').decode('utf-8')
    for child in result['document_shell']['head_children']:
        if child['disposition'] == 'reproduced-in-source-readme' and child['text']:
            section = f"### ThML.head/{child['tag']}\n\n{child['text']}"
            if section not in readme:
                raise ValueError('selected ThML source metadata deliverable differs')
    for dependency in acquisition['source_selection']['dependencies']:
        dependency_node = etree.parse(
            str(manifest.authority_path('retained-source')),
            etree.XMLParser(resolve_entities=False, no_network=True),
        ).xpath('//*[@id=$value]', value=dependency['native_id'])
        if len(dependency_node) != 1 or ''.join(dependency_node[0].itertext()) not in readme:
            raise ValueError('selected ThML human-visible source-credit deliverable differs')

    bindings = _validation_authority_bindings(manifest)
    facts = MechanicalFacts(
        validator_implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        validator_import_closure_sha256=closure_digest(manifest.repository_root),
        source_sha256=result['source_sha256'],
        profile_sha256=bindings['profile_sha256'],
        package_schema_sha256=bindings['package_schema_sha256'],
        xsd_sha256=bindings['xsd_sha256'],
        policy_sha256=bindings['policy_sha256'],
        findings=(),
    )
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


_oracle.oracle_id = 'ocd-selected-thml-independent-check'
_oracle.oracle_version = '1'
