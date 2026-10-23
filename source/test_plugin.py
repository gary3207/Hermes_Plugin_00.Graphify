"""Portable plugin checks: isolated homes and Vaults, never real profiles."""
import importlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


class Context:
    def __init__(self):
        self.values = {}
        self.registrations = {}

    def get_config(self, key, default=None):
        return self.values.get(key, default)

    def set_config(self, key, value):
        self.values[key] = value

    def register_cli_command(self, name, help_text, setup_fn, handler_fn):
        self.registrations['cli'] = (name, setup_fn, handler_fn)

    def register_skill(self, name, path, description=''):
        assert Path(path).is_file(), 'Bundled Skill is missing'
        self.registrations[name] = Path(path)

    def register_system_prompt_section(self, name, content, **kwargs):
        self.registrations['prompt'] = content


class PluginTests(unittest.TestCase):
    def test_configured_forwards_profile_local_sync_controls_without_writes(self):
        service = self.service()
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            vault = root / 'vault'
            vault.mkdir()
            ctx = Context()
            controls = {'extract_timeout_seconds': 450,
                        'project_extract_timeout_seconds': {'fixture': 600},
                        'source_exclusions': {'fixture': ['generated/temporary-*']}}
            ctx.values.update(vault_path=str(vault), graphify_folder='Graphify', **controls)
            before = dict(ctx.values)
            cfg = service.configured(ctx, home=root / 'home')
            self.assertEqual({key: cfg.get(key) for key in controls}, controls)
            self.assertEqual(ctx.values, before)
            self.assertFalse((vault / 'Graphify').exists())
            self.assertFalse((root / 'home').exists())
            for key in controls:
                ctx.values.pop(key)
            cfg = service.configured(ctx, home=root / 'home')
            self.assertEqual(cfg['extract_timeout_seconds'], 300)
            self.assertEqual(cfg['project_extract_timeout_seconds'], {})
            self.assertEqual(cfg['source_exclusions'], {})

    def test_direct_config_destination_change_requires_migration(self):
        service = self.service()
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            vault = root / 'vault'
            vault.mkdir()
            ctx = Context()
            service.setup(ctx, vault, 'First', home=root / 'home')
            ctx.values['graphify_folder'] = 'Second'
            with self.assertRaisesRegex(ValueError, 'DESTINATION_CHANGE_REQUIRES_SEPARATE_MIGRATION'):
                service.sync(ctx, discovery_only=True, home=root / 'home')
            self.assertFalse((vault / 'Second').exists())

    def test_batch_launcher_rejects_arbitrary_project_metacharacters_before_launch(self):
        import bootstrap
        from unittest.mock import patch
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            for name in ('Project&outside', 'Project%TEMP%', 'Project!var!',
                         'Project^name', 'Project|name', 'Project"name', 'Project\nname'):
                with self.subTest(name=name), patch('bootstrap.shutil.which', return_value='hermes.CMD'), \
                        patch('graphify_ops.subprocess.run') as launch:
                    launch.return_value.returncode = 0
                    with self.assertRaisesRegex(ValueError, 'UNSAFE_BATCH_ARGUMENT'):
                        bootstrap.hermes_command(['graphify', 'sync', '--project',
                                                  str(Path(tmp) / name)], Path(tmp) / 'home')
                    launch.assert_not_called()

    def test_other_project_edited_graph_is_not_merged_or_adopted(self):
        import graphify_ops as ops
        work = Path(__file__).parent / 'test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            cfg = {'vault': str(root / 'vault'), 'runtime': str(root / 'runtime'),
                   'base_home': str(root / 'home'), 'project_roots': [],
                   'managed_output': True, 'extensions': ['.py'], 'graphify': 'unused'}
            projects = []
            state = {'projects': {}, 'manual_projects': projects}
            ops.prepare_owned(cfg)
            for pid in ('a', 'b'):
                project = {'id': pid, 'name': pid, 'path': str(root / pid), 'origin': 'fixture'}
                Path(project['path']).mkdir()
                projects.append(project)
                meta, _ = ops.rebuild(cfg, project, {}, 'fixture')
                state['projects'][pid] = meta
            ops.global_graph(cfg, projects, state)
            target = root / 'vault/Global/graphify-out/graph.json'
            before = target.read_bytes()
            ledger = dict(cfg['_owner']['files'])
            a_graph = ops.graph_path(cfg, projects[0])
            a_graph.write_text(ops.packed({'nodes': [{'id': 'injected', 'label': 'injected'}]}))
            ops.publish(root / 'runtime/state.json', ops.packed(state))
            from unittest.mock import patch
            with patch('graphify_ops.command', return_value='fixture'):
                result = ops.run(cfg, selected=projects[1]['path'])
            self.assertTrue(result['errors'], 'edited A graph was silently merged during B sync')
            self.assertFalse(result['global_changed'])
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(cfg['_owner']['files']['Projects/a/graphify-out/graph.json'],
                             ledger['Projects/a/graphify-out/graph.json'])
            with self.assertRaises(ValueError):
                ops.global_graph(cfg, projects, state)
            with patch.object(Path, 'is_symlink', lambda path: path == a_graph):
                with patch('graphify_ops.command', return_value='fixture'):
                    result = ops.run(cfg, selected=projects[1]['path'])
            self.assertTrue(result['errors'])
            self.assertFalse(result['global_changed'])
            self.assertEqual(target.read_bytes(), before)

    def service(self):
        try:
            return importlib.import_module('setup_graphify')
        except ModuleNotFoundError:
            self.fail('Portable Graphify setup module is missing')

    def test_destination_handles_nested_unicode_and_rejects_escapes(self):
        service = self.service()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            vault = Path(tmp) / '한글 Vault'
            vault.mkdir()
            result = service.destination(vault, 'AgentData/Graphify')
            self.assertEqual(result['graphify_root'], str(vault / 'AgentData/Graphify'))
            self.assertEqual(result['graphify_folder'], 'AgentData/Graphify')
            self.assertFalse((vault / 'AgentData').exists())
            for folder in ('', '../escape', '/absolute', 'C:/escape', 'a/../b',
                           'a//b', '.obsidian', 'bad:name', 'bad\nname'):
                with self.subTest(folder=folder), self.assertRaises(ValueError):
                    service.destination(vault, folder)
            with self.assertRaises(ValueError):
                service.destination(vault / 'missing', 'Graphify')

    def test_setup_is_profile_local_repeatable_and_preserves_foreign_files(self):
        service = self.service()
        self.assertTrue(hasattr(service, 'setup'), 'setup is not implemented')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            home, vault = root / 'home', root / 'Vault'
            home.mkdir()
            vault.mkdir()
            other = home / 'profiles/other/config.yaml'
            other.parent.mkdir(parents=True)
            other.write_text('unrelated profile')
            ctx = Context()
            self.assertFalse(service.status(ctx, home=home)['configured'])
            self.assertFalse((home / 'plugin-data').exists())
            result = service.setup(ctx, vault, 'Nested/Graphify', home=home)
            self.assertTrue(result['success'])
            index = vault / 'Nested/Graphify/00_Index.md'
            text = index.read_text(encoding='utf-8')
            self.assertIn('[[Nested/Graphify/', text)
            self.assertNotIn('[[Graphify/', text)
            stamp = index.stat().st_mtime_ns
            service.setup(ctx, vault, 'Nested/Graphify', home=home)
            self.assertEqual(index.stat().st_mtime_ns, stamp)
            self.assertEqual(other.read_text(), 'unrelated profile')
            self.assertFalse((other.parent / 'plugins').exists())
            foreign = vault / 'Foreign'
            foreign.mkdir()
            (foreign / '00_Index.md').write_text('user owned')
            foreign_ctx = Context()
            with self.assertRaises(ValueError):
                service.setup(foreign_ctx, vault, 'Foreign', home=home / 'other-home')
            self.assertEqual((foreign / '00_Index.md').read_text(), 'user owned')
            self.assertEqual(foreign_ctx.values, {})

    def test_real_sync_query_and_reconnection_preserve_authored_notes(self):
        service = self.service()
        self.assertTrue(hasattr(service, 'sync'), 'sync is not implemented')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            home, vault, project = root / 'home', root / 'Vault', root / 'Project'
            vault.mkdir()
            (project / 'source').mkdir(parents=True)
            (project / 'source/example.py').write_text(
                'def normalize(value):\n    return value.strip()\n\n'
                'def greeting(value):\n    return normalize(value)\n')
            ctx = Context()
            service.setup(ctx, vault, 'Nested/Graphify', home=home)
            result = service.sync(ctx, project=project, home=home)
            self.assertTrue(result['success'])
            graph_root = vault / 'Nested/Graphify'
            graph = json.loads((graph_root / 'Global/graphify-out/graph.json').read_text())
            self.assertIn('normalize()', {n['label'] for n in graph['nodes']})
            self.assertEqual(graph['input_tokens'] if 'input_tokens' in graph else 0, 0)
            query = service.query(ctx, 'greeting', home=home)
            self.assertIn('example.py', query['output'])
            affected = service.query(ctx, 'normalize', mode='affected', project=project, home=home)
            self.assertIn('greeting', affected['output'])
            note = next(graph_root.glob('Projects/*/10_Architecture.md'))
            note.write_text('human verified architecture')
            shutil.rmtree(home / 'plugin-data')
            restored = Context()
            service.setup(restored, vault, 'Nested/Graphify', home=home)
            self.assertEqual(note.read_text(), 'human verified architecture')
            repeat = service.sync(restored, project=project, home=home)
            self.assertEqual(repeat['indexed'], 0)
            self.assertEqual(note.read_text(), 'human verified architecture')
            index = graph_root / '00_Index.md'
            index.write_text('edited generated index')
            with self.assertRaises(ValueError):
                service.sync(restored, project=project, home=home)
            self.assertEqual(index.read_text(), 'edited generated index')

    def test_plugin_registration_is_read_only_and_guidance_uses_configuration(self):
        entry = Path(__file__).parent / '__init__.py'
        self.assertTrue(entry.is_file(), 'Plugin entrypoint is missing')
        spec = importlib.util.spec_from_file_location('test_graphify_plugin', entry,
                                                    submodule_search_locations=[str(entry.parent)])
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        ctx = Context()
        module.register(ctx)
        self.assertEqual(ctx.registrations['cli'][0], 'graphify')
        self.assertEqual(ctx.values, {})
        text = ctx.registrations['prompt']({})
        self.assertIn('setup', text)
        self.assertNotIn('Gary Lee', text)
        self.assertIn('graphify-context:graphify-context', text)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            vault = Path(tmp) / 'Vault'
            vault.mkdir()
            ctx.values.update(vault_path=str(vault), graphify_folder='Nested/Graphify')
            text = ctx.registrations['prompt']({})
            self.assertIn(str(vault / 'Nested/Graphify/00_Index.md'), text)
            self.assertFalse((vault / 'Nested').exists())

    def test_bootstrap_payload_updates_only_owned_current_profile_files(self):
        path = Path(__file__).parent / 'bootstrap.py'
        self.assertTrue(path.is_file(), 'Bootstrap is missing')
        bootstrap = importlib.import_module('bootstrap')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            home = root / 'home'
            other = home / 'profiles/other/keep.txt'
            other.parent.mkdir(parents=True)
            other.write_text('untouched')
            source = Path(__file__).parent
            result = bootstrap.install_payload(home, source)
            self.assertEqual(result['profile_home'], str(home.resolve()))
            target = home / 'plugins/graphify-context/__init__.py'
            self.assertEqual(target.read_bytes(), (source / '__init__.py').read_bytes())
            bootstrap.install_payload(home, source)
            target.write_text('user edit')
            with self.assertRaises(ValueError):
                bootstrap.install_payload(home, source)
            self.assertEqual(target.read_text(), 'user edit')
            self.assertEqual(other.read_text(), 'untouched')
            self.assertFalse((other.parent / 'plugins').exists())

    def test_native_command_cannot_override_explicit_profile_home(self):
        from unittest.mock import patch
        import bootstrap
        home = Path(__file__).parent / 'test-work/scoped-home'
        other = Path(__file__).parent / 'test-work/other-home'
        with patch.object(bootstrap.shutil, 'which', return_value='mock-hermes.CMD'), \
                patch.object(bootstrap.service.ops, 'command', return_value='{}') as command:
            bootstrap.hermes_command(['graphify', 'status'], home, {
                'HERMES_HOME': str(other), 'PYTHONUTF8': '0',
                'PYTHONIOENCODING': 'ascii', 'GIT_TERMINAL_PROMPT': '0'})
        self.assertEqual(command.call_count, 1)
        environment = command.call_args.kwargs['env']
        self.assertEqual(environment['HERMES_HOME'], str(home))
        self.assertEqual(environment['PYTHONUTF8'], '1')
        self.assertEqual(environment['PYTHONIOENCODING'], 'utf-8')
        self.assertEqual(environment['GIT_TERMINAL_PROMPT'], '0')

    def test_native_verifier_rejects_malformed_git_sources_before_launch(self):
        import contextlib
        import io
        from unittest.mock import patch
        import verify_install
        for source in ('owner/repo/source&unexpected', 'owner/../source',
                       'owner/repo/source"', 'owner/repo/source%TEMP%'):
            with self.subTest(source=source), patch.object(sys, 'argv',
                    ['verify_install.py', '--repository', source, '--ref', 'a' * 40]), \
                    patch.object(verify_install.tempfile, 'TemporaryDirectory') as temporary, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    verify_install.main()
                self.assertEqual(failure.exception.code, 2)
                temporary.assert_not_called()


if __name__ == '__main__':
    unittest.main()
