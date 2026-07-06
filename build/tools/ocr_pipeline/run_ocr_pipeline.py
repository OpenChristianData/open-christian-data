"""S1+S2 pipeline: run OCR engines and render outputs.

Runs S1 for each configured engine (live OCR and imported OCR), renders S2
renderings across all 13 volumes.

Active S1 engines fall into two categories:

  Live OCR -- run inference on the page image:
    Tesseract     fast    -- seconds per page
    Surya         slow    -- ~185s/page at --surya-max-width 2500 (no GPU)
    Kraken        fast    -- seconds per page (CATMuS-Print Latin model)
    Kraken Greek  fast    -- seconds per page (AjaxMultiCommentary Greek model)

  Imported OCR -- parse pre-computed results that Internet Archive bundles
    with the scans (NOT live inference):
    ABBYY         instant -- reads FineReader JSON files IA ships alongside
                            the page JPEGs; ingestion is fast because the
                            OCR work was already done upstream.

## Engine throughput

Engines run sequentially. Surya is the bottleneck at full resolution.
Use --surya-max-width 2500 to halve the time with no measurable quality loss
(same word count, near-identical block count).

--throttle minimal-4 (idle priority) is appropriate for Surya (GPU-bound, runs
unattended). For CPU-bound engines (Tesseract, Kraken), idle priority collapses
throughput to 3+ min/page. Use --throttle background-8 (below-normal) for those.

## Typical usage (from repo root):

    py -3 build/tools/ocr_pipeline/run_ocr_pipeline.py --volumes 2 3 4
    py -3 build/tools/ocr_pipeline/run_ocr_pipeline.py  # defaults to 1-13

## Geometry-only preset

The WCT geometry chain (downstream reconciliation) only consumes Surya,
Tesseract, and ABBYY outputs. Use --engines geometry to skip the Kraken lanes:

    py -3 build/tools/ocr_pipeline/run_ocr_pipeline.py --engines geometry --volumes 1 --pages 1-10
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class _Tee:
    """Write every print() to both stdout and a log file simultaneously."""

    def __init__(self, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = log_path.open("a", encoding="utf-8")
        self._stdout = sys.__stdout__

    def write(self, s: str) -> None:
        self._stdout.write(s)
        if not self._log.closed:
            self._log.write(s)

    def flush(self) -> None:
        self._stdout.flush()
        if not self._log.closed:
            self._log.flush()

    def fileno(self) -> int:
        return self._stdout.fileno()

    def close(self) -> None:
        self._log.close()

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.nsh_leaf_model import ocr_input  # noqa: E402
from build.lib.page_order import volume_duplicate_stems  # noqa: E402
from build.lib.ocr_store_paths import (  # noqa: E402
    S1_SIDECARS_ROOT,
    S2_RENDERINGS_ROOT,
)
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.ocr_throttle import THROTTLE_CHOICES  # noqa: E402
from build.parsers.s1_abbyy_normalizer import normalize_abbyy_rich_volume  # noqa: E402
from build.parsers.s1_kraken_greek_runner import normalize_volume as kraken_greek_normalize  # noqa: E402
from build.parsers.s1_kraken_runner import normalize_volume as kraken_normalize  # noqa: E402
from build.parsers.s1_surya_runner import normalize_volume as surya_normalize  # noqa: E402
from build.parsers.s1_tesseract_runner import normalize_volume as tesseract_normalize  # noqa: E402
from build.tools.ocr_pipeline import ocr_doctor  # noqa: E402
from build.tools.ocr_pipeline.render_s2 import (  # noqa: E402
    STAGE_VERSION as _S2_STAGE_VERSION,
    _RenderAborted,
    _file_sha256,
    render_manifest,
)

# Live OCR engines: run inference on the page image.
LIVE_OCR_ENGINES = ("tesseract", "surya", "kraken", "kraken-greek")

# Imported OCR engines: parse pre-computed results bundled with IA scans.
# ABBYY FineReader output is NOT generated here -- it is ingested from the
# ia-abbyy-* JSON files that Internet Archive ships alongside the page JPEGs.
IMPORTED_OCR_ENGINES = ("abbyy",)

# All S1 engine selector names (CLI --engines). Live engines first.
ALL_ENGINES = LIVE_OCR_ENGINES + IMPORTED_OCR_ENGINES

# Geometry preset: engines whose word-bbox outputs the WCT geometry chain
# consumes (Surya layout + Tesseract/ABBYY word geometry). Skips Kraken lanes.
GEOMETRY_PRESET = frozenset({"surya", "tesseract", "abbyy"})

DEFAULT_VOLUMES = list(range(1, 14))

DEFAULT_S1_ROOT = S1_SIDECARS_ROOT
DEFAULT_S2_ROOT = S2_RENDERINGS_ROOT
DEFAULT_INPUT_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"

# Sentinel file: GUI or operator creates this to request graceful shutdown.
_STOP_SENTINEL = REPO_ROOT / "reports" / ".pipeline_stop_requested"

# Module-level shutdown event; also set by SIGINT handler.
_shutdown_event = threading.Event()

# ABBYY lineages: rich per-page sidecars live under DEFAULT_INPUT_ROOT as
# page_NNNN.<suffix>.json where <suffix> is the lineage minus its -vN tag.
# Presence is checked per volume (uneven coverage across volumes).
ABBYY_LINEAGES = [
    "ia-abbyy-v1",
    "ia-abbyy-haucgoog-v1",
    "ia-abbyy-dli-v1",
    "ia-abbyy-haucgoog-c1-v1",
    "ia-abbyy-haucgoog-c2-v1",
    "ia-abbyy-haucgoog-c3-v1",
    "ia-abbyy-haucgoog-c4-v1",
]

LIVE_ENGINE_LINEAGES = {
    "tesseract": "tesseract-py314-v1",
    "surya": "surya-py312-v1",
    "kraken": "kraken-py312-v1",
    "kraken-greek": "kraken-greek-py312-v1",
}


def _check_shutdown() -> bool:
    """Return True if a graceful shutdown has been requested.

    Checks both the threading event (set by SIGINT / second Ctrl+C) and the
    sentinel file (created by the GUI Stop button or any external process).
    Consuming the sentinel file prevents it from being seen by future runs.
    """
    if _shutdown_event.is_set():
        return True
    if _STOP_SENTINEL.exists():
        _shutdown_event.set()
        try:
            _STOP_SENTINEL.unlink()  # standards: log/temp rotation -- stop sentinel is a one-shot signal file
        except OSError:
            pass
        return True
    return False


def _start_stop_sentinel_watcher(poll_seconds: float = 1.0) -> threading.Thread:
    """Watch the GUI stop sentinel while long-running engines are active."""

    def _watch() -> None:
        while not _shutdown_event.is_set():
            if _STOP_SENTINEL.exists():
                _shutdown_event.set()
                try:
                    _STOP_SENTINEL.unlink()  # standards: log/temp rotation -- stop sentinel is a one-shot signal file
                except OSError:
                    pass
                return
            time.sleep(poll_seconds)

    thread = threading.Thread(target=_watch, name="ocr-stop-sentinel", daemon=True)
    thread.start()
    return thread


def _setup_shutdown_handlers() -> None:
    """Handle Ctrl+C gracefully: set the shutdown event instead of raising.

    First Ctrl+C: sets the event, pipeline finishes the current page (~10-45s).
    Second Ctrl+C: restores default SIGINT so the process exits immediately.
    """
    _original_sigint = signal.getsignal(signal.SIGINT)

    def _handler(sig: int, frame: Any) -> None:
        if not _shutdown_event.is_set():
            _shutdown_event.set()
            print(
                "\nInterrupted -- finishing current page before stopping"
                " (Ctrl+C again to force-quit)...",
                flush=True,
            )
        else:
            signal.signal(signal.SIGINT, _original_sigint)
            if callable(_original_sigint):
                _original_sigint(sig, frame)
            elif _original_sigint == signal.SIG_DFL:
                raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _handler)


def _volume_label(volume: int) -> str:
    return f"vol_{volume:02d}"


def _volume_leaf_range(input_root: Path, volume: int) -> str:
    """``leaves <min>-<max> (<n> body)`` for the run-start log (R6a).

    Read-only summary of the OCR-input body leaves a volume will process, so the
    run log records the leaf range each volume covers next to its progress line.
    """
    manifest_path = Path(input_root) / f"{_volume_label(volume)}.manifest.json"
    if not manifest_path.exists():
        return "leaf range unknown (no source manifest)"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        leaves = [
            leaf["leaf_num"]
            for leaf in ocr_input(manifest)
            if isinstance(leaf.get("leaf_num"), int)
        ]
    except (json.JSONDecodeError, KeyError, OSError, ValueError) as exc:
        return f"leaf range unavailable ({type(exc).__name__})"
    if not leaves:
        return "no OCR-input body leaves"
    return f"leaves {min(leaves)}-{max(leaves)} ({len(leaves)} body)"


def _parse_pages_arg(values: list[str]) -> list[int] | None:
    """Convert --pages CLI tokens to a sorted, deduped list of page numbers.

    Each token is either an integer ("5") or an inclusive range ("1-10").
    Returns None when values is empty (meaning: process whole volume).
    Raises ValueError for invalid inputs: page < 1, reversed range, empty result.
    """
    if not values:
        return None
    result: set[int] = set()
    for token in values:
        if "-" in token:
            parts = token.split("-", 1)
            lo, hi = int(parts[0]), int(parts[1])
            if lo < 1:
                raise ValueError(f"--pages: page numbers must be >= 1, got {lo!r}")
            if hi < lo:
                raise ValueError(
                    f"--pages: range {token!r} is reversed (lo={lo} > hi={hi})"
                )
            result.update(range(lo, hi + 1))
        else:
            p = int(token)
            if p < 1:
                raise ValueError(f"--pages: page numbers must be >= 1, got {p!r}")
            result.add(p)
    if not result:
        raise ValueError("--pages: resolved page set is empty")
    return sorted(result)


def _resolve_engines(engine_args: list[str] | None) -> list[str] | None:
    """Expand --engines CLI tokens to an ordered engine list.

    Returns None (run all engines in default order) when engine_args is empty.
    Engines run in the order given on the CLI; duplicates drop (first wins).
    The special token "geometry" expands in-place to the WCT geometry preset in
    canonical order (surya, tesseract, abbyy).
    Example: --engines kraken geometry runs kraken, then surya, tesseract, abbyy.
    """
    if not engine_args:
        return None
    seen: set[str] = set()
    result: list[str] = []
    for name in engine_args:
        candidates = ["surya", "tesseract", "abbyy"] if name == "geometry" else [name]
        for engine in candidates:
            if engine not in seen:
                seen.add(engine)
                result.append(engine)
    return result


def _s2_output_dir(s2_root: Path, vol_label: str, source_lineage_id: str) -> Path:
    return s2_root / vol_label / source_lineage_id


def _eligible_s2_page_ids(manifest: dict[str, Any]) -> list[str]:
    return [
        str(page_ref["page_native_id"])
        for page_ref in manifest.get("pages", [])
        if page_ref.get("status") in {"eligible", "diagnostic_only"}
    ]


def _s2_output_is_current(output_dir: Path, index_path: Path, manifest: dict[str, Any]) -> bool:
    """Return true when existing S2 pages match the current stable S1 inputs."""
    index = json.loads(index_path.read_text(encoding="utf-8"))
    expected_refs = [
        page_ref
        for page_ref in manifest.get("pages", [])
        if page_ref.get("status") in {"eligible", "diagnostic_only"}
    ]
    expected_pages = [str(page_ref["page_native_id"]) for page_ref in expected_refs]
    if not expected_pages or index.get("pages") != expected_pages:
        return False

    pages_dir = output_dir / "pages"
    for page_ref in expected_refs:
        page_id = str(page_ref["page_native_id"])
        page_file = pages_dir / f"{page_id}.rendering-v1.json"
        if not page_file.exists():
            return False
        existing = json.loads(page_file.read_text(encoding="utf-8"))
        rendered_pages = existing.get("pages") or []
        if len(rendered_pages) != 1 or not isinstance(rendered_pages[0], dict):
            return False
        rendered_page = rendered_pages[0]
        sidecar_refs = existing.get("source_sidecar_refs") or []
        if len(sidecar_refs) < 2 or not isinstance(sidecar_refs[1], dict):
            return False
        sidecar_path = Path(page_ref["sidecar_page_path"])
        if not sidecar_path.is_absolute():
            sidecar_path = REPO_ROOT / sidecar_path
        # R4a: per-page currentness keys on (canonical_leaf_id,
        # source_payload_sha256, sidecar sha); drop the volume-global manifest_id
        # equality so a rename elsewhere no longer invalidates an unchanged leaf.
        # Not-yet-leaf-keyed lineages (ABBYY, R7) fall back to the filename stem.
        if page_ref.get("canonical_leaf_id") is not None:
            page_identity_stale = (
                rendered_page.get("canonical_leaf_id") != page_ref.get("canonical_leaf_id")
            )
        else:
            page_identity_stale = (
                rendered_page.get("page_native_id") != page_ref.get("page_native_id")
            )
        if (
            existing.get("schema_version") != "rendering-v1"
            or existing.get("stage_version") != _S2_STAGE_VERSION
            or existing.get("rendering_id") != manifest.get("rendering_id")
            or existing.get("engine_family") != manifest.get("engine_family")
            or existing.get("engine_version") != manifest.get("engine_version")
            or existing.get("source_lineage_id") != manifest.get("source_lineage_id")
            or existing.get("work_id") != manifest.get("work_id")
            or existing.get("edition_id") != manifest.get("edition_id")
            or int(existing.get("volume", -1)) != int(manifest.get("volume", -2))
            # Mirror render_s2._page_rendering_is_current's identity key-set so the
            # two S2 currentness gates cannot drift (audit 2026-06-15): a stale
            # rendering must invalidate under either gate, never just one.
            or rendered_page.get("rendering_id") != manifest.get("rendering_id")
            or page_identity_stale
            or rendered_page.get("source_payload_sha256") != page_ref.get("source_payload_sha256")
            or sidecar_refs[1].get("path") != page_ref.get("sidecar_page_path")
            or sidecar_refs[1].get("sha256") != _file_sha256(sidecar_path)
        ):
            return False
    return True


def _run_tesseract(
    volume: int,
    *,
    s1_root: Path,
    input_root: Path,
    throttle_mode: str = "full-speed",
    pages: list[int] | None = None,
    force: bool = False,
    shutdown_event: threading.Event | None = None,
) -> Any:
    return tesseract_normalize(
        volume=volume,
        output_root=s1_root,
        input_root=input_root,
        throttle_mode=throttle_mode,
        pages=pages,
        force=force,
        shutdown_event=shutdown_event,
    )


def _run_surya(
    volume: int,
    *,
    s1_root: Path,
    input_root: Path,
    throttle_mode: str = "full-speed",
    pages: list[int] | None = None,
    force: bool = False,
    max_width: int | None = None,
    shutdown_event: threading.Event | None = None,
) -> Any:
    return surya_normalize(
        volume=volume,
        output_root=s1_root,
        input_root=input_root,
        throttle_mode=throttle_mode,
        pages=pages,
        force=force,
        max_width=max_width,
        shutdown_event=shutdown_event,
    )


def _run_kraken(
    volume: int,
    *,
    s1_root: Path,
    input_root: Path,
    throttle_mode: str = "full-speed",
    pages: list[int] | None = None,
    force: bool = False,
    shutdown_event: threading.Event | None = None,
) -> Any:
    return kraken_normalize(
        volume=volume,
        output_root=s1_root,
        input_root=input_root,
        throttle_mode=throttle_mode,
        pages=pages,
        force=force,
        shutdown_event=shutdown_event,
    )


def _run_kraken_greek(
    volume: int,
    *,
    s1_root: Path,
    input_root: Path,
    throttle_mode: str = "full-speed",
    pages: list[int] | None = None,
    force: bool = False,
    shutdown_event: threading.Event | None = None,
) -> Any:
    return kraken_greek_normalize(
        volume=volume,
        output_root=s1_root,
        input_root=input_root,
        throttle_mode=throttle_mode,
        pages=pages,
        force=force,
        shutdown_event=shutdown_event,
    )


def _run_abbyy_lineages(
    volume: int,
    *,
    s1_root: Path,
    input_root: Path,
    repo_root: Path = REPO_ROOT,
    pages: list[int] | None = None,
    force: bool = False,
) -> tuple[list[Any], dict[str, str]]:
    """Ingest ABBYY FineReader results pre-computed by Internet Archive.

    Internet Archive bundles ABBYY FineReader OCR alongside the page JPEGs as
    page_NNNN.<suffix>.json files. This function reads and normalizes those
    existing files -- it does NOT run OCR. The rich sidecars carry word
    bbox{x,y,w,h}, so ABBYY joins Tesseract as a word-geometry engine in the WCT.

    Skips lineages whose sidecars are absent for this volume -- IA coverage
    is uneven across volumes.
    """
    summaries = []
    lineage_failures: dict[str, str] = {}
    for lineage in ABBYY_LINEAGES:
        try:
            summary = normalize_abbyy_rich_volume(
                input_root,
                source_lineage_id=lineage,
                volume=volume,
                output_root=s1_root,
                repo_root=repo_root,
                pages=pages,
                force=force,
            )
            summaries.append(summary)
        except FileNotFoundError:
            # No pre-computed sidecars for this lineage/volume -- skip.
            continue
        except Exception as exc:
            lineage_failures[lineage] = str(exc)
            print(f"    abbyy/{lineage}: ingest failed -- {str(exc)[:120]}", flush=True)
    return summaries, lineage_failures


def _s2_render(
    manifest_path: Path,
    *,
    s2_root: Path,
    vol_label: str,
    input_root: Path = DEFAULT_INPUT_ROOT,
    manifest_index: int | None = None,
    manifest_total: int | None = None,
    shutdown_event: threading.Event | None = None,
    allow_stale_manifest: bool = False,
) -> Path | None:
    """Render one S1 manifest to S2. Returns output dir or None on failure.

    Skips re-rendering when the output already exists with a matching
    STAGE_VERSION (render_manifest enforces this via force=False).  Progress
    is printed so the GUI and log stay informative during the S2 phase.
    """
    if shutdown_event is not None and shutdown_event.is_set():
        return None  # pre-render check: skip silently, shutdown already announced
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lineage = str(manifest.get("source_lineage_id", "unknown"))
    output_dir = _s2_output_dir(s2_root, vol_label, lineage)
    index_path = output_dir / "index.json"
    idx_str = f"[{manifest_index}/{manifest_total}] " if manifest_index is not None else ""

    vol_num = int(manifest.get("volume", 0))
    exclude_stems = volume_duplicate_stems(input_root / f"vol_{vol_num:02d}") if vol_num > 0 else frozenset()

    # Fast-path: check skip before delegating so we can print "skipped" accurately.
    # Do not key this on the raw manifest file hash: S1 manifests carry
    # volatile metadata such as created_at, so timestamp-only rewrites must not
    # invalidate already-rendered S2 pages.
    if index_path.exists():
        try:
            if _s2_output_is_current(output_dir, index_path, manifest):
                print(f"    s2 {idx_str}{lineage}: skipped (ok)", flush=True)
                return output_dir
        except (OSError, ValueError, KeyError):
            pass  # corrupt/unreadable cached output -- fall through to re-render

    print(f"    s2 {idx_str}{lineage}: rendering...", flush=True)
    _t = time.monotonic()
    try:
        render_manifest(
            manifest_path,
            repo_root=REPO_ROOT,
            output_dir=output_dir,
            force=True,  # skip check already done above
            shutdown_event=shutdown_event,
            allow_stale_manifest=allow_stale_manifest,
            exclude_stems=exclude_stems,
        )
        elapsed = time.monotonic() - _t
        print(f"    s2 {idx_str}{lineage}: rendered ({elapsed:.1f}s)", flush=True)
        return output_dir
    except _RenderAborted:
        print(f"    s2 {idx_str}{lineage}: aborted (shutdown)", flush=True)
        return None
    except Exception as exc:
        print(f"    s2 {idx_str}{lineage}: failed -- {str(exc)[:120]}", flush=True)
        return None


def process_volume(
    volume: int,
    *,
    s1_root: Path,
    s2_root: Path,
    input_root: Path,
    throttle_mode: str = "full-speed",
    pages: list[int] | None = None,
    surya_max_width: int | None = None,
    engines: list[str] | None = None,
    shutdown_event: threading.Event | None = None,
    allow_stale_manifest: bool = False,
) -> dict[str, Any]:
    """Run S1+S2 for the selected engines on one volume.

    Failures at the page or engine level write visible records and are counted
    but do not abort processing of other engines or pages (REL-08).

    pages: optional 1-based page sequence numbers to process. Applies to both
    live OCR engines and ABBYY ingestion so smoke tests do not render a full
    ABBYY volume.
    surya_max_width: downscale images wider than this before Surya inference.
    2500 gives a ~2x speedup on 5034px-wide NSH scans with no measurable
    quality loss (same word count, near-identical block count).
    engines: ordered list of engines to run. None means all in default order.
    Pass the result of _resolve_engines() to honour CLI ordering.
    To re-run a volume from scratch, delete its manifest.state.json -- the runner
    will then treat all pages as unemitted.
    """
    vol_label = _volume_label(volume)
    engine_order = list(ALL_ENGINES) if engines is None else list(engines)
    vol_start = time.monotonic()
    pages_label = f" pages={pages}" if pages is not None else ""
    print(f"  {vol_label}: starting S1+S2{pages_label}", flush=True)

    s1_manifests: list[Path] = []
    s1_failures: dict[str, str] = {}
    engine_times: dict[str, float] = {}

    # S1 -- run engines in the requested order ---------------------------------

    for engine in engine_order:
        if shutdown_event is not None and shutdown_event.is_set():
            print(f"    Shutdown requested -- skipping remaining engines for {vol_label}", flush=True)
            break
        _t = time.monotonic()
        try:
            if engine == "tesseract":
                summary = _run_tesseract(
                    volume,
                    s1_root=s1_root,
                    input_root=input_root,
                    throttle_mode=throttle_mode,
                    pages=pages,
                    force=False,
                    shutdown_event=shutdown_event,
                )
                s1_manifests.append(summary.manifest_path)
                if summary.failed_pages:
                    print(
                        f"    tesseract: {summary.failed_pages} page(s) failed "
                        "(visible via ocr_inventory.py status)",
                        flush=True,
                    )
            elif engine == "surya":
                summary = _run_surya(
                    volume,
                    s1_root=s1_root,
                    input_root=input_root,
                    throttle_mode=throttle_mode,
                    pages=pages,
                    force=False,
                    max_width=surya_max_width,
                    shutdown_event=shutdown_event,
                )
                s1_manifests.append(summary.manifest_path)
                if summary.failed_pages:
                    print(
                        f"    surya: {summary.failed_pages} page(s) failed "
                        "(visible via ocr_inventory.py status)",
                        flush=True,
                    )
            elif engine == "kraken":
                summary = _run_kraken(
                    volume,
                    s1_root=s1_root,
                    input_root=input_root,
                    throttle_mode=throttle_mode,
                    pages=pages,
                    force=False,
                    shutdown_event=shutdown_event,
                )
                s1_manifests.append(summary.manifest_path)
                if summary.failed_pages:
                    print(
                        f"    kraken: {summary.failed_pages} page(s) failed "
                        "(visible via ocr_inventory.py status)",
                        flush=True,
                    )
            elif engine == "kraken-greek":
                summary = _run_kraken_greek(
                    volume,
                    s1_root=s1_root,
                    input_root=input_root,
                    throttle_mode=throttle_mode,
                    pages=pages,
                    force=False,
                    shutdown_event=shutdown_event,
                )
                s1_manifests.append(summary.manifest_path)
                if summary.failed_pages:
                    print(
                        f"    kraken-greek: {summary.failed_pages} page(s) failed "
                        "(visible via ocr_inventory.py status)",
                        flush=True,
                    )
            elif engine == "abbyy":
                # ABBYY is NOT live inference -- reads IA-bundled FineReader JSON.
                abbyy_summaries, abbyy_lineage_failures = _run_abbyy_lineages(
                    volume,
                    s1_root=s1_root,
                    input_root=input_root,
                    repo_root=REPO_ROOT,
                    pages=pages,
                    force=False,
                )
                for summary in abbyy_summaries:
                    s1_manifests.append(summary.manifest_path)
                if not abbyy_summaries and not abbyy_lineage_failures:
                    s1_failures["abbyy"] = (
                        "no ABBYY sidecars found for selected volume/pages"
                    )
                    print(
                        "    abbyy: no sidecars found for selected volume/pages",
                        flush=True,
                    )
                if abbyy_lineage_failures:
                    for lin, err in abbyy_lineage_failures.items():
                        s1_failures[f"abbyy/{lin}"] = err
        except Exception as exc:
            s1_failures[engine] = str(exc)
            print(f"    {engine}: S1 failed -- {str(exc)[:120]}", flush=True)
        finally:
            engine_times[engine] = time.monotonic() - _t

    n_s1 = len(s1_manifests)
    print(f"    {vol_label}: {n_s1} S1 manifest(s) produced", flush=True)

    # S2 -- render each S1 manifest
    s2_count = 0
    s2_failures: dict[str, str] = {}
    for s2_idx, manifest_path in enumerate(s1_manifests, start=1):
        if shutdown_event is not None and shutdown_event.is_set():
            break
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            lineage_key = manifest_path.name
            s2_failures[lineage_key] = f"manifest_read_error: {str(exc)[:120]}"
            print(f"    s2 [{s2_idx}/{n_s1}] {manifest_path.name}: corrupt manifest -- {str(exc)[:120]}", flush=True)
            continue
        lineage = str(manifest_data.get("source_lineage_id", "unknown"))
        output = _s2_render(
            manifest_path,
            s2_root=s2_root,
            vol_label=vol_label,
            manifest_index=s2_idx,
            manifest_total=n_s1,
            shutdown_event=shutdown_event,
            allow_stale_manifest=allow_stale_manifest,
        )
        if output:
            s2_count += 1
        else:
            s2_failures[lineage] = "render_failed"

    elapsed = time.monotonic() - vol_start
    timing_parts = [
        f"{eng}={engine_times[eng]:.1f}s"
        for eng in list(LIVE_OCR_ENGINES) + list(IMPORTED_OCR_ENGINES)
        if eng in engine_times
    ]
    print(
        f"  {vol_label}: done in {elapsed:.1f}s -- "
        f"{len(s1_manifests)} S1, {s2_count} S2",
        flush=True,
    )
    if timing_parts:
        print(f"    engine times: {' '.join(timing_parts)}", flush=True)
    return {
        "volume": volume,
        "s1_count": len(s1_manifests),
        "s2_count": s2_count,
        "s1_failures": s1_failures,
        "s2_failures": s2_failures,
        "engine_times": engine_times,
    }


def _preflight(
    args: argparse.Namespace,
    volumes: list[int],
    engines: list[str] | None,
) -> list[str]:
    """Run preflight checks. Returns a list of warning strings (empty = all clear).

    Checks performed:
    - input_root exists
    - s1_root parent can be created
    - s2_root parent can be created
    - for ABBYY engine: counts how many lineage directories are present per volume
    """
    warnings: list[str] = []
    if not args.input_root.exists():
        warnings.append(f"input_root does not exist: {args.input_root}")
    for root_name, root_path in [
        ("s1_root", args.s1_root),
        ("s2_root", args.s2_root),
    ]:
        try:
            root_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            warnings.append(f"cannot create {root_name} {root_path}: {exc}")

    selected = engines if engines is not None else list(ALL_ENGINES)
    if "abbyy" in selected and args.input_root.exists():
        for vol in volumes:
            vol_dir = args.input_root / _volume_label(vol)
            if not vol_dir.exists():
                warnings.append(f"input vol directory missing: {vol_dir}")
                continue
            present = sum(
                1 for lin in ABBYY_LINEAGES
                if any(vol_dir.glob(f"page_????.{lin.rsplit('-', 1)[0]}.json"))
                   or any(
                       vol_dir.glob(
                           f"page_????.*{lin.split('-abbyy-')[-1].rsplit('-v', 1)[0]}*.json"
                       )
                   )
            )
            if present == 0:
                warnings.append(
                    f"vol_{vol:02d}: no ABBYY sidecars found for any lineage in {vol_dir}"
                )
    return warnings


def _doctor_lineages_for_engines(engines: list[str] | None) -> list[str]:
    """Expand CLI engine selectors to S1 source_lineage_id values."""
    selected = list(ALL_ENGINES) if engines is None else engines
    lineages: list[str] = []
    seen: set[str] = set()

    for engine in selected:
        if engine == "abbyy":
            candidates = ABBYY_LINEAGES
        else:
            candidates = [LIVE_ENGINE_LINEAGES[engine]]
        for lineage in candidates:
            if lineage not in seen:
                seen.add(lineage)
                lineages.append(lineage)
    return lineages


def _run_doctor_preflight(
    volumes: list[int],
    engines: list[str] | None,
    *,
    s1_root: Path,
) -> int:
    lineages = _doctor_lineages_for_engines(engines)
    print(
        f"Doctor first: checking {len(lineages)} S1 lineage(s) before OCR",
        flush=True,
    )
    return ocr_doctor.run_doctor(volumes, lineages, output_root=s1_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--volumes", type=int, nargs="+", default=DEFAULT_VOLUMES,
        metavar="N", help="Volume numbers to process (default: 1-13)",
    )
    parser.add_argument(
        "--pages", nargs="+", default=[], metavar="N_OR_RANGE",
        help=(
            "Optional page subset for live OCR engines (Tesseract, Surya, Kraken). "
            "Accepts integers and inclusive ranges: --pages 1-10 or --pages 1 2 3. "
            "ABBYY ingestion is filtered to the same subset. "
            "Omit to process whole volume."
        ),
    )
    parser.add_argument("--s1-root", type=Path, default=DEFAULT_S1_ROOT)
    parser.add_argument("--s2-root", type=Path, default=DEFAULT_S2_ROOT)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument(
        "--throttle",
        choices=THROTTLE_CHOICES,
        default="full-speed",
        help=(
            "CPU throttle: 'full-speed' (no limit), 'background-8' (8 threads, "
            "below-normal priority -- the correct mode for CPU engines overnight), "
            "'minimal-4' (4 threads, idle priority -- GPU-Surya only; collapses CPU "
            "engines to 3+ min/page)."
        ),
    )

    parser.add_argument(
        "--surya-max-width",
        type=int,
        default=None,
        dest="surya_max_width",
        metavar="PX",
        help=(
            "Downscale images wider than PX before Surya inference; bboxes are scaled "
            "back to native coordinates. 2500 gives a ~2x speedup on 5034px-wide NSH "
            "scans with no measurable quality loss. Omit to use full resolution "
            "(default, backward-compatible)."
        ),
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        default=False,
        help=(
            "Return exit code 0 even when volumes have engine failures. "
            "Use for smoke tests only. Production runs should fail-closed."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help=(
            "Validate inputs and print a preflight report without processing any pages. "
            "Checks input root, output root writeability, and ABBYY sidecar presence."
        ),
    )
    parser.add_argument(
        "--allow-stale-manifest",
        action="store_true",
        default=False,
        help="Allow S2 rendering when sidecars on disk outnumber manifest pages.",
    )
    parser.add_argument(
        "--doctor-first",
        action="store_true",
        default=False,
        help=(
            "Run ocr_doctor on the selected volumes/engines before OCR and abort "
            "if sidecar manifests are stale."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help=(
            "Safe restart mode: clear stale stop markers and run --doctor-first "
            "before continuing with the selected volumes/engines."
        ),
    )
    _engine_choices = list(ALL_ENGINES) + ["geometry"]
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=_engine_choices,
        default=None,
        metavar="ENGINE",
        help=(
            "S1 engines to run: " + " ".join(ALL_ENGINES) + ". "
            "Use 'geometry' as a preset to run only the WCT geometry lanes "
            "(surya + tesseract + abbyy), skipping the Kraken lanes. "
            "Explicit names and 'geometry' can be combined. "
            "Omit to run all engines (default, backward-compatible)."
        ),
    )
    args = parser.parse_args(argv)

    volumes = sorted(set(args.volumes))
    invalid_vols = [v for v in volumes if not (1 <= v <= 13)]
    if invalid_vols:
        print(f"ERROR: --volumes out of range (1-13): {invalid_vols}", flush=True)
        return 2
    try:
        pages = _parse_pages_arg(args.pages)
    except ValueError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 2
    engines = _resolve_engines(args.engines)

    preflight_warnings = _preflight(args, volumes, engines)
    if preflight_warnings:
        for w in preflight_warnings:
            print(f"PREFLIGHT WARNING: {w}", flush=True)

    if args.dry_run:
        print("Dry run complete. No pages processed.", flush=True)
        return 0 if not preflight_warnings else 2

    # Clean up any leftover sentinel before the GUI can request a new stop.
    _STOP_SENTINEL.unlink(missing_ok=True)  # standards: log/temp rotation -- stop sentinel is a one-shot signal file
    _setup_shutdown_handlers()
    _start_stop_sentinel_watcher()

    # Tee all output to a timestamped log file so progress survives terminal close.
    # Logs live under _logs/ocr-pipeline/ (not the reports/ top level) so run
    # artifacts don't accumulate next to the data stores (2026-07-04 cleanup).
    _ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M")
    _log_dir = DEFAULT_S1_ROOT.parent / "_logs" / "ocr-pipeline"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_path = _log_dir / f"ocr-pipeline-{_ts}.log"
    sys.stdout = _Tee(_log_path)
    atexit.register(sys.stdout.close)
    print(f"Log: {_log_path}", flush=True)

    # Prevent Windows idle sleep for the duration of the run.
    # SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) tells the OS
    # the system is in use; cleared automatically via atexit on any exit path.
    if sys.platform == "win32":
        import ctypes
        _ES_CONTINUOUS = 0x80000000
        _ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)  # type: ignore[attr-defined]
        atexit.register(ctypes.windll.kernel32.SetThreadExecutionState, _ES_CONTINUOUS)  # type: ignore[attr-defined]
        print("Standby prevention: active", flush=True)

    print(f"OCR pipeline: {len(volumes)} volume(s) -- {volumes}", flush=True)
    if pages is not None:
        print(f"  page subset: {pages}", flush=True)
    selected_engines = engines if engines is not None else list(ALL_ENGINES)
    print(f"  engines: {selected_engines}", flush=True)
    # R6a: record the resolved CLI args so the run log shows exactly what ran.
    print(f"  resolved args: {vars(args)}", flush=True)

    if args.surya_max_width is not None:
        print(f"  Surya max_width: {args.surya_max_width}px", flush=True)
    if args.resume:
        print("  resume mode: doctor-first enabled", flush=True)

    if args.doctor_first or args.resume:
        doctor_status = _run_doctor_preflight(volumes, engines, s1_root=args.s1_root)
        if doctor_status != 0:
            print(
                "ERROR: doctor-first found stale or invalid S1 sidecar state. "
                "Run reindex_manifest.py for the reported volume/engine first.",
                flush=True,
            )
            return 2

    run_start = time.monotonic()
    summaries = []
    for i, vol_num in enumerate(volumes, start=1):
        if _check_shutdown():
            print(f"Shutdown requested -- stopping before vol_{vol_num:02d}", flush=True)
            break
        print(
            f"[{i}/{len(volumes)}] vol_{vol_num:02d} -- {_volume_leaf_range(args.input_root, vol_num)}",
            flush=True,
        )
        summary = process_volume(
            vol_num,
            s1_root=args.s1_root,
            s2_root=args.s2_root,
            input_root=args.input_root,
            throttle_mode=args.throttle,
            pages=pages,
            surya_max_width=args.surya_max_width,
            engines=engines,
            shutdown_event=_shutdown_event,
            allow_stale_manifest=args.allow_stale_manifest,
        )
        summaries.append(summary)
        if _check_shutdown():
            print(f"Shutdown requested -- stopping after vol_{vol_num:02d}", flush=True)
            break

    elapsed = time.monotonic() - run_start
    total_s1 = sum(s["s1_count"] for s in summaries)
    total_s2 = sum(s["s2_count"] for s in summaries)
    error_vols = [
        s["volume"] for s in summaries
        if s["s1_failures"] or s["s2_failures"]
    ]
    has_failures = bool(error_vols)

    # Per-engine wall-clock totals across all processed volumes.
    engine_totals: dict[str, float] = {}
    for s in summaries:
        for eng, t in s.get("engine_times", {}).items():
            engine_totals[eng] = engine_totals.get(eng, 0.0) + t

    print(f"\nOCR pipeline complete: {len(summaries)} vol(s) in {elapsed:.1f}s", flush=True)
    if engine_totals:
        live_parts = [
            f"{eng}={engine_totals[eng]:.1f}s"
            for eng in LIVE_OCR_ENGINES
            if eng in engine_totals
        ]
        imported_parts = [
            f"{eng}={engine_totals[eng]:.1f}s"
            for eng in IMPORTED_OCR_ENGINES
            if eng in engine_totals
        ]
        if live_parts:
            print(f"  engine totals (live OCR):     {' '.join(live_parts)}", flush=True)
        if imported_parts:
            print(f"  engine totals (imported OCR): {' '.join(imported_parts)}", flush=True)
    print("  Engine manifest accounting:", flush=True)
    for eng in selected_engines:
        produced = sum(
            1 for s in summaries
            if not any(k == eng or k.startswith(f"{eng}/") for k in s["s1_failures"])
        )
        total_vols = len(summaries)
        status = "OK" if produced == total_vols else f"PARTIAL ({produced}/{total_vols})"
        print(f"    {eng}: {status}", flush=True)
    print(f"  S1 manifests: {total_s1}", flush=True)
    print(f"  S2 renderings: {total_s2}", flush=True)
    if error_vols:
        print(f"  Volumes with partial failures: {error_vols}", flush=True)
    if has_failures:
        _failure_report = {
            "pipeline_run": _ts,
            "volumes_processed": len(summaries),
            "has_failures": has_failures,
            "volume_failures": [
                {
                    "volume": s["volume"],
                    "s1_failures": s["s1_failures"],
                    "s2_failures": s["s2_failures"],
                }
                for s in summaries
                if s["s1_failures"] or s["s2_failures"]
            ],
        }
        _failure_path = _log_dir / f"ocr-pipeline-{_ts}.failures.json"
        _failure_tmp = _failure_path.with_name(_failure_path.name + f".tmp-{os.getpid()}")
        try:
            _failure_tmp.write_text(
                json.dumps(_failure_report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(_failure_tmp, _failure_path)
            print(f"  Failure report: {_failure_path}", flush=True)
        except Exception as exc:
            print(f"  Warning: could not write failure report -- {exc}", flush=True)
            try:
                _failure_tmp.unlink(missing_ok=True)  # standards: log/temp rotation
            except OSError:
                pass
    if has_failures and not args.allow_partial:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
