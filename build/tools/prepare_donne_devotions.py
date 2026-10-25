"""Bind retained Donne source, existing literary mapping, and complete work scope."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path

from build.tei import donne_devotions_scoped as producer, donne_devotions_scoped_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "donne-devotions-upon-emergent-occasions"
FORM_ID = WORK_ID + "-retained-electronic"
EDITION_ID = WORK_ID + "-retained-electronic-witness"
ACQUISITION_ID = WORK_ID + "-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
BASE = Path("sources/donne-devotions-pg23772") / WORK_ID
HISTORICAL = Path("reports/_logs/donne-reconciliation-20261001-v1/historical-package/content.tei.xml")
SOURCE = Path("raw/gutenberg/pg23772.txt")
SOURCE_SHA = "f1f2b08f2dcfe9f6618bb8031a5d055b5d58e30f80a399ff866d5b205b1773b7"
HISTORICAL_SHA = "9be8461fd68186277563a70bcaf961691dd08cfa05fc2a78f8f8ab4ca3308740"
SCOPE = ("Complete Devotions Upon Emergent Occasions in retained Project Gutenberg eBook 23772: "
         "physical lines 1481–6490, including its title/imprint, dedication, station contents, "
         "all 23 stations with Meditation, Expostulation and Prayer, and all 346 footnotes. "
         "Shared volume metadata/credits/title/imprint/contents at lines 1–92 and the explicitly "
         "Izaak Walton-attributed biographical excerpt at lines 93–1480 are front context; "
         "the complete Gutenberg terminator/license at lines 7296–7647 is back context. "
         "The volume Contents lists the biographical excerpt at roman page v; it is not a complete "
         "independent Walton Life or Donne's original Devotions body. The independently titled "
         "Death's Duel sermon (6491–7295) remains retained but is excluded from this Devotions identity. "
         "No new work identities are created; no original source bytes are removed or corrected.")
TITLE = "Devotions Upon Emergent Occasions"
DATA_NOTICE = Path("data/prose") / WORK_ID / "README.md"
canonical = producer.canonical


def put(relative, value):
    path = io_path(ROOT / relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def binding(name, path, role):
    raw = io_path(ROOT / path).read_bytes()
    return dict(name=name, path=Path(path).as_posix(), role=role, bytes=len(raw), sha256=sha256(raw).hexdigest())


def main():
    acquisition = validate_acquisition(io_path(ROOT / ACQUISITION), root=ROOT)
    source = io_path(ROOT / SOURCE).read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA or acquisition["source_sha256"] != SOURCE_SHA:
        raise ValueError("retained Donne source/acquisition differs")
    if sha256(io_path(ROOT / HISTORICAL).read_bytes()).hexdigest() != HISTORICAL_SHA:
        raise ValueError("historical verified literary TEI differs")
    lines = source.decode("utf8").split("\r\n")
    dispositions = [dict(first=1, last=92, destination="TEI text/front shared volume context"),
        dict(first=93, last=1480, destination="TEI text/front attributed Walton biographical excerpt; shared volume context"),
        dict(first=1481, last=6490, destination="TEI text/body complete Devotions"),
        dict(first=6491, last=7295, destination="retained only; separate Death's Duel excluded from Devotions"),
        dict(first=7296, last=7647, destination="TEI text/back shared Gutenberg license")]
    ledger = [dict(position=i, sha256=sha256(line.encode()).hexdigest(),
        destination=next(r["destination"] for r in dispositions if r["first"] <= i <= r["last"]))
        for i, line in enumerate(lines, 1)]
    boundary = dict(status="resolved-retained-electronic-work", source_sha256=SOURCE_SHA,
        source_line_count=len(lines), dispositions=dispositions, complete_work=[1481, 6490],
        opening=lines[1480:1484], closing=lines[6485], preceding_closing=lines[1475],
        next_work_title=lines[6490], volume_contents=lines[83:88],
        cardinality="One complete Devotions work; its 23 stations and 69 movements are parts.",
        neighboring_works="Walton biography is explicitly an excerpt, listed at roman page v before Devotions page 1; preserve it as attributed shared front context, not an independent complete Life. Death's Duel starts page 161 and has its own title, delivery statement, reader preface and completed sermon; retain it outside Devotions.",
        superseded_narrow_disposition="The earlier exclusion of Walton's excerpt at 93–1480 is superseded by source Contents/frontmatter classification and root approval; narrow candidates/receipts remain historical.",
        original_declaration=acquisition["source_scope"], historical_package_retained=HISTORICAL.as_posix(),
        print_identity="Retained volume states Ann Arbor Paperback 1959, University of Michigan Press; reproduced Devotions imprint states London, A. M. for Thomas Iones, 1624. Physical-print equivalence unverified.",
        ledger=ledger)
    put(BASE / "boundary-review.json", canonical(boundary))
    accounting = dict(contract="ocd-donne-devotions-scoped-accountability-v1", work_id=WORK_ID,
        source_sha256=SOURCE_SHA, source_bytes=len(source), source_line_count=len(lines),
        represented_line_count=6842, devotions_line_count=5010, shared_front_line_count=1480,
        shared_back_line_count=352, excluded_other_work_line_count=805,
        omitted_unexplained_line_count=0, duplicate_line_count=0, invented_line_count=0,
        reordered_line_count=0, station_count=23, movement_count=69, footnote_count=346,
        dispositions=dispositions, full_envelope_accounted=True)
    questions = [dict(id=WORK_ID + "-" + kind, status="unresolved", kind=kind,
        detail="Technical electronic-witness acceptance does not establish " + detail)
        for kind, detail in [("visual-human", "current visual or human textual verification."),
                            ("print", "physical-print equivalence or a bibliographical edition identification beyond retained statements."),
                            ("rights", "jurisdictional rights clearance."), ("publication", "publication authorization.")]]
    profile = dict(work_id=WORK_ID, source_sha256=SOURCE_SHA, scope=SCOPE,
        encoding_statement="Every included physical line is represented exactly once in source order, with original coordinates, blank lines and indentation. The retained file uses CRLF and a BOM-bearing first line. Devotions is the body; shared volume context, including the explicitly attributed Walton biographical excerpt, and Gutenberg license are front/back. Death's Duel remains in the unchanged retained source and historical whole-volume candidate and is excluded from this Devotions identity. LIB-068 literary v2 structures, literal underscores, note links, paragraphs, verse/stanzas, illustration placeholders and embedded document roles are preserved without spelling correction.",
        accounting=accounting, questions=questions, excluded_works=[dispositions[3]])
    put(BASE / "profile.json", canonical(profile))
    put(BASE / "validation-policy.json", canonical(dict(contract="ocd-donne-devotions-scoped-policy-v1",
        scope=SCOPE, rules=["independent retained-text work-boundary/station/note census",
            "whole-source literary oracle on preserved and actual scoped sections",
            "exact line/indentation/blank/inline and attachment conservation", "P5", "local note closure",
            "no unexplained source-envelope omission", "meaningful mutations and exact fresh-process replay"])))
    notice = ("# Donne, Devotions Upon Emergent Occasions\n\n"
        "Source: the retained Project Gutenberg eBook 23772, *Devotions Upon Emergent Occasions; Together with Death's Duel*. "
        "[Project Gutenberg source](https://www.gutenberg.org/ebooks/23772). The retained file credits Stacy Brown, John Hagerson, Juliet Sutherland, and the Online Distributed Proofreading Team (http://www.pgdp.net). "
        "Its electronic header states release December 8, 2007 and latest update December 8, 2011. The volume states First edition as an Ann Arbor Paperback 1959, University of Michigan Press; the reproduced Devotions title/imprint states London, A. M. for Thomas Iones, 1624. These retained statements do not establish physical-print equivalence.\n\n"
        + SCOPE + "\n\nThe shared biographical introduction is explicitly an excerpt taken from Izaak Walton's Life of Donne and ends I.W.; its verse quotations, embedded documents and literal illustration placeholders remain source-owned context, with no invented image pixels. It is not a complete independent Life or Donne's original Devotions text. Shared volume contents and introduction do not transfer Walton authorship to Donne. Death's Duel remains unchanged in the retained source, outside this master.\n\n"
        "The original Project Gutenberg metadata, credits, complete license and territorial notice are preserved in the TEI. The retained notice says users outside the United States must check local law. Consult the complete [Project Gutenberg License](https://www.gutenberg.org/policy/license.html) before redistribution. No independent rights clearance or publication authorization is claimed.\n\n"
        "Carry this visible source/production/rights credit to `" + DATA_NOTICE.as_posix() + "`. Human textual/visual review and print collation remain separate.\n")
    put(BASE / "README.source.md", notice.encode())
    paths = [("retained-text", SOURCE, "primary-source"), ("historical-literary-tei", HISTORICAL, "checked-retained-literary-reconstruction"),
        ("historical-profile", "reports/_logs/donne-reconciliation-20261001-v2/before/sources/structured-text/" + WORK_ID + "/LIB-068.reconstruction-profile.json", "source-feature-profile"),
        ("historical-manifest", "reports/_logs/donne-reconciliation-20261001-v2/before/sources/structured-text/" + WORK_ID + "/LIB-068.source-manifest.json", "historical-mapping-binding"),
        ("profile", BASE / "profile.json", "complete-source-feature-profile"),
        ("validation-policy", BASE / "validation-policy.json", "independent-validation-policy"),
        ("boundary-review", BASE / "boundary-review.json", "whole-envelope-source-ledger"),
        ("source-readme", BASE / "README.source.md", "source-attribution"),
        ("canonical-acquisition", ACQUISITION, "retained-source-identity"),
        ("tei-p5-xsd", "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-validation-schema"),
        ("candidate-package-schema", "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "candidate-package-schema")]
    for name in ("lib068_source_local_oracle", "lib068_source_letters_oracle", "lib068_literary_blocks_oracle"):
        paths.append((name, "build/tei/" + name + ".py", "independent-legacy-literary-checker"))
    manifest = dict(contract="ocd-source-manifest-v1", source_id="donne-devotions-pg23772-scoped-v1",
        work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID,
        authorities=[binding(*p) for p in paths], scope=SCOPE,
        converter=dict(id=producer.CONVERTER_ID, version=producer.CONVERTER_VERSION, callable="_convert",
            implementation_path="build/tei/donne_devotions_scoped.py", implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
        validator=dict(id=checker.ORACLE_ID, version=checker.ORACLE_VERSION, callable="_oracle",
            implementation_path="build/tei/donne_devotions_scoped_oracle.py", implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(), import_closure_sha256=checker.closure_sha(ROOT)),
        package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
            sha256=sha256((ROOT / "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE / "source-manifest.json", canonical(manifest))
    print(json.dumps(dict(status="prepared", source_sha256=SOURCE_SHA, scope=SCOPE, full_source_lines=len(lines))))


if __name__ == "__main__":
    main()
