"""Verify the exact installed complete Matthew collection through normal APIs."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_matthew_collection import ROOT,WORK,WORK_ID,EDITION,ACQUISITION,BASE,SOURCE,SOURCE_SHA,SCOPE,TITLE,canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import project_accepted_prose,verify_accepted_prose
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader

def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(canonical(v))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--installation',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    installation=json.loads(a.installation.read_bytes());acceptance=ROOT/EDITION/'acceptance.json'
    before={ (WORK/relative).as_posix():h for relative,h in installation['installed_files'].items() }
    for path,h in before.items():
        if digest(ROOT/path)!=h:raise ValueError('Installed generation differs: '+path)
    if digest(ROOT/SOURCE)!=SOURCE_SHA:raise ValueError('Retained source differs')
    before[SOURCE.as_posix()]=SOURCE_SHA
    source_notice_path=Path('sources/structured-text')/WORK_ID/'README.source.md'
    notice_path=Path('data/structured-text')/WORK_ID/'README.md'
    source_notice=(ROOT/BASE/'README.source.md').read_bytes()
    notice=('# Homilies on the Gospel of Matthew: source and data credits\n\n'
            'Sourced via [CCEL.org](https://www.ccel.org/ccel/schaff/npnf110.html), Nicene and Post-Nicene Fathers, Series 1, volume 10. '
            'The retained work title page credits George Prevost as translator and M. B. Riddle for revision with notes; the Introductory Essay explicitly names M. B. Riddle as its author. '
            'Philip Schaff is the volume editor. The retained electronic print-source header states New York: Christian Literature Publishing Co., 1886; source title-page statements remain literal in the complete body.\n\n'
            +SCOPE+'\n\nThe retained electronic header states Public Domain. Retained CCEL permission permits parsing ThML/XML for text; do not sell CCEL files or derivatives of CCEL formatting. '
            'These provider statements do not establish independent rights clearance. OCD reused the independently checked complete historical body, bound a supported TEI header, and projected the exact installed master through the generic native route. '
            'Human textual acceptance, fresh visual comparison, print equivalence, final rights disposition, global selection and public publication remain separate.\n').encode()
    for relative,payload in ((source_notice_path,source_notice),(notice_path,notice)):
        path=ROOT/relative
        if path.exists() and path.read_bytes()!=payload:raise ValueError('Existing notice differs: '+str(relative))
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
        before[relative.as_posix()]=digest(path)
    pub=ROOT/WORK/'publication/private-offline-20261001'
    if (pub/'completion.json').exists():raise FileExistsError('Completed release already exists')
    selection=dict(schema_version='2.0',release_id='matthew-collection-private-offline-20261001-v1',items=[dict(item_id=WORK_ID,category='prose',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=[dict(source_path=source_notice_path.as_posix(),source_sha256=sha256(source_notice).hexdigest(),notice_path=notice_path.as_posix(),notice_sha256=sha256(notice).hexdigest())])])
    save(pub/'selection.json',selection);save(a.output/'selection.json',selection)
    notice_texts_for_item(ROOT,selection['items'][0],acceptance)
    schemas=['schemas/v2/native-content.schema.json','schemas/v2/categories/prose.schema.json','schemas/v2/public-row.schema.json','ocd_kernel/tei/vendor/xsd/tei_all.xsd']
    implementations=['ocd_kernel/projection/categories/native_documents.py','ocd_kernel/release/assemble.py','ocd_kernel/release/verify.py']
    frozen={path:digest(ROOT/path) for path in schemas+implementations}
    if frozen['schemas/v2/native-content.schema.json']!='5e1e050416ac3a04affb03cf5cfd5afd9ada078f1a3abab51716bb845e757e38':raise ValueError('Expected final frozen schema differs')
    save(a.output/'authority-before.json',before)
    out=a.output/'release'
    with cached_edition_lookups():
        projected=project_accepted_prose(ROOT,acceptance_path=acceptance)
        errors=verify_accepted_prose(ROOT,acceptance_path=acceptance,rows=projected['rows'],receipt=projected['receipt'])
        if errors or len(projected['rows'])!=1:raise ValueError({'projection_errors':errors,'rows':len(projected['rows'])})
        save(a.output/'actual-master-projection.json',projected)
        print('actual installed master: pass, one complete prose row',flush=True)
        assembly=assemble_release_v2(ROOT,out,selection=selection);save(a.output/'assembly.json',assembly)
        if assembly['status']!='pass':raise ValueError(assembly)
        for name,action in [('independent-verification',lambda:verify_release_v2(ROOT,out,selection=selection)),('statistics',lambda:release_statistics(ROOT,out,selection)),('readers',lambda:check_reader(ROOT,out,selection))]:
            result=action();save(a.output/(name+'.json'),result)
            if result['status']!='pass':raise ValueError(result)
            print(name+': pass',flush=True)
    if any(digest(ROOT/path)!=h for path,h in before.items()) or any(digest(ROOT/path)!=h for path,h in frozen.items()):raise ValueError('Final authority/schema/implementation drift')
    result=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK_ID,master_sha256=digest(ROOT/EDITION/'master.tei.xml'),acceptance_sha256=digest(acceptance),source_sha256=SOURCE_SHA,acquisition_sha256=digest(ROOT/ACQUISITION),projection_rows=1,release_statistics=json.loads((a.output/'statistics.json').read_bytes()),release_path=out.as_posix(),selection_sha256=sha256(canonical(selection)).hexdigest(),notice_sha256=sha256(notice).hexdigest(),private_offline=True,publication_performed=False,bound_schema_stability=dict(status='pass',before={p:frozen[p] for p in schemas},after={p:digest(ROOT/p) for p in schemas}),bound_implementation_stability=dict(status='pass',before={p:frozen[p] for p in implementations},after={p:digest(ROOT/p) for p in implementations}),authority_files_checked=len(before),all_authority_hashes_unchanged=True,limits=['Human acceptance not recorded','Fresh full visual comparison not performed; historical sample remains dated','Print completeness/equivalence not established','Independent rights clearance unresolved','Global selection and publication not authorized'])
    save(a.output/'completion.json',result);save(pub/'completion.json',result)
    (pub/'README.md').write_text('# Complete Matthew homily collection\n\nThe complete retained source-defined book, including its title page, Oxford preface, introductory essay and all 86 present homily divisions, is technically accepted and guarded-installed. Exact replay, twelve semantic mutations and isolated rollback pass; the coordinator independently compared all 15,971 original source elements. Its actual installed master passes generic projection, private offline assembly and independent verification, statistics, and normal/streaming readers. Source-native numbering jumps remain without correction or filling.\n\nSee completion.json and selection.json; private evidence: '+a.output.as_posix()+'. Source/data attribution is visible in the selected release. Exact source/acquisition, title/language/IDs/locator and the final schema freeze were conserved; category-only prose prerequisite is separately pinned. Human/print review, rights clearance, global selection and publication remain separate.\n',encoding='utf-8')
    print(json.dumps(dict(status='pass',rows=1,text_characters=result['release_statistics']['total']['text_characters'],evidence=a.output.as_posix())))
if __name__=='__main__':main()
