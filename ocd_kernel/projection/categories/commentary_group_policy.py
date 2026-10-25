"""Exact accepted complete-group commentary transport profile, scratch proposal only."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path

TEI = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
MAPPING_VERSION = 'ocd-commentary-grouped-native-v1'
INHERITED_VERSION = 'ocd-commentary-grouped-native-v1+literal-inherited-base-v1'
PROFILES = {item['identity']['edition_id']: item for item in json.loads(r'''[
  {
    "identity": {
      "acquisition_id": "expositors-bible--alexander-maclaren--maclaren-psalms-complete--retained-member-set",
      "edition_id": "expositors-bible--alexander-maclaren--maclaren-psalms-complete--ccel-electronic",
      "textual_form_id": "expositors-bible--alexander-maclaren--maclaren-psalms-complete--retained-en",
      "work_id": "expositors-bible--alexander-maclaren"
    },
    "revision": "maclaren-psalms-complete-20261003-v1",
    "master_path": "library/works/expositors-bible--alexander-maclaren/forms/expositors-bible--alexander-maclaren--maclaren-psalms-complete--retained-en/editions/expositors-bible--alexander-maclaren--maclaren-psalms-complete--ccel-electronic/master.tei.xml",
    "master_sha256": "18b7d84bb045046579249660ae85bdaa0cd4a73e4b50f69a060e296ec8ff92ff",
    "grouped_acquisition_path": "library/works/expositors-bible--alexander-maclaren/forms/expositors-bible--alexander-maclaren--maclaren-psalms-complete--retained-en/editions/expositors-bible--alexander-maclaren--maclaren-psalms-complete--ccel-electronic/acquisitions/expositors-bible--alexander-maclaren--maclaren-psalms-complete--retained-member-set.json",
    "grouped_acquisition_sha256": "b3974c750a5f0101ba248709e96d25a76d9d995e336cf4349252819e1b221b6c",
    "group_id": "maclaren-psalms-source-volumes",
    "members": [
      {
        "member_id": "maclaren-expositorpsalms1",
        "source": {
          "bytes": 790728,
          "media_type": "application/xml",
          "path": "raw/ccel/expositors-bible/maclaren_expositorpsalms1.xml",
          "scope": "Complete original Maclaren Psalms source Volume 1 including all electronic regions and source metadata.",
          "sha256": "5f76553f07cf45368a772e0a2f654df2852ee9be5c3f0f4d35549391a4791b58"
        },
        "acquisition_path": "library/works/expositors-bible--alexander-maclaren/forms/expositors-bible--alexander-maclaren--maclaren-expositorpsalms1--retained-en/editions/expositors-bible--alexander-maclaren--maclaren-expositorpsalms1--ccel-electronic/acquisitions/expositors-bible--alexander-maclaren--maclaren-expositorpsalms1--acquired.json",
        "acquisition_sha256": "bbaa183822806b5ff637a34ea62102d834a29e83267b5c74efc6b2dc99bcc994",
        "base": "https://www.ccel.org/ccel/maclaren/expositorpsalms1.html",
        "declared_member_base": null,
        "part_counts": {
          "back": 1,
          "body": 38,
          "front": 2
        },
        "relative_ref_count": 426,
        "explicit_ref_base_count": 38
      },
      {
        "member_id": "maclaren-expositorpsalms2",
        "source": {
          "bytes": 1048849,
          "media_type": "application/xml",
          "path": "raw/ccel/expositors-bible/maclaren_expositorpsalms2.xml",
          "scope": "Complete original Maclaren Psalms source Volume 2 including all electronic regions and source metadata.",
          "sha256": "e7bf253c78cc91a77c3a3a5173122f89d03b29390ade4f3e14f5d2db2ef98ebb"
        },
        "acquisition_path": "library/works/expositors-bible--alexander-maclaren/forms/expositors-bible--alexander-maclaren--maclaren-expositorpsalms2--retained-en/editions/expositors-bible--alexander-maclaren--maclaren-expositorpsalms2--ccel-electronic/acquisitions/expositors-bible--alexander-maclaren--maclaren-expositorpsalms2--acquired.json",
        "acquisition_sha256": "3fa479c5d19149315c51948a660afb6e3316e61347d47011c6742c3395f77aa7",
        "base": "https://www.ccel.org/ccel/maclaren/expositorpsalms2.html",
        "declared_member_base": null,
        "part_counts": {
          "back": 1,
          "body": 50,
          "front": 1
        },
        "relative_ref_count": 551,
        "explicit_ref_base_count": 51
      },
      {
        "member_id": "maclaren-expositorpsalms3",
        "source": {
          "bytes": 960697,
          "media_type": "application/xml",
          "path": "raw/ccel/expositors-bible/maclaren_expositorpsalms3.xml",
          "scope": "Complete original Maclaren Psalms source Volume 3 including all electronic regions and source metadata.",
          "sha256": "451e5e3c7196a06caa96992cbc7c43f23f033ab84459373368b5685195c942bb"
        },
        "acquisition_path": "library/works/expositors-bible--alexander-maclaren/forms/expositors-bible--alexander-maclaren--maclaren-expositorpsalms3--retained-en/editions/expositors-bible--alexander-maclaren--maclaren-expositorpsalms3--ccel-electronic/acquisitions/expositors-bible--alexander-maclaren--maclaren-expositorpsalms3--acquired.json",
        "acquisition_sha256": "9f486efb0fab6bafb15776125eb32ac5530754edf4ae634d409f855270fc2ad0",
        "base": "https://www.ccel.org/ccel/maclaren/expositorpsalms3.html",
        "declared_member_base": null,
        "part_counts": {
          "back": 1,
          "body": 61,
          "front": 1
        },
        "relative_ref_count": 522,
        "explicit_ref_base_count": 61
      }
    ]
  },
  {
    "identity": {
      "acquisition_id": "expositors-bible--marcus-dods--dods-expositorjohn-complete--retained-member-set",
      "edition_id": "expositors-bible--marcus-dods--dods-expositorjohn-complete--ccel-electronic",
      "textual_form_id": "expositors-bible--marcus-dods--dods-expositorjohn-complete--retained-en",
      "work_id": "expositors-bible--marcus-dods"
    },
    "revision": "dods-gospel-john-complete-current-20261003-v1",
    "master_path": "library/works/expositors-bible--marcus-dods/forms/expositors-bible--marcus-dods--dods-expositorjohn-complete--retained-en/editions/expositors-bible--marcus-dods--dods-expositorjohn-complete--ccel-electronic/master.tei.xml",
    "master_sha256": "7d059751104477d963354e6b33222c6fb13644bf65772bb5b03ac7e3f5626b12",
    "grouped_acquisition_path": "library/works/expositors-bible--marcus-dods/forms/expositors-bible--marcus-dods--dods-expositorjohn-complete--retained-en/editions/expositors-bible--marcus-dods--dods-expositorjohn-complete--ccel-electronic/acquisitions/expositors-bible--marcus-dods--dods-expositorjohn-complete--retained-member-set.json",
    "grouped_acquisition_sha256": "d38754310597a2e9180d6980d243377d1db71ba908b53fb696e855da6beff817",
    "group_id": "dods-gospel-john-volumes",
    "members": [
      {
        "member_id": "dods-expositorjohn1-volume",
        "source": {
          "bytes": 677469,
          "media_type": "application/xml",
          "path": "raw/ccel/expositors-bible/dods_expositorjohn1.xml",
          "scope": "Source-attested Volume I of The Gospel of St. John, in two volumes; entire retained CCEL XML, including front/body/back and literal print statement New York: A. C. Armstrong and Son, 1891.",
          "sha256": "a492b1d93e0fb5ca06ee88cf515fd7b35b61e432419b7f0e94f0cb84a1ad54d6"
        },
        "acquisition_path": "library/works/expositors-bible--marcus-dods/forms/expositors-bible--marcus-dods--dods-expositorjohn1--retained-en/editions/expositors-bible--marcus-dods--dods-expositorjohn1--ccel-electronic/acquisitions/expositors-bible--marcus-dods--dods-expositorjohn1--acquired.json",
        "acquisition_sha256": "0329c280e7f6c338a75d08bb895d619cdb57f7f781d0573addc69d39d49153b0",
        "base": "https://www.ccel.org/ccel/dods/expositorjohn1.html",
        "declared_member_base": null,
        "part_counts": {
          "back": 2,
          "body": 24,
          "front": 2
        },
        "relative_ref_count": 410,
        "explicit_ref_base_count": 27
      },
      {
        "member_id": "dods-expositorjohn2-volume",
        "source": {
          "bytes": 733463,
          "media_type": "application/xml",
          "path": "raw/ccel/expositors-bible/dods_expositorjohn2.xml",
          "scope": "Source-attested Volume II of The Gospel of St. John, in two volumes; entire retained CCEL XML, including front/body/back and literal print statement London: Hodder and Stoughton, 1892.",
          "sha256": "409412471fd4a5965579d992e76b70a08bfce14b446617fff49994c2e4aa47b8"
        },
        "acquisition_path": "library/works/expositors-bible--marcus-dods/forms/expositors-bible--marcus-dods--dods-expositorjohn2--retained-en/editions/expositors-bible--marcus-dods--dods-expositorjohn2--ccel-electronic/acquisitions/expositors-bible--marcus-dods--dods-expositorjohn2--acquired.json",
        "acquisition_sha256": "9053dc3ee55fa721786d5623cc9e1b9dd1c9c770e62b1ee405603f76129adf97",
        "base": "https://www.ccel.org/ccel/dods/expositorjohn2.html",
        "declared_member_base": null,
        "part_counts": {
          "back": 1,
          "body": 26,
          "front": 1
        },
        "relative_ref_count": 453,
        "explicit_ref_base_count": 32
      }
    ]
  },
  {
    "identity": {
      "acquisition_id": "expositors-bible--g-t-stokes--acts-complete-retained-member-set",
      "edition_id": "expositors-bible--g-t-stokes--acts-complete-ccel-electronic",
      "textual_form_id": "expositors-bible--g-t-stokes--acts-complete-retained-en",
      "work_id": "expositors-bible--g-t-stokes"
    },
    "revision": "stokes-acts-complete-current-20261003-v2",
    "master_path": "library/works/expositors-bible--g-t-stokes/forms/expositors-bible--g-t-stokes--acts-complete-retained-en/editions/expositors-bible--g-t-stokes--acts-complete-ccel-electronic/master.tei.xml",
    "master_sha256": "c529c9541da67a86a42accda956cb854d7148ba916642dc725738e3186e3eef0",
    "grouped_acquisition_path": "library/works/expositors-bible--g-t-stokes/forms/expositors-bible--g-t-stokes--acts-complete-retained-en/editions/expositors-bible--g-t-stokes--acts-complete-ccel-electronic/acquisitions/expositors-bible--g-t-stokes--acts-complete-retained-member-set.json",
    "grouped_acquisition_sha256": "4b75614f803dfa2d94db144676900c6be303d1680f80b4af308560b551b66030",
    "group_id": "stokes-acts-source-volumes",
    "members": [
      {
        "member_id": "stokes-expositoracts1-volume",
        "source": {
          "bytes": 1022435,
          "media_type": "application/xml",
          "path": "raw/ccel/expositors-bible/stokes_expositoracts1.xml",
          "scope": "Entire already acquired Stokes Acts Volume 1 in complete work source order",
          "sha256": "a6d7b301d9fd13ff5d298093eca5caa7463505684b0e4eae951ef2fc0fda34f6"
        },
        "acquisition_path": "library/works/expositors-bible--g-t-stokes/forms/expositors-bible--g-t-stokes--stokes-expositoracts1--retained-en/editions/expositors-bible--g-t-stokes--stokes-expositoracts1--ccel-electronic/acquisitions/expositors-bible--g-t-stokes--stokes-expositoracts1--acquired.json",
        "acquisition_sha256": "42ca1c57397828e1a6d052652818e10729c8decaaefb6b42958e022f3cb6405c",
        "base": "https://www.ccel.org/ccel/stokes/expositoracts1.html",
        "declared_member_base": null,
        "part_counts": {
          "back": 2,
          "body": 20,
          "front": 3
        },
        "relative_ref_count": 1375,
        "explicit_ref_base_count": 28
      },
      {
        "member_id": "stokes-expositoracts2-volume",
        "source": {
          "bytes": 1202000,
          "media_type": "application/xml",
          "path": "raw/ccel/expositors-bible/stokes_expositoracts2.xml",
          "scope": "Entire already acquired Stokes Acts Volume 2 in complete work source order",
          "sha256": "2f6cbaf722c823db42d7e63dda7b6ef17f691bc83e7fedc563df51440d15edf8"
        },
        "acquisition_path": "library/works/expositors-bible--g-t-stokes/forms/expositors-bible--g-t-stokes--stokes-expositoracts2--retained-en/editions/expositors-bible--g-t-stokes--stokes-expositoracts2--ccel-electronic/acquisitions/expositors-bible--g-t-stokes--stokes-expositoracts2--acquired.json",
        "acquisition_sha256": "a5b65eb4ed16cad1f4731616855274ec00e9f80f4fa80484c2229c9f25747911",
        "base": "https://www.ccel.org/ccel/stokes/expositoracts2.html",
        "declared_member_base": null,
        "part_counts": {
          "back": 2,
          "body": 18,
          "front": 3
        },
        "relative_ref_count": 1863,
        "explicit_ref_base_count": 29
      }
    ]
  },
  {
    "identity": {
      "acquisition_id": "expositors-bible--george-adam-smith--smith-ga-isaiah-complete--retained-member-set",
      "edition_id": "expositors-bible--george-adam-smith--smith-ga-isaiah-complete--ccel-electronic",
      "textual_form_id": "expositors-bible--george-adam-smith--smith-ga-isaiah-complete--retained-en",
      "work_id": "expositors-bible--george-adam-smith"
    },
    "revision": "smith-isaiah-complete-20261003-v1",
    "master_path": "library/works/expositors-bible--george-adam-smith/forms/expositors-bible--george-adam-smith--smith-ga-isaiah-complete--retained-en/editions/expositors-bible--george-adam-smith--smith-ga-isaiah-complete--ccel-electronic/master.tei.xml",
    "master_sha256": "05fcaded50edc2db2677c04f6fc1d0e30af245bc8cc94fa5f65b0fb3f76b33bf",
    "grouped_acquisition_path": "library/works/expositors-bible--george-adam-smith/forms/expositors-bible--george-adam-smith--smith-ga-isaiah-complete--retained-en/editions/expositors-bible--george-adam-smith--smith-ga-isaiah-complete--ccel-electronic/acquisitions/expositors-bible--george-adam-smith--smith-ga-isaiah-complete--retained-member-set.json",
    "grouped_acquisition_sha256": "8f44d117b5f3b66c0f53aabd78ca906df44cec324d0c9346ac5ca4246dac0116",
    "group_id": "smith-ga-isaiah-complete-volumes",
    "members": [
      {
        "member_id": "smith-ga-expositorisa1-volume",
        "source": {
          "bytes": 985575,
          "media_type": "application/xml",
          "path": "raw/ccel/expositors-bible/smith_ga_expositorisa1.xml",
          "scope": "Entire source-attested Volume I: The Expositor's Bible: The Book of Isaiah, Volume I; literal printed witness London: Hodder and Stoughton, 1910.; acquired URI https://www.ccel.org/ccel/smith_ga/expositorisa1.html. Full front/body/back, metadata, directives and source defects retained.",
          "sha256": "a464f1047de41078f887246295a2ec79b0911cecf14e893a9087b0ad72dc6646"
        },
        "acquisition_path": "library/works/expositors-bible--george-adam-smith/forms/expositors-bible--george-adam-smith--smith-ga-expositorisa1--retained-en/editions/expositors-bible--george-adam-smith--smith-ga-expositorisa1--ccel-electronic/acquisitions/expositors-bible--george-adam-smith--smith-ga-expositorisa1--acquired.json",
        "acquisition_sha256": "724c2ed1e9e9540d394d6f6a9a0510971959b4b13a038a64a5b8091f9cc1fff8",
        "base": "https://www.ccel.org/ccel/smith_ga/expositorisa1.html",
        "declared_member_base": "https://www.ccel.org/ccel/smith_ga/expositorisa1.html",
        "part_counts": {
          "back": 3,
          "body": 5,
          "front": 4
        },
        "relative_ref_count": 757,
        "explicit_ref_base_count": 0
      },
      {
        "member_id": "smith-ga-expositorisa2-volume",
        "source": {
          "bytes": 1083084,
          "media_type": "application/xml",
          "path": "raw/ccel/expositors-bible/smith_ga_expositorisa2.xml",
          "scope": "Entire source-attested Volume II: The Expositor's Bible: The Book of Isaiah, Volume II; literal printed witness London: Hodder and Stoughton, 1890.; acquired URI https://www.ccel.org/ccel/smith_ga/expositorisa2.html. Full front/body/back, metadata, directives and source defects retained.",
          "sha256": "284d42fbc9813cf06cb88e72362aea9c0cd08ea09e47776707541b8bc0998a80"
        },
        "acquisition_path": "library/works/expositors-bible--george-adam-smith/forms/expositors-bible--george-adam-smith--smith-ga-expositorisa2--retained-en/editions/expositors-bible--george-adam-smith--smith-ga-expositorisa2--ccel-electronic/acquisitions/expositors-bible--george-adam-smith--smith-ga-expositorisa2--acquired.json",
        "acquisition_sha256": "831b796e16379404a2852bf40ffd83dd41c92dab4711a9c84efc777413620d41",
        "base": "https://www.ccel.org/ccel/smith_ga/expositorisa2.html",
        "declared_member_base": "https://www.ccel.org/ccel/smith_ga/expositorisa2.html",
        "part_counts": {
          "back": 4,
          "body": 4,
          "front": 3
        },
        "relative_ref_count": 1038,
        "explicit_ref_base_count": 0
      }
    ]
  }
]''')}


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def select(context: dict, *, category: str):
    """Admit only the four source-bound accepted complete-title editions."""
    identity = context['identity']
    spec = PROFILES.get(identity.get('edition_id'))
    if spec is None:
        return None
    root = Path(context['root'])
    accepted = context['accepted']
    if accepted.get('representation_revision', {}).get('id') == 'dods-expositorjohn1-source-text-corrections-20261008-v1':
        if identity.get('edition_id') != 'expositors-bible--marcus-dods--dods-expositorjohn-complete--ccel-electronic':
            raise PipelineError('Dods corrected revision has a different edition')
        spec = spec | {'revision': 'dods-expositorjohn1-source-text-corrections-20261008-v1',
                       'master_sha256': '45b5f5affd11c69a63872c49e62f64617bdbcc63891552b0a85bebf7e709a0ec'}
    source = accepted.get('source', {})
    master_raw = io_path(context['edition'].path).read_bytes()
    manifest_raw = io_path(root / spec['grouped_acquisition_path']).read_bytes()
    manifest = json.loads(manifest_raw)
    if (category != 'commentary' or accepted.get('identity') != spec['identity']
            or identity != {key: spec['identity'][key] for key in ('work_id', 'textual_form_id', 'edition_id')}
            or accepted.get('representation_revision', {}).get('id') != spec['revision']
            or context['edition'].path != root / spec['master_path']
            or _sha(master_raw) != spec['master_sha256']
            or accepted.get('promotion', {}).get('master', {}).get('sha256') != spec['master_sha256']
            or source.get('source_manifest', {}).get('path') != spec['grouped_acquisition_path']
            or source.get('source_manifest', {}).get('sha256') != spec['grouped_acquisition_sha256']
            or _sha(manifest_raw) != spec['grouped_acquisition_sha256']
            or manifest.get('source_kind') != 'retained-member-set'
            or manifest.get('acquisition_id') != spec['identity']['acquisition_id']
            or manifest.get('edition_id') != spec['identity']['edition_id']
            or manifest.get('source_path') != source.get('source_path')
            or manifest.get('source_sha256') != source.get('source_sha256')
            or manifest.get('source_bytes') != source.get('source_bytes')):
        raise PipelineError('complete-group commentary authority differs')
    actual = [(m['path'], m['bytes'], m['sha256']) for m in manifest['retained_files']]
    expected = [(m['source']['path'], m['source']['bytes'], m['source']['sha256'])
                for m in spec['members']]
    included = [(m['path'], m['bytes'], m['sha256']) for m in accepted['scope']['included_members']]
    if actual != expected or included != expected:
        raise PipelineError('complete-group retained source set differs')
    for member in spec['members']:
        legacy_raw = io_path(root / member['acquisition_path']).read_bytes()
        if _sha(legacy_raw) != member['acquisition_sha256']:
            raise PipelineError('complete-group original acquisition differs')
        legacy = json.loads(legacy_raw)
        source_member = member['source']
        if (legacy.get('url') != member['base']
                or legacy.get('source_path') != source_member['path']
                or legacy.get('source_sha256') != source_member['sha256']
                or legacy.get('source_bytes') != source_member['bytes']):
            raise PipelineError('complete-group original member binding differs')
        retained = io_path(root / source_member['path']).read_bytes()
        if len(retained) != source_member['bytes'] or _sha(retained) != source_member['sha256']:
            raise PipelineError('complete-group retained member bytes differ')
    return spec


def version(spec: dict) -> str:
    return INHERITED_VERSION if any(m['declared_member_base'] for m in spec['members']) else MAPPING_VERSION


def source_census_et(raw: bytes, spec: dict) -> list[ET.Element]:
    root = ET.fromstring(raw)
    outer = root.find(TEI+'text')
    if (root.tag != TEI+'TEI' or outer is None or outer.attrib != {XML+'lang': 'en'}
            or len(outer) != 1 or outer[0].tag != TEI+'group'
            or outer[0].attrib != {XML+'id': spec['group_id']}
            or len(outer[0]) != len(spec['members'])):
        raise PipelineError('complete-group ET envelope differs')
    members = list(outer[0])
    for member, declared in zip(members, spec['members']):
        attrs = {XML+'lang': 'en', XML+'id': declared['member_id']}
        if declared['declared_member_base'] is not None:
            attrs[XML+'base'] = declared['base']
        if (member.tag != TEI+'text' or member.attrib != attrs
                or [part.tag for part in member] != [TEI+'front', TEI+'body', TEI+'back']
                or {part.tag.removeprefix(TEI): len(part) for part in member} != declared['part_counts']
                or any(child.tag != TEI+'div' or child.get('type') != 'source-div1'
                       for part in member for child in part)):
            raise PipelineError('complete-group ET member parts differ')
        refs = list(member.iter(TEI+'ref'))
        if sum(ref.get(XML+'base') == declared['base'] for ref in refs) != declared['explicit_ref_base_count']:
            raise PipelineError('complete-group ET explicit base count differs')
        if any(ref.get(XML+'base') not in (None, declared['base']) for ref in refs):
            raise PipelineError('complete-group ET explicit base differs')
        if sum(_is_relative(ref.get('target')) for ref in refs) != declared['relative_ref_count']:
            raise PipelineError('complete-group ET relative reference count differs')
    return members


def source_census_lxml(raw: bytes, spec: dict):
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    outer = root.find(TEI+'text')
    groups = list(outer) if outer is not None else []
    if (root.tag != TEI+'TEI' or outer is None or dict(outer.attrib) != {XML+'lang': 'en'}
            or len(groups) != 1 or groups[0].tag != TEI+'group'
            or dict(groups[0].attrib) != {XML+'id': spec['group_id']}
            or len(groups[0]) != len(spec['members'])):
        raise ValueError('observed complete-group envelope differs')
    members = list(groups[0])
    for member, declared in zip(members, spec['members']):
        attrs = {XML+'lang': 'en', XML+'id': declared['member_id']}
        if declared['declared_member_base'] is not None:
            attrs[XML+'base'] = declared['base']
        if (member.tag != TEI+'text' or dict(member.attrib) != attrs
                or tuple(part.tag for part in member) != (TEI+'front', TEI+'body', TEI+'back')
                or {part.tag.removeprefix(TEI): len(part) for part in member} != declared['part_counts']
                or any(child.tag != TEI+'div' or child.get('type') != 'source-div1'
                       for part in member for child in part)):
            raise ValueError('observed complete-group member parts differ')
        refs = member.xpath('.//tei:ref', namespaces={'tei': TEI[1:-1]})
        if len([ref for ref in refs if ref.get(XML+'base') == declared['base']]) != declared['explicit_ref_base_count']:
            raise ValueError('observed explicit base count differs')
        if any(ref.get(XML+'base') not in (None, declared['base']) for ref in refs):
            raise ValueError('observed explicit base differs')
        if len([ref for ref in refs if _is_relative(ref.get('target'))]) != declared['relative_ref_count']:
            raise ValueError('observed relative reference count differs')
    return members


def _is_relative(target: str | None) -> bool:
    if not target:
        return False
    if target.startswith(('#', '?')):
        return True
    if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target):
        return False
    raise ValueError('complete-group unclassified relative target')


def _content_refs(value):
    if isinstance(value, dict):
        if value.get('kind') == 'source-reference':
            yield value
        for child in value.values():
            yield from _content_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _content_refs(child)


def inherit_base_et(unit: ET.Element, content: dict, member: dict) -> None:
    """Relocate a declared member base to literal relative ref fields, without URL resolution."""
    native = list(unit.iter(TEI+'ref'))
    public = list(_content_refs(content))
    if len(native) != len(public):
        raise PipelineError('complete-group ET reference traversal differs')
    for source_ref, mapped in zip(native, public):
        attrs = mapped.get('attributes', {})
        target = source_ref.get('target')
        if attrs.get('source_target') != target:
            raise PipelineError('complete-group ET literal target differs')
        explicit = source_ref.get(XML+'base')
        if explicit:
            if attrs.get('source_base') != member['base'] or explicit != member['base']:
                raise PipelineError('complete-group ET explicit source base differs')
        elif member['declared_member_base'] and _is_relative(target):
            if 'source_base' in attrs:
                raise PipelineError('complete-group ET inherited base duplicated')
            attrs['source_base'] = member['base']
        elif 'source_base' in attrs:
            raise PipelineError('complete-group ET unexpected source base')


def inherit_base_lxml(unit, content: dict, member: dict) -> None:
    """Independently check each literal lxml ref before adding inherited base."""
    native = unit.xpath('.//tei:ref', namespaces={'tei': TEI[1:-1]})
    public = list(_content_refs(content))
    if len(native) != len(public):
        raise ValueError('observed complete-group ref count differs')
    for ordinal, source_ref in enumerate(native):
        attrs = public[ordinal].get('attributes', {})
        target = source_ref.attrib.get('target')
        if attrs.get('source_target') != target:
            raise ValueError('observed complete-group literal target differs')
        explicit = source_ref.attrib.get(XML+'base')
        if explicit is not None:
            if explicit != member['base'] or attrs.get('source_base') != explicit:
                raise ValueError('observed complete-group explicit base differs')
        elif member['declared_member_base'] is not None and _is_relative(target):
            if attrs.get('source_base') is not None:
                raise ValueError('observed inherited base already present')
            attrs['source_base'] = member['base']
        elif 'source_base' in attrs:
            raise ValueError('observed unexpected complete-group base')

