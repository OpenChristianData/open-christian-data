"""Prepare standalone Maclaren stage/guard derivatives before authority freeze."""
from pathlib import Path
ROOT=Path.cwd()
def rep(s,old,new):
 if old not in s:raise ValueError('Maclaren stage basis differs: '+old[:120])
 return s.replace(old,new)
for kind in ('stage','install','prove'):
 source=ROOT/('build/tools/'+kind+'_findlay_retained_acceptance.py' if kind!='prove' else 'build/tools/prove_findlay_retained_install.py')
 s=source.read_text(encoding='utf-8').replace('Findlay','Maclaren').replace('findlay','maclaren').replace('maclaren_retained_prepare','maclaren_retained_native_prepare').replace('maclaren_retained_oracle','maclaren_retained_native_oracle').replace('two-edition','four-unit').replace('two accepted editions','four accepted editions')
 s=s.replace('included_volumes=2','included_volumes=4').replace('acquired_volumes=2','acquired_volumes=4').replace('accepted_editions=2','accepted_editions=4').replace('complete_acquired_work_volumes=2','complete_acquired_work_volumes=4').replace("!= 2","!= 4").replace("accepted_scope_kind='edition'","accepted_scope_kind='volume'").replace("scope_kind='edition'","scope_kind='volume'").replace("scope_kind='edition'","scope_kind='volume'").replace("!= 'edition'","!= 'volume'").replace("kind='edition'","kind='volume'").replace("b'</ns0:teiHeader>'","b'</teiHeader>'")
 if kind=='stage':
  s=rep(s,'ROOT, LOG, WORK_ID, MEMBERS, OLD_PACKAGE, sha','ROOT, LOG, WORK_ID, SPECS as MEMBERS, OLD_PACKAGE, sha')
  s=rep(s,'from build.tools.prepare_maclaren_retained_candidates import CANDIDATES','from build.tools.prepare_maclaren_retained_candidates import CANDIDATES, EXPECTED_MUTATIONS')
  s=rep(s,"Path('build/tei/expositors_bible_maclaren_validation.py')" if "Path('build/tei/expositors_bible_maclaren_validation.py')" in s else "Path('build/tei/expositors_bible_findlay_validation.py')","Path('build/tei/maclaren_retained_native_emitter.py')")
  s=s.replace("LOG / 'existing_scope_review.py'","LOG / 'source_inventory.py'").replace("LOG / 'existing-scope-review.json'","LOG / 'source-inventory.json'").replace("LOG / 'relative_uri_review.py', LOG / 'relative-uri-review.json', ",'').replace("Path('build/tools/maclaren_stage_adapt.py')","Path('build/tools/prepare_maclaren_stage_code.py'), Path('build/tools/prepare_maclaren_code.py')")
  s=s.replace("['current_acquired_denominator']","['acquired_denominator']").replace("len(work['textual_forms']) != 4","len(work['textual_forms']) != 4")
  s=s.replace("execution-imports-v3.json","execution-imports.json").replace("candidate-completion-receipt-v3.json","candidate-completion-receipt-v2.json").replace("-current-review-v3.json","-current-review-v2.json")
  s=rep(s,"(15 if member_id == 'maclaren-expositoreph' else 13)","EXPECTED_MUTATIONS[member_id]")
  start=s.index('        selected = f"');end=s.index('        revision = ',start)
  s=s[:start]+"        selected = declared_scope(edition_record, member_id)\n"+s[end:]
  s=rep(s,"note='Readable faithful retained volume; original source order and literal identities preserved.'","note=REVISION_NOTE")
  start=s.index('        bound = bind_reviewed_header(');end=s.index('        candidate = write(',start)
  s=s[:start]+"        bound = recompute_header(raw, identity=identity, source=source, source_url=acquisition['url'], declared=selected, revision=revision)\n"+s[end:]
  s=rep(s,"relative_uri_bases=direct['relative_uri_bases'], table_summary_changes=direct['table_summary_changes']","relative_uri_context=direct['relative_uri_context'], table_count=direct['table_count'], table_header_cell_count=direct['table_header_cell_count']")
  start=s.index('        technical = dict(');end=s.index("        for name in ['validation'",start)
  s=s[:start]+'''        technical = dict(producer={'id': manifest.record['converter']['id']}, checker={'id': manifest.record['validator']['id']}, shared_assumptions=['Pinned XML, P5 and declared native mapping; prior producer/mapping exposure declared. Independent stdlib raw source traversal with secondary lxml corroboration; oracle imports no producer/emitter or projection code.'], independent_corroboration='Complete actual root/text/front/body/back fields, semantic attributes, paragraph/heading/verse and source span/br ownership, note attachment, table summaries/spans/header roles, exact next/prev or missing toc annotations and all relative URI contexts independently compared against raw. All ten administrative comments per source and two tbody wrappers in PsalmsII independently reconciled with exact joins before entire actual-backed source-body inverse. All original head/prolog/CSS/copyright human-visible. Schema-valid 15/19/15/20 mutations including same-text wrong attachment and extra outer body payload reject. Two fresh Python six-member equality replays each pass. Complete original flat graphs/encoded witnesses independently reconciled before repair; not a readable-native equality claim. No image elements or source U+FFFD occur.')
''' +s[end:]
  s=s.replace('all 14/22 administrative comments','all ten administrative comments per volume')
  start=s.index("            source_quality_uncertainty=");end=s.index('        review_path = ',start)
  s=s[:start]+'''            source_quality_uncertainty=['Exact retained CCEL electronic witnesses only; no print or independent provider collation.', 'Psalms I1-38 /II39-89 /III90-150 retained as three volume units. Colossians/Philemon remains its acquired combined volume. Source-specific span/br versus verse/l arrangements retained, with no invented verse targets or typography equivalence.', 'Missing source navigation toc references remain literal typed annotations; no source images or U+FFFD in these four XML witnesses.'], discrepancies=[], unreviewed_residuals=['Human review, CCEL formatting rights, print collation and release remain separate; actual commentary projection measured independently.'])
''' +s[end:]
  s=rep(s,"installation='not-performed')","installation='not-performed', staged_at=at)")
  index=s.index('\ndef prepare(stage,')
  s=s[:index]+'''
REVISION_NOTE='Readable faithful retained volume; original source order and literal identities preserved.'
def declared_scope(edition_record, member_id):
    ranges={'maclaren-expositorpsalms1':'Psalms I-XXXVIII (1-38), volume I','maclaren-expositorpsalms2':'Psalms XXXIX-LXXXIX (39-89), volume II','maclaren-expositorpsalms3':'Psalms XC-CL (90-150), volume III','maclaren-expositorcolphm':'Colossians and Philemon, the complete acquired combined volume'}
    return f"Complete retained CCEL electronic volume unit: {edition_record['title']}; {ranges[member_id]}. All source front matter, ordered commentary, printed and generated indices, notes, tables, verse/line and source span/br carriers, navigation and literal references are retained. All ten administrative comments per source remain exact ledger fields with independently checked whitespace joins; both PsalmsII tbody wrappers retain intact owning rows and exact inverse fields. Table summaries/spans and six Colossians/Philemon source th roles preserved. Relative hrefs (38/51/61/33 by acquired unit) retain literal targets and exact corresponding acquisition-URL context; known next/prev source IDs map locally, missing toc remains literal annotation. Entire source body independently restored from actual native payload and source-derived original attributes; complete source head/prolog/CSS/copyright human-visible. All four acquired units accounted (4/4) under unchanged existing author catalog, not complete author or series. Three Psalms volumes jointly cover the retained Psalm ranges1-150, without claiming any one is the whole Psalms work. No print, universal layout or invented verse-target claim. These four XML witnesses contain no image elements or U+FFFD."
def recompute_header(raw, *, identity, source, source_url, declared, revision):
    bound=bind_reviewed_header(raw,expected_sha256=sha(raw),identity=identity,source=source,source_url=source_url,declared_scope=declared,revision=revision)
    old=b'Reconstruction candidate of an existing acquired electronic witness. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
    new=b'Agent-accepted faithful retained electronic volume. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
    if bound.count(old)!=1:raise PipelineError('Maclaren ordered header publication preimage differs')
    bound=bound.replace(old,new,1)
    if bound.split(b'</teiHeader>',1)[1]!=raw.split(b'</teiHeader>',1)[1]:raise PipelineError('Maclaren ordered header binding changed body bytes')
    return bound
''' +s[index:]
 if kind=='install':
  s=rep(s,'from contextlib import ExitStack','from contextlib import ExitStack\nfrom datetime import datetime\nimport sys')
  s=rep(s,'edition_path, dependencies, projection_gate, read, sha','edition_path, dependencies, projection_gate, read, sha, declared_scope, recompute_header, REVISION_NOTE')
  after="        accounting = read(stage / lane / 'source-accounting.json')"
  insert='''        accepted=validate_acceptance(stage / edition / 'acceptance.json',root=stage)
        revision=accepted['representation_revision'];date=datetime.fromisoformat(receipt['staged_at'].replace('Z','+00:00')).date().isoformat()
        expected_revision=dict(id=member_id+'-retained-current-20261003-v1',date=date,note=REVISION_NOTE)
        if revision!=expected_revision:raise PipelineError('Maclaren ordered header revision differs')
        form=next(f for f in expected_work['textual_forms'] if f['textual_form_id']==spec['form']);entry=next(e for e in form['editions'] if e['edition_id']==spec['edition'])
        identity=dict(work_id=WORK_ID,textual_form_id=spec['form'],edition_id=spec['edition'],acquisition_id=spec['acquisition'])
        acq=read(root / edition / 'acquisitions' / (spec['acquisition']+'.json'));source={k:acq[k] for k in ['source_path','source_sha256','source_bytes','source_scope']}
        expected_bound=recompute_header(original,identity=identity,source=source,source_url=acq['url'],declared=declared_scope(entry,member_id),revision=expected_revision)
        if master!=expected_bound or _io_path(stage / lane / 'candidate.tei.xml').read_bytes()!=expected_bound:raise PipelineError('Maclaren full ordered header recomputation differs')
'''
  s=rep(s,after,insert+after)
  s=rep(s,'        def checkpoint(point):','        runtime_files=[]\n        def checkpoint(point):')
  s=rep(s,"                validate_state(target / 'state.json', root=root)","                validate_state(target / 'state.json', root=root)\n                runtime_files.extend(assert_executed_dependencies(receipt))")
  s=rep(s,'    return result\n','    result[\'executed_first_party_files\']=runtime_files\n    result[\'late_execution_dependency_gate\']=\'pass\'\n    return result\n')
  index=s.index('\ndef install(stage,')
  s=s[:index]+'''
def assert_executed_dependencies(receipt):
    records={}
    for module in sys.modules.copy().values():
        file=getattr(module,'__file__',None)
        if not file:continue
        path=Path(file).resolve(strict=True)
        if path.is_relative_to(ROOT):
            relative=path.relative_to(ROOT).as_posix();pin=sha(path.read_bytes())
            if receipt['dependency_files'].get(relative)!=pin:raise PipelineError('Maclaren unexpected or drifted executed dependency: '+relative)
            records[relative]=pin
    return [dict(path=p,sha256=records[p]) for p in sorted(records)]
''' +s[index:]
 target=ROOT/('build/tools/'+kind+'_maclaren_retained_acceptance.py' if kind!='prove' else 'build/tools/prove_maclaren_retained_install.py')
 if target.exists():raise FileExistsError('Preserve existing Maclaren standalone guard')
 target.write_text(s,encoding='utf-8')
