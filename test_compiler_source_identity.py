"""A normalized cache file cannot substitute for reviewed original source bytes."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'scripts'))
import compile_card_workflows as compiler


class OriginalSourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'original.json'
        self.data = b'{"nodes": [], "links": [], "version": 0.4}\n'
        self.path.write_bytes(self.data)
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.sources = [{'id': 'local-card-70', 'source': str(self.path)}]

    def load(self, sources=None, reviewed=None, snapshot=None):
        return compiler.reviewed_original_source('local-card-70', self.sources if sources is None else sources,
                                                self.sha if reviewed is None else reviewed,
                                                self.sha if snapshot is None else snapshot)

    def test_unique_original_bytes_are_loaded_and_cache_cannot_override(self):
        cache = self.root / 'graph-070.json'
        cache.write_text(json.dumps({'nodes': [{'id': 999, 'type': 'wrong-cache'}]}), 'utf-8')
        with patch.object(compiler, 'CACHE', self.root):
            self.assertEqual(self.load(), json.loads(self.data))
        self.assertEqual(self.path.read_bytes(), self.data)
        cache.unlink()
        self.assertEqual(self.load(), json.loads(self.data))

    def test_formatting_only_byte_drift_is_rejected_even_when_json_equals(self):
        self.path.write_text(json.dumps(json.loads(self.data), indent=2), 'utf-8')
        self.assertEqual(json.loads(self.path.read_bytes()), json.loads(self.data))
        with self.assertRaisesRegex(compiler.CompileError, 'bytes differ'):
            self.load()

    def test_missing_duplicate_and_ambiguous_original_sources_are_rejected(self):
        for sources in ([], {}, self.sources + self.sources,
                        self.sources + [{'id': 'local-card-70', 'source': str(self.root / 'other.json')}],
                        [{'id': 'local-card-70'}], [{'id': 'local-card-70', 'source': ''}],
                        [{'id': 'local-card-70', 'source': str(self.root / 'missing.json')}]):
            with self.subTest(sources=sources), self.assertRaises(compiler.CompileError):
                self.load(sources=sources)

    def test_all_three_hashes_must_match_before_json_is_used(self):
        for reviewed, snapshot in ((self.sha, 'a' * 64), ('b' * 64, self.sha),
                                   ('c' * 64, 'c' * 64), ('not-a-hash', 'not-a-hash')):
            with self.subTest(reviewed=reviewed, snapshot=snapshot), self.assertRaises(compiler.CompileError):
                self.load(reviewed=reviewed, snapshot=snapshot)

    def test_relative_source_is_resolved_against_project_root(self):
        with patch.object(compiler, 'ROOT', self.root):
            self.assertEqual(self.load(sources=[{'id': 'local-card-70', 'source': 'original.json'}]), json.loads(self.data))

    def test_authenticated_invalid_json_still_fails_closed(self):
        self.path.write_bytes(b'not JSON')
        sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaises(compiler.CompileError):
            self.load(reviewed=sha, snapshot=sha)

    def test_all_133_actual_sources_match_review_and_snapshot(self):
        audit = ROOT / 'verification/catalog-audit.json'
        interfaces = ROOT / 'public/workflow-interfaces.json'
        snapshot = ROOT / 'private/research/card-20261004/snapshot.json'
        if not all(path.exists() for path in (audit, interfaces, snapshot)):
            self.skipTest('Actual owner originals and snapshots are private local evidence.')
        sources = json.loads(audit.read_text('utf-8'))
        ui = json.loads(interfaces.read_text('utf-8'))['workflows']
        downloaded = {f"local-card-{row['index']}": row['sha256']
                      for row in json.loads(snapshot.read_text('utf-8'))['files']}
        actual = [row for row in sources if row.get('id', '').startswith('local-card-')]
        self.assertEqual(len(actual), 133)
        for row in actual:
            wid = row['id']; path = Path(row['source']); before = path.read_bytes()
            with self.subTest(workflow=wid):
                self.assertEqual(compiler.reviewed_original_source(wid, sources, ui[wid]['sourceHash'], downloaded[wid]),
                                 json.loads(before.decode('utf-8-sig')))
                self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__': unittest.main()
