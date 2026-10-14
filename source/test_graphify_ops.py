"""Small stdlib regression checks; no network and no live Profile changes."""
import unittest
import os
import tempfile
import json
from pathlib import Path


class CacheTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows long path regression')
    def test_long_source_paths_are_scanned_hashed_and_extracted(self):
        import graphify_ops as ops
        import shutil
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='\\\\?\\' + str(work.resolve())) as tmp:
            root = Path(tmp[4:])
            relative = '/'.join(['nested_' + 'x' * 35] * 6 + ['example.py'])
            code = root / 'source' / relative
            extended = Path('\\\\?\\' + str(code.resolve()))
            self.assertGreater(len(str(code)), 260)
            extended.parent.mkdir(parents=True)
            extended.write_text('def long_path_example(): return 1\n')
            files = ops.source_files(root, {'.py'})
            self.assertEqual(list(files), [relative])
            first = ops.fingerprint(files)
            extended.write_text('def long_path_example(): return 2\n')
            self.assertNotEqual(first, ops.fingerprint(files))
            cfg = {'vault': str(root / 'vault'), 'runtime': str(root / 'runtime'),
                   'extensions': ['.py'], 'graphify': shutil.which('graphify')}
            project = {'id': 'long', 'name': 'long', 'path': str(root)}
            meta, changed = ops.rebuild(cfg, project, {}, 'fixture')
            self.assertTrue(changed)
            self.assertEqual(meta['files'], 1)
            graph = ops.load(ops.graph_path(cfg, project), {})
            self.assertTrue(any(n.get('label') == 'long_path_example()' for n in graph['nodes']))
            self.assertTrue(any(n.get('source_file') == relative for n in graph['nodes']))
            self.assertTrue(any(n.get('source_file') == relative and n.get('label') == 'example.py'
                                for n in graph['nodes']), 'staging hash leaked into file label')

    @unittest.skipUnless(os.name == 'nt', 'Windows junction regression')
    def test_cache_lock_and_publisher_reject_real_junctions(self):
        import graphify_ops as ops
        import subprocess
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            outside = root / 'sentinel'
            outside.mkdir()
            (outside / 'keep').write_bytes(b'unchanged')
            project = {'id': 'safe', 'path': str(root)}
            cfg = {'runtime': str(root / 'runtime')}
            for linked in (root / 'source/.graphify-cache', root / '.graphify-lock',
                           root / 'runtime', root / 'runtime/sync.lock', root / 'receipt'):
                linked.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(linked), str(outside)],
                               check=True, capture_output=True)
                try:
                    with self.assertRaises(ValueError):
                        if linked.name == '.graphify-cache':
                            ops.cache_path(cfg, project)
                        elif linked.name == 'receipt':
                            ops.publish(linked / 'install-receipt.json', 'unsafe')
                        else:
                            with ops.host_lock(linked.parent if linked.name == 'sync.lock' else linked):
                                pass
                    self.assertEqual(sorted(p.name for p in outside.iterdir()), ['keep'])
                    self.assertEqual((outside / 'keep').read_bytes(), b'unchanged')
                finally:
                    linked.rmdir()

    def test_untrusted_ids_and_linked_cache_or_lock_fail_before_io(self):
        import graphify_ops as ops
        from unittest.mock import patch
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            project: dict = {'id': '../../../outside', 'name': 'bad', 'path': str(root)}
            cfg = {'vault': str(root / 'vault'), 'runtime': str(root / 'runtime'),
                   'extensions': ['.py'], 'graphify': 'unused'}
            for pid in ('../../../outside', 'a/b', 'a\\b', 'C:escape', '..', 'CON', '', None, 7):
                project['id'] = pid
                for getter in (ops.cache_path, ops.graph_path):
                    with self.subTest(getter=getter.__name__, pid=pid), self.assertRaises(ValueError):
                        getter(cfg, project)
            project['id'] = 'safe'
            cache = root / 'source/.graphify-cache/safe'
            for linked in (cache, cache / 'graphify-out', cache / 'manifest.json',
                           root / 'runtime', root / 'runtime/sync.lock',
                           root / 'vault/.graphify-lock'):
                with self.subTest(linked=linked), patch.object(Path, 'is_symlink',
                        lambda path: path == linked), patch.object(Path, 'mkdir',
                        side_effect=AssertionError('mkdir reached before link rejection')) as mkdir, \
                        patch.object(Path, 'open',
                        side_effect=AssertionError('open reached before link rejection')) as opened:
                    with self.assertRaises(ValueError):
                        if linked.is_relative_to(root / 'source'):
                            ops.rebuild(cfg, project, {}, 'fixture')
                        else:
                            runtime = linked if linked.name == '.graphify-lock' else root / 'runtime'
                            with ops.host_lock(runtime):
                                pass
                    mkdir.assert_not_called()
                    opened.assert_not_called()

    def test_publish_does_not_open_predictable_temporary_link(self):
        import graphify_ops as ops
        from unittest.mock import patch
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            target = Path(tmp) / 'receipt.json'
            legacy = target.with_name(target.name + '.graphify-tmp')
            legacy.write_bytes(b'preserve')
            original = Path.write_bytes
            def guarded_write(path, data):
                self.assertNotEqual(path, legacy, 'predictable temp path was opened')
                return original(path, data)
            with patch.object(Path, 'write_bytes', guarded_write):
                ops.publish(target, 'new')
            self.assertEqual(legacy.read_bytes(), b'preserve')
            self.assertEqual(target.read_text(), 'new')

    def test_fingerprint_tracks_uncommitted_add_delete_and_ignores_cache(self):
        import graphify_ops as ops
        self.assertTrue(hasattr(ops, 'source_files'), 'source_files is not implemented')
        self.assertTrue(hasattr(ops, 'fingerprint'), 'fingerprint is not implemented')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            (root / 'source').mkdir()
            code = root / 'source/a.py'
            code.write_text('x = 1')
            (root / 'source/.graphify-cache').mkdir()
            (root / 'source/.graphify-cache/ignored.py').write_text('x = 9')
            (root / 'source/.env.py').write_text('secret = 1')
            files = ops.source_files(root, {'.py'})
            self.assertEqual(list(files), ['a.py'])
            first = ops.fingerprint(files)
            code.write_text('x = 2')
            self.assertNotEqual(first, ops.fingerprint(ops.source_files(root, {'.py'})))
            code.unlink()
            self.assertNotEqual(first, ops.fingerprint(ops.source_files(root, {'.py'})))
            (root / 'source/new.py').write_text('x = 1')
            self.assertNotEqual(first, ops.fingerprint(ops.source_files(root, {'.py'})))

    @unittest.skipUnless(os.name == 'nt', 'Windows junction regression')
    def test_source_boundary_rejects_directory_and_root_junctions(self):
        import graphify_ops as ops
        import subprocess
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            project, outside = root / 'project', root / 'outside'
            (project / 'source').mkdir(parents=True)
            outside.mkdir()
            (outside / 'secret.py').write_text('secret = 1')
            junction = project / 'source/escape'
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)],
                           check=True, capture_output=True)
            try:
                self.assertEqual(ops.source_files(project, {'.py'}), {})
            finally:
                junction.rmdir()
            (project / 'source').rmdir()
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(project / 'source'), str(outside)],
                           check=True, capture_output=True)
            try:
                with self.assertRaises(OSError):
                    ops.source_files(project, {'.py'})
            finally:
                (project / 'source').rmdir()

    def test_missing_indexed_source_retains_last_good_graph(self):
        import graphify_ops as ops
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            project = {'id': 'p', 'name': 'p', 'path': str(root / 'project')}
            (root / 'project').mkdir()
            cfg = {'vault': str(root / 'vault'), 'runtime': str(root / 'runtime'),
                   'extensions': ['.py'], 'graphify': 'not-used'}
            target = ops.graph_path(cfg, project)
            ops.publish(target, ops.packed({'nodes': [{'id': 'last-good'}], 'edges': []}))
            original = target.read_bytes()
            for previous in ({'files': 1}, {'files': 0, 'source_present': True},
                             {'files': 0, 'fingerprint': ops.fingerprint({})}):
                with self.subTest(previous=previous):
                    with self.assertRaises(OSError):
                        ops.rebuild(cfg, project, previous, 'fixture')
                    self.assertEqual(target.read_bytes(), original)
            meta, changed = ops.rebuild(cfg, project, {}, 'fixture')
            self.assertTrue(changed)
            self.assertEqual(meta['files'], 0)
            self.assertEqual(ops.load(target, {})['nodes'], [])

    def test_empty_source_disappearing_during_rebuild_retains_graph(self):
        import graphify_ops as ops
        import shutil
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            (root / 'project/source').mkdir(parents=True)
            project = {'id': 'p', 'name': 'p', 'path': str(root / 'project')}
            cfg = {'vault': str(root / 'vault'), 'runtime': str(root / 'runtime'),
                   'extensions': ['.py'], 'graphify': 'not-used'}
            target = ops.graph_path(cfg, project)
            ops.publish(target, ops.packed({'nodes': [{'id': 'last-good'}], 'edges': []}))
            original = target.read_bytes()
            scan = ops.source_files
            calls = 0

            def disappearing_source(*args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    shutil.rmtree(root / 'project/source')
                return scan(*args)

            with patch('graphify_ops.source_files', side_effect=disappearing_source):
                with self.assertRaises(RuntimeError):
                    ops.rebuild(cfg, project, {'files': 1}, 'fixture')
            self.assertEqual(target.read_bytes(), original)

    def test_unreadable_scan_is_not_published_as_empty(self):
        import graphify_ops as ops
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            (root / 'source').mkdir()
            (root / 'source/a.py').write_text('x = 1')
            project = {'id': 'p', 'name': 'p', 'path': str(root), 'origin': 'fixture'}
            cfg = {'base_home': str(root / 'home'), 'vault': str(root / 'vault'),
                   'runtime': str(root / 'runtime'), 'project_roots': [],
                   'extensions': ['.py'], 'graphify': 'fixture'}
            target = ops.graph_path(cfg, project)
            ops.publish(target, ops.packed({'nodes': [{'id': 'last-good'}], 'edges': []}))
            original = target.read_bytes()
            previous = {'files': 1, 'fingerprint': ops.fingerprint(ops.source_files(root, {'.py'}))}
            ops.publish(root / 'runtime/state.json', ops.packed(
                {'projects': {'p': previous}, 'profiles': {}, 'manual_projects': [project]}))
            with patch('graphify_ops.os.scandir', side_effect=PermissionError('sensitive detail')):
                with self.assertRaisesRegex(OSError, 'Source scan incomplete'):
                    ops.source_files(root, {'.py'})
                with patch('graphify_ops.command', return_value='fixture'):
                    result = ops.run(cfg, provision=False)
            self.assertEqual(result['errors'], ['p: OSError'])
            self.assertEqual(target.read_bytes(), original)
            stored = ops.load(root / 'runtime/state.json', {})['projects']['p']
            self.assertEqual(stored['status'], 'stale')
            self.assertEqual(stored['fingerprint'], previous['fingerprint'])
            self.assertNotIn('sensitive detail', (root / 'runtime/last-run.json').read_text())

    def test_pyw_staging_collision_retains_last_good_graph(self):
        import graphify_ops as ops
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            (root / 'source').mkdir()
            for name in ('runner.pyw', 'runner.pyw.py'):
                (root / 'source' / name).write_text('def example(): return 1')
            project = {'id': 'p', 'name': 'p', 'path': str(root)}
            cfg = {'vault': str(root / 'vault'), 'runtime': str(root / 'runtime'),
                   'extensions': ['.py', '.pyw'], 'graphify': 'not-used'}
            target = ops.graph_path(cfg, project)
            ops.publish(target, ops.packed({'nodes': [{'id': 'last-good'}], 'edges': []}))
            original = target.read_bytes()
            with patch('graphify_ops.command') as command:
                with self.assertRaisesRegex(ValueError, 'Source staging collision'):
                    ops.rebuild(cfg, project, {'files': 1}, 'fixture')
                command.assert_not_called()
            self.assertEqual(target.read_bytes(), original)

    def test_atomic_publish_is_unchanged_and_authored_files_are_preserved(self):
        import graphify_ops as ops
        self.assertTrue(hasattr(ops, 'publish'), 'publish is not implemented')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            target = Path(tmp) / 'a.md'
            self.assertTrue(ops.publish(target, 'first'))
            stamp = target.stat().st_mtime_ns
            self.assertFalse(ops.publish(target, 'first'))
            self.assertEqual(stamp, target.stat().st_mtime_ns)
            self.assertFalse(ops.publish(target, 'replace', authored=True))
            self.assertEqual(target.read_text(), 'first')

    def test_managed_file_updates_preserve_user_edits(self):
        import graphify_ops as ops
        self.assertTrue(hasattr(ops, 'install_managed'), 'install_managed is not implemented')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            target = Path(tmp) / 'managed/SKILL.md'
            state = {}
            self.assertEqual(ops.install_managed(target, 'v1', state), 'installed')
            self.assertEqual(target.read_text(), 'v1')
            self.assertEqual(ops.install_managed(target, 'v2', state), 'installed')
            target.write_text('user custom')
            self.assertEqual(ops.install_managed(target, 'v3', state), 'preserved-user-edit')
            self.assertEqual(target.read_text(), 'user custom')


class IntegrationTests(unittest.TestCase):
    def test_unchanged_sync_repairs_damaged_integrated_graph(self):
        import graphify_ops as ops
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            cfg = {'base_home': str(root / 'home'), 'vault': str(root / 'vault'),
                   'runtime': str(root / 'runtime'), 'project_roots': []}
            ops.run(cfg, discovery_only=True, provision=False)
            target = root / 'vault/Global/graphify-out/graph.json'
            original = target.read_bytes()
            for damaged in (b'corrupted', b'{"nodes": [], "links": [], "wrong": true}', None):
                with self.subTest(damaged=damaged):
                    if damaged is None:
                        target.unlink()
                    else:
                        target.write_bytes(damaged)
                    result = ops.run(cfg, discovery_only=True, provision=False)
                    self.assertFalse(result['errors'])
                    self.assertTrue(result['global_changed'])
                    self.assertEqual(target.read_bytes(), original)
                    result = ops.run(cfg, discovery_only=True, provision=False)
                    self.assertFalse(result['global_changed'])

    def test_unknown_actual_project_is_registered_and_lock_is_nonblocking(self):
        import graphify_ops as ops
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            outside = root / 'outside/source'
            outside.mkdir(parents=True)
            (outside / 'a.py').write_text('def outside():\n    return 1\n')
            import shutil
            cfg = {'base_home': str(root/'home'), 'vault': str(root/'vault'),
                   'runtime': str(root/'runtime'), 'project_roots': [], 'graphify': shutil.which('graphify'),
                   'hermes': 'not-used', 'extensions': ['.py'], 'source': str(Path(__file__).parent)}
            result = ops.run(cfg, selected=str(outside.parent), provision=False)
            self.assertEqual(result['projects'], 1)
            self.assertFalse(result['errors'])
            result = ops.run(cfg, discovery_only=True, provision=False)
            self.assertEqual(result['projects'], 1)
            with ops.host_lock(cfg['runtime']):
                with self.assertRaises(OSError):
                    with ops.host_lock(cfg['runtime']):
                        self.fail('second host lock must not be acquired')

    def test_discovery_never_deploys_or_changes_profiles(self):
        import graphify_ops as ops
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            cfg = {'base_home': str(root/'home'), 'vault': str(root/'vault'),
                   'runtime': str(root/'runtime'), 'project_roots': [],
                   'hermes': 'must-not-execute', 'source': str(Path(__file__).parent)}
            for home in (root/'home', root/'home/profiles/future-bot'):
                home.mkdir(parents=True, exist_ok=True)
                (home/'config.yaml').write_text('plugins:\n  enabled: []\n  disabled: []\n')
            before = {p.relative_to(root/'home').as_posix(): p.read_bytes()
                      for p in (root/'home').rglob('*') if p.is_file()}
            result = ops.run(cfg, discovery_only=True)
            self.assertFalse(result['errors'])
            after = {p.relative_to(root/'home').as_posix(): p.read_bytes()
                     for p in (root/'home').rglob('*') if p.is_file()}
            self.assertEqual(after, before)
            self.assertEqual(result['profiles'], {})
            self.assertEqual(result['indexed'], 0)

    def test_real_sync_incremental_deletion_and_nonblocking_failure(self):
        import graphify_ops as ops
        self.assertTrue(hasattr(ops, 'run'), 'run is not implemented')
        import shutil
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            for name in ('First', 'Second', 'Empty'):
                (root / 'projects/category' / name / 'source').mkdir(parents=True)
            first = root / 'projects/category/First/source/a.py'
            first.write_text('import pathlib\n\ndef one():\n    return 1\n')
            second = root / 'projects/category/Second/source/b.py'
            second.write_text('def two():\n    return 2\n')
            cfg = {'base_home': str(root / 'home'), 'vault': str(root / 'vault'),
                   'runtime': str(root / 'runtime'), 'project_roots': [str(root / 'projects')],
                   'graphify': shutil.which('graphify'), 'hermes': 'not-used',
                   'extensions': ['.py'], 'source': str(Path(__file__).parent)}
            result = ops.run(cfg, provision=False)
            self.assertFalse(result['errors'])
            self.assertEqual(result['indexed'], 3)
            graph_path = root / 'vault/Global/graphify-out/graph.json'
            original = graph_path.read_bytes()
            result = ops.run(cfg, provision=False)
            self.assertEqual(result['indexed'], 0)
            self.assertEqual(graph_path.read_bytes(), original)
            first.write_text(first.read_text() + '# source-only change\n')
            result = ops.run(cfg, provision=False)
            self.assertFalse(result['errors'])
            state = json.loads((root/'runtime/state.json').read_text())
            manifest = json.loads((root/'vault/Global/manifest.json').read_text())
            first_id = next(p['id'] for p in manifest['projects'] if p['name'] == 'First')
            published = next(p for p in manifest['projects'] if p['id'] == first_id)
            self.assertEqual(published['fingerprint'], state['projects'][first_id]['fingerprint'])
            first.write_text('def changed():\n    return 3\n')
            cfg['graphify'] = str(root / 'missing.exe')
            result = ops.run(cfg, provision=False)
            self.assertTrue(result['errors'])
            self.assertEqual(graph_path.read_bytes(), original)
            cfg['graphify'] = shutil.which('graphify')
            second.unlink()
            result = ops.run(cfg, provision=False)
            self.assertFalse(result['errors'])
            labels = {n['label'] for n in json.loads(graph_path.read_text())['nodes']}
            self.assertIn('changed()', labels)
            self.assertNotIn('two()', labels)


class MergeTests(unittest.TestCase):
    def test_merge_preserves_projects_direction_and_parallel_relations(self):
        try:
            from graphify_ops import merge_graphs
        except ImportError:
            self.fail('merge_graphs is not implemented')
        graph = {'nodes': [{'id': 'a', 'label': 'a.py', 'source_file': 'a.py'}, {'id': 'b', 'label': 'f()'}],
                 'edges': [{'source': 'a', 'target': 'b', 'relation': 'contains'},
                           {'source': 'a', 'target': 'b', 'relation': 'calls'}]}
        projects = [{'id': 'p1', 'name': 'First', 'path': 'C:/First'},
                    {'id': 'p2', 'name': 'Second', 'path': 'C:/Second'},
                    {'id': 'p3', 'name': 'Empty', 'path': 'C:/Empty'}]
        merged = merge_graphs(projects, {'p1': graph, 'p2': graph})
        self.assertTrue(merged['directed'])
        self.assertTrue(merged['multigraph'])
        ids = {n['id'] for n in merged['nodes']}
        self.assertEqual(len(ids), 7)
        self.assertIn('p3::PROJECT', ids)
        edges = [e for e in merged['links'] if e['source'] == 'p1::a' and e['target'] == 'p1::b']
        self.assertEqual({e['relation'] for e in edges}, {'contains', 'calls'})
        self.assertNotEqual(edges[0]['key'], edges[1]['key'])
        self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in merged['links']))


if __name__ == '__main__':
    unittest.main()
