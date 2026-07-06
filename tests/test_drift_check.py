"""Tests for the JE apparatus-TEI drift checker."""
from __future__ import annotations

import json
from pathlib import Path

from lxml import etree

from build.lib.canonical_token import canonical_token_id
from build.tei.drift_check import main, page_drift
from build.tei.materialize_je import materialize_page_document
from build.tei.writer import TEI_NS, serialize

LEM = f"{{{TEI_NS}}}lem"


def _doc_position(position_id: str, text: str, x: int) -> dict:
    return {
        "position_id": position_id,
        "reference_bbox": {"x": x, "y": 20, "w": 30, "h": 10},
        "candidate_set": [
            {"candidate_id": "cand_001", "raw_reading": text, "attesting_families": ["abbyy", "tesseract"]},
            {"candidate_id": "cand_002", "raw_reading": f"{text}x", "attesting_families": ["azure-ai-vision"]},
        ],
    }


def _wct_page(page_id: str = "page_0010", first_text: str = "on", token_count: int = 2) -> dict:
    token_texts = [first_text] + [f"token{index:03d}" for index in range(1, token_count)]
    positions = [
        _doc_position(f"vol_02:{page_id}:body:c1:l000:p{index:03d}", text, 10 + (index * 40))
        for index, text in enumerate(token_texts)
    ]
    return {
        "work_id": "jewish-encyclopedia.vol_02",
        "volume_id": "vol_02",
        "page_id": page_id,
        "source_image": {
            "path": f"raw/jewish-encyclopedia/ia-pages/vol_02/{page_id}.jpg",
            "sha256": "abc123",
        },
        "available_engines": [
            {"engine_id": "ia-abbyy-v1", "family": "abbyy"},
            {"engine_id": "tesseract-py314-v1", "family": "tesseract"},
            {"engine_id": "azure-ai-vision-v1", "family": "azure-ai-vision"},
        ],
        "reading_order": [position["position_id"] for position in positions],
        "positions": positions,
    }


def _event_for(wct_page: dict, edition_page_key: dict, ordinal: int) -> dict:
    position_id = wct_page["reading_order"][ordinal]
    return {
        "event_id": f"evt-{ordinal}",
        "canonical_token_id": canonical_token_id(
            "jewish-encyclopedia.vol_02",
            "vol_02",
            edition_page_key,
            ordinal,
        ),
        "structural_path_at_decision": position_id,
        "status_authority": "consensus",
        "actor_id": "system:corrector",
        "decision_extras_carried": {"chosen_reading_index": 0, "origin_kind": "observed"},
    }


def _events(wct_page: dict, edition_page_key: dict) -> list[dict]:
    return [_event_for(wct_page, edition_page_key, ordinal) for ordinal in range(len(wct_page["reading_order"]))]


def _write_materialized(
    tmp_path: Path,
    first_text: str = "on",
    token_count: int = 2,
    page_id: str = "page_0010",
) -> tuple[Path, dict, list[dict], dict]:
    wct_page = _wct_page(page_id=page_id, first_text=first_text, token_count=token_count)
    edition_page_key = {"section": "body", "anchor": 10, "ordinal": 0}
    events = _events(wct_page, edition_page_key)
    tree = materialize_page_document(
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    )
    committed_path = tmp_path / f"{page_id}.tei.xml"
    serialize(tree, committed_path)
    return committed_path, wct_page, events, edition_page_key


def test_page_drift_returns_empty_for_clean_rebuild(tmp_path: Path) -> None:
    committed_path, wct_page, events, edition_page_key = _write_materialized(tmp_path)

    assert page_drift(
        committed_path,
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    ) == []


def test_page_drift_reports_hand_edited_lemma(tmp_path: Path) -> None:
    committed_path, wct_page, events, edition_page_key = _write_materialized(tmp_path)
    tree = etree.parse(str(committed_path))
    lem = tree.find(f".//{LEM}")
    lem.text = "hand-edit"
    tree.write(str(committed_path), encoding="UTF-8", xml_declaration=True, pretty_print=True)

    differences = page_drift(
        committed_path,
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    )

    assert differences
    assert any("page_0010" in difference for difference in differences)
    assert any("drift" in difference.lower() for difference in differences)
    assert any("hand-edit" in difference or "on" in difference for difference in differences)


def test_page_drift_reports_injected_xml_comment(tmp_path: Path) -> None:
    committed_path, wct_page, events, edition_page_key = _write_materialized(tmp_path)
    text = committed_path.read_text(encoding="utf-8")
    committed_path.write_text(text.replace("<body>", "<body><!-- reviewer drift -->", 1), encoding="utf-8")

    differences = page_drift(
        committed_path,
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    )

    assert differences
    assert any("drift" in difference.lower() for difference in differences)


def test_page_drift_ignores_trailing_newline_only_difference(tmp_path: Path) -> None:
    committed_path, wct_page, events, edition_page_key = _write_materialized(tmp_path)
    committed_path.write_text(committed_path.read_text(encoding="utf-8").rstrip() + "\n\n", encoding="utf-8")

    assert page_drift(
        committed_path,
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    ) == []


def test_page_drift_treats_entity_and_literal_as_equivalent(tmp_path: Path) -> None:
    committed_path, wct_page, events, edition_page_key = _write_materialized(tmp_path, first_text="A&B")
    committed_path.write_text(
        committed_path.read_text(encoding="utf-8").replace("A&amp;B", "A&#38;B", 1),
        encoding="utf-8",
    )

    assert page_drift(
        committed_path,
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    ) == []


def test_page_drift_reports_non_ascii_lemma_with_ascii_safe_detail(tmp_path: Path) -> None:
    committed_path, wct_page, events, edition_page_key = _write_materialized(tmp_path, first_text="λόγος")
    tree = etree.parse(str(committed_path))
    lem = tree.find(f".//{LEM}")
    lem.text = "logos"
    tree.write(str(committed_path), encoding="UTF-8", xml_declaration=True, pretty_print=True)

    differences = page_drift(
        committed_path,
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    )

    assert differences
    assert all(difference.isascii() for difference in differences)


def test_page_drift_bounds_single_lemma_difference_detail(tmp_path: Path) -> None:
    committed_path, _committed_wct_page, _committed_events, edition_page_key = _write_materialized(
        tmp_path,
        first_text="original",
        token_count=80,
    )
    rebuilt_wct_page = _wct_page(first_text="changed", token_count=80)
    rebuilt_events = _events(rebuilt_wct_page, edition_page_key)

    differences = page_drift(
        committed_path,
        rebuilt_wct_page,
        rebuilt_events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    )

    assert differences
    assert differences[0].isascii()
    assert len(differences[0]) <= 500


def test_page_drift_reports_missing_committed_file(tmp_path: Path) -> None:
    _committed_path, wct_page, events, edition_page_key = _write_materialized(tmp_path)
    missing_path = tmp_path / "missing.tei.xml"

    differences = page_drift(
        missing_path,
        wct_page,
        events,
        work_id="jewish-encyclopedia.vol_02",
        volume_id="vol_02",
        edition_page_key=edition_page_key,
    )

    assert differences == ["page_0010: missing committed TEI at " + missing_path.as_posix()]


def test_cli_returns_nonzero_when_any_page_drifts(tmp_path: Path, capsys) -> None:
    committed_path, wct_page, events, _edition_page_key = _write_materialized(tmp_path)
    tree = etree.parse(str(committed_path))
    tree.find(f".//{LEM}").text = "hand-edit"
    tree.write(str(committed_path), encoding="UTF-8", xml_declaration=True, pretty_print=True)

    ledger_path = tmp_path / "events.jsonl"
    ledger_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    wct_dir = tmp_path / "wct"
    wct_dir.mkdir()
    (wct_dir / "page_0010.json").write_text(json.dumps(wct_page), encoding="utf-8")
    ia_manifest_path = tmp_path / "ia_manifest.json"
    ia_manifest_path.write_text(json.dumps({"pages": [{"sha256": "sha256:abc123", "page_num": 10}]}), encoding="utf-8")

    result = main(
        [
            "--ledger",
            str(ledger_path),
            "--wct-dir",
            str(wct_dir),
            "--ia-manifest",
            str(ia_manifest_path),
            "--tei-dir",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "DRIFT page_0010" in output
    assert "summary: pages_checked=1 drift_free=0 drifted=1 missing=0" in output


def test_cli_reports_page_error_and_continues_to_later_clean_page(tmp_path: Path, capsys) -> None:
    _bad_path, bad_wct_page, bad_events, _bad_key = _write_materialized(tmp_path, page_id="page_0010")
    _clean_path, clean_wct_page, clean_events, _clean_key = _write_materialized(tmp_path, page_id="page_0011")
    bad_events[0]["structural_path_at_decision"] = "vol_02:page_0010:body:c9:l999:p999"

    ledger_path = tmp_path / "events.jsonl"
    all_events = bad_events + clean_events
    ledger_path.write_text("\n".join(json.dumps(event) for event in all_events) + "\n", encoding="utf-8")
    wct_dir = tmp_path / "wct"
    wct_dir.mkdir()
    (wct_dir / "page_0010.json").write_text(json.dumps(bad_wct_page), encoding="utf-8")
    (wct_dir / "page_0011.json").write_text(json.dumps(clean_wct_page), encoding="utf-8")
    ia_manifest_path = tmp_path / "ia_manifest.json"
    ia_manifest_path.write_text(json.dumps({"pages": [{"sha256": "sha256:abc123", "page_num": 10}]}), encoding="utf-8")

    result = main(
        [
            "--ledger",
            str(ledger_path),
            "--wct-dir",
            str(wct_dir),
            "--ia-manifest",
            str(ia_manifest_path),
            "--tei-dir",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "DRIFT page_0010" in output
    assert "structural_path_at_decision" in output
    assert "PASS page_0011" in output
    assert "summary: pages_checked=2 drift_free=1 drifted=1 missing=0" in output
