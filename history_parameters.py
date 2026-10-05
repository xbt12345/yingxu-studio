"""Project reviewed executed seeds into old receipts without exposing graphs."""
from functools import lru_cache
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
JS_INTEGER_MAX=9007199254740991
LEGACY_STAGE_SEEDS={
    'local-card-85':('dd292b96f8e6f02fab2ccdb63b9e29b5e95976fbd26b71a8415fc139da571ef1',
        '63:seed','63','seed','KSampler','58','seed','Seed (rgthree)',
        (('56','KSampler','seed',['58',0]),('55','LatentUpscaleBy','samples',['56',0]),
         ('63','KSampler','latent_image',['55',0]))),
    'local-card-107':('396a12617c7e9e3fafc8aba2dee7fadb5f9f2d3fc8cdc20498b1ebfaa8ea67b2',
        '80:seed','80','seed','SeedVR2VideoUpscaler','3','seed','KSampler',
        (('8','VAEDecode','samples',['3',0]),('85','easy cleanGpuUsed','anything',['8',0]),
         ('80','SeedVR2VideoUpscaler','image',['85',0]))),
}


@lru_cache(maxsize=2)
def _interfaces(stamp,size):
    return json.loads((ROOT/'public/workflow-interfaces.json').read_text('utf-8'))['workflows']


def current_interface(workflow_id):
    path=ROOT/'public/workflow-interfaces.json'
    try:
        stat=path.stat()
        return _interfaces(stat.st_mtime_ns,stat.st_size).get(workflow_id,{})
    except (OSError,ValueError,KeyError):
        return {}


def _integer(value,field):
    return (type(value)is int and 0<=value<=min(field.get('max',JS_INTEGER_MAX),JS_INTEGER_MAX)
            and value>=field.get('min',0))


def history_seed_values(job,interface=None):
    """Only missing form seed IDs, same source or two bounded legacy contracts.

    Legacy tickets predate source hashes. Those two cases require the pinned
    current source, exact stage topology and primary seed/settings agreement;
    they are compatibility checks, not a claim of an archived source hash.
    """
    wid=job.get('workflow_id');cfg=interface if interface is not None else current_interface(wid)
    graph=job.get('graph')or{};saved=job.get('catalog_values')or{}
    old=job.get('schema_spec')or{};result={}
    same_source=(old.get('id')==wid and old.get('source_hash')==cfg.get('sourceHash')
                 and isinstance(cfg.get('sourceHash'),str) and len(cfg['sourceHash'])==64)
    if same_source:
        for field in cfg.get('controls',[]):
            if field.get('kind')!='seed' or field['id']in saved:continue
            targets=field.get('targets',[]);values=[]
            if not targets:continue
            for target in targets:
                port=target.get('input');node=graph.get(str(target.get('node')), {})
                if port not in ('seed','noise_seed','sampling_mode.seed')or node.get('class_type')!=field.get('node'):
                    break
                value=node.get('inputs',{}).get(port)
                if not _integer(value,field):break
                values.append(value)
            if len(values)==len(targets)and len(set(values))==1:result[field['id']]=values[0]
    elif not old and wid in LEGACY_STAGE_SEEDS:
        sha,fid,nid,key,typ,primary,pkey,ptype,edges=LEGACY_STAGE_SEEDS[wid]
        field=next((f for f in cfg.get('controls',[])if f.get('id')==fid and f.get('kind')=='seed'),None)
        if cfg.get('sourceHash')!=sha or not field or fid in saved:return {}
        node=graph.get(nid,{})
        primary_node=graph.get(primary,{})
        primary_value=primary_node.get('inputs',{}).get(pkey)
        if (node.get('class_type')!=typ or primary_node.get('class_type')!=ptype
            or type(primary_value)is not int or primary_value!=job.get('settings',{}).get('seed')
            or field.get('targets')!=[{'node':nid,'input':key}]):return {}
        for dst,kind,port,value in edges:
            actual=graph.get(dst,{})
            if actual.get('class_type')!=kind or actual.get('inputs',{}).get(port)!=value:return {}
        value=node.get('inputs',{}).get(key)
        if _integer(value,field):result[fid]=value
    return result
