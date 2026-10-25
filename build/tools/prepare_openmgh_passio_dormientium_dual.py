"""Prepare both exact Passio Dormientium source-division candidates outside the checkout."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tei import openmgh_passio_dormientium_dual as source
from build.tei.openmgh_passio_dormientium_dual_oracle import check
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


CONTRACT = "ocd-openmgh-passio-dormientium-dual-direct-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def prepare(output: Path) -> dict:
    output = output.absolute()
    if (_io_path(output).exists() or not _io_path(output.parent).is_dir()
            or source.ROOT.resolve() in output.resolve().parents):
        raise ValueError("fresh external Passio Dormientium candidate directory required")
    _io_path(output).mkdir()
    works = []
    for code in sorted(source.WITNESSES):
        content, producer = source.convert(code)
        oracle = check(code, content)
        candidate_path = output / code / "candidate.tei.xml"
        _io_path(candidate_path).parent.mkdir(parents=True)
        _io_path(candidate_path).write_bytes(content)
        if errors := validate_file(_io_path(candidate_path)):
            raise ValueError(f"{code} source candidate P5 XSD errors: {errors[:3]}")
        works.append(dict(code=code, candidate_path=candidate_path.as_posix(),
                          candidate_sha256=_sha(candidate_path), producer=producer, oracle=oracle,
                          source_path=producer["source_path"], source_sha256=producer["source_sha256"],
                          source_div_c14n_sha256=producer["source_div_c14n_sha256"],
                          source_package_path=source.paths(code)[1].as_posix(),
                          package_sha256=source.WITNESSES[code]["package_sha256"],
                          acquisition_receipt_path=source.paths(code)[2].as_posix(),
                          acquisition_receipt_sha256=source.WITNESSES[code]["receipt_sha256"],
                          validation="tei-p5-pass"))
    result = dict(contract=CONTRACT, status="nonaccepted", work_id=source.WORK_ID,
                  prepared_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                  selected_editions=2, sources=works,
                  disposition="Two separate source-exclusive electronic editions; each excludes all sibling volume divisions.",
                  canonical_install="not-performed")
    _io_path(output / "receipt.json").write_bytes(_json(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.output)
    print(json.dumps(dict(status=result["status"], editions=len(result["sources"]),
                          receipt=(args.output / "receipt.json").as_posix(),
                          receipt_sha256=_sha(args.output / "receipt.json")), sort_keys=True))


if __name__ == "__main__":
    main()
