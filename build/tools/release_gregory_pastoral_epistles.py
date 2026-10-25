"""Assemble and independently verify one private complete retained Gregory Pastoral Rule and Epistles offline release."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from build.tools.prepare_gregory_pastoral_epistles import ROOT, WORK_ID, WORK, EDITION, BASE, SOURCE_SHA, SCOPE, DATA_NOTICE
PINS = ROOT / BASE / "stage-pin.json"
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _io_path, _files


PIN = json.loads(PINS.read_bytes())
RECEIPT = Path(PIN["receipt"])
RECEIPT_SHA = PIN["receipt_sha256"]

PUBLICATION = WORK / "publication/private-offline-20261001"
SOURCE_NOTE = BASE / "README.source.md"
RELEASE_ID = "gregory-pastoral-epistles-private-offline-20261001-v1"


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
        raise PipelineError("Gregory Pastoral Rule and Epistles release requires the canonical Workspace authority")
    output = output.absolute()
    if output.exists():
        raise PipelineError("Gregory Pastoral Rule and Epistles offline output must be fresh")
    schema_paths = [Path("schemas/v2") / name for name in ("native-content.schema.json", "release-selection.schema.json", "release-report.schema.json", "public-row.schema.json", "projection-receipt.schema.json", "categories/prose.schema.json")]
    schema_pins = {p.as_posix(): _sha(root / p) for p in schema_paths}
    if _sha(RECEIPT) != RECEIPT_SHA or PIN["work_id"] != WORK_ID:
        raise PipelineError("Gregory Pastoral Rule and Epistles frozen install receipt differs")
    frozen = json.loads(_io_path(RECEIPT).read_bytes())
    if frozen["schema_pins"] != schema_pins or PIN["native_schema_sha256"] != schema_pins["schemas/v2/native-content.schema.json"]:
        raise PipelineError("Gregory Pastoral Rule and Epistles stage/release schema pins differ")
    generation = {path: digest for path, digest in _files(root / WORK).items()
                  if not path.startswith("publication/")}
    if generation != frozen["after"]:
        raise PipelineError("Gregory Pastoral Rule and Epistles installed generation differs from frozen stage")
    accepted_path = root / EDITION / "acceptance.json"
    request = selection(root)
    notice_texts_for_item(root, request["items"][0], accepted_path)
    print("Checking canonical installed acceptance and actual-master projection", flush=True)
    accepted = validate_acceptance(accepted_path, root=root)
    if accepted["identity"]["work_id"] != WORK_ID or accepted["source"]["source_sha256"] != SOURCE_SHA:
        raise PipelineError("Gregory Pastoral Rule and Epistles source/accepted identity differs")
    projection = project_accepted_document(root, acceptance_path=accepted_path, category="prose")
    errors = verify_accepted_document(root, acceptance_path=accepted_path,
                                    rows=projection["rows"], receipt=projection["receipt"], category="prose")
    if errors or len(projection["rows"]) != 1:
        raise PipelineError(f"Gregory Pastoral Rule and Epistles actual-master correspondence failed: {errors[:3]}")
    _write(root / PUBLICATION / "selection.json", request)
    _write(root / PUBLICATION / "actual-master-projection.json", projection)
    print("Assembling and independently verifying canonical one-work offline release", flush=True)
    assembled = assemble_release_v2(root, output, selection=request)
    verified = verify_release_v2(root, output, selection=request)
    _write(root / PUBLICATION / "assembly.json", assembled)
    _write(root / PUBLICATION / "independent-verification.json", verified)
    if verified["status"] != "pass":
        raise PipelineError(f"Gregory Pastoral Rule and Epistles independent release verification failed: {verified['errors']}")
    print("Checking release statistics and normal/streaming readers", flush=True)
    stats = release_statistics(root, output, request)
    _write(root / PUBLICATION / "statistics.json", stats)
    reader = check_reader(root, output, request)
    _write(root / PUBLICATION / "reader-proof.json", reader)
    completion = dict(source_title_and_boundary_qualification=SCOPE, status="offline-verified-not-authorized-for-publication",
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
        raise PipelineError("Gregory Pastoral Rule and Epistles installed authority changed during release checks")
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
