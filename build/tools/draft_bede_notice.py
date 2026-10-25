"""Prepare own source credit and literal retained PG footer as a reviewable notice."""
from pathlib import Path
from hashlib import sha256
import json
from lxml import html
from ocd_kernel.library._common import io_path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/_logs/bede-pg38326-downstream-preflight-20261001'
def main():
    b=io_path(ROOT/'raw/gutenberg/38326/html/pg38326-images.html').read_bytes();d=html.fromstring(b.decode('utf-8'))
    footer=d.xpath('//*[@id="pg-footer"]')
    if len(footer)!=1:raise ValueError('Not one exact retained PG footer')
    literal=''.join(footer[0].itertext()).replace('\r','').strip()+'\n'
    notice="""# Bede's Ecclesiastical History of England: source and data credit

This edition uses the complete retained [Project Gutenberg eBook 38326](https://www.gutenberg.org/ebooks/38326) literary witness. Its title page states: A Revised Translation With Introduction, Life, and Notes By A. M. Sellar; London: George Bell and Sons, 1907. The electronic header names Bede as author and A. M. Sellar as translator and gives release date December 17, 2011. These are retained electronic source statements, not newly verified print collation or independent publication-date research.

The accepted literary master retains the title page, contents, editor's preface, introduction, Life of Bede, errata, Bede's preface, Books I–V, Continuation, index and all 1,081 footnotes. Footnote 1056 attributes the Continuation to a later hand while discussing uncertainty concerning some early entries; this release does not resolve that attribution. The source cover is retained support material without a body-image occurrence. No new source reconstruction, print collation or human acceptance is claimed.

The electronic source states that the text is in the public domain and qualifies this as public domain in the USA. Its Project Gutenberg provider header and footer are outside the accepted literary text. The complete retained footer and license are reproduced below as human-visible source rights evidence. Territorial law, distribution and trademark requirements remain qualified source statements; independent rights clearance and public publication remain separate. This is a private offline preparation.

## Retained Project Gutenberg footer and license

"""+literal
    data=notice.encode('utf-8')
    if len(data)>65536 or '<' in notice or '>' in notice:raise ValueError('Maintained notice size/HTML boundary differs')
    io_path(OUT/'draft-data-README.md').write_bytes(data)
    source="""# Bede PG38326 source and data attribution

This existing accepted work uses the complete retained Project Gutenberg eBook38326 literary text: Bede's Ecclesiastical History of England, revised translation with introduction, life and notes by A. M. Sellar, with retained London: George Bell and Sons,1907 title-page imprint and electronic release December17,2011. Preserve the complete literary envelope, five books, Continuation, index and1081footnotes. The Continuation's later-hand attribution and uncertain early entries remain qualified as in source note1056.

The provider's public-domain-in-USA statement and complete retained Project Gutenberg footer/license are source rights evidence, not independent clearance. Provider wrapper exclusion from the literary master does not exclude its rights statements from human-visible data attribution. Carry the own credit, territorial qualifications and retained full footer to `data/prose/bede-ecclesiastical-history-of-england/README.md`. No new reconstruction, independent print verification or public publication is implied.
""".encode()
    io_path(OUT/'draft-source-README.md').write_bytes(source)
    result=dict(status='drafted',source_sha256=sha256(b).hexdigest(),footer_parsed_text_sha256=sha256(literal.encode()).hexdigest(),footer_parsed_bytes=len(literal.encode()),draft_notice_sha256=sha256(data).hexdigest(),draft_notice_bytes=len(data),full_footer_carried=True,canonical_authority_changed=False)
    io_path(OUT/'draft-notice-evidence.json').write_text(json.dumps(result,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main()
