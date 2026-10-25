"""Bind reused full BSB native body and source-grounded publication scaffolds."""
import json
from pathlib import Path
from hashlib import sha256
from lxml import etree
from build.tei import bsb_current_reconstruction as producer, bsb_current_oracle as checker
from ocd_kernel.library._common import io_path

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "bsb"
FORM_ID = "bsb-english"
EDITION_ID = "bsb-retained-electronic-witness"
ACQUISITION_ID = "bsb-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
BASE = Path("sources/bible-bsb-current/bsb")
SOURCE = Path("raw/bible_databases/formats/json/BSB.json")
SOURCE_SHA = "73ca9ea1e36041bbbbd077738b250e266192669819117326516f871804872dac"
TITLE = "Berean Standard Bible"
LOG = Path("reports/_logs/bsb-current-reconciliation-20261002-v1")
BASELINE = LOG / "source-derived-historical-native"
DATA_NOTICE = Path("data/bible/bsb/README.md")
SCOPE = "Complete acquired scrollmapper/bible_databases BSB JSON electronic witness: all 66 ordered books, 1,189 chapters and 31,102 source verse records, including 16 exact empty strings, in one existing work and one TEI. Literal strings, Unicode, leading/trailing whitespace, numbers, original IDs, ordering and attachments are conserved. Reversible generated scaffolds change only 66 book n ordinals to their literal source names, mark all 31,102 strings with xml:space=preserve, remove generated text@type=bible, and renew the qualified header. Independent inversion restores exact historical native d2382c bytes. Separate spreadsheet/repository CC0 and credit metadata is permission/comparison support, not the acquired JSON textual source or a confirmed print equivalence. Human acceptance, underlying rights assessment and public publication remain separate."
canonical = producer.canonical


def put(path, content):
    physical = io_path(ROOT / path)
    physical.parent.mkdir(parents=True, exist_ok=True)
    physical.write_bytes(content)


def binding(name, path, role):
    content = io_path(ROOT / path).read_bytes()
    return dict(name=name, path=Path(path).as_posix(), role=role, bytes=len(content), sha256=sha256(content).hexdigest())


def main():
    source = json.loads(io_path(ROOT / SOURCE).read_bytes())
    baseline = io_path(ROOT / BASELINE / "content.tei.xml").read_bytes()
    if sha256(baseline).hexdigest() != "d2382c393edf36488497e1865c2bd155a00c515103219b2fb5d4cd6491d5b511" or sha256(io_path(ROOT / SOURCE).read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError("Exact source/reused historical native preimage differs")
    ns = "{http://www.tei-c.org/ns/1.0}"
    header = etree.Element(ns + "teiHeader", nsmap={None: ns[1:-1]})
    desc = etree.SubElement(header, ns + "fileDesc")
    titles = etree.SubElement(desc, ns + "titleStmt")
    etree.SubElement(titles, ns + "title").text = TITLE
    publication = etree.SubElement(desc, ns + "publicationStmt")
    etree.SubElement(publication, ns + "p").text = "Private retained electronic witness preparation; human textual acceptance, print equivalence, exact-witness rights and publication remain separate."
    source_desc = etree.SubElement(desc, ns + "sourceDesc")
    bibl = etree.SubElement(source_desc, ns + "bibl", {"type": "retained-json-witness", "{http://www.w3.org/XML/1998/namespace}id": "bsb-retained-source"})
    etree.SubElement(bibl, ns + "title", {"type": "translation-marker"}).text = source["translation"]
    etree.SubElement(bibl, ns + "note", {"type": "translation-marker", "{http://www.w3.org/XML/1998/namespace}id": "bsb-translation"}).text = source["translation"]
    etree.SubElement(bibl, ns + "idno", {"type": "sha256"}).text = SOURCE_SHA
    for kind, value in [
        ("retained-source-scope", SCOPE),
        ("credit-scope", "The acquired JSON has no named translators, editors, publisher, imprint or copyright fields. Separate retained openbible-io BSB metadata names BSB Publishing and lists advisors and extended translation notes; these are not silently allocated to the exact JSON witness. Config 2020 and April 2023 claims remain historical metadata support, not a freshly confirmed print or dedication date."),
        ("permission-evidence", "Separate retained openbible-io/bsb metadata associates Berean Standard Bible with CC0-1.0; its full CC0 1.0 Universal legal text is retained and visibly reproduced. The scrollmapper repository MIT software permission is retained separately. These observations do not assert verified byte equivalence to its spreadsheet, legal clearance for the exact JSON witness, or publication authorization."),
        ("generated-scaffolds", "Original generated text role bible is declared here rather than retained as an unsupported text attribute. All source string carriers receive explicit xml:space=preserve, including 16 true-empty strings; no filling, trimming or verse omission."),
    ]:
        etree.SubElement(bibl, ns + "note", {"type": kind}).text = value
    header_xml = etree.tostring(header, encoding="utf-8").decode()
    questions = [dict(id="bsb-" + name, kind=name, status="unassessed", detail=value) for name, value in [
        ("human", "Human textual/visual acceptance not recorded."), ("print", "Specific JSON print edition/date and spreadsheet equivalence not collated."),
        ("credits", "Separate retained metadata roles are visibly qualified; no named contributor allocation to JSON inferred."),
        ("rights", "CC0 and MIT permission evidence is visible; independent exact-witness rights clearance remains unassessed."),
        ("publication", "No public publication performed or authorized.")]]
    profile = dict(work_id=WORK_ID, scope=SCOPE, source_sha256=SOURCE_SHA, header_xml=header_xml, questions=questions,
                   book_label_revisions=[dict(source_pointer=f"/books/{i - 1}/name", old_n=str(i), source_name=b["name"], id=f"bsb-book-{i:02d}") for i, b in enumerate(source["books"], 1)],
                   whitespace_preserve_markers=31102, generated_text_role=dict(old="bible", new=None), source_empty_slots=16)
    put(BASE / "header.xml", header_xml.encode())
    put(BASE / "profile.json", canonical(profile))
    put(BASE / "validation-policy.json", canonical(dict(scope=SCOPE, declared_changes=profile["generated_text_role"], checks=["full independent original source/native/ledger proof", "direct source strings and 16 empty leaf identities", "66 source-backed routing labels", "all31102 whitespace markers", "exact inverse to historical native d2382c bytes", "new qualified header and exact namespace", "current P5 and fresh package replay"])))
    mit = io_path(ROOT / "raw/bible_databases/LICENSE").read_text(encoding="utf-8").strip()
    cc0 = io_path(ROOT / "raw/bsb/LICENSE.md").read_text(encoding="utf-8").strip()
    notice = f'''# Berean Standard Bible: complete retained JSON witness

Text provider: scrollmapper/bible_databases. The acquired literal marker is **BSB: Berean Standard Bible**. All 66 ordered books, 1,189 chapters and 31,102 source verse records are included, with 16 true-empty strings retained as empty verse slots. All literal leading/trailing spaces, wording, Unicode, numeric labels, IDs and order are conserved. Empty strings are not guessed, filled, omitted or interpreted as new editorial decisions. Only generated routing labels and explicit whitespace-preservation scaffolds are renewed.

The acquired JSON does not name translators, editors, publisher, print edition/date or rights holders. Separate retained openbible-io/bsb metadata associates Berean Standard Bible with **CC0-1.0** and names **BSB Publishing**. It lists **Gary Hill, Grant R. Osborne, Eugene H. Merrill, Maury Robertson, Ulrik Sandborg-Petersen and Baruch Korman** as **Advisor**, and **Gleason Archer** for **Extended translation notes**. These are precisely attributed observations of that separate metadata, not newly verified allocations to this JSON witness. Its preface names the Berean Bible Translation Committee and describes freely shareable resources. No individual role or print equivalence is inferred. The old local 2020/April 2023 claims remain historical support rather than newly confirmed source dates.

The full retained CC0 legal text below belongs to the separate openbible-io BSB repository; its metadata explicitly declares that license. The separately retained scrollmapper MIT software notice follows. Neither is silently expanded into a verified rights decision for every transformation or a claim that the spreadsheet and JSON are identical. Human acceptance, print collation, exact-witness rights review and public publication remain separate from private technical preparation.

## Retained openbible-io/bsb CC0 legal text

```text
{cc0}
```

## Retained scrollmapper software permission

```text
{mit}
```

For data at `data/bible/bsb`, maintain this notice at `data/bible/bsb/README.md` and in the release README containing these rows.
'''
    put(BASE / "README.source.md", notice.encode())
    put(DATA_NOTICE, notice.encode())
    old = json.loads((ROOT / "sources/bible-text/bsb/bsb.source-manifest.json").read_bytes())
    authorities = [binding(a["name"], a["path"], a["role"]) for a in old["authorities"]]
    extras = [("profile", BASE / "profile.json", "current-complete-source-scaffold-profile"), ("current-validation-policy", BASE / "validation-policy.json", "current-independent-scaffold-policy"),
              ("source-readme", BASE / "README.source.md", "current-visible-source-data-permission"), ("canonical-acquisition", ACQUISITION, "retained-source-identity"),
              ("historical-native-baseline", BASELINE / "content.tei.xml", "exact-recorded-historical-native-body"), ("historical-accountability", BASELINE / "source-accountability.json", "full-independent-source-ledger"),
              ("baseline-validation", BASELINE / "validation.json", "current-independent-baseline-proof"), ("historical-manifest", "sources/bible-text/bsb/bsb.source-manifest.json", "unaltered-historical-binding"),
              ("prior-producer", "build/tei/bsb_reconstruction.py", "unchanged-historical-source-producer"), ("prior-checker", "build/tei/bsb_oracle.py", "unchanged-independent-source-checker"),
              ("mit-permission", "raw/bible_databases/LICENSE", "retained-software-permission"), ("cc0-permission", "raw/bsb/LICENSE.md", "separate-retained-cc0-permission"),
              ("cc0-metadata", "raw/bsb/src/index.ts", "separate-retained-cc0-role-metadata"), ("preface-metadata", "raw/bsb/src/frt.ts", "separate-retained-preface-support"),
              ("reconciliation-preflight", LOG / "preflight.json", "source-and-prior-evidence-reconciliation")]
    authorities += [binding(*args) for args in extras]
    record = {k: v for k, v in old.items() if k not in ("authorities", "converter", "validator")}
    record.update(textual_form_id=FORM_ID, edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID, authorities=authorities,
                  converter=dict(id=producer.CONVERTER_ID, version="1", callable="_convert", implementation_path="build/tei/bsb_current_reconstruction.py", implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
                  validator=dict(id=checker.ORACLE_ID, version="1", callable="_oracle", implementation_path="build/tei/bsb_current_oracle.py", implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(), import_closure_sha256=checker.closure_sha(ROOT)))
    put(BASE / "source-manifest.json", canonical(record))
    print(json.dumps(dict(status="prepared", baseline_sha256=sha256(baseline).hexdigest(), source_sha256=SOURCE_SHA, source_empty_slots=16)))


if __name__ == "__main__":
    main()
