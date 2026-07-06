from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from build.lib.wct_builder import LayoutEscalation
from build.tools.ocr_pipeline import drive_reconciliation_chain as chain
from build.tools.ocr_pipeline import reconcile_s3


def test_workers_for_throttle_matches_s1_runner_pattern() -> None:
    # canonical names (centralized in build/lib/ocr_throttle.py)
    assert chain._workers_for_throttle("minimal-4") == 4
    assert chain._workers_for_throttle("background-8") == 8


def test_build_parser_accepts_workers_override() -> None:
    args = chain.build_parser().parse_args(["--pages", "10", "--workers", "1"])

    assert args.workers == 1


def test_reconcile_page_inline_writes_record_and_sidecars(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[Path, dict]] = []

    def fake_reconcile_degraded(wct_page, work_meta, *, occurred_at):
        assert wct_page == {"positions": []}
        assert work_meta == {"work_id": "w1"}
        assert occurred_at == "2026-06-06T00:00:00+00:00"
        return SimpleNamespace(
            reconciled_record={"blocks": []},
            matrix_event_candidates=[],
            reviewer_queue=[{"position_id": "p1"}],
        )

    def fake_write_json_atomic(path, payload, schema):
        calls.append((path, payload))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(reconcile_s3, "reconcile_degraded", fake_reconcile_degraded)
    monkeypatch.setattr(reconcile_s3, "write_json_atomic", fake_write_json_atomic)

    output = tmp_path / "vol_01" / "page_0010.json"
    reconcile_s3.reconcile_page_inline(
        {"positions": []},
        {"work_id": "w1"},
        output,
        "2026-06-06T00:00:00+00:00",
    )

    assert calls == [
        (output, {"blocks": []}),
        (output.parent / "page_0010.matrix_candidates.json", {"candidates": []}),
        (
            output.parent / "page_0010.reviewer_queue.json",
            {"queue": [{"position_id": "p1"}]},
        ),
    ]


def test_drive_pages_skip_existing_skips_completed_pages(
    tmp_path: Path, monkeypatch
) -> None:
    """skip_existing=True skips pages whose reconciled output already exists on disk.

    Verifies the idempotency path: a page whose reconciled JSON is already
    present is not re-processed (WCT not rebuilt, reconcile not re-run).
    """
    reconciled_path = tmp_path / "reconciled" / "vol_01" / "page_0010.json"
    reconciled_path.parent.mkdir(parents=True)
    reconciled_path.write_text('{"done": true}', encoding="utf-8")

    build_calls: list = []
    monkeypatch.setattr(chain, "build_wct_for_page", lambda **kw: build_calls.append(kw) or {})

    result = chain.drive_pages(
        volume=1,
        pages=[10],
        skip_existing=True,
        run_s1_s2=False,
        s2_root=tmp_path / "s2",
        single_root=tmp_path / "single",
        wct_root=tmp_path / "wct",
        reconciled_root=tmp_path / "reconciled",
        max_workers=1,
    )

    assert result == [], "skipped pages must not appear in the summary list"
    assert build_calls == [], "build_wct_for_page must not be called for already-done pages"


def test_source_image_metadata_uses_repo_relative_path(tmp_path: Path) -> None:
    repo = tmp_path
    image = repo / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_01" / "page_0010.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"fixture image")

    metadata = chain.source_image_metadata(repo, 1, 10)

    assert metadata == {
        "path": "raw/internet-archive/schaff-herzog-pages/vol_01/page_0010.jpg",
        "sha256": hashlib.sha256(b"fixture image").hexdigest(),
    }


def test_default_engines_no_surya() -> None:
    assert "surya-py312-v1" not in chain.DEFAULT_ENGINES


def test_default_engines_has_azure_and_kraken() -> None:
    assert "azure-ai-vision-v1" in chain.DEFAULT_ENGINES
    assert "kraken-py312-v1" in chain.DEFAULT_ENGINES


def test_single_rendering_paths_missing_engine_skips(tmp_path: Path) -> None:
    """A missing engine file is skipped; the two present engines are returned."""
    s2_root = tmp_path / "s2"
    for engine in ("tesseract-py314-v1", "ia-abbyy-v1"):
        page_dir = s2_root / "vol_01" / engine / "pages"
        page_dir.mkdir(parents=True)
        (page_dir / "page_0005.rendering-v1.json").write_text(
            "{}", encoding="utf-8"
        )

    paths = chain._single_rendering_paths(
        volume=1,
        page=5,
        engines=["tesseract-py314-v1", "ia-abbyy-v1", "azure-ai-vision-v1"],
        s2_root=s2_root,
        single_root=tmp_path / "single",
    )

    assert len(paths) == 2
    engine_names = [p.parent.parent.name for p in paths]
    assert "tesseract-py314-v1" in engine_names
    assert "ia-abbyy-v1" in engine_names
    assert "azure-ai-vision-v1" not in engine_names


def test_single_rendering_paths_too_few_engines_raises(tmp_path: Path) -> None:
    """Fewer than 2 valid engines raises FileNotFoundError."""
    import pytest

    s2_root = tmp_path / "s2"
    engine = "tesseract-py314-v1"
    page_dir = s2_root / "vol_01" / engine / "pages"
    page_dir.mkdir(parents=True)
    (page_dir / "page_0005.rendering-v1.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        chain._single_rendering_paths(
            volume=1,
            page=5,
            engines=["tesseract-py314-v1", "ia-abbyy-v1"],
            s2_root=s2_root,
            single_root=tmp_path / "single",
        )


def test_find_escalated_pages_empty(tmp_path: Path) -> None:
    """No reviewer_queue files returns empty list."""
    reconciled_root = tmp_path / "reconciled"
    (reconciled_root / "vol_01").mkdir(parents=True)

    result = chain.find_escalated_pages(reconciled_root, "vol_01", [1, 2, 3])

    assert result == []


def test_find_escalated_pages_detects_non_empty_queue(tmp_path: Path) -> None:
    """Page with non-empty queue array is returned as escalated."""
    reconciled_root = tmp_path / "reconciled"
    vol_dir = reconciled_root / "vol_01"
    vol_dir.mkdir(parents=True)
    (vol_dir / "page_0007.reviewer_queue.json").write_text(
        '{"queue": [{"position_id": "vol_01:page_0007:body:c1:l000:p000",'
        ' "reason": "dispute"}]}',
        encoding="utf-8",
    )

    result = chain.find_escalated_pages(reconciled_root, "vol_01", [7])

    assert result == [7]


def test_drive_pages_layout_escalation_skips_page(
    tmp_path: Path, monkeypatch
) -> None:
    """LayoutEscalation from build_wct_for_page skips the page and continues.

    A page that triggers layout escalation (e.g. spanning_lines with no surya
    fallback) must not crash the whole drive -- the page is logged and skipped.
    """
    s2_root = tmp_path / "s2"
    for engine in ("tesseract-py314-v1", "ia-abbyy-v1"):
        page_dir = s2_root / "vol_01" / engine / "pages"
        page_dir.mkdir(parents=True)
        (page_dir / "page_0010.rendering-v1.json").write_text("{}", encoding="utf-8")
        (page_dir / "page_0011.rendering-v1.json").write_text("{}", encoding="utf-8")

    (tmp_path / "work_meta.json").write_text("{}", encoding="utf-8")
    build_calls: list[int] = []

    def fake_build(**kw):
        build_calls.append(kw["page"])
        if kw["page"] == 10:
            raise LayoutEscalation("page_0010", ["spanning_lines"])
        return {"positions": [], "available_engines": []}

    monkeypatch.setattr(chain, "build_wct_for_page", fake_build)
    monkeypatch.setattr(chain, "reconcile_page_inline", lambda **kw: None)
    monkeypatch.setattr(
        chain,
        "source_image_metadata",
        lambda *args: {"path": "raw/fixture/page_0010.jpg", "sha256": "0" * 64},
    )

    result = chain.drive_pages(
        volume=1,
        pages=[10, 11],
        skip_existing=False,
        run_s1_s2=False,
        s2_root=s2_root,
        single_root=tmp_path / "single",
        wct_root=tmp_path / "wct",
        reconciled_root=tmp_path / "reconciled",
        work_meta=tmp_path / "work_meta.json",
        max_workers=1,
    )

    assert build_calls == [10, 11], "build must be attempted for both pages"
    assert len(result) == 1, "escalated page must not appear in summary"
    assert result[0]["page"] == 11, "only the non-escalated page is in summary"


def test_find_escalated_pages_ignores_empty_queue(tmp_path: Path) -> None:
    """Page whose queue array is empty is not escalated."""
    reconciled_root = tmp_path / "reconciled"
    vol_dir = reconciled_root / "vol_01"
    vol_dir.mkdir(parents=True)
    (vol_dir / "page_0008.reviewer_queue.json").write_text(
        '{"queue": []}', encoding="utf-8"
    )

    result = chain.find_escalated_pages(reconciled_root, "vol_01", [8])

    assert result == []


def test_drive_pages_non_fatal_exception_skips_page_and_continues(
    tmp_path: Path, monkeypatch
) -> None:
    """A non-LayoutEscalation exception is logged and skipped; drive continues.

    A page with fewer than 2 engine renderings raises FileNotFoundError inside
    _single_rendering_paths. This must not abort the drive -- the failing page is
    counted as an error while remaining pages proceed (REL-08 compliance for the
    sequential path).
    """
    s2_root = tmp_path / "s2"
    # page 10: only ONE engine rendering -- _single_rendering_paths raises FileNotFoundError
    for engine in ("tesseract-py314-v1",):
        page_dir = s2_root / "vol_01" / engine / "pages"
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "page_0010.rendering-v1.json").write_text("{}", encoding="utf-8")
    # page 11: TWO engines -- should process normally (tesseract dir already exists from above)
    for engine in ("tesseract-py314-v1", "ia-abbyy-v1"):
        page_dir = s2_root / "vol_01" / engine / "pages"
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "page_0011.rendering-v1.json").write_text("{}", encoding="utf-8")

    (tmp_path / "work_meta.json").write_text("{}", encoding="utf-8")
    build_calls: list[int] = []

    def fake_build(**kw):
        build_calls.append(kw["page"])
        return {"positions": [], "available_engines": []}

    monkeypatch.setattr(chain, "build_wct_for_page", fake_build)
    monkeypatch.setattr(chain, "reconcile_page_inline", lambda **kw: None)
    monkeypatch.setattr(
        chain,
        "source_image_metadata",
        lambda *args: {"path": "raw/fixture/page_0010.jpg", "sha256": "0" * 64},
    )

    result = chain.drive_pages(
        volume=1,
        pages=[10, 11],
        skip_existing=False,
        run_s1_s2=False,
        s2_root=s2_root,
        single_root=tmp_path / "single",
        wct_root=tmp_path / "wct",
        reconciled_root=tmp_path / "reconciled",
        work_meta=tmp_path / "work_meta.json",
        max_workers=1,
    )

    # Page 10 failed before build (only 1 engine); page 11 succeeded.
    assert build_calls == [11], "build must not be called for the page that fails before it"
    assert len(result) == 1
    assert result[0]["page"] == 11
