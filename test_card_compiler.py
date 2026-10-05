"""Regression checks for graph conversion without submitting GPU jobs."""
import copy
import json
import sys
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
from compile_card_workflows import Compiler, CompileError, sanitize
from workflow_customization import label_first_last_frames, preserves_system_instruction, reviewed_text_purpose, label_animate_reference_slots, refresh_curated_controls, directory_image_order_control, description_language_control, verified_description_language_options, seedvr2_short_edge_control, dance_ratio_protocol_form


def ui_graph_from_api(api):
    """Retain named ports and actual output slots for display-only graph rules."""
    nodes={key:{'type':node['class_type'],'inputs':[{'name':name}for name in node.get('inputs',{})]}for key,node in api.items()}
    out=defaultdict(list)
    for key,node in api.items():
        for slot,value in enumerate(node.get('inputs',{}).values()):
            if isinstance(value,list)and len(value)==2 and str(value[0])in api:
                out[str(value[0])].append((key,slot,value[1]))
    return SimpleNamespace(nodes=nodes,out=out,reachable=set(api))


class CompilerTests(unittest.TestCase):
    def test_dance_machine_ratios_are_not_creative_prompts_and_source_survives_compilation(self):
        from build_workflow_interfaces import Graph
        root=Path(__file__).parent
        source=root/'private/research/card-20261004/graph-030.json'
        original=source.read_bytes();raw=json.loads(original)
        public=json.loads((root/'public/workflow-interfaces.json').read_text('utf-8'))['workflows']['local-card-30']
        source_hash='1d4bb89d8e5531a50b800e5d1228ac9a230091b4df1ab7bf49e9e4062fc115c0'
        controls,texts=dance_ratio_protocol_form(copy.deepcopy(public['controls']),copy.deepcopy(public['texts']),graph=Graph(raw))
        self.assertNotIn('156:text',{t['id']for t in texts})
        self.assertNotIn('157:text',{t['id']for t in texts})
        self.assertEqual(next(t for t in texts if t['id']=='75:prompt'),next(t for t in public['texts']if t['id']=='75:prompt'))
        self.assertEqual(next(c for c in controls if c['id']=='159:widget_0')['label'],'输出短边（像素）')
        reviewed=refresh_curated_controls({'id':'local-card-30'},copy.deepcopy(public),
                                          {'sourceHash':source_hash,'controls':controls,'texts':texts})
        self.assertEqual({t['id']for t in reviewed['texts']},{'75:prompt','95:negative_prompt'})
        schemas=json.loads((root/'private/review72/object_info.json').read_text('utf-8'))
        compiler=Compiler(raw,schemas);compiler.compile_node('161')
        compiled=sanitize(compiler.compiled,[{**t,'targets':compiler.targets(*t['id'].rsplit(':',1))}for t in texts],[])
        self.assertEqual(compiled['156']['inputs']['text'],'16:9')
        self.assertEqual(compiled['157']['inputs']['text'],'9:16')
        self.assertEqual(compiled['160']['inputs'],{'boolean':['158',0],'ON_TRUE':['156',0],'ON_FALSE':['157',0]})
        self.assertEqual(compiled['161']['inputs']['aspect_ratio'],['160',0])
        self.assertEqual(source.read_bytes(),original)

    def test_dance_protocol_rejects_unknown_source_or_changed_ratio_consumers(self):
        root=Path(__file__).parent
        graph=json.loads((root/'private/card-compiled/local-card-30.api.json').read_text('utf-8'))
        for nid,key,value in (('156','text','new creative text'),('161','aspect_ratio',['75',0]),
                              ('160','ON_FALSE',['156',0]),('161','scale_to_side','longest')):
            with self.subTest(node=nid,key=key):
                changed=copy.deepcopy(graph);changed[nid]['inputs'][key]=value
                with self.assertRaises(ValueError):dance_ratio_protocol_form([],[],graph=changed)
        with self.assertRaises(ValueError):dance_ratio_protocol_form([],[],source_hash='unknown')
        with self.assertRaises(ValueError):dance_ratio_protocol_form([], [{'id':'156:text','key':'text','targets':[{'node':'75','input':'prompt'}]}],source_hash='1d4bb89d8e5531a50b800e5d1228ac9a230091b4df1ab7bf49e9e4062fc115c0')

    def setUp(self):
        self.schemas = {
            'Source': {'input': {'required': {'value': ['STRING', {'default': ''}]}}, 'output': ['STRING']},
            'SaveImage': {'input': {'required': {'images': ['STRING']}}, 'output': [], 'output_node': True},
        }

    def test_tail_frame_control_uses_actual_source_default_and_survives_curated_refresh(self):
        from build_workflow_interfaces import Graph
        from workflow_customization import add_review70_controls
        api=json.loads((Path(__file__).parent/'workflows/api/local-card-57.api.json').read_text('utf-8'))
        workflow={'id':'local-card-57','category':'首尾帧'}
        controls=add_review70_controls(workflow,Graph(api),[])
        field=next(f for f in controls if f['id']=='56:switch')
        self.assertEqual((field['kind'],field['type'],field['value']),('toggle','checkbox',False))
        self.assertEqual(field['targets'],[{'node':'56','input':'switch'}])
        reviewed={'controls':[],'texts':[],'media':[{'id':'24','kind':'image','label':'尾帧'}]}
        refresh_curated_controls(workflow,reviewed,{'controls':controls})
        self.assertEqual(reviewed['controls'][0],field)
        self.assertEqual(reviewed['media'][0]['label'],'尾帧（需启用）')
        reviewed['controls'][0]['value']=True
        refresh_curated_controls(workflow,reviewed,{'controls':controls})
        self.assertTrue(reviewed['controls'][0]['value'],'preserve explicit enabled choice')

    def test_directory_sort_control_survives_curated_refresh_and_matches_real_options(self):
        controls=directory_image_order_control([])
        field=controls[0]
        self.assertEqual(field['id'],'12:sort_method')
        self.assertEqual(field['targets'],[{'node':'12','input':'sort_method'}])
        self.assertEqual(field['value'],'Alphabetical (ASC)')
        self.assertIn('None',[item['value']for item in field['options']])
        reviewed={'controls':[],'texts':[],'media':[]}
        refreshed=refresh_curated_controls({'id':'local-card-135'},reviewed,{'controls':controls})
        self.assertEqual(refreshed['controls'],controls)
        self.assertEqual(len(directory_image_order_control(refreshed['controls'])),1)

    def test_qwen_description_language_is_explicit_real_enum_and_survives_refresh(self):
        controls=description_language_control([]);field=controls[0]
        self.assertEqual(field['id'],'76:from_translate')
        self.assertEqual(field['targets'],[{'node':'76','input':'from_translate'}])
        self.assertEqual(field['value'],'auto')
        self.assertLessEqual(len(field['help']),12)
        actual=['auto','english','chinese (simplified)','chinese (traditional)','spanish']
        self.assertEqual(verified_description_language_options(field,actual),field['options'])
        self.assertEqual([item['value']for item in field['options']],['auto','english','chinese (simplified)'])
        with self.assertRaises(ValueError):verified_description_language_options(field,['auto','english'])
        changed=copy.deepcopy(field);changed['targets']=[{'node':'76','input':'to_translate'}]
        with self.assertRaises(ValueError):verified_description_language_options(changed,actual)
        field['value']='english'
        reviewed={'controls':controls,'texts':[],'media':[]}
        refreshed=refresh_curated_controls({'id':'local-card-93'},reviewed,{'controls':[]})
        self.assertEqual(refreshed['controls'][0]['value'],'english','refresh does not override explicit saved choice')
        self.assertEqual(len(description_language_control(refreshed['controls'])),1)

    def test_seedvr2_size_control_describes_actual_short_edge_socket(self):
        root=Path(__file__).parent
        api=json.loads((root/'workflows/api/local-card-122.api.json').read_text('utf-8'))
        interface=json.loads((root/'public/workflow-interfaces.json').read_text('utf-8'))['workflows']['local-card-122']
        field=next(f for f in interface['controls']if f['id']=='34:value')
        self.assertEqual(api['10']['class_type'],'SeedVR2VideoUpscaler')
        self.assertEqual(api['10']['inputs']['resolution'],['34',0])
        self.assertEqual(field['targets'],[{'node':'10','input':'resolution'}])
        self.assertIn('shortest side',api['34']['_meta']['title'])
        self.assertEqual(field['label'],'输出短边（像素）')
        self.assertEqual(field['value'],api['34']['inputs']['value'])
        self.assertEqual(api['10']['inputs']['max_resolution'],0,
                         'no separate maximum-edge cap is mistaken for the short-edge selector')

    def test_seedvr2_registered_range_survives_curated_refresh_without_changing_size(self):
        root=Path(__file__).parent
        interface=json.loads((root/'public/workflow-interfaces.json').read_text('utf-8'))['workflows']['local-card-122']
        reviewed=copy.deepcopy(interface)
        field=next(f for f in reviewed['controls']if f['id']=='34:value')
        field['value']=1082
        refreshed=refresh_curated_controls({'id':'local-card-122'},reviewed,copy.deepcopy(interface))
        field=next(f for f in refreshed['controls']if f['id']=='34:value')
        self.assertEqual((field['min'],field['max'],field['step'],field['integer']),(16,16384,2,True))
        self.assertEqual(field['value'],1082,'explicit even-pixel short side is preserved')
        self.assertEqual(field['targets'],[{'node':'10','input':'resolution'}])
        changed=copy.deepcopy(field);changed['targets']=[{'node':'10','input':'max_resolution'}]
        before=copy.deepcopy(changed)
        with self.assertRaises(ValueError):seedvr2_short_edge_control([changed])
        self.assertEqual(changed,before,'never apply short-edge range to a different socket')

    def test_real_link_id_overrides_stale_slot_metadata(self):
        raw = {'nodes': [
            {'id': 1, 'type': 'Source', 'inputs': [{'name': 'value', 'widget': {'name': 'value'}}], 'widgets_values': ['x']},
            {'id': 2, 'type': 'SaveImage', 'inputs': [{'name': 'images', 'link': 22}]},
        ], 'links': [[22, 1, 0, 2, 1, 'STRING']]}
        compiler = Compiler(raw, self.schemas)
        self.assertEqual(compiler.outputs('image'), ['2'])
        self.assertEqual(compiler.compiled['2']['inputs']['images'], ['1', 0])

    def test_missing_node_is_blocked_instead_of_replaced(self):
        raw = {'nodes': [{'id': 1, 'type': 'MissingSaveImage'}], 'links': []}
        with self.assertRaisesRegex(CompileError, 'Card node unavailable'):
            Compiler(raw, self.schemas).outputs('image')

    def test_rgthree_flexible_switch_keeps_connected_sources_in_order(self):
        schema = {**self.schemas, 'Any Switch (rgthree)': {
            'input': {'required': {}, 'optional': {}}, 'output': ['*']}}
        raw = {'nodes': [
            {'id': 1, 'type': 'Source', 'inputs': [{'name': 'value', 'widget': {'name': 'value'}}], 'widgets_values': ['first']},
            {'id': 3, 'type': 'Source', 'inputs': [{'name': 'value', 'widget': {'name': 'value'}}], 'widgets_values': ['second']},
            {'id': 4, 'type': 'Any Switch (rgthree)', 'inputs': [
                {'name': 'any_01', 'link': 10}, {'name': 'any_02', 'link': 11}, {'name': 'any_03', 'link': None}]},
            {'id': 2, 'type': 'SaveImage', 'inputs': [{'name': 'images', 'link': 12}]},
        ], 'links': [[10, 1, 0, 4, 0, 'STRING'], [11, 3, 0, 4, 1, 'STRING'], [12, 4, 0, 2, 0, 'STRING']]}
        c = Compiler(raw, schema)
        c.outputs('image')
        self.assertEqual(c.compiled['4']['inputs'], {'any_01': ['1', 0], 'any_02': ['3', 0]})
        self.assertIn('1', c.compiled)
        self.assertIn('3', c.compiled)

    def test_saved_link_to_a_different_node_is_blocked(self):
        raw = {'nodes': [
            {'id': 1, 'type': 'Source', 'inputs': [{'name': 'value', 'widget': {'name': 'value'}}], 'widgets_values': ['x']},
            {'id': 2, 'type': 'SaveImage', 'inputs': [{'name': 'images', 'link': 22}]},
            {'id': 3, 'type': 'SaveImage', 'inputs': [{'name': 'images', 'link': 22}]},
        ], 'links': [[22, 1, 0, 3, 0, 'STRING']]}
        with self.assertRaisesRegex(CompileError, 'targets a different node'):
            Compiler(raw, self.schemas).outputs('image')

    def test_missing_saved_link_cannot_fall_back_to_a_widget_default(self):
        raw = {'nodes': [{'id': 2, 'type': 'SaveImage', 'inputs': [
            {'name': 'images', 'link': 22, 'widget': {'name': 'images'}}],
            'widgets_values': ['fallback']}], 'links': []}
        with self.assertRaisesRegex(CompileError, 'Missing saved link'):
            Compiler(raw, self.schemas).outputs('image')

    def test_disabled_subgraph_does_not_emit_child_results(self):
        definition = {'id': 'off', 'nodes': [{'id': 5, 'type': 'SaveImage', 'inputs': [{'name': 'images', 'widget': {'name': 'images'}}], 'widgets_values': ['disabled output']}], 'links': []}
        raw = {'nodes': [
            {'id': 1, 'type': 'off', 'mode': 4},
            {'id': 2, 'type': 'SaveImage', 'inputs': [{'name': 'images', 'widget': {'name': 'images'}}], 'widgets_values': ['active output']},
        ], 'links': [], 'definitions': {'subgraphs': [definition]}}
        compiler = Compiler(raw, self.schemas)
        self.assertEqual(compiler.outputs('image'), ['2'])
        self.assertNotIn('1:5', compiler.compiled)

    def test_saved_boolean_and_number_widgets_have_current_api_types(self):
        schema = {'Int': {'input': {'required': {'Number': ['STRING']}}},
                  'WanVideoSampler': {'input': {'required': {'batched_cfg': ['BOOLEAN', {'default': False}]}}}}
        raw = {'nodes': [
            {'id': 1, 'type': 'Int', 'inputs': [{'name': 'Number', 'widget': {'name': 'Number'}}], 'widgets_values': [81]},
            {'id': 2, 'type': 'WanVideoSampler', 'inputs': [{'name': 'batched_cfg', 'widget': {'name': 'batched_cfg'}}], 'widgets_values': ['']},
        ], 'links': []}
        compiler = Compiler(raw, schema)
        compiler.compile_node('1'); compiler.compile_node('2')
        self.assertEqual(compiler.compiled['1']['inputs']['Number'], '81')
        self.assertIs(compiler.compiled['2']['inputs']['batched_cfg'], False)
        self.assertEqual(len(compiler.normalized), 2)

    def test_legacy_one_guide_socket_keeps_its_reference_link(self):
        schema = {**self.schemas, 'LTXVAddGuideMulti': {'input': {'required': {
            'num_guides': ['COMFY_DYNAMICCOMBO_V3', {'options': [{'key': '1', 'inputs': {'required': {
                'image_1': ['STRING'], 'frame_idx_1': ['INT', {'default': 0}], 'strength_1': ['FLOAT', {'default': 1.0}]}}}]}]}}}}
        raw = {'nodes': [
            {'id': 1, 'type': 'Source', 'inputs': [{'name': 'value', 'widget': {'name': 'value'}}], 'widgets_values': ['reference']},
            {'id': 2, 'type': 'LTXVAddGuideMulti', 'inputs': [{'name': 'num_guides', 'widget': {'name': 'num_guides'}}, {'name': 'image_1', 'link': 9}], 'widgets_values': [0]},
        ], 'links': [[9, 1, 0, 2, 1, 'STRING']]}
        compiler = Compiler(raw, schema)
        compiler.compile_node('2')
        self.assertEqual(compiler.compiled['2']['inputs']['num_guides'], '1')
        self.assertEqual(compiler.compiled['2']['inputs']['num_guides.image_1'], ['1', 0])

    def test_upstream_chat_rename_preserves_prompt_names_and_output_slots(self):
        schema = {'VisionChat': {'input': {'required': {
            'system_prompt': ['STRING'], 'prompt': ['STRING'], 'thinking_mode': [['auto', 'off', 'medium']]}},
            'output': ['STRING', 'STRING', 'STRING', 'STRING']}}
        raw = {'nodes': [{'id': 2, 'type': 'MultimodalChat', 'inputs': [
            {'name': 'prompt', 'widget': {'name': 'prompt'}},
            {'name': 'system_prompt', 'widget': {'name': 'system_prompt'}},
            {'name': 'thinking_mode', 'widget': {'name': 'thinking_mode'}},
        ], 'widgets_values': ['user instruction', 'system instruction', 'thinking']}], 'links': []}
        compiler = Compiler(raw, schema)
        compiler.compile_node('2')
        migrated = compiler.compiled['2']
        self.assertEqual(migrated['class_type'], 'VisionChat')
        self.assertEqual(migrated['inputs']['prompt'], 'user instruction')
        self.assertEqual(migrated['inputs']['system_prompt'], 'system instruction')
        self.assertEqual(migrated['inputs']['thinking_mode'], 'medium')
        self.assertEqual(raw['nodes'][0]['type'], 'MultimodalChat')

    def test_rename_does_not_override_an_available_original_class(self):
        schema = {name: {'input': {'required': {'prompt': ['STRING']}}} for name in ('MultimodalChat', 'VisionChat')}
        raw = {'nodes': [{'id': 2, 'type': 'MultimodalChat', 'inputs': [{'name': 'prompt', 'widget': {'name': 'prompt'}}], 'widgets_values': ['original']}], 'links': []}
        compiler = Compiler(raw, schema)
        compiler.compile_node('2')
        self.assertEqual(compiler.compiled['2']['class_type'], 'MultimodalChat')
        self.assertEqual(compiler.normalized, [])

    def test_dynamic_subgraph_instance_ids_keep_independent_inputs(self):
        definition = {'id': 'def', 'nodes': [
            {'id': 5, 'type': 'SaveImage', 'inputs': [{'name': 'images', 'link': 10}]},
        ], 'links': [[10, -10, 0, 5, 0, 'STRING'], [11, 5, 0, -20, 0, 'STRING']]}
        raw = {'nodes': [
            {'id': 1, 'type': 'def', 'inputs': [{'name': 'input', 'widget': {'name': 'input'}}], 'widgets_values': ['a']},
            {'id': 2, 'type': 'def', 'inputs': [{'name': 'input', 'widget': {'name': 'input'}}], 'widgets_values': ['b']},
        ], 'links': [], 'definitions': {'subgraphs': [definition]}}
        compiler = Compiler(raw, self.schemas)
        compiler.outputs('image')
        self.assertEqual(compiler.compiled['1:5']['inputs']['images'], 'a')
        self.assertEqual(compiler.compiled['2:5']['inputs']['images'], 'b')

    def test_dependency_path_repair_requires_exact_unique_basename(self):
        schema = {'Model': {'input': {'required': {'lora_name': [['new/same.safetensors', 'other/model.safetensors']]}}}}
        raw = {'nodes': [{'id': 1, 'type': 'Model', 'inputs': [{'name': 'lora_name', 'widget': {'name': 'lora_name'}}], 'widgets_values': ['old/same.safetensors']}], 'links': []}
        compiler = Compiler(raw, schema)
        compiler.compile_node('1')
        self.assertEqual(compiler.dependency_errors(), [])
        self.assertEqual(compiler.compiled['1']['inputs']['lora_name'], 'new/same.safetensors')
        ambiguous = copy.deepcopy(schema)
        ambiguous['Model']['input']['required']['lora_name'][0].append('another/same.safetensors')
        compiler = Compiler(raw, ambiguous)
        compiler.compile_node('1')
        self.assertEqual(len(compiler.dependency_errors()), 1)

    def test_export_removes_linked_keys_media_and_saved_point_state(self):
        graph = {
            'key': {'class_type': 'Source', 'inputs': {'value': 'private-key'}},
            'api': {'class_type': 'API', 'inputs': {'apikey': ['key', 0], 'prompt': 'private prompt'}},
            'video': {'class_type': 'Video', 'inputs': {'video': 'personal.mp4'}},
            'points': {'class_type': 'PointsEditor', 'inputs': {'points_store': '{"positive":[1]}', 'coordinates': '[1]', 'neg_coordinates': '[2]', 'bbox_store': '[3]', 'bboxes': '[4]'}},
        }
        cleaned = sanitize(graph, [{'targets': [{'node': 'api', 'input': 'prompt'}]}], [{'targets': [{'node': 'video', 'input': 'video'}]}])
        self.assertEqual(cleaned['key']['inputs']['value'], '')
        self.assertEqual(cleaned['api']['inputs']['prompt'], '')
        self.assertEqual(cleaned['video']['inputs']['video'], '')
        self.assertEqual(cleaned['points']['inputs']['points_store'], '{"positive":[],"negative":[]}')
        self.assertEqual(cleaned['points']['inputs']['bboxes'], '[]')
        self.assertEqual(graph['key']['inputs']['value'], 'private-key')

    def test_export_preserves_token_limits_counts_and_scope_but_removes_credentials(self):
        numeric = {'max_tokens': 0, 'min_tokens': 64, 'token_count': 1024, 'chunk_tokens': 4096,
                   'num_tokens': 512, 'token_scope': 'all', 'maximum_tokens': 8192}
        credentials = {key: 'test-private-owner-value' for key in
                       ('api_key', 'access_token', 'token', 'password', 'secret', 'authorization',
                        'apiToken', 'refresh_token', 'auth_token', 'hf_token')}
        graph = {'api': {'class_type': 'VisionAPIDirect', 'inputs': {**numeric, **credentials,
                     'unclassified_value': 'sk-' + 'testsecretvalue000001', 'filename_prefix': 'private/prefix'}}}
        before = copy.deepcopy(graph)
        cleaned = sanitize(graph, [], [])
        for key, value in numeric.items():
            self.assertEqual(cleaned['api']['inputs'][key], value, key)
            self.assertEqual(type(cleaned['api']['inputs'][key]), type(value), key)
        for key in credentials:
            self.assertEqual(cleaned['api']['inputs'][key], '', key)
        self.assertEqual(cleaned['api']['inputs']['unclassified_value'], '')
        self.assertEqual(cleaned['api']['inputs']['filename_prefix'], 'yingxu/result')
        self.assertEqual(graph, before, 'source input values remain unchanged')

    def test_export_cleans_credential_relay_widgets_without_treating_numeric_links_as_secrets(self):
        graph = {
            'credential': {'class_type': 'Source', 'inputs': {'value': 'test-non-sk-owner-secret'}},
            'relay': {'class_type': 'Relay', 'inputs': {'text': ['credential', 0]}},
            'budget': {'class_type': 'PrimitiveInt', 'inputs': {'value': 1024}},
            'api': {'class_type': 'API', 'inputs': {'access_token': ['relay', 0], 'max_tokens': ['budget', 0]}},
        }
        before = copy.deepcopy(graph)
        cleaned = sanitize(graph, [], [])
        self.assertEqual(cleaned['credential']['inputs']['value'], '')
        self.assertEqual(cleaned['relay']['inputs']['text'], ['credential', 0])
        self.assertEqual(cleaned['api']['inputs']['access_token'], ['relay', 0])
        self.assertEqual(cleaned['api']['inputs']['max_tokens'], ['budget', 0])
        self.assertEqual(cleaned['budget']['inputs']['value'], 1024)
        self.assertEqual(graph, before)

    def test_frame_labels_follow_real_image_ports_not_stale_titles_or_geometry(self):
        api=json.loads((Path(__file__).parent/'workflows/api/local-card-124.api.json').read_text('utf-8'))
        before=copy.deepcopy(api)
        media=[{'id':'79','kind':'image','label':'首帧 1','node':'Load First Frame'},
               {'id':'78','kind':'image','label':'首帧 2','node':'Load First Frame'}]
        labelled=label_first_last_frames(ui_graph_from_api(api),copy.deepcopy(media))
        self.assertEqual([(m['id'],m['label'])for m in labelled],[('79','尾帧'),('78','首帧')])
        self.assertEqual(api,before)
        for old,new in zip(media,labelled):
            self.assertEqual({k:v for k,v in old.items()if k!='label'},{k:v for k,v in new.items()if k!='label'})
        # The real source also connects resize15 dimensions to resize48. Those
        # INT wires must not make image78 appear to supply the end image.
        self.assertEqual(api['48']['inputs']['width'],['15',2])
        swapped=copy.deepcopy(api)
        for node in ('60','44'):
            inputs=swapped[node]['inputs'];inputs['start_image'],inputs['end_image']=inputs['end_image'],inputs['start_image']
        labelled=label_first_last_frames(ui_graph_from_api(swapped),copy.deepcopy(media))
        self.assertEqual([(m['id'],m['label'])for m in labelled],[('79','首帧'),('78','尾帧')])

    def test_fixed_system_instruction_requires_real_reachable_consumer(self):
        for number,source,consumer in [(4,'187','186'),(52,'187','186'),(54,'159','161')]:
            with self.subTest(number=number):
                api=json.loads((Path(__file__).parent/f'workflows/api/local-card-{number}.api.json').read_text('utf-8'))
                before=copy.deepcopy(api)
                self.assertEqual(api[consumer]['inputs']['system_prompt'],[source,0])
                self.assertTrue(preserves_system_instruction(api,source,'value'))
                self.assertTrue(preserves_system_instruction(ui_graph_from_api(api),source,'value'))
                wrong=copy.deepcopy(api);wrong[consumer]['inputs']['prompt']=[source,0];wrong[consumer]['inputs']['system_prompt']='fixed elsewhere'
                self.assertFalse(preserves_system_instruction(wrong,source,'value'))
                self.assertFalse(preserves_system_instruction(api,source,'prompt'))
                raw=ui_graph_from_api(api);raw.reachable.remove(consumer)
                self.assertFalse(preserves_system_instruction(raw,source,'value'))
                self.assertEqual(api,before)

    def test_detection_text_labels_follow_actual_detector_ports_not_generation_category(self):
        for number,source,key in [(24,'3724','value'),(25,'623','value'),(27,'753','value'),
                                  (116,'753','value'),(28,'443','value'),(30,'75','prompt')]:
            with self.subTest(number=number):
                api=json.loads((Path(__file__).parent/f'workflows/api/local-card-{number}.api.json').read_text('utf-8'))
                expected={'label':'姿势检测目标'if number==30 else'分割目标','help':'用简短词描述目标'}
                before=copy.deepcopy(api)
                self.assertEqual(reviewed_text_purpose(api,source,key),expected)
                self.assertEqual(reviewed_text_purpose(ui_graph_from_api(api),source,key),expected)
                raw=ui_graph_from_api(api);raw.reachable.remove(source)
                self.assertEqual(reviewed_text_purpose(raw,source,key),{})
                wrong=copy.deepcopy(api)
                if number==30:wrong[source]['class_type']='CLIPTextEncode'
                else:
                    detector=next(n for n in wrong.values()if n.get('inputs',{}).get('prompt')==[source,0])
                    detector['class_type']='CLIPTextEncode'
                self.assertEqual(reviewed_text_purpose(wrong,source,key),{})
                self.assertEqual(api,before)

    def test_animate_media_labels_follow_background_and_character_image_ports(self):
        api=json.loads((Path(__file__).parent/'workflows/api/local-card-24.api.json').read_text('utf-8'))
        before=copy.deepcopy(api)
        slots=[{'id':'3688','kind':'image','label':'角色参考图 1'},
               {'id':'3737','kind':'image','label':'角色参考图 2'}]
        result=label_animate_reference_slots(ui_graph_from_api(api),copy.deepcopy(slots))
        self.assertEqual([m['label']for m in result],['背景图','角色参考图'])
        self.assertEqual(api['3689']['inputs']['width'],['3697',1],'geometry sharing is not an image role')
        swapped=copy.deepcopy(api);inputs=swapped['3744']['inputs']
        inputs['bg_images'],inputs['ref_images']=inputs['ref_images'],inputs['bg_images']
        result=label_animate_reference_slots(ui_graph_from_api(swapped),copy.deepcopy(slots))
        self.assertEqual([m['label']for m in result],['角色参考图','背景图'])
        changed=copy.deepcopy(api);changed['3673']['inputs']['image']=['3737',0]
        result=label_animate_reference_slots(ui_graph_from_api(changed),copy.deepcopy(slots))
        self.assertEqual([m['label']for m in result],['角色参考图 1','角色参考图 2'],'ambiguous or disconnected image roles keep the reviewed label')
        self.assertEqual(api,before)
        reviewed={'controls':[],'texts':[{'id':'3724:value','label':'创作描述','preserveWhenEmpty':False}],
                  'media':copy.deepcopy(slots)}
        derived={'controls':[],'texts':[{'id':'3724:value','label':'分割目标','help':'用简短词描述目标','preserveWhenEmpty':True}],
                 'media':label_animate_reference_slots(ui_graph_from_api(api),copy.deepcopy(slots))}
        refreshed=refresh_curated_controls({'id':'local-card-24','category':'动作迁移与舞蹈'},reviewed,derived)
        self.assertEqual([m['label']for m in refreshed['media']],['背景图','角色参考图'])
        self.assertEqual(refreshed['texts'][0]['label'],'分割目标');self.assertTrue(refreshed['texts'][0]['preserveWhenEmpty'])


if __name__ == '__main__':
    unittest.main()
