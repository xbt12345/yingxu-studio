"""Prompt helper results: actual source graph and exact collection functions."""
import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import schema_adapters as runtime
from adapters import prune
from workflow_result_contracts import (
    HELPER_ID,HELPER_HASH,MODEL_OUTPUTS,finalize_prompt_helper_outputs,
    prompt_helper_output_metadata,prompt_helper_receipt_error,
)


class PromptOutputContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=copy.deepcopy(runtime.manifest(HELPER_ID))
        cls.graph=json.loads(runtime.template_path(cls.spec).read_text('utf-8'))
        tree=ast.parse((ROOT/'server.py').read_text('utf-8'))
        wanted={'output_items','_collect_outputs'}
        cls.functions=[node for node in tree.body if isinstance(node,ast.FunctionDef)and node.name in wanted]
        assert{node.name for node in cls.functions}==wanted
        cls.kinds=next(node for node in tree.body if isinstance(node,ast.Assign)and any(isinstance(target,ast.Name)and target.id=='MEDIA_KINDS'for target in node.targets))

    def scope(self,private,record):
        updates=[]
        def update(job_id,**fields):
            self.assertEqual(job_id,record['id']);record.update(copy.deepcopy(fields));updates.append(copy.deepcopy(fields));return record
        no_network=Mock(side_effect=AssertionError('No provider or GPU request permitted.'))
        scope={'Path':Path,'json':json,'time':time,'PRIVATE':private,'BASE':'https://synthetic.invalid',
               'requests':SimpleNamespace(get=no_network),'av':SimpleNamespace(error=SimpleNamespace(FFmpegError=RuntimeError)),
               'manifest':lambda _:None,'schema_adapters':SimpleNamespace(manifest=lambda _:None),
               'update':update,'prompt_helper_receipt_error':prompt_helper_receipt_error,
               'reviewed_compiler_failure':lambda *_:None,'reviewed_translation_failure':lambda *_:None,
               'probe_output_metadata':lambda *_:{},'present_outputs':lambda j,items,outputs:copy.deepcopy(outputs),
               'embed_workflow':Mock(),'public_graph':copy.deepcopy,'Image':SimpleNamespace(open=no_network),
               'repeat_output_if_needed':Mock(side_effect=AssertionError('Text collection must not repeat media.'))}
        exec(compile(ast.Module(body=[self.kinds,*self.functions],type_ignores=[]),'exact-review88-server-collection','exec'),scope)
        return scope,updates,no_network

    def receipt(self,first='First generated result',second='Second generated result'):
        outputs={'1486':{'text':['Text branch input instruction']},'1529':{'text':['Image branch input instruction']}}
        if first is not None:outputs['1515']={'text':first if isinstance(first,list)else[first]}
        if second is not None:outputs['1524']={'text':second if isinstance(second,list)else[second]}
        return{'outputs':outputs,'status':{'completed':True,'status_str':'success'}}

    def record(self):
        spec=finalize_prompt_helper_outputs(copy.deepcopy(self.spec),self.graph)
        return{'id':'review88-prompt-output-job','workflow_id':HELPER_ID,'schema_spec':spec,
               'graph':copy.deepcopy(self.graph),'status':'queued','outputs':[],'prompt_id':'owned-prompt'}

    def test_only_two_real_model_results_are_outputs_and_upstream_role_previews_stay_dependencies(self):
        original=copy.deepcopy(self.spec);original['outputs']=['1515','1486','1529','1524']
        before=copy.deepcopy(original)
        result=finalize_prompt_helper_outputs(original,self.graph)
        self.assertEqual(original,before)
        self.assertEqual(result['outputs'],list(MODEL_OUTPUTS))
        self.assertEqual(finalize_prompt_helper_outputs(result,self.graph),result)
        pruned=prune(copy.deepcopy(self.graph),result['outputs'])
        for node in('1515','1524','1486','1529','1514','1525','1496','1528'):self.assertIn(node,pruned)
        self.assertEqual(pruned['1514']['inputs']['role'],['1486',0])
        self.assertEqual(pruned['1525']['inputs']['role'],['1529',0])

    def test_source_hash_and_each_reviewed_link_drift_fail_closed(self):
        bad=copy.deepcopy(self.spec);bad['source_hash']='0'*64
        with self.assertRaises(ValueError):finalize_prompt_helper_outputs(bad,self.graph)
        for node,key in(('1515','text'),('1524','text'),('1514','role'),('1525','role'),('1486','text'),('1529','text')):
            graph=copy.deepcopy(self.graph);graph[node]['inputs'][key]=['unreviewed',0]
            with self.subTest(node=node),self.assertRaises(ValueError):finalize_prompt_helper_outputs(self.spec,graph)
        changed=copy.deepcopy(self.spec);changed['outputs']=['1486','1529']
        with self.assertRaises(ValueError):finalize_prompt_helper_outputs(changed,self.graph)

    def test_historical_input_previews_have_accurate_roles_instead_of_model_result_labels(self):
        old=copy.deepcopy(self.spec);old['outputs']=['1515','1486','1529','1524']
        labels=prompt_helper_output_metadata(old,self.graph)
        self.assertEqual(labels['1486'],{'label':'文字分支输入预览','role':'input-preview'})
        self.assertEqual(labels['1529'],{'label':'图片分支输入预览','role':'input-preview'})
        self.assertEqual(labels['1515']['role'],'result')
        self.assertEqual(labels['1524']['role'],'result')

    def test_empty_missing_or_single_empty_model_result_is_not_complete(self):
        for first,second in(('', ''),(['',' \n'],['\t']),('real text',''),('','real text'),(None,'real text'),('real text',None)):
            with self.subTest(first=first,second=second):
                self.assertIsNotNone(prompt_helper_receipt_error(self.spec,self.graph,self.receipt(first,second)))
        for bad in(None,[],{},'not a node block'):
            receipt=self.receipt();receipt['outputs']['1515']=bad
            with self.subTest(block=bad):self.assertIsNotNone(prompt_helper_receipt_error(self.spec,self.graph,receipt))

    def test_two_real_model_texts_accept_string_or_list_receipt_shapes(self):
        self.assertIsNone(prompt_helper_receipt_error(self.spec,self.graph,self.receipt()))
        receipt={'outputs':{'1515':{'string':'真实结果A'},'1524':{'strings':['','真实结果B','']}}}
        self.assertIsNone(prompt_helper_receipt_error(self.spec,self.graph,receipt))

    def test_other_workflows_are_not_filtered_or_forced_to_two_text_branches(self):
        spec={'id':'local-card-8','source_hash':HELPER_HASH,'outputs':['5']}
        self.assertIs(finalize_prompt_helper_outputs(spec,self.graph),spec)
        self.assertEqual(prompt_helper_output_metadata(spec,self.graph),{})
        self.assertIsNone(prompt_helper_receipt_error(spec,self.graph,{'outputs':{}}))

    def test_exact_server_output_items_skips_whitespace_but_preserves_mixed_text_format(self):
        with tempfile.TemporaryDirectory(prefix='result-contract-')as temp:
            scope,_,network=self.scope(Path(temp),self.record())
            all_empty={'outputs':{'1515':{'text':['',' \t\n']}}}
            self.assertEqual(scope['output_items'](all_empty,'text',['1515']),[])
            mixed={'outputs':{'1515':{'text':['',' First line ','','Second line','']}}}
            results=scope['output_items'](mixed,'text',['1515'])
            self.assertEqual(len(results),1)
            self.assertEqual(results[0]['text'],'\n First line \n\nSecond line\n')
            self.assertEqual(results[0]['output_node'],'1515')
            network.assert_not_called()

    def test_exact_collection_marks_empty_response_failed_and_keeps_receipt_without_outputs(self):
        for first,second in(('', ''),('real text',''),(None,'real text')):
            with self.subTest(first=first,second=second),tempfile.TemporaryDirectory(prefix='result-contract-')as temp:
                private=Path(temp);(private/'outputs').mkdir();(private/'receipts').mkdir()
                record=self.record();scope,updates,network=self.scope(private,record);receipt=self.receipt(first,second)
                scope['_collect_outputs'](record,receipt)
                self.assertEqual(record['status'],'failed')
                self.assertEqual(record['output_failure_code'],'empty_text_response')
                self.assertFalse(any(update.get('status')=='done'for update in updates))
                self.assertEqual(record['outputs'],[])
                saved=json.loads((private/'receipts'/f"{record['id']}.json").read_text('utf-8'))
                self.assertEqual(saved['outputs'],receipt['outputs'])
                network.assert_not_called()

    def test_exact_collection_accepts_two_results_and_never_saves_input_previews_as_new_works(self):
        with tempfile.TemporaryDirectory(prefix='result-contract-')as temp:
            private=Path(temp);(private/'outputs').mkdir();(private/'receipts').mkdir()
            record=self.record();scope,updates,network=self.scope(private,record)
            receipt=self.receipt(['','A\nline',''],['B text'])
            scope['_collect_outputs'](record,receipt)
            self.assertEqual(record['status'],'done')
            self.assertEqual(len(record['outputs']),2)
            files=sorted((private/'outputs'/record['id']).glob('*.txt'))
            self.assertEqual([path.read_text('utf-8')for path in files],['\nA\nline\n','B text'])
            self.assertEqual([output['text']for output in record['outputs']],['\nA\nline\n','B text'])
            self.assertNotIn('Text branch input instruction',''.join(path.read_text('utf-8')for path in files))
            network.assert_not_called()

    def test_current_compiled_contract_is_pinned_to_the_intended_model_outputs(self):
        self.assertEqual(self.spec['id'],HELPER_ID)
        self.assertEqual(self.spec['source_hash'],HELPER_HASH)
        self.assertEqual(self.spec['outputs'],list(MODEL_OUTPUTS))
        self.assertEqual(set(finalize_prompt_helper_outputs(self.spec,self.graph)['outputs']),set(MODEL_OUTPUTS))

if __name__=='__main__':unittest.main()
