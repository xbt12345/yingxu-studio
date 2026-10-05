"""Keep source-defined generation and refinement seeds independent.

Only the reviewed source graphs qualify. Native seed maxima are restricted to
the browser's exact integer domain; SeedVR2's smaller 32-bit range is preserved.
This changes the form contract, never the original workflow or its defaults.
"""
from copy import deepcopy

JS_INTEGER_MAX=9007199254740991
SEEDVR_MAX=4294967295
RGTHREE_SEED_MAX=1125899906842624

# (node, source input, public key, source class, source default, label, maximum)
STAGE_SEEDS={
 'local-card-50':{
  'sourceHash':'3d342e398469872d2acbcaf4fa7e6030e48e311d6e7b7aee5dbe0cd9abcf3075',
  'stages':(('467','noise_seed','noise_seed','RandomNoise',42,'首轮生成种子',JS_INTEGER_MAX),
            ('432','noise_seed','noise_seed','RandomNoise',43,'放大精修种子',JS_INTEGER_MAX)),
  'edges':(('467',0,'470','noise','SamplerCustomAdvanced'),
           ('432',0,'437','noise','SamplerCustomAdvanced'),
           ('470',0,'465','samples','LTXVLatentUpsampler'))},
 'local-card-51':{
  'sourceHash':'22850d24d702737845f1774c14f4c6af1bb0d0d99f8dc6397fb5963be21aea3d',
  'stages':(('1020','noise_seed','noise_seed','RandomNoise',666,'首轮局部重绘种子',JS_INTEGER_MAX),
            ('981','noise_seed','noise_seed','RandomNoise',999,'放大精修种子',JS_INTEGER_MAX)),
  'edges':(('1020',0,'1009','noise','SamplerCustomAdvanced'),
           ('981',0,'972','noise','SamplerCustomAdvanced'),
           ('1009',0,'1003','av_latent','LTXVSeparateAVLatent'),
           ('980',0,'988','latent','LTXVAddGuideMulti'),
           ('974',0,'972','latent_image','SamplerCustomAdvanced'))},
 'local-card-77':{
  'sourceHash':'6bb5b69b61828f91c8c90eea29725c8a9a2e6b175fa7580aa29f1efcf58d07b0',
  'stages':(('14','seed','seed','KSampler',1057166318720754,'图像生成种子',JS_INTEGER_MAX),
            ('89','seed','upscale_seed','SeedVR2VideoUpscaler',622687745,'增强种子',SEEDVR_MAX)),
  'edges':(('14',0,'12','samples','VAEDecode'),
           ('12',0,'92','anything','easy cleanGpuUsed'),
           ('92',0,'89','image','SeedVR2VideoUpscaler'))},
 'local-card-85':{
  'sourceHash':'dd292b96f8e6f02fab2ccdb63b9e29b5e95976fbd26b71a8415fc139da571ef1',
  'stages':(('58','seed','seed','Seed (rgthree)',187155922071792,'基础生成种子',RGTHREE_SEED_MAX),
            ('63','seed','refine_seed','KSampler',199739316831602,'放大重绘种子',JS_INTEGER_MAX)),
  'edges':(('58',0,'56','seed','KSampler'),
           ('56',0,'55','samples','LatentUpscaleBy'),
           ('55',0,'63','latent_image','KSampler'))},
 'local-card-90':{
  'sourceHash':'ec33accad083c57935c1be88a69d776f3ef08fb35612707e30a7b8d76f598d09',
  'stages':(('13','seed','seed','SeedVR2VideoUpscaler',622687745,'原图直接增强种子',SEEDVR_MAX),
            ('91','seed','seed','KSampler',547451245111443,'分块重绘种子',JS_INTEGER_MAX),
            ('126','seed','seed','SeedVR2VideoUpscaler',622687745,'重绘后增强种子',SEEDVR_MAX)),
  'edges':(('13',0,'16','images','PreviewImage'),
           ('91',0,'68','samples','VAEDecode'),
           ('86',0,'126','image','SeedVR2VideoUpscaler'))},
 'local-card-107':{
  'sourceHash':'396a12617c7e9e3fafc8aba2dee7fadb5f9f2d3fc8cdc20498b1ebfaa8ea67b2',
  'stages':(('3','seed','seed','KSampler',998425033959259,'图像生成种子',JS_INTEGER_MAX),
            ('80','seed','upscale_seed','SeedVR2VideoUpscaler',1375963829,'增强种子',SEEDVR_MAX)),
  'edges':(('3',0,'8','samples','VAEDecode'),
           ('8',0,'85','anything','easy cleanGpuUsed'),
           ('85',0,'80','image','SeedVR2VideoUpscaler'))}}


def _expected(stage):
    nid,source_key,public_key,typ,value,label,maximum=stage
    target={'node':nid,'input':source_key}
    return {'id':nid+':'+source_key,'nodeId':nid,'key':public_key,
            'node':typ,'kind':'seed','type':'number','value':value,'label':label,
            'min':0,'max':maximum,'step':1,'integer':True,'help':'',
            'targets':[target],
            'members':[{'id':nid+':'+source_key,'nodeId':nid,'key':source_key,'targets':[deepcopy(target)]}]}


def _check_edges(graph,edges):
    for src,oslot,dst,port,typ in edges:
        node=graph.nodes.get(dst,{})
        index=next((i for i,v in enumerate(node.get('inputs',[])) if v.get('name')==port),None)
        if (node.get('type')!=typ or src not in graph.reachable or dst not in graph.reachable or
            index is None or (dst,index,oslot)not in graph.out.get(src,[])):
            raise ValueError('独立种子的阶段连线已改变。')


def reviewed_stage_seeds(workflow,controls,*,graph=None,source_hash=None,derived=None):
    contract=STAGE_SEEDS.get(workflow.get('id'))
    if contract is None:return controls
    if source_hash!=contract['sourceHash']:
        raise ValueError('独立阶段种子的来源已改变。')
    stage_nodes={stage[0]for stage in contract['stages']}
    replaced=[c for c in controls if c.get('kind')=='seed' and
              (c.get('nodeId')in stage_nodes or any(m.get('nodeId')in stage_nodes for m in c.get('members',[])))]
    if not replaced:raise ValueError('缺少原始阶段种子控件。')
    if any(any(m.get('nodeId')not in stage_nodes for m in c.get('members',[]))for c in replaced):
        raise ValueError('原合并种子含未审查的阶段。')
    if graph is not None:
        from build_workflow_interfaces import widget_bindings
        _check_edges(graph,contract['edges'])
        for nid,key,_,typ,value,_,_ in contract['stages']:
            node=graph.nodes.get(nid,{})
            if (node.get('type')!=typ or nid not in graph.reachable or
                not graph.editable(nid,key) or widget_bindings(node).get(key,(None,))[0]!=value or
                graph.targets(nid,key)!=[(nid,key)]):
                raise ValueError('独立种子的原始值或真实目标未匹配。')
    elif (derived or {}).get('sourceHash')!=source_hash:
        raise ValueError('缺少独立阶段种子的同源证明。')
    fields=[]
    for stage in contract['stages']:
        field=_expected(stage)
        if graph is None:
            proofs=[c for c in (derived or {}).get('controls',[])if c.get('id')==field['id']]
            if len(proofs)!=1 or any(proofs[0].get(k)!=v for k,v in field.items()):
                raise ValueError('独立阶段种子的审核证明未匹配。')
            field=deepcopy(proofs[0])
        elif 'uiGroup'in replaced[0]:field['uiGroup']=replaced[0]['uiGroup']
        fields.append(field)
    result=[];inserted=False
    for control in controls:
        if control in replaced:
            if not inserted:result.extend(fields);inserted=True
        else:result.append(deepcopy(control))
    return result
