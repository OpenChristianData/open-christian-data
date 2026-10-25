"""Prepare own retained-source credits and immutable downstream preflight for Watson."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.library._common import io_path, io_glob

ROOT=Path(__file__).resolve().parents[2]
WORK='watson-ten-commandments';BASE=ROOT/'library/works'/WORK;PUB=BASE/'publication'
PRE=ROOT/'reports/_logs/watson-ten-commandments-downstream-preflight-20261002-v1'
SOURCE_NOTE='sources/private-watson-ten-commandments/watson-ten-commandments/README.source.md'
DATA_NOTE='data/prose/watson-ten-commandments/README.md'
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def save(p,v):
    q=io_path(p);q.parent.mkdir(parents=True,exist_ok=True);q.write_text(json.dumps(v,ensure_ascii=True,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
def main():
    if PUB.exists() or PRE.exists():raise FileExistsError('Fresh Watson preflight; existing publication must be reconciled')
    accepted=list(io_glob(BASE,'**/acceptance.json'))
    if len(accepted)!=1:raise ValueError('Exactly one assigned accepted Watson edition required')
    path=accepted[0];a=json.loads(io_path(path).read_bytes());source=ROOT/a['source']['source_path'];master=ROOT/a['promotion']['master']['path']
    if a['identity']['work_id']!=WORK or digest(source)!='88f65cbe3a515841a14ecd7c982880b528a32c4420ac71169485ef54ccdb89d6' or digest(master)!='3dff41b0c8491bff320763ed578e80cdfa29145252381dbaa0c58aa044035dd7':raise ValueError('Assigned accepted/source identity differs')
    bindings=[a['promotion']['master'],a['technical']['candidate'],a['source']['source_manifest'],a['source']['accounting'],*[a['technical'][k] for k in ['validation','schema','accounting','fidelity','closure','reproducibility']],a['review']['report']]
    for b in bindings:
        p=io_path(ROOT/b['path'])
        if digest(p)!=b['sha256'] or p.stat().st_size!=b['bytes']:raise ValueError('Accepted bound historical evidence differs: '+b['path'])
    tree=etree.fromstring(io_path(source).read_bytes());head=tree.find('ThML.head');body=tree.find('ThML.body');description=''.join(head.find('generalInfo/description').itertext())
    if 'Kathleen O\u2019Bannon' not in description or '\ufffd' in description:raise ValueError('Literal Unicode primary description credit differs')
    roots=[n for n in body if isinstance(n.tag,str)];comments=[n for n in body if not isinstance(n.tag,str)];ids=[n.get('id') for n in roots]
    if ids!=['i','iii','iv','v','vi','vii'] or len(comments)!=2:raise ValueError('Whole source envelope differs')
    ns={'t':'http://www.tei-c.org/ns/1.0'};tei=etree.fromstring(io_path(master).read_bytes());parts=tei.find('t:text',ns)
    actual=[dict(part=etree.QName(p).localname,roots=[dict(id=n.get('{http://www.w3.org/XML/1998/namespace}id'),head=''.join(n.find('t:head',ns).itertext())) for n in p if isinstance(n.tag,str)]) for p in parts]
    if [len(p['roots']) for p in actual]!=[1,4,1]:raise ValueError('Accepted whole front/body/back placement differs')
    title=''.join(roots[0].itertext());published=head.findtext('printSourceInfo/published');created=head.findtext("electronicEdInfo/DC/DC.Date[@sub='Created']");rights=head.findtext('electronicEdInfo/DC/DC.Rights')
    if published!='1692' or created!='2000-07-09' or rights!='Public Domain':raise ValueError('Own primary metadata differs')
    authority={p.relative_to(ROOT).as_posix():digest(p) for p in io_glob(BASE,'**/*') if io_path(p).is_file()}
    authority[a['source']['source_path']]=digest(source)
    save(PRE/'primary-credit-evidence.json',dict(source_sha256=digest(source),header_xml=etree.tostring(head,encoding='unicode'),description_literal=description,titlepage_literal=title,print_date_source_claim=published,electronic_created=created,provider_rights_literal=rights,scope_roots=[dict(id=n.get('id'),title=n.get('title'),elements=sum(isinstance(d.tag,str) for d in n.iter())) for n in roots],comment_count=2,source_comments=[dict(text=n.text,tail=n.tail) for n in comments],accepted_parts=actual,qualification='Retained six-root source envelope and accepted placement inspected; existing full source-accounting/fidelity/replay and two-locus visual evidence reused as dated receipts. No fresh source reconstruction or exhaustive visual review.'))
    prior_dirs=[p.as_posix() for p in io_glob(ROOT/'reports/_logs','*watson*')]
    save(PRE/'prior-completion-search.json',dict(canonical_publication_present=False,work_named_report_homes=prior_dirs,matching_accessible_varied_completion_receipts=[],limitation='Whole reports completion/final-delivery search returned no Watson match, with access errors on unrelated release subtrees; no global absence asserted. Canonical work has no publication folder and root downstream queue assigned this accepted work.'))
    note='''# The Ten Commandments: source credit and use notice

Sourced via CCEL.org from its retained Thomas Watson, **The Ten Commandments**, ThML electronic publication. Thomas Watson is the author named in the retained title page and Dublin Core. **Kathleen O’Bannon, CCEL Staff**, is credited for the source description only; no main-text transcription, editing or translation role is inferred for her.

The source title page literally says “First published as part at A Body of Practical Divinity, 1692.” Its printSourceInfo published field also says 1692. These are source statements about the work’s printed context, not independently established identity of the transcribed print exemplar. Electronic creation **2000-07-09** is separate. The electronic publisher is **Grand Rapids, MI: Christian Classics Ethereal Library**. Source version, series, transcription lineage and print-imprint fields are blank or unspecified; no additional edition, print publisher, editor or transcriber is supplied.

The complete retained work stays together: title page; Introduction; The Ten Commandments; The Law and Sin; The Way of Salvation; and indexes, in that order. The accepted TEI places the title in front matter, the four content divisions in the body and the indexes in back matter. Its four body roots do not mean that title or index text was dropped. Existing source-shell/comment accounting and dated partial visual evidence remain qualified; no new print collation or exhaustive proofreading is claimed.

The retained provider rights field says **Public Domain**. This is provider metadata, not independent clearance for every edition, formatting layer or jurisdiction. The maintained CCEL permission record reports that parsing ThML/XML for text is permitted and that CCEL’s copyright applies to its files and formatting rather than underlying public-domain text. **Do not sell CCEL files or derivatives of their formatting.** Attribution is appreciated; retain “sourced via CCEL.org” in the dataset README/card.

Technical acceptance and private offline verification do not establish human acceptance, print equivalence, independent rights clearance or authorization for public publication.

For data at `data/prose/watson-ten-commandments`, maintain this complete source credit and use notice in `data/prose/watson-ten-commandments/README.md` and in any release README containing these rows.
'''
    for name in [SOURCE_NOTE,DATA_NOTE]:
        p=io_path(ROOT/name);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(note,encoding='utf-8',newline='\n')
    # Actual stable inputs, not a mutable explanatory receipt.
    previous=json.loads((ROOT/'library/works/boethius-theological-tractates/publication/runtime-freeze.json').read_bytes())
    modules=[p for p in previous if not p.endswith('categories/sermons.schema.json')]
    modules+=['ocd_kernel/projection/envelope.py','ocd_kernel/release/assemble.py','ocd_kernel/release/selection.py','ocd_kernel/library/identities.py','ocd_kernel/tei/acceptance.py','schemas/v2/categories/prose.schema.json']
    runtime={p:digest(ROOT/p) for p in modules}
    expected={'ocd_kernel/projection/source_projection_evidence.py':'d749eb107efc8e762642a05dc35c7ebcd7789b37459851f74d9faf14c7c1c013','schemas/v2/native-content.schema.json':'8e6cb79b79c2c72e1b896404fa6ed7f1d1c49e6043cf01b0de50a6883391c30a','ocd_kernel/reconstruction/contract.py':'ee9fe78b88bfe68c04223a4273918e065b9bc2f5abbd002405eb7ae063c08ce9'}
    if any(runtime[p]!=h for p,h in expected.items()):raise ValueError('Assigned shared runtime differs')
    PUB.mkdir(parents=True);save(PUB/'runtime-freeze.json',runtime)
    item=dict(item_id=WORK,category='prose',acceptance_path=path.relative_to(ROOT).as_posix(),public_notices=[dict(source_path=SOURCE_NOTE,source_sha256=digest(ROOT/SOURCE_NOTE),notice_path=DATA_NOTE,notice_sha256=digest(ROOT/DATA_NOTE))])
    save(PUB/'selection-draft.json',dict(schema_version='2.0',release_id='watson-ten-commandments-private-offline-20261002-v1',items=[item]))
    if any(digest(ROOT/p)!=h for p,h in authority.items()):raise ValueError('Accepted source/authority changed during preparation')
    save(PRE/'preflight.json',dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK,authority_bindings=authority,runtime_bindings=runtime,accepted_master_sha256=digest(master),source_sha256=digest(source),acceptance_sha256=digest(path),accepted_historical_bindings_reused=len(bindings),primary_evidence_sha256=digest(PRE/'primary-credit-evidence.json'),reconstruction_performed=False,authority_unchanged=True))
    print(json.dumps(dict(status='pass',authority_bindings=len(authority),runtime_bindings=len(runtime),master_sha256=digest(master))))
if __name__=='__main__':main()
