"""Inventory the already retained Nancy Prince electronic edition; no acquisition."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import html
from build.tei import nancy_prince_pg63579_reconstruction as producer
from build.tei import nancy_prince_pg63579_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT = Path(__file__).resolve().parents[2]
BASE = Path("sources/manifest-acquisitions/nancy-prince-pg63579")
WORK_ID = "nancy-prince-narrative-life-travels"


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def put(relative: Path, content: bytes) -> None:
    target = io_path(ROOT / relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def binding(name: str, path: str | Path, role: str) -> dict:
    raw = io_path(ROOT / path).read_bytes()
    return dict(name=name, path=Path(path).as_posix(), role=role, bytes=len(raw), sha256=sha256(raw).hexdigest())


def main() -> None:
    roster = json.loads((ROOT / "plans/2026-09-22-source-preflight/whole-library-handoff-inventory-20260926.json").read_bytes())
    if not any(work["work_id"] == WORK_ID for work in roster["works"]):
        raise ValueError("Nancy Prince is outside the fixed roster")
    raw = (ROOT / producer.SOURCE).read_bytes()
    if sha256(raw).hexdigest() != producer.SOURCE_SHA:
        raise ValueError("retained source differs")
    doc = html.document_fromstring(raw)
    body = doc.find("body")
    archive = "raw/gutenberg/63579/pg63579-h.zip"
    members = []
    authorities = []
    with ZipFile(ROOT / archive) as package:
        if package.testzip() is not None:
            raise ValueError("retained ZIP CRC mismatch")
        for info in package.infolist():
            payload = package.read(info.filename)
            path = "raw/gutenberg/63579/html/" + info.filename
            if (ROOT / path).read_bytes() != payload:
                raise ValueError("extracted source member differs: " + path)
            role = "primary-text" if info.filename.endswith(".html") else "unreferenced-support" if info.filename == "images/cover.jpg" else "referenced-body-image"
            authority = "retained-source" if role == "primary-text" else "retained-" + Path(info.filename).stem
            members.append(dict(path=info.filename, bytes=len(payload), crc32=f"{info.CRC:08x}", sha256=sha256(payload).hexdigest(), extracted_path=path, role=role, authority=authority))
            authorities.append(binding(authority, path, "primary-source" if role == "primary-text" else role))
    work = ROOT / "library/works" / WORK_ID
    acquisition_path = next(work.rglob("acquisitions/*.json"))
    acquisition = validate_acquisition(io_path(acquisition_path), root=ROOT)
    if acquisition["source_path"] != producer.SOURCE or acquisition["source_sha256"] != producer.SOURCE_SHA:
        raise ValueError("canonical acquisition is not bound to extracted HTML")
    notice = ("# Nancy Prince: retained electronic source notice\n\n"
              "A Narrative of the Life and Travels of Mrs. Nancy Prince. The retained title page names Nancy Prince as author and publisher, Boston, 1850. "
              "Source: Project Gutenberg ebook 63579, https://www.gutenberg.org/ebooks/63579. "
              "The reconstruction represents this retained electronic edition; it does not establish print equivalence.\n\n"
              "The transcriber states that obvious typographic errors were corrected. Those source readings are preserved without further correction. "
              "The complete narrative and appended Divine Contentment remain components of this one book. "
              "Both linked illustrations remain in the TEI; the unlinked cover is retained as support.\n\n"
              "Technical agent acceptance is separate from human review, jurisdictional rights clearance, and publication authorization. "
              "This private offline preparation does not authorize publication. The exact retained provider header and full license follow, including source-supplied contact details.\n\n"
              "## Retained Project Gutenberg header\n\n" + "".join(body.find("header").itertext()).strip() +
              "\n\n## Retained Project Gutenberg footer and license\n\n" + "".join(body.find("footer").itertext()).strip() + "\n")
    put(BASE / "README.source.md", notice.encode())
    profile = dict(contract="ocd-nancy-prince-pg63579-profile-v1", work_id=WORK_ID,
                   scope="Complete HTML body, including provider envelope, narrative and appended Divine Contentment; one complete electronic volume, one TEI.",
                   source=dict(path=producer.SOURCE, sha256=producer.SOURCE_SHA, bytes=len(raw),
                               archive_path=archive, archive_sha256=sha256((ROOT / archive).read_bytes()).hexdigest(),
                               members=[{k:v for k,v in member.items() if k != "authority"} for member in members],
                               body_children=len(body), body_descendants=len(list(body.iterdescendants())),
                               tag_counts=dict(Counter(n.tag for n in body.iterdescendants())),
                               headings=[dict(tag=n.tag, text="".join(n.itertext()), id=n.get("id")) for n in body.iterdescendants() if n.tag in {"h1","h2","h3"}],
                               carriers=[dict(position=i, tag=n.tag, attributes=dict(n.attrib), text_sha256=sha256("".join(n.itertext()).encode()).hexdigest()) for i,n in enumerate(body,1)],
                               poem_groups=len(body.xpath(".//div[contains(concat(' ', @class, ' '), ' poem ')]")),
                               stanzas=len(body.xpath(".//div[@class='stanza']")),
                               footnotes=len(body.xpath(".//div[@class='footnote']")), contents_rows=len(body.xpath(".//table//tr"))),
                   boundary_basis="The title page identifies one retained 1850 Nancy Prince volume. The 14 contents rows concern the narrative; they do not list Divine Contentment. After narrative material on printed page 81 and a rule, a separate Divine Contentment heading begins on page 82 and continues within the retained body before the provider footer. Complete retained-volume continuity and the declared acquisition envelope support keeping this appended devotional component in the same complete-volume TEI; no contents or explicit appendix label is claimed.",
                   mapping="The 547 body descendants have 546 readable TEI carriers; tbody alone is explicitly flattened. Block wrapper div/ab preserve mixed text and tails. Poems map to lg, stanzas to nested lg, lines to l, footnote to note. Graphic URLs retain the exact source-relative src; graphic@n retains exact source alt/width/height annotations. Local anchors and links remain exact.",
                   exclusions=["HTML head is bound metadata and styling support outside the readable body; no body content excluded.","Unlinked cover image is bound support, not invented body content."],
                   independence="Checker has separate mapping and traversal; HTMLParser corroborates lexical source tag census; ZIP extraction equality independently binds all source/support members. Both implementations use lxml for source tree; this shared parser assumption is disclosed.",
                   unassessed=["whole-work visual review","human verification","print collation","rights clearance","publication"])
    put(BASE / "profile.json", canonical(profile))
    policy = dict(contract="ocd-nancy-prince-pg63579-validation-policy-v1", checks=["exact extracted HTML binding and complete ZIP members", "independent lexical/source-tree census", "complete readable text and ordered IDs/tags/hierarchy", "poem/stanza/line and footnote roles", "local anchor/link and figure/caption closure", "P5 schema", "independent source-accountability crosswalk", "fresh process byte-identical replay", "feature mutations rejected"], scope=profile["scope"], independence=profile["independence"])
    put(BASE / "validation-policy.json", canonical(policy))
    for name,path,role in [
        ("retained-package",archive,"supporting-package"),
        ("reconstruction-profile",BASE/"profile.json","complete-source-feature-profile"),
        ("validation-policy",BASE/"validation-policy.json","independent-validation-policy"),
        ("source-readme",BASE/"README.source.md","source-attribution-readme"),
        ("tei-p5-xsd","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),
        ("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema"),
        ("producer-implementation",Path(producer.__file__).relative_to(ROOT),"supporting-converter-implementation"),
        ("oracle-implementation",Path(checker.__file__).relative_to(ROOT),"supporting-validator-implementation"),
        ("reproduction-runner","build/tei/run_nancy_prince_pg63579.py","fresh-process-reproduction-runner"),
        ("canonical-acquisition",acquisition_path.relative_to(ROOT),"canonical-acquisition-evidence")]:
        authorities.append(binding(name,path,role))
    primary = authorities[0]
    manifest = dict(contract="ocd-source-manifest-v1", source_id="nancy-prince-pg63579-complete-html-v1", work_id=WORK_ID,
                    textual_form_id="nancy-prince-narrative-life-travels-gutenberg-retained", edition_id="nancy-prince-narrative-life-travels-gutenberg-electronic", acquisition_id=acquisition["acquisition_id"],
                    authorities=authorities, archive_members=members, archive_sha256=profile["source"]["archive_sha256"],
                    source_members=[dict(name="pg63579-images.html", logical_name="pg63579-images.html", path=producer.SOURCE, order=1, bytes=len(raw), sha256=producer.SOURCE_SHA)],
                    source_bundle=dict(bytes=len(raw), members=1, sha256=producer.SOURCE_SHA), scope=dict(kind="one-complete-html-member", title="A Narrative of the Life and Travels of Mrs. Nancy Prince"),
                    converter=dict(id=producer.CONVERTER_ID, version=producer.CONVERTER_VERSION, callable="_convert", implementation_path=Path(producer.__file__).relative_to(ROOT).as_posix(), implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
                    validator=dict(id=checker.ORACLE_ID, version=checker.ORACLE_VERSION, callable="_oracle", implementation_path=Path(checker.__file__).relative_to(ROOT).as_posix(), implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(), import_closure_sha256=checker._closure_sha()),
                    package_schema=dict(path="ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", sha256=sha256((ROOT/"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()).hexdigest()))
    put(BASE / "source-manifest.json", canonical(manifest))
    print(json.dumps(dict(status="prepared", work_id=WORK_ID, body_children=len(body), descendants=len(list(body.iterdescendants())), source_sha256=primary["sha256"])))


if __name__ == "__main__":
    main()
