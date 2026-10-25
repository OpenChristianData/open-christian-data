"""Bind renewed whole Murray collection proof, unchanged historical TEI and source credits."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json
from build.tei import murray_absolute_surrender_current_reconstruction as producer,murray_absolute_surrender_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
ROOT=Path(__file__).resolve().parents[2]
WORK_ID='murray-absolute-surrender'
FORM_ID=WORK_ID+'-english'
EDITION_ID=WORK_ID+'-retained-electronic-witness'
ACQUISITION_ID=WORK_ID+'-retained-source'
WORK=Path('library/works')/WORK_ID
EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/ccel-murray-surrender-current')/WORK_ID
DATA_NOTICE=Path('data/prose')/WORK_ID/'README.md'
SOURCE=Path('raw/ccel/murray/surrender.xml')
SOURCE_SHA='3b8a474258f452b6d43ce14735c2594da52cd583a0271e8a650969aad97aff7d'
TITLE='Absolute Surrender'
SCOPE='Complete retained CCEL Absolute Surrender and Other Addresses electronic collection, one existing work identity and one TEI: own title page i; all nine ordered addresses ii through x, including subtitle An Address to Christian Workers in x; integral scripture-reference index xi. All954source elements/body890, four native verse groups/twelve lines,167italic carriers,69scripRef labels/sourceosisRef and69hyperlinks, all mixed text/tails/attributes/hierarchy and source-projection crosswalk retained. Electronic header/CSS/support metadata and DOCTYPE/two comments accounted explicitly in complete private source-accountability, not silently treated as book text. This is the retained lightly language-edited and scripture-added CCEL witness, not an assertion of unchanged1895 print equivalence. MoodyPressChicago1895 own title and First published in1895 literal statement preserved; inherited config MarshallBrothersLondon claim qualified as conflicting historical support only. No new address work IDs, translation inference, source correction or media acquisition. Source scripture classification/cRef preserves source-carrier labels, not verified Biblical identification or parsed-reference correctness.'
canonical=producer.canonical

def put(p,b):
    target=io_path(ROOT/p);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
def binding(name,p,role):
    b=io_path(ROOT/p).read_bytes();return dict(name=name,path=Path(p).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())

def main():
    source=io_path(ROOT/SOURCE).read_bytes();acq=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if sha256(source).hexdigest()!=SOURCE_SHA or acq['retained_files'][0]['sha256']!=SOURCE_SHA:raise ValueError('source/acquisition differs')
    sr=checker.prior._parse_retained_xml(source);credits=[]
    for name,role,selector in [('Andrew Murray','own title author',"//*[@id='i-p0.4']"),('Claude King','electronic transcriber','/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor[@sub="Transcriber"]'),('Claude King','own scanned and corrected attestation',"//*[@id='i-p3']"),('Moody Press - Chicago','literal own imprint',"//*[@id='i-p1.1']"),('1895','literal own title date, no print-equivalence claim',"//*[@id='i-p1.2']"),('Christian Classics Ethereal Library','electronic publisher','/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher'),('CCEL editorial note','source-attested light language edits and added scripture references','/ThML/ThML.head/electronicEdInfo/editorialComments')]:
        n=sr.xpath(selector)
        if len(n)!=1:raise ValueError('nonunique credit '+selector)
        credits.append(dict(name=name,role=role,source_selector=selector,literal_text=''.join(n[0].itertext())))
    questions=[dict(id=WORK_ID+'-'+k,status='unassessed',kind=k,detail=v) for k,v in [('human','No current human textual acceptance; dated exact-pair CVW evidence remains historical.'),('print','Retained witness explicitly lightly edited; no exact print collation/equivalence.'),('rights','Provider PublicDomain statements and permission evidence are not independent jurisdictional rights clearance.'),('publication','No public publication authorization/action.')]]
    profile=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,credits=credits,questions=questions,historical_tei_sha256='ab481d00926b0fa9e4d57084f1541b0c5e207e037b7ec41ba80621ad6b5aec10',historical_accountability_sha256='e302e47fc61630a573714a73bd67b2277ade0d93e6b14d8ce1ac061936fe4621',historical_config_claim_disposition='Retained config unchanged; Marshall Brothers London1895 is conflicting historical claim, not accepted factual source title/imprint.')
    put(BASE/'profile.json',canonical(profile));put(BASE/'validation-policy.json',canonical(dict(scope=SCOPE,rules=['exact historically source-proven full TEI byte replay','independent complete954source-accountability reconstruction','full topology and exacttext/tails/attributes/reference/verse mapping','primary credits; current P5; meaningful mutations; fresh process replay'],historical_source_specific_mapping_reused=True,body_changes_permitted=False,source_header_disposition='All detailed source-header metadata/CSS retained in private954carrier source-accountability; selected primary literal author/transcriber/print/editorial/provider/rights/language mapped in TEI header. Source description only credits TimPerrine as staffwriter.')))
    notice="""# Absolute Surrender: source and data credit

Sourced via [CCEL.org](https://www.ccel.org/ccel/murray/surrender.html). The retained own title names Andrew Murray and reads Absolute Surrender and Other Addresses. This private preparation keeps the complete collection in one existing work: own title page, nine addresses, and integral scripture index. Each address remains independently locatable within the same TEI; no new work IDs are created.

The own title literally names Moody Press - Chicago and1895. The electronic printSourceInfo says First published in1895. This edition, Chicago: Moody Press. The retained electronic edition explicitly says the book has been lightly edited to update language and add scripture references. These statements do not establish unchanged equivalence to an1895 print witness. A inherited config assertion Marshall Brothers, London,1895 is retained as conflicting historical evidence and is not adopted as factual source credit. The current canonical short title Absolute Surrender remains unchanged.

Claude King is the electronic transcriber; the own titlepage says Scanned and corrected by Claude King, September1999. Electronic creation is1999-09-29. Christian Classics Ethereal Library is the electronic publisher. Tim Perrine is credited only for the CCEL Staff Writer description. No translator or unnamed editor is inferred.

The provider DC.Rights says Public Domain and the own titlepage calls the text public domain. These are retained provider statements, not independent jurisdictional rights clearance. CCEL permission allows parsing ThML/XML for text, reserves its files/formatting rights, prohibits selling CCEL files or derivatives of their formatting, and requests publication credit. Do not sell CCEL files or derivatives of their formatting. This private preparation carries visible source credit; technical acceptance does not authorize public publication.

All954 source carriers and their exact ordered attributes, text/tails, parent/ordinal relationships, header/CSS/support metadata and non-element events are retained in source-accountability evidence. The original native TEI is reproduced unchanged, including four verse groups/twelve lines and all scripture references/hyperlinks. Source scripture classification and cRef do not constitute independently verified biblical identification or parsed-reference correctness. Historical visual screenshots remain dated exact-pair evidence; no current visual or print-collation claim is made.

"""+SCOPE+'\n\nHuman textual/visual verification, print equivalence, rights clearance, final global selection and public publication remain separate.\n'
    notice=notice.replace('and1895','and 1895').replace('in1895','in 1895').replace('an1895','an 1895').replace('London,1895','London, 1895').replace('September1999','September 1999').replace('is1999','is 1999').replace('All954','All 954')
    put(BASE/'README.source.md',notice.encode());put(DATA_NOTICE,notice.encode())
    authority=[('primary-source',SOURCE,'primary-source'),('profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('source-readme',BASE/'README.source.md','source-attribution'),('canonical-acquisition',ACQUISITION,'retained-source-identity'),('historical-profile','sources/structured-text/murray-absolute-surrender/murray-absolute-surrender.reconstruction-profile.json','historical-mapping-contract'),('historical-config','sources/structured-text/murray-absolute-surrender/config.json','conflicting-historical-metadata-not-adopted'),('legacy-mapper','build/tei/murray_absolute_surrender_reconstruction.py','unchanged-source-specific-mapping'),('legacy-checker','build/tei/murray_absolute_surrender_oracle.py','unchanged-independent-source-specific-expectation'),('ccel-permission','docs/sources/ccel-permission.md','source-permission-evidence'),('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema')]
    record=dict(contract='ocd-source-manifest-v1',source_id='ccel-murray-complete-current-v1',work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authority],converter=dict(id=producer.CONVERTER_ID,version='1',callable='_convert',implementation_path='build/tei/murray_absolute_surrender_current_reconstruction.py',implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version='1',callable='_oracle',implementation_path='build/tei/murray_absolute_surrender_current_oracle.py',implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()))
    put(BASE/'source-manifest.json',canonical(record));print(json.dumps(dict(status='prepared',source_elements=954,body_elements=890,body_roots=11,address_count=9,historical_tei_reuse=True)))
if __name__=='__main__':main()
