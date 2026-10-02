"""User controls derived from each graph's concrete bindings, not category templates."""
import re
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit

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


def refresh_curated_controls(workflow, reviewed, derived):
    """Carry source-checked control corrections into an unchanged curated form."""
    idx=int(workflow['id'].split('-')[-1]) if workflow['id'].startswith('local-card-') else -1
    current=reviewed['controls']
    fresh={field['key']:field for field in derived['controls']}
    if idx==19:
        current=[fresh['size']]+[field for field in current if field['kind']=='seed']
    for field in current:
        key=field['key']
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
    reviewed['controls']=current
    return reviewed


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


def safe_endpoint(value):
    try:
        u=urlsplit(str(value));return urlunsplit((u.scheme,u.hostname+((':'+str(u.port)) if u.port else '') if u.hostname else '',u.path,'','')) if u.scheme in ['http','https'] else ''
    except ValueError:return ''


def customize(w,graph,controls,texts,media):
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
            if c['kind']=='restoration':c.update(min=0,max=1,step=0.05)
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
    if idx==101:
        for c in controls:
            if c['id']=='365:value':c['label']='两路音频终点（分:秒）'
    if idx==135:
        for c in controls:
            if c['key']=='start_index':c['label']='跳过开头图片数'
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
    return controls,texts,media,{'apiProfiles':apis,'annotation':annotation,'notes':notes,'presentation':{'kind':w['category'] if focused else 'generic','branches':branches},
       'referencePolicy':{'mode':'graph-ports','imageSlots':sum(m['kind']=='image' for m in media),'help':'按该工作流有效输入端口接收素材；额外上限须由真实模型协议确认。'},
       'auditMethod':'active-output-path + concrete-input-binding','execution':'demo'}
