"""Build a scoped declared-library index from current work sidecars."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from build.tools.report_library import render_markdown
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.views import library_browse_snapshot


def collect_entries(root: Path | None = None) -> list[dict]:
    return library_browse_snapshot(root or ROOT)["works"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True,
                        help="Explicit destination; historical index is not overwritten by default.")
    args = parser.parse_args(argv)
    try:
        report = library_browse_snapshot(args.root)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    except (PipelineError, OSError) as exc:
        parser.error(str(exc))
    print(f"Wrote {len(report['works'])} declared work identities to {args.output}")
    return int(bool(report["counts"]["failed"] or any(
        issue.get("severity") == "error" for issue in report["issues"])))


if __name__ == "__main__":
    raise SystemExit(main())
