"""Bind terminal and independent install corroboration without repeating gates."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_bcp1559_current import ROOT,LOG as INSTALL_LOG,canonical
from ocd_kernel.library._common import io_path

LOG=ROOT/'reports/_logs/bcp1559-offline-release-20261002-v1'

def main():
    final=json.loads((LOG/'final-delivery.json').read_bytes())
    completion=json.loads((LOG/'completion.json').read_bytes())
    terminal=ROOT/INSTALL_LOG/'private-release-v1-terminal.json'
    installed=ROOT/INSTALL_LOG/'canonical-install/coordinator-installed-generation-review.json'
    if json.loads(terminal.read_bytes())['exit_code']!=0 or json.loads(installed.read_bytes())['status']!='pass':
        raise ValueError('Authoritative terminal or independent install check absent')
    journal=ROOT/'.tmp_audit/accepted-install-08404a2c59cb433f/operation.json'
    if json.loads(io_path(journal).read_bytes())['phase']!='complete':raise ValueError('Canonical journal not complete')
    paths=[LOG/'final-delivery.json',LOG/'completion.json',terminal,installed,journal,Path(__file__)]
    bound={p.relative_to(ROOT).as_posix():sha256(io_path(p).read_bytes()).hexdigest() for p in paths}
    record=dict(status='pass',utc=datetime.now(timezone.utc).isoformat(),work_id='bcp-1559',terminal_exit=0,
                completed_gates_repeated=False,additional_authority_bindings=bound,
                map_bases=dict(authority=str(ROOT),schemas=str(ROOT),release=str(LOG/'release'),evidence=str(LOG)),
                original_map_counts={k:len(final[k]) for k in ('authority','schemas','release','evidence')},
                source_scope='Complete declared sixteen-member retained electronic expression with later variants and supplementary context; no pure1559 print claim.',
                rows=16,text_characters=completion['characters'],uncompressed_bytes=completion['statistics']['uncompressed_bytes'],
                qualification='Immutable original delivery maps and completed gates retained. Supplemental post-process terminal/journal/coordinator install corroboration only; no projection, release, reader or source gates rerun. Human acceptance, print/browser collation, rights and public publication remain separate.')
    target=LOG/'terminal-install-corroboration.json'
    if target.exists():raise FileExistsError(target)
    target.write_bytes(canonical(record));print(json.dumps(record))

if __name__=='__main__':main()
