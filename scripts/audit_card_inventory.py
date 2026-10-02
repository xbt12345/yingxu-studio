"""Compare every live ComfyUI workflow with the local catalog and graph snapshot."""
import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = os.environ.get('CHENYU_CARD_URL', '')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args()
    if not args.base_url:parser.error('Set CHENYU_CARD_URL or pass --base-url')
    base = args.base_url.rstrip("/")
    response = requests.get(base + "/api/userdata", params={"dir": "workflows", "recurse": "true"}, timeout=20)
    response.raise_for_status()
    remote = response.json()
    if not isinstance(remote, list):
        raise ValueError("Platform did not return a workflow filename list")
    snapshot = json.loads((ROOT / "private/research/card-20260923/files.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "public/local-catalog.json").read_text(encoding="utf-8"))["workflows"]
    alias_to_entry = {alias: w for w in catalog for alias in w["aliases"]}
    index_by_name = {name: index for index, name in enumerate(snapshot)}

    def check(name):
        url = base + "/api/userdata/" + quote("workflows/" + name, safe="")
        result = requests.get(url, timeout=40)
        result.raise_for_status()
        body = result.content
        source = ROOT / f"private/research/card-20260923/graph-{index_by_name[name]:03}.json" if name in index_by_name else None
        parsed = json.loads(body)
        valid = isinstance(parsed, dict) and bool(parsed.get("nodes"))
        entry = alias_to_entry.get(name)
        return {
            "path": name,
            "folder": name.split("/", 1)[0] if "/" in name else "(root)",
            "validWorkflow": valid,
            "nodes": len(parsed.get("nodes", [])) if isinstance(parsed, dict) else 0,
            "remoteSha256": hashlib.sha256(body).hexdigest(),
            "snapshotSha256": hashlib.sha256(source.read_bytes()).hexdigest() if source and source.is_file() else None,
            "catalogId": entry["id"] if entry else None,
            "catalogName": entry["name"] if entry else None,
            "category": entry["category"] if entry else None,
        }

    results = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(check, name): name for name in remote}
        for future in as_completed(futures):
            name = futures[future]
            results[name] = future.result()
    rows = [results[name] for name in remote]
    report = {
        "date": str(date.today()),
        "platform": base,
        "remoteFiles": len(remote),
        "validWorkflows": sum(r["validWorkflow"] for r in rows),
        "catalogCovered": sum(r["validWorkflow"] and bool(r["catalogId"]) for r in rows),
        "snapshotMatches": sum(r["remoteSha256"] == r["snapshotSha256"] for r in rows),
        "uncoveredValid": [r["path"] for r in rows if r["validWorkflow"] and not r["catalogId"]],
        "invalidFiles": [r["path"] for r in rows if not r["validWorkflow"]],
        "changedFiles": [r["path"] for r in rows if r["remoteSha256"] != r["snapshotSha256"]],
        "workflows": rows,
    }
    target = ROOT / "verification" / f"card-inventory-{date.today()}.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "workflows"}, ensure_ascii=False))
    print(target)


if __name__ == "__main__":
    main()
