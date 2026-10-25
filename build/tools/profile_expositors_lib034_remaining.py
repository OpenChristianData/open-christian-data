"""Read-only source-shape inventory for the eight unaccepted LIB-034 members."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.expositors_bible_lib034_readable_pair import TAGS

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / 'sources/commentaries/expositors-bible/lib034.reconstruction-profile.json'


def main() -> None:
    profile = json.loads(PROFILE.read_text(encoding='utf-8'))
    results = []
    for member in profile['included_members']:
        if member['member_id'] in {'burton-expositorluke', 'gibson-expositormatt'}:
            continue
        name = member['source_url'].split('/ccel/', 1)[1].replace('/', '_').replace('.html', '.xml')
        path = ROOT / 'raw/ccel/expositors-bible' / name
        raw = path.read_bytes()
        source = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
        body = source.find('ThML.body')
        if body is None:
            raise ValueError(f"{member['member_id']} lacks ThML.body")
        tags = Counter(node.tag for node in body.iter() if isinstance(node.tag, str))
        roots = [(node.tag, node.get('id')) for node in body if isinstance(node.tag, str)]
        result = dict(member=member['member_id'], work=member['work_id'], path=path.relative_to(ROOT).as_posix(),
                      sha_ok=sha256(raw).hexdigest() == member['sha256'], size_ok=len(raw) == member['bytes'],
                      unsupported={tag: count for tag, count in tags.items() if tag not in TAGS and tag != 'ThML.body'},
                      root_count=len(roots), first_roots=roots[:3], last_roots=roots[-3:],
                      comments=sum(node.tag is etree.Comment for node in body.iter()),
                      links=sum(node.tag == 'a' for node in body.iter() if isinstance(node.tag, str)))
        results.append(result)
    print(json.dumps(results, sort_keys=True))


if __name__ == '__main__':
    main()
