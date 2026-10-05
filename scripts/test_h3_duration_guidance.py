"""Verify source/FPS guards and preserve the seconds controls' binding contract."""
import copy
import hashlib
import json
import unittest
from pathlib import Path
from build_workflow_interfaces import Graph
from workflow_customization import reviewed_h3_duration_guidance,refresh_curated_controls,H3_DURATION_SOURCES,H3_DURATION_RECIPE

ROOT=Path(__file__).resolve().parents[1]

class H3DurationGuidance(unittest.TestCase):
    def setUp(self):
        self.audit={row['id']:row for row in json.loads((ROOT/'verification/catalog-audit.json').read_text('utf-8'))if'id'in row}
        self.forms=json.loads((ROOT/'public/workflow-interfaces.json').read_text('utf-8'))['workflows']
    def source(self,card):
        raw=Path(self.audit[f'local-card-{card}']['source']).read_bytes()
        return Graph(json.loads(raw.decode('utf-8-sig'))),hashlib.sha256(raw).hexdigest()
    def test_annotates_verified_source_without_changing_parameter_or_binding(self):
        for card,(_,control_id,*_)in H3_DURATION_SOURCES.items():
            with self.subTest(card=card):
                graph,source_hash=self.source(card)
                fields=copy.deepcopy(self.forms[f'local-card-{card}']['controls'])
                before=copy.deepcopy(fields)
                result=reviewed_h3_duration_guidance({'id':f'local-card-{card}'},graph,fields,source_hash=source_hash)
                field=next(f for f in result if f['id']==control_id)
                self.assertEqual(field['effectiveDuration'],H3_DURATION_RECIPE)
                for old,current in zip(before,result):
                    self.assertEqual({k:v for k,v in old.items()if k not in('help','effectiveDuration')},
                                     {k:v for k,v in current.items()if k not in('help','effectiveDuration')})
                derived={'sourceHash':source_hash,'controls':result,'texts':[],'media':[]}
                curated={'controls':before,'texts':[],'media':[]}
                refreshed=refresh_curated_controls({'id':f'local-card-{card}','category':'首尾帧生视频'},curated,derived)
                refreshed_field=next(f for f in refreshed['controls']if f['id']==control_id)
                self.assertEqual(refreshed_field['effectiveDuration'],H3_DURATION_RECIPE)
                old=next(f for f in before if f['id']==control_id)
                for key in ('value','targets','type','min','step'):self.assertEqual(refreshed_field.get(key),old.get(key))
    def test_rejects_unreviewed_hash_expression_fps_and_consumer_port(self):
        for card,(_,control_id,relay,math,consumer,save)in H3_DURATION_SOURCES.items():
            graph,source_hash=self.source(card)
            fields=copy.deepcopy(self.forms[f'local-card-{card}']['controls'])
            for field in fields:field.pop('effectiveDuration',None)
            self.assertFalse(any(f.get('effectiveDuration')for f in reviewed_h3_duration_guidance({'id':f'local-card-{card}'},graph,copy.deepcopy(fields),source_hash='changed')))
            changed=copy.deepcopy(graph);changed.nodes[math]['widgets_values_named']={'expression':'a*24'}
            self.assertFalse(any(f.get('effectiveDuration')for f in reviewed_h3_duration_guidance({'id':f'local-card-{card}'},changed,copy.deepcopy(fields),source_hash=source_hash)))
            changed=copy.deepcopy(graph);changed.nodes[save]['widgets_values_named']={'fps':16}
            self.assertFalse(any(f.get('effectiveDuration')for f in reviewed_h3_duration_guidance({'id':f'local-card-{card}'},changed,copy.deepcopy(fields),source_hash=source_hash)))
            changed=copy.deepcopy(graph);changed.out[math]=[(dst,slot,0)if dst==consumer else(dst,slot,out)for dst,slot,out in changed.out[math]]
            self.assertFalse(any(f.get('effectiveDuration')for f in reviewed_h3_duration_guidance({'id':f'local-card-{card}'},changed,copy.deepcopy(fields),source_hash=source_hash)))
    def test_video_repair_has_source_length_help_without_false_exact_estimate(self):
        graph,source_hash=self.source(60);fields=copy.deepcopy(self.forms['local-card-60']['controls']);before=copy.deepcopy(fields)
        result=reviewed_h3_duration_guidance({'id':'local-card-60'},graph,fields,source_hash=source_hash)
        self.assertIn('原片长度',next(f for f in result if f['id']=='366:value')['help'])
        self.assertFalse(any(f.get('effectiveDuration')for f in result))
        for a,b in zip(before,result):self.assertEqual({k:v for k,v in a.items()if k!='help'},{k:v for k,v in b.items()if k!='help'})

if __name__=='__main__':unittest.main()
