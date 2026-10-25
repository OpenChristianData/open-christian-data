"""Focused source-text and work-boundary regressions for L744 hymn candidates."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from lxml import etree

from ocd_kernel.reconstruction import SourceManifest

ROOT=Path(__file__).resolve().parents[1]
TEI="http://www.tei-c.org/ns/1.0"
XML_ID="{http://www.w3.org/XML/1998/namespace}id"
WORKS=(
 "l744-pg33128-gospel-hymns",
 "l744-pg33105-chinook-hymns",
)
def _load_module(name,path):
 spec=importlib.util.spec_from_file_location(name,path)
 if spec is None or spec.loader is None:raise RuntimeError(f"cannot load {path}")
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module
PRODUCER=_load_module("l744_test_producer",ROOT/"build/tei/l744_hymns.py")
ORACLE=_load_module("l744_test_oracle",ROOT/"build/tei/l744_hymns_oracle.py")

class MemoryCandidate:
 def __init__(self,members):
  self.members=members
  self.sha256=hashlib.sha256(members["content.tei.xml"]).hexdigest()
 def member_bytes(self,name):return self.members[name]

def _manifest(slug):
 return SourceManifest.load(ROOT/"sources/manifest-acquisitions"/slug/"source-manifest.json",repository_root=ROOT)
def _baseline(slug):
 manifest=_manifest(slug)
 return manifest,dict(PRODUCER._convert(manifest))
def _oracle(manifest,members):
 return ORACLE._oracle(manifest,MemoryCandidate(members))
def _rebind_accountability(members):
 xml=members["content.tei.xml"]
 account=json.loads(members["source-accountability.json"])
 account["candidate_sha256"]=hashlib.sha256(xml).hexdigest()
 account["candidate_bytes"]=len(xml)
 members["source-accountability.json"]=(
  json.dumps(account,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n"
 ).encode("utf-8")
def _mutate(members,callback):
 changed=dict(members)
 tree=etree.fromstring(changed["content.tei.xml"],etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
 callback(tree)
 changed["content.tei.xml"]=etree.tostring(tree,encoding="UTF-8",xml_declaration=True)
 _rebind_accountability(changed)
 return changed

@pytest.mark.parametrize("slug",WORKS)
def test_source_complete_candidate_has_direct_tei_and_independent_p5_oracle(slug):
 manifest,members=_baseline(slug)
 tree=etree.fromstring(members["content.tei.xml"],etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
 assert etree.QName(tree).localname=="TEI"
 assert tree.find(f"{{{TEI}}}text/{{{TEI}}}body") is not None
 report=_oracle(manifest,members)
 assert report["status"]=="pass",report["findings"]
 assert report["findings"]==[]

@pytest.mark.parametrize("slug",WORKS)
def test_source_text_mutation_is_rejected(slug):
 manifest,members=_baseline(slug)
 def change(tree):
  body=tree.find(f".//{{{TEI}}}text/{{{TEI}}}body")
  assert body is not None
  paragraph=next((x for x in body.iter(f"{{{TEI}}}p") if x.text and x.text.strip()),None)
  assert paragraph is not None
  paragraph.text+=" [source-text mutation]"
 changed=_mutate(members,change)
 report=_oracle(manifest,changed)
 assert report["status"]=="fail"
 assert any("source body text or whitespace differs" in finding for finding in report["findings"])

def test_ojibway_english_collection_boundary_mutation_is_rejected():
 manifest,members=_baseline("l744-pg33128-gospel-hymns")
 def change(tree):
  collection=next((x for x in tree.iter() if x.get(XML_ID)=="h"),None)
  assert collection is not None
  collection.set("n","999999")
 report=_oracle(manifest,_mutate(members,change))
 assert report["status"]=="fail"
 assert any("source element order/identity differs" in finding for finding in report["findings"])

def test_chinook_interlinear_pair_boundary_mutation_is_rejected():
 manifest,members=_baseline("l744-pg33105-chinook-hymns")
 def change(tree):
  table=next(tree.iter(f"{{{TEI}}}table"),None)
  assert table is not None
  rows=list(table.iter(f"{{{TEI}}}row"))
  assert len(rows)==2
  rows[0].getparent().remove(rows[0])
 report=_oracle(manifest,_mutate(members,change))
 assert report["status"]=="fail"
 assert any("Chinook interlinear table 1 must retain its two-row boundary" in finding
            for finding in report["findings"])
