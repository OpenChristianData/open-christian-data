"""Prepare one current source-bound Aquinas four-component handoff, preserving its body."""
from pathlib import Path
from hashlib import sha256
import json
from lxml import etree,html
from ocd_kernel.library._common import io_path
from build.tei import aquinas_four_current_reconstruction as producer
ROOT=Path(__file__).resolve().parents[2]
WORK_ID='aquinas-summa-theologica-four-parts'; FORM_ID=WORK_ID+'-gutenberg-retained-en'; EDITION_ID=WORK_ID+'-gutenberg-electronic'; ACQUISITION_ID=WORK_ID+'-gutenberg-acquired'
WORK=Path('library/works')/WORK_ID; EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID; ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/aquinas-four-current-v3')/WORK_ID; DATA_NOTICE=Path('data/prose')/WORK_ID/'README.md'; LOG=Path('reports/_logs/aquinas-four-current-reconciliation-20261002-v1')
HISTORICAL=Path('reports/clean-ready-acquisition-to-tei/master-1/09')/WORK_ID/'candidate.tei.xml'
SOURCE_SHA='f5a0f8e7e52dcd9e1d6c2a71cfd21eff54b5c2728d3e707313ed280a8d6dd37d'
TITLE='Summa Theologica'; SCOPE='One existing partial English Summa Theologica witness in one TEI: exactly four ordered retained Project Gutenberg components I (Prima Pars), I-II (Prima Secundae), II-II (Secunda Secundae), III (Tertia Pars), all own dedication/electronic edition notes/contents/prologues/questions/articles/editorial insertion/closings. All35,488 source units,512questions and2,669 semantic articles preserved. No traditional Supplement/fifth component, invented pagination, restored print formulae, new component work IDs or print-equivalence claim. Retained Gutenberg wrappers and cover packages are explicit source/support context outside book text; visible complete license/credits remain paired publication deliverables.'
canonical=producer.canonical
NS='{http://www.tei-c.org/ns/1.0}'; XML='{http://www.w3.org/XML/1998/namespace}'
def put(p,b):
    q=io_path(ROOT/p);q.parent.mkdir(parents=True,exist_ok=True)
    if q.exists() and q.read_bytes()!=b:raise FileExistsError('Refuse overwrite: '+str(q))
    q.write_bytes(b)
def binding(name,p,role):
    raw=io_path(ROOT/p).read_bytes();return dict(name=name,path=Path(p).as_posix(),role=role,bytes=len(raw),sha256=sha256(raw).hexdigest())
def main():
    from build.tei import aquinas_four_current_oracle as checker
    raw=io_path(ROOT/HISTORICAL).read_bytes(); old=etree.fromstring(raw); header=old.find(NS+'teiHeader'); desc=header.find(NS+'fileDesc/'+NS+'sourceDesc'); listbibl=desc.find(NS+'listBibl')
    bibliographic=[etree.tostring(n,with_tail=False).decode() for n in listbibl]
    desc.remove(listbibl)
    for bibl in listbibl:desc.append(bibl)
    encoding=header.find(NS+'encodingDesc'); classes=encoding.find(NS+'classDecl'); tax=classes.find(NS+'taxonomy')
    labels=[dict(id=n.get(XML+'id'),label=''.join(n.find(NS+'catDesc').itertext())) for n in tax]
    bibl=etree.SubElement(desc,NS+'bibl'); note=etree.SubElement(bibl,NS+'note',type='reconstruction-analysis'); note.text='Generated reconstruction analysis from the historical source-specific mapper; not authored-source taxonomy. Original IDs and labels retained for body analysis links. '
    listing=etree.SubElement(note,NS+'list'); listing.set(XML+'id',tax.get(XML+'id'))
    for item in labels:
        n=etree.SubElement(listing,NS+'item');n.set(XML+'id',item['id']);n.text=item['label']
    encoding.remove(classes)
    availability=header.find(NS+'fileDesc/'+NS+'publicationStmt/'+NS+'availability');availability.set('status','restricted')
    availability.find(NS+'licence').text='Retained provider USA public-domain statements and Project Gutenberg redistribution/trademark terms are distinct evidence. Technical preparation, including this partial four-component scope, establishes neither independent rights clearance nor public publication authorization.'
    header_bytes=etree.tostring(header,encoding='UTF-8',with_tail=False)
    put(BASE/'historical-header.xml',raw[raw.index(b'<teiHeader>'):raw.index(b'</teiHeader>')+len(b'</teiHeader>')]);put(BASE/'fresh-header.xml',header_bytes)
    fresh=raw[:raw.index(b'<teiHeader>')]+header_bytes+raw[raw.index(b'</teiHeader>')+len(b'</teiHeader>'):]
    put(BASE/'header-renewal-candidate.tei.xml',fresh)
    members=json.loads(io_path(ROOT/EDITION/'source-member-set.json').read_bytes())['members']; components=[];license_blocks=[];credits=[]
    for i,(m,code,pg) in enumerate(zip(members,['prima-pars','prima-secundae','secunda-secundae','tertia-pars'],[17611,17897,18755,19950],strict=True),1):
        source=io_path(ROOT/m['path']).read_bytes();doc=html.fromstring(source);body=doc.xpath('//body')[0]
        if sha256(source).hexdigest()!=m['sha256']:raise ValueError('Primary source member differs')
        units=[n for n in body if isinstance(n.tag,str) and n.tag not in ('header','footer')]
        components.append(dict(position=i,code=code,pg_id=pg,source_path=m['path'],source_sha256=m['sha256'],units=len(units),terminal_source_id=units[-1].get('id'),terminal_text=''.join(units[-1].itertext())))
        credits.append(dict(pg_id=pg,wrapper_header=''.join(body.find('header').itertext()),opening_units=[dict(id=n.get('id'),text=''.join(n.itertext())) for n in units[:15]]))
        license_blocks.append('PG '+str(pg)+' retained provider footer/license:\n\n'+''.join(body.find('footer').itertext()).strip()+'\n')
    notice='# Summa Theologica: four-component source and data credit\n\nThis one retained English witness contains Parts I, I-II, II-II and III. The traditional Supplement is absent; neither the whole traditional five-component Summa nor unchanged print equivalence is claimed. The own title/imprint identifies Thomas Aquinas, translated by the Fathers of the English Dominican Province, Complete American Edition, Benziger Brothers, New York. No unverified print year is inferred.\n\nThe retained electronic material credits Sandra K. Perry. Individual wrapper and own opening credit statements also credit David McClamrock for corrections and supplementation; these primary statements are preserved in the private source profile rather than expanded to an undocumented uniform role across all components. All own electronic notes, source numbering anomalies, omitted question headings, bracketed material, transliterated Greek, italic emphasis, explicit breaks and the Part III editorial insertion remain literal. Generated semantic question/article positions and analysis are reconstruction labels, not corrections of the source wording.\n\nOfficial retained source records: [Part I](https://www.gutenberg.org/ebooks/17611), [Part I-II](https://www.gutenberg.org/ebooks/17897), [Part II-II](https://www.gutenberg.org/ebooks/18755), [Part III](https://www.gutenberg.org/ebooks/19950). The four HTML members are the text sources; ZIP packages and their cover PNGs are retained support context. Header/footer redistribution wrappers remain retained source evidence and are excluded from TEI book text. The complete retained provider footer/license for each component follows.\n\nProject Gutenberg provider statements about public domain in the USA do not establish rights in other countries. The Gutenberg name/trademark, redistribution license, original-format availability conditions and underlying text rights remain distinct. Users outside the USA must check applicable local law; this private preparation grants no independent rights clearance or public publication authorization. Human textual and visual review, print collation and public publication remain separate.\n\n'+ '\n'.join(license_blocks)
    notice=notice.strip('\n')+'\n';put(BASE/'README.source.md',notice.encode());put(DATA_NOTICE,notice.encode())
    questions=[dict(id=WORK_ID+'-'+key,status='unassessed',kind=key,detail=detail) for key,detail in [('human','Historical spot visuals remain dated, no full human acceptance.'),('print','Four electronic components only; traditional Supplement absent; no unchanged print equivalence.'),('rights','Retained jurisdiction/provider license is not independent clearance.'),('publication','No public publication authorization/action.')]]
    profile=dict(work_id=WORK_ID,scope=SCOPE,components=components,credits=credits,questions=questions,historical_candidate_sha256=sha256(raw).hexdigest(),historical_text_bytes_sha256=sha256(raw.split(b'</teiHeader>',1)[1]).hexdigest(),fresh_header_sha256=sha256(header_bytes).hexdigest(),member_set_sha256=sha256(io_path(ROOT/EDITION/'source-member-set.json').read_bytes()).hexdigest(),bibliographic_payloads=bibliographic,taxonomy_labels=labels,taxonomy_id=tax.get(XML+'id'),header_changes=['Flatten historical listBibl to four same ordered bibl payloads/IDs','Relocate generated classDecl/taxonomy to reconstruction-analysis note/list/item preserving IDs and labels/body ana targets','Qualify availability as technical restricted preparation, preserving provider terms separately'],prior_exposure='Existing source-specific producer and historical accounting reviewed; fresh independent checker reads source literals and original handoff tree without importing producer; root independent source review required before installation.')
    put(BASE/'profile.json',canonical(profile));put(BASE/'validation-policy.json',canonical(dict(scope=SCOPE,rules=['Exact full retained HTML ledger including header/footer context and ordered attributes','Literal selected unit text/all inline payloads/tails/order/IDs checked without producer import','Whole historical text-tree and bytes conserved; explicit generated semantic hierarchy reviewed separately','Source-backed header relocation and complete own provider notices','Current P5, deterministic fresh process package replay and meaningful mutations'],source_top_tail_disposition='HTML layout newline framing retained in full source ledger; all readable unit and inline text/tails conserved.')))
    authorities=[('profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('source-readme',BASE/'README.source.md','source-attribution'),('fresh-header',BASE/'fresh-header.xml','explicit-generated-header-renewal'),('historical-candidate',HISTORICAL,'retained-whole-native-handoff'),('historical-accounting',HISTORICAL.with_name('accounting.json'),'historical-semantic-accounting'),('primary-source',EDITION/'source-member-set.json','exact-retained-member-set'),('canonical-acquisition',ACQUISITION,'retained-source-identity'),('legacy-mapper','build/tei/aquinas_summa_theologica_four_parts.py','unchanged-source-specific-mapper'),('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema')]
    for component in components:
        authorities.append(('source-html-'+str(component['position']),Path(component['source_path']),'primary-source'))
        authorities.append(('source-archive-'+str(component['position']),Path(component['source_path']).parents[2]/('pg'+str(component['pg_id'])+'-h.zip'),'retained-acquisition-package'))
    authorities.append(('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'))
    record=dict(contract='ocd-source-manifest-v1',source_id='aquinas-four-current-v2',work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*entry) for entry in authorities],converter=dict(id=producer.CONVERTER_ID,version='1',callable='_convert',implementation_path='build/tei/aquinas_four_current_reconstruction.py',implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version='1',callable='_oracle',implementation_path='build/tei/aquinas_four_current_oracle.py',implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()))
    put(BASE/'source-manifest.json',canonical(record));put(LOG/'header-renewal.json',canonical(dict(status='prepared',historical_sha256=sha256(raw).hexdigest(),fresh_candidate_sha256=sha256(fresh).hexdigest(),body_bytes_exact=True,profile_sha256=sha256(canonical(profile)).hexdigest(),changes=profile['header_changes'])))
    print(json.dumps(dict(status='prepared',source_units=35488,components=4,header_only=True,candidate_sha256=sha256(fresh).hexdigest())))
if __name__=='__main__':main()
