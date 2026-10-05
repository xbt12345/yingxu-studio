"""Invalid compiler text must not be passed off as a successful video edit."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
import schema_adapters
from reviewed_repairs import apply_reviewed_repairs, preserve_117_source_audio, ReviewedRepairError


class CompilerGuard(unittest.TestCase):
    def source(self,wid=68):
        spec=schema_adapters.manifest(f'local-card-{wid}')
        graph=json.loads((Path(__file__).parent/f'workflows/api/local-card-{wid}.api.json').read_text('utf-8'))
        return graph,spec

    def test_bound_guard_is_idempotent_and_preserves_source_and_user_input(self):
        graph,spec=self.source();source=copy.deepcopy(graph)
        apply_reviewed_repairs(graph,spec)
        expected='yingxu_review73_compiler_prompt'
        self.assertEqual(graph['219']['inputs']['prompt'],[expected,0])
        for nid,value in source.items():
            for key,before in value['inputs'].items():
                if (nid,key)==('219','prompt'):continue
                self.assertEqual(graph[nid]['inputs'][key],before,(nid,key))
        self.assertEqual(graph[expected]['inputs'],{'continue':[expected+'_valid',0],'in':['253',0]})
        self.assertEqual(graph[expected+'_valid']['inputs']['b'],False)
        fixed=copy.deepcopy(graph);apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph,fixed)
        changed=copy.deepcopy(graph);changed['253']['inputs']['text']=['270',0]
        before=copy.deepcopy(changed)
        with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(changed,spec)
        self.assertEqual(changed,before)
        changed=copy.deepcopy(graph);changed[expected]['inputs']['continue']=True
        before=copy.deepcopy(changed)
        with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(changed,spec)
        self.assertEqual(changed,before)

    def test_explicit_error_receipt_fails_even_without_media_and_is_saved(self):
        graph,spec=self.source()
        job={'id':'compiler-error','token':'compiler-error','workflow_id':spec['id'],
             'schema_spec':spec,'graph':graph,'status':'queued'}
        receipt={'outputs':{'276':{'text':['COMPILATION_ERROR: specify the arm pose in words.']}},
                 'status':{'status_str':'success'}}
        self.assertIn('姿势',server.reviewed_compiler_failure(job,receipt))
        for output in (None,{}, {'276':None},{'276':{'text':['Raise the right arm.']}},
                       {'276':{'text':[None]}},{'276':{'text':[]}}):
            self.assertIsNone(server.reviewed_compiler_failure(job,{'outputs':output}))
        altered=copy.deepcopy(job);altered['schema_spec']['source_hash']='changed'
        self.assertIsNone(server.reviewed_compiler_failure(altered,receipt))
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'DB',Path(tmp)/'db.sqlite3'),patch.object(server,'PRIVATE',Path(tmp)):
            (server.PRIVATE/'receipts').mkdir()
            with server.database() as db:
                db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, token TEXT UNIQUE, data TEXT NOT NULL)')
                db.execute('INSERT INTO jobs VALUES (?,?,?)',(job['id'],job['token'],json.dumps(job)))
            with patch.object(server.requests,'get') as remote:
                server.collect(job,receipt);remote.assert_not_called()
            saved=server.job(job['id'])
            self.assertEqual(saved['status'],'failed')
            self.assertEqual(saved['stage'],'姿势描述编译失败')
            self.assertEqual(json.loads((server.PRIVATE/'receipts/compiler-error.json').read_text('utf-8')),receipt)

    def test_117_guard_preserves_all_creative_inputs_and_is_idempotent(self):
        graph,spec=self.source(117);source=copy.deepcopy(graph)
        apply_reviewed_repairs(graph,spec)
        guard='yingxu_review73_compiler_prompt'
        self.assertEqual(graph['219']['inputs']['prompt'],[guard,0])
        self.assertEqual(graph[guard]['inputs']['in'],[guard+'_nonempty',0])
        self.assertEqual(graph[guard+'_nonempty']['inputs']['in'],['253',0])
        self.assertEqual(graph[guard+'_trim']['inputs'],{'string':['253',0],'mode':'Both'})
        self.assertEqual(graph[guard+'_length']['inputs'],{'string':[guard+'_trim',0]})
        for nid,value in source.items():
            for key,before in value['inputs'].items():
                if (nid,key) in (('219','prompt'),('190','images'),('288','image1'),
                                 ('190','audio'),('289','audio'),('190','fps'),('289','fps')):continue
                self.assertEqual(graph[nid]['inputs'][key],before,(nid,key))
        self.assertFalse(any(v['class_type']=='globalQueueStop'for v in graph.values()))
        fixed=copy.deepcopy(graph);apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph,fixed)

    def test_117_unknown_source_or_real_link_drift_fails_atomically(self):
        graph,spec=self.source(117)
        for change in ('source','frame','audio','text','output','guard'):
            with self.subTest(change=change):
                changed=copy.deepcopy(graph);contract=copy.deepcopy(spec)
                if change=='source':contract['source_hash']='changed'
                if change=='frame':changed['273']['inputs']['video_frames']=['other',0]
                if change=='audio':changed['219']['inputs']['ref_video_audios.ref_video_audio_0']=['269',0]
                if change=='text':changed['253']['inputs']['text']=['270',0]
                if change=='output':contract['outputs']=['302']
                if change=='guard':
                    apply_reviewed_repairs(changed,contract)
                    changed['yingxu_review73_compiler_prompt_nonempty']['inputs']['continue']=True
                before=copy.deepcopy(changed)
                with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(changed,contract)
                self.assertEqual(changed,before)
        untouched=copy.deepcopy(graph)
        self.assertEqual(apply_reviewed_repairs(untouched,{'id':'unreviewed','source_hash':spec['source_hash']}),[])
        self.assertEqual(untouched,graph)

    def test_117_error_and_empty_receipt_fail_but_normal_description_is_not_changed(self):
        graph,spec=self.source(117)
        job={'id':'compiler-117','token':'compiler-117','workflow_id':spec['id'],
             'schema_spec':spec,'graph':graph,'status':'queued'}
        for text in ('COMPILATION_ERROR: unclear garment assignment.','  compilation_error: missing reference.','', ' \n\t '):
            with self.subTest(text=text):
                receipt={'outputs':{'273':{'text':[text]}},'status':{'status_str':'success'}}
                self.assertIsNotNone(server.reviewed_compiler_failure(job,receipt))
                with tempfile.TemporaryDirectory()as tmp,patch.object(server,'DB',Path(tmp)/'db.sqlite3'),patch.object(server,'PRIVATE',Path(tmp)):
                    (server.PRIVATE/'receipts').mkdir()
                    with server.database()as db:
                        db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, token TEXT UNIQUE, data TEXT NOT NULL)')
                        db.execute('INSERT INTO jobs VALUES (?,?,?)',(job['id'],job['token'],json.dumps(job)))
                    with patch.object(server.requests,'get')as remote:
                        server.collect(job,receipt);remote.assert_not_called()
                    saved=server.job(job['id'])
                    self.assertEqual(saved['status'],'failed')
                    self.assertEqual(saved['stage'],'视频编辑描述编译失败')
                    self.assertEqual(saved['graph'],graph)
                    self.assertEqual(json.loads((server.PRIVATE/'receipts/compiler-117.json').read_text('utf-8')),receipt)
        for text in ('Replace the blue sweater with yellow knit.','subject_definitions:\n保留人物身份与动作。',None):
            self.assertIsNone(server.reviewed_compiler_failure(job,{'outputs':{'273':{'text':[text]}}}))
        altered=copy.deepcopy(job);altered['schema_spec']['source_hash']='changed'
        self.assertIsNone(server.reviewed_compiler_failure(altered,{'outputs':{'273':{'text':['COMPILATION_ERROR: x']}}}))

    def test_117_portable_build_keeps_legal_inline_duration_and_media_controls(self):
        import configuration
        spec=schema_adapters.manifest('local-card-117')
        assets={slot['id']:{'kind':slot['kind'],'remote':'owned-fixture.'+('mp4'if slot['kind']=='video'else'png')}
                for slot in spec['media']}
        with patch.object(schema_adapters,'ROOT',Path('/nonexistent-yingxu-source')),patch.object(configuration,'ROOT',Path('/nonexistent-yingxu-source')):
            for duration,long_side,skip in ((1,512,0),(2,640,3)):
                with self.subTest(duration=duration,long_side=long_side,skip=skip):
                    graph,values,_=schema_adapters.build(spec,{'279:value':duration,'281:value':long_side,'269:skip_first_frames':skip},
                        {'270:value':'Change only the blue sweater to yellow knit.'},assets,{},'portable117')
                    self.assertEqual(graph['277']['inputs']['a'],duration)
                    self.assertEqual(graph['272']['inputs']['scale_to_length'],long_side)
                    self.assertEqual(graph['269']['inputs']['skip_first_frames'],skip)
                    self.assertEqual(graph['219']['inputs']['prompt'],['yingxu_review73_compiler_prompt',0])
                    fixed=copy.deepcopy(graph);apply_reviewed_repairs(graph,spec)
                    self.assertEqual(graph,fixed)

    def test_117_text_guard_does_not_freeze_unrelated_api_limits_or_video_rate(self):
        graph,spec=self.source(117)
        graph['273']['inputs'].update(max_tokens=256,max_video_frames=4)
        graph['278']['inputs']['value']=30
        graph['190']['inputs']['fps']=30
        graph['289']['inputs']['fps']=30
        graph['277']['inputs'].update(a=2,b=30)
        before=copy.deepcopy(graph)
        apply_reviewed_repairs(graph,spec)
        for nid in ('273','278','190','289','277'):
            if nid in ('190','289'):
                self.assertEqual(graph[nid]['inputs']['fps'],['yingxu_review73_117_loaded_info',0])
                self.assertEqual({k:v for k,v in graph[nid]['inputs'].items() if k not in ('fps','audio','images')},
                                 {k:v for k,v in before[nid]['inputs'].items() if k not in ('fps','audio','images')})
            else:self.assertEqual(graph[nid]['inputs'],before[nid]['inputs'])

    def test_117_save_uses_actual_loaded_count_duration_and_source_audio(self):
        graph,spec=self.source(117);original=copy.deepcopy(graph)
        apply_reviewed_repairs(graph,spec)
        frames='yingxu_review73_117_selected_frames'
        info='yingxu_review73_117_loaded_info'
        audio='yingxu_review73_117_source_audio'
        self.assertEqual(graph[frames]['class_type'],'ImageFromBatch')
        self.assertEqual(graph[frames]['inputs'],{'image':['194',0],'batch_index':0,'length':['269',1]})
        self.assertEqual(graph[info]['inputs'],{'video_info':['269',3]})
        self.assertEqual(graph[audio]['inputs'],{'audio':['269',2],'start_index':0.0,'duration':[info,2]})
        self.assertEqual(graph['190']['inputs']['images'],[frames,0])
        self.assertEqual(graph['288']['inputs']['image1'],[frames,0])
        self.assertEqual(graph['288']['inputs']['image2'],['269',0])
        for save in ('190','289'):
            self.assertEqual(graph[save]['inputs']['audio'],[audio,0])
            self.assertEqual(graph[save]['inputs']['fps'],[info,0])
        for nid in ('269','277','278','273','219','194'):
            if nid=='219':
                self.assertEqual({k:v for k,v in graph[nid]['inputs'].items() if k!='prompt'},
                                 {k:v for k,v in original[nid]['inputs'].items() if k!='prompt'})
            else:self.assertEqual(graph[nid]['inputs'],original[nid]['inputs'])
        self.assertEqual(spec['outputs'],['290','302'])

        # Evaluate only the new wiring over known synthetic loaded/decoded
        # values. Wrong slots, generated audio, duration=1, or forgotten compare
        # redirection would fail. Real registered-node execution is a separate
        # CPU acceptance gate, never claimed by this local fixture evaluation.
        import numpy as np
        for loaded,fps,generated in ((25,24,39),(49,24,56),(31,30,39)):
            rate=48000
            source_wave=np.sin(2*np.pi*400*np.arange(rate*3)/rate)
            decoded_wave=np.sin(2*np.pi*600*np.arange(rate*3)/rate)
            cache={('269',1):loaded,('269',2):source_wave,('269',3):{'loaded_fps':fps,'loaded_duration':loaded/fps},
                   ('194',0):np.arange(generated),('194',1):decoded_wave}
            def run_node(nid):
                kind=graph[nid]['class_type'];inputs=graph[nid]['inputs']
                def value(v):
                    if isinstance(v,list):
                        if tuple(v) not in cache:run_node(v[0])
                        return cache[tuple(v)]
                    return v
                if kind=='VHS_VideoInfoLoaded':
                    data=value(inputs['video_info']);cache[(nid,0)]=data['loaded_fps'];cache[(nid,2)]=data['loaded_duration']
                elif kind=='ImageFromBatch':
                    image=value(inputs['image']);start=value(inputs['batch_index']);cache[(nid,0)]=image[start:start+value(inputs['length'])]
                elif kind=='TrimAudioDuration':
                    wave=value(inputs['audio']);start=round(value(inputs['start_index'])*rate);end=start+round(value(inputs['duration'])*rate)
                    cache[(nid,0)]=wave[start:end]
                else:self.fail('unreviewed node entered synthetic evaluator')
            run_node(frames);run_node(audio)
            self.assertEqual(cache[(frames,0)].tolist(),list(range(loaded)))
            self.assertEqual(len(cache[(audio,0)]),round(loaded/fps*rate))
            np.testing.assert_array_equal(cache[(audio,0)],source_wave[:round(loaded/fps*rate)])
            self.assertEqual(cache[(info,0)],fps)

    def test_117_save_unknown_audio_count_info_or_injection_fails_atomically(self):
        graph,spec=self.source(117)
        for mutation in ('audio','comparison-source','decoder','frame-count','duration','fps','extra-input'):
            with self.subTest(mutation=mutation):
                altered=copy.deepcopy(graph);apply_reviewed_repairs(altered,spec)
                if mutation=='audio':altered['190']['inputs']['audio']=['269',1]
                if mutation=='comparison-source':altered['288']['inputs']['image2']=['272',0]
                if mutation=='decoder':altered['194']['class_type']='VAEDecode'
                if mutation=='frame-count':altered['yingxu_review73_117_selected_frames']['inputs']['length']=25
                if mutation=='duration':altered['yingxu_review73_117_source_audio']['inputs']['duration']=1.0
                if mutation=='fps':altered['289']['inputs']['fps']=['278',0]
                if mutation=='extra-input':altered['yingxu_review73_117_source_audio']['inputs']['unreviewed_option']=True
                before=copy.deepcopy(altered)
                with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(altered,spec)
                self.assertEqual(altered,before)

    def test_117_silent_source_omits_only_actual_audio_consumers_and_reruns(self):
        graph,spec=self.source(117)
        apply_reviewed_repairs(graph,spec)
        before=copy.deepcopy(graph)
        source_file=Path(__file__).parent/'private/research/card-20260923/graph-117.json'
        source_bytes=source_file.read_bytes() if source_file.exists() else None
        audio='yingxu_review73_117_source_audio'
        evidence=preserve_117_source_audio(spec,graph,source_has_audio=False)
        self.assertFalse(evidence['source_has_audio'])
        self.assertNotIn(audio,graph)
        self.assertNotIn('ref_video_audios.ref_video_audio_0',graph['219']['inputs'])
        self.assertNotIn('audio',graph['190']['inputs'])
        self.assertNotIn('audio',graph['289']['inputs'])
        self.assertFalse(any(value==['269',2] for node in graph.values()for value in node['inputs'].values()))
        for nid,node in before.items():
            if nid==audio:continue
            for key,value in node['inputs'].items():
                if (nid,key)in(('219','ref_video_audios.ref_video_audio_0'),('190','audio'),('289','audio')):continue
                self.assertEqual(graph[nid]['inputs'][key],value,(nid,key))
        self.assertEqual(spec['outputs'],['290','302'])
        adapted=copy.deepcopy(graph)
        apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph,adapted)
        self.assertEqual(preserve_117_source_audio(spec,graph,source_has_audio=False),evidence)
        self.assertEqual(graph,adapted)
        if source_bytes is not None:self.assertEqual(source_file.read_bytes(),source_bytes)

    def test_117_audio_presence_preserves_reviewed_graph_and_legal_controls(self):
        for duration,fps,skip in ((1,24,0),(2,30,3)):
            with self.subTest(duration=duration,fps=fps,skip=skip):
                graph,spec=self.source(117)
                graph['277']['inputs'].update(a=duration,b=fps)
                graph['269']['inputs']['skip_first_frames']=skip
                graph['278']['inputs']['value']=fps
                apply_reviewed_repairs(graph,spec)
                before=copy.deepcopy(graph)
                self.assertIsNone(preserve_117_source_audio(spec,graph,source_has_audio=True))
                self.assertEqual(graph,before)
                preserve_117_source_audio(spec,graph,source_has_audio=False)
                self.assertEqual(graph['277']['inputs'],before['277']['inputs'])
                self.assertEqual(graph['269']['inputs'],before['269']['inputs'])
                self.assertEqual(graph['278']['inputs'],before['278']['inputs'])
                self.assertEqual(graph['190']['inputs']['fps'],before['190']['inputs']['fps'])

    def test_117_silent_source_unknowns_and_unmarked_port_loss_fail_atomically(self):
        graph,spec=self.source(117);apply_reviewed_repairs(graph,spec)
        for mutation in ('source','audio-vae','h3-port','save-port','extra-consumer','trim-consumer',
                         'bad-marker','marked-port','marked-trim','marked-other-audio','restore-sound'):
            with self.subTest(mutation=mutation):
                altered=copy.deepcopy(graph);contract=copy.deepcopy(spec);has_audio=False
                if mutation=='source':contract['source_hash']='changed'
                if mutation=='audio-vae':altered['219']['inputs']['audio_vae']=['other',0]
                if mutation=='h3-port':del altered['219']['inputs']['ref_video_audios.ref_video_audio_0']
                if mutation=='save-port':del altered['190']['inputs']['audio']
                if mutation=='extra-consumer':altered['unreviewed']={'class_type':'ShowText|pysssss','inputs':{'text':['269',2]}}
                if mutation=='trim-consumer':altered['unreviewed']={'class_type':'ShowText|pysssss','inputs':{'text':['yingxu_review73_117_source_audio',0]}}
                if mutation=='bad-marker':altered['269'].setdefault('_meta',{})['yingxu_review73_117_source_audio_state']=False
                if mutation.startswith('marked-')or mutation=='restore-sound':
                    preserve_117_source_audio(contract,altered,source_has_audio=False)
                    if mutation=='marked-port':altered['190']['inputs']['audio']=['194',1]
                    if mutation=='marked-trim':altered['yingxu_review73_117_source_audio']=copy.deepcopy(graph['yingxu_review73_117_source_audio'])
                    if mutation=='marked-other-audio':altered['219']['inputs']['ref_video_audios.ref_video_audio_1']=['269',2]
                    if mutation=='restore-sound':has_audio=True
                before=copy.deepcopy(altered)
                with self.assertRaises(ReviewedRepairError):preserve_117_source_audio(contract,altered,source_has_audio=has_audio)
                self.assertEqual(altered,before)
        for unknown in (None,0,1,'false','true'):
            altered=copy.deepcopy(graph);before=copy.deepcopy(altered)
            with self.assertRaises(ReviewedRepairError):preserve_117_source_audio(spec,altered,source_has_audio=unknown)
            self.assertEqual(altered,before)
        other=copy.deepcopy(graph)
        self.assertIsNone(preserve_117_source_audio({'id':'local-card-68'},other,source_has_audio=None))
        self.assertEqual(other,graph)


if __name__=='__main__':unittest.main()
