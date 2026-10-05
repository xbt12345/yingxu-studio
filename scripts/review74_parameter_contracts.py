"""Small source-pinned corrections for real creative inputs."""
from copy import deepcopy

SEED112_HASH='4df1a3d0a0b345d345a1092e7d2aafc158051da9612f6979bd7ca2540c269ffe'
SEED112_FIELDS=(('116',324348895176675,'去遮挡种子'),('196',324348895176621,'上色种子'))


def reviewed_independent_seeds(workflow,controls,*,graph=None,source_hash=None,derived=None):
    if workflow.get('id')!='local-card-112':return controls
    if source_hash!=SEED112_HASH:raise ValueError('两阶段种子来源已改变。')
    original=[c for c in controls if c.get('kind')=='seed']
    if not original or any(c.get('nodeId')not in ('116','196') for c in original):
        raise ValueError('两阶段种子控件未匹配。')
    fresh=[]
    for nid,value,label in SEED112_FIELDS:
        if graph is not None:
            from build_workflow_interfaces import widget_bindings
            node=graph.nodes.get(nid,{})
            if (node.get('type')!='RandomNoise' or nid not in graph.reachable or
                not graph.editable(nid,'noise_seed') or widget_bindings(node).get('noise_seed',(None,))[0]!=value or
                graph.targets(nid,'noise_seed')!=[(nid,'noise_seed')]):
                raise ValueError('两阶段种子的原始值或输出绑定未匹配。')
            field=deepcopy(original[0])
            field.update(id=nid+':noise_seed',nodeId=nid,key='noise_seed',node='RandomNoise',value=value,
                targets=[{'node':nid,'input':'noise_seed'}])
        else:
            proofs=[c for c in (derived or {}).get('controls',[]) if c.get('id')==nid+':noise_seed']
            if (len(proofs)!=1 or (derived or {}).get('sourceHash')!=source_hash or
                proofs[0].get('value')!=value or proofs[0].get('targets')!=[{'node':nid,'input':'noise_seed'}]):
                raise ValueError('缺少独立阶段种子的同源证明。')
            field=deepcopy(proofs[0])
        field.update(label=label,members=[{k:deepcopy(field[k]) for k in ('id','nodeId','key','targets')}])
        fresh.append(field)
    # Place both independent controls where the merged seed previously lived.
    result=[];inserted=False
    for field in controls:
        if field.get('kind')=='seed':
            if not inserted:result.extend(fresh);inserted=True
        else:result.append(field)
    return result


def reviewed_batch_count(workflow,controls,*,source_hash=None):
    if workflow.get('id')!='local-card-80':return controls
    if source_hash!='83d4166f18f6215116e365394b1d4a3393fcd069d8afd8b6c29ca0e1247c5a41':
        raise ValueError('动漫套图数量来源已改变。')
    result=deepcopy(controls);counts=[f for f in result if f.get('id')=='88:value']
    if len(counts)!=1 or counts[0].get('targets')!=[{'node':'85','input':'int_'},{'node':'87','input':'max_count'}]:
        raise ValueError('动漫套图数量绑定未匹配。')
    counts[0].update(min=1,max=1000,step=1,integer=True)
    return result


COLOR_SUPPLEMENTS={
 'local-card-112':(SEED112_HASH,'203','197'),
 'local-card-113':('8b39490de70ada82241859f38ac197521f0876b695a6886077ce6cd2d139f90a','171','172')}

def reviewed_color_supplement(workflow,texts,*,graph=None,source_hash=None,derived=None):
    contract=COLOR_SUPPLEMENTS.get(workflow.get('id'))
    if not contract:return texts
    expected,nid,tagger=contract
    if source_hash!=expected:raise ValueError('上色补充说明来源已改变。')
    field={'id':nid+':string_b','key':'string_b','node':'StringConcatenate','role':'prompt',
        'label':'上色补充说明','help':'留空沿用原上色设置','preserveWhenEmpty':True,'required':False}
    if graph is not None:
        from build_workflow_interfaces import widget_bindings
        node=graph.nodes.get(nid,{});values=widget_bindings(node)
        if (node.get('type')!='StringConcatenate' or nid not in graph.reachable or
            graph.nodes.get(tagger,{}).get('type')!='WD14Tagger|pysssss' or graph.nodes[tagger].get('mode')!=4 or
            values.get('string_a',(None,))[0]!='colorMangaKlein. ' or values.get('string_b',(None,))[0]!='' or
            values.get('delimiter',(None,))[0]!='' or graph.ins.get(nid)!=[(tagger,0,1)]):
            raise ValueError('上色触发词或原停用标签分支已改变。')
    else:
        proofs=[f for f in (derived or {}).get('texts',[]) if f.get('id')==field['id']]
        if len(proofs)!=1 or proofs[0]!=field or (derived or {}).get('sourceHash')!=source_hash:
            raise ValueError('缺少补充上色说明的同源证明。')
    result=deepcopy(texts)
    existing=[f for f in result if f.get('id')==field['id']]
    if len(existing)>1:raise ValueError('上色补充说明出现重复入口。')
    if existing:existing[0].update(field)
    else:result.append(field)
    if workflow.get('id')=='local-card-112':
        for f in result:
            if f['id']=='118:text':f['label']='去遮挡描述'
    return result


def reviewed_camera14_size(workflow,controls,*,graph=None,source_hash=None,derived=None):
    if workflow.get('id')!='local-card-14':return controls
    expected='2734f9df96bc0dd7ba8157e2acb935033db8a9c39d873d79c094272f72ee86f5'
    if source_hash!=expected:raise ValueError('视角输出尺寸来源已改变。')
    field={'id':'135:scale_to_length','nodeId':'135','key':'output_pixels','kind':'resolution','type':'number',
        'label':'输出总像素','node':'LayerUtility: ImageScaleByAspectRatio V2','value':1324,'min':512,'max':4096,'step':1,
        'targets':[{'node':'135','input':'scale_to_length'}],
        'customRange':{'min':512,'max':4096,'step':1},'options':[1024,1536,2048],'help':'越大，生成成本越高'}
    if graph is not None:
        from build_workflow_interfaces import widget_bindings
        node=graph.nodes.get('135',{});values=widget_bindings(node)
        if (node.get('type')!=field['node'] or '135' not in graph.reachable or
            values.get('scale_to_side',(None,))[0]!='total_pixel(kilo pixel)' or
            values.get('scale_to_length',(None,))[0]!=1324 or not graph.editable('135','scale_to_length')):
            raise ValueError('视角真实输出像素预算未匹配。')
    else:
        proofs=[f for f in (derived or {}).get('controls',[]) if f.get('id')==field['id']]
        if len(proofs)!=1 or proofs[0]!=field or (derived or {}).get('sourceHash')!=source_hash:
            raise ValueError('缺少视角尺寸的同源证明。')
    result=deepcopy(controls)
    existing=[f for f in result if f.get('id')==field['id']]
    if len(existing)>1:raise ValueError('输出像素预算出现重复入口。')
    if existing:existing[0].update(field)
    else:result.insert(0,field)
    return result


def reviewed_final_enhancement_size(workflow,controls,*,graph=None,source_hash=None,derived=None):
    if workflow.get('id')!='local-card-77':return controls
    expected='6bb5b69b61828f91c8c90eea29725c8a9a2e6b175fa7580aa29f1efcf58d07b0'
    if source_hash!=expected:raise ValueError('增强输出尺寸的来源已改变。')
    field={'id':'89:resolution','nodeId':'89','key':'resolution','kind':'resolution','type':'number',
        'label':'增强输出分辨率','node':'SeedVR2VideoUpscaler','value':1536,'min':16,'max':16384,'step':2,'integer':True,
        'targets':[{'node':'89','input':'resolution'}],
        'customRange':{'min':16,'max':16384,'step':2},'options':[1024,1536,2048],
        'help':'短边像素，越大越慢'}
    if graph is not None:
        from build_workflow_interfaces import widget_bindings
        from configuration import workflow_path
        import json
        node=graph.nodes.get('89',{});values=widget_bindings(node)
        if (node.get('type')!=field['node'] or '89' not in graph.reachable or
            values.get('resolution',(None,))[0]!=1536 or not graph.editable('89','resolution') or
            graph.targets('89','resolution')!=[('89','resolution')] or
            graph.nodes.get('80',{}).get('type')!='SaveImage' or graph.ins.get('80')!=[('89',0,0)]):
            raise ValueError('增强尺寸的真实默认值或最终图像输出已改变。')
        template=json.loads(workflow_path('local-card-77').read_text(encoding='utf-8'))
        if (template.get('89',{}).get('class_type')!=field['node'] or
            template['89'].get('inputs',{}).get('resolution')!=1536 or
            template.get('80',{}).get('class_type')!='SaveImage' or
            template['80'].get('inputs',{}).get('images')!=['89',0]):
            raise ValueError('增强尺寸的实际执行输出已改变。')
    else:
        proofs=[f for f in (derived or {}).get('controls',[]) if f.get('id')==field['id']]
        if len(proofs)!=1 or proofs[0]!=field or (derived or {}).get('sourceHash')!=source_hash:
            raise ValueError('缺少最终增强尺寸的同源证明。')
    result=deepcopy(controls)
    existing=[f for f in result if f.get('id')==field['id']]
    if len(existing)>1:raise ValueError('增强输出尺寸出现重复入口。')
    if existing:existing[0].update(field)
    else:result.insert(0,field)
    return result


def reviewed_refinement_reference(workflow,controls,*,graph=None,source_hash=None,derived=None):
    if workflow.get('id')!='local-card-51':return controls
    expected='22850d24d702737845f1774c14f4c6af1bb0d0d99f8dc6397fb5963be21aea3d'
    if source_hash!=expected:raise ValueError('精修参考强度的来源已改变。')
    field={'id':'988:num_guides.strength_1','nodeId':'988','key':'num_guides.strength_1','kind':'strength','type':'number',
        'label':'精修参考强度','node':'LTXVAddGuideMulti','value':1.0,'min':0,'max':10,'step':0.01,
        'targets':[{'node':'988','input':'num_guides.strength_1'}],
        'help':'精修阶段参考约束','valueOrigin':'installed-selected-dynamic-option-default'}
    if graph is not None:
        from pathlib import Path
        from build_workflow_interfaces import widget_bindings
        from configuration import workflow_path
        import json
        node=graph.nodes.get('988',{})
        if (node.get('type')!=field['node'] or '988' not in graph.reachable or node.get('mode',0)!=0 or
            widget_bindings(node).get('num_guides',(None,))[0]!=0 or
            ('987',0,5) not in graph.ins.get('988',[]) or graph.nodes.get('987',{}).get('type')!='GetNode'):
            raise ValueError('精修参考图的源分组或真实输入已改变。')
        info=json.loads((Path(__file__).resolve().parents[1]/'private/review72/object_info.json').read_text(encoding='utf-8'))
        dynamic=info[field['node']]['input']['required']['num_guides']
        selected=dynamic[1]['options'][0]
        leaf=selected['inputs']['required']['strength_1']
        if (dynamic[0]!='COMFY_DYNAMICCOMBO_V3' or selected['key']!='1' or leaf[0]!='FLOAT' or
            {k:leaf[1].get(k)for k in ('default','min','max','step')}!={'default':1.0,'min':0.0,'max':10.0,'step':0.01}):
            raise ValueError('精修参考强度的已安装动态节点合同已改变。')
        template=json.loads(workflow_path('local-card-51').read_text(encoding='utf-8'))
        inputs=template.get('988',{}).get('inputs',{})
        if (template.get('988',{}).get('class_type')!=field['node'] or inputs.get('num_guides')!='1' or
            inputs.get('num_guides.image_1')!=['1063',0] or inputs.get('num_guides.strength_1')!=1.0 or
            template.get('974',{}).get('inputs',{}).get('video_latent')!=['988',2] or
            template.get('968',{}).get('inputs',{}).get('samples')!=['966',2]):
            raise ValueError('精修参考强度的实际输入或输出阶段已改变。')
    else:
        proofs=[f for f in (derived or {}).get('controls',[]) if f.get('id')==field['id']]
        if len(proofs)!=1 or proofs[0]!=field or (derived or {}).get('sourceHash')!=source_hash:
            raise ValueError('缺少精修参考强度的同源证明。')
    result=deepcopy(controls)
    existing=[f for f in result if f.get('id')==field['id']]
    if len(existing)>1:raise ValueError('精修参考强度出现重复入口。')
    if existing:existing[0].update(field)
    else:
        index=next((i+1 for i,f in enumerate(result)if f.get('id')=='1065:num_guides.strength_1'),len(result))
        result.insert(index,field)
    return result


def reviewed_inactive_middle_position(workflow,controls,*,graph=None,source_hash=None,derived=None):
    if workflow.get('id')!='local-card-124':return controls
    expected='539ebf8eb167f3571a11bb9cddfc08a819b6f906aa4f80907cbe320b61dd436e'
    if source_hash!=expected:raise ValueError('中间帧输入的来源已改变。')
    if graph is not None:
        from build_workflow_interfaces import widget_bindings
        from configuration import workflow_path
        import json
        node=graph.nodes.get('44',{})
        if (node.get('type')!='WanFirstMiddleLastFrameToVideo' or
            widget_bindings(node).get('middle_frame_ratio',(None,))[0]!=0.5 or
            ('46',0,4) not in graph.ins.get('44',[]) or
            any(graph.nodes.get(n,{}).get('mode')!=4 for n in ('45','46'))):
            raise ValueError('作者停用的中间图分支已改变。')
        template=json.loads(workflow_path('local-card-124').read_text(encoding='utf-8'))
        inputs=template.get('44',{}).get('inputs',{})
        if (template.get('44',{}).get('class_type')!='WanFirstMiddleLastFrameToVideo' or
            'middle_image' in inputs or inputs.get('middle_frame_ratio')!=0.5 or any(n in template for n in ('45','46'))):
            raise ValueError('执行图已启用中间图，不能隐藏其位置控件。')
    elif ((derived or {}).get('sourceHash')!=source_hash or
          any(f.get('id')=='44:middle_frame_ratio'for f in (derived or {}).get('controls',[]))):
        raise ValueError('缺少中间图停用分支的同源证明。')
    return [deepcopy(f)for f in controls if f.get('id')!='44:middle_frame_ratio']


MULTIVIEW_OUTPUT_SIZES={
 'local-card-72':('dbdae1e7e950bc3a00beaa9a50d9ab803ccad6403e30235c647ae453602beb33','140',1536,'longest','85','pixels'),
 'local-card-73':('8d3c565d0a9503a9adb20cc5738b95c9fd21b8548be6658e4c061189227f5fc4','43',1024,'total_pixel(kilo pixel)','35','pixels'),
 'local-card-75':('0eb7da0d8c7d97d59a093d361c0eb357222fbca0e1423eb9459137df960b7945','52',1536,'longest','9','image')}


def reviewed_multiview_output_size(workflow,controls,*,graph=None,source_hash=None,derived=None):
    contract=MULTIVIEW_OUTPUT_SIZES.get(workflow.get('id'))
    if not contract:return controls
    expected,nid,value,side,consumer,port=contract
    if source_hash!=expected:raise ValueError('生成尺寸预算的来源已改变。')
    total=side=='total_pixel(kilo pixel)'
    field={'id':nid+':scale_to_length','nodeId':nid,'key':'output_pixels'if total else 'scale_to_length',
        'kind':'resolution','type':'number','integer':True,'label':'输出总像素'if total else '输出最长边',
        'node':'LayerUtility: ImageScaleByAspectRatio V2','value':value,'min':512,'max':4096,'step':1,
        'targets':[{'node':nid,'input':'scale_to_length'}],
        'customRange':{'min':512,'max':4096,'step':1},'options':[1024,1536,2048],
        'help':'沿用原比例，越大越慢'}
    if graph is not None:
        from build_workflow_interfaces import widget_bindings
        from configuration import workflow_path
        import json
        node=graph.nodes.get(nid,{});values=widget_bindings(node)
        if (node.get('type')!=field['node'] or nid not in graph.reachable or
            values.get('scale_to_length',(None,))[0]!=value or values.get('scale_to_side',(None,))[0]!=side or
            values.get('round_to_multiple',(None,))[0]!='16' or not graph.editable(nid,'scale_to_length')):
            raise ValueError('生成尺寸的源模式或原默认值已改变。')
        template=json.loads(workflow_path(workflow['id']).read_text(encoding='utf-8'))
        actual=template.get(nid,{})
        if (actual.get('class_type')!=field['node'] or
            actual.get('inputs',{}).get('scale_to_length')!=value or actual['inputs'].get('scale_to_side')!=side or
            actual['inputs'].get('round_to_multiple')!='16' or template.get(consumer,{}).get('inputs',{}).get(port)!=[nid,0]):
            raise ValueError('生成尺寸的实际潜空间尺寸输入已改变。')
    else:
        proofs=[f for f in (derived or {}).get('controls',[])if f.get('id')==field['id']]
        if len(proofs)!=1 or proofs[0]!=field or (derived or {}).get('sourceHash')!=source_hash:
            raise ValueError('缺少生成尺寸预算的同源证明。')
    result=deepcopy(controls)
    existing=[f for f in result if f.get('id')==field['id']]
    if len(existing)>1:raise ValueError('生成尺寸预算出现重复入口。')
    if existing:existing[0].update(field)
    else:result.insert(0,field)
    return result
