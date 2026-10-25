"""Recheck four saved accepted rows under exactly two reviewed additive freezes."""
from pathlib import Path
from hashlib import sha256
import json
from build.tools.prepare_aquinas_four_current import ROOT, BASE, WORK, EDITION, LOG, canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection import native_content

STAGE_SHA = '7f1fdebfc12ca6a4e21dddf347382917aa97b6e5277c1e693283f024adbd47de'
ALLOWED = {
    'ocd_kernel/projection/categories/native_documents.py': ('b42785aed7a673de68e42f19d2675bb39dfe208e2f3636b1f78afc703ef805c6', 'fb734a9764cbb641f5580f6f5474428c00c6efdddb331fe1e969e5f3ec269bf7'),
    'ocd_kernel/projection/native_content.py': ('f1c83f2af372362405cb696665b320fe4c68191b29b6b70a8fe1320778250c40', '3b2b2c453ae828147a2b3a38ef5bb74eb700c21284fc842f1e36b040ff5086a5'),
    'ocd_kernel/projection/native_content_check.py': ('b5f12fb6db8e010d9a60a413c8fcc16efdb0719589961df46f06448d54f7659c', '403f88e7fa696594cbf9b4d4d7af5ff97ae4f20ef16ad32c0cf2309a46853d42'),
    'schemas/v2/categories/bible.schema.json': ('5908bb5eae8070db4e7cbfec4f208c777b1d77b6ed7f6403b5da8f4ff24fff40', '069ef09c7872b4c3ef750ac261aeba1db8cc974329d978aaae3a727fdc05c9f2'),
}
EXTRA = {'ocd_kernel/projection/categories/prose.py': '2755768f7f33ddb3dd1c09fcbfe9f6fe25bfab7a7707eac9cc68e6b3d6a9e6da', 'ocd_kernel/projection/categories/bible.py': '2c890668641e932d4ada645b787f484e6f579e11b87aa5cc910057115f827780'}
REVIEWS = {'reports/_logs/hodge-vol1-current-reconciliation-20261002-v1/shared-span-proposal/coordinator-reviewed-freeze.json': '68653f66e6e6b2e8cfd3ace97c0968847eabe2570db81d773cd953f16b0fed05', 'reports/_logs/original-douay-zero-chapter-support-20261002-v1/coordinator-reviewed-freeze.json': 'ed3f83d02051862215d550c3db3f897a448204b0cebb7700fdba7ebf5805f6cb'}


def digest(path):
    return sha256(io_path(path).read_bytes()).hexdigest()


def validate_closed_pins(receipt, runtime, schemas):
    old = receipt['runtime_pins'] | receipt['schema_pins']
    new = runtime | schemas
    expected = dict(old)
    for path, (before, after) in ALLOWED.items():
        if old.get(path) != before:
            raise ValueError('Reviewed exact old transition differs: ' + path)
        expected[path] = after
    if new != expected or set(runtime) != set(receipt['runtime_pins']) or set(schemas) != set(receipt['schema_pins']):
        raise ValueError('Additional or unknown staged dependency drift')


def main():
    pin = json.loads((ROOT / BASE / 'stage-pin.json').read_bytes())
    receipt_path = Path(pin['receipt'])
    if pin['receipt_sha256'] != STAGE_SHA or digest(receipt_path) != STAGE_SHA:
        raise ValueError('Frozen dated stage differs')
    receipt = json.loads(receipt_path.read_bytes())
    promoted = receipt_path.parent
    if _files(ROOT / WORK) != receipt['before'] or _files(promoted / WORK) != receipt['after']:
        raise ValueError('Exact five current preimages or twenty-nine staged files differ')
    for path, expected in REVIEWS.items():
        if digest(ROOT / path) != expected or not json.loads(io_path(ROOT / path).read_bytes())['status'].startswith('pass'):
            raise ValueError('Immutable coordinator freeze differs')
    runtime = {p: digest(ROOT / p) for p in receipt['runtime_pins']}
    schemas = {p: digest(ROOT / p) for p in receipt['schema_pins']}
    validate_closed_pins(receipt, runtime, schemas)
    if any(digest(ROOT / p) != h for p, h in EXTRA.items()):
        raise ValueError('Additional reviewed module closure differs')
    source = promoted / WORK / 'integration/aquinas-four-current-v1/stage-projection.json'
    saved = json.loads(source.read_bytes())
    if len(saved['rows']) != 4 or saved['receipt']['master_sha256'] != receipt['master_sha256']:
        raise ValueError('Exact saved complete projection differs')
    def forbidden(*a, **kw):
        raise AssertionError('Producer disabled for current saved-row check')
    native_documents.project_document = native_documents.project_accepted_document = native_content.project_content = native_content.readable_content = forbidden
    with cached_edition_lookups():
        errors = native_documents.verify_accepted_document(io_path(promoted), acceptance_path=io_path(promoted / EDITION / 'acceptance.json'), rows=saved['rows'], receipt=saved['receipt'], category='prose')
    if errors:
        failure = ROOT / LOG / 'current-runtime-saved-row-failure.json'
        if failure.exists():
            raise FileExistsError(failure)
        failure.write_bytes(canonical(dict(errors=errors, original_projection_sha256=digest(source), producer_disabled=True)))
        raise ValueError(errors)
    challenges = []
    for kind in ['unknown-hash', 'missing-pin', 'extra-pin']:
        altered = dict(runtime)
        if kind == 'unknown-hash':
            altered[next(iter(altered))] = '0' * 64
        elif kind == 'missing-pin':
            altered.pop(next(iter(altered)))
        else:
            altered['unreviewed/module.py'] = '0' * 64
        try:
            validate_closed_pins(receipt, altered, schemas)
        except ValueError:
            challenges.append(dict(case=kind, status='rejected'))
        else:
            raise ValueError('Closed pin challenge escaped')
    target = ROOT / LOG / 'current-runtime-projection.json'
    supplement = ROOT / LOG / 'current-runtime-supplement.json'
    if target.exists() or supplement.exists():
        raise FileExistsError('Current supplement already exists')
    target.write_bytes(source.read_bytes())
    result = dict(status='pass', original_stage_sha256=STAGE_SHA, before=receipt['before'], after=receipt['after'], master_sha256=receipt['master_sha256'], acceptance_sha256=digest(promoted / EDITION / 'acceptance.json'), runtime_pins=runtime, schema_pins=schemas, allowed_transitions={p: dict(before=b, after=a) for p, (b, a) in ALLOWED.items()}, extra_reviewed_closure=EXTRA, coordinator_reviews=REVIEWS, saved_projection=dict(path=target.relative_to(ROOT).as_posix(), sha256=digest(target), original_stage_projection_sha256=digest(source), byte_identical=True), producer_disabled=True, errors=errors, rows=4, unknown_drift_challenges=challenges, projection_repeated=False, qualification='Exact old stage retained as dated evidence. Only three reviewed Hodge runtime transitions and one unrelated reviewed Bible schema transition alter staged pins; current default-profile saved rows and receipt are independently unchanged. The reviewed prose/Bible modules are additionally bound. No source, header, candidate, package, mutation, stage, accepted byte replay or rollback proof repeated.')
    if _files(ROOT / WORK) != receipt['before'] or _files(promoted / WORK) != receipt['after'] or {p: digest(ROOT / p) for p in runtime} != runtime or {p: digest(ROOT / p) for p in schemas} != schemas:
        raise ValueError('Inputs drifted during current check')
    supplement.write_bytes(canonical(result))
    print(json.dumps(dict(status='pass', rows=4, saved_projection_sha256=digest(target), supplement_sha256=digest(supplement), closed_pin_challenges=len(challenges))), flush=True)


if __name__ == '__main__':
    main()
