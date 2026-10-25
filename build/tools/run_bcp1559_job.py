"""Capture authoritative outcomes for only this work's scoped commands."""
from datetime import datetime,timezone
from pathlib import Path
import argparse
import json
import subprocess
import sys
from build.tools.prepare_bcp1559_current import ROOT,LOG

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--name',required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    target=ROOT/LOG/(args.name+'-terminal.json')
    if target.exists():raise FileExistsError(target)
    command=[sys.executable,*(args.command[1:] if args.command[:1]==['--'] else args.command)]
    start=datetime.now(timezone.utc).isoformat()
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',check=False)
    receipt=dict(command=command,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr,started_utc=start,finished_utc=datetime.now(timezone.utc).isoformat())
    target.write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(exit_code=result.returncode,receipt=str(target))))
    if result.returncode:raise subprocess.CalledProcessError(result.returncode,command,result.stdout,result.stderr)

if __name__=='__main__':main()
