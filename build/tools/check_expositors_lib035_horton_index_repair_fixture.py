"""Exercise Horton's guarded swap and rollback on marked external fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from build.tools.install_expositors_lib035_horton_index_repair import (
    FIXTURE_MARKER, ROOT, WORK_ID, install, preflight,
)
from ocd_kernel.tei.install_accepted import _files, _io_path


def check(base: Path) -> dict[str, object]:
    if base.exists() or not base.parent.is_dir():
        raise ValueError("fixture requires a fresh external directory")
    _, _, _, _ = preflight()
    before = _files(ROOT / "library/works" / WORK_ID)
    results = {}
    for name in ("after-old-rename", "after-new-rename", "success"):
        fixture = base / name
        target = fixture / "library/works" / WORK_ID
        _io_path(target).mkdir(parents=True)
        _io_path(fixture / FIXTURE_MARKER).write_text("Horton isolated fixture\n", encoding="utf-8")
        for relative, digest in before.items():
            source = _io_path(ROOT / "library/works" / WORK_ID / relative)
            destination = _io_path(target / relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if _files(target) != before:
            raise ValueError("Horton fixture preimage differs")
        if name == "success":
            result = install(root_override=fixture)
            if result["status"] != "installed-and-validated":
                raise ValueError("Horton success fixture did not install")
            results[name] = result["operation"]
        else:
            def interrupt(seam: str) -> None:
                if seam == name:
                    raise RuntimeError("Horton fixture interruption")

            try:
                install(root_override=fixture, fail_at=interrupt)
            except RuntimeError as exc:
                if str(exc) != "Horton fixture interruption":
                    raise
            else:
                raise ValueError(f"Horton {name} seam did not interrupt")
            if _files(target) != before:
                raise ValueError(f"Horton {name} rollback changed preimage")
            results[name] = "restored-preimage"
    return {"status": "pass", "seams": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.base), sort_keys=True))


if __name__ == "__main__":
    main()
