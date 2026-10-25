"""Add canonical work-local completion/selection pointers; preserve all finished receipts."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_bcp1559_current import ROOT,WORK,EDITION,LOG as INSTALL_LOG,canonical
from ocd_kernel.library._common import io_path

OUT=ROOT/'reports/_logs/bcp1559-offline-release-20261002-v1'
PUB=ROOT/WORK/'publication'

def digest(path):return sha256(io_path(path).read_bytes()).hexdigest()
def binding(path):return dict(path=path.relative_to(ROOT).as_posix(),sha256=digest(path))

def main():
    original_completion=OUT/'completion.json';original_delivery=OUT/'final-delivery.json'
    completed=json.loads(original_completion.read_bytes());delivery=json.loads(original_delivery.read_bytes())
    install=ROOT/INSTALL_LOG/'canonical-install/coordinator-installed-generation-review.json'
    terminal=ROOT/INSTALL_LOG/'private-release-v1-terminal.json'
    if json.loads(install.read_bytes())['status']!='pass' or json.loads(terminal.read_bytes())['exit_code']!=0:raise ValueError('Independent install or terminal missing')
    if digest(ROOT/EDITION/'master.tei.xml')!=completed['accepted_master_sha256']:raise ValueError('Master changed')
    before={p:digest(p) for p in [original_completion,original_delivery,install,terminal]}
    if any((PUB/name).exists() for name in ['completion.json','selection.json','README.md']):raise FileExistsError('Canonical publication pointers already exist')
    (PUB/'selection.json').write_bytes((OUT/'selection.json').read_bytes())
    (PUB/'README.md').write_bytes((OUT/'README.md').read_bytes())
    completion=dict(status='pass',work_id='bcp-1559',private_offline=True,publication_performed=False,
        accepted_master_sha256=completed['accepted_master_sha256'],acceptance_sha256=digest(ROOT/EDITION/'acceptance.json'),
        source_sha256='3907571f9368082a0f45e2aba8d4c36d0503a7931631d690ee5dc700d336591e',
        rows=16,members=16,tables=128,table_rows=391,cells=998,rowspans=46,text_characters=314200,uncompressed_bytes=3082302,
        completion_report=binding(original_completion),delivery_report=binding(original_delivery),selection=binding(PUB/'selection.json'),
        terminal_report=binding(terminal),coordinator_installed_review=binding(install),
        authority_bindings=delivery['authority'],schema_implementation_bindings=delivery['schemas'],release_file_bindings=delivery['release'],
        release_path=str(OUT/'release'),
        actual_master_projection_and_independent_verification='pass',statistics_and_normal_streaming_readers='pass',exact_source_data_credit_visible=True,
        source_scope='Entire declared sixteen-member retained BCP1559 electronic expression; later variants and supplementary context retained, no pure1559 print equivalence claimed.',
        remaining=completed['remaining'],checked_at=completed['checked_at'],
        qualification='Canonical accounting pointers added after dated private release completion; original205 delivery-map bindings and all completed receipts remain immutable. No source, installation, projection, release, statistics or reader gates repeated.')
    (PUB/'completion.json').write_bytes(canonical(completion))
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Preserved evidence changed')
    paths=[PUB/'completion.json',PUB/'selection.json',PUB/'README.md',install,terminal,original_completion,original_delivery,OUT/'terminal-install-corroboration.json',Path(__file__),ROOT/EDITION/'master.tei.xml',ROOT/EDITION/'acceptance.json']
    bindings={p.relative_to(ROOT).as_posix():digest(p) for p in paths}
    supplement=dict(status='pass',utc=datetime.now(timezone.utc).isoformat(),canonical_publication_accounting=True,
                    authority_bindings=bindings,original_delivery_map_sha256=digest(original_delivery),original_map_entries=205,
                    original_map_bases=dict(authority=str(ROOT),schemas=str(ROOT),release=str(OUT/'release'),evidence=str(OUT)),
                    completed_gates_repeated=False,canonical_master_acceptance_unchanged=True,
                    canonical_selection_byte_identical_to_checked_selection=True,
                    qualification='Only canonical work-local completion/selection/README accounting was added; unchanged master and dated private release evidence are bound explicitly.')
    target=OUT/'canonical-publication-pointer-corroboration.json'
    if target.exists():raise FileExistsError(target)
    target.write_bytes(canonical(supplement));print(json.dumps(dict(status='pass',completion=binding(PUB/'completion.json'),supplement=binding(target),bindings=len(bindings))))

if __name__=='__main__':main()
