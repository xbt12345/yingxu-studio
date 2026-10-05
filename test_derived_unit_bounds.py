"""Unit conversions stay inside real registered sockets without runtime jobs."""
import copy
import hashlib
import json
import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'scripts'))
import schema_adapters
from compile_card_workflows import bind_derived_native_bounds, CompileError
from build_workflow_interfaces import Graph
from workflow_customization import (DERIVED_NATIVE_LIMITS, frame_seconds_maximum,
                                    reviewed_derived_unit_bounds, refresh_curated_controls)


def frame_field(maximum=9007199254740991):
    return {'id':'seconds','key':'seconds','kind':'duration','type':'number',
            'value':1.5,'min':0,'step':'any','targets':[{'node':'native','input':'frames'}],
            'transform':{'operation':'frames','fps':24,'nativeBounds':{'min':0,'max':maximum}}}


def audio_field(maximum=10):
    return {'id':'end','key':'end','kind':'segment','type':'number','value':5,
            'min':0,'targets':[{'node':'native','input':'duration'}],
            'transform':{'operation':'audio-end','startId':'start','nativeBounds':{'min':0,'max':maximum}}}


class DerivedUnitBoundsTests(unittest.TestCase):
    def test_frames_zero_normal_and_representable_native_ceiling(self):
        for maximum in (9007199254740991,18446744073709551615):
            field=frame_field(maximum)
            field['max']=frame_seconds_maximum(maximum,24)
            spec={'controls':[field]}
            for seconds in (0,0.1,1.5,3.3333333333333335,field['max']):
                with self.subTest(maximum=maximum,seconds=seconds):
                    values=schema_adapters.validate_values(spec,{'seconds':seconds})
                    actual=schema_adapters._control_values(field,values['seconds'],values)[0][1]
                    self.assertEqual(actual,round(seconds*24))
                    self.assertLessEqual(actual,maximum)
            above=math.nextafter(field['max'],math.inf)
            self.assertGreater(round(above*24),maximum)
            with self.assertRaises(ValueError):schema_adapters.validate_values(spec,{'seconds':above})
            # Conversion also rejects if an older UI had no public maximum.
            field.pop('max')
            with self.assertRaises(ValueError):schema_adapters._control_values(field,above,{'seconds':above})

    def test_frames_overflow_and_invalid_metadata_fail_as_value_errors(self):
        field=frame_field()
        for seconds in (1e18,1e308,float('inf'),float('nan'),True):
            with self.subTest(seconds=seconds),self.assertRaises(ValueError):
                schema_adapters._control_values(field,seconds,{'seconds':seconds})
        for bounds in (None,{'min':0},{'min':0,'max':float('inf')},
                       {'min':11,'max':10},{'min':False,'max':10}):
            changed=copy.deepcopy(field);changed['transform']['nativeBounds']=bounds
            with self.subTest(bounds=bounds),self.assertRaises(ValueError):
                schema_adapters._control_values(changed,1,{'seconds':1})

    def test_audio_endpoint_uses_duration_limit_not_absolute_endpoint_limit(self):
        field=audio_field()
        values={'start':7,'end':17}
        self.assertEqual(schema_adapters._control_values(field,17,values)[0][1],10)
        # Real registered limit also permits a late start plus a legal duration.
        field=audio_field(1e17)
        self.assertEqual(schema_adapters._control_values(field,2e17,{'start':1e17})[0][1],1e17)
        for start,end in ((7,18),(7,7),(7,6),(0,1e18),(-1e308,1e308)):
            with self.subTest(start=start,end=end),self.assertRaises(ValueError):
                schema_adapters._control_values(audio_field(),end,{'start':start})

    def test_compiler_binds_registered_limits_and_keeps_stricter_ui_limits(self):
        field=frame_field();field['transform'].pop('nativeBounds')
        bind_derived_native_bounds(field,[['INT',{'min':0,'max':9007199254740991}]])
        self.assertEqual(field['transform']['nativeBounds'],{'min':0,'max':9007199254740991})
        self.assertLessEqual(round(field['max']*24),9007199254740991)
        field['max']=5
        bind_derived_native_bounds(field,[['INT',{'min':0,'max':9007199254740991}]])
        self.assertEqual(field['max'],5)
        audio=audio_field();audio['max']=10
        bind_derived_native_bounds(audio,[['FLOAT',{'min':0,'max':10}]])
        self.assertNotIn('max',audio)
        self.assertEqual(audio['transform']['nativeBounds'],{'min':0,'max':10})

    def test_compiler_rejects_wrong_socket_or_reviewed_range_drift(self):
        for specs in ([],[['FLOAT',{'min':0,'max':10}]],
                      [['INT',{'min':0}]], [['INT',{'min':0,'max':float('inf')}]],
                      [['INT',{'min':0,'max':9007199254740990}]]):
            with self.subTest(specs=specs),self.assertRaises(CompileError):
                bind_derived_native_bounds(frame_field(),specs)
        for fps in (0,-1,True,float('nan'),float('inf'),1e-308):
            field=frame_field();field['transform']['fps']=fps
            with self.subTest(fps=fps),self.assertRaises(CompileError):
                bind_derived_native_bounds(field,[['INT',{'min':0,'max':9007199254740991}]])

    def test_all_ten_source_contracts_match_original_bytes_and_registered_sockets(self):
        sources=json.loads((ROOT/'verification/catalog-audit.json').read_text('utf-8'))
        schemas=json.loads((ROOT/'private/research/card-20261004/object_info.json').read_text('utf-8'))
        interfaces=json.loads((ROOT/'public/workflow-interfaces.json').read_text('utf-8'))['workflows']
        for idx,(expected,nid,key,typ,minimum,maximum)in DERIVED_NATIVE_LIMITS.items():
            wid=f'local-card-{idx}'
            row=next(row for row in sources if row.get('id')==wid)
            source=Path(row['source']);before=source.read_bytes()
            self.assertEqual(hashlib.sha256(before).hexdigest(),expected)
            graph=Graph(json.loads(before.decode('utf-8-sig')))
            original=next(c for c in interfaces[wid]['controls']if(c.get('derived')or{}).get('targetId')==nid+':'+key)
            controls=[copy.deepcopy(original)]
            with self.subTest(workflow=wid):
                reviewed_derived_unit_bounds({'id':wid},controls,graph=graph,source_hash=expected)
                self.assertEqual(controls[0]['derived']['nativeBounds'],{'min':minimum,'max':maximum})
                input_spec=next(ports[key]for ports in schemas[typ]['input'].values()
                                if isinstance(ports,dict)and key in ports)
                compiled=copy.deepcopy(controls[0]);compiled['transform']=compiled.pop('derived')
                bind_derived_native_bounds(compiled,[input_spec])
                self.assertEqual(compiled['transform']['nativeBounds'],controls[0]['derived']['nativeBounds'])
                self.assertEqual(source.read_bytes(),before)
                with self.assertRaises(ValueError):
                    reviewed_derived_unit_bounds({'id':wid},[copy.deepcopy(original)],graph=graph,source_hash='0'*64)
                changed=SimpleNamespace(nodes=copy.deepcopy(graph.nodes));changed.nodes[nid]['type']='wrong-class'
                with self.assertRaises(ValueError):
                    reviewed_derived_unit_bounds({'id':wid},[copy.deepcopy(original)],graph=changed,source_hash=expected)

    def test_curated_refresh_preserves_default_and_only_refreshes_unit_contract(self):
        field=frame_field();field['derived']=field.pop('transform');field['derived']['targetId']='native:frames'
        field['value']=2.25
        reviewed={'controls':[copy.deepcopy(field)],'texts':[],'media':[]}
        reviewed['controls'][0]['derived'].pop('nativeBounds')
        fresh={'controls':[copy.deepcopy(field)]}
        fresh['controls'][0]['max']=frame_seconds_maximum(9007199254740991,24)
        refresh_curated_controls({'id':'local-card-7'},reviewed,fresh)
        self.assertEqual(reviewed['controls'][0]['value'],2.25)
        self.assertEqual(reviewed['controls'][0]['derived'],fresh['controls'][0]['derived'])
        self.assertEqual(reviewed['controls'][0]['max'],fresh['controls'][0]['max'])
        wrong=copy.deepcopy(fresh);wrong['controls'][0]['derived']['targetId']='other:frames'
        with self.assertRaises(ValueError):refresh_curated_controls({'id':'local-card-7'},reviewed,wrong)


if __name__=='__main__':unittest.main()
