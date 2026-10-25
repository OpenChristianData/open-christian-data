"""Isolated exact-work maintained wrapper proposal, not installed or executed.

Validate actual promoted acceptance/full 11680-member scope before any leaf.
No generic one-member assumption and no source reconstruction module imports.
"""
from pathlib import Path
from collections import Counter
import hashlib,json
from ocd_kernel.library._common import PipelineError

IDENTITY={'work_id':'catholic-encyclopedia-vol01','textual_form_id':'catholic-encyclopedia-vol01-retained-en','edition_id':'catholic-encyclopedia-vol01-retained-electronic'}
ACQUISITION='catholic-encyclopedia-vol01-acquired-member-set'
MASTER_SHA='5d9bd4892220a40418c5c04cf9421f6a1e40fc8232da06df2dc5796ad460fa33'
SOURCE_SHA='159e69948931054b0496e4a4b79a6f22d497a65d6b460a09520d3ca007cc353a'
POLICY_SHA='999ae9c02989c957b08e4b73f9764d57d39cb7389cae5ebd107cda30a9f475c4'
REVISION='lib025-newadvent-retained-complete-20261004-v1'
COUNTS={'encyclopedia-entry':11632,'encyclopedia-index':48,'unavailable-source-register':1}
CONTRACT='ocd-lib025-native-reference-receipt-v1'

def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
def fail(condition,message):
    if not condition:raise PipelineError(message)
def output_sha(rows):
    h=hashlib.sha256();h.update(b'[')
    for i,row in enumerate(rows):
        if i:h.update(b',')
        h.update(canonical(row))
    h.update(b']');return h.hexdigest()

def metadata(root,acceptance_path):
    from ocd_kernel.tei.acceptance import validate_acceptance
    from ocd_kernel.library.identities import edition_by_id
    from ocd_kernel.library.acquisitions import acquisition_for_edition
    from ocd_kernel.projection.categories.catechisms import _accepted_bound_file,_accepted_local_binding
    base=Path(root).resolve();accepted_path=Path(acceptance_path).resolve()
    accepted=validate_acceptance(accepted_path,root=base)
    fail(accepted['promotion']['status']=='promoted','Native reference projection requires actual promoted acceptance')
    fail(accepted['identity']=={**IDENTITY,'acquisition_id':ACQUISITION},'Native reference exact accepted identity differs')
    work,edition=edition_by_id(base,IDENTITY['edition_id'], work_id=IDENTITY["work_id"])
    fail(work.work_id==IDENTITY['work_id'] and edition.textual_form_id==IDENTITY['textual_form_id'],'Canonical native reference identity differs')
    fail(edition.record.get('category')=='reference-entries' and edition.record.get('language')=='en','Native reference category/language differs')
    fail(accepted['representation_revision']['id']==REVISION,'Native reference revision differs')
    acq_path,acq=acquisition_for_edition(base,IDENTITY['work_id'],IDENTITY['edition_id'],acquisition_id=ACQUISITION)
    source=accepted['source'];scope=accepted['scope']
    fail(acq.get('source_kind')==source.get('source_kind')=='retained-member-set','Native reference requires retained member-set acquisition')
    fail(source['source_sha256']==acq['source_sha256']==SOURCE_SHA and source['source_bytes']==3946037,'Native reference descriptor binding differs')
    fail(source['source_path']==acq['source_path'] and acq['url']=='https://www.newadvent.org/cathen/','Native reference descriptor/URL differs')
    ordered=acq['retained_files'];included=sorted(scope['included_members'],key=lambda m:m['position']);expected=sorted(scope['expected_members'],key=lambda m:m['position'])
    fail(len(ordered)==len(included)==len(expected)==11680 and not scope['excluded_members'],'Native reference scope contracts retained HTML envelope')
    fail([m['path'] for m in expected]==[m['path'] for m in included]==[m['path'] for m in ordered],'Native reference HTML source order differs')
    fail(all(a['sha256']==b['sha256'] and a['bytes']==b['bytes'] for a,b in zip(included,ordered,strict=True)),'Native reference included member bindings differ')
    fail(not source['missing_members'] and not source['unknown_members'],'Already downloaded retained members cannot be marked unavailable')
    # Failed requests outside the downloaded member set remain preserved in the
    # qualified bridge/body register. They do not shrink included HTML members.
    descriptor_path=base/source['source_path']
    fail(digest(descriptor_path)==SOURCE_SHA,'Native reference descriptor bytes differ')
    master=Path(edition.path).resolve();fail(digest(master)==MASTER_SHA,'Exact reviewed native master differs')
    accounting_path,accounting_binding=_accepted_bound_file(base,source['accounting'],field='source.accounting')
    fail(accounting_path.stat().st_size<=64*1024*1024,'Native accounting must be member-bound qualified bridge, not whole historic accounting DOM')
    accounting=json.loads(accounting_path.read_text(encoding='utf-8'))
    fail(accounting.get('native_reference_profile')=='lib025-complete-retained-native-units-v1','Native accounting profile differs')
    fail(accounting.get('identity')==accepted['identity'] and accounting.get('native_reference_scope')==scope['declared'],'Native accounting identity/native scope differs')
    fail(accounting.get('native_unit_counts')==COUNTS and accounting.get('html_member_count')==11680,'Native accounting source/native denominators differ')
    fail(accounting.get('support_authority_counts')=={'images':378,'stylesheet':1} and accounting.get('preserved_global_failure_entries')==17 and accounting.get('preserved_body_image_gaps')==9,'Native accounting support/gap scopes differ')
    fail(accounting.get('policy_sha256')==POLICY_SHA and accounting.get('historical_source_execution_admitted') is False,'Native accounting policy/runtime qualification differs')
    proof=accounting.get('qualified_proof_reuse')
    fail(isinstance(proof,dict),'Qualified source proof reuse bridge is missing')
    proof_path,proof_binding=_accepted_bound_file(base,proof,field='source.accounting.qualified_proof_reuse')
    proof_doc=json.loads(proof_path.read_text(encoding='utf-8'))
    fail(proof_doc.get('current_source_execution_admitted') is False or proof_doc.get('status')=='proposed-not-admitted','Source closure must not be admitted by reuse bridge')
    fail(proof_doc.get('runtime_qualification') and proof_doc.get('source_converter_oracle_replayed') is False,'Source proof bridge qualifications differ')
    authority={'acceptance':_accepted_local_binding(base,accepted_path,field='acceptance'),'work':_accepted_local_binding(base,work.path,field='work'),'master':_accepted_local_binding(base,master,field='master'),'acquisition':_accepted_local_binding(base,acq_path,field='acquisition'),'source_accounting':accounting_binding,'qualified_source_proof_reuse':proof_binding,'retained_member_set_descriptor':_accepted_local_binding(base,descriptor_path,field='retained-member-set-descriptor')}
    schema=base/'schemas/v2/categories/reference-entries.schema.json';common=base/'schemas/v2/public-row.schema.json';native=base/'schemas/v2/native-content.schema.json'
    return {'root':base,'accepted':accepted,'master':master,'edition_title':edition.title,'scope':scope['declared'],'source_location':source['source_path'],'authority':authority,'schemas':{'schema_sha256':digest(schema),'common_schema_sha256':digest(common),'native_content_schema_sha256':digest(native)}}

def row_context(meta,unit,private):
    seq=unit['sequence']
    return {'record_id':IDENTITY['work_id']+'::'+IDENTITY['edition_id']+'::native-reference-unit:'+str(seq),'representation_revision':REVISION,'locator':{'kind':'native-reference-unit','text_part':'body','unit':seq},'provenance':{'edition_title':meta['edition_title'],'source_title':unit['source_title'],'source_url':private['source_url'] or 'https://www.newadvent.org/cathen/','source_location':meta['source_location'],'source_credit':'New Advent Catholic Encyclopedia web transcription; article-local credits preserved in source structure.'}}

def iter_rows_from_metadata(meta):
    from .lib025_native_reference import iter_proposed_units
    counts=Counter()
    for record in iter_proposed_units(meta['master'],identity=IDENTITY,accepted=True):
        unit=record['public_unit'];counts[unit['unit_kind']]+=1
        yield {**unit,**row_context(meta,unit,record['private_receipt'])},record['private_receipt']
    fail(dict(counts)==COUNTS,'Actual complete native unit-kind totals differ')

def receipt(meta,rows,inventory):
    return receipt_from_hash(meta,output_sha(rows),inventory)

def receipt_from_hash(meta,output_hash,inventory):
    return {'contract':CONTRACT,'scope':'tei-document; complete retained HTML/source-native units plus preserved failure register','identity':dict(IDENTITY),'master_sha256':MASTER_SHA,**meta['schemas'],'policy_sha256':POLICY_SHA,'mapping_version':'ocd-lib025-native-reference-v1','assembler_version':'ocd-lib025-native-reference-v1','output_sha256':output_hash,'row_count':11681,'unit_kind_counts':dict(COUNTS),'source_accounting':{'html_members':11680,'support_images':378,'stylesheets':1,'native_body_units':11681,'retained_scope':meta['scope'],'historic_source_execution_admitted':False},'unit_inventory':inventory,'warnings':[{'reason':'retained-source-gaps-preserved','description':'Indexed Alexandria, Councils of article, generic theology link, nine body images and all seventeen failure records remain explicitly qualified.'}],'exclusions':[],'unsupported':[],'independent_check':{'status':'pending','errors':[]},'authority':meta['authority']}

def project_accepted(root,*,acceptance_path):
    meta=metadata(root,acceptance_path);rows=[];inventory=[]
    for row,private in iter_rows_from_metadata(meta):rows.append(row);inventory.append(private)
    from .reference_entries import _validate_rows
    _validate_rows(rows)
    return {'rows':rows,'receipt':receipt(meta,rows,inventory),'authority':meta['authority'],'master_sha256':MASTER_SHA,'unsupported':[]}

def iter_accepted(root,*,acceptance_path):
    """Streaming API; consumers must exhaust it to obtain complete-count checks."""
    meta=metadata(root,acceptance_path)
    yield from iter_rows_from_metadata(meta)

def verify_accepted(root,*,acceptance_path,rows,receipt_document):
    if not isinstance(rows,list) or len(rows)!=11681:return ['Complete native row list required by compatibility API']
    return verify_accepted_streaming(root,acceptance_path=acceptance_path,rows=iter(rows),receipt_document=receipt_document)

def verify_accepted_streaming(root,*,acceptance_path,rows,receipt_document):
    try:
        meta=metadata(root,acceptance_path)
        fail(isinstance(receipt_document,dict),'Complete native receipt required')
        marker=receipt_document.get('independent_check')
        fail(isinstance(marker,dict) and set(marker)=={'status','errors'} and marker['status'] in ('pending','pass') and marker['errors']==[],'Native independent outcome must be exact pending/pass with no errors')
        inventory=receipt_document.get('unit_inventory')
        fail(isinstance(inventory,list) and len(inventory)==11681,'Complete private native inventory required')
        counts=Counter();context_keys={'record_id','representation_revision','locator','provenance'};output=hashlib.sha256();output.update(b'[');count=0
        from .reference_entries import _validator
        validator=_validator()
        def actual():
            nonlocal count
            for row,private in zip(rows,inventory,strict=True):
                fail(isinstance(row,dict),'Native public row must be an object')
                base={k:v for k,v in row.items() if k not in context_keys}
                # Explicit correspondence: validate every added ordinary field
                # against accepted identity/revision/title/source URL/location
                # and actual native sequence/source title. Expat subsequently
                # verifies those base facts/private IDs against actual source.
                expected_context=row_context(meta,base,private)
                fail({k:row[k] for k in context_keys}==expected_context,'Accepted native row identity/provenance/locator differs')
                fail(not list(validator.iter_errors(row)),'Native complete public row schema differs')
                counts[row['unit_kind']]+=1
                if count:output.update(b',')
                output.update(canonical(row));count+=1
                yield {'public_unit':base,'private_receipt':private}
        from .lib025_native_reference_observer import verify_proposed_units
        verify_proposed_units(meta['master'],actual(),identity=IDENTITY,accepted=True)
        output.update(b']')
        fail(count==11681 and dict(counts)==COUNTS,'Independent observed native row/unit-kind totals differ')
        expected=receipt_from_hash(meta,output.hexdigest(),inventory)
        # Only the exact framework outcome marker may advance from pending to
        # pass. Every other receipt byte/value stays in complete correspondence.
        normalized=dict(receipt_document);normalized['independent_check']={'status':'pending','errors':[]}
        fail(normalized==expected,'Native reference complete receipt differs')
        return []
    except (PipelineError,OSError,ValueError,KeyError,TypeError) as exc:return ['Native Catholic Encyclopedia verification failed: '+str(exc)]
