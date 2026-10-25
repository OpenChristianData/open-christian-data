"""Refresh the exact local emitter bytes after Windows text serialization."""
from pathlib import Path
from hashlib import sha256
import re
ROOT=Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    path=ROOT/'build/tei/watson_retained_native_prepare.py'
    value=path.read_text(encoding='utf-8')
    pin=sha256((ROOT/'build/tei/watson_retained_native_emitter.py').read_bytes()).hexdigest()
    value,count=re.subn(r'^EMITTER_SHA = .*$', 'EMITTER_SHA = '+repr(pin),value,flags=re.M)
    assert count==1
    path.write_text(value,encoding='utf-8')
    print(pin)
