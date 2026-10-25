"""Verify an actual-master projection and one-work private offline release."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path

from build.tools.stage_predestination import ROOT, WORK, EDITION
from build.tools.prepare_predestination import canonical
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--master-sha256",required=True,help="Pin the guarded-installed representation being released")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("fresh release proof directory required")
    acceptance = ROOT/EDITION/"acceptance.json"
    master = io_path(ROOT/EDITION/"master.tei.xml").read_bytes()
    if sha256(master).hexdigest() != args.master_sha256:
        raise ValueError("installed master differs from staged pin")
    notice_path = Path("data/structured-text/augustine-predestination-of-saints/README.md")
    source_notice_path = Path("sources/structured-text/augustine-predestination-of-saints/README.source.md")
    notice = ("# On the Predestination of the Saints: source and data credits\n\n"
              "Sourced via [CCEL.org](https://www.ccel.org/ccel/schaff/npnf105.html), Nicene and Post-Nicene Fathers, Series 1, volume 5. "
              "The retained electronic source header states Public Domain and gives New York: Christian Literature Publishing Co., 1886. "
              "Robert Ernest Wallis translated both books according to the retained Edinburgh preface. Philip Schaff is volume editor; "
              "the volume credits Benjamin B. Warfield as translation reviser and introduction author. These statements do not establish print-edition equivalence.\n\n"
              "This preparation includes the entire source-defined two-book work: its title page, Book I with 43 chapters, "
              "and Book II, separately titled On the Gift of Perseverance, with its own title page, introduction and 68 chapters. "
              "The retained opening explicitly identifies it as the second book of On the Predestination of the Saints. "
              "The shared Contents says One Book; that discrepant reading is recorded as outside-work context without correcting the body or contents. "
              "Source notes, alternate-title discussion, references, page markers and native spelling are preserved. Shared volume matter and sibling works are excluded.\n\n"
              "Retained CCEL permission evidence permits parsing ThML; do not sell CCEL files or derivatives of CCEL formatting. "
              "The source header's Public Domain statement and this parsing permission are retained provider statements, "
              "not independent rights clearance. Human/visual review, print comparison, final rights disposition and public publication remain separate.\n").encode()
    source_notice = ("# Predestination two-book work: source credit direction\n\n"
                     "Complete retained CCEL NPNF1-05 two-book work, including On the Gift of Perseverance as source-defined Book II. "
                     "Preserve the native alternate-title discussion and record the outside contents-count discrepancy.\n\n"
                     "Carry CCEL source credit, Robert Ernest Wallis translator credit, volume editor/reviser attribution, "
                     "retained Public Domain statement and no-sale formatting restriction to "
                     "`data/structured-text/augustine-predestination-of-saints/README.md`. "
                     "Human review, print equivalence, rights and publication remain separate.\n").encode()
    source_target = ROOT/source_notice_path
    source_target.parent.mkdir(parents=True,exist_ok=True)
    if source_target.exists() and source_target.read_bytes() != source_notice:
        raise ValueError("canonical source notice differs")
    source_target.write_bytes(source_notice)
    notice_target = ROOT/notice_path
    notice_target.parent.mkdir(parents=True,exist_ok=True)
    if notice_target.exists() and notice_target.read_bytes() != notice:
        original_notice = (ROOT/"sources/manifest-acquisitions/predestination-npnf105/README.source.md").read_bytes()
        if notice_target.read_bytes() != original_notice:
            raise ValueError("existing data notice is not the known failed-generation notice")
    notice_target.write_bytes(notice)
    publication = ROOT/WORK/"publication/private-offline-20261001"
    publication.mkdir(parents=True,exist_ok=True)
    if (publication/"completion.json").exists():
        raise ValueError("completed publication evidence already exists")
    selection = dict(schema_version="2.0",release_id="predestination-npnf105-private-offline-20261001-v1",items=[
        dict(item_id="predestination-npnf105",category="prose",acceptance_path=(EDITION/"acceptance.json").as_posix(),
             public_notices=[dict(source_path=source_notice_path.as_posix(),source_sha256=sha256(source_notice).hexdigest(),notice_path=notice_path.as_posix(),notice_sha256=sha256(notice).hexdigest())])])
    (publication/"selection.json").write_bytes(canonical(selection))
    args.output.mkdir(parents=True)
    (args.output/"selection.json").write_bytes(canonical(selection))
    root = io_path(ROOT)
    release = args.output/"release"
    schema_paths = ["schemas/v2/native-content.schema.json","schemas/v2/categories/prose.schema.json","schemas/v2/public-row.schema.json","ocd_kernel/tei/vendor/xsd/tei_all.xsd"]
    schemas_before = {path:sha256((ROOT/path).read_bytes()).hexdigest() for path in schema_paths}
    implementation_paths = ['ocd_kernel/projection/categories/native_documents.py','ocd_kernel/release/assemble.py','ocd_kernel/release/verify.py']
    implementations_before = {path:sha256((ROOT/path).read_bytes()).hexdigest() for path in implementation_paths}
    with cached_edition_lookups():
        projected = project_accepted_document(root,acceptance_path=io_path(acceptance),category="prose")
        errors = verify_accepted_document(root,acceptance_path=io_path(acceptance),rows=projected["rows"],receipt=projected["receipt"],category="prose")
        if errors or len(projected["rows"]) != 1:
            raise ValueError(f"installed actual-master projection differs: {errors}")
        (args.output/"actual-master-projection.json").write_bytes(canonical(projected))
        print("actual-master projection: pass, 1 row",flush=True)
        assembled = assemble_release_v2(root,release,selection=selection)
        (args.output/"assembly.json").write_bytes(canonical(assembled))
        if assembled["status"] != "pass":
            raise ValueError(f"release assembly failed: {assembled}")
        verified = verify_release_v2(root,release,selection=selection)
        (args.output/"independent-verification.json").write_bytes(canonical(verified))
        if verified["status"] != "pass":
            raise ValueError(verified)
        print("release assembly and independent verification: pass",flush=True)
        statistics = release_statistics(root,release,selection)
        (args.output/"statistics.json").write_bytes(canonical(statistics))
        readers = check_reader(root,release,selection)
        (args.output/"readers.json").write_bytes(canonical(readers))
        if readers["status"] != "pass":
            raise ValueError(readers)
    result = dict(status="pass",work_id="augustine-predestination-of-saints",source_sha256="224f0e6a188ddfe691c1433c8db9a883755a9f030b71fede644d4af6c18ee63f",master_sha256=sha256(master).hexdigest(),
                  acceptance_sha256=sha256(io_path(acceptance).read_bytes()).hexdigest(),projection_rows=len(projected["rows"]),release_statistics=statistics,
                  release_path=release.as_posix(),notice_sha256=sha256(notice).hexdigest(),selection_sha256=sha256(canonical(selection)).hexdigest(),
                  private_offline=True,publication_performed=False,limits=["human verification not recorded","visual comparison not performed","print equivalence not established","rights clearance unresolved","global selection and publication not authorized"])
    schemas_after = {path:sha256((ROOT/path).read_bytes()).hexdigest() for path in schema_paths}
    if schemas_after != schemas_before:
        raise ValueError("bound schemas changed during final verification")
    result["bound_schema_stability"] = dict(status="pass",before=schemas_before,after=schemas_after)
    implementations_after = {path:sha256((ROOT/path).read_bytes()).hexdigest() for path in implementation_paths}
    if implementations_after != implementations_before:
        raise ValueError('projection/release implementation changed during final checks')
    result['bound_implementation_stability'] = dict(status='pass',before=implementations_before,after=implementations_after)
    (args.output/"completion.json").write_bytes(canonical(result))
    (publication/"completion.json").write_bytes(canonical(result))
    (publication/"README.md").write_text("# Predestination two-book work private offline verification\n\nTechnical source-bound acceptance and guarded installation are complete. The exact installed master projects to one complete source-defined work, including both books, their title matter, all 43 and 68 chapters, original comments/notes/references and pages; shared contents-count discrepancy accounted, siblings excluded. Its private offline release passed assembly, independent verification, statistics, and normal/streaming readers.\n\nEvidence: " + args.output.as_posix() + ". See completion.json for exact hashes and selection.json for the one-work release and source/data notices.\n\nHuman verification, visual comparison, print equivalence, jurisdictional rights clearance, global release selection, and publication remain separate and unresolved. No publication was performed.\n",encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
