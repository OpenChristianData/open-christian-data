from __future__ import annotations

from pathlib import Path

import pytest

from ocd_kernel.tei.validate_schematron import validate_file

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_PAGE = REPO_ROOT / ".tmp_audit" / "taskA-materializer-out" / "page_0010.tei.xml"
WITNESSLESS_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "witnessless_lemma_fixture.tei.xml"


def _write_tei(tmp_path: Path, xml: str) -> Path:
    path = tmp_path / "fixture.tei.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def _synthetic_valid_materialized_page(tmp_path: Path) -> Path:
    return _write_tei(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>JE synthetic page</title>
        <author>Jewish Encyclopedia contributors</author>
        <respStmt xml:id="corrector">
          <resp>Machine corrector</resp>
          <name>Open Christian Data corrector</name>
        </respStmt>
      </titleStmt>
      <publicationStmt><p>Test</p></publicationStmt>
      <sourceDesc>
        <p>Test source</p>
        <listWit><witness xml:id="abbyy">abbyy</witness></listWit>
      </sourceDesc>
    </fileDesc>
  </teiHeader>
  <facsimile>
    <surface xml:id="surface_page_0001">
      <zone xml:id="z_page_0001_0000" ulx="0" uly="0" lrx="10" lry="10"/>
    </surface>
  </facsimile>
  <text>
    <body>
      <ab>
        <w xml:id="w_page_0001_0000" facs="#z_page_0001_0000">
          <app><lem wit="#abbyy" cert="high">Aaron</lem></app>
        </w>
      </ab>
    </body>
  </text>
</TEI>
""",
    )


def test_valid_materialized_page_passes_both_critical_invariants(tmp_path: Path) -> None:
    page = REAL_PAGE if REAL_PAGE.exists() else _synthetic_valid_materialized_page(tmp_path)

    assert validate_file(page) == []


def test_witnessless_lemma_without_resp_fails(tmp_path: Path) -> None:
    page = _write_tei(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>Bad witnessless lemma</title></titleStmt>
      <publicationStmt><p>Test</p></publicationStmt>
      <sourceDesc><p>Test source</p></sourceDesc>
    </fileDesc>
  </teiHeader>
  <text><body><p><app><lem cert="medium">Aaron</lem></app></p></body></text>
</TEI>
""",
    )

    errors = validate_file(page)

    assert errors
    assert any("witnessless lem" in error for error in errors)


def test_word_facs_without_matching_zone_fails(tmp_path: Path) -> None:
    page = _write_tei(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>Bad facs target</title></titleStmt>
      <publicationStmt><p>Test</p></publicationStmt>
      <sourceDesc>
        <p>Test source</p>
        <listWit><witness xml:id="abbyy">abbyy</witness></listWit>
      </sourceDesc>
    </fileDesc>
  </teiHeader>
  <facsimile>
    <surface xml:id="surface_page_0001">
      <zone xml:id="z_page_0001_0000" ulx="0" uly="0" lrx="10" lry="10"/>
    </surface>
  </facsimile>
  <text>
    <body>
      <ab>
        <w xml:id="w_page_0001_0000" facs="#z_missing">
          <app><lem wit="#abbyy" cert="high">Aaron</lem></app>
        </w>
      </ab>
    </body>
  </text>
</TEI>
""",
    )

    errors = validate_file(page)

    assert errors
    assert any("#z_missing" in error for error in errors)


def test_witnessless_lemma_fixture_with_resp_passes() -> None:
    if not WITNESSLESS_FIXTURE.exists():
        pytest.skip(f"{WITNESSLESS_FIXTURE.as_posix()} is absent")

    assert validate_file(WITNESSLESS_FIXTURE) == []
