"""Joshua's one complete authored work and qualified existing LIB036 replay."""
from pathlib import Path
import hashlib,json,base64
from lxml import etree

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/blaikie-joshua-existing-install-20261003-v1')
OLD_PACKAGE=LOG/'qualified-current-lib036-replay'
WORK_ID='expositors-bible--william-g-blaikie'
NS='{http://www.tei-c.org/ns/1.0}'
XML_ID='{http://www.w3.org/XML/1998/namespace}id'
MEMBERS={'blaikie-expositorjosh':{'volume': 1, 'path': 'raw/ccel/expositors-bible/blaikie_expositorjosh.xml', 'sha256': '7a2be4c01ca4ed8ecf37aa6905a161c126ac8cc4752e00448126ae363d2139b3', 'bytes': 823168, 'elements': 2352, 'body_elements': 2286, 'body_comments': 22, 'tbody_wrappers': 0, 'colgroup_wrappers': 0, 'native_source_elements': 2285, 'front': ['i'], 'back': ['xxxv'], 'source_base_url': 'https://www.ccel.org/ccel/blaikie/expositorjosh.html'}
}
for member,spec in MEMBERS.items():spec.update(form=WORK_ID+'--'+member+'--retained-en',edition=WORK_ID+'--'+member+'--ccel-electronic',acquisition=WORK_ID+'--'+member+'--acquired')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def parse(raw):return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,remove_comments=False,huge_tree=True))
def correction_rows(member):
 profile=json.loads((ROOT/'sources/commentaries/expositors-bible/lib036.reconstruction-profile.json').read_bytes())
 return [r for r in profile['text_corrections'] if r['member_id']==member]
def retained(member):
 spec=MEMBERS[member];raw=(ROOT/spec['path']).read_bytes()
 if len(raw)!=spec['bytes'] or sha(raw)!=spec['sha256']:raise ValueError('Joshua acquired witness drifted')
 return raw
