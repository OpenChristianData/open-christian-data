"""Source-bound native reader profile for the existing Strong three-volume TEI.

Checks volume identity and structural conservation without reconstructing source text.
This profile does not establish acceptance, print collation, rights, or publication.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import xml.etree.ElementTree as ET
from lxml import etree
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import strong_vol2_source_lines as middle

VERSION = 'ocd-prose-strong-retained-three-volume-group-v2'
MASTER_SHA = 'fdb9d4b9194461581af6f352fc0bf98d6d77cad5e42b2ae4a0ebfd65cc332591'
IDENTITY = {'work_id': 'strong-systematic-theology',
            'textual_form_id': 'strong-systematic-theology-retained-english',
            'edition_id': 'strong-systematic-theology-three-volume-retained-electronic'}
ACQUISITION = 'strong-systematic-theology-retained-three-volume-member-set'
ROOT = Path(__file__).resolve().parents[3]
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
MEMBERS = (
    ('strong-systematic-theology-vol-1/forms/strong-systematic-theology-vol-1-english/editions/strong-systematic-theology-vol-1-retained-electronic-witness',
     '97707a20de7acf8e9e6629b1b58c2fd7889587036fdaff9ad9bf3163bab3bee0'),
    ('strong-systematic-theology-vol-2/forms/strong-systematic-theology-vol-2-english/editions/strong-systematic-theology-vol-2-retained-electronic-witness',
     '12938e99a0aef121f5380b9ee4b0c8d58a4d8afbc5f3e19d30bff7e6a85ed3ab'),
    ('strong-systematic-theology-vol-3/forms/strong-systematic-theology-vol-3-english/editions/project-gutenberg-45283',
     '30c1382b60287f338309afd94c47932976444e4833af3586117d29c19a80e210'),
)
WARNINGS = [
    'One authored Systematic Theology, revised and enlarged, in three retained electronic volumes, ordered by their own source title pages.',
    'Volume I: Judson Press, eight title-page cities, 1907; Volume II: Judson Press, Philadelphia, 1907; Volume III: Griffith & Rowland Press, Philadelphia, 1909. No uniform printed edition is asserted.',
    'Volumes I and II account for 376 provider-envelope records each outside text; Volume III retains its complete acquired provider envelope inside text. No member scope is silently changed.',
    'Complete original headers remain private dated administrative evidence. Human review, print collation, electronic-transcription lineage, rights and publication remain separate.',
]


def route(identity, raw, *, language, category, collection,
          allow_acceptance_metadata, projection_profile=None, source_base=None,
          acquisition_id=None):
    if identity.get('work_id') != IDENTITY['work_id']:
        return False
    if (identity != IDENTITY or sha256(raw).hexdigest() != MASTER_SHA
            or acquisition_id != ACQUISITION
            or language != 'en' or category != 'prose' or collection
            or not allow_acceptance_metadata or projection_profile is not None
            or source_base is not None):
        raise PipelineError('Complete Strong group requires its exact reviewed master and supported accepted context')
    return True


def member_content_profile(volume):
    if volume not in (1, 2, 3):
        raise PipelineError('Invalid Strong source volume')
    # Reuse precisely the existing node grammar for II; I/III keep the
    # existing generic native-content semantics, subject to their whole inverse.
    return middle.PROFILE if volume == 2 else None


def header_rules(elements, attributes):
    # The exact master/whole header is already hash-bound. These two fields
    # are new bibliographic grouping/context, confined to this selected route.
    result = {key: list(value) for key, value in attributes.items()}
    result['bibl'] = list(dict.fromkeys(result.get('bibl', []) + ['n']))
    result['note'] = list(dict.fromkeys(result.get('note', []) + ['xml:space']))
    return elements, result


def check_et(root):
    """Producer-side full original field/context comparison, using ET."""
    if (root.tag != NS+'TEI' or root.attrib
            or [node.tag for node in root] != [NS+'teiHeader', NS+'text']):
        raise PipelineError('Strong complete root/header/text envelope differs')
    outer = root[1]
    if outer.attrib or outer.text is not None or len(outer) != 1 or outer[0].tag != NS+'group':
        raise PipelineError('Strong outer text/group context differs')
    group = outer[0]
    if group.attrib or group.text is not None or len(group) != 3:
        raise PipelineError('Strong complete group must have three members')
    identifiers = set()
    for number, (path, digest) in enumerate(MEMBERS, 1):
        original = io_path(ROOT/'library/works'/path/'master.tei.xml').read_bytes()
        if sha256(original).hexdigest() != digest:
            raise PipelineError('Strong original member authority changed')
        expected = ET.fromstring(original).find(NS+'text')
        actual = group[number-1]
        if actual.tag != NS+'text' or actual.attrib != {'n': str(number)}:
            raise PipelineError('Strong source member order/number differs')
        old = list(expected.iter()); current = list(actual.iter())
        if len(old) != len(current):
            raise PipelineError('Strong complete member node count differs')
        parents = {child: node for node in actual.iter() for child in node}
        for ordinal, (before, after) in enumerate(zip(old, current, strict=True)):
            attrs = dict(after.attrib)
            if ordinal == 0:
                attrs.pop('n')
            if (before.tag, dict(before.attrib), before.text, before.tail) != (after.tag, attrs, after.text, after.tail):
                raise PipelineError('Strong entire member fields/context differ')
            identifier = after.get(XML+'id')
            if identifier:
                if identifier in identifiers:
                    raise PipelineError('Strong source ID collision')
                identifiers.add(identifier)
            if number == 2 and after.tag not in (NS+'text', NS+'front', NS+'body'):
                try:
                    middle.check_content_node(after, parents[after].tag.removeprefix(NS))
                except ValueError as exc:
                    raise PipelineError(str(exc)) from exc
    if len(identifiers) != 89634:
        raise PipelineError('Strong complete source ID count differs')


def check_lxml(doc):
    """Observer-side independently parsed full fields/ns/context, using lxml."""
    if doc.tag != NS+'TEI' or doc.attrib or doc.nsmap != {None: NS[1:-1]}:
        raise ValueError('Observed Strong root namespaces/fields differ')
    if [node.tag for node in doc] != [NS+'teiHeader', NS+'text']:
        raise ValueError('Observed Strong header/text attachment differs')
    outer = doc.find(NS+'text')
    if outer.attrib or outer.text is not None or len(outer) != 1 or outer[0].tag != NS+'group':
        raise ValueError('Observed Strong outer group differs')
    members = outer[0]
    if members.attrib or members.text is not None or len(members) != 3:
        raise ValueError('Observed Strong member count differs')
    seen = set()
    for position in range(3):
        path, digest = MEMBERS[position]
        original = io_path(ROOT/'library/works'/path/'master.tei.xml').read_bytes()
        if sha256(original).hexdigest() != digest:
            raise ValueError('Observed Strong original master binding differs')
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, remove_blank_text=False)
        source_text = etree.fromstring(original, parser).find(NS+'text')
        member = members[position]
        if member.tag != NS+'text' or dict(member.attrib) != {'n': str(position+1)}:
            raise ValueError('Observed Strong source member ownership differs')
        sources = list(source_text.iter()); nodes = list(member.iter())
        if len(nodes) != len(sources):
            raise ValueError('Observed Strong complete node census differs')
        for offset, source in enumerate(sources):
            node = nodes[offset]; fields = dict(node.attrib)
            if offset == 0:
                del fields['n']
            if (node.tag != source.tag or fields != dict(source.attrib)
                    or node.nsmap != source.nsmap or node.text != source.text or node.tail != source.tail):
                raise ValueError('Observed Strong whole original member object/context differs')
            key = node.get(XML+'id')
            if key:
                if key in seen:
                    raise ValueError('Observed Strong duplicate source locator')
                seen.add(key)
            if position == 1 and node.tag not in (NS+'text', NS+'front', NS+'body'):
                middle.check_content_node(node, etree.QName(node.getparent()).localname)
    if len(seen) != 89634:
        raise ValueError('Observed Strong full source locator census differs')
