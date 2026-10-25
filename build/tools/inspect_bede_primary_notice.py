"""Inspect retained PG38326 credits/license without editing authority or public data."""
from pathlib import Path
import json
from hashlib import sha256
from lxml import html
from ocd_kernel.library._common import io_path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/_logs/bede-pg38326-downstream-preflight-20261001'
def main():
    p=ROOT/'raw/gutenberg/38326/html/pg38326-images.html';b=io_path(p).read_bytes();d=html.fromstring(b.decode('utf-8'))
    header=d.xpath('//*[@id="pg-header"]');footer=d.xpath('//*[@id="pg-footer"]')
    if not footer:
        footer=d.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," pg-boilerplate ")]')
    candidates=[n for n in d.iter() if 'THE FULL PROJECT GUTENBERG LICENSE' in (n.text or '')]
    print(json.dumps(dict(header_nodes=[dict(tag=n.tag,attrs=dict(n.attrib)) for n in header],footer_nodes=[dict(tag=n.tag,attrs=dict(n.attrib)) for n in footer],license_candidates=[dict(tag=n.tag,attrs=dict(n.attrib),parent_tag=n.getparent().tag,parent_attrs=dict(n.getparent().attrib)) for n in candidates])))
    for name,nodes in [('provider-header',header),('provider-footer',footer)]:
        if nodes:io_path(OUT/(name+'.txt')).write_text('\n\n'.join(''.join(n.itertext()) for n in nodes),encoding='utf-8')
    license_nodes=d.xpath('//*[@id="project-gutenberg-license"]')
    for n in license_nodes:print(json.dumps(dict(license_tag=n.tag,license_parent=n.getparent().tag,parent_attributes=dict(n.getparent().attrib),replacement_characters=''.join(n.getparent().itertext()).count(chr(65533)))))
    source=' '.join(' '.join(''.join(n.itertext()).split()) for n in header+footer)
    start=source.find('FULL PROJECT GUTENBERG')
    print(source[:1800]);print(source[start:start+2600])
if __name__=='__main__':main()
