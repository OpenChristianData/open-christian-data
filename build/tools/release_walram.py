"""Verify an actual-master projection and one-work private offline release."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path

from build.tools.stage_walram import ROOT, WORK, EDITION
from build.tools.prepare_walram import canonical
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
    notice_path = Path("data/structured-text/walram-of-naumburg-letter-to-ludewic/README.md")
    source_notice_path = Path("sources/structured-text/walram-of-naumburg-letter-to-ludewic/README.source.md")
    notice = ("# Walram of Naumburg, Letter to Count Ludewic\n\n"
              "Source: Monumenta Germaniae Historica (MGH) and Bavarian State Library, Munich (BSB), "
              "[openMGH electronic MGH Ldl 2](https://www.dmgh.de/mgh_ldl_2/index.htm). "
              "The retained volume bibliography credits Ernst Dümmler and gives Hannover: Hahn, 1892. "
              "These volume-level statements do not establish print equivalence or a stronger allocation to this child letter.\n\n"
              "The retained electronic header licenses the annotations added by MGH and BSB in the digital MGH project under "
              "[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/), "
              "and does not claim rights in the underlying text, which it believes to be public domain. "
              "Credit MGH and BSB when distributing a copy or derivative version. This preparation preserves that source credit and licensing statement; "
              "final rights disposition and publication authorization remain separate.\n\n"
              "This is the complete quoted Walram letter delimited by its salutation and closing in the electronic witness. "
              "Surrounding narrative and Count Ludewic's reply are separate and excluded. Native inline style, page and line markers, "
              "split-word annotations, and their exact mixed content are retained. Two native word segments have empty text; "
              "their lemma and links remain exact, with no guessed reading filled. Human verification, visual review and print collation remain unresolved.\n").encode()
    source_notice = ("# Walram letter source and data attribution\n\n"
                     "Retained source: Monumenta Germaniae Historica (MGH) and Bavarian State Library, Munich (BSB), "
                     "openMGH electronic MGH Ldl 2. The prepared work is the complete quoted Walram letter; surrounding narrative "
                     "and Count Ludewic's reply are excluded. Preserve exact native empty word segments without invented readings.\n\n"
                     "Carry human-visible MGH and BSB credit and the retained CC BY 4.0 annotation license and underlying-text disclaimer "
                     "to `data/structured-text/walram-of-naumburg-letter-to-ludewic/README.md`. "
                     "Human review, print equivalence, final rights disposition and publication remain separate.\n").encode()
    source_target = ROOT/source_notice_path
    source_target.parent.mkdir(parents=True,exist_ok=True)
    if source_target.exists() and source_target.read_bytes() != source_notice:
        raise ValueError("canonical source notice differs")
    source_target.write_bytes(source_notice)
    notice_target = ROOT/notice_path
    notice_target.parent.mkdir(parents=True,exist_ok=True)
    if notice_target.exists() and notice_target.read_bytes() != notice:
        original_notice = (ROOT/"sources/manifest-acquisitions/walram-bsb829/README.source.md").read_bytes()
        if notice_target.read_bytes() != original_notice:
            raise ValueError("existing data notice is not the known failed-generation notice")
    notice_target.write_bytes(notice)
    publication = ROOT/WORK/"publication/private-offline-20261001"
    publication.mkdir(parents=True,exist_ok=True)
    if (publication/"completion.json").exists():
        raise ValueError("completed publication evidence already exists")
    selection = dict(schema_version="2.0",release_id="walram-bsb829-private-offline-20261001-v1",items=[
        dict(item_id="walram-bsb829",category="prose",acceptance_path=(EDITION/"acceptance.json").as_posix(),
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
    result = dict(status="pass",work_id="walram-of-naumburg-letter-to-ludewic",source_sha256="cb35385e4e4ba87f80a002452a527527866322af7ccea7f23f366735e46df989",master_sha256=sha256(master).hexdigest(),
                  acceptance_sha256=sha256(io_path(acceptance).read_bytes()).hexdigest(),projection_rows=len(projected["rows"]),release_statistics=statistics,
                  release_path=release.as_posix(),notice_sha256=sha256(notice).hexdigest(),selection_sha256=sha256(canonical(selection)).hexdigest(),
                  private_offline=True,publication_performed=False,limits=["human verification not recorded","visual comparison not performed","print equivalence not established","rights clearance unresolved","global selection and publication not authorized"])
    schemas_after = {path:sha256((ROOT/path).read_bytes()).hexdigest() for path in schema_paths}
    if schemas_after != schemas_before:
        raise ValueError("bound schemas changed during final verification")
    result["bound_schema_stability"] = dict(status="pass",before=schemas_before,after=schemas_after)
    (args.output/"completion.json").write_bytes(canonical(result))
    (publication/"completion.json").write_bytes(canonical(result))
    (publication/"README.md").write_text("# Walram letter private offline verification\n\nTechnical source-bound acceptance and guarded installation are complete. The exact installed master projects to one complete source-defined work, including its quoted salutation and complete closing. Its private offline release passed assembly, independent verification, statistics, and normal/streaming readers.\n\nEvidence: " + args.output.as_posix() + ". See completion.json for exact hashes and selection.json for the one-work release and source/data notices.\n\nHuman verification, visual comparison, print equivalence, jurisdictional rights clearance, global release selection, and publication remain separate and unresolved. No publication was performed.\n",encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
