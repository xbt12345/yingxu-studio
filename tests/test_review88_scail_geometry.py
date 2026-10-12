"""Source-pinned Scail preflight; no inference, template rewrites or uploads."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import pytest
import schema_adapters as runtime
from scripts.review86_scail_controls import CONTRACTS,derive_scail_processing_geometry


def spec(wid):
    return deepcopy(runtime.manifest(wid))


@pytest.mark.parametrize('wid',sorted(CONTRACTS))
@pytest.mark.parametrize('source,longest,layer,target',[
    ({'width':1920,'height':1080},1536,(1536,864),(1536,864)),
    ({'width':848,'height':480},1536,(1536,880),(1536,864)),
    ({'width':480,'height':848},1536,(880,1536),(864,1536)),
    ({'width':638,'height':360},1024,(1024,576),(1024,576)),
    ({'width':1920,'height':1080},1024,(1024,576),(1024,576)),
])
def test_native_floor32_accepts_authored_round16_instead_of_changing_it(wid,source,longest,layer,target):
    c=CONTRACTS[wid]
    result=derive_scail_processing_geometry(spec(wid),{c['length']+':value':longest},source)
    assert result['layerTarget']==dict(zip(('width','height'),layer))
    assert result['target']==dict(zip(('width','height'),target))
    assert result['defaultChainPreserved'] is True
    assert result['layerMultiple']==16
    assert result['mediaSlotId']==c['loader']


@pytest.mark.parametrize('wid',sorted(CONTRACTS))
@pytest.mark.parametrize('source,longest',[
    ({'width':2000,'height':16},1024),
    ({'width':16,'height':2000},1024),
    ({'width':3,'height':64},1024),
    ({'width':64,'height':64},4),
    ({'width':1920,'height':1080},8192),
    ({'width':64,'height':64},100000000),
])
def test_zero_or_out_of_contract_effective_size_rejects_before_upload(wid,source,longest):
    with pytest.raises(ValueError,match='过小|小于64|超过8096'):
        derive_scail_processing_geometry(spec(wid),{CONTRACTS[wid]['length']+':value':longest},source)


@pytest.mark.parametrize('wid',sorted(CONTRACTS))
@pytest.mark.parametrize('width,height',[(64,64),(512,512),(640,480),(8096,8096)])
def test_custom_pair_preserves_existing_native32_contract_even_when_source_is_skinny(wid,width,height):
    c=CONTRACTS[wid];values={c['embeds']+':width':width,c['embeds']+':height':height}
    result=derive_scail_processing_geometry(spec(wid),values,{'width':2000,'height':16})
    assert result['target']=={'width':width,'height':height}
    assert result['layerTarget']==result['target']
    assert result['custom'] is True
    assert result['defaultChainPreserved'] is False


@pytest.mark.parametrize('wid',sorted(CONTRACTS))
@pytest.mark.parametrize('width,height',[(0,640),(640,0),(32,32),(656,480),(8097,8096),(-1,0),(True,64),(10**1000,64)])
def test_custom_pair_cannot_bypass_existing_validation(wid,width,height):
    c=CONTRACTS[wid]
    with pytest.raises(ValueError):
        derive_scail_processing_geometry(spec(wid),{c['embeds']+':width':width,c['embeds']+':height':height}, {'width':1920,'height':1080})


@pytest.mark.parametrize('source',[None,[],{}, {'width':True,'height':64}, {'width':64.0,'height':64}, {'width':0,'height':64}, {'width':64,'height':-1}])
def test_decoded_source_dimensions_are_required(source):
    with pytest.raises(ValueError):
        derive_scail_processing_geometry(spec('local-card-23'),{},source)


@pytest.mark.parametrize('longest',[float('nan'),float('inf'),True,'1536',1.5,10**1000])
def test_invalid_or_huge_longest_returns_valueerror_without_math_overflow(longest):
    with pytest.raises(ValueError):
        derive_scail_processing_geometry(spec('local-card-23'),{'571:value':longest},{'width':1920,'height':1080})


@pytest.mark.parametrize('what',['source','metadata','loader','link'])
def test_source_identity_and_exact_dimension_path_fail_closed(monkeypatch,what):
    s=spec('local-card-23')
    if what=='source':s['source_hash']='0'*64
    elif what=='metadata':s['scail_dimensions']['multiple']=16
    else:
        template=json.loads(runtime.template_path(s).read_text('utf-8'))
        if what=='loader':template['552']['inputs']['format']='LTXV'
        else:template['560']['inputs']['image']=['other',0]
        monkeypatch.setattr('scripts.review86_scail_controls._template',lambda *a,**k:template)
    with pytest.raises(ValueError):
        derive_scail_processing_geometry(s,{}, {'width':1920,'height':1080})


@pytest.mark.parametrize('wid',sorted(CONTRACTS))
def test_preflight_never_mutates_values_spec_graph_or_api_bytes(wid):
    s=spec(wid);values={CONTRACTS[wid]['length']+':value':1536}
    before_spec,before_values=deepcopy(s),deepcopy(values)
    path=runtime.template_path(s);before=hashlib.sha256(path.read_bytes()).hexdigest()
    derive_scail_processing_geometry(s,values,{'width':848,'height':480})
    assert s==before_spec and values==before_values
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
