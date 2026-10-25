"""Transient readable work scope; original artifact bytes remain the exact view.

Shared credit notes are displayed as labeled source context after the work.
This projection never writes TEI or produces literary dataset rows.
"""
import copy
from xml.etree import ElementTree as ET

from cvw_app.review_renderers import RendererError


def selected_reader_input(exact: str, kind: str, selection: dict | None) -> str:
    if selection is None and kind != 'tei-reader':
        return exact
    if kind == 'tei-reader' and 'source_selection_sha256' not in exact:
        return exact
    try:
        tree = ET.fromstring(exact)
    except ET.ParseError as exc:
        raise RendererError(f'selected reading XML is malformed: {exc}') from exc
    if kind == 'xml-reader' and selection is not None:
        if tree.tag != 'ThML':
            raise RendererError('selected source reader requires ThML')
        body = tree.find('ThML.body')
        if body is None:
            raise RendererError('selected source body is absent')
        copied = []
        for unit in selection['units']:
            matches = [n for n in body if n.get('id') == unit['native_id']]
            if len(matches) != 1 or matches[0].get('title') != unit['title']:
                raise RendererError('selected source division differs')
            copied.append(copy.deepcopy(matches[0]))
        credits = ET.Element('div1', {'id':'cvw-source-context', 'title':'Shared source credits (source-level attribution)'})
        for dependency in selection['dependencies']:
            matches = [n for n in tree.iter() if n.get('id') == dependency['native_id']]
            if len(matches) != 1:
                raise RendererError('selected source dependency differs')
            credits.append(copy.deepcopy(matches[0]))
        body.clear()
        body.extend(copied)
        if len(credits):
            body.append(credits)
        return ET.tostring(tree, encoding='unicode')
    if kind == 'tei-reader':
        ns = {'t':'http://www.tei-c.org/ns/1.0'}
        if not tree.findall('./t:teiHeader//t:idno[@type="source_selection_sha256"]',ns):
            return exact
        credits = tree.findall('./t:teiHeader//t:note[@type="source-credit"]',ns)
        if not credits:
            return exact
        text = tree.find('t:text',ns)
        if text is None:
            raise RendererError('selected TEI text is absent')
        q = '{' + ns['t'] + '}'
        back = text.find(q+'back')
        if back is None:
            back = ET.SubElement(text,q+'back')
        div = ET.SubElement(back,q+'div', {'{http://www.w3.org/XML/1998/namespace}id':'cvw-source-context'})
        ET.SubElement(div,q+'head').text = 'Shared source credits (source-level attribution)'
        for note in credits:
            ET.SubElement(div,q+'p').text = ''.join(note.itertext())
        return ET.tostring(tree,encoding='unicode')
    return exact
