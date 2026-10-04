"""Offline contract audit: imports templates and metadata, never submits jobs."""
import collections
import copy
import hashlib
import json
import math
import pathlib
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import schema_adapters as adapters
import server

metadata=json.loads((ROOT/'private/research/card-20261004/object_info.json').read_text('utf-8'))
registry=adapters.registry()
file_fields={('LoadImage','image'),('LoadAudio','audio'),('LoadVideo','file'),('VHS_LoadVideo','video'),('VHS_LoadVideoFFmpeg','video'),('LoadImageMask','image')}

def expanded_fields(meta,inputs):
    """Resolve actual Comfy v3 dotted socket descriptions from object_info."""
    fields={};required=set();problems=[]
    def expand(name,info,needed):
        typ=info[0]; options=info[1]if len(info)>1 and isinstance(info[1],dict)else{}
        if typ=='COMFY_AUTOGROW_V3':
            children={key:value for key,value in inputs.items()if key.startswith(name+'.')}
            template=options.get('template',{}).get('input',{})
            prototypes={**template.get('required',{}),**template.get('optional',{})}
            names=options.get('names');prefix=options.get('prefix')
            accepted=[]
            for key in children:
                short=key[len(name)+1:]
                if names is not None and short not in names or prefix is not None and not short.startswith(prefix):
                    problems.append((key,'invalid-dynamic-name'));continue
                if len(prototypes)!=1:
                    problems.append((key,'unreviewed-dynamic-template'));continue
                accepted.append(key);fields[key]=next(iter(prototypes.values()))
            if len(accepted)<options.get('min',0)or len(accepted)>options.get('max',float('inf')):
                problems.append((name,'invalid-dynamic-count'))
            return
        fields[name]=info
        if needed and not options.get('hidden'):required.add(name)
        if typ=='COMFY_DYNAMICCOMBO_V3':
            choice=next((item for item in options.get('options',[])if item.get('key')==inputs.get(name)),None)
            if choice is None:
                if name in inputs:problems.append((name,'invalid-dynamic-choice'))
                return
            for kind in ('required','optional'):
                for key,child in choice.get('inputs',{}).get(kind,{}).items():expand(name+'.'+key,child,kind=='required')
    for kind in ('required','optional'):
        for name,info in meta.get('input',{}).get(kind,{}).items():expand(name,info,kind=='required')
    return fields,required,problems

def valid_graph(graph):
    issues=[]
    for node_id,node in graph.items():
        cls=node.get('class_type')
        if cls not in metadata:
            issues.append({'node':node_id,'kind':'missing-class','class':cls});continue
        meta=metadata[cls]
        inputs=node.get('inputs',{})
        fields,required,problems=expanded_fields(meta,inputs)
        issues.extend({'node':node_id,'input':name,'kind':kind}for name,kind in problems)
        for name in required-set(inputs):
            issues.append({'node':node_id,'input':name,'kind':'missing-required'})
        for name,value in inputs.items():
            if name not in fields:
                # A few node widgets add frontend-only values; record separately
                # instead of assuming they are required backend socket inputs.
                issues.append({'node':node_id,'input':name,'kind':'unknown-input'});continue
            info=fields[name]
            typ=info[0]
            constraints=info[1]if len(info)>1 and isinstance(info[1],dict)else{}
            if isinstance(value,list)and len(value)==2 and isinstance(value[0],str)and isinstance(value[1],int)and not isinstance(value[1],bool):
                upstream=graph.get(value[0])
                if upstream is None:
                    issues.append({'node':node_id,'input':name,'kind':'missing-link'});continue
                output=metadata.get(upstream.get('class_type'),{}).get('output',[])
                if value[1]<0 or value[1]>=len(output):
                    issues.append({'node':node_id,'input':name,'kind':'invalid-output-index'});continue
                # Comfy custom types can deliberately accept arbitrary socket
                # types. Only report primitive exact mismatches as diagnostics.
                continue
            if isinstance(typ,list):
                if (cls,name)not in file_fields and value not in typ:
                    issues.append({'node':node_id,'input':name,'kind':'invalid-enum'})
            elif typ=='COMBO'and (cls,name)not in file_fields and constraints.get('options') and value not in constraints['options']:
                issues.append({'node':node_id,'input':name,'kind':'invalid-enum'})
            elif typ in ('INT','FLOAT'):
                number=isinstance(value,(int,float))and not isinstance(value,bool)and math.isfinite(value)
                if not number or typ=='INT'and int(value)!=value:
                    issues.append({'node':node_id,'input':name,'kind':'invalid-'+typ.lower()})
                elif ('min'in constraints and value<constraints['min'])or('max'in constraints and value>constraints['max']):
                    issues.append({'node':node_id,'input':name,'kind':'out-of-range'})
            elif typ=='BOOLEAN'and not isinstance(value,bool):
                issues.append({'node':node_id,'input':name,'kind':'invalid-boolean'})
            elif typ=='STRING'and not isinstance(value,str):
                issues.append({'node':node_id,'input':name,'kind':'invalid-string'})
    return issues

def must_reject(call,code,issues):
    try:call()
    except ValueError:return
    issues.append({'kind':'malformed-accepted','case':code})

results=[]
for workflow_id,spec in registry.items():
    result={'id':workflow_id,'source_hash':spec.get('source_hash'),'validation':spec.get('validation'),
            'controls':len(spec.get('controls',[])),'texts':len(spec.get('texts',[])),
            'media':len(spec.get('media',[])),'issues':[]}
    public=server.public_schema(spec)
    for source,key in (('controls','supportedControlIds'),('texts','supportedTextIds'),('media','supportedMediaIds')):
        if public[key]!=[field['id']for field in spec.get(source,[])]:result['issues'].append({'kind':'projection-ids','field':source})
    for field in public['media']:
        original=next(item for item in spec['media']if item['id']==field['id'])
        if field['required']!=original.get('required',not original.get('optional',False))or field['optional']==field['required']:
            result['issues'].append({'kind':'projection-required-slot','field':field['id']})
    if any('targets'in field for source in ('controls','texts','media')for field in public[source]):result['issues'].append({'kind':'projection-execution-target'})
    if spec.get('validation')!='structural-verified':
        result['blocking_reason']=spec.get('blocking_reason')
        must_reject(lambda:adapters.require_ready(spec),'blocked',result['issues'])
        results.append(result);continue
    values={field['id']:-1 for field in spec.get('controls',[])if field.get('kind')=='seed'}
    for field in spec.get('controls',[]):
        if field.get('kind')=='points':
            values[field['id']]='{"positive":[{"x":0.5,"y":0.5}],"negative":[{"x":0.1,"y":0.1}]}'
    recipe=spec.get('pointsRecipe')
    geometry=({'width':1280,'height':736,'node':recipe['node'],'negativeTarget':recipe.get('negativeTarget')}
              if recipe else None)
    records={field['id']:{'kind':field['kind'],'remote':'offline-audit.'+{'image':'png','video':'mp4','audio':'wav'}[field['kind']]}
             for field in spec.get('media',[])}
    must_reject(lambda:adapters.validate_values(spec,{'__unknown__':0}),'unknown-control',result['issues'])
    must_reject(lambda:adapters.validate_texts(spec,{'__unknown__':'x'}),'unknown-text',result['issues'])
    must_reject(lambda:adapters.validate_assets(spec,{'__unknown__':{'kind':'image'}}),'unknown-media',result['issues'])
    for field in spec.get('controls',[]):
        if field.get('type')=='number':
            must_reject(lambda f=field:adapters.validate_values(spec,{**values,f['id']:True}),'numeric-bool:'+field['id'],result['issues'])
            bound=field.get('max')
            if isinstance(bound,(int,float)):
                must_reject(lambda f=field,b=bound:adapters.validate_values(spec,{**values,f['id']:b+max(1,abs(b))}),'max:'+field['id'],result['issues'])
    for field in spec.get('media',[]):
        wrong=copy.deepcopy(records);wrong[field['id']]['kind']='text'
        must_reject(lambda r=wrong:adapters.validate_assets(spec,r),'media-kind:'+field['id'],result['issues'])
        if field.get('required',not field.get('optional',False)):
            absent={k:v for k,v in records.items()if k!=field['id']}
            must_reject(lambda r=absent:adapters.validate_assets(spec,r),'required-media:'+field['id'],result['issues'])
    for mode in ('all-media','required-only'):
        selected=(records if mode=='all-media'else{k:records[k]for k in records if next(f for f in spec['media']if f['id']==k).get('required',True)})
        try:
            graph,actual,texts=adapters.build(spec,values,{},selected,{},'offline-'+workflow_id,geometry=geometry)
            issues=valid_graph(graph)
            result['issues'].extend({'mode':mode,**issue}for issue in issues)
            result[mode]={'nodes':len(graph),'outputs':spec['outputs'],'random_seeds':len([f for f in spec.get('controls',[])if f.get('kind')=='seed'])}
            if mode=='all-media':
                original={'schema_spec':spec,'graph':graph,'catalog_values':actual}
                redrawn,updated=adapters.rerun(original,selected,'offline-rerun-'+workflow_id)
                changed={f['id']for f in spec.get('controls',[])if f.get('kind')=='seed'}
                if any(actual[k]!=updated[k]for k in set(actual)-changed):result['issues'].append({'kind':'rerun-modified-nonseed'})
                result['issues'].extend({'mode':'rerun',**issue}for issue in valid_graph(redrawn))
                if geometry:
                    pointnode=recipe['node']
                    if graph[pointnode]!=redrawn[pointnode]:result['issues'].append({'kind':'rerun-modified-points'})
        except (ValueError,TypeError,KeyError)as error:
            result['issues'].append({'mode':mode,'kind':'build-failed','error':str(error)})
    results.append(result)

summary={'scope':'offline templates + downloaded card object_info; no execution or paid API calls',
         'enum_scope':'Model and enum values checked, except dynamic uploaded-file lists; empty CustomCombo options are source-node configured.',
         'registry_sha256':hashlib.sha256(adapters.REGISTRY_PATH.read_bytes()).hexdigest(),
         'counts':dict(collections.Counter(r['validation']for r in results)),
         'ready_with_issues':sum(bool(r['issues'])for r in results if r['validation']=='structural-verified'),
         'issue_kinds':dict(collections.Counter(issue['kind']for r in results for issue in r['issues'])),
         'workflows':results}
destination=ROOT/'private/review70/backend-contract-audit.json'
destination.write_text(json.dumps(summary,ensure_ascii=False,indent=2),'utf-8')
diagnostics=[]
for result in results:
    if result['validation']!='structural-verified' or not result['issues']:continue
    spec=registry[result['id']]
    graph=json.loads(adapters.template_path(spec).read_text('utf-8'))
    for issue in result['issues']:
        if issue.get('mode')!='all-media':continue
        node=graph.get(issue.get('node'),{})
        cls=node.get('class_type')
        fields={**metadata.get(cls,{}).get('input',{}).get('required',{}),**metadata.get(cls,{}).get('input',{}).get('optional',{})}
        description=fields.get(issue.get('input'),[])
        definition=description[1]if len(description)>1 and isinstance(description[1],dict)else{}
        actual=node.get('inputs',{}).get(issue.get('input'))
        diagnostic={'id':result['id'],'node':issue.get('node'),'class_type':cls,'input':issue.get('input'),
                    'error':issue['kind'],'schema_type':description[0]if description else None,
                    'schema_default':definition.get('default'),'actual_type':type(actual).__name__}
        if issue['kind']=='invalid-boolean'or isinstance(actual,(int,float)):diagnostic['actual']=actual
        if description and isinstance(description[0],str)and description[0]=='COMFY_DYNAMICCOMBO_V3':diagnostic['available_keys']=[option['key']for option in definition.get('options',[])]
        diagnostics.append(diagnostic)
(ROOT/'private/review70/backend-type-diagnostics.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({k:v for k,v in summary.items()if k!='workflows'},ensure_ascii=False))
print(json.dumps([{ 'id':r['id'],'issues':[x for x in r['issues']if x.get('mode')in (None,'all-media')]}for r in results if r['issues']],ensure_ascii=False))
raise SystemExit(1 if summary['ready_with_issues'] else 0)
