"""Narrow execution repairs backed by review72 failures and exact source graphs.

The owner's original workflow files never change. Both compiled templates and
runtime job graphs record the applied repair in node metadata. Unknown source
identities or changed links fail closed instead of receiving a guessed repair.
"""
import copy
from h3_duration_preservation import preserve_h3_duration, CONTRACTS as H3_DURATION_CONTRACTS
from anime_batch_protocol import repair_anime_batch_protocol


SOURCE_HASHES = {
    'local-card-0': '391288f05147959d95d43fb617fa775c6f79413910a363cf7272dd972449c056',
    'local-card-5': '4c37ca0b7de7de9754bb40eaa749f567df99a5a2eafada1f2a72971aea7e7c9f',
    'local-card-33': 'f9990b19d1ce659ef7416f75e59b5614722069637c40f31c9106737f6048a5cb',
    'local-card-32': 'b716566c7fc4e99c10aae6b93f5ae95bfcc945385709dc8732f865f40917eab6',
    'local-card-40': '1ee0c5812e0cd846ba6460ae69411de2bae4797ee38e5be60017e8e34b7655e7',
    'local-card-41': 'cbc23fea743b2442ce7785a8871395c1a42ff44f722210f1df4622aaf2dadcdf',
    'local-card-46': '09721c7ecf536bcda5e07f038d4fb223de8db67c48e3e38e844f219bdf6f0e5c',
    'local-card-68': '87aeca2157dafa9dddc059b0bb3658f90c302332e32dca509b133caa3e8e04b9',
    'local-card-75': '0eb7da0d8c7d97d59a093d361c0eb357222fbca0e1423eb9459137df960b7945',
    'local-card-80': '83d4166f18f6215116e365394b1d4a3393fcd069d8afd8b6c29ca0e1247c5a41',
    'local-card-93': '45c4103740959e1e7890af7a8a25e2292c67720682020f5387aa637697c89970',
    'local-card-117': 'c167d210db8f5270d0b760f5e0bb330f89217d34ba48b7e4d4b737ddfc18b6bf',
    'local-card-118': 'a66e533d5c4c2f2e3605dd3b26e32f1c63730a91c4837eed333091f40f14f1ec',
    'local-card-119': '110d7f6bab4e5a2a4d1880c6ece2db2ca92b3e3c10f301c8ce1dafe73de14f7f',
    'local-card-120': 'b8ab76162041b1893180996f3badbdc26eaa82be7fa63b913de4a7ebef2b65e2',
    'local-card-121': '9f7c6e6b8bfe7cf14ea33a3b763f02b0415ca155d8c5b531a8deaa40b3fa5882',
    'local-card-122': '0036eac90c054211b9507171597c8486415ca4b2504d4cbf33c373e36e269f91',
    'local-card-123': '5c46f4ef6b61dfa42edead5da785672bc87253f4b20315f83fd2505f1d0dfdf1',
    'local-card-124': '539ebf8eb167f3571a11bb9cddfc08a819b6f906aa4f80907cbe320b61dd436e',
    'local-card-135': '648b72a9050cbac21a0873dacc262a943a5f3aaea52b40f3bd0995fa8552d0ad',
}

# These source chains upscale frames without changing their playback rate.
VIDEO_CHAINS = {
    'local-card-118': ('13', '24', '42', 'FlashVSRNode'),
    'local-card-119': ('507', '502', '530', 'LayerUtility: PurgeVRAM V2'),
    'local-card-120': ('18', '3', '19', 'FlashVSRNode'),
    'local-card-121': ('15', '9', '5', 'ImageUpscaleWithModelBatched'),
    'local-card-122': ('25', '28', '10', 'SeedVR2VideoUpscaler'),
    'local-card-123': ('18', '16', '1', 'FlashVSRNodeAdv'),
}
RESIZE_BRANCHES = {
    'local-card-118': ('31', '27', '28', '26', '30', '42'),
    'local-card-120': ('5', '7', '6', '9', '4', '19'),
    'local-card-123': ('8', '11', '14', '13', '7', '1'),
}
SORT_METHODS = ('None', 'Alphabetical (ASC)', 'Alphabetical (DESC)',
                'Numerical (ASC)', 'Numerical (DESC)', 'Datetime (ASC)', 'Datetime (DESC)')
DESCRIPTION_LANGUAGES = ('auto', 'english', 'chinese (simplified)')
OWNER_DEFAULT_MODELS = {
    'local-card-0': ('577', 'grok-4-fast-non-reasoning', 'grok-4.6'),
    'local-card-32': ('31', 'grok-4-fast-non-reasoning', 'grok-4.6'),
    'local-card-33': ('29', 'gemini-3.8-flash-low', 'gemini-3.8-flash-thinking-low'),
    'local-card-80': ('146', 'grok-4-fast-reasoning', 'grok-4.6'),
}
OWNER_GROK_OUTPUTS = {
    'local-card-0': ['292', '246'],
    'local-card-32': ['38'],
    'local-card-80': ['64'],
}


class ReviewedRepairError(ValueError):
    pass


_117_AUDIO_NODE = 'yingxu_review73_117_source_audio'
_117_AUDIO_STATE = 'yingxu_review73_117_source_audio_state'
_117_AUDIO_PORT = 'ref_video_audios.ref_video_audio_0'


def _117_silent_state(graph, spec):
    """Accept only the recorded, exact silent-source adaptation on saved jobs."""
    state = graph.get('269', {}).get('_meta', {}).get(_117_AUDIO_STATE)
    if state is None:
        return False
    expected = {
        'id': 'review73-117-silent-source-omits-audio',
        'source_hash': SOURCE_HASHES['local-card-117'],
        'source_has_audio': False,
        'source_node': '269',
        'audio_ports_omitted': [['219', _117_AUDIO_PORT], ['190', 'audio'], ['289', 'audio']],
        'removed_node': _117_AUDIO_NODE,
    }
    if (not isinstance(state, dict) or spec.get('source_hash') != expected['source_hash'] or state != expected
            or type(state.get('source_has_audio')) is not bool):
        raise ReviewedRepairError('无音轨素材的执行记录已改变，需要重新审查。')
    return True


def preserve_117_source_audio(spec, graph, *, source_has_audio):
    """Omit optional audio only for a positively inspected silent 117 source.

    The server supplies a real source-stream inspection, never an absent or
    failed probe treated as False. With sound the reviewed graph is unchanged.
    Saved silent jobs require exact metadata and links for idempotent rerun.
    """
    if spec.get('id') != 'local-card-117':
        return None
    if type(source_has_audio) is not bool:
        raise ReviewedRepairError('无法确认原视频是否含音轨，不能猜测音频分支。')
    candidate = copy.deepcopy(graph)
    silent = _117_silent_state(candidate, spec)
    if source_has_audio and silent:
        raise ReviewedRepairError('已记录无音轨的任务不能自动恢复为有声分支。')
    # This verifies the full source/visual/compiler/save contract atomically,
    # including the precise silent state, without rebuilding unrelated inputs.
    apply_reviewed_repairs(candidate, spec)
    if candidate != graph:
        raise ReviewedRepairError('视频换装保存适配尚未完成，不能单独猜测音频路径。')
    if source_has_audio:
        return None
    evidence = {
        'id': 'review73-117-silent-source-omits-audio',
        'source_hash': SOURCE_HASHES['local-card-117'],
        'source_has_audio': False,
        'source_node': '269',
        'audio_ports_omitted': [['219', _117_AUDIO_PORT], ['190', 'audio'], ['289', 'audio']],
        'removed_node': _117_AUDIO_NODE,
    }
    if silent:
        return copy.deepcopy(evidence)
    # Current installed H3 declares ref_video_audios optional autogrow min=0;
    # the reviewed graph has no separate selector/count. Removing its sole
    # dynamic AUDIO socket is the empty set, not a fabricated silent track.
    expected = [('219', _117_AUDIO_PORT), (_117_AUDIO_NODE, 'audio')]
    actual = [(nid, key) for nid, value in candidate.items()
              for key, source in value.get('inputs', {}).items() if source == ['269', 2]]
    if sorted(actual) != sorted(expected):
        raise ReviewedRepairError('原视频音轨出现未审查的消费者。')
    for nid, key in evidence['audio_ports_omitted']:
        expected_link = ['269', 2] if nid == '219' else [_117_AUDIO_NODE, 0]
        if candidate[nid]['inputs'].get(key) != expected_link:
            raise ReviewedRepairError('无音轨适配未匹配已审音频端口。')
        del candidate[nid]['inputs'][key]
    consumers = [(nid, key) for nid, value in candidate.items()
                 for key, source in value.get('inputs', {}).items()
                 if isinstance(source, list) and len(source) == 2 and source[0] == _117_AUDIO_NODE]
    if consumers:
        raise ReviewedRepairError('原声裁剪节点仍有未审查的消费者。')
    del candidate[_117_AUDIO_NODE]
    candidate['269'].setdefault('_meta', {})[_117_AUDIO_STATE] = copy.deepcopy(evidence)
    # Recheck the adapted state before replacing the caller's graph.
    verified = copy.deepcopy(candidate)
    apply_reviewed_repairs(verified, spec)
    if verified != candidate:
        raise ReviewedRepairError('无音轨适配不能稳定重放。')
    graph.clear()
    graph.update(candidate)
    return evidence


def apply_reviewed_repairs(graph, spec, *, for_template=False):
    """Mutate only matched execution graphs; return non-secret repair evidence.

    All guards run against a temporary copy before changing the caller's graph,
    so a later mismatch cannot leave half of a repair applied. Idempotence also
    covers already-pruned saved job graphs used by rerun.
    """
    wid = spec.get('id')
    if wid in H3_DURATION_CONTRACTS:
        return preserve_h3_duration(graph, spec)
    if wid not in SOURCE_HASHES:
        return []
    if spec.get('source_hash') != SOURCE_HASHES[wid]:
        raise ReviewedRepairError('工作流来源已改变，需要重新审查执行修复后再生成。')
    candidate = copy.deepcopy(graph)
    evidence = []

    def node(nid, cls, **links):
        actual = candidate.get(nid, {})
        if actual.get('class_type') != cls or any(actual.get('inputs', {}).get(key) != value for key, value in links.items()):
            raise ReviewedRepairError(f'工作流执行修复未匹配节点 {nid}，请重新核对来源和连线。')
        return actual['inputs']

    def change(nid, key, allowed, value, repair_id):
        before = candidate[nid]['inputs'].get(key)
        if not any(before == old and type(before) is type(old) for old in allowed):
            raise ReviewedRepairError(f'工作流执行修复未匹配节点 {nid} 的 {key}。')
        entry = {'id': repair_id, 'node': nid, 'input': key, 'from': before, 'to': value}
        metadata = candidate[nid].setdefault('_meta', {})
        recorded = metadata.setdefault('yingxu_execution_repairs', [])
        if not any(item.get('id') == repair_id for item in recorded):
            recorded.append(copy.deepcopy(entry))
        evidence.append(entry)
        candidate[nid]['inputs'][key] = copy.deepcopy(value)

    if wid == 'local-card-33':
        if spec.get('outputs')!=['18']:
            raise ReviewedRepairError('图像描述输出绑定已经变化，请重新审查。')
        api=node('29','RH_LLMAPI_NODE',ref_image=['54',0])
        # Preserve explicit user API selections, including on a saved rerun.
        # Only the reviewed unavailable owner-default alias receives the
        # same-account model already proven by workflow 34. No key is copied.
        if not candidate['29'].get('_meta',{}).get('yingxu_custom_api_profile'):
            _, old_model, new_model = OWNER_DEFAULT_MODELS[wid]
            change('29','model',(old_model,new_model),new_model,
                   'review73-unavailable-owner-model-alias')

    if wid in OWNER_GROK_OUTPUTS:
        api_id, unavailable_alias, replacement = OWNER_DEFAULT_MODELS[wid]
        outputs = OWNER_GROK_OUTPUTS[wid]
        if spec.get('outputs') != outputs:
            raise ReviewedRepairError('已审查的默认模型输出绑定已改变，请重新核对。')
        if wid == 'local-card-0':
            api = node('577', 'RH_LLMAPI_NODE', ref_image=['189', 0])
            node('189', 'LoadImage')
            node('576', 'easy showAnything', anything=['577', 0])
            node('261:3', 'CLIPTextEncode', text=['576', 0], clip=['261:9', 0])
            node('246', 'SaveVideo', video=['245', 0])
            node('292', 'SaveVideo', video=['291:80', 0])
        elif wid == 'local-card-32':
            api = node('31', 'RH_LLMAPI_NODE', ref_image=['7', 0])
            node('7', 'LoadImage')
            node('38', 'easy showAnything', anything=['31', 0])
        else:
            from anime_batch_protocol import ROLE_NODE, PROMPT_NODE
            api = node('146', 'RH_LLMAPI_NODE', ref_image=['73', 0])
            if api.get('role') not in (['83', 0], [ROLE_NODE, 0]):
                raise ReviewedRepairError('动漫套图的角色输入已改变，请重新核对。')
            node('73', 'LayerUtility: ImageScaleByAspectRatio V2', image=['84', 0])
            node('84', 'LoadImage')
            split = node('87', 'TextSplitByDelimiter')
            if split.get('text') not in (['146', 0], [PROMPT_NODE, 0]):
                raise ReviewedRepairError('动漫套图的拆分输入已改变，请重新核对。')
            node('92', 'ShowText|pysssss', text=['87', 0])
            node('45', 'TextEncodeQwenImageEditPlusAdvance_lrzjason', prompt=['92', 0])
            node('38', 'KSampler', positive=['45', 0], latent_image=['45', 1])
            node('60', 'VAEDecode', samples=['38', 0])
            node('64', 'SaveImage', images=['60', 0])
        required_fields = {'api_baseurl', 'api_key', 'model', 'prompt',
                           'ref_image', 'role', 'seed', 'temperature'}
        if set(api) != required_fields or not isinstance(api.get('prompt'), str):
            raise ReviewedRepairError('已审查的默认模型 API 协议已变化，请重新核对。')
        # Workflow 81 completed with grok-4.6 using the exact registered RH
        # protocol and the same owner host/key. Replace only source defaults;
        # user-selected API profiles, including unavailable choices, survive.
        if not candidate[api_id].get('_meta', {}).get('yingxu_custom_api_profile'):
            if api.get('api_baseurl') != 'https://api.apilio.ai/v1':
                raise ReviewedRepairError('已审查的默认模型服务地址已改变，请重新核对。')
            change(api_id, 'model', (unavailable_alias, replacement), replacement,
                   'review73-unavailable-owner-grok-alias')

    if wid == 'local-card-93':
        if spec.get('outputs') != ['48']:
            raise ReviewedRepairError('图像编辑的输出绑定已经变化，请重新审查后接入。')
        prompt = node('71', 'CR Prompt Text').get('prompt')
        if not isinstance(prompt, str):
            raise ReviewedRepairError('图像编辑描述没有已确认的文字输入。')
        node('1', 'CLIPLoader')
        node('2', 'VAELoader')
        node('3', 'ModelSamplingAuraFlow', model=['79', 0])
        node('4', 'CFGNorm', model=['3', 0])
        node('8', 'LoadImage')
        node('16', 'ImageScaleToTotalPixels', image=['8', 0])
        node('103', 'LayerUtility: ImageScaleByAspectRatio V2', image=['16', 0])
        node('5', 'VAEEncode', pixels=['103', 0], vae=['2', 0])
        encoding_repair='review73-qwen2511-reference-encoding'
        for nid in ('10','13'):
            encoder=candidate.get(nid,{})
            links={'clip':['1',0],'vae':['2',0]}
            if nid=='10':links['prompt']=['82',0]
            if encoder.get('class_type')=='TextEncodeQwenImageEdit':
                node(nid,'TextEncodeQwenImageEdit',image=['103',0],**links)
            elif (encoder.get('class_type')=='TextEncodeQwenImageEditPlus' and
                  any(record.get('id')==encoding_repair and record.get('input')=='class_type' and
                      record.get('from')=='TextEncodeQwenImageEdit' and record.get('to')=='TextEncodeQwenImageEditPlus'
                      for record in encoder.get('_meta',{}).get('yingxu_execution_repairs',[]))):
                node(nid,'TextEncodeQwenImageEditPlus',image1=['103',0],**links)
            else:
                raise ReviewedRepairError('图像编辑的参考编码器未匹配已审查路径。')
        node('50', 'Seed (rgthree)')
        node('20', 'KSampler', model=['4', 0], seed=['50', 0],
             positive=['10', 0], negative=['13', 0], latent_image=['5', 0])
        node('15', 'VAEDecode', samples=['20', 0], vae=['2', 0])
        node('48', 'SaveImage', images=['15', 0])
        preview = node('82', 'ShowText|pysssss')
        repair_id = 'review73-explicit-english-description'
        records = candidate['82'].get('_meta', {}).get('yingxu_execution_repairs', [])
        direct_recorded = any(isinstance(item, dict) and item.get('id') == repair_id and
                              item.get('node') == '82' and item.get('input') == 'text' and
                              item.get('from') == ['76', 0] and item.get('to') == ['71', 0]
                              for item in records)
        language_field = next((field for field in spec.get('controls', [])
                               if field.get('id') == '76:from_translate'), None)
        if language_field is not None:
            options = [item.get('value') if isinstance(item, dict) else item
                       for item in language_field.get('options', [])]
            if (language_field.get('targets') != [{'node': '76', 'input': 'from_translate'}] or
                    tuple(options) != DESCRIPTION_LANGUAGES or
                    language_field.get('value') not in DESCRIPTION_LANGUAGES):
                raise ReviewedRepairError('描述语言的公开控件与实际翻译字段不一致。')
        if '76' in candidate:
            language = node('76', 'DeepTranslatorTextNode', text=['71', 0],
                            to_translate='english', service='GoogleTranslator [free]',
                            add_proxies=False, proxies='', auth_data='').get('from_translate')
        elif direct_recorded and preview.get('text') == ['71', 0]:
            # The saved direct-English graph has correctly pruned its unused
            # translator. Only our recorded original-to-direct link permits it.
            language = 'english'
        else:
            raise ReviewedRepairError('描述翻译链已改变，不能自动猜测输入路径。')
        if language not in DESCRIPTION_LANGUAGES or (language_field is None and language != 'auto'):
            raise ReviewedRepairError('请选择已经审查的描述语言。')
        if language == 'english':
            if not prompt.strip():
                raise ReviewedRepairError('请填写英文图像修改描述后再生成。')
            allowed = (['76', 0], ['71', 0]) if direct_recorded else (['76', 0],)
            change('82', 'text', allowed, ['71', 0], repair_id)
        elif preview.get('text') != ['76', 0]:
            raise ReviewedRepairError('中文或自动翻译必须保留已确认的翻译路径。')

        # The actual 2511 base must use its matching, already-installed
        # acceleration/conditioning setup. Do not download or silently substitute
        # a different base model. Source images, edit text and random seed stay.
        node('78','UNETLoader',unet_name='qwen/qwen_image_edit_2511_fp8mixed.safetensors',weight_dtype='default')
        node('79','LoraLoaderModelOnly',model=['78',0],strength_model=1)
        change('79','lora_name',('qwen/Qwen-Image-Edit-Lightning-8steps-V1.0.safetensors',
               'qwen/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors'),
               'qwen/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors',
               'review73-qwen2511-matching-lightning')
        change('20','steps',(8,4),4,'review73-qwen2511-four-step-sampling')
        change('20','cfg',(2.5,1),1,'review73-qwen2511-distilled-guidance')
        for nid in ('10','13'):
            encoder=candidate[nid]
            if encoder['class_type']=='TextEncodeQwenImageEdit':
                entry={'id':encoding_repair,'node':nid,'input':'class_type',
                       'from':'TextEncodeQwenImageEdit','to':'TextEncodeQwenImageEditPlus',
                       'reference_port':{'from':'image','to':'image1','value':['103',0]}}
                encoder.setdefault('_meta',{}).setdefault('yingxu_execution_repairs',[]).append(copy.deepcopy(entry))
                encoder['inputs']['image1']=encoder['inputs'].pop('image')
                encoder['class_type']='TextEncodeQwenImageEditPlus'
                evidence.append(entry)

    if wid == 'local-card-5':
        if spec.get('outputs') != ['395']:
            raise ReviewedRepairError('视频编辑的输出绑定已经变化，请重新审查后接入。')
        node('374', 'INTConstant', value=24)
        frames = node('378', 'INTConstant').get('value')
        if type(frames) is not int or frames < 0:
            raise ReviewedRepairError('视频编辑的处理帧数未匹配已确认的非负整数。')
        node('394', 'Evaluate Integers', python_expression='a+99999 if a<1 else b',
             a=['378', 0], b=['378', 0], c=0)
        node('373', 'SimpleMath+', value='a+3', a=['394', 0])
        node('399', 'VHS_LoadVideo', force_rate=['374', 0],
             frame_load_cap=['373', 0], select_every_nth=1)
        node('368', 'VHS_VideoInfoLoaded', video_info=['399', 3])
        node('415', 'LayerUtility: ImageScaleByAspectRatio V2', image=['399', 0])
        node('410', 'BerniniConditioning', source_video=['415', 0],
             length=['368', 1], width=['415', 3], height=['415', 4])
        node('386', 'KSamplerAdvanced', positive=['410', 0], negative=['410', 1],
             latent_image=['410', 2])
        node('407', 'KSamplerAdvanced', positive=['410', 0], negative=['410', 1],
             latent_image=['386', 0])
        node('392', 'VAEDecode', samples=['407', 0], vae=['380', 0])
        node('393', 'GetImageRangeFromBatch', images=['392', 0],
             start_index=0, num_frames=['394', 0])
        node('395', 'VHS_VideoCombine', images=['393', 0], pingpong=False,
             audio=['399', 2])
        # Use the registered FLOAT loaded-FPS output, rather than introducing
        # another fixed literal or an INT-to-FLOAT connection. The original
        # 24-FPS loader and seconds-to-frames control keep their exact meaning.
        change('395', 'frame_rate', (8, ['368', 0]), ['368', 0],
               'review73-preserve-bernini-video-playback-rate')

    if wid == 'local-card-40':
        if spec.get('outputs') != ['40', '42']:
            raise ReviewedRepairError('视频编辑的输出绑定已经变化，请重新审查后接入。')
        node('13', 'easy float', value=16)
        node('8', 'easy convertAnything', **{'*': ['13', 0], 'output_type': 'int'})
        duration = node('15', 'Evaluate Integers', python_expression='a*b+1',
                        b=['8', 0], c=0).get('a')
        if duration == ['16', 0]:
            duration = node('16', 'easy int').get('value')
        if (type(duration) not in (int, float) or not 0 <= duration <= 48000 or
                int(duration) != duration):
            raise ReviewedRepairError('视频编辑的参考时长未匹配已确认的整数秒数。')
        node('27', 'VHS_LoadVideo', force_rate=['13', 0],
             frame_load_cap=['15', 0], select_every_nth=1)
        selected = node('17', 'ImageFromBatch', image=['27', 0], batch_index=0).get('length')
        length = node('33', 'BerniniStudio', source_video=['38', 0],
                      width=['38', 3], height=['38', 4]).get('length')
        if selected != length:
            raise ReviewedRepairError('视频编辑的参考帧数与生成帧数绑定已经变化。')
        if selected == ['32', 0]:
            selected = node('32', 'PrimitiveInt').get('value')
        if (type(selected) not in (int, float) or not 1 <= selected <= 4096 or
                int(selected) != selected or (selected - 1) % 4 != 0):
            raise ReviewedRepairError('视频编辑的生成帧数未匹配已确认的 4n+1 帧数。')
        node('38', 'LayerUtility: ImageScaleByAspectRatio V2', image=['17', 0])
        node('26', 'SamplerCustom', positive=['33', 0], negative=['33', 1],
             latent_image=['33', 2])
        node('31', 'SamplerCustom', positive=['33', 0], negative=['33', 1],
             latent_image=['26', 0])
        node('18', 'VAEDecode', samples=['31', 0], vae=['5', 0])
        node('20', 'ImageConcanate', image1=['38', 0], image2=['18', 0],
             direction='right', match_image_size=True)
        node('41', 'ImageConcanate', image1=['20', 0], image2=['36', 0],
             direction='down', match_image_size=True)
        for saver, result in (('40', '18'), ('42', '41')):
            node(saver, 'VHS_VideoCombine', images=[result, 0], pingpong=False,
                 audio=['27', 2])
            # Preserve the user's selected frame count; only playback rate is
            # shared with the exact FLOAT source already used by the loader.
            change(saver, 'frame_rate', (8, ['13', 0]), ['13', 0],
                   'review73-preserve-bernini-video-playback-rate')

    if wid == 'local-card-41':
        if spec.get('outputs') != ['443']:
            raise ReviewedRepairError('视频编辑的输出绑定已经变化，请重新审查后接入。')
        node('428', 'easy float', value=16)
        node('426', 'easy convertAnything', **{'*': ['428', 0], 'output_type': 'int'})
        duration = node('427', 'Evaluate Integers', python_expression='a*b+1',
                        b=['426', 0], c=0).get('a')
        if duration == ['429', 0]:
            duration = node('429', 'easy int').get('value')
        # build binds the visible integer seconds directly into 427.a; pruning
        # can then remove the original 429 constant. Both forms are reviewed.
        if (type(duration) not in (int, float) or not 0 <= duration <= 48000 or
                int(duration) != duration):
            raise ReviewedRepairError('视频编辑的时长绑定未匹配已确认的整数秒数。')
        node('425', 'VHS_LoadVideo', force_rate=['428', 0],
             frame_load_cap=['427', 0], select_every_nth=1)
        node('430', 'GetImageSizeAndCount', image=['425', 0])
        node('434', 'LayerUtility: ImageScaleByAspectRatio V2', image=['430', 0])
        node('111', 'GetImageSize', image=['434', 0])
        node('387', 'BerniniConditioning', source_video=['434', 0],
             length=['111', 2], width=['111', 0], height=['111', 1])
        node('384', 'SamplerCustom', positive=['387', 0], negative=['387', 1],
             latent_image=['387', 2])
        node('386', 'SamplerCustom', positive=['387', 0], negative=['387', 1],
             latent_image=['384', 0])
        node('382', 'VAEDecode', samples=['386', 0], vae=['377', 0])
        node('443', 'VHS_VideoCombine', images=['382', 0], pingpong=False,
             audio=['425', 2])
        change('443', 'frame_rate', (8, ['428', 0]), ['428', 0],
               'review73-preserve-bernini-video-playback-rate')

    if wid in VIDEO_CHAINS:
        loader, saver, result, result_class = VIDEO_CHAINS[wid]
        node(loader, 'VHS_LoadVideo', force_rate=24, select_every_nth=1)
        node(result, result_class)
        node(saver, 'VHS_VideoCombine', images=[result, 0], pingpong=False)
        if wid in RESIZE_BRANCHES:
            size, threshold, compare, resize, switch, upscale = RESIZE_BRANCHES[wid]
            node(size, 'easy imageSizeByLongerSide', image=[loader, 0])
            node(threshold, 'ImpactInt')
            node(compare, 'ImpactCompare', cmp='a >= b', a=[size, 0], b=[threshold, 0])
            node(resize, 'LayerUtility: ImageScaleByAspectRatio V2', image=[loader, 0])
            node(switch, 'easy ifElse', boolean=[compare, 0], on_true=[resize, 0], on_false=[loader, 0])
            node(upscale, result_class, frames=[switch, 0])
        if wid == 'local-card-122':
            node('27', 'GetImageSizeAndCount', image=['25', 0])
            node('14', 'SeedVR2LoadDiTModel')
            node('13', 'SeedVR2LoadVAEModel')
            node('10', 'SeedVR2VideoUpscaler', image=['27', 0], dit=['14', 0], vae=['13', 0], prepend_frames=0)
        change(saver, 'frame_rate', (8, 24), 24, 'review73-preserve-video-playback-rate')

    if wid == 'local-card-119':
        node('493', 'easy imageSizeByLongerSide', image=['507', 0])
        node('496', 'ImpactInt', value=1500)
        node('500', 'ImpactCompare', cmp='a >= b', a=['493', 0], b=['496', 0])
        node('499', 'LayerUtility: ImageScaleByAspectRatio V2', image=['507', 0])
        node('510', 'easy ifElse', boolean=['500', 0], on_true=['499', 0], on_false=['507', 0])
        node('521', 'GetImageSizeAndCount', image=['510', 0])
        node('519', 'ImpactInt', value=360)
        node('517', 'MathExpression|pysssss', a=['521', 3], b=['519', 0])
        node('488', 'easy forLoopStart', total=['517', 0], initial_value1=['510', 0])
        node('514', 'VHS_SplitImages', images=['488', 2])
        node('512', 'GetImageSizeAndCount', image=['514', 0])
        node('513', 'GetImageSizeAndCount', image=['514', 2])
        node('531', 'FlashVSRNode', frames=['512', 0])
        node('522', 'GetImageSizeAndCount', image=['531', 0])
        accumulated = node('515', 'easy batchAnything', any_1=['488', 3])
        if accumulated.get('any_2') == ['527', 0]:
            node('525', 'Pick From Batch (mtb)', image=['522', 0], from_direction='end', count=1)
            node('523', 'RepeatImageBatch', image=['525', 0], amount=3)
            node('526', 'easy batchAnything', any_1=['522', 0], any_2=['523', 0])
            node('527', 'GetImageSizeAndCount', image=['526', 0])
        node('503', 'easy forLoopEnd', flow=['488', 0], initial_value1=['513', 0], initial_value2=['515', 0])
        node('516', 'GetImageSizeAndCount', image=['503', 1])
        node('530', 'LayerUtility: PurgeVRAM V2', anything=['516', 0])
        change('514', 'split_index', (0, ['519', 0]), ['519', 0], 'review73-nonempty-flashvsr-chunks')
        change('517', 'expression', ('(a // b) + 1 ', '(a + b - 1) // b'), '(a + b - 1) // b', 'review73-exact-ceiling-chunk-count')
        change('515', 'any_2', (['527', 0], ['522', 0]), ['522', 0], 'review73-preserve-upscaled-frame-count')

    if wid == 'local-card-121':
        node('16', 'easy imageSizeByLongerSide', image=['15', 0])
        node('19', 'ImpactInt', value=1000)
        node('18', 'ImpactCompare', cmp='a >= b', a=['16', 0], b=['19', 0])
        node('20', 'LayerUtility: ImageScaleByAspectRatio V2', image=['15', 0])
        node('17', 'easy ifElse', boolean=['18', 0], on_true=['20', 0], on_false=['15', 0])
        node('13', 'ImpactInt', value=1000)
        node('14', 'easy compare', comparison='a >= b', b=['13', 0])
        node('6', 'ImpactInt', value=8)
        node('7', 'ImpactInt', value=12)
        node('12', 'easy ifElse', boolean=['14', 0], on_true=['6', 0], on_false=['7', 0])
        node('5', 'ImageUpscaleWithModelBatched', images=['17', 0], per_batch=['12', 0])
        nid = 'yingxu_review73_upscale_longest_side'
        if nid in candidate:
            node(nid, 'easy imageSizeByLongerSide', image=['17', 0])
        else:
            candidate[nid] = {'class_type': 'easy imageSizeByLongerSide', 'inputs': {'image': ['17', 0]},
                              '_meta': {'title': '待放大帧实际最长边'}}
        change('14', 'a', (['20', 0], [nid, 0]), [nid, 0], 'review73-scalar-upscale-batch-condition')
        # VHS_LoadVideo output slot 2 and VHS_VideoCombine.audio are both the
        # currently registered AUDIO protocol. Upscaling frames must not drop
        # the source soundtrack. Existing reviewed links remain idempotent;
        # a different audio source requires its own review.
        change('9', 'audio', (None, ['15', 2]), ['15', 2], 'review73-preserve-upscaled-video-audio')

    if wid == 'local-card-135':
        node('12', 'LoadImageListFromDir //Inspire')
        node('11', 'ImageListToBatch+', image=['12', 0])
        node('10', 'VHS_VideoCombine', images=['11', 0])
        field = next((field for field in spec.get('controls', []) if field.get('id') == '12:sort_method'), None)
        if field is not None:
            if field.get('targets') != [{'node': '12', 'input': 'sort_method'}] or field.get('value') not in SORT_METHODS:
                raise ReviewedRepairError('目录图片排列顺序的公开控件与执行绑定不一致。')
            selected = field['value'] if for_template else candidate['12']['inputs'].get('sort_method')
            if selected not in SORT_METHODS:
                raise ReviewedRepairError('请选择有效的目录图片排列顺序。')
            change('12', 'sort_method', SORT_METHODS, selected, 'review73-explicit-directory-image-order')
        # Old saved jobs have no visible ordering choice. Preserve their meaning.

    if wid == 'local-card-75':
        node('135', 'PrimitiveStringMultiline')
        node('52', 'LayerUtility: ImageScaleByAspectRatio V2', image=['15', 0])
        node('15', 'LoadImage')
        node('2', 'CLIPLoader')
        node('3', 'VAELoader')
        node('127', 'QwenMultiangleCameraNode', image=['52', 0])
        node('55', 'ShowText|pysssss', text=['127', 0])
        node('136', 'JoinStringMulti', inputcount=2, string_1=['55', 0], string_2=['135', 0],
             delimiter=' ', return_list=False)
        node('5', 'TextEncodeQwenImageEditPlus', prompt=['136', 0], clip=['2', 0], vae=['3', 0], image1=['52', 0])
        for conditioning, camera in (('62', '129'), ('95', '130'), ('105', '133'), ('115', '131'), ('125', '132')):
            node(camera, 'QwenMultiangleCameraNode', image=['52', 0])
            node(conditioning, 'TextEncodeQwenImageEditPlus', clip=['2', 0], vae=['3', 0], image1=['52', 0])
            joined = 'yingxu_review73_view_prompt_' + conditioning
            if joined in candidate:
                node(joined, 'JoinStringMulti', inputcount=2, string_1=[camera, 0], string_2=['135', 0],
                     delimiter=' ', return_list=False)
            else:
                candidate[joined] = {'class_type': 'JoinStringMulti',
                                     'inputs': {'inputcount': 2, 'string_1': [camera, 0],
                                                'string_2': ['135', 0], 'delimiter': ' ', 'return_list': False},
                                     '_meta': {'title': '视角补充描述'}}
            change(conditioning, 'prompt', ([camera, 0], [joined, 0]), [joined, 0],
                   'review73-all-views-receive-user-description')

    if wid == 'local-card-46':
        # The reviewed source leaves both forceInput target sockets unbound.
        # The compiler supplied the registered 512 defaults nevertheless;
        # ImagePadKJ then ignores the user's four padding values altogether.
        # Omit only these confirmed injected defaults, never an authored size.
        if spec.get('outputs') != ['5104', '5131']:
            raise ReviewedRepairError('视频扩图输出绑定已变化，请重新审查。')
        padding = node('5149', 'ImagePadKJ', image=['5141', 0], extra_padding=0,
                       pad_mode='color', color='0, 0, 0')
        allowed_keys = {'image', 'left', 'right', 'top', 'bottom', 'extra_padding',
                        'pad_mode', 'color', 'mask', 'target_width', 'target_height'}
        if set(padding) - allowed_keys or padding.get('mask') is not None:
            raise ReviewedRepairError('视频扩图输入已变化，请重新审查。')
        for side in ('left', 'right', 'top', 'bottom'):
            value = padding.get(side)
            if type(value) is not int or not 0 <= value <= 16384:
                raise ReviewedRepairError('视频扩图边距没有有效的已确认整数。')
        for key in ('target_width', 'target_height'):
            value = padding.get(key)
            if value is not None and not (type(value) is int and value == 512):
                raise ReviewedRepairError('视频扩图有未知目标尺寸，不能替换原有选择。')
        node('5155', 'PrimitiveFloat', value=24)
        custom_size={'custom_width':0,'custom_height':0}
        dimensions={field.get('id'):field for field in spec.get('controls',[])}
        reviewed_size=all(dimensions.get('5141:'+key,{}).get('targets')==[{'node':'5141','input':key}]
                          for key in ('custom_width','custom_height'))
        if reviewed_size:
            source_size=candidate.get('5141',{}).get('inputs',{})
            for key in custom_size:
                value=source_size.get(key)
                if (isinstance(value,bool) or not isinstance(value,(int,float)) or
                        not 0<=value<=8192 or value!=int(value)):
                    raise ReviewedRepairError('视频扩图的自定义输入尺寸无效。')
                custom_size[key]=int(value)
        node('5141', 'VHS_LoadVideo', force_rate=['5155', 0], frame_load_cap=['5166', 0],
             **custom_size, select_every_nth=1, format='AnimateDiff')
        count = node('5166', 'MathExpression|pysssss', expression='a*b', a=['5155', 0])
        if count.get('b') != ['5162', 0] and not (
                type(count.get('b')) in (int, float) and count['b'] >= 0):
            raise ReviewedRepairError('视频扩图时长来源已变化，请重新审查。')
        node('5167:5146', 'ResizeImageMaskNode', input=['5149', 0],
             resize_type='scale by multiplier', **{'resize_type.multiplier': 1}, scale_method='lanczos')
        node('5167:5147', 'ResizeImageMaskNode', input=['5167:5146', 0],
             resize_type='scale to multiple', **{'resize_type.multiple': 32}, scale_method='lanczos')
        node('5167:5114', 'GetImageSize', image=['5167:5147', 0])
        node('5167:5109', 'EmptyLTXVLatentVideo', width=['5167:5114', 0],
             height=['5167:5114', 1], length=['5167:5114', 2], batch_size=1)
        node('5167:5115', 'Switch image [Crystools]', on_true=['5167:5144', 0],
             on_false=['5167:5147', 0], boolean=['5167:5137', 0])
        node('5167:5118', 'LTXAddVideoICLoRAGuide', image=['5167:5115', 0],
             latent=['5167:5117', 0], positive=['5167:5125', 0], negative=['5167:5125', 1],
             vae=['5167:5139', 0])
        node('5167:5120', 'VHS_VideoInfo', video_info=['5141', 3])
        node('5167:5130', 'Switch image [Crystools]', on_true=['5167:5129', 0],
             on_false=['5167:5132', 0], boolean=['5167:5137', 0])
        node('5167:5133', 'ImageConcanate', image1=['5167:5130', 0],
             image2=['5167:5147', 0], direction='left', match_image_size=True)
        node('5104', 'VHS_VideoCombine', images=['5167:5130', 0],
             frame_rate=['5167:5120', 0], audio=['5141', 2])
        node('5131', 'VHS_VideoCombine', images=['5167:5133', 0],
             frame_rate=['5167:5120', 0], audio=['5141', 2])
        for key in ('target_width', 'target_height'):
            entry = {'id': 'review73-outpaint-source-padding-' + key, 'node': '5149',
                     'input': key, 'from': padding.get(key), 'to': 'omitted optional socket'}
            recorded = candidate['5149'].setdefault('_meta', {}).setdefault('yingxu_execution_repairs', [])
            if not any(item.get('id') == entry['id'] for item in recorded):
                recorded.append(copy.deepcopy(entry))
            evidence.append(entry)
            padding.pop(key, None)

    if wid == 'local-card-124':
        if spec.get('outputs')!=['65','34']:
            raise ReviewedRepairError('首尾帧输出绑定已变化，请重新审查。')
        # The failed receipt reaches WAN's fused fp16 linear through this
        # exact GGUF branch. Disable only its existing opt-in Torch setting;
        # keep weights, LoRAs, attention, conditioning and sampling intact.
        node('71','easy int',value=0)
        node('55','UnetLoaderGGUF',unet_name='smooth/Smooth Mix Wan 2.2 I2V v2.0 GGUF high.gguf')
        node('56','UnetLoaderGGUF',unet_name='smooth/Smooth Mix Wan 2.2 I2V v2.0 GGUF low.gguf')
        node('77','LoraLoaderModelOnly',model=['55',0])
        node('76','LoraLoaderModelOnly',model=['56',0])
        node('66','easy anythingIndexSwitch',index=['71',0],value0=['77',0])
        node('67','easy anythingIndexSwitch',index=['71',0],value0=['76',0])
        node('40','PathchSageAttentionKJ',model=['66',0])
        node('42','PathchSageAttentionKJ',model=['67',0])
        node('41','ModelPatchTorchSettings',model=['40',0])
        node('43','ModelPatchTorchSettings',model=['42',0])
        node('3','ModelSamplingSD3',model=['41',0])
        node('4','ModelSamplingSD3',model=['43',0])
        node('18','KSamplerAdvanced',model=['3',0],positive=['44',0],negative=['44',2],latent_image=['44',3])
        node('19','KSamplerAdvanced',model=['4',0],positive=['44',1],negative=['44',2],latent_image=['18',0])
        node('44','WanFirstMiddleLastFrameToVideo',start_image=['15',0],end_image=['48',0])
        for nid in ('41','43'):
            change(nid,'enable_fp16_accumulation',(True,False),False,'review73-gguf-fused-linear-compatibility')
        node('60','WanFirstLastFrameToVideo',start_image=['15',0],end_image=['48',0])
        node('64','KSamplerAdvanced',model=['3',0],positive=['60',0],negative=['60',1],
             latent_image=['60',2],steps=6,start_at_step=0,add_noise='enable',return_with_leftover_noise='enable')
        low=node('61','KSamplerAdvanced',model=['4',0],positive=['60',0],negative=['60',1],
                 latent_image=['64',0],steps=6,start_at_step=3,add_noise='disable',return_with_leftover_noise='disable')
        node('62','VAEDecode',samples=['61',0])
        node('65','VHS_VideoCombine',images=['62',0],frame_rate=16)
        change('64','end_at_step',(0,3),low['start_at_step'],
               'review73-firstlast-continuous-noise-schedule')

    if wid in ('local-card-68', 'local-card-117'):
        # This source compiler deliberately emits COMPILATION_ERROR instead
        # of a usable prompt. Keep the receipt visible, but block that text
        # before H3 conditioning; never interrupt another queued workflow.
        node('273','VisionAPIDirect',prompt=['270',0],system_prompt=['274',0])
        node('276','ShowText|pysssss',text=['273',0])
        node('265','Any Switch (rgthree)',any_01=['276',0],any_02=['270',0])
        node('253','ShowText|pysssss',text=['265',0])
        conditioning=node('219','MiniMaxH3ReferenceToVideo')
        if conditioning.get('ref_videos.ref_video_0')!=['272',0]:
            raise ReviewedRepairError('视频编辑的素材绑定已变化。')
        if wid == 'local-card-117':
            silent_source = _117_silent_state(candidate, spec)
            if spec.get('outputs') != ['290', '302']:
                raise ReviewedRepairError('视频换装的输出绑定已变化。')
            node('273','VisionAPIDirect',image=['264',0],video_frames=['272',0])
            node('264','ImpactMakeImageBatch',image1=['229:91',0])
            node('268','LoadImage')
            node('229:91','LayerUtility: If ',when_TRUE=['229:92',0],when_FALSE=['268',0])
            node('272','LayerUtility: ImageScaleByAspectRatio V2',image=['301',0])
            node('301','GetImageSizeAndCount',image=['269',0])
            node('269','VHS_LoadVideo')
            node('278','easy float')
            # Real duration controls may legitimately inline the expression's
            # a/b inputs. Their values do not affect the compiler-text guard.
            node('277','Evaluate Integers',python_expression='a*b+1')
            node('219','MiniMaxH3ReferenceToVideo',width=['271',1],height=['271',2],length=['271',3],
                 audio_vae=['238',0], **{'ref_images.ref_image_0':['229:91',0]})
            audio_refs = {key:value for key,value in conditioning.items()
                          if key == 'ref_video_audios' or key.startswith('ref_video_audios.')}
            if audio_refs != ({} if silent_source else {_117_AUDIO_PORT:['269',2]}):
                raise ReviewedRepairError('视频换装的原声参考绑定已变化。')
            node('271','GetImageSizeAndCount',image=['272',0])
            node('194','MiniMaxH3AVDecodeT8',av_latent=['206',0])
            node('206','SamplerCustomAdvanced',latent_image=['219',1])
            node('190','CreateVideo')
            node('302','SaveVideo',video=['190',0])
            node('288','ImageStitch',image2=['269',0])
            node('289','CreateVideo',images=['288',0])
            node('290','SaveVideo',video=['289',0])
            # H3 may pad a legal source-frame selection to its latent grid.
            # Save only the actual loader count, retaining source cadence and
            # the selected original soundtrack, not synthesized decoder audio.
            # Both solo and comparison outputs share this exact save contract.
            loaded='yingxu_review73_117_loaded_info'
            frames='yingxu_review73_117_selected_frames'
            audio='yingxu_review73_117_source_audio'
            save_nodes={
                loaded:{'class_type':'VHS_VideoInfoLoaded','inputs':{'video_info':['269',3]}},
                frames:{'class_type':'ImageFromBatch','inputs':{
                    'image':['194',0],'batch_index':0,'length':['269',1]}},
            }
            if not silent_source:
                save_nodes[audio]={'class_type':'TrimAudioDuration','inputs':{
                    'audio':['269',2],'start_index':0.0,'duration':[loaded,2]}}
            elif audio in candidate or any(value == ['269',2] for item in candidate.values()
                                           for value in item.get('inputs',{}).values()):
                raise ReviewedRepairError('无音轨素材仍连接了音频读取分支。')
            for nid,value in save_nodes.items():
                if nid in candidate:
                    node(nid,value['class_type'],**value['inputs'])
                    if candidate[nid]['inputs'] != value['inputs']:
                        raise ReviewedRepairError('视频换装的保存修复节点已变化。')
                else:
                    candidate[nid]={**value,'_meta':{'title':'保留已载入片段的时长与原声'}}
            change('190','images',(['194',0],[frames,0]),[frames,0],
                   'review73-117-save-selected-source-frames')
            change('288','image1',(['194',0],[frames,0]),[frames,0],
                   'review73-117-compare-selected-source-frames')
            for nid in ('190','289'):
                fps=candidate[nid]['inputs'].get('fps')
                if fps != [loaded,0] and not (type(fps) in (int,float) and 0 < fps < float('inf')):
                    raise ReviewedRepairError('视频换装的保存帧率来源已变化。')
                change(nid,'fps',(fps,[loaded,0]),[loaded,0],
                       'review73-117-save-loaded-source-cadence')
                if silent_source:
                    if 'audio' in candidate[nid]['inputs']:
                        raise ReviewedRepairError('无音轨素材仍连接了保存音轨。')
                else:
                    change(nid,'audio',(['194',1],[audio,0]),[audio,0],
                           'review73-117-save-selected-original-audio')
        guard='yingxu_review73_compiler_prompt'
        incoming=['253',0]
        injected={}
        if wid == 'local-card-117':
            # Check a trimmed copy only. The unchanged compiler response is
            # passed to conditioning when valid, preserving prose and spacing.
            injected.update({
                guard+'_trim':{'class_type':'StringTrim','inputs':{'string':['253',0],'mode':'Both'}},
                guard+'_length':{'class_type':'StringLength','inputs':{'string':[guard+'_trim',0]}},
                guard+'_nonempty_valid':{'class_type':'easy compare','inputs':{
                    'a':[guard+'_length',0],'b':0,'comparison':'a > 0'}},
                guard+'_nonempty':{'class_type':'easy blocker','inputs':{
                    'continue':[guard+'_nonempty_valid',0],'in':['253',0]}},
            })
            incoming=[guard+'_nonempty',0]
        injected.update({
            guard+'_error':{'class_type':'StringContains','inputs':{
                'string':['253',0],'substring':'COMPILATION_ERROR:','case_sensitive':False}},
            guard+'_valid':{'class_type':'easy compare','inputs':{
                'a':[guard+'_error',0],'b':False,'comparison':'a == b'}},
            guard:{'class_type':'easy blocker','inputs':{
                'continue':[guard+'_valid',0],'in':incoming}},
        })
        for nid,value in injected.items():
            if nid in candidate:
                node(nid,value['class_type'],**value['inputs'])
            else:
                candidate[nid]={**value,'_meta':{'title':'拒绝无效的编辑描述'}}
        change('219','prompt',(['253',0],[guard,0]),[guard,0],
               'review73-compiler-error-blocks-generation')

    if wid == 'local-card-80':
        batch_evidence = repair_anime_batch_protocol(spec, candidate)
        if batch_evidence:
            evidence.append(batch_evidence)
    graph.clear()
    graph.update(candidate)
    return evidence
