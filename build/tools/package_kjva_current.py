"""Exact KJVA replay and meaningful body/header/Apocrypha mutation checks."""
import argparse,json,re
from pathlib import Path
from hashlib import sha256
from lxml import etree
from build.tools.prepare_kjva_current import ROOT,BASE,canonical
from build.tei.kjva_current_oracle import check
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('candidate','replay','output'):p.add_argument('--'+n,type=Path,required=True)
 args=p.parse_args();a=CandidatePackage.load(args.candidate/'package');b=CandidatePackage.load(args.replay/'package')
 if a.sha256!=b.sha256 or any(a.member_bytes(n)!=b.member_bytes(n) for n in a.member_names) or (args.candidate/'validation.json').read_bytes()!=(args.replay/'validation.json').read_bytes():raise ValueError('Exact fresh replay differs')
 m=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);raw=a.member_bytes('content.tei.xml');baseline=check(m,raw)
 verse=re.search(rb'<ab type="verse" n="1" xml:id="kjva-book-001-chapter-001-verse-001" xml:space="preserve">.*?</ab>',raw).group()
 next_verse=re.search(rb'<ab type="verse" n="2" xml:id="kjva-book-001-chapter-001-verse-002" xml:space="preserve">.*?</ab>',raw).group()
 apocrypha=re.search(rb'<div type="book" n="I Esdras".*?(?=<div type="book")',raw).group()
 samples={'wording':raw.replace(verse,verse.replace(b'In the beginning',b'Invented opening'),1),'verse-omission':raw.replace(verse,b'',1),'verse-duplicate':raw.replace(verse,verse+verse,1),'verse-order':raw.replace(verse+next_verse,next_verse+verse,1),'verse-number':raw.replace(verse,verse.replace(b'n="1"',b'n="2"',1),1),'verse-id':raw.replace(verse,verse.replace(b'verse-001',b'verse-999',1),1),'verse-child':raw.replace(verse,verse.replace(b'</ab>',b'<note>Invented</note></ab>'),1),'verse-tail':raw.replace(verse,verse+b'Invented tail',1),'book-name':raw.replace(b'type="book" n="Genesis"',b'type="book" n="1"',1),'book-attachment':raw.replace(b'xml:id="kjva-book-001-chapter-001"',b'xml:id="kjva-book-002-chapter-001"',1),'apocrypha-omission':raw.replace(apocrypha,b'',1),'apocrypha-label':raw.replace(b'type="book" n="I Esdras"',b'type="book" n="Genesis"',1),'header-label':raw.replace(b'King James Version (1769)',b'Invented print edition',1),'header-rights':raw.replace(b'not fresh worldwide underlying-translation rights clearance',b'Universal permission established',1),'foreign-namespace':raw.replace(b'<ab type="verse"',b'<ab xmlns="urn:invented" type="verse"',1)}
 args.output.mkdir(parents=True,exist_ok=False);cases=[]
 for name,changed in samples.items():
  if changed==raw:raise ValueError('Inert mutation '+name)
  try:check(m,changed)
  except (ValueError,etree.XMLSyntaxError,etree.DocumentInvalid) as error:cases.append(dict(name=name,status='rejected',reason=str(error),mutated_sha256=sha256(changed).hexdigest()))
  else:raise ValueError('Accepted mutation '+name)
  print('Rejected '+name,flush=True)
 proof=dict(status='pass',baseline=baseline,cases=cases,candidate_sha256=a.sha256,replay_sha256=b.sha256,validation_equal=True,mutation_selectors='Exact byte replacements in this SHA-bound script; original complete candidate retained.')
 (args.output/'result.json').write_bytes(canonical(proof));print(json.dumps(dict(status='pass',cases=len(cases))))
if __name__=='__main__':main()
