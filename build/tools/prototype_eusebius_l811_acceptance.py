"""Released bounded L811 header/P5/inverse or scratch native leaf prototype.

This writes only dated work-local review evidence. It cannot stage or install.
The outer runner retains command/stdout/stderr/exit before checking success.
"""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from build.tools import eusebius_l811_install as install
from ocd_kernel.lib.path_io import io_path


def write(path, value):
    if io_path(path).exists():
        raise FileExistsError('Preserve earlier prototype: ' + str(path))
    io_path(path).parent.mkdir(parents=True, exist_ok=True)
    data = value if isinstance(value, bytes) else install.enc(value)
    io_path(path).write_bytes(data)
    return dict(path=path.as_posix(), bytes=len(data), sha256=sha256(data).hexdigest())


def header():
    from ocd_kernel.tei.validate import validate_file
    from ocd_kernel.tei.acceptance import _tei_facts
    from lxml import etree
    _, acquisition = install.records()
    original = io_path(install.PACKAGE / 'content.tei.xml').read_bytes()
    output = ROOT / install.LOG / 'accepted-header-proposal-v1'
    master = output / 'accepted-representation.tei.xml'
    actual = install.bound(original, acquisition, install.REVISION)
    master_pin = write(master, actual)
    errors = validate_file(master)
    _, facts = _tei_facts(master)
    expected = {**install.identity(), 'source_sha256': acquisition['source_sha256'],
                'sha256': acquisition['source_sha256'], 'source_bytes': str(acquisition['source_bytes']),
                'source_kind': 'retained-member-set', 'representation_revision': install.REVISION['id'],
                'source_url': acquisition['url'], 'source-location': acquisition['source_path'],
                'source-scope': install.SCOPE,
                'revision_changes': json.dumps([install.REVISION], sort_keys=True)}
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(actual, parser)
    ns = {'t': install.NS}
    revision = root.xpath('./t:teiHeader/t:revisionDesc/t:change[@xml:id=$id]', id=install.REVISION['id'], namespaces=ns)
    binding = root.xpath('./t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl[@type="ocd-acceptance-binding"]', namespaces=ns)
    inverse = actual
    for opening, closing in [(b'<bibl xmlns="http://www.tei-c.org/ns/1.0" type="ocd-acceptance-binding">', b'</bibl>'),
                             (b'<change xmlns="http://www.tei-c.org/ns/1.0" xml:id="' + install.REVISION['id'].encode() + b'"', b'</change>')]:
        start = inverse.index(opening)
        end = inverse.index(closing, start) + len(closing)
        inverse = inverse[:start] + inverse[end:]
    passed = (not errors and facts == expected and inverse == original
              and len(revision) == 1 and len(binding) == 1
              and actual.split(b'</teiHeader>', 1)[1] == original.split(b'</teiHeader>', 1)[1])
    receipt = dict(status='pass' if passed else 'failed', contract='ocd-l811-bounded-accepted-header-proposal-v1',
                   identity=install.identity(), revision=install.REVISION, master=master_pin,
                   source_candidate_sha256=install.TEI_SHA, source_package_sha256=install.PACKAGE_SHA,
                   source_manifest_sha256=install.SOURCE_SHA, p5_errors=errors, actual_typed_binding_facts=facts,
                   expected_typed_binding_facts=expected, exact_full_source_tei_byte_inverse=inverse == original,
                   body_text_suffix_bytes_unchanged=actual.split(b'</teiHeader>',1)[1] == original.split(b'</teiHeader>',1)[1],
                   body_suffix_sha256=sha256(actual.split(b'</teiHeader>',1)[1]).hexdigest(),
                   existing_revision_changes_preserved=9, original_canonical_five=install.original_five(),
                   agent_acceptance='not-recorded', canonical_installation='not-executed',
                   qualification='Header proposal only. Source I/II remain draft/work in progress, III approved; rights/human/publication gates separate.')
    pin = write(output / 'proposal-receipt.json', receipt)
    if not passed:
        raise ValueError('Bounded header/P5/inverse/facts proof failed; receipt preserved')
    return dict(status='pass', master=master_pin, receipt=pin)


def leaf():
    from build.tei import eusebius_l811_native_leaf_proposal as leaf
    from jsonschema import Draft202012Validator
    output = ROOT / install.LOG / 'native-leaf-prototype-v2'
    raw = io_path(install.PACKAGE / 'content.tei.xml').read_bytes()
    projected = leaf.proposed_leaf(raw, identity=leaf.IDENTITY, language='grc', category='prose',
                                  collection=None, source_base=None)
    result_pin = write(output / 'scratch-leaf.json', projected)
    schema = install.read(ROOT / 'schemas/v2/native-content.schema.json')
    validator = Draft202012Validator(schema)
    errors = []
    anchors = []
    public_refs = []
    for part in ['native_body', 'native_header_reference_context']:
        errors.extend(str(e) for e in validator.iter_errors(projected[part]))
        def visit(node):
            if node['kind'] == 'text':
                return
            attrs = node['attributes']
            if 'source_anchor' in attrs:
                anchors.append(attrs['source_anchor'])
            annotations = json.loads(attrs.get('source_annotations', '{}'))
            for field, value in annotations.get('fields', {}).items():
                if field in leaf.REFERENCE_ATTRIBUTES:
                    public_refs.extend(token[1:] for token in value.split() if token.startswith('#PgL811'))
            for child in node['content']:
                visit(child)
        visit(projected[part])
    unique = len(anchors) == len(set(anchors))
    missing = sorted(set(public_refs) - set(anchors))
    body_unbound = [row for row in projected['unresolved_literal_qualification'] if row['location'] == 'body']
    passed = not errors and unique and not missing and len(body_unbound) == 199 and len({r['literal'] for r in body_unbound}) == 29
    receipt = dict(status='pass' if passed else 'failed', scratch_only=True, maintained_reader_registered=False,
                   source_candidate_sha256=install.TEI_SHA, scratch_leaf=result_pin,
                   native_schema_errors=errors, reference_census=projected['reference_census'],
                   actual_public_anchor_count=len(anchors), unique_anchors=unique,
                   actual_bound_public_reference_tokens=len(public_refs), missing_public_targets=missing,
                   body_unresolved_literal_occurrences=len(body_unbound), body_unresolved_distinct_literals=len({r['literal'] for r in body_unbound}),
                   actual_body_feature_census=projected['source_feature_census'],
                   private_full_actual_object_rows=len(projected['private_actual_object_ledger']),
                   private_full_actual_object_sha256=projected['private_ledger_sha256'],
                   scripture_normalizations=projected['scripture_normalizations'],
                   independent_native_checker='not-yet-maintained; this is prototype diagnostics, not independent projection verification',
                   original_canonical_five=install.original_five())
    pin = write(output / 'prototype-receipt.json', receipt)
    if not passed:
        raise ValueError('Scratch leaf schema/anchor/literal diagnostic failed; result and receipt preserved')
    return dict(status='pass', receipt=pin, scratch_leaf=result_pin, census=projected['reference_census'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['header', 'leaf'])
    args = parser.parse_args()
    print(json.dumps(header() if args.mode == 'header' else leaf(), sort_keys=True))
