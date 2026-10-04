"""Audit every real workflow input without exporting prompts, media names or secrets.

The interface builder intentionally uses a conservative allowlist. This audit
starts from *all* active scalar widgets so omissions outside that allowlist are
visible, while keeping internal defaults separate from useful creation inputs.
It does not enqueue a workflow or infer ranges from sample widget values.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from build_workflow_interfaces import Graph, semantic, widget_bindings
from workflow_customization import INTERNAL, REVIEW70_INPUTS, REVIEW70_LINKED_INPUTS, downstream

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(r"api.?key|access.?token|authorization|password|secret|credential", re.I)
DISPLAY = re.compile(r"Note|Show|Preview|Markdown|Display|Label", re.I)
SAMPLING = re.compile(r"^(steps|cfg|guidance|sampler_name|scheduler|shift(?:_.*)?|tau|sigma(?:_.*)?|noise_aug_strength|start_at_step|end_at_step|add_noise|return_with_leftover_noise)$", re.I)
PROCESS = re.compile(r"^(batch_size|batch_count|tile(?:_.*)?|overlap(?:_.*)?|cache(?:_.*)?|chunk(?:_.*)?|device|dtype|precision|attention(?:_.*)?|offload(?:_.*)?|verbose|debug|multiple|resolution_steps|resample|interpolation|bit_depth|codec|crf|pix_fmt|quality|save_metadata|filename_prefix|output_path|output_dir|pingpong|loop_count|format|select_every_nth|force_rate|custom_width|custom_height|ref_image_size|reference_image_size|conditioning_.*|fast_mode|int8_.*|morton|use_tma|noise_seed_behavior|control_after_generate)$", re.I)
MODEL = re.compile(r"(?:model|checkpoint|ckpt|lora|vae|clip|unet|gguf|quantization|strength_model|strength_clip)", re.I)
INTERNAL_NODE = re.compile(r"^(SetNode|GetNode|Anything Everywhere.*|Reroute|MathExpression.*|ComfyMathExpression|Evaluate Integers|easy compare|easy mathInt|easy mathFloat|.*ContextWindows.*|.*ContextOptions|SolAttnPatch|.*Sampler.*|.*Scheduler.*|.*Sigma.*|.*Attention.*|.*ModelPatch.*|.*Lora.*|.*LoRA.*|.*VAE.*|.*Decode.*|.*Encode.*)$", re.I)
INTERNAL_KEY = re.compile(r"^(Constant|expression|python_expression|comparison|fixed|USE_LAST_SEED|🎲.*|save_output|trim_to_audio|color_space|format\..*|proportional_width|proportional_height|fit|method|round_to_multiple|scale_to_side|background_color|upscale_method|divisible_by|keep_proportion|pad_color|crop_position|print_to_console|video_transport|thinking_mode|thinking|match_image_size|spacing_width|spacing_color|direction|return_list|inputcount|delimiter|separator|output_type|low_mem_load|force_offload|load_device|use_disk_cache|normalize|normalization|cache_threshold|ref_max_size|video_frames|detect|label|load_always|sort_method|.*_tile_size|.*_tile_overlap)$", re.I)
# Nodes whose remaining widgets describe backend processing. Existing reviewed
# bindings win before this list; it must not manufacture a universal user slider.
PROCESSING_NODES = {
    'CFGNorm','ModelSamplingAuraFlow','WanVideoBlockSwap','LTXVPreprocess',
    'DrawViTPose','PoseAndFaceDetection','BlockifyMask','DrawMaskOnImage',
    'ImpactCompare','ImpactConditionalBranch','CM_IntBinaryOperation','SimpleMath+',
    'LayerUtility: PurgeVRAM V2','ImageConcatMulti',
}
MEDIA = re.compile(r"^(image|video|audio|image_path|video_path|audio_path|upload)$", re.I)
TEXT = re.compile(r"^(prompt|text|positive|negative|positive_prompt|negative_prompt|system_prompt|role)$", re.I)
USER_KEYS = {
    "seed", "noise_seed", "random_seed", "aspect_ratio", "megapixels", "duration",
    "duration_seconds", "seconds", "horizontal_angle", "vertical_angle", "zoom",
    "azimuth", "elevation", "distance", "left", "right", "top", "bottom",
    "brightness", "contrast", "saturation", "gamma", "pose_strength",
    "reference_image_strength", "reference_image_strength_1", "pose_strength_1",
    "offset_seconds", "start_time", "start_seconds", "end_time", "end_seconds",
    "frame_load_cap", "skip_first_frames", "video_frame_offset", "video_frame_offset_1",
    "length", "num_frames", "task_type", "scale_by", "scale", "max_count",
    "scale_to_length", "longest_side", "max_side_length", "long_side", "target_long_side",
    "directory", "path", "pattern", "frame", "image_load_cap",
}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def binding_sets(config):
    result = {}
    for family in ("controls", "texts", "media"):
        for field in config.get(family, []):
            bindings = set()
            identifier = field.get("id", "")
            if family != "media" and ":" in identifier:
                bindings.add(tuple(identifier.rsplit(":", 1)))
            if field.get("nodeId") and field.get("key"):
                bindings.add((str(field["nodeId"]), field["key"]))
            for target in field.get("targets", []):
                bindings.add((str(target["node"]), target["input"]))
            for member in field.get("members", []):
                if ":" in member.get("id", ""):
                    bindings.add(tuple(member["id"].rsplit(":", 1)))
                bindings.update((str(t["node"]), t["input"]) for t in member.get("targets", []))
            derived_id = field.get("derived", {}).get("targetId")
            if derived_id and ":" in derived_id:
                bindings.add(tuple(derived_id.rsplit(":", 1)))
            result[(family, identifier)] = bindings
    for profile in config.get("apiProfiles", []):
        for target in profile.get("bindings", {}).values():
            if target:
                result[("apiProfiles", profile["id"])] = result.get(("apiProfiles", profile["id"]), set()) | {(str(target["node"]), target["input"])}
    return result


def covered_by(node_id, key, targets, config, bindings):
    own = {(node_id, key)} | set(targets)
    hits = [{"family": family, "id": identifier}
            for (family, identifier), known in bindings.items() if own & known]
    if MEDIA.match(key):
        hits += [{"family": "media", "id": m["id"]} for m in config.get("media", [])
                 if node_id in {str(m["id"]), str(m.get("sourceNodeId", ""))}]
    return hits


def classify(workflow, graph, node_id, key, targets, value, hits):
    typ = graph.nodes[node_id]["type"]
    effective = {key} | {name for _, name in targets}
    if hits:
        return "visible", "existing-schema-binding"
    if any(SECRET.search(name) for name in effective) or any(SECRET.search(k) for _, k in downstream(graph, node_id)):
        return "hidden-credential", "private-runtime-credential"
    index = int(workflow["id"].rsplit("-", 1)[-1]) if workflow["id"].startswith("local-card-") else -1
    if node_id in INTERNAL.get(index, set()):
        return "hidden-internal", "reviewed-internal-instruction"
    if DISPLAY.search(typ):
        return "hidden-internal", "display-or-preview-only"
    if typ in PROCESSING_NODES:
        return 'hidden-internal','reviewed-processing-node-default-preserved'
    if typ=='QwenMultiangleCameraNode' and key in ('default_prompts','camera_view'):
        return 'hidden-internal','camera-widget-preview-or-instruction-state'
    if typ=='PointsEditor' and key in ('points_store','neg_coordinates','bbox_store','bboxes','bbox_format'):
        return 'hidden-internal','coordinate-state-owned-by-subject-point-picker'
    if typ=='VHS_LoadVideo' and key=='choose video to upload':
        return 'hidden-internal','comfy-browser-upload-widget-not-api-input'
    if typ in ('CreateVideo','VHS_VideoCombine') and key in ('fps','frame_rate') and workflow['category']!='素材格式工具':
        return 'hidden-internal','generation-frame-rate-contract-preserved'
    if key.startswith('sampling_mode.') and key!='sampling_mode.seed':
        return 'hidden-internal','language-model-generation-default'
    if (workflow['id'],node_id,key) in {
        ('local-card-22','58','positive_prompt'),('local-card-23','549','positive_prompt'),
        ('local-card-30','95','positive_prompt')}:
        return 'hidden-internal','reviewed-fixed-motion-or-quality-instruction'
    if any(nid == node_id and name == key for nid, name, *_ in REVIEW70_INPUTS.get(index, [])+REVIEW70_LINKED_INPUTS.get(index, [])):
        return "missing-reviewed-kind", "individual-creation-input-review"
    if effective & USER_KEYS:
        # Frame count and width can be processing inputs. Do not assert every
        # matching name should be displayed; first use proved builder semantics.
        probe = {"nodeId": node_id, "key": key, "value": value}
        kind, _ = semantic(graph, probe, workflow)
        if kind:
            return "missing-reviewed-kind", kind
        return "needs-review", "creation-or-processing-input-needs-context"
    if any(TEXT.match(name) for name in effective):
        if key in ("system_prompt", "role") and workflow["category"] != "提示词辅助":
            return "hidden-internal", "model-system-instruction"
        return "needs-review", "active-description-not-covered"
    if MEDIA.match(key):
        return "needs-review", "active-media-source-not-covered"
    if typ == 'LoadVideo' and key == 'file' and any(str(m['id'])==node_id for m in workflow.get('media', [])):
        return "hidden-internal", "media-source-owned-by-upload-control"
    if SAMPLING.match(key):
        return "hidden-internal", "sampling-default-preserved"
    if MODEL.search(key) or re.search(r"Loader|ModelPatch|Attention|Sigma|Scheduler", typ):
        return "hidden-internal", "model-or-processing-default-preserved"
    if PROCESS.match(key):
        return "hidden-internal", "processing-or-export-default-preserved"
    if INTERNAL_NODE.match(typ) or INTERNAL_KEY.match(key):
        return "hidden-internal", "graph-routing-or-processing-default-preserved"
    if key in ("temperature", "top_p", "max_tokens", "frequency_penalty", "presence_penalty"):
        return "hidden-internal", "language-model-generation-default"
    return "needs-review", "unclassified-active-widget-no-inferred-control"


def source_fields(workflow, graph):
    fields = {}
    def names_with_preview_tail(node):
        names=[inp['widget']['name'] for inp in node.get('inputs',[]) if inp.get('widget')]
        values=node.get('widgets_values',[])
        if node.get('type')=='QwenMultiangleCameraNode' and len(values)==len(names)+1 and values[-1]=='':
            return {name:(values[index],index) for index,name in enumerate(names)}
        return {}
    for item in workflow.get("fields", []):
        node_id, key = str(item["nodeId"]), item["key"]
        if key.startswith("widget_"):
            index = int(key.split("_")[1])
            actual = next((name for name, (_, position) in (widget_bindings(graph.nodes.get(node_id, {})) or names_with_preview_tail(graph.nodes.get(node_id,{}))).items()
                           if position == index), None)
            if not actual and names_with_preview_tail(graph.nodes.get(node_id,{})):continue
            key = actual or key
        fields[(node_id, key)] = item.get("value")
    for node_id, node in graph.nodes.items():
        for key, (value, _) in (widget_bindings(node) or names_with_preview_tail(node)).items():
            if isinstance(value, (int, float, str, bool)):
                fields[(node_id, key)] = value
    return fields


def input_metadata(graph, node_id, key, object_info):
    node=graph.nodes.get(node_id,{})
    definitions=object_info.get(node.get('type'),{}).get('input',{})
    spec=definitions.get('required',{}).get(key) or definitions.get('optional',{}).get(key)
    if not spec and '.' in key:
        parent,child=key.split('.',1)
        outer=definitions.get('required',{}).get(parent) or definitions.get('optional',{}).get(parent)
        selected=widget_bindings(node).get(parent,(None,None))[0]
        if isinstance(outer,list) and len(outer)>1 and isinstance(outer[1],dict):
            for option in outer[1].get('options',[]):
                if isinstance(option,dict) and option.get('key')==selected:
                    nested=option.get('inputs',{})
                    spec=nested.get('required',{}).get(child) or nested.get('optional',{}).get(child)
    if not isinstance(spec,list) or not spec:return None
    attrs=spec[1] if len(spec)>1 and isinstance(spec[1],dict) else {}
    result={'nodeType':node.get('type'),'inputType':spec[0] if isinstance(spec[0],str) else 'COMBO'}
    for attr in ('min','max','step'):
        if attr in attrs:result[attr]=attrs[attr]
    options=spec[0] if isinstance(spec[0],list) else attrs.get('options')
    if isinstance(options,list):
        # Loader options are an inventory of the owner's uploaded files / model
        # resources, not portable creative enums. Never copy that inventory.
        if MEDIA.match(key) or MODEL.search(key) and len(options)>50 or len(options)>100:
            result['choiceCount']=len(options)
        else:result['options']=options
    return result


def execution_view(config, spec):
    if not spec or spec.get('validation')=='blocked':return config
    out=dict(config)
    for family in ('controls','texts','media','apiProfiles'):
        # Keep UI labels / groups while using the concrete supported identity.
        ids={item['id'] for item in spec.get(family,[])}
        out[family]=[item for item in config.get(family,[]) if item['id'] in ids]
    return out


def audit(workflow, raw, config, source, object_info, compiled_dir, spec):
    graph = Graph(raw)
    bindings = binding_sets(config)
    executable={}
    if spec and spec.get('validation')!='blocked' and spec.get('template'):
        for candidate in (ROOT/'private/card-compiled'/spec['template'],ROOT/'workflows/api'/spec['template']):
            if candidate.exists():
                executable=load_json(candidate)
                break
    inputs, skipped = [], Counter()
    original_fields=source_fields(workflow,graph)
    for (node_id, key), value in original_fields.items():
        if node_id not in graph.nodes:
            skipped["source-node-missing"] += 1
            continue
        if not graph.editable(node_id, key):
            skipped["linked-inactive-or-outside-output"] += 1
            continue
        targets = graph.targets(node_id, key)
        hits = covered_by(node_id, key, targets, config, bindings)
        status, reason = classify(workflow, graph, node_id, key, targets, value, hits)
        if executable and status not in ('visible','hidden-credential'):
            if node_id not in executable and not any(nid in executable for nid,_ in targets):
                status,reason='hidden-pruned','source-node-outside-compiled-active-output-path'
            elif node_id in executable and key not in executable[node_id].get('inputs',{}) and not any(name in executable.get(nid,{}).get('inputs',{}) for nid,name in targets):
                status,reason='hidden-internal','source-ui-widget-not-executable-api-input'
        if status=='visible' and spec and spec.get('validation')!='blocked':
            supported={(family,item['id']) for family in ('controls','texts','media','apiProfiles') for item in spec.get(family,[])}
            if not any((item['family'],item['id']) in supported for item in hits):
                status,reason='hidden-pruned','outside-compiled-active-output-path'
        inputs.append({"id": node_id + ":" + key, "nodeType": graph.nodes[node_id]["type"],
                       "key": key, "status": status, "reason": reason,
                       "targets": [{"node": node, "input": name} for node, name in targets],
                       "sourceConstraints":input_metadata(graph,node_id,key,object_info),"coveredBy": hits})
    schema_issues = []
    verified_constraints=[]
    compiled_path=compiled_dir/(workflow['id']+'.api.json')
    compiled=load_json(compiled_path) if compiled_path.exists() else {}
    for family in ("controls", "texts"):
        for field in config.get(family, []):
            identifier = field["id"]
            if ":" in identifier and not identifier.startswith("site:"):
                # Derived seconds retain the original source identity. Some
                # reviewed fields target flattened nested API node IDs instead.
                source_id=field.get('derived',{}).get('targetId') or identifier
                nid, key = source_id.rsplit(":", 1)
                if field.get('nodeId') and field.get('nodeId') in graph.nodes:
                    nid=field['nodeId']
                if nid not in graph.nodes:
                    if nid not in compiled:
                        schema_issues.append({"id": identifier, "issue": "source-and-compiled-node-missing"})
                elif nid not in graph.reachable or graph.nodes[nid].get("mode", 0) in (2, 4):
                    schema_issues.append({"id": identifier, "issue": "inactive-or-outside-output"})
            if any(SECRET.search(t.get("input", "")) for t in field.get("targets", [])):
                schema_issues.append({"id": identifier, "issue": "credential-in-creative-field"})
            if family=='controls' and (any(n+':'+k==identifier for n,k,*_ in REVIEW70_INPUTS.get(int(workflow['id'].rsplit('-',1)[-1]) if workflow['id'].startswith('local-card-') else -1, [])) or workflow['id']=='local-card-75' and field.get('kind')=='camera'):
                nid,key=identifier.rsplit(':',1)
                metadata=input_metadata(graph,nid,key,object_info)
                findings=[]
                if metadata:
                    for attr in ('min','max','step'):
                        if attr in metadata and field.get(attr)!=metadata[attr]:findings.append('constraint-'+attr+'-mismatch')
                    if metadata.get('options'):
                        actual=[item.get('value') if isinstance(item,dict) else item for item in field.get('options',[])]
                        if actual!=metadata['options']:findings.append('enum-mismatch')
                    source_value=original_fields.get((nid,key))
                    if source_value!=field.get('value'):findings.append('source-default-mismatch')
                else:findings.append('object-info-metadata-missing')
                verified_constraints.append({'id':identifier,'sourceConstraints':metadata,'issues':findings})
                schema_issues.extend({'id':identifier,'issue':issue} for issue in findings)
            if family=='controls' and field.get('constraintSources'):
                nid,key=identifier.rsplit(':',1);findings=[]
                constraints=[{'node':t['node'],'input':t['input'],'definition':input_metadata(graph,t['node'],t['input'],object_info)} for t in field['constraintSources']]
                if any(not t['definition'] for t in constraints):findings.append('linked-consumer-metadata-missing')
                if field.get('value')!=original_fields.get((nid,key)):findings.append('source-default-mismatch')
                formula=field.get('frameFormula')
                if formula:
                    actual=widget_bindings(graph.nodes.get(formula['node'],{}))
                    expression=actual.get('python_expression',actual.get('expression',actual.get('value',(None,None))))[0]
                    try:
                        same_expression=ast.dump(ast.parse(str(expression),mode='eval'))==ast.dump(ast.parse(formula['expression'],mode='eval'))
                    except SyntaxError:same_expression=False
                    if not same_expression:findings.append('frame-expression-mismatch')
                    fps_source=formula.get('fpsSource')
                    if fps_source and 'fps' in formula:
                        src_node,src_key=fps_source.rsplit(':',1)
                        if widget_bindings(graph.nodes[src_node]).get(src_key,(None,None))[0]!=formula['fps']:findings.append('fixed-fps-mismatch')
                else:
                    for attr,fn in [('min',max),('max',min),('step',max)]:
                        values=[t['definition'][attr] for t in constraints if t['definition'] and attr in t['definition']]
                        expected=fn(values) if values else 1 if attr=='step' else None
                        if expected is not None and field.get(attr)!=expected:findings.append('consumer-'+attr+'-mismatch')
                verified_constraints.append({'id':identifier,'linkedConsumerConstraints':constraints,'frameFormula':formula,'issues':findings})
                schema_issues.extend({'id':identifier,'issue':issue} for issue in findings)
    return {"id": workflow["id"], "name": workflow["name"], "category": workflow["category"],
            "source": str(source), "sourceHash": hashlib.sha256(Path(source).read_bytes()).hexdigest(),
            "sourceHashMatchesSchema": hashlib.sha256(Path(source).read_bytes()).hexdigest() == config.get("sourceHash"),
            "output": workflow.get("output"), "reachableNodes": len(graph.reachable),
            "execution": spec.get('validation') if spec else "legacy-compiled" if compiled else "catalog-only",
            "executionVisible":{key:len(execution_view(config,spec).get(key,[])) for key in ('controls','texts','media','apiProfiles')},
            "executionExcluded":spec.get('excluded',[]) if spec else [],
            "executionBlockingReason":spec.get('blocking_reason','') if spec else '',
            "visible": {k: len(config.get(k, [])) for k in ("controls", "texts", "media", "apiProfiles")},
            "dispositions": dict(Counter(item["status"] for item in inputs)),
            "skipped": dict(skipped), "inputs": inputs, "schemaIssues": schema_issues,
            "newCreationConstraints":verified_constraints,
            "defaultAdjustments":[{"id":field["id"],"sourceDefault":field["sourceDefault"],"value":field.get("value"),
                                   "adjustment":field["defaultAdjustment"]}
                                  for field in config.get("controls",[]) if field.get("defaultAdjustment")],
            "missingReviewedKinds": [item for item in inputs if item["status"] == "missing-reviewed-kind"],
            "reviewCandidates": [item for item in inputs if item["status"] == "needs-review"]}


def short_fields(config):
    counts=Counter(item.get('label','描述') for item in config.get('texts',[]))
    result=[name+(f' ×{n}' if n>1 else '') for name,n in counts.items()]
    controls=config.get('controls',[])
    camera=[item for item in controls if item['kind']=='camera']
    if camera:
        nodes={item.get('nodeId') for item in camera}
        result.append(f'{len(nodes)} 组机位（方位 / 俯仰 / 拉近）')
    result.extend(item['label'] for item in controls if item['kind'] not in ('camera','seed'))
    seeds=[item for item in controls if item['kind']=='seed']
    if seeds:result.append('随机 / 固定种子'+(f' ×{len(seeds)}' if len(seeds)>1 else ''))
    return '；'.join(result) or '素材处理，无独立创作参数'


def semantic_disposition(typ,key,instances):
    """Record a human-reviewed role; this never changes public input visibility."""
    if re.fullmatch(r'[a-f\d-]{36}',typ) or key.startswith('widget_'):
        return 'version-or-wrapper','旧前端的子图/位置widget；真实输出尺寸、种子、描述等通过具体节点独立核对，不把包装器重复作为新参数。'
    if typ=='SDXLEmptyLatentSizePicker+' and key=='resolution':
        return 'covered-by-explicit-size','基础画面尺寸已绑定该节点width_override/height_override，旧分辨率预设不重复开放。'
    if typ=='MultimodalChat':
        return 'version-or-wrapper','卡8旧MultimodalChat已按官方同名接口迁移VisionChat；上下文/采样/工具JSON/释放模型均为推理预置，不是用户文本内容。'
    if typ=='ImagePadKJ':
        return 'image-processing-preset','四边扩展像素已开放；额外内边距、填色与填充模式维持该视频扩展图的原预置。'
    if typ=='LayerUtility: LaMa':
        return 'mask-or-detection-preset','清理区域与描述已开放；剩余蒙版反转、膨胀和羽化属于清理算法的边缘预置。'
    if typ in ('CFGOverride','LatentUpscaleBy'):
        return 'model-conditioning-preset','采样指导的阶段区间或高清二阶段潜空间倍率；基础画面与主描述已可修改，不重复当作最终导出分辨率。'
    if typ in ('TTP_Image_Assy','ColorMatch','easy imagePixelPerfect'):
        return 'image-processing-preset','分块拼回留白、多线程或检测预处理的缩放方式；原图/蒙版/实际输出尺寸与调色强度通过既有入口修改。'
    if SECRET.search(key) or key in ('auth_data','proxies','ollama_url','url'):
        return 'runtime-configuration','服务认证、代理、本机模型地址或权重来源属于运行端配置，不能成为普通创作参数。'
    if typ.startswith('Comfly'):
        if key in ('background','output_format','output_compression'):
            return 'optional-export-choice','透明背景/导出格式/压缩可作为后续导出能力；不缺少素材、描述、数量、尺寸和质量入口，当前保留原导出预置。'
        return 'provider-operation','轮询、重试、错误处理、固定服务模式及协议预置；固定模式/单一清晰度不重复开放成可变功能。'
    if typ=='BerniniStudio':
        return 'task-or-runtime-preset','编辑任务已开放；提示词增强依赖运行端模型，默认负面词、参考图发送格式和Ollama配置保留原节点策略。'
    if typ in ('PrimitiveStringMultiline','StringConcatenate','JoinStringMulti','ttN concat','Text Concatenate','CR Text Replace','StringReplace','JsonExtractString','SomethingToString','easy promptList','RH_LLMAPI_NODE'):
        return 'fixed-instruction-or-format','用户的主描述/主体描述独立开放；剩余为系统扩写、质量前缀、JSON提取/替换/拼接、空补充入口或固定视角提示，不把格式规则当用户描述。'
    if typ in ('TextGenerate','TextSplitByDelimiter'):
        return 'prompt-processing','文本模型采样、模板、分段提取与固定结果数量；用户的要求在上游文本入口修改。'
    if typ in ('PrimitiveInt','PrimitiveFloat','PrimitiveBoolean','ImpactInt','INTConstant','Float','Int','easy int','easy float','easy boolean','PrimitiveNode'):
        return 'routing-or-algorithm-scalar','逐条对照接收端后保留的加速开关、比较阈值、FPS、CFG、步数和内部批处理常量；有用户含义的尺寸/时长/数量/起点已另行补回。'
    if re.search(r'Resize|Scale|Resolution|EmptyImage|Image Blank|ImageComposite|PadForOutpaint|CropByMask|ImageUpscale|ImageRemoveAlpha|ColorPicker',typ):
        return 'image-processing-preset','用户画面尺寸/比例、实际输出长边和扩展四边已独立核对；剩余是参考图预处理、模型对齐、缩放插值、固定填色/裁剪锚点或拼贴位置。'
    if re.search(r'ImageFromBatch|GetImageRange|RepeatImageBatch|SplitImages|Pick From Batch|LatentCut|LatentConcat',typ):
        return 'internal-frame-routing','用户片段起点/读取时长/生成长度在素材加载或真实长度源修改；剩余是首帧提取、引导帧、续段拼接及内部批次窗口。'
    if re.search(r'LayerMask|GrowMask|InpaintModel|Canny|Preprocessor|RenderNLF|SDPose|SAM3_|SeCVideo|SCAIL2ColoredMask',typ):
        return 'mask-or-detection-preset','实际主体点选/对象编号/跟踪描述已单独开放；剩余检测阈值、人体部位预置、蒙版羽化、描边、排序、跟踪缓存和渲染方式保留。'
    if typ.startswith('MiniMax') or typ.startswith('Spectrum'):
        return 'h3-model-preset','用户视频描述、素材、时长、输出画面与面部修复幅度已独立开放；剩余为双阶段采样/音轨条件、裁脸跟踪、潜空间放大和贴回算法的固定计划。'
    if re.search(r'Wan|LTX|MultiTalk|Wav2Vec|RIFE|NLF|FlashVSR|SeedVR|Controlnet|DifferentialDiffusion|FluxKontext|QwenEdit',typ):
        return 'model-conditioning-preset','模型条件、引导帧、插帧倍率/匹配帧率、显存与噪声策略；不把内部缩放/采样/引导强度伪装成统一创作强度。'
    if typ.startswith('DeepTranslator'):
        return 'translation-preset','该编辑图的提示词翻译语言/服务固定，用户在主描述中修改内容；翻译认证不导出。'
    if typ.startswith('AudioCrop'):
        return 'audio-processing','音频素材与起止区间已开放；增益、重采样与声道转换保持原音频处理策略。'
    if re.search(r'Grid Panel|ImageReel|QwenMultiangleCameraNode',typ):
        return 'presentation-state','模型对比拼图文字/边框/列数与摄影机预览状态；真正机位数值已开放，不作为新的生成参数。'
    if typ in ('CustomCombo','ComfySwitchNode','easy anythingIndexSwitch'):
        return 'routing-preset','模型/采样策略或内部掩膜分支开关，保持该命名工具的原执行策略。'
    if typ=='DownloadAndLoadNLFModel':
        return 'runtime-configuration','姿态模型权重地址、预热与加载由运行端负责，不属于视频内容选择。'
    return 'unconfirmed-node-behavior','尚未归入明确用户语义；保留实际字段与来源，需核实该节点实现而非猜测功能。'


def write_semantic_review(path,rows,schemas):
    groups={}
    for row in rows:
        if not row['id'].startswith('local-card-') or row['execution']=='blocked':continue
        for field in row['reviewCandidates']:
            key=(field['nodeType'],field['key'])
            groups.setdefault(key,[]).append({'workflow':row['id'],'id':field['id'],'targets':field['targets'],'sourceConstraints':field['sourceConstraints']})
    pairs=[]
    for (typ,key),instances in sorted(groups.items()):
        category,reason=semantic_disposition(typ,key,instances)
        pairs.append({'nodeType':typ,'key':key,'disposition':category,'reason':reason,'instances':instances})
    counts=Counter(p['disposition'] for p in pairs)
    added=[]
    for idx,fields in REVIEW70_LINKED_INPUTS.items():
        cfg=schemas['local-card-'+str(idx)]
        for nid,key,*_ in fields:
            field=next((c for c in cfg['controls'] if c['id']==nid+':'+key),None)
            if field:added.append({'workflow':'local-card-'+str(idx),'id':field['id'],'label':field['label'],'constraints':{k:field[k] for k in ('min','max','step') if k in field},'constraintSources':field['constraintSources'],'frameFormula':field.get('frameFormula')})
    result={'scope':'用户指定卡的可编译工作流；逐个源图与实际输出路径核对，不代表GPU实测',
            'summary':{'workflows':sum(row['id'].startswith('local-card-') and row['execution']!='blocked' for row in rows),
                       'candidateInstances':sum(len(p['instances']) for p in pairs),'uniquePairs':len(pairs),'dispositions':dict(counts),
                       'unconfirmedPairs':sum(p['disposition']=='unconfirmed-node-behavior' for p in pairs)},
            'newKeyInputs':added,'pairs':pairs}
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result['summary']


def write_card_document(path, card_dir, catalog, schemas, rows,registry):
    files=load_json(card_dir/'files.json')
    aliases={alias:workflow for workflow in catalog for alias in workflow.get('aliases',[])}
    row_by_id={row['id']:row for row in rows}
    notes={
        7:'小脸 / 大脸分别控制；处理秒数写回原帧数，音轨设置保留原值。',
        8:'按官方兼容关系迁移旧多模态Chat/Loader到VisionChat/Qwen38VLLoader；用户要求和系统扩写指令保留，GPU真实运行仍待验收。',
        22:'主体描述用于跟踪；动作/参考对象与参考图保留对象分别选择，空编号表示全部检测对象；两个排序契约未证明等价，不合并。24FPS，秒数按a*b+1，跳帧独立。',
        23:'主体描述用于跟踪，空编号表示全部检测对象；具体编号以检测结果为准，未虚构对象预览。24FPS，秒数按a*b+1，跳帧独立。',
        24:'处理秒数按固定16FPS的a*b+1写回；跳帧与生成种子独立，姿态/面部强度分别控制。',
        25:'处理秒数按固定16FPS的a*b+1写回；跳帧与生成种子独立，姿态/面部强度分别控制。',
        26:'处理秒数按固定16FPS的a*b+1写回；跳帧与生成种子独立，姿态/面部强度分别控制。',
        27:'处理秒数按固定16FPS的a*b+1写回；跳帧与生成种子独立，姿态/面部强度分别控制。',
        30:'原加载帧数上限常量实际进入FPS×秒数公式，界面明确秒；片段起点独立，FPS维持运行图预置。',
        31:'处理秒数按固定16FPS的a*b+1写回；跳帧与生成种子独立，面部动作参考单独控制。',
        36:'文生图 / 参考图编辑分别控制；第三方 API 计费，密钥在运行端配置。',
        37:'长视频固定 720P；标准视频支持 480P / 720P / 1080P，两个输出分支独立。',
        38:'文字 / 参考图两条分支固定原模式，避免无图切换图生图；第三方 API 计费。',
        39:'宽高16像素步进；生成帧数遵循1+4n。参考图与编辑任务独立，不猜视频秒数。',
        40:'参考视频读取秒数与生成帧数分别控制；读取按16FPS的a*b+1，生成帧数遵循1+4n。',
        43:'输出最长边直接写回实际resize源；秒数与跳帧独立，FPS/引导帧/模型策略保留。',
        46:'四边扩展是ImagePadKJ真实像素；填充方式/羽化维持原视频扩展策略，不添加假的扩展强度。',
        47:'输出最长边写回外部源常量，实际消费端为展开子图resize；秒数与跳帧独立。',
        48:'与43同族，输出最长边/秒数/跳帧分别控制，保留视频衣物/背景条件原预置。',
        49:'输出最长边/秒数/跳帧分别控制；下采样与衣物引导内部布局保留。',
        51:'主体选区必填：正点保留、负点排除；缺正点阻止提交；源长边1280 / 对齐32、固定24 FPS，按实际跳帧值预览首帧；旧点位不进入公开模板，真实运行仍需验收。',
        72:'第8机位原俯仰90°超出当前节点-30°至60°范围，采用节点有效默认0°并保留来源记录；旧草稿90°须主动修正。',
        75:'六个真实摄影机各开放方位 / 俯仰 / 拉近，尾部空预览串不当参数；拼图与模型设置保留。',
        85:'基础画面通过width_override/height_override控制；高清二阶段潜空间倍率保留，不把基础尺寸冒充最终导出尺寸。',
        89:'SDXL九档尺寸枚举与批次生成数量直接控制EmptyLatentImage；质量前缀与内部模型词保留。',
        116:'与27同族，处理秒数按固定16FPS的a*b+1写回；原跳帧、姿态/面部参考强度独立。',
        124:'源9是秒数，公式a*16+1且输出16FPS；当前NORMAL执行图未连入middle_image，中间帧位置不能据此承诺生效。',
        125:'宽高来自两个真实缩放节点；0保持比例，但宽高同时0应阻止提交；已有生成秒数与首尾帧独立。',
        126:'生成帧数同时控制视频latent与首尾帧编码；16FPS/插帧32FPS多输出不强行换成秒。',
        131:'放大倍率与细节重绘分别控制；采样器、分块、接缝默认值不进入表单。',
    }
    result=['# 算力卡工作流逐图参数审查','',
            '来源：2026-10-04 从用户指定算力卡读取的 137 个文件、真实节点定义 `object_info` 与网站 schema。137 个目录项中 136 个有图内容、1 个为空；3 个是重复图别名，复用 133 个工作流表单。', '',
            '判断原则：用户提供什么素材、希望什么结果、能有效改变什么，才成为工作区输入；采样、编码、模型加载、流程连线及未确认参数保留原值。既有组件承载全部新增字段，没有虚构统一强度或推测单位。', '',
            '本次复核 25 个源图标量 / 枚举候选，补回套图工作流六个摄影机的18项视角输入，并加入真实主体点选：面部修复、面部动作跟随、API 图像尺寸 / 数量 / 质量、视频比例 / 清晰度、输出规格、中间帧位置及放大 / 重绘。候选保留源图默认值，范围 / 枚举与节点定义逐项核对；旁路输入按实际执行图继续隐藏。主体点位由用户重新选定，不携带原素材的旧坐标。', '',
            '唯一默认值修正：`local-card-72` 的第8机位俯仰角原为90°，当前 `QwenMultiangleCameraNode` 只允许-30°至60°，因此采用节点自身默认0°。schema 用 `sourceDefault` / `defaultAdjustment` 保留原值和原因；原私有图不变，旧草稿中的90°仍需用户修正。', '',
            '全族复查另补21项关键时长 / 区间 / 数量 / 尺寸，补回4个LTX编辑变体输出长边、视频扩展四边、SDXL九档画面与3个真实对象索引。对象索引复用共享组件，空值代表全部；各节点索引独立，编号以检测结果为准。原始通用白名单之外的字段仍保留在私有审查清单，并按实际语义另列解释，未把计数清零当完整性证据。', '',
            '表中的“调整项”说明实际 schema 可见内容；仅代表来源与表单绑定审查。编译、加载模型、第三方 API 和真实生成验收是独立门槛，不能据此声称已逐图成功出图。', '',
            '| 卡目录项 / 网站 ID | 工作流 | 素材与可调项目 | 关键注意 |',
            '| --- | --- | --- | --- |']
    missing=[]
    seen=set()
    for index,name in enumerate(files):
        workflow=aliases.get(name)
        if not workflow:
            raw=load_json(card_dir/('graph-%03d.json'%index))
            if raw is None:
                result.append(f'| {index} / 未接入 | {Path(name).stem} | 卡端返回空内容 | 需要卡端补回原图；无法猜测参数或编译执行。 |')
                continue
            missing.append({'index':index,'name':name})
            result.append(f'| {index} / 待核对 | {Path(name).stem} | 未找到网站目录对应项 | 需要核对身份，不能标记完成。 |')
            continue
        spec=registry.get(workflow['id'])
        cfg=execution_view(schemas[workflow['id']],spec)
        media=' / '.join(item['label'] for item in cfg.get('media',[]))
        fields=short_fields(cfg)
        detail=(media+'；' if media else '')+fields
        identity=str(index)+' / '+workflow['id']
        if workflow['id'] in seen:
            note='同图别名，复用上述表单与输入绑定。'
        else:
            note=notes.get(index,'')
            if spec and spec.get('validation')=='blocked':
                note='暂不可生成：'+spec.get('blocking_reason','需要运行端修复')
            elif index==131 and spec and any(item['id']=='158:upscale_by' for item in spec.get('excluded',[])):
                note='当前输出旁路不执行 Ultimate 放大，倍率 / 重绘候选按执行图隐藏；不改变原分支。'
            if not note:
                if workflow['category']=='素材格式工具':note='目录是运行端路径；选本机文件夹不等于远程卡能访问。'
                elif any(c.get('derived') for c in cfg.get('controls',[])):note='界面单位转换沿用真实节点字段，不按未知 FPS 推算。'
                elif any(c['kind']=='camera' for c in cfg.get('controls',[])):note='机位与数值同步，独立节点独立保存。'
                elif cfg.get('apiProfiles'):note='API 需运行端可用且协议匹配；密钥不导出到公共仓库。'
                elif workflow.get('output')=='video':note='原片段 / 生成长度按节点单位；内部编码与采样原值保留。'
                elif len(cfg.get('texts',[]))>1:note='各实际文本分支保留，只有已有明确共用绑定才合并。'
                else:note='仅开放有效输出链输入；内部处理尺寸与输出尺寸区分。'
        seen.add(workflow['id'])
        safe=lambda text:str(text).replace('|',' / ').replace('\n',' ')
        result.append('| '+ ' | '.join(map(safe,[identity,workflow['name'],detail,note]))+' |')
    result.extend(['','完整字段与判断原因：`private/review70/parameter-audit.json`（不含提示词正文、文件名默认值或密钥）。',
                   '通用白名单外的有效 widget 已列入该审查文件；其中处理 / 路由默认值单列保留，未确认用途的字段不会自动进入表单。'])
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(result)+'\n',encoding='utf-8')
    return missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "public/local-catalog.json")
    parser.add_argument("--interfaces", type=Path, default=ROOT / "public/workflow-interfaces.json")
    parser.add_argument("--sources", type=Path, default=ROOT / "verification/catalog-audit.json")
    parser.add_argument("--card-dir", type=Path, default=ROOT / "private/research/card-20261004")
    parser.add_argument("--object-info", type=Path, default=ROOT / "private/research/card-20261004/object_info.json")
    parser.add_argument("--compiled-dir", type=Path, default=ROOT / "private/platform-compiled")
    parser.add_argument("--registry", type=Path, default=ROOT / "workflows/compiled-registry.json")
    parser.add_argument("--output", type=Path, default=ROOT / "private/review70/parameter-audit.json")
    parser.add_argument("--document", type=Path, default=ROOT / "docs/card-workflow-parameter-audit.md")
    parser.add_argument("--semantic-review",type=Path,default=ROOT/'private/review70/parameter-semantic-review.json')
    args = parser.parse_args()
    catalog = load_json(args.catalog)["workflows"]
    schemas = load_json(args.interfaces)["workflows"]
    sources = {item["id"]: item for item in load_json(args.sources) if "id" in item}
    object_info=load_json(args.object_info) if args.object_info.exists() else {}
    registry=load_json(args.registry).get('workflows',{}) if args.registry.exists() else {}
    rows = []
    for workflow in catalog:
        source = Path(sources[workflow["id"]]["source"])
        rows.append(audit(workflow, load_json(source), schemas[workflow["id"]], source, object_info, args.compiled_dir, registry.get(workflow['id'])))
    totals = Counter(status for row in rows for status in (item["status"] for item in row["inputs"]))
    summary = {"workflows": len(rows), "inputs": sum(len(row["inputs"]) for row in rows),
               "dispositions": dict(totals), "schemaIssues": sum(len(row["schemaIssues"]) for row in rows),
               "sourceHashDrift": [row["id"] for row in rows if not row["sourceHashMatchesSchema"]]}
    families=('controls','texts','media','apiProfiles')
    executable_card=[row for row in rows if row['id'].startswith('local-card-') and row['execution']!='blocked']
    summary.update(
        storedSchemaFields={family:sum(row['visible'][family] for row in rows) for family in families},
        effectiveSchemaFields={family:sum(row['executionVisible'][family] for row in rows) for family in families},
        cardExecutableWorkflows=len(executable_card),
        cardExecutableVisible={family:sum(row['executionVisible'][family] for row in executable_card) for family in families},
        blockedSchemaFields={row['id']:row['visible'] for row in rows if row['execution']=='blocked'},
        defaultAdjustmentCount=sum(len(row['defaultAdjustments']) for row in rows))
    if args.card_dir.exists():
        summary['cardDirectoryMissingSchemas']=write_card_document(args.document,args.card_dir,catalog,schemas,rows,registry)
    summary['semanticReview']=write_semantic_review(args.semantic_review,rows,schemas)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"scope": "active scalar source widgets; no generation or inferred ranges",
                                      "summary": summary, "workflows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if summary["schemaIssues"] or summary["sourceHashDrift"] or totals["missing-reviewed-kind"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
