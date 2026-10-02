"""Submit neutral review fixtures through the same local endpoint as the website."""
import json
import time
import requests
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8770'
cfg=json.loads((ROOT/'public/workflow-interfaces.json').read_text('utf-8'))['workflows']
assets={}
for name in ('blue-vase.png','amber-vase.png','blue-mask.png'):
    with (ROOT/'private/second-round-fixtures'/name).open('rb') as image:
        response=requests.post(BASE+'/api/assets',files={'file':(name,image,'image/png')},timeout=180)
    response.raise_for_status();assets[name]=response.json()['id']
specs=[('local-card-16','text',{}),('local-card-16','marked',{}),('local-card-11','native-size',{'resolution':'1024x1024'}),('local-card-17','shared-prompt',{}),('local-card-18','shared-prompt-negative',{})]
results=[]
for wid,case,settings in specs:
    source='blue-mask.png' if case=='marked' else 'blue-vase.png'
    body=dict(workflow_id=wid,source_hash=cfg[wid]['sourceHash'],prompt='Keep the vase and composition in @图片1. Change the vase color to amber, matching @图片2. Keep the wooden table and plain background.',negative='text, watermark' if wid in ('local-card-11','local-card-18') else '',settings={'seed':424242,**settings},asset_ids=[assets[source],assets['amber-vase.png']],token='review54-'+wid+'-'+case)
    response=requests.post(BASE+'/api/jobs',json=body,timeout=180);response.raise_for_status();job=response.json()
    results.append({'workflow':wid,'case':case,'job_id':job['id'],'status':job['status']})
    print(json.dumps(results[-1]),flush=True)
dest=ROOT/'private/review54-results.json';dest.write_text(json.dumps(results,indent=2),'utf-8')
pending=True
while pending:
    pending=False
    for item in results:
        if item['status'] in ('done','failed','cancelled','abandoned'):continue
        job=requests.get(BASE+'/api/jobs/'+item['job_id'],timeout=30).json()
        if job['status']!=item['status']:
            item.update(status=job['status'],error=job.get('error'),outputs=job.get('outputs',[]));print(json.dumps(item),flush=True)
        pending |= item['status'] not in ('done','failed','cancelled','abandoned')
    dest.write_text(json.dumps(results,indent=2),'utf-8')
    if pending:time.sleep(10)
