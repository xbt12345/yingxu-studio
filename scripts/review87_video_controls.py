"""Review87: source-pinned WanAnimate/Bernini video controls.

Dimensions are real VHS loader widgets, followed by the owner's existing
LayerStyle scale and linked reference/conditioning sizes. A zero pair retains
the authored pipeline byte for byte. Explicit dimensions suppress only the
second longest-edge resize and retain model alignment. This module introduces
no execution nodes or GPU requests. Its loop metadata records native VHS output
ports; the platform subsequently generates once and repeats the complete saved
audio/video on the CPU through prepare_output_loops and FFmpeg stream-copy.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_HASHES = {
    "local-card-5": "4c37ca0b7de7de9754bb40eaa749f567df99a5a2eafada1f2a72971aea7e7c9f",
    "local-card-24": "a1e69dc545ea63073ca8705efb5824d3f3eb762b1fd338700e70ba51fc14b54a",
    "local-card-25": "12e1b1cad67733bcb99ffb9777b560216fa53633bbd5b238857f989af1449d7d",
    "local-card-26": "a2d8fa4a081f547c85c5590e49be9796b9316a767a90acdcb9d252c8c1157f31",
    "local-card-27": "ded45c025eeccf3c67b793e1ee73c859b29038b0fe3b8e8a838f65835ce0c449",
    "local-card-28": "c8b4de0c30b61edcd8b430ed44be76461e7d52cc2aadf332080b7df401aba53e",
    "local-card-40": "1ee0c5812e0cd846ba6460ae69411de2bae4797ee38e5be60017e8e34b7655e7",
    "local-card-41": "cbc23fea743b2442ce7785a8871395c1a42ff44f722210f1df4622aaf2dadcdf",
    "local-card-116": "c1f298110654069dd391f1ecd8422a952ca0b3deee229d234ca1ff3a53ab073d",
}


def _policy(loader, layer, long_id, model, reference, *, minimum=64,
            maximum=8096, original_multiple=16, default_long=1280,
            intermediates=(), model_class="WanVideoAnimateEmbeds"):
    return dict(loader=loader, layer=layer, longId=long_id,
                widthId=loader + ":custom_width", heightId=loader + ":custom_height",
                model=model, modelClass=model_class, reference=reference,
                intermediates=list(intermediates), modelMinimum=minimum,
                modelMaximum=maximum, originalMultiple=original_multiple,
                customMultiple=math.lcm(original_multiple, 16),
                sourceMultiple=8, defaultLong=default_long)


POLICIES = {
    "local-card-5": _policy("399", "415", "415:scale_to_length", "410", [],
                           minimum=16, maximum=8192, original_multiple=8,
                           default_long=1024, model_class="BerniniConditioning"),
    "local-card-24": _policy("3751", "3727", "3750:value", "3744", ["3697", "3689"]),
    "local-card-25": _policy("653", "626", "647:value", "641", ["596"]),
    "local-card-26": _policy("483", "456", "477:value", "471", ["426"], default_long=1024),
    "local-card-27": _policy("783", "756", "777:value", "771", ["726"], default_long=1024),
    "local-card-28": _policy("427", "440", "350:value", "286", ["390"],
                            minimum=16, maximum=8192, model_class="WanAnimateToVideo"),
    "local-card-40": _policy("27", "38", "37:value", "33", [],
                            minimum=16, maximum=8192, original_multiple=8,
                            default_long=1024, intermediates=[("17", "image", "27")],
                            model_class="BerniniStudio"),
    "local-card-41": _policy("425", "434", "434:scale_to_length", "387", [],
                            minimum=16, maximum=8192, original_multiple=32,
                            default_long=1024, intermediates=[("430", "image", "425")],
                            model_class="BerniniConditioning"),
    "local-card-116": _policy("783", "756", "777:value", "771", ["726"], default_long=1024),
}

WAN_FIELDS = {
    "local-card-24": dict(model="3744", pose="3744:widget_6", face="3744:face_strength", duration="3743:value",
                          seconds="3743", expression="3748", segment="3724:value", segmentation="3720", prompt="3724", label="定位视频中的人物", help="定位原视频人物"),
    "local-card-25": dict(model="641", pose="641:widget_6", face="641:face_strength", duration="654:value",
                          seconds="654", expression="645", segment="623:value", segmentation="619", prompt="623", label="定位视频中的人物", help="定位原视频人物"),
    "local-card-26": dict(model="471", pose="471:widget_6", face="471:face_strength", duration="484:value",
                          seconds="484", expression="475"),
    "local-card-27": dict(model="771", pose="771:widget_6", face="771:face_strength", duration="784:value",
                          seconds="784", expression="775", segment="753:value", segmentation="749", prompt="753", label="定位要修改的衣服", help="定位原视频衣物"),
    "local-card-116": dict(model="771", pose="771:pose_strength", face="771:face_strength", duration="784:value",
                           seconds="784", expression="775", segment="753:value", segmentation="749", prompt="753", label="定位要修改的衣服", help="定位原视频衣物"),
}

LOCATOR_TEXTS = {wid: fields for wid, fields in WAN_FIELDS.items() if fields.get("segment")}
LOCATOR_TEXTS["local-card-28"] = dict(segment="443:value", label="定位视频中的人物", help="定位原视频人物")


def _locator_text_presentation(spec, workflow_id=None):
    fields = LOCATOR_TEXTS.get(workflow_id or spec.get("id"))
    if fields:
        for text in spec.get("texts", []):
            if text.get("id") == fields["segment"]:
                text.update(label=fields["label"], help=fields["help"] + "；留空沿用", preserveWhenEmpty=True, sanitizeValue=True)
    return spec

OUTPUT_LOOP_POLICIES = {
    "local-card-5": dict(controlId="395:loop_count", node="395", format="video/h264-mp4",
                         audio=["399", 2], trimToAudio=False, min=0, max=100,
                         semantics="extra-frame-repetitions", playsFormula="loop_count+1",
                         audioSemantics="original-audio-once-then-silence"),
}


def _pin(spec):
    wid = spec.get("id")
    expected = SOURCE_HASHES.get(wid)
    if expected and spec.get("source_hash", spec.get("sourceHash")) != expected:
        raise ValueError("视频工作流源码已经变化，请重新审查尺寸和输出设置。")


def _number(value, name, minimum=0, maximum=8192):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + "需要填写有效整数。")
    if value != int(value) or value < minimum or value > maximum:
        raise ValueError(name + "超出已确认整数范围。")
    return int(value)


def reviewed_video_controls(workflow_id):
    p = POLICIES.get(workflow_id)
    if not p:
        return []
    result = []
    for axis in ("width", "height"):
        result.append(dict(id=p[axis + "Id"], nodeId=p["loader"], key="custom_" + axis,
                           label="处理宽度" if axis == "width" else "处理高度", kind="resolution",
                           type="number", value=0, min=0, max=p["modelMaximum"], step=1, integer=True,
                           dimensionGroup="video-size", dimensionAxis=axis,
                           help="0沿用比例；自定义优先",
                           title=f"两项都为0沿用原尺寸链；改比例会居中裁切，按{p['customMultiple']}像素对齐。",
                           targets=[dict(node=p["loader"], input="custom_" + axis)]))
    if workflow_id in OUTPUT_LOOP_POLICIES:
        policy = OUTPUT_LOOP_POLICIES[workflow_id]
        result.append(dict(id=policy["controlId"], nodeId=policy["node"], key="loop_count",
                           label="输出循环次数", kind="loop", type="number", value=0,
                           min=0, max=100, step=1, integer=True, uiGroup="output",
                           help="0不循环；音画同步重复",
                           title="0播放1遍；1播放2遍；完整音画一起循环，不重新推理生成。",
                           targets=[dict(node=policy["node"], input="loop_count")]))
    return result


def reviewed_video_config(workflow, cfg, graph=None):
    """Call after existing customization; returned copy preserves old defaults."""
    wid = workflow if isinstance(workflow, str) else workflow.get("id")
    if wid not in POLICIES:
        return copy.deepcopy(cfg)
    _pin({**cfg, "id": wid})
    result = copy.deepcopy(cfg)
    controls = result.setdefault("controls", [])
    by_id = {f["id"]: f for f in controls}
    for new in reviewed_video_controls(wid):
        if new["id"] in by_id:
            existing = by_id[new["id"]]
            if existing.get("targets") != new["targets"] or existing.get("value") != new["value"]:
                raise ValueError("已审查的宽高或输出循环默认值发生变化。")
            existing.update(copy.deepcopy(new))
        else:
            controls.append(new)
    p = POLICIES[wid]
    if p["longId"] in by_id:
        by_id[p["longId"]]["help"] = "自定义宽高优先"
        if wid == "local-card-5":
            by_id[p["longId"]]["hidden"] = True
    fields = WAN_FIELDS.get(wid)
    if fields:
        for field_id, key, help_text in ((fields["pose"], "pose_strength", "姿势跟随；1为默认"),
                                          (fields["face"], "face_strength", "表情跟随；1为默认")):
            if field_id not in by_id or by_id[field_id].get("targets") != [dict(node=fields["model"], input=key)]:
                raise ValueError("动作或面部参考强度的真实节点绑定变化。")
            by_id[field_id].update(min=0, max=10, step=0.001, help=help_text)
        duration = by_id.get(fields["duration"])
        if duration:
            if duration.get("targets") != [dict(node=fields["expression"], input="a")]:
                raise ValueError("处理时长的真实帧数公式绑定变化。")
            duration.update(max=min(duration.get("max", 624), 624), help="16帧/秒加载参考")
        for text in result.get("texts", []):
            if text.get("id") == fields.get("segment"):
                text.update(label=fields["label"], help=fields["help"])
    if wid == "local-card-5":
        duration = by_id.get("378:value:seconds")
        if duration:
            duration["help"] = "24帧/秒；0全部"
    _locator_text_presentation(result, wid)
    result["videoGeometryPolicy"] = copy.deepcopy(p)
    if wid in OUTPUT_LOOP_POLICIES:
        result["outputLoopPolicies"] = [copy.deepcopy(OUTPUT_LOOP_POLICIES[wid])]
    if graph is not None:
        classes = {str(n["id"]): n.get("type") for n in graph.get("nodes", [])} if isinstance(graph.get("nodes"), list) else {str(k): n.get("class_type") for k, n in graph.items() if isinstance(n, dict)}
        if classes.get(p["loader"]) != "VHS_LoadVideo" or classes.get(p["layer"]) != "LayerUtility: ImageScaleByAspectRatio V2":
            raise ValueError("自定义宽高的原始节点类型发生变化。")
    return result


def _require_path(graph, p):
    loader, layer, model = (graph.get(p[k], {}) for k in ("loader", "layer", "model"))
    if (loader.get("class_type") != "VHS_LoadVideo" or
            layer.get("class_type") != "LayerUtility: ImageScaleByAspectRatio V2" or
            model.get("class_type") != p["modelClass"]):
        raise ValueError("视频尺寸的真实执行节点发生变化。")
    source = p["intermediates"][-1][0] if p["intermediates"] else p["loader"]
    if layer.get("inputs", {}).get("image") != [source, 0]:
        raise ValueError("视频尺寸的原始输入链发生变化。")
    for node, key, source in p["intermediates"]:
        if graph.get(node, {}).get("inputs", {}).get(key) != [source, 0]:
            raise ValueError("视频尺寸的前处理链发生变化。")
    if p["modelClass"] == "BerniniConditioning" and p["model"] == "387":
        if graph.get("111", {}).get("inputs", {}).get("image") != [p["layer"], 0]:
            raise ValueError("Bernini视频条件尺寸链发生变化。")
        expected_width, expected_height = ["111", 0], ["111", 1]
    else:
        expected_width, expected_height = [p["layer"], 3], [p["layer"], 4]
    if model.get("inputs", {}).get("width") != expected_width or model.get("inputs", {}).get("height") != expected_height:
        raise ValueError("视频条件尺寸未跟随处理视频。")
    for index, node in enumerate(p["reference"]):
        parent = p["reference"][0] if index else p["layer"]
        slots = (1, 2) if index else (3, 4)
        inputs = graph.get(node, {}).get("inputs", {})
        if (graph.get(node, {}).get("class_type") != "ImageResizeKJv2" or
                inputs.get("width") != [parent, slots[0]] or inputs.get("height") != [parent, slots[1]]):
            raise ValueError("参考人物或背景尺寸没有同步处理视频。")
    if p["modelClass"] == "WanAnimateToVideo":
        second = graph.get("296", {})
        if (second.get("class_type") != "WanAnimateToVideo" or
                second.get("inputs", {}).get("width") != expected_width or
                second.get("inputs", {}).get("height") != expected_height):
            raise ValueError("WanAnimate续段尺寸链发生变化。")


def apply_video_control_projection(graph, spec, values):
    """Call after generic scalar bindings and before pruning; RETURN the graph."""
    wid = spec.get("id")
    result = copy.deepcopy(graph)
    if wid not in POLICIES:
        return result
    _pin(spec)
    p = POLICIES[wid]
    _require_path(result, p)
    fields = WAN_FIELDS.get(wid)
    if fields:
        expr = result.get(fields["expression"], {})
        if (expr.get("class_type") != "Evaluate Integers" or
                expr.get("inputs", {}).get("python_expression") != "a*b+1"):
            raise ValueError("处理时长的原始帧数公式发生变化。")
        if fields.get("segment"):
            segment = result.get(fields["segmentation"], {})
            if (segment.get("class_type") != "LayerMask: SegmentAnythingUltra V3" or
                    segment.get("inputs", {}).get("prompt") != [fields["prompt"], 0]):
                raise ValueError("人物或衣物定位的真实提示词绑定变化。")
    loader, layer = result[p["loader"]]["inputs"], result[p["layer"]]["inputs"]
    width = _number(values.get(p["widthId"], loader.get("custom_width", 0)), "处理宽度", maximum=p["modelMaximum"])
    height = _number(values.get(p["heightId"], loader.get("custom_height", 0)), "处理高度", maximum=p["modelMaximum"])
    loader.update(custom_width=width, custom_height=height)
    if width or height:
        layer.update(scale_to_side="None", round_to_multiple=str(p["customMultiple"]))
    elif layer.get("scale_to_side") == "None":
        layer.update(scale_to_side="longest", round_to_multiple=str(p["originalMultiple"]))
    loop = OUTPUT_LOOP_POLICIES.get(wid)
    if loop:
        output = result.get(loop["node"], {})
        inputs = output.get("inputs", {})
        if output.get("class_type") != "VHS_VideoCombine" or inputs.get("format") != loop["format"] or inputs.get("audio") != loop["audio"]:
            raise ValueError("输出循环的视频或声音绑定发生变化。")
        count = _number(values.get(loop["controlId"], inputs.get("loop_count", 0)), "输出循环次数", maximum=100)
        if count and inputs.get("trim_to_audio", False):
            raise ValueError("重复输出画面时不能同时按原音频时长裁切。")
        inputs["loop_count"] = count
    return result


def derive_video_processing_geometry(spec, values, source_width, source_height):
    """CPU size precheck before enqueue; follows actual VHS/LayerStyle math."""
    _pin(spec)
    p = POLICIES.get(spec.get("id"))
    if not p:
        raise ValueError("没有已审查的视频尺寸投影。")
    sw, sh = _number(source_width, "视频宽度", 1, 1000000), _number(source_height, "视频高度", 1, 1000000)
    cw = _number(values.get(p["widthId"], 0), "处理宽度", maximum=p["modelMaximum"])
    ch = _number(values.get(p["heightId"], 0), "处理高度", maximum=p["modelMaximum"])
    w, h = (cw, ch) if cw and ch else (cw, sh*cw/sw) if cw else (sw*ch/sh, ch) if ch else (sw, sh)
    unit = p["sourceMultiple"]
    w, h = int(w/unit + 0.5)*unit, int(h/unit + 0.5)*unit
    if min(w, h) <= 0:
        raise ValueError("自定义视频尺寸过小。")
    custom = bool(cw or ch)
    if custom:
        tw, th, multiple = w, h, p["customMultiple"]
    else:
        long_side = _number(values.get(p["longId"], p["defaultLong"]), "原处理最长边", 4, 100000000)
        tw, th = (long_side, int(long_side*h/w)) if w >= h else (int(long_side*w/h), long_side)
        multiple = p["originalMultiple"]
    tw, th = math.ceil(tw/multiple)*multiple, math.ceil(th/multiple)*multiple
    if min(tw, th) < p["modelMinimum"] or max(tw, th) > p["modelMaximum"]:
        raise ValueError(f"模型处理宽高需要在{p['modelMinimum']}–{p['modelMaximum']}像素之间，请调整尺寸。")
    scale = max(w/sw, h/sh)
    cropw, croph = min(sw, w/scale), min(sh, h/scale)
    return dict(custom=custom, loader=dict(width=w, height=h), target=dict(width=tw, height=th),
                crop=dict(x=(sw-cropw)/2, y=(sh-croph)/2, width=cropw, height=croph),
                fit="center-cover", multiple=multiple)


def finalize_video_schema(spec, *, template=None):
    """Compiler hook after native intersections; preserve fractional strengths."""
    wid = spec.get("id")
    if wid not in POLICIES:
        return spec
    _pin(spec)
    result = copy.deepcopy(spec)
    p = POLICIES[wid]
    if template is not None:
        _require_path(template, p)
    result["videoGeometryPolicy"] = copy.deepcopy(p)
    if wid in OUTPUT_LOOP_POLICIES:
        result["outputLoopPolicies"] = [copy.deepcopy(OUTPUT_LOOP_POLICIES[wid])]
    fields = WAN_FIELDS.get(wid)
    if fields:
        for text in result.get("texts", []):
            if text.get("id") == fields.get("segment"):
                text.update(label=fields["label"], help=fields["help"])
        for f in result.get("controls", []):
            if f.get("id") in (fields["pose"], fields["face"]):
                key = "pose_strength" if f["id"] == fields["pose"] else "face_strength"
                if f.get("targets") != [dict(node=fields["model"], input=key)]:
                    raise ValueError("参考强度的编译后目标发生变化。")
                f.update(min=0, max=10, step=0.001)
    return _locator_text_presentation(result)


def write_audit(root=ROOT):
    from scripts.review86_ltx_controls import reachable_nodes
    root = Path(root)
    catalog = json.loads((root/"public/local-catalog.json").read_text("utf-8"))["workflows"]
    registry = json.loads((root/"workflows/compiled-registry.json").read_text("utf-8"))["workflows"]
    interfaces = json.loads((root/"public/workflow-interfaces.json").read_text("utf-8"))["workflows"]
    original = {r["id"]: r["source"] for r in json.loads((root/"verification/catalog-audit.json").read_text("utf-8")) if isinstance(r, dict) and "id" in r and "source" in r}
    rows = []
    categories = {"动作迁移与舞蹈", "视频修复与扩展", "视频编辑与人物替换"}
    for w in catalog:
        if w.get("category") not in categories:
            continue
        wid, spec = w["id"], registry.get(w["id"], {})
        row = dict(id=wid, name=w["name"], category=w["category"], validation=spec.get("validation", "UI-only"),
                   blockingReason=spec.get("blocking_reason", ""), reviewedProjection=wid in POLICIES)
        path = root/"workflows/api"/spec.get("template", "absent")
        source = Path(original.get(wid, "absent"))
        if source.is_file():
            row["sourceHash"] = hashlib.sha256(source.read_bytes()).hexdigest()
            row["sourceHashMatchesSpec"] = row["sourceHash"] == spec.get("source_hash") if spec else None
        if path.is_file() and path.suffix == ".json":
            graph = json.loads(path.read_text("utf-8"))
            reached = reachable_nodes(graph, spec.get("outputs", []))
            row["inputs"] = []
            for id, n in graph.items():
                if id not in reached:
                    continue
                if n.get("class_type") in ("VHS_LoadVideo", "VHS_LoadVideoFFmpeg", "LayerUtility: ImageScaleByAspectRatio V2", "WanVideoAnimateEmbeds", "WanAnimateToVideo", "BerniniConditioning", "BerniniStudio", "VHS_VideoCombine"):
                    safe = {k:v for k,v in n.get("inputs", {}).items() if k in ("custom_width", "custom_height", "width", "height", "length", "num_frames", "pose_strength", "face_strength", "frame_load_cap", "force_rate", "scale_to_length", "round_to_multiple", "scale_to_side", "loop_count", "format", "audio", "trim_to_audio", "save_output", "image", "source_video")}
                    row["inputs"].append(dict(id=id, type=n["class_type"], inputs=safe))
            row["durationBindings"] = [dict(id=f["id"], value=f.get("value"), targets=f.get("targets"), transform=f.get("transform"), frameFormula=f.get("frameFormula")) for f in spec.get("controls", []) if f.get("kind") == "duration"]
            row["segmentationLabels"] = [dict(id=f["id"], label=f.get("label"), help=f.get("help")) for f in interfaces.get(wid, {}).get("texts", []) if "分割" in f.get("label", "") or "定位" in f.get("label", "")]
            if wid in POLICIES:
                projected = apply_video_control_projection(graph, spec, {})
                custom = apply_video_control_projection(graph, spec, {POLICIES[wid]["widthId"]:640, POLICIES[wid]["heightId"]:480})
                row["defaultGraphPreserved"] = projected == graph
                row["customSizeGraphPassed"] = custom[POLICIES[wid]["layer"]]["inputs"]["scale_to_side"] == "None"
                row["noNewNodes"] = set(custom) == set(graph)
        if wid == "local-card-0":
            row["reviewNote"] = "内置WanAnimate2子图，须按其可达尺寸链接单独设计；不套WanVideoAnimateEmbeds/VHS普通投影。"
        elif wid == "local-card-30":
            row["reviewNote"] = "VHS FFmpeg宽高由参考图Layer尺寸驱动，当前比例和输出短边已能改变尺寸；不套原视频驱动的投影。"
        elif wid == "local-card-31":
            row["reviewNote"] = "当前tracking_direction原生选择不兼容，保持阻塞，不新增未经运行验证的尺寸设置。"
        rows.append(row)
    out = root/"private/workflow-controls-review87"
    out.mkdir(parents=True, exist_ok=True)
    doc = dict(scope=sorted(categories), count=len(rows), workflows=rows,
               modifications=list(POLICIES), outputLoopPolicies=OUTPUT_LOOP_POLICIES,
               limits="本专项为静态图与CPU绑定检查；最终平台另有101一次真实GPU成功，见live-dual-test.json。",
               loopPolicyStage="本模块保留原生VHS端口语义快照；最终平台由prepare_output_loops及FFmpeg重复完整成片音画，GPU原生loop_count保持0。")
    (out/"wan-bernini-audit.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")
    lines = ["# WanAnimate / Bernini 同类工作流审查", "", f"按真实目录分类逐项审查 {len(rows)} 个工作流；尺寸投影仅启用已核对链路的 {len(POLICIES)} 个。", "", "|工作流|当前状态|宽高投影|检查说明|", "|---|---|---|---|"]
    for row in rows:
        lines.append(f"|{row['id']} {row['name']}|{row['validation']}|{'已核对' if row['reviewedProjection'] else '保留原图'}|{row.get('reviewNote',row.get('blockingReason',''))}|")
    lines += ["", "24: 定位文本3724→3720 SegmentAnythingUltra.prompt→3764 SeCVideoSegmentation.input_mask；作用是选择原视频人物区域，不是生成描述。", "24: 姿势与表情强度分别写3744 WanVideoAnimateEmbeds.pose_strength / face_strength，真实范围0–10、步长0.001；处理时长3743→3748 a*b+1，b=16FPS，写3751.frame_load_cap。", "5: 秒数先转换为24FPS帧数，写378，再经394的全部/限定分支及373多加载3帧；393截取输出帧。输出395沿用加载视频24FPS，不是原保存错误8FPS。", "5: 输出循环控件对应真实395.loop_count端口，平台含义为完整成片额外重复次数：0播1遍，1播2遍，画面和声音一起重复。最终GPU图的原生loop_count写0，由prepare_output_loops登记任务，再由FFmpeg在本地stream-copy完整成片，不再推理生成。", "原生VHS的loop_count只重复画面，后续音轨mux还可能截短循环画面；本模块OUTPUT_LOOP_POLICIES是该原生阶段快照，不代表平台最终音频行为。trim_to_audio=true与输出循环冲突时拒绝提交，默认false保留。", "宽高0/0保留原视频处理链；指定宽高以VHS真实custom_width/height驱动，关闭后续最长边覆盖，保留原参考/背景/条件尺寸链接和模型对齐。", "30的VHS FFmpeg由参考图尺寸驱动，0的WanAnimate2内置子图和31原阻塞单独保留，避免给不同实现套同一种控制。", "", "本专项没有提交GPU任务。最终平台另已完成101的一次真实生成并保存、验证完整音画循环，见live-dual-test.json；这不证明本表40个或本轮52个工作流均已真实生成通过。"]
    (out/"wan-bernini-audit.md").write_text("\n".join(lines)+"\n", "utf-8")
    return doc


if __name__ == "__main__":
    print(json.dumps({"audited": write_audit()["count"]}))
