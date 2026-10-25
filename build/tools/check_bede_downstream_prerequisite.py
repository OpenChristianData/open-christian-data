"""Check only accepted canonical category prerequisite; no native projection call."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json
from ocd_kernel.library._common import io_path,PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.sermons import _accepted_context
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/_logs/bede-pg38326-downstream-preflight-20261001'
def main():
    pre=json.loads(io_path(OUT/'preflight.json').read_bytes());p=ROOT/'library/works/bede-ecclesiastical-history-of-england/work.json';b=io_path(p).read_bytes()
    try:
        with cached_edition_lookups():_accepted_context(io_path(ROOT),io_path(ROOT/pre['acceptance_path']),expected_category='prose')
    except PipelineError as e:
        v=dict(status='canonical-category-prerequisite-failed',checked_at=datetime.now(timezone.utc).isoformat(),exception_type=type(e).__name__,literal_error=str(e),work_json_sha256=sha256(b).hexdigest(),work_json=json.loads(b),full_native_projection_started=False,canonical_authority_changed=False)
    else:v=dict(status='canonical-category-prerequisite-pass',full_native_projection_started=False)
    io_path(OUT/'category-prerequisite.json').write_text(json.dumps(v,sort_keys=True,ensure_ascii=False)+'\n',encoding='utf-8');print(json.dumps(v))
if __name__=='__main__':main()
