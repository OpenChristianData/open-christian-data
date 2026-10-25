"""Verify an actual-master projection and one-work private offline release."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path

from build.tools.stage_basil_holy_spirit import ROOT, WORK, EDITION
from build.tools.prepare_basil_holy_spirit import canonical
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
    notice_path = Path("data/structured-text/basil-of-caesarea-on-the-holy-spirit/README.md")
    source_notice_path = Path("sources/structured-text/basil-of-caesarea-on-the-holy-spirit/README.source.md")
    notice = ("# Basil of Caesarea: On the Holy Spirit\n\n"
              "Complete English electronic On the Holy Spirit, including its preface and thirty chapters, in NPNF2-08. Basil: Letters and Select Works; sourced via CCEL.org. "
              "Source: [CCEL NPNF208](https://www.ccel.org/ccel/schaff/npnf208.html). "
              "The retained print-source statement reads Edinburgh: T&T Clark, 1895; this preparation does not establish print equivalence.\n\n"
              "The volume title pages and preface credit Blomfield Jackson, Philip Schaff, and Henry Wace. "
              "These retained contributor statements remain volume-scoped; no stronger child-work allocation is inferred. "
              "The electronic header labels the text Public Domain and Carefully proofed. Source readings, including native reference-parser anomalies, remain preserved. "
              "Native passage and parsed reference annotations remain exact; reference parsing and versification are not independently corrected or established.\n\n"
              "CCEL permission evidence permits parsing, reserves rights in CCEL files and formatting, and restricts selling those files or derivatives of their formatting. "
              "See [CCEL copyright policy](https://ccel.org/about/copyright.html). "
              "This private offline preparation does not establish rights clearance or authorize publication.\n\n"
              "Native structured content retains the complete work, notes, languages, page markers, and reference annotations in source order. "
              "The convenience text field omits notes. Human verification, visual comparison, and print collation remain unresolved.\n").encode()
    source_notice = ("# On the Holy Spirit source notice and data-path attribution\n\n"
                     "Exact retained authority: `raw/ccel/npnf2/npnf208.xml`, SHA-256 `95cf3dafefccec80e0949a03c7f1f605da293302d0dc7a8bd62a4e711a0c5532`; complete child `/ThML/ThML.body/div1[7]`, ID `vii`. "
                     "The acquired sidecar binds the entire volume; the readable reconstruction represents only this complete child work.\n\n"
                     "Carry human-visible source credit, source-level contributor scope, electronic-edition limitations and retained CCEL usage conditions to `data/structured-text/basil-of-caesarea-on-the-holy-spirit/README.md`. "
                     "Include sourced via CCEL.org. The full bound reconstruction notice remains at sources/manifest-acquisitions/basil-holy-spirit-npnf208/README.source.md. "
                     "Human review, print equivalence, rights clearance and publication are separate.\n").encode()
    source_target = ROOT/source_notice_path
    source_target.parent.mkdir(parents=True,exist_ok=True)
    if source_target.exists() and source_target.read_bytes() != source_notice:
        raise ValueError("canonical source notice differs")
    source_target.write_bytes(source_notice)
    notice_target = ROOT/notice_path
    notice_target.parent.mkdir(parents=True,exist_ok=True)
    if notice_target.exists() and notice_target.read_bytes() != notice:
        original_notice = (ROOT/"sources/manifest-acquisitions/basil-holy-spirit-npnf208/README.source.md").read_bytes()
        if notice_target.read_bytes() != original_notice:
            raise ValueError("existing data notice is not the known failed-generation notice")
    notice_target.write_bytes(notice)
    publication = ROOT/WORK/"publication/private-offline-20261001"
    publication.mkdir(parents=True,exist_ok=True)
    if (publication/"completion.json").exists():
        raise ValueError("completed publication evidence already exists")
    selection = dict(schema_version="2.0",release_id="basil-holy-spirit-npnf208-private-offline-20261001-v1",items=[
        dict(item_id="basil-holy-spirit-npnf208",category="prose",acceptance_path=(EDITION/"acceptance.json").as_posix(),
             public_notices=[dict(source_path=source_notice_path.as_posix(),source_sha256=sha256(source_notice).hexdigest(),notice_path=notice_path.as_posix(),notice_sha256=sha256(notice).hexdigest())])])
    (publication/"selection.json").write_bytes(canonical(selection))
    args.output.mkdir(parents=True)
    (args.output/"selection.json").write_bytes(canonical(selection))
    root = io_path(ROOT)
    release = args.output/"release"
    schema_paths = ["schemas/v2/native-content.schema.json","schemas/v2/categories/prose.schema.json","schemas/v2/public-row.schema.json","ocd_kernel/tei/vendor/xsd/tei_all.xsd"]
    schemas_before = {path:sha256((ROOT/path).read_bytes()).hexdigest() for path in schema_paths}
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
    result = dict(status="pass",work_id="basil-of-caesarea-on-the-holy-spirit",source_sha256="95cf3dafefccec80e0949a03c7f1f605da293302d0dc7a8bd62a4e711a0c5532",master_sha256=sha256(master).hexdigest(),
                  acceptance_sha256=sha256(io_path(acceptance).read_bytes()).hexdigest(),projection_rows=len(projected["rows"]),release_statistics=statistics,
                  release_path=release.as_posix(),notice_sha256=sha256(notice).hexdigest(),selection_sha256=sha256(canonical(selection)).hexdigest(),
                  private_offline=True,publication_performed=False,limits=["human verification not recorded","visual comparison not performed","print equivalence not established","rights clearance unresolved","global selection and publication not authorized"])
    schemas_after = {path:sha256((ROOT/path).read_bytes()).hexdigest() for path in schema_paths}
    if schemas_after != schemas_before:
        raise ValueError("bound schemas changed during final verification")
    result["bound_schema_stability"] = dict(status="pass",before=schemas_before,after=schemas_after)
    (args.output/"completion.json").write_bytes(canonical(result))
    (publication/"completion.json").write_bytes(canonical(result))
    (publication/"README.md").write_text("# Basil On the Holy Spirit private offline verification\n\nTechnical source-bound acceptance and guarded installation are complete. The exact installed master projects to one complete source-defined work, including its preface and thirty chapters. Its private offline release passed assembly, independent verification, statistics, and normal/streaming readers.\n\nEvidence: " + args.output.as_posix() + ". See completion.json for exact hashes and selection.json for the one-work release and source/data notices.\n\nHuman verification, visual comparison, print equivalence, jurisdictional rights clearance, global release selection, and publication remain separate and unresolved. No publication was performed.\n",encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
