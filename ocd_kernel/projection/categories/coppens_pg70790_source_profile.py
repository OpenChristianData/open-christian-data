"""Proposed narrow native reader profile for the retained PG 70790 Coppens edition."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError, io_path

PROFILE = "ocd-prose-coppens-pg70790-source-native-v1"
IDENTITY = {
    "work_id": "charles-coppens-spiritual-exercises-adaptation",
    "textual_form_id": "charles-coppens-eight-days-six-triduums-1916",
    "edition_id": "charles-coppens-exercises-1916-pg70790",
}
ACQUISITION_ID = "pg70790-retained-zip"
MASTER_SHA256 = "e3d43d5c193c6db00e02690b738dd70f159c87c1c213ea26cf9afc073041a639"
SOURCE_MANIFEST_SHA256 = "52388607e93edf315cb962aa6443199c3eb3d6dc02c9520f5f08e4ec997bb0cf"
SOURCE_ARCHIVE_PATH = "raw/gutenberg/70790/pg70790-h.zip"
SOURCE_ARCHIVE_SHA256 = "fdfcd5228a14f985fff53cb1bddca74574cee04daca68400b0b11a66a81fcedf"
SOURCE_ARCHIVE_BYTES = 1596270
HTML_MEMBER = {"path": "pg70790-images.html", "bytes": 451272,
               "sha256": "5a824563e0a08ed885c4b4e4bac49c43750ae91946e677d06b3e5ce701e50b54"}
COVER = {"path": "images/cover.jpg", "bytes": 1450734,
         "sha256": "514e7a598719e6950f1c645feaa09b37ab98712d42991866a2cb9fd124a147df"}
PACKAGE_SHA256 = "61f0687a6e75e2b95568ded35fac4c42c67c98681cdf62f37ff0d521a4e3dbb4"
BODY_BLOCK_COUNTS = {
    "source-p": 994,
    "source-h3": 61,
    "source-div": 42,
    "source-h4": 15,
    "source-header": 1,
    "source-footer": 1,
}
PROFILE_BLOCK_TYPES = {"source-p", "source-div", "source-header", "source-footer"}
ACCEPTANCE_ACCOUNTING_PATH = (
    "library/works/charles-coppens-spiritual-exercises-adaptation/"
    "integration/pg70790-source-native-v5/acceptance-v1/source-accounting.json"
)
CANDIDATE_PATH = (
    "library/works/charles-coppens-spiritual-exercises-adaptation/"
    "integration/pg70790-source-native-v5/acceptance-v1/candidate.tei.xml"
)
MASTER_PATH = (
    "library/works/charles-coppens-spiritual-exercises-adaptation/"
    "forms/charles-coppens-eight-days-six-triduums-1916/editions/"
    "charles-coppens-exercises-1916-pg70790/master.tei.xml"
)
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def select(root: Path, context: dict) -> str | None:
    """Select only the exact staged/installed accepted Coppens generation."""
    identity = context.get("identity")
    if not isinstance(identity, dict) or identity.get("work_id") != IDENTITY["work_id"]:
        return None
    if identity != IDENTITY:
        raise PipelineError("Coppens native profile identity differs")
    accepted = context.get("accepted", {})
    if accepted.get("identity", {}).get("acquisition_id") != ACQUISITION_ID:
        raise PipelineError("Coppens native profile acquisition differs")
    if context.get("authority", {}).get("master", {}).get("sha256") != MASTER_SHA256:
        raise PipelineError("Coppens native profile master differs")
    if context.get("authority", {}).get("master", {}).get("path") != MASTER_PATH:
        raise PipelineError("Coppens native profile master path differs")
    if context.get("language") != "en" or context["edition"].record.get("category") != "prose":
        raise PipelineError("Coppens native profile language/category differs")
    source = accepted.get("source", {})
    if (source.get("source_path") != SOURCE_ARCHIVE_PATH
            or source.get("source_sha256") != SOURCE_ARCHIVE_SHA256
            or source.get("source_bytes") != SOURCE_ARCHIVE_BYTES
            or source.get("source_kind") is not None):
        raise PipelineError("Coppens native profile retained archive binding differs")
    accounting_binding = source.get("accounting")
    if (not isinstance(accounting_binding, dict)
            or accounting_binding.get("path") != ACCEPTANCE_ACCOUNTING_PATH):
        raise PipelineError("Coppens native profile accounting path differs")
    accounting_path = root / ACCEPTANCE_ACCOUNTING_PATH
    raw = io_path(accounting_path).read_bytes()
    if (len(raw) != accounting_binding.get("bytes")
            or hashlib.sha256(raw).hexdigest() != accounting_binding.get("sha256")):
        raise PipelineError("Coppens native profile accounting bytes differ")
    accounting = json.loads(raw)
    if (accounting.get("projection_profile") != PROFILE
            or accounting.get("identity") != identity | {"acquisition_id": ACQUISITION_ID}
            or accounting.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA256
            or accounting.get("source_sha256") != SOURCE_ARCHIVE_SHA256
            or accounting.get("source_bytes") != SOURCE_ARCHIVE_BYTES
            or accounting.get("candidate_package_sha256") != PACKAGE_SHA256
            or accounting.get("source_html_member") != HTML_MEMBER
            or accounting.get("candidate", {}).get("path") != CANDIDATE_PATH
            or accounting.get("candidate", {}).get("sha256") != MASTER_SHA256):
        raise PipelineError("Coppens native profile source/accounting evidence differs")
    manifest_path = root / "sources/manifest-acquisitions/coppens-pg70790-source-native-v5-20261004/source-manifest.json"
    if hashlib.sha256(io_path(manifest_path).read_bytes()).hexdigest() != SOURCE_MANIFEST_SHA256:
        raise PipelineError("Coppens native profile current source manifest differs")
    archive_path = io_path(root / SOURCE_ARCHIVE_PATH)
    if (archive_path.stat().st_size != SOURCE_ARCHIVE_BYTES
            or hashlib.sha256(archive_path.read_bytes()).hexdigest() != SOURCE_ARCHIVE_SHA256):
        raise PipelineError("Coppens native profile retained archive differs")
    if len(accounting.get("support_assets", [])) != 1:
        raise PipelineError("Coppens native profile cover accounting is incomplete")
    asset = accounting["support_assets"][0]
    if (asset.get("member") != COVER["path"]
            or asset.get("bytes") != COVER["bytes"]
            or asset.get("sha256") != COVER["sha256"]
            or asset.get("candidate_path") != ACCEPTANCE_ACCOUNTING_PATH.rsplit("/", 1)[0] + "/images/cover.jpg"
            or asset.get("edition_path") != MASTER_PATH.rsplit("/", 1)[0] + "/images/cover.jpg"
            or asset.get("candidate_and_master_relative_urls_resolved") is not True):
        raise PipelineError("Coppens native profile cover route differs")
    for relative in (
        ACCEPTANCE_ACCOUNTING_PATH.rsplit("/", 1)[0] + "/images/cover.jpg",
        MASTER_PATH.rsplit("/", 1)[0] + "/images/cover.jpg",
    ):
        path = io_path(root / relative)
        if (path.stat().st_size != COVER["bytes"]
                or hashlib.sha256(path.read_bytes()).hexdigest() != COVER["sha256"]):
            raise PipelineError("Coppens native profile local cover bytes differ")
    return PROFILE


def graphic_allowed(node) -> bool:
    """Accept only the one source-pinned retained cover carrier."""
    return (node.tag == NS + "graphic"
            and node.attrib == {"n": "3.2", XML + "id": "img_images_cover.jpg",
                                "rend": "source-class:ig001 source-alt-empty",
                                "url": "images/cover.jpg"}
            and len(node) == 0 and not (node.text or "").strip())


def _shape(root, raw: bytes, identity: dict, language: str, category: str, collection: bool) -> None:
    if (identity != IDENTITY or language != "en" or category != "prose" or collection
            or hashlib.sha256(raw).hexdigest() != MASTER_SHA256):
        raise PipelineError("Coppens native profile exact edition/master binding differs")
    body = root.find(NS + "text/" + NS + "body")
    if body is None or len(body) != 1114 or any(node.tag != NS + "ab" for node in body):
        raise PipelineError("Coppens native profile complete body envelope differs")
    if Counter(node.get("type") for node in body) != BODY_BLOCK_COUNTS:
        raise PipelineError("Coppens native profile source block inventory differs")
    if (body[0].get("type") != "source-header" or body[0].get("n") != "1"
            or body[0].get(XML + "id") != "pg-header"
            or body[-1].get("type") != "source-footer" or body[-1].get("n") != "1114"
            or body[-1].get(XML + "id") != "pg-footer"):
        raise PipelineError("Coppens native profile source header/footer bounds differ")
    milestones = root.findall(".//" + NS + "milestone")
    if (len(milestones) != 1 or milestones[0].attrib != {
            "unit": "source-rule", "n": "4.1", XML + "id": "source-node-4.1", "rend": "source-class:pb c000"}):
        raise PipelineError("Coppens native profile source-rule marker differs")


def check_et(root, raw: bytes, identity: dict, language: str, category: str, collection: bool) -> None:
    _shape(root, raw, identity, language, category, collection)


def check_lxml(root, raw: bytes, identity: dict, language: str, category: str, collection: bool) -> None:
    _shape(root, raw, identity, language, category, collection)
