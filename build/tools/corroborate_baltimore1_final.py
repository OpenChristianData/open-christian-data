"""Read back completed Baltimore1 maps and bind authoritative terminal evidence."""
from datetime import datetime, timezone
from pathlib import Path
import json
from build.tools.complete_baltimore1_private_release import ROOT, LOG, PUB, RELEASE, digest, save
from build.tools.prepare_baltimore1_private_release import LOG as PRELOG

def main():
    terminal=ROOT/PRELOG/'private-release-finish-v4-terminal.json'
    captured=json.loads(terminal.read_bytes())
    if captured['exit_code']!=0: raise ValueError('Authoritative finish terminal is not zero')
    delivery=LOG/'final-delivery.json'; maps=json.loads(delivery.read_bytes())
    checks=[]
    for key,base in [('authority',ROOT),('schemas',ROOT),('release',RELEASE),('evidence',LOG)]:
        for relative,expected in maps[key].items():
            observed=digest(base/relative)
            if observed!=expected: raise ValueError('Current map mismatch: '+key+'/'+relative)
            checks.append(dict(map=key,path=relative,sha256=observed))
    completion=LOG/'completion.json'
    current=json.loads(completion.read_bytes())
    if digest(PUB/'completion.json')!=digest(completion) or current['status']!='pass': raise ValueError('Canonical completion differs')
    supplement={p.relative_to(ROOT).as_posix():digest(p) for p in [terminal,delivery,completion,PUB/'completion.json',PUB/'selection.json',Path(__file__)]}
    result=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),terminal_exit_code=0,completed_gates_repeated=False,
        map_counts={k:len(maps[k]) for k in ['authority','schemas','release','evidence']},total_map_bindings=len(checks),
        map_bases=dict(authority=str(ROOT),schemas=str(ROOT),release=str(RELEASE),evidence=str(LOG)),checks=checks,
        supplemental_bindings=supplement,accepted_master_sha256=current['accepted_master_sha256'],source_sha256=current['source_sha256'],
        counts=dict(rows=current['rows'],source_lines=current['source_lines'],question_answer_groups=current['question_answer_groups'],text_characters=current['text_characters'],statistics=current['statistics']),
        qualification='Final readback only. Source, master, acceptance, work, state and acquisition remain unchanged. Original path/framing and command-wrapper failures retained. Projection, source, assembly, verification, statistics and readers were not rerun during this corroboration.')
    save(LOG/'terminal-and-current-binding-corroboration.json',result)
    print(json.dumps(dict(status='pass',total_map_bindings=len(checks),map_counts=result['map_counts'],counts=result['counts'],completion_sha256=digest(completion),final_delivery_sha256=digest(delivery),corroboration_sha256=digest(LOG/'terminal-and-current-binding-corroboration.json'),terminal_sha256=digest(terminal))),flush=True)

if __name__=='__main__': main()
