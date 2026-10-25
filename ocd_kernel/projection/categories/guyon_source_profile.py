"""Source-bound Guyon reader guard selected through validated acceptance.

The retained v16 candidate is not an accepted edition. The accepted context
supplies the edition identity and live master digest; this policy independently
binds the retained source set, original source header, and entire source text.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree

NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
SOURCE_MANIFEST = Path('sources/manifest-acquisitions/guyon-short-method-pg24989-v16/source-manifest.json')
SOURCE_MANIFEST_SHA = 'f77c6d1fe6c9cf65f4fb6a4f442dc4e2bb742e7343ade3cf4a9f40910e6c84e6'
SOURCE_ID = 'pg24989-l772-l790-retained-witness'
IDENTITY = {
    'work_id': 'jeanne-guyon-short-method-prayer',
    'textual_form_id': 'english',
    'edition_id': 'jeanne-guyon-short-method-prayer-pg24989',
}
ACQUISITION_ID = 'pg24989-retained-zip'
MEMBER_SET_PATH = ('library/works/jeanne-guyon-short-method-prayer/forms/english/'
                   'editions/jeanne-guyon-short-method-prayer-pg24989/source-member-set.json')
MEMBER_SET_BYTES = 2358
MEMBER_SET_SHA = 'dd178e780fae6a51a8d6bebb58343af2830f531f3569496a15f11f8f38e42875'
SOURCE_URL = 'https://www.gutenberg.org/ebooks/24989'
SOURCE_AUTHORITY = {
    'raw/gutenberg/24989/pg24989-h.zip': (123756, 'c07fc7a789cbbc2a8f56b0f8f20949511d1a2c0726f132cafbeae979405736a4'),
    'raw/gutenberg/24989/html/pg24989-images.html': (144002, 'fb4576d4e74f90e087ecf608881c53f127f70d21d2efd75a02762c0f16878cf2'),
    'sources/manifest-acquisitions/guyon-short-method-pg24989-v16/profile.json': (1784, 'a04b30c690da15c2967410d90acd42d20d077a88088beaf9930bdba663b7d99d'),
}
SOURCE_PARAGRAPHS_SHA = 'a0a94848b007670ccd177fa1a3f9bc9302e077dc3476ec9dd439af6ba422431e'
SOURCE_TEXT_SHA = '2413ac4f8c9c30eeb5e2e34b7b6934c534d84f463878e86bde712661d9e59583'
SOURCE_METADATA_N = ('1', '3', '5', '6', '7', '8', '9', '10', '11', '12', '13',
                     '14', '15', '16', '17', '18', '19', '20', '21')


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_source_bindings(root: Path) -> dict:
    """Recheck the exact retained source set; this does not establish acceptance."""
    from ocd_kernel.library._common import io_path

    raw = (root / SOURCE_MANIFEST).read_bytes()
    if _sha(raw) != SOURCE_MANIFEST_SHA:
        raise ValueError('Guyon source manifest differs')
    manifest = json.loads(raw)
    if manifest.get('source_id') != SOURCE_ID:
        raise ValueError('Guyon source identity differs')
    recorded = {row['path']: (row['bytes'], row['sha256'])
                for row in manifest['authorities'] if row['path'] in SOURCE_AUTHORITY}
    if recorded != SOURCE_AUTHORITY:
        raise ValueError('Guyon source manifest authority differs')
    for relative, (length, digest) in SOURCE_AUTHORITY.items():
        path = root / relative
        content = io_path(path).read_bytes() if relative.startswith('raw/') else path.read_bytes()
        if len(content) != length or _sha(content) != digest:
            raise ValueError(f'Guyon retained source differs: {relative}')
    return {'manifest_sha256': SOURCE_MANIFEST_SHA, 'source_id': SOURCE_ID,
            'authorities': SOURCE_AUTHORITY}


def select_accepted(context: dict, *, category: str, collection: bool,
                    projection_profile: str | None) -> dict | None:
    """Select only after the caller has used the maintained validated context."""
    if context['identity'].get('work_id') != IDENTITY['work_id']:
        return None
    from ocd_kernel.library.acquisitions import acquisition_for_edition
    from ocd_kernel.library._common import io_path

    accepted = context['accepted']
    source = accepted.get('source', {})
    if (context['identity'] != IDENTITY or category != 'prose' or collection
            or projection_profile not in (None, 'ocd-prose-guyon-pg24989-v16-source-native-v1')
            or context['language'] != 'en'
            or accepted.get('identity') != {**IDENTITY, 'acquisition_id': ACQUISITION_ID}
            or {key: source.get(key) for key in ('source_kind', 'source_path', 'source_bytes', 'source_sha256')} != {
                'source_kind': 'retained-member-set', 'source_path': MEMBER_SET_PATH,
                'source_bytes': MEMBER_SET_BYTES, 'source_sha256': MEMBER_SET_SHA,
            }
            or source.get('missing_members') != [] or source.get('unknown_members') != []):
        raise ValueError('Guyon accepted identity or source-member-set authority differs')
    root = context['root']
    acquisition_path, acquisition = acquisition_for_edition(
        root, IDENTITY['work_id'], IDENTITY['edition_id'], acquisition_id=ACQUISITION_ID)
    if (acquisition.get('acquisition_id') != ACQUISITION_ID
            or acquisition.get('source_kind') != 'retained-member-set'
            or acquisition.get('source_path') != MEMBER_SET_PATH
            or acquisition.get('source_bytes') != MEMBER_SET_BYTES
            or acquisition.get('source_sha256') != MEMBER_SET_SHA
            or acquisition.get('url') != SOURCE_URL
            or context['authority']['acquisition']['sha256'] != _sha(io_path(acquisition_path).read_bytes())):
        raise ValueError('Guyon accepted acquisition authority differs')
    members = io_path(root / MEMBER_SET_PATH).read_bytes()
    if len(members) != MEMBER_SET_BYTES or _sha(members) != MEMBER_SET_SHA:
        raise ValueError('Guyon retained member-set bytes differ')
    check_source_bindings(root)
    master_digest = context['authority']['master']['sha256']
    if _sha(io_path(context['edition'].path).read_bytes()) != master_digest:
        raise ValueError('Guyon validated accepted master changed')
    return {'master_sha256': master_digest, 'source_manifest_sha256': SOURCE_MANIFEST_SHA,
            'source_text_sha256': SOURCE_TEXT_SHA}


def _text_signature_et(node: ET.Element):
    return [node.tag, sorted(node.attrib.items()), node.text or '', node.tail or '',
            [_text_signature_et(child) for child in node]]


def check_text_et(root: ET.Element) -> dict:
    """Require the exact source text/envelope; the accepted header may differ."""
    text = root.find(NS+'text')
    if (root.tag != NS+'TEI' or root.attrib != {XML+'id': 'pg24989-complete-edition'}
            or [child.tag for child in root] != [NS+'teiHeader', NS+'text']
            or text is None or text.attrib or [child.tag for child in text] != [NS+'body']
            or text[0].attrib or [child.tag for child in text[0]] != [NS+'div']
            or text[0][0].get('type') != 'source-body'
            or text[0][0].get(XML+'id') != 'source-body'):
        raise ValueError('Guyon accepted source envelope differs')
    digest = _sha(json.dumps(_text_signature_et(text), ensure_ascii=False,
                             separators=(',', ':')).encode())
    if digest != SOURCE_TEXT_SHA:
        raise ValueError('Guyon accepted source text differs')
    return {'source_text_sha256': digest, 'source_text_nodes': sum(1 for _ in text.iter())}


def _text_signature_lxml(node: etree._Element):
    return [str(node.tag), sorted((str(k), str(v)) for k, v in node.attrib.items()),
            str(node.text or ''), str(node.tail or ''),
            [_text_signature_lxml(child) for child in node]]


def check_text_lxml(root: etree._Element) -> dict:
    text = root.find(NS+'text')
    if (root.tag != NS+'TEI' or dict(root.attrib) != {XML+'id': 'pg24989-complete-edition'}
            or [child.tag for child in root] != [NS+'teiHeader', NS+'text']
            or text is None or dict(text.attrib) or [child.tag for child in text] != [NS+'body']
            or dict(text[0].attrib) or [child.tag for child in text[0]] != [NS+'div']
            or text[0][0].get('type') != 'source-body'
            or text[0][0].get(XML+'id') != 'source-body'):
        raise ValueError('observed Guyon accepted source envelope differs')
    digest = _sha(json.dumps(_text_signature_lxml(text), ensure_ascii=False,
                             separators=(',', ':')).encode())
    if digest != SOURCE_TEXT_SHA:
        raise ValueError('observed Guyon accepted source text differs')
    return {'source_text_sha256': digest, 'source_text_nodes': sum(1 for _ in text.iter())}


def _source_paragraphs_et(source_desc: ET.Element, *, accepted: bool) -> list[ET.Element]:
    paragraphs = []
    bindings = 0
    for child in source_desc:
        if child.tag == NS+'bibl' and child.get('type') == 'ocd-acceptance-binding':
            bindings += 1
        elif (child.tag == NS+'p' and not child.attrib and len(child) == 1
              and child[0].tag == NS+'bibl'
              and child[0].get('type') == 'ocd-acceptance-binding'
              and not (child.text or '').strip() and not (child[0].tail or '').strip()):
            bindings += 1
        elif child.tag == NS+'p':
            paragraphs.append(child)
        else:
            raise ValueError('Guyon sourceDesc has an unknown sibling')
    if len(paragraphs) != 21 or bindings != int(accepted):
        raise ValueError('Guyon sourceDesc paragraph or accepted binding count differs')
    return paragraphs


def check_header_et(root: ET.Element, *, accepted: bool) -> dict:
    """Producer-side private sourceDesc census, including all nested source text."""
    source_desc = root.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc')
    if source_desc is None:
        raise ValueError('Guyon sourceDesc is absent')
    paragraphs = _source_paragraphs_et(source_desc, accepted=accepted)

    def signature(node: ET.Element, include_tail: bool = True):
        return [node.tag, sorted(node.attrib.items()), node.text or '',
                (node.tail or '') if include_tail else '',
                [signature(child) for child in node]]

    digest = _sha(json.dumps([signature(p, False) for p in paragraphs],
                             ensure_ascii=False, separators=(',', ':')).encode())
    metadata = tuple(p[0].get('n') for p in paragraphs if len(p)
                     and p[0].get('type') == 'source-head-metadata')
    if digest != SOURCE_PARAGRAPHS_SHA or metadata != SOURCE_METADATA_N:
        raise ValueError('Guyon retained private source header differs')
    return {'source_paragraphs': 21, 'source_metadata': 19,
            'source_paragraphs_sha256': digest, 'accepted_binding_count': int(accepted)}


def source_header_nodes_et(root: ET.Element) -> set[ET.Element]:
    check_header_et(root, accepted=True)
    source_desc = root.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc')
    if source_desc is None:
        raise ValueError('Guyon sourceDesc is absent')
    return {node for paragraph in _source_paragraphs_et(source_desc, accepted=True)
            for node in paragraph.iter()}


def _source_paragraphs_lxml(source_desc: etree._Element, *, accepted: bool) -> list[etree._Element]:
    paragraphs = []
    binding_count = 0
    for child in source_desc:
        if child.tag == NS+'bibl' and child.get('type') == 'ocd-acceptance-binding':
            binding_count += 1
        elif (child.tag == NS+'p' and dict(child.attrib) == {} and len(child) == 1
              and child[0].tag == NS+'bibl'
              and child[0].get('type') == 'ocd-acceptance-binding'
              and not (child.text or '').strip() and not (child[0].tail or '').strip()):
            binding_count += 1
        elif child.tag == NS+'p':
            paragraphs.append(child)
        else:
            raise ValueError('observed Guyon sourceDesc sibling differs')
    if len(paragraphs) != 21 or binding_count != int(accepted):
        raise ValueError('observed Guyon sourceDesc count differs')
    return paragraphs


def check_header_lxml(root: etree._Element, *, accepted: bool) -> dict:
    """Observer-side sourceDesc census, independently traversed with lxml."""
    source_desc = root.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc')
    if source_desc is None:
        raise ValueError('observed Guyon sourceDesc is absent')
    paragraphs = _source_paragraphs_lxml(source_desc, accepted=accepted)

    def signature(node: etree._Element, include_tail: bool = True):
        children = [signature(child) for child in node]
        return [str(node.tag), sorted((str(k), str(v)) for k, v in node.attrib.items()),
                str(node.text or ''), str(node.tail or '') if include_tail else '', children]

    digest = _sha(json.dumps([signature(p, False) for p in paragraphs],
                             ensure_ascii=False, separators=(',', ':')).encode())
    numbers = tuple(p[0].get('n') for p in paragraphs if len(p)
                    and p[0].get('type') == 'source-head-metadata')
    if digest != SOURCE_PARAGRAPHS_SHA or numbers != SOURCE_METADATA_N:
        raise ValueError('observed Guyon retained private source header differs')
    return {'source_paragraphs': 21, 'source_metadata': 19,
            'source_paragraphs_sha256': digest, 'accepted_binding_count': int(accepted)}


def source_header_nodes_lxml(root: etree._Element) -> set[etree._Element]:
    check_header_lxml(root, accepted=True)
    source_desc = root.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc')
    if source_desc is None:
        raise ValueError('observed Guyon sourceDesc is absent')
    return {node for paragraph in _source_paragraphs_lxml(source_desc, accepted=True)
            for node in paragraph.iter()}
