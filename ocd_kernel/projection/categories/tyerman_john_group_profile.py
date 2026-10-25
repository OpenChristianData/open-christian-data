"""Exact three-volume John Wesley prose group and public image disposition."""
from __future__ import annotations

import copy
import hashlib
import json
from lxml import etree
import xml.etree.ElementTree as ET

from ocd_kernel.library._common import PipelineError

TEI = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
VERSION = 'ocd-prose-tyerman-john-three-volume-source-native-v2+public-annotation-alias-v1'
GROUP_ID = 'tyerman-life-times-john-wesley--volumes'
PRIVATE_ANNOTATION_PREFIX = 'urn:ocd:tyerman-wesley:source-fields:'
PUBLIC_ANNOTATION_PREFIX = 'source-annotation:'
ANNOTATIONS_PER_ROW = (26, 7178, 58, 25, 9824, 58, 25, 17306, 58)
PRIVATE_ANNOTATION_STREAM_SHA256 = '87a4292a94727ffd6569887f4abcb1e5f225dce50f2bf3377fb4e8fbbab75901'
GRAPHICS = (
    ('v1--img_images_i_frontis.jpg', 'images/i_frontis.jpg', '9c7d04c9f0930e081721a4a71050945e859ae8fb0e7436c00c5cfeb84f1d3990'),
    ('v1--img_images_colophon.jpg', 'images/colophon.jpg', '5a318ff03b087b98d775b5aeae4db4461a8fe060d548806f01bf2c74b33db54a'),
    ('v2--img_images_i_frontis.jpg', 'images/i_frontis.jpg', 'b3c3eaba8b134234efdb0c492c0ec6718957996c23860e25c2b3103eef41a205'),
    ('v2--img_images_colophon.jpg', 'images/colophon.jpg', '5a318ff03b087b98d775b5aeae4db4461a8fe060d548806f01bf2c74b33db54a'),
    ('v3--img_images_frontis.jpg', 'images/frontis.jpg', 'df6ee2624c7a092775d04e9493848be82bde37ed83dc0be15f019ebf306d380f'),
    ('v3--img_images_colophon.jpg', 'images/colophon.jpg', '21a0cec570a27a6cc34c5a32aecc1336677e9dc2be15a4935ec1205a43de0c90'),
    ('v3--img_images_i_back.jpg', 'images/i_back.jpg', '95152af55444d44187205bf69c9cf2d2eeb99d26839f9ae581ab355b42cfd03a'),
)
ARCHIVES = (
    'fd78f98a6b79186a5f886c2e0f49a30c4b6d2ab9eae59c43d49e5f582898bf8b',
    '0dd3ef53f9081c06cb604c052748cb155ae1100e52720961472e387421bfe062',
    '7e3d35ea02e40d5bdfee8294ac4c3bd3316ce11c3322a06e687c2b6199824245',
)
COUNTS = {'div': 20577, 'figure': 7, 'graphic': 7, 'table': 20, 'row': 230,
          'cell': 831, 'choice': 2057, 'abbr': 2057, 'expan': 2057}


def _source_graphics(root):
    return list(root.iter(TEI+'graphic'))


def _common_shape(root, error):
    header = root.find(TEI+'teiHeader')
    text = root.find(TEI+'text')
    group = text.find(TEI+'group') if text is not None else None
    if (header is None or text is None or dict(text.attrib) or len(text) != 1
            or group is None or group.get(XML+'id') != GROUP_ID or len(group) != 3):
        raise error('John source group envelope differs')
    for ordinal, member in enumerate(group, 1):
        if (member.tag != TEI+'text' or member.get(XML+'id') != f'wesley-volume-{ordinal}'
                or member.get(XML+'lang') != 'en' or not (member.get('ana') or '').startswith('urn:ocd:tyerman-wesley:source-fields:')
                or [child.tag for child in member] != [TEI+'front', TEI+'body', TEI+'back']
                or any(len(part) != 1 or part[0].tag != TEI+'div' for part in member)
                or [part[0].get('type') for part in member] !=
                ['source-provider-header', 'source-book-content', 'source-provider-footer']):
            raise error('John source volume order or attachment differs')
    source = header.find(TEI+'fileDesc/'+TEI+'sourceDesc')
    if (source is None or len(source) != 4
            or [child.get('type') for child in source] !=
            ['retained-source-volume']*3+['ocd-acceptance-binding']
            or [source[i].get(XML+'id') for i in range(3)] !=
            ['wesley-source-1', 'wesley-source-2', 'wesley-source-3']):
        raise error('John private source volumes or acceptance binding differ')
    counts = {name: sum(1 for _ in root.iter(TEI+name)) for name in COUNTS}
    if counts != COUNTS:
        raise error('John source structure census differs')
    images = _source_graphics(root)
    if len(images) != len(GRAPHICS):
        raise error('John source image count differs')
    for ordinal, (node, (identifier, path, digest)) in enumerate(zip(images, GRAPHICS, strict=True)):
        archive = ARCHIVES[ordinal // 2 if ordinal < 4 else 2]
        expected_corresp = f'urn:ocd:retained-archive-member:sha256:{archive}:{path.replace("/", "%2F")}'
        url = node.get('url') or ''
        if (node.get(XML+'id') != identifier or node.get('corresp') != expected_corresp
                or not url.startswith('data:image/jpeg;base64,')
                or hashlib.sha256(url.encode()).hexdigest() != digest):
            raise error('John retained JPEG or archive member differs')
    return images


def source_census_et(root: ET.Element):
    return _common_shape(root, PipelineError)


def source_census_lxml(root: etree._Element):
    return _common_shape(root, ValueError)


def _image_nodes(value):
    if isinstance(value, dict):
        if value.get('kind') == 'image-reference':
            yield value
        for child in value.values():
            yield from _image_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _image_nodes(child)


def _alias_rows(rows, images, error):
    output = copy.deepcopy(rows)
    public_images = list(_image_nodes([row['structure'] for row in output]))
    if len(public_images) != len(images):
        raise error('John public image count differs from private source')
    for ordinal, (node, image) in enumerate(zip(public_images, images, strict=True)):
        attrs = node['attributes']
        if attrs.get('source_target') != image.get('url'):
            raise error('John public image target differs from private source')
        volume = 1 if ordinal < 2 else 2 if ordinal < 4 else 3
        attrs['source_target'] = f'retained-embedded-image:volume-{volume}/{GRAPHICS[ordinal][1]}'
    return output


def _check_private_annotations(values, counts, error):
    if (tuple(counts) != ANNOTATIONS_PER_ROW
            or len(values) != sum(ANNOTATIONS_PER_ROW)
            or any(not isinstance(value, str)
                   or not value.startswith(PRIVATE_ANNOTATION_PREFIX)
                   for value in values)
            or hashlib.sha256(json.dumps(
                values, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
            != PRIVATE_ANNOTATION_STREAM_SHA256):
        raise error('John private source annotation order or content differs')


def _project_annotation_aliases(rows):
    """ET producer: enumerate only the exact private annotation stream."""
    locations = []
    values = []
    counts = []

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'source_annotations':
                    locations.append(value)
                    values.append(child)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for row in rows:
        before = len(values)
        visit(row)
        counts.append(len(values) - before)
    _check_private_annotations(values, counts, PipelineError)
    for ordinal, location in enumerate(locations, 1):
        location['source_annotations'] = f'{PUBLIC_ANNOTATION_PREFIX}{ordinal:05d}'


def _observe_annotation_aliases(rows):
    """lxml observer: independently enumerate the source-order row forest."""
    positions = []
    originals = []
    per_row = []
    for row in rows:
        beginning = len(originals)
        pending = [(None, None, row)]
        while pending:
            parent, key, item = pending.pop()
            if key == 'source_annotations':
                positions.append(parent)
                originals.append(item)
                continue
            if isinstance(item, list):
                pending.extend((None, None, child) for child in reversed(item))
            elif isinstance(item, dict):
                pending.extend((item, name, child)
                               for name, child in reversed(list(item.items())))
        per_row.append(len(originals) - beginning)
    _check_private_annotations(originals, per_row, ValueError)
    for number, location in enumerate(positions, 1):
        location['source_annotations'] = PUBLIC_ANNOTATION_PREFIX + str(number).zfill(5)


def project_rows(rows, root):
    output = _alias_rows(rows, source_census_et(root), PipelineError)
    _project_annotation_aliases(output)
    return output


def observe_rows(rows, root):
    output = _alias_rows(rows, source_census_lxml(root), ValueError)
    _observe_annotation_aliases(output)
    return output
