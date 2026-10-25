"""Prepare, promote, install, and read back one reviewed acceptance declaration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocd_kernel.library._common import PipelineError, load_json, within
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    promote_accepted_master,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import install_accepted_work, read_accepted_work


_REQUIRED = {
    "acceptance_path",
    "identity",
    "candidate_path",
    "source_accounting_path",
    "scope",
    "technical",
    "review",
    "representation_revision",
    "decision",
}
_OPTIONAL = {"acceptance_id", "missing_members", "unknown_members", "scoped"}


def _request(path: Path) -> dict[str, Any]:
    request = load_json(path)
    if not isinstance(request, dict):
        raise PipelineError("admission declaration must be a JSON object")
    missing = sorted(_REQUIRED - request.keys())
    unexpected = sorted(request.keys() - _REQUIRED - _OPTIONAL)
    if missing:
        raise PipelineError(f"admission declaration is missing: {', '.join(missing)}")
    if unexpected:
        raise PipelineError(f"admission declaration has unsupported fields: {', '.join(unexpected)}")
    if not isinstance(request["identity"], dict):
        raise PipelineError("admission declaration identity must be an object")
    return request


def prepare_acceptance(root: Path, declaration_path: Path) -> tuple[Path, dict[str, Any]]:
    """Seal supplied review evidence into one fresh pending acceptance sidecar."""

    root = Path(root).resolve(strict=True)
    declaration = _request(Path(declaration_path))
    acceptance_path = within(root, declaration.pop("acceptance_path"), field="acceptance_path")
    if acceptance_path.exists():
        raise PipelineError(f"acceptance path must be fresh: {acceptance_path}")
    record = build_acceptance_record(root, **declaration)
    write_acceptance(acceptance_path, record)
    return acceptance_path, record


def admit(
    root: Path,
    declaration_path: Path,
    promotion_destination: Path,
    install_root: Path,
    *,
    fail_at: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the shared administrative route without producing source evidence."""

    root = Path(root).resolve(strict=True)
    declaration = _request(Path(declaration_path))
    identity = declaration["identity"]
    work_id = str(identity.get("work_id", "<missing-work-id>"))
    try:
        acceptance_path, record = prepare_acceptance(root, declaration_path)
        promoted = promote_accepted_master(
            root,
            acceptance_path=acceptance_path,
            destination=promotion_destination,
            candidate_path=Path(root) / record["technical"]["candidate"]["path"],
        )
        installed = install_accepted_work(
            install_root,
            promoted.destination_root,
            work_id=work_id,
            fail_at=fail_at,
        )
        live_work = read_accepted_work(install_root, work_id=work_id)
        live_acceptance = live_work / promoted.acceptance_path.relative_to(
            promoted.destination_root / "library" / "works" / work_id
        )
        readback = validate_acceptance(live_acceptance, root=Path(install_root))
    except (KeyError, OSError, TypeError, ValueError, PipelineError) as exc:
        raise PipelineError(f"admission {work_id} failed: {exc}") from exc
    return {
        "status": "admitted-and-validated",
        "identity": readback["identity"],
        "acceptance": str(live_acceptance),
        "master_sha256": promoted.master_sha256,
        "installation": installed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Bounded copied evidence root")
    parser.add_argument("--declaration", required=True, type=Path, help="Reviewed admission declaration JSON")
    parser.add_argument("--promotion", required=True, type=Path, help="Fresh promotion destination")
    parser.add_argument("--install-root", required=True, type=Path, help="Bounded destination repository root")
    args = parser.parse_args(argv)
    try:
        result = admit(args.root, args.declaration, args.promotion, args.install_root)
    except (OSError, ValueError, PipelineError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
