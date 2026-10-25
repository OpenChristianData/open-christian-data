"""Retained command entrypoints must parse arguments before performing operations."""

from pathlib import Path
import subprocess
import sys

import pytest

from build.tools.pre_commit_pytest import CLI_CONTRACT_SOURCES


ROOT = Path(__file__).resolve().parents[1]
# Private publication helpers intentionally omitted from public mirrors.
PUBLICLY_OMITTED_MODULES = frozenset({
    'build/tei/l599_slave_trade_runtime.py',
    'build/tei/l599_slave_trade_source_oracle.py',
    'build/tei/l599_slave_trade_source_package.py',
    'build/tei/strong_vol2_current_oracle.py',
    'build/tei/strong_vol2_current_prepare.py',
    'build/tools/accept_maclaren_expositions_v3.py',
    'build/tools/capture_l599_slave_trade_acceptance.py',
    'build/tools/capture_strong_vol2_current_acceptance.py',
    'build/tools/capture_tyerman_john_wesley_acceptance.py',
    'build/tools/derive_blaikie_first_samuel_install.py',
    'build/tools/derive_smith_isaiah_install.py',
    'build/tools/finalize_bcp1662_private_release.py',
    'build/tools/findlay_stage_adapt.py',
    'build/tools/install_dods_complete_acceptance.py',
    'build/tools/install_findlay_retained_acceptance.py',
    'build/tools/install_lightfoot_bom_revision.py',
    'build/tools/l599_slave_trade_install.py',
    'build/tools/prepare_l599_slave_trade_source.py',
    'build/tools/prepare_lightfoot_bom_revision.py',
    'build/tools/prepare_watson_body_of_divinity_acceptance.py',
    'build/tools/probe_smith_isaiah_execution.py',
    'build/tools/prove_dods_complete_install.py',
    'build/tools/prove_findlay_retained_install.py',
    'build/tools/prove_l599_slave_trade_install.py',
    'build/tools/prove_l599_slave_trade_source.py',
    'build/tools/prove_strong_vol2_current_install.py',
    'build/tools/prove_tyerman_john_wesley_install.py',
    'build/tools/publish_public_mirror.py',
    'build/tools/revise_ccel_source_text.py',
    'build/tools/revise_reviewed_library_text.py',
    'build/tools/smith_isaiah_complete_install.py',
    'build/tools/stage_anne_a22095_acceptance.py',
    'build/tools/stage_dods_complete_acceptance.py',
    'build/tools/stage_findlay_retained_acceptance.py',
    'build/tools/stage_l742_acceptance.py',
    'build/tools/strong_vol2_current_install.py',
    'build/tools/tyerman_john_wesley_install.py',
})


def _contract_case(source, *values):
    local_case = (source in PUBLICLY_OMITTED_MODULES
                  and ((ROOT / "config/public_mirror_allowlist.json").is_file()
                       or not (ROOT / source).is_file()))
    marks = pytest.mark.requires_local_artifacts if local_case else ()
    return pytest.param(source, *values, marks=marks)


def test_contract_cases_keep_missing_public_and_private_modules_in_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    source = "build/tools/publish_public_mirror.py"
    assert source in PUBLICLY_OMITTED_MODULES
    case = _contract_case(source, ("main", 1))
    assert case.values == (source, ("main", 1))
    assert [mark.name for mark in case.marks] == ["requires_local_artifacts"]
    assert not _contract_case("build/tools/ordinary_public_module.py").marks
    target = tmp_path / source
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    assert not _contract_case(source).marks
    target.unlink()
    configuration = tmp_path / "config/public_mirror_allowlist.json"
    configuration.parent.mkdir()
    configuration.write_text("{}", encoding="utf-8")
    case = _contract_case(source, ("main", 1))
    assert case.values == (source, ("main", 1))
    assert [mark.name for mark in case.marks] == ["requires_local_artifacts"]
    assert _invoke("build.tools.publish_public_mirror", "__ocd_import_contract__", cwd=tmp_path).returncode != 0


@pytest.mark.requires_local_artifacts
def test_public_contract_omissions_match_the_owning_mirror_policy():
    import json

    policy = json.loads((ROOT / "config/public_mirror_allowlist.json").read_bytes())
    assert PUBLICLY_OMITTED_MODULES == {
        path for path in policy["exclude"]
        if path.startswith("build/") and path.endswith(".py")
    }


IMPORT_GUARD = """
import importlib, inspect, json, os, runpy, sys
from pathlib import Path
attempted = []
def protect(event, args):
    writing = event == 'open' and (
        isinstance(args[1], str) and any(c in args[1] for c in 'wax+')
        or isinstance(args[2], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
    )
    if writing or event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.truncate', 'os.link', 'os.symlink', 'os.utime', 'os.chmod', 'os.chown', 'os.system', 'os.startfile', 'os.startfile/2', 'shutil.rmtree', 'subprocess.Popen', 'socket.connect', 'socket.sendto', 'socket.bind'}:
        attempted.append(event)
        raise AssertionError('CLI argument parsing attempted an operation: ' + event)
sys.dont_write_bytecode = True
sys.addaudithook(protect)
module, argument = sys.argv[1:3]
entrypoints = json.loads(sys.argv[3])
sys.argv = [module, argument]
try:
    if argument == '__ocd_import_contract__':
        loaded = importlib.import_module(module)
        expected = Path.cwd() / (module.replace('.', '/') + '.py')
        assert Path(loaded.__file__).resolve() == expected.resolve()
        for name, arity in entrypoints:
            value = getattr(loaded, name)
            assert callable(value), name
            inspect.signature(value).bind(*(object() for _ in range(arity)))
        print('OCD_IMPORT_CONTRACT_PASSED')
    else:
        runpy.run_module(module, run_name='__main__')
finally:
    if attempted:
        raise AssertionError('CLI argument parsing attempted operations: ' + repr(attempted))
"""


def _invoke(module, argument, *, cwd=ROOT, entrypoints=()):
    import json

    return subprocess.run(
        [sys.executable, "-B", "-c", IMPORT_GUARD, module, argument, json.dumps(entrypoints)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("source", [_contract_case(source) for source in CLI_CONTRACT_SOURCES], ids=CLI_CONTRACT_SOURCES)
def test_cli_parses_help_and_rejects_unknown_arguments_without_operations(source):
    module = source.removesuffix(".py").replace("/", ".")
    for argument, expected in (("--help", 0), ("--ocd-invalid-option-for-entrypoint-test", 2)):
        result = _invoke(module, argument)
        assert result.returncode == expected, result.stderr


@pytest.mark.parametrize("argument", ["--help", "__ocd_import_contract__"])
def test_import_guard_prevents_startup_writes_even_when_the_module_catches_errors(tmp_path, argument):
    target = tmp_path / "sentinel.txt"
    target.write_text("original", encoding="utf-8")
    (tmp_path / "unsafe_cli.py").write_text(
        "from pathlib import Path\ntry:\n Path('sentinel.txt').write_text('changed')\nexcept Exception:\n pass\n",
        encoding="utf-8",
    )
    result = _invoke("unsafe_cli", argument, cwd=tmp_path)
    assert result.returncode != 0
    assert "CLI argument parsing attempted operations" in result.stderr
    assert target.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("event", ["os.utime", "os.chmod", "os.system", "os.startfile", "socket.sendto"])
def test_import_guard_blocks_other_mutation_and_process_audit_events(tmp_path, event):
    (tmp_path / "unsafe_cli.py").write_text(
        f"import sys\nsys.audit({event!r}, 'guard self-check')\n", encoding="utf-8"
    )
    result = _invoke("unsafe_cli", "__ocd_import_contract__", cwd=tmp_path)
    assert result.returncode != 0
    assert f"attempted an operation: {event}" in result.stderr
