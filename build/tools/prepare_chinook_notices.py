"""Deliver source-bound PG33105 credits and the complete retained provider license."""
from __future__ import annotations
import json
from pathlib import Path
from lxml import html
from build.tools.prepare_chinook_current import ROOT, LOG, WID, digest, save

SOURCE_NOTICE = Path("sources/publication-chinook") / WID / "README.source.md"
DATA_NOTICE = Path("data/hymns") / WID / "README.md"

def main() -> None:
    retained = ROOT / "raw/gutenberg/33105/html/pg33105-images.html"
    if digest(retained.read_bytes()) != "a56254c11f6ed220052501248fcca2fb84b37239cadb6168ccd37e6f3526d60f":
        raise ValueError("Retained PG33105 HTML changed")
    tree = html.fromstring(retained.read_bytes())
    footer = tree.xpath('//*[@id="pg-footer"]')
    if len(footer) != 1:
        raise ValueError("Provider footer not unique")
    # All source footer text is delivered in source order. Whitespace alone is collapsed.
    paragraphs = list(footer[0])
    license_text = "\n\n".join(" ".join("".join(node.itertext()).split()) for node in paragraphs)
    if " ".join(license_text.split()) != " ".join("".join(footer[0].itertext()).split()):
        raise ValueError("Delivered provider footer text differs from complete retained text")
    if "FULL PROJECT GUTENBERG" not in license_text or "Section 5." not in license_text:
        raise ValueError("Complete provider-license boundaries absent")
    notice = f"""# Hymns in the Chinook Jargon Language: source and use notice

This folder accompanies a private offline preparation of 20 numbered hymn occurrences, each with its source English translation in a separate section. The complete retained electronic work is preserved in the internal master. This is an agent technical result; human acceptance, print collation, independent rights clearance and public publication are not recorded.

The source title page says **Hymns in the Chinook Jargon Language**, **Compiled by Rev. M. Eells**, **Second Edition. Revised and Enlarged.**, Portland, Oregon, David Steel, successor to Himes the Printer, **1889**. It preserves the source's 1878 and 1889 copyright-entry statement naming Geo. H. Himes. The provider header separately lists Myron Eells as Author; the project credits the title-page compiler role without assigning authorship to every lyric or expanding the initials.

The electronic witness is [Project Gutenberg eBook 33105](https://www.gutenberg.org/ebooks/33105), released July 7, 2010. Its source credit reads: Produced by Stephen Hutcheson and the Online Distributed Proofreading Team at http://www.pgdp.net (This file was produced from images generously made available by The Internet Archive/Canadian Libraries). The 2010 electronic release and 1889 printed title-page date are distinct; no page-image collation is asserted.

Source orthography, repetition directions, literal chorus cues and tune labels are preserved. Stanza-number labels are represented by numeric stanza fields, and source paragraph whitespace is collapsed in the derived rows. Each row keeps original and TRANSLATION. sections distinct. The source describes No. 20 as a medley in four languages and includes a permission statement for material from Ten Years at Skokomish; those statements remain in the full master. The edition and row language code mul means multiple languages under the [Library of Congress ISO 639-2 list](https://www.loc.gov/standards/iso639-2/php/code_list.php). It reflects the source-attested paired Chinook Jargon and English material and multilingual medley without assigning inferred language codes to individual lines.

This bounded hymn selection excludes title/prefatory matter, provider header/footer/license, page-formatting carriers, hymn-information paragraphs outside verses, and the two closing prayers (the Lord's Prayer and a blessing before meals) with their 142 two-row interlinear tables. All remain in the complete internal master. The unreferenced retained cover is support. The archive contains no scanned page images. No sibling Ojibway collection is included.

Project Gutenberg's notice qualifies use under United States law and directs users elsewhere to check their local law. The retained provider terms follow in full, with whitespace normalized for readability. No worldwide clearance, license for separately identified music, or public-release decision is implied.

## Complete retained provider footer and license

{license_text}
"""
    if "<" in notice or ">" in notice:
        raise ValueError("Unexpected HTML or angle syntax in plain notice")
    source_note = f"""# PG33105 source attribution and release direction

The source is the already-retained Project Gutenberg eBook 33105 complete digital HTML witness. Its compiler, title-page, electronic transcription credits, source-language qualifications and provider footer/terms are delivered to the downloader-visible `{DATA_NOTICE.as_posix()}`.

The notice is paired specifically with the 20-row hymn/translation selection; all excluded matter is still represented in the complete technically accepted master. No new source was acquired. Human acceptance, print collation, independent rights clearance and public publication remain separate and unresolved.
"""
    for relative, text in ((SOURCE_NOTICE,source_note),(DATA_NOTICE,notice)):
        destination = ROOT / relative
        if destination.exists() and destination.read_bytes() != text.encode():
            prior = LOG / "notice-history" / (relative.parts[0] + "-" + digest(destination.read_bytes())[:16] + ".md")
            if not prior.exists():
                save(prior,destination.read_bytes())
        save(destination,text.encode())
    save(LOG / "notice-binding.json",dict(source_path=SOURCE_NOTICE.as_posix(), source_sha256=digest((ROOT/SOURCE_NOTICE).read_bytes()),
        notice_path=DATA_NOTICE.as_posix(), notice_sha256=digest((ROOT/DATA_NOTICE).read_bytes()),
        retained_footer_word_count=len("".join(footer[0].itertext()).split()), delivered_footer_word_count=len(license_text.split()),
        license_disposition="All direct-footer-child text, including headings and nested lists, in original source order. Display whitespace normalized."))
    print(json.dumps({"source":str(ROOT/SOURCE_NOTICE),"notice":str(ROOT/DATA_NOTICE)}))

if __name__ == "__main__":
    main()
