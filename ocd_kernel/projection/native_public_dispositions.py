"""Closed public dispositions for selected accepted Gutenberg works.

The maintained accepted-prose route selects these source-bound mappings before
receipt output hashing. ET producer and lxml observer validate independently;
the original TEI and private inventory remain intact.
"""
from __future__ import annotations

from copy import deepcopy
import base64
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import quote, unquote
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path

TEI = '{http://www.tei-c.org/ns/1.0}'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
ANNOTATION = 'urn:ocd:pg49917:source-marker:'
PRIVATE_PAGE = 'raw/gutenberg/77576/html/pg77576-images.html#Page_141'
PUBLIC_PAGE = 'source-page:141'
COMMENT_PUBLIC = 'source-comment-retained-privately'
STYLE_PUBLIC = 'source-presentation-style-omitted'
PROSE_MAPPING_VERSION = 'ocd-prose-native-v3+ocd-public-dispositions-v1'
WHITEFIELD_WORK = 'george-whitefield-works'
COX_WORK = 'cox-sacred-hymns-from-the-german-1841'
COX_MAPPING_VERSION = 'ocd-poetry-native-v2+ocd-cox-opaque-annotations-v1'
COX_MASTER = 'b55298b1597c740d2c4d682bb035b1a61f879e59914091195731c67a5a549141'
COX_SOURCE = '638f615c16fddc08b8bb4f803816b67ae73e0827c9a975816fe64560af540305'
COX_MANIFEST = '5a1510569059907ac5709ebe8d0d01db6dc667e13ac0307b4a402459d513624b'
COX_PRIVATE_ROWS = '8c7320d3900d765e48ac646d0d137e7ea038b22a4c3d9f0ac98366ecc4ba105f'
COX_SOURCE_PREFIX = 'urn:ocd:cox-pg39440:'
COX_ALIAS_PREFIX = 'source-annotation:'
COX_SOURCE_CLASSES = {'unit': 125, 'source': 6343, 'division-flow': 1218, 'flow': 46}
COX_ROW_CLASSES = {'unit': 125, 'source': 6547, 'division-flow': 1218, 'flow': 46}
COX_IDENTITY = {
    'work_id': COX_WORK,
    'textual_form_id': 'german-english',
    'edition_id': 'cox-sacred-hymns-1841-pg39440',
    'acquisition_id': 'pg39440-retained-html',
}
COX_EDITION = ('library/works/cox-sacred-hymns-from-the-german-1841/forms/'
               'german-english/editions/cox-sacred-hymns-1841-pg39440')
COX_SOURCE_PATH = 'raw/gutenberg/39440/html/pg39440-images.html'
COX_MANIFEST_PATH = COX_EDITION + '/acquisitions/pg39440-retained-html.json'
WHITEFIELD_MAPPING_VERSION = 'ocd-prose-native-v3+ocd-whitefield-media-aliases-v1'
WHITEFIELD_MASTER = 'dd40ccf073688af11a28a788b38667365eb8646c1a792dd5db85bbba2a6f101e'
WHITEFIELD_SOURCE_SET = 'e00fe455983034c6e9d63dc371d8603283fd2e280281523219b1d5ec0d474b26'
WHITEFIELD_MANIFEST = '2b530395dd46d406db5712b0e4e42ec64a8616ea2511b8ce80e0d36957ff4ed8'
WHITEFIELD_IDENTITY = {
    'work_id': WHITEFIELD_WORK,
    'textual_form_id': 'george-whitefield-works-english',
    'edition_id': 'whitefield-works-1771-vols-i-iii-electronic',
    'acquisition_id': 'whitefield-retained-i-iii-source-set',
}
WHITEFIELD_EDITION = ('library/works/george-whitefield-works/forms/'
                      'george-whitefield-works-english/editions/'
                      'whitefield-works-1771-vols-i-iii-electronic')
WHITEFIELD_MEMBER_SET_PATH = ('library/works/george-whitefield-works/integration/'
                              'l646-source-bound-v3/complete-source-member-set.json')
WHITEFIELD_IMAGES = (
    ('v1-img_images_cover.jpg', 'Book Cover', 'figure', 3589299, '7ff356e360c03d9fc75c596ad6575805ace9f10ebc6bb73fccdd4a8f6a5d34d8', '6042ad5a1f41c42c171742d3e3a52466d5e7aa65bf44693ccda060882fb97061'),
    ('v1-img_images_frontispiece.jpg', None, 'ref', 1823991, '49d9e71519788af93450210418841badc713734f4d70aa248c321450dafa851f', '6c84f332fa9aa708d5b327538b85a3e5f226d78152ebbf8990df052e8ebcd258'),
    ('v2-img_images_whitefield2.jpg', '(\u2021 Book Cover)', 'figure', 3590539, '4195de114824e608de33e7c8c72d0fe695ceb0cf4a3f03de8c455e60b723f255', 'dbd9d6a00d309300d526bb489dfa726eddf7d14c87431662df9b541ea094a1b0'),
    ('v3-img_images_cover.jpg', '(\u2021 Book Cover)', 'figure', 337247, '4f6e3bc2636731031861cc502d91c0d4a228555e3a86eb9191d1f09a9fc207d2', '14358f59a131e0d3cdd016c1d65b330b960a01de415d8deed9d9c8d495595277'),
    ('v3-img_images_i_430b.jpg', '(\u2021 floor plan of Orphan-house)', 'ref', 284491, '68e113ebe1c67e548cca59c0ce9b2741581a0704db1cb1f97fe3ebf14f9c6d6d', '5b53b1cf3caeeecd650637102398bd6b209a066ebb481a0f85dff20b87956d26'),
    ('v3-img_images_brace_rt.png', '}', 'cell', 354, '49e01fde0003db16d0852af4c4b70c0b9ecd0ef1c22124c6f6caf01fc79d2666', 'd5d691b9271798786c42e3ad3a559c7308b9b82d56b3a966eecf230ab2f77c4d'),
    ('v3-img_images_brace_rt.png_1', '}', 'cell', 354, '49e01fde0003db16d0852af4c4b70c0b9ecd0ef1c22124c6f6caf01fc79d2666', 'd5d691b9271798786c42e3ad3a559c7308b9b82d56b3a966eecf230ab2f77c4d'),
    ('v3-img_images_brace_rt.png_2', '}', 'cell', 354, '49e01fde0003db16d0852af4c4b70c0b9ecd0ef1c22124c6f6caf01fc79d2666', 'd5d691b9271798786c42e3ad3a559c7308b9b82d56b3a966eecf230ab2f77c4d'),
    ('v3-img_images_i_494b.jpg', '(\u2021 Sketch of Land plot)', 'ref', 339995, '319ef2f57aa6b63d877a8b08afad3e68c0ac09047bcd2c0615bb73258a4af1bc', '249553d0d15feb6415c42f50d0c5162c2a35078443b6b60a2dad3e9e71b952ae'),
)



NEWMAN_WORK = 'newman-parochial-sermons'
NEWMAN_MASTER = 'a5de6d99f4725b509139fccdb5cec5af22728a958b28aa617a1c56bdf221d3ff'
NEWMAN_IDENTITY = {'work_id': NEWMAN_WORK,
                   'textual_form_id': 'newman-parochial-gutenberg-english',
                   'edition_id': 'newman-parochial-sermons-pg-vii-viii-retained-electronic'}
NEWMAN_MARKER = 'urn:ocd:newman-parochial:underscore-delimited'
NEWMAN_MAPPING_VERSION = 'ocd-sermons-newman-pg-vii-viii-public-annotation-v1'
_NEWMAN_BASE = 'library/works/' + NEWMAN_WORK
_NEWMAN_EDITION = _NEWMAN_BASE + '/forms/' + NEWMAN_IDENTITY['textual_form_id'] + '/editions/' + NEWMAN_IDENTITY['edition_id']
_NEWMAN_MEMBER_SET = _NEWMAN_BASE + '/integration/retained-pg-vii-viii-20261004-v1/one-work-v1/source-member-set.json'
_NEWMAN_SOURCE = '86811f5039213e18b65e6f3ae0e77160c724e9ad625fead98978088c01aa4447'
_NEWMAN_ACQUISITION = 'newman-parochial-sermons-pg-vii-viii-acquired-member-set'
_NEWMAN_MANIFEST = _NEWMAN_EDITION + '/acquisitions/' + _NEWMAN_ACQUISITION + '.json'
_NEWMAN_MANIFEST_SHA = 'fa1ed2d436c22d28140d44fbd8d1ee1d0d768fd1be2f8396b0bd1231aa7cb323'


def _newman_source_et(raw: bytes) -> list[str]:
    if _sha(raw) != NEWMAN_MASTER:
        raise PipelineError('Newman public annotation master differs')
    root = ET.fromstring(raw)
    marked = [node for node in root.iter() if node.get('ana') == NEWMAN_MARKER]
    if len(marked) != 386 or any(node.tag != TEI+'hi' or dict(node.attrib) !=
                                {'rend': 'italic', 'ana': NEWMAN_MARKER} for node in marked):
        raise PipelineError('Newman source italic annotation census differs')
    return [''.join(node.itertext()) for node in marked]


def _newman_source_lxml(raw: bytes) -> list[str]:
    if sha256(raw).hexdigest() != NEWMAN_MASTER:
        raise ValueError('observed Newman annotation master differs')
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    markers = root.xpath('//*[@ana=$marker]', marker=NEWMAN_MARKER)
    if len(markers) != 386:
        raise ValueError('observed Newman annotation count differs')
    for node in markers:
        if (etree.QName(node).namespace != TEI[1:-1] or etree.QName(node).localname != 'hi'
                or set(node.attrib) != {'rend', 'ana'} or node.get('rend') != 'italic'):
            raise ValueError('observed Newman italic carrier differs')
    return [''.join(node.itertext()) for node in markers]


def _newman_project_rows(rows: list[dict], raw: bytes) -> list[dict]:
    source = _newman_source_et(raw)
    public = deepcopy(rows)
    found = []
    per_row = []
    def readable(node):
        return node['text'] if node.get('kind') == 'text' else ''.join(readable(child) for child in node.get('content', []))
    def visit(value):
        if isinstance(value, list):
            for child in value: visit(child)
        elif isinstance(value, dict):
            attrs = value.get('attributes')
            if isinstance(attrs, dict) and attrs.get('source_annotations') == NEWMAN_MARKER:
                if value.get('kind') != 'emphasis' or attrs != {'style': 'italic', 'source_annotations': NEWMAN_MARKER}:
                    raise PipelineError('Newman projected annotation carrier differs')
                found.append(readable(value))
                del attrs['source_annotations']
            for child in value.values(): visit(child)
    if len(public) != 2:
        raise PipelineError('Newman public annotation requires both volume rows')
    for row in public:
        if any(row.get(key) != value for key, value in NEWMAN_IDENTITY.items()) or row.get('language') != 'en':
            raise PipelineError('Newman projected row identity differs')
        before = len(found)
        visit(row)
        per_row.append(len(found)-before)
    if per_row != [197, 189] or found != source:
        raise PipelineError('Newman projected italic annotation order/text differs')
    return public


def _newman_observe_rows(rows: list[dict], raw: bytes) -> list[dict]:
    source_text = _newman_source_lxml(raw)
    expected = deepcopy(rows)
    observations = []
    counts = []
    def visible(node):
        if node.get('kind') == 'text': return node['text']
        return ''.join(visible(child) for child in node.get('content', []))
    def observe(value):
        if isinstance(value, dict):
            attributes = value.get('attributes')
            if isinstance(attributes, dict) and attributes.get('source_annotations') == NEWMAN_MARKER:
                if (value.get('kind') != 'emphasis' or set(attributes) != {'style', 'source_annotations'}
                        or attributes['style'] != 'italic'):
                    raise ValueError('observed Newman public annotation style/kind differs')
                observations.append(visible(value))
                attributes.pop('source_annotations')
            for child in value.values(): observe(child)
        elif isinstance(value, list):
            for child in value: observe(child)
    if len(expected) != 2:
        raise ValueError('observed Newman public volume count differs')
    for index in range(len(expected)):
        row = expected[index]
        if {key: row.get(key) for key in NEWMAN_IDENTITY} != NEWMAN_IDENTITY or row.get('language') != 'en':
            raise ValueError('observed Newman row identity differs')
        start = len(observations)
        observe(row)
        counts.append(len(observations)-start)
    if counts != [197, 189] or observations != source_text:
        raise ValueError('observed Newman annotation sequence/text differs')
    return expected


def mapping_version(work: str | None) -> str:
    if work == NEWMAN_WORK:
        return NEWMAN_MAPPING_VERSION
    if work == COX_WORK:
        return COX_MAPPING_VERSION
    return WHITEFIELD_MAPPING_VERSION if work == WHITEFIELD_WORK else PROSE_MAPPING_VERSION
OMITTED = 'presentation-style-omitted-sha256:4d524dc3cba160cd5649028baa7d4174cf30a15278a4d08504d2d3baaf2db8bc'

_SPECS = {
    'pg49917-assumption-sermon-i': {
        'master': 'd888df20a5eaf43429bd0f52c3369b6f1abc79936007d4921cf94e91a99c426b',
        'revision': 'pg49917-assumption-sermon-i-accepted-20261003-v1',
        'manifest': 'c7a286bcb05021727c156eaacba6be2fd8e0a3d8af2373bc9fb0ed944ed95e9d',
        'source': 'a517174360b8c13609b74c005965f1386e6a0cc0f97fd795d248ccb496944204',
        'comment': 'comment-digest:2e9da984f99e53da97f60626aee67570dd4ea219018ca9726e6ad946315c992f',
        'comment_n': '1221', 'style_ns': tuple(map(str, range(2538, 2623, 12))),
    },
    'pg49917-assumption-sermon-ii': {
        'master': 'acd499fc37a113405c22136086c466d81f33a05944955b2378be4c7904221062',
        'revision': 'pg49917-assumption-sermon-ii-accepted-20261003-v1',
        'manifest': 'd1e82dffdab5a814f8553a0db4d4405d2e552699acc4d7f5fcede0c01de35077',
        'source': 'a517174360b8c13609b74c005965f1386e6a0cc0f97fd795d248ccb496944204',
        'comment': 'comment-digest:0348bcd6b351987f7145ebdd5edc6ec3c38289e40f8d1bc8fd10dd193f99e1dc',
        'comment_n': '1408', 'style_ns': tuple(map(str, range(2634, 2731, 12))),
    },
    'pg77576-ignatius-romans': {
        'master': 'a7d4340952bda7986880426921d56a41c08bb0cd5d6822cac838d6d1b6163bd1',
        'revision': 'pg77576-ignatius-romans-accepted-20261002-v1',
        'manifest': 'bc9409b860e4b4aac4812c09cd8bd08ba3ba556c7b8b3919828c87deccd6f192',
        'source': 'ca58049f2ee7c62c8c34dffb6badfdb910ab698748f8decc9d9b978e7972e507',
    },
    'pg77576-ignatius-polycarp': {
        'master': 'e923e6e0d4b98007680da16bf8e2de69c5ac18146f5f5ec50dcab2795e3063f5',
        'revision': 'pg77576-ignatius-polycarp-accepted-20261002-v1',
        'manifest': '26361e0415b13cf4e4b29b52c40856925b54ac3de7db226e33a499a38593c944',
        'source': 'ca58049f2ee7c62c8c34dffb6badfdb910ab698748f8decc9d9b978e7972e507',
    },
}


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def select(root: Path, identity: dict, accepted: dict, master_raw: bytes, *,
           category: str, collection: bool, projection_profile: str | None,
           allow_acceptance_metadata: bool) -> str | None:
    """Known work with changed authority fails; unknown work stays generic."""
    work = identity.get('work_id')
    if work != NEWMAN_WORK and (_sha(master_raw) == NEWMAN_MASTER
                                or accepted.get('source', {}).get('source_path') == _NEWMAN_MEMBER_SET):
        raise PipelineError('Newman retained source requires its exact work identity')
    if work == NEWMAN_WORK and (
            identity.get('edition_id') == NEWMAN_IDENTITY['edition_id']
            or accepted.get('source', {}).get('source_path') == _NEWMAN_MEMBER_SET
            or _sha(master_raw) == NEWMAN_MASTER):
        source = accepted.get('source', {})
        manifest = source.get('source_manifest', {})
        member_raw = io_path(root / _NEWMAN_MEMBER_SET).read_bytes()
        manifest_raw = io_path(root / _NEWMAN_MANIFEST).read_bytes()
        if (identity != NEWMAN_IDENTITY
                or accepted.get('identity') != {**NEWMAN_IDENTITY, 'acquisition_id': _NEWMAN_ACQUISITION}
                or accepted.get('representation_revision', {}).get('id') != 'newman-parochial-sermons-one-work-pg-vii-viii-accepted-20261004-v1'
                or category != 'sermons' or not collection or projection_profile is not None
                or not allow_acceptance_metadata or _sha(master_raw) != NEWMAN_MASTER
                or accepted.get('promotion', {}).get('master') != {'path': _NEWMAN_EDITION+'/master.tei.xml', 'sha256': NEWMAN_MASTER, 'bytes': len(master_raw)}
                or source.get('source_kind') != 'retained-member-set'
                or source.get('source_path') != _NEWMAN_MEMBER_SET
                or source.get('source_sha256') != _NEWMAN_SOURCE
                or source.get('source_bytes') != len(member_raw) or _sha(member_raw) != _NEWMAN_SOURCE
                or manifest != {'path': _NEWMAN_MANIFEST, 'sha256': _NEWMAN_MANIFEST_SHA, 'bytes': len(manifest_raw)}
                or _sha(manifest_raw) != _NEWMAN_MANIFEST_SHA):
            raise PipelineError('Newman public annotation authority differs')
        return NEWMAN_WORK
    if work != COX_WORK and (
            _sha(master_raw) == COX_MASTER
            or accepted.get('source', {}).get('source_path') == COX_SOURCE_PATH
            or accepted.get('source', {}).get('source_manifest', {}).get('path') == COX_MANIFEST_PATH):
        raise PipelineError('Cox source authority requires its exact work identity')
    if work == COX_WORK:
        promoted = accepted.get('promotion', {}).get('master', {})
        source = accepted.get('source', {})
        manifest = source.get('source_manifest', {})
        source_raw = io_path(root / COX_SOURCE_PATH).read_bytes()
        manifest_raw = io_path(root / COX_MANIFEST_PATH).read_bytes()
        if (identity != {k: COX_IDENTITY[k] for k in ('work_id', 'textual_form_id', 'edition_id')}
                or accepted.get('identity') != COX_IDENTITY
                or accepted.get('acceptance_id') !=
                    'cox-sacred-hymns-1841-pg39440-acceptance-cox-retained-accepted-20261004-v1'
                or accepted.get('representation_revision', {}).get('id') != 'cox-retained-accepted-20261004-v1'
                or category != 'poetry' or collection or projection_profile is not None
                or not allow_acceptance_metadata or _sha(master_raw) != COX_MASTER
                or promoted != {'path': COX_EDITION + '/master.tei.xml',
                                'sha256': COX_MASTER, 'bytes': len(master_raw)}
                or source.get('source_path') != COX_SOURCE_PATH
                or source.get('source_sha256') != COX_SOURCE
                or source.get('source_bytes') != len(source_raw)
                or _sha(source_raw) != COX_SOURCE
                or manifest != {'path': COX_MANIFEST_PATH,
                                'sha256': COX_MANIFEST, 'bytes': len(manifest_raw)}
                or _sha(manifest_raw) != COX_MANIFEST):
            raise PipelineError('Cox public annotation authority differs')
        return COX_WORK
    if work == WHITEFIELD_WORK:
        acquisition_path = WHITEFIELD_EDITION + '/acquisitions/whitefield-retained-i-iii-source-set.json'
        promoted = accepted.get('promotion', {}).get('master', {})
        source = accepted.get('source', {})
        source_manifest = source.get('source_manifest', {})
        member_set_raw = io_path(root / WHITEFIELD_MEMBER_SET_PATH).read_bytes()
        manifest_raw = io_path(root / acquisition_path).read_bytes()
        if (identity != {k: WHITEFIELD_IDENTITY[k] for k in ('work_id', 'textual_form_id', 'edition_id')}
                or accepted.get('identity') != WHITEFIELD_IDENTITY
                or accepted.get('representation_revision', {}).get('id') != 'whitefield-works-i-iii-accepted-20261004-v1'
                or category != 'prose' or collection or projection_profile is not None
                or not allow_acceptance_metadata or _sha(master_raw) != WHITEFIELD_MASTER
                or promoted.get('path') != WHITEFIELD_EDITION + '/master.tei.xml'
                or promoted.get('sha256') != WHITEFIELD_MASTER
                or promoted.get('bytes') != len(master_raw)
                or source.get('source_path') != WHITEFIELD_MEMBER_SET_PATH
                or source.get('source_sha256') != WHITEFIELD_SOURCE_SET
                or source.get('source_bytes') != len(member_set_raw)
                or _sha(member_set_raw) != WHITEFIELD_SOURCE_SET
                or source_manifest.get('path') != acquisition_path
                or source_manifest.get('sha256') != WHITEFIELD_MANIFEST
                or source_manifest.get('bytes') != len(manifest_raw)
                or _sha(manifest_raw) != WHITEFIELD_MANIFEST):
            raise PipelineError('Whitefield public media authority differs')
        member_set = json.loads(member_set_raw)
        members = member_set.get('members')
        included = accepted.get('scope', {}).get('included_members')
        expected = accepted.get('scope', {}).get('expected_members')
        if (not isinstance(members, list) or len(members) != 19
                or not isinstance(included, list) or len(included) != 19
                or not isinstance(expected, list) or len(expected) != 19):
            raise PipelineError('Whitefield public media member count differs')
        for position, (member, bound, planned) in enumerate(zip(members, included, expected, strict=True), 1):
            path = member.get('path')
            if (path != bound.get('path') or path != planned.get('path')
                    or member.get('sha256') != bound.get('sha256')
                    or member.get('bytes') != bound.get('bytes')
                    or member.get('position') != position
                    or bound.get('position') != position
                    or planned.get('position') != position
                    or not isinstance(path, str) or not path.startswith('raw/gutenberg/')
                    or _sha(io_path(root / path).read_bytes()) != member['sha256']):
                raise PipelineError('Whitefield public media retained member differs')
        return WHITEFIELD_WORK
    spec = _SPECS.get(work)
    if spec is None:
        return None
    source_number = '49917' if work.startswith('pg49917-') else '77576'
    edition = f'{work}-pg{source_number}-edition'
    form = f'{work}-english'
    expected_identity = {'work_id': work, 'textual_form_id': form, 'edition_id': edition}
    expected_accepted_identity = {**expected_identity, 'acquisition_id': f'{work}-pg{source_number}-acquisition'}
    source_path = f'raw/gutenberg/{source_number}/html/pg{source_number}-images.html'
    manifest_path = (f'library/works/{work}/forms/{form}/editions/{edition}/acquisitions/'
                     f'{work}-pg{source_number}-acquisition.json')
    master_path = f'library/works/{work}/forms/{form}/editions/{edition}/master.tei.xml'
    source = accepted.get('source', {})
    manifest = source.get('source_manifest', {})
    promoted = accepted.get('promotion', {}).get('master', {})
    manifest_raw = io_path(root / manifest_path).read_bytes()
    retained_raw = io_path(root / source_path).read_bytes()
    if (identity != expected_identity or accepted.get('identity') != expected_accepted_identity
            or accepted.get('representation_revision', {}).get('id') != spec['revision']
            or category != 'prose' or collection or projection_profile is not None
            or not allow_acceptance_metadata or _sha(master_raw) != spec['master']
            or promoted.get('path') != master_path or promoted.get('sha256') != spec['master']
            or promoted.get('bytes') != len(master_raw)
            or source.get('source_path') != source_path or source.get('source_sha256') != spec['source']
            or manifest.get('path') != manifest_path or manifest.get('sha256') != spec['manifest']
            or manifest.get('bytes') != len(manifest_raw)
            or _sha(manifest_raw) != spec['manifest']
            or source.get('source_bytes') != len(retained_raw)
            or _sha(retained_raw) != spec['source']):
        raise PipelineError(f'{work} public disposition authority differs')
    return work


def _rules(work: str) -> dict[str, tuple[str, str, str]]:
    spec = _SPECS[work]
    return {spec['comment_n']: (spec['comment'], 'source-html-comment', COMMENT_PUBLIC),
            **{number: (OMITTED, 'source-html-tbody', STYLE_PUBLIC)
               for number in spec['style_ns']}}


def _distinct(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate source annotation key')
        value[key] = item
    return value


def _annotation(annotation: str, number: str, token: str, unit: str) -> dict:
    if not isinstance(annotation, str) or not annotation.startswith(ANNOTATION):
        raise ValueError('source marker annotation prefix differs')
    encoded = annotation[len(ANNOTATION):]
    try:
        detail = json.loads(unquote(encoded, errors='strict'), object_pairs_hook=_distinct)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('source marker annotation cannot be decoded') from exc
    keys = ['unit', 'n'] + ([XML_ID] if unit == 'source-html-tbody' else []) + ['rend']
    if (not isinstance(detail, dict) or list(detail) != keys
            or detail['unit'] != unit or detail['n'] != number or detail['rend'] != token
            or unit == 'source-html-tbody' and detail[XML_ID] != f'source-node-{number}'
            or quote(json.dumps(detail, ensure_ascii=False, separators=(',', ':')), safe='') != encoded):
        raise ValueError('source marker annotation shape/value differs')
    return detail


def _observed_annotation(annotation: str, number: str, token: str, unit: str) -> dict:
    """Independently decode and validate the observed URI payload."""
    if not isinstance(annotation, str) or not annotation.startswith(ANNOTATION):
        raise ValueError('observed marker annotation prefix differs')
    payload = annotation.removeprefix(ANNOTATION)
    def unique(items):
        names = set()
        for name, _ in items:
            if name in names:
                raise ValueError('observed duplicate annotation key')
            names.add(name)
        return dict(items)
    try:
        detail = json.loads(unquote(payload, errors='strict'), object_pairs_hook=unique)
    except (UnicodeError, ValueError) as exc:
        raise ValueError('observed marker annotation decode differs') from exc
    expected_names = ('unit', 'n', 'rend') if unit == 'source-html-comment' else (
        'unit', 'n', XML_ID, 'rend')
    if (not isinstance(detail, dict) or tuple(detail) != expected_names
            or detail.get('unit') != unit or detail.get('n') != number
            or detail.get('rend') != token
            or unit == 'source-html-tbody' and detail.get(XML_ID) != 'source-node-'+number
            or payload != quote(json.dumps(detail, separators=(',', ':'), ensure_ascii=False), safe='')):
        raise ValueError('observed marker annotation fields differ')
    return detail


def _whitefield_source_et(raw: bytes) -> None:
    root = ET.fromstring(raw)
    parents = {child: parent for parent in root.iter() for child in parent}
    images = list(root.iter(TEI+'graphic'))
    if len(images) != len(WHITEFIELD_IMAGES):
        raise PipelineError('Whitefield source image reference count differs')
    for node, (source_id, label, parent_name, length, uri_digest, asset_digest) in zip(images, WHITEFIELD_IMAGES, strict=True):
        uri = node.get('url') or ''
        mime = 'png' if source_id.startswith('v3-img_images_brace_rt.png') else 'jpeg'
        attrs = {XML_ID: source_id, 'url': uri}
        if label is not None:
            attrs['n'] = label
        if (node.attrib != attrs or len(node) or (node.text or '').strip()
                or parents[node].tag != TEI+parent_name
                or len(uri) != length or _sha(uri.encode()) != uri_digest
                or not uri.startswith(f'data:image/{mime};base64,')):
            raise PipelineError('Whitefield source image carrier differs')
        try:
            payload = base64.b64decode(uri.split(',', 1)[1], validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise PipelineError('Whitefield source image encoding differs') from exc
        if _sha(payload) != asset_digest:
            raise PipelineError('Whitefield source image asset bytes differ')


def _whitefield_source_lxml(raw: bytes) -> None:
    document = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    images = document.xpath('.//tei:graphic', namespaces={'tei': TEI[1:-1]})
    if len(images) != 9:
        raise ValueError('observed Whitefield image reference count differs')
    for number, node in enumerate(images):
        source_id, label, parent_name, length, uri_digest, asset_digest = WHITEFIELD_IMAGES[number]
        uri = node.get('url')
        expected = {'url': uri, XML_ID: source_id}
        if label is not None:
            expected['n'] = label
        parent = node.getparent()
        mime = 'png' if '.png' in source_id else 'jpeg'
        if (dict(node.attrib) != expected or len(node) or (node.text or '').strip()
                or parent is None or parent.tag != TEI+parent_name
                or not isinstance(uri, str) or len(uri) != length
                or _sha(uri.encode()) != uri_digest
                or not uri.startswith('data:image/'+mime+';base64,')):
            raise ValueError('observed Whitefield image carrier differs')
        try:
            source_bytes = base64.b64decode(uri.partition(',')[2], validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError('observed Whitefield image encoding differs') from exc
        if _sha(source_bytes) != asset_digest:
            raise ValueError('observed Whitefield source asset bytes differ')


def _cox_source_et(raw: bytes) -> None:
    root = ET.fromstring(raw)
    annotations = [node.get('ana') for node in root.iter()
                   if isinstance(node.tag, str) and node.get('ana') is not None]
    if (len(annotations) != 7732
            or any(not value.startswith(COX_SOURCE_PREFIX) for value in annotations)
            or Counter(value.split(':', 4)[3] for value in annotations) != COX_SOURCE_CLASSES):
        raise PipelineError('Cox private source annotation census differs')


def _cox_source_lxml(raw: bytes) -> None:
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    annotations = [node.attrib['ana'] for node in root.iter()
                   if isinstance(node.tag, str) and 'ana' in node.attrib]
    classes = Counter()
    for value in annotations:
        if not value.startswith(COX_SOURCE_PREFIX):
            raise ValueError('observed Cox source annotation prefix differs')
        classes[value.partition(COX_SOURCE_PREFIX)[2].partition(':')[0]] += 1
    if len(annotations) != 7732 or classes != COX_SOURCE_CLASSES:
        raise ValueError('observed Cox private source annotation census differs')


def source_census_et(raw: bytes, work: str) -> None:
    """Producer-side exact source carriers, independent of public rows."""
    if work == NEWMAN_WORK:
        _newman_source_et(raw)
        return
    if work == WHITEFIELD_WORK:
        _whitefield_source_et(raw)
        return
    if work == COX_WORK:
        _cox_source_et(raw)
        return
    root = ET.fromstring(raw)
    if work.startswith('pg49917-'):
        rules = _rules(work)
        marked = [node for node in root.iter() if isinstance(node.tag, str)
                  and node.get('rend', '').startswith(('comment-digest:', 'presentation-style-omitted-sha256:'))]
        if len(marked) != len(rules) or [node.get('n') for node in marked] != list(rules):
            raise PipelineError('source marker order/count differs')
        for node in marked:
            number = node.get('n')
            token, unit, _ = rules[number]
            expected = {'unit': 'source-text-break', 'n': number, 'rend': token, 'ana': node.get('ana')}
            if unit == 'source-html-tbody':
                expected[XML_ID] = f'source-node-{number}'
            if node.tag != TEI+'milestone' or node.attrib != expected:
                raise PipelineError('source marker carrier differs')
            try:
                _annotation(node.get('ana'), number, token, unit)
            except ValueError as exc:
                raise PipelineError(str(exc)) from exc
    else:
        refs = [node for node in root.iter(TEI+'ref') if (node.get('target') or '').startswith('raw/')]
        if len(refs) != 1:
            raise PipelineError('private source page carrier count differs')
        ref = refs[0]
        parent = next((node for node in root.iter() if ref in node), None)
        if (ref.attrib != {'n': 'source-html-class:pginternal', 'target': PRIVATE_PAGE}
                or ref.text != '141' or len(ref) or parent is None
                or parent.tag != TEI+'seg' or parent.attrib != {'n': 'source-paragraph-class:c005'}):
            raise PipelineError('private source page carrier/attachment differs')


def source_census_lxml(raw: bytes, work: str) -> None:
    """Observer-side lxml source census; never invokes the ET producer."""
    if work == NEWMAN_WORK:
        _newman_source_lxml(raw)
        return
    if work == WHITEFIELD_WORK:
        _whitefield_source_lxml(raw)
        return
    if work == COX_WORK:
        _cox_source_lxml(raw)
        return
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    if work.startswith('pg49917-'):
        rules = _rules(work)
        nodes = [node for node in root.iter() if isinstance(node.tag, str)
                 and node.get('rend', '').startswith(('comment-digest:', 'presentation-style-omitted-sha256:'))]
        if tuple(node.get('n') for node in nodes) != tuple(rules):
            raise ValueError('observed source marker sequence differs')
        for node in nodes:
            number = node.get('n')
            token, unit, _ = rules[number]
            actual = dict(node.attrib)
            expected = {'unit': 'source-text-break', 'n': number, 'rend': token, 'ana': node.get('ana')}
            if unit == 'source-html-tbody':
                expected[XML_ID] = 'source-node-'+number
            if node.tag != TEI+'milestone' or actual != expected:
                raise ValueError('observed source marker carrier differs')
            _observed_annotation(node.get('ana'), number, token, unit)
    else:
        private = [node for node in root.iter(TEI+'ref') if (node.get('target') or '').startswith('raw/')]
        if len(private) != 1:
            raise ValueError('observed private source page count differs')
        node = private[0]
        parent = node.getparent()
        if (dict(node.attrib) != {'n': 'source-html-class:pginternal', 'target': PRIVATE_PAGE}
                or node.text != '141' or len(node) or parent is None
                or parent.tag != TEI+'seg' or dict(parent.attrib) != {'n': 'source-paragraph-class:c005'}):
            raise ValueError('observed private source page carrier differs')


def _marker_attributes(attributes: dict, number: str, rule: tuple[str, str, str]) -> None:
    token, unit, alias = rule
    if (not isinstance(attributes, dict) or attributes.get('number') != number
            or set(attributes) != {'number', 'source_annotations', 'style', 'unit'}
            or attributes.get('unit') != 'source-text-break'
            or attributes.get('style') != token):
        raise ValueError('public marker carrier/style differs')
    detail = _annotation(attributes.get('source_annotations'), number, token, unit)
    detail['rend'] = alias
    attributes['style'] = alias
    attributes['source_annotations'] = ANNOTATION + quote(
        json.dumps(detail, ensure_ascii=False, separators=(',', ':')), safe='')


def _public_page_row(rows: list[dict]) -> None:
    if len(rows) != 3:
        raise ValueError('public page work row count differs')
    try:
        node = rows[0]['structure'][0]['content'][4]['content'][0]['content'][3]
        record = rows[0]['source_references'][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('public page attachment differs') from exc
    if (node != {'kind': 'source-reference', 'attributes': {'number': 'source-html-class:pginternal',
                                                            'source_target': PRIVATE_PAGE},
                 'content': [{'kind': 'text', 'text': '141'}]}
            or record != {'raw': '141', 'target': PRIVATE_PAGE,
                          'normalization_attribute': 'target',
                          'normalization_status': 'unsupported-explicit-target',
                          'source_child_path': [4, 0, 1]}):
        raise ValueError('public page fields differ from exact source relationship')
    node['attributes']['source_target'] = PUBLIC_PAGE
    record['target'] = PUBLIC_PAGE


def _observed_page_row(rows: list[dict]) -> None:
    """Independent row check for the one page reference and its source record."""
    if len(rows) != 3:
        raise ValueError('observed page row count differs')
    try:
        structure = rows[0]['structure']
        reference = structure[0]['content'][4]['content'][0]['content'][3]
        companion = rows[0]['source_references'][0]
    except (IndexError, KeyError, TypeError) as exc:
        raise ValueError('observed page attachment differs') from exc
    if (reference.get('kind') != 'source-reference'
            or reference.get('attributes') != {'number': 'source-html-class:pginternal',
                                               'source_target': PRIVATE_PAGE}
            or reference.get('content') != [{'kind': 'text', 'text': '141'}]
            or set(reference) != {'kind', 'attributes', 'content'}
            or companion.get('raw') != '141' or companion.get('target') != PRIVATE_PAGE
            or companion.get('source_child_path') != [4, 0, 1]
            or companion.get('normalization_attribute') != 'target'
            or companion.get('normalization_status') != 'unsupported-explicit-target'
            or set(companion) != {'raw', 'target', 'source_child_path',
                                  'normalization_attribute', 'normalization_status'}):
        raise ValueError('observed page fields differ from source')
    reference['attributes']['source_target'] = PUBLIC_PAGE
    companion['target'] = PUBLIC_PAGE


def _public_check(rows: list[dict]) -> None:
    serialized = json.dumps(rows, ensure_ascii=False)
    decoded = unquote(serialized)
    if (re.search(r'(?i)[0-9a-f]{64}', serialized) or re.search(r'(?i)[0-9a-f]{64}', decoded)
            or 'raw/' in serialized or 'raw/' in decoded
            or 'data:image/' in serialized.lower() or 'data:image/' in decoded.lower()
            or ';base64,' in serialized.lower() or ';base64,' in decoded.lower()):
        raise ValueError('unmapped private source value remains in public rows')


def _cox_private_rows(rows: list[dict]) -> None:
    if len(rows) != 123 or _sha(json.dumps(
            rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()) != COX_PRIVATE_ROWS:
        raise ValueError('Cox original public row shape/text/annotation order differs')


def _cox_annotation_kind(value: object) -> str:
    if not isinstance(value, str) or not value.startswith(COX_SOURCE_PREFIX):
        raise ValueError('Cox source annotation differs from private master')
    kind, sep, tail = value[len(COX_SOURCE_PREFIX):].partition(':')
    if not sep or not tail or kind not in COX_ROW_CLASSES:
        raise ValueError('Cox source annotation kind/identity differs')
    return kind


def _cox_public_rows(rows: list[dict]) -> None:
    """ET producer: replace only the source-annotation carrier at its position."""
    _cox_private_rows(rows)
    counts: Counter[str] = Counter()
    index = 0

    def visit(item: object) -> None:
        nonlocal index
        if isinstance(item, dict):
            for key, value in item.items():
                if key == 'source_annotations':
                    counts[_cox_annotation_kind(value)] += 1
                    index += 1
                    item[key] = f'{COX_ALIAS_PREFIX}{index:05d}'
                else:
                    visit(value)
        elif isinstance(item, list):
            for value in item:
                visit(value)

    visit(rows)
    if counts != COX_ROW_CLASSES or index != 7936:
        raise ValueError('Cox public annotation census differs')


def _cox_observed_rows(rows: list[dict]) -> None:
    """lxml observer: separately walk the independently observed row forest."""
    _cox_private_rows(rows)
    pending: list[tuple[dict | None, str | None, object]] = [(None, None, rows)]
    kinds: Counter[str] = Counter()
    position = 0
    while pending:
        parent, key, item = pending.pop()
        if key == 'source_annotations':
            kinds[_cox_annotation_kind(item)] += 1
            position += 1
            assert parent is not None
            parent[key] = COX_ALIAS_PREFIX + str(position).zfill(5)
            continue
        if isinstance(item, list):
            pending.extend((None, None, value) for value in reversed(item))
        elif isinstance(item, dict):
            for key, value in reversed(list(item.items())):
                pending.append((item, key, value))
    if position != 7936 or kinds != COX_ROW_CLASSES:
        raise ValueError('observed Cox annotation positions/count differ')


def _cox_public_check(rows: list[dict]) -> None:
    annotations = []
    pending: list[object] = [rows]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if key == 'source_annotations':
                    annotations.append(value)
                else:
                    pending.append(value)
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str):
            if 'urn:ocd:' in unquote(item).lower():
                raise ValueError('Cox private source URN remains in public value')
    if (len(annotations) != 7936 or
            set(annotations) != {f'{COX_ALIAS_PREFIX}{index:05d}' for index in range(1, 7937)}):
        raise ValueError('Cox opaque public annotation alias set differs')


def _whitefield_public_images(rows: list[dict]) -> None:
    if len(rows) != 3:
        raise ValueError('Whitefield public volume row count differs')
    found = []
    def visit(value):
        if isinstance(value, dict):
            if value.get('kind') == 'image-reference':
                position = len(found)
                if position >= len(WHITEFIELD_IMAGES):
                    raise ValueError('Whitefield public image count differs')
                _, label, _, length, uri_digest, _ = WHITEFIELD_IMAGES[position]
                attrs = value.get('attributes')
                expected_keys = {'source_target'} | ({'number'} if label is not None else set())
                uri = attrs.get('source_target') if isinstance(attrs, dict) else None
                if (set(value) != {'kind', 'attributes', 'content'} or value.get('content') != []
                        or not isinstance(attrs, dict) or set(attrs) != expected_keys
                        or attrs.get('number') != label
                        or not isinstance(uri, str) or len(uri) != length
                        or _sha(uri.encode()) != uri_digest):
                    raise ValueError('Whitefield public image/source attachment differs')
                attrs['source_target'] = f'source-image:{position+1:04d}'
                found.append(position)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for row, cumulative in zip(rows, (2, 3, 9), strict=True):
        visit(row)
        if len(found) != cumulative:
            raise ValueError('Whitefield public image/volume attachment differs')
    if found != list(range(len(WHITEFIELD_IMAGES))):
        raise ValueError('Whitefield public image order/count differs')


def _whitefield_observed_images(rows: list[dict]) -> None:
    if len(rows) != 3:
        raise ValueError('observed Whitefield volume row count differs')
    positions = []
    for row, cumulative in zip(rows, (2, 3, 9), strict=True):
        pending = [row]
        while pending:
            value = pending.pop()
            if isinstance(value, list):
                pending.extend(reversed(value))
            elif isinstance(value, dict):
                if value.get('kind') == 'image-reference':
                    position = len(positions)
                    if position >= 9 or set(value) != {'kind', 'attributes', 'content'} or value.get('content') != []:
                        raise ValueError('observed Whitefield image shape/count differs')
                    _, label, _, length, uri_digest, _ = WHITEFIELD_IMAGES[position]
                    attributes = value.get('attributes')
                    if not isinstance(attributes, dict):
                        raise ValueError('observed Whitefield image attributes differ')
                    expected_keys = {'source_target'} if label is None else {'source_target', 'number'}
                    target = attributes.get('source_target')
                    if (set(attributes) != expected_keys or attributes.get('number') != label
                            or not isinstance(target, str) or len(target) != length
                            or sha256(target.encode()).hexdigest() != uri_digest):
                        raise ValueError('observed Whitefield image target differs')
                    attributes['source_target'] = 'source-image:' + str(position+1).zfill(4)
                    positions.append(position)
                pending.extend(reversed(list(value.values())))
        if len(positions) != cumulative:
            raise ValueError('observed Whitefield image/volume attachment differs')
    if positions != list(range(9)):
        raise ValueError('observed Whitefield image order differs')


def project_rows(rows: list[dict], raw: bytes, work: str | None) -> list[dict]:
    """ET producer disposition; the accepted wrapper owns selection."""
    if work is None:
        return deepcopy(rows)
    if work == NEWMAN_WORK:
        return _newman_project_rows(rows, raw)
    if (work not in {WHITEFIELD_WORK, COX_WORK} and work not in _SPECS
            or _sha(raw) != (WHITEFIELD_MASTER if work == WHITEFIELD_WORK else
                             COX_MASTER if work == COX_WORK else _SPECS[work]['master'])):
        raise PipelineError('public disposition work/master differs')
    source_census_et(raw, work)
    result = deepcopy(rows)
    if work == COX_WORK:
        _cox_public_rows(result)
        _cox_public_check(result)
    elif work == WHITEFIELD_WORK:
        _whitefield_public_images(result)
    elif work.startswith('pg49917-'):
        rules = _rules(work)
        seen = []
        def visit(value):
            if isinstance(value, dict):
                if value.get('kind') == 'source-marker':
                    attrs = value.get('attributes', {})
                    number = attrs.get('number')
                    if number in rules:
                        if set(value) != {'kind', 'attributes', 'content'} or value.get('content') != []:
                            raise ValueError('public marker outer shape differs')
                        _marker_attributes(attrs, number, rules[number])
                        seen.append(number)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(result)
        if seen != list(rules):
            raise ValueError('public source marker order/count differs')
    else:
        _public_page_row(result)
    _public_check(result)
    return result


def observe_rows(rows: list[dict], raw: bytes, work: str | None) -> list[dict]:
    """lxml observer disposition; does not call the producer transform."""
    if work is None:
        return deepcopy(rows)
    if work == NEWMAN_WORK:
        return _newman_observe_rows(rows, raw)
    if (work not in {WHITEFIELD_WORK, COX_WORK} and work not in _SPECS
            or _sha(raw) != (WHITEFIELD_MASTER if work == WHITEFIELD_WORK else
                             COX_MASTER if work == COX_WORK else _SPECS[work]['master'])):
        raise ValueError('observed public disposition work/master differs')
    source_census_lxml(raw, work)
    expected = deepcopy(rows)
    if work == COX_WORK:
        _cox_observed_rows(expected)
        _cox_public_check(expected)
    elif work == WHITEFIELD_WORK:
        _whitefield_observed_images(expected)
    elif work.startswith('pg49917-'):
        rules = _rules(work)
        found = []
        pending = [expected]
        while pending:
            item = pending.pop()
            if isinstance(item, list):
                pending.extend(reversed(item))
            elif isinstance(item, dict):
                if item.get('kind') == 'source-marker':
                    attrs = item.get('attributes')
                    if not isinstance(attrs, dict):
                        raise ValueError('observed source marker attributes differ')
                    number = attrs.get('number')
                    if number in rules:
                        token, unit, alias = rules[number]
                        if (set(item) != {'kind', 'attributes', 'content'} or item.get('content') != []
                                or set(attrs) != {'number', 'source_annotations', 'style', 'unit'}
                                or attrs.get('unit') != 'source-text-break'
                                or attrs.get('style') != token):
                            raise ValueError('observed source marker style differs')
                        detail = _observed_annotation(attrs.get('source_annotations'), number, token, unit)
                        attrs['style'] = alias
                        detail['rend'] = alias
                        attrs['source_annotations'] = ANNOTATION + quote(
                            json.dumps(detail, ensure_ascii=False, separators=(',', ':')), safe='')
                        found.append(number)
                pending.extend(reversed(list(item.values())))
        if found != list(rules):
            raise ValueError('observed public source marker count/order differs')
    else:
        _observed_page_row(expected)
    _public_check(expected)
    return expected
