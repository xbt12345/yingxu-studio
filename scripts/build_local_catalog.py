"""Build a public, sanitized UI catalog from local ComfyUI graphs. Never export prompts, credentials or paths."""
from pathlib import Path
import json, hashlib, re, collections
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'private/research/card-20260923'
TAX=json.loads((ROOT/'design-workflow-v1/taxonomy.json').read_text('utf8'))
NAMES=json.loads((CACHE/'files.json').read_text('utf8'))
LABELS={'width':'宽度 px','height':'高度 px','megapixels':'像素预算 MP','aspect_ratio':'画面比例','steps':'采样步数','cfg':'提示词引导 CFG','denoise':'重绘幅度','seed':'随机种子','noise_seed':'噪声种子','batch_size':'批次数量','length':'帧数','num_frames':'帧数','frames_number':'帧数','duration':'时长 秒','fps':'帧率','frame_rate':'输出帧率','force_rate':'重采样帧率','frame_load_cap':'最多加载帧数','skip_first_frames':'跳过前 N 帧','select_every_nth':'每 N 帧取一帧','scale_by':'放大倍率','scale_to_length':'目标长边 px','ref_image_size':'参考图处理尺寸','ref_max_size':'参考图上限 px','ref_image_size_mode':'参考图尺寸方式','ref_image_size_value':'参考图尺寸','ref_image_size_megapixels':'参考像素预算','ref_size':'参考尺寸','strength':'强度','strength_model':'模型作用强度','strength_clip':'文本编码强度','shift':'采样偏移','shift_video':'视频采样偏移','shift_audio':'音频采样偏移','temperature':'文本温度','max_tokens':'最大文本长度','crf':'视频 CRF','loop_count':'循环次数','pingpong':'往返播放','trim_to_audio':'按音频裁切','sampler_name':'采样器','scheduler':'调度器','format':'输出格式','method':'缩放算法','fit':'适配方式','crop':'裁切方式','multiple':'尺寸对齐倍数','resolution':'处理分辨率','max_resolution':'最大分辨率','tile_size':'分块大小','overlap':'重叠区域','temporal_overlap':'时间重叠','context_length':'上下文帧数','context_overlap':'上下文重叠','start_percent':'起始比例','end_percent':'结束比例','start_index':'起始序号','batch_index':'批次序号','start_at_step':'起始采样步','end_at_step':'结束采样步','add_noise':'添加噪声','boolean':'开关','value':'数值','Number':'数值','match_image_size':'匹配图像尺寸'}
LABELS.update({'start_time':'音频起点','end_time':'音频终点','top_p':'文本 Top P','top_k':'文本 Top K','min_p':'文本 Min P','repetition_penalty':'重复惩罚','rescale_factor':'缩放倍率','guide_size':'引导尺寸','max_size':'尺寸上限','feather':'羽化像素','noise_aug_strength':'噪声增强'})
SAFE_STR={'start_time','end_time','aspect_ratio','ref_image_size','ref_size','sampler_name','scheduler','format','method','fit','crop'}
def nodes(g,prefix=''):
 for n in g.get('nodes',[]):yield prefix,n
 for i,sub in enumerate(g.get('definitions',{}).get('subgraphs',[])):yield from nodes(sub,prefix+f'sub{i}/')
def fingerprint(g):
 # Only exact semantic equality is deduplicated, not just the same model or filename.
 def clean(v):
  if isinstance(v,list):return [clean(x) for x in v]
  if not isinstance(v,dict):return v
  return {k:clean(x) for k,x in v.items() if k not in {'pos','size','color','bgcolor','flags','extra','groups','revision','last_node_id','last_link_id','bounding','state'}}
 return hashlib.sha256(json.dumps(clean({'nodes':g.get('nodes'), 'links':g.get('links'), 'definitions':g.get('definitions')}),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def classify(name):
 rules=[('数字人|s2v|infinite','数字人与对口型'),('首尾帧','首尾帧生视频'),('跳舞|舞蹈|姿势迁移|wananimate|wan_animate','动作迁移与舞蹈'),('视频.*(放大|修复|增强)|flash|seedvr','视频修复与扩展'),('视频.*(编辑|替换|换脸|换装)|bernini','视频编辑与人物替换'),('文生视频','文字生视频'),('minimax|h3|i2v','参考图生视频'),('提示词|反推','提示词辅助'),('写真|套图|多角度','参考图与套图'),('放大|去背景|调色','图像增强与整理'),('编辑|重绘|换衣','图像编辑')]
 for pattern,cat in rules:
  if re.search(pattern,name,re.I):return cat
 return '文字生图'
def extract(g,cat):
 fields=[];media=[];seen=set();allnodes=list(nodes(g));subnames={sub['id']:sub.get('name','子图') for sub in g.get('definitions',{}).get('subgraphs',[])}
 for prefix,n in allnodes:
  typ=n.get('type','');nodeid=prefix+str(n.get('id'));title=n.get('title') or subnames.get(typ) or typ
  if re.search('Note|Label|Preview',typ,re.I):continue
  kind='video' if re.search('LoadVideo|VideoLoader',typ,re.I) else 'audio' if re.search('LoadAudio|AudioLoader',typ,re.I) else 'image' if re.search('LoadImage|ImageLoader|LoadImages',typ,re.I) else None
  if kind:
   role=('动作来源' if cat=='动作迁移与舞蹈' and kind=='video' else '驱动音频' if kind=='audio' else '原视频' if kind=='video' else '参考图片')
   if cat=='首尾帧生视频' and kind=='image':role='首帧' if not any(x['kind']=='image' for x in media) else '尾帧 / 参考图'
   if cat=='图像编辑' and kind=='image':role='原图' if not media else '修改参考图'
   if re.search('mask',typ,re.I):role='区域遮罩'
   media.append({'id':nodeid,'kind':kind,'label':role,'node':title})
  named=n.get('widgets_values_named') or (n.get('widgets_values') if isinstance(n.get('widgets_values'),dict) else {})
  if not named and isinstance(n.get('widgets_values'),list):
   values=n['widgets_values']
   schemas={
    'KSampler':['seed','control_after_generate','steps','cfg','sampler_name','scheduler','denoise'],
    'KSamplerAdvanced':['add_noise','noise_seed','control_after_generate','steps','cfg','sampler_name','scheduler','start_at_step','end_at_step','return_with_leftover_noise'],
    'EmptySD3LatentImage':['width','height','batch_size'], 'EmptyLatentImage':['width','height','batch_size'],
    'LatentUpscaleBy':['method','scale_by'],'ModelSamplingSD3':['shift'],'ModelSamplingAuraFlow':['shift'],
    'LoraLoader':['lora_name','strength_model','strength_clip'],'LoraLoaderModelOnly':['lora_name','strength_model'],
    'AudioCrop':['start_time','end_time'],'PrimitiveInt':['value'],'PrimitiveFloat':['value'],'ImpactInt':['value'],
    'ImageResizeKJv2':['width','height','method','fit','background','crop','multiple','device'],
    'CR Upscale Image':['model','mode','rescale_factor','resolution','method','supersample','multiple']}
   if typ in schemas:named=dict(zip(schemas[typ],values))
   else:
    # Preserve unnamed numeric widgets explicitly as raw positions, never guess labels.
    for pos,val in enumerate(values):
     if isinstance(val,(int,float,bool)):
      key='widget_'+str(pos);LABELS[key]='节点参数 '+str(pos+1);named[key]=val
  # For API graphs, inputs are named directly.
  if 'class_type' in n:named=n.get('inputs',{})
  for key,val in named.items():
   if key not in LABELS:
    if isinstance(val,(int,float,bool)) and not re.search('token|key|secret|password',key,re.I):LABELS[key]=key
    else:continue
   if isinstance(val,str) and (key not in SAFE_STR or len(val)>90 or any(x in val for x in ['http',':\\','sk-'])):continue
   if not isinstance(val,(str,int,float,bool)) or val is None:continue
   ident=nodeid+':'+key
   if ident in seen:continue
   seen.add(ident)
   inputs=n.get('inputs',[]);input_info=next((x for x in inputs if isinstance(x,dict) and x.get('name')==key),{}) if isinstance(inputs,list) else {}
   fields.append({'id':ident,'key':key,'label':title if key in ('value','boolean','Number') else LABELS[key],'node':title,'nodeId':nodeid,'value':val,'type':'checkbox' if isinstance(val,bool) else 'number' if isinstance(val,(int,float)) else 'text','linked':input_info.get('link') is not None,'inactive':n.get('mode',0) in [2,4]})
 return fields,media

def main():
 candidates=[];missing=[]
 for i,name in enumerate(NAMES):
  cat=next((t['id'] for t in TAX if i in t['indices']),classify(name))
  candidates.append((CACHE/f'graph-{i:03}.json',name,cat,'card-'+str(i)))
 for folder in [ROOT/'private/research',Path.home()/'Downloads',Path.home()/'Documents/ChatGPT/工作流',Path.home()/'Documents/ChatGPT/视频编辑提示词']:
  for p in sorted(folder.glob('*.json')):candidates.append((p,p.name,classify(p.name),'local-'+hashlib.sha256(p.name.encode()).hexdigest()[:10]))
 unique={};records=[];audit=[]
 for p,name,cat,ident in candidates:
  try:g=json.loads(p.read_text('utf-8-sig'))
  except (ValueError,OSError):continue
  if not isinstance(g,dict):missing.append({'name':name,'category':cat,'reason':'本地文件为空，无法解析节点'});continue
  if not g.get('nodes'):
   if g and all(isinstance(v,dict) and 'class_type' in v for v in g.values()):g={'nodes':[dict(id=k,type=v['class_type'],**v) for k,v in g.items()],'links':[]}
   else:continue
  if ident.startswith('local-'):
   types=' '.join(str(n.get('type',n.get('class_type',''))) for _,n in nodes(g))
   if re.search('MiniMaxH3|Hunyuan|LTXV',types,re.I):
    cat='视频编辑与人物替换' if re.search('替换|编辑|换脸|换装',name) else '首尾帧生视频' if '首尾帧' in name else '参考图生视频'
   elif re.search('Bernini',types,re.I):cat='视频编辑与人物替换'
  fp=fingerprint(g)
  if fp in unique:
   unique[fp]['aliases'].append(name);audit.append({'source':str(p),'duplicateOf':unique[fp]['id']});continue
  fields,media=extract(g,cat)
  texts=[]
  for prefix,node in nodes(g):
   typ=node.get('type','')
   if re.search('Note|Label|ShowText',typ,re.I):continue
   named=node.get('widgets_values_named') or (node.get('inputs',{}) if 'class_type' in node else {})
   if not isinstance(named,dict):named={}
   if not named and typ=='CLIPTextEncode':named={'text':''}
   for key in ['prompt','text','negative_prompt','system_prompt']:
    if key in named and isinstance(named[key],str):
     texts.append({'id':prefix+str(node['id'])+':'+key,'label':('反向提示词' if 'negative' in key or re.search('负|反向|negative',node.get('title',''),re.I) else '系统指令' if key=='system_prompt' else '节点描述'),'node':node.get('title') or typ,'key':key})

  rec={'id':'local-'+ident,'name':Path(name).stem,'category':cat,'aliases':[name],'fields':fields,'media':media,'texts':texts,'nodeCount':len(list(nodes(g))),'inputNote':'没有发现文件加载节点；使用文字或由上游节点提供素材。' if not media else '','output':'text' if cat=='提示词辅助' else 'video' if any(x in cat for x in ['视频','舞蹈','数字人']) else 'image','catalogOnly':True,'cover':{'文字生图':'portal-ocean.png','图像编辑':'dunes.jpg','参考图与套图':'award-poster.jpg','视频编辑与人物替换':'award-poster.jpg'}.get(cat,'coast.jpg'),'desc':next((t['flow'] for t in TAX if t['id']==cat),'素材 → 结果'),'mode':'multi'}
  unique[fp]=rec;records.append(rec);audit.append({'source':str(p),'id':rec['id'],'sha256':fp,'fields':len(fields)})
 data={'workflows':records,'categories':[t['id'] for t in TAX],'missing':missing,'sourceCount':sum(len(r['aliases']) for r in records),'duplicateCount':sum(len(r['aliases'])-1 for r in records)}
 (ROOT/'public/local-catalog.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),'utf8')
 (ROOT/'verification/catalog-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),'utf8')
 print(json.dumps({'unique':len(records),'sources':data['sourceCount'],'duplicates':data['duplicateCount'],'missing':missing,'fields':sum(len(r['fields']) for r in records),'categories':dict(collections.Counter(r['category'] for r in records))},ensure_ascii=False))
if __name__=='__main__':main()
