"""Assemble and independently verify one private retained York IV offline release."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from build.tools.prepare_openmgh_bsb830_york_four import ROOT, WORK_ID, SOURCE_SHA, BREAKOFF
from build.tools.install_openmgh_bsb830_york_four import PINS, PINS_SHA
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _io_path, _files


WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / f"{WORK_ID}-openmgh-retained" / "editions" / f"{WORK_ID}-openmgh-electronic"
PIN = json.loads(PINS.read_bytes())["stages"][0]
RECEIPT = Path(PIN["receipt"])
RECEIPT_SHA = PIN["receipt_sha256"]

PUBLICATION = WORK / "publication/private-offline-20261001"
SOURCE_NOTE = Path("sources/openmgh-bsb830-york-four") / WORK_ID / "README.source.md"
DATA_NOTICE = Path("data/prose") / WORK_ID / "README.md"
RELEASE_ID = "york-tractate-consecration-of-bishops-and-kings-private-offline-20261001-v3"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    target = _io_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def selection(root: Path) -> dict:
    return dict(schema_version="2.0", release_id=RELEASE_ID, items=[dict(
        item_id=WORK_ID, category="prose", acceptance_path=(EDITION / "acceptance.json").as_posix(),
        public_notices=[dict(source_path=SOURCE_NOTE.as_posix(), source_sha256=_sha(root / SOURCE_NOTE),
                             notice_path=DATA_NOTICE.as_posix(), notice_sha256=_sha(root / DATA_NOTICE))])])


@cached_edition_lookups()
def run(root: Path, output: Path) -> dict:
    root = root.resolve(strict=True)
    if root != ROOT.resolve(strict=True):
        raise PipelineError("York IV release requires the canonical Workspace authority")
    output = output.absolute()
    if output.exists():
        raise PipelineError("York IV offline output must be fresh")
    schema_paths = [Path("schemas/v2") / name for name in ("native-content.schema.json", "release-selection.schema.json", "release-report.schema.json", "public-row.schema.json", "projection-receipt.schema.json", "categories/prose.schema.json")]
    schema_pins = {p.as_posix(): _sha(root / p) for p in schema_paths}
    if _sha(PINS) != PINS_SHA or _sha(RECEIPT) != RECEIPT_SHA:
        raise PipelineError("York IV frozen install receipt differs")
    frozen = json.loads(_io_path(RECEIPT).read_bytes())
    generation = {path: digest for path, digest in _files(root / WORK).items()
                  if not path.startswith("publication/")}
    if generation != frozen["after"]:
        raise PipelineError("York IV installed generation differs from frozen stage")
    accepted_path = root / EDITION / "acceptance.json"
    print("Checking canonical installed acceptance and actual-master projection", flush=True)
    accepted = validate_acceptance(accepted_path, root=root)
    if accepted["identity"]["work_id"] != WORK_ID or accepted["source"]["source_sha256"] != SOURCE_SHA:
        raise PipelineError("York IV source/accepted identity differs")
    projection = project_accepted_prose(root, acceptance_path=accepted_path)
    errors = verify_accepted_prose(root, acceptance_path=accepted_path,
                                    rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 1:
        raise PipelineError(f"York IV actual-master correspondence failed: {errors[:3]}")
    request = selection(root)
    _write(root / PUBLICATION / "selection.json", request)
    _write(root / PUBLICATION / "actual-master-projection.json", projection)
    print("Assembling and independently verifying canonical one-work offline release", flush=True)
    assembled = assemble_release_v2(root, output, selection=request)
    verified = verify_release_v2(root, output, selection=request)
    _write(root / PUBLICATION / "assembly.json", assembled)
    _write(root / PUBLICATION / "independent-verification.json", verified)
    if verified["status"] != "pass":
        raise PipelineError(f"York IV independent release verification failed: {verified['errors']}")
    print("Checking release statistics and normal/streaming readers", flush=True)
    stats = release_statistics(root, output, request)
    _write(root / PUBLICATION / "statistics.json", stats)
    reader = check_reader(root, output, request)
    _write(root / PUBLICATION / "reader-proof.json", reader)
    completion = dict(source_breakoff=BREAKOFF, original_composition_completeness="unresolved", status="offline-verified-not-authorized-for-publication",
                      checked_at=datetime.now(timezone.utc).isoformat(), work_id=WORK_ID,
                      release=output.as_posix(), authority_root=root.as_posix(), source_sha256=SOURCE_SHA,
                      master_sha256=_sha(root / EDITION / "master.tei.xml"),
                      acceptance_sha256=_sha(accepted_path), projection_rows=1,
                      independent_check=verified, statistics=stats["total"],
                      reader_normal_and_streaming=reader["status"], human_review="not-recorded",
                      print_collation="not-performed", rights_clearance="not-recorded",
                      publication_authorization="not-recorded", publication_performed=False,
                      attribution_notices=request["items"][0]["public_notices"], schema_pins=schema_pins)
    if {p.as_posix(): _sha(root / p) for p in schema_paths} != schema_pins:
        raise PipelineError("Shared schemas changed during release checks")
    if ({path: digest for path, digest in _files(root / WORK).items()
         if not path.startswith("publication/")} != generation):
        raise PipelineError("York IV installed authority changed during release checks")
    _write(root / PUBLICATION / "completion.json", completion)
    return completion


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.output), indent=2))


if __name__ == "__main__":
    main()
