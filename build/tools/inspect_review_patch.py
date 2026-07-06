from __future__ import annotations

import sys

from build.tools.apply_review_patch import (
    SchemaValidationError,
    decision_target,
    load_patch,
    validate_review_patch,
    verify_content_hashes,
)


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if len(args) != 1:
        print("usage: inspect_review_patch.py <patch.json>", file=sys.stderr)
        raise SystemExit(2)

    patch = load_patch(args[0])
    validate_review_patch(patch)
    verify_content_hashes(patch)
    for decision in patch["decisions"]:
        print(f"{decision['decision_kind']}  {decision_target(decision)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]) or 0)
    except SchemaValidationError as exc:
        print(f"review patch schema violation: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
