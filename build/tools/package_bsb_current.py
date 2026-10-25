"""Exact current BSB replay and 22 meaningful source/scaffold mutations."""
import argparse
from hashlib import sha256
import re
from pathlib import Path
from lxml import etree
from build.tools.prepare_bsb_current import ROOT, BASE, canonical
from build.tei.bsb_current_oracle import check
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "replay", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    candidate = CandidatePackage.load(args.candidate / "package")
    replay = CandidatePackage.load(args.replay / "package")
    if candidate.sha256 != replay.sha256 or any(candidate.member_bytes(n) != replay.member_bytes(n) for n in candidate.member_names) or (args.candidate / "validation.json").read_bytes() != (args.replay / "validation.json").read_bytes():
        raise ValueError("Exact complete fresh-process replay differs")
    manifest = SourceManifest.load(ROOT / BASE / "source-manifest.json", repository_root=ROOT)
    raw = candidate.member_bytes("content.tei.xml")
    baseline = check(manifest, raw)
    first = re.search(rb'<ab type="verse" n="1" xml:id="bsb-book-01-chapter-001-verse-001" xml:space="preserve">.*?</ab>', raw, re.S).group()
    second = re.search(rb'<ab type="verse" n="2" xml:id="bsb-book-01-chapter-001-verse-002" xml:space="preserve">.*?</ab>', raw, re.S).group()
    gap = raw[raw.index(first) + len(first):raw.index(second)]
    empty = b'<ab type="verse" n="21" xml:id="bsb-book-40-chapter-017-verse-021" xml:space="preserve"/>'
    if raw.count(empty) != 1:
        raise ValueError("Source-native empty mutation selector differs")
    samples = {
        "wording": raw.replace(first, first.replace(b"In the beginning", b"Invented opening"), 1),
        "verse-omission": raw.replace(first, b"", 1),
        "verse-duplicate": raw.replace(first, first + first, 1),
        "verse-order": raw.replace(first + gap + second, second + gap + first, 1),
        "verse-number": raw.replace(first, first.replace(b'n="1"', b'n="2"', 1), 1),
        "verse-id": raw.replace(first, first.replace(b"verse-001", b"verse-999", 1), 1),
        "verse-child": raw.replace(first, first.replace(b"</ab>", b"<note>Invented</note></ab>"), 1),
        "verse-tail": raw.replace(first, first + b"Invented tail", 1),
        "book-name": raw.replace(b'type="book" n="Genesis"', b'type="book" n="1"', 1),
        "book-attachment": raw.replace(b'xml:id="bsb-book-01-chapter-001"', b'xml:id="bsb-book-02-chapter-001"', 1),
        "header-label": raw.replace(b"BSB: Berean Standard Bible", b"Invented print edition", 1),
        "header-rights": raw.replace(b"legal clearance for the exact JSON witness", b"Universal clearance established", 1),
        "foreign-namespace": raw.replace(b'<ab type="verse"', b'<ab xmlns="urn:invented" type="verse"', 1),
        "whitespace-trim": raw.replace(first, first.replace(b"> In the", b">In the").replace(b"earth. </ab>", b"earth.</ab>"), 1),
        "preserve-marker-loss": raw.replace(first, first.replace(b' xml:space="preserve"', b""), 1),
        "empty-verse-fill": raw.replace(empty, empty[:-2] + b">Invented filling</ab>", 1),
        "empty-verse-omission": raw.replace(empty, b"", 1),
        "empty-verse-child": raw.replace(empty, empty[:-2] + b"><note>Invented</note></ab>", 1),
        "generated-role-invention": raw.replace(b'<text xml:id="bsb-text">', b'<text xml:id="bsb-text" type="bible">', 1),
        "header-cc0": raw.replace(b"CC0-1.0", b"Invented license", 1),
    }
    first_book = re.search(rb'<div type="book" n="Genesis".*?(?=<div type="book")', raw, re.S).group()
    second_book = re.search(rb'<div type="book" n="Exodus".*?(?=<div type="book")', raw, re.S).group()
    samples["book-omission"] = raw.replace(first_book, b"", 1)
    samples["book-order"] = raw.replace(first_book + second_book, second_book + first_book, 1)
    if len(samples) != 22:
        raise ValueError("Mutation inventory differs")
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    for name, changed in samples.items():
        if changed == raw:
            raise ValueError("Inert mutation " + name)
        try:
            check(manifest, changed)
        except (ValueError, etree.XMLSyntaxError, etree.DocumentInvalid) as error:
            cases.append(dict(name=name, status="rejected", reason=str(error), mutated_sha256=sha256(changed).hexdigest()))
        else:
            raise ValueError("Accepted source/scaffold mutation " + name)
        print("Rejected " + name, flush=True)
    proof = dict(status="pass", baseline=baseline, cases=cases, candidate_sha256=candidate.sha256, replay_sha256=replay.sha256,
                 validation_equal=True, mutation_selectors="Exact byte transformations in this SHA-bound work-local script; source/candidate/replay retained.")
    (args.output / "result.json").write_bytes(canonical(proof))
    print(dict(status="pass", cases=len(cases)))


if __name__ == "__main__":
    main()
