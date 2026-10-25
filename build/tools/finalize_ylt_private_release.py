"""Bind authoritative terminal and installation corroboration without rerunning gates."""
from pathlib import Path
from hashlib import sha256
import json
from build.tools.prepare_ylt_current import ROOT,LOG as INSTALL_LOG,canonical
from ocd_kernel.library._common import io_path
LOG=ROOT/'reports/_logs/ylt-offline-release-20261002-v1'
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def main():
 terminal_path=ROOT/INSTALL_LOG/'private-release-terminal.json'
 terminal=json.loads(io_path(terminal_path).read_bytes())
 delivery=json.loads((LOG/'final-delivery.json').read_bytes())
 if terminal['exit_code']!=0 or delivery['status']!='pass':raise ValueError('Terminal or final delivery failed')
 maps={k:dict(delivery[k]) for k in ['authority','schemas','release','evidence']}
 bases={'authority':ROOT,'schemas':ROOT,'release':LOG/'release','evidence':LOG}
 for kind,entries in maps.items():
  for p,h in entries.items():
   if digest(bases[kind]/p)!=h:raise ValueError('Completed current binding changed: '+p)
 supplement={}
 for p in [terminal_path,ROOT/INSTALL_LOG/'canonical-install/coordinator-installed-generation-review.json',ROOT/INSTALL_LOG/'canonical-install/coordinator-installed-hash-audit.json',ROOT/'reports/_logs/ylt-coordinator-source-review-20261002-v1/renewed-body-review.json',ROOT/'reports/_logs/ylt-coordinator-source-review-20261002-v1/install-clearance.json']:
  if io_path(p).exists():supplement[p.relative_to(ROOT).as_posix()]=digest(p)
 maps['authority'].update(supplement)
 maps['authority']['build/tools/finalize_ylt_private_release.py']=digest(Path(__file__))
 maps['evidence']['final-delivery.json']=digest(LOG/'final-delivery.json')
 completion=json.loads((LOG/'completion.json').read_bytes())
 record=dict(status='pass',map_bases={k:v.as_posix() for k,v in bases.items()},**maps,terminal_exit_code=0,counts={k:len(v) for k,v in maps.items()},completed=completion,qualification='Fresh retained-source reproduction matches historical native hash without claiming recovery of disposed package; full current installed accepted master projected. Source-native book labels retain IDs. Human/print/translator/rights/publication assessments remain separate.')
 out=LOG/'current-delivery-audit.json'
 if out.exists():raise FileExistsError(out)
 out.write_bytes(canonical(record));print(json.dumps(dict(status='pass',path=out.as_posix(),sha256=digest(out),counts=record['counts'],rows=completion['rows'],characters=completion['characters'])))
if __name__=='__main__':main()
