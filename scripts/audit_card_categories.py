"""Check card workflow categories against live-snapshot names and graph input/output shapes."""
import json
import re
from collections import Counter
from pathlib import Path

from build_workflow_interfaces import Graph

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-09-28"


def main():
    inventory = json.loads((ROOT / f"verification/card-inventory-{DAY}.json").read_text(encoding="utf-8"))
    files = json.loads((ROOT / "private/research/card-20260923/files.json").read_text(encoding="utf-8"))
    index = {name: i for i, name in enumerate(files)}
    configs = json.loads((ROOT / "public/workflow-interfaces.json").read_text(encoding="utf-8"))["workflows"]
    rows = []
    for item in inventory["workflows"]:
        if not item["validWorkflow"]:
            continue
        source = ROOT / f"private/research/card-20260923/graph-{index[item['path']]:03}.json"
        graph = Graph(json.loads(source.read_text(encoding="utf-8")))
        sinks = sorted({node["type"] for key, node in graph.nodes.items() if key in graph.reachable and re.search(
            r"SaveImage|SaveVideo|VideoCombine|ShowText|showAnything|PreviewImage|PreviewAudio|TextPreview|SaveAudio|SaveAnimated", node["type"], re.I)})
        output = "video" if any(re.search(r"Video|VideoCombine|SaveAnimated", t, re.I) for t in sinks) else "image" if any(re.search(r"Image", t, re.I) for t in sinks) else "text" if any(re.search(r"Text|showAnything", t, re.I) for t in sinks) else "unknown"
        media = Counter(m["kind"] for m in configs[item["catalogId"]]["media"])
        category = item["category"]
        problems = []
        if Path(item["path"]).stem != item["catalogName"]:
            problems.append("display name differs from source basename")
        if category in ["文字生图", "图像编辑", "图像增强与整理", "参考图与套图"] and output != "image":
            problems.append("image category has no active image output")
        if category in ["文字生视频", "参考图生视频", "首尾帧生视频", "视频编辑与人物替换", "动作迁移与舞蹈", "视频修复与扩展", "数字人与对口型"] and output != "video":
            problems.append("video category has no active video output")
        if category == "提示词辅助" and output != "text":
            problems.append("prompt category has no active text output")
        if category == "文字生图" and media["image"] + media["video"]:
            problems.append("text-to-image has visual input")
        if category == "文字生视频" and media["image"] + media["video"]:
            problems.append("text-to-video has visual input")
        if category in ["图像编辑", "参考图与套图"] and not media["image"]:
            problems.append("image reference/edit category has no image input")
        if category == "参考图生视频" and not media["image"]:
            problems.append("reference-video has no image input")
        if category == "首尾帧生视频" and media["image"] < 2:
            problems.append("first/last-frame has fewer than two image inputs")
        if category in ["视频编辑与人物替换", "动作迁移与舞蹈", "视频修复与扩展"] and not media["video"]:
            problems.append("video edit/repair category has no video input")
        if category == "数字人与对口型" and not media["audio"] and not any(
            m["kind"] == "video" and "音频" in m["label"] for m in configs[item["catalogId"]]["media"]):
            problems.append("digital human has neither audio input nor a video-with-audio input")
        rows.append({"path": item["path"], "id": item["catalogId"], "name": item["catalogName"], "category": category,
                     "media": dict(media), "output": output, "sinkTypes": sinks, "problems": problems})
    report = {"date": DAY, "checked": len(rows), "flagged": [r for r in rows if r["problems"]], "workflows": rows}
    path = ROOT / f"verification/card-category-audit-{DAY}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"checked": len(rows), "flagged": len(report["flagged"]), "issues": [(r["path"], r["problems"]) for r in report["flagged"]]}, ensure_ascii=False))
    print(path)


if __name__ == "__main__":
    main()
