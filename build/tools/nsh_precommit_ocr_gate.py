"""Fast pre-commit OCR tripwire for NSH page-image content position.

The structural verifier (verify_nsh_page_accounting.py) is pixel-blind: it passes
on a disk whose files are mis-named, because it only counts filenames against the
manifest (PIPE-29). This gate reads PIXELS -- it OCRs the running header of a small
SAMPLE of pages per volume and fails the commit if a sustained constant offset
(the rename signature) appears. It is the cheap tripwire; verify_nsh_running_headers.py
is the thorough audit.

Scope + speed: only volumes whose manifest or page_order is in the staged change
set are sampled (a few pages each), so the gate stays well under a second and does
not tempt --no-verify. It SKIPS gracefully (exit 0) when it cannot read pixels:
no tesseract (clean CI), no jpg on disk, or too few readable samples to judge --
absence of evidence is not a failure here; the full audit covers those.

Usage:
  py -3 build/tools/nsh_precommit_ocr_gate.py            # gate staged NSH changes
  py -3 build/tools/nsh_precommit_ocr_gate.py --volume 8 # gate one volume explicitly
  py -3 build/tools/nsh_precommit_ocr_gate.py --selftest # TP + TN self-check
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.nsh_leaf_model import body_pages  # noqa: E402

PAGES_BASE = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"

# --- Tuning (PY-03: config at the top) -------------------------------------
SAMPLE_SIZE = 8          # pages spread evenly across the body
TAIL_SAMPLE = 6          # PLUS the last N body pages, sampled densely. A rename
                         # offset always persists to the volume tail (the diagnosis
                         # signature is "persistent-to-tail"), and late-onset offsets
                         # (vol_02 from p253, vol_05/06 from p451, vol_11 from p478)
                         # would otherwise be missed by an even spread -- only 1-2 of
                         # 8 spread samples land in a short corrupted tail. The dense
                         # tail makes those visible.
MIN_OFFSET_RUN = 3       # >= this many readable samples sharing one non-zero delta
                         # = a sustained offset (rename signature). Isolated OCR
                         # misreads produce random, non-agreeing deltas and never
                         # reach this count, so the gate tolerates the noise floor.

_STAGED_RE = re.compile(
    r"^raw/internet-archive/schaff-herzog-pages/vol_(\d{2})"
    r"(?:\.manifest\.json|/page_order\.json)$"
)


def _load_verifier():
    """Import verify_nsh_running_headers by path and wire up tesseract."""
    spec = importlib.util.spec_from_file_location(
        "verify_nsh_running_headers",
        REPO_ROOT / "build" / "tools" / "verify_nsh_running_headers.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def staged_nsh_volumes() -> list[int]:
    """Volumes whose committed bookkeeping (manifest / page_order) is staged."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    vols: set[int] = set()
    for line in result.stdout.splitlines():
        m = _STAGED_RE.match(line.strip())
        if m:
            vols.add(int(m.group(1)))
    return sorted(vols)


def sample_pages(volume: int) -> list[int]:
    """Pick up to SAMPLE_SIZE present body pages spread across the volume.

    Reads the manifest's present page_nums and keeps only those with a jpg on
    disk (the gate can only OCR what is materialized locally). Always includes
    the last present page (where a sustained offset is most visible).
    """
    manifest_path = PAGES_BASE / f"vol_{volume:02d}.manifest.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    vol_dir = PAGES_BASE / f"vol_{volume:02d}"
    present = sorted(
        p["page_num"]
        for p in body_pages(manifest)
        if isinstance(p.get("page_num"), int)
        and (vol_dir / f"page_{p['page_num']:04d}.jpg").exists()
    )
    if not present:
        return []
    if len(present) <= SAMPLE_SIZE + TAIL_SAMPLE:
        return present
    # Evenly spaced across the body ...
    idx = {round(i * (len(present) - 1) / (SAMPLE_SIZE - 1)) for i in range(SAMPLE_SIZE)}
    # ... PLUS a dense tail (where a sustained offset always shows).
    idx |= set(range(len(present) - TAIL_SAMPLE, len(present)))
    return [present[i] for i in sorted(idx)]


def gate_volume(vh, volume: int) -> tuple[bool, str]:
    """Return (ok, detail) for one volume. ok=True means no sustained offset found
    (including the can't-judge cases, which are not failures here)."""
    samples = sample_pages(volume)
    if not samples:
        return True, "no page jpgs on disk -- skipped (full audit covers this)"
    records = vh.scan_volume(volume, samples, workers=min(8, len(samples)))
    readable = [r for r in records if r.get("delta") is not None]
    if len(readable) < MIN_OFFSET_RUN:
        return True, f"only {len(readable)} readable of {len(samples)} sampled -- cannot judge, skipped"
    nonzero = Counter(r["delta"] for r in readable if r["delta"] != 0)
    for delta, count in sorted(nonzero.items(), key=lambda kv: -kv[1]):
        if count >= MIN_OFFSET_RUN:
            offenders = [r["file"] for r in readable if r["delta"] == delta][:5]
            return False, (
                f"sustained offset {delta:+d} on {count}/{len(readable)} readable samples "
                f"(rename signature) -- e.g. {offenders}"
            )
    zeros = sum(1 for r in readable if r["delta"] == 0)
    return True, f"delta-0 dominant ({zeros}/{len(readable)} readable samples match)"


def run_gate(volumes: list[int]) -> int:
    vh = _load_verifier()
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = vh.resolve_tesseract()
        pytesseract.get_tesseract_version()
    except Exception as exc:  # noqa: BLE001 -- any tesseract resolution failure
        print(f"[nsh-ocr-gate] tesseract unavailable ({exc}); skipping (cannot gate pixels here)")
        return 0
    failed = False
    for vol in volumes:
        ok, detail = gate_volume(vh, vol)
        flag = "OK  " if ok else "FAIL"
        print(f"[nsh-ocr-gate] vol_{vol:02d}: {flag} -- {detail}")
        if not ok:
            failed = True
    if failed:
        print(
            "[nsh-ocr-gate] BLOCKED: a volume's page images are mis-named "
            "(content does not match filename). Run "
            "build/tools/verify_nsh_running_headers.py for the full audit."
        )
        return 1
    return 0


def _selftest() -> int:
    """One true-positive (sustained offset must FAIL) and one true-negative
    (delta-0 dominant with isolated noise must PASS)."""

    class FakeVH:
        def resolve_tesseract(self):
            return "tesseract"

        def __init__(self, records):
            self._records = records

        def scan_volume(self, volume, pages, workers=8):
            return self._records

    def judge(records):
        original_sample_pages = sample_pages
        globals()["sample_pages"] = lambda volume: list(range(1, len(records) + 1))
        vh = FakeVH(records)
        try:
            ok, _ = gate_volume(vh, 1)
            return ok
        finally:
            globals()["sample_pages"] = original_sample_pages

    # TP: every readable sample shows +4 -> sustained offset -> must FAIL (ok False)
    tp = [{"file": f"page_{p:04d}.jpg", "delta": 4} for p in (100, 200, 300, 400)]
    # TN: delta-0 dominant with two isolated, non-agreeing misreads -> must PASS
    tn = (
        [{"file": f"page_{p:04d}.jpg", "delta": 0} for p in (100, 200, 300, 400, 500)]
        + [{"file": "page_0250.jpg", "delta": 5}, {"file": "page_0350.jpg", "delta": -3}]
    )
    ok = True
    if judge(tp) is not False:
        print("SELFTEST FAIL: sustained +4 offset was not flagged")
        ok = False
    else:
        print("SELFTEST PASS: sustained offset flagged")
    if judge(tn) is not True:
        print("SELFTEST FAIL: delta-0-dominant-with-noise was wrongly flagged")
        ok = False
    else:
        print("SELFTEST PASS: noise floor tolerated")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fast pre-commit OCR tripwire for NSH page content position.")
    parser.add_argument("--volume", type=int, action="append", help="Gate this volume (repeatable). Default: staged volumes.")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    volumes = args.volume if args.volume else staged_nsh_volumes()
    if not volumes:
        return 0  # nothing NSH staged -- gate is a no-op
    return run_gate(volumes)


if __name__ == "__main__":
    raise SystemExit(main())
