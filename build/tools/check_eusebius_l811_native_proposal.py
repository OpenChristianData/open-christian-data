"""Fresh independent scratch comparison; never imports the native projector."""
from pathlib import Path
import argparse,json,sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from build.tei.eusebius_l811_native_observer_proposal import verify

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tei',type=Path,required=True)
    parser.add_argument('--leaf',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('Preserve independent scratch proof')
    result=verify(args.tei.read_bytes(),json.loads(args.leaf.read_bytes()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
    if result['producer_imported']:raise ValueError('Actual projector path imported under an alias into independent process')
    print(json.dumps(result,sort_keys=True))
