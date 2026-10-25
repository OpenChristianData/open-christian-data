"""Exact accepted PG37311 source-native route for Woolman's Everyman volume."""

from collections import Counter
from hashlib import sha256
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree


PROFILE = "ocd-prose-woolman-pg37311-source-native-v1"
IDENTITY = {
    "work_id": "john-woolman-journal-other-writings",
    "textual_form_id": "english",
    "edition_id": "everyman-402-1910-electronic",
}
ACQUISITION_ID = "gutenberg-37311"
MASTER_SHA256 = "03d1cad51281dd3271b0f32139de2b6aa9265bde39a66a3cbb0a7a42c1f1dc3e"
ACCEPTANCE_SHA256 = "af870ac063be83343508aa1ccf7ee4f16c32c469bdbcd5081556e5f95f41b5c0"
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
UNIT_IDS = (
    "pg37311-volume-front", "pg37311-abridged-journal",
    "pg37311-writings-introduction", "pg37311-pure-wisdom", "pg37311-on-labour",
    "pg37311-on-schools", "pg37311-outward-gifts", "pg37311-harmony",
    "pg37311-epistle", "pg37311-remarks", "pg37311-last-illness",
    "pg37311-provider-footer",
)
BLOCK_COUNTS = {
    "source-p": 872, "source-hr": 54, "source-h3": 36,
    "source-blockquote": 20, "source-h2": 12, "source-div": 7,
    "source-pre": 2, "source-h1": 2,
    "source-header": 1, "source-footer": 1,
}
BLOCK_TYPES = frozenset(BLOCK_COUNTS)
GRAPHICS = {
    "img_images_cover.jpg": ("images/cover.jpg", "3.1"),
    "img_images_illus.jpg": ("images/illus.jpg", "16.1"),
    "img_images_end.jpg": ("images/end.jpg", "1005.1"),
}
TBODY = frozenset({"source-tbody-start", "source-tbody-end"})


def select_accepted(context, *, category, collection, projection_profile):
    identity = context["identity"]
    if identity.get("work_id") != IDENTITY["work_id"]:
        if projection_profile == PROFILE:
            raise ValueError("Woolman source profile cannot apply to another work")
        return None
    accepted = context["accepted"]
    if (identity != IDENTITY or context["language"] != "en" or category != "prose"
            or collection or projection_profile not in (None, PROFILE)
            or accepted["identity"]["acquisition_id"] != ACQUISITION_ID
            or sha256(Path(context["edition"].path).read_bytes()).hexdigest() != MASTER_SHA256
            or sha256(Path(context["acceptance_path"]).read_bytes()).hexdigest() != ACCEPTANCE_SHA256):
        raise ValueError("Woolman accepted identity, acquisition, master, or acceptance differs")
    return PROFILE


def route(raw, *, identity, language, category, collection, projection_profile,
          allow_acceptance_metadata):
    if identity.get("work_id") != IDENTITY["work_id"]:
        if projection_profile == PROFILE:
            raise ValueError("Woolman source profile cannot apply to another work")
        return False
    if (identity != IDENTITY or language != "en" or category != "prose" or collection
            or projection_profile != PROFILE or not allow_acceptance_metadata
            or sha256(raw).hexdigest() != MASTER_SHA256):
        raise ValueError("Woolman source-native route requires its exact accepted master")
    return True


def _inventory(root):
    body = root.find(NS + "text/" + NS + "body")
    if body is None or tuple(node.get(XML_ID) for node in body) != UNIT_IDS:
        raise ValueError("Woolman source-unit order differs")
    if Counter(node.get("type") for node in body.iter(NS + "ab")) != Counter(BLOCK_COUNTS):
        raise ValueError("Woolman source-block census differs")
    ids = [node.get(XML_ID) for node in root.iter() if node.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError("Woolman source-node IDs differ")
    graphics = {node.get(XML_ID): (node.get("url"), node.get("n"))
                for node in body.iter(NS + "graphic")}
    if graphics != GRAPHICS:
        raise ValueError("Woolman source-image references differ")
    markers = [(node.get("unit"), node.get("n")) for node in body.iter(NS + "milestone")]
    if markers != [("source-tbody-start", "52.1"), ("source-tbody-end", "52.1.end")]:
        raise ValueError("Woolman source table boundaries differ")


def check_et(root, raw):
    _inventory(root)


def check_lxml(root, raw):
    _inventory(root)
