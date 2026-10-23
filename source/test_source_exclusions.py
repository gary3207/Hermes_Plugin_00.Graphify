"""Per-project exclusions use real source scans and the native extractor."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import graphify_ops as ops


class SourceExclusionTests(unittest.TestCase):
    def test_kanban_generated_homes_are_excluded_without_dropping_maintained_worktrees(self):
        rules = ['jm-check/jm-*', 'jm-check/fresh-*', 'jm-check/ctrl-*',
                 'test-sandboxes/tmp*', 'pc-20261023']

        kept = ['test_job_manager.py', 'jm-check/helper.py', 'jm-check/jm-maintained.py',
                'jm-check/other-code/maintained.py', 'test-sandboxes/helpers.py',
                'worktrees/runtime-compat-20261023/source/nativecheck_from_index.py',
                'worktrees/job-manager-runtime-20261023/source/test_job_manager.py',
                'other/test-sandboxes/tmp-one/maintained.py']
        generated = [rule.replace('*', 'one') + '/nested/generated.py' for rule in rules]
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            for relative in kept + generated:
                path = root / 'source' / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('def example(): return 1\n')
            self.assertEqual(set(ops.source_files(root, {'.py'}, rules)), set(kept))
            self.assertEqual(set(ops.source_files(root, {'.py'})), set(kept + generated))

    def test_generated_directories_are_project_scoped_and_do_not_stale_cache(self):
        # Keep the fixture independent of whether production config is updated yet.
        rules = [
            'scheduled_plugin_packaging/ri-*',
            'scheduled_plugin_packaging/sync-20261012/p',
            'scheduled_plugin_packaging/sync-20261012/scan',
            'scheduled_plugin_packaging/sync-20261012/payloads',
            'scheduled_plugin_packaging/auth-mcp-20261013/v-*/p',
            'scheduled_plugin_packaging/auth-mcp-20261013/old-shared',
            'scheduled-package-update-20261019-151846/backup',
        ]

        kept = [
            'scheduled_plugin_packaging/verify_reinstall_sync.py',
            'scheduled_plugin_packaging/sync-20261012/prepare.py',
            'scheduled_plugin_packaging/auth-mcp-20261013/v-one/update.py',
            'scheduled_plugin_packaging/auth-mcp-20261013/test_auth.py',
            'scheduled_plugin_packaging/auth-mcp-20261013/old-shared.py',
            'other/scheduled_plugin_packaging/ri-one/maintained.py',
        ]
        excluded = [rule.replace('*', 'one') + '/nested/generated.py' for rule in rules]
        # Exercise the existing external-cache route with a short sandbox staging path.
        with tempfile.TemporaryDirectory(prefix='onedrive-', dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            for i, relative in enumerate(kept + excluded):
                path = root / 'source' / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f'def symbol_{i}(): return {i}\n')
            cfg = {'vault': str(root / 'vault'), 'runtime': str(root / 'r'),
                   'extensions': ['.py'], 'graphify': shutil.which('graphify'),
                   'source_exclusions': {'fixture': rules}}
            project = {'id': 'fixture', 'name': 'fixture', 'path': str(root)}
            command = ops.command

            def extract_then_change_generated(args, **kwargs):
                result = command(args, **kwargs)
                if len(args) > 1 and args[1] == 'extract':
                    (root / 'source' / excluded[0]).write_text('def ignored_change(): return 9\n')
                return result

            meta, changed = ops.rebuild(cfg, project, {}, 'fixture')
            self.assertTrue(changed)
            self.assertEqual(meta['files'], len(kept))
            self.assertEqual(set(ops.source_files(root, {'.py'}, rules)), set(kept))
            self.assertEqual(set(ops.source_files(root, {'.py'})), set(kept + excluded))
            graph_path = ops.graph_path(cfg, project)
            graph = ops.load(graph_path, {})
            self.assertEqual({n['source_file'] for n in graph['nodes'] if n.get('source_file')}, set(kept))
            self.assertIn('symbol_0()', {n.get('label') for n in graph['nodes']})
            self.assertNotIn('ignored_change()', {n.get('label') for n in graph['nodes']})
            artifacts = [graph_path, Path(meta['cache']) / 'graphify-out/graph.json',
                         Path(meta['cache']) / 'manifest.json']
            before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in artifacts]
            (root / 'source' / excluded[1]).write_text('def another_ignored_change(): return 10\n')
            unchanged, changed = ops.rebuild(cfg, project, meta, 'fixture')
            self.assertFalse(changed)
            self.assertEqual(unchanged, meta)
            self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in artifacts], before)
            (root / 'source' / kept[0]).write_text('def maintained_change(): return 11\n')
            with patch.object(ops, 'command', side_effect=extract_then_change_generated):
                updated, changed = ops.rebuild(cfg, project, meta, 'fixture')
            self.assertTrue(changed)
            self.assertNotEqual(updated['fingerprint'], meta['fingerprint'])
            self.assertNotEqual(updated['graph_hash'], meta['graph_hash'])
            self.assertIn('maintained_change()', {n.get('label') for n in ops.load(graph_path, {})['nodes']})
            other = {**project, 'id': 'other'}
            other_meta, changed = ops.rebuild(cfg, other, {}, 'fixture')
            self.assertTrue(changed)
            self.assertEqual(other_meta['files'], len(kept + excluded))
            other_graph = ops.load(ops.graph_path(cfg, other), {})
            self.assertEqual({n['source_file'] for n in other_graph['nodes'] if n.get('source_file')},
                             set(kept + excluded))
