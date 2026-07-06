from __future__ import annotations

import pytest

from build.tools import produce_je_corrected


def test_produce_page_0010_matches_committed_sidecar_byte_for_byte(tmp_path) -> None:
    wct_path = produce_je_corrected.WCT_DIR / "page_0010.json"
    expected = produce_je_corrected.REPO_ROOT / "reports" / "je-corrected" / "vol_02" / "page_0010.json"
    if not wct_path.exists() or not expected.exists() or not produce_je_corrected.WORK_META_PATH.exists():
        pytest.skip("JE vol_02 frozen evidence is not present in this checkout")

    work_meta = produce_je_corrected._load_json(produce_je_corrected.WORK_META_PATH)
    thresholds = produce_je_corrected.load_thresholds(produce_je_corrected.THRESHOLDS_PATH)
    schema = produce_je_corrected._load_json(produce_je_corrected.CORRECTED_SCHEMA_PATH)

    produced = produce_je_corrected.produce_page(
        wct_path=wct_path,
        output_dir=tmp_path,
        work_meta=work_meta,
        thresholds=thresholds,
        schema=schema,
    )

    assert produced.read_bytes() == expected.read_bytes()
