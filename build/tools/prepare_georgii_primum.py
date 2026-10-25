"""Bind the first complete Georgius epitaph and its shared collection context."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.tei.install_accepted import _files, _io_path

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "lambertus-epitaphium-georgii-primum"
SOURCE = Path("raw/openmgh/bsb00000720/tei/bsb00000720.xml")
SOURCE_SHA = "2a096d80ae17e4f701fdce91585d77afb5d69e385167a46f45173e887dc38ce5"
RECEIPT = Path("raw/openmgh/bsb00000720/acquisition-receipt.json")
RECEIPT_SHA = "0bda7667b5337ad4466bd2f8d78a8bd12cef3f7f7db8f345b6141af3b0171696"
HOME = SIDE_HOME = Path("sources/openmgh-bsb720-georgii-primum")
BATCH = HOME / "frozen-selection.json"
BATCH_SHA = "2f9a00467a1155007d6477d9c1008bb88317fb447592b7a52e44129482932633"
PRODUCER = Path("build/tei/georgii_primum_reconstruction.py")
ORACLE = Path("build/tei/georgii_primum_oracle.py")
CONTRACT = Path("ocd_kernel/reconstruction/contract.py")
LONG_PATH = Path("ocd_kernel/tei/install_accepted.py")
XSD = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
SCHEMA = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
FIRST = "bsb00000720_00271_10"
LAST = "bsb00000720_00271_16"
COMBINED_LAST = "bsb00000720_00272_11"
OLD_TITLE = "EPITAPHIUM SENIORIS GEORGII TRIPLEX"
TITLE = "First Epitaph for Georgius (from Epitaphium senioris Georgii triplex)"
SCOPE = "The complete first six-line epitaph for Georgius in retained bsb00000720, volume/Carmina/ab children 89 through 95 inclusive: shared collection heading at 00271_10 and the entire first epitaph text at 00271_11 through 00271_16. ALIUD beginning 00271_17, TERTIUM beginning 00272_5, their texts and internal page marker, and other volume content are excluded."
QUALIFICATION = "EPITAPHIUM SENIORIS GEORGII TRIPLEX is the shared collection context for three independent complete six-line epitaphs. This TEI represents the entire first epitaph only, preserving the literal numbered shared heading once as context; it does not represent the entire triplex. ALIUD introduces another epitaph and TERTIUM a third, each with its own complete wording and closing. The precise first-poem display title is editorial metadata, not invented source wording."

def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()

def _sha(path):
    return sha256(_io_path(path).read_bytes()).hexdigest()

def _read(path):
    return json.loads(_io_path(path).read_bytes())

def _write_once(path, content):
    target = _io_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != content:
        raise ValueError(f"existing first-epitaph authority differs: {path}")
    target.write_bytes(content)

def verify_siblings(root):
    batch = _read(ROOT / BATCH)
    if _sha(ROOT / BATCH) != BATCH_SHA:
        raise ValueError("frozen first-epitaph selection changed")
    for work_id, expected in batch["siblings"].items():
        actual = _files(root / "library/works" / work_id)
        if any(actual.get(path) != digest for path, digest in expected.items()):
            raise ValueError(f"protected sibling generation changed: {work_id}")

def _authority(name, path, role):
    content = _io_path(ROOT / path).read_bytes()
    return dict(name=name, path=path.as_posix(), role=role, bytes=len(content), sha256=sha256(content).hexdigest())

def prepare():
    if _sha(ROOT / SOURCE) != SOURCE_SHA or _sha(ROOT / RECEIPT) != RECEIPT_SHA or _sha(ROOT / BATCH) != BATCH_SHA:
        raise ValueError("retained epitaph authority changed")
    batch = _read(ROOT / BATCH)
    verify_siblings(ROOT)
    preflight = batch["source_preflight"]
    if _sha(ROOT / preflight["path"]) != preflight["sha256"]:
        raise ValueError("independent boundary preflight changed")
    source = etree.fromstring(_io_path(ROOT / SOURCE).read_bytes(), etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if source.getroottree().docinfo.doctype:
        raise ValueError("DOCTYPE forbidden")
    volume = source.find(f"{TEI}text/{TEI}body/{TEI}div")
    if volume is None or len(volume) != 3 or volume[2].get("n") != "Carmina" or len(volume[2]) != 1:
        raise ValueError("source volume envelope changed")
    carrier = volume[2][0]
    if carrier.tag != TEI + "ab" or len(carrier) != 959 or carrier[89].get(XML_ID) != FIRST or carrier[95].get(XML_ID) != LAST or carrier[96].tail != "ALIUD\n" or carrier[104].tail != "TERTIUM\n":
        raise ValueError("triplex/first-epitaph boundary changed")
    work_rel = Path("library/works") / WORK_ID / "work.json"
    work = _read(ROOT / work_rel)
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if work["title"] != OLD_TITLE or len(work["textual_forms"]) != 1 or len(form["editions"]) != 1 or len(edition["acquisition_ids"]) != 1:
        raise ValueError("first-poem identity or title preimage differs")
    acquisition_rel = work_rel.parent / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"] / "acquisitions" / (edition["acquisition_ids"][0] + ".json")
    acquisition = _read(ROOT / acquisition_rel)
    locator = SOURCE.as_posix() + "#" + FIRST + "; " + SOURCE.as_posix() + "#" + LAST
    if acquisition["source_path"] != SOURCE.as_posix() or acquisition["source_sha256"] != SOURCE_SHA or edition["containing_source"]["locator"] != locator:
        raise ValueError("wrong textual authority or first-poem locator")
    selected = list(carrier)[89:96]
    selection_hash = sha256(b"".join(etree.tostring(e, method="c14n", with_comments=True, with_tail=True) for e in selected)).hexdigest()
    boundary = dict(contract="ocd-georgii-primum-boundary-v1", work_id=WORK_ID, source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA, source_division_ordinal=3, native_type="ab-excerpt", start_xml_id=FIRST, end_xml_id=LAST, catalog_start_xml_id=FIRST, catalog_end_xml_id=LAST, selection_c14n_sha256=selection_hash, source_qualification=QUALIFICATION, shared_matter_disposition="Shared triplex heading is included once as explicit collection context. The section-I Lambert attribution, source electronic publication, and print bibliography remain accounted for; source publication and bibliography are preserved in the TEI header.", unassigned_fragment_disposition="The two complete sibling epitaphs ALIUD and TERTIUM remain retained, excluded, and untouched under their existing acquired identities. The internal page at child99 belongs to ALIUD, outside this first poem.", cardinality_disposition=batch["cardinality_disposition"], combined_alternative=batch["combined_alternative"], title_change=batch["title_change"], siblings=batch["siblings"], volume_inventory=[dict(position=i+1, attributes=dict(e.attrib), children=len(e), c14n_sha256=sha256(etree.tostring(e, method="c14n", with_comments=True)).hexdigest(), disposition="first epitaph excerpt only" if i == 2 else "other work excluded") for i, e in enumerate(volume)], carrier_inventory=[dict(position=i, tag=etree.QName(e).localname, attributes=dict(e.attrib), tail=e.tail, c14n_sha256=sha256(etree.tostring(e, method="c14n", with_comments=True, with_tail=True)).hexdigest(), disposition="shared collection heading included" if i == 89 else "first epitaph included" if 90 <= i <= 95 else "sibling ALIUD excluded" if 96 <= i <= 103 else "sibling TERTIUM excluded" if 104 <= i <= 110 else "other source content excluded") for i, e in enumerate(carrier)], first_poem_verse_ids=["bsb00000720_00271_" + str(n) for n in range(11, 17)], next_heading_xml_id="bsb00000720_00271_17", source_attribution_ids=["bsb00000720_00267_1", "bsb00000720_00267_2"])
    home = HOME / WORK_ID
    bp, pp, mp = (home / name for name in ("boundary-review.json", "reconstruction-profile.json", "source-manifest.json"))
    _write_once(ROOT / bp, _json(boundary))
    profile = dict(boundary, contract="ocd-georgii-primum-profile-v1", work_title=TITLE, original_work_title=OLD_TITLE, edition_id=edition["edition_id"], acquisition_id=acquisition["acquisition_id"], acquisition_path=acquisition_rel.as_posix(), acquisition_sha256=_sha(ROOT / acquisition_rel))
    _write_once(ROOT / pp, _json(profile))
    policy = dict(contract="ocd-georgii-primum-policy-v1", status="nonaccepted", closure_inputs=[p.as_posix() for p in (ORACLE, CONTRACT, LONG_PATH)], forbidden_oracle_imports=["build.tei.georgii_primum_reconstruction"], checks=["complete volume and Carmina carrier inventory", "independent numbered18/ALIUD/TERTIUM/numbered19 boundary", "first six-line poem with complete closure", "exact recursive text, tails, attributes and IDs", "literal shared heading and explicit first-poem qualification", "source publication and print bibliography", "immutable identities and protected sibling hash maps", "P5 XSD"])
    _write_once(ROOT / HOME / "validation-policy.json", _json(policy))
    closure = [dict(path=p, sha256=_sha(ROOT / p)) for p in policy["closure_inputs"]]
    manifest = dict(contract="ocd-source-manifest-v1", source_id=WORK_ID + "-bsb720-electronic-v1", authorities=[_authority("extracted-xml", SOURCE, "primary-source"), _authority("work-sidecar", work_rel, "identity"), _authority("boundary-review", bp, "inspected-source-boundary"), _authority("reconstruction-profile", pp, "complete-source-feature-profile"), _authority("validation-policy", HOME / "validation-policy.json", "independent-validation-policy"), _authority("tei-p5-xsd", XSD, "tei-validation-schema"), _authority("candidate-package-schema", SCHEMA, "candidate-package-schema")], converter=dict(id="ocd-georgii-primum-to-tei", version="1", callable="_convert", implementation_path=PRODUCER.as_posix(), implementation_sha256=_sha(ROOT / PRODUCER)), validator=dict(id="ocd-georgii-primum-source-oracle", version="1", callable="_oracle", implementation_path=ORACLE.as_posix(), implementation_sha256=_sha(ROOT / ORACLE), import_closure_sha256=sha256(_json(closure)).hexdigest()), package_schema=dict(path=SCHEMA.as_posix(), sha256=_sha(ROOT / SCHEMA)))
    _write_once(ROOT / mp, _json(manifest))
    return dict(work_id=WORK_ID, manifest_sha256=_sha(ROOT / mp), boundary_sha256=_sha(ROOT / bp))

if __name__ == "__main__":
    print(json.dumps(prepare()))
