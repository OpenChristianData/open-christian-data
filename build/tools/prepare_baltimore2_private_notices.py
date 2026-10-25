"""Prepare source-bound private release notices for Baltimore Catechism No. 2."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "raw/gutenberg/pg14552.txt"
SOURCE_SHA = "3d4b556fdb094ab8e22a53df85f60ba3310b49c9c65a24281aeecb9119f9746c"
SOURCE_NOTICE = ROOT / "sources/publication-pg14552/baltimore-catechism-no-2/README.source.md"
DATA_NOTICE = ROOT / "data/catechisms/baltimore-catechism-no-2/README.md"
PREVIOUS_SHA = "9fb47992c38dacb1f16281fe2569124a97e99452313c69a1da7883e03ad260c3"
LICENSE_START = b"Updated editions will replace the previous one"
COMMON_INTRO = """# Baltimore Catechism No. 2: retained electronic source and use notice

This private dataset selection represents the complete retained Project Gutenberg
eBook 14552, *A catechism of Christian doctrine, no. 2: for confirmation
classes*. The accepted TEI preserves all 3,675 physical source lines, including
the provider header, title and approval statements, transcriber's note,
prayers, 421 question-and-answer groups, hymns, end markers, and the full
retained Project Gutenberg license. The question-and-answer index accompanies
the complete source transcription; it does not replace it.

The retained provider header lists J. De Concilio and Saint Roberto Francesco
Romolo Bellarmino as authors, Catholic Church. Plenary Council of Baltimore as
creator, and Dennis McCarthy as electronic producer. The title states that the
catechism was prepared and enjoined by order of the Third Plenary Council of
Baltimore. A closing marker calls the work "by Anonymous"; that marker remains
source context and does not override the distinct provider credits. No
translator or print publisher is inferred.

The electronic source lists a January 1, 2005 release and an October 28, 2024
update. Its New York and Baltimore approval statements are dated April 6,
1885; these do not establish the exact print exemplar behind this electronic
transcription. The transcriber's note says the four-volume e-text substantially
uses files supplied by catholic.net, with missing material added. A 1977
printing note appears in the answer text. These statements remain distinct
from the modern electronic witness. Historical print identity, human text
review, exhaustive collation, rights clearance, and public publication
authorization are unresolved.

The retained wrapper directs reuse under its included or online Project
Gutenberg License and tells users outside the United States to check local
law. Preserve this source credit and the full retained license when
distributing Gutenberg-branded material. This private release makes no claim
of public distribution compliance or independent rights clearance. The legal
text below comes from this exact retained member; it was not fetched or
copied from a different work.

Source reference: https://www.gutenberg.org/ebooks/14552 .

"""
SOURCE_END = """The original text is retained at `raw/gutenberg/pg14552.txt`, SHA-256
`3d4b556fdb094ab8e22a53df85f60ba3310b49c9c65a24281aeecb9119f9746c`.
Carry the full public source/use notice at
`data/catechisms/baltimore-catechism-no-2/README.md` with generated data for
this edition.

"""
PUBLIC_END = """This source/use notice must accompany generated data for this edition.

"""
LICENSE_HEADING = """## Full retained Project Gutenberg license and closing provider information

"""


def main() -> None:
    source = SOURCE.read_bytes()
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA or len(source) != 138043:
        raise ValueError("Retained Baltimore No. 2 source bytes changed")
    if source.count(LICENSE_START) != 1 or source.count(b"START: FULL LICENSE") != 1:
        raise ValueError("Exact retained license boundary is ambiguous")
    license_text = source[source.index(LICENSE_START) :].replace(b"\r\n", b"\n").rstrip(b"\n") + b"\n"
    if b"THE FULL PROJECT GUTENBERG" not in license_text:
        raise ValueError("Full retained license is absent")
    for path, ending in ((SOURCE_NOTICE, SOURCE_END), (DATA_NOTICE, PUBLIC_END)):
        content = (COMMON_INTRO + ending + LICENSE_HEADING).encode("utf-8") + license_text
        content.decode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != content and hashlib.sha256(path.read_bytes()).hexdigest() != PREVIOUS_SHA:
                raise ValueError(f"Existing Baltimore No. 2 notice differs: {path}")
            if path.read_bytes() != content:
                path.write_bytes(content)
        else:
            path.write_bytes(content)
        print(path.relative_to(ROOT).as_posix(), hashlib.sha256(content).hexdigest())


if __name__ == "__main__":
    main()
