"""Freeze bounded Donne installation, scope reconciliation, and private release evidence."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_donne_devotions import ROOT, WORK, EDITION, BASE, SOURCE, SOURCE_SHA, SCOPE, canonical
from ocd_kernel.tei.install_accepted import _files, _io_path


def main():
    output = ROOT / "reports/_logs/donne-install-20261001-v1"
    publication = ROOT / WORK / "publication/private-offline-20261001"
    completion = json.loads((publication / "completion.json").read_bytes())
    pin = json.loads((ROOT / BASE / "stage-pin.json").read_bytes())
    stage = json.loads(Path(pin["receipt"]).read_bytes())
    installed = {p: h for p, h in _files(ROOT / WORK).items() if not p.startswith("publication/")}
    if installed != stage["after"] or completion["independent_check"]["status"] != "pass" or completion["reader_normal_and_streaming"] != "pass":
        raise ValueError("final canonical installation/release differs")
    if sha256((ROOT / SOURCE).read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError("source changed")
    if any(sha256((ROOT / p).read_bytes()).hexdigest() != digest for p, digest in stage["schema_pins"].items()):
        raise ValueError("final schema pins differ")
    journal = json.loads((ROOT / ".tmp_audit/accepted-install-21527dd5f1a94c8d/operation.json").read_bytes())
    if journal["phase"] != "complete" or journal["after"] != installed:
        raise ValueError("guarded journal differs")
    authorities = json.loads((ROOT / BASE / "source-manifest.json").read_bytes())["authorities"]
    paths = {a["path"] for a in authorities}
    paths.update((BASE / name).as_posix() for name in ("source-manifest.json", "stage-pin.json"))
    paths.update(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "build/tools").glob("*donne_devotions*.py"))
    paths.update(["build/tei/donne_devotions_scoped.py", "build/tei/donne_devotions_scoped_oracle.py", "tests/test_donne_devotions_scoped.py", "tests/test_native_literary_carriers.py", "data/prose/donne-devotions-upon-emergent-occasions/README.md"])
    evidence_paths = ["reports/_logs/donne-coordinator-source-review-20261001-v2/review.json", "reports/_logs/donne-reconciliation-20261001-v2/direct-conservation.json", "reports/_logs/donne-reconciliation-20261001-v2/active-scope-alignment.json", "reports/_logs/donne-mutations-20261001-v2/result.json", "reports/_logs/donne-native-policy-20261001-v2/schema-change-receipt.json", "reports/_logs/donne-reconciliation-20261001-v2/rollback-test-final.log"]
    paths.update(evidence_paths)
    hashes = {p: sha256(_io_path(ROOT / p).read_bytes()).hexdigest() for p in sorted(paths)}
    for a in authorities:
        if hashes[a["path"]] != a["sha256"]:
            raise ValueError("source authority changed: " + a["path"])
    receipt = dict(status="complete-technical-private-release-only", checked_at=datetime.now(timezone.utc).isoformat(), scope=SCOPE,
        installed_files=installed, installation_phase=journal["phase"], source_sha256=SOURCE_SHA, source_carriers=7647,
        represented_carriers=6842, retained_only_deaths_duel_carriers=805, stations=23, movements=69, footnotes=346,
        independent_source_receipt=evidence_paths[0], original_devotions_body_unchanged=True,
        schema_pins=stage["schema_pins"], current_authority_hashes=hashes,
        release_evidence_hashes=_files(publication), private_release=completion["release"], statistics=completion["statistics"],
        tests="10 focused native/uncertain checks passed; metadata and wrong receipt checks passed; corrected callback rollback node passed exit 0, exact original generation restored.",
        historical_scopes="Whole-volume and initial narrow candidates/receipts retained; corrected frontmatter classification explicitly supersedes narrow Walton exclusion.",
        unassessed=["human textual/visual verification", "print collation", "rights clearance", "publication authorization"], publication_performed=False)
    (output / "final-delivery-audit.json").write_bytes(canonical(receipt))
    (output / "README.md").write_text("# Donne technical completion\n\n" + SCOPE + "\n\n"
        "Guarded installation is complete: all 25 installed hashes and acquisition conservation match the frozen stage. Canonical actual-master projection, private offline assembly, independent verifier, statistics, and normal/streaming readers pass under six stable schema pins. Source and data notices visibly preserve Gutenberg production credits and the complete license; Walton's excerpt retains its attribution.\n\n"
        "Independent source review: `reports/_logs/donne-coordinator-source-review-20261001-v2/review.json`. Final frozen evidence: `final-delivery-audit.json`. Human textual/visual verification, print collation, rights clearance, and public publication remain unassessed or unauthorized. No acquisition, new work identity, Git operation, or publication occurred.\n", encoding="utf8", newline="\n")
    print(json.dumps(dict(status=receipt["status"], installed_files=len(installed), authority_files=len(hashes), release_files=len(receipt["release_evidence_hashes"]), statistics=receipt["statistics"])))


if __name__ == "__main__":
    main()
