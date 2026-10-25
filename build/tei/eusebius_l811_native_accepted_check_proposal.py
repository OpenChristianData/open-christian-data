"""Independent L811 maintained checker proposal; shared row serialization/schema and exact context are declared assumptions. No native producer is imported."""
from hashlib import sha256
from pathlib import Path
import json

from ocd_kernel.lib.path_io import io_path
from ocd_kernel.library._common import PipelineError
from build.tei.eusebius_l811_native_context_proposal import select, PROFILE
from build.tei.eusebius_l811_native_observer_proposal import observe


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def role_text(node):
    if node['kind'] == 'text':
        return node['text']
    role = node['attributes'].get('source_role', '')
    label = '\n[' + role + ']\n' if role in {
        'critical-apparatus', 'lemma', 'variant-reading', 'variant-reading-group',
        'witness-detail', 'retained-header-witness', 'retained-header-bibl'} else ''
    return label + ''.join(role_text(child) for child in node['content'])


def schemas(root):
    return {p: sha256(io_path(Path(root)/p).read_bytes()).hexdigest() for p in
            ('schemas/v2/categories/prose.schema.json', 'schemas/v2/public-row.schema.json',
             'schemas/v2/native-content.schema.json')}


def from_leaf(root, context, leaf):
    structure = dict(kind='source-block', attributes=dict(source_role='complete-retained-critical-work'),
                     content=[leaf['native_header_reference_context'], leaf['native_body']])
    text = '[Source inventory with labeled critical roles; no preferred reading inferred]\n' + role_text(structure)
    row = context['identity'] | dict(record_id=context['identity']['edition_id']+':native:l811-complete',
        sequence=1, category='prose', language='grc', representation_revision=context['representation_revision'],
        provenance=dict(edition_title=context['edition_title']), content_format='ocd-native-content-v1',
        locator=dict(kind='native-unit', text_part='body', unit=1), structure=[structure], text=text,
        source_references=[])
    rows = [row]
    from ocd_kernel.projection.categories.prose import _prose_validator
    errors = list(_prose_validator().iter_errors(row))
    if errors:
        raise PipelineError('Actual L811 whole native row schema fails: '+str(errors))
    receipt = dict(scope='tei-document; context derived from validated acceptance', mapping_version=PROFILE,
        authority=context['authority'], master_sha256=context['authority']['master']['sha256'],
        schema_sha256=schemas(root), output_sha256=sha256(canonical(rows).encode()).hexdigest(), row_count=1,
        ordered_tome_labels=leaf['ordered_tome_labels'], reference_census=leaf['reference_census'],
        unresolved_literal_qualification=leaf['unresolved_literal_qualification'],
        private_actual_object_ledger=leaf['private_actual_object_ledger'], private_ledger_sha256=leaf['private_ledger_sha256'],
        source_feature_census=leaf['source_feature_census'], scripture_normalizations=[],
        display_requirement=leaf['display_requirement'], qualifications=leaf['qualifications'], unsupported=[])
    return dict(rows=rows, receipt=receipt)


def verify(root, *, acceptance_path, rows, receipt):
    """Independent ET whole object comparison; no producer module is imported."""
    from ocd_kernel.projection.categories.sermons import _accepted_context
    try:
        context = _accepted_context(root, acceptance_path, expected_category='prose')
        if not select(root, context):
            raise PipelineError('Observed L811 accepted identity differs')
        expected = from_leaf(root, context, observe(io_path(context['edition'].path).read_bytes()))
        if canonical(rows) != canonical(expected['rows']):
            raise PipelineError('Independent L811 actual whole rows differ')
        if canonical(receipt) != canonical(expected['receipt']):
            raise PipelineError('Independent L811 actual whole private receipt differs')
        return []
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as error:
        return [str(error)]
