"""Find lost acknowledgements through read-only, bounded history scans."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class UnknownReconciliation(unittest.TestCase):
    def run_reconciliation(self,pages):
        node=next(n for n in ast.parse(Path(__file__).with_name('server.py').read_text('utf-8')).body
                  if isinstance(n,ast.FunctionDef) and n.name=='reconcile_unknown')
        get=Mock(side_effect=lambda url,params,timeout:SimpleNamespace(raise_for_status=lambda:None,json=lambda:pages(params)))
        post=Mock(side_effect=AssertionError('Reconciliation must not submit or cancel'))
        update=Mock(side_effect=lambda id,**values:{'id':id,**values})
        scope={'requests':SimpleNamespace(get=get,post=post),'BASE':'https://synthetic.invalid','update':update}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'exact-reconcile','exec'),scope)
        record={'id':'lost-job','status':'unknown','billing_state':'held'}
        result=scope['reconcile_unknown'](record,{'queue_running':[],'queue_pending':[]})
        post.assert_not_called()
        return result,get,update,record

    @staticmethod
    def page(prefix,count=100):
        return {f'{prefix}-{i}':{'prompt':[0,'id',{},{}]} for i in range(count)}

    def test_recovers_an_older_page_without_resubmission(self):
        def pages(params):
            offset=params.get('offset')
            if offset==100:return {'original-remote':{'prompt':[0,'id',{}, {'yingxu_job_id':'lost-job'}]}}
            return self.page('recent' if offset is None else 'old')
        result,get,update,record=self.run_reconciliation(pages)
        self.assertEqual(result['prompt_id'],'original-remote')
        self.assertEqual([c.kwargs['params'].get('offset') for c in get.call_args_list],[None,0,100])
        self.assertEqual(update.call_count,1)

    def test_ignored_offset_stops_on_repeated_page(self):
        result,get,update,record=self.run_reconciliation(lambda params:self.page('repeated'))
        self.assertIs(result,record)
        self.assertEqual(get.call_count,2)
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(result['billing_state'],'held')
        update.assert_not_called()

    def test_unknown_scan_has_a_finite_bound(self):
        result,get,update,record=self.run_reconciliation(lambda params:self.page(str(params.get('offset'))))
        self.assertIs(result,record)
        self.assertEqual(get.call_count,11)
        self.assertEqual(get.call_args_list[-1].kwargs['params']['offset'],900)
        update.assert_not_called()

    def test_empty_history_keeps_unknown_and_held(self):
        result,get,update,record=self.run_reconciliation(lambda params:{})
        self.assertIs(result,record)
        self.assertEqual(get.call_count,1)
        update.assert_not_called()


if __name__=='__main__':unittest.main()
