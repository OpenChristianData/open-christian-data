"""Pin final canonical state and retain coordinator review of the direction repair."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tools.prepare_basil_holy_spirit import ROOT, WORK, EDITION, ACQUISITION, BASE, canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.acceptance import validate_acceptance


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
    source_sha = sha256((ROOT / "raw/ccel/npnf2/npnf208.xml").read_bytes()).hexdigest()
    acquisition_sha = sha256(io_path(ROOT / ACQUISITION).read_bytes()).hexdigest()
    if source_sha != completion["source_sha256"] or acquisition_sha != "0133f38e470bd062aa7b6626d398dfa2be2e6247ed50e4d5d01682e192576e55":
        raise ValueError("source or acquisition drift")
    if readers["status"] != "pass":
        raise ValueError("readers did not pass")
    after = {path: sha256((ROOT / path).read_bytes()).hexdigest() for path in schemas}
    if after != before:
        raise ValueError("schemas changed during final canonical checks")
    record = dict(status="pass", source_sha256=source_sha, acquisition_sha256=acquisition_sha,
                  installed_files_checked=len(installation["installed_files"]),
                  all_installed_hashes_unchanged=True, canonical_acceptance_state="pass",
                  current_source_manifest="pass", normal_and_streaming_readers="pass",
                  bound_schema_stability=dict(status="pass", before=before, after=after),
                  new_downstream_work_paths=["publication/private-offline-20261001/selection.json", "publication/private-offline-20261001/completion.json", "publication/private-offline-20261001/README.md"])
    (args.release_evidence / "final-canonical-check.json").write_bytes(canonical(record))
    coordinator = dict(status="pass", recorded_at=datetime.now(timezone.utc).isoformat(),
                       provenance="Coordinator /root direct team message: independent source/candidate comparison; retained here as an attributed review receipt, not a new automated check.",
                       finding="All 3440 text-tree elements retain identical tags, text, tails and hierarchy; sole attribute change is rend c59 -> c59 direction:rtl on span vii.vii-p30.6. Direct retained source uniquely confirms dir=rtl,class=c59.",
                       old_candidate="D:/Library/Open Christian Data/candidate-reviews/basil-holy-spirit-current-20261001-v1/package/content.tei.xml",
                       old_candidate_sha256="e34ee3a90d3ff0d7aab9d9d5f76eb19d2721da2eeda3e1e08318a2cc854c2031",
                       repaired_candidate="D:/Library/Open Christian Data/candidate-reviews/basil-holy-spirit-current-20261001-v2/package/content.tei.xml",
                       repaired_candidate_sha256="3d48eb9d0d5296aab22633c51b7b62c0ef4dc6bfc02f063309e97f5ac86490c6",
                       source_xpath="/ThML/ThML.body/div1[@id='vii']/div2[@id='vii.vii']//span[@id='vii.vii-p30.6']",
                       candidate_xpath="//t:seg[@xml:id='lib046-npnf208-000610-vii.vii-p30.6']", tei_namespace="http://www.tei-c.org/ns/1.0")
    (args.release_evidence / "coordinator-direction-review.json").write_bytes(canonical(coordinator))
    print(json.dumps(record))


if __name__ == "__main__":
    main()
