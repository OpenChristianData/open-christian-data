"""Create a work-local independent raw checker from preserved Smith mapping."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def main():
    original=(ROOT/'build/tei/smith_retained_native_oracle.py').read_text(encoding='utf-8')
    start=original.index('def _parse(');end=original.index('\ndef _oracle(')
    core=original[start:end]
    branch=core.index('\n if native:')
    core=core[:branch]+'\n return result\n'
    core=core.replace('*,native=True','*,native=False')
    imports='''"""Independent actual-volume raw checker for the two acquired Isaiah sources.

Prior exposure: derived from the previously exercised independent Smith source
mapping. No producer, emitter or projection module is imported. The raw source
is independently parsed using stdlib and corroborated with lxml; actual text
fields, attributes, attachment/order and complete body inverse are checked.
"""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json,re
from urllib.parse import quote
import xml.etree.ElementTree as ET
from lxml import etree
ROOT=Path(__file__).resolve().parents[2]
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
SOURCES={
 'smith-ga-expositorisa1':('smith_ga_expositorisa1.xml','a464f1047de41078f887246295a2ec79b0911cecf14e893a9087b0ad72dc6646',('i','ii','iii','iv'),('x','xi','xii'),5702),
 'smith-ga-expositorisa2':('smith_ga_expositorisa2.xml','284d42fbc9813cf06cb88e72362aea9c0cd08ea09e47776707541b8bc0998a80',('i','ii','iii'),('viii','ix','x','xi'),7349),
}
'''
    target=ROOT/'build/tei/smith_isaiah_source_oracle.py'
    if target.exists():raise FileExistsError('Preserve existing oracle')
    target.write_text(imports+core,encoding='utf-8',newline='\n')
if __name__=='__main__':main()
