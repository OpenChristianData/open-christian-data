"""Exact fresh replay and independently rejected source-preservation mutations."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from lxml import etree
from build.tools.prepare_jps_current import ROOT, BASE, canonical
from build.tei.jps_current_oracle import check
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage

def challenge(manifest, raw):
    baseline = check(manifest, raw)
    verse = re.search(rb'<ab type="verse" n="1" xml:id="jps-b1-c1-v1" xml:space="preserve">.*?</ab>', raw).group()
    empty = re.search(rb'<ab type="verse" n="24" xml:id="jps-b2-c20-v24" xml:space="preserve" />', raw).group()
    next_verse = re.search(rb'<ab type="verse" n="2" xml:id="jps-b1-c1-v2" xml:space="preserve">.*?</ab>', raw).group()
    samples = {
        'wording': raw.replace(verse, verse.replace(b'IN THE beginning', b'Invented opening'), 1),
        'omitted-empty': raw.replace(empty, b'', 1),
        'invented-empty': raw.replace(empty, empty.replace(b' />', b'>Invented content</ab>'), 1),
        'duplicated-empty': raw.replace(empty, empty+empty, 1),
        'empty-preserve-omitted': raw.replace(empty, empty.replace(b' xml:space="preserve"', b''), 1),
        'empty-notes-only': raw.replace(empty, empty.replace(b' />', b'><note>Invented note</note></ab>'), 1),
        'verse-order': raw.replace(verse+next_verse, next_verse+verse, 1),
        'verse-number': raw.replace(verse, verse.replace(b'n="1"', b'n="2"', 1), 1),
        'verse-id': raw.replace(verse, verse.replace(b'jps-b1-c1-v1', b'invented'), 1),
        'book-name': raw.replace(b'type="book" n="Genesis"', b'type="book" n="1"', 1),
        'book-attachment': raw.replace(b'xml:id="jps-b1-c1"', b'xml:id="jps-b2-c1"', 1),
        'header-print-publisher': raw.replace(b'scrollmapper/bible_databases; retained electronic source provider, not an inferred print publisher', b'Invented print publisher', 1),
        'header-rights': raw.replace(b'Underlying translation rights', b'Invented universal permission', 1) if b'Underlying translation rights' in raw else raw.replace(b'underlying translation rights', b'invented universal permission', 1),
    }
    cases = []
    for name, changed in samples.items():
        if changed == raw:
            raise ValueError('Mutation did not change candidate: '+name)
        try:
            check(manifest, changed)
        except (ValueError, etree.XMLSyntaxError, etree.DocumentInvalid) as error:
            cases.append(dict(name=name, status='rejected', reason=str(error), mutated_sha256=sha256(changed).hexdigest()))
        else:
            raise ValueError('Independent oracle accepted '+name)
    return dict(status='pass', baseline=baseline, cases=cases)

def main():
    p = argparse.ArgumentParser()
    for name in ('candidate','replay','output'):
        p.add_argument('--'+name, type=Path, required=True)
    args = p.parse_args()
    candidate = CandidatePackage.load(args.candidate/'package')
    replay = CandidatePackage.load(args.replay/'package')
    if candidate.sha256 != replay.sha256 or any(candidate.member_bytes(n) != replay.member_bytes(n) for n in candidate.member_names):
        raise ValueError('Fresh complete package replay differs')
    if (args.candidate/'validation.json').read_bytes() != (args.replay/'validation.json').read_bytes():
        raise ValueError('Fresh validation bytes differ')
    manifest = SourceManifest.load(ROOT/BASE/'source-manifest.json', repository_root=ROOT)
    proof = challenge(manifest, candidate.member_bytes('content.tei.xml'))
    proof.update(candidate_sha256=candidate.sha256, replay_sha256=replay.sha256, validation_equal=True)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'result.json').write_bytes(canonical(proof))
    print(json.dumps(dict(status='pass', cases=len(proof['cases']), candidate_sha256=candidate.sha256)))

if __name__ == '__main__':
    main()
