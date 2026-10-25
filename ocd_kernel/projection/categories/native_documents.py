"""Versioned native prose and whole-sermon projection for TCP mixed content.

Public structure preserves source hierarchy. Private receipts account for every
node, including the bibliographic header and attributes omitted from public rows.
The checker observes the master with lxml and never calls the producer.
"""
from __future__ import annotations
from ocd_kernel.projection.categories import strong_vol2_source_lines as strong_source
from ocd_kernel.projection.categories import strong_complete_group_profile as strong_complete
from ocd_kernel.projection.categories import coppens_pg70790_source_profile as coppens_source

from ocd_kernel.projection.categories import l599_slave_trade_source_profile as l599_source

import base64
import binascii
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path
from ocd_kernel.projection import native_content, native_public_dispositions
from ocd_kernel.projection.categories import commentary_group_policy, guyon_source_profile, tyerman_john_group_profile, tyerman_whitefield_source_profile as whitefield_source
from ocd_kernel.projection.categories import cassiodorus_source_profile as cass_source
from ocd_kernel.projection.categories import fox_pg43031_source_profile as fox_source
from ocd_kernel.projection.categories import woolman_pg37311_source_profile as woolman_source
from ocd_kernel.projection.native_content_check import observe_content
from ocd_kernel.projection.source_projection_evidence import project_evidence, observe_evidence
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets import normalize_reference_record
from ocd_kernel.projection.scripture_targets_check import observe_reference_record

NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
VERSION = 'ocd-sermons-native-v3'
FORMAT = 'ocd-native-content-v1'

_GAINES_SOURCE_ROLES = {
    'titlePage': ('div', 'source-title-page'),
    'docTitle': ('ab', 'source-block'),
    'titlePart': ('ab', 'source-block'),
    'byline': ('ab', 'source-block'),
    'docAuthor': ('ab', 'source-block'),
    'docImprint': ('ab', 'source-block'),
    'pubPlace': ('ab', 'source-block'),
    'publisher': ('ab', 'source-block'),
    'docDate': ('ab', 'source-block'),
}


def _gaines_readable_shadow(unit):
    """Expose exact historical title-page roles without altering the accepted master."""
    result = deepcopy(unit)
    observed = []
    for node in result.iter():
        if not isinstance(node.tag, str) or not node.tag.startswith(NS):
            continue
        original = node.tag[len(NS):]
        mapped = _GAINES_SOURCE_ROLES.get(original)
        if original == 'emph':
            if dict(node.attrib) != {'rend': 'bold'} or (node.text or '') != 'CONTENTS.':
                raise PipelineError('Gaines source emphasis differs')
            source = {'tag': original, 'attributes': [['rend', 'bold']]}
            node.tag = NS + 'hi'
            node.set('ana', 'source-role:' + quote(json.dumps(source, ensure_ascii=False,
                                                              separators=(',', ':')), safe=''))
            observed.append(original)
            continue
        if mapped is None:
            continue
        attributes = sorted(node.attrib.items())
        if attributes and (original != 'titlePart' or attributes != [('type', 'main')]):
            raise PipelineError('Gaines historical title-page source attributes differ')
        source = {'tag': original, 'attributes': [[key, value] for key, value in attributes]}
        annotation = 'source-role:' + quote(json.dumps(source, ensure_ascii=False,
                                                        separators=(',', ':')), safe='')
        node.tag = NS + mapped[0]
        node.attrib.clear()
        node.set('type', mapped[1])
        node.set('subtype', original)
        node.set('ana', annotation)
        observed.append(original)
    if observed != ['titlePage', 'docTitle', 'titlePart', 'byline', 'docAuthor',
                    'docImprint', 'pubPlace', 'publisher', 'docDate', 'docImprint']:
        # Other units do not carry title-page source roles.
        if observed and observed != ['emph']:
            raise PipelineError('Gaines historical title-page source roles differ')
    return result
SCOPE = 'tei-document; caller-supplied context'
GREENLEAF_MARKER_PROFILE = 'ocd-prose-greenleaf-paired-page-markers-v1'
CAREY_GROUPED_TABLE_PROFILE = 'ocd-prose-carey-pg11449-grouped-tables-v1'
ELMSLIE_CHOICE_PROFILE = 'ocd-prose-elmslie-pg71811-abbreviation-choice-v1'
HOLY_IMAGES_PROFILE = 'ocd-prose-pg49917-holy-images-v1'
PETER_JONES_PROFILE = 'ocd-prose-peter-jones-1860-source-markers-v1'
HODGE_PROFILE = 'ocd-prose-hodge-theology1-retained-volume-v1'
AMERICAN_MISSIONARY_PROFILE = 'ocd-prose-american-missionary-monthly-issues-v1'
GUYON_PROFILE = 'ocd-prose-guyon-pg24989-v16-source-native-v1'
SAMUEL_PROFILE = 'ocd-prose-tyerman-samuel-pg67980-source-native-v1'
JOHN_PROFILE = 'ocd-prose-tyerman-john-three-volume-source-native-v1'
_JOHN_MASTER_SHA = 'd56533f26e5ed677fa1d8afe6c451c209dfc49e4b211e6035b046b0727907c9c'
_JOHN_IDENTITY = {'work_id': 'tyerman-life-times-john-wesley',
                  'textual_form_id': 'tyerman-life-times-john-wesley--retained-en',
                  'edition_id': 'tyerman-life-times-john-wesley--gutenberg-electronic'}


def _allow_preserved_text_space(node, allowed: set[str], *, error_type: type[Exception]) -> None:
    """Account for standard xml:space=preserve on a text envelope only."""
    value = node.get(XML+'space')
    if value is None:
        return
    if value != 'preserve':
        raise error_type('unsupported native text whitespace declaration')
    allowed.add(XML+'space')

def _john_route(identity, raw, *, language, category, collection, projection_profile,
                allow_acceptance_metadata, source_base, group_profile):
    if identity.get('work_id') != _JOHN_IDENTITY['work_id']:
        return False
    if (identity != _JOHN_IDENTITY or _sha(raw) != _JOHN_MASTER_SHA
            or language != 'en' or category != 'prose' or collection
            or projection_profile is not None or not allow_acceptance_metadata
            or source_base is not None or group_profile is not None):
        raise PipelineError('John three-volume source-native route requires its exact accepted draft and identity')
    return True


def _observe_john_route(identity, raw, *, language, category, collection,
                        projection_profile, allow_acceptance_metadata,
                        source_base, group_profile):
    if identity.get('work_id') != _JOHN_IDENTITY['work_id']:
        return False
    if (identity != _JOHN_IDENTITY or hashlib.sha256(raw).hexdigest() != _JOHN_MASTER_SHA
            or language != 'en' or category != 'prose' or collection
            or projection_profile is not None or not allow_acceptance_metadata
            or source_base is not None or group_profile is not None):
        raise ValueError('observed John three-volume source-native candidate or identity differs')
    return True
_SAMUEL_CANDIDATE_SHA = '82be22755ca1771ff6d3a6ae29d67e9bc49449d164f2c0366930f1c056167af1'
_SAMUEL_ACCEPTED_DRAFT_SHA = '193b6e6921df36eddb0f06c4dd815f05f11a78272754476fa69d3c0dd7617802'
_SAMUEL_IDENTITY = {'work_id': 'tyerman-life-times-samuel-wesley-1866',
                    'textual_form_id': 'english', 'edition_id': 'pg67980-1866-simpkin-marshall'}


def _samuel_route(identity, raw, *, language, category, collection, projection_profile,
                  allow_acceptance_metadata, source_base):
    if identity.get('work_id') != _SAMUEL_IDENTITY['work_id']:
        return False
    # The immutable candidate is admitted only for direct scratch proof. Public
    # entry separately requires a validated acceptance and the bound header.
    if (identity != _SAMUEL_IDENTITY or _sha(raw) not in {_SAMUEL_CANDIDATE_SHA, _SAMUEL_ACCEPTED_DRAFT_SHA}
            or language != 'en' or category != 'prose' or collection
            or projection_profile is not None or not allow_acceptance_metadata
            or source_base is not None):
        raise PipelineError('Samuel source-native route requires its exact candidate and identity')
    return True


def _observe_samuel_route(identity, raw, *, language, category, collection,
                          projection_profile, allow_acceptance_metadata, source_base):
    if identity.get('work_id') != 'tyerman-life-times-samuel-wesley-1866':
        return False
    if (identity != {'work_id': 'tyerman-life-times-samuel-wesley-1866',
                     'textual_form_id': 'english', 'edition_id': 'pg67980-1866-simpkin-marshall'}
            or hashlib.sha256(raw).hexdigest() not in {
                '82be22755ca1771ff6d3a6ae29d67e9bc49449d164f2c0366930f1c056167af1',
                '193b6e6921df36eddb0f06c4dd815f05f11a78272754476fa69d3c0dd7617802'}
            or language != 'en' or category != 'prose' or collection
            or projection_profile is not None or not allow_acceptance_metadata
            or source_base is not None):
        raise ValueError('observed Samuel source-native candidate or identity differs')
    return True


def _samuel_header_rules(elements, attributes):
    elements = {name: list(children) for name, children in elements.items()}
    attributes = {name: list(names) for name, names in attributes.items()}
    elements['titleStmt'] = list(dict.fromkeys(elements['titleStmt'] + ['author']))
    elements['author'] = []
    elements['p'] = list(dict.fromkeys(elements['p'] + ['seg']))
    elements['seg'] = []
    attributes['p'] = list(dict.fromkeys(attributes.get('p', []) + ['n']))
    attributes['seg'] = ['n', 'type']
    return elements, attributes


def _samuel_source_et(root):
    header = root.find(NS+'teiHeader')
    text = root.find(NS+'text')
    if (header is None or text is None or [part.tag for part in text] !=
            [NS+'front', NS+'body', NS+'back']
            or [[child.get('type') for child in part] for part in text] !=
            [['source-provider-header'], ['source-book-content'], ['source-provider-footer']]):
        raise PipelineError('Samuel source front/body/back attachment differs')
    source_desc = header.find(NS+'fileDesc/'+NS+'sourceDesc')
    if source_desc is None:
        raise PipelineError('Samuel private source description is missing')
    source_children = list(source_desc)
    if source_children and source_children[0].tag == NS+'bibl':
        if (len(source_children) != 2 or source_children[0].get('type') != 'retained-source-administration'
                or [child.tag for child in source_children[0]] != [NS+'note']
                or source_children[0][0].get('type') != 'retained-source-description'
                or len(source_children[0][0]) != 32
                or any(child.tag != NS+'p' for child in source_children[0][0])
                or source_children[1].tag != NS+'bibl'
                or source_children[1].get('type') != 'ocd-acceptance-binding'
                or [child.tag for child in header] != [NS+'fileDesc', NS+'revisionDesc']):
            raise PipelineError('Samuel accepted private source administration differs')
    elif (len(source_children) != 32 or any(child.tag != NS+'p' for child in source_children)
          or [child.tag for child in header] != [NS+'fileDesc']):
        raise PipelineError('Samuel candidate private source description differs')
    counts = {name: sum(1 for _ in root.iter(NS+name))
              for name in ('div', 'graphic', 'table', 'row', 'cell', 'list', 'item')}
    if counts != {'div': 5623, 'graphic': 2, 'table': 7, 'row': 534,
                  'cell': 1094, 'list': 29, 'item': 588}:
        raise PipelineError('Samuel source structure census differs')
    parents = {child: parent for parent in header.iter() for child in parent}
    bindings = [node for node in header.iter(NS+'bibl') if node.get('type') == 'ocd-acceptance-binding']
    binding_p = (len(bindings) == 1 and parents.get(bindings[0]) is not None
                 and parents[bindings[0]].tag == NS+'p')
    if (sum(node.get('unit') == 'source-column' for node in root.iter(NS+'milestone')) != 25
            or sum(node.get('unit') == 'source-rule' for node in root.iter(NS+'milestone')) != 8
            or len(list(header.iter(NS+'p'))) != 33 + int(binding_p)
            or len(list(header.iter(NS+'seg'))) != 110):
        raise PipelineError('Samuel source marker or private header census differs')


def _samuel_source_lxml(root):
    header = root.find(NS+'teiHeader')
    text = root.find(NS+'text')
    if (header is None or text is None
            or [etree.QName(part).localname for part in text] != ['front', 'body', 'back']
            or [[child.get('type') for child in part] for part in text] !=
            [['source-provider-header'], ['source-book-content'], ['source-provider-footer']]):
        raise ValueError('observed Samuel part ownership differs')
    source_desc = header.find(NS+'fileDesc/'+NS+'sourceDesc')
    if source_desc is None:
        raise ValueError('observed Samuel source description is missing')
    source_children = list(source_desc)
    if source_children and source_children[0].tag == NS+'bibl':
        if (len(source_children) != 2 or source_children[0].get('type') != 'retained-source-administration'
                or [child.tag for child in source_children[0]] != [NS+'note']
                or source_children[0][0].get('type') != 'retained-source-description'
                or len(source_children[0][0]) != 32
                or any(child.tag != NS+'p' for child in source_children[0][0])
                or source_children[1].tag != NS+'bibl'
                or source_children[1].get('type') != 'ocd-acceptance-binding'
                or [child.tag for child in header] != [NS+'fileDesc', NS+'revisionDesc']):
            raise ValueError('observed Samuel accepted source administration differs')
    elif (len(source_children) != 32 or any(child.tag != NS+'p' for child in source_children)
          or [child.tag for child in header] != [NS+'fileDesc']):
        raise ValueError('observed Samuel candidate source description differs')
    observed = {name: len(root.xpath('.//t:'+name, namespaces={'t': NS[1:-1]}))
                for name in ('div', 'graphic', 'table', 'row', 'cell', 'list', 'item')}
    if observed != {'div': 5623, 'graphic': 2, 'table': 7, 'row': 534,
                    'cell': 1094, 'list': 29, 'item': 588}:
        raise ValueError('observed Samuel structural carriers differ')
    bindings = header.xpath('.//t:bibl[@type="ocd-acceptance-binding"]', namespaces={'t': NS[1:-1]})
    binding_p = (len(bindings) == 1 and bindings[0].getparent() is not None
                 and bindings[0].getparent().tag == NS+'p')
    if (len(root.xpath('.//t:milestone[@unit="source-column"]', namespaces={'t': NS[1:-1]})) != 25
            or len(root.xpath('.//t:milestone[@unit="source-rule"]', namespaces={'t': NS[1:-1]})) != 8
            or len(header.xpath('.//t:p', namespaces={'t': NS[1:-1]})) != 33 + int(binding_p)
            or len(header.xpath('.//t:seg', namespaces={'t': NS[1:-1]})) != 110):
        raise ValueError('observed Samuel markers or header fields differ')
MOODY_PROFILE = 'ocd-prose-moody-pg61883-source-native-v1'
COPPENS_PROFILE = coppens_source.PROFILE
CASSIODORUS_PROFILE = cass_source.PROFILE
FOX_PROFILE = fox_source.PROFILE
WOOLMAN_PROFILE = woolman_source.PROFILE
_PTA_ANONYMOUS_VITA_IDENTITY = {
    'work_id': 'anonymous-vita-sancti-cononis-bidanae',
    'textual_form_id': 'pta-grc',
    'edition_id': 'pta-ef861ab3-vita-sancti-cononis-bidanae-grc1',
}
_PTA_ANONYMOUS_VITA_ACQUISITION = 'ptaef861'
_PTA_ANONYMOUS_VITA_MASTER_SHA = '8f3284d365aad8d27ae71ac0528824e09a3954b8a2b006740b5bc29f959dd4ed'


def _pta_anonymous_vita_sic_route(identity, master_sha256, *, language, category,
                                   collection, projection_profile,
                                   allow_acceptance_metadata, acquisition_id):
    target = (identity == _PTA_ANONYMOUS_VITA_IDENTITY
              and acquisition_id == _PTA_ANONYMOUS_VITA_ACQUISITION
              and language == 'grc')
    if not target:
        if projection_profile == native_content.PTA_ANONYMOUS_VITA_PROFILE:
            raise PipelineError('PTA standalone-sic profile requires its exact accepted edition')
        return False
    if (not allow_acceptance_metadata or category != 'prose' or collection
            or projection_profile not in (None, native_content.PTA_ANONYMOUS_VITA_PROFILE)
            or master_sha256 != _PTA_ANONYMOUS_VITA_MASTER_SHA):
        raise PipelineError('PTA standalone-sic profile requires its exact accepted master')
    return True

_PTA_HESYCHIUS_IDENTITY = {
    'work_id': 'hesychius-commentarius-magnus-in-psalmos',
    'textual_form_id': 'pta-grc',
    'edition_id': 'pta-ef861ab3-hesychius-commentarius-magnus-in-psalmos',
}
_PTA_HESYCHIUS_ACQUISITION = 'ptaef861'
_PTA_HESYCHIUS_MASTER_SHA = '892715353efa05b16332457d36974e9f5d52bf236c5457afe6f9997f20de8d7f'


def _pta_hesychius_empty_sic_route(identity, master_sha256, *, language, category,
                                   collection, projection_profile,
                                   allow_acceptance_metadata, acquisition_id):
    target = (identity == _PTA_HESYCHIUS_IDENTITY
              and acquisition_id == _PTA_HESYCHIUS_ACQUISITION
              and language == 'grc')
    if not target:
        if projection_profile == native_content.PTA_HESYCHIUS_PROFILE:
            raise PipelineError('Hesychius empty-sic profile requires its exact accepted edition')
        return False
    if (not allow_acceptance_metadata or category != 'prose' or collection
            or projection_profile not in (None, native_content.PTA_HESYCHIUS_PROFILE)
            or master_sha256 != _PTA_HESYCHIUS_MASTER_SHA):
        raise PipelineError('Hesychius empty-sic profile requires its exact accepted master')
    return True


_MOODY_MASTER_SHA = '127d8e70baa4cef26a5db89c4d4e09714dfcc4baca1af3a328803b18c4191251'
_MOODY_IDENTITY = {'work_id': 'd-l-moody-prevailing-prayer', 'textual_form_id': 'english', 'edition_id': 'd-l-moody-prevailing-prayer-pg61883'}
_MOODY_COUNTS = {'source-header': 1, 'source-div': 109, 'source-footer': 1, 'source-hr': 56, 'source-p': 283, 'source-blockquote': 44}


def _moody_profile_shape_et(root, raw, identity, language, category, collection):
    """Admit only the pinned, source-inventoried Moody body in the producer."""
    from collections import Counter
    if (identity != _MOODY_IDENTITY or language != 'en' or category != 'prose' or collection
            or hashlib.sha256(raw).hexdigest() != _MOODY_MASTER_SHA):
        raise PipelineError('Moody native profile binding differs')
    body = root.find(NS+'text/'+NS+'body')
    if body is None or len(body) != 495 or body[20].tag != NS+'table':
        raise PipelineError('Moody native body envelope differs')
    blocks = [node for node in body if node.tag == NS+'ab']
    if Counter(node.get('type') for node in blocks) != _MOODY_COUNTS or len(blocks) != 494:
        raise PipelineError('Moody native source carrier inventory differs')
    if (blocks[0].get('type') != 'source-header' or blocks[0].get('n') != '1'
            or blocks[-1].get('type') != 'source-footer' or blocks[-1].get('n') != '495'):
        raise PipelineError('Moody native source header/footer boundary differs')


def _moody_profile_shape_lxml(doc, raw, identity, language, category, collection):
    """Independently observe the pinned Moody body with lxml."""
    from collections import Counter
    if (identity != _MOODY_IDENTITY or language != 'en' or category != 'prose' or collection
            or hashlib.sha256(raw).hexdigest() != _MOODY_MASTER_SHA):
        raise ValueError('observed Moody native profile binding differs')
    body = doc.find(NS+'text/'+NS+'body')
    if body is None or len(body) != 495 or body[20].tag != NS+'table':
        raise ValueError('observed Moody native body envelope differs')
    blocks = [node for node in body if node.tag == NS+'ab']
    if Counter(node.get('type') for node in blocks) != _MOODY_COUNTS or len(blocks) != 494:
        raise ValueError('observed Moody source carrier inventory differs')
    if (blocks[0].get('type') != 'source-header' or blocks[0].get('n') != '1'
            or blocks[-1].get('type') != 'source-footer' or blocks[-1].get('n') != '495'):
        raise ValueError('observed Moody source header/footer boundary differs')



MARK_PROFILE = 'ocd-commentary-chadwick-mark-source-native-v1'
MTP_PROFILE = 'ocd-sermons-spurgeon-mtp-source-native-v1'
_WESLEY_MASTER_SHA = 'ba1e808e23b49fb623c8d0758731931b560a510aa42587666cf48079a35c5c1e'
_WESLEY_IDENTITY = {'work_id': 'john-wesley-sermons',
                    'textual_form_id': 'john-wesley-sermons-retained-electronic-en',
                    'edition_id': 'john-wesley-sermons-retained-electronic-edition'}
_WESLEY_ACQUISITION = 'john-wesley-sermons-retained-electronic-acquired'
WESLEY_PROFILE = 'ocd-sermons-wesley-ccel-native-v1'

_MTP_MASTER_SHA = 'e1db04c2728cddacd9ce6fa675ebb329fe931e4c79659d754b6de6df7be2addc'
_MTP_IDENTITY = {'work_id': 'spurgeon-mtp', 'textual_form_id': 'spurgeon-mtp-retained-en',
                 'edition_id': 'spurgeon-mtp-retained-electronic'}
_MARK_MASTER_SHA = 'd0c6a20dfe6bba8ee038d7d38f093af5d7a6bc49761e4b89a471101d81c5cc87'
_MARK_IDENTITY = {'work_id': 'expositors-bible--g-a-chadwick',
                  'textual_form_id': 'chadwick-expositors-retained-english',
                  'edition_id': 'expositors-bible--g-a-chadwick-mark-retained-electronic'}
_MARK_TOP_TYPES = ('title-page', 'contents') + ('chapter',) * 16 + ('indexes',)
_MARK_TOP_IDS = ('i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x', 'xi',
                 'xii', 'xiii', 'xiv', 'xv', 'xvi', 'xvii', 'xviii', 'xix')


def _wesley_route(identity, raw, *, language, category, collection,
                  projection_profile, source_base, acquisition_id,
                  allow_acceptance_metadata):
    if identity.get('work_id') != _WESLEY_IDENTITY['work_id']:
        return False
    if (identity != _WESLEY_IDENTITY or _sha(raw) != _WESLEY_MASTER_SHA
            or acquisition_id != _WESLEY_ACQUISITION or language != 'en'
            or category != 'sermons' or not collection
            or projection_profile is not None or source_base is not None
            or not allow_acceptance_metadata):
        raise PipelineError('Wesley native collection requires its exact accepted master and context')
    return True


def _wesley_header_rules(elements, attributes):
    elements = {name: list(children) for name, children in elements.items()}
    attributes = {name: list(names) for name, names in attributes.items()}
    for parent, child in (('seg', 'lb'), ('seg', 'hi'), ('seg', 'note')):
        if child not in elements.setdefault(parent, []):
            elements[parent].append(child)
    if 'rend' not in attributes.setdefault('seg', []):
        attributes['seg'].append('rend')
    return elements, attributes


def _mtp_route(identity, raw, *, language, category, collection, projection_profile,
               allow_acceptance_metadata, source_base):
    if identity.get('work_id') != 'spurgeon-mtp':
        return False
    if (identity != _MTP_IDENTITY or _sha(raw) != _MTP_MASTER_SHA or language != 'en'
            or category != 'sermons' or collection or projection_profile is not None
            or not allow_acceptance_metadata or source_base is not None):
        raise PipelineError('MTP native-unit route requires its exact accepted master and context')
    return True


def _mtp_body_et(body):
    units = list(body)
    if (len(units) != 3550 or any(unit.tag != NS+'div' or unit.get('type') != 'sermon'
                                  or not (unit.get('n') or '').isdecimal()
                                  or not unit.get(XML+'id') for unit in units)):
        raise PipelineError('MTP source sermon units differ')
    subtypes = [unit.get('subtype') for unit in units]
    if (subtypes.count('primary-article') != 3547
            or [(index, value) for index, value in enumerate(subtypes, 1)
                if value != 'primary-article'] != [
                    (695, 'supplemental-aig-sermon-content'),
                    (1685, 'supplemental-spurgeon-archive-sermon-content'),
                    (3019, 'supplemental-aig-sermon-content')]):
        raise PipelineError('MTP source subtype order differs')
    if (sum(node.get('type') == 'source-flow' for node in body.iter(NS+'ab')) != 3827
            or sum(node.get('type') == 'ordered' and node.get('rend') == 'a'
                   for node in body.iter(NS+'list')) != 3760
            or sum(node.get('type') == 'ordered' and node.get('rend') is None
                   for node in body.iter(NS+'list')) != 6
            or sum(1 for _ in body.iter(NS+'graphic')) != 27):
        raise PipelineError('MTP source flow, lists, or image counts differ')


def _mtp_body_lxml(body):
    units = list(body)
    if (len(units) != 3550 or any(unit.tag != NS+'div' or unit.get('type') != 'sermon'
                                  or not (unit.get('n') or '').isdecimal()
                                  or not unit.get(XML+'id') for unit in units)):
        raise ValueError('observed MTP source sermon units differ')
    supplemental = [(number, unit.get('subtype')) for number, unit in enumerate(units, 1)
                    if unit.get('subtype') != 'primary-article']
    if (len(units) - len(supplemental) != 3547 or supplemental != [
            (695, 'supplemental-aig-sermon-content'),
            (1685, 'supplemental-spurgeon-archive-sermon-content'),
            (3019, 'supplemental-aig-sermon-content')]):
        raise ValueError('observed MTP subtype order differs')
    blocks = body.xpath('.//t:ab', namespaces={'t': NS[1:-1]})
    lists = body.xpath('.//t:list', namespaces={'t': NS[1:-1]})
    graphics = body.xpath('.//t:graphic', namespaces={'t': NS[1:-1]})
    if (sum(node.get('type') == 'source-flow' for node in blocks) != 3827
            or sum(node.get('type') == 'ordered' and node.get('rend') == 'a' for node in lists) != 3760
            or sum(node.get('type') == 'ordered' and node.get('rend') is None for node in lists) != 6
            or len(graphics) != 27):
        raise ValueError('observed MTP source flow, lists, or image counts differ')


def _mark_route(identity, raw, *, language, category, collection, projection_profile,
                allow_acceptance_metadata, source_base):
    if identity.get('edition_id') != _MARK_IDENTITY['edition_id']:
        return False
    if (identity != _MARK_IDENTITY or _sha(raw) != _MARK_MASTER_SHA
            or language != 'en' or category != 'commentary' or collection
            or projection_profile is not None or not allow_acceptance_metadata
            or source_base != 'https://www.ccel.org/ccel/chadwick/mark.html'):
        raise PipelineError('Chadwick Mark native route requires its exact accepted context')
    return True


def _mark_body_et(body):
    top = list(body)
    if (tuple(child.tag for child in top) != (NS+'div',) * 19
            or tuple(child.get('type') for child in top) != _MARK_TOP_TYPES
            or tuple(child.get(XML+'id') for child in top) != _MARK_TOP_IDS):
        raise PipelineError('Chadwick Mark source top-unit order differs')
    divisions = list(body.iter(NS+'div'))
    blocks = list(body.iter(NS+'ab'))
    refs = list(body.iter(NS+'ref'))
    if (len(divisions), sum(node.get('next') is not None for node in divisions),
            sum(node.get('prev') is not None for node in divisions),
            len(blocks), sum(node.get('type') == 'heading' for node in blocks),
            sum(node.get('type') == 'scripture-commentary' for node in blocks),
            len(refs), sum(node.get(XML+'base') is not None for node in refs)) != (114, 110, 110, 270, 186, 84, 590, 348):
        raise PipelineError('Chadwick Mark linked divisions or source carriers differ')


def _mark_body_lxml(body):
    top = list(body)
    if (tuple(node.tag for node in top) != (NS+'div',) * 19
            or tuple(node.get('type') for node in top) != _MARK_TOP_TYPES
            or tuple(node.get(XML+'id') for node in top) != _MARK_TOP_IDS):
        raise ValueError('observed Chadwick Mark top-unit order differs')
    divisions = body.xpath('.//t:div', namespaces={'t': NS[1:-1]})
    blocks = body.xpath('.//t:ab', namespaces={'t': NS[1:-1]})
    refs = body.xpath('.//t:ref', namespaces={'t': NS[1:-1]})
    counts = (len(divisions), len([node for node in divisions if node.get('next') is not None]),
              len([node for node in divisions if node.get('prev') is not None]),
              len(blocks), len([node for node in blocks if node.get('type') == 'heading']),
              len([node for node in blocks if node.get('type') == 'scripture-commentary']),
              len(refs), len([node for node in refs if node.get(XML+'base') is not None]))
    if counts != (114, 110, 110, 270, 186, 84, 590, 348):
        raise ValueError('observed Chadwick Mark linked/source-carrier counts differ')
FARRAR_TEXT_SPACE_PROFILE = 'ocd-commentary-farrar-retained-text-space-v1'
_FARRAR_TEXT_SPACE_MASTERS = {
    'expositors-bible--frederic-w-farrar--farrar-expositor1kings--ccel-electronic': (
        'expositors-bible--frederic-w-farrar--farrar-expositor1kings--retained-en',
        'eaebe2ce2838dbad22f38d5dddf513f69209900550aa792c181e5ebe86cc436a',
        'https://www.ccel.org/ccel/farrar/expositor1kings.html'),
    'expositors-bible--frederic-w-farrar--farrar-expositor2kings--ccel-electronic': (
        'expositors-bible--frederic-w-farrar--farrar-expositor2kings--retained-en',
        'aa9399f8332bede05512a85033e409b18331c9faec39d3e506b2e34c6d9fdb42',
        'https://www.ccel.org/ccel/farrar/expositor2kings.html'),
    'expositors-bible--frederic-w-farrar--farrar-expositordan--ccel-electronic': (
        'expositors-bible--frederic-w-farrar--farrar-expositordan--retained-en',
        'c56899554b14bee5177dcb04d9c9a5d2cb2a371658eaae4f0732aaa98e2e7bb6',
        'https://www.ccel.org/ccel/farrar/expositordan.html'),
}
_AMERICAN_MISSIONARY_MASTERS = {
    'american-missionary-volume-36-1882-gutenberg-electronic': '23ba8c41c30e31a2c49f17ad3e9c2a2355fd955ca618242314c284ad305c80d4',
    'american-missionary-volume-37-1883-gutenberg-electronic': '3191c74c88e41515cf60f936c5b0d9fef8a9e2e8b6b37789fbfffe7dc60f72df',
}


def _american_missionary_profile(identity, raw, *, language, category, collection,
                                 projection_profile, allow_acceptance_metadata):
    selected = identity.get('work_id') == 'american-missionary'
    profiled = projection_profile == AMERICAN_MISSIONARY_PROFILE
    if selected != profiled:
        raise PipelineError('American Missionary requires its exact accepted profile')
    if profiled and (identity.get('textual_form_id') != 'american-missionary-gutenberg-retained-en'
                     or _AMERICAN_MISSIONARY_MASTERS.get(identity.get('edition_id')) != _sha(raw)
                     or language != 'en' or category != 'prose' or collection
                     or not allow_acceptance_metadata):
        raise PipelineError('American Missionary accepted identity or master differs')
    return profiled


def _farrar_text_space_route(identity, raw, *, language, category, collection,
                             projection_profile, source_base, allow_acceptance_metadata):
    """Admit only the three accepted Farrar witnesses' retained text wrapper."""
    if identity.get('work_id') != 'expositors-bible--frederic-w-farrar':
        return False
    expected = _FARRAR_TEXT_SPACE_MASTERS.get(identity.get('edition_id'))
    if (expected is None or identity != {'work_id': 'expositors-bible--frederic-w-farrar',
                                         'textual_form_id': expected[0],
                                         'edition_id': identity.get('edition_id')}
            or hashlib.sha256(raw).hexdigest() != expected[1] or source_base != expected[2]
            or language != 'en' or category != 'commentary' or collection
            or projection_profile is not None or not allow_acceptance_metadata):
        raise PipelineError('Farrar retained text-space profile requires its exact accepted witness')
    return True
_HODGE_IDENTITY = {'work_id': 'hodge-systematic-theology-vol-1',
                   'textual_form_id': 'hodge-systematic-theology-vol-1-english',
                   'edition_id': 'hodge-systematic-theology-vol-1-retained-electronic-witness'}
_PETER_JONES_MASTER_SHA = 'ee67ac29066b35c6fc98252d5f1bbfa8988a94df53f0fd7d7cb11eaa09354039'
_PETER_JONES_IDENTITY = {'work_id': 'peter-jones-life-and-journals',
                         'textual_form_id': 'peter-jones-life-and-journals-wikisource-retained',
                         'edition_id': 'peter-jones-life-and-journals-wikisource-electronic'}
VIRGIN_MARY_NOTE_PROFILE = 'ocd-prose-pg77576-virgin-mary-endnote-v1'
_VIRGIN_MARY_MASTER_SHA = 'ad7b9d02f056797d62f1bc2b7b79867b769b106168108ad7285a654491117665'
MAGNESIANS_NOTE_PROFILE = 'ocd-prose-pg77576-ignatius-magnesians-endnotes-v1'
_MAGNESIANS_MASTER_SHA = '415a4613bb5ec7d81b810cbc58bf4459b5f80a5761634ef61b03b75f8f84b6a2'
TRALLIANS_NOTE_PROFILE = 'ocd-prose-pg77576-ignatius-trallians-endnotes-v1'
_TRALLIANS_MASTER_SHA = '8694d86721038ca77afc027f1be395701e669cba2f66eee8de1c4f447e6ef513'
_GREENLEAF_CHARACTERS = (
    ('U0x2014', 'mdash; EM DASH', '--'),
    ('U0x2003', 'emsp; EM SPACE', '  '),
    ('U0x2026', 'hellip; HORIZONTAL ELLIPSIS', '...'),
)


def _virgin_mary_note_route(identity, raw, *, category, collection, projection_profile):
    """Keep this source's note-only back unit readable without changing other works."""
    if identity['work_id'] != 'pg77576-ignatius-virgin-mary':
        return False
    if (identity['edition_id'] != 'pg77576-ignatius-virgin-mary-pg77576-edition'
            or category != 'prose' or collection or projection_profile is not None
            or hashlib.sha256(raw).hexdigest() != _VIRGIN_MARY_MASTER_SHA):
        raise PipelineError('PG77576 Virgin Mary note projection requires its exact accepted master')
    return True


def _virgin_mary_note_text_et(unit):
    if (unit.tag != NS+'div' or unit.attrib != {'type': 'notes'} or len(unit) != 1
            or unit[0].tag != NS+'note' or unit[0].get(XML+'id') != 'f2025'
            or len(unit[0]) != 1 or unit[0][0].tag != NS+'p'):
        raise PipelineError('PG77576 Virgin Mary endnote unit differs')
    value = re.sub(r'\s+', ' ', ''.join(unit[0][0].itertext())).strip()
    if not value or 'Literally, “her own.”' not in value:
        raise PipelineError('PG77576 Virgin Mary endnote text differs')
    return value


def _virgin_mary_note_text_lxml(unit):
    if (unit.tag != NS+'div' or dict(unit.attrib) != {'type': 'notes'} or len(unit) != 1
            or unit[0].tag != NS+'note' or unit[0].get(XML+'id') != 'f2025'
            or len(unit[0]) != 1 or unit[0][0].tag != NS+'p'):
        raise ValueError('PG77576 Virgin Mary endnote unit differs')
    value = re.sub(r'\s+', ' ', unit[0][0].xpath('string()')).strip()
    if not value or 'Literally, “her own.”' not in value:
        raise ValueError('PG77576 Virgin Mary endnote text differs')
    return value


def _magnesians_note_route(identity, raw, *, category, collection,
                           projection_profile, allow_acceptance_metadata):
    """Make only the accepted Magnesians endnote unit readable."""
    if identity.get('work_id') != 'pg77576-ignatius-magnesians':
        return False
    expected = {
        'work_id': 'pg77576-ignatius-magnesians',
        'textual_form_id': 'pg77576-ignatius-magnesians-english',
        'edition_id': 'pg77576-ignatius-magnesians-pg77576-edition',
    }
    if (identity != expected or category != 'prose' or collection
            or projection_profile is not None or not allow_acceptance_metadata
            or hashlib.sha256(raw).hexdigest() != _MAGNESIANS_MASTER_SHA):
        raise PipelineError('PG77576 Magnesians note projection requires its exact accepted master')
    return True


def _trallians_note_route(identity, raw, *, category, collection,
                          projection_profile, allow_acceptance_metadata):
    """Admit only the accepted Trallians note-only back unit."""
    if identity.get('work_id') != 'pg77576-ignatius-trallians':
        return False
    expected = {
        'work_id': 'pg77576-ignatius-trallians',
        'textual_form_id': 'pg77576-ignatius-trallians-english',
        'edition_id': 'pg77576-ignatius-trallians-pg77576-edition',
    }
    if (identity != expected or category != 'prose' or collection
            or projection_profile is not None or not allow_acceptance_metadata
            or hashlib.sha256(raw).hexdigest() != _TRALLIANS_MASTER_SHA):
        raise PipelineError('PG77576 Trallians note projection requires its exact accepted master')
    return True


def _numbered_note_text_et(unit, *, first_number, count, first_paragraph, work_label):
    if unit.tag != NS+'div' or unit.attrib != {'type': 'notes'} or len(unit) != count:
        raise PipelineError(f'PG77576 {work_label} endnote unit differs')
    bodies = []
    for offset, note in enumerate(unit):
        number = first_number + offset
        if (note.tag != NS+'note'
                or note.attrib != {XML+'id': f'f{number}', 'n': str(number), 'place': 'end'}
                or len(note) != 1 or note[0].tag != NS+'p'
                or note[0].attrib != {'n': str(first_paragraph + offset)}
                or (note.text or '').strip() or (note[0].tail or '').strip()):
            raise PipelineError(f'PG77576 {work_label} endnote order or attachment differs')
        body = native_content.readable_content(native_content.project_content(note[0]))
        if not body or not body.startswith(f'{number}.'):
            raise PipelineError(f'PG77576 {work_label} endnote body or label differs')
        bodies.append(body)
    return '\n\n'.join(bodies)


def _numbered_note_text_lxml(unit, *, first_number, count, first_paragraph, work_label):
    if unit.tag != NS+'div' or dict(unit.attrib) != {'type': 'notes'} or len(unit) != count:
        raise ValueError(f'PG77576 {work_label} endnote unit differs')
    bodies = []
    for offset, note in enumerate(unit):
        number = first_number + offset
        if (note.tag != NS+'note'
                or dict(note.attrib) != {XML+'id': f'f{number}', 'n': str(number), 'place': 'end'}
                or len(note) != 1 or note[0].tag != NS+'p'
                or dict(note[0].attrib) != {'n': str(first_paragraph + offset)}
                or (note.text or '').strip() or (note[0].tail or '').strip()):
            raise ValueError(f'PG77576 {work_label} endnote order or attachment differs')
        body = observe_content(etree.tostring(note[0], with_tail=False))[1]
        if not body or not body.startswith(f'{number}.'):
            raise ValueError(f'PG77576 {work_label} endnote body or label differs')
        bodies.append(body)
    return '\n\n'.join(bodies)


def _greenleaf_characters_et(root):
    """Require the retained Gutenberg character map before exposing its glyph."""
    declaration = root.find(NS+'teiHeader/'+NS+'encodingDesc/'+NS+'charDecl')
    if declaration is None or len(declaration) != len(_GREENLEAF_CHARACTERS) or (declaration.text or '').strip():
        raise PipelineError('Greenleaf source character declaration differs')
    for char, (identifier, description, mapping) in zip(declaration, _GREENLEAF_CHARACTERS):
        if (char.tag != NS+'char' or char.attrib != {XML+'id': identifier}
                or [child.tag for child in char] != [NS+'desc', NS+'mapping']
                or (char.text or '').strip() or any((child.tail or '').strip() for child in char)
                or char[0].attrib or char[0].text != description or len(char[0])
                or char[1].attrib != {'type': 'txt.iso-8859-1'} or char[1].text != mapping or len(char[1])):
            raise PipelineError('Greenleaf source character declaration differs')
    text = root.find(NS+'text')
    if text is None:
        raise PipelineError('Greenleaf source text is missing')
    glyphs = list(text.iter(NS+'g'))
    if not glyphs or any(glyph.attrib != {'ref': '#U0x2014'} or glyph.text != '\u2014' or len(glyph) for glyph in glyphs):
        raise PipelineError('Greenleaf source em-dash glyph differs')


def _greenleaf_characters_lxml(root):
    """Check the same source declaration through independent lxml observations."""
    declarations = root.xpath('./t:teiHeader/t:encodingDesc/t:charDecl', namespaces={'t': NS[1:-1]})
    if len(declarations) != 1 or len(declarations[0]) != len(_GREENLEAF_CHARACTERS) or (declarations[0].text or '').strip():
        raise ValueError('Greenleaf source character declaration differs')
    for node, expected in zip(declarations[0], _GREENLEAF_CHARACTERS):
        identifier, description, mapping = expected
        children = list(node)
        if (node.tag != NS+'char' or dict(node.attrib) != {XML+'id': identifier}
                or [child.tag for child in children] != [NS+'desc', NS+'mapping']
                or (node.text or '').strip() or any((child.tail or '').strip() for child in node)
                or dict(children[0].attrib) or children[0].text != description or len(children[0])
                or dict(children[1].attrib) != {'type': 'txt.iso-8859-1'} or children[1].text != mapping or len(children[1])):
            raise ValueError('Greenleaf source character declaration differs')
    glyphs = root.xpath('./t:text//t:g', namespaces={'t': NS[1:-1]})
    if not glyphs or any(dict(glyph.attrib) != {'ref': '#U0x2014'} or glyph.text != '\u2014' or len(glyph) for glyph in glyphs):
        raise ValueError('Greenleaf source em-dash glyph differs')


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _prose_references(unit, book_codes, source_profile=None):
    if next(unit.iter(NS+'ref'), None) is None:
        return []
    schema_raw = native_content.SCHEMA.read_bytes()
    policy = json.loads(schema_raw)['x-ocd-native-content']
    result = []
    def visit(node, location):
        if node.tag == NS+'ref':
            record = normalize_reference_record({'raw': native_content.readable_content(native_content.project_content(node,source_profile=source_profile, _policy=policy), _policy=policy), **{key: node.get(key) for key in ('cRef', 'target') if node.get(key) is not None}}, book_codes=book_codes)
            result.append({**record, 'source_child_path': location})
        for index, child in enumerate(node):
            visit(child, location + [index])
    visit(unit, [])
    if native_content.SCHEMA.read_bytes() != schema_raw:
        raise PipelineError('native content schema changed during reference projection')
    return result


def _observe_prose_references(unit, book_codes, source_profile=None):
    from ocd_kernel.projection import native_content_check
    if next(unit.iter(NS+'ref'), None) is None:
        return []
    schema_raw = native_content_check.SCHEMA.read_bytes()
    schema = json.loads(schema_raw)
    records = []
    for node in unit.iter(NS+'ref'):
        location = []
        ancestor = node
        while ancestor is not unit:
            parent = ancestor.getparent()
            location.insert(0, parent.index(ancestor))
            ancestor = parent
        record = observe_reference_record({'raw': observe_content(etree.tostring(node, with_tail=False),source_profile=source_profile, _schema=schema)[1], **{key: node.get(key) for key in ('cRef', 'target') if node.get(key) is not None}}, book_codes=book_codes)
        records.append({**record, 'source_child_path': location})
    if native_content_check.SCHEMA.read_bytes() != schema_raw:
        raise ValueError('native content schema changed during reference verification')
    return records


def _entry_attribution(unit):
    """Read only an explicit attribution note attached to this output unit."""
    notes = unit.findall(NS + "note[@type='source-attribution']")
    if not notes:
        return {}
    if len(notes) != 1:
        raise PipelineError('multiple entry source-attribution notes')
    note = notes[0]
    if (note.text or '').strip() or any((node.tail or '').strip() for node in note):
        raise PipelineError('unassigned entry attribution text')
    result = {}
    for node in note:
        role = node.get('type')
        if node.tag == NS+'seg' and role in ('source-title', 'source-credit', 'source-location', 'attribution-note'):
            value = native_content.readable_content(native_content.project_content(node))
        elif node.tag == NS+'ref' and role == 'source-url':
            value = node.get('target', '')
            if not re.fullmatch(r'https?://[^\s/]+(?:/[^\s]*)?', value):
                raise PipelineError('entry source URL requires an explicit HTTP(S) target')
        else:
            raise PipelineError('unsupported entry attribution field')
        key = role.replace('-', '_')
        if not value.strip() or key in result:
            raise PipelineError('empty or duplicate entry attribution field')
        result[key] = value
    if not result:
        raise PipelineError('empty entry source-attribution note')
    return result


def _observe_entry_attribution(unit):
    """Independently read scoped attribution using the checker's lxml tree."""
    notes = unit.xpath('./t:note[@type="source-attribution"]', namespaces={'t': NS[1:-1]})
    if len(notes) > 1:
        raise ValueError('ambiguous entry attribution')
    result = {}
    for note in notes:
        if (note.text or '').strip() or any((child.tail or '').strip() for child in note):
            raise ValueError('unassigned attribution text')
        for child in note:
            role = child.get('type')
            if child.tag == NS+'ref' and role == 'source-url':
                value = child.get('target', '')
                if not re.fullmatch(r'https?://[^\s/]+(?:/[^\s]*)?', value):
                    raise ValueError('invalid attribution URL')
            elif child.tag == NS+'seg' and role in ('source-title', 'source-credit', 'source-location', 'attribution-note'):
                value = observe_content(etree.tostring(child, with_tail=False))[1]
            else:
                raise ValueError('unknown attribution field')
            field = role.replace('-', '_')
            if field in result or not value.strip():
                raise ValueError('duplicate or empty attribution field')
            result[field] = value
        if not result:
            raise ValueError('empty attribution')
    return result


THOME_PROFILE = 'ocd-prose-thome-pg70704-source-native-v1'

def _header_rules(accepted):
    from ocd_kernel.projection.categories import sermons
    if accepted:
        return sermons._ACCEPTANCE_HEADER_ELEMENTS, sermons._ACCEPTANCE_HEADER_ATTRIBUTES
    policy = json.loads(sermons.SCHEMA.read_text(encoding='utf-8'))['x-ocd-profile']
    return policy['elements'], policy['attributes']


_BENNETT_CHRONICLES_IDENTITY = {
    'work_id': 'expositors-bible--w-h-bennett',
    'textual_form_id': 'expositors-bible--w-h-bennett--bennett-expositor10--retained-en',
    'edition_id': 'expositors-bible--w-h-bennett--bennett-expositor10--ccel-electronic',
}
_BENNETT_CHRONICLES_MASTER_SHA = '687ada6bf687e9727f2e95d76b8d66d96d1a9af7a2f04a20fe906cfd01a3e523'


def _bennett_chronicles_route(identity, raw, *, language, category, collection,
                              projection_profile, source_base, acquisition_id,
                              allow_acceptance_metadata):
    eligible = (identity == _BENNETT_CHRONICLES_IDENTITY
                and language == 'en' and category == 'commentary' and not collection
                and projection_profile is None and allow_acceptance_metadata
                and source_base == 'https://www.ccel.org/ccel/bennett/expositor10.html'
                and acquisition_id == 'expositors-bible--w-h-bennett--bennett-expositor10--acquired'
                and _sha(raw) == _BENNETT_CHRONICLES_MASTER_SHA)
    if identity.get('edition_id') == _BENNETT_CHRONICLES_IDENTITY['edition_id'] and not eligible:
        raise PipelineError('Bennett Chronicles route requires exact accepted master and identity')
    return eligible


_TITLE_EXPOSITOR_MEMBERS = {
    'blaikie-first-book-of-samuel': (
        'raw/ccel/expositors-bible/blaikie_expositor8.xml',
        'b46bd6cb856df0819dedc06b23a657f7763b49501248db63ce762585d67603d4',
        818071, 'https://www.ccel.org/ccel/blaikie/expositor8.html'),
    'blaikie-second-book-of-samuel': (
        'raw/ccel/expositors-bible/blaikie_expositor2sam.xml',
        'e3397acdd20cbc7ea8ef6c81eb10407263fe1276b40973c07cd908cf4902c379',
        758940, 'https://www.ccel.org/ccel/blaikie/expositor2sam.html'),
    'blaikie-book-of-joshua': (
        'raw/ccel/expositors-bible/blaikie_expositorjosh.xml',
        '7a2be4c01ca4ed8ecf37aa6905a161c126ac8cc4752e00448126ae363d2139b3',
        823168, 'https://www.ccel.org/ccel/blaikie/expositorjosh.html'),
}


def _expositor_base_identity(identity, source_base):
    work = identity.get('work_id')
    if work.startswith('expositors-bible--'):
        return True
    expected = _TITLE_EXPOSITOR_MEMBERS.get(work)
    return expected is not None and source_base == expected[3]


def _accepted_expositor_source_base(context, category):
    """Bind legacy or exact title-specific Expositor base to accepted source."""
    if category != 'commentary':
        return None
    work = context['identity']['work_id']
    member = _TITLE_EXPOSITOR_MEMBERS.get(work)
    if not work.startswith('expositors-bible--') and member is None:
        return None
    from ocd_kernel.library.acquisitions import acquisition_for_edition

    _, acquisition = acquisition_for_edition(
        context['root'], work, context['identity']['edition_id'],
        acquisition_id=context['accepted']['identity']['acquisition_id'])
    base = acquisition.get('url')
    if not isinstance(base, str) or not re.fullmatch(
            r'https://www\.ccel\.org/ccel/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.html', base):
        raise PipelineError('accepted Expositor acquisition URL differs')
    if member is not None:
        path, digest, length, expected_url = member
        source = context['accepted'].get('source', {})
        retained = io_path(context['root'] / path).read_bytes()
        if (base != expected_url
                or source.get('source_path') != path
                or source.get('source_sha256') != digest
                or source.get('source_bytes') != length
                or acquisition.get('source_path') != path
                or acquisition.get('source_sha256') != digest
                or acquisition.get('source_bytes') != length
                or len(retained) != length or _sha(retained) != digest):
            raise PipelineError('title-specific Expositor member authority differs')
    return base


_XML_MODEL_SCHEMAS = {
    "https://raw.githubusercontent.com/PatristicTextArchive/Schema/master/tei-pta.rng",
    "http://www.stoa.org/epidoc/schema/latest/tei-epidoc.rng",
}
_PTA_SOURCE_COMMENT_COUNTS = {
    "amphilochius-epistula-synodalis": 2,
    "anonymous-vita-sancti-cononis-bidanae": 38,
    "hesychius-commentarius-magnus-in-psalmos": 67,
    "severian-de-fide-et-lege-naturae": 6,
}
_PTA_XML_MODEL_HINT = (
    'href="https://raw.githubusercontent.com/PatristicTextArchive/Schema/master/tei-pta.rng" '
    'schematypens="http://relaxng.org/ns/structure/1.0"'
)


def _source_document_marker_ledger(raw, *, expected_pta_comment_count=None):
    """Keep recognized source comments and XML model hints private and accounted."""
    try:
        document = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise PipelineError(f'invalid native sermon XML: {exc}') from exc
    tree = document.getroottree()
    if tree.docinfo.doctype:
        raise PipelineError('unsupported native sermon declarations')
    all_instructions = tree.xpath('//processing-instruction()')
    all_comments = tree.xpath('//comment()')
    records = {}
    declared_evidence = document.find(NS+'standOff') is not None
    prolog = list(document.itersiblings(preceding=True)); prolog.reverse()
    processing_instructions = []
    for instruction in all_instructions:
        match = re.fullmatch(
            r'\s*href="([^"]+)"\s+schematypens="([^"]+)"\s*',
            instruction.text or '',
        )
        if (
            instruction.getparent() is not None
            or instruction not in prolog
            or instruction.target != 'xml-model'
            or match is None
            or match.group(1) not in _XML_MODEL_SCHEMAS
            or match.group(2) != 'http://relaxng.org/ns/structure/1.0'
        ):
            raise PipelineError('unsupported native source processing instruction')
        processing_instructions.append({
            'parent_path': '#document', 'child_index': prolog.index(instruction),
            'target': instruction.target, 'text': instruction.text or '',
            'tail': instruction.tail or '', 'disposition': 'private-xml-model-hint',
        })
    if expected_pta_comment_count is not None and (
        len(all_comments) != expected_pta_comment_count
        or len(processing_instructions) != 1
        or processing_instructions[0]['text'] != _PTA_XML_MODEL_HINT
    ):
        raise PipelineError('unsupported PTA source comment profile')
    for comment in all_comments:
        if comment.getparent() is not None:
            continue
        if declared_evidence and comment in prolog and not (comment.tail or '').strip():
            records[comment] = {'parent_path': '#document', 'child_index': prolog.index(comment), 'text': comment.text or '', 'tail': comment.tail or '', 'disposition': 'source-prolog-comment-evidence'}
            continue
        if comment.text != ' Copyright Christian Classics Ethereal Library ' or comment.getprevious() is not None or comment.getnext() is not document or (comment.tail or '').strip():
            raise PipelineError('unsupported native prolog comment')
        records[comment] = {'parent_path': '#document', 'child_index': 0,
                            'text': comment.text, 'tail': comment.tail or '',
                            'disposition': 'source-rights-notice-handoff'}
    for parent in tree.iter():
        comments = [child for child in parent if isinstance(child, etree._Comment)]
        if not comments:
            continue
        if parent.tag == NS+'body':
            if len(comments) != 2 or [item.text for item in comments] != [' added reason="AutoIndexing" ', ' /added '] or parent.index(comments[1]) <= parent.index(comments[0])+1:
                raise PipelineError('unsupported native auto-index wrapper')
            groups = [(comments, 'private-auto-index-wrapper')]
        elif parent.tag == NS+'div' and len(comments) % 4 == 0:
            groups = [(comments[offset:offset+4], 'private-auto-index-marker') for offset in range(0, len(comments), 4)]
            for group, _ in groups:
                begin, opening, closing, end = group
                match = re.fullmatch(r' added reason="insertIndex" class="(scripRef|scripCom|foreign)" ', begin.text or '')
                if not match or [opening.text, closing.text, end.text] != [
                    f' Start of automatically inserted {match.group(1)} index ',
                    f' End of {match.group(1)} index ', ' /added ',
                ] or parent.index(opening) != parent.index(begin)+1 or parent.index(end) != parent.index(closing)+1 or parent.index(closing) <= parent.index(opening)+1:
                    raise PipelineError('unsupported native source comment structure')
        elif parent.tag == NS+'seg' and parent.attrib == {XML+'id': 'npnf105-xiv.iv-p1.2', 'rend': 'MsoEndnoteReference'}:
            if (len(comments) != 2 or len(parent) != 2 or (parent.text or '') != ' '
                    or comments[0].text != ' <a href="#_edn1609" name="_ednref1609" id="xiv.iv-p1.3">  '
                    or comments[0].tail != '[1609]' or comments[1].text != ' </a> '
                    or (comments[1].tail or '') != ''):
                raise PipelineError('unsupported native source endnote marker')
            groups = [(comments, 'source-endnote-anchor-marker')]
        elif parent.tag == NS+'seg' and parent.attrib == {XML+'id': 'npnf105-xxi.ii-p5.2', 'rend': 'MsoEndnoteReference'}:
            paragraph = parent.getparent()
            if (paragraph is None or paragraph.tag != NS+'p'
                    or paragraph.attrib != {XML+'id': 'npnf105-xxi.ii-p5', 'rend': 'c39'}
                    or len(paragraph) != 2 or paragraph.index(parent) != 1
                    or len(comments) != 2 or len(parent) != 2 or (parent.text or '') != ''
                    or comments[0].text != ' <a href="#_edn3415" name="_ednref3415" id="xxi.ii-p5.3"> '
                    or comments[0].tail != ' [3415]' or comments[1].text != ' </a> '
                    or (comments[1].tail or '') != ''):
                raise PipelineError('unsupported native source endnote marker')
            groups = [(comments, 'source-endnote-anchor-marker')]
        elif expected_pta_comment_count is not None:
            groups = [(comments, 'private-pta-editorial-comment')]
        else:
            raise PipelineError('unsupported native source comment location')
        for group, disposition in groups:
            for comment in group:
                if disposition not in {'source-endnote-anchor-marker', 'private-pta-editorial-comment'} and (comment.tail or '').strip():
                    raise PipelineError('native source comment has visible tail text')
                records[comment] = {'parent_path': tree.getpath(parent),
                                    'child_index': parent.index(comment), 'text': comment.text or '',
                                    'tail': comment.tail or '', 'disposition': disposition}
    if len(records) != len(all_comments):
        raise PipelineError('unsupported native source comment location')
    return [records[comment] for comment in all_comments], processing_instructions


def _schema_bindings(category):
    from ocd_kernel.projection.categories import sermons
    return {key: _sha(path.read_bytes()) for key, path in {
        'schema_sha256': sermons.ROOT / f'schemas/v2/categories/{category}.schema.json',
        'common_schema_sha256': sermons.COMMON,
        'native_content_schema_sha256': native_content.SCHEMA,
    }.items()}


def _validate_rows(rows, category):
    from ocd_kernel.projection.categories import sermons
    if category == 'sermons':
        schema, validator = sermons._schema()
        # Construct after reordering: evolve() selects the plain class via $schema.
        _, native_validator = sermons._schema(native_first=True)
    elif category == 'poetry':
        from ocd_kernel.projection.categories.poetry import _validator
        validator = _validator()
    elif category == 'prayers':
        from ocd_kernel.projection.categories.prayers import _prayers_validator
        validator = _prayers_validator()
    elif category == 'commentary':
        from ocd_kernel.projection.categories.commentary import _validator
        validator = _validator()
    else:
        from ocd_kernel.projection.categories.prose import _prose_validator
        validator = _prose_validator()
    for row in rows:
        selected = (native_validator if category == 'sermons' and isinstance(row, dict)
                    and isinstance(row.get('locator'), dict)
                    and row['locator'].get('kind') == 'native-unit' else validator)
        problem = next(selected.iter_errors(row), None)
        if problem is not None:
            if selected is not validator:
                problem = next(validator.iter_errors(row))
            raise PipelineError('native sermon schema: ' + problem.message)


def select_accepted_source_lines_profile(root, context):
    """Select a line-preserving electronic transcription from bound source bytes.

    The profile is available only when every numbered body carrier reproduces
    the complete retained source in order. The accepted source-accounting
    document must independently bind that source and the unchanged body.
    """
    accepted = context['accepted']
    source = accepted.get('source', {})
    accounting = source.get('accounting')
    if not isinstance(accounting, dict) or not isinstance(accounting.get('path'), str):
        return None
    root = Path(root).resolve()
    try:
        accounting_path = resolve_repo_path(root, accounting['path'])
    except StorageTopologyError as exc:
        raise PipelineError('accepted source-line accounting outside configured storage') from exc
    raw_accounting = io_path(accounting_path).read_bytes()
    if (len(raw_accounting) != accounting.get('bytes')
            or _sha(raw_accounting) != accounting.get('sha256')):
        raise PipelineError('accepted source-line accounting binding differs')
    data = json.loads(raw_accounting)
    if not isinstance(data, dict) or data.get('accepted_body_unchanged') is not True:
        return None
    try:
        source_path = resolve_repo_path(root, source.get('source_path', ''))
    except StorageTopologyError as exc:
        raise PipelineError('accepted source-line source outside configured storage') from exc
    source_raw = io_path(source_path).read_bytes()
    if (len(source_raw) != source.get('source_bytes')
            or _sha(source_raw) != source.get('source_sha256')
            or data.get('source_sha256') != source.get('source_sha256')):
        raise PipelineError('accepted source-line retained source binding differs')
    document = ET.parse(context['edition'].path).getroot()
    body = document.find('.//' + NS + 'body')
    if body is None:
        return None
    carriers = [node for node in body.iter()
                if node.tag in {NS + 'ab', NS + 'head'} and node.get('n') is not None]
    if not carriers or any(node.tag == NS + 'head' and node.get('type') != 'source-line'
                           for node in carriers):
        return None
    if any(node.tag == NS + 'ab' and node.get('type') not in native_content.SOURCE_LINES_BLOCK_TYPES | {'blank'}
           for node in carriers):
        return None
    try:
        lines = source_raw.decode('utf-8').splitlines()
    except UnicodeDecodeError as exc:
        raise PipelineError('accepted source-line source is not UTF-8') from exc
    if source_raw.endswith(b'\n') and len(lines) + 1 == len(carriers):
        lines.append('')
    if len(lines) != len(carriers):
        raise PipelineError('accepted source-line count differs from retained source')
    for number, (node, line) in enumerate(zip(carriers, lines), 1):
        if node.get('n') != str(number) or len(node) or (node.text or '') != line:
            raise PipelineError(f'accepted source-line {number} differs from retained source')
    return native_content.SOURCE_LINES_PROFILE


def _source_lines_public_shadow(unit):
    """Omit a CCEL text-cache generator footer from public source-line rows.

    Its local ``file://`` links cannot enter a public dataset. Every omitted
    leaf remains in the accepted master and is explicitly marked in inventory.
    This policy applies only when the complete, recognizable generator footer
    follows the historical body; all other source lines remain public.
    """
    carriers = [node for node in unit.iter()
                if node.tag in {NS + 'ab', NS + 'head'} and node.get('n') is not None]
    markers = [index for index, node in enumerate(carriers)
               if (node.text or '').strip() == 'This document is from the Christian Classics Ethereal']
    if not markers:
        return unit, set()
    if len(markers) != 1:
        raise PipelineError('CCEL source-generator footer boundary is ambiguous')
    start = markers[0]
    suffix = carriers[start:]
    prefix = [(node.text or '').strip() for node in suffix[:6]]
    if prefix != [
            'This document is from the Christian Classics Ethereal',
            'Library at Calvin College, http://www.ccel.org,',
            'generated on demand from ThML source.', '', 'References', '',
    ] or not any('file:///ccel/' in (node.text or '') for node in suffix[6:]):
        raise PipelineError('CCEL source-generator footer content differs')
    references = suffix[6:]
    if references and not (references[-1].text or '').strip():
        references = references[:-1]
    if any(re.fullmatch(r'[0-9]+\. file:///ccel/\S+', (node.text or '').strip()) is None
           for node in references):
        raise PipelineError('CCEL footer contains content outside generated references')
    excluded = set(suffix)
    shadow = deepcopy(unit)
    original_by_shadow = dict(zip(shadow.iter(), unit.iter()))
    parents = {child: parent for parent in shadow.iter() for child in parent}
    for node in list(shadow.iter()):
        if node.tag in {NS + 'ab', NS + 'head'} and node.get('n') is not None:
            try:
                number = int(node.get('n'))
            except ValueError as exc:
                raise PipelineError('source-line number is not numeric') from exc
            if number >= int(suffix[0].get('n')):
                parent = parents[node]
                parent.remove(node)
                while (parent is not shadow and parent.tag == NS + 'div'
                       and not len(parent) and not (parent.text or '').strip()):
                    excluded.add(original_by_shadow[parent])
                    ancestor = parents[parent]
                    ancestor.remove(parent)
                    parent = ancestor
    return shadow, excluded


def _greenleaf_units_et(document):
    text = document.find(NS+'text')
    if text is None or [part.tag for part in text] != [NS+'front', NS+'body', NS+'back']:
        raise PipelineError('Greenleaf marker profile requires front, body, and back')
    selected = []
    private_nodes = set()
    for part in text:
        name = part.tag[len(NS):]
        if name == 'body':
            if not len(part) or len(part) % 3:
                raise PipelineError('Greenleaf body lacks complete page-marker triples')
            for offset in range(0, len(part), 3):
                page, anchor, division = part[offset:offset+3]
                page_number = page.get('n')
                if ([node.tag for node in (page, anchor, division)] != [NS+'pb', NS+'anchor', NS+'div']
                        or not page_number or anchor.get(XML+'id') != 'Pg'+page_number
                        or any((node.text or '').strip() or len(node) for node in (page, anchor))):
                    raise PipelineError('Greenleaf body page-marker triple differs')
                selected.append((1, name, offset+3, division, '', (page, anchor)))
        else:
            for sibling, unit in enumerate(part, 1):
                if unit.tag != NS+'div':
                    raise PipelineError('Greenleaf front/back requires source divisions')
                generator = unit[0] if len(unit) == 1 and unit[0].tag == NS+'divGen' else None
                if generator is not None and not (unit.text or '').strip() and not (generator.tail or '').strip():
                    allowed = {'pgheader', 'encodingDesc'} if name == 'front' else {'pgfooter'}
                    if generator.get('type') not in allowed or len(generator) or (generator.text or '').strip():
                        raise PipelineError('Greenleaf private generator division differs')
                    private_nodes.update(unit.iter())
                else:
                    selected.append((1, name, sibling, unit, '', ()))
    if not selected or not private_nodes:
        raise PipelineError('Greenleaf source unit accounting is empty')
    return selected, private_nodes


_SOURCE_NODE_KEYS = {'attributes', 'feature_id', 'kind', 'namespace_declarations', 'ordinal',
                     'parent_ordinal', 'payload_sha256', 'pi_target', 'qname', 'scope',
                     'sibling_ordinal', 'tail', 'text'}


def _readable_source_member(root, unit, *, corpus):
    """Select the readable child only after binding its sibling to source evidence."""
    if unit.tag != NS+'div' or unit.get('type') != 'retained-source-member':
        return None
    if not corpus or set(unit.attrib) != {'type'} or len(unit) != 2 or (unit.text or '').strip() or any((child.tail or '').strip() for child in unit):
        raise PipelineError('invalid retained source member envelope')
    readable, evidence = unit
    if readable.tag != NS+'div' or readable.get('type') != 'readable-transcription' or evidence.tag != NS+'div' or evidence.attrib != {'type': 'exact-source-evidence'} or len(evidence) != 2:
        raise PipelineError('invalid readable/source-evidence pair')
    raw_bytes, transcription = evidence
    if raw_bytes.tag != NS+'ab' or set(raw_bytes.attrib) != {'type', 'subtype', 'n'} or raw_bytes.get('type') != 'exact-retained-source-bytes' or raw_bytes.get('subtype') != 'base64' or len(raw_bytes):
        raise PipelineError('invalid retained source bytes carrier')
    if transcription.tag != NS+'div' or transcription.attrib != {'type': 'complete-xml-node-transcription'} or not len(transcription):
        raise PipelineError('invalid complete source-node transcription')
    if (evidence.text or '').strip() or (transcription.text or '').strip() or any((child.tail or '').strip() for child in evidence.iter()):
        raise PipelineError('loose source-evidence text')
    hashes = [node.text.strip() for node in root[0].iter(NS+'idno') if node.get('type') in ('sha256', 'source_sha256') and node.text]
    if len(hashes) != 2 or len(set(hashes)) != 1 or not re.fullmatch(r'[0-9a-f]{64}', hashes[0]):
        raise PipelineError('retained source evidence lacks one header hash')
    try:
        decoded = base64.b64decode(raw_bytes.text or '', validate=True)
    except (ValueError, binascii.Error) as exc:
        raise PipelineError('invalid retained source base64 evidence') from exc
    if _sha(decoded) != hashes[0] or raw_bytes.get('n') != hashes[0]:
        raise PipelineError('retained source bytes do not bind source header')
    for ordinal, node in enumerate(transcription, 1):
        if node.tag != NS+'ab' or set(node.attrib) != {XML+'id', 'type', 'subtype', 'n'} or node.get('type') != 'source-xml-node' or node.get('n') != str(ordinal) or not node.text or len(node):
            raise PipelineError('invalid source XML node carrier')
        try:
            record = json.loads(node.text)
        except json.JSONDecodeError as exc:
            raise PipelineError('invalid source XML node JSON') from exc
        if not isinstance(record, dict) or set(record) != _SOURCE_NODE_KEYS or record.get('ordinal') != ordinal or record.get('feature_id') != node.get(XML+'id') or record.get('kind') != node.get('subtype') or record.get('kind') not in ('element', 'comment'):
            raise PipelineError('source XML node does not bind its carrier')
    return readable, evidence


def project_document(path, *, identity, language, representation_revision, edition_title,
                     _allow_acceptance_metadata=False, category="sermons", collection=False,
                     projection_profile=None, source_base=None, public_disposition=None,
                     group_profile=None, guyon_binding=None, acquisition_id=None):
    raw = io_path(Path(path)).read_bytes()
    thome_exact = (_allow_acceptance_metadata and category == 'prose' and identity == {'work_id':'james-a-thome-prayer-oppressed','textual_form_id':'james-a-thome-prayer-oppressed-1859','edition_id':'james-a-thome-prayer-oppressed-pg70704'} and language == 'en' and not collection and projection_profile is None and hashlib.sha256(raw).hexdigest() == '8a79d0d778d87e501c4109632c50461289afa3aa13f4240ec90330bb8d6dc6d5')
    bennett_chronicles = _bennett_chronicles_route(
        identity, raw, language=language, category=category, collection=collection,
        projection_profile=projection_profile, source_base=source_base,
        acquisition_id=acquisition_id, allow_acceptance_metadata=_allow_acceptance_metadata)
    gaines_exact = (_allow_acceptance_metadata and category == 'prose' and identity == {'work_id':'gaines-african-methodism-south-1890','textual_form_id':'gaines-docsouth-retained','edition_id':'gaines-docsouth-electronic'} and language == 'en' and not collection and projection_profile is None and source_base is None and acquisition_id == 'gaines-docsouth-acquired' and _sha(raw) == '17342bef749798012bf0bcd581be474a8127fd7e8cb3680a87f86139130bb280')
    if identity.get('work_id') == 'gaines-african-methodism-south-1890' and not gaines_exact:
        raise PipelineError('Gaines retained header route requires its exact accepted master and identity')
    pta_vita_sic = _pta_anonymous_vita_sic_route(
        identity, _sha(raw), language=language, category=category,
        collection=collection, projection_profile=projection_profile,
        allow_acceptance_metadata=_allow_acceptance_metadata,
        acquisition_id=acquisition_id)
    pta_hesychius_sic = _pta_hesychius_empty_sic_route(
        identity, _sha(raw), language=language, category=category,
        collection=collection, projection_profile=projection_profile,
        allow_acceptance_metadata=_allow_acceptance_metadata,
        acquisition_id=acquisition_id)
    if identity.get('work_id') == 'james-a-thome-prayer-oppressed' and not thome_exact:
        raise PipelineError('Thome retained reader requires its exact master, identity, language and category')
    fox_exact = fox_source.route(raw, identity=identity, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata)
    woolman_exact = woolman_source.route(raw, identity=identity, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata)
    if group_profile is not None:
        if (not _allow_acceptance_metadata or category != 'commentary' or collection
                or projection_profile is not None or source_base is not None
                or identity != {key: group_profile['identity'][key]
                                for key in ('work_id', 'textual_form_id', 'edition_id')}
                or _sha(raw) != group_profile['master_sha256']):
            raise PipelineError('accepted complete-group commentary profile differs')
        commentary_group_policy.source_census_et(raw, group_profile)
    if public_disposition is not None and (public_disposition != identity.get('work_id')
                                           or category != ('sermons' if public_disposition == native_public_dispositions.NEWMAN_WORK else 'poetry' if public_disposition == native_public_dispositions.COX_WORK else 'prose') or collection != (public_disposition == native_public_dispositions.NEWMAN_WORK)
                                           or projection_profile is not None or not _allow_acceptance_metadata):
        raise PipelineError('native public disposition requires its accepted identity/category')
    scan = raw.replace(b'\x00', b'')
    if any(token in scan.upper() for token in (b'<!DOCTYPE', b'<!ENTITY')):
        raise PipelineError('unsupported native sermon declarations')
    pta_comment_count = (
        _PTA_SOURCE_COMMENT_COUNTS.get(identity.get('work_id'))
        if _allow_acceptance_metadata else None
    )
    comments, processing_instructions = _source_document_marker_ledger(
        raw, expected_pta_comment_count=pta_comment_count)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PipelineError('invalid native sermon XML') from exc
    if fox_exact:
        fox_source.check_et(root, raw)
    if woolman_exact:
        woolman_source.check_et(root, raw)
    binding_wrapper = None
    if _allow_acceptance_metadata:
        header = root.find(NS+'teiHeader')
        marked = ([node for node in header.iter(NS+'bibl')
                   if node.get('type') == 'ocd-acceptance-binding'] if header is not None else [])
        if len(marked) > 1:
            raise PipelineError('multiple native acceptance bindings')
        if marked:
            parents = {child: parent for parent in header.iter() for child in parent}
            binding = marked[0]
            parent = parents.get(binding)
            source_desc = header.find(NS+'fileDesc/'+NS+'sourceDesc')
            if parent is source_desc:
                pass
            elif (parent is not None and parent.tag == NS+'p'
                  and parents.get(parent) is source_desc and not parent.attrib
                  and len(parent) == 1 and parent[0] is binding
                  and not (parent.text or '').strip()
                  and not (binding.tail or '').strip()
                  and not (parent.tail or '').strip()):
                binding_wrapper = parent
            else:
                raise PipelineError('unsupported native acceptance binding location')
    source_projection_nodes = project_evidence(root)
    if category not in ('sermons', 'prose', 'poetry', 'prayers', 'commentary') or (collection and category != 'sermons'):
        raise PipelineError('unsupported native category')
    if source_base is not None and (category != 'commentary' or not _allow_acceptance_metadata
                                    or not _expositor_base_identity(identity, source_base)):
        raise PipelineError('native source reference base requires accepted Expositor commentary')
    mark = _mark_route(identity, raw, language=language, category=category,
                       collection=collection, projection_profile=projection_profile,
                       allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
    wesley = _wesley_route(identity, raw, language=language, category=category,
                           collection=collection, projection_profile=projection_profile,
                           source_base=source_base, acquisition_id=acquisition_id,
                           allow_acceptance_metadata=_allow_acceptance_metadata)
    mtp = _mtp_route(identity, raw, language=language, category=category,
                     collection=collection, projection_profile=projection_profile,
                     allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
    samuel = _samuel_route(identity, raw, language=language, category=category,
                           collection=collection, projection_profile=projection_profile,
                           allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
    john = _john_route(identity, raw, language=language, category=category,
                       collection=collection, projection_profile=projection_profile,
                       allow_acceptance_metadata=_allow_acceptance_metadata,
                       source_base=source_base, group_profile=group_profile)
    if john:
        tyerman_john_group_profile.source_census_et(root)
    if samuel:
        _samuel_source_et(root)
    whitefield = whitefield_source.route(identity, raw, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
    l599 = l599_source.route(identity, raw, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
    if l599:l599_source.check_et(root)
    strong = strong_source.route(identity, raw, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
    if strong:
        try:strong_source.check_et(root)
        except ValueError as exc:raise PipelineError(str(exc)) from exc
    if whitefield:whitefield_source.check_et(root)
    strong_group = strong_complete.route(identity, raw, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base, acquisition_id=acquisition_id)
    if strong_group:strong_complete.check_et(root)
    virgin_mary_note = _virgin_mary_note_route(identity, raw, category=category,
                                               collection=collection, projection_profile=projection_profile)
    magnesians_note = _magnesians_note_route(identity, raw, category=category,
                                             collection=collection, projection_profile=projection_profile,
                                             allow_acceptance_metadata=_allow_acceptance_metadata)
    trallians_note = _trallians_note_route(identity, raw, category=category,
                                           collection=collection, projection_profile=projection_profile,
                                           allow_acceptance_metadata=_allow_acceptance_metadata)
    farrar_text_space = _farrar_text_space_route(
        identity, raw, language=language, category=category, collection=collection,
        projection_profile=projection_profile, source_base=source_base,
        allow_acceptance_metadata=_allow_acceptance_metadata)
    paired = projection_profile == GREENLEAF_MARKER_PROFILE
    source_lines = projection_profile == native_content.SOURCE_LINES_PROFILE
    carey = projection_profile == CAREY_GROUPED_TABLE_PROFILE
    elmslie = projection_profile == ELMSLIE_CHOICE_PROFILE
    holy_images = projection_profile == HOLY_IMAGES_PROFILE
    peter_jones = projection_profile == PETER_JONES_PROFILE
    hodge = projection_profile == HODGE_PROFILE
    american_missionary = _american_missionary_profile(
        identity, raw, language=language, category=category, collection=collection,
        projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata)
    guyon = projection_profile == GUYON_PROFILE
    moody = projection_profile == MOODY_PROFILE
    coppens = projection_profile == COPPENS_PROFILE
    cassiodorus = projection_profile == CASSIODORUS_PROFILE
    fox = fox_exact
    woolman = woolman_exact
    if guyon:
        if (not _allow_acceptance_metadata or category != 'prose' or collection
                or identity != guyon_source_profile.IDENTITY or language != 'en'
                or source_base is not None or public_disposition is not None
                or group_profile is not None or not isinstance(guyon_binding, dict)
                or guyon_binding.get('master_sha256') != _sha(raw)
                or guyon_binding.get('source_manifest_sha256') != guyon_source_profile.SOURCE_MANIFEST_SHA
                or guyon_binding.get('source_text_sha256') != guyon_source_profile.SOURCE_TEXT_SHA):
            raise PipelineError('Guyon native route requires its validated accepted context')
        guyon_source_profile.check_text_et(root)
        guyon_source_profile.check_header_et(root, accepted=True)
    elif guyon_binding is not None:
        raise PipelineError('Guyon accepted binding cannot apply to another profile')
    if moody:
        _moody_profile_shape_et(root, raw, identity, language, category, collection)
    if coppens:
        coppens_source.check_et(root, raw, identity, language, category, collection)
    if cassiodorus:
        try:cass_source.check_document_et(root, raw, identity, language, category, collection)
        except ValueError as exc:raise PipelineError(str(exc)) from exc
    if projection_profile is not None and (not (paired or carey or elmslie or holy_images or peter_jones or hodge or american_missionary or guyon or moody or coppens or cassiodorus or fox or woolman or source_lines or pta_vita_sic or pta_hesychius_sic) or (category != 'prose' and not (source_lines and category == 'prayers')) or collection or not _allow_acceptance_metadata):
        raise PipelineError('unsupported native prose projection profile')
    if hodge and (identity != _HODGE_IDENTITY or language != 'en'
                  or root.tag != NS+'TEI' or root.get(XML+'id') != 'hodge-systematic-theology-vol-1-candidate'):
        raise PipelineError('Hodge native accepted identity or envelope differs')
    if peter_jones and (identity != _PETER_JONES_IDENTITY or language != 'en'
                        or _sha(raw) != _PETER_JONES_MASTER_SHA
                        or root.get(XML+'id') != 'peter-jones-1860-wikisource-edited-selection'):
        raise PipelineError('Peter Jones accepted master or identity differs')
    whole_sermon = category == 'sermons' and not collection and not mtp
    corpus = root.tag == NS+'teiCorpus'
    if corpus and (category in ('sermons', 'commentary') or len(root) < 2 or root[0].tag != NS+'teiHeader'):
        raise PipelineError('native corpus requires an edition header and at least one prose document')
    documents = list(root)[1:] if corpus else [root]
    wilberforce_group = identity['work_id'] == 'wilberforce-practical-view'
    if carey and (corpus or language != 'en'
                  or identity != {'work_id': 'carey-enquiry', 'textual_form_id': 'carey-enquiry-retained-text',
                                  'edition_id': 'carey-enquiry-pg11449-electronic-witness'}
                  or root.get(XML+'id') != 'gutenberg-carey-enquiry'):
        raise PipelineError('Carey grouped source identity differs')
    if elmslie and (corpus or language != 'en'
                    or identity != {'work_id': 'elmslie-books-of-chronicles',
                                    'textual_form_id': 'elmslie-books-of-chronicles-gutenberg-retained',
                                    'edition_id': 'elmslie-books-of-chronicles-gutenberg-electronic'}
                    or root.get(XML+'id') != 'gutenberg-elmslie-books-of-chronicles'):
        raise PipelineError('Elmslie abbreviation source identity differs')
    if holy_images and (corpus or language != 'en' or identity != {
            'work_id': 'pg49917-holy-images', 'textual_form_id': 'pg49917-holy-images-english',
            'edition_id': 'pg49917-holy-images-pg49917-edition'}
            or root.get(XML+'id') != 'pg49917-holy-images-tei'):
        raise PipelineError('Holy Images source identity differs')
    if wilberforce_group and (corpus or category != 'prose' or collection or projection_profile is not None
                             or language != 'en' or root.get(XML+'id') != 'gutenberg-wilberforce-practical-view'):
        raise PipelineError('Wilberforce grouped source envelope differs')
    text_root = root.find(NS+'text')
    if paired:
        if corpus or root.get(XML+'lang') != language:
            raise PipelineError('Greenleaf source language or document envelope differs')
        _greenleaf_characters_et(root)
    elif (root.find(NS+'teiHeader/'+NS+'encodingDesc/'+NS+'charDecl') is not None
          or text_root is not None and any(
              node.tag == NS+'divGen' or node.tag == NS+'index' and node.get('indexName') in ('toc', 'pdf')
              or node.tag == NS+'g' and node.get('ref') == '#U0x2014' for node in text_root.iter())):
        raise PipelineError('source-declared Greenleaf features require their projection profile')
    document_attributes = {XML+'id', 'version', XML+'lang'}
    envelopes = [(root, document_attributes)]
    member_texts = []
    for document in documents:
        if document.tag != NS+'TEI' or [e.tag for e in document] != [NS+'teiHeader', NS+'text'] + ([NS+'standOff'] if source_projection_nodes else []):
            raise PipelineError('native document requires one header and text')
        text = document[1]
        if group_profile is not None or john or strong_group:
            outer = text
            group = outer[0]
            source_texts = list(group)
            envelopes.extend([(outer, {XML+'lang'}), (group, {XML+'id'})])
        elif whitefield:
            outer=text;group=outer[0];source_texts=list(group)
            envelopes.extend([(outer,set()),(group,set())])
        elif wilberforce_group or carey:
            outer = text
            inner_id = 'carey-enquiry' if carey else 'wilberforce-practical-view'
            if (outer.attrib != {XML+'lang': 'en'} or len(outer) != 1
                    or outer[0].tag != NS+'group' or outer[0].attrib or len(outer[0]) != 1
                    or outer[0][0].tag != NS+'text'
                    or outer[0][0].attrib != {XML+'id': inner_id}):
                raise PipelineError('grouped source envelope differs')
            source_texts = [outer[0][0]]
            envelopes.extend([(outer, {XML+'lang'}), (outer[0], set())])
        else:
            source_texts = [text]
        envelopes.append((document, document_attributes))
        document_language = document.get(XML+'lang')
        if document_language and not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', document_language):
            raise PipelineError('invalid native document language')
        for member_number, text in enumerate(source_texts):
            member_texts.append(text)
            if farrar_text_space and text.get(XML+'space') != 'preserve':
                raise PipelineError('Farrar retained text whitespace declaration differs')
            parts = [e.tag.removeprefix(NS) for e in text]
            if parts not in (['front', 'body'], ['body'], ['body', 'back'], ['front', 'body', 'back']):
                raise PipelineError('native text parts are missing, duplicated, or out of order')
            text_allowed = ({XML+'id', XML+'lang', XML+'base', 'ana', 'n'} if whitefield else {XML+'id', XML+'lang'}) | ({XML+'space'} if farrar_text_space else set()) | ({'ana'} if john else set()) | ({'n'} if strong_group else set())
            if group_profile is not None and group_profile['members'][member_number]['declared_member_base']:
                text_allowed.add(XML+'base')
            _allow_preserved_text_space(text, text_allowed, error_type=PipelineError)
            envelopes.append((text, text_allowed))
            envelopes.extend((part, {XML+'id', XML+'lang'} | ({'rend'} if paired and part.tag == NS+'back' else set())) for part in text)
            if text.get(XML+'lang') and not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', text.get(XML+'lang')):
                raise PipelineError('invalid native document language')
            if corpus and text.get(XML+'lang') and text.get(XML+'lang') != language:
                raise PipelineError('native member language differs from edition language')
    text = member_texts[0]
    front = text.find(NS+'front')
    body = text.find(NS+'body')
    if whole_sermon and (parts != ['front', 'body'] or not len(body) or any(e.tag != NS+'div' or e.get('type') != 'sermon' for e in body)):
        raise PipelineError('native sermon profile requires front and complete sermon divisions')
    if mark:
        _mark_body_et(body)
    elif mtp:
        _mtp_body_et(body)
    elif collection or category == 'commentary':
        if not len(body) or any(e.tag != NS+'div' or e.get('type') != ('thml-div1' if wesley else 'source-div1') for e in body):
            raise PipelineError('native collection requires source-defined body divisions')
    for node, allowed in envelopes:
        if node.get('version') is not None and not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,2}', node.get('version')):
            raise PipelineError('invalid native TEI version')
        if set(node.attrib) - allowed or (node.text or '').strip() or any((child.tail or '').strip() for child in node):
            raise PipelineError('unsupported native sermon envelope content or attributes')
    if text.get(XML+'lang') and not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', text.get(XML+'lang')):
        raise PipelineError('invalid native document language')
    if paired and (text.get(XML+'lang') != language or text.find(NS+'back') is None
                   or text.find(NS+'back').get('rend') != 'page-break-before: right'):
        raise PipelineError('Greenleaf source language or back-matter rendition differs')
    elements, attributes = _header_rules(_allow_acceptance_metadata)
    if wesley:elements, attributes = _wesley_header_rules(elements, attributes)
    if strong_group:elements, attributes = strong_complete.header_rules(elements, attributes)
    if thome_exact:
        elements = dict(elements)
        elements['sourceDesc'] = list(set(elements.get('sourceDesc', [])) | {'p'})
        elements['p'] = list(set(elements.get('p', [])) | {'bibl'})
    if l599:elements, attributes = l599_source.header_rules(elements, attributes)
    if samuel:
        elements, attributes = _samuel_header_rules(elements, attributes)
    guyon_header_nodes = guyon_source_profile.source_header_nodes_et(root) if guyon else set()
    selected = []
    evidence_nodes = set(source_projection_nodes)
    private_nodes = set()
    if holy_images:
        markers = [node for node in root.iter(NS+'milestone') if node.get('unit') == 'source-html-comment']
        if len(markers) != 5:
            raise PipelineError('Holy Images source-comment count differs')
        private_nodes.update(markers)
    if paired:
        selected, private_nodes = _greenleaf_units_et(root)
    elif whole_sermon:
        selected = [(1, 'body', sibling, unit, '', ()) for sibling, unit in enumerate(body, 1)]
    else:
        for volume, text_member in enumerate(member_texts, 1):
            for part in text_member:
                for sibling, source_unit in enumerate(part, 1):
                    if _ryle_private_ledger_et(source_unit, identity=identity, part=part.tag[len(NS):]):
                        private_nodes.update(source_unit.iter())
                        continue
                    if source_lines:
                        source_unit, excluded = _source_lines_public_shadow(source_unit)
                        private_nodes.update(excluded)
                    pair = _readable_source_member(root, source_unit, corpus=corpus) if category == 'prose' else None
                    if pair is None:
                        selected.append((volume, part.tag[len(NS):], sibling, source_unit, '', ()))
                    else:
                        readable, evidence = pair
                        selected.append((volume, part.tag[len(NS):], sibling, readable, '/div[1]', ()))
                        evidence_nodes.update(evidence.iter())
    if identity['work_id'] == 'ryle-holiness' and not private_nodes:
        raise PipelineError('Ryle private source ledger is missing')
    if not selected:
        raise PipelineError('empty native document')
    inventory = []
    exclusions = []
    ids = set()

    def account(node, header=False, parent=None):
        header = header or node.tag == NS+'teiHeader'
        if not isinstance(node.tag, str) or not node.tag.startswith(NS):
            raise PipelineError('unsupported native sermon namespace')
        tag = node.tag[len(NS):]
        if header and not whitefield and not gaines_exact and node not in source_projection_nodes and node not in guyon_header_nodes:
            stokes_bibl_p = (_allow_acceptance_metadata and category == 'commentary'
                            and identity['work_id'] == 'expositors-bible--g-t-stokes'
                            and tag == 'p' and parent is not None and parent.tag == NS+'sourceDesc'
                            and not node.attrib and [child.tag for child in node] == [NS+'bibl'])
            accepted_binding_p = node is binding_wrapper
            if tag == 'p' and any(child.tag == NS+'bibl' for child in node) and not (stokes_bibl_p or accepted_binding_p or thome_exact):
                raise PipelineError(f'unsupported native sermon header element: {tag} in {parent.tag if parent is not None else "root"}')
            group_bibl_list = group_profile is not None and tag == 'listBibl'
            group_bibl_head = group_profile is not None and tag == 'head' and parent is not None and parent.tag == NS+'listBibl'
            allowed_children = (set(elements.get(tag, []))
                                | ({'bibl'} if stokes_bibl_p or accepted_binding_p else set())
                                | ({'listBibl'} if group_profile is not None and tag == 'sourceDesc' else set())
                                | ({'listBibl', 'head', 'bibl', 'biblFull'} if group_bibl_list else set()))
            if tag not in elements and not (group_bibl_list or group_bibl_head) or any(child.tag != NS+child.tag.removeprefix(NS) or child.tag.removeprefix(NS) not in allowed_children for child in node):
                raise PipelineError(f'unsupported native sermon header element: {tag} in {parent.tag if parent is not None else "root"}')
            allowed = set(attributes.get(tag, [])) | {'xml:id'}
            if any(('xml:'+key[len(XML):] if key.startswith(XML) else key) not in allowed for key in node.attrib):
                raise PipelineError('unsupported native sermon header attribute')
            if tag == 'revisionDesc' and node.get('status') not in (None, 'candidate', 'draft', 'approved'):
                raise PipelineError('unsupported native revision status')
            if tag == 'rendition' and (node.get('scheme') != 'css' or (node.get('selector') is not None and not node.get('selector').strip()) or not (node.text or '').strip()):
                raise PipelineError('unsupported native CSS rendition')
        identifier = node.get(XML+'id')
        if identifier:
            if identifier in ids:
                raise PipelineError('duplicate native source identifier')
            ids.add(identifier)
        ordinal = len(inventory)+1
        role = ('machine-source-evidence' if node in evidence_nodes else 'bibliographic-header' if header
                else 'source-generator-only' if node in private_nodes else 'native-content-or-envelope')
        inventory.append({'ordinal': ordinal, 'tag': tag, 'attributes': dict(node.attrib),
                          'text_sha256': _sha((node.text or '').encode()),
                          'tail_sha256': _sha((node.tail or '').encode()), 'role': role})
        if header or node in evidence_nodes or node in private_nodes:
            exclusions.append({'ordinal': ordinal, 'reason': role})
        for child in node:
            account(child, header, node)
    account(root)
    front_content = native_content.project_content(front) if whole_sermon else None
    front_text = native_content.readable_content(front_content) if front_content is not None else None
    book_codes = load_book_codes() if whole_sermon or category == 'prose' else None
    rows = []
    anchors = []
    for index, (volume, part_name, sibling, unit, nested_path, leading) in enumerate(selected, 1):
        heads = unit.findall(NS+'head')
        labels = unit.findall(NS+'epigraph/'+NS+'bibl')
        if whole_sermon and (len(heads) != 1 or len(labels) != 1):
            raise PipelineError('native sermon requires one heading and primary bibliographic label')
        member_profile = group_profile['members'][volume-1] if group_profile is not None else None
        effective_base = member_profile['base'] if member_profile is not None else source_base
        content = native_content.project_content(_gaines_readable_shadow(unit) if gaines_exact else unit, source_profile=strong_complete.member_content_profile(volume) if strong_group else THOME_PROFILE if thome_exact else native_content.PTA_ANONYMOUS_VITA_PROFILE if pta_vita_sic else native_content.PTA_HESYCHIUS_PROFILE if pta_hesychius_sic else strong_source.PROFILE if strong else whitefield_source.PROFILE if whitefield else SAMUEL_PROFILE if samuel else MTP_PROFILE if mtp else WESLEY_PROFILE if wesley else MARK_PROFILE if mark else FOX_PROFILE if fox else native_content.BENNETT_CHRONICLES_PROFILE if bennett_chronicles else projection_profile if carey or elmslie or holy_images or peter_jones or hodge or american_missionary or guyon or moody or coppens or cassiodorus or fox or woolman or source_lines else None,
                                                 source_base=effective_base)
        if member_profile is not None:
            commentary_group_policy.inherit_base_et(unit, content, member_profile)
        readable = native_content.readable_content(content)
        if virgin_mary_note and part_name == 'back':
            readable = _virgin_mary_note_text_et(unit)
        if magnesians_note and part_name == 'back':
            readable = _numbered_note_text_et(unit, first_number=890, count=96,
                                               first_paragraph=2296, work_label='Magnesians')
        if trallians_note and part_name == 'back':
            readable = _numbered_note_text_et(unit, first_number=986, count=91,
                                               first_paragraph=2392, work_label='Trallians')
        if paired and not readable:
            raise PipelineError('Greenleaf source division has no readable text')
        structure = [native_content.project_content(marker) for marker in leading] + [content]
        if leading:
            structure[1]['attributes']['source_anchor'] = leading[1].get(XML+'id')
        heading = native_content.readable_content(native_content.project_content(heads[0])) if whole_sermon else None
        primary = native_content.readable_content(native_content.project_content(labels[0])) if whole_sermon else None
        text_path = (f'/TEI/text/group/text[{volume}]' if whitefield or group_profile is not None or john or strong_group else
                     '/TEI/text/group/text' if wilberforce_group or carey else '/TEI/text')
        unit_path = f'{text_path}/{part_name}/div[{sibling}]' if whole_sermon else f'{text_path}/{part_name}/*[{sibling}]'
        if corpus:
            unit_path = f'/teiCorpus/TEI[{volume}]' + unit_path[len('/TEI'):]
        unit_path += nested_path
        record_id = identity['edition_id']+(':'+('sermon' if whole_sermon else 'native')+':')+_sha(unit_path.encode())[:20]
        rows.append({**identity, 'record_id': record_id, 'sequence': index, 'category': 'sermons',
                     'language': language, 'representation_revision': representation_revision,
                     'provenance': {'edition_title': edition_title, **_entry_attribution(unit)}, 'content_format': FORMAT,
                     'locator': {'kind': 'sermon', 'number': unit.get('n'), 'headings': [heading]},
                     'primary_passage': primary, 'collection': None,
                     'delivery': dict.fromkeys(('statement', 'date', 'place', 'occasion')),
                     'structure': structure, 'text': readable,
                     'front_matter': [{'structure': front_content, 'text': front_text}] if index == 1 else []})
        if whole_sermon:
            rows[-1]['primary_reference'] = {'raw': primary, 'references': [normalize_reference_record({'raw': native_content.readable_content(native_content.project_content(ref)), **{k: ref.get(k) for k in ('cRef', 'target') if ref.get(k) is not None}}, book_codes=book_codes) for ref in labels[0].iter(NS+'ref')]}
        if category == 'prose':
            rows[-1]['source_references'] = _prose_references(unit, book_codes, THOME_PROFILE if thome_exact else FOX_PROFILE if fox else whitefield_source.PROFILE if whitefield else None)
        if not whole_sermon:
            row = rows[-1]
            for key in ('primary_passage', 'collection', 'delivery', 'front_matter'):
                row.pop(key)
            row['category'] = category
            row['locator'] = {'kind': 'native-unit', 'text_part': part_name, 'unit': sibling}
            if corpus or whitefield or group_profile is not None or john or strong_group:
                row['locator']['document'] = volume
        anchors.append({'unit_id': unit_path, 'record_id': record_id, 'text_sha256': _sha(readable.encode())})
    if public_disposition is not None:
        rows = native_public_dispositions.project_rows(rows, raw, public_disposition)
    if john:
        rows = tyerman_john_group_profile.project_rows(rows, root)
    _validate_rows(rows, category)
    receipt = {'scope': SCOPE, 'mapping_version': strong_complete.VERSION if strong_group else THOME_PROFILE if thome_exact else native_content.PTA_ANONYMOUS_VITA_PROFILE if pta_vita_sic else native_content.PTA_HESYCHIUS_PROFILE if pta_hesychius_sic else strong_source.PROFILE if strong else whitefield_source.PROFILE if whitefield else tyerman_john_group_profile.VERSION if john else SAMUEL_PROFILE if samuel else MTP_PROFILE if mtp else commentary_group_policy.version(group_profile) if group_profile is not None else FARRAR_TEXT_SPACE_PROFILE if farrar_text_space else native_public_dispositions.mapping_version(public_disposition) if public_disposition else MARK_PROFILE if mark else TRALLIANS_NOTE_PROFILE if trallians_note else MAGNESIANS_NOTE_PROFILE if magnesians_note else VIRGIN_MARY_NOTE_PROFILE if virgin_mary_note else FOX_PROFILE if fox else native_content.BENNETT_CHRONICLES_PROFILE if bennett_chronicles else projection_profile if carey or paired or elmslie or peter_jones or hodge or american_missionary or guyon or moody or coppens or cassiodorus or fox or woolman or source_lines else VERSION if whole_sermon else ('ocd-prose-native-v3' if category == 'prose' else f'ocd-{category}-native-v2'), 'master_sha256': _sha(raw),
               **_schema_bindings(category), **({'book_codes_sha256': _sha(BOOK_CODES_PATH.read_bytes())} if whole_sermon or category == 'prose' else {}), 'output_sha256': _sha(_json(rows)), 'row_count': len(rows),
               'anchors': anchors, 'inventory': inventory, 'exclusions': exclusions,
               **({'source_comments': comments} if comments else {}),
                **({'source_processing_instructions': processing_instructions} if processing_instructions else {}),
               **({'projection_profile': native_content.PTA_ANONYMOUS_VITA_PROFILE} if pta_vita_sic else {'projection_profile': native_content.PTA_HESYCHIUS_PROFILE} if pta_hesychius_sic else {'projection_profile': projection_profile} if carey or paired or elmslie or peter_jones or hodge or american_missionary or guyon or moody or coppens or cassiodorus or fox or woolman or source_lines else {}),
               **({'guyon_source_binding': {**guyon_binding,
                    'source_header_sha256': guyon_source_profile.SOURCE_PARAGRAPHS_SHA}}
                  if guyon else {}),
               'warnings': ['Bennett Chronicles retains a source column-group span marker in the private content structure; no print collation or inferred Bible target is claimed.'] if bennett_chronicles else list(strong_complete.WARNINGS) if strong_group else ['Strong Volume II is a retained middle-volume witness of one authored three-volume work. Literal source line IDs, numbers, whitespace declarations and heading continuation attachments are conserved; no print collation or complete three-volume reconstruction is claimed.'] if strong else ['John Wesley source has three retained volumes. Seven JPEG data URIs and archive member digests stay in private TEI; public rows carry stable image references, not image bytes. Abbreviation display chooses the source abbr branch while preserving both alternatives in structure.'] if john else ['Guyon source head metadata stays in private inventory. Cell numbers are literal DOM locators, not table columns; the retained cover is not a fetched public image.'] if guyon else ['Cassiodorus table cell @n values are literal source DOM locators, not semantic column numbers; @cols preserves source colspan. Table-boundary markers retain the source CRLF tail as base64 DQo=.'] if cassiodorus else ['MTP source units lack a uniform primary passage; no Bible target is inferred. The 27 archive images remain literal references, not fetched image assets.'] if mtp else ['The Farrar text wrapper declares xml:space="preserve"; its source attribute remains in the private inventory.'] if farrar_text_space else ['The 91 source endnotes form a separate readable back-matter row; page markers remain in structure.'] if trallians_note else ['The 96 source endnotes form a separate readable back-matter row; page markers remain in structure.'] if magnesians_note else ['The source endnote is a separate readable back-matter row; page markers remain in structure.'] if virgin_mary_note else ['Notes and page markers remain in structure; readable text omits them.'],
               'unsupported': [], 'independent_check': {'status': 'pending'}}
    return {'rows': rows, 'receipt': receipt}


def _observe_readable_source_member(doc, unit, *, corpus):
    """Checker-side structural and byte observations for a retained source member."""
    if unit.tag != NS+'div' or unit.get('type') != 'retained-source-member':
        return None
    if not corpus or dict(unit.attrib) != {'type': 'retained-source-member'} or len(unit) != 2 or (unit.text or '').strip() or any((child.tail or '').strip() for child in unit):
        raise ValueError('retained source member differs')
    readable, evidence = unit
    if readable.tag != NS+'div' or readable.get('type') != 'readable-transcription' or evidence.tag != NS+'div' or dict(evidence.attrib) != {'type': 'exact-source-evidence'} or len(evidence) != 2:
        raise ValueError('readable/source-evidence pair differs')
    encoded, ledger = evidence
    if encoded.tag != NS+'ab' or dict(encoded.attrib).keys() != {'type', 'subtype', 'n'} or encoded.get('type') != 'exact-retained-source-bytes' or encoded.get('subtype') != 'base64' or len(encoded):
        raise ValueError('retained source bytes carrier differs')
    if ledger.tag != NS+'div' or dict(ledger.attrib) != {'type': 'complete-xml-node-transcription'} or not len(ledger):
        raise ValueError('complete source-node transcription differs')
    if any((node.tail or '').strip() for node in evidence.iter()) or (evidence.text or '').strip() or (ledger.text or '').strip():
        raise ValueError('source-evidence whitespace differs')
    source_hashes = [(node.text or '').strip() for node in doc[0].iter(NS+'idno') if node.get('type') in ('source_sha256', 'sha256')]
    if len(source_hashes) != 2 or len(set(source_hashes)) != 1 or not re.fullmatch(r'[0-9a-f]{64}', source_hashes[0]):
        raise ValueError('source hash evidence differs')
    try:
        source_bytes = base64.b64decode(encoded.text or '', validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('retained source base64 differs') from exc
    if hashlib.sha256(source_bytes).hexdigest() != source_hashes[0] or encoded.get('n') != source_hashes[0]:
        raise ValueError('retained source bytes/hash differ')
    expected_keys = {'attributes', 'feature_id', 'kind', 'namespace_declarations', 'ordinal',
                     'parent_ordinal', 'payload_sha256', 'pi_target', 'qname', 'scope',
                     'sibling_ordinal', 'tail', 'text'}
    for number, node in enumerate(ledger, 1):
        if node.tag != NS+'ab' or set(node.attrib) != {XML+'id', 'type', 'subtype', 'n'} or node.get('type') != 'source-xml-node' or node.get('n') != str(number) or not node.text or len(node):
            raise ValueError('source XML node carrier differs')
        try:
            item = json.loads(node.text)
        except json.JSONDecodeError as exc:
            raise ValueError('source XML node JSON differs') from exc
        if not isinstance(item, dict) or set(item) != expected_keys or item.get('ordinal') != number or item.get('feature_id') != node.get(XML+'id') or item.get('kind') != node.get('subtype') or item.get('kind') not in ('element', 'comment'):
            raise ValueError('source XML node identity differs')
    return readable, evidence


def _ryle_private_ledger_et(unit, *, identity, part):
    """Keep the exact source-accountability carrier in private inventory."""
    if identity['work_id'] != 'ryle-holiness':
        return False
    marker = unit.get(XML+'id') == 'ryle-holiness-source-ledger' or unit.get('type') == 'source-accountability'
    if not marker:
        return False
    if (identity['work_id'] != 'ryle-holiness' or part != 'back' or unit.tag != NS+'div'
            or unit.attrib != {XML+'id': 'ryle-holiness-source-ledger', 'type': 'source-accountability'}
            or len(unit) != 5699 or unit[0].tag != NS+'head'
            or unit[0].attrib or unit[0].text != 'Complete retained source element ledger'
            or len(unit[0])):
        raise PipelineError('Ryle private source ledger envelope differs')
    for ordinal, carrier in enumerate(list(unit)[1:], 1):
        if (carrier.tag != NS+'ab' or carrier.get(XML+'id') != f'ryle-holiness-source-feature-{ordinal:05d}'
                or carrier.get('type') != 'source-element' or not carrier.get('subtype')
                or not carrier.get('n') or not (carrier.get('corresp') or '').startswith('urn:source-xpath:')
                or set(carrier.attrib) != {XML+'id', 'type', 'subtype', 'n', 'corresp'}
                or [child.tag for child in carrier] != [NS+'seg'] * 3
                or [child.get('type') for child in carrier] != ['direct-text', 'tail-text', 'source-attributes']):
            raise PipelineError(f'Ryle private source ledger carrier differs at {ordinal}')
    return True


def _ryle_private_ledger_lxml(unit, *, identity, part):
    """Independently observe the Ryle ledger's exact private carrier shape."""
    if identity['work_id'] != 'ryle-holiness':
        return False
    candidate = unit.get(XML+'id') == 'ryle-holiness-source-ledger' or unit.get('type') == 'source-accountability'
    if not candidate:
        return False
    if (identity['work_id'] != 'ryle-holiness' or part != 'back' or unit.tag != NS+'div'
            or dict(unit.attrib) != {XML+'id': 'ryle-holiness-source-ledger', 'type': 'source-accountability'}
            or len(unit) != 5699 or unit[0].tag != NS+'head'
            or dict(unit[0].attrib) or unit[0].text != 'Complete retained source element ledger'
            or len(unit[0])):
        raise ValueError('Ryle private source ledger envelope differs')
    for number, node in enumerate(unit[1:], 1):
        if (node.tag != NS+'ab' or dict(node.attrib).keys() != {XML+'id', 'type', 'subtype', 'n', 'corresp'}
                or node.get(XML+'id') != f'ryle-holiness-source-feature-{number:05d}'
                or node.get('type') != 'source-element' or not node.get('subtype') or not node.get('n')
                or not (node.get('corresp') or '').startswith('urn:source-xpath:')
                or [child.tag for child in node] != [NS+'seg', NS+'seg', NS+'seg']
                or [child.get('type') for child in node] != ['direct-text', 'tail-text', 'source-attributes']):
            raise ValueError(f'Ryle private source ledger carrier differs at {number}')
    return True


def _greenleaf_units_lxml(document):
    text = document.find(NS+'text')
    if text is None or [part.tag for part in text] != [NS+'front', NS+'body', NS+'back']:
        raise ValueError('Greenleaf marker profile text parts differ')
    selected = []
    private_nodes = set()
    for part in text:
        name = etree.QName(part).localname
        if name == 'body':
            if len(part) == 0 or len(part) % 3:
                raise ValueError('Greenleaf page-marker triple count differs')
            for offset in range(0, len(part), 3):
                page, anchor, division = part[offset:offset+3]
                label = page.get('n')
                if ([node.tag for node in (page, anchor, division)] != [NS+'pb', NS+'anchor', NS+'div']
                        or not label or anchor.get(XML+'id') != 'Pg'+label
                        or any((node.text or '').strip() or len(node) for node in (page, anchor))):
                    raise ValueError('Greenleaf page-marker order or attachment differs')
                selected.append((1, name, offset+3, division, '', (page, anchor)))
        else:
            for sibling, unit in enumerate(part, 1):
                if unit.tag != NS+'div':
                    raise ValueError('Greenleaf front/back division differs')
                generator = unit[0] if len(unit) == 1 and unit[0].tag == NS+'divGen' else None
                if generator is not None and not (unit.text or '').strip() and not (generator.tail or '').strip():
                    allowed = {'pgheader', 'encodingDesc'} if name == 'front' else {'pgfooter'}
                    if generator.get('type') not in allowed or len(generator) or (generator.text or '').strip():
                        raise ValueError('Greenleaf private generator division differs')
                    private_nodes.update(unit.iter())
                else:
                    selected.append((1, name, sibling, unit, '', ()))
    if not selected or not private_nodes:
        raise ValueError('Greenleaf source units differ')
    return selected, private_nodes


def verify_document(path, rows, receipt, *, identity, language, representation_revision,
                    edition_title, _allow_acceptance_metadata=False, category="sermons", collection=False,
                    projection_profile=None, source_base=None, public_disposition=None,
                    group_profile=None, guyon_binding=None, acquisition_id=None):
    """Rebuild unit selection, public rows and accounting from independent XML observations."""
    try:
        if source_base is not None and (category != 'commentary' or not _allow_acceptance_metadata
                                        or not _expositor_base_identity(identity, source_base)):
            raise ValueError('native source reference base requires accepted Expositor commentary')
        raw = io_path(Path(path)).read_bytes()
        thome_exact = (_allow_acceptance_metadata and category == 'prose' and identity == {'work_id':'james-a-thome-prayer-oppressed','textual_form_id':'james-a-thome-prayer-oppressed-1859','edition_id':'james-a-thome-prayer-oppressed-pg70704'} and language == 'en' and not collection and projection_profile is None and hashlib.sha256(raw).hexdigest() == '8a79d0d778d87e501c4109632c50461289afa3aa13f4240ec90330bb8d6dc6d5')
        bennett_chronicles = _bennett_chronicles_route(
            identity, raw, language=language, category=category, collection=collection,
            projection_profile=projection_profile, source_base=source_base,
            acquisition_id=acquisition_id, allow_acceptance_metadata=_allow_acceptance_metadata)
        gaines_exact = (_allow_acceptance_metadata and category == 'prose' and identity == {'work_id':'gaines-african-methodism-south-1890','textual_form_id':'gaines-docsouth-retained','edition_id':'gaines-docsouth-electronic'} and language == 'en' and not collection and projection_profile is None and source_base is None and acquisition_id == 'gaines-docsouth-acquired' and hashlib.sha256(raw).hexdigest() == '17342bef749798012bf0bcd581be474a8127fd7e8cb3680a87f86139130bb280')
        if identity.get('work_id') == 'gaines-african-methodism-south-1890' and not gaines_exact:
            raise ValueError('Gaines retained header route requires its exact accepted master and identity')
        pta_vita_sic = _pta_anonymous_vita_sic_route(
            identity, hashlib.sha256(raw).hexdigest(), language=language,
            category=category, collection=collection,
            projection_profile=projection_profile,
            allow_acceptance_metadata=_allow_acceptance_metadata,
            acquisition_id=acquisition_id)
        pta_hesychius_sic = _pta_hesychius_empty_sic_route(
            identity, hashlib.sha256(raw).hexdigest(), language=language,
            category=category, collection=collection,
            projection_profile=projection_profile,
            allow_acceptance_metadata=_allow_acceptance_metadata,
            acquisition_id=acquisition_id)
        if identity.get('work_id') == 'james-a-thome-prayer-oppressed' and not thome_exact:
            raise ValueError('Thome retained reader requires its exact master, identity, language and category')
        fox_exact = fox_source.route(raw, identity=identity, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata)
        woolman_exact = woolman_source.route(raw, identity=identity, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata)
        if group_profile is not None:
            if (not _allow_acceptance_metadata or category != 'commentary' or collection
                    or projection_profile is not None or source_base is not None
                    or identity != {key: group_profile['identity'][key]
                                    for key in ('work_id', 'textual_form_id', 'edition_id')}
                    or hashlib.sha256(raw).hexdigest() != group_profile['master_sha256']):
                raise ValueError('observed accepted complete-group profile differs')
            commentary_group_policy.source_census_lxml(raw, group_profile)
        if public_disposition is not None and (public_disposition != identity.get('work_id')
                                               or category != ('sermons' if public_disposition == native_public_dispositions.NEWMAN_WORK else 'poetry' if public_disposition == native_public_dispositions.COX_WORK else 'prose') or collection != (public_disposition == native_public_dispositions.NEWMAN_WORK)
                                               or projection_profile is not None or not _allow_acceptance_metadata):
            raise ValueError('observed public disposition requires accepted identity/category')
        source = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        tree = source.getroottree()
        if tree.docinfo.doctype:
            raise ValueError('unsupported native sermon declarations')
        observed = {}
        source_comments = tree.xpath('//comment()')
        source_processing_instructions = tree.xpath('//processing-instruction()')
        observed_pta_comment_count = ({
            'amphilochius-epistula-synodalis': 2,
            'anonymous-vita-sancti-cononis-bidanae': 38,
            'hesychius-commentarius-magnus-in-psalmos': 67,
            'severian-de-fide-et-lege-naturae': 6,
        }.get(identity.get('work_id')) if _allow_acceptance_metadata else None)
        declared_evidence = source.find(NS+'standOff') is not None
        prolog = list(source.itersiblings(preceding=True)); prolog.reverse()
        processing_instructions = []
        for instruction in source_processing_instructions:
            match = re.fullmatch(
                r'\s*href="([^"]+)"\s+schematypens="([^"]+)"\s*',
                instruction.text or '',
            )
            if (
                instruction.getparent() is not None
                or instruction not in prolog
                or instruction.target != 'xml-model'
                or match is None
                or match.group(1) not in _XML_MODEL_SCHEMAS
                or match.group(2) != 'http://relaxng.org/ns/structure/1.0'
            ):
                raise ValueError('native source processing instruction differs')
            processing_instructions.append({
                'parent_path': '#document', 'child_index': prolog.index(instruction),
                'target': instruction.target, 'text': instruction.text or '',
                'tail': instruction.tail or '', 'disposition': 'private-xml-model-hint',
            })
        if observed_pta_comment_count is not None and (
            len(source_comments) != observed_pta_comment_count
            or len(processing_instructions) != 1
            or processing_instructions[0]['text'] != (
                'href="https://raw.githubusercontent.com/PatristicTextArchive/Schema/master/tei-pta.rng" '
                'schematypens="http://relaxng.org/ns/structure/1.0"'
            )
        ):
            raise ValueError('observed PTA source comment profile differs')
        for marker in source_comments:
            if marker.getparent() is not None:
                continue
            if declared_evidence and marker in prolog and not (marker.tail or '').strip():
                observed[marker] = {'parent_path': '#document', 'child_index': prolog.index(marker), 'text': marker.text or '', 'tail': marker.tail or '', 'disposition': 'source-prolog-comment-evidence'}
                continue
            if marker.text != ' Copyright Christian Classics Ethereal Library ' or marker.getprevious() is not None or marker.getnext() is not source or (marker.tail or '').strip():
                raise ValueError('native prolog comment differs')
            observed[marker] = {'parent_path': '#document', 'child_index': 0,
                                'text': marker.text, 'tail': marker.tail or '',
                                'disposition': 'source-rights-notice-handoff'}
        for parent in tree.iter():
            markers = [child for child in parent if isinstance(child, etree._Comment)]
            if not markers:
                continue
            if parent.tag == NS+'body':
                if len(markers) != 2 or markers[0].text != ' added reason="AutoIndexing" ' or markers[1].text != ' /added ' or parent.index(markers[1]) <= parent.index(markers[0])+1:
                    raise ValueError('native auto-index wrapper differs')
                groups = [(markers, 'private-auto-index-wrapper')]
            elif parent.tag == NS+'div' and len(markers) % 4 == 0:
                groups = [(markers[offset:offset+4], 'private-auto-index-marker') for offset in range(0, len(markers), 4)]
                for group, _ in groups:
                    label = next((name for name in ('scripRef', 'scripCom', 'foreign')
                                  if group[0].text == f' added reason="insertIndex" class="{name}" '), None)
                    if label is None or [item.text for item in group[1:]] != [
                        f' Start of automatically inserted {label} index ',
                        f' End of {label} index ', ' /added ',
                    ] or parent.index(group[1]) != parent.index(group[0])+1 or parent.index(group[3]) != parent.index(group[2])+1 or parent.index(group[2]) <= parent.index(group[1])+1:
                        raise ValueError('native source comment sequence differs')
            elif parent.tag == NS+'seg' and parent.attrib == {XML+'id': 'npnf105-xiv.iv-p1.2', 'rend': 'MsoEndnoteReference'}:
                if (len(markers) != 2 or len(parent) != 2 or (parent.text or '') != ' '
                        or markers[0].text != ' <a href="#_edn1609" name="_ednref1609" id="xiv.iv-p1.3">  '
                        or markers[0].tail != '[1609]' or markers[1].text != ' </a> '
                        or (markers[1].tail or '') != ''):
                    raise ValueError('native source endnote marker differs')
                groups = [(markers, 'source-endnote-anchor-marker')]
            elif parent.tag == NS+'seg' and parent.attrib == {XML+'id': 'npnf105-xxi.ii-p5.2', 'rend': 'MsoEndnoteReference'}:
                container = parent.getparent()
                if (container is None or container.tag != NS+'p'
                        or dict(container.attrib) != {XML+'id': 'npnf105-xxi.ii-p5', 'rend': 'c39'}
                        or len(container) != 2 or container[1] is not parent
                        or len(markers) != 2 or len(parent) != 2 or (parent.text or '') != ''
                        or [marker.text for marker in markers] != [
                            ' <a href="#_edn3415" name="_ednref3415" id="xxi.ii-p5.3"> ', ' </a> ']
                        or [marker.tail or '' for marker in markers] != [' [3415]', '']):
                    raise ValueError('native source endnote marker differs')
                groups = [(markers, 'source-endnote-anchor-marker')]
            elif observed_pta_comment_count is not None:
                groups = [(markers, 'private-pta-editorial-comment')]
            else:
                raise ValueError('native source comment location differs')
            for group, disposition in groups:
                for marker in group:
                    if disposition not in {'source-endnote-anchor-marker', 'private-pta-editorial-comment'} and (marker.tail or '').strip():
                        raise ValueError('native source comment tail differs')
                    observed[marker] = {'parent_path': tree.getpath(parent),
                                        'child_index': parent.index(marker), 'text': marker.text or '',
                                        'tail': marker.tail or '', 'disposition': disposition}
        if len(observed) != len(source_comments):
            raise ValueError('native source comment count differs')
        comments = [observed[marker] for marker in source_comments]
        doc = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=True))
        if fox_exact:
            fox_source.check_lxml(doc, raw)
        if woolman_exact:
            woolman_source.check_lxml(doc, raw)
        binding_wrapper = None
        if _allow_acceptance_metadata:
            header = doc.find(NS+'teiHeader')
            marked = ([node for node in header.iter(NS+'bibl')
                       if node.get('type') == 'ocd-acceptance-binding'] if header is not None else [])
            if len(marked) > 1:
                raise ValueError('multiple observed native acceptance bindings')
            if marked:
                binding = marked[0]
                parent = binding.getparent()
                source_desc = header.find(NS+'fileDesc/'+NS+'sourceDesc')
                if parent is source_desc:
                    pass
                elif (parent is not None and parent.tag == NS+'p'
                      and parent.getparent() is source_desc and not parent.attrib
                      and len(parent) == 1 and parent[0] is binding
                      and not (parent.text or '').strip()
                      and not (binding.tail or '').strip()
                      and not (parent.tail or '').strip()):
                    binding_wrapper = parent
                else:
                    raise ValueError('observed native acceptance binding location differs')
        source_projection_nodes = observe_evidence(doc)
        if category not in ('sermons', 'prose', 'poetry', 'prayers', 'commentary') or (collection and category != 'sermons'):
            raise ValueError('unknown native category')
        mark = _mark_route(identity, raw, language=language, category=category,
                           collection=collection, projection_profile=projection_profile,
                           allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
        wesley = _wesley_route(identity, raw, language=language, category=category,
                               collection=collection, projection_profile=projection_profile,
                               source_base=source_base, acquisition_id=acquisition_id,
                               allow_acceptance_metadata=_allow_acceptance_metadata)
        mtp = _mtp_route(identity, raw, language=language, category=category,
                         collection=collection, projection_profile=projection_profile,
                         allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
        samuel = _observe_samuel_route(identity, raw, language=language, category=category,
                                       collection=collection, projection_profile=projection_profile,
                                       allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
        john = _observe_john_route(identity, raw, language=language, category=category,
                                   collection=collection, projection_profile=projection_profile,
                                   allow_acceptance_metadata=_allow_acceptance_metadata,
                                   source_base=source_base, group_profile=group_profile)
        if john:
            tyerman_john_group_profile.source_census_lxml(doc)
        if samuel:
            _samuel_source_lxml(doc)
        whitefield = whitefield_source.route(identity, raw, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
        l599 = l599_source.route(identity, raw, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
        if l599:l599_source.check_lxml(doc)
        strong = strong_source.route(identity, raw, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)
        if strong:strong_source.check_lxml(doc)
        if whitefield:whitefield_source.check_lxml(doc)
        strong_group = strong_complete.route(identity, raw, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base, acquisition_id=acquisition_id)
        if strong_group:strong_complete.check_lxml(doc)
        virgin_mary_note = _virgin_mary_note_route(identity, raw, category=category,
                                                   collection=collection, projection_profile=projection_profile)
        magnesians_note = _magnesians_note_route(identity, raw, category=category,
                                                 collection=collection, projection_profile=projection_profile,
                                                 allow_acceptance_metadata=_allow_acceptance_metadata)
        trallians_note = _trallians_note_route(identity, raw, category=category,
                                               collection=collection, projection_profile=projection_profile,
                                               allow_acceptance_metadata=_allow_acceptance_metadata)
        farrar_text_space = _farrar_text_space_route(
            identity, raw, language=language, category=category, collection=collection,
            projection_profile=projection_profile, source_base=source_base,
            allow_acceptance_metadata=_allow_acceptance_metadata)
        paired = projection_profile == GREENLEAF_MARKER_PROFILE
        source_lines = projection_profile == native_content.SOURCE_LINES_PROFILE
        carey = projection_profile == CAREY_GROUPED_TABLE_PROFILE
        elmslie = projection_profile == ELMSLIE_CHOICE_PROFILE
        holy_images = projection_profile == HOLY_IMAGES_PROFILE
        peter_jones = projection_profile == PETER_JONES_PROFILE
        hodge = projection_profile == HODGE_PROFILE
        american_missionary = _american_missionary_profile(
            identity, raw, language=language, category=category, collection=collection,
            projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata)
        guyon = projection_profile == GUYON_PROFILE
        moody = projection_profile == MOODY_PROFILE
        coppens = projection_profile == COPPENS_PROFILE
        cassiodorus = projection_profile == CASSIODORUS_PROFILE
        fox = fox_exact
        woolman = woolman_exact
        if guyon:
            if (not _allow_acceptance_metadata or category != 'prose' or collection
                    or identity != guyon_source_profile.IDENTITY or language != 'en'
                    or source_base is not None or public_disposition is not None
                    or group_profile is not None or not isinstance(guyon_binding, dict)
                    or guyon_binding.get('master_sha256') != hashlib.sha256(raw).hexdigest()
                    or guyon_binding.get('source_manifest_sha256') != guyon_source_profile.SOURCE_MANIFEST_SHA
                    or guyon_binding.get('source_text_sha256') != guyon_source_profile.SOURCE_TEXT_SHA):
                raise ValueError('observed Guyon route requires validated accepted context')
            guyon_source_profile.check_text_lxml(doc)
            guyon_source_profile.check_header_lxml(doc, accepted=True)
        elif guyon_binding is not None:
            raise ValueError('observed Guyon binding cannot apply to another profile')
        if moody:
            _moody_profile_shape_lxml(doc, raw, identity, language, category, collection)
        if coppens:
            coppens_source.check_lxml(doc, raw, identity, language, category, collection)
        if cassiodorus:
            cass_source.check_document_lxml(doc, raw, identity, language, category, collection)
        if projection_profile is not None and (not (paired or carey or elmslie or holy_images or peter_jones or hodge or american_missionary or guyon or moody or coppens or cassiodorus or fox or woolman or source_lines or pta_vita_sic or pta_hesychius_sic) or (category != 'prose' and not (source_lines and category == 'prayers')) or collection or not _allow_acceptance_metadata):
            raise ValueError('unknown native prose projection profile')
        if hodge and (identity != _HODGE_IDENTITY or language != 'en'
                      or doc.tag != NS+'TEI' or doc.get(XML+'id') != 'hodge-systematic-theology-vol-1-candidate'):
            raise ValueError('Hodge native accepted identity or envelope differs')
        if peter_jones and (identity != _PETER_JONES_IDENTITY or language != 'en'
                            or hashlib.sha256(raw).hexdigest() != _PETER_JONES_MASTER_SHA
                            or doc.get(XML+'id') != 'peter-jones-1860-wikisource-edited-selection'):
            raise ValueError('Peter Jones accepted master or identity differs')
        whole_sermon = category == 'sermons' and not collection and not mtp
        corpus = doc.tag == NS+'teiCorpus'
        if corpus and (category in ('sermons', 'commentary') or len(doc) < 2 or doc[0].tag != NS+'teiHeader'):
            raise ValueError('native corpus edition/member envelope differs')
        documents = list(doc)[1:] if corpus else [doc]
        wilberforce_group = identity['work_id'] == 'wilberforce-practical-view'
        if carey and (corpus or language != 'en'
                      or identity != {'work_id': 'carey-enquiry', 'textual_form_id': 'carey-enquiry-retained-text',
                                      'edition_id': 'carey-enquiry-pg11449-electronic-witness'}
                      or doc.get(XML+'id') != 'gutenberg-carey-enquiry'):
            raise ValueError('Carey grouped source identity differs')
        if elmslie and (corpus or language != 'en'
                        or identity != {'work_id': 'elmslie-books-of-chronicles',
                                        'textual_form_id': 'elmslie-books-of-chronicles-gutenberg-retained',
                                        'edition_id': 'elmslie-books-of-chronicles-gutenberg-electronic'}
                        or doc.get(XML+'id') != 'gutenberg-elmslie-books-of-chronicles'):
            raise ValueError('Elmslie abbreviation source identity differs')
        if holy_images and (corpus or language != 'en' or identity != {
                'work_id': 'pg49917-holy-images', 'textual_form_id': 'pg49917-holy-images-english',
                'edition_id': 'pg49917-holy-images-pg49917-edition'}
                or doc.get(XML+'id') != 'pg49917-holy-images-tei'):
            raise ValueError('Holy Images source identity differs')
        if wilberforce_group and (corpus or category != 'prose' or collection or projection_profile is not None
                                 or language != 'en' or doc.get(XML+'id') != 'gutenberg-wilberforce-practical-view'):
            raise ValueError('Wilberforce grouped source envelope differs')
        valid_orders = [[NS+name for name in names] for names in (('front', 'body'), ('body',), ('body', 'back'), ('front', 'body', 'back'))]
        text_root = doc.find(NS+'text')
        if paired:
            if corpus or doc.get(XML+'lang') != language:
                raise ValueError('Greenleaf source document language differs')
            _greenleaf_characters_lxml(doc)
        elif (doc.find(NS+'teiHeader/'+NS+'encodingDesc/'+NS+'charDecl') is not None
              or text_root is not None and any(
                  node.tag == NS+'divGen' or node.tag == NS+'index' and node.get('indexName') in ('toc', 'pdf')
                  or node.tag == NS+'g' and node.get('ref') == '#U0x2014' for node in text_root.iter())):
            raise ValueError('source-declared Greenleaf features lack projection profile')
        document_attributes = {XML+'id', 'version', XML+'lang'}
        envelopes = [(doc, document_attributes)]
        member_texts = []
        for member in documents:
            if member.tag != NS+'TEI' or [child.tag for child in member] != [NS+'teiHeader', NS+'text'] + ([NS+'standOff'] if source_projection_nodes else []):
                raise ValueError('native document header/text envelope differs')
            source_text = member[1]
            if group_profile is not None or john or strong_group:
                outer = source_text
                group = outer[0]
                source_texts = list(group)
                envelopes.extend([(outer, {XML+'lang'}), (group, {XML+'id'})])
            elif whitefield:
                outer=source_text;group=outer[0];source_texts=list(group)
                envelopes.extend([(outer,set()),(group,set())])
            elif wilberforce_group or carey:
                outer = source_text
                inner_id = 'carey-enquiry' if carey else 'wilberforce-practical-view'
                if (dict(outer.attrib) != {XML+'lang': 'en'} or len(outer) != 1
                        or outer[0].tag != NS+'group' or len(outer[0].attrib) or len(outer[0]) != 1
                        or outer[0][0].tag != NS+'text'
                        or dict(outer[0][0].attrib) != {XML+'id': inner_id}):
                    raise ValueError('grouped source envelope differs')
                source_texts = [outer[0][0]]
                envelopes.extend([(outer, {XML+'lang'}), (outer[0], set())])
            else:
                source_texts = [source_text]
            envelopes.append((member, document_attributes))
            member_language = member.get(XML+'lang')
            if member_language and not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', member_language):
                raise ValueError('invalid native document language')
            for member_number, source_text in enumerate(source_texts):
                member_texts.append(source_text)
                if farrar_text_space and source_text.get(XML+'space') != 'preserve':
                    raise ValueError('Farrar retained text whitespace declaration differs')
                order = [node.tag for node in source_text]
                if order not in valid_orders:
                    raise ValueError('native document part order differs')
                text_allowed = ({XML+'id', XML+'lang', XML+'base', 'ana', 'n'} if whitefield else {XML+'id', XML+'lang'}) | ({XML+'space'} if farrar_text_space else set()) | ({'ana'} if john else set()) | ({'n'} if strong_group else set())
                if group_profile is not None and group_profile['members'][member_number]['declared_member_base']:
                    text_allowed.add(XML+'base')
                _allow_preserved_text_space(source_text, text_allowed, error_type=ValueError)
                envelopes.append((source_text, text_allowed))
                envelopes.extend((part, {XML+'id', XML+'lang'} | ({'rend'} if paired and part.tag == NS+'back' else set())) for part in source_text)
                declared_language = source_text.get(XML+'lang')
                if declared_language and ((corpus and declared_language != language) or not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', declared_language)):
                    raise ValueError('native member language differs')
        source_text = member_texts[0]
        front = source_text.find(NS+'front')
        body = source_text.find(NS+'body')
        if whole_sermon and (order != [NS+'front', NS+'body'] or not len(body) or any(child.tag != NS+'div' or child.get('type') != 'sermon' for child in body)):
            raise ValueError('native sermon unit selection differs')
        if mark:
            _mark_body_lxml(body)
        elif mtp:
            _mtp_body_lxml(body)
        elif collection or category == 'commentary':
            if not len(body) or any(child.tag != NS+'div' or child.get('type') != ('thml-div1' if wesley else 'source-div1') for child in body):
                raise ValueError('native collection body divisions differ')
        for node, allowed in envelopes:
            if node.get('version') is not None and not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,2}', node.get('version')):
                raise ValueError('invalid native TEI version')
            if set(node.attrib)-allowed or (node.text or '').strip() or any((child.tail or '').strip() for child in node):
                raise ValueError('native sermon envelope has unaccounted content')
        if source_text.get(XML+'lang') and not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', source_text.get(XML+'lang')):
            raise ValueError('native document language differs')
        if paired and (source_text.get(XML+'lang') != language or source_text.find(NS+'back') is None
                       or source_text.find(NS+'back').get('rend') != 'page-break-before: right'):
            raise ValueError('Greenleaf source language or back-matter rendition differs')
        elements, attributes = _header_rules(_allow_acceptance_metadata)
        if wesley:elements, attributes = _wesley_header_rules(elements, attributes)
        if strong_group:elements, attributes = strong_complete.header_rules(elements, attributes)
        if thome_exact:
            elements = dict(elements)
            elements['sourceDesc'] = list(set(elements.get('sourceDesc', [])) | {'p'})
            elements['p'] = list(set(elements.get('p', [])) | {'bibl'})
        if l599:elements, attributes = l599_source.header_rules(elements, attributes)
        if samuel:
            elements, attributes = _samuel_header_rules(elements, attributes)
        guyon_header_nodes = guyon_source_profile.source_header_nodes_lxml(doc) if guyon else set()
        selected = []
        evidence_nodes = set(source_projection_nodes)
        private_nodes = set()
        if holy_images:
            markers = doc.xpath('.//t:milestone[@unit="source-html-comment"]', namespaces={'t': NS[1:-1]})
            if len(markers) != 5:
                raise ValueError('Holy Images source-comment count differs')
            private_nodes.update(markers)
        if paired:
            selected, private_nodes = _greenleaf_units_lxml(doc)
        elif whole_sermon:
            selected = [(1, 'body', sibling, unit, '', ()) for sibling, unit in enumerate(body, 1)]
        else:
            for volume, text_member in enumerate(member_texts, 1):
                for part in text_member:
                    for sibling, source_unit in enumerate(part, 1):
                        if _ryle_private_ledger_lxml(source_unit, identity=identity, part=etree.QName(part).localname):
                            private_nodes.update(source_unit.iter())
                            continue
                        if source_lines:
                            source_unit, excluded = _source_lines_public_shadow(source_unit)
                            private_nodes.update(excluded)
                        pair = _observe_readable_source_member(doc, source_unit, corpus=corpus) if category == 'prose' else None
                        if pair is None:
                            selected.append((volume, etree.QName(part).localname, sibling, source_unit, '', ()))
                        else:
                            readable, evidence = pair
                            selected.append((volume, etree.QName(part).localname, sibling, readable, '/div[1]', ()))
                            evidence_nodes.update(evidence.iter())
        if identity['work_id'] == 'ryle-holiness' and not private_nodes:
            raise ValueError('Ryle private source ledger is missing')
        if not selected:
            raise ValueError('empty native document')
        inventory = []
        exclusions = []
        identifiers = []
        for ordinal, node in enumerate(doc.iter(), 1):
            qname = etree.QName(node)
            if qname.namespace != NS[1:-1]:
                raise ValueError('native sermon namespace differs')
            tag = qname.localname
            header = node.tag == NS+'teiHeader' or any(parent.tag == NS+'teiHeader' for parent in node.iterancestors())
            if header and not whitefield and not gaines_exact and node not in source_projection_nodes and node not in guyon_header_nodes:
                stokes_bibl_p = (_allow_acceptance_metadata and category == 'commentary'
                                and identity['work_id'] == 'expositors-bible--g-t-stokes'
                                and tag == 'p' and node.getparent() is not None
                                and node.getparent().tag == NS+'sourceDesc'
                                and not node.attrib and [child.tag for child in node] == [NS+'bibl'])
                accepted_binding_p = node is binding_wrapper
                if tag == 'p' and any(child.tag == NS+'bibl' for child in node) and not (stokes_bibl_p or accepted_binding_p or thome_exact):
                    raise ValueError('native sermon header structure differs')
                group_bibl_list = group_profile is not None and tag == 'listBibl'
                group_bibl_head = group_profile is not None and tag == 'head' and node.getparent() is not None and node.getparent().tag == NS+'listBibl'
                allowed_children = (set(elements.get(tag, []))
                                    | ({'bibl'} if stokes_bibl_p or accepted_binding_p else set())
                                    | ({'listBibl'} if group_profile is not None and tag == 'sourceDesc' else set())
                                    | ({'listBibl', 'head', 'bibl', 'biblFull'} if group_bibl_list else set()))
                if tag not in elements and not (group_bibl_list or group_bibl_head) or any(child.tag not in {NS+name for name in allowed_children} for child in node):
                    raise ValueError('native sermon header structure differs')
                for key in node.attrib:
                    name = etree.QName(key)
                    spelling = 'xml:'+name.localname if name.namespace == XML[1:-1] else key
                    if spelling not in set(attributes.get(tag, [])) | {'xml:id'}:
                        raise ValueError('native sermon header attributes differ')
                if tag == 'revisionDesc' and node.get('status') not in (None, 'candidate', 'draft', 'approved'):
                    raise ValueError('native revision status differs')
                if tag == 'rendition' and (node.get('scheme') != 'css' or (node.get('selector') is not None and not node.get('selector').strip()) or not (node.text or '').strip()):
                    raise ValueError('native CSS rendition differs')
            if node.get(XML+'id'):
                identifiers.append(node.get(XML+'id'))
            role = ('machine-source-evidence' if node in evidence_nodes else 'bibliographic-header' if header
                    else 'source-generator-only' if node in private_nodes else 'native-content-or-envelope')
            inventory.append({'ordinal': ordinal, 'tag': tag, 'attributes': dict(node.attrib),
                              'text_sha256': hashlib.sha256((node.text or '').encode()).hexdigest(),
                              'tail_sha256': hashlib.sha256((node.tail or '').encode()).hexdigest(), 'role': role})
            if header or node in evidence_nodes or node in private_nodes:
                exclusions.append({'ordinal': ordinal, 'reason': role})
        if len(identifiers) != len(set(identifiers)):
            raise ValueError('duplicate native source identifiers')
        observed_front, front_text = observe_content(etree.tostring(front, with_tail=False)) if whole_sermon else (None, None)
        book_codes = load_book_codes() if whole_sermon or category == 'prose' else None
        expected = []
        anchors = []
        for index, (volume, part_name, sibling, source, nested_path, leading) in enumerate(selected, 1):
            heads = source.findall(NS+'head')
            labels = source.findall(NS+'epigraph/'+NS+'bibl')
            if whole_sermon and (len(heads) != 1 or len(labels) != 1):
                raise ValueError('native primary passage or heading selection differs')
            member_profile = group_profile['members'][volume-1] if group_profile is not None else None
            effective_base = member_profile['base'] if member_profile is not None else source_base
            content, readable = observe_content(etree.tostring(_gaines_readable_shadow(source) if gaines_exact else source, with_tail=False), source_profile=strong_complete.member_content_profile(volume) if strong_group else THOME_PROFILE if thome_exact else native_content.PTA_ANONYMOUS_VITA_PROFILE if pta_vita_sic else native_content.PTA_HESYCHIUS_PROFILE if pta_hesychius_sic else strong_source.PROFILE if strong else whitefield_source.PROFILE if whitefield else SAMUEL_PROFILE if samuel else MTP_PROFILE if mtp else WESLEY_PROFILE if wesley else MARK_PROFILE if mark else FOX_PROFILE if fox else native_content.BENNETT_CHRONICLES_PROFILE if bennett_chronicles else projection_profile if carey or elmslie or holy_images or peter_jones or hodge or american_missionary or guyon or moody or coppens or cassiodorus or fox or woolman or source_lines else None,
                                                source_base=effective_base)
            if member_profile is not None:
                commentary_group_policy.inherit_base_lxml(source, content, member_profile)
            if virgin_mary_note and part_name == 'back':
                readable = _virgin_mary_note_text_lxml(source)
            if magnesians_note and part_name == 'back':
                readable = _numbered_note_text_lxml(source, first_number=890, count=96,
                                                     first_paragraph=2296, work_label='Magnesians')
            if trallians_note and part_name == 'back':
                readable = _numbered_note_text_lxml(source, first_number=986, count=91,
                                                     first_paragraph=2392, work_label='Trallians')
            if paired and not readable:
                raise ValueError('Greenleaf source division has no readable text')
            structure = [observe_content(etree.tostring(marker, with_tail=False))[0] for marker in leading] + [content]
            if leading:
                structure[1]['attributes']['source_anchor'] = leading[1].get(XML+'id')
            heading = observe_content(etree.tostring(heads[0], with_tail=False))[1] if whole_sermon else None
            primary = observe_content(etree.tostring(labels[0], with_tail=False))[1] if whole_sermon else None
            text_path = (f'/TEI/text/group/text[{volume}]' if whitefield or group_profile is not None or john or strong_group else
                         '/TEI/text/group/text' if wilberforce_group or carey else '/TEI/text')
            location = text_path+'/'+part_name+('/div[' if whole_sermon else '/*[')+str(sibling)+']'
            if corpus:
                location = '/teiCorpus/TEI['+str(volume)+']'+location[len('/TEI'):]
            location += nested_path
            identifier = identity['edition_id']+(':'+('sermon' if whole_sermon else 'native')+':')+hashlib.sha256(location.encode()).hexdigest()[:20]
            expected.append({**identity, 'record_id': identifier, 'sequence': index, 'category': 'sermons',
                             'language': language, 'representation_revision': representation_revision,
                             'provenance': {'edition_title': edition_title, **_observe_entry_attribution(source)}, 'content_format': FORMAT,
                             'locator': {'kind': 'sermon', 'number': source.get('n'), 'headings': [heading]},
                             'primary_passage': primary, 'collection': None,
                             'delivery': {'statement': None, 'date': None, 'place': None, 'occasion': None},
                             'structure': structure, 'text': readable,
                             'front_matter': [{'structure': observed_front, 'text': front_text}] if index == 1 else []})
            if whole_sermon:
                expected[-1]['primary_reference'] = {'raw': primary, 'references': [observe_reference_record({'raw': observe_content(etree.tostring(ref, with_tail=False))[1], **{k: ref.get(k) for k in ('cRef', 'target') if ref.get(k) is not None}}, book_codes=book_codes) for ref in labels[0].iter(NS+'ref')]}
            if category == 'prose':
                expected[-1]['source_references'] = _observe_prose_references(source, book_codes, THOME_PROFILE if thome_exact else FOX_PROFILE if fox else whitefield_source.PROFILE if whitefield else None)
            if not whole_sermon:
                row = expected[-1]
                for key in ('primary_passage', 'collection', 'delivery', 'front_matter'):
                    del row[key]
                row['category'] = category
                row['locator'] = {'kind': 'native-unit', 'text_part': part_name, 'unit': sibling}
                if corpus or whitefield or group_profile is not None or john or strong_group:
                    row['locator']['document'] = volume
            anchors.append({'unit_id': location, 'record_id': identifier,
                            'text_sha256': hashlib.sha256(readable.encode()).hexdigest()})
        if public_disposition is not None:
            expected = native_public_dispositions.observe_rows(expected, raw, public_disposition)
        if john:
            expected = tyerman_john_group_profile.observe_rows(expected, doc)
        _validate_rows(rows, category)
        wanted = {'scope': SCOPE, 'mapping_version': strong_complete.VERSION if strong_group else THOME_PROFILE if thome_exact else native_content.PTA_ANONYMOUS_VITA_PROFILE if pta_vita_sic else native_content.PTA_HESYCHIUS_PROFILE if pta_hesychius_sic else strong_source.PROFILE if strong else whitefield_source.PROFILE if whitefield else tyerman_john_group_profile.VERSION if john else SAMUEL_PROFILE if samuel else MTP_PROFILE if mtp else commentary_group_policy.version(group_profile) if group_profile is not None else FARRAR_TEXT_SPACE_PROFILE if farrar_text_space else native_public_dispositions.mapping_version(public_disposition) if public_disposition else MARK_PROFILE if mark else TRALLIANS_NOTE_PROFILE if trallians_note else MAGNESIANS_NOTE_PROFILE if magnesians_note else VIRGIN_MARY_NOTE_PROFILE if virgin_mary_note else FOX_PROFILE if fox else native_content.BENNETT_CHRONICLES_PROFILE if bennett_chronicles else projection_profile if carey or paired or elmslie or peter_jones or hodge or american_missionary or guyon or moody or coppens or cassiodorus or fox or woolman or source_lines else VERSION if whole_sermon else ('ocd-prose-native-v3' if category == 'prose' else f'ocd-{category}-native-v2'),
                  'master_sha256': hashlib.sha256(raw).hexdigest(), **_schema_bindings(category), **({'book_codes_sha256': _sha(BOOK_CODES_PATH.read_bytes())} if whole_sermon or category == 'prose' else {}),
                  'output_sha256': hashlib.sha256(json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                  'row_count': len(expected), 'anchors': anchors, 'inventory': inventory, 'exclusions': exclusions,
                  **({'source_comments': comments} if comments else {}),
                   **({'source_processing_instructions': processing_instructions} if processing_instructions else {}),
                  **({'projection_profile': native_content.PTA_ANONYMOUS_VITA_PROFILE} if pta_vita_sic else {'projection_profile': native_content.PTA_HESYCHIUS_PROFILE} if pta_hesychius_sic else {'projection_profile': projection_profile} if carey or paired or elmslie or peter_jones or hodge or american_missionary or guyon or moody or coppens or cassiodorus or fox or woolman or source_lines else {}),
                  **({'guyon_source_binding': {**guyon_binding,
                       'source_header_sha256': guyon_source_profile.SOURCE_PARAGRAPHS_SHA}}
                     if guyon else {}),
                  'warnings': ['Bennett Chronicles retains a source column-group span marker in the private content structure; no print collation or inferred Bible target is claimed.'] if bennett_chronicles else list(strong_complete.WARNINGS) if strong_group else ['Strong Volume II is a retained middle-volume witness of one authored three-volume work. Literal source line IDs, numbers, whitespace declarations and heading continuation attachments are conserved; no print collation or complete three-volume reconstruction is claimed.'] if strong else ['John Wesley source has three retained volumes. Seven JPEG data URIs and archive member digests stay in private TEI; public rows carry stable image references, not image bytes. Abbreviation display chooses the source abbr branch while preserving both alternatives in structure.'] if john else ['Guyon source head metadata stays in private inventory. Cell numbers are literal DOM locators, not table columns; the retained cover is not a fetched public image.'] if guyon else ['Cassiodorus table cell @n values are literal source DOM locators, not semantic column numbers; @cols preserves source colspan. Table-boundary markers retain the source CRLF tail as base64 DQo=.'] if cassiodorus else ['MTP source units lack a uniform primary passage; no Bible target is inferred. The 27 archive images remain literal references, not fetched image assets.'] if mtp else ['The Farrar text wrapper declares xml:space="preserve"; its source attribute remains in the private inventory.'] if farrar_text_space else ['The 91 source endnotes form a separate readable back-matter row; page markers remain in structure.'] if trallians_note else ['The 96 source endnotes form a separate readable back-matter row; page markers remain in structure.'] if magnesians_note else ['The source endnote is a separate readable back-matter row; page markers remain in structure.'] if virgin_mary_note else ['Notes and page markers remain in structure; readable text omits them.'],
                  'unsupported': [], 'independent_check': {'status': 'pending'}}
        problems = []
        if rows != expected:
            problems.append('native sermon rows differ from independent source observations')
        if receipt != wanted:
            problems.append('native sermon receipt differs from independent accounting')
        return problems
    except (PipelineError, OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return ['native sermon verification failed: '+str(exc)]


def is_source_collection(path):
    """Route source divisions, including grouped member texts, to native units."""
    raw = io_path(Path(path)).read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise PipelineError('unsupported native collection declaration')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PipelineError(f'invalid native collection XML: {exc}') from exc
    if root.tag != NS+'TEI':
        return False
    body = root.find(NS+'text/'+NS+'body')
    if body is not None:
        return len(body) > 0 and (_sha(raw) in (_MARK_MASTER_SHA, _WESLEY_MASTER_SHA) or all(
            child.tag == NS+'div' and child.get('type') == 'source-div1' for child in body
        ))
    group = root.find(NS+'text/'+NS+'group')
    if group is None or len(group) == 0:
        return False
    return all(member.tag == NS+'text' and (member.find(NS+'body') is not None)
               and len(member.find(NS+'body')) > 0 and all(
                   child.tag == NS+'div' and child.get('type') == 'source-div1'
                   for child in member.find(NS+'body')) for member in group)


def project_accepted_document(root, *, acceptance_path, category, collection=False, projection_profile=None):
    """Connect a validated edition to the shared native document projection."""
    if projection_profile == 'ocd-prose-apostolic-tradition-pg61614-eleven-spans-v1':
        if category != 'prose' or collection:
            raise PipelineError('Apostolic profile requires one prose document')
        from ocd_kernel.projection.categories.apostolic_tradition import project_accepted
        return project_accepted(root, acceptance_path=acceptance_path)
    from ocd_kernel.projection.categories.sermons import _accepted_context
    context = _accepted_context(root, acceptance_path, expected_category=category)
    fox_binding = fox_source.select_accepted(context, category=category, collection=collection, projection_profile=projection_profile)
    if fox_binding is not None:
        projection_profile = fox_binding
    elif projection_profile == FOX_PROFILE:
        raise PipelineError('Fox profile requires its exact accepted identity')
    woolman_binding = woolman_source.select_accepted(context, category=category, collection=collection, projection_profile=projection_profile)
    if woolman_binding is not None:
        projection_profile = woolman_binding
    elif projection_profile == WOOLMAN_PROFILE:
        raise PipelineError('Woolman profile requires its exact accepted identity')
    guyon_binding = guyon_source_profile.select_accepted(
        context, category=category, collection=collection,
        projection_profile=projection_profile)
    if guyon_binding is not None:
        projection_profile = GUYON_PROFILE
    elif projection_profile == GUYON_PROFILE:
        raise PipelineError('Guyon profile requires its exact accepted identity')
    if _pta_anonymous_vita_sic_route(
            context['identity'], context['accepted']['promotion']['master']['sha256'],
            language=context['language'], category=category, collection=collection,
            projection_profile=projection_profile, allow_acceptance_metadata=True,
            acquisition_id=context['accepted']['identity']['acquisition_id']):
        projection_profile = native_content.PTA_ANONYMOUS_VITA_PROFILE
    if _pta_hesychius_empty_sic_route(
            context['identity'], context['accepted']['promotion']['master']['sha256'],
            language=context['language'], category=category, collection=collection,
            projection_profile=projection_profile, allow_acceptance_metadata=True,
            acquisition_id=context['accepted']['identity']['acquisition_id']):
        projection_profile = native_content.PTA_HESYCHIUS_PROFILE
    group_profile = commentary_group_policy.select(context, category=category)
    source_base = None if group_profile is not None else _accepted_expositor_source_base(context, category)
    public_disposition = native_public_dispositions.select(
        context['root'], context['identity'], context['accepted'],
        io_path(context['edition'].path).read_bytes(), category=category,
        collection=collection, projection_profile=projection_profile,
        allow_acceptance_metadata=True)
    result = project_document(context['edition'].path, identity=context['identity'],
                              language=context['language'], representation_revision=context['representation_revision'],
                              edition_title=context['edition_title'], _allow_acceptance_metadata=True, category=category,
                              collection=collection, projection_profile=projection_profile, source_base=source_base,
                              public_disposition=public_disposition, group_profile=group_profile,
                              guyon_binding=guyon_binding,
                              acquisition_id=context['accepted']['identity']['acquisition_id'])
    result['receipt']['authority'] = context['authority']
    result['receipt']['scope'] = 'tei-document; context derived from validated acceptance'
    return result


def verify_accepted_document(root, *, acceptance_path, rows, receipt, category, collection=False, projection_profile=None):
    """Check canonical authority and independently observe the complete edition."""
    if projection_profile == 'ocd-prose-apostolic-tradition-pg61614-eleven-spans-v1':
        if category != 'prose' or collection:
            return ['Apostolic profile requires one prose document']
        from ocd_kernel.projection.categories.apostolic_tradition_check import verify_accepted
        return verify_accepted(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)
    from ocd_kernel.projection.categories.sermons import _accepted_context
    try:
        context = _accepted_context(root, acceptance_path, expected_category=category)
        fox_binding = fox_source.select_accepted(context, category=category, collection=collection, projection_profile=projection_profile)
        if fox_binding is not None:
            projection_profile = fox_binding
        elif projection_profile == FOX_PROFILE:
            raise ValueError('observed Fox profile requires its exact accepted identity')
        woolman_binding = woolman_source.select_accepted(context, category=category, collection=collection, projection_profile=projection_profile)
        if woolman_binding is not None:
            projection_profile = woolman_binding
        elif projection_profile == WOOLMAN_PROFILE:
            raise ValueError('observed Woolman profile requires its exact accepted identity')
        guyon_binding = guyon_source_profile.select_accepted(
            context, category=category, collection=collection,
            projection_profile=projection_profile)
        if guyon_binding is not None:
            projection_profile = GUYON_PROFILE
        elif projection_profile == GUYON_PROFILE:
            raise ValueError('observed Guyon profile requires its exact accepted identity')
        if _pta_anonymous_vita_sic_route(
                context['identity'], context['accepted']['promotion']['master']['sha256'],
                language=context['language'], category=category, collection=collection,
                projection_profile=projection_profile, allow_acceptance_metadata=True,
                acquisition_id=context['accepted']['identity']['acquisition_id']):
            projection_profile = native_content.PTA_ANONYMOUS_VITA_PROFILE
        if _pta_hesychius_empty_sic_route(
                context['identity'], context['accepted']['promotion']['master']['sha256'],
                language=context['language'], category=category, collection=collection,
                projection_profile=projection_profile, allow_acceptance_metadata=True,
                acquisition_id=context['accepted']['identity']['acquisition_id']):
            projection_profile = native_content.PTA_HESYCHIUS_PROFILE
        group_profile = commentary_group_policy.select(context, category=category)
        source_base = None if group_profile is not None else _accepted_expositor_source_base(context, category)
        public_disposition = native_public_dispositions.select(
            context['root'], context['identity'], context['accepted'],
            io_path(context['edition'].path).read_bytes(), category=category,
            collection=collection, projection_profile=projection_profile,
            allow_acceptance_metadata=True)
        if not isinstance(receipt, dict):
            return [f'native {category} receipt must be an object']
        errors = []
        if receipt.get('authority') != context['authority']:
            errors.append(f'native {category} accepted authority differs')
        if receipt.get('scope') != 'tei-document; context derived from validated acceptance':
            errors.append(f'native {category} accepted scope differs')
        document_receipt = dict(receipt)
        document_receipt.pop('authority', None)
        document_receipt['scope'] = SCOPE
        errors.extend(verify_document(context['edition'].path, rows, document_receipt,
                      identity=context['identity'], language=context['language'],
                      representation_revision=context['representation_revision'],
                      edition_title=context['edition_title'], _allow_acceptance_metadata=True, category=category,
                      collection=collection, projection_profile=projection_profile, source_base=source_base,
                      public_disposition=public_disposition, group_profile=group_profile,
                      guyon_binding=guyon_binding,
                      acquisition_id=context['accepted']['identity']['acquisition_id']))
        return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        return [str(exc)]
