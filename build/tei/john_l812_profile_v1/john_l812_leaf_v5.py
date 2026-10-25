"""Work-local L812 accepted-reader leaf v2; proposal only, not imported by OCD."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from ocd_kernel.lib.path_io import io_path
from ocd_kernel.lib.path_io import resolve_path

PROFILE = "ocd-prose-pta-l812-john-ephesus-part-iii-apparatus-v1"
IDENTITY = {
    "work_id": "john-of-ephesus-ecclesiastical-history",
    "textual_form_id": "syriac",
    "edition_id": "pta-ef861ab3-john-ecclesiastical-history-part-iii",
}
ACQUISITION_ID = "pta-l812-part-iii"
MASTER_PATH = (
    "library/works/john-of-ephesus-ecclesiastical-history/forms/syriac/editions/"
    "pta-ef861ab3-john-ecclesiastical-history-part-iii/master.tei.xml"
)
SOURCE_PATH = (
    "raw/pta/ef861ab391ea35c5d85b41dd8d7ba2bf65530b21/"
    "pta-l812-john-of-ephesus-ecclesiastical-history-syriac-part-iii-ef861ab3/"
    "pta0200.pta001.pta-syc1.xml"
)
SOURCE_SHA256 = "35e8d68a884aaa10d1e9f4ae0aee4eb447a4cca7ff0c1393bee6674a6b7e437e"
SOURCE_BYTES = 1_292_998
BOUND_MASTER_SHA256 = "c0aab5dd6685ee6b29db074426e5395871171664a5b3029714d250f599e3a153"
SOURCE_MANIFEST_PATH = (
    "sources/manifest-acquisitions/manifest-acquisition-pta-l812-john-of-ephesus-"
    "syriac-part-iii-ef861ab3-v3/source-manifest.json"
)
SOURCE_MANIFEST_SHA256 = "49b3db003120d8aef5aa12ae91370c00326def6238c7de0fb242012aa8cce039"
FEATURE_PROFILE_PATH = (
    "sources/manifest-acquisitions/manifest-acquisition-pta-l812-john-of-ephesus-"
    "syriac-part-iii-ef861ab3-v3/complete-source-feature-profile.json"
)
FEATURE_PROFILE_SHA256 = "b196afe20a94577e5478253864bfeb19ec76fdbf48c781b1470add5c4bd7e5e8"
POLICY_PATH = (
    "sources/manifest-acquisitions/manifest-acquisition-pta-l812-john-of-ephesus-"
    "syriac-part-iii-ef861ab3-v3/policy.json"
)
POLICY_SHA256 = "23e8d24621fa8655175551e353db82ce1b89a56651cdab633da11e23d04842b4"
ORACLE_PATH = "build/tei/pta_l812_retained_tei_oracle_v3.py"
ORACLE_SHA256 = "ec9f4bc317d7511641feb581998859b9e396da19bab4ba89a6ad81dc4cb3bedf"
CONVERTER_PATH = "build/tei/pta_retained_tei.py"
CONVERTER_SHA256 = "040cacdeeeb8febcfcebb9528f6bc399878d93dc0b31cfd68b053ba0d9d0360c"
TEI_NS = "{http://www.tei-c.org/ns/1.0}"
XML_NS = "{http://www.w3.org/XML/1998/namespace}"


class ProfileMismatch(ValueError):
    """The validated accepted context is outside the exact L812 route."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def select_accepted(context: dict, *, category: str, collection: bool,
                    projection_profile: str | None) -> dict | None:
    """Select from maintained validated context; never trust a caller alias."""
    identity = context.get("identity")
    if not isinstance(identity, dict) or identity.get("work_id") != IDENTITY["work_id"]:
        return None
    accepted = context.get("accepted")
    if not isinstance(accepted, dict):
        raise ProfileMismatch("L812 validated acceptance object is missing")
    expected_accepted_identity = {**IDENTITY, "acquisition_id": ACQUISITION_ID}
    if (identity != IDENTITY
            or accepted.get("identity") != expected_accepted_identity
            or category != "prose" or collection
            or projection_profile not in (None, PROFILE)
            or context.get("language") != "syc"
            or not isinstance(context.get("representation_revision"), str)
            or not context["representation_revision"]):
        raise ProfileMismatch("L812 accepted identity/category/language differs")
    source = accepted.get("source")
    if not isinstance(source, dict) or (source.get("source_path"), source.get("source_bytes"),
                                        source.get("source_sha256")) != (
                                            SOURCE_PATH, SOURCE_BYTES, SOURCE_SHA256):
        raise ProfileMismatch("L812 accepted source binding differs")
    scope = accepted.get("scope")
    if not isinstance(scope, dict):
        raise ProfileMismatch("L812 accepted source scope is missing")
    if scope.get("kind") != "work":
        raise ProfileMismatch("L812 accepted scope kind differs")
    expected_members = scope.get("expected_members")
    included_members = scope.get("included_members")
    if (not isinstance(expected_members, list) or len(expected_members) != 1
            or expected_members != [{"path": SOURCE_PATH, "position": 1}]
            or not isinstance(included_members, list) or len(included_members) != 1
            or not isinstance(included_members[0], dict)):
        raise ProfileMismatch("L812 accepted member scope differs")
    member = included_members[0]
    from ocd_kernel.library.acquisitions import acquisition_for_edition
    acquisition_path, acquisition = acquisition_for_edition(
        Path(context["root"]), IDENTITY["work_id"], IDENTITY["edition_id"],
        acquisition_id=ACQUISITION_ID,
    )
    retained = acquisition.get("retained_files")
    if (not isinstance(retained, list) or len(retained) != 1
            or not isinstance(retained[0], dict)
            or member != {"path": SOURCE_PATH, "position": 1, "bytes": SOURCE_BYTES,
                          "sha256": SOURCE_SHA256, "scope": retained[0].get("scope")}
            or retained[0].get("path") != SOURCE_PATH
            or retained[0].get("bytes") != SOURCE_BYTES
            or retained[0].get("sha256") != SOURCE_SHA256):
        raise ProfileMismatch("L812 accepted included member does not match the retained acquisition")
    master_authority = context.get("authority", {}).get("master", {})
    if master_authority.get("sha256") != BOUND_MASTER_SHA256:
        raise ProfileMismatch("L812 accepted master authority differs")
    root = context.get("root")
    edition = context.get("edition")
    if root is None or edition is None:
        raise ProfileMismatch("L812 accepted edition path differs")
    resolved_root = resolve_path(Path(root))
    if resolve_path(Path(edition.path)) != resolve_path(resolved_root / MASTER_PATH):
        raise ProfileMismatch("L812 accepted edition path differs")
    verify_runtime_authorities(resolved_root)
    return {"profile": PROFILE, "master_sha256": BOUND_MASTER_SHA256,
            "source_sha256": SOURCE_SHA256, "source_bytes": SOURCE_BYTES}


def verify_runtime_authorities(root: Path) -> dict:
    """Bind the canonical retained inputs and maintained source recipe bytes."""
    root = Path(root)
    observed = {}
    manifest_raw = io_path(root / SOURCE_MANIFEST_PATH).read_bytes()
    if _sha(manifest_raw) != SOURCE_MANIFEST_SHA256:
        raise ProfileMismatch("L812 source manifest changed")
    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError as exc:
        raise ProfileMismatch("L812 source manifest is invalid") from exc
    if (manifest.get("source_id") != "pta-l812-john-of-ephesus-ecclesiastical-history-syriac-part-iii-ef861ab3"
            or manifest.get("work_id") != IDENTITY["work_id"]
            or manifest.get("converter") != {
                "callable": "_convert", "id": "ocd-pta-retained-tei-byte-preserving-converter",
                "implementation_path": CONVERTER_PATH,
                "implementation_sha256": CONVERTER_SHA256, "version": "2"}
            or manifest.get("validator", {}).get("implementation_path") != ORACLE_PATH
            or manifest.get("validator", {}).get("implementation_sha256") != ORACLE_SHA256):
        raise ProfileMismatch("L812 source manifest identity or runtime declaration differs")
    rows = manifest.get("authorities")
    if not isinstance(rows, list) or len(rows) != 9:
        raise ProfileMismatch("L812 source authority inventory differs")
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("path"), str)
                or not isinstance(row.get("bytes"), int) or isinstance(row.get("bytes"), bool)
                or not isinstance(row.get("sha256"), str)
                or len(row["sha256"]) != 64):
            raise ProfileMismatch("L812 source authority inventory has an invalid row")
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ProfileMismatch("L812 source authority path escapes repository")
        path = io_path(root / relative)
        raw = path.read_bytes()
        if len(raw) != row["bytes"] or _sha(raw) != row["sha256"]:
            raise ProfileMismatch(f"L812 source authority changed: {row['path']}")
        observed[row["path"]] = {"bytes": len(raw), "sha256": row["sha256"],
                                  "role": row.get("role")}
    for relative, digest in ((FEATURE_PROFILE_PATH, FEATURE_PROFILE_SHA256),
                             (POLICY_PATH, POLICY_SHA256), (ORACLE_PATH, ORACLE_SHA256),
                             (CONVERTER_PATH, CONVERTER_SHA256)):
        raw = io_path(root / relative).read_bytes()
        if _sha(raw) != digest:
            raise ProfileMismatch(f"L812 authority changed: {relative}")
    return {"manifest_sha256": SOURCE_MANIFEST_SHA256,
            "authorities": observed,
            "runtime": {relative: digest for relative, digest in
                        ((FEATURE_PROFILE_PATH, FEATURE_PROFILE_SHA256),
                         (POLICY_PATH, POLICY_SHA256), (ORACLE_PATH, ORACLE_SHA256),
                         (CONVERTER_PATH, CONVERTER_SHA256))}}


def verify_master(master_raw: bytes) -> dict:
    """Require the exact bound header/body and the two retained source PIs."""
    if _sha(master_raw) != BOUND_MASTER_SHA256:
        raise ProfileMismatch("L812 bound master bytes differ")
    if b"<!DOCTYPE" in master_raw.upper() or b"<!ENTITY" in master_raw.upper():
        raise ProfileMismatch("L812 master contains a forbidden declaration")
    expected_prolog = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<?xml-model href="https://raw.githubusercontent.com/PatristicTextArchive/Schema/master/tei-pta.rng" '
        b'schematypens="http://relaxng.org/ns/structure/1.0"?>\n'
        b'<?xml-stylesheet type="text/css" href="standard.css"?>\n'
    )
    if (not master_raw.startswith(expected_prolog)
            or master_raw.count(b"<?xml-model ") != 1
            or master_raw.count(b"<?xml-stylesheet ") != 1):
        raise ProfileMismatch("L812 processing instructions differ")
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
        root = ET.fromstring(master_raw, parser=parser)
    except ET.ParseError as exc:
        raise ProfileMismatch("L812 bound master XML is invalid") from exc
    if root.tag != TEI_NS + "TEI":
        raise ProfileMismatch("L812 TEI root differs")
    body = root.find(TEI_NS + "text/" + TEI_NS + "body")
    if body is None or len(body) != 2:
        raise ProfileMismatch("L812 body division set differs")
    preface, edition = body
    if (preface.tag != TEI_NS + "div" or preface.get("type") != "praefatio"
            or preface.get(XML_NS + "lang") != "eng"
            or edition.tag != TEI_NS + "div" or edition.get("type") != "edition"
            or edition.get("n") != "urn:cts:pta:pta0200.pta001.pta-syc1"
            or edition.get(XML_NS + "lang") != "syc"):
        raise ProfileMismatch("L812 ordered source divisions or languages differ")
    part = edition.find(TEI_NS + "div")
    part_children = [] if part is None else [child for child in part if isinstance(child.tag, str)]
    if (part is None or part.get("type") != "textpart" or part.get("subtype") != "part"
            or part.get("n") != "3" or len(part_children) != 7
            or part_children[0].get("subtype") != "chapter" or part_children[0].get("n") != "0"
            or [child.get("subtype") for child in part_children[1:]] != ["book"] * 6
            or [child.get("n") for child in part_children[1:]] != ["1", "2", "3", "4", "5", "6"]):
        observed = (None if part is None else [
            {"tag": child.tag, "type": child.get("type"), "subtype": child.get("subtype"),
             "n": child.get("n")} for child in part])
        raise ProfileMismatch(f"L812 Part III chapter/book hierarchy differs: {observed}")
    return {"master_sha256": BOUND_MASTER_SHA256, "prolog_pi_count": 2,
            "source_divisions": [{"type": "praefatio", "language": "eng"},
                                 {"type": "edition", "language": "syc"}],
            "part_children": [{"subtype": part_children[0].get("subtype"), "n": part_children[0].get("n")},
                              *[{"subtype": child.get("subtype"), "n": child.get("n")}
                                for child in part_children[1:]]],
            "direct_part_comments": sum(1 for child in part if child.tag is ET.Comment)}
