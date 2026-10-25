"""Independent source-derived triplex cardinality and first-poem tree oracle."""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from lxml import etree
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage
from ocd_kernel.tei.install_accepted import _files, _io_path

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
ORACLE_ID = "ocd-georgii-primum-source-oracle"
ORACLE_VERSION = "1"
FIRST = "bsb00000720_00271_10"
LAST = "bsb00000720_00271_16"
TITLE = "First Epitaph for Georgius (from Epitaphium senioris Georgii triplex)"
OLD_TITLE = "EPITAPHIUM SENIORIS GEORGII TRIPLEX"

def _sha(content):
    return sha256(content).hexdigest()

def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()

def _equal(a, b, *, outer=False):
    if a.tag != b.tag or dict(a.attrib) != dict(b.attrib) or a.text != b.text or len(a) != len(b) or (not outer and a.tail != b.tail):
        return False
    return all(_equal(x, y) for x, y in zip(a, b, strict=True))

def _source(raw):
    source = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if source.getroottree().docinfo.doctype:
        raise ValueError("DOCTYPE forbidden")
    headings = source.xpath("//*[@xml:id='bsb00000720_00271_10']")
    if len(headings) != 1 or headings[0].tail != "〈18.〉 EPITAPHIUM SENIORIS GEORGII TRIPLEX\n":
        raise ValueError("literal numbered triplex heading changed")
    heading = headings[0]
    ab = heading.getparent()
    parent = ab.getparent()
    volume = parent.getparent()
    if ab.tag != TEI + "ab" or parent.get("n") != "Carmina" or len(volume) != 3 or volume.index(parent) != 2 or len(parent) != 1 or len(ab) != 959:
        raise ValueError("independent Carmina envelope changed")
    start = ab.index(heading)
    subsequent = list(ab)[start+1:]
    aliud = [e for e in subsequent if e.tail == "ALIUD\n"]
    tertium = [e for e in subsequent if e.tail == "TERTIUM\n"]
    next_titles = [e for e in subsequent if e.tail == "〈19.〉 EPITAPHIUM ENGELBERTI\n"]
    if len(aliud) != 1 or len(tertium) != 1 or len(next_titles) != 1:
        raise ValueError("three epitaph/neighbor boundaries changed")
    stop, third, next_work = (ab.index(e[0]) for e in (aliud, tertium, next_titles))
    if (start, stop, third, next_work) != (89, 96, 104, 111):
        raise ValueError("source triplex order/cardinality changed")
    poems = [list(ab)[start+1:stop], list(ab)[stop+1:third], list(ab)[third+1:next_work]]
    verses = [[e for e in poem if e.tag == TEI + "lb"] for poem in poems]
    if [len(v) for v in verses] != [6, 6, 6] or [(ab.index(e), e.get(XML_ID)) for e in poems[1] if e.tag != TEI + "lb"] != [(99, "bsb00000720_00272")]:
        raise ValueError("complete six-line epitaphs/internal sibling page changed")
    openings = ["Quis mea sors restat, lux hęc peregrina tepescat,\n", "Sublevita dei, frater salveto Georgi,\n", "Tollitur e medio tenero Georgius ęvo;\n"]
    endings = ["et velut umbra levis ceu nihilum fuerit.\n", "quo senior metitur, iunior et rapitur.\n", "quo perit ulterius mors, dolor et gemitus.\n"]
    if [v[0].tail for v in verses] != openings or [v[-1].tail for v in verses] != endings:
        raise ValueError("independent complete poem openings/closures changed")
    selected = list(ab)[start:stop]
    ids = [e.get(XML_ID) for node in selected for e in node.iter() if e.get(XML_ID)]
    if len(ids) != 7 or len(set(ids)) != 7 or selected[-1].get(XML_ID) != LAST:
        raise ValueError("first poem physical identities changed")
    if any(e.get(k) for node in selected for e in node.iter() for k in ("corresp", "target", "spanTo")):
        raise ValueError("unaccounted selected local references")
    return source, volume, ab, selected, verses

def check(source_bytes, candidate_bytes, *, first_id=FIRST, last_id=LAST):
    if (first_id, last_id) != (FIRST, LAST):
        raise ValueError("locator does not bound the complete first epitaph; combined triplex exceeds this identity")
    source, volume, ab, selected, verses = _source(source_bytes)
    candidate = etree.fromstring(candidate_bytes, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if candidate.getroottree().docinfo.doctype:
        raise ValueError("DOCTYPE forbidden")
    body = candidate.find(f"{TEI}text/{TEI}body")
    if candidate.tag != TEI + "TEI" or body is None or len(body) != 1 or body[0].get("type") != "work" or body[0].get("n") != TITLE or len(body[0]) != 1:
        raise ValueError("candidate is not one complete first epitaph")
    actual = body[0][0]
    if actual.tag != ab.tag or dict(actual.attrib) != dict(ab.attrib) or actual.text != ab.text or actual.tail != ab.tail or len(actual) != len(selected) or not all(_equal(s, t) for s, t in zip(selected, actual, strict=True)):
        raise ValueError("complete first-epitaph carrier trees differ")
    return dict(status="pass", source_sha256=_sha(source_bytes), selection_c14n_sha256=_sha(b"".join(etree.tostring(e, method="c14n", with_comments=True, with_tail=True) for e in selected)), elements=sum(1 for e in actual.iter()), source_carriers=len(selected), xml_ids=7, carrier_counts=dict(Counter(etree.QName(e).localname for e in actual.iter())), first_poem_lines=[e.tail for e in verses[0]], triplex_poem_line_counts=[len(v) for v in verses], shared_heading_context=True, sibling_epitaphs_excluded=True, sibling_internal_page_excluded=True, external_local_targets=0)

def _oracle(manifest: SourceManifest, candidate: CandidatePackage):
    manifest.verify()
    candidate.verify_integrity()
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    policy = json.loads(manifest.authority_path("validation-policy").read_bytes())
    boundary = json.loads(manifest.authority_path("boundary-review").read_bytes())
    raw = manifest.authority_path("extracted-xml").read_bytes()
    work = json.loads(manifest.authority_path("work-sidecar").read_bytes())
    acqbytes = _io_path(manifest.repository_root / profile["acquisition_path"]).read_bytes()
    acquisition = json.loads(acqbytes)
    if profile["contract"] != "ocd-georgii-primum-profile-v1" or policy["contract"] != "ocd-georgii-primum-policy-v1" or profile["work_id"] != "lambertus-epitaphium-georgii-primum" or work["work_id"] != profile["work_id"] or work["title"] not in (OLD_TITLE, TITLE) or profile["work_title"] != TITLE or profile["original_work_title"] != OLD_TITLE or _sha(acqbytes) != profile["acquisition_sha256"] or acquisition["source_path"] != profile["source_path"] or acquisition["source_sha256"] != _sha(raw) or acquisition["acquisition_id"] != profile["acquisition_id"]:
        raise ValueError("source/profile/acquisition/exact identity changed")
    edition = work["textual_forms"][0]["editions"][0]
    if acquisition["edition_id"] != profile["edition_id"] or edition["edition_id"] != profile["edition_id"] or edition["acquisition_ids"] != [profile["acquisition_id"]] or any(profile.get(k) != v for k, v in boundary.items() if k != "contract"):
        raise ValueError("profile/boundary/edition association differs")
    expected_locator = profile["source_path"] + "#" + FIRST + "; " + profile["source_path"] + "#" + LAST
    if edition["containing_source"]["locator"] != expected_locator:
        raise ValueError("first-poem locator differs")
    result = check(raw, candidate.member_bytes("content.tei.xml"))
    source, volume, ab, selected, verses = _source(raw)
    expected_volume = [dict(position=i+1, attributes=dict(e.attrib), children=len(e), c14n_sha256=_sha(etree.tostring(e, method="c14n", with_comments=True)), disposition="first epitaph excerpt only" if i == 2 else "other work excluded") for i, e in enumerate(volume)]
    expected_carriers = [dict(position=i, tag=etree.QName(e).localname, attributes=dict(e.attrib), tail=e.tail, c14n_sha256=_sha(etree.tostring(e, method="c14n", with_comments=True, with_tail=True)), disposition="shared collection heading included" if i == 89 else "first epitaph included" if 90 <= i <= 95 else "sibling ALIUD excluded" if 96 <= i <= 103 else "sibling TERTIUM excluded" if 104 <= i <= 110 else "other source content excluded") for i, e in enumerate(ab)]
    if boundary["volume_inventory"] != expected_volume or boundary["carrier_inventory"] != expected_carriers or profile["selection_c14n_sha256"] != result["selection_c14n_sha256"] or boundary["title_change"]["before"] != OLD_TITLE or boundary["title_change"]["after"] != TITLE or boundary["combined_alternative"]["status"] != "rejected-for-this-identity":
        raise ValueError("whole source accounting/cardinality/title proposal differs")
    for work_id, expected in boundary["siblings"].items():
        actual_sibling = _files(manifest.repository_root / "library/works" / work_id)
        if any(actual_sibling.get(path) != digest for path, digest in expected.items()):
            raise ValueError("protected sibling authority changed")
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    if any(accounting.get(k) != v for k, v in boundary.items() if k != "contract"):
        raise ValueError("candidate source accounting differs")
    xml = etree.fromstring(candidate.member_bytes("content.tei.xml"), etree.XMLParser(resolve_entities=False, no_network=True))
    if xml.get(XML_ID) != "ocd-lambertus-epitaphium-georgii-primum-bsb720-electronic-v1" or xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}titleStmt/{TEI}title").text != TITLE or xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}notesStmt/{TEI}note").text != profile["source_qualification"]:
        raise ValueError("candidate title/first-poem qualification differs")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        if not _equal(source.find(f"{TEI}teiHeader/{TEI}fileDesc/{suffix}"), xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{suffix}"), outer=True):
            raise ValueError("source publication or print bibliography differs")
    etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd")))).assertValid(xml)
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if provenance.get("status") != "nonaccepted" or provenance.get("work_id") != profile["work_id"] or provenance.get("edition_id") != profile["edition_id"] or provenance.get("source_sha256") != _sha(raw) or provenance.get("canonical_ir_written") is not False or not candidate.member_bytes("unresolved.jsonl").strip() or b"Monumenta" not in candidate.member_bytes("README.source.md"):
        raise ValueError("candidate provenance/review/credit differs")
    closure = [dict(path=p, sha256=_sha((manifest.repository_root / p).read_bytes())) for p in policy["closure_inputs"]]
    outcome = dict(status="pass", oracle_id=ORACLE_ID, oracle_version=ORACLE_VERSION, implementation_sha256=_sha(Path(__file__).read_bytes()), import_closure_sha256=_sha(_json(closure)), runtime=f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})", source_manifest_sha256=manifest.sha256, candidate_sha256=candidate.sha256, profile_sha256=_sha(manifest.authority_path("reconstruction-profile").read_bytes()), package_schema_sha256=_sha(manifest.authority_path("candidate-package-schema").read_bytes()), source_sha256=_sha(raw), xsd_sha256=_sha(manifest.authority_path("tei-p5-xsd").read_bytes()), policy_sha256=_sha(manifest.authority_path("validation-policy").read_bytes()), findings=[])
    outcome["result_sha256"] = _sha(_json(outcome))
    return outcome

_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
