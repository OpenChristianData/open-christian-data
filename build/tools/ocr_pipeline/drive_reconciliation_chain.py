"""Drive selected Schaff-Herzog pages through S1 -> WCT -> S3 reconciliation.

This productionises the thin-slice runner from reports/_thinslice for repeatable
page-list runs. By default it uses the geometry-bearing engine set proven by the
page_0010 slice: Surya layout, Tesseract word geometry, and ABBYY word geometry.
Additional rendering lineages can be supplied explicitly once their WCT behaviour
is intended.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.atomic_io import write_json_atomic  # noqa: E402
from build.lib.ocr_store_paths import (  # noqa: E402
    RECONCILED_ROOT,
    S2_RENDERINGS_ROOT,
    WCT_ROOT,
)
from build.lib.ocr_throttle import (  # noqa: E402
    THROTTLE_CHOICES,
    priority_for_throttle,
    workers_for_throttle as _workers_for_throttle,
)
from build.lib.wct_builder import LayoutEscalation  # noqa: E402
from build.tools.ocr_pipeline.build_wct import SCHEMA_PATH as WCT_SCHEMA_PATH  # noqa: E402
from build.tools.ocr_pipeline.build_wct import build_from_files  # noqa: E402
from build.tools.ocr_pipeline.align_ccel_to_wct import align_page as _align_page_inline  # noqa: E402
from build.tools.ocr_pipeline.reconcile_s3 import (  # noqa: E402
    MATRIX_EVENTS_SCHEMA_PATH,
    SCHEMA_PATH as RECONCILED_SCHEMA_PATH,
    reconcile_page_inline,
)

DEFAULT_ENGINES = (
    "tesseract-py314-v1",
    "ia-abbyy-v1",
    "azure-ai-vision-v1",
    "kraken-py312-v1",
)
DEFAULT_INPUT_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
DEFAULT_S2_ROOT = S2_RENDERINGS_ROOT
DEFAULT_WCT_ROOT = WCT_ROOT
DEFAULT_RECONCILED_ROOT = RECONCILED_ROOT
DEFAULT_SINGLE_ROOT = REPO_ROOT / ".tmp" / "ocr-chain-single-renderings"
DEFAULT_WORK_META = REPO_ROOT / "reports" / "reconciled" / "vol_01" / "work_meta.json"

# CPU-throttle worker counts + priority are centralized in build/lib/ocr_throttle.py
# (workers_for_throttle / priority_for_throttle, imported above).

# Worker-process-local schema cache. Populated once by _init_worker; read by _drive_one_page.
# Each spawned worker (Windows spawn method) has its own copy of this module, so the
# populated dict is private to that worker -- no inter-process sharing needed.
_WORKER_SCHEMAS: dict[str, dict] = {}


def _init_worker(throttle_mode: str) -> None:
    """Initialise a worker process: set Windows priority and pre-load schemas.

    Called once per worker via ProcessPoolExecutor initializer= (before any page
    task runs). Schemas are loaded here so _drive_one_page avoids reading the
    same two files from disk on every page.
    """
    global _WORKER_SCHEMAS
    # Priority -- best-effort; non-fatal on non-Windows or permission denial.
    priority = priority_for_throttle(throttle_mode)
    if priority is not None:
        try:
            handle = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
            ctypes.windll.kernel32.SetPriorityClass(handle, priority)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            print(
                f"WARNING: could not set process priority ({exc})",
                file=sys.stderr, flush=True,
            )
    # Pre-load schemas once per worker to avoid per-page disk reads in _drive_one_page.
    _WORKER_SCHEMAS = {
        "reconciled": json.loads(RECONCILED_SCHEMA_PATH.read_text(encoding="utf-8")),
        "matrix": json.loads(MATRIX_EVENTS_SCHEMA_PATH.read_text(encoding="utf-8")),
        "wct": json.loads(WCT_SCHEMA_PATH.read_text(encoding="utf-8")),
    }


@dataclass
class _PageArgs:
    """Per-page arguments bundle for _drive_one_page; must be picklable."""

    repo_root: Path
    volume: int
    page: int
    engines: tuple
    s2_root: Path
    single_root: Path
    wct_root: Path
    reconciled_root: Path
    work_meta_dict: dict
    align_ccel: bool
    ccel_proposal: Path | None
    ccel_output_root: Path
    source_image: dict | None
    ccel_proposal_dict: dict | None


def _drive_one_page(args: _PageArgs) -> dict:
    """Worker function: build WCT + reconcile one page. Returns summary dict.

    LayoutEscalation is returned as {"escalated": True, ...} so the pool
    coordinator can collect escalated pages without crashing the executor.
    All other exceptions propagate so the pool coordinator can log them as
    per-page errors and continue (REL-08).
    """
    # Generate a per-page timestamp. ZoneInfo("Australia/Melbourne") may be absent
    # in some sandbox environments; UTC is always safe in a spawned worker process.
    occurred_at = datetime.now(timezone.utc).isoformat()

    page = args.page
    target = page_native_id(page)
    vol_label = volume_label(args.volume)

    renderings = _single_rendering_paths(
        volume=args.volume,
        page=page,
        engines=args.engines,
        s2_root=args.s2_root,
        single_root=args.single_root,
    )
    wct_path = args.wct_root / vol_label / f"{target}.json"

    try:
        wct = build_wct_for_page(
            repo_root=args.repo_root,
            volume=args.volume,
            page=page,
            renderings=renderings,
            output=wct_path,
            _schema=_WORKER_SCHEMAS.get("wct"),
            source_image=args.source_image,
        )
    except LayoutEscalation as exc:
        print(
            f"WARNING: layout escalation for {target} flags={exc.flags} -- page skipped",
            file=sys.stderr, flush=True,
        )
        return {"escalated": True, "page": page, "page_id": target, "flags": exc.flags}

    reconciled_path = args.reconciled_root / vol_label / f"{target}.json"
    reconcile_page_inline(
        wct_page=wct,
        work_meta=args.work_meta_dict,
        output_path=reconciled_path,
        occurred_at=occurred_at,
        # Pass worker-cached schemas to avoid per-page disk reads.
        _schema=_WORKER_SCHEMAS.get("reconciled"),
        _matrix_schema=_WORKER_SCHEMAS.get("matrix"),
    )

    ccel_alignment_path = None
    if args.align_ccel and args.ccel_proposal_dict is not None:
        ccel_alignment_path = (
            args.ccel_output_root / vol_label / f"ccel_wct_alignment_{target}.json"
        )
        artifact = _align_page_inline(
            wct,
            args.ccel_proposal_dict,
            wct_path=wct_path.as_posix(),
            proposal_path=args.ccel_proposal.as_posix() if args.ccel_proposal else None,
        )
        ccel_alignment_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = ccel_alignment_path.with_suffix(ccel_alignment_path.suffix + ".tmp")
        tmp.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(ccel_alignment_path)

    return {
        "escalated": False,
        "page": page,
        "page_id": target,
        "wct": wct_path.as_posix(),
        "reconciled": reconciled_path.as_posix(),
        "matrix_candidates": (reconciled_path.parent / f"{target}.matrix_candidates.json").as_posix(),
        "reviewer_queue": (reconciled_path.parent / f"{target}.reviewer_queue.json").as_posix(),
        "ccel_alignment": ccel_alignment_path.as_posix() if ccel_alignment_path else None,
        "positions": len(wct["positions"]),
        "engines": [engine["engine_id"] for engine in wct["available_engines"]],
    }


def parse_pages(values: Sequence[str]) -> list[int]:
    """Parse CLI page tokens into a sorted, de-duplicated page list."""
    pages: set[int] = set()
    for token in values:
        if "-" in token:
            lo, hi = token.split("-", 1)
            pages.update(range(int(lo), int(hi) + 1))
        else:
            pages.add(int(token))
    if not pages:
        raise ValueError("at least one page is required")
    return sorted(pages)


def volume_label(volume: int) -> str:
    return f"vol_{volume:02d}"


def page_native_id(page: int) -> str:
    return f"page_{page:04d}"


def source_image_metadata(repo_root: Path, volume: int, page: int) -> dict[str, str]:
    rel = Path("raw") / "internet-archive" / "schaff-herzog-pages" / volume_label(volume) / f"{page_native_id(page)}.jpg"
    image_path = repo_root / rel
    if not image_path.exists():
        raise FileNotFoundError(f"source image not found: {image_path}")
    return {
        "path": rel.as_posix(),
        "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
    }


def _single_rendering_paths(
    *,
    volume: int,
    page: int,
    engines: Sequence[str],
    s2_root: Path,
    single_root: Path,
) -> list[Path]:
    target = page_native_id(page)
    paths: list[Path] = []
    for engine in engines:
        page_file = s2_root / volume_label(volume) / engine / "pages" / f"{target}.rendering-v1.json"
        if not page_file.exists():
            print(
                f"WARNING: S2 rendering missing for engine={engine} "
                f"page={target} -- engine skipped",
                file=sys.stderr, flush=True,
            )
            continue
        paths.append(page_file)
    if len(paths) < 2:
        raise FileNotFoundError(
            f"fewer than 2 engines have S2 renderings for page {target}: "
            f"got {len(paths)} "
            f"({[p.parent.parent.name for p in paths]})"
        )
    return paths


def find_escalated_pages(
    reconciled_root: Path,
    vol_label: str,
    pages: Sequence[int],
) -> list[int]:
    """Return pages whose reviewer queue is non-empty.

    Reads page_NNNN.reviewer_queue.json for each page. A non-empty
    queue array signals positions that could not be auto-resolved and
    need escalation (e.g. a second pass with surya).
    """
    escalated = []
    for page in pages:
        target = page_native_id(page)
        queue_path = reconciled_root / vol_label / f"{target}.reviewer_queue.json"
        if not queue_path.exists():
            continue
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        if data.get("queue"):
            escalated.append(page)
    return escalated


def run_fanout(
    *,
    volume: int,
    pages: Sequence[int],
    throttle: str,
    surya_max_width: int | None,
    force_s1: bool,
    s1_engines: Sequence[str] | None = None,
) -> None:
    command = [
        sys.executable,
        str(REPO_ROOT / "build" / "tools" / "ocr_pipeline" / "run_ocr_pipeline.py"),
        "--volumes",
        str(volume),
        "--pages",
        *[str(page) for page in pages],
        "--throttle",
        throttle,
    ]
    if force_s1:
        command.append("--force-s1")
    if surya_max_width is not None:
        command.extend(["--surya-max-width", str(surya_max_width)])
    if s1_engines:
        command.extend(["--engines", *s1_engines])
    subprocess.run(command, check=True)


def build_wct_for_page(
    *,
    repo_root: Path,
    volume: int,
    page: int,
    renderings: Sequence[Path],
    output: Path,
    _schema: dict | None = None,
    source_image: dict | None = None,
) -> dict:
    image_meta = source_image if source_image is not None else source_image_metadata(repo_root, volume, page)
    wct_page = build_from_files(
        list(renderings),
        source_image=image_meta,
        volume_id=volume_label(volume),
        page_id=page_native_id(page),
    )
    schema = _schema if _schema is not None else json.loads(WCT_SCHEMA_PATH.read_text(encoding="utf-8"))
    write_json_atomic(output, wct_page, schema)
    return wct_page


def reconcile_page(*, wct_path: Path, work_meta: Path, output: Path, occurred_at: str | None) -> None:
    command = [
        sys.executable,
        str(REPO_ROOT / "build" / "tools" / "ocr_pipeline" / "reconcile_s3.py"),
        "--wct",
        str(wct_path),
        "--work-meta",
        str(work_meta),
        "--output",
        str(output),
    ]
    if occurred_at:
        command.extend(["--occurred-at", occurred_at])
    subprocess.run(command, check=True)


def align_ccel_page(
    *,
    volume: int,
    page: int,
    wct_path: Path,
    proposal: Path | None,
    output: Path,
) -> None:
    command = [
        sys.executable,
        str(REPO_ROOT / "build" / "tools" / "ocr_pipeline" / "align_ccel_to_wct.py"),
        "--volume",
        str(volume),
        "--page",
        str(page),
        "--wct",
        str(wct_path),
        "--output",
        str(output),
        "--write",
    ]
    if proposal is not None:
        command.extend(["--proposal", str(proposal)])
    subprocess.run(command, check=True)


def drive_pages(
    *,
    volume: int,
    pages: Sequence[int],
    engines: Sequence[str] = DEFAULT_ENGINES,
    run_s1_s2: bool = False,
    throttle: str = "8",
    surya_max_width: int | None = 2500,
    force_s1: bool = False,
    s1_engines: Sequence[str] | None = None,
    s2_root: Path = DEFAULT_S2_ROOT,
    single_root: Path = DEFAULT_SINGLE_ROOT,
    wct_root: Path = DEFAULT_WCT_ROOT,
    reconciled_root: Path = DEFAULT_RECONCILED_ROOT,
    work_meta: Path = DEFAULT_WORK_META,
    align_ccel: bool = False,
    ccel_proposal: Path | None = None,
    ccel_output_root: Path = REPO_ROOT / "reports" / "gold",
    occurred_at: str | None = None,
    skip_existing: bool = True,
    max_workers: int | None = None,
) -> list[dict]:
    """Drive selected pages through WCT -> S3 reconcile -> (optional) CCEL align.

    skip_existing: skip pages whose reconciled output already exists on disk
    (default True -- avoids re-running expensive WCT/reconcile for done pages).
    Pass skip_existing=False (or --force on the CLI) to reprocess everything.
    """
    pages = sorted(set(pages))
    vol_label = volume_label(volume)
    effective_workers = max_workers if max_workers is not None else _workers_for_throttle(throttle)
    if occurred_at is None:
        occurred_at = datetime.now(timezone.utc).isoformat()

    if run_s1_s2:
        # When skip_existing, only feed pages that still need reconciliation into S1/S2.
        # The S1 runners have their own per-page skip logic, but filtering here avoids
        # paying for S2 rendering and coverage for pages whose downstream output exists.
        s1_pages = (
            [
                p for p in pages
                if not (reconciled_root / vol_label / f"{page_native_id(p)}.json").exists()
            ]
            if skip_existing else pages
        )
        if s1_pages:
            run_fanout(
                volume=volume,
                pages=s1_pages,
                throttle=throttle,
                surya_max_width=surya_max_width,
                force_s1=force_s1,
                s1_engines=s1_engines,
            )

    summary: list[dict] = []
    layout_escalated: list[dict] = []
    skipped = 0
    page_errors = 0

    pending = []
    for page in pages:
        target = page_native_id(page)
        reconciled_path = reconciled_root / vol_label / f"{target}.json"
        if skip_existing and reconciled_path.exists():
            skipped += 1
        else:
            pending.append(page)

    # Load work_meta once -- needed by both the sequential and parallel paths.
    # Skip the read when there are no pending pages (nothing to process).
    work_meta_dict = json.loads(work_meta.read_text(encoding="utf-8")) if pending else {}

    # Pre-load CCEL proposal once (avoids one subprocess spawn + file read per aligned page).
    _effective_ccel_proposal_path = ccel_proposal
    if align_ccel and _effective_ccel_proposal_path is None:
        _effective_ccel_proposal_path = (
            REPO_ROOT / "reports" / "gold" / vol_label / "ccel_page_gold_proposal.json"
        )
    ccel_proposal_dict: dict | None = None
    if align_ccel and _effective_ccel_proposal_path is not None:
        if _effective_ccel_proposal_path.exists():
            ccel_proposal_dict = json.loads(
                _effective_ccel_proposal_path.read_text(encoding="utf-8")
            )
        else:
            print(
                f"WARNING: CCEL proposal not found: {_effective_ccel_proposal_path} "
                "-- CCEL alignment skipped for all pages",
                file=sys.stderr, flush=True,
            )

    # Route tiny batches to the sequential path to avoid process-pool startup
    # overhead dominating a 1-2 page run on Windows.
    if effective_workers == 1 or len(pending) <= 1:
        # Pre-compute source image metadata (SHA-256 + path) once for the sequential path.
        # Parallel workers compute their own hashes to keep hashing distributed across cores.
        page_source_images: dict[int, dict] = {}
        for _pg in list(pending):
            try:
                page_source_images[_pg] = source_image_metadata(REPO_ROOT, volume, _pg)
            except FileNotFoundError as _exc:
                print(
                    f"ERROR: page {page_native_id(_pg)} source image not found: {_exc}",
                    file=sys.stderr, flush=True,
                )
                page_errors += 1
        pending = [p for p in pending if p in page_source_images]
        # Load schemas once for the sequential path (avoids per-page disk reads).
        _seq_wct_schema = json.loads(WCT_SCHEMA_PATH.read_text(encoding="utf-8")) if pending else None
        _seq_reconciled_schema = json.loads(RECONCILED_SCHEMA_PATH.read_text(encoding="utf-8")) if pending else None
        _seq_matrix_schema = json.loads(MATRIX_EVENTS_SCHEMA_PATH.read_text(encoding="utf-8")) if pending else None
        for page in pending:
            target = page_native_id(page)
            reconciled_path = reconciled_root / vol_label / f"{target}.json"
            try:
                renderings = _single_rendering_paths(
                    volume=volume,
                    page=page,
                    engines=engines,
                    s2_root=s2_root,
                    single_root=single_root,
                )
                wct_path = wct_root / vol_label / f"{target}.json"
                try:
                    wct = build_wct_for_page(
                        repo_root=REPO_ROOT,
                        volume=volume,
                        page=page,
                        renderings=renderings,
                        output=wct_path,
                        _schema=_seq_wct_schema,
                        source_image=page_source_images[page],
                    )
                except LayoutEscalation as exc:
                    print(
                        f"WARNING: layout escalation for {target} flags={exc.flags} -- page skipped",
                        file=sys.stderr, flush=True,
                    )
                    layout_escalated.append({"page": page, "page_id": target, "flags": exc.flags})
                    continue
                reconcile_page_inline(
                    wct_page=wct,
                    work_meta=work_meta_dict,
                    output_path=reconciled_path,
                    occurred_at=occurred_at,
                    _schema=_seq_reconciled_schema,
                    _matrix_schema=_seq_matrix_schema,
                )
                ccel_alignment_path = None
                if align_ccel and ccel_proposal_dict is not None:
                    ccel_alignment_path = (
                        ccel_output_root / vol_label / f"ccel_wct_alignment_{target}.json"
                    )
                    artifact = _align_page_inline(
                        wct,
                        ccel_proposal_dict,
                        wct_path=wct_path.as_posix(),
                        proposal_path=_effective_ccel_proposal_path.as_posix() if _effective_ccel_proposal_path else None,
                    )
                    ccel_alignment_path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = ccel_alignment_path.with_suffix(ccel_alignment_path.suffix + ".tmp")
                    tmp.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                    tmp.replace(ccel_alignment_path)
                summary.append(
                    {
                        "page": page,
                        "page_id": target,
                        "wct": wct_path.as_posix(),
                        "reconciled": reconciled_path.as_posix(),
                        "matrix_candidates": (reconciled_path.parent / f"{target}.matrix_candidates.json").as_posix(),
                        "reviewer_queue": (reconciled_path.parent / f"{target}.reviewer_queue.json").as_posix(),
                        "ccel_alignment": ccel_alignment_path.as_posix() if ccel_alignment_path else None,
                        "positions": len(wct["positions"]),
                        "engines": [engine["engine_id"] for engine in wct["available_engines"]],
                    }
                )
                print(
                    f"{target}: positions={len(wct['positions'])} "
                    f"engines={','.join(item['engine_id'] for item in wct['available_engines'])}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 -- per-page error; log and continue (REL-08)
                print(
                    f"ERROR: page {target} failed: {type(exc).__name__}: {exc}",
                    file=sys.stderr, flush=True,
                )
                page_errors += 1
    else:
        # Pre-create output directories once to avoid per-page mkdir syscalls in workers.
        (wct_root / vol_label).mkdir(parents=True, exist_ok=True)
        (reconciled_root / vol_label).mkdir(parents=True, exist_ok=True)
        if align_ccel:
            (ccel_output_root / vol_label).mkdir(parents=True, exist_ok=True)
        page_args_list = [
            _PageArgs(
                repo_root=REPO_ROOT,
                volume=volume,
                page=page,
                engines=tuple(engines),
                s2_root=s2_root,
                single_root=single_root,
                wct_root=wct_root,
                reconciled_root=reconciled_root,
                work_meta_dict=work_meta_dict,
                align_ccel=align_ccel,
                ccel_proposal=_effective_ccel_proposal_path,
                ccel_output_root=ccel_output_root,
                source_image=None,
                ccel_proposal_dict=ccel_proposal_dict,
            )
            for page in pending
        ]
        with ProcessPoolExecutor(
            max_workers=effective_workers,
            initializer=_init_worker,
            initargs=(throttle,),
        ) as executor:
            future_to_page = {
                executor.submit(_drive_one_page, args): args.page
                for args in page_args_list
            }
            try:
                for future in as_completed(future_to_page):
                    page_num = future_to_page[future]
                    try:
                        result = future.result()
                    except BrokenProcessPool:
                        # OS killed a worker; remaining futures are undeliverable.
                        print(
                            "ERROR: a worker process was killed unexpectedly -- "
                            f"partial summary ({len(summary)} pages collected so far)",
                            file=sys.stderr, flush=True,
                        )
                        break
                    except Exception as exc:  # noqa: BLE001 -- per-page error; log and continue (REL-08)
                        print(
                            f"ERROR: page {page_num} failed: {type(exc).__name__}: {exc}",
                            file=sys.stderr, flush=True,
                        )
                        page_errors += 1
                        continue
                    if result["escalated"]:
                        layout_escalated.append(
                            {
                                "page": result["page"],
                                "page_id": result["page_id"],
                                "flags": result["flags"],
                            }
                        )
                    else:
                        summary.append({k: v for k, v in result.items() if k != "escalated"})
            except KeyboardInterrupt:
                # cancel_futures=True drops queued work that hasn't started yet;
                # already-running workers finish their current page before exiting.
                print(
                    "\nInterrupted -- cancelling pending pages...",
                    file=sys.stderr, flush=True,
                )
                executor.shutdown(cancel_futures=True, wait=False)
                raise
        summary.sort(key=lambda r: r["page"])
    if skipped:
        print(f"skipped {skipped} already-done pages", flush=True)
    if page_errors:
        print(
            f"WARNING: {page_errors} page(s) failed during processing",
            file=sys.stderr, flush=True,
        )
    if layout_escalated:
        print(
            f"WARNING: {len(layout_escalated)} pages skipped due to layout escalation: "
            + ", ".join(e["page_id"] for e in layout_escalated),
            file=sys.stderr, flush=True,
        )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume", type=int, default=1)
    parser.add_argument("--pages", nargs="+", required=True, metavar="N_OR_RANGE")
    parser.add_argument("--engine", action="append", dest="engines", default=[])
    parser.add_argument("--run-s1-s2", action="store_true")
    parser.add_argument("--force-s1", action="store_true")
    # S1 engine names (source of truth: run_ocr_pipeline.ALL_ENGINES).
    # Distinct from --engine above, which selects WCT rendering lineages.
    parser.add_argument(
        "--s1-engines",
        nargs="+",
        choices=("tesseract", "surya", "abbyy", "kraken", "kraken-greek", "geometry"),
        default=None,
        metavar="ENGINE",
        help=(
            "S1 engines to run when --run-s1-s2 (default: all). Use 'geometry' as "
            "a preset for surya + tesseract + abbyy (the WCT geometry lanes), "
            "skipping the Kraken lanes the WCT does not consume."
        ),
    )
    parser.add_argument("--throttle", choices=THROTTLE_CHOICES, default="background-8",
                        help="background-8=8 workers below-normal priority (at desk); minimal-4=4 workers idle priority (unattended); full-speed=cpu_count normal priority.")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Override the number of parallel page-processing workers. "
            "Default: derived from --throttle (minimal-4=4 workers, background-8=8 workers, full-speed=cpu_count). "
            "Pass 1 to run sequentially (useful for debugging)."
        ),
    )
    parser.add_argument("--surya-max-width", type=int, default=2500)
    parser.add_argument(
        "--work-meta",
        type=Path,
        default=None,
        help=(
            "Path to the work metadata JSON for this volume. "
            "Defaults to reports/reconciled/vol_NN/work_meta.json derived from --volume."
        ),
    )
    parser.add_argument("--align-ccel", action="store_true")
    parser.add_argument("--ccel-proposal", type=Path, default=None)
    parser.add_argument("--occurred-at", default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-process pages even when their reconciled output already exists. "
            "By default, pages with existing reconciled output are skipped to avoid "
            "redundant WCT/reconcile work."
        ),
    )
    parser.add_argument(
        "--two-pass",
        action="store_true",
        help=(
            "After the first drive, identify escalated pages (non-empty reviewer "
            "queue), run surya S1/S2 on those pages, then re-drive them with "
            "surya added to the engine list. Gracefully skips if no surya "
            "renderings are available for the escalated set."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pages = parse_pages(args.pages)
    engines = tuple(args.engines) if args.engines else DEFAULT_ENGINES
    vol = args.volume
    vol_lab = volume_label(vol)
    work_meta = args.work_meta or DEFAULT_RECONCILED_ROOT / vol_lab / "work_meta.json"

    summary = drive_pages(
        volume=vol,
        pages=pages,
        engines=engines,
        run_s1_s2=args.run_s1_s2,
        throttle=args.throttle,
        surya_max_width=args.surya_max_width,
        force_s1=args.force_s1,
        s1_engines=args.s1_engines,
        work_meta=work_meta,
        align_ccel=args.align_ccel,
        ccel_proposal=args.ccel_proposal,
        occurred_at=args.occurred_at,
        skip_existing=not args.force,
        max_workers=args.workers,
    )

    if args.two_pass:
        escalated = find_escalated_pages(DEFAULT_RECONCILED_ROOT, vol_lab, pages)
        if not escalated:
            print(
                "two-pass: no escalated pages -- skipping surya escalation",
                file=sys.stderr,
            )
        else:
            print(
                f"two-pass: {len(escalated)} escalated pages -- running surya S1/S2",
                file=sys.stderr,
            )
            run_fanout(
                volume=vol,
                pages=escalated,
                throttle=args.throttle,
                surya_max_width=args.surya_max_width,
                force_s1=False,
                s1_engines=["surya-py312-v1"],
            )
            surya_pages_root = (
                DEFAULT_S2_ROOT / vol_lab / "surya-py312-v1" / "pages"
            )
            available = [
                p for p in escalated
                if (
                    surya_pages_root
                    / f"{page_native_id(p)}.rendering-v1.json"
                ).exists()
            ]
            if not available:
                print(
                    "two-pass: no surya S2 renderings available for escalated "
                    "pages -- skipping second pass",
                    file=sys.stderr,
                )
            else:
                print(
                    f"two-pass: {len(available)}/{len(escalated)} escalated pages "
                    f"have surya -- re-driving",
                    file=sys.stderr,
                )
                surya_engines = list(engines) + ["surya-py312-v1"]
                second_summary = drive_pages(
                    volume=vol,
                    pages=available,
                    engines=tuple(surya_engines),
                    run_s1_s2=False,
                    throttle=args.throttle,
                    surya_max_width=args.surya_max_width,
                    force_s1=False,
                    work_meta=work_meta,
                    align_ccel=args.align_ccel,
                    ccel_proposal=args.ccel_proposal,
                    occurred_at=args.occurred_at,
                    skip_existing=False,
                    max_workers=args.workers,
                )
                summary.extend(second_summary)

    print(json.dumps({"pages": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
