"""No-write probe of the reviewed Beatitudes selection overwrite guard."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
import copy
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from ocd_kernel.library._common import io_path


def main():
    runner = Path('library/works/watson-beatitudes/publication/complete_private_release.py')
    frozen = Path('library/works/watson-beatitudes/publication/release-input-freeze-v3.json')
    log = ROOT/'reports/_logs/watson-beatitudes-downstream-preflight-20261002-v1/selection-preimage-amendment-v3'
    spec = importlib.util.spec_from_file_location('watson_guard_probe', io_path(ROOT/runner))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    freeze = json.loads(io_path(ROOT/frozen).read_bytes())
    control = freeze['controlled_selection_output']
    selection = ROOT/control['path']
    original = io_path(selection).read_bytes()
    module.check_selection_preimage(selection, control, module.selection_bytes(freeze['selection']))
    probe_output = ROOT/'reports/_logs/watson-beatitudes-selection-mismatch-no-write-20261002-v3'
    assert not io_path(probe_output).exists()
    real_read = module.read
    altered = copy.deepcopy(freeze)
    altered['controlled_selection_output']['before_sha256'] = '0'*64

    def read_probe(path):
        return altered if path == ROOT/frozen else real_read(path)

    writes = []

    def forbidden_write(*args, **kwargs):
        writes.append(str(args[0]))
        raise AssertionError('Guard probe reached a write')

    module.read = read_probe
    module.OUT = probe_output
    module.save = forbidden_write
    module.replace_selection = forbidden_write
    try:
        module.main()
    except ValueError as error:
        assert str(error) == 'Canonical selection preimage differs from reviewed bytes', str(error)
        diagnostic = str(error)
    else:
        raise AssertionError('Mismatched preimage did not fail closed')
    assert not writes and not io_path(probe_output).exists()
    assert io_path(selection).read_bytes() == original
    assert not io_path(ROOT/'reports/_logs/watson-beatitudes-private-release-20261002-v2').exists()
    assert not io_path(ROOT/'library/works/watson-beatitudes/publication/completion.json').exists()
    checks = []
    for basis in ('authority_bindings', 'schema_implementation_bindings'):
        for path, expected in freeze[basis].items():
            actual = sha256(io_path(ROOT/path).read_bytes()).hexdigest()
            assert actual == expected, path
            checks.append(dict(path=path, sha256=actual, basis=basis))
    report = dict(status='pass', checked_at=datetime.now(timezone.utc).isoformat(),
        driver_path=runner.as_posix(), driver_sha256=sha256(io_path(ROOT/runner).read_bytes()).hexdigest(),
        freeze_path=frozen.as_posix(), freeze_sha256=sha256(io_path(ROOT/frozen).read_bytes()).hexdigest(),
        probe_sha256=sha256(io_path(Path(__file__)).read_bytes()).hexdigest(),
        positive_exact_preimage_guard='pass', negative_main_probe='pass', negative_error=diagnostic,
        mutation='In-memory expected preimage hash replaced with zeros; canonical selection untouched',
        writes_attempted=writes, probe_output_absent=True, release_output_absent=True,
        canonical_completion_absent=True, canonical_selection_unchanged=True,
        canonical_selection_sha256=sha256(original).hexdigest(), current_input_checks=checks,
        assembly_not_run=True, exit_code=0,
        prior_probe_failure=dict(tool_chunk='8df177', exit_code=1,
            reason='Extended-path import ROOT bypassed normal-path freeze interception; forbidden-write spy stopped before writes'))
    target = io_path(log/'guard-probe-and-current-input-audit.json')
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(report, sort_keys=True, indent=2)+'\n')
    print(json.dumps(dict(status='pass', path=target.as_posix(), sha256=sha256(target.read_bytes()).hexdigest(),
        checks=len(checks), writes_attempted=0, output_absent=True)))


if __name__ == '__main__':
    main()
