"""Unexecuted L811 native leaf proposal for the maintained reader owner.

This is a work-specific draft, not a registered reader or accepted projection.
It uses existing native-content schema kinds and distinguishes critical roles.
No source reference is normalized to scripture or resolved against a guessed
base. Independent maintained observation/verification is still required.
"""
from collections import Counter
from hashlib import sha256
import json
import re

from lxml import etree

NS = 'http://www.tei-c.org/ns/1.0'
XML = '{http://www.w3.org/XML/1998/namespace}'
IDENTITY = dict(work_id='eusebius-commentarii-in-psalmos', textual_form_id='pta-english',
                edition_id='pta-ef861ab3-commentarii-psalmos')
SOURCE_TEI_SHA = '29d0845997301ec67aef8625d5014b402ffe552590296db2ca65742944db0697'
# A separately reviewed header proposal supplies this pin after release.
# An arbitrary caller-supplied master digest must never authorize this route.
REVIEWED_ACCEPTED_MASTER_SHA = 'b67b84fe42425800cabcd99f923e26d866b34f4123e37d65dca8e0922577acae'
PROFILE = 'ocd-prose-eusebius-l811-pta-three-tome-critical-v1'
KINDS = {
    'body': 'body', 'div': 'division', 'p': 'paragraph', 'head': 'heading',
    'quote': 'quotation-block', 'l': 'verse-line', 'list': 'list', 'item': 'list-item',
    'note': 'note', 'hi': 'emphasis', 'emph': 'emphasis', 'foreign': 'foreign-text',
    'gap': 'gap', 'pb': 'page-break', 'ref': 'source-reference', 'anchor': 'anchor',
    'bibl': 'bibliographic-label', 'title': 'work-title', 'persName': 'person-name',
    'placeName': 'segment', 'orgName': 'segment', 'num': 'segment', 'seg': 'segment',
    'mentioned': 'segment', 'supplied': 'segment', 'unclear': 'uncertain-text',
    'add': 'segment', 'del': 'segment', 'surplus': 'segment', 'milestone': 'source-marker',
    'app': 'source-block', 'rdgGrp': 'source-block', 'lem': 'segment', 'rdg': 'segment',
    'witDetail': 'note', 'witStart': 'source-marker', 'witEnd': 'source-marker',
    'lacunaStart': 'source-marker', 'lacunaEnd': 'source-marker',
}
ROLES = {
    'app': 'critical-apparatus', 'rdgGrp': 'variant-reading-group',
    'lem': 'lemma', 'rdg': 'variant-reading', 'witDetail': 'witness-detail',
    'witStart': 'witness-start', 'witEnd': 'witness-end',
    'lacunaStart': 'lacuna-start', 'lacunaEnd': 'lacuna-end',
    'add': 'source-addition', 'del': 'source-deletion', 'supplied': 'supplied-text',
    'surplus': 'surplus-text', 'ref': 'literal-source-reference',
    'mentioned': 'mentioned-source-text', 'milestone': 'source-milestone',
}
REFERENCE_ATTRIBUTES = {'corresp', 'decls', 'edRef', 'target', 'targetEnd', 'wit',
                        'resp', 'copyOf', 'next', 'prev', 'source', 'ref', 'cRef', 'rendition', 'n'}
PUBLIC_LITERAL_ATTRIBUTES = {'type', 'subtype', 'n', 'rend', 'place', 'reason',
                             'quantity', 'unit', 'break', 'anchored', 'varSeq'}
FEATURES = {'add':19,'anchor':707,'app':4950,'bibl':85,'body':1,'del':13,'div':1346,
            'emph':116,'foreign':26,'gap':90,'head':166,'hi':70,'item':8,'l':7718,
            'lacunaEnd':9,'lacunaStart':10,'lem':4712,'list':2,'mentioned':1020,
            'milestone':2,'note':1330,'num':451,'orgName':336,'p':4038,'pb':1078,
            'persName':2090,'placeName':443,'quote':16382,'rdg':5606,'rdgGrp':17,
            'ref':8810,'seg':220,'supplied':168,'surplus':6,'title':180,'unclear':6,
            'witDetail':156,'witEnd':102,'witStart':122}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def source_object_ledger(root):
    """All actual header/text/comment fields, including empty versus absent values."""
    rows = []
    def visit(node, path, parent, position):
        if isinstance(node, etree._Comment):
            name, kind = '#comment', 'comment'
        elif isinstance(node, etree._ProcessingInstruction):
            name, kind = node.target, 'processing-instruction'
        else:
            name, kind = node.tag, 'element'
        rows.append(dict(path=path, parent=parent, position=position, node_kind=kind,
                         expanded_tag=name, attributes=list(node.attrib.items()),
                         namespace_bindings=list(node.nsmap.items()), text=node.text,
                         tail=node.tail))
        for ordinal, child in enumerate(node):
            visit(child, path + [ordinal], path, ordinal)
    visit(root, [], None, 0)
    return rows


def public_reference_context(root, body):
    """Actual targets only; header context closes references without false sigla."""
    ids = {}
    for node in root.iter():
        identifier = node.get(XML+'id')
        if identifier:
            if identifier in ids:
                raise ValueError('Duplicate actual L811 ID')
            ids[identifier] = node
    body_nodes = set(body.iter())
    body_ids = {identifier for identifier, node in ids.items() if node in body_nodes}
    header_targets = set()
    unbound = []
    def references(nodes, location, *, collect=True):
        found = set()
        for node in nodes:
            for key, value in node.attrib.items():
                if key not in REFERENCE_ATTRIBUTES:
                    continue
                for token in value.split():
                    if not token.startswith('#'):
                        continue
                    if token[1:] in ids:
                        found.add(token[1:])
                    elif collect:
                        unbound.append(dict(location=location, tag=str(node.tag), attribute=key,
                                            literal=token, disposition='unbound-source-literal-not-a-public-anchor'))
        return found
    body_targets = references(body.iter(), 'body')
    header_targets.update(body_targets - body_ids)
    expected_ids = 1278 if root.find('{%s}teiHeader/{%s}revisionDesc/{%s}change[@{%s}id="eusebius-l811-retained-complete-20261004-v1"]' % (NS,NS,NS,'http://www.w3.org/XML/1998/namespace')) is not None else 1277
    if len(ids) != expected_ids or len(body_ids) != 1135 or len(header_targets) != 58:
        raise ValueError('Actual ID/body/header target denominator differs')
    initial_targets = set(header_targets)
    # Retained context can itself cite another actual header target. Close that
    # finite support graph rather than emit a mapped link to a missing anchor.
    while True:
        roots = [node for identifier, node in ids.items() if identifier in header_targets
                 and not any(parent.get(XML+'id') in header_targets for parent in node.iterancestors())]
        context_set = {n for node in roots for n in node.iter()}
        context_nodes = [n for n in root.iter() if n in context_set]
        needed = references(context_nodes, 'header-context', collect=False) - body_ids
        if needed <= header_targets:
            break
        header_targets.update(needed)
    references(context_nodes, 'header-context')
    context_ids = {identifier for identifier, node in ids.items() if node in context_set}
    aliases = {identifier: 'PgL811' + identifier.encode('utf-8').hex()
               for identifier in ids if identifier in body_ids | context_ids}
    if len(set(aliases.values())) != len(aliases):
        raise ValueError('Noninjective public ID map')
    return aliases, roots, unbound, dict(actual_ids=len(ids), body_ids=len(body_ids),
                                        initial_body_header_targets=len(initial_targets),
                                        closed_header_targets=len(header_targets),
                                        displayed_header_ids=len(context_ids))


def native(node, aliases, *, context=False):
    """Nested mixed content preserves direct text/child/tail order without joins."""
    if isinstance(node, (etree._Comment, etree._ProcessingInstruction)):
        return dict(kind='source-marker', attributes=dict(source_role='source-administration-node'), content=[])
    qname = etree.QName(node)
    if qname.namespace != NS or (qname.localname not in KINDS and not context):
        raise ValueError('Unreviewed L811 native carrier: ' + str(node.tag))
    tag = qname.localname
    source_role = 'retained-header-' + tag if context else ROLES.get(tag, 'source-' + tag)
    safe = {key: value for key, value in node.attrib.items() if key in PUBLIC_LITERAL_ATTRIBUTES}
    qualified = []
    for key, value in node.attrib.items():
        if key not in REFERENCE_ATTRIBUTES:
            continue
        def mapped(match):
            token = match.group()
            if token.startswith('#') and token[1:] in aliases:
                return '#' + aliases[token[1:]]
            if token.startswith('#'):
                qualified.append(dict(attribute=key, literal=token,
                                      disposition='unbound-source-literal-not-a-public-anchor'))
            return token
        safe[key] = re.sub(r'\S+', mapped, value)
    attributes = dict(source_role=source_role,
                      source_annotations=encoded(dict(source_element=tag, fields=safe,
                                                       qualified_reference_literals=qualified)))
    if node.get(XML+'id'):
        attributes['source_anchor'] = aliases[node.get(XML+'id')]
    for source, target in [(XML+'lang','language'),('n','number'),('type','type'),
                           ('subtype','subtype'),('place','place'),('rend','style'),
                           ('rendition','rendition'),('anchored','anchored')]:
        if source in node.attrib:
            attributes[target] = safe[source] if source in REFERENCE_ATTRIBUTES else node.attrib[source]
    if 'target' in node.attrib:
        attributes['source_target'] = safe['target']
    if 'cRef' in node.attrib:
        attributes['reference'] = safe['cRef']  # Opaque Greek-source literal.
    elif 'ref' in node.attrib:
        attributes['reference'] = safe['ref']
    content = []
    if node.text:
        content.append(dict(kind='text', text=node.text))
    for child in node:
        content.append(native(child, aliases, context=context))
        if child.tail:
            content.append(dict(kind='text', text=child.tail))
    return dict(kind=KINDS.get(tag, 'source-block'), attributes=attributes, content=content)


def proposed_leaf(raw, *, identity, language, category, collection, source_base,
                  accepted=False):
    """Static implementation, awaiting independent reader review and execution."""
    expected = REVIEWED_ACCEPTED_MASTER_SHA if accepted else SOURCE_TEI_SHA
    if (expected is None or sha256(raw).hexdigest() != expected or identity != IDENTITY
            or language != 'grc' or category != 'prose' or collection
            or source_base is not None):
        raise ValueError('L811 leaf requires exact reviewed identity/master and no inferred base')
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_blank_text=False, remove_comments=False)
    root = etree.fromstring(raw, parser)
    if root.tag != '{%s}TEI' % NS or root.getroottree().docinfo.doctype:
        raise ValueError('L811 exact TEI envelope differs')
    text = root.find('{%s}text' % NS)
    body = text.find('{%s}body' % NS) if text is not None else None
    if body is None:
        raise ValueError('L811 text/body missing')
    census = Counter(etree.QName(n).localname for n in body.iter() if isinstance(n.tag, str))
    if dict(census) != FEATURES:
        raise ValueError('L811 entire actual body feature denominator differs')
    volumes = list(body)
    if len(volumes) != 3 or [(n.tag,n.get('type'),n.get('n')) for n in volumes] != [
            ('{%s}div' % NS,'volume','Tome I'), ('{%s}div' % NS,'volume','Tome II'),
            ('{%s}div' % NS,'volume','Tome III')]:
        raise ValueError('L811 ordered three-tome boundaries differ')
    ledger = source_object_ledger(root)
    aliases, context_roots, unbound, reference_census = public_reference_context(root, body)
    support = dict(kind='source-block', attributes=dict(source_role='retained-header-reference-context'),
                   content=[native(n, aliases, context=True) for n in context_roots])
    native_body = native(body, aliases)
    return dict(contract='ocd-l811-native-leaf-proposal-v1', profile=PROFILE,
                complete_authored_works=1, proposed_prose_rows=1,
                native_body=native_body, native_header_reference_context=support,
                ordered_tome_labels=[n.get('n') for n in volumes],
                public_anchor_map=aliases, reference_census=reference_census,
                unresolved_literal_qualification=unbound,
                private_actual_object_ledger=ledger,
                private_ledger_sha256=sha256(encoded(ledger).encode('utf-8')).hexdigest(),
                source_feature_census=dict(census), scripture_normalizations=[],
                display_requirement='Render nested lemma, variant-reading and witness roles distinctly; never concatenate apparatus readings as a preferred commentary reading.',
                qualifications='Exact retained electronic three-tome edition; source I/II work in progress, source III approved; Greek Psalm labels remain literal.')
