"""Assemble and independently verify one private A47235 offline release."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from build.tools.stage_prayers_baths_for_cure_acceptance import ROOT, WORK, WORK_ID, EDITION, SOURCE_SHA
from build.tools.install_prayers_baths_for_cure_acceptance import RECEIPT, RECEIPT_SHA
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prayers import project_accepted_prayers, verify_accepted_prayers
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _io_path, _files


PUBLICATION = WORK / "publication/private-offline-20261001"
SOURCE_NOTE = Path("sources/structured-text") / WORK_ID / "README.source.md"
DATA_NOTICE = Path("data/prayers") / WORK_ID / "README.md"
RELEASE_ID = "prayers-baths-for-cure-private-offline-20261001-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    target = _io_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def selection(root: Path) -> dict:
    return dict(schema_version="2.0", release_id=RELEASE_ID, items=[dict(
        item_id=WORK_ID, category="prayers", acceptance_path=(EDITION / "acceptance.json").as_posix(),
        public_notices=[dict(source_path=SOURCE_NOTE.as_posix(), source_sha256=_sha(root / SOURCE_NOTE),
                             notice_path=DATA_NOTICE.as_posix(), notice_sha256=_sha(root / DATA_NOTICE))])])


@cached_edition_lookups()
def run(root: Path, output: Path) -> dict:
    root = root.resolve(strict=True)
    output = output.absolute()
    if output.exists():
        raise PipelineError("A47235 offline output must be fresh")
    if _sha(RECEIPT) != RECEIPT_SHA:
        raise PipelineError("A47235 frozen install receipt differs")
    frozen = json.loads(_io_path(RECEIPT).read_bytes())
    generation = {path: digest for path, digest in _files(root / WORK).items()
                  if not path.startswith("publication/")}
    if generation != frozen["after"]:
        raise PipelineError("A47235 installed generation differs from frozen stage")
    accepted_path = root / EDITION / "acceptance.json"
    print("Checking canonical installed acceptance and actual-master projection", flush=True)
    accepted = validate_acceptance(accepted_path, root=root)
    if accepted["identity"]["work_id"] != WORK_ID or accepted["source"]["source_sha256"] != SOURCE_SHA:
        raise PipelineError("A47235 source/accepted identity differs")
    projection = project_accepted_prayers(root, acceptance_path=accepted_path)
    errors = verify_accepted_prayers(root, acceptance_path=accepted_path,
                                    rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 3:
        raise PipelineError(f"A47235 actual-master correspondence failed: {errors[:3]}")
    request = selection(root)
    _write(root / PUBLICATION / "selection.json", request)
    _write(root / PUBLICATION / "actual-master-projection.json", projection)
    print("Assembling and independently verifying canonical one-work offline release", flush=True)
    assembled = assemble_release_v2(root, output, selection=request)
    verified = verify_release_v2(root, output, selection=request)
    _write(root / PUBLICATION / "assembly.json", assembled)
    _write(root / PUBLICATION / "independent-verification.json", verified)
    if verified["status"] != "pass":
        raise PipelineError(f"A47235 independent release verification failed: {verified['errors']}")
    print("Checking release statistics and normal/streaming readers", flush=True)
    stats = release_statistics(root, output, request)
    _write(root / PUBLICATION / "statistics.json", stats)
    reader = check_reader(root, output, request)
    _write(root / PUBLICATION / "reader-proof.json", reader)
    completion = dict(status="offline-verified-not-authorized-for-publication",
                      checked_at=datetime.now(timezone.utc).isoformat(), work_id=WORK_ID,
                      release=output.as_posix(), authority_root=root.as_posix(), source_sha256=SOURCE_SHA,
                      master_sha256=_sha(root / EDITION / "master.tei.xml"),
                      acceptance_sha256=_sha(accepted_path), projection_rows=3,
                      independent_check=verified, statistics=stats["total"],
                      reader_normal_and_streaming=reader["status"], human_review="not-recorded",
                      print_collation="not-performed", rights_clearance="not-recorded",
                      publication_authorization="not-recorded", publication_performed=False,
                      attribution_notices=request["items"][0]["public_notices"])
    if ({path: digest for path, digest in _files(root / WORK).items()
         if not path.startswith("publication/")} != generation):
        raise PipelineError("A47235 installed authority changed during release checks")
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
