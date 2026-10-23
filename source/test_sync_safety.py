"""Bounded extraction and readable publication; no live Profile writes."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import graphify_ops as ops


class SyncSafetyTests(unittest.TestCase):
    def test_invalid_exclusion_values_cannot_replace_existing_outputs(self):
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            (root / 'source/nested').mkdir(parents=True)
            (root / 'source/nested/a.py').write_text('def example(): return 1\n')
            cfg = {'vault': str(root / 'vault'), 'runtime': str(root / 'runtime'),
                   'extensions': ['.py'], 'graphify': 'fixture'}
            project = {'id': 'p', 'name': 'fixture', 'path': str(root)}

            def extract(argv, **kwargs):
                if argv[1] == 'extract':
                    output = Path(argv[argv.index('--out') + 1]) / 'graphify-out/graph.json'
                    ops.publish(output, ops.packed({'nodes': [{'id': 'a', 'label': 'example()'}], 'edges': []}))
                return ''

            with patch.object(ops, 'command', side_effect=extract):
                meta, _ = ops.rebuild(cfg, project, {}, 'fixture')
            paths = [ops.graph_path(cfg, project), Path(meta['cache']) / 'graphify-out/graph.json',
                     Path(meta['cache']) / 'manifest.json']
            before = [p.read_bytes() for p in paths]
            for invalid in ('generated/*', {'*': 'generated'}, None, 42, [1], ['generated/*', None]):
                invalid_cfg = {**cfg, 'source_exclusions': {'p': invalid}}
                with self.subTest(invalid=invalid), patch.object(ops, 'command', return_value='') as command:
                    with self.assertRaisesRegex(ValueError, 'INVALID_SOURCE_EXCLUSIONS'):
                        ops.rebuild(invalid_cfg, project, meta, 'fixture')
                    command.assert_not_called()
                    self.assertEqual([p.read_bytes() for p in paths], before)
            self.assertEqual(set(ops.source_files(root, {'.py'}, [])), {'nested/a.py'})
            self.assertEqual(set(ops.source_files(root, {'.py'}, ())), {'nested/a.py'})
            self.assertEqual(ops.failure_details(ValueError('INVALID_SOURCE_EXCLUSIONS')),
                             {'error_type': 'ValueError', 'error_code': 'INVALID_SOURCE_EXCLUSIONS'})

    def test_failure_details_distinguish_timeout_size_and_source_change_without_raw_output(self):
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            project = {'id': 'p', 'name': 'fixture', 'path': str(root), 'origin': 'fixture'}
            cfg = {'vault': str(root / 'vault'), 'runtime': str(root / 'runtime')}
            cases = [
                (ops.subprocess.TimeoutExpired(['secret-argument'], 600, output='sensitive output'),
                 {'error_type': 'TimeoutExpired', 'error_code': 'EXTRACTION_TIMEOUT', 'timeout_seconds': 600}),
                (ops.GraphTooLargeError(600_000_000),
                 {'error_type': 'GraphTooLargeError', 'error_code': 'GRAPH_TOO_LARGE',
                  'size_bytes': 600_000_000, 'limit_bytes': ops.MAX_GRAPH_BYTES}),
                (RuntimeError('Source changed during extraction; previous graph retained'),
                 {'error_type': 'RuntimeError', 'error_code': 'SOURCE_CHANGED_DURING_EXTRACTION'}),
            ]
            for error, expected in cases:
                with self.subTest(error=type(error).__name__), \
                     patch.object(ops, 'discover', return_value=[project]), \
                     patch.object(ops, 'command', return_value='fixture'), \
                     patch.object(ops, 'rebuild', side_effect=error):
                    result = ops.run(cfg)
                self.assertEqual(result.get('error_details', {}).get('p'), expected)
                self.assertNotIn('sensitive', ops.packed(result))
                self.assertNotIn('secret-argument', ops.packed(result))
            with patch.object(ops, 'discover', return_value=[]), \
                 patch.object(ops, 'global_graph', side_effect=ops.GraphTooLargeError(600_000_000)):
                result = ops.run(cfg, discovery_only=True)
            self.assertEqual(result.get('error_details', {}).get('Global graph'), cases[1][1])

    def test_timeout_or_oversized_project_retains_vault_cache_and_manifest(self):
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            (root / 'source').mkdir()
            code = root / 'source/a.py'
            code.write_text('def example(): return 1\n')
            cfg = {'vault': str(root / 'vault'), 'runtime': str(root / 'runtime'),
                   'extensions': ['.py'], 'graphify': 'fixture'}
            project = {'id': 'p', 'name': 'fixture', 'path': str(root)}
            label = 'example()'

            def extract(argv, **kwargs):
                if argv[1] == 'extract':
                    output = Path(argv[argv.index('--out') + 1]) / 'graphify-out/graph.json'
                    ops.publish(output, ops.packed({'nodes': [{'id': 'a', 'label': label}], 'edges': []}))
                return ''

            with patch.object(ops, 'command', side_effect=extract):
                meta, _ = ops.rebuild(cfg, project, {}, 'fixture')
                paths = [ops.graph_path(cfg, project), Path(meta['cache']) / 'graphify-out/graph.json',
                         Path(meta['cache']) / 'manifest.json']
                before = [p.read_bytes() for p in paths]
                code.write_text('def example(): return 2\n')
                label = '한' * 3000
                with patch.object(ops, 'MAX_GRAPH_BYTES', 4096, create=True):
                    with self.assertRaisesRegex(ValueError, 'GRAPH_TOO_LARGE'):
                        ops.rebuild(cfg, project, meta, 'fixture')
                self.assertEqual([p.read_bytes() for p in paths], before)
                with patch.object(ops, 'command', side_effect=ops.subprocess.TimeoutExpired(['fixture'], 300)):
                    with self.assertRaises(ops.subprocess.TimeoutExpired):
                        ops.rebuild(cfg, project, meta, 'fixture')
                self.assertEqual([p.read_bytes() for p in paths], before)

    def test_oversized_union_retains_global_graph_manifest_and_report(self):
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            cfg = {'vault': str(root / 'vault')}
            state = {'projects': {}}
            ops.global_graph(cfg, [], state)
            paths = [root / 'vault/Global/graphify-out/graph.json',
                     root / 'vault/Global/manifest.json', root / 'vault/Global/graphify-out/GRAPH_REPORT.md']
            before = [p.read_bytes() for p in paths]
            projects = [{'id': 'p' + str(i), 'name': 'fixture', 'path': str(root / str(i))}
                        for i in range(2)]
            graph = {'nodes': [{'id': 'a', 'label': '한' * 350}], 'edges': []}
            for project in projects:
                data = ops.packed(graph)
                self.assertLess(len(data.encode('utf-8')), 3000)
                ops.publish(ops.graph_path(cfg, project), data)
            self.assertGreater(len(ops.packed(ops.merge_graphs(projects, {p['id']: graph for p in projects})).encode('utf-8')), 3000)
            with patch.object(ops, 'MAX_GRAPH_BYTES', 3000, create=True):
                with self.assertRaisesRegex(ValueError, 'GRAPH_TOO_LARGE'):
                    ops.global_graph(cfg, projects, state)
            self.assertEqual([p.read_bytes() for p in paths], before)

    def test_extraction_timeout_is_project_scoped_validated_and_recorded(self):
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            (root / 'source').mkdir()
            (root / 'source/a.py').write_text('def example(): return 1\n')
            cfg = {'vault': str(root / 'vault'), 'runtime': str(root / 'runtime'),
                   'extensions': ['.py'], 'graphify': 'fixture',
                   'extract_timeout_seconds': 310,
                   'project_extract_timeout_seconds': {'selected': 600}}
            project = {'id': 'selected', 'name': 'fixture', 'path': str(root)}
            timeouts = []

            def extract(argv, timeout=180, **kwargs):
                if argv[1] == 'extract':
                    timeouts.append(timeout)
                    output = Path(argv[argv.index('--out') + 1]) / 'graphify-out/graph.json'
                    ops.publish(output, ops.packed({'nodes': [], 'edges': []}))
                return ''

            with patch.object(ops, 'command', side_effect=extract), \
                 patch.object(ops.time, 'perf_counter', side_effect=[10, 12.5, 20, 23, 30, 34]):
                meta, changed = ops.rebuild(cfg, project, {}, 'fixture')
                other, _ = ops.rebuild(cfg, {**project, 'id': 'other'}, {}, 'fixture')
                default, _ = ops.rebuild({k: v for k, v in cfg.items()
                                         if k not in {'extract_timeout_seconds', 'project_extract_timeout_seconds'}},
                                        {**project, 'id': 'default'}, {}, 'fixture')
            self.assertTrue(changed)
            self.assertEqual(timeouts, [600, 310, 300])
            self.assertEqual(meta['extract_timeout_seconds'], 600)
            self.assertEqual(other['extract_timeout_seconds'], 310)
            self.assertEqual(default['extract_timeout_seconds'], 300)
            self.assertEqual([meta['extract_seconds'], other['extract_seconds'], default['extract_seconds']],
                             [2.5, 3, 4])
            self.assertEqual(meta['graph_bytes'], ops.graph_path(cfg, project).stat().st_size)
            for invalid in (0, -1, True, '600', None, 1.5):
                invalid_cfg = {**cfg, 'project_extract_timeout_seconds': {'selected': invalid}}
                with self.subTest(invalid=invalid), patch.object(ops, 'command') as command:
                    with self.assertRaisesRegex(ValueError, 'INVALID_EXTRACT_TIMEOUT_SECONDS'):
                        ops.rebuild(invalid_cfg, project, {}, 'fixture')
                    command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
