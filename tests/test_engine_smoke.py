"""B1 engine readiness smoke tests.

Pure-logic tests (specs, schema-valid families, path helper) always run. The
subprocess-spawning smokes import torch/tensorflow inside the engine venvs and
add real time, so they are opt-in: set OCD_ENGINE_SMOKE=1 to run them, and they
additionally skip when an engine venv is absent (clean CI checkout has none).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib import engine_inventory as ei  # noqa: E402
from build.lib.schema_enums import get_enum  # noqa: E402

_SMOKE_ENABLED = os.environ.get("OCD_ENGINE_SMOKE") == "1"
_SMOKE_REASON = "set OCD_ENGINE_SMOKE=1 to run in-venv engine smokes"


# --------------------------------------------------------------------------- #
# Pure-logic tests (always run)
# --------------------------------------------------------------------------- #


def test_specs_cover_active_engines() -> None:
    """Calamari retired 2026-05-31 (tested, insufficient quality on NSH scans).
    kraken-greek is the specialist Greek lane using Ciaconna model weights.
    """
    names = {spec.name for spec in ei.ENGINE_SPECS}
    assert names == {"tesseract", "surya", "kraken", "kraken-greek"}


def test_engine_families_are_schema_valid() -> None:
    # Families must be members of the WCT engine_family enum -- never hardcoded.
    valid = get_enum("word-confusion-table-v1", "available_engines", "family")
    for spec in ei.ENGINE_SPECS:
        assert spec.family in valid, f"{spec.family} not in engine_family enum"


def test_kraken_greek_family_is_kraken() -> None:
    """The Greek specialist lane must share the kraken family so
    family_independence.py collapses both Kraken lanes to one block
    by declaration (arch D plan section 2 B9).
    """
    greek_spec = next(s for s in ei.ENGINE_SPECS if s.name == "kraken-greek")
    assert greek_spec.family == "kraken"


def test_kraken_greek_uses_same_venv_as_kraken() -> None:
    """Both Kraken lanes share one venv; model weights differ."""
    base_spec = next(s for s in ei.ENGINE_SPECS if s.name == "kraken")
    greek_spec = next(s for s in ei.ENGINE_SPECS if s.name == "kraken-greek")
    assert greek_spec.venv == base_spec.venv


def test_kraken_greek_has_different_import_module() -> None:
    """Different import module name ensures the readiness probe
    can distinguish the two specs even in the same venv.
    """
    base_spec = next(s for s in ei.ENGINE_SPECS if s.name == "kraken")
    greek_spec = next(s for s in ei.ENGINE_SPECS if s.name == "kraken-greek")
    assert greek_spec.import_module != base_spec.import_module


def test_exactly_one_ocr_kind_is_the_new_tesseract() -> None:
    ocr_kind = [s for s in ei.ENGINE_SPECS if s.kind == "ocr"]
    assert [s.name for s in ocr_kind] == ["tesseract"]


def test_relative_path_helper_repo_vs_outside(tmp_path: Path) -> None:
    inside = REPO_ROOT / "raw" / "x.jpg"
    assert ei._relative_to_repo(inside, REPO_ROOT) == "raw/x.jpg"
    outside = tmp_path / "stray.jpg"
    assert ei._relative_to_repo(outside, REPO_ROOT) == "stray.jpg"


# --------------------------------------------------------------------------- #
# In-venv smokes (opt-in)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _SMOKE_ENABLED, reason=_SMOKE_REASON)
@pytest.mark.parametrize("spec", ei.ENGINE_SPECS, ids=lambda s: s.name)
def test_engine_venv_imports(spec) -> None:
    if not ei.venv_python(spec).exists():
        pytest.skip(f"{spec.venv} venv not present")
    sidecar = ei.smoke_engine(spec, REPO_ROOT / ei.DEFAULT_SAMPLE_LEAF, REPO_ROOT)
    assert sidecar["import_ok"], sidecar.get("probe_error")


@pytest.mark.skipif(not _SMOKE_ENABLED, reason=_SMOKE_REASON)
def test_tesseract_produces_a_sidecar_with_text() -> None:
    spec = next(s for s in ei.ENGINE_SPECS if s.name == "tesseract")
    if not ei.venv_python(spec).exists():
        pytest.skip("tesseract venv not present")
    sample = REPO_ROOT / ei.DEFAULT_SAMPLE_LEAF
    if not sample.exists():
        pytest.skip("sample leaf not present (raw/ not downloaded)")
    sidecar = ei.smoke_engine(spec, sample, REPO_ROOT)
    assert sidecar["mode"] == "ocr"
    assert sidecar["ok"], sidecar.get("ocr_error")
    assert sidecar["text_len"] and sidecar["text_len"] > 0
    # Path written into the sidecar is repo-root-relative (OUT-03).
    assert not sidecar["sample_leaf"].startswith("/")
    assert ":" not in sidecar["sample_leaf"]
