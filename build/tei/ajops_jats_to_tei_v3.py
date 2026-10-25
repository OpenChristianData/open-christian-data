from __future__ import annotations
import base64,hashlib,json
from typing import Mapping
from lxml import etree
TEI="http://www.tei-c.org/ns/1.0"; XML="http://www.w3.org/XML/1998/namespace"; XLINK="http://www.w3.org/1999/xlink"
INLINE={"italic","bold","underline","sup","sub","sc","monospace","named-content","styled-content","xref","ext-link","email","inline-formula","inline-graphic","break","string-name"}
HEADS={"article-title","title"}
def _sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def _canon(o:object)->bytes:return (json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
def _authority(manifest,name:str)->Mapping[str,object]:
 for row in manifest.record["authorities"]:
  if row["name"]==name:return row
 raise ValueError(f"missing authority {name}")
def _local(tag:str)->str:return etree.QName(tag).localname
def _tei(tag:str)->str:return f"{{{TEI}}}{tag}"
def _locus(node)->str:
 parts=[];current=node
 while current is not None:
  name=_local(current.tag);parent=current.getparent()
  rank=1 if parent is None else 1+sum(1 for sibling in current.itersiblings(preceding=True) if _local(sibling.tag)==name)
  parts.append(f"{name}[{rank}]");current=parent
 return "/"+"/".join(reversed(parts))
def _mark(out,node,tag:str|None=None)->None:
 if node.get("id"):out.set(f"{{{XML}}}id",node.get("id"))
 name=tag or _local(node.tag);tokens=[f"urn:ocd:jats-tag:{name}"]
 attrs=dict(node.attrib)
 if attrs:tokens.append("urn:ocd:jats-attrs:"+base64.urlsafe_b64encode(_canon(attrs)).decode("ascii").rstrip("="))
 tokens.append("urn:ocd:jats-path:"+base64.urlsafe_b64encode(_locus(node).encode("utf-8")).decode("ascii").rstrip("="))
 out.set("ana"," ".join(tokens))
def _inline(node):
 tag=_local(node.tag)
 if tag in {"italic","bold","underline","sup","sub","sc","monospace"}:
  out=etree.Element(_tei("hi"),rend=f"jats:{tag}")
 elif tag in {"xref","ext-link","email"}:
  out=etree.Element(_tei("ref"))
  target=node.get(f"{{{XLINK}}}href")
  if tag=="xref" and node.get("rid"):
   target=" ".join("#"+identity for identity in node.get("rid").split())
  elif tag=="email":
   target=target or "".join(node.itertext()).strip()
   if target and not target.startswith("mailto:"):target="mailto:"+target
  if target:out.set("target",target)
 elif tag=="inline-graphic":
  out=etree.Element(_tei("graphic"))
  href=node.get(f"{{{XLINK}}}href")
  if href:out.set("url",href)
 elif tag=="break":out=etree.Element(_tei("lb"))
 else:out=etree.Element(_tei("seg"))
 _mark(out,node)
 out.text=node.text
 for child in node:
  out.append(_inline(child));out[-1].tail=child.tail
 return out
def _text_run(parent,text:str|None,inline=None):
 if (text is None or not text.strip()) and inline is None:return
 run=etree.SubElement(parent,_tei("div"),type="jats:text-run")
 p=etree.SubElement(run,_tei("p"))
 p.text=text
 if inline is not None:
  p.append(_inline(inline))
def _paragraph(node,tag):
 out=etree.Element(_tei("div"),type=f"jats:{tag}");_mark(out,node,tag)
 p=etree.SubElement(out,_tei("head") if tag in HEADS else _tei("p"));_paragraph_content(p,node)
 return out
def _paragraph_content(p,node):
 p.text=node.text
 for child in node:
  if _local(child.tag) in INLINE or _local(child.tag) in {"graphic","inline-graphic"}:p.append(_inline(child))
  else:
   phrase=etree.SubElement(p,_tei("seg"));_mark(phrase,child);phrase.text="".join(child.itertext())
  p[-1].tail=child.tail
 return p
def _footnote(node):
 out=etree.Element(_tei("note"),type="jats:fn");_mark(out,node);out.text=node.text
 for child in node:
  tag=_local(child.tag)
  if tag=="p":
   p=etree.SubElement(out,_tei("p"));_mark(p,child);_paragraph_content(p,child)
  elif tag=="label":
   p=etree.SubElement(out,_tei("p"));_mark(p,child);_paragraph_content(p,child)
  elif tag in INLINE:out.append(_inline(child));out[-1].tail=child.tail
  else:out.append(_block(child));out[-1].tail=child.tail
 return out
def _table_wrap_foot(node):
 out=etree.Element(_tei("div"),type="jats:table-wrap-foot");_mark(out,node)
 notes=etree.SubElement(out,_tei("noteGrp"));notes.text=node.text
 for child in node:
  if _local(child.tag)=="fn":notes.append(_footnote(child))
  else:notes.append(_block(child))
  notes[-1].tail=child.tail
 return out
def _figure(node):
 out=etree.Element(_tei("div"),type="jats:fig");_mark(out,node)
 for child in node:
  tag=_local(child.tag)
  if tag=="graphic":
   carrier=etree.SubElement(out,_tei("div"),type="jats:fig-graphic")
   fig=etree.SubElement(carrier,_tei("figure"))
   graphic=etree.SubElement(fig,_tei("graphic"))
   href=child.get(f"{{{XLINK}}}href")
   if href:graphic.set("url",href)
   _mark(graphic,child)
  elif tag=="caption":out.append(_block(child))
  elif tag=="label":
   head=etree.SubElement(out,_tei("head"));head.text=" ".join("".join(child.itertext()).split());_mark(head,child)
  else:out.append(_block(child))
  out[-1].tail=child.tail
 return out
def _table(node):
 if _local(node.tag)!="table-wrap":return _table_node(node)
 out=etree.Element(_tei("div"),type="jats:table-wrap");_mark(out,node)
 for child in node:
  tag=_local(child.tag)
  if tag=="label":
   label=etree.SubElement(out,_tei("head"));label.text=" ".join("".join(child.itertext()).split());_mark(label,child)
  elif tag=="table":
   carrier=etree.SubElement(out,_tei("div"),type="jats:table")
   carrier.append(_table_node(child))
  else:out.append(_block(child))
  out[-1].tail=child.tail
 return out
def _table_node(table_source):
 table=etree.Element(_tei("table"));_mark(table,table_source)
 def add_rows(container,section=None):
  for child in container:
   tag=_local(child.tag)
   if tag in {"thead","tbody","tfoot"}:add_rows(child,tag)
   elif tag=="tr":
    row=etree.SubElement(table,_tei("row"));_mark(row,child)
    if section:row.set("ana",row.get("ana")+f" urn:ocd:jats-row-section:{section}")
    for c in child:
     ctag=_local(c.tag)
     if ctag in {"td","th"}:
      cell=etree.SubElement(row,_tei("cell"),role="label" if ctag=="th" else "data");_mark(cell,c)
      p=etree.SubElement(cell,_tei("p"));_paragraph_content(p,c)
 add_rows(table_source)
 return table
def _block(node):
 tag=_local(node.tag)
 if tag in INLINE:return _inline(node)
 if tag in HEADS or tag=="p":return _paragraph(node,tag)
 if tag=="fn":return _footnote(node)
 if tag=="table-wrap-foot":return _table_wrap_foot(node)
 if tag=="fig":return _figure(node)
 if tag in {"table","table-wrap"}:return _table(node)
 if tag=="graphic":
  out=etree.Element(_tei("div"),type="jats:graphic");_mark(out,node)
  g=etree.SubElement(out,_tei("figure"));gr=etree.SubElement(g,_tei("graphic"))
  href=node.get(f"{{{XLINK}}}href")
  if href:gr.set("url",href)
  return out
 out=etree.Element(_tei("div"),type=f"jats:{tag}");_mark(out,node)
 _text_run(out,node.text)
 for child in node:
  ctag=_local(child.tag)
  if ctag in INLINE:
   _text_run(out,None,child)
  else:out.append(_block(child))
  _text_run(out,child.tail)
 return out
def _convert(manifest)->Mapping[str,bytes]:
 primary=_authority(manifest,"publisher-xml");xml=manifest.authority_path("publisher-xml").read_bytes()
 if _sha(xml)!=primary["sha256"]:raise ValueError("AJOPS source XML digest drifted")
 source=etree.fromstring(xml,etree.XMLParser(resolve_entities=False,no_network=True,remove_comments=False,huge_tree=True))
 title=" ".join(source.xpath("string((.//article-title)[1])").split())
 doi=" ".join(source.xpath("string((.//article-id[@pub-id-type='doi'])[1])").split())
 root=etree.Element(_tei("TEI"),nsmap={None:TEI});header=etree.SubElement(root,_tei("teiHeader"))
 fd=etree.SubElement(header,_tei("fileDesc"));ts=etree.SubElement(fd,_tei("titleStmt"));etree.SubElement(ts,_tei("title")).text=title
 pub=etree.SubElement(fd,_tei("publicationStmt"));etree.SubElement(pub,_tei("p")).text="Nonaccepted technical reconstruction candidate."
 sd=etree.SubElement(fd,_tei("sourceDesc"));etree.SubElement(sd,_tei("p")).text=f"Publisher JATS XML; DOI {doi}; exact source bytes are bound in the source manifest."
 text=etree.SubElement(root,_tei("text"));body=etree.SubElement(text,_tei("body"));body.append(_block(source))
 tei=etree.tostring(root,encoding="UTF-8",xml_declaration=True,pretty_print=True)
 profile=json.loads(manifest.authority_path("feature-profile").read_text(encoding="utf-8"))
 accountability={"contract":"ocd-ajops-source-accountability-v1","work_id":manifest.record["work_id"],"source_id":manifest.record["source_id"],"primary_xml_sha256":primary["sha256"],"source_element_counts":profile["element_counts"],"text_node_count":profile["text_node_count"],"figure_inventory":profile["figures"],"table_count":profile["table_count"],"note_count":profile["note_count"],"mapping":"Source paths and attributes are bound to marked TEI carriers in source order. Nested table and figure caption paragraphs remain explicit paragraph carriers; table-wrap footnotes remain attached as TEI note groups and notes. Table rows/cells and source-relative figure graphic references are preserved. JATS whitespace-only formatting nodes are excluded; the publisher PDF is the retained visual witness and exact page locators are listed in the profile."}
 prov={"contract":"ocd-ajops-provenance-v1","title":title,"doi":doi,"publisher":"AOSIS","source_formats":["publisher JATS XML","publisher PDF"],"item_license_label":profile["license"]["display_label"],"item_license_uri":profile["license"]["resolved_uri"],"retained_source_hashes":{"publisher-xml":primary["sha256"],"publisher-pdf":_authority(manifest,"publisher-pdf")["sha256"]},"status":"rights clearance and acceptance remain open"}
 unresolved=b"".join(_canon(x) for x in [{"category":"rights","status":"open","claim":"The item-level publisher license is CC BY 4.0; human rights clearance remains open.","doi":doi},{"category":"review","status":"open","claim":"No human acceptance, visual review, integration, or publication is claimed.","doi":doi}])
 if profile["figures"]:
  unresolved+=_canon({"category":"media","status":"open","claim":"Source-relative graphic references are preserved, but standalone figure assets are not retained in this package. The bound publisher PDF supplies the comparison image; a working graphic URL is not claimed.","figures":profile["figures"]})
 return {"README.source.md":profile["attribution_readme"].encode("utf-8"),"content.tei.xml":tei,"provenance.json":_canon(prov),"source-accountability.json":_canon(accountability),"unresolved.jsonl":unresolved}
_convert.converter_id="ocd-ajops-jats-article-to-tei";_convert.converter_version="3"
