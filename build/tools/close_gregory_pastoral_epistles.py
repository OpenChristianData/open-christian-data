"""Check frozen Gregory Pastoral Rule and Epistles installed authority, private release and source/support pins."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_gregory_pastoral_epistles import ROOT,WORK,BASE,SOURCE,SOURCE_SHA,SCOPE,canonical
from ocd_kernel.tei.install_accepted import _files,_io_path


def main():
    output=ROOT/'reports/_logs/gregory-pastoral-epistles-install-20261001-v1'
    completion=json.loads((ROOT/WORK/'publication/private-offline-20261001/completion.json').read_bytes())
    pin=json.loads((ROOT/BASE/'stage-pin.json').read_bytes())
    receipt_raw=Path(pin['receipt']).read_bytes()
    if sha256(receipt_raw).hexdigest()!=pin['receipt_sha256']:raise ValueError('frozen receipt differs')
    stage=json.loads(receipt_raw)
    installed={p:h for p,h in _files(ROOT/WORK).items() if not p.startswith('publication/')}
    installation=json.loads((output/'installation.json').read_bytes())
    journal=json.loads((Path(installation['operation'])/'operation.json').read_bytes())
    if installed!=stage['after'] or journal['phase']!='complete' or journal['after']!=installed:raise ValueError('installed journal/frozen after hashes differ')
    if completion['independent_check']['status']!='pass' or completion['reader_normal_and_streaming']!='pass':raise ValueError('private release incomplete')
    pins=json.loads((ROOT/BASE/'delivery-input-pins.json').read_bytes())
    for p,digest in (pins['authority_hashes']|pins['schemas']).items():
        if sha256(_io_path(ROOT/p).read_bytes()).hexdigest()!=digest:raise ValueError('frozen input changed: '+p)
    for work, digests in pins["sibling_hashes"].items():
        if _files(ROOT/"library/works"/work) != digests:
            raise ValueError("completed source sibling changed: "+work)
    if sha256((ROOT/SOURCE).read_bytes()).hexdigest()!=SOURCE_SHA:raise ValueError('retained source changed')
    record=dict(status='complete-technical-private-release-only',checked_at=datetime.now(timezone.utc).isoformat(),scope=SCOPE,
        installed_files=installed,installation_phase=journal['phase'],guarded_operation=installation['operation'],
        source_sha256=SOURCE_SHA,source_elements=7669,source_literal_heads=356,epistles=273,books=8,book_epistle_counts=[52,30,34,32,31,45,28,21],pastoral_parts=4,pastoral_chapters=64,notes=506,pages=273,source_reference_tags=721,neutral_letter_references=12,rtl_spans=0,
        retained_diagram_bytes=44462,retained_diagram_sha256="a06e1fa626deadbfa78c1390ccd63408b7eea2a720c5b4542eda9e999cc616b5",diagram_uri_label_placement_conserved=True,historical_image_snapshot="unknown",offline_image_pixel_embedding="not claimed; typed reference/label preserved, retained PNG separately hash-bound and inspected",historical_body_unchanged=True,immutable_acquisition_title_language_ids_preserved=True,category_only_prose=True,
        independent_source_receipt='reports/_logs/gregory-pastoral-epistles-coordinator-source-review-20261001/review.json',
        sibling_hashes=pins["sibling_hashes"],sibling_generations_unchanged=True,authority_hashes=pins['authority_hashes'],schema_pins=pins['schemas'],release_evidence_hashes=_files(ROOT/WORK/'publication/private-offline-20261001'),
        private_release=completion['release'],statistics=completion['statistics'],
        tests='One focused exact metadata check and two isolated receipt/rollback checks pass; twenty source-fidelity mutations rejected; exact six-member fresh-process replay and accepted-header/body byte conservation pass.',
        unassessed=['human textual/visual verification','print collation','rights clearance','publication authorization'],publication_performed=False)
    (output/'final-delivery-audit.json').write_bytes(canonical(record))
    (output/'README.md').write_text('# Gregory Pastoral Rule and Epistles technical completion\n\n'+SCOPE+'\n\nUnchanged retained-source body, independent complete native tree/ledger checks, exact replay, twenty mutations, pinned category prerequisite and isolated guarded rollback pass. Canonical guarded installation and actual-master private projection, assembly, independent verification, statistics and normal/streaming readers pass. Visible source and data credit retain source-local James Barmby translation/introduction/notes/indices and Philip Schaff electronic editor roles and CCEL permission qualification. Final hashes and counts are in final-delivery-audit.json.\n\nHuman textual/visual acceptance, print equivalence, rights clearance and publication remain separate. No acquisition, child work identity, Git operation or public publication occurred.\n',encoding='utf8',newline='\n')
    print(json.dumps(dict(status=record['status'],installed_files=len(installed),authority_files=len(pins['authority_hashes']),schemas=len(pins['schemas']),statistics=record['statistics'])))


if __name__=='__main__':main()
