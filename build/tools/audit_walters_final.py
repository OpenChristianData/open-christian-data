"""Read-only exact binding audit of Walters private preparation."""
from pathlib import Path
from datetime import datetime,timezone
import json
from build.tools.complete_walters_private_release import ROOT,PUB,OUT,PRE,digest,read,save,MASTER

def main():
    c=read(ROOT/PUB/'completion.json');checked={}
    if c['status']!='pass' or c['accepted_master_sha256']!=MASTER or c['projection_document_sha256']!=MASTER:raise ValueError('Actual accepted master linkage differs')
    for name,base in [('authority_bindings',ROOT),('schema_implementation_bindings',ROOT),('release_file_bindings',Path(c['release_path'])),('release_evidence_bindings',OUT)]:
        for rel,h in c[name].items():
            if digest(base/rel)!=h:raise ValueError('Current binding drift '+rel)
        checked[name]=len(c[name])
    before=read(OUT/'authority-before.json');after=read(OUT/'authority-after.json')
    expected_additions={'sources/private-docsouth-walters/alexander-walters-my-life-and-work/README.source.md','data/prose/alexander-walters-my-life-and-work/README.md'}
    if set(after)-set(before)!=expected_additions or any(after.get(p)!=h for p,h in before.items()) or read(OUT/'schema-implementation-before.json')!=read(OUT/'schema-implementation-after.json'):raise ValueError('Preexisting authority/runtime drift or unexpected addition')
    linkage=read(OUT/'independent-projection-linkage.json');command=read(OUT/'independent-projection-command.json')
    if linkage['errors'] or not linkage['producer_disabled'] or command['exit_code']!=0:raise ValueError('Saved independent linkage failed')
    for name in ['assembly','independent-verification','statistics','readers','notice-gate','released-notice-check']:
        if read(OUT/(name+'.json'))['status']!='pass':raise ValueError('Required private gate not passing '+name)
    result=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),implementation_sha256=digest(Path(__file__)),completion_sha256=digest(ROOT/PUB/'completion.json'),checked_binding_counts=checked,accepted_master_sha256=MASTER,source_sha256=c['source_sha256'],rows=c['rows'],text_characters=c['text_characters'],all_existing_canonical_authority_unchanged=True,independent_linkage_producer_disabled=True,private_offline=True,public_publication_performed=False,remaining=c['remaining'])
    save(OUT/'final-delivery-audit.json',result);print(json.dumps(dict(status='pass',counts=checked,completion_sha256=result['completion_sha256'],audit_sha256=digest(OUT/'final-delivery-audit.json'))))
if __name__=='__main__':main()
