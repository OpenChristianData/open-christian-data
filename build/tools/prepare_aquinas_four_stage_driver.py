"""Adapt the established guarded work-local stage, without changing shared code."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    source=(ROOT/'build/tools/stage_murray_absolute_surrender_current.py').read_text(encoding='utf-8')
    source=source.replace('murray_absolute_surrender_current','aquinas_four_current').replace('murray-absolute-surrender','aquinas-summa-theologica-four-parts').replace('ccel-murray-surrender-v1','aquinas-four-current-v1').replace('murray-surrender-','aquinas-four-')
    source=source.replace('b211e8373f66fa98c8206fe6d0b694ff7c3232d89b0c7a8da20d5340a9536cd3','d749eb107efc8e762642a05dc35c7ebcd7789b37459851f74d9faf14c7c1c013')
    source=source.replace('len(mutations["cases"]) != 25','len(mutations["cases"]) != 33').replace('len(projection["rows"]) != 11','len(projection["rows"]) != 4')
    source=source.replace('    put(stage,WORK/"SOURCE_CREDIT.md",notice)\n','    # Preserve existing canonical source credit; new paired notice is separately bound.\n')
    old='    coordinator = ROOT/"reports/_logs/aquinas-summa-theologica-four-parts-reconciliation-20261001-v1/coordinator-historical-body-review.json"\n    put(stage,EVIDENCE/"coordinator-source-review.json",coordinator.read_bytes())'
    if old not in source:raise ValueError('Coordinator replacement preimage differs')
    source=source.replace(old,'    coordinator = ROOT/"reports/_logs/aquinas-four-coordinator-source-review-20261002-v1/review.json"\n    put(stage,EVIDENCE/"coordinator-source-review.json",coordinator.read_bytes())\n    put(stage,EVIDENCE/"coordinator-header-review.json",(coordinator.parent/"header-renewal-review.json").read_bytes())')
    source=source.replace("id='aquinas-summa-theologica-four-parts-ccel-electronic-v1',date='2026-10-01',note='Technical acceptance of the complete retained Murray collection, own title page, nine addresses, integral scripture index; exact historically proven native TEI and source-accountability reused with renewed whole collection scope and literal electronic credits.'","id='aquinas-four-gutenberg-agent-v1',date='2026-10-02',note='Technical acceptance of the complete retained four-component partial English witness; exact original text conserved with explicitly renewed generated header and full primary HTML accounting. No Supplement, full traditional scope, print equivalence, rights clearance or public publication claim.'")
    source=source.replace('scope=SCOPE if m["path"]==source["source_path"] else "Unexpected supplemental source member; this route declares exactly the retained XML"','scope="Complete retained component "+str(i)+" of this four-part partial electronic witness; own contextual source scope: "+m["scope"]')
    start=source.index('    def refs(value):');end=source.index('    if {p.as_posix(): sha256((ROOT / p).read_bytes()).hexdigest() for p in schema_paths}',start)
    source=source[:start]+'''    challenges=[]
    for kind in ('wording','row-order','generated-question-number'):
        rows=deepcopy(projection['rows'])
        if kind=='wording': rows[0]['text']='Invented public text'
        elif kind=='row-order': rows[0],rows[1]=rows[1],rows[0]
        else:
            def alter(value):
                if isinstance(value,dict):
                    if value.get('attributes',{}).get('type')=='question':value['attributes']['number']='999';return True
                    return any(alter(child) for child in value.values())
                if isinstance(value,list):return any(alter(child) for child in value)
                return False
            if not alter(rows):raise ValueError('Question structure absent from actual public output')
        failures=verify_accepted_document(io_path(promoted_root),acceptance_path=io_path(promoted_acceptance),rows=rows,receipt=projection['receipt'],category='prose')
        if not failures:raise ValueError('Public output challenge escaped '+kind)
        challenges.append(dict(mutation=kind,status='rejected',errors=failures))
    put_json(promoted_root,EVIDENCE/'public-preservation-proof.json',dict(status='pass',rows=4,independent_mutation_checks=challenges,qualification='Source-derived generated question/article labels preserved as structure; no scripture parsing or source correction inferred.'))
''' +source[end:]
    source=source.replace('Murray','Aquinas four-component witness').replace('whole954source','whole retained HTML source').replace('full954source','full retained HTML source').replace('954carrier','complete retained HTML carrier').replace('954source','complete retained HTML source').replace('889body descendant','35,488 unit').replace('Twenty-five','Thirty-three').replace('titlepage/nine addresses/integral scripture index, four verse groups/twelve lines,167italic carriers,69scripRef/69hyperlinks and fullcomplete retained HTML source-accountability','all four component front matter,512questions/2669articles,7962italic spans,2961explicitbreaks and full primary HTML accounting')
    source=source.replace('one existing identity and unchanged source text/evidence','one existing identity and unchanged source text/evidence')
    destination=ROOT/'build/tools/stage_aquinas_four_current.py'
    if destination.exists():raise FileExistsError(destination)
    destination.write_text(source,encoding='utf-8')
    print(str(destination))
if __name__=='__main__':main()
