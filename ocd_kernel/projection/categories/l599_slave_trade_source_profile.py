"""Exact L599 retained Wikisource header admission; no acceptance creation."""
import hashlib
import json
N='{http://www.tei-c.org/ns/1.0}'
IDENTITY={'work_id': 'slave-trade-of-east-africa', 'textual_form_id': 'slave-trade-of-east-africa-wikisource-retained', 'edition_id': 'slave-trade-of-east-africa-wikisource-electronic'}
MASTER_SHA='ee878aaef13d726507ec51954c991373b96cba6ece3b19d701b97ef0eecf71ce'
FULL_FIELDS_SHA='092a64174e3b8b72c3711235f6f4f198c590a1bf3abc5225484876f7361a14bf'
def digest(raw):return hashlib.sha256(raw).hexdigest()
def route(identity,raw,*,language,category,collection,projection_profile,allow_acceptance_metadata,source_base):
 if identity.get('work_id')!=IDENTITY['work_id']:return False
 if identity!=IDENTITY or digest(raw)!=MASTER_SHA or language!='en' or category!='prose' or collection or projection_profile is not None or not allow_acceptance_metadata or source_base is not None:raise ValueError('L599 exact reviewed master/identity/prose context differs')
 return True
def fields_et(node):return [node.tag,sorted(node.attrib.items()),node.text,node.tail,[fields_et(c) for c in node]]
def fields_lxml(node):return [str(node.tag),sorted((str(k),str(v)) for k,v in node.attrib.items()),node.text,node.tail,[fields_lxml(c) for c in node]]
def check_et(root):
 if digest(json.dumps(fields_et(root),ensure_ascii=False,separators=(',',':')).encode())!=FULL_FIELDS_SHA:raise ValueError('L599 whole actual header/body/fields/ownership differs')
 return True
def check_lxml(root):
 if digest(json.dumps(fields_lxml(root),ensure_ascii=False,separators=(',',':')).encode())!=FULL_FIELDS_SHA:raise ValueError('Observed L599 entire actual tree/fields differs')
 return True
def header_rules(elements,attributes):
 elements={key:list(value) for key,value in elements.items()};attributes={key:list(value) for key,value in attributes.items()}
 elements['sourceDesc']=list(dict.fromkeys(elements['sourceDesc']+['biblStruct']))
 elements.update(biblStruct=['monogr','note'],monogr=['title','author','imprint'],imprint=['pubPlace','publisher','date'])
 attributes['author']=list(dict.fromkeys(attributes.get('author',[])+['role']))
 attributes['p']=list(dict.fromkeys(attributes.get('p',[])+['n','xml:space']))
 return elements,attributes
