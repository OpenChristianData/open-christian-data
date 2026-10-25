"""Read explicitly structured XML bodies without executing source markup."""
from xml.etree import ElementTree as ET

from cvw_app.renderer_nodes import _node, _local_name, _finalize_structure, _heading_contexts, project_visible_text


def legacy_tei_book(exact):
    if '<TEI.2' not in exact:
        return None
    from lxml import etree
    from cvw_app.tei_renderer import render_tei

    try:
        root=etree.fromstring(exact.encode('utf8'),etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
    except etree.XMLSyntaxError:
        return None
    if root.tag != 'TEI.2':
        return None
    entities=[element for element in root.iter() if isinstance(element,etree._Entity)]
    if entities:
        import hashlib
        # This retained witness's registered converter explicitly maps mdash.
        greenleaf_sha='b2a42f1d0e23563887e310d8465c298c6434eed35df1e4a4ff27b924feb16fe7'
        if hashlib.sha256(exact.encode('utf8')).hexdigest()!=greenleaf_sha or any(e.name!='mdash' for e in entities):
            return None
        for entity in entities:
            parent=entity.getparent()
            previous=entity.getprevious()
            value='—'+(entity.tail or '')
            if previous is None:
                parent.text=(parent.text or '')+value
            else:
                previous.tail=(previous.tail or '')+value
            parent.remove(entity)
    if any(not isinstance(element.tag,str) for element in root.iter()):
        return None
    metadata=[]
    for element in list(root):
        if _local_name(element.tag)=='pgExtensions':
            metadata.append(etree.tostring(element,encoding='unicode'))
            root.remove(element)
    root.tag='TEI'
    for element in root.iter():
        if element.get('id'):
            element.set('{http://www.w3.org/XML/1998/namespace}id',element.attrib.pop('id'))
    rendered=render_tei('application/tei+xml',etree.tostring(root,encoding='unicode'))
    if not metadata:
        return rendered
    nodes=rendered['nodes']+[_node('details','About this source',children=[_node('preformatted',value) for value in metadata])]
    result=_finalize_structure('tei-reader',nodes,rendered['outline'],_heading_contexts(nodes,rendered['outline'],include_nested=True))
    result['limitations']=rendered.get('limitations',[])
    return result


def jats_tei_book(root):
    articles=[element for element in root.iter() if element.get('type')=='jats:article']
    if len(articles)!=1:
        return None

    def restore(element):
        kind=element.get('type','')
        if kind=='jats:text-run':
            return ''.join(''.join(child.itertext()) for child in element)
        native=not kind.startswith('jats:')
        if native:
            name=_local_name(element.tag)
            if name not in {'p','head','hi','ref'}:
                raise ValueError('Unknown JATS transcription node')
            tag=(element.get('rend') or '').removeprefix('jats:') if name=='hi' else 'span'
            if tag not in {'italic','bold','sup','sub'}:
                tag='span'
        else:
            tag=kind.removeprefix('jats:')
        restored=ET.Element(tag)
        if native:
            restored.text=element.text
        for child in element:
            value=restore(child)
            if isinstance(value,str):
                if len(restored):
                    restored[-1].tail=(restored[-1].tail or '')+value
                else:
                    restored.text=(restored.text or '')+value
            else:
                if native:
                    value.tail=child.tail
                restored.append(value)
        return restored
    try:
        return render_xml_book(restore(articles[0]))
    except ValueError:
        return None


def render_xml_book(root):
    vocabulary = _local_name(root.tag).lower()
    nodes, outline = [], []

    def heading(label, location):
        nodes.append(_node("heading", label, level=2, location=location))
        outline.append(dict(location=location, label=label, level=2))

    if vocabulary == "djvuxml":
        for number, page in enumerate((e for e in root.iter() if _local_name(e.tag).upper() == "OBJECT"), 1):
            heading(f"Page {number}", f"page-{number}")
            for line in page.iter():
                if _local_name(line.tag).upper() == "LINE":
                    nodes.append(_node("paragraph", project_visible_text(" ".join("".join(word.itertext()) for word in line if _local_name(word.tag).upper() == "WORD"))))
    elif vocabulary == "mediawiki":
        pages=[e for e in root if _local_name(e.tag)=="page"]
        page_texts=any(next((e.text for e in page if _local_name(e.tag)=="ns"),None)=="104" for page in pages)
        support=[]
        for number, page in enumerate(pages, 1):
            title = next((e.text for e in page if _local_name(e.tag) == "title"), None)
            texts = [e for e in page.iter() if _local_name(e.tag) == "text"]
            if not title or len(texts) != 1:
                return None
            namespace=next((e.text for e in page if _local_name(e.tag)=="ns"),None)
            text_node=_node("preformatted", texts[0].text or "")
            if page_texts and namespace!="104":
                support.append(_node("details",f"Wiki source details: {title}",children=[text_node]))
            else:
                heading(title, f"page-{number}")
                nodes.append(text_node)
        nodes.extend(support)
    elif vocabulary in {"article", "ets"}:
        from cvw_app.review_renderers import _SafeHtmlNodes, _thml_body_markup

        selected = ([e for e in root.iter() if _local_name(e.tag) in {"article-title", "abstract"}]
                    + [e for e in root if _local_name(e.tag) in {"body", "back"}]) if vocabulary == "article" else [e for e in root.iter() if _local_name(e.tag).upper() == "TEXT"]
        wrapper = ET.Element("div")
        for element in selected:
            wrapper.append(element)
        for element in wrapper.iter():
            tag = _local_name(element.tag).lower()
            element.tag = {"title": "h2", "article-title": "h1", "head": "h2", "div1": "section", "div2": "section", "div3": "section", "hi": "em", "italic": "em", "bold": "strong", "xref": "span", "q": "blockquote", "lb": "br"}.get(tag, tag)
            if tag == "gap" and not element.text:
                element.text = element.get("DISP") or element.get("disp") or "[gap]"
        parser = _SafeHtmlNodes(native_divisions=True)
        parser.feed(_thml_body_markup(wrapper))
        parser.close()
        nodes, outline = parser.nodes, parser.outline
    if not nodes:
        return None
    return _finalize_structure("xml-reader", nodes, outline, _heading_contexts(nodes, outline))
