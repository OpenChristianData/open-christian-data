"""Work-local proposal gate for Fox PG43031's exact source-native reader profile."""
from __future__ import annotations
from collections import Counter
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
from lxml import etree

PROFILE = "ocd-prose-fox-pg43031-source-native-v1"
WORK_ID = "george-fox-autobiography"
IDENTITY = {
    "work_id": WORK_ID,
    "textual_form_id": "george-fox-autobiography-1909-abridged",
    "edition_id": "george-fox-autobiography-jones-1909-pg43031",
}
LANGUAGE = "en"
CATEGORY = "prose"
MASTER_SHA256 = "c4722275a5a517dfc0a0e9e89c8d827e6ccdf30127be39ad7d9da4f145a9a440"
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
UNIT_IDS = (
    "pg43031-provider-and-editorial-front",
    "pg43031-william-penn-testimony",
    "pg43031-contents",
    "pg43031-fox-autobiography",
    "pg43031-editorial-back",
)
BLOCK_COUNTS = {
    "source-blockquote": 48,
    "source-div": 151,
    "source-footer": 1,
    "source-h1": 1,
    "source-h2": 26,
    "source-h3": 21,
    "source-header": 1,
    "source-hr": 42,
    "source-p": 1819,
}
BLOCK_TYPES = frozenset(BLOCK_COUNTS)

def _route_gate(raw, *, identity, language, category, collection, projection_profile):
    if identity.get("work_id") != WORK_ID:
        if projection_profile == PROFILE:
            raise ValueError("Fox profile cannot apply to another work")
        return False
    if (identity != IDENTITY or language != LANGUAGE or category != CATEGORY or collection
            or projection_profile not in (None, PROFILE)
            or hashlib.sha256(raw).hexdigest() != MASTER_SHA256):
        raise ValueError("Fox 43031 source-native reader identity, scope, or master pin differs")
    return True

def _check_inventory(unit_ids, block_types, ids):
    if tuple(unit_ids) != UNIT_IDS:
        raise ValueError("Fox 43031 source-unit census differs")
    if Counter(block_types) != Counter(BLOCK_COUNTS):
        raise ValueError("Fox 43031 source-block type census differs")
    if len(ids) != len(set(ids)) or not set(UNIT_IDS).issubset(ids):
        raise ValueError("Fox 43031 source-node ID ledger differs")

def check_et(root, raw):
    body = root.find(NS + "text/" + NS + "body")
    if body is None:
        raise ValueError("Fox 43031 source body is missing")
    _check_inventory(
        [node.get(XML_ID) for node in list(body)],
        [node.get("type") for node in body.iter(NS + "ab")],
        [node.get(XML_ID) for node in root.iter() if node.get(XML_ID)],
    )

def check_lxml(root, raw):
    body = root.find(NS + "text/" + NS + "body")
    if body is None:
        raise ValueError("observed Fox 43031 source body is missing")
    _check_inventory(
        [node.get(XML_ID) for node in list(body)],
        [node.get("type") for node in body.iter(NS + "ab")],
        [node.get(XML_ID) for node in root.iter() if node.get(XML_ID)],
    )


def route(raw, *, identity, language, category, collection, projection_profile,
          allow_acceptance_metadata):
    if identity.get("work_id") != WORK_ID:
        if projection_profile == PROFILE:
            raise ValueError("Fox profile cannot apply to another accepted work")
        return False
    if (not allow_acceptance_metadata or identity != IDENTITY or language != LANGUAGE
            or category != CATEGORY or collection or projection_profile != PROFILE
            or hashlib.sha256(raw).hexdigest() != MASTER_SHA256):
        raise ValueError("Fox accepted reader requires the exact accepted master and source profile")
    return True
def select_accepted(context, *, category, collection, projection_profile):
    identity = context["identity"]
    if identity.get("work_id") != WORK_ID:
        if projection_profile == PROFILE:
            raise ValueError("Fox profile cannot apply to another accepted work")
        return None
    if (identity != IDENTITY or context.get("language") != LANGUAGE or category != CATEGORY
            or collection or projection_profile not in (None, PROFILE)):
        raise ValueError("Fox accepted-reader identity, language, category, or profile differs")
    raw = Path(context["edition"].path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != MASTER_SHA256:
        raise ValueError("Fox accepted master pin differs")
    return PROFILE

def admit_producer(raw, *, identity, language, category, collection, projection_profile):
    if not _route_gate(raw, identity=identity, language=language, category=category,
                       collection=collection, projection_profile=projection_profile):
        return False
    root = ET.fromstring(raw)
    check_et(root, raw)
    return True

def admit_observer(raw, *, identity, language, category, collection, projection_profile):
    if not _route_gate(raw, identity=identity, language=language, category=category,
                       collection=collection, projection_profile=projection_profile):
        return False
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    check_lxml(root, raw)
    return True