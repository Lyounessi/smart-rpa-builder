"""Bounded selector candidates. Only validated unique matches may be chosen."""
from itertools import combinations
import re
from .quality import assess_id

SEMANTIC_ATTRIBUTES = ['formcontrolname','ng-reflect-name','data-qa','data-cy','data-test','data-automation-id','aria-label','name']


def quoted(value):
    return '"'+''.join('\\'+format(ord(char),'x')+' ' if ord(char)<32 or ord(char)==127
        else '\\'+char if char in '\\"' else char for char in value)+'"'


def stable_classes(tokens):
    return [value for value in tokens if len(value)<=100 and not re.search(
        r'^(?:ng-|is-|has-|css-|sc-)|^(?:active|focus|focused|hover|selected|disabled)$|[0-9a-f]{8,}|\d{4,}',value,re.I)][:6]


def candidates(metadata):
    tag=metadata['tag'] if re.fullmatch(r'[a-z][a-z0-9-]*',metadata['tag']) else '*'
    attrs=metadata['attributes']
    result=[]
    def add(value):
        if value not in result and len(result)<48:
            result.append(value)
    def css(value): add({'strategy':'css','value':value})
    def attribute(tag,key,value): return f'{tag}[{key}={quoted(value)}]'
    if attrs.get('data-testid'): add({'strategy':'test_id','value':attrs['data-testid']})
    if metadata.get('role') and metadata.get('name'):
        add({'strategy':'role','role':metadata['role'],'name':metadata['name']})
    if metadata.get('label'): add({'strategy':'label','value':metadata['label']})
    for key in SEMANTIC_ATTRIBUTES:
        if attrs.get(key): css(attribute(tag,key,attrs[key]))
    if attrs.get('id') and assess_id(attrs['id'])['assessment']!='suspected_generated':
        css(attribute(tag,'id',attrs['id']))
    for key in ['placeholder','title','alt']:
        if attrs.get(key): css(attribute(tag,key,attrs[key]))
    if metadata.get('name') and tag in {'p','span','label'}:
        add({'strategy':'text','value':metadata['name']})
    tokens=stable_classes(metadata.get('classes',[]))
    for group in [(token,) for token in tokens]+list(combinations(tokens,2))[:6]:
        css(tag+''.join(f'[class~={quoted(token)}]' for token in group))
    for ancestor in metadata.get('ancestors',[])[:3]:
        parent_tag=ancestor['tag'] if re.fullmatch(r'[a-z][a-z0-9-]*',ancestor['tag']) else '*'
        parent_attrs=ancestor.get('attributes',{})
        prefixes=[]
        for key in ['data-testid',*SEMANTIC_ATTRIBUTES,'id']:
            if parent_attrs.get(key) and (key!='id' or assess_id(parent_attrs[key])['assessment']!='suspected_generated'):
                prefixes.append(attribute(parent_tag,key,parent_attrs[key]))
        if ancestor.get('label'):
            prefixes.append(f'{parent_tag}:has(> label:text-is({quoted(ancestor["label"])}))')
        for token in stable_classes(ancestor.get('classes',[]))[:2]:
            prefixes.append(f'{parent_tag}[class~={quoted(token)}]')
        for prefix in prefixes[:6]:
            # Child attributes/classes may distinguish repeated controls in a stable container.
            css(prefix+' '+tag)
            for token in tokens[:2]: css(prefix+' '+tag+f'[class~={quoted(token)}]')
    return result
