"""Independent finite root review of an existing L811 completion packet."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / 'reports/_logs/eusebius-l811-existing-install-20261004-v1'

def enc(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()

def digest(data):
    return sha256(data).hexdigest()

def main():
    receipt = LOG / 'root-final-source-review-v1.json'
    process_path = LOG / 'root-independent-source-command-v1.json'
    output_path = LOG / 'root-independent-whole-source-readback-v1.json'
    if any(p.exists() for p in [receipt, process_path, output_path]):
        raise FileExistsError('Preserve previous root review generation')
    final = json.loads((LOG / 'source-final-review-packet-v1.json').read_bytes())
    packet = json.loads((LOG / 'source-completion-packet-v1.json').read_bytes())
    checked = {}
    def pins(value):
        if isinstance(value, dict):
            if {'path', 'bytes', 'sha256'} <= value.keys():
                p = Path(value['path'])
                p = p if p.is_absolute() else ROOT / p
                data = p.read_bytes()
                if len(data) != value['bytes'] or digest(data) != value['sha256']:
                    raise ValueError('Current receipt pin mismatch: ' + str(p))
                checked[p.as_posix()] = value
            for child in value.values():
                pins(child)
        elif isinstance(value, list):
            for child in value:
                pins(child)
    pins(final)
    pins(packet)
    route = json.loads(Path(final['completed_evidence_routing_proposal']['path']).read_bytes())
    pins(route)
    process_checks = []
    for family in ['semantic_challenges', 'accounting_challenges', 'outer_candidate_contract_challenges']:
        for row in packet[family]:
            saved = json.loads(Path(row['process']['path']).read_bytes())
            reason = row.get('intended_reason', 'Complete actual repair ledger differs' if family == 'accounting_challenges' else 'Exact outer candidate manifest record/path/schema/status differs')
            if saved['exit_code'] == 0 or reason not in saved['stdout'] + saved['stderr']:
                raise ValueError('Intended source rejection missing: ' + row['name'])
            process_checks.append({'family': family, 'name': row['name'], 'exit_code': saved['exit_code'], 'reason': reason})
    for row in packet['late_import_negatives']:
        saved = json.loads(Path(row['process']['path']).read_bytes())
        if saved['exit_code'] == 0 or 'Unexpected or changed L811 executed dependency:' not in saved['stdout'] + saved['stderr'] or row['checkpoint'] not in saved['stdout']:
            raise ValueError('Genuinely late rejection not demonstrated')
    for row in packet['bootstrap_history']['failed_commands']:
        if json.loads(Path(row['path']).read_bytes())['exit_code'] == 0:
            raise ValueError('Failed bootstrap unexpectedly relabeled')
    base = Path(packet['candidate_members']['manifest.json']['path']).parent
    replay_checks = []
    for replay in packet['fresh_isolated_six_member_replays']:
        other = Path(replay['package']['path']).parent
        actual = {name: (base / name).read_bytes() == (other / name).read_bytes() for name in packet['candidate_members']}
        if not all(actual.values()) or json.loads(Path(replay['process']['path']).read_bytes())['exit_code'] != 0:
            raise ValueError('Fresh replay byte identity missing')
        replay_checks.append({'package': other.as_posix(), 'actual_six_members_identical': actual})
    old = json.loads((LOG / 'whole-retained-assessment-v1.json').read_bytes())
    for relative, row in old['canonical_before'].items():
        data = (ROOT / 'library/works/eusebius-commentarii-in-psalmos' / relative).read_bytes()
        if digest(data) != row['sha256'] or len(data) != row['bytes']:
            raise ValueError('Canonical preimage changed: ' + relative)
    command = [sys.executable, '-I', '-B', str(ROOT / 'build/tools/prove_eusebius_l811_retained.py'), '--package', str(base), '--output', str(output_path)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
    process_path.write_bytes(enc({'command': command, 'cwd': ROOT.as_posix(), 'exit_code': result.returncode, 'stdout': result.stdout.decode('utf-8'), 'stderr': result.stderr.decode('utf-8')}))
    if result.returncode:
        raise ValueError('Root independent source check failed; saved process evidence')
    actual = json.loads(output_path.read_bytes())
    if actual['status'] != 'pass' or not actual['full_old_tei_byte_inverse'] or actual['actual_source_carrier_nodes'] != 63218 or actual['attributes_compared'] != 57271:
        raise ValueError('Root whole-source census or inverse differs')
    observed = actual['actual_execution_paths']
    if any('pta_l811_three_tome' in path or 'eusebius_l811_retained_repair.py' in path for path in observed):
        raise ValueError('Producer lineage executed in independent source process')
    for row in checked.values():
        p = Path(row['path']); p = p if p.is_absolute() else ROOT / p
        if digest(p.read_bytes()) != row['sha256']:
            raise ValueError('Pinned input drifted during root review')
    value = {'status': 'root-source-reviewed-ready-for-installation-proposal', 'at': datetime.now(timezone.utc).isoformat(), 'checked_current_pins': list(checked.values()), 'negative_process_checks': process_checks, 'replays': replay_checks, 'root_independent_process': process_path.as_posix(), 'root_independent_readback': {'path': output_path.as_posix(), 'bytes': output_path.stat().st_size, 'sha256': digest(output_path.read_bytes())}, 'actual_source_census': {key: actual[key] for key in ['actual_source_carrier_nodes', 'attributes_compared', 'rewritten_reference_attributes']}, 'source_only_actual_execution_paths': observed, 'canonical_original_five': 'unchanged', 'review': 'Read final/completion packets, current successor diffs, complete capture/proof/orchestrator code and separate completed evidence route; independently verified actual current files, failed attempts, intended rejection reasons and fresh replay bytes.', 'next': 'Prepare accepted header/state, complete native apparatus reader proposal and guarded installation stage for root review. No acceptance or canonical apply by this receipt.', 'qualifications': ['Greek source Psalm labels are opaque; no Hebrew numbering equivalence.', 'Source I/II draft/work in progress and III approved are preserved.', 'Historical swap-source-Ps-sections label actually moves Ps_1 before a leading source comment; actual field/order rejection only.', 'Technical source proof does not establish print completeness, human visual acceptance, rights clearance or publication.']}
    receipt.write_bytes(enc(value))
    print(json.dumps({'receipt': receipt.as_posix(), 'sha256': digest(receipt.read_bytes()), 'pins': len(checked), 'status': value['status']}))

if __name__ == '__main__':
    main()
