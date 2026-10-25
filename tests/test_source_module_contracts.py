"""New source modules load without operations and expose declared route callables."""

import pytest

from build.tools.pre_commit_pytest import MODULE_CONTRACT_SOURCES
from tests.test_cli_input_guards import _contract_case, _invoke


@pytest.mark.parametrize(
    ("source", "entrypoints"),
    [_contract_case(source, entrypoints) for source, entrypoints in MODULE_CONTRACT_SOURCES.items()],
    ids=MODULE_CONTRACT_SOURCES,
)
def test_module_imports_without_operations_and_exposes_declared_callables(source, entrypoints):
    module = source.removesuffix(".py").replace("/", ".")
    result = _invoke(module, "__ocd_import_contract__", entrypoints=entrypoints)
    assert result.returncode == 0, result.stderr
    assert result.stdout.rstrip().endswith("OCD_IMPORT_CONTRACT_PASSED"), result.stdout
