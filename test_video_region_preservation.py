"""Offline graph contracts and CPU reference pixels; no card/API execution.

The NumPy evaluator checks the 25-frame compositing contract, not the installed
ComfyUI tensor implementation. Native batched masks and encoded seam quality
still require the real candidate acceptance run.
"""
import copy
import json
import unittest

import numpy as np

import schema_adapters
from region_preservation import (
    VIDEO_REGION_FIRST, VIDEO_REGION_REFINED, VIDEO_REGION_SIZE,
    VIDEO_REGION_MASK_IMAGE, VIDEO_REGION_MASK_SCALED, VIDEO_REGION_MASK,
    preserve_region_output,
)


class TrackedVideoRegionContracts(unittest.TestCase):
    def setUp(self):
        self.spec = copy.deepcopy(schema_adapters.manifest('local-card-51'))
        self.graph = json.loads(schema_adapters.template_path(self.spec).read_text('utf-8'))

    def test_output_roles_survive_complete_region_adaptation_but_reject_mask_drift(self):
        import server
        original = copy.deepcopy(self.graph)
        expected = server.reviewed_output_metadata(self.spec, original)
        preserve_region_output(self.spec, self.graph)
        self.assertEqual(server.reviewed_output_metadata(self.spec, self.graph), expected)
        snapshot = copy.deepcopy(self.graph)
        self.graph[VIDEO_REGION_FIRST]['inputs']['mask'] = ['1080', 0]
        metadata = server.reviewed_output_metadata(self.spec, self.graph)
        for node in ('948', '949', '939', '955'):
            self.assertNotIn(node, metadata)
        self.assertEqual(metadata['1048']['role'], 'mask')
        self.assertEqual(metadata['1049']['role'], 'control')
        self.graph = snapshot
        wrong_source = {**self.spec, 'source_hash': 'unreviewed'}
        self.assertNotIn('949', server.reviewed_output_metadata(wrong_source, self.graph))

    def test_only_four_image_consumers_change_and_media_contracts_remain(self):
        original = copy.deepcopy(self.graph)
        original_spec = copy.deepcopy(self.spec)
        result = preserve_region_output(self.spec, self.graph)
        redirects = {'953': ('images', VIDEO_REGION_FIRST),
                     '944': ('images', VIDEO_REGION_REFINED),
                     '962': ('image2', VIDEO_REGION_FIRST),
                     '945': ('image2', VIDEO_REGION_REFINED)}
        for node, before in original.items():
            after = copy.deepcopy(self.graph[node])
            if node in redirects:
                key, target = redirects[node]
                self.assertEqual(after['inputs'][key], [target, 0])
                after['inputs'][key] = before['inputs'][key]
            self.assertEqual(after, before, node)
        self.assertEqual(self.spec, original_spec)
        self.assertEqual(result['output_nodes'], ['949', '948'])
        self.assertEqual(self.graph[VIDEO_REGION_FIRST]['inputs']['mask'], ['1062', 0])
        self.assertEqual(self.graph[VIDEO_REGION_REFINED]['inputs']['destination'], ['1064', 0])
        self.assertEqual(self.graph[VIDEO_REGION_SIZE]['inputs']['image'], ['1064', 0])
        self.assertEqual(self.graph[VIDEO_REGION_MASK_SCALED]['inputs']['width'], [VIDEO_REGION_SIZE, 0])
        self.assertEqual(self.graph[VIDEO_REGION_MASK_SCALED]['inputs']['height'], [VIDEO_REGION_SIZE, 1])
        self.assertEqual(self.graph[VIDEO_REGION_MASK_SCALED]['inputs']['upscale_method'], 'nearest-exact')
        # Final preservation must not use the expanded, block-aligned guide.
        self.assertEqual(self.graph[VIDEO_REGION_MASK_IMAGE]['inputs']['mask'], ['1062', 0])

    def test_adaptation_is_idempotent_and_preserves_legal_asset_seed_size_changes(self):
        self.graph['1084']['inputs']['video'] = 'different-owned-video.mp4'
        self.graph['1084']['inputs']['skip_first_frames'] = 17
        self.graph['1105']['inputs']['value'] = 1024
        self.graph['1104']['inputs']['value'] = 2
        self.graph['981']['inputs']['noise_seed'] = 12345
        before = copy.deepcopy(self.graph)
        preserve_region_output(self.spec, self.graph)
        once = copy.deepcopy(self.graph)
        preserve_region_output(self.spec, self.graph)
        self.assertEqual(self.graph, once)
        for node in ['1084', '1105', '1104', '981', '1020', '1102']:
            self.assertEqual(self.graph[node], before[node])

    def test_source_mask_decoder_output_or_reserved_node_drift_rejects_atomically(self):
        mutations = [
            lambda s, g: s.update(source_hash='different-source'),
            lambda s, g: s['outputs'].reverse(),
            lambda s, g: g['1062']['inputs'].update(frames=['1064', 0]),
            lambda s, g: g['1062']['inputs'].update(positive_points=['unreviewed', 0]),
            lambda s, g: g['1058']['inputs'].update(scale_by=0.75),
            lambda s, g: g['989']['inputs'].update(samples=['unreviewed', 0]),
            lambda s, g: g['968'].update(class_type='UnreviewedDecode'),
            lambda s, g: g['1083']['inputs'].update(model_name='different-upscaler'),
            lambda s, g: g['953']['inputs'].update(images=['unreviewed', 0]),
            lambda s, g: g['945']['inputs'].update(image2=['unreviewed', 0]),
            lambda s, g: g.update({VIDEO_REGION_MASK: {'class_type': 'UnexpectedMask'}}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                spec, graph = copy.deepcopy(self.spec), copy.deepcopy(self.graph)
                mutate(spec, graph)
                before = copy.deepcopy(graph)
                with self.assertRaises(ValueError):
                    preserve_region_output(spec, graph)
                self.assertEqual(graph, before)

    def test_partial_rewrite_or_changed_adapted_mask_is_not_accepted_as_rerun(self):
        preserve_region_output(self.spec, self.graph)
        for node, key, value in [
            ('953', 'images', ['989', 0]),
            (VIDEO_REGION_FIRST, 'mask', ['1069', 0]),
            (VIDEO_REGION_MASK_SCALED, 'upscale_method', 'bilinear'),
        ]:
            with self.subTest(node=node):
                changed = copy.deepcopy(self.graph)
                changed[node]['inputs'][key] = value
                before = copy.deepcopy(changed)
                with self.assertRaises(ValueError):
                    preserve_region_output(self.spec, changed)
                self.assertEqual(changed, before)

    def test_cpu_reference_pairs_all_25_unique_masks_and_keeps_unselected_pixels(self):
        preserve_region_output(self.spec, self.graph)
        rng = np.random.default_rng(71)
        for height, width in [(8, 12), (12, 16)]:
            with self.subTest(first_size=(width, height)):
                original = rng.random((25, height, width, 3), dtype=np.float32)
                original_refined = rng.random((25, height * 2, width * 2, 3), dtype=np.float32)
                edited = np.ones_like(original)
                edited_refined = np.ones_like(original_refined)
                masks = np.zeros((25, height, width), dtype=np.float32)
                for index in range(25):
                    row = (index // width) % height
                    masks[index, row, index % width] = 1
                    masks[index, (row + 1) % height, index % width] = 0.5
                arrays = {('1058', 0): original, ('1064', 0): original_refined,
                          ('989', 0): edited, ('968', 0): edited_refined,
                          ('1062', 0): masks}
                snapshots = {key: value.copy() for key, value in arrays.items()}

                def evaluate(link):
                    key = tuple(link)
                    if key in arrays:
                        return arrays[key]
                    node = self.graph[link[0]]
                    inputs = node['inputs']
                    if node['class_type'] == 'GetImageSize+':
                        image = evaluate(inputs['image'])
                        return (image.shape[2], image.shape[1], image.shape[0])[link[1]]
                    if node['class_type'] == 'MaskToImage':
                        return np.repeat(evaluate(inputs['mask'])[:, :, :, None], 3, axis=3)
                    if node['class_type'] == 'ImageScale':
                        image = evaluate(inputs['image'])
                        new_width, new_height = evaluate(inputs['width']), evaluate(inputs['height'])
                        xs = np.minimum(((np.arange(new_width) + 0.5) * image.shape[2] / new_width).astype(int), image.shape[2] - 1)
                        ys = np.minimum(((np.arange(new_height) + 0.5) * image.shape[1] / new_height).astype(int), image.shape[1] - 1)
                        return image[:, ys[:, None], xs[None, :], :]
                    if node['class_type'] == 'ImageToMask':
                        return evaluate(inputs['image'])[:, :, :, 0]
                    if node['class_type'] == 'ImageCompositeMasked':
                        destination, source, mask = (evaluate(inputs[name]) for name in ['destination', 'source', 'mask'])
                        self.assertEqual(destination.shape, source.shape)
                        self.assertEqual(destination.shape[:3], mask.shape)
                        return source * mask[:, :, :, None] + destination * (1 - mask[:, :, :, None])
                    self.fail('Unexpected CPU reference node: ' + node['class_type'])

                first = evaluate([VIDEO_REGION_FIRST, 0])
                refined = evaluate([VIDEO_REGION_REFINED, 0])
                refined_masks = evaluate([VIDEO_REGION_MASK, 0])
                self.assertEqual(first.shape[0], 25)
                self.assertEqual(refined.shape[0], 25)
                self.assertEqual(refined_masks.shape[0], 25)
                np.testing.assert_array_equal(first[masks == 0], original[masks == 0])
                np.testing.assert_array_equal(refined[refined_masks == 0], original_refined[refined_masks == 0])
                for index in range(25):
                    np.testing.assert_array_equal(first[index][masks[index] == 1], edited[index][masks[index] == 1])
                    np.testing.assert_array_equal(refined[index][refined_masks[index] == 1], edited_refined[index][refined_masks[index] == 1])
                for key, snapshot in snapshots.items():
                    np.testing.assert_array_equal(arrays[key], snapshot)


if __name__ == '__main__':
    unittest.main()
