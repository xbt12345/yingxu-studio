"""User controls derived from each graph's concrete bindings, not category templates."""
import re
import copy
import math
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit

# Original graph identity, native source socket and the reviewed registered
# numeric contract. The compiler independently checks these against object_info.
DERIVED_NATIVE_LIMITS={
 5:('4c37ca0b7de7de9754bb40eaa749f567df99a5a2eafada1f2a72971aea7e7c9f','378','value','INTConstant',-18446744073709551615,18446744073709551615),
 7:('280644c0b578269a554f37f74b15e631b3efd0cf71c6b7197129d8629f801ee4','45','frame_load_cap','VHS_LoadVideo',0,9007199254740991),
 45:('e9c061de44e449dcb59e76cd5f5cdb5ac39e488b3ae1a078f26e1449db6bc169','34','frame_load_cap','VHS_LoadVideo',0,9007199254740991),
 98:('f17d75d4d430df62b7a0c7e786292b7ff03b09dc386a9f28be131e49de12f421','15','duration_seconds','AudioCropProcessUTK',0,1e17),
 118:('a66e533d5c4c2f2e3605dd3b26e32f1c63730a91c4837eed333091f40f14f1ec','13','frame_load_cap','VHS_LoadVideo',0,9007199254740991),
 119:('110d7f6bab4e5a2a4d1880c6ece2db2ca92b3e3c10f301c8ce1dafe73de14f7f','507','frame_load_cap','VHS_LoadVideo',0,9007199254740991),
 120:('b8ab76162041b1893180996f3badbdc26eaa82be7fa63b913de4a7ebef2b65e2','18','frame_load_cap','VHS_LoadVideo',0,9007199254740991),
 121:('9f7c6e6b8bfe7cf14ea33a3b763f02b0415ca155d8c5b531a8deaa40b3fa5882','15','frame_load_cap','VHS_LoadVideo',0,9007199254740991),
 122:('0036eac90c054211b9507171597c8486415ca4b2504d4cbf33c373e36e269f91','25','frame_load_cap','VHS_LoadVideo',0,9007199254740991),
 123:('5c46f4ef6b61dfa42edead5da785672bc87253f4b20315f83fd2505f1d0dfdf1','18','frame_load_cap','VHS_LoadVideo',0,9007199254740991),
}


def frame_seconds_maximum(maximum,fps):
    """A representable UI limit whose round(seconds * fps) stays in range."""
    if (isinstance(maximum,bool) or not isinstance(maximum,(int,float)) or not math.isfinite(maximum)
            or isinstance(fps,bool) or not isinstance(fps,(int,float)) or not math.isfinite(fps) or fps<=0):
        raise ValueError('秒数转换的原生范围或帧率无效。')
    value=maximum/fps
    if not math.isfinite(value):raise ValueError('秒数转换的范围无法表示。')
    while round(value*fps)>maximum:value=math.nextafter(value,-math.inf)
    return value


def reviewed_derived_unit_bounds(workflow,controls,*,graph,source_hash):
    idx=int(workflow['id'].rsplit('-',1)[-1]) if workflow['id'].startswith('local-card-') else -1
    contract=DERIVED_NATIVE_LIMITS.get(idx)
    if not contract:return controls
    expected,nid,key,typ,minimum,maximum=contract
    if source_hash!=expected or graph.nodes.get(nid,{}).get('type')!=typ:
        raise ValueError('秒数转换的原始来源已改变，需要重新审查。')
    field=next((c for c in controls if(c.get('derived')or{}).get('targetId')==nid+':'+key),None)
    if field is None:raise ValueError('秒数转换的原生输入绑定缺失。')
    operation=field['derived'].get('operation')
    if operation!=('audio-end' if idx==98 else 'frames'):
        raise ValueError('秒数转换的类型已改变。')
    field['derived']['nativeBounds']={'min':minimum,'max':maximum}
    if operation=='frames':
        fps=field['derived'].get('fps')
        if isinstance(fps,bool)or not isinstance(fps,(int,float))or fps!=24:
            raise ValueError('秒数转换的已审查帧率已改变。')
        field['min']=max(0,minimum/fps)
        field['max']=frame_seconds_maximum(maximum,fps)
    else:
        # The endpoint is start + duration. A duration ceiling is not an
        # endpoint ceiling; validate the subtraction against nativeBounds.
        field.pop('max',None)
    return controls

# Names carry the explanation; hints remain only for non-obvious behavior.
HELP = {
 'playback':'只改速度，不补帧',
 'restoration':'越大，重绘改动越多',
 'mask':'白色区域为清理区',
}

TEXTS = {
 79:{'19:prompt':'写真补充要求'},
 92:{'22:value':'清理区域描述','64:text':'细节修复描述'},
 34:{'1479:text':'文字分支 · 用户描述','1488:text':'文字分支 · 扩写指令',
     '1520:text':'图片分支 · 用户描述','1518:text':'图片分支 · 扩写指令',
     '1514:prompt':'文字分支 · 补充要求','1525:prompt':'图片分支 · 补充要求'},
 0:{'581:value':'生成视频描述','577:prompt':'提示词辅助 · 用户描述'},
}
# These paths reach a positive encoder through joins, translation, prompt
# helpers or subgraph boundaries. Direct-encoder discovery cannot see them.
PROMPT_INPUTS = {
 41:'400:value',43:'376:value',47:'222:value',48:'376:value',49:'407:value',
 50:'567:value',59:'270:value',75:'135:value',85:'67:value',
 87:'704:value',88:'684:value',105:'186:value',106:'134:value',108:'63:value',
}
PROMPT_INPUTS_BY_ID = {
 'local-local-03ae6981ed':'400:value',
 'local-local-16cf1a4ad1':'270:value',
}
INTERNAL = {79:{'31','32','34'},34:{'1492','1522'}}

# Reviewed against the compute card's object_info on 2026-10-04. These are
# creation decisions on enabled output branches, not sampler/encoder controls.
# The current graph supplies every default; this table supplies only verified
# labels, allowed values and node constraints. Independent branches stay apart.
REVIEW70_INPUTS = {
 7:[('13','strength_small_face','restoration','小脸修复强度',{'min':0,'max':1,'step':0.01}),
    ('13','strength_large_face','restoration','大脸修复强度',{'min':0,'max':1,'step':0.01})],
 36:[(nid,key,kind,branch+' · '+label,extra) for nid,branch in [('17','文字生成'),('10','参考图编辑')]
     for key,kind,label,extra in [
      ('size','ratio','画面尺寸',{'options':[{'value':v,'label':'自动' if v=='auto' else v.replace('x','×')} for v in ['auto','1024x1024','1536x1024','1024x1536','2048x2048','2048x1152','3840x2160','2160x3840']]}),
      ('n','count','生成数量',{'min':1,'max':10,'step':1}),
      ('quality','choice','生成质量',{'options':[{'value':v,'label':label} for v,label in [('auto','自动'),('high','高'),('medium','中'),('low','低')]]})]],
 37:[('5','ratio','ratio','长视频 · 画面比例',{'options':['2:3','3:2','16:9','9:16','1:1']}),
     ('6','ratio','ratio','标准视频 · 画面比例',{'options':['2:3','3:2','16:9','9:16','1:1']}),
     ('6','resolution','choice','标准视频 · 输出清晰度',{'options':['480P','720P','1080P']})],
 38:[(nid,key,kind,branch+' · '+label,extra) for nid,branch in [('12','文字生成'),('5','参考图编辑')]
     for key,kind,label,extra in [
      ('aspect_ratio','ratio','画面比例',{'options':[{'value':v,'label':'自动' if v=='auto' else v} for v in ['auto','16:9','4:3','4:5','3:2','1:1','2:3','3:4','5:4','9:16','21:9','9:21']]}),
      ('image_size','choice','输出规格',{'options':['1K','2K','4K']})]],
 131:[('136','strength','strength','参考约束强度',{'min':-10,'max':10,'step':0.01,'help':'调整对原图的依赖'}),
      ('158','upscale_by','upscale','放大倍率',{'min':0.05,'max':4,'step':0.05}),
      ('158','denoise','restoration','细节重绘幅度',{'min':0,'max':1,'step':0.01})],
 124:[('44','middle_frame_ratio','strength','中间帧位置',{'min':0,'max':1,'step':0.01,'help':'0 开头，1 末尾'})],
}
for _idx,_node in [(24,'3744'),(25,'641'),(26,'471'),(27,'771'),(31,'62'),(116,'771')]:
    REVIEW70_INPUTS[_idx]=[(_node,'face_strength','motion','面部动作参考强度',{'min':0,'max':10,'step':0.001,'help':'越大，面部动作跟随越强'})]
REVIEW70_INPUTS[116].append(('771','pose_strength','motion','动作参考强度',{'min':0,'max':10,'step':0.001,'help':'越大，动作跟随越强'}))
REVIEW70_INPUTS[89]=[('28','resolution','ratio','画面尺寸',{'options':[{'value':v,'label':v.replace('x','×')} for v in ['1024x1024','1152x896','896x1152','1216x832','832x1216','1344x768','768x1344','1536x640','640x1536']]})]
REVIEW70_INPUTS[46]=[('5149',key,'outpaint',label,{'min':0,'max':16384,'step':1}) for key,label in [('left','向左扩展（像素）'),('right','向右扩展（像素）'),('top','向上扩展（像素）'),('bottom','向下扩展（像素）')]]
REVIEW70_INPUTS[57]=[('56','switch','toggle','使用尾帧',{'type':'checkbox','help':'开启后才会使用尾帧图片'})]
REVIEW70_INPUTS[22]=[('197','object_indices','indices','动作与参考图处理对象',{'help':'留空处理所有检测对象；填写检测结果中的对象编号，例如 0,2。编号以检测结果为准。','type':'string'}),
                    ('579','object_indices','indices','参考图保留对象',{'help':'留空处理所有检测对象；填写检测结果中的对象编号，例如 0,2。编号以检测结果为准。','type':'string'})]
REVIEW70_INPUTS[23]=[('527','object_indices','indices','处理对象',{'help':'留空处理所有检测对象；填写检测结果中的对象编号，例如 0,2。编号以检测结果为准。','type':'string'})]
REVIEW70_INPUTS[97]=[('23',key,'choice',label,{'options':[{'value':'enable','label':'启用'},{'value':'disable','label':'忽略'}]})
    for key,label in [('detect_hand','手部姿态'),('detect_body','身体姿态'),('detect_face','面部姿态')]]
REVIEW70_INPUTS[97].append(('18','megapixels','resolution','输出总像素',{'min':0.01,'max':16,'step':0.01,'unit':'MP','help':'越大，生成成本越高'}))
REVIEW70_INPUTS[86]=[('88','strength','strength','参考约束强度',{'min':-10,'max':10,'step':0.01,'help':'调整参考图约束'})]
REVIEW70_INPUTS[125]=[(nid,'strength','strength',label,{'min':0,'max':10,'step':0.01}) for nid,label in [('216','首帧参考强度'),('214','尾帧参考强度')]]
REVIEW70_INPUTS[126]=[('28','strength','strength','参考素材强度',{'min':0,'max':1000,'step':0.01,'help':'调整首尾帧约束'})]
for _idx,_nid in [(43,'455'),(48,'455'),(49,'440'),(51,'1065')]:
    REVIEW70_INPUTS.setdefault(_idx,[]).append((_nid,'num_guides.strength_1','strength',
        '初次重绘参考强度' if _idx==51 else '原视频参考强度',{'min':0,'max':10,'step':0.01}))

# Source scalar widgets can feed the creative input through Set/Get, casting or
# an explicit seconds-to-frames expression. Review the consuming node's contract
# rather than exposing the converter or silently fixing the clip length.
REVIEW70_LINKED_INPUTS={
 22:[('111','Number','segment','跳过开头帧数',{'min':0,'max':9007199254740991,'step':1,'constraintSources':[{'node':'112','input':'skip_first_frames'}]}),
     ('610','Number','duration','处理时长（秒）',{'min':0,'max':48000,'step':1,'constraintSources':[{'node':'604','input':'a'}],'frameFormula':{'node':'604','expression':'a*b+1','fps':24,'fpsSource':'606:value'}})],
 23:[('563','Number','segment','跳过开头帧数',{'min':0,'max':9007199254740991,'step':1,'constraintSources':[{'node':'552','input':'skip_first_frames'}]}),
     ('573','Number','duration','处理时长（秒）',{'min':0,'max':48000,'step':1,'constraintSources':[{'node':'556','input':'a'}],'frameFormula':{'node':'556','expression':'a*b+1','fps':24,'fpsSource':'572:value'}})],
 30:[('132','value','duration','处理时长（秒）',{'min':0,'max':999999,'step':1,'constraintSources':[{'node':'132','input':'value'}],'frameFormula':{'node':'190','expression':'a*b','fpsSource':'115:value'}})],
 39:[('130','value','resolution','输出宽度（像素）',{'min':16,'max':8192,'step':16,'constraintSources':[{'node':'129','input':'width'}]}),
     ('133','value','resolution','输出高度（像素）',{'min':16,'max':8192,'step':16,'constraintSources':[{'node':'129','input':'height'}]}),
     ('137','value','duration','生成帧数',{'min':1,'max':8192,'step':4,'constraintSources':[{'node':'129','input':'length'}]})],
 40:[('32','value','duration','生成帧数',{'min':1,'max':8192,'step':4,'constraintSources':[{'node':'33','input':'length'}]}),
     ('16','value','duration','参考视频时长（秒）',{'min':0,'max':48000,'step':1,'constraintSources':[{'node':'15','input':'a'}],'frameFormula':{'node':'15','expression':'a*b+1','fps':16,'fpsSource':'13:value'}})],
 89:[('183','value','count','生成数量',{'min':1,'max':4096,'step':1,'constraintSources':[{'node':'10','input':'batch_size'}]})],
 124:[('9','value','duration','生成时长（秒）',{'min':0,'max':511,'step':1,'constraintSources':[{'node':'44','input':'length'}],'frameFormula':{'node':'10','expression':'a*16+1','fps':16}})],
 125:[('225','value','resolution','输出宽度（像素）',{'min':0,'max':16384,'step':1,'help':'0 自动保持比例','constraintSources':[{'node':'223','input':'resize_type.width'},{'node':'224','input':'resize_type.width'}]}),
      ('226','value','resolution','输出高度（像素）',{'min':0,'max':16384,'step':1,'help':'0 自动保持比例','constraintSources':[{'node':'223','input':'resize_type.height'},{'node':'224','input':'resize_type.height'}]})],
 126:[('48','value','duration','生成帧数',{'min':1,'max':10000,'step':4,'constraintSources':[{'node':'28','input':'length'},{'node':'34','input':'num_frames'}]})],
}
for _idx,_nid,_math,_fps_source in [(24,'3743','3748','3732:value'),(25,'654','645','631:value'),(26,'484','475','461:value'),(27,'784','775','761:value'),(31,'319','323','318:value'),(116,'784','775','761:value')]:
    REVIEW70_LINKED_INPUTS[_idx]=[(_nid,'value','duration','处理时长（秒）',{'min':0,'max':48000,'step':1,
        'constraintSources':[{'node':_math,'input':'a'}],'frameFormula':{'node':_math,'expression':'a*b+1','fps':16,'fpsSource':_fps_source}})]
for _idx,_nid,_target in [(43,'369','496'),(47,'220','sub0/83'),(48,'369','496'),(49,'404','453')]:
    REVIEW70_LINKED_INPUTS[_idx]=[(_nid,'value','resolution','输出最长边（像素）',{'min':0,'max':16384,'step':1,
        'constraintSources':[{'node':_target,'input':'resize_type.longer_size'}],'targets':[{'node':_nid,'input':'value'}]})]


def reviewed_default_api_models(workflow, profiles, *, source_hash, graph=None, derived=None):
    """Display the same reviewed owner default that the execution repair uses.

    Saved user API choices are request state, never rewritten by this builder.
    """
    # Direct invocation sets sys.path to scripts/. Load only the reviewed
    # local data module; never import the server or create a database ticket.
    import importlib.util
    from pathlib import Path
    module_spec=importlib.util.spec_from_file_location('yingxu_owner_model_defaults',Path(__file__).resolve().parents[1]/'reviewed_repairs.py')
    repair_module=importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(repair_module)
    SOURCE_HASHES,OWNER_DEFAULT_MODELS=repair_module.SOURCE_HASHES,repair_module.OWNER_DEFAULT_MODELS
    wid=workflow.get('id')
    models=OWNER_DEFAULT_MODELS
    if wid not in models:return profiles
    if source_hash!=SOURCE_HASHES[wid]:raise ValueError('默认 API 模型来源变化，需要重新审查。')
    nid,old,new=models[wid]
    candidates=[p for p in profiles if p['id']==nid]
    if len(candidates)!=1:raise ValueError('默认 API 模型配置节点未匹配。')
    profile=candidates[0]
    if profile.get('bindings',{}).get('model')!={'node':nid,'input':'model'}:
        raise ValueError('默认 API 模型配置绑定未匹配。')
    if graph is not None:
        from build_workflow_interfaces import widget_bindings
        actual=graph.nodes.get(nid,{})
        if actual.get('type')!='RH_LLMAPI_NODE' or widget_bindings(actual).get('model',(None,))[0]!=old:
            raise ValueError('默认 API 模型源节点未匹配。')
    else:
        proof=next((p for p in (derived or {}).get('apiProfiles',[]) if p['id']==nid),{})
        if (derived or {}).get('sourceHash')!=source_hash or proof.get('reviewedOwnerDefaultModel')!=new:
            raise ValueError('默认 API 模型配置缺少同源证明。')
    if profile.get('model') not in (old,new):raise ValueError('默认 API 模型有未经审查的变更。')
    profile.update(model=new,reviewedOwnerDefaultModel=new)
    return profiles


def add_review70_controls(workflow, graph, controls):
    """Add only source-present, unlinked fields from the individually reviewed list."""
    from build_workflow_interfaces import widget_bindings
    idx=int(workflow['id'].split('-')[-1]) if workflow['id'].startswith('local-card-') else -1
    for nid,key,kind,label,extra in REVIEW70_INPUTS.get(idx,[])+REVIEW70_LINKED_INPUTS.get(idx,[]):
        bindings=widget_bindings(graph.nodes.get(nid,{}))
        if key not in bindings or not graph.editable(nid,key):continue
        if any(c['id']==nid+':'+key or any(t=={'node':nid,'input':key} for t in c.get('targets',[])) for c in controls):continue
        current=bindings[key][0]
        control={'id':nid+':'+key,'nodeId':nid,'key':key,'label':label,
                         'node':graph.nodes[nid].get('title')or graph.nodes[nid]['type'],
                         'value':current,'type':'number' if isinstance(current,(int,float)) or idx in REVIEW70_LINKED_INPUTS and 'min' in extra else 'text',
                         'kind':kind,'targets':[{'node':n,'input':k} for n,k in graph.targets(nid,key)],
                         'help':'越大，重绘改动越多' if kind=='restoration' else '',**extra}
        if workflow['category'] in ['视频修复与扩展','数字人与对口型']:
            control['uiGroup']='output'
        controls.append(control)
    if idx==51 and graph.nodes.get('1095',{}).get('type')=='PointsEditor' and graph.editable('1095','coordinates') and not any(c['id']=='1095:points' for c in controls):
        # The UI stores normalized point lists; the adapter converts them to
        # the actual scaled first frame before writing the PointsEditor inputs.
        controls.append({'id':'1095:points','nodeId':'1095','key':'points','kind':'points','type':'text',
                         'value':'{"positive":[],"negative":[]}','label':'选择跟踪主体',
                         'help':'点选主体，红点排除干扰','mediaSlotId':'1084',
                         'targets':[{'node':'1095','input':'coordinates'}],
                         'previewRecipe':{'longSideControlId':'1105:value','longSide':widget_bindings(graph.nodes['1105'])['value'][0],
                                          'multiple':32,'sourceMultiple':8,'fit':'crop','frameRate':widget_bindings(graph.nodes['1084'])['force_rate'][0],
                                          'postScale':widget_bindings(graph.nodes['1058'])['scale_by'][0],
                                          'skipControlId':'1084:skip_first_frames','skipFrames':widget_bindings(graph.nodes['1084'])['skip_first_frames'][0]}})
    if idx==75:
        # This source appends a UI-only empty preview string after five named
        # camera widgets. The generic conservative parser rejects that extra
        # entry, but the card's actual API inputs confirm the first positions.
        camera_fields=[('horizontal_angle','水平视角',0,360,1),('vertical_angle','垂直视角',-30,60,1),('zoom','镜头距离',0,10,0.1)]
        for order,nid in enumerate(('127','129','130','131','132','133'),1):
            node=graph.nodes.get(nid,{})
            values=node.get('widgets_values',[])
            names=[inp['widget']['name'] for inp in node.get('inputs',[]) if inp.get('widget')]
            if node.get('type')!='QwenMultiangleCameraNode' or names[:3]!=[f[0] for f in camera_fields] or len(values)!=len(names)+1 or values[-1]!='':continue
            for position,(key,label,minimum,maximum,step) in enumerate(camera_fields):
                if not graph.editable(nid,key) or any(c['id']==nid+':'+key for c in controls):continue
                controls.append({'id':nid+':'+key,'nodeId':nid,'key':key,'kind':'camera','type':'number',
                                 'label':f'视角 {order} · {label}','node':node.get('title')or node['type'],
                                 'value':values[position],'min':minimum,'max':maximum,'step':step,
                                 'targets':[{'node':nid,'input':key}],'help':''})
    return apply_review70_defaults(workflow,controls)


def apply_review70_defaults(workflow, controls):
    """Record the one source default rejected by the current card node contract."""
    if workflow['id']=='local-card-72':
        field=next((c for c in controls if c['id']=='119:widget_1' and c['key']=='vertical_angle'),None)
        if field:
            field.update(value=0,min=-30,max=60,step=1,sourceDefault=90,
                         defaultAdjustment={'from':90,'to':0,'reason':'源图90°超出当前节点-30°至60°范围，采用节点默认0°',
                                            'source':'QwenMultiangleCameraNode object_info 2026-10-04'})
    return controls


REVIEW70_API_NODES = {
 36:{'10':('参考图编辑 API','GPT Image'), '17':('文字生成 API','GPT Image')},
 37:{'5':('长视频 API','Grok Video'), '6':('标准视频 API','Grok Video')},
 38:{'12':('文字生成 API','Nano Banana'), '5':('参考图编辑 API','Nano Banana')},
}
REVIEW70_API_MODELS = {
 'Comfly_gpt_image_2_official':['gpt-image-2','gpt-image-2-all','gpt-image-2-2K','gpt-image-2-4K'],
 'ComflyGrok3VideoApi30S':['grok-video-3'],
 'ComflyGrok3VideoApi':['grok-video-3'],
 'Comfly_nano_banana2_edit':['nano-banana-2','nano-banana-pro','nano-banana-pro-2k','nano-banana-pro-4k'],
}


def add_review70_api_profiles(workflow, graph, profiles):
    """Fixed-provider nodes accept a personal key without inventing a Base URL."""
    from build_workflow_interfaces import widget_bindings
    idx=int(workflow['id'].split('-')[-1]) if workflow['id'].startswith('local-card-') else -1
    for nid,(label,provider) in REVIEW70_API_NODES.get(idx,{}).items():
        node=graph.nodes.get(nid,{})
        if nid not in graph.reachable or node.get('mode',0) in [2,4]:continue
        bindings=widget_bindings(node)
        key=next((name for name in ('api_key','apikey') if name in bindings),None)
        if not key or 'model' not in bindings or any(p['id']==nid for p in profiles):continue
        # Never copy bindings[key][0]: keys remain solely on the card / server,
        # or in the frontend's existing transient key store for a custom run.
        profiles.append({'id':nid,'label':label,'provider':provider,'keyOnly':True,
                         'baseUrl':'','model':str(bindings['model'][0]),
                         'modelOptions':REVIEW70_API_MODELS[node['type']],
                         'bindings':{'model':{'node':nid,'input':'model'},'apiKey':{'node':nid,'input':key}},
                         'help':'服务地址由节点固定'})
    return profiles


REVIEW70_TEXT_LABELS = {
 22:{'75:text':'跟踪主体描述'},23:{'518:text':'跟踪主体描述'},
 36:{'18:value':'文字生成描述','7:value':'参考图编辑描述'},
 37:{'7:value':'长视频描述','8:value':'标准视频描述'},
 38:{'7:value':'参考图编辑描述','11:value':'文字生成描述'},
}
REVIEW70_PRESERVED_TEXTS={32:{'31:role'},33:{'29:role'},34:{'1488:text','1518:text'}}


def apply_review70_labels(workflow, controls, texts, media):
    """Name independent prompts/media by their proved execution branches."""
    idx=int(workflow['id'].split('-')[-1]) if workflow['id'].startswith('local-card-') else -1
    if idx==131:
        for field in controls:
            if field['id']=='136:strength':field['help']='调整对原图的依赖'
    if idx==57:
        for slot in media:
            if slot['id']=='24':slot['label']='尾帧（需启用）'
    if idx==50:
        for control in controls:
            if control['id']=='403:aspect_ratio':
                control.update(label='处理范围比例',help='保留原片比例，设缩放范围')
            elif control['id']=='403:megapixels':
                control.update(label='处理像素预算',help='按原片比例，像素可能少')
    for text in texts:
        if text['id'] in REVIEW70_TEXT_LABELS.get(idx,{}):
            text['label']=REVIEW70_TEXT_LABELS[idx][text['id']]
        if text['id'] in REVIEW70_PRESERVED_TEXTS.get(idx,set()):
            text['preserveWhenEmpty']=True
    if idx==37:
        for control in controls:
            if control['id']=='5:duration':control['label']='长视频 · 生成时长（秒）'
            elif control['id']=='6:duration':control['label']='标准视频 · 生成时长（秒）'
        for slot in media:
            if slot['id'] in ['13','14','15','16']:
                slot['label']=('长视频' if slot['id'] in ['13','14'] else '标准视频')+'参考图 '+('1' if slot['id'] in ['13','15'] else '2')
    if idx==36:
        for slot in media:
            if slot['id']=='2':slot['label']='编辑参考图'
    for slot in media:
        if slot['kind']=='video' and slot['label']=='身体参考图':
            slot['label']='动作参考视频' if workflow['category']=='动作迁移与舞蹈' else '原视频'
    return controls,texts,media


def refresh_curated_controls(workflow, reviewed, derived):
    """Carry source-checked control corrections into an unchanged curated form."""
    idx=int(workflow['id'].split('-')[-1]) if workflow['id'].startswith('local-card-') else -1
    current=reviewed['controls']
    fresh={field['key']:field for field in derived['controls']}
    fresh_units={field['id']:field for field in derived['controls']
                 if(field.get('derived')or{}).get('operation')in ('frames','audio-end')}
    if idx==19:
        current=[fresh['size']]+[field for field in current if field['kind']=='seed']
    for field in current:
        key=field['key']
        unit=fresh_units.get(field['id'])
        if unit:
            before={k:v for k,v in field.get('derived',{}).items()if k!='nativeBounds'}
            after={k:v for k,v in unit['derived'].items()if k!='nativeBounds'}
            if before!=after or 'nativeBounds'not in unit['derived']:
                raise ValueError('已审核的秒数转换绑定已经改变。')
            field['derived']=copy.deepcopy(unit['derived'])
            for attr in ('min','max'):
                if attr in unit:field[attr]=unit[attr]
                else:field.pop(attr,None)
        if idx in (9,10) and key=='resolution':
            field['options']=[{'value':str(item['value'] if isinstance(item,dict) else item),
                               'label':str(item['value'] if isinstance(item,dict) else item).replace('x','×')}
                              for item in field['options']]
        if idx in (9,10) and key=='output_pixels':
            field.update(label='输出总像素',help='',
                         options=[{'value':n,'label':f'{n} 千像素'} for n in (1024,1536,2048)])
        if idx==13 and key=='output_long_side':field['help']='独立控制最终导出尺寸'
        if idx==14 and key=='zoom':field.update(label='镜头拉近',help='0 远景，10 特写')
        if key=='megapixels':
            source=fresh.get(key)
            if source:
                for attr in ('label','options','help'):
                    if attr in source:field[attr]=source[attr]
    additions={nid+':'+key for nid,key,*_ in REVIEW70_INPUTS.get(idx,[])+REVIEW70_LINKED_INPUTS.get(idx,[])}
    if idx==51:additions.add('1095:points')
    if idx==75:additions.update(nid+':'+key for nid in ('127','129','130','131','132','133') for key in ('horizontal_angle','vertical_angle','zoom'))
    current.extend(field for field in derived['controls'] if field['id'] in additions and not any(c['id']==field['id'] for c in current))
    if idx==135:
        current=directory_image_order_control(current)
    if idx==93:
        current=description_language_control(current)
    if idx==122 and derived.get('sourceHash')=='0036eac90c054211b9507171597c8486415ca4b2504d4cbf33c373e36e269f91':
        current=seedvr2_short_edge_control(current)
    if idx==30:
        current,reviewed['texts']=dance_ratio_protocol_form(
            current,reviewed.get('texts',[]),source_hash=derived.get('sourceHash'))
    api_additions=REVIEW70_API_NODES.get(idx,{})
    reviewed.setdefault('apiProfiles',[]).extend(profile for profile in derived.get('apiProfiles',[]) if profile['id'] in api_additions and not any(p['id']==profile['id'] for p in reviewed['apiProfiles']))
    reviewed['apiProfiles']=reviewed_default_api_models(workflow,reviewed['apiProfiles'],
        source_hash=derived.get('sourceHash'),derived=derived)
    for field in current:
        if field['kind']=='restoration' and 'denoise' in field.get('key',''):
            # KSampler.INPUT_TYPES uses hundredths; defaults such as .17 must
            # stay directly submitable rather than being rounded to .05 steps.
            field['step']=0.01
    # Only the verified fresh annotation crosses into an unchanged curated form.
    fresh_by_id={field['id']:field for field in derived['controls']}
    guidance_source=H3_DURATION_SOURCES.get(idx)
    if guidance_source and derived.get('sourceHash')==guidance_source[0]:
        for field in current:
            source=fresh_by_id.get(field['id'],{})
            if field['id']==guidance_source[1] and source.get('effectiveDuration')==H3_DURATION_RECIPE:
                field.update(effectiveDuration=dict(H3_DURATION_RECIPE),help=source['help'])
    if idx==60 and derived.get('sourceHash')==H3_REPAIR_DURATION_HASH:
        for field in current:
            source=fresh_by_id.get(field['id'],{})
            if field['id']=='366:value' and source.get('help')=='依选段及原片长度补齐':
                field['help']=source['help']
    requested_source=H3_REQUESTED_DURATION_SOURCES.get(idx)
    if requested_source and derived.get('sourceHash')==requested_source[0]:
        for field in current:
            source=fresh_by_id.get(field['id'],{})
            if field['id']==requested_source[1] and source.get('help')==H3_REQUESTED_DURATION_HELP:
                field['help']=source['help']
    reviewed['controls']=current
    apply_review70_defaults(workflow,reviewed['controls'])
    apply_review70_labels(workflow,reviewed['controls'],reviewed.get('texts',[]),reviewed.get('media',[]))
    reviewed['media']=reviewed_media_roles(workflow,reviewed.get('media',[]),source_hash=derived.get('sourceHash'))
    from portrait_size_contract import reviewed_portrait_size_controls
    reviewed['controls']=reviewed_portrait_size_controls(workflow,reviewed['controls'],
        source_hash=derived.get('sourceHash'),derived=derived)
    from camera72_contract import reviewed_camera72_controls
    reviewed['controls']=reviewed_camera72_controls(workflow,reviewed['controls'],source_hash=derived.get('sourceHash'),derived=derived)
    from review74_parameter_contracts import reviewed_independent_seeds,reviewed_batch_count,reviewed_color_supplement,reviewed_camera14_size,reviewed_final_enhancement_size,reviewed_refinement_reference,reviewed_inactive_middle_position,reviewed_multiview_output_size
    reviewed['controls']=reviewed_independent_seeds(workflow,reviewed['controls'],source_hash=derived.get('sourceHash'),derived=derived)
    reviewed['controls']=reviewed_batch_count(workflow,reviewed['controls'],source_hash=derived.get('sourceHash'))
    reviewed['controls']=reviewed_camera14_size(workflow,reviewed['controls'],source_hash=derived.get('sourceHash'),derived=derived)
    reviewed['controls']=reviewed_final_enhancement_size(workflow,reviewed['controls'],source_hash=derived.get('sourceHash'),derived=derived)
    reviewed['controls']=reviewed_refinement_reference(workflow,reviewed['controls'],source_hash=derived.get('sourceHash'),derived=derived)
    reviewed['controls']=reviewed_inactive_middle_position(workflow,reviewed['controls'],source_hash=derived.get('sourceHash'),derived=derived)
    reviewed['controls']=reviewed_multiview_output_size(workflow,reviewed['controls'],source_hash=derived.get('sourceHash'),derived=derived)
    from review75_generation_sizes import reviewed_generation_sizes
    reviewed['controls']=reviewed_generation_sizes(workflow,reviewed['controls'],source_hash=derived.get('sourceHash'),derived=derived)
    reviewed['texts']=reviewed_color_supplement(workflow,reviewed.get('texts',[]),source_hash=derived.get('sourceHash'),derived=derived)
    from reviewed_stage_seeds import reviewed_stage_seeds
    reviewed['controls']=reviewed_stage_seeds(workflow,reviewed['controls'],source_hash=derived.get('sourceHash'),derived=derived)
    from reviewed_native_seed_limits import reviewed_native_seed_limits
    reviewed['controls']=reviewed_native_seed_limits(workflow,reviewed['controls'],source_hash=derived.get('sourceHash'),derived=derived)
    # Curated layouts keep their field order, while these graph-proved display
    # corrections must survive an unchanged sourceHash.
    fresh_texts={field['id']:field for field in derived.get('texts',[])}
    for field in reviewed.get('texts',[]):
        source=fresh_texts.get(field['id'],{})
        if source.get('label')in ('分割目标','姿势检测目标'):
            field.update(label=source['label'],help=source.get('help',''))
        if source.get('preserveWhenEmpty')is True:field['preserveWhenEmpty']=True
    if idx in (24,124):
        fresh_media={field['id']:field for field in derived.get('media',[])}
        for field in reviewed.get('media',[]):
            source=fresh_media.get(field['id'],{})
            if source.get('label')in ('背景图','角色参考图','首帧','尾帧'):field['label']=source['label']
    return reviewed


def dance_ratio_protocol_form(controls,texts,*,graph=None,source_hash=None):
    """Keep the reviewed orientation-ratio constants out of creative text UI."""
    expected_hash='1d4bb89d8e5531a50b800e5d1228ac9a230091b4df1ab7bf49e9e4062fc115c0'
    if source_hash is not None and source_hash!=expected_hash:
        raise ValueError('姿势迁移比例来源已改变，需要重新审查。')
    if graph is not None:
        from build_workflow_interfaces import widget_bindings
        nodes=graph if isinstance(graph,dict)else graph.nodes
        def kind(nid):
            entry=nodes.get(nid,{})
            return entry.get('class_type',entry.get('type'))
        def value(nid,key):
            entry=nodes.get(nid,{})
            if isinstance(graph,dict):return entry.get('inputs',{}).get(key)
            return widget_bindings(entry).get(key,(None,None))[0]
        def links(nid):
            if isinstance(graph,dict):
                return {(dst,key,val[1])for dst,node in graph.items()
                        for key,val in node.get('inputs',{}).items()
                        if isinstance(val,list)and len(val)==2 and str(val[0])==nid}
            return {(dst,nodes[dst]['inputs'][slot]['name'],output)
                    for dst,slot,output in graph.out.get(nid,[])}
        if not (kind('156')==kind('157')=='CR Text'
                and value('156','text')=='16:9' and value('157','text')=='9:16'
                and kind('160')=='LazySwitch1way'
                and kind('161')=='LayerUtility: ImageScaleByAspectRatio V2'
                and value('161','scale_to_side')=='shortest'
                and links('156')=={('160','ON_TRUE',0)}
                and links('157')=={('160','ON_FALSE',0)}
                and links('160')=={('161','aspect_ratio',0)}
                and ('160','boolean',0) in links('158')):
            raise ValueError('姿势迁移比例协议连线已改变，不能隐藏未知文本输入。')
    for field in texts:
        if field['id'] in ('156:text','157:text'):
            nid=field['id'].split(':',1)[0]
            if field.get('key')!='text' or field.get('targets') not in (None,[{'node':nid,'input':'text'}]):
                raise ValueError('姿势迁移比例文本绑定已改变，需要重新审查。')
    for field in controls:
        if field['id']=='159:widget_0':
            if field.get('targets') != [{'node':'161','input':'scale_to_length'}]:
                raise ValueError('姿势迁移输出边长绑定已改变，需要重新审查。')
            field.update(label='输出短边（像素）')
    return controls,[field for field in texts if field['id'] not in ('156:text','157:text')]


def directory_image_order_control(controls):
    """Expose the exact Inspire sorting socket; do not hide an execution default."""
    options=[{'value':value,'label':label} for value,label in (
        ('None','原目录顺序'),('Alphabetical (ASC)','文件名升序'),
        ('Alphabetical (DESC)','文件名降序'),('Numerical (ASC)','数字升序'),
        ('Numerical (DESC)','数字降序'),('Datetime (ASC)','修改时间升序'),
        ('Datetime (DESC)','修改时间降序'))]
    field=next((field for field in controls if field['id']=='12:sort_method'),None)
    if field is None:
        controls.append({'id':'12:sort_method','key':'sort_method','nodeId':'12',
                         'node':'LoadImageListFromDir //Inspire','label':'图片排列顺序',
                         'type':'text','kind':'choice','value':'Alphabetical (ASC)',
                         'options':options,'targets':[{'node':'12','input':'sort_method'}],
                         'help':'连续帧按001命名','uiGroup':'read'})
    else:
        field.update(label='图片排列顺序',options=options,
                     help='连续帧按001命名',uiGroup='read')
    return controls


def description_language_control(controls):
    """Explicit routing using the translator's real source-language socket."""
    options=[{'value':value,'label':label}for value,label in (
        ('auto','自动翻译'),('english','英文直接使用'),
        ('chinese (simplified)','简体中文翻译'))]
    field=next((field for field in controls if field['id']=='76:from_translate'),None)
    if field is None:
        controls.append({'id':'76:from_translate','key':'from_translate','nodeId':'76',
                         'node':'DeepTranslatorTextNode','label':'描述语言',
                         'type':'text','kind':'choice','value':'auto','options':options,
                         'targets':[{'node':'76','input':'from_translate'}],
                         'help':'英文直接使用，不翻译'})
    else:
        field.update(label='描述语言',options=options,help='英文直接使用，不翻译')
    return controls


def verified_description_language_options(field, actual_choices):
    """Keep only the three reviewed, registered values when compiling 93."""
    options=description_language_control([])[0]['options']
    if (field.get('id')!='76:from_translate' or
            field.get('targets')!=[{'node':'76','input':'from_translate'}] or
            [item.get('value')for item in field.get('options',[])]!=[item['value']for item in options] or
            any(item['value']not in actual_choices for item in options)):
        raise ValueError('描述语言选项与实际翻译节点不一致，需重新审查。')
    return options


def seedvr2_short_edge_control(controls):
    """Match the registered SeedVR2 resolution range on its reviewed UI binding."""
    field=next((field for field in controls if field['id']=='34:value'),None)
    if field is None:return controls
    if field.get('type')!='number' or field.get('targets')!=[{'node':'10','input':'resolution'}]:
        raise ValueError('输出短边绑定已变化，需重新审查。')
    field.update(min=16,max=16384,step=2,integer=True)
    return controls


def downstream(graph,nid):
    pending, seen, result = [nid], set(), []
    while pending:
        src=pending.pop()
        if src in seen: continue
        seen.add(src)
        for dst,slot,_ in graph.out[src]:
            n=graph.nodes.get(dst,{})
            ins=n.get('inputs',[])
            if slot<len(ins):result.append((dst,ins[slot]['name']))
            if dst in graph.nodes:pending.append(dst)
    return result


def label_first_last_frames(graph,media):
    """Follow IMAGE data through the reviewed resize nodes, not size wires."""
    for item in media:
        if item.get('kind')!='image':continue
        pending,seen,roles=[item['id']],set(),set()
        while pending:
            src=pending.pop()
            if src in seen:continue
            seen.add(src)
            for dst,slot,output in graph.out[src]:
                node=graph.nodes.get(dst,{})
                inputs=node.get('inputs',[])
                if output!=0 or slot>=len(inputs) or dst not in graph.reachable:continue
                key=inputs[slot].get('name')
                if node.get('type')in ('WanFirstLastFrameToVideo','WanFirstMiddleLastFrameToVideo') and key in ('start_image','end_image'):
                    roles.add(key)
                elif node.get('type')=='ImageResizeKJv2' and key=='image':pending.append(dst)
        if roles=={'start_image'}:item['label']='首帧'
        elif roles=={'end_image'}:item['label']='尾帧'
    return media


def preserves_system_instruction(graph,nid,key):
    """Only a proved reachable multiline constant feeding system_prompt."""
    nodes=graph if isinstance(graph,dict)else graph.nodes
    source=nodes.get(nid,{})
    if key!='value' or source.get('class_type',source.get('type'))!='PrimitiveStringMultiline':return False
    if isinstance(graph,dict):
        return any(node.get('class_type')=='VisionAPIDirect' and node.get('inputs',{}).get('system_prompt')==[nid,0]
                   for node in graph.values())
    for dst,slot,output in graph.out[nid]:
        node=nodes.get(dst,{})
        inputs=node.get('inputs',[])
        if dst in graph.reachable and output==0 and node.get('type')=='VisionAPIDirect' and slot<len(inputs) and inputs[slot].get('name')=='system_prompt':return True
    return False


def reviewed_text_purpose(graph,nid,key):
    """Name detection text only when it reaches the proved detector input."""
    nodes=graph if isinstance(graph,dict)else graph.nodes
    node=nodes.get(nid,{})
    typ=node.get('class_type',node.get('type'))
    if not isinstance(graph,dict)and nid not in graph.reachable:return {}
    if typ=='SDPoseOODProcessor'and key=='prompt':
        return {'label':'姿势检测目标','help':'用简短词描述目标'}
    if typ!='PrimitiveStringMultiline'or key!='value':return {}
    if isinstance(graph,dict):
        consumers=[(other.get('class_type'),name)for other in graph.values()
                   for name,value in other.get('inputs',{}).items()if value==[nid,0]]
    else:
        consumers=[]
        for dst,slot,output in graph.out[nid]:
            other=nodes.get(dst,{});inputs=other.get('inputs',[])
            if dst in graph.reachable and output==0 and slot<len(inputs):consumers.append((other.get('type'),inputs[slot].get('name')))
    if consumers and all(typ in ('LayerMask: SegmentAnythingUltra','LayerMask: SegmentAnythingUltra V2','LayerMask: SegmentAnythingUltra V3')and name=='prompt'for typ,name in consumers):
        return {'label':'分割目标','help':'用简短词描述目标'}
    return {}


def label_animate_reference_slots(graph,media):
    """Follow actual IMAGE ports; ignore resize geometry and mask branches."""
    for item in media:
        if item.get('kind')!='image'or graph.nodes.get(item['id'],{}).get('type')!='LoadImage':continue
        pending,seen,roles=[item['id']],set(),set()
        while pending:
            src=pending.pop()
            if src in seen:continue
            seen.add(src)
            for dst,slot,output in graph.out[src]:
                node=graph.nodes.get(dst,{});inputs=node.get('inputs',[])
                if output!=0 or dst not in graph.reachable or slot>=len(inputs):continue
                typ=node.get('type');key=inputs[slot].get('name')
                if typ=='WanVideoAnimateEmbeds'and key in ('ref_images','bg_images'):roles.add(key)
                elif ((typ in ('ImageResizeKJv2','RepeatImageBatch','DrawMaskOnImage')and key=='image')or
                      typ=='Any Switch (rgthree)'and key.startswith('any_')):pending.append(dst)
        if roles=={'bg_images'}:item['label']='背景图'
        elif roles=={'ref_images'}:item['label']='角色参考图'
    return media


def safe_endpoint(value):
    try:
        u=urlsplit(str(value));return urlunsplit((u.scheme,u.hostname+((':'+str(u.port)) if u.port else '') if u.hostname else '',u.path,'','')) if u.scheme in ['http','https'] else ''
    except ValueError:return ''


H3_DURATION_SOURCES={
 4:('204e1f8d6eccd1995721ee8f1281a57edd0ee3b86af2edef33ba64bd2afa3549','69:value','69','68','144','53'),
 52:('5be77a076e8ec3988556a8259499661c6fca728e4a809c093cb6994b3f59ed1b','69:value','69','68','144','53'),
 54:('47fe1f8301a17197c7b06a089ac61c97e22310651a496bd69df50c1500c41446','121:value','142','141','140','139'),
 56:('0502f0dc461bd07cfc6047bcaa00eaccd4fb061b7e5d5111b0c5179402107f2c','132:value','sub0/111','sub0/107','sub0/104','sub0/91'),
 57:('ebd2ee400475fdf6158c1fb52f1cd5d7842e32284d7a1143432d1b816782f0a5','8:value','29','28','18','53'),
 65:('25809c9610340136a70db167c36b74101365808cd7ed38bef50a821951be9fdc','144:value','168','167','166','165'),
 71:('7537b76022fd8d9701c122f092bf5ea0becbedc35d0f7bdec6706b7041c7a824','16:value','32','19','13','15'),
}
H3_DURATION_RECIPE={'kind':'h3-frame-grid','fps':24,'minFrames':5,'stepFrames':17,'rounding':'python-round'}
H3_DURATION_HELP='模型会补齐到支持的长度'
H3_REPAIR_DURATION_HASH='6efa2411b5e5f4211054ea8b51e4b2e53adc053a57c55c7c7d866f485caecb48'
H3_REQUESTED_DURATION_SOURCES={
 55:('13d646fa7dd7669d9b1ac2792ba1029889284bce7bd35d15b8172a2cf9a589f1','105:value_1','sub0/111','sub0/107','sub0/104','sub0/91'),
 58:('cd02a64bdf7ef7e28d91aad6731b7eea7e115a84504b4ad03dc0d2f742de0053','14:value','31','21','18','9'),
 63:('0455d4a25ad67f328b077c8f031c0b71f5e8d90f185af5e219f813072f2caf05','7:value','27','14','28','26'),
 64:('2aee949e9b20edabc0971eb08d106eb27cee0e11a45d7383afb1e00333530bdc','133:value','133','132','131','130'),
}
H3_REQUESTED_DURATION_HELP='至少5帧，时长按帧取整'


def reviewed_h3_duration_guidance(workflow,graph,controls,*,source_hash=None):
    """Annotate only source-pinned, reachable H3 duration/FPS chains."""
    from build_workflow_interfaces import widget_bindings
    idx=int(workflow['id'].split('-')[-1]) if workflow['id'].startswith('local-card-') else -1
    def kind(nid):return graph.nodes.get(nid,{}).get('type')
    def value(nid,key):return widget_bindings(graph.nodes.get(nid,{})).get(key,(None,None))[0]
    def edge(src,dst,key,output=0):
        return any(target==dst and out==output and slot<len(graph.nodes[dst].get('inputs',[])) and
                   graph.nodes[dst]['inputs'][slot]['name']==key for target,slot,out in graph.out.get(src,[]))
    def fixed_fps(nid):
        return kind(nid)=='CreateVideo' and value(nid,'fps')==24 and not any(
            graph.nodes[nid]['inputs'][slot]['name']=='fps' for _,slot,_ in graph.ins.get(nid,[]))
    if idx in H3_REQUESTED_DURATION_SOURCES:
        expected,control_id,relay,math,consumer,save=H3_REQUESTED_DURATION_SOURCES[idx]
        expression='max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17'
        if not(source_hash==expected and kind(relay)=='PrimitiveFloat' and kind(math)=='ComfyMathExpression' and
               value(math,'expression')==expression and edge(relay,math,'values.a') and
               kind(consumer)=='MiniMaxH3ImageToVideo' and edge(math,consumer,'length',1) and
               all(nid in graph.reachable for nid in (relay,math,consumer,save)) and fixed_fps(save)):
            return controls
        expected_targets=([{'node':relay,'input':'value'}] if idx!=64 else [{'node':math,'input':'values.a'}])
        for field in controls:
            if field['id']==control_id and field.get('kind')=='duration' and field.get('targets')==expected_targets:
                field['help']=H3_REQUESTED_DURATION_HELP
    elif idx in H3_DURATION_SOURCES:
        expected,control_id,relay,math,consumer,save=H3_DURATION_SOURCES[idx]
        if source_hash!=expected:return controls
        source=control_id.split(':')[0]
        source_path=(edge(source,'135','value_1') and edge('135',relay,'value',5)) if idx==56 else (
            source==relay or edge(source,relay,'value'))
        expression='max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17'
        if not(source_path and kind(relay)=='PrimitiveFloat' and kind(math)=='ComfyMathExpression' and
               value(math,'expression')==expression and edge(relay,math,'values.a') and
               kind(consumer)==('MiniMaxH3ReferenceToVideo'if idx in(4,52)else 'MiniMaxH3ImageToVideo') and edge(math,consumer,'length',1) and
               all(nid in graph.reachable for nid in (source,relay,math,consumer,save)) and fixed_fps(save)):
            return controls
        expected_targets=([{'node':'135','input':'value_1'}]if idx==56 else
                          [{'node':'182','input':'float_'},{'node':'68','input':'values.a'}]if idx in(4,52)else
                          [{'node':relay,'input':'value'}])
        for field in controls:
            if field['id']==control_id and field.get('targets')==expected_targets and field.get('kind')=='duration':
                field.update(effectiveDuration=dict(H3_DURATION_RECIPE),help=H3_DURATION_HELP)
    elif idx==60 and source_hash==H3_REPAIR_DURATION_HASH:
        if not(kind('365')=='Evaluate Integers' and value('365','python_expression')=='a*b+1' and
               edge('366','365','a') and value('164','value')==24 and edge('164','365','b') and
               kind('359')=='VHS_LoadVideo' and value('359','force_rate')==24 and edge('365','359','frame_load_cap') and
               kind('353')=='VHS_VideoInfo' and edge('359','353','video_info',3) and
               kind('289')=='EmptyMiniMaxH3LatentAV' and edge('353','289','length',6) and
               all(nid in graph.reachable for nid in ('366','365','359','353','289'))):return controls
        for field in controls:
            if field['id']=='366:value' and field.get('targets')==[{'node':'365','input':'a'}]:
                field['help']='依选段及原片长度补齐'
    return controls


def reviewed_media_roles(workflow,media,*,source_hash=None):
    roles={
      'local-card-112':('4df1a3d0a0b345d345a1092e7d2aafc158051da9612f6979bd7ca2540c269ffe',{'76':'待去遮挡原图','205':'颜色参考图'}),
      'local-card-97':('9384c460c9af79dbc32de960beda895bd8492cc7d11ba11d9cd60ffea27e3c26',{'7':'人物原图','24':'姿势参考图'}),
      'local-card-113':('8b39490de70ada82241859f38ac197521f0876b695a6886077ce6cd2d139f90a',{'76':'线稿原图','81':'颜色参考图'})}
    contract=roles.get(workflow.get('id'))
    if not contract:return media
    expected,labels=contract
    if source_hash!=expected or len(media)!=len(labels) or {m['id'] for m in media}!=set(labels) or any(m['kind']!='image' for m in media):
        raise ValueError('已审素材角色或来源已改变。')
    result=copy.deepcopy(media)
    for field in result:
        field['label']=labels[field['id']]
    return sorted(result,key=lambda field:list(labels).index(field['id']))


def customize(w,graph,controls,texts,media,*,source_hash=None):
    from build_workflow_interfaces import widget_bindings
    idx=int(w['id'].split('-')[-1]) if w['id'].startswith('local-card-') else -1
    prompt_input=PROMPT_INPUTS.get(idx) or PROMPT_INPUTS_BY_ID.get(w['id'])
    if prompt_input:
        tid=prompt_input;nid,key=tid.rsplit(':',1)
        if graph.editable(nid,key) and tid not in {t['id'] for t in texts}:
            texts.insert(0,{'id':tid,'key':key,'node':graph.nodes[nid].get('title')or graph.nodes[nid]['type'],
                'role':'prompt','label':'生成视频描述' if w['category']=='视频编辑与人物替换' else '创作描述'})
    # Recover source-specific inputs omitted by the discovery catalog.
    def add_control(nid,key,kind,label):
        b=widget_bindings(graph.nodes[nid])
        if key not in b or not graph.editable(nid,key):return
        if any(c['id']==nid+':'+key for c in controls):return
        v=b[key][0]
        controls.append({'id':nid+':'+key,'nodeId':nid,'key':key,'node':graph.nodes[nid].get('title')or graph.nodes[nid]['type'],
            'value':v,'type':'number' if isinstance(v,(int,float)) else 'text','kind':kind,'label':label,
            'targets':[{'node':t,'input':k}for t,k in graph.targets(nid,key)]})
    if idx==13:add_control('131','scale_to_length','resolution','输出最长边')
    if idx==45:add_control('53','value','resolution','输出最长边（像素）')
    if idx==74:
        # The Int node's lone unnamed widget drives both scale_to_length and
        # max_size on the two active image branches. The discovery catalog has
        # widget_0, while the graph socket is named Number.
        source=next((f for f in w['fields'] if f['id']=='361:widget_0'),None)
        target_keys={'scale_to_length','max_size'}
        targets=[{'node':dst,'input':graph.nodes[dst]['inputs'][slot]['name']}
                 for dst,slot,outslot in graph.out['361'] if outslot==0 and
                 graph.nodes[dst]['inputs'][slot]['name'] in target_keys]
        if source and graph.nodes['361']['type']=='Int' and graph.editable('361','Number') and len(targets)==4:
            controls.append({**source,'kind':'resolution','label':'输出最长边（像素）',
                             'targets':targets,'min':1,'step':1})
    if idx==102:
        texts=[t for t in texts if t['id']not in ['56:prompt','57:prompt']]
        add_control('56','prompt','segment','音频片段起点（分:秒）')
        add_control('57','prompt','segment','音频片段终点（分:秒）')
    if idx==103:add_control('104','value','motion','单段生成帧数')
    if idx==5:add_control('378','value','segment','处理总帧数（0 为全部）')
    for nid,n in graph.nodes.items():
        if nid not in graph.reachable or n.get('mode',0)in[2,4]:continue
        b=widget_bindings(n)
        if n['type']=='Primitive string multiline [Crystools]' and 'string'in b and graph.editable(nid,'string'):
            if any(k=='text' for _,k in graph.targets(nid,'string')):
                texts.append({'id':nid+':string','key':'string','node':n.get('title')or n['type'],'role':graph.text_role(nid,'string')})
        if w['category']=='提示词辅助':
            for key in ['system_prompt','role']:
                if key in b and graph.editable(nid,key):
                    texts.append({'id':nid+':'+key,'key':key,'node':n.get('title')or n['type'],'role':'prompt','label':'扩写指令'})
    apis=[]
    for nid,n in graph.nodes.items():
        if nid not in graph.reachable or n.get('mode',0)in[2,4]:continue
        b=widget_bindings(n)
        if not re.search(r'LLMAPI|VisionAPI',n['type']):continue
        base=next((k for k in ['api_baseurl','base_url','api_base_url'] if k in b),None)
        if not base or 'model' not in b:continue
        apis.append({'id':nid,'label':('图片分支' if nid=='1525' else '文字分支') if idx==34 else '提示词辅助 API' if re.search('LLMAPI',n['type']) else '视觉分析 API',
          'baseUrl':safe_endpoint(b[base][0]),'model':str(b['model'][0]),
          'bindings':{'baseUrl':{'node':nid,'input':base},'model':{'node':nid,'input':'model'},'apiKey':{'node':nid,'input':'api_key'}},
          'help':'需兼容节点协议'})
    # Never mistake a linked credential primitive for a creative prompt.
    clean=[]
    for t in texts:
        nid=t['id'].rsplit(':',1)[0]
        if nid in INTERNAL.get(idx,set()):continue
        if any(re.search('api.?key|authorization|access.?token',k,re.I) for _,k in downstream(graph,nid)):continue
        if t['id'] not in {x['id'] for x in clean}:clean.append(t)
    texts=clean
    for nid,n in graph.nodes.items():
        if n.get('mode',0)in[2,4] or nid not in graph.reachable:continue
        b=widget_bindings(n)
        if n['type']in['PrimitiveStringMultiline','PrimitiveString'] and 'value'in b and graph.editable(nid,'value'):
            ts=graph.targets(nid,'value')
            if any(re.search('prompt|text',k,re.I) for _,k in ts) and not any(re.search('api.?key',k,re.I) for _,k in downstream(graph,nid)):
                tid=nid+':value'
                if tid not in {x['id'] for x in texts}:texts.append({'id':tid,'key':'value','node':n.get('title')or n['type'],'role':graph.text_role(nid,'value')})
    # Proven cleanup text supplied to segmentation, not the creative encoder.
    if idx==92 and '22:value' not in {t['id'] for t in texts}:
        texts.insert(0,{'id':'22:value','key':'value','node':'清理区域','role':'prompt'})
    for t in texts:
        nid,key=t['id'].rsplit(':',1)
        if t['role']=='negative':t['label']='不希望出现的内容';t['help']=''
        else:
            t['label']=TEXTS.get(idx,{}).get(t['id'], '扩写指令' if t['key']in ['system_prompt','role'] else '用户描述' if w['category']=='提示词辅助' else '生成视频描述' if w['category']in ['视频编辑与人物替换','视频修复与扩展'] else '图像修改描述' if w['category']=='图像编辑' else '创作描述')
            t['help']='结果需复制到生成描述' if idx==0 and nid=='577' else ''
    if idx==0:texts.sort(key=lambda t:t['id']!='581:value')
    if idx==79:texts.sort(key=lambda t:t['id']!='19:prompt')
    if idx==34:
        order=['1479:text','1488:text','1520:text','1518:text','1514:prompt','1525:prompt']
        texts.sort(key=lambda t:order.index(t['id']) if t['id']in order else 99)
    # Flux comparison graphs save distinct results. Name each editable input by
    # the output branch it really reaches instead of showing duplicate prompts.
    if idx==11:
        for t in texts:
            if t['id']=='158:value':t['label']='两模型共用描述'
            if t['id']=='145:prompt':t['label']='Qwen 分支 · 不希望出现的内容'
    if idx in (17,18):
        single={'109:text','107:text','108:text'}
        for t in texts:
            t['label']=('单图结果 · ' if t['id'] in single else '双图结果 · ')+('不希望出现的内容' if t['role']=='negative' else '创作描述')
        order=(['109:text','121:text'] if idx==17 else ['107:text','127:text','108:text','128:text'])
        texts.sort(key=lambda t:order.index(t['id']) if t['id'] in order else 99)
    # Same-stage seed fan-out: a single user value records every concrete member.
    if idx==103:
        # Node IDs are not execution order: node 3 generates the initial segment.
        controls.sort(key=lambda c: {'3:seed':0,'79:seed':1,'85:seed':2}.get(c['id'],3))
    groups=defaultdict(list)
    for c in controls:
        c['help']=HELP.get(c['kind'],'')
        if c['key']=='frame_load_cap':c['help']=''
        if c['label']=='动作片段起始帧':c['help']='0 从首帧开始'
        if c['label']=='单段生成帧数':c['help']='需符合模型帧数规则'
        if c['label']=='动作参考强度':c['help']='越大，动作跟随越强'
        if c['label']=='输出分辨率（百万像素）':c['help']=''
        if c['label']=='输出大小（百万像素）':c['help']='越大，图片尺寸越大'
        if c['label']=='本地素材目录':c['help']='填写运行端的目录'
        if c['label']=='文件匹配规则':c['help']='如 *.mp4'
        if c['kind']=='mask':
            entries=[]
            n=graph.nodes[c['nodeId']]
            for src,_,slot in graph.ins[c['nodeId']]:
                key=n.get('inputs',[])[slot]['name']
                if re.fullmatch('value\\d+',key):
                    v=int(key[5:]);typ=graph.nodes[src]['type']
                    label='描述自动分割' if 'SegmentAnything'in typ else '手动画笔掩膜' if 'PreviewBridge'in typ else '检测模型掩膜'
                    entries.append({'value':v,'label':label})
            c['options']=entries
        if c['type']=='number' and c['kind']not in ['seed','color','camera','outpaint']:
            c['min']=0;c['step']=1 if isinstance(c['value'],int) else 'any'
            if c['kind']=='restoration':c.update(min=0,max=1,step=0.01)
            if c['kind']in ['resolution','count','upscale']:c['min']=0.01 if isinstance(c['value'],float) else 1
        if c['kind']!='seed':continue
        typ=graph.nodes[c['nodeId']]['type']
        prompt=bool(re.search('LLM|Vision|Multimodal|TextGenerate',typ,re.I)) or any(re.search('LLM|Vision|Multimodal',graph.nodes[t]['type'],re.I) for t,k in graph.targets(c['nodeId'],c['key']) if t in graph.nodes)
        role='prompt' if prompt else 'media'
        group=c['id'] if (w['category']=='数字人与对口型' or w['category']=='提示词辅助') else role
        groups[group].append(c)
    merged=[];seen=set();media_index=0;prompt_index=0
    for c in controls:
        if c['kind']!='seed':merged.append(c);continue
        key=next(k for k,items in groups.items() if c in items)
        if key in seen:continue
        seen.add(key);items=groups[key]
        c['members']=[{'id':s['id'],'nodeId':s['nodeId'],'key':s['key'],'targets':s['targets']} for s in items]
        prompt=bool(re.search('LLM|Vision|Multimodal|TextGenerate',graph.nodes[c['nodeId']]['type'],re.I))
        if prompt:
            prompt_index+=1;c['label']='提示词种子'
            if w['category']=='提示词辅助':c['label']=('图片分支' if idx==34 and c['nodeId']=='1525' else '文字分支' if idx==34 and c['nodeId']=='1514' else f'提示词分支 {prompt_index}')+' · 提示词种子'
            c['help']=''
        else:
            media_index+=1;c['label']='素材抽取种子' if w['category']=='素材格式工具' else '图像生成种子' if w['output']=='image' else '视频生成种子'
            if w['category']=='数字人与对口型':c['label']=('首段生成种子' if media_index==1 else f'续段 {media_index-1} · 视频种子') if len(groups)>1 else '视频生成种子'
            c['help']=''

        merged.append(c)
    controls=merged
    if idx in (11,17,18):
        for c in controls:
            if c['kind']=='seed':c['help']='两条结果共用，便于对比'
    if idx==15:
        for c in controls:
            if c['id']=='144:strength':c.update(min=0,max=10,step=0.01)
    # Connected forms expose only values that the selected output graph consumes.
    def ui_control(identifier,key,label,value,kind,typ,targets,**extra):
        return {'id':identifier,'key':key,'label':label,'value':value,'type':typ,
                'kind':kind,'targets':targets,'help':'',**extra}
    size_options=['1024x1024','1152x896','896x1152','1344x768','768x1344','1024x1536']
    if idx in (9,10):
        for c in controls:
            if c['key']=='resolution':
                c['options']=[{'value':str(o['value'] if isinstance(o,dict) else o),
                               'label':str(o['value'] if isinstance(o,dict) else o).replace('x','×')}
                              for o in c['options']]
            elif c['key']=='output_pixels':
                c.update(label='输出总像素',help='',
                         options=[{'value':n,'label':f'{n} 千像素'} for n in (1024,1536,2048)])
    if idx==19:
        controls=[c for c in controls if c['kind']=='seed']
        controls.insert(0,ui_control('site:size','size','画面尺寸','1024x1024','ratio','text',
            [{'node':'86','input':'value'},{'node':'87','input':'value'}],
            options=size_options,customRange={'min':512,'max':4096,'step':32}))
    if idx in (21,85,107):
        if idx==21:
            controls=[c for c in controls if c['kind']=='seed']
            controls.insert(0,ui_control('site:size','size','画面尺寸','1024x1024','ratio','text',
                [{'node':'19','input':'value'},{'node':'20','input':'value'}],options=size_options,customRange={'min':512,'max':2048,'step':8}))
        elif idx==85:
            controls=[c for c in controls if c['kind']=='seed']
            controls.insert(0,ui_control('65:size','size','画面尺寸','896x1088','ratio','text',
                [{'node':'65','input':'width_override'},{'node':'65','input':'height_override'}],
                options=['896x1088','1024x1024','1152x896','896x1152','768x1344','1344x768'],customRange={'min':512,'max':2048,'step':8}))
        else:
            controls=[c for c in controls if c['kind']=='seed' or c['id']=='80:resolution']
            controls.insert(0,ui_control('58:size','size','基础画面尺寸','1024x1536','ratio','text',
                [{'node':'58','input':'width'},{'node':'58','input':'height'}],options=size_options,customRange={'min':512,'max':2048,'step':32}))
            enhancement=next((c for c in controls if c['id']=='80:resolution'),None)
            if enhancement is None:
                enhancement=ui_control('80:resolution','output_size','增强输出分辨率',1536,'resolution','number',
                    [{'node':'80','input':'resolution'}])
                controls.insert(1,enhancement)
            enhancement.update(key='output_size',label='增强输出分辨率',help='增强后图片的短边像素',
                options=[{'value':n,'label':f'{n} px'} for n in (1024,1536,2048)])
            for c in controls:
                if c['kind']=='seed':
                    members=c.get('members') or [{'id':c['id'],'nodeId':c.get('nodeId','3'),'key':'seed','targets':c['targets']}]
                    if not any(m['id']=='80:seed' for m in members):members.append({'id':'80:seed','nodeId':'80','key':'seed','targets':[{'node':'80','input':'seed'}]})
                    c['members']=members;c['help']='同时控制生成与增强'
    if idx==78:controls=[c for c in controls if c['kind']=='seed']
    if idx==12:
        texts=[{'id':nid+':text','label':label,'node':'CLIPTextEncode','key':'text','role':'prompt','help':'',**({'value':default} if default else {})}
               for nid,label,default in [('19','模型 1 · Anything-to-Real',None),('171','模型 2 · Turn2Real','reskin this into a real photo'),('180','模型 3 · anime2real-semi','转为写实摄影')]]
    if idx==108:
        for c in controls:
            if c['id']=='60:sampling_mode.seed':c['key']='prompt_seed'
        controls.extend([
            ui_control('67:value','lora_enabled','LoRA 加速',False,'toggle','checkbox',
                [{'node':'66','input':'switch'},{'node':'70','input':'switch'}],help='启用写实 LoRA 分支'),
            ui_control('68:value','prompt_optimize','提示词优化',True,'toggle','checkbox',
                [{'node':'65','input':'switch'}],help='先扩写描述再生成'),
            ui_control('59:strength_model','model_strength','模型强度',0.8,'strength','number',
                [{'node':'59','input':'strength_model'}],help='仅开启 LoRA 时生效',min=0,max=2,step=0.05)])
        for c in controls:
            if c['id']=='49:megapixels':c.update(label='百万像素',options=[{'value':v,'label':f'{v:g} MP'} for v in (0.5,1,1.5,2,4)])
        controls.sort(key=lambda c:c['kind']=='seed')
    if idx in (109,128):
        controls=[
            ui_control('44:resolution','resolution','画面尺寸','768x1344','ratio','text',
                [{'node':'44','input':'resolution'}],options=['1024x1024','1152x896','896x1152','1216x832','832x1216','1344x768','768x1344','1536x640','640x1536']),
            ui_control('site:branch','branch','写实身材 LoRA','standard','choice','text',
                [{'node':'42','input':'model'},{'node':'58','input':'model'}],
                options=[{'value':'standard','label':'关闭 · 基础模型'},{'value':'lora','label':'开启 · 写实 LoRA'}],help='启用写实 LoRA 分支'),
            ui_control('site:upscale','upscale','二次放大',1.5,'upscale','number',
                [{'node':'47','input':'scale_by'},{'node':'52','input':'scale_by'}],
                options=[{'value':1,'label':'1 倍'},{'value':1.5,'label':'1.5 倍'}]),
            ui_control('57:seed','seed','图像生成种子',752166193025910,'seed','number',
                [{'node':str(n),'input':'seed'} for n in (57,48,51)],min=0,max=9007199254740991,step=1,
                members=[{'id':'57:seed','nodeId':'57','key':'seed','targets':[{'node':str(n),'input':'seed'} for n in (57,48,51)]}])]
    # Seconds are a UI conversion only when the graph proves a fixed read FPS.
    # The snapshot still writes the original frame-count input, never a fake port.
    if w['category']=='视频修复与扩展':
        for c in controls:
            if c['key']!='frame_load_cap' and not(idx==5 and c['id']=='378:value'):continue
            b=widget_bindings(graph.nodes[c['nodeId']]);fps=b.get('force_rate',(0,None))[0]
            if idx==5:fps=widget_bindings(graph.nodes['374'])['value'][0]
            elif not graph.editable(c['nodeId'],'force_rate'):
                sources=[s for s,_,slot in graph.ins[c['nodeId']] if graph.nodes[c['nodeId']]['inputs'][slot]['name']=='force_rate']
                fps=widget_bindings(graph.nodes[sources[0]]).get('value',(0,None))[0] if len(sources)==1 and graph.nodes[sources[0]]['type']in ['INTConstant','PrimitiveInt','PrimitiveFloat'] else 0
            if not fps or not isinstance(fps,(int,float)):continue
            native=c['id'];c.update(id=native+':seconds',key='seconds',value=c['value']/fps,kind='duration',
                label='处理时长（秒，0 为全部）',step='any',min=0,
                derived={'operation':'frames','targetId':native,'fps':fps})
    if idx==98:
        c=next(c for c in controls if c['id']=='15:duration_seconds')
        start=widget_bindings(graph.nodes['15'])['offset_seconds'][0]
        c.update(id='15:audio_end_seconds',key='audio_end_seconds',kind='segment',label='音频片段终点（秒）',
            value=start+c['value'],derived={'operation':'audio-end','startId':'15:offset_seconds','targetId':'15:duration_seconds'})
    controls=reviewed_derived_unit_bounds(w,controls,graph=graph,source_hash=source_hash)
    if idx==101:
        for c in controls:
            if c['id']=='365:value':c['label']='两路音频终点（分:秒）'
    if idx==93 and graph.nodes.get('76',{}).get('type')=='DeepTranslatorTextNode':
        controls=description_language_control(controls)
    if (idx==122 and graph.nodes.get('34',{}).get('type')=='ImpactInt' and
            graph.nodes.get('10',{}).get('type')=='SeedVR2VideoUpscaler' and
            graph.targets('34','value')==[('10','resolution')]):
        controls=seedvr2_short_edge_control(controls)
    if idx==135:
        for c in controls:
            if c['key']=='start_index':c['label']='跳过开头图片数'
        if graph.nodes.get('12',{}).get('type')=='LoadImageListFromDir //Inspire':
            controls=directory_image_order_control(controls)
    if idx==136:
        # LoadVideoBatchFrame.INPUT_TYPES in the node's upstream implementation
        # defines these exact three mode values. Keep their raw values in the
        # snapshot while presenting a readable choice instead of free text.
        mode=next((c for c in controls if c['id']=='61:mode'),None)
        if mode and graph.nodes['61']['type']=='LoadVideoBatchFrame' and mode['value']=='single_video':
            mode.update(label='视频选择方式',
                        options=[{'value':'single_video','label':'指定索引'},
                                 {'value':'incremental_video','label':'顺序索引'},
                                 {'value':'random','label':'随机视频'}],
                        help='随机模式使用种子选择视频')
    # Site request keys are a stable API contract. Comfy node widget names are
    # implementation details and can differ (noise_seed / widget_0).
    if idx in (9,10,19,21,110):
        for c in controls:
            if c['kind']=='seed' and c['key'] in ('noise_seed','widget_0'):
                c['key']='seed'
    custom_ranges={
        1:{'megapixels':(0.1,16,0.1)},2:{'megapixels':(0.1,16,0.1)},
        3:{'megapixels':(0.1,16,0.1)},84:{'megapixels':(0.1,16,0.1)},
        9:{'output_pixels':(512,4096,32)},10:{'output_pixels':(512,4096,32)},
        13:{'output_long_side':(256,4096,1)},19:{'size':(512,4096,32)},
        21:{'size':(512,2048,8)},82:{'output_long_side':(256,4096,32)},
        85:{'size':(512,2048,8)},107:{'size':(512,2048,32),'output_size':(512,2048,32)},
        108:{'megapixels':(0.1,16,0.1)},110:{'size':(512,2048,8)},
        130:{'size':(512,2048,8)},
    }
    for c in controls:
        if c['key'] in custom_ranges.get(idx,{}):
            minimum,maximum,step=custom_ranges[idx][c['key']]
            c['customRange']={'min':minimum,'max':maximum,'step':step}
        if c['kind']=='ratio' and c['key'] in ('resolution','size'):
            c['label']='画面尺寸'
        if c['key']=='megapixels':
            c['label']='百万像素'
            if c.get('customRange'):
                c['options']=[{'value':v,'label':f'{v:g} MP'} for v in (0.5,1,1.5,2,4)]
    controls.sort(key=lambda c:0 if c['label']=='本地素材目录' else 1 if c['label']=='文件匹配规则' else 2)
    if w['category']=='数字人与对口型':
        for m in media:
            if m['kind']=='audio':m['label']='驱动音频'+(' '+m['label'].split()[-1] if m['label'].split()[-1].isdigit() else '')
            if m['kind']=='image' and '人脸'not in m['label']:m['label']='人物参考图'
            if idx==102 and m['kind']=='video':m['label']='驱动视频（含音频）'
    focused=w['category']in ['视频修复与扩展','数字人与对口型','提示词辅助','素材格式工具']
    branches=[]
    if w['category']=='提示词辅助':
        nodes=[p['id']for p in apis] or [c['nodeId']for c in controls if c['kind']=='seed']
        for nid in nodes:
            matches=lambda src:src==nid or any(t==nid for t,_ in downstream(graph,src))
            branch_media=[m for m in media if matches(m['id'])]
            label='图片反推' if branch_media else '文字扩写'
            branches.append({'id':nid,'label':label})
            for t in texts:
                if matches(t['id'].rsplit(':',1)[0]):t['branchId']=nid;t['label']=re.sub(r'^(文字|图片)分支 · ','',t['label'])
            for m in branch_media:m['branchId']=nid
            for c in controls:
                if matches(c['nodeId']):c['branchId']=nid;c['label']=label+' · 提示词种子' if c['kind']=='seed' else c['label']
            for p in apis:
                if p['id']==nid:p['branchId']=nid;p['label']=label+' API'
        branches.sort(key=lambda b: b['label']!='文字扩写')
    if focused:
        for c in controls:
            if c['kind']=='seed':c['uiGroup']='seed'+(':'+c['branchId'] if c.get('branchId') else '')
            elif w['category']=='素材格式工具':
                c['uiGroup']='location' if c['label']in ['本地素材目录','文件匹配规则'] else 'playback' if c['kind']=='playback' else 'read'
            else:c['uiGroup']='output' if c['kind']in ['resolution','upscale','motion'] else 'clip'
    if w['category']=='素材格式工具':media=[]
    if w['category']=='视频编辑与人物替换':
        for m in media:
            if m['kind']=='image' and m['label']=='首帧':m['label']='角色参考图' if re.search('人物|角色|换人',w['name']) else '修改参考图'
    annotation=None
    if w['category']in ['图像编辑','图像增强与整理'] and any(m['kind']=='image' for m in media):
        has_mask=any(any(oslot<len(graph.nodes[n].get('outputs',[])) and graph.nodes[n]['outputs'][oslot].get('type')=='MASK' and dst in graph.reachable for dst,_,oslot in graph.out[n]) for n in [m['id']for m in media])
        manual_bridge=any(n.get('type')=='PreviewBridge' and nid in graph.reachable and n.get('mode',0)not in [2,4] for nid,n in graph.nodes.items())
        annotation={'mode':'mask' if has_mask else 'visual','help':'涂抹区域用于生成掩膜' if has_mask else '掩膜需手动载入清理分支' if manual_bridge else '仅作视觉参考，不限制编辑区域'}
    if idx==13:
        for m in media:
            if m['kind']=='image':m['label']='待扩展原图'
        for t in texts:
            if t['role']=='prompt':t['label']='扩展画面描述'
        for c in controls:
            if c['kind']=='outpaint':c.update(min=0,max=16384,step=8)
            if c['id']=='124:strength':c.update(min=0,max=10,step=0.1)
            if c['id']=='131:scale_to_length':c.update(options=[1024,1324,1536],value=1324,help='独立控制最终导出尺寸')
        annotation=None
    if idx==14:
        for c in controls:
            if c['key']=='zoom':c.update(label='镜头拉近',help='0 远景，10 特写')
    if idx==134:
        for m in media:
            if m['id']=='11':m['label']='待调色原图'
            if m['id']=='12':m['label']='色彩参考图'
        for c in controls:
            if c['id']=='10:strength':c.update(min=0,max=10,step=0.1)
        annotation=None
    if idx==16:
        for m in media:
            if m['id']=='36':m['label']='待编辑原图'
            if m['id']=='25':m['label']='修改参考图'
        media.sort(key=lambda m:m['id']!='36')
        annotation={'mode':'mask','optional':True,'slots':['36'],'help':'可选；涂抹区域作为修改位置参考'}
    if idx in (15,86,131):
        annotation={**annotation,'editor':'reference-region','required':True}
        if idx in (86,131):annotation['help']='选中区域用于局部重绘，未选区域保留原图。'
    if idx==133:
        annotation=None
        for m in media:
            if m['kind']=='image':m['label']='原图'
    if idx==124:
        media=label_first_last_frames(graph,media)
    if idx==24:
        media=label_animate_reference_slots(graph,media)
    if idx==92:
        # PreviewBridge's browser paint/upload path is not wired into this website.
        annotation=None
        for c in controls:
            if c['id']=='47:index':
                for option in c.get('options',[]):
                    if isinstance(option,dict) and option.get('value')==1:option.update(disabled=True,reason='网站尚不支持手工掩膜桥接，请使用自动分割。')
    if idx==11:
        dimensions=['1024x1024','1152x896','896x1152','1216x832','832x1216','1344x768','768x1344','1536x640','640x1536']
        controls=[dict(id='162:resolution',key='resolution',label='画面尺寸',node='CM_SDXLResolution',nodeId='162',value='1344x768',type='text',kind='ratio',options=[{'value':v,'label':v.replace('x','×')} for v in dimensions],targets=[{'node':'162','input':'resolution'}],help='')]+[c for c in controls if c['kind']=='seed']
    if idx in (17,18):
        for m in media:
            if m['id']=='76':m['label']='待编辑原图'
            if m['id']=='81':m['label']='补充参考图'
        media.sort(key=lambda m:m['id']!='76')
        shared=[]
        for role,label in [('prompt','图像修改描述'),('negative','不希望出现的内容')]:
            fields=[t for t in texts if t['role']==role]
            if fields:
                shared.append({**fields[0],'label':label,'help':'','targets':[{'node':t['id'].split(':')[0],'input':'text'} for t in fields]})
        texts=shared
    notes=[]
    if not any(c['kind']=='resolution' for c in controls) and w['category']in ['图像编辑','文字生视频','参考图生视频']:
        notes.append('原图未提供可独立编辑的输出尺寸；不能把预处理尺寸当成输出分辨率。')
    if not any(c['kind']=='duration' for c in controls) and w['category']=='视频修复与扩展':notes.append('此图保持输入帧数，长度随原片段；未发现可直接绑定的生成秒数。')
    if w['category']=='参考图生视频':
        # Only expose optional slots whose exact model ports are present. A model
        # cap does not imply that other graphs can be wired in the same fashion.
        for nid,n in graph.nodes.items():
            if n['type']!='MiniMaxH3ReferenceToVideo' or nid not in graph.reachable:continue
            ports=[i for i in n.get('inputs',[]) if re.fullmatch(r'ref_images\.ref_image_\d+',i['name'])]
            for port in ports:
                ordinal=int(port['name'].rsplit('_',1)[1]);linked=port.get('link')
                src=next((s for s,_,slot in graph.ins[nid] if n['inputs'][slot]['name']==port['name']),None)
                if src and any(m['id']==src for m in media):continue
                slot=next((m for m in w['media'] if m['id']==src and m['kind']=='image'),None)
                # No enabled, unrelated loader is repurposed.
                if slot and graph.nodes[src].get('mode',0)==2:
                    media.append({**slot,'label':f'可选参考图 {ordinal+1}','optional':True,'activateOnUpload':True,'target':{'node':nid,'input':port['name']}})
                elif linked is None or src and graph.nodes.get(src,{}).get('mode',0) in [2,4]:
                    media.append({'id':f'{nid}:ref_image_{ordinal}','kind':'image','label':f'可选参考图 {ordinal+1}','optional':True,'sourceNodeId':src,'target':{'node':nid,'input':port['name']}})
            notes.append(f'此图有 {len(ports)} 个模型参考图端口；按实际端口提供可选入口，不设置额外的网页总数上限。')
    if idx==30:
        controls,texts=dance_ratio_protocol_form(controls,texts,graph=graph)
    controls=add_review70_controls(w,graph,controls)
    apis=add_review70_api_profiles(w,graph,apis)
    apis=reviewed_default_api_models(w,apis,source_hash=source_hash,graph=graph)
    controls,texts,media=apply_review70_labels(w,controls,texts,media)
    media=reviewed_media_roles(w,media,source_hash=source_hash)
    controls=reviewed_h3_duration_guidance(w,graph,controls,source_hash=source_hash)
    from portrait_size_contract import reviewed_portrait_size_controls
    controls=reviewed_portrait_size_controls(w,controls,graph=graph,source_hash=source_hash)
    from camera72_contract import reviewed_camera72_controls
    controls=reviewed_camera72_controls(w,controls,graph=graph,source_hash=source_hash)
    from review74_parameter_contracts import reviewed_independent_seeds,reviewed_batch_count,reviewed_color_supplement,reviewed_camera14_size,reviewed_final_enhancement_size,reviewed_refinement_reference,reviewed_inactive_middle_position,reviewed_multiview_output_size
    controls=reviewed_independent_seeds(w,controls,graph=graph,source_hash=source_hash)
    controls=reviewed_batch_count(w,controls,source_hash=source_hash)
    controls=reviewed_camera14_size(w,controls,graph=graph,source_hash=source_hash)
    controls=reviewed_final_enhancement_size(w,controls,graph=graph,source_hash=source_hash)
    controls=reviewed_refinement_reference(w,controls,graph=graph,source_hash=source_hash)
    controls=reviewed_inactive_middle_position(w,controls,graph=graph,source_hash=source_hash)
    controls=reviewed_multiview_output_size(w,controls,graph=graph,source_hash=source_hash)
    from review75_generation_sizes import reviewed_generation_sizes
    controls=reviewed_generation_sizes(w,controls,graph=graph,source_hash=source_hash)
    texts=reviewed_color_supplement(w,texts,graph=graph,source_hash=source_hash)
    from reviewed_stage_seeds import reviewed_stage_seeds
    controls=reviewed_stage_seeds(w,controls,graph=graph,source_hash=source_hash)
    from reviewed_native_seed_limits import reviewed_native_seed_limits
    controls=reviewed_native_seed_limits(w,controls,graph=graph,source_hash=source_hash)
    for text in texts:
        nid,key=text['id'].rsplit(':',1)
        if preserves_system_instruction(graph,nid,key):text['preserveWhenEmpty']=True
        text.update(reviewed_text_purpose(graph,nid,key))
    return controls,texts,media,{'apiProfiles':apis,'annotation':annotation,'notes':notes,'presentation':{'kind':w['category'] if focused else 'generic','branches':branches},
       'referencePolicy':{'mode':'graph-ports','imageSlots':sum(m['kind']=='image' for m in media),'help':'按该工作流有效输入端口接收素材；额外上限须由真实模型协议确认。'},
       'auditMethod':'active-output-path + concrete-input-binding','execution':'demo'}
