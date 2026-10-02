"""Serve the official ComfyUI frontend for local structural review, without an executor."""
import json
import mimetypes
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'private/runtime'))
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from organize_representative_workflows import ROOT, OUT, strip_secrets
from build_workflow_interfaces import widget_bindings

STATIC = ROOT / 'private/review-runtime/extracted/comfyui_frontend_package/static'
UI = ROOT / 'private/review-runtime/ui'
INDEX = json.loads((OUT / '审查索引.json').read_text(encoding='utf-8'))
GRAPHS = {str(e['number']): json.loads((OUT / e['file']).read_text(encoding='utf-8')) for e in INDEX}
USERDATA = {}
RATIOS = sorted({value for config in json.loads((ROOT / 'public/workflow-interfaces.json').read_text(encoding='utf-8'))['workflows'].values() for c in config['controls'] if c['kind'] == 'ratio' for value in c.get('options', [])})
SETTINGS = {'Comfy.Locale': 'zh', 'Comfy.TutorialCompleted': True, 'Comfy.UseNewMenu': 'Top', 'Comfy.Workflow.ShowMissingModelsWarning': False, 'Comfy.Node.AutoSnapToGrid': False, 'Comfy.UseNewRenderer': False, 'Comfy.Workflow.WorkflowTabsPosition': 'Topbar', 'Comfy.ColorPalette': 'dark', 'Comfy.Onboarding.Completed': True}


def definitions():
    bytype = {}
    for graph in GRAPHS.values():
        allnodes = graph['nodes'] + [n for d in graph.get('definitions', {}).get('subgraphs', []) for n in d['nodes']]
        ids = {d['id'] for d in graph.get('definitions', {}).get('subgraphs', [])}
        for n in allnodes:
            if n['type'] in ids or n['type'] == 'PrimitiveNode':
                continue
            bytype.setdefault(n['type'], []).append(n)
    result = {}
    for typ, ns in bytype.items():
        node = max(ns, key=lambda n: len(n.get('inputs', [])))
        req = {}
        for p in node.get('inputs', []):
            key, itype = p['name'], p.get('type', '*')
            if p.get('widget'):
                vals = [widget_bindings(n)[key][0] for n in ns if key in widget_bindings(n)]
                default = vals[0] if vals else ''
                if itype == 'COMBO' or isinstance(itype, list):
                    opts = list(dict.fromkeys(str(v) for v in vals)) or ['default']
                    if typ == 'ResolutionSelector' and key == 'aspect_ratio':
                        opts = list(dict.fromkeys(RATIOS + opts))
                    req[key] = [opts, {'default': str(default)}]
                elif itype in ['INT', 'FLOAT']:
                    controls = any(isinstance(n.get('widgets_values'), list) and any(v in ['fixed', 'randomize', 'increment', 'decrement'] for v in n['widgets_values'] if isinstance(v, str)) for n in ns) and (key in ['seed', 'noise_seed'] or typ == 'PrimitiveInt' and key == 'value')
                    req[key] = [itype, {'default': default, 'min': -9007199254740991, 'max': 9007199254740991, 'control_after_generate': controls}]
                elif itype == 'BOOLEAN':
                    req[key] = ['BOOLEAN', {'default': bool(default)}]
                else:
                    req[key] = ['STRING', {'default': str(default), 'multiline': bool(len(str(default)) > 100 or key in ['text', 'prompt', 'negative_prompt', 'value']), 'dynamicPrompts': False}]
            else:
                req[key] = [itype, {'forceInput': True}]
        # Most saved graphs include a named widget map; cover widgets omitted from sockets.
        for n in ns:
            for key, (value, _) in widget_bindings(n).items():
                if key in req or key in ['control_after_generate', 'videopreview', 'choose video to upload']:
                    continue
                itype = 'BOOLEAN' if isinstance(value, bool) else 'INT' if isinstance(value, int) else 'FLOAT' if isinstance(value, float) else 'STRING'
                req[key] = [itype, {'default': value, 'multiline': isinstance(value, str) and len(value) > 100}]
        if not req and typ in ['MarkdownNote', 'Note', 'Label (rgthree)']:
            req['text'] = ['STRING', {'default': '', 'multiline': True}]
        if typ == 'Seed (rgthree)':
            req = {'seed': ['INT', {'default': 0, 'min': 0, 'max': 9007199254740991}], 'randomize': ['STRING', {'default': ''}], 'last_seed': ['STRING', {'default': ''}], 'state': ['STRING', {'default': ''}]}
        outputs = max(ns, key=lambda n: len(n.get('outputs', []))).get('outputs', [])
        result[typ] = {'input': {'required': req}, 'input_order': {'required': list(req)}, 'output': [p.get('type', '*') for p in outputs], 'output_name': [p.get('name', p.get('type', '*')) for p in outputs], 'output_is_list': [False] * len(outputs), 'name': typ, 'display_name': typ, 'description': '本地结构审查用节点定义；无模型执行后端。', 'category': '本地工作流审查', 'output_node': any(x in typ for x in ['Save', 'Preview', 'ShowText', 'showAnything']), 'python_module': 'owner_review'}
    return result


NODEINFO = definitions()
app = FastAPI()


@app.websocket('/ws')
async def ws(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({'type': 'status', 'data': {'status': {'exec_info': {'queue_remaining': 0}}, 'sid': 'owner-local-review'}})
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass


@app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'HEAD'])
async def route(path: str, request: Request):
    api = path.removeprefix('api/')
    if api.startswith('review-original/'):
        key = str(int(api.split('/')[1].split('.')[0]))
        e = next(e for e in INDEX if str(e['number']) == key)
        return JSONResponse(strip_secrets(json.loads((ROOT / e['source']).read_text(encoding='utf-8-sig'))))
    if api.startswith('review-data/'):
        part = api.split('/', 1)[1]
        if part == 'index':
            return INDEX
        if part.endswith('.json'):
            key = str(int(part.split('.')[0]))
            if key in GRAPHS:
                return JSONResponse(GRAPHS[key])
    if api.startswith('download/'):
        key = str(int(api.split('/')[1]))
        e = next(e for e in INDEX if str(e['number']) == key)
        return FileResponse(OUT / e['file'], filename=e['file'], media_type='application/json')
    if api == 'download-all':
        return FileResponse(ROOT / '代表工作流-ComfyUI审查版.zip', filename='代表工作流-ComfyUI审查版.zip')
    if api == 'object_info':
        return NODEINFO
    if api == 'extensions':
        return ['/extensions/owner-review.js']
    if api == 'features':
        return {'supports_preview_metadata': False, 'supports_manager_v4': False, 'supports_user_data_metadata': True}
    if api == 'users':
        return {'storage': 'server', 'migrated': True, 'users': {'default': 'Owner Review'}}
    if api == 'settings':
        if request.method != 'GET':
            SETTINGS.update(await request.json())
        return SETTINGS
    if api.startswith('settings/'):
        if request.method != 'GET':
            SETTINGS[api.split('/', 1)[1]] = await request.json()
        return {}
    if api == 'userdata':
        return []
    if api.startswith('userdata/'):
        name = api.split('/', 1)[1]
        if request.method in ['POST', 'PUT']:
            USERDATA[name] = await request.body()
            return {}
        if name in USERDATA:
            return Response(USERDATA[name], media_type='application/json')
        if name.endswith('.css'):
            return Response('', media_type='text/css')
        return Response(status_code=404)
    if api == 'queue':
        return {'queue_running': [], 'queue_pending': []}
    if api == 'prompt':
        if request.method == 'GET':
            return {'exec_info': {'queue_remaining': 0}}
        return JSONResponse({'error': '仅用于工作流结构审查，不执行模型。'}, status_code=403)
    if api == 'history':
        return {}
    if api == 'system_stats':
        return {'system': {'os': 'win32', 'python_version': 'structural-review', 'embedded_python': False, 'comfyui_version': 'review-only', 'required_frontend_version': '1.53.6', 'installed_templates_version': '0.0.0', 'required_templates_version': '0.0.0', 'pytorch_version': 'not-installed', 'argv': [], 'ram_total': 0, 'ram_free': 0}, 'devices': []}
    if api in ['models', 'embeddings', 'workflow_templates', 'i18n', 'experiment'] or api.startswith('models/'):
        return [] if api in ['models', 'embeddings'] or api.startswith('models/') else {}
    if path == 'review':
        return FileResponse(UI / 'review.html', media_type='text/html')
    if path == 'extensions/owner-review.js':
        return FileResponse(UI / 'owner-review.js', media_type='text/javascript')
    if path in ['user.css', 'api/userdata/user.css']:
        return Response('', media_type='text/css')
    candidate = (STATIC / (path or 'index.html')).resolve()
    if candidate.is_relative_to(STATIC.resolve()) and candidate.is_file():
        return FileResponse(candidate, media_type=mimetypes.guess_type(str(candidate))[0])
    return Response(status_code=404)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8771)
