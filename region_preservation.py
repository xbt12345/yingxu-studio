"""Reviewed final compositing for uploaded-mask and tracked-mask edit graphs.

The sampler is left intact. Its edited region is composited over the original
RGB at the original image size, rather than trusting diffusion to preserve the
unselected pixels. This is an execution adaptation, visible in the saved graph.
"""
import copy


REGION_NODE = 'yingxu_region_preservation'
SOURCE_HASHES = {
    'local-card-51': '22850d24d702737845f1774c14f4c6af1bb0d0d99f8dc6397fb5963be21aea3d',
    'local-card-86': '922411c5bbd74ab1f0e2b0eae6c4bed3969e5f0726a48b4e1f47889cf92c6d97',
    'local-card-131': 'de18dc223d93c056c668a052589109440531871ae3e8fc50e93447fbdc1be9b5',
}

VIDEO_REGION_FIRST = 'yingxu_video_region_first'
VIDEO_REGION_REFINED = 'yingxu_video_region_refined'
VIDEO_REGION_SIZE = 'yingxu_video_region_size'
VIDEO_REGION_MASK_IMAGE = 'yingxu_video_region_mask_image'
VIDEO_REGION_MASK_SCALED = 'yingxu_video_region_mask_scaled'
VIDEO_REGION_MASK = 'yingxu_video_region_mask'


def _preserve_tracked_video_output(spec, graph):
    """Protect the raw tracked region, rather than the enlarged model guide.

    Both outputs keep their existing frame batches, geometry, FPS and audio.
    The refinement mask is resized to the actual destination image dimensions;
    no user-selectable edge length is frozen in this adaptation.
    """
    if spec.get('source_hash') != SOURCE_HASHES['local-card-51']:
        raise ValueError('局部视频编辑的来源已经变化，请重新审查后接入。')

    def matches(node, class_type, **inputs):
        current = graph.get(node, {})
        return (current.get('class_type') == class_type and
                all(current.get('inputs', {}).get(key) == value
                    for key, value in inputs.items()))

    confirmed = (
        spec.get('outputs') == ['939', '948', '949', '955', '1048', '1049'] and
        matches('1084', 'VHS_LoadVideo') and
        isinstance(graph.get('1084', {}).get('inputs', {}).get('video'), str) and
        matches('1064', 'LayerUtility: ImageScaleByAspectRatio V2',
                image=['1084', 0], aspect_ratio='original', fit='crop',
                round_to_multiple='32', scale_to_side='longest') and
        matches('1058', 'ImageScaleBy', image=['1064', 0], scale_by=0.5) and
        matches('1057', 'LTXVPreprocess', image=['1058', 0]) and
        matches('1081', 'GetImageRangeFromBatch', images=['1057', 0],
                start_index=0, num_frames=1) and
        matches('1095', 'PointsEditor', bg_image=['1081', 0], normalize=False) and
        matches('1062', 'SeCVideoSegmentation', frames=['1057', 0],
                positive_points=['1095', 0], negative_points=['1095', 1]) and
        matches('1080', 'GrowMaskWithBlur', mask=['1062', 0]) and
        matches('1069', 'BlockifyMask', masks=['1080', 0]) and
        matches('1063', 'ImageCompositeFromMaskBatch+',
                image_from=['1057', 0], mask=['1069', 0]) and
        matches('989', 'VAEDecode', samples=['1004', 2]) and
        matches('1004', 'LTXVCropGuides', latent=['1003', 0]) and
        matches('1003', 'LTXVSeparateAVLatent', av_latent=['1009', 0]) and
        matches('1009', 'SamplerCustomAdvanced') and
        matches('968', 'VAEDecodeTiled', samples=['966', 2]) and
        matches('966', 'LTXVCropGuides', latent=['965', 0]) and
        matches('965', 'LTXVSeparateAVLatent', av_latent=['972', 0]) and
        matches('972', 'SamplerCustomAdvanced', latent_image=['974', 0]) and
        matches('974', 'LTXVConcatAVLatent', video_latent=['988', 2]) and
        matches('988', 'LTXVAddGuideMulti', latent=['980', 0]) and
        matches('980', 'LTXVLatentUpsampler', samples=['1004', 2],
                upscale_model=['1083', 0]) and
        matches('1083', 'LatentUpscaleModelLoader',
                model_name='ltx-2.3-spatial-upscaler-x2-1.0.safetensors') and
        matches('953', 'CreateVideo', fps=['1102', 0]) and
        matches('944', 'CreateVideo', fps=['1102', 0]) and
        matches('949', 'SaveVideo', video=['953', 0]) and
        matches('948', 'SaveVideo', video=['944', 0]) and
        matches('955', 'VHS_VideoCombine', images=['962', 0], frame_rate=['1102', 0]) and
        matches('939', 'VHS_VideoCombine', images=['945', 0], frame_rate=['1102', 0]) and
        matches('961', 'ImageConcanate', image1=['1057', 0], image2=['1063', 0]) and
        matches('942', 'ImageConcanate', image1=['1057', 0], image2=['1063', 0]) and
        matches('962', 'ImageConcanate', image1=['961', 0]) and
        matches('945', 'ImageConcanate', image1=['942', 0]) and
        matches('1033', 'MaskToImage', mask=['1062', 0]) and
        matches('1048', 'VHS_VideoCombine', images=['1033', 0]) and
        matches('1049', 'VHS_VideoCombine', images=['1063', 0]))

    added = {
        VIDEO_REGION_FIRST: {'class_type': 'ImageCompositeMasked', 'inputs': {
            'destination': ['1058', 0], 'source': ['989', 0],
            'mask': ['1062', 0], 'x': 0, 'y': 0, 'resize_source': False}},
        VIDEO_REGION_SIZE: {'class_type': 'GetImageSize+',
                            'inputs': {'image': ['1064', 0]}},
        VIDEO_REGION_MASK_IMAGE: {'class_type': 'MaskToImage',
                                  'inputs': {'mask': ['1062', 0]}},
        VIDEO_REGION_MASK_SCALED: {'class_type': 'ImageScale', 'inputs': {
            'image': [VIDEO_REGION_MASK_IMAGE, 0],
            'width': [VIDEO_REGION_SIZE, 0], 'height': [VIDEO_REGION_SIZE, 1],
            'upscale_method': 'nearest-exact', 'crop': 'disabled'}},
        VIDEO_REGION_MASK: {'class_type': 'ImageToMask', 'inputs': {
            'image': [VIDEO_REGION_MASK_SCALED, 0], 'channel': 'red'}},
        VIDEO_REGION_REFINED: {'class_type': 'ImageCompositeMasked', 'inputs': {
            'destination': ['1064', 0], 'source': ['968', 0],
            'mask': [VIDEO_REGION_MASK, 0], 'x': 0, 'y': 0,
            'resize_source': False}},
    }
    redirects = [('953', 'images', ['989', 0], [VIDEO_REGION_FIRST, 0]),
                 ('944', 'images', ['968', 0], [VIDEO_REGION_REFINED, 0]),
                 ('962', 'image2', ['989', 0], [VIDEO_REGION_FIRST, 0]),
                 ('945', 'image2', ['968', 0], [VIDEO_REGION_REFINED, 0])]
    original = (all(node not in graph for node in added) and
                all(graph.get(node, {}).get('inputs', {}).get(key) == old
                    for node, key, old, _ in redirects))
    adapted = (all(graph.get(node) == value for node, value in added.items()) and
               all(graph.get(node, {}).get('inputs', {}).get(key) == new
                   for node, key, _, new in redirects))
    if not confirmed or not (original or adapted):
        raise ValueError('局部视频编辑的蒙版或输出绑定已经变化，请重新审查后接入。')

    graph.update(copy.deepcopy(added))
    for node, key, _, new in redirects:
        graph[node]['inputs'][key] = copy.deepcopy(new)
    return {'operation': 'preserve-unselected-tracked-video-region',
            'nodes': [VIDEO_REGION_FIRST, VIDEO_REGION_REFINED],
            'source_slot': '1084', 'mask_node': '1062',
            'output_nodes': ['949', '948'],
            'output_size': 'existing-first-and-refined-video-sizes',
            'boundary': 'pre-encode unselected RGB; video encoding remains lossy'}


def preserve_region_output(spec, graph):
    workflow_id = spec.get('id')
    if workflow_id == 'local-card-51':
        return _preserve_tracked_video_output(spec, graph)
    if workflow_id not in ('local-card-86', 'local-card-131'):
        return None
    if spec.get('source_hash') != SOURCE_HASHES[workflow_id]:
        raise ValueError('局部编辑的来源已经变化，请重新审查后接入。')

    def matches(node, class_type, **inputs):
        current = graph.get(node, {})
        return (current.get('class_type') == class_type and
                all(current.get('inputs', {}).get(key) == value
                    for key, value in inputs.items()))

    if workflow_id == 'local-card-86':
        loader, output, decoded = '91', '46', ['88:105', 0]
        confirmed = (matches(loader, 'LoadImage') and
                     matches('695', 'MaskPreview', mask=[loader, 1]) and
                     matches('703', 'LayerUtility: ImageScaleByAspectRatio V2',
                             image=[loader, 0], mask=['695', 0],
                             aspect_ratio='original') and
                     matches('88:87', 'AnimaLLLiteApply',
                             image=['703', 0], mask=['703', 1]) and
                     matches('88:105', 'VAEDecode'))
    else:
        loader, output, decoded = '134', '174', ['140', 0]
        confirmed = (matches(loader, 'LoadImage') and
                     matches('136', 'ZImageFunControlnet',
                             inpaint_image=[loader, 0], mask=[loader, 1]) and
                     matches('140', 'VAEDecode'))
    expected = {
        'class_type': 'ImageCompositeMasked',
        'inputs': {'destination': [loader, 0], 'source': copy.deepcopy(decoded),
                   'mask': [loader, 1], 'x': 0, 'y': 0, 'resize_source': True},
    }
    already_preserved = (graph.get(REGION_NODE) == expected and
                         matches(output, 'SaveImage', images=[REGION_NODE, 0]))
    confirmed = (confirmed and spec.get('outputs') == [output] and
                 (matches(output, 'SaveImage', images=decoded) or already_preserved) and
                 isinstance(graph[loader].get('inputs', {}).get('image'), str))
    if not confirmed or (REGION_NODE in graph and not already_preserved):
        raise ValueError('局部编辑的输出绑定已经变化，请重新审查后接入。')

    graph[REGION_NODE] = expected
    graph[output]['inputs']['images'] = [REGION_NODE, 0]
    return {'operation': 'preserve-unselected-region', 'node': REGION_NODE,
            'source_slot': loader, 'output_node': output,
            'output_size': 'original-image'}
