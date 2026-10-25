"""Recheck the exact installed generation, acquisition, metadata and release freeze."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_first_corinthians_collection import ROOT,WORK,EDITION,ACQUISITION,BASE,SOURCE,SOURCE_SHA,canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.acceptance import validate_acceptance
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--release-evidence',type=Path,required=True);p.add_argument('--installation',type=Path,required=True);a=p.parse_args()
    installation=json.loads(a.installation.read_bytes());completion=json.loads((a.release_evidence/'completion.json').read_bytes())
    frozen=completion['bound_schema_stability']['after']|completion['bound_implementation_stability']['after']
    before={p:digest(ROOT/p) for p in frozen}
    if before!=frozen:raise ValueError('release-bound schema/implementation changed')
    changed=[p for p,h in installation['installed_files'].items() if digest(ROOT/WORK/p)!=h]
    if changed:raise ValueError('installed generation changed: '+repr(changed))
    with cached_edition_lookups():
        validate_acceptance(ROOT/EDITION/'acceptance.json',root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT);SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT)
    original=json.loads((a.installation.parent/'original-work.json').read_bytes());expected=json.loads(json.dumps(original));expected['textual_forms'][0]['editions'][0]['category']='prose'
    if json.loads(io_path(ROOT/WORK/'work.json').read_bytes())!=expected:raise ValueError('metadata exceeded category-only prerequisite')
    staged=json.loads((a.installation.parent/'stage-receipt.json').read_bytes());acq_rel=ACQUISITION.relative_to(WORK).as_posix()
    if digest(ROOT/ACQUISITION)!=staged['before'][acq_rel] or digest(ROOT/SOURCE)!=SOURCE_SHA:raise ValueError('acquisition/source changed')
    after={p:digest(ROOT/p) for p in frozen}
    if after!=before:raise ValueError('freeze changed during canonical checks')
    record=dict(status='pass',installed_files_checked=len(installation['installed_files']),all_installed_hashes_unchanged=True,canonical_acceptance_state='pass',current_source_manifest='pass',source_sha256=SOURCE_SHA,acquisition_sha256=digest(ROOT/ACQUISITION),exact_category_only_prerequisite='pass',original_title_ids_locator_acquisition_preserved=True,bound_schema_and_implementation_stability=dict(status='pass',before=before,after=after),normal_and_streaming_readers=json.loads((a.release_evidence/'readers.json').read_bytes())['status'])
    if record['normal_and_streaming_readers']!='pass':raise ValueError('readers not passing')
    (a.release_evidence/'final-canonical-check.json').write_bytes(canonical(record));print(json.dumps(record))
if __name__=='__main__':main()
