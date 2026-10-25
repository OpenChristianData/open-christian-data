"""Pin final canonical state, installed file hashes, source and schema stability."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tools.prepare_georgii_aliud import ROOT, WORK, EDITION, ACQUISITION, BASE, TITLE, ORIGINAL_TITLE, canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-evidence", type=Path, required=True)
    parser.add_argument("--installation", type=Path, required=True)
    args = parser.parse_args()
    installation = json.loads(args.installation.read_bytes())
    completion = json.loads((args.release_evidence / "completion.json").read_bytes())
    readers = json.loads((args.release_evidence / "readers.json").read_bytes())
    schemas = completion["bound_schema_stability"]["after"]
    before = {path: sha256((ROOT / path).read_bytes()).hexdigest() for path in schemas}
    if before != schemas:
        raise ValueError("release-bound schema drift")
    for path, digest in installation["installed_files"].items():
        if sha256(io_path(ROOT / WORK / path).read_bytes()).hexdigest() != digest:
            raise ValueError(f"installed file drift: {path}")
    with cached_edition_lookups():
        validate_acceptance(ROOT / EDITION / "acceptance.json", root=ROOT)
        validate_state(ROOT / WORK / "state.json", root=ROOT)
        SourceManifest.load(ROOT / BASE / "source-manifest.json", repository_root=ROOT)
    source_sha = sha256((ROOT / "raw/openmgh/bsb00000720/tei/bsb00000720.xml").read_bytes()).hexdigest()
    acquisition_sha = sha256(io_path(ROOT / ACQUISITION).read_bytes()).hexdigest()
    if source_sha != completion["source_sha256"] or acquisition_sha != "c5e41bb261ee54524e3821f90ccff869ec8a1c0601ecd630aae1a6c3c50d1194":
        raise ValueError("source or acquisition drift")
    if readers["status"] != "pass":
        raise ValueError("readers did not pass")
    original = json.loads((args.installation.parent/"original-work.json").read_bytes())
    if original["title"] != ORIGINAL_TITLE:
        raise ValueError("precise original title pin differs")
    expected = json.loads(json.dumps(original))
    expected["title"] = TITLE
    expected["textual_forms"][0]["language"] = "la"
    expected["textual_forms"][0]["editions"][0].update(language="la",category="poetry")
    if json.loads(io_path(ROOT/WORK/"work.json").read_bytes()) != expected:
        raise ValueError("canonical metadata exceeds precise title/language/category prerequisite")
    siblings = json.loads((args.installation.parent/"sibling-conservation.json").read_bytes())
    sibling_now = {work_id:_files(ROOT/"library/works"/work_id) for work_id in siblings["before"]}
    if sibling_now != siblings["before"]:
        raise ValueError("sibling changed during second-poem private release phase")
    after = {path: sha256((ROOT / path).read_bytes()).hexdigest() for path in schemas}
    if after != before:
        raise ValueError("schemas changed during final canonical checks")
    record = dict(status="pass", source_sha256=source_sha, acquisition_sha256=acquisition_sha,
                  installed_files_checked=len(installation["installed_files"]),
                  all_installed_hashes_unchanged=True, canonical_acceptance_state="pass",
                  current_source_manifest="pass", normal_and_streaming_readers="pass",
                  exact_title_language_category_prerequisite="pass", sibling_installation_and_short_release_conservation="pass",
                  bound_schema_stability=dict(status="pass", before=before, after=after),
                  new_downstream_work_paths=["publication/private-offline-20261001/selection.json", "publication/private-offline-20261001/completion.json", "publication/private-offline-20261001/README.md"])
    (args.release_evidence / "final-canonical-check.json").write_bytes(canonical(record))
    print(json.dumps(record))


if __name__ == "__main__":
    main()
