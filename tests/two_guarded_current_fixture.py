"""Two named guarded transactions run current code over exact historical inputs."""
from __future__ import annotations
from hashlib import sha256
import importlib.util
import json
import shutil
from pathlib import Path
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.runtime_candidate_baselines import current_runtime_baseline
from tests.vendored_schema_mirrors import copy_vendored_schema_imports


def current_guarded_context(input_root, route, destination, *, runtime_manifest):
    original_raw = _io_path(route.RECEIPT).read_bytes()
    assert sha256(original_raw).hexdigest() == route.RECEIPT_SHA
    original = json.loads(original_raw)
    assert original['work_id'] in {'schleitheim-confession-1527', 'sum-of-saving-knowledge'}
    assert _files(route.STAGE / route.WORK) == original['after']
    root, stage = destination / 'root', destination / 'stage'
    shutil.copytree(_io_path(route.STAGE), _io_path(root))
    shutil.copytree(_io_path(route.STAGE), _io_path(stage))
    target = _io_path(root / route.WORK)
    assert target.resolve().is_relative_to(_io_path(root).resolve()) and not target.is_symlink()
    shutil.rmtree(target)
    before_home = Path(__file__).parent / 'fixtures/two-guarded-before' / original['work_id']
    for relative, expected in original['before'].items():
        raw = (before_home / relative).read_bytes()
        assert sha256(raw).hexdigest() == expected
        target = _io_path(root / route.WORK / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    assert _files(root / route.WORK) == original['before']
    historical = Path('historical-source-records') / original['work_id'] / 'source-manifest.json'
    original_manifest = _io_path(input_root / route.MANIFEST).read_bytes()
    assert sha256(original_manifest).hexdigest() == original['source_manifest_sha256']
    (root / historical).parent.mkdir(parents=True)
    (root / historical).write_bytes(original_manifest)
    runtime_raw = (input_root / runtime_manifest).read_bytes()
    runtime = json.loads(runtime_raw)
    code = {
        Path(runtime['converter']['implementation_path']),
        Path(runtime['validator']['implementation_path']),
        Path('ocd_kernel/reconstruction/contract.py'),
        Path('ocd_kernel/reconstruction/verifier.py'),
        Path('ocd_kernel/reconstruction/__init__.py'),
    }
    original_dependencies = set(_files(route.STAGE))
    for relative in code:
        raw = _io_path(input_root / relative).read_bytes()
        target = _io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        if relative.as_posix() in original_dependencies:
            _io_path(stage / relative).write_bytes(raw)
    for place in (root, stage):
        _io_path(place / route.MANIFEST).write_bytes(runtime_raw)
    copy_vendored_schema_imports(input_root, root)
    candidate_home = destination / 'current-candidate'
    manifest, candidate = current_runtime_baseline(
        root=root, tool_root=input_root, original_manifest=historical,
        runtime_manifest=route.MANIFEST, retained_package=route.CANDIDATE,
        retained_sha256=original['candidate_package_sha256'], destination=candidate_home,
    )
    validation = json.loads((candidate_home / 'validation.json').read_bytes())
    package_manifest = route.EVIDENCE / 'inputs/package/manifest.json'
    package_root = stage / route.EVIDENCE / 'inputs/package'
    assert set(_files(package_root)) == set(candidate.member_names)
    for name in candidate.member_names:
        _io_path(package_root / name).write_bytes(candidate.member_bytes(name))
    after = _files(stage / route.WORK)
    assert set(after) == set(original['after'])
    assert {p for p in after if after[p] != original['after'][p]} == {
        package_manifest.relative_to(route.WORK).as_posix(),
        (package_manifest.parent / 'provenance.json').relative_to(route.WORK).as_posix(),
    }
    current = dict(
        original, canonical_root=root.as_posix(), stage_root=stage.as_posix(),
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=candidate.sha256,
        oracle_report_sha256=validation['report_sha256'], after=after,
    )
    restored = dict(current)
    for key in ('canonical_root', 'stage_root', 'source_manifest_sha256',
                'candidate_package_sha256', 'oracle_report_sha256', 'after'):
        restored[key] = original[key]
    assert restored == original
    raw = (json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()
    receipt = stage / route.RECEIPT.name
    receipt.write_bytes(raw)
    oracle_path = root / runtime['validator']['implementation_path']
    spec = importlib.util.spec_from_file_location(
        'build.tei._' + original['work_id'].replace('-', '_') + '_current_fixture', oracle_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return root, stage, receipt, sha256(raw).hexdigest(), candidate.path, module._oracle
