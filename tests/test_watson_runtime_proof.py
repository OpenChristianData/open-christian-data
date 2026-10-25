"""Public acceptance regression for retained Thomas Watson runtime evidence."""

from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei import acceptance


ROOT = Path(__file__).resolve().parents[1]
BEATITUDES_ACCEPTANCE = ROOT / (
    "library/works/watson-beatitudes/forms/"
    "watson-beatitudes-route-source-form/editions/"
    "watson-beatitudes-retained-thml-route/acceptance.json"
)


def test_current_beatitudes_fresh_recipe_mutation_fails_public_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed staged recipe cannot borrow the accepted current proof."""
    canonical = ROOT / acceptance.BEATITUDES_ACCEPTANCE_MANIFEST
    changed = tmp_path / "changed-source-manifest.json"
    original_bytes = canonical.read_bytes()
    assert b'"contract"' in original_bytes
    changed.write_bytes(original_bytes.replace(b'"contract"', b'"contracx"', 1))

    original_fixture_path = acceptance._fixture_path

    def fixture_path(root: Path, relative: str, *, field: str) -> Path:
        if field == "Beatitudes source manifest":
            assert relative == acceptance.BEATITUDES_ACCEPTANCE_MANIFEST
            return changed
        return original_fixture_path(root, relative, field=field)

    monkeypatch.setattr(acceptance, "_fixture_path", fixture_path)
    with pytest.raises(PipelineError, match="Beatitudes source manifest differs"):
        acceptance.validate_acceptance(BEATITUDES_ACCEPTANCE, root=ROOT)
