"""Check the real latent size budget without uploads or sampler execution."""
import copy,hashlib,json,sys,unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from adapters import settings_for,manifest,build_graph,workflow_path


class Camera14SizeContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow=manifest('local-card-14')
        self.asset={'kind':'image','remote':'owned-original.png'}
        self.base={'seed':720014,'strength':0.4,'horizontal_angle':90,'vertical_angle':0,'zoom':5}
        self.template_path=workflow_path('local-card-14')

    def build(self,settings):
        return build_graph('local-card-14','保持主体，镜头向右','',settings,[self.asset],'cpu-contract')

    def test_source_identity_default_and_old_saved_settings_keep_1324(self):
        self.assertEqual(self.workflow['source_hash'],'2734f9df96bc0dd7ba8157e2acb935033db8a9c39d873d79c094272f72ee86f5')
        original_bytes=self.template_path.read_bytes()
        settings=settings_for(self.workflow,self.base)
        self.assertEqual(settings['output_pixels'],1324)
        default_graph=self.build(settings)
        legacy_graph=self.build(self.base)
        self.assertEqual(default_graph,legacy_graph)
        self.assertEqual(default_graph['135']['inputs']['scale_to_length'],1324)
        self.assertEqual(default_graph['83']['inputs']['width'],['135',3])
        self.assertEqual(default_graph['83']['inputs']['height'],['135',4])
        self.assertEqual(default_graph['135']['inputs']['scale_to_side'],'total_pixel(kilo pixel)')
        self.assertEqual(self.template_path.read_bytes(),original_bytes)

    def test_budget_changes_only_real_size_scalar_and_accepts_integer_boundaries(self):
        base=self.build(settings_for(self.workflow,self.base))
        for value in (512,1024,1324,1536,4096):
            with self.subTest(value=value):
                settings=settings_for(self.workflow,{**self.base,'output_pixels':value})
                graph=self.build(settings)
                self.assertEqual(graph['135']['inputs']['scale_to_length'],value)
                restored=copy.deepcopy(graph)
                restored['135']['inputs']['scale_to_length']=1324
                self.assertEqual(restored,base)
        self.assertEqual(base['63']['inputs']['image'],'owned-original.png')
        self.assertEqual(base['114']['inputs']['prompt'],'保持主体，镜头向右')
        self.assertEqual(base['95']['inputs']['seed'],720014)

    def test_rejects_invalid_budget_unknown_alias_and_drifted_latent_source(self):
        for value in (True,False,511,4097,-1,0,1024.0,1324.5,float('nan'),float('inf'),'1024',None,10**1000):
            with self.subTest(value=repr(value)),self.assertRaises(ValueError):
                settings_for(self.workflow,{**self.base,'output_pixels':value})
        with self.assertRaises(ValueError):settings_for(self.workflow,{**self.base,'scale_to_length':1024})
        template=json.loads(self.template_path.read_text(encoding='utf-8'))
        for node,key,value in [('135','scale_to_side','longest'),('135','scale_to_length',1536),
                               ('135','round_to_multiple','32'),('83','width',['135',4])]:
            changed=copy.deepcopy(template);changed[node]['inputs'][key]=value
            class FakePath:
                def read_text(self,*args,**kwargs):return json.dumps(changed)
            with self.subTest(node=node,key=key),patch('adapters.workflow_path',return_value=FakePath()),self.assertRaises(ValueError):
                self.build(settings_for(self.workflow,self.base))


if __name__=='__main__':unittest.main()
