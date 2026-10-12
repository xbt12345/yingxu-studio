"""Actual CPU graphs for optional locator text: empty preserves source targets."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import schema_adapters as runtime
from scripts.review87_video_controls import SOURCE_HASHES

LOCATORS={
    'local-card-24': ('3724:value','3724','human','3720'),
    'local-card-25': ('623:value','623','human','619'),
    'local-card-27': ('753:value','753','cloths','749'),
    'local-card-28': ('443:value','443','human','433'),
    'local-card-116': ('753:value','753','cloths','749'),
}

class LocatorTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.interfaces=json.loads((ROOT/'public/workflow-interfaces.json').read_text('utf-8'))['workflows']

    def spec(self,wid):
        spec=copy.deepcopy(runtime.manifest(wid))
        self.assertEqual(spec['source_hash'],SOURCE_HASHES[wid])
        return spec

    def build(self,spec,text):
        field=LOCATORS[spec['id']][0]
        records={slot['id']:{'kind':slot['kind'],'remote':'owned-review88.'+{'image':'png','video':'mp4','audio':'wav'}[slot['kind']]}for slot in spec['media']}
        seeds={f['id']:0 for f in spec['controls']if f.get('kind')=='seed'}
        return runtime.build(spec,seeds,{field:text},records,{},'offline-locator-review',prompt='Preserve the original motion and background.')[0]

    def test_ui_and_compiler_preserve_optionality_and_default_identity(self):
        for wid,(field,node,default,consumer)in LOCATORS.items():
            with self.subTest(wid=wid):
                spec=self.spec(wid)
                control=next(t for t in spec['texts']if t['id']==field)
                ui=next(t for t in self.interfaces[wid]['texts']if t['id']==field)
                self.assertTrue(control.get('preserveWhenEmpty'))
                self.assertTrue(ui.get('preserveWhenEmpty'))
                self.assertFalse(control.get('required',False))
                self.assertEqual(control['targets'],[{'node':node,'input':'value'}])
                self.assertEqual(control.get('default',''),'')
                template=json.loads(runtime.template_path(spec).read_text('utf-8'))
                self.assertEqual(template[node]['inputs']['value'],default)
                self.assertEqual(template[consumer]['inputs']['prompt'],[node,0])

    def test_empty_string_keeps_authored_human_or_cloths(self):
        for wid,(_,node,default,consumer)in LOCATORS.items():
            with self.subTest(wid=wid):
                graph=self.build(self.spec(wid),'')
                self.assertEqual(graph[node]['inputs']['value'],default)
                self.assertEqual(graph[consumer]['inputs']['prompt'],[node,0])

    def test_whitespace_also_keeps_the_authored_locator_word(self):
        for wid,(_,node,default,_)in LOCATORS.items():
            with self.subTest(wid=wid):self.assertEqual(self.build(self.spec(wid),' \t ')[node]['inputs']['value'],default)

    def test_custom_keyword_changes_the_real_sam_target(self):
        for wid,(_,node,_,consumer)in LOCATORS.items():
            with self.subTest(wid=wid):
                graph=self.build(self.spec(wid),'person wearing a red shirt')
                self.assertEqual(graph[node]['inputs']['value'],'person wearing a red shirt')
                self.assertEqual(graph[consumer]['inputs']['prompt'],[node,0])

    def test_auxiliary_target_does_not_replace_positive_generation_description(self):
        for wid,(locator,_,_,_)in LOCATORS.items():
            with self.subTest(wid=wid):
                spec=self.spec(wid);graph=self.build(spec,'red jacket')
                primary=next(t for t in spec['texts']if t.get('role')=='prompt'and t['id']!=locator)
                for target in primary['targets']:
                    self.assertEqual(graph[target['node']]['inputs'][target['input']],'Preserve the original motion and background.')

    def test_source_drift_rejects_instead_of_restoring_words_to_an_unknown_graph(self):
        spec=self.spec('local-card-28');spec['source_hash']='0'*64
        with self.assertRaises(ValueError):self.build(spec,'')

    def test_cpu_projection_keeps_shipped_template_bytes(self):
        for wid in LOCATORS:
            spec=self.spec(wid);public=runtime.template_path(spec)
            before_public=public.read_bytes()
            self.build(spec,'');self.build(spec,'blue sweater')
            self.assertEqual(public.read_bytes(),before_public)

if __name__=='__main__':unittest.main()
