"""Repair confirmed entity/graphic losses and relative links in existing MTP TEI."""
from pathlib import Path
from hashlib import sha256
from xml.sax.saxutils import escape,quoteattr
import json,sys,importlib.util,re,shutil
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage,validate
from lxml import etree
TASK=ROOT/'.tmp_audit/spurgeon-mtp-install';LOG=ROOT/'reports/_logs/spurgeon-mtp-retained-install-20261003-v1'
ORIGINAL=Path('build/tei/spurgeon_mtp_oracle.py');SUCCESSOR=Path('build/tei/spurgeon_mtp_install_20261003_oracle.py')
MANIFEST=Path('sources/spurgeon-mtp/spurgeon-mtp.source-manifest.install-20261003-v1.json')
PROFILE=Path('sources/spurgeon-mtp/spurgeon-mtp.reconstruction-profile.install-20261003-v1.json')
IMAGE_POLICY='Outside the selected sermon 1698 region, non-textual site images remain excluded. All 27 selected sermon 1698 images are represented as literal TEI graphic carriers at source native parent and break/inline/block boundaries, preserving surrounding text and tails.'
REPAIR_POLICY=dict(source_path='raw/spurgeon_sermons/missing/1698.html',source_sha256='27496a547db664fcbe5dd1306a812bb010513a65b9875bf6eef9da3b55c7cd36',entity_repair=dict(literal='&#151;',count=12,html5_reading='U+2014 EM DASH',literal_controls_unchanged=True),graphic_count=27,source_base='https://archive.spurgeon.org/',attribute_mapping={'src':'graphic@url','alt':'graphic@n','align':'graphic@rend source-align-LEFT','BASE.href':'graphic@xml:base'},placement='Native parent and break/inline/block events under existing libxml recovery, with generated wrappers transparent.',asset_status='Not retained; exact pointers preserved; no inferred glyph or visual interpretation.',recovery_qualification='For graphics 8 through 27, HTML5 retains FONT ancestry while libxml exposes selected-root children. HTML5 DOM ancestry and rendered font inheritance are not claimed equivalent.',other_3549_sermons='Exact existing body bytes unchanged.')
LINK_BASES={708:'https://answersingenesis.org/education/spurgeon-sermons/708-the-blood-of-abel-and-the-blood-of-jesus/',1698:'https://archive.spurgeon.org/',3032:'https://answersingenesis.org/education/spurgeon-sermons/3032-form-of-this-world/'}
REPAIR_POLICY.pop('other_3549_sermons')
REPAIR_POLICY.update(relative_source_links=dict(count=12,changed_sermons=[708,1698,3032],source_contexts={str(k):v for k,v in LINK_BASES.items()},source_authority='Retained canonical link for 708/3032; retained BASE for 1698.',operation='Only add per-ref xml:base; literal targets and all text/structure remain unchanged; one absolute link remains unchanged.'),other_3547_sermons='Exact existing body bytes unchanged.')
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
def digest(raw):return sha256(raw).hexdigest()
def encoded(obj):return (json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def save(path,obj):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(encoded(obj))
def module():
    spec=importlib.util.spec_from_file_location('_mtp_repaired_oracle',ROOT/SUCCESSOR);value=importlib.util.module_from_spec(spec);sys.modules[spec.name]=value;spec.loader.exec_module(value);return value
def code():
    original=(ROOT/ORIGINAL).read_bytes();assert digest(original)=='22192d3181150c9a3a7487ec73953754cf65ba2ee2eec03720d00ba29135d5f4'
    text=original.decode();text=text.replace(ORIGINAL.as_posix(),SUCCESSOR.as_posix())
    text=text.replace('    "ocd_kernel/__init__.py",\n','    "ocd_kernel/__init__.py",\n    "ocd_kernel/lib/__init__.py",\n    "ocd_kernel/lib/path_io.py",\n    "ocd_kernel/lib/storage_topology.py",\n',1)
    definition='def _evidence_region(path: Path, number: int) -> tuple[etree._Element, str]:\n'
    old=definition+'    page = html.document_fromstring(path.read_bytes())\n'
    new=definition+'''    retained = path.read_bytes()
    if number == 1698 and path.parent.name == "missing":
        # Exact retained numeric references have the independently confirmed
        # HTML5 em-dash reading. Literal source control characters are untouched.
        if retained.count(b"&#151;") != 12:
            raise ValueError("Spurgeon 1698 numeric-reference repair scope drifted")
        retained = retained.replace(b"&#151;", b"&#8212;")
    page = html.document_fromstring(retained)
'''
    assert text.count(old)==1;text=text.replace(old,new,1)
    old='    structure = profile.get("structure_policy")\n'
    new='''    if profile.get("bounded_retained_repair") != REPAIR_POLICY or profile.get("source_selection", {}).get("excluded_elements", {}).get("img") != IMAGE_POLICY or profile.get("structure_policy", {}).get("tei_mapping", {}).get("img") != "graphic":
        raise ValueError("Spurgeon bounded retained graphic/entity repair policy drifted")
    structure = profile.get("structure_policy")
'''
    assert text.count(old)==1;text=text.replace(old,new,1)
    text+='\nREPAIR_POLICY = '+repr(REPAIR_POLICY)+'\nIMAGE_POLICY = '+repr(IMAGE_POLICY)+'\n'
    old='    return sermon\n\n\ndef _validate_complete_sermon_tree('
    new='    if number == 1698:\n        _insert_1698_source_graphics(source, sermon)\n    return sermon\n\n\ndef _validate_complete_sermon_tree('
    assert text.count(old)==1;text=text.replace(old,new,1)
    text += '''

def _insert_1698_source_graphics(source, sermon):
    """Keep the fixed 27 graphics at source native structure boundaries.

    Existing mapped carriers, whitespace and tails remain intact. The retained
    BASE element is independently bound by the caller's exact source authority;
    relative graphic URLs remain literal. No absent asset glyph is inferred.
    """
    mapped = {}
    ordinal = 0
    for node in source.iter():
        if node is source or str(node.tag).lower() in _SKIP:
            continue
        ordinal += 1
        mapped[node] = sermon.xpath('.//*[@xml:id=$id]', namespaces={'xml':'http://www.w3.org/XML/1998/namespace'}, id=f'spurgeon-1698-source-{ordinal:06d}')[0]
    images = source.xpath('.//img')
    if len(images) != 27:
        raise ValueError("Spurgeon 1698 graphic envelope drifted")
    wrappers = {}
    index = 0
    for child in source:
        if str(child.tag).lower() in _SKIP and not child.tail:
            continue
        wrappers[child] = sermon[index]
        index += 1
    if index != len(sermon):
        raise ValueError('Spurgeon 1698 generated wrapper census drifted')
    for ordinal, image in enumerate(images, 1):
        attributes = dict(image.attrib)
        if attributes not in ({"src":"images/indent.gif", "alt":"    "}, {"src":"images/s.gif", "align":"LEFT"}):
            raise ValueError("Spurgeon 1698 graphic attributes drifted")
        attrs = {"url":attributes["src"], "{http://www.w3.org/XML/1998/namespace}base":"https://archive.spurgeon.org/", _XML_ID:f"spurgeon-1698-image-{ordinal:06d}", "rend":"source-layout-spacer" if attributes["src"] == "images/indent.gif" else "source-initial-letter source-align-LEFT"}
        if "alt" in attributes:
            attrs["n"] = attributes["alt"]
        graphic = _tei_element("graphic", attrs)
        parent = image.getparent()
        if parent is source:
            wrapper = wrappers.get(image)
            if wrapper is None:
                following = image.getnext()
                if following is None:
                    raise ValueError('Spurgeon image has no represented boundary')
                wrapper = wrappers[following]
            owner = wrapper[0]
            field = 'text'
            prefix = ''
        else:
            previous = image.getprevious()
            if previous is None:
                owner, field, prefix = mapped[parent], 'text', parent.text or ''
            else:
                owner, field, prefix = mapped[previous], 'tail', previous.tail or ''
        value = getattr(owner, field) or ''
        if not value.startswith(prefix):
            raise ValueError('Spurgeon source graphic text boundary drifted')
        setattr(owner, field, prefix or None)
        graphic.tail = value[len(prefix):] or None
        if field == 'text':
            owner.insert(0, graphic)
        else:
            owner.getparent().insert(owner.getparent().index(owner)+1, graphic)
'''
    old='        if number in rights_evidence:\n            expected_record["witness_rights"] = rights_evidence[number]\n'
    new='''        if number == 1698:
            graphics = region.xpath(".//img")
            if len(graphics) != 27:
                raise ValueError("Spurgeon 1698 graphic source envelope drifted")
            expected_record["represented_graphics"] = [
                {"position": i, "source_attributes": dict(node.attrib),
                 "tei_xml_id": f"spurgeon-1698-image-{i:06d}",
                 "source_base": "https://archive.spurgeon.org/",
                 "asset_status": "not-retained; pointer preserved; no visual interpretation"}
                for i, node in enumerate(graphics, 1)
            ]
        if number in rights_evidence:
            expected_record["witness_rights"] = rights_evidence[number]
'''
    assert text.count(old)==1;text=text.replace(old,new,1)
    # Add only URI context; source hrefs remain literal and text/structure exact.
    original_return='    return sermon'+chr(10)+chr(10)+chr(10)+'def _validate_complete_sermon_tree('
    assert text.count(original_return)==1
    text=text.replace(original_return,'    _bind_supplemental_source_links(sermon, number)'+chr(10)+original_return,1)
    attribute='"tei_attributes": _expected_tei_attributes(node),'
    assert text.count(attribute)==1
    text=text.replace(attribute,'"tei_attributes": dict(_expected_tei_attributes(node), **({"base": LINK_BASES[number]} if source_tag == "a" and number in LINK_BASES and (node.get("href") or "").startswith("/") else {})),',1)
    text+=chr(10)+'LINK_BASES = '+repr(LINK_BASES)+chr(10)+'''
def _bind_supplemental_source_links(sermon, number):
    if number not in LINK_BASES:
        return
    count = 0
    for node in sermon.iter('{http://www.tei-c.org/ns/1.0}ref'):
        if node.get('type') == 'source-link' and (node.get('target') or '').startswith('/'):
            node.set('{http://www.w3.org/XML/1998/namespace}base', LINK_BASES[number])
            count += 1
    if count != {708:6,1698:1,3032:5}[number]:
        raise ValueError('Spurgeon retained relative source-link count drifted')
'''
    provenance_anchor='        "retained_source_bytes_embedded": False,\n'
    assert text.count(provenance_anchor)==1
    text=text.replace(provenance_anchor,provenance_anchor+'        "bounded_repair": _bounded_repair_producer(source_manifest),\n',1)
    text+='''

def _bounded_repair_producer(source_manifest):
    authority = next(a for a in source_manifest.record['authorities'] if a['name'] == 'bounded-repair-implementation')
    return dict(
        id='ocd-spurgeon-mtp-existing-bounded-retained-repair',
        implementation={k:authority[k] for k in ('path','sha256','bytes')},
        command='py -3 build/tei/spurgeon_mtp_install_20261003_repair.py',
        historical_package_sha256='3d4d2e37fcc1b83ec6543592582b15c1f3e68c6086201a95f6a270d52b677c88',
        historical_package_path='reports/_logs/spurgeon-mtp-retained-install-20261003-v1/retained-original-package',
        historical_package_members=[{k:a[k] for k in ('path','sha256','bytes')} for a in sorted(source_manifest.record['authorities'],key=lambda a:a['name']) if a['name'].startswith('historical-package-')],
        historical_tei_sha256='f0b9550fda2127a42b280aa634cbc402eadc37b8dd3acd48eed6f7d74687e3a8',
        historical_converter=dict(source_manifest.record['converter']),
        manifest_converter_role='Preserved historical input lineage; not the sole producer of the current repaired package.',
        recipe='Read the exact historical candidate package; interpret only twelve retained numeric references as em dashes and attach twenty-seven literal source graphic carriers in sermon 1698; add only twelve source-attested ref xml:base attributes in sermons 708, 1698 and 3032; refresh manifest and provenance bindings; preserve all other 3547 sermon bytes and prove the exact whole-TEI inverse. No download or fresh source conversion.',
        repair_policy=dict(REPAIR_POLICY))
'''
    (ROOT/SUCCESSOR).write_text(text,encoding='utf-8',newline='\n')
    save(LOG/'successor-code-repair.json',dict(status='prepared',original_oracle_sha256=digest(original),successor_oracle_sha256=digest(text.encode()),source_semantic_changes=['exactly twelve retained &#151; references in missing/1698.html interpreted as em dash, leaving literal controls untouched','all twenty-seven selected 1698 graphics retained at source attachment with literal URL, source-attested BASE, source alt in n and source align in rend','exact graphic envelope required in member accounting','twelve relative source links receive only per-ref xml:base from retained canonical/BASE URLs; all literal targets and text/structure preserved'],global_runtime_unchanged=True))
def prepare(destination=None,verify=True):
    census=json.loads((LOG/'independent-source-readback.json').read_bytes())
    entities=census['selected_region_c1_numeric_references'];assert len(entities)==12 and all(e['entity']=='&#151;' and e['sermon_number']=='1698' for e in entities)
    assert len(census['selected_region_images'])==27 and all(e['sermon_number']=='1698' for e in census['selected_region_images'])
    original_profile=(ROOT/'sources/spurgeon-mtp/spurgeon-mtp.reconstruction-profile.json').read_bytes()
    assert digest(original_profile)=='4715e3d5be8a070243045773f8df0e8c0394e7ddadab7952685e912f816a7a9e'
    profile=json.loads(original_profile);profile['source_selection']['excluded_elements']['img']=IMAGE_POLICY
    profile['structure_policy']['required_html_carriers'].append('img');profile['structure_policy']['tei_mapping']['img']='graphic';profile['bounded_retained_repair']=REPAIR_POLICY
    save(ROOT/PROFILE,profile)
    code();oracle=module()
    m=json.loads((ROOT/MANIFEST).read_bytes());m['validator'].update(implementation_sha256=digest((ROOT/SUCCESSOR).read_bytes()),import_closure_sha256=oracle._import_closure(ROOT))
    for authority in m['authorities']:
        if authority['name'] in ('reconstruction-profile','validation-policy'):authority.update(path=PROFILE.as_posix(),bytes=len((ROOT/PROFILE).read_bytes()),sha256=digest((ROOT/PROFILE).read_bytes()))
    recipe_path=Path('build/tei/spurgeon_mtp_install_20261003_repair.py');recipe_bytes=(ROOT/recipe_path).read_bytes()
    historical=CandidatePackage.load(LOG/'retained-original-package')
    assert historical.sha256=='3d4d2e37fcc1b83ec6543592582b15c1f3e68c6086201a95f6a270d52b677c88'
    m['authorities']=[a for a in m['authorities'] if a['name']!='bounded-repair-implementation' and not a['name'].startswith('historical-package-')]
    m['authorities'].append(dict(name='bounded-repair-implementation',role='producer-implementation',path=recipe_path.as_posix(),bytes=len(recipe_bytes),sha256=digest(recipe_bytes)))
    for member_name in historical.member_names:
        raw=historical.member_bytes(member_name);relative=(LOG/'retained-original-package'/member_name).relative_to(ROOT)
        m['authorities'].append(dict(name='historical-package-'+member_name,role='historical-input-lineage',path=relative.as_posix(),bytes=len(raw),sha256=digest(raw)))
    save(ROOT/MANIFEST,m)
    save(LOG/'profile-successor-reconciliation.json',dict(status='pass',original_profile_sha256=digest(original_profile),successor_profile_path=PROFILE.as_posix(),successor_profile_sha256=digest((ROOT/PROFILE).read_bytes()),changed_fields=['source_selection.excluded_elements.img','structure_policy.required_html_carriers append img','structure_policy.tei_mapping.img','bounded_retained_repair'],bounded_policy=REPAIR_POLICY,canonical_profile_unchanged=True))
    source=historical;original=source.member_bytes('content.tei.xml')
    marker=b'xml:id="spurgeon-mtp-1698"';start=max(original.rfind(b'<div',0,original.index(marker)),original.rfind(b'<ns0:div',0,original.index(marker)));nextmark=original.index(b'xml:id="spurgeon-mtp-1699"');end=max(original.rfind(b'<div',0,nextmark),original.rfind(b'<ns0:div',0,nextmark))
    old=original[start:end];assert old.count(b'\xc2\x97')==12 and b'\xe2\x80\x94' not in old
    fragment=old.replace(b'\xc2\x97',b'\xe2\x80\x94')
    path=ROOT/'raw/spurgeon_sermons/missing/1698.html';raw_source=path.read_bytes()
    assert b'<BASE HREF="https://archive.spurgeon.org/">' in raw_source
    region,selection=oracle._evidence_region(path,1698)
    from html import unescape
    actual=etree.fromstring(fragment)
    assert etree.tostring(actual,encoding='UTF-8')==fragment, 'Existing sermon lexical serialization must remain exact'
    oracle._insert_1698_source_graphics(region,actual)
    oracle._bind_supplemental_source_links(actual,1698)
    fragment=etree.tostring(actual,encoding='UTF-8')
    generated=[];repairs=[]
    for i,image in enumerate(census['selected_region_images'],1):
        source_attrs=image['attributes'];offset=image['text_position_nonwhitespace']
        role='source-layout-spacer' if source_attrs['src']=='images/indent.gif' else 'source-initial-letter source-align-LEFT'
        attrs=dict(url=source_attrs['src'],**{'xml:base':'https://archive.spurgeon.org/','xml:id':f'spurgeon-1698-image-{i:06d}'},rend=role)
        if 'alt' in source_attrs:attrs['n']=source_attrs['alt']
        node=actual.xpath('.//t:graphic[@xml:id=$id]',namespaces={'t':'http://www.tei-c.org/ns/1.0','xml':'http://www.w3.org/XML/1998/namespace'},id=f'spurgeon-1698-image-{i:06d}')[0]
        serialized=etree.tostring(node,with_tail=False)
        # Local serialization includes an inherited declaration absent from the
        # original lexical sermon. Use the exact emitted start/end carrier.
        marker=(f'xml:id="spurgeon-1698-image-{i:06d}"').encode()
        at=fragment.index(marker);begin=fragment.rfind(b'<',0,at);carrier_end=fragment.index(b'/>',at)+2
        graphic=fragment[begin:carrier_end];generated.append(graphic)
        repairs.append(dict(position=i,text_position_nonwhitespace=offset,source_attributes=source_attrs,tei_attributes=attrs,source_base='https://archive.spurgeon.org/',asset_status='not-retained; source pointer preserved; no image text inferred'))
    restored=fragment
    for graphic in generated:
        assert restored.count(graphic)==1;restored=restored.replace(graphic,b'',1)
    restored=restored.replace(b' xml:base="https://archive.spurgeon.org/"',b'')
    restored=restored.replace(b'\xe2\x80\x94',b'\xc2\x97');assert restored==old
    repaired=original[:start]+fragment+original[end:];assert len(generated)==27
    sermon_repairs=[dict(number=1698,original_sha256=digest(old),repaired_sha256=digest(fragment),relative_links=1,inverse_exact=True)]
    for number in (708,3032):
        marker=(f'xml:id="spurgeon-mtp-{number:04d}"').encode();at=repaired.index(marker);s=repaired.rfind(b'<ns0:div',0,at)
        nextmark=repaired.index((f'xml:id="spurgeon-mtp-{number+1:04d}"').encode());e=repaired.rfind(b'<ns0:div',0,nextmark)
        before=repaired[s:e];node=etree.fromstring(before);assert etree.tostring(node,encoding='UTF-8')==before
        oracle._bind_supplemental_source_links(node,number);after=etree.tostring(node,encoding='UTF-8')
        token=(' xml:base="'+LINK_BASES[number]+'"').encode();assert after.count(token)=={708:6,3032:5}[number]
        assert after.replace(token,b'')==before
        repaired=repaired[:s]+after+repaired[e:]
        sermon_repairs.append(dict(number=number,original_sha256=digest(before),repaired_sha256=digest(after),relative_links=after.count(token),inverse_exact=True))
    inverse=repaired
    for graphic in generated:inverse=inverse.replace(graphic,b'',1)
    for base in LINK_BASES.values():inverse=inverse.replace((' xml:base="'+base+'"').encode(),b'')
    im=inverse.index(b'xml:id="spurgeon-mtp-1698"');is_=inverse.rfind(b'<ns0:div',0,im);imnext=inverse.index(b'xml:id="spurgeon-mtp-1699"');ie=inverse.rfind(b'<ns0:div',0,imnext)
    inverse=inverse[:is_]+inverse[is_:ie].replace(b'\xe2\x80\x94',b'\xc2\x97')+inverse[ie:]
    assert inverse==original
    destination=destination or LOG/'repaired-package';destination.mkdir(parents=True,exist_ok=True)
    manifest=SourceManifest.load(ROOT/MANIFEST,repository_root=ROOT)
    for name in source.member_names:
        if name=='manifest.json':continue
        data=source.member_bytes(name)
        if name=='content.tei.xml':data=repaired
        elif name=='provenance.json':
            value=json.loads(data);value['source_manifest_sha256']=manifest.sha256;value['profile_sha256']=digest((ROOT/PROFILE).read_bytes());value['bounded_repair']=oracle._bounded_repair_producer(manifest);data=encoded(value)
        elif name=='source-accountability.json':
            value=json.loads(data);record=next(x for x in value['members'] if x.get('number')==1698)
            events=oracle._source_events(region,1698)
            record.update(normalized_text_sha256=digest(oracle._text(region).encode()),mapped_structure_sha256=digest(oracle._canonical(events)),represented_graphics=[dict(position=i,source_attributes=dict(n.attrib),tei_xml_id=f'spurgeon-1698-image-{i:06d}',source_base='https://archive.spurgeon.org/',asset_status='not-retained; pointer preserved; no visual interpretation') for i,n in enumerate(region.xpath('.//img'),1)])
            for number in (708,3032):
                scoped,_=oracle._evidence_region(ROOT/f'raw/spurgeon_sermons/missing/{number}.html',number)
                entry=next(x for x in value['members'] if x.get('number')==number)
                entry['mapped_structure_sha256']=digest(oracle._canonical(oracle._source_events(scoped,number)))
            data=encoded(value)
        (destination/name).write_bytes(data)
    package_record=json.loads(source.member_bytes('manifest.json'));package_record['source_manifest']=dict(path=MANIFEST.as_posix(),sha256=manifest.sha256)
    for member in package_record['members']:
        data=(destination/member['name']).read_bytes();member.update(bytes=len(data),sha256=digest(data))
    save(destination/'manifest.json',package_record)
    save(LOG/'source-backed-body-repair.json',dict(status='pass',source_path='raw/spurgeon_sermons/missing/1698.html',source_sha256=digest(raw_source),original_candidate_sha256=digest(original),repaired_candidate_sha256=digest(repaired),original_sermon_sha256=digest(old),repaired_sermon_sha256=digest(fragment),entity_occurrences=entities,graphics=repairs,changed_sermons=[708,1698,3032],sermon_repairs=sermon_repairs,relative_source_links=12,source_link_bases={str(k):v for k,v in LINK_BASES.items()},all_other_retained_source_and_body_bytes_unchanged=True,inverse_restores_entire_original_tei=True,asset_bytes_not_retained=True))
    print(json.dumps(dict(status='bounded-body-repair',entities=12,graphics=27,relative_links=12,unchanged_sermons=3547)),flush=True)
    package=CandidatePackage.load(destination)
    if not verify:
        print(json.dumps(dict(status='fresh-repair-replay',package_sha256=package.sha256)),flush=True);return
    report=validate(manifest,package,oracle._oracle)
    save(LOG/'repaired-current-validation.json',dict(contract='ocd-validation-report-v1',status=report.status,candidate_sha256=report.candidate_sha256,source_manifest_sha256=report.source_manifest_sha256,attestation=dict(report.attestation),findings=list(report.findings),report_sha256=report.sha256))
    assert report.status=='pass',report.findings
    print(json.dumps(dict(status='repaired-full-oracle-pass',report_sha256=report.sha256)),flush=True)
if __name__=='__main__':
    if len(sys.argv)==1:prepare()
    else:
        assert sys.argv[1] in ('replay-1','replay-2')
        prepare(TASK/sys.argv[1],verify=False)
