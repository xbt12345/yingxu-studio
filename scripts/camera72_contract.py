"""Align the nine authored camera controls with the reviewed prompt-list order."""
from copy import deepcopy

CAMERA72_SOURCE_HASH = 'dbdae1e7e950bc3a00beaa9a50d9ab803ccad6403e30235c647ae453602beb33'
CAMERA72_ORDER = ('108','109','110','111','112','119','121','122','120')
CAMERA72_FIELDS = {
    'horizontal_angle': {'min':0,'max':360,'step':1,'label':'水平视角'},
    'vertical_angle': {'min':-30,'max':60,'step':1,'label':'垂直视角'},
    'zoom': {'min':0,'max':10,'step':0.1,'label':'镜头距离'},
}
CAMERA72_SEQUENCE = {
    'kind':'camera-prompt-list',
    'firstList':{'node':'137','cameraNodes':['108','109','110','111','112']},
    'secondList':{'node':'138','optionalList':['137',0],'cameraNodes':['119','121','122','120']},
    'positivePrompt':{'node':'68','input':'prompt','source':['138',1]},
}


def _check_source(graph):
    from build_workflow_interfaces import widget_bindings

    def kind(nid):return graph.nodes.get(nid,{}).get('type')
    def edge(dst,key,src,port=0):
        inputs=graph.nodes.get(dst,{}).get('inputs',[])
        matches={(origin,output) for origin,output,index in graph.ins.get(dst,[])
                 if index<len(inputs) and inputs[index]['name']==key}
        return matches=={(src,port)}
    required=(*CAMERA72_ORDER,'137','138','68','70','65','8','123')
    if not all(n in graph.reachable and graph.nodes[n].get('mode',0)==0 for n in required):return False
    for nid in CAMERA72_ORDER:
        if kind(nid)!='QwenMultiangleCameraNode':return False
        values=widget_bindings(graph.nodes[nid])
        if any(key not in values or not graph.editable(nid,key) for key in CAMERA72_FIELDS):return False
    for list_id,nodes in [('137',CAMERA72_ORDER[:5]),('138',CAMERA72_ORDER[5:])]:
        if kind(list_id)!='easy promptList':return False
        for position,nid in enumerate(nodes,1):
            if not edge(list_id,f'prompt_{position}',nid):return False
    empty=widget_bindings(graph.nodes['138']).get('prompt_5',(None,None))[0]
    return (empty=='' and graph.editable('138','prompt_5') and edge('138','optional_prompt_list','137')
            and kind('68')=='TextEncodeQwenImageEditPlus' and edge('68','prompt','138',1)
            and kind('70')=='FluxKontextMultiReferenceLatentMethod' and edge('70','conditioning','68')
            and kind('65')=='KSampler' and edge('65','positive','70')
            and kind('8')=='VAEDecode' and edge('8','samples','65')
            and kind('123')=='SaveImage' and edge('123','images','8'))


def reviewed_camera72_controls(workflow, controls, *, graph=None, source_hash=None, derived=None):
    """Fresh and curated metadata share one proof; values and bindings never change.

    The frontend already groups these nodes in authored output order. This also
    aligns the schema/parameter summary and supplies the installed node ranges.
    Existing source-default corrections remain explicit and are not performed
    here. In particular the original 119 vertical angle is 90, above max 60.
    """
    if workflow.get('id')!='local-card-72':return controls
    if source_hash!=CAMERA72_SOURCE_HASH:raise ValueError('九视角源已改变，需要重新审查。')
    if graph is not None:
        if not _check_source(graph):raise ValueError('九视角列表或输出连线已改变，需要重新审查。')
    elif not isinstance(derived,dict) or derived.get('sourceHash')!=source_hash:
        raise ValueError('缺少已核实的九视角源证明。')

    cameras=[f for f in controls if f.get('kind')=='camera']
    expected={(nid,key) for nid in CAMERA72_ORDER for key in CAMERA72_FIELDS}
    identities={(str(f.get('nodeId')),f.get('key')) for f in cameras}
    if len(cameras)!=27 or identities!=expected:raise ValueError('九视角控件集合已改变，需要重新审查。')
    for field in cameras:
        nid=str(field['nodeId']);key=field['key']
        if (field.get('type')!='number' or field.get('targets')!=[{'node':nid,'input':key}]):
            raise ValueError('九视角控件类型或绑定已改变，需要重新审查。')
        if graph is None:
            matches=[f for f in derived.get('controls',[]) if f.get('id')==field['id']]
            if (len(matches)!=1 or matches[0].get('nodeId')!=field['nodeId'] or matches[0].get('key')!=key
                    or matches[0].get('targets')!=field['targets'] or matches[0].get('type')!='number'
                    or matches[0].get('cameraSequence')!=CAMERA72_SEQUENCE
                    or matches[0].get('viewIndex')!=CAMERA72_ORDER.index(nid)+1
                    or any(matches[0].get(k)!=v for k,v in CAMERA72_FIELDS[key].items() if k!='label')):
                raise ValueError('九视角顺序或范围证明已改变，需要重新审查。')

    result=deepcopy(controls)
    lookup={(str(f['nodeId']),f['key']):f for f in result if f.get('kind')=='camera'}
    ordered=[]
    for index,nid in enumerate(CAMERA72_ORDER,1):
        for key,contract in CAMERA72_FIELDS.items():
            field=lookup[(nid,key)]
            field.update({k:v for k,v in contract.items() if k!='label'})
            field.update(label=f'视角 {index} · {contract["label"]}',viewIndex=index,
                         cameraSequence=deepcopy(CAMERA72_SEQUENCE))
            if nid=='119' and key=='vertical_angle':
                field['sourceDefaultRangeIssue']={'value':90,'min':-30,'max':60}
            ordered.append(field)
    # Keep every non-camera field in its prior position, including seed groups.
    iterator=iter(ordered)
    return [next(iterator) if f.get('kind')=='camera' else f for f in result]
