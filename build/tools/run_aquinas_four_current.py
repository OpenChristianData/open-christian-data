"""Capture explicit outcomes for one bounded Aquinas work-local job."""
from datetime import datetime,timezone
from pathlib import Path
import argparse,json,subprocess,sys
from build.tools.prepare_aquinas_four_current import ROOT,LOG,canonical
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--name',required=True);parser.add_argument('command',nargs=argparse.REMAINDER);args=parser.parse_args()
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    command=[sys.executable,*command];path=ROOT/LOG/(args.name+'-terminal.json')
    if path.exists():raise FileExistsError(path)
    start=datetime.now(timezone.utc).isoformat();r=subprocess.run(command,cwd=ROOT,check=False,capture_output=True,text=True,encoding='utf-8')
    path.write_bytes(canonical(dict(command=command,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr,started_utc=start,finished_utc=datetime.now(timezone.utc).isoformat())))
    print(json.dumps(dict(exit_code=r.returncode,receipt=str(path))),flush=True)
    if r.returncode:raise subprocess.CalledProcessError(r.returncode,command,r.stdout,r.stderr)
if __name__=='__main__':main()
