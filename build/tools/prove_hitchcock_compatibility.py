"""Run the existing focused reference-entry surface against an unapplied proposal."""

import importlib.util
import sys

import pytest

from build.tools.prepare_hitchcock_current import LOG
from ocd_kernel.projection.categories import reference_entries as current


def main() -> int:
    name = "ocd_kernel.projection.categories.reference_entries"
    spec = importlib.util.spec_from_file_location(name, LOG / "native-support-proposal/reference_entries.after.py")
    proposed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proposed)
    proposed.ROOT, proposed.SCHEMA, proposed.COMMON = current.ROOT, current.SCHEMA, current.COMMON
    sys.modules[name] = proposed
    return pytest.main(["-p", "no:cacheprovider", "tests/test_projection_reference_entries.py", "-k", "not fixture_is_valid_full_tei_p5 and not source_to_fixture_builder", "-v", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
