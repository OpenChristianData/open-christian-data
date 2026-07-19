"""Batch 05 — validate the witnessless-lemma TEI fixture against both schema flavors.

This test answers the source-plan question (unknown 1): does a witnessless <lem>
carrying @resp and @cert but NO @wit validate against tei_all?

Both flavors are checked:
  - XSD via ocd_kernel.tei.validate.validate_file (the pipeline gate)
  - RelaxNG via lxml.etree.RelaxNG (the TEI-canonical reference flavor)

Marked @pytest.mark.slow because the ~14-second schema parse dwarfs the fast
suite budget. Run explicitly with: py -3 -m pytest -p no:cacheprovider
tests/test_witnessless_lemma_fixture.py -q
"""
from __future__ import annotations

import pytest
from pathlib import Path
from lxml import etree

from ocd_kernel.tei import validate as tei_validate
from ocd_kernel.tei.validate import validate_file

_REPO_ROOT = Path(__file__).parents[1]
_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "witnessless_lemma_fixture.tei.xml"
_RNG_PATH = Path(tei_validate.__file__).parent / "vendor" / "relaxng" / "tei_all.rng"


pytestmark = pytest.mark.slow


def test_fixture_exists() -> None:
    assert _FIXTURE_PATH.exists(), (
        f"Fixture not yet authored — dispatch Codex per batch-05 spec: {_FIXTURE_PATH}"
    )


def test_witnessless_lemma_validates_xsd() -> None:
    """XSD validation must return zero errors (the pipeline gate flavor)."""
    assert _FIXTURE_PATH.exists(), f"Fixture missing: {_FIXTURE_PATH}"
    errors = validate_file(_FIXTURE_PATH)
    assert errors == [], "\n".join(errors)


def test_witnessless_lemma_validates_relaxng() -> None:
    """RelaxNG validation must return zero errors (the TEI-canonical reference flavor)."""
    assert _FIXTURE_PATH.exists(), f"Fixture missing: {_FIXTURE_PATH}"
    rng = etree.RelaxNG(etree.parse(str(_RNG_PATH)))
    doc = etree.parse(str(_FIXTURE_PATH))
    valid = rng.validate(doc)
    errors = [str(e) for e in rng.error_log]
    assert valid, "RelaxNG validation failed:\n" + "\n".join(errors)


def test_fixture_contains_witnessless_lem() -> None:
    """The fixture must contain a <lem> element with no @wit attribute."""
    assert _FIXTURE_PATH.exists(), f"Fixture missing: {_FIXTURE_PATH}"
    tree = etree.parse(str(_FIXTURE_PATH))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    lems = tree.findall(".//t:lem", ns)
    assert lems, "No <lem> element found in fixture"
    witnessless = [el for el in lems if el.get("wit") is None]
    assert witnessless, (
        "No witnessless <lem> found — every <lem> carries @wit; "
        "the encoding under test requires one without @wit"
    )
    lem = witnessless[0]
    assert lem.get("resp") is not None, "<lem> must carry @resp"
    assert lem.get("cert") is not None, "<lem> must carry @cert"
