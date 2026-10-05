"""Expose the portrait size decision only on its reviewed latent branch."""
from copy import deepcopy

PORTRAIT_SIZE_SOURCE_HASH = 'de8594834f1330083470075bacc9cd796e7b9bc767bba5e16d2fc269d1919642'
PORTRAIT_SIZE_SWITCH_ID = '485:switch'
PORTRAIT_SIZE_TARGETS = [{'node': 'sub0/468', 'input': 'switch'}]
PORTRAIT_SIZE_PROOF = {
    'kind': 'qwen21-latent-choice',
    'referenceInput': '36',
    'customControls': ['486:aspect_ratio', '486:megapixels'],
    'referenceLongestEdge': 1664,
}
SWITCH_LABEL = '自定义输出尺寸'
SWITCH_HELP = '关闭沿用参考图处理尺寸'
CUSTOM_HELP = '开启自定义尺寸后生效'


def _check_source(graph):
    from build_workflow_interfaces import widget_bindings

    def kind(nid):
        return graph.nodes.get(nid, {}).get('type')

    def value(nid, key):
        return widget_bindings(graph.nodes.get(nid, {})).get(key, (None, None))[0]

    def input_from(dst, key, src, output=0):
        inputs = graph.nodes.get(dst, {}).get('inputs', [])
        sources = {(str(origin), port) for origin, port, slot in graph.ins.get(dst, [])
                   if slot < len(inputs) and inputs[slot]['name'] == key
                   and not str(origin).endswith('/-10')}
        return sources == {(src, output)}

    required = ('36', '12', '486', '485', 'sub0/456', 'sub0/468',
                'sub0/474', 'sub0/458', 'sub0/457', '484')
    return (
        all(nid in graph.reachable and graph.enabled(nid) for nid in required)
        and kind('36') == 'LoadImage'
        and kind('12') == 'LayerUtility: ImageScaleByAspectRatio V2'
        and value('12', 'aspect_ratio') == 'original'
        and value('12', 'scale_to_side') == 'longest'
        and value('12', 'scale_to_length') == 1664
        and input_from('12', 'image', '36')
        and graph.nodes['485'].get('type') == '8c8f6d85-63e2-4f16-b659-77e0c1f357d0'
        and value('485', 'switch') is False
        and value('485', 'resolution') == 0
        and graph.editable('485', 'switch')
        and graph.targets('485', 'switch') == [('sub0/468', 'switch')]
        and kind('486') == 'ResolutionSelector'
        and graph.editable('486', 'aspect_ratio') and graph.editable('486', 'megapixels')
        and input_from('485', 'width', '486', 0)
        and input_from('485', 'height', '486', 1)
        and input_from('485', 'images.image_1', '12')
        and kind('sub0/456') == 'EmptyLatentImage'
        and input_from('sub0/456', 'width', '485', 6)
        and input_from('sub0/456', 'height', '485', 7)
        and value('sub0/456', 'batch_size') == 1
        and kind('sub0/474') == 'TextEncodeQwenImage21'
        and input_from('sub0/474', 'images.image_1', '485', 14)
        and input_from('sub0/474', 'resolution', '485', 0)
        and kind('sub0/468') == 'ComfySwitchNode'
        and input_from('sub0/468', 'switch', '485', 5)
        and input_from('sub0/468', 'on_false', 'sub0/474', 2)
        and input_from('sub0/468', 'on_true', 'sub0/456', 0)
        and kind('sub0/458') == 'KSampler'
        and input_from('sub0/458', 'latent_image', 'sub0/468')
        and input_from('sub0/458', 'positive', 'sub0/474', 0)
        and input_from('sub0/458', 'negative', 'sub0/474', 1)
        and kind('sub0/457') == 'VAEDecode'
        and input_from('sub0/457', 'samples', 'sub0/458')
        and kind('484') == 'SaveImageAdvanced'
        and input_from('484', 'images', '485')
        and ('485', 0, 0) in graph.out.get('sub0/457', [])
    )


def reviewed_portrait_size_controls(workflow, controls, *, graph=None,
                                    source_hash=None, derived=None):
    """Use one annotation path for freshly derived and unchanged curated forms.

    Fresh forms require the exact source graph. Curated forms can only carry the
    switch produced by that checked fresh form; missing or drifted proof fails.
    No graph, existing value, existing binding, or execution default is changed.
    """
    if workflow.get('id') != 'local-card-79':
        return controls
    if source_hash != PORTRAIT_SIZE_SOURCE_HASH:
        raise ValueError('写真尺寸来源已改变，需要重新审查。')
    if graph is not None:
        if not _check_source(graph):
            raise ValueError('写真尺寸分支连线已改变，需要重新审查。')
        switch = {
            'id': PORTRAIT_SIZE_SWITCH_ID, 'nodeId': '485', 'key': 'switch',
            'node': graph.nodes['485']['type'], 'value': False,
            'type': 'checkbox', 'kind': 'toggle', 'linked': False, 'inactive': False,
            'targets': deepcopy(PORTRAIT_SIZE_TARGETS),
        }
    else:
        if not isinstance(derived, dict) or derived.get('sourceHash') != source_hash:
            raise ValueError('缺少已核实的写真尺寸来源。')
        matches = [f for f in derived.get('controls', []) if f.get('id') == PORTRAIT_SIZE_SWITCH_ID]
        if (len(matches) != 1 or matches[0].get('targets') != PORTRAIT_SIZE_TARGETS
                or matches[0].get('dimensionSource') != PORTRAIT_SIZE_PROOF
                or matches[0].get('key') != 'switch' or matches[0].get('nodeId') != '485'
                or matches[0].get('type') != 'checkbox' or matches[0].get('kind') != 'toggle'
                or matches[0].get('value') is not False):
            raise ValueError('写真尺寸来源证明已改变，需要重新审查。')
        switch = deepcopy(matches[0])

    # Check the public bindings as well: labels must not legitimize a stale form.
    for control_id, key in [('486:aspect_ratio', 'aspect_ratio'), ('486:megapixels', 'megapixels')]:
        matches = [f for f in controls if f.get('id') == control_id]
        if (len(matches) != 1 or matches[0].get('key') != key
                or matches[0].get('targets') != [{'node': '486', 'input': key}]):
            raise ValueError('写真输出尺寸控件绑定已改变，需要重新审查。')
    existing = [f for f in controls if f.get('id') == PORTRAIT_SIZE_SWITCH_ID]
    if existing:
        if (len(existing) != 1 or existing[0].get('targets') != PORTRAIT_SIZE_TARGETS
                or existing[0].get('key') != 'switch' or existing[0].get('nodeId') != '485'
                or existing[0].get('type') != 'checkbox' or existing[0].get('kind') != 'toggle'
                or existing[0].get('value') is not False):
            raise ValueError('写真尺寸开关绑定或默认值已改变，需要重新审查。')
        switch = existing[0]
    else:
        position = next(i for i, f in enumerate(controls) if f['id'] == '486:aspect_ratio')
        controls.insert(position, switch)
    switch.update(label=SWITCH_LABEL, help=SWITCH_HELP, dimensionSource=deepcopy(PORTRAIT_SIZE_PROOF))
    for field in controls:
        if field['id'] in PORTRAIT_SIZE_PROOF['customControls']:
            field['help'] = CUSTOM_HELP
    return controls
