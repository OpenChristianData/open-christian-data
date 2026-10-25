"""Bind the whole source-titled Gangulf hymn to retained bsb754 authority."""
from __future__ import annotations
import json
from hashlib import sha256
from pathlib import Path
from lxml import etree
from ocd_kernel.tei.install_accepted import _io_path
ROOT=Path(__file__).resolve().parents[2]
WORK_ID="hymnus-sancti-gangulfi"
SOURCE=Path("raw/openmgh/bsb00000754/tei/bsb00000754.xml")
SOURCE_SHA="3349fbef5e7e957e964433d097e94a4a35d84addcbd6a314a88819e6a53039ff"
RECEIPT=Path("raw/openmgh/bsb00000754/acquisition-receipt.json")
RECEIPT_SHA="67f23305c57ba40d40f351393c3dd7408b36bbcdaeef27113fb6bd2b7ee0eeb2"
HOME=SIDE_HOME=Path("sources/openmgh-bsb754-gangulf-hymn")
BATCH=HOME/"frozen-selection.json"
BATCH_SHA="ab1ef5cc4369d3f3e0685137add0bb1cf564243dad725de16453ff4597fe7220"
PRODUCER=Path("build/tei/gangulf_hymn_reconstruction.py")
ORACLE=Path("build/tei/gangulf_hymn_oracle.py")
CONTRACT=Path("ocd_kernel/reconstruction/contract.py")
LONG_PATH=Path("ocd_kernel/tei/install_accepted.py")
XSD=Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
SCHEMA=Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
TEI="{http://www.tei-c.org/ns/1.0}"
XML_ID="{http://www.w3.org/XML/1998/namespace}id"
FIRST="bsb00000754_00180_8"
LAST="bsb00000754_00180_29"
OLD_LAST="bsb00000754_00184_24"
SCOPE="The complete five-stanza Gangulf hymn in retained bsb00000754, volume work division 5, part 2, ab children 0 through 25 inclusive, from II at00180_8 through Amen at00180_29; the separately titled following Vita beginning00180_30 and all other volume content are excluded. Both column markers and target anchors are included."
QUALIFICATION="The literal hymn heading starts [HYMNUS DE GLORIOSISSIMO CHRISTI MARTIRE GENGULFO. with an opening bracket; its closing bracket occurs in the following excluded Vita heading. No closing bracket, corrected spelling, or neighboring text is invented. The existing catalog work title is an identity label; the retained source heading and wording remain exact."
def _json(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def _sha(p):return sha256(_io_path(p).read_bytes()).hexdigest()
def _read(p):return json.loads(_io_path(p).read_bytes())
def _write_once(p,b):
    q=_io_path(p);q.parent.mkdir(parents=True,exist_ok=True)
    if q.exists() and q.read_bytes()!=b:raise ValueError(f"existing Gangulf authority differs: {p}")
    q.write_bytes(b)
def _authority(name,p,role):
    b=_io_path(ROOT/p).read_bytes();return dict(name=name,path=p.as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def prepare():
    if _sha(ROOT/SOURCE)!=SOURCE_SHA or _sha(ROOT/RECEIPT)!=RECEIPT_SHA or _sha(ROOT/BATCH)!=BATCH_SHA:raise ValueError("retained hymn authority changed")
    source=etree.fromstring(_io_path(ROOT/SOURCE).read_bytes(),etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    if source.getroottree().docinfo.doctype:raise ValueError("DOCTYPE forbidden")
    volume=source.find(f"{TEI}text/{TEI}body/{TEI}div")
    if volume is None or len(volume)!=20 or volume[4].get("n")!="Vita Gangulfi" or len(volume[4])!=2:raise ValueError("source envelope changed")
    carrier=volume[4][1][0]
    if carrier.tag!=TEI+"ab" or len(carrier)!=192 or carrier[0].get(XML_ID)!=FIRST or carrier[25].get(XML_ID)!=LAST or not (carrier[25].tail or "").endswith("Amen.\n") or not (carrier[26].tail or "").startswith("INCIPIT VITA SEU ACTUS"):raise ValueError("hymn/Vita boundary changed")
    work_rel=Path("library/works")/WORK_ID/"work.json";work=_read(ROOT/work_rel);form=work["textual_forms"][0];edition=form["editions"][0]
    if len(work["textual_forms"])!=1 or len(form["editions"])!=1 or len(edition["acquisition_ids"])!=1:raise ValueError("ambiguous hymn identity")
    acquisition_rel=work_rel.parent/"forms"/form["textual_form_id"]/"editions"/edition["edition_id"]/"acquisitions"/(edition["acquisition_ids"][0]+".json")
    a=_read(ROOT/acquisition_rel)
    if a["source_path"]!=SOURCE.as_posix() or a["source_sha256"]!=SOURCE_SHA:raise ValueError("wrong textual authority")
    start,end=edition["containing_source"]["locator"].split("; ")
    if start!=SOURCE.as_posix()+"#"+FIRST or end not in (SOURCE.as_posix()+"#"+OLD_LAST,SOURCE.as_posix()+"#"+LAST):raise ValueError("catalog locator changed")
    selected=list(carrier)[:26];selection_hash=sha256(b"".join(etree.tostring(e,method="c14n",with_comments=True,with_tail=True) for e in selected)).hexdigest()
    boundary=dict(contract="ocd-gangulf-hymn-boundary-v1",work_id=WORK_ID,source_path=SOURCE.as_posix(),source_sha256=SOURCE_SHA,source_division_ordinal=5,source_part_ordinal=2,native_type="part-excerpt",start_xml_id=FIRST,end_xml_id=LAST,catalog_start_xml_id=FIRST,catalog_end_xml_id=LAST,original_catalog_end_xml_id=OLD_LAST,selection_c14n_sha256=selection_hash,source_qualification=QUALIFICATION,shared_matter_disposition="Source electronic publication and print bibliography are preserved. Volume identity remains in sourceDesc; other works/parts remain retained outside the hymn.",unassigned_fragment_disposition="The following independently titled Vita and its closing title bracket remain source-owned outside this hymn; the historical endpoint is inside that Vita.",volume_inventory=[dict(position=i+1,attributes=dict(e.attrib),children=len(e),c14n_sha256=sha256(etree.tostring(e,method="c14n",with_comments=True)).hexdigest(),disposition="hymn excerpt only" if i==4 else "other work excluded") for i,e in enumerate(volume)],carrier_inventory=[dict(position=i,tag=etree.QName(e).localname,attributes=dict(e.attrib),tail=e.tail,c14n_sha256=sha256(etree.tostring(e,method="c14n",with_comments=True,with_tail=True)).hexdigest(),disposition="hymn included" if i<26 else "following Vita excluded") for i,e in enumerate(carrier)],stanza_start_ids=["bsb00000754_00180_"+str(n) for n in (10,14,18,22,26)],column_spans=[dict(marker_position=2,number="1",spanTo="#cb20",anchor_position=11),dict(marker_position=12,number="2",spanTo="#cb21",anchor_position=21)])
    home=HOME/WORK_ID;bp=home/"boundary-review.json";pp=home/"reconstruction-profile.json";mp=home/"source-manifest.json"
    _write_once(ROOT/bp,_json(boundary));profile=dict(boundary,contract="ocd-gangulf-hymn-profile-v1",work_title=work["title"],edition_id=edition["edition_id"],acquisition_id=a["acquisition_id"],acquisition_path=acquisition_rel.as_posix(),acquisition_sha256=_sha(ROOT/acquisition_rel));_write_once(ROOT/pp,_json(profile))
    policy=dict(contract="ocd-gangulf-hymn-policy-v1",status="nonaccepted",closure_inputs=[p.as_posix() for p in (ORACLE,CONTRACT,LONG_PATH)],forbidden_oracle_imports=["build.tei.gangulf_hymn_reconstruction"],checks=["entire source envelope and carrier disposition","independent title/Amen/next-Vita boundary","recursive mixed tree and physical column span preservation","stanza number/line association","literal title bracket and source spelling","header publication and bibliography","local span closure","P5 XSD"]);_write_once(ROOT/HOME/"validation-policy.json",_json(policy))
    closure=[dict(path=p,sha256=_sha(ROOT/p)) for p in policy["closure_inputs"]]
    manifest=dict(contract="ocd-source-manifest-v1",source_id=WORK_ID+"-bsb754-electronic-v1",authorities=[_authority("extracted-xml",SOURCE,"primary-source"),_authority("work-sidecar",work_rel,"identity"),_authority("boundary-review",bp,"inspected-source-boundary"),_authority("reconstruction-profile",pp,"complete-source-feature-profile"),_authority("validation-policy",HOME/"validation-policy.json","independent-validation-policy"),_authority("tei-p5-xsd",XSD,"tei-validation-schema"),_authority("candidate-package-schema",SCHEMA,"candidate-package-schema")],converter=dict(id="ocd-gangulf-hymn-to-tei",version="1",callable="_convert",implementation_path=PRODUCER.as_posix(),implementation_sha256=_sha(ROOT/PRODUCER)),validator=dict(id="ocd-gangulf-hymn-source-oracle",version="1",callable="_oracle",implementation_path=ORACLE.as_posix(),implementation_sha256=_sha(ROOT/ORACLE),import_closure_sha256=sha256(_json(closure)).hexdigest()),package_schema=dict(path=SCHEMA.as_posix(),sha256=_sha(ROOT/SCHEMA)));_write_once(ROOT/mp,_json(manifest));return dict(work_id=WORK_ID,manifest_sha256=_sha(ROOT/mp),boundary_sha256=_sha(ROOT/bp))
if __name__=="__main__":print(json.dumps(prepare()))
