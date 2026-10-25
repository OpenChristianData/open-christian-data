"""Compose a reviewed current header around the unchanged retained Nave TEI."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library._common import io_path


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "naves-topical-bible"
FORM_ID = WORK_ID + "-retained-electronic"
EDITION_ID = WORK_ID + "-retained-electronic-witness"
ACQUISITION_ID = WORK_ID + "-retained-source-set"
REVISION = "nave-retained-native-technical-v1"
TITLE = "Nave SWORD module v3 retained electronic witness"
WORK = ROOT / "library/works" / WORK_ID
BASE = WORK / "integration/nave-current-v2"
LOG = ROOT / "reports/_logs/naves-topical-bible-current-reconciliation-20261002-v1"
HISTORICAL = LOG / "historical-package"
ACQUISITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID / "acquisitions" / (ACQUISITION_ID + ".json")
TEI = "{http://www.tei-c.org/ns/1.0}"
OLD_SHA = "eb8504033ade25981d56ec6249b87b5184c599cc70270cca3cee650ad2adf1f5"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def save(path, raw):
    path = io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise FileExistsError(f"Frozen Nave artifact differs: {path}")
    else:
        path.write_bytes(raw)


def main():
    old = (HISTORICAL / "content.tei.xml").read_bytes()
    if digest(old) != OLD_SHA:
        raise ValueError("Retained native Nave TEI drifted")
    acquisition = json.loads(io_path(ACQUISITION).read_bytes())
    members = acquisition["retained_files"]
    if len(members) != 4 or acquisition["acquisition_id"] != ACQUISITION_ID or acquisition["edition_id"] != EDITION_ID:
        raise ValueError("Nave acquired identity/member set differs")
    for member in members:
        raw = (ROOT / member["path"]).read_bytes()
        if len(raw) != member["bytes"] or digest(raw) != member["sha256"]:
            raise ValueError("Nave source member differs: " + member["path"])
    member_set = (ROOT / acquisition["source_path"]).read_bytes()
    if digest(member_set) != acquisition["source_sha256"] or len(member_set) != acquisition["source_bytes"]:
        raise ValueError("Nave source-member-set acquisition binding differs")
    conf_raw = (ROOT / "raw/naves_topical/mods.d/nave.conf").read_bytes()
    config = {}
    for line in conf_raw.decode("utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if key in config:
                raise ValueError("Repeated Nave metadata key")
            config[key] = value
    source_proof = json.loads((LOG / "retained-source-native-review.json").read_bytes())
    if source_proof["status"] != "pass" or source_proof["candidate_sha256"] != OLD_SHA or not source_proof["accountability_exact"]:
        raise ValueError("Existing complete source linkage proof differs")
    scope = "Complete retained CrossWire Nave v3.0 electronic module: all 5,322 ordered dictionary keys and addressed entryFree/def payloads, including duplicate key occurrences, literal references, nested lists and line breaks. Four extracted binary members are source authority; config is metadata/rights support and ZIP packaging is not another witness. No complete identified print-edition claim."
    header = etree.Element(TEI + "teiHeader", nsmap={None: TEI[1:-1]})
    file_desc = etree.SubElement(header, TEI + "fileDesc")
    title_stmt = etree.SubElement(file_desc, TEI + "titleStmt")
    etree.SubElement(title_stmt, TEI + "title").text = "Nave's Topical Bible"
    publication = etree.SubElement(file_desc, TEI + "publicationStmt")
    etree.SubElement(publication, TEI + "publisher").text = "Open Christian Data: technical electronic-witness reconstruction"
    availability = etree.SubElement(publication, TEI + "availability", status="restricted")
    etree.SubElement(availability, TEI + "p").text = "The module states DistributionLicense=Public Domain. Independent rights clearance, human textual acceptance, exact print lineage and public publication authorization remain unresolved; technical adoption and private verification do not establish them."
    description = etree.SubElement(file_desc, TEI + "sourceDesc")
    bibl = etree.SubElement(description, TEI + "bibl", type="ocd-acceptance-binding")
    etree.SubElement(bibl, TEI + "ptr", target=acquisition["url"])
    identities = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID, "representation_revision": REVISION, "source_sha256": acquisition["source_sha256"], "retained_sha256": acquisition["source_sha256"], "transformation_source_set_sha256": "8c5cf1cc42248214ba0d9e0fda51c99925b9a06760a71dd2a33a5750e09afc6d", "module_config_sha256": digest(conf_raw), "source_bytes": str(acquisition["source_bytes"]), "source_kind": acquisition["source_kind"], "sha256": acquisition["source_sha256"]}
    for key, value in identities.items():
        etree.SubElement(bibl, TEI + "idno", type=key).text = value
    notes = {
        "source-scope": acquisition["source_scope"],
        "source-location": acquisition["source_path"],
        "native-text-scope": scope,
        "source-credit": "Credit CrossWire Bible Society as the SWORD module distributor and CCEL as the module's stated TextSource: " + config["TextSource"] + ". These roles do not independently verify a historical print edition or reuse permission.",
        "literal-module-description": config["Description"],
        "literal-module-about": config["About"],
        "source-metadata-qualification": "Version=" + config["Version"] + "; History_3.0=" + config["History_3.0"] + "; SwordVersionDate=" + config["SwordVersionDate"] + ". Preserve the differing literal module date fields without conflating revision, publication or print dates. TextSource and historical publication/ISBN claims are provider statements, not independent collation.",
        "source-format-control": "Every addressed payload has exactly one terminal NUL and every compressed allocation has 1,024 zero padding bytes. These binary format carriers remain in retained bytes and exact accountability, with explicit non-readable dispositions; no readable wording is removed.",
        "historical-header-context": "Retained CrossWire SWORD Nave module version 3.0; the exact transformation source is the manifest-bound four-member zLD set.",
    }
    for role, value in notes.items():
        etree.SubElement(bibl, TEI + "note", type=role).text = value
    encoding = etree.SubElement(header, TEI + "encodingDesc")
    etree.SubElement(encoding, TEI + "p").text = "Existing complete native TEI reused without body conversion or normalization. Source ref/@osisRef remains target with type=osisRef; external dictionary keys remain form/orth and payload@n remains distinct. Public readable text uses explicit line-break boundaries and depth-indented source list items; full XML hierarchy/text/tails/attributes remain in the master and private receipt, not an XML-preserving public-row claim."
    revisions = etree.SubElement(header, TEI + "revisionDesc")
    etree.SubElement(revisions, TEI + "change", {"when": "2026-10-02", "{http://www.w3.org/XML/1998/namespace}id": REVISION}).text = "Reviewed current electronic identity/source bindings and qualified module metadata; historical complete native body conserved byte for byte."
    fresh_header = etree.tostring(header).replace(b' xmlns="http://www.tei-c.org/ns/1.0"', b"", 1)
    start = old.index(b"<teiHeader>"); end = old.index(b"</teiHeader>") + len(b"</teiHeader>")
    fresh = old[:start] + fresh_header + old[end:]
    if old[end:] != fresh[fresh.index(b"</teiHeader>") + len(b"</teiHeader>"):] or etree.tostring(etree.fromstring(old).find(TEI + "text")) != etree.tostring(etree.fromstring(fresh).find(TEI + "text")):
        raise ValueError("Nave historical body changed during header composition")
    for name, raw in (("candidate.tei.xml", fresh), ("fresh-header.xml", fresh_header), ("historical-header.xml", old[start:end])):
        save(BASE / name, raw)
    profile = {"contract": "ocd-nave-current-native-profile-v1", "identity": identities, "edition_title": TITLE, "category_prerequisite": {"path": "edition.category", "before": None, "after": "topical-indexes"}, "scope": scope, "included_members": members, "support_config": {"path": "raw/naves_topical/mods.d/nave.conf", "sha256": digest(conf_raw)}, "historical_candidate_sha256": OLD_SHA, "candidate_sha256": digest(fresh), "native_body_byte_equal": True, "header_sha256": digest(fresh_header), "missing_historical_manifest": {"path": "sources/naves-topical-bible/naves-topical-bible.l876-v2.source-manifest.json", "disposition": "Retained package historical binding; not fabricated. Current actual source-member acquisition plus maintained source manifest and fresh source-native proof establish renewal."}, "source_proof": {"path": (LOG / "retained-source-native-review.json").relative_to(ROOT).as_posix(), "sha256": digest((LOG / "retained-source-native-review.json").read_bytes())}, "producer": "Exact pinned historical body plus reviewed current header composition; no new source conversion", "unassessed": ["rights clearance", "human acceptance", "exact print lineage", "public publication"]}
    save(BASE / "profile.json", json_bytes(profile))
    visible = ("# Nave's Topical Bible: source credit and scope\n\n"
        "This dataset represents the complete retained CrossWire SWORD Nave module version 3.0: 5,322 ordered topics, including repeated keys. Credit [CrossWire Bible Society](https://www.crosswire.org/) as module distributor and [CCEL](https://ccel.org/ccel/n/nave/bible.xml) as its stated text source. The module describes Orville J. Nave as the original compiler; the precise historic print edition and electronic editorial lineage remain unverified.\n\n"
        "The module declares `DistributionLicense=Public Domain`. This is a retained provider statement; independent rights clearance and public publication authorization remain unresolved. Module `History_3.0` states a new CCEL source dated 2021-02-28, while `SwordVersionDate` says 2008-11-29; these are distinct literal metadata fields, not confirmed print dates. Technical adoption and verified private offline use do not establish human textual approval or reuse permission.\n\n"
        "Each public topic keeps its literal dictionary key and complete definition, with literal reference labels and targets. Line breaks and depth-indented list-item boundaries support readable text. Full source XML hierarchy, exact text/tails and payload topic labels remain in the accepted master and private verification evidence. The public rows are a readable category projection. Scripture references remain source-classified literal targets; no independent interpretation or corrected citation is claimed.\n").encode()
    save(BASE / "README.data.md", visible)
    save(BASE / "README.source.md", visible + b"\nThe exact selected visible data notice is `data/topical_indexes/naves-topical-bible/README.md`.\n")
    save(BASE / "SOURCE_CREDIT.md", visible + ("\nLiteral retained module About statement:\n\n" + config["About"] + "\n").encode())
    print(json.dumps({"status": "pass", "candidate_sha256": digest(fresh), "header_sha256": digest(fresh_header), "body_byte_equal": True, "source_members": 4, "profile_sha256": digest(json_bytes(profile))}))


if __name__ == "__main__":
    main()
