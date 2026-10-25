"""Closed ThML standOff source-projection evidence; source-byte fidelity remains a separate oracle gate."""
import json,re
from ocd_kernel.library._common import PipelineError
NS="{http://www.tei-c.org/ns/1.0}"
XML="{http://www.w3.org/XML/1998/namespace}"

def project_evidence(root):
    stand=root.find(NS+"standOff")
    if stand is None:return set()
    if [n.tag for n in root]!=[NS+"teiHeader",NS+"text",NS+"standOff"] or stand.attrib or len(stand)!=1 or (stand.text or "").strip() or (stand.tail or "").strip():raise PipelineError("source-projection document envelope differs")
    listing=stand[0]
    if listing.tag!=NS+"list" or dict(listing.attrib)!={"type":"source-projection"} or (listing.text or "").strip() or (listing.tail or "").strip():raise PipelineError("source-projection list differs")
    ids={}
    for n in root.iter():
        if not isinstance(n.tag,str):raise PipelineError("source-projection in-root non-element")
        identifier=n.get(XML+"id")
        if identifier:
            if identifier in ids:raise PipelineError("source-projection duplicate target ID")
            ids[identifier]=n
    entries={};targets={};ordered=[];children={};reverse={}
    def strict(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise PipelineError("source-projection duplicate JSON key")
            value[key]=item
        return value
    for item in listing:
        if item.tag!=NS+"item" or set(item.attrib)!={"n","corresp"} or len(item) or not item.text or (item.tail or "").strip():raise PipelineError("source-projection item differs")
        try:record=json.loads(item.text,object_pairs_hook=strict)
        except (json.JSONDecodeError,TypeError) as error:raise PipelineError("source-projection invalid JSON") from error
        if not isinstance(record,dict) or set(record)!={"source_key","source_element","source_attributes","source_parent_key","source_ordinal"}:raise PipelineError("source-projection fields differ")
        key=record["source_key"];parent=record["source_parent_key"];ordinal=record["source_ordinal"];tag=record["source_element"];attrs=record["source_attributes"]
        if not isinstance(key,str) or not key or item.get("n")!=key or key in entries or not isinstance(parent,str) or type(ordinal)!=int or ordinal<1 or not isinstance(tag,str) or not tag or not isinstance(attrs,list):raise PipelineError("source-projection record identity differs")
        attr_names=[]
        for pair in attrs:
            if not isinstance(pair,list) or len(pair)!=2 or any(not isinstance(v,str) for v in pair) or not pair[0] or pair[0] in attr_names:raise PipelineError("source-projection ordered attributes differ")
            attr_names.append(pair[0])
        ref=item.get("corresp")
        if not ref or not ref.startswith("#") or not ref[1:] or ref[1:] not in ids or ids[ref[1:]] in reverse:raise PipelineError("source-projection target differs")
        target=ids[ref[1:]]
        if dict(attrs).get("id",ref[1:])!=ref[1:]:raise PipelineError("source-projection literal source ID differs")
        if parent and parent not in entries:raise PipelineError("source-projection parent must precede child")
        siblings=children.setdefault(parent,[])
        if ordinal!=len(siblings)+1:raise PipelineError("source-projection sibling ordinal differs")
        siblings.append(key);entries[key]=record;targets[key]=target;reverse[target]=key;ordered.append(key)
    if not entries or len(children.get("",[]))!=1:raise PipelineError("source-projection requires one source root")
    root_key=children[""][0]
    if entries[root_key]["source_element"]!="ThML" or targets[root_key] is not root:raise PipelineError("source-projection root differs")
    source_roots=children.get(root_key,[])
    if [entries[k]["source_element"] for k in source_roots]!=["ThML.head","ThML.body"]:raise PipelineError("source-projection complete header/body differ")
    head_key,body_key=source_roots
    mapped_head=root.find(NS+"teiHeader/"+NS+"fileDesc/"+NS+"notesStmt/"+NS+"note[@type='retained-ThML-header']/"+NS+"p/"+NS+"seg")
    if mapped_head is None or targets[head_key] is not mapped_head or targets[body_key] is not root.find(NS+"text/"+NS+"body"):raise PipelineError("source-projection mapped header/body locus differs")
    def flatten(n):
        found=[]
        for c in n:
            if c.tag==NS+"div" and c.get("type")=="source-order-wrapper":
                if dict(c.attrib)!={"type":"source-order-wrapper"} or c.text is not None or c.tail is not None or not len(c):raise PipelineError("source-projection order wrapper differs")
                found.extend(list(c))
            else:found.append(c)
        return found
    preorder=[]
    def visit(k):
        preorder.append(k)
        for child in children.get(k,[]):visit(child)
    visit(root_key)
    if preorder!=ordered:raise PipelineError("source-projection record preorder differs")
    body_nodes=set(targets[body_key].iter())
    names={"p":"p","note":"note","i":"hi","b":"hi","sup":"hi","unclear":"unclear","br":"lb","scripRef":"ref","a":"ref","span":"seg","verse":"lg","index":"index","l":"l","ul":"list","li":"item","insertIndex":"anchor","attr":"p","ThML":"TEI","ThML.head":"seg","ThML.body":"body"}
    divs={"div","div1","div2","div3","div4","div5","div6"}
    for key,record in entries.items():
        target=targets[key];tag=record["source_element"]
        expected="div" if tag in divs else names.get(tag,"seg")
        if re.fullmatch(r"h[1-6]",tag):expected="head" if record["source_ordinal"]==1 and entries[record["source_parent_key"]]["source_element"] in divs else "ab"
        # Semantic additions apply only to readable source-body carriers. Header
        # fallback and previously accepted exact neutral carriers remain unchanged.
        body_names={"ol":"list","blockquote":"quote","em":"hi","strong":"hi","img":"graphic","hr":"milestone","scripCom":"anchor"}
        original=dict(record["source_attributes"])
        if target in body_nodes and tag in body_names:
            semantic={XML+"id":target.get(XML+"id")}
            if original.get("class"):semantic["rend"]=original["class"]
            if original.get("style"):semantic["rend"]=(original.get("class","")+"; " if original.get("class") else "")+original["style"]
            if original.get("lang"):semantic[XML+"lang"]=original["lang"]
            if tag=="ol":semantic["type"]="ordered"
            elif tag=="em":semantic["rend"]=original.get("class") or "italic"
            elif tag=="strong":semantic["rend"]="bold"
            elif tag=="img":
                if not original.get("src") or "alt" not in original:raise PipelineError("source-projection image source attributes differ")
                semantic.update(url=original["src"],n=original["alt"])
            elif tag=="hr":semantic["unit"]="horizontal-rule"
            elif tag=="scripCom":semantic.update(type="ThML-scripCom",subtype=original.get("type") or "unspecified",n=original.get("passage", ""))
            if target.tag==NS+"seg":
                legacy={XML+"id":target.get(XML+"id"),"type":"ThML-"+tag}
                if original.get("class"):legacy["rend"]=original["class"]
                if original.get("lang"):legacy[XML+"lang"]=original["lang"]
                if dict(target.attrib)!=legacy:raise PipelineError("source-projection legacy body attributes differ")
            else:
                expected=body_names[tag]
                if dict(target.attrib)!=semantic:raise PipelineError("source-projection native body attributes differ")
        if target in body_nodes and tag=="div" and target.tag==NS+"ab":
            parent_key=record["source_parent_key"]
            descendants=list(children.get(key,[]))
            cursor=0
            while cursor<len(descendants):
                descendants.extend(children.get(descendants[cursor],[]));cursor+=1
            wanted={XML+"id":original.get("id"),"type":"source-inline-container","rend":"margin-left: 2em"}
            if (set(original)!={"id","style"} or original.get("style")!="margin-left: 2em"
                    or not parent_key or entries[parent_key]["source_element"]!="li"
                    or targets[parent_key].tag!=NS+"item" or target not in list(targets[parent_key])
                    or not descendants or any(entries[d]["source_element"] not in {"b","br"} for d in descendants)
                    or dict(target.attrib)!=wanted):raise PipelineError("source-projection inline container differs")
            expected="ab"

        # Preserve the exact older neutral carriers while supporting native inline semantics.
        # This exception is restricted to the two retained source names and exact legacy attributes.
        if tag in {"b","unclear"} and target in body_nodes and target.tag==NS+"seg":
            original=dict(record["source_attributes"])
            legacy={XML+"id":target.get(XML+"id"),"type":"ThML-"+tag}
            if original.get("class"):legacy["rend"]=original["class"]
            if dict(target.attrib)!=legacy:raise PipelineError("source-projection legacy inline attributes differ")
            expected="seg"
        if target.tag!=NS+expected:raise PipelineError("source-projection mapped target tag differs")
        if key!=root_key and flatten(target)!=[targets[k] for k in children.get(key,[])]:raise PipelineError("source-projection child attachment/order differs")
    mapped_nodes=set(mapped_head.iter())
    if not mapped_nodes.issubset(reverse):raise PipelineError("source-projection orphan header descendant")
    for node in mapped_nodes:
        record=entries[reverse[node]];tag=record["source_element"];attrs=dict(record["source_attributes"])
        expected={XML+"id":node.get(XML+"id")}
        if attrs.get("class"):expected["rend"]=attrs["class"]
        if tag=="i":expected["rend"]=attrs.get("class") or "italic"
        elif tag=="ThML.head":expected["type"]="retained-ThML-header"
        elif tag!="br":expected["type"]="ThML-"+tag
        if node.tag not in {NS+"seg",NS+"hi",NS+"lb"} or dict(node.attrib)!=expected:raise PipelineError("source-projection mapped header attributes differ")
    for node in targets[body_key].iter():
        if node not in reverse and not (node.tag==NS+"div" and dict(node.attrib)=={"type":"source-order-wrapper"}):raise PipelineError("source-projection orphan body descendant")
    return set(stand.iter())|mapped_nodes

def observe_evidence(root):
    """Independently observe the lxml tree; never calls the producer function."""
    stand=root.find(NS+"standOff")
    if stand is None:return set()
    if [n.tag for n in root]!=[NS+"teiHeader",NS+"text",NS+"standOff"] or stand.attrib or len(stand)!=1 or (stand.text or "").strip() or (stand.tail or "").strip():raise ValueError("source-projection document envelope differs")
    listing=stand[0]
    if listing.tag!=NS+"list" or dict(listing.attrib)!={"type":"source-projection"} or (listing.text or "").strip() or (listing.tail or "").strip():raise ValueError("source-projection list differs")
    ids={}
    for n in root.iter():
        if not isinstance(n.tag,str):raise ValueError("source-projection in-root non-element")
        identifier=n.get(XML+"id")
        if identifier:
            if identifier in ids:raise ValueError("source-projection duplicate target ID")
            ids[identifier]=n
    entries={};targets={};ordered=[];children={};reverse={}
    def strict(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError("source-projection duplicate JSON key")
            value[key]=item
        return value
    for item in listing:
        if item.tag!=NS+"item" or set(item.attrib)!={"n","corresp"} or len(item) or not item.text or (item.tail or "").strip():raise ValueError("source-projection item differs")
        try:record=json.loads(item.text,object_pairs_hook=strict)
        except (json.JSONDecodeError,TypeError) as error:raise ValueError("source-projection invalid JSON") from error
        if not isinstance(record,dict) or set(record)!={"source_key","source_element","source_attributes","source_parent_key","source_ordinal"}:raise ValueError("source-projection fields differ")
        key=record["source_key"];parent=record["source_parent_key"];ordinal=record["source_ordinal"];tag=record["source_element"];attrs=record["source_attributes"]
        if not isinstance(key,str) or not key or item.get("n")!=key or key in entries or not isinstance(parent,str) or type(ordinal)!=int or ordinal<1 or not isinstance(tag,str) or not tag or not isinstance(attrs,list):raise ValueError("source-projection record identity differs")
        attr_names=[]
        for pair in attrs:
            if not isinstance(pair,list) or len(pair)!=2 or any(not isinstance(v,str) for v in pair) or not pair[0] or pair[0] in attr_names:raise ValueError("source-projection ordered attributes differ")
            attr_names.append(pair[0])
        ref=item.get("corresp")
        if not ref or not ref.startswith("#") or not ref[1:] or ref[1:] not in ids or ids[ref[1:]] in reverse:raise ValueError("source-projection target differs")
        target=ids[ref[1:]]
        if dict(attrs).get("id",ref[1:])!=ref[1:]:raise ValueError("source-projection literal source ID differs")
        if parent and parent not in entries:raise ValueError("source-projection parent must precede child")
        siblings=children.setdefault(parent,[])
        if ordinal!=len(siblings)+1:raise ValueError("source-projection sibling ordinal differs")
        siblings.append(key);entries[key]=record;targets[key]=target;reverse[target]=key;ordered.append(key)
    if not entries or len(children.get("",[]))!=1:raise ValueError("source-projection requires one source root")
    root_key=children[""][0]
    if entries[root_key]["source_element"]!="ThML" or targets[root_key] is not root:raise ValueError("source-projection root differs")
    source_roots=children.get(root_key,[])
    if [entries[k]["source_element"] for k in source_roots]!=["ThML.head","ThML.body"]:raise ValueError("source-projection complete header/body differ")
    head_key,body_key=source_roots
    mapped_head=root.find(NS+"teiHeader/"+NS+"fileDesc/"+NS+"notesStmt/"+NS+"note[@type='retained-ThML-header']/"+NS+"p/"+NS+"seg")
    if mapped_head is None or targets[head_key] is not mapped_head or targets[body_key] is not root.find(NS+"text/"+NS+"body"):raise ValueError("source-projection mapped header/body locus differs")
    def flatten(n):
        found=[]
        for c in n:
            if c.tag==NS+"div" and c.get("type")=="source-order-wrapper":
                if dict(c.attrib)!={"type":"source-order-wrapper"} or c.text is not None or c.tail is not None or not len(c):raise ValueError("source-projection order wrapper differs")
                found.extend(list(c))
            else:found.append(c)
        return found
    preorder=[]
    def visit(k):
        preorder.append(k)
        for child in children.get(k,[]):visit(child)
    visit(root_key)
    if preorder!=ordered:raise ValueError("source-projection record preorder differs")
    body_nodes=set(targets[body_key].iter())
    names={"p":"p","note":"note","i":"hi","b":"hi","sup":"hi","unclear":"unclear","br":"lb","scripRef":"ref","a":"ref","span":"seg","verse":"lg","index":"index","l":"l","ul":"list","li":"item","insertIndex":"anchor","attr":"p","ThML":"TEI","ThML.head":"seg","ThML.body":"body"}
    divs={"div","div1","div2","div3","div4","div5","div6"}
    for key,record in entries.items():
        target=targets[key];tag=record["source_element"]
        expected="div" if tag in divs else names.get(tag,"seg")
        if re.fullmatch(r"h[1-6]",tag):expected="head" if record["source_ordinal"]==1 and entries[record["source_parent_key"]]["source_element"] in divs else "ab"
        # Semantic additions apply only to readable source-body carriers. Header
        # fallback and previously accepted exact neutral carriers remain unchanged.
        body_names={"ol":"list","blockquote":"quote","em":"hi","strong":"hi","img":"graphic","hr":"milestone","scripCom":"anchor"}
        original=dict(record["source_attributes"])
        if target in body_nodes and tag in body_names:
            semantic={XML+"id":target.get(XML+"id")}
            if original.get("class"):semantic["rend"]=original["class"]
            if original.get("style"):semantic["rend"]=(original.get("class","")+"; " if original.get("class") else "")+original["style"]
            if original.get("lang"):semantic[XML+"lang"]=original["lang"]
            if tag=="ol":semantic["type"]="ordered"
            elif tag=="em":semantic["rend"]=original.get("class") or "italic"
            elif tag=="strong":semantic["rend"]="bold"
            elif tag=="img":
                if not original.get("src") or "alt" not in original:raise ValueError("source-projection image source attributes differ")
                semantic.update(url=original["src"],n=original["alt"])
            elif tag=="hr":semantic["unit"]="horizontal-rule"
            elif tag=="scripCom":semantic.update(type="ThML-scripCom",subtype=original.get("type") or "unspecified",n=original.get("passage", ""))
            if target.tag==NS+"seg":
                legacy={XML+"id":target.get(XML+"id"),"type":"ThML-"+tag}
                if original.get("class"):legacy["rend"]=original["class"]
                if original.get("lang"):legacy[XML+"lang"]=original["lang"]
                if dict(target.attrib)!=legacy:raise ValueError("source-projection legacy body attributes differ")
            else:
                expected=body_names[tag]
                if dict(target.attrib)!=semantic:raise ValueError("source-projection native body attributes differ")
        if target in body_nodes and tag=="div" and target.tag==NS+"ab":
            parent_key=record["source_parent_key"]
            descendants=list(children.get(key,[]))
            cursor=0
            while cursor<len(descendants):
                descendants.extend(children.get(descendants[cursor],[]));cursor+=1
            wanted={XML+"id":original.get("id"),"type":"source-inline-container","rend":"margin-left: 2em"}
            if (set(original)!={"id","style"} or original.get("style")!="margin-left: 2em"
                    or not parent_key or entries[parent_key]["source_element"]!="li"
                    or targets[parent_key].tag!=NS+"item" or target not in list(targets[parent_key])
                    or not descendants or any(entries[d]["source_element"] not in {"b","br"} for d in descendants)
                    or dict(target.attrib)!=wanted):raise ValueError("source-projection inline container differs")
            expected="ab"

        # Preserve the exact older neutral carriers while supporting native inline semantics.
        # This exception is restricted to the two retained source names and exact legacy attributes.
        if tag in {"b","unclear"} and target in body_nodes and target.tag==NS+"seg":
            original=dict(record["source_attributes"])
            legacy={XML+"id":target.get(XML+"id"),"type":"ThML-"+tag}
            if original.get("class"):legacy["rend"]=original["class"]
            if dict(target.attrib)!=legacy:raise ValueError("source-projection legacy inline attributes differ")
            expected="seg"
        if target.tag!=NS+expected:raise ValueError("source-projection mapped target tag differs")
        if key!=root_key and flatten(target)!=[targets[k] for k in children.get(key,[])]:raise ValueError("source-projection child attachment/order differs")
    mapped_nodes=set(mapped_head.iter())
    if not mapped_nodes.issubset(reverse):raise ValueError("source-projection orphan header descendant")
    for node in mapped_nodes:
        record=entries[reverse[node]];tag=record["source_element"];attrs=dict(record["source_attributes"])
        expected={XML+"id":node.get(XML+"id")}
        if attrs.get("class"):expected["rend"]=attrs["class"]
        if tag=="i":expected["rend"]=attrs.get("class") or "italic"
        elif tag=="ThML.head":expected["type"]="retained-ThML-header"
        elif tag!="br":expected["type"]="ThML-"+tag
        if node.tag not in {NS+"seg",NS+"hi",NS+"lb"} or dict(node.attrib)!=expected:raise ValueError("source-projection mapped header attributes differ")
    for node in targets[body_key].iter():
        if node not in reverse and not (node.tag==NS+"div" and dict(node.attrib)=={"type":"source-order-wrapper"}):raise ValueError("source-projection orphan body descendant")
    return set(stand.iter())|mapped_nodes
