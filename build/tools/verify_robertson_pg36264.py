"""Focused positive, replay, native, and resealed negative Robertson checks."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from lxml import etree
from build.tei.robertson_pg36264_oracle import _oracle
from build.tools.reconstruct_candidate import run
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate

MANIFEST = "sources/structured-text/robertson-pg36264/source-manifest.json"
REVIEW = Path("D:/Library/Open Christian Data/candidate-reviews/robertson-pg36264-v3")
IDENTITY = dict(work_id="robertson-harmony-of-the-gospels", textual_form_id="robertson-harmony-english",
                edition_id="robertson-harmony-1922-harper-pg36264")
NS = {"t": "http://www.tei-c.org/ns/1.0"}


def _sha(value):
    return sha256(value).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    root = Path.cwd().resolve(strict=True)
    report_path = args.report.absolute()
    if not report_path.is_relative_to(root / "library/works" / IDENTITY["work_id"]):
        raise ValueError("Robertson work-local report required")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    original = CandidatePackage.load(REVIEW / "handoff/package")
    baseline = validate(manifest, original, _oracle)
    replay = run(manifest=MANIFEST, destination=str(REVIEW / "replay"), repository_root=str(root))
    reproduced = CandidatePackage.load(REVIEW / "replay/package")
    if reproduced.sha256 != original.sha256 or any(original.member_bytes(n) != reproduced.member_bytes(n) for n in original.member_names):
        raise ValueError("fresh maintained replay differs")
    raw = original.member_bytes("content.tei.xml")
    mutated = []
    cases = ["word", "column-span", "row-span", "empty-extra-cell", "fragment-target", "map-target", "section-ownership"]
    for case in cases:
        doc = etree.fromstring(raw)
        if case == "word":
            node = next(n for n in doc.iter() if n.text and "CHAIR OF NEW TESTAMENT INTERPRETATION" in n.text)
            node.text = node.text.replace("CHAIR", "CHAIB", 1)
        elif case == "column-span":
            doc.xpath("//t:cell[@cols]", namespaces=NS)[0].set("cols", "9")
        elif case == "row-span":
            doc.xpath("//t:cell[@rows]", namespaces=NS)[0].set("rows", "1")
        elif case == "empty-extra-cell":
            etree.SubElement(doc.xpath("//t:row", namespaces=NS)[0], "{" + NS["t"] + "}cell")
        elif case == "fragment-target":
            doc.xpath("//t:ref[@target]", namespaces=NS)[0].set("target", "#section184")
        elif case == "map-target":
            doc.xpath("//t:graphic", namespaces=NS)[0].set("url", "images/2.jpg")
        else:
            doc.xpath("//t:div[@n='section1']", namespaces=NS)[0].set("n", "section184")
        content = etree.tostring(doc, encoding="UTF-8", xml_declaration=True)
        # Deliberately reseal isolated negative fixtures: the oracle must reject
        # changed semantics even when the package integrity hashes are valid.
        with TemporaryDirectory(prefix="negative-", dir=REVIEW) as scratch:
            target = Path(scratch).resolve(strict=True)
            if target.parent != REVIEW.resolve(strict=True) or target.is_junction():
                raise ValueError("unsafe negative fixture cleanup boundary")
            for name in original.member_names:
                shutil.copyfile(original.path / name, target / name)
            (target / "content.tei.xml").write_bytes(content)
            package_manifest = json.loads((target / "manifest.json").read_bytes())
            entry = next(x for x in package_manifest["members"] if x["name"] == "content.tei.xml")
            entry.update(bytes=len(content), sha256=_sha(content))
            (target / "manifest.json").write_text(json.dumps(package_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            fixture = CandidatePackage.load(target)
            observed = _oracle(manifest, fixture)
            if observed["status"] != "fail" or not observed["findings"]:
                raise ValueError("source oracle accepted mutation: " + case)
            mutated.append(dict(case=case, integrity_valid=True, oracle_status="fail", findings=observed["findings"], fixture_sha256=fixture.sha256))
        print("rejected " + case, flush=True)
    native_args = dict(identity=IDENTITY, language="en", representation_revision="robertson-pg36264-v3",
                       edition_title="Harper & Brothers 1922 retained Gutenberg electronic witness",
                       category="prose", _allow_acceptance_metadata=True)
    projected = project_document(original.path / "content.tei.xml", **native_args)
    errors = verify_document(original.path / "content.tei.xml", projected["rows"], projected["receipt"], **native_args)
    if errors:
        raise ValueError("independent native verifier failed: " + repr(errors))
    result = dict(contract="ocd-robertson-pg36264-focused-verification-v1", status="pass", exit_code=0,
                  command="py -3 -m build.tools.verify_robertson_pg36264 --report " + report_path.relative_to(root).as_posix(),
                  candidate_path=original.path.as_posix(), candidate_sha256=original.sha256,
                  tei_sha256=_sha(raw), source_manifest_sha256=manifest.sha256,
                  baseline_validation_sha256=baseline.sha256, replay=replay, replay_members_byte_equal=True,
                  negative_fixtures=mutated, native=dict(rows=len(projected["rows"]), independent_verifier_errors=errors,
                  scope="in-memory nonaccepted candidate; header metadata mode; no accepted-master or public-row write"),
                  acceptance="not-performed", installation="not-performed", release="external-rights-profile-hold")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(status="pass", mutations_rejected=len(mutated), native_rows=len(projected["rows"]))))


if __name__ == "__main__":
    main()
