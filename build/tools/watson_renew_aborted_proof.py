"""Preserve aborted v1 authoring and repair its two-child lxml order mutant."""
from pathlib import Path
from hashlib import sha256
import json,shutil
ROOT=Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    LOG=ROOT/'reports/_logs/watson-existing-install-20261003-v1'
    archive=LOG/'aborted-v1-source-contract'
    if archive.exists():raise FileExistsError('Preserve prior aborted Watson proof archive')
    archive.mkdir()
    source=ROOT/'sources/commentaries/expositors-bible/watson-retained-install-20261003-v1'
    shutil.copytree(source,archive/'source-contract')
    code=('build/tei/watson_retained_native_emitter.py','build/tei/watson_retained_native_prepare.py','build/tei/watson_retained_native_oracle.py','build/tei/watson_original_scope.py','build/tools/prepare_watson_retained_candidates.py')
    for relative in code:(archive/Path(relative).name).write_bytes((ROOT/relative).read_bytes())
    record=dict(status='aborted-proof-harness-defect',native_source_oracle='passed for first package; all three refined direct source reviews passed previously',reason='Inherited lxml tuple child swap fails for exactly two body roots; use explicit remove and insert so the mutant actually reorders both intact source parts.',source_inputs_unchanged=True,readable_native_bytes_unchanged=True,retained_candidate_root='D:/Library/Open Christian Data/candidate-reviews/watson-existing-native-20261003-v1',archive={p.relative_to(archive).as_posix():sha256(p.read_bytes()).hexdigest() for p in archive.rglob('*') if p.is_file()})
    (archive/'aborted-run.json').write_text(json.dumps(record,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
    path=ROOT/'build/tei/watson_retained_native_prepare.py';text=path.read_text(encoding='utf-8');old="SOURCE_DIR = Path('sources/commentaries/expositors-bible/watson-retained-install-20261003-v1')";assert text.count(old)==1
    path.write_text(text.replace(old,old.replace('-v1','-v2')),encoding='utf-8',newline='\n')
    path=ROOT/'build/tools/prepare_watson_retained_candidates.py';text=path.read_text(encoding='utf-8');old='root[0],root[1]=root[1],root[0]';assert text.count(old)==1
    text=text.replace(old,'first=root[0];root.remove(first);root.insert(1,first)').replace('candidate-reviews/watson-existing-native-20261003-v1','candidate-reviews/watson-existing-native-20261003-v2')
    path.write_text(text,encoding='utf-8',newline='\n')
    print(json.dumps(dict(status='renewed',code_sha256={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in code})))
