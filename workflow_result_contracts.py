"""Source-pinned result roles; input previews are never counted as model results."""
import copy

HELPER_ID = "local-card-34"
HELPER_HASH = "7e42310611fd39b2591be056ba5795a9620b4a436fa127ddc6821f67772bc537"
MODEL_OUTPUTS = ("1515", "1524")


def _matches(graph, node, kind, **links):
    item = graph.get(node, {})
    return item.get("class_type") == kind and all(item.get("inputs", {}).get(k) == v for k, v in links.items())


def _helper_chain(spec, graph):
    return (spec.get("id") == HELPER_ID and spec.get("source_hash") == HELPER_HASH
            and _matches(graph, "1515", "ShowText|pysssss", text=["1514", 0])
            and _matches(graph, "1524", "ShowText|pysssss", text=["1525", 0])
            and _matches(graph, "1514", "RH_LLMAPI_NODE", role=["1486", 0])
            and _matches(graph, "1525", "RH_LLMAPI_NODE", role=["1529", 0])
            and _matches(graph, "1486", "ShowText|pysssss", text=["1496", 0])
            and _matches(graph, "1529", "ShowText|pysssss", text=["1528", 0]))


def finalize_prompt_helper_outputs(spec, graph):
    if spec.get("id") != HELPER_ID:
        return spec
    if not _helper_chain(spec, graph):
        raise ValueError("提示词辅助的模型结果连线发生变化，请重新审查。")
    if set(spec.get("outputs", [])) not in ({"1515", "1486", "1529", "1524"}, set(MODEL_OUTPUTS)):
        raise ValueError("提示词辅助的输出节点发生变化，请重新审查。")
    result = copy.deepcopy(spec)
    result["outputs"] = list(MODEL_OUTPUTS)
    return result


def prompt_helper_output_metadata(spec, graph):
    if not _helper_chain(spec, graph):
        return {}
    return {"1515": dict(label="文字扩写结果", role="result"),
            "1524": dict(label="图片反推结果", role="result"),
            "1486": dict(label="文字分支输入预览", role="input-preview"),
            "1529": dict(label="图片分支输入预览", role="input-preview")}


def prompt_helper_receipt_error(spec, graph, receipt):
    if not _helper_chain(spec, graph):
        return None
    outputs = receipt.get("outputs", {})
    if not isinstance(outputs, dict):
        outputs = {}
    for node, label in (("1515", "文字扩写"), ("1524", "图片反推")):
        block = outputs.get(node, {})
        if not isinstance(block, dict):
            block = {}
        texts = []
        for key in ("text", "string", "strings"):
            values = block.get(key, [])
            if isinstance(values, str):
                values = [values]
            if isinstance(values, list):
                texts.extend(v for v in values if isinstance(v, str) and v.strip())
        if not texts:
            return f"{label}服务没有返回有效文字。输入和返回记录已保留，请稍后重试。"
    return None
