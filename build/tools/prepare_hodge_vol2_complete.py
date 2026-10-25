"""Prepare the complete retained Volume II source manifest; never install it."""
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei import hodge_vol2_complete_reconstruction as producer
from build.tei import hodge_vol2_complete_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "hodge-systematic-theology-vol-2"
WORK = Path("library/works") / WORK_ID
IDENTITY = dict(work_id=WORK_ID, textual_form_id=WORK_ID + "-english",
                edition_id=WORK_ID + "-retained-electronic-witness",
                acquisition_id=WORK_ID + "-retained-source")
EDITION = WORK / "forms" / IDENTITY["textual_form_id"] / "editions" / IDENTITY["edition_id"]
ACQUISITION = EDITION / "acquisitions" / (IDENTITY["acquisition_id"] + ".json")
HISTORICAL = WORK / "integration/hodge-vol2-parts-ii-iii-electronic-v2/inputs/package"
BASE = Path("sources/structured-text") / WORK_ID
MANIFEST = BASE / "hodge-systematic-theology-vol-2.source-manifest.complete-v1.json"
SOURCE = Path("raw/ccel/hodge/theology2.xml")
SCOPE = ("Complete retained CCEL theology2.xml electronic Volume II: roots i (title pages, "
         "1940 imprint and separate 1871 copyright notice), ii (full contents table), iii "
         "(Part II, Anthropology), iv (Part III, Soteriology), and v (all seven rendered indexes), "
         "once in source order. All 11,903 body descendants, 251 table rows, 567 cells, 52 row spans, "
         "52 column spans, 2,693 index links, seven index markers, 586 notes, 741 page markers and "
         "769 scripture references are represented. Parts II/III remain byte equal to the valid "
         "historical readable subtrees. The complete source header and prolog remain accounted "
         "private support evidence; useful source metadata is qualified in the TEI header. "
         "No three-volume completeness, physical print collation, human verification, rights "
         "clearance or publication claim.")
canonical = producer.canonical


def put(relative, raw):
    path = io_path(ROOT / relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def binding(name, path, role):
    raw = io_path(ROOT / path).read_bytes()
    return dict(name=name, path=path.as_posix(), role=role, bytes=len(raw), sha256=sha256(raw).hexdigest())


def main():
    acquisition = validate_acquisition(io_path(ROOT / ACQUISITION), root=ROOT)
    if len(acquisition["retained_files"]) != 1 or acquisition["source_sha256"] != producer.SOURCE_SHA:
        raise ValueError("Volume II retained acquisition differs")
    raw, account = producer.build(io_path(ROOT / SOURCE).read_bytes(),
                                 io_path(ROOT / HISTORICAL / "content.tei.xml").read_bytes(),
                                 io_path(ROOT / HISTORICAL / "source-accountability.json").read_bytes())
    facts = checker.inspect(io_path(ROOT / SOURCE).read_bytes(), raw, account,
                            io_path(ROOT / HISTORICAL / "content.tei.xml").read_bytes())
    questions = [dict(id="rights-human-print-publication", status="unresolved",
                     evidence="Physical print collation, human acceptance, rights clearance and public publication remain separate.")]
    profile_path = BASE / "hodge-systematic-theology-vol-2.complete-profile.json"
    put(profile_path, canonical(dict(work_id=WORK_ID, source_sha256=producer.SOURCE_SHA, scope=SCOPE,
                                    source_facts=facts, questions=questions,
                                    header_xml=etree.tostring(producer.parse(raw).getroot()[0], encoding="unicode"))))
    policy_path = BASE / "hodge-systematic-theology-vol-2.complete-policy.json"
    put(policy_path, canonical(dict(work_id=WORK_ID, projection_profile=producer.PROFILE, scope=SCOPE,
        rules=["Exact ordered source carriers, attributes, direct text, tails and child attachment",
               "All five roots; source table cells, spans and column layout; seven rendered indexes",
               "Literal href/query retained in reversible annotations; checked source-to-TEI local targets",
               "Unchanged valid iii/iv readable subtrees; independent ledger and document envelope check",
               "Qualified header metadata; P5 validation; fresh process replay and meaningful mutations"])))
    readme_path = BASE / "README.complete.source.md"
    put(readme_path, ("# Hodge, Systematic Theology, Volume II: retained source\n\n"
        "Sourced via [CCEL.org](https://www.ccel.org/ccel/hodge/theology2.html). Charles Hodge is the author. "
        "The electronic header names Christian Classics Ethereal Library and creation on June 20, 2005. "
        "Tim Perrine is credited only for the CCEL Staff Writer description, not as the volume's editor, "
        "translator or transcriber. The retained title page states Wm. B. Eerdmans Publishing Co., "
        "Grand Rapids, Mich., 1940, with a separate 1871 Scribner copyright notice. The inherited "
        "1872-1873 edition claim remains unverified.\n\n"
        "All five own-volume roots are represented, including the complete contents table and seven "
        "rendered indexes. The source header, styles and prolog are private support evidence. The "
        "source DC.Rights is empty. CCEL permission evidence permits parsing and requests credit, "
        "while reserving rights in its files and formatting. CCEL formatting rights are not cleared. "
        "Technical acceptance, human verification, print collation and publication remain separate. "
        "This private source-local credit is not a selected public-card notice.\n").encode())
    acquisition_preimage = BASE / "hodge-systematic-theology-vol-2.complete-acquisition-preimage.json"
    put(acquisition_preimage, io_path(ROOT / ACQUISITION).read_bytes())
    authorities = [("primary-source", SOURCE, "primary-source"),
        ("historical-candidate", HISTORICAL / "content.tei.xml", "valid-readable-subtrees"),
        ("historical-accounting", HISTORICAL / "source-accountability.json", "historical-source-crosswalk"),
        ("profile", profile_path, "complete-source-feature-profile"),
        ("validation-policy", policy_path, "independent-validation-policy"),
        ("source-readme", readme_path, "source-attribution"),
        ("acquisition-preimage", acquisition_preimage, "unchanged-acquisition-at-reconstruction"),
        ("ccel-permission", Path("docs/sources/ccel-permission.md"), "source-permission-evidence"),
        ("tei-p5-xsd", Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd"), "tei-validation-schema"),
        ("candidate-package-schema", Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"), "candidate-package-schema")]
    manifest = dict(contract="ocd-source-manifest-v1", source_id="ccel-hodge-theology2-complete-v1",
                    **IDENTITY, scope=SCOPE, authorities=[binding(*a) for a in authorities])
    for role, module, identifier, version, callable_name in (
        ("converter", producer, producer.CONVERTER_ID, producer.CONVERTER_VERSION, "_convert"),
        ("validator", checker, checker.ORACLE_ID, checker.ORACLE_VERSION, "_oracle")):
        path = Path(module.__file__).resolve().relative_to(ROOT)
        manifest[role] = dict(id=identifier, version=version, callable=callable_name,
                             implementation_path=path.as_posix(), implementation_sha256=sha256(Path(module.__file__).read_bytes()).hexdigest())
    manifest["validator"]["import_closure_sha256"] = checker.closure_sha(ROOT)
    manifest["package_schema"] = dict(path=authorities[-1][1].as_posix(), sha256=sha256(io_path(ROOT / authorities[-1][1]).read_bytes()).hexdigest())
    put(MANIFEST, canonical(manifest))
    print(json.dumps(dict(status="prepared", manifest=MANIFEST.as_posix(), source_facts=facts)))


if __name__ == "__main__":
    main()
