"""Reviewed LTX video processing controls and read-only graph audit.

The optional dimensions are real VHS loader inputs. 0/0 preserves the
existing graph; a positive edge enables a reviewed projection which prevents
the subsequent longest-edge node from resizing the clip a second time.
No new execution nodes, generic output_width fields, or GPU jobs are created.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_HASHES = {
    "local-card-49": "4e0bc9ff0db7e4a5401bdd6b3f15bd295e1e94361e5ebc029e5ebde929bda9e7",
    "local-card-51": "22850d24d702737845f1774c14f4c6af1bb0d0d99f8dc6397fb5963be21aea3d",
    "local-card-125": "7ba9b5a6f05c3b3d07114971ce2694467c1e925428293542c598be77cd996868",
    "local-card-40": "1ee0c5812e0cd846ba6460ae69411de2bae4797ee38e5be60017e8e34b7655e7",
    "local-card-41": "cbc23fea743b2442ce7785a8871395c1a42ff44f722210f1df4622aaf2dadcdf",
    "local-card-43": "5a71b45bc2030730b179714c99d5d57da3db5a2c22e02a5ec25f35fdaf97f36b",
    "local-card-48": "3f7f78cef2917358ec4907c88567e082fa926358ed6d474c0d3f8242f99aab1e",
    "local-card-56": "0502f0dc461bd07cfc6047bcaa00eaccd4fb061b7e5d5111b0c5179402107f2c",
    "local-card-57": "ebd2ee400475fdf6158c1fb52f1cd5d7842e32284d7a1143432d1b816782f0a5",
    "local-card-59": "e2fdba9cffa3a634266ce66d0c0c65b47f00676a5c36b24a0d88c362b9e92665",
    "local-card-61": "97ef35ebca5e087546da5ea2dcff822560c68a9d62cb5191d20df37012137dc0",
    "local-card-66": "8ce5bec5561cb9b7a466efba3c06910305999867a1c9282b164af3c430d47e86",
    "local-card-67": "a2f7f243bda66b5ae1ee4d9364aa22dd9ae8dc0f771595537082ab8520d617ab",
    "local-card-68": "87aeca2157dafa9dddc059b0bb3658f90c302332e32dca509b133caa3e8e04b9",
    "local-card-69": "96c5c7295813425adf9af75ca66a0ceac8b136cf5b8a6c0a5ed9c350b7221dc6",
    "local-card-116": "c1f298110654069dd391f1ecd8422a952ca0b3deee229d234ca1ff3a53ab073d",
    "local-card-117": "c167d210db8f5270d0b760f5e0bb330f89217d34ba48b7e4d4b737ddfc18b6bf",
    "local-card-126": "bf0d7a376b716c0fd40bd1dfe55fac31ab22553b3189b974498592165652a20e",
}
LONG_SIDE_FIELDS = {
    "local-card-40": ("37:value", (("38", "scale_to_length"),), 4, 100000000),
    "local-card-41": ("434:scale_to_length", (("434", "scale_to_length"),), 4, 100000000),
    "local-card-43": ("369:value", (("369", "value"),), 1, 16384),
    "local-card-48": ("369:value", (("369", "value"),), 1, 16384),
    "local-card-49": ("404:value", (("404", "value"),), 1, 16384),
    "local-card-51": ("1105:value", (("1064", "scale_to_length"),), 4, 100000000),
    "local-card-56": ("133:value", (("131", "scale_to_length"),), 4, 100000000),
    "local-card-57": ("21:value", (("9", "scale_to_length"),), 4, 100000000),
    "local-card-59": ("272:scale_to_length", (("272", "scale_to_length"),), 4, 100000000),
    "local-card-61": ("281:value", (("272", "scale_to_length"),), 4, 100000000),
    "local-card-66": ("281:value", (("272", "scale_to_length"),), 4, 100000000),
    "local-card-67": ("281:value", (("272", "scale_to_length"),), 4, 100000000),
    "local-card-68": ("281:value", (("272", "scale_to_length"),), 4, 100000000),
    "local-card-69": ("281:value", (("272", "scale_to_length"),), 4, 100000000),
    "local-card-116": ("777:value", (("756", "scale_to_length"),), 4, 100000000),
    "local-card-117": ("281:value", (("272", "scale_to_length"),), 4, 100000000),
    "local-card-126": ("56:value", (("52", "scale_to_length"), ("69", "a")), 4, 100000000),
}
POLICIES = {
    "local-card-49": {
        "loader": "363", "resize": "453", "long": "404",
        "widthId": "363:custom_width", "heightId": "363:custom_height",
        "longId": "404:value", "scaleId": "467:value", "scaleNode": "467",
        "sourceMultiple": 32, "multiple": 1, "postScale": 1,
        "resizeClass": "ResizeImageMaskNode",
    },
    "local-card-51": {
        "loader": "1084", "resize": "1064", "long": "1105",
        "widthId": "1084:custom_width", "heightId": "1084:custom_height",
        "longId": "1105:value", "scaleId": None,
        "sourceMultiple": 8, "multiple": 32, "postScale": 0.5,
        "resizeClass": "LayerUtility: ImageScaleByAspectRatio V2",
    },
}


def _number(value, name, minimum=0, maximum=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name}需要填写有效数值。")
    if value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{name}超出已确认范围。")
    if integer and value != int(value):
        raise ValueError(f"{name}需要填写整数。")
    return int(value) if integer else float(value)


def reviewed_ltx_controls(workflow_id):
    """Definitions bind only existing, reachable native input fields."""
    policy = POLICIES.get(workflow_id)
    if policy is None:
        return []
    result = []
    for axis, key in (("width", "widthId"), ("height", "heightId")):
        result.append({
            "id": policy[key], "nodeId": policy["loader"], "key": "custom_" + axis,
            "label": "处理宽度" if axis == "width" else "处理高度",
            "kind": "resolution", "type": "number", "value": 0,
            "min": 0, "max": 8192, "step": 1, "integer": True,
            "dimensionGroup": "video-size", "dimensionAxis": axis,
            "help": "0沿用比例；模型对齐",
            "targets": [{"node": policy["loader"], "input": "custom_" + axis}],
        })
    if policy["scaleId"]:
        result.append({
            "id": policy["scaleId"], "nodeId": policy["scaleNode"], "key": "value",
            "label": "视频处理缩放系数", "kind": "strength", "type": "number",
            "value": 1, "min": 0.01, "max": 8, "step": 0.01,
            "help": "1不缩放；小于1缩小",
            "targets": [{"node": policy["scaleNode"], "input": "value"}],
            "constraintSources": [{"node": "448", "input": "scale_by"}],
        })
    return result


def _require_reviewed_hash(spec):
    workflow_id = spec.get("id")
    expected = SOURCE_HASHES.get(workflow_id)
    actual = spec.get("source_hash", spec.get("sourceHash"))
    if expected and actual != expected:
        raise ValueError("LTX工作流源码版本已经变化，不能套用旧尺寸规则。")


def _tighten_long_side(field, targets, minimum, maximum, *, alternate_targets=None):
    actual = tuple((str(target.get("node")), target.get("input")) for target in field.get("targets", []))
    matches = set(actual) == set(targets) and len(actual) == len(targets)
    if alternate_targets is not None:
        matches = matches or (set(actual) == set(alternate_targets) and len(actual) == len(alternate_targets))
    if not matches:
        raise ValueError("视频最长边的真实目标已经变化，请重新审查。")
    custom = field.get("customRange") if isinstance(field.get("customRange"), dict) else {}
    lower = [minimum]
    upper = [maximum]
    steps = [1]
    for source in (field, custom):
        if isinstance(source.get("min"), (int, float)) and not isinstance(source.get("min"), bool):
            lower.append(source["min"])
        if isinstance(source.get("max"), (int, float)) and not isinstance(source.get("max"), bool):
            upper.append(source["max"])
        if isinstance(source.get("step"), (int, float)) and source["step"] > 0:
            steps.append(source["step"])
    step = max(steps)
    origin = custom.get("min", field.get("min", 0))
    if not isinstance(origin, (int, float)) or isinstance(origin, bool):
        origin = 0
    # Retain the existing custom-step lattice. Raising min from0 to4 with a
    #64px step must not make the old valid1280 default fail step validation.
    effective_min = origin + math.ceil((max(lower) - origin) / step) * step
    field.update(min=effective_min, max=min(upper), step=step, integer=True)
    if field["min"] > field["max"]:
        raise ValueError("视频最长边的已审查范围发生冲突。")
    if custom:
        custom.update(min=field["min"], max=field["max"], step=field["step"])


def reviewed_ltx_config(workflow, cfg, graph=None):
    """Add reviewed controls/config, preserving defaults and execution bytes."""
    workflow_id = workflow if isinstance(workflow, str) else workflow.get("id")
    result = copy.deepcopy(cfg)
    if workflow_id not in SOURCE_HASHES:
        return result
    _require_reviewed_hash({**result, "id": workflow_id})
    if graph is not None:
        classes = ({str(node["id"]): node.get("type") for node in graph["nodes"]}
                   if isinstance(graph.get("nodes"), list) else
                   {str(key): node.get("class_type") for key, node in graph.items() if isinstance(node, dict)})
        if workflow_id == "local-card-125":
            required = {"208": "PrimitiveInt", "215": "PrimitiveInt", "233": "ComfyMathExpression"}
        elif workflow_id in POLICIES:
            required = {POLICIES[workflow_id]["loader"]: "VHS_LoadVideo",
                        POLICIES[workflow_id]["resize"]: POLICIES[workflow_id]["resizeClass"]}
        elif workflow_id in ("local-card-43", "local-card-48"):
            required = {"369": "PrimitiveInt", "496": "ResizeImageMaskNode"}
        else:
            native_node = LONG_SIDE_FIELDS[workflow_id][1][0][0]
            required = {native_node: "LayerUtility: ImageScaleByAspectRatio V2"}
        if any(classes.get(node) != kind for node, kind in required.items()):
            raise ValueError("LTX已审查的尺寸或时长节点已经变化。")
    controls = result.setdefault("controls", [])
    if not isinstance(controls, list):
        raise ValueError("LTX控件配置格式不正确。")
    by_id = {field["id"]: field for field in controls}
    for field in reviewed_ltx_controls(workflow_id):
        if field["id"] not in by_id:
            controls.append(field)
        else:
            actual = {(str(target.get("node")), target.get("input")) for target in by_id[field["id"]].get("targets", [])}
            expected = {(str(target["node"]), target["input"]) for target in field["targets"]}
            if actual != expected:
                raise ValueError("自定义处理尺寸的真实字段绑定已经变化。")
    if workflow_id in LONG_SIDE_FIELDS:
        field_id, targets, minimum, maximum = LONG_SIDE_FIELDS[workflow_id]
        if field_id not in by_id:
            raise ValueError("视频最长边的已审查控件缺失，不能静默修改配置。")
        # Card116's source UI also includes the authored 680.a branch. The
        # compiled output retains only 756.scale_to_length. Both exact lists
        # are covered by the pinned source hash; keep all source bindings.
        alternate = (("680", "a"), ("756", "scale_to_length")) if workflow_id == "local-card-116" else None
        _tighten_long_side(by_id[field_id], targets, minimum, maximum, alternate_targets=alternate)
    if workflow_id == "local-card-49" and "404:value" in by_id:
        # Native core accepts zero syntactically, but its longer-edge path
        # computes zero dimensions. This is an effective semantic lower bound.
        by_id["404:value"]["help"] = "自定义尺寸优先"
    if workflow_id == "local-card-51":
        if "1105:value" in by_id:
            by_id["1105:value"]["help"] = "自定义尺寸优先"
        metadata = ltx_points_recipe_metadata(workflow_id)
        if isinstance(result.get("pointsRecipe"), dict):
            result["pointsRecipe"].update(metadata)
        points = by_id.get("1095:points")
        if points is not None and isinstance(points.get("previewRecipe"), dict):
            points["previewRecipe"].update(metadata)
    if workflow_id == "local-card-125" and "208:value" in by_id:
        duration = by_id["208:value"]
        duration.update(label="目标生成时长（秒）", help="按模型帧数对齐",
                        max=min(duration.get("max",655),655))
        duration["frameFormula"] = {"node": "233", "expression": "a*b+1", "fps": 25, "fpsSource": "215:value"}
        duration["effectiveDuration"] = {"kind": "ltx-frame-grid", "fps": 25,
                                         "minFrames": 1, "stepFrames": 8,
                                         "extraFrames": 1, "offsetFrames": 1, "rounding": "floor"}
    return result


def finalize_ltx_schema(spec, *, template=None):
    """Keep the scale control on ImageScaleBy's grid after primitive mapping."""
    if spec.get('id')!='local-card-49':
        return spec
    _require_reviewed_hash(spec)
    field_list=[field for field in spec.get('controls',[]) if field['id']=='467:value']
    if len(field_list)!=1 or field_list[0].get('targets')!=[{'node':'467','input':'value'}]:
        raise ValueError('LTX处理缩放的已审查绑定已经变化。')
    if template is not None:
        if (template.get('467',{}).get('class_type')!='PrimitiveFloat' or
            template.get('448',{}).get('class_type')!='ImageScaleBy' or
            template['448'].get('inputs',{}).get('scale_by')!=['467',0]):
            raise ValueError('LTX处理缩放的原生执行路径已经变化。')
    result=copy.deepcopy(spec)
    field=next(field for field in result['controls'] if field['id']=='467:value')
    field.update(min=0.01,max=8,step=0.01)
    return result


def ltx_points_recipe_metadata(workflow_id):
    policy = POLICIES.get(workflow_id)
    if policy is None:
        return {}
    return {
        "customWidthControlId": policy["widthId"],
        "customHeightControlId": policy["heightId"],
        "sourceMultiple": policy["sourceMultiple"],
        "multiple": policy["multiple"], "postScale": policy["postScale"],
        "customGeometryPolicy": "vhs-center-crop-then-layer-none-v1" if workflow_id == "local-card-51" else "vhs-center-crop-then-resize-identity-v1",
    }


def _dimensions(policy, graph, values):
    inputs = graph[policy["loader"]]["inputs"]
    return tuple(
        _number(values.get(policy[key], inputs.get("custom_" + axis, 0)),
                "处理宽度" if axis == "width" else "处理高度", 0, 8192, True)
        for axis, key in (("width", "widthId"), ("height", "heightId"))
    )


def apply_ltx_control_projection(graph, spec, values):
    """Return a copy after generic control binding, before graph pruning.

    All-zero dimensions preserve the original longest-edge pipeline. Values
    are not changed: old jobs retain their original scale/default behavior.
    """
    result = copy.deepcopy(graph)
    workflow_id = spec.get("id")
    policy = POLICIES.get(workflow_id)
    if policy is None:
        return result
    _require_reviewed_hash(spec)
    loader = result.get(policy["loader"], {})
    resize = result.get(policy["resize"], {})
    if loader.get("class_type") != "VHS_LoadVideo" or resize.get("class_type") != policy["resizeClass"]:
        raise ValueError("视频处理尺寸的执行节点已经变化，请重新审查。")
    if resize.get("inputs", {}).get("input" if workflow_id == "local-card-49" else "image") != [policy["loader"], 0]:
        raise ValueError("视频处理尺寸的原始输入绑定已经变化，请重新审查。")
    width, height = _dimensions(policy, result, values)
    loader["inputs"].update(custom_width=width, custom_height=height)
    if policy["scaleId"] and policy["scaleId"] in values:
        scale = _number(values[policy["scaleId"]], "缩放系数", 0.01, 8)
        scale_node = result.get(policy["scaleNode"], {})
        if scale_node.get("class_type") != "PrimitiveFloat" or result.get("448", {}).get("inputs", {}).get("scale_by") != [policy["scaleNode"], 0]:
            raise ValueError("视频缩放系数的真实绑定已经变化，请重新审查。")
        scale_node["inputs"]["value"] = scale
    custom = width > 0 or height > 0
    if workflow_id == "local-card-49":
        inputs = resize["inputs"]
        if custom:
            for key in list(inputs):
                if key.startswith("resize_type."):
                    del inputs[key]
            inputs.update({"resize_type": "scale dimensions", "resize_type.width": 0,
                           "resize_type.height": 0, "resize_type.crop": "center"})
        elif inputs.get("resize_type") == "scale dimensions":
            for key in list(inputs):
                if key.startswith("resize_type."):
                    del inputs[key]
            inputs.update({"resize_type": "scale longer dimension",
                           "resize_type.longer_size": [policy["long"], 0]})
    elif custom:
        resize["inputs"]["scale_to_side"] = "None"
    elif resize["inputs"].get("scale_to_side") == "None":
        resize["inputs"]["scale_to_side"] = "longest"
    return result


def _cover_rect(width, height, target_width, target_height):
    scale = max(target_width / width, target_height / height)
    crop_width = min(width, target_width / scale)
    crop_height = min(height, target_height / scale)
    return {"x": (width - crop_width) / 2, "y": (height - crop_height) / 2,
            "width": crop_width, "height": crop_height}


def derive_ltx_processing_geometry(spec, values, source_width, source_height):
    """Pure size/crop math for the reviewed native processing path.

    VHS custom dimensions use center-cover crop, not stretch. A zero side is
    derived from the source ratio, then VHS rounds to its format multiple.
    Card51 retains LayerStyle's round32 and then ImageScaleBy's half scale.
    The returned target is SeC/PointsEditor tracking space, not a promise of
    exact final generated pixels. No frames are decoded by this function.
    """
    workflow_id = spec.get("id")
    policy = POLICIES.get(workflow_id)
    if policy is None:
        raise ValueError("此工作流没有已审查的LTX处理尺寸路径。")
    _require_reviewed_hash(spec)
    width = _number(source_width, "原视频宽度", 1, integer=True)
    height = _number(source_height, "原视频高度", 1, integer=True)
    custom_width = _number(values.get(policy["widthId"], 0), "处理宽度", 0, 8192, True)
    custom_height = _number(values.get(policy["heightId"], 0), "处理高度", 0, 8192, True)
    custom = custom_width > 0 or custom_height > 0
    load_width, load_height = width, height
    if custom_width and custom_height:
        load_width, load_height = custom_width, custom_height
    elif custom_width:
        load_width, load_height = custom_width, height * custom_width / width
    elif custom_height:
        load_width, load_height = width * custom_height / height, custom_height
    multiple = policy["sourceMultiple"]
    load_width = int(load_width / multiple + 0.5) * multiple
    load_height = int(load_height / multiple + 0.5) * multiple
    if min(load_width, load_height) <= 0:
        raise ValueError("自定义处理尺寸过小，不能形成有效视频画面。")
    if custom:
        layer_width, layer_height = load_width, load_height
    else:
        long_side = _number(values.get(policy["longId"], 1280), "处理最长边", 1)
        if workflow_id == "local-card-49":
            scale = long_side / max(load_width, load_height)
            layer_width, layer_height = round(load_width * scale), round(load_height * scale)
        elif load_width >= load_height:
            layer_width, layer_height = int(long_side), int(long_side * load_height / load_width)
        else:
            layer_width, layer_height = int(long_side * load_width / load_height), int(long_side)
    multiple = policy["multiple"]
    if multiple > 1:
        layer_width = math.ceil(layer_width / multiple) * multiple
        layer_height = math.ceil(layer_height / multiple) * multiple
    post_scale = policy["postScale"]
    if policy["scaleId"]:
        post_scale = _number(values.get(policy["scaleId"], 1), "缩放系数", 0.01, 8)
    target_width, target_height = round(layer_width * post_scale), round(layer_height * post_scale)
    # LTXVPreprocess(img_compression>0) requires even edges. Card51's
    # round32/half path always has even edges; card49 arbitrary factors may not.
    target_width -= target_width % 2
    target_height -= target_height % 2
    if min(target_width, target_height) < 64:
        raise ValueError("缩放后的LTX处理画面至少需要64×64像素。")
    if max(target_width, target_height) > 16384:
        raise ValueError("缩放后的LTX处理宽高不能超过16384像素，请减小尺寸或缩放系数。")
    first = _cover_rect(width, height, load_width, load_height)
    second = _cover_rect(load_width, load_height, layer_width, layer_height)
    crop = {
        "x": first["x"] + second["x"] / load_width * first["width"],
        "y": first["y"] + second["y"] / load_height * first["height"],
        "width": second["width"] / load_width * first["width"],
        "height": second["height"] / load_height * first["height"],
    }
    cover = max(layer_width / load_width, layer_height / load_height)
    return {"custom": custom, "source": {"width": load_width, "height": load_height},
            "layerTarget": {"width": layer_width, "height": layer_height},
            "target": {"width": target_width, "height": target_height}, "crop": crop,
            "framePercent": {"width": load_width * cover / layer_width * 100,
                             "height": load_height * cover / layer_height * 100},
            "fit": "center-cover", "postScale": post_scale}


def ltx_duration_info(seconds, fps=25):
    seconds = _number(seconds, "目标生成时长", 0, integer=True)
    fps = _number(fps, "帧率", 1, integer=True)
    requested_frames = seconds * fps + 1
    if requested_frames > 16384:
        raise ValueError("目标生成时长超出LTX原生帧数范围。")
    grid_frames = (requested_frames - 1) // 8 * 8 + 1
    return {"targetSeconds": seconds, "fps": fps, "frameFormula": "25*a+1" if fps == 25 else f"{fps}*a+1",
            "requestedFrames": requested_frames, "frameGrid": {"step": 8, "offset": 1, "rounding": "floor"},
            "gridFrames": grid_frames, "gridDurationSeconds": grid_frames / fps}


def _connections(value, graph):
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[1], int) and str(value[0]) in graph:
            yield str(value[0])
        else:
            for item in value:
                yield from _connections(item, graph)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _connections(item, graph)


def reachable_nodes(graph, outputs):
    visited = set()
    def visit(node):
        if node in visited or node not in graph:
            return
        visited.add(node)
        for dependency in _connections(graph[node].get("inputs", {}), graph):
            visit(dependency)
    for node in outputs:
        visit(str(node))
    return visited


def write_audit(root=ROOT):
    """Audit all named category members; no network, writes only report files."""
    root = Path(root)
    catalog = json.loads((root / "public/local-catalog.json").read_text("utf-8"))["workflows"]
    registry = json.loads((root / "workflows/compiled-registry.json").read_text("utf-8"))["workflows"]
    interfaces = json.loads((root / "public/workflow-interfaces.json").read_text("utf-8"))["workflows"]
    original_index = {row["id"]: row["source"] for row in json.loads((root / "verification/catalog-audit.json").read_text("utf-8"))
                      if isinstance(row, dict) and isinstance(row.get("id"), str) and isinstance(row.get("source"), str)}
    rows = []
    for entry in catalog:
        wid = entry["id"]
        if entry.get("category") not in ("视频编辑与人物替换", "首尾帧生视频") or wid == "local-card-65":
            continue
        spec = registry.get(wid)
        row = {"id": wid, "name": entry["name"], "category": entry["category"],
               "availableCompiledSpec": bool(spec), "fields": [], "blockingReason": spec.get("blocking_reason") if spec else "No compiled spec"}
        source_path = Path(original_index.get(wid, ""))
        if source_path.is_file():
            data = source_path.read_bytes()
            raw = json.loads(data.decode("utf-8-sig"))
            row.update(source=str(source_path), sourceHash=hashlib.sha256(data).hexdigest(),
                       sourceNodes=[{"id": n["id"], "type": n["type"]} for n in raw.get("nodes", [])])
        graph_path = root / "workflows/api" / spec["template"] if spec and spec.get("template") else None
        if graph_path and graph_path.is_file():
            graph = json.loads(graph_path.read_text("utf-8"))
            reachable = reachable_nodes(graph, spec.get("outputs", []))
            row.update(compiled=str(graph_path), compiledNodeCount=len(graph), outputReachableNodeCount=len(reachable),
                       sourceHashMatchesSpec=row.get("sourceHash") == spec.get("source_hash"),
                       compiledFileSha256=hashlib.sha256(graph_path.read_bytes()).hexdigest())
            public_fields = {field["id"]: field for field in interfaces.get(wid, {}).get("controls", [])}
            # Executable targets come from the compiled registry. The public
            # interface can use display-only subgraph aliases such as sub0/.
            for field in spec.get("controls", []):
                bindings = []
                for target in field.get("targets", []):
                    node = graph.get(str(target["node"]), {})
                    bindings.append({"node": str(target["node"]), "input": target["input"],
                                     "nodeType": node.get("class_type"), "exists": target["input"] in node.get("inputs", {}),
                                     "reachable": str(target["node"]) in reachable})
                row["fields"].append({"id": field["id"], "label": field.get("label"), "kind": field.get("kind"), "bindings": bindings,
                                      "publicBindingRepresentationDiffers": public_fields.get(field["id"], {}).get("targets") != field.get("targets")})
            if wid in LONG_SIDE_FIELDS:
                reviewed = reviewed_ltx_config(wid, {"sourceHash": spec["source_hash"],
                                                     "controls": copy.deepcopy(spec.get("controls", []))}, graph)
                field_id, targets, minimum, maximum = LONG_SIDE_FIELDS[wid]
                applied = next(field for field in reviewed["controls"] if field["id"] == field_id)
                row["reviewedLongSideBounds"] = {"fieldId": field_id, "operationMinimum": minimum,
                                                 "nativeMaximum": maximum, "effectiveMin": applied["min"],
                                                 "effectiveMax": applied["max"], "step": applied["step"],
                                                 "defaultPreserved": applied.get("value"), "targets": list(targets)}
            row["sizeAndDurationNodes"] = []
            for node_id in sorted(reachable):
                node = graph[node_id]
                if any(token in node.get("class_type", "") for token in ("Resize", "Scale", "VHS_LoadVideo", "MathExpression", "EmptyLTX")):
                    inputs = node.get("inputs", {})
                    safe = {key: val for key, val in inputs.items() if any(token in key for token in ("width", "height", "scale", "length", "frame", "expression", "resize_type", "force_rate")) and "model" not in key and "image" not in key}
                    row["sizeAndDurationNodes"].append({"id": node_id, "type": node["class_type"], "safeInputs": safe})
        rows.append(row)
    out = root / "private/workflow-video-review-2026-10-08"
    out.mkdir(parents=True, exist_ok=True)
    report = {"scope": "All video editing/person replacement and first-last video category entries except card65; source and graph audit, no GPU or deployment", "workflows": rows,
              "count": len(rows), "newControls": {wid: reviewed_ltx_controls(wid) for wid in POLICIES},
              "pointsMetadata": {wid: ltx_points_recipe_metadata(wid) for wid in POLICIES},
              "card125Duration": ltx_duration_info(2),
              "runtimeNativeDefinitions": "ltx-live-nodeinfo.json",
              "reviewedPositiveLongestFields": {wid: {"fieldId": item[0], "targets": list(item[1]),
                                                       "operationMin": item[2], "nativeMax": item[3],
                                                       "sourceHash": SOURCE_HASHES[wid]}
                                                  for wid, item in LONG_SIDE_FIELDS.items()},
              "boundsFixStatus": "Owned reviewed_ltx_config implements all14 LayerStyle min4 and3 core-longer min1 rules; defaults and stricter custom limits preserved. Root integrates public/compiled config.",
              "integration": {"build": "schema_adapters.build: after generic controls and apply_reviewed_repairs; before prune, call apply_ltx_control_projection(graph,spec,values).",
                              "points": "server.points_geometry for card51: derive_ltx_processing_geometry(spec,values,width,height); bind tracking target dimensions, not pre-half layer dimensions.",
                              "frontend": "previewRecipe must carry customWidthControlId/customHeightControlId. Follow source center-cover crop, Layer ceil32, half scale; clear old selections when effective crop changes."},
              "evidenceBoundary": "Pure graph/geometry validation only. Existing native inputs/classes and current nodeinfo are verified; upstream implementation is referenced without claiming installed-source byte equivalence. No added source nodes or GPU generation."}
    (out / "ltx-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    lines = ["# LTX及同类视频参数审查", "", f"覆盖{len(rows)}项类别条目；原图/当前执行图/可达绑定核对，没有提交GPU任务。", "", "| 工作流 | 编译入口 | 源哈希一致 | 现有字段 |", "|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['id']} {row['name']} | {row['availableCompiledSpec']} | {row.get('sourceHashMatchesSpec', '未验证')} | {len(row['fields'])} |")
    lines += ["", "125的真实时长是208 PrimitiveInt，233计算25*a+1。LTX按8n+1帧向下对齐；2秒目标51帧，本轮旧产物实际49帧25FPS=1.96秒。时长应表达目标，不保证精确秒数。", "", "49真实缩放为467.value→448.scale_by，默认1；native范围0.01–8。新增宽高只绑定363.custom_width/custom_height，原值均0。51对应1084的真实宽高字段。0/0保留原longest1280；任意边>0才启用自定义处理路径。49将既有453切到scale dimensions并令其宽高0/0，避免再次缩放；51把1064.scale_to_side设为已有None枚举，保留round32、全部接线、半尺寸处理。", "", "最长边边界已在owned reviewed_ltx_config修正：40/41/51/56/57/59/61/66/67/68/69/116/117/126共14项按LayerStyle原生min4；43/48/49共3项Core长边操作按有效min1。Core虽接受0的类型输入，计算会生成零尺寸，不能显示为沿用。配置按新鲜源hash白名单和完整targets核对；默认值不变，原有更严格customRange上下限/步长保留，既有步长网格不平移。", "", "宽高是处理尺寸，0由原比例补边；不是精确最终作品像素承诺。VHS先按格式倍数取最近尺寸，使用中心cover裁切；51再按LayerStyle向上对齐32并缩放0.5。点选必须以最终tracking空间计算，不能用预半尺寸空间。前端预览需依次组合原视频→VHS中心裁切、VHS→Layer中心裁切。有效裁切改变时清除旧点，默认几何不变时不清。", "", "接口及完整target见ltx-audit.json。reviewed_ltx_config供builder配置派生；apply_ltx_control_projection在schema_adapters.build通用控件绑定后、prune前；derive_ltx_processing_geometry在server.points_geometry读取源尺寸之后。125 effectiveDuration含kind=ltx-frame-grid,fps25,stepFrames8,extraFrames1,rounding=floor，预估不冒充文件实际时长。没有改共享schema/server/public文件。", "", "原生尺寸输入当前nodeinfo已保存。实现行为参考：[Comfy Resize](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_post_processing.py)、[VHS loader](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite/blob/main/videohelpersuite/load_video_nodes.py)、[LayerStyle V2](https://github.com/chflame163/ComfyUI_LayerStyle/blob/main/py/image_scale_by_aspect_ratio_v2.py)。VHS源代码common_upscale明确center模式，LayerStyle自定义None分支仍round到倍数并按crop拟合，均非stretch。运行端schema已实时查询，但这些官方源码不冒称安装端字节一致。"]
    (out / "ltx-audit.md").write_text("\n".join(lines), "utf-8")
    return report


if __name__ == "__main__":
    report = write_audit()
    print(f"Audited {report['count']} workflow category entries; no GPU submission.")
