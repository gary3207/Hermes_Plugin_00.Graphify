"""Offline distribution checks; fixtures stay beneath this source folder."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

EXPECTED = (
    'README.md', 'LICENSE', '.gitignore', '.gitattributes',
    'source/plugin.yaml', 'source/__init__.py', 'source/setup_graphify.py',
    'source/bootstrap.py', 'source/verify_install.py', 'source/graphify_ops.py', 'source/test_plugin.py',
    'source/test_graphify_ops.py', 'source/test_source_exclusions.py',
    'source/test_sync_safety.py', 'source/build_package.py',
    'source/test_build_package.py', 'source/skills/graphify-context/SKILL.md',
    'source/skills/setup/SKILL.md',
)


class PackageTests(unittest.TestCase):
    def builder(self):
        path = Path(__file__).with_name('build_package.py')
        self.assertTrue(path.is_file(), 'allowlist packaging builder is not implemented')
        spec = importlib.util.spec_from_file_location('package_builder', path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self, root):
        for name in EXPECTED:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('fixture: ' + name + '\n').encode())
        for name in ('source/graphify-config.json', 'source/profile/plugin.yaml',
                     'source/register-task.ps1', 'source/run-discovery.pyw',
                     'source/runtime/state.json', 'source/.graphify-cache/graph.json',
                     'source/private-evidence.txt', '.git/config', '.env',
                     'source/auth.json', 'source/__pycache__/ops.pyc'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('DO NOT DISTRIBUTE', encoding='utf-8')

    def test_exact_allowlist_zip_and_publication_preserve_git_on_repeat(self):
        builder = self.builder()
        self.assertEqual(set(builder.ALLOWLIST), set(EXPECTED))
        with tempfile.TemporaryDirectory(prefix='tmp-package-', dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            self.fixture(root)
            git = root / 'source/release-repo/.git/config'
            git.parent.mkdir(parents=True)
            git.write_bytes(b'publication metadata')
            archive = builder.build(root)
            self.assertEqual(archive, root / 'Hermes_Plugin_Graphify.zip')
            with zipfile.ZipFile(archive) as package:
                self.assertEqual(sorted(package.namelist()), sorted(EXPECTED))
                self.assertIsNone(package.testzip())
                for name in EXPECTED:
                    self.assertEqual(package.read(name), (root / name).read_bytes())
                    self.assertEqual((root / 'source/release-repo' / name).read_bytes(),
                                     (root / name).read_bytes())
            builder.build(root)
            self.assertEqual(git.read_bytes(), b'publication metadata')
    def test_cli_builds_beside_its_source_not_the_working_directory(self):
        import subprocess
        import sys
        builder = self.builder()
        with tempfile.TemporaryDirectory(prefix='tmp-package-', dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            self.fixture(root)
            script = root / 'source/build_package.py'
            assert builder.__file__ is not None
            script.write_bytes(Path(builder.__file__).read_bytes())
            result = subprocess.run([sys.executable, '-B', str(script)],
                                    cwd=Path(__file__).parent, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(root / 'Hermes_Plugin_Graphify.zip'))
            with zipfile.ZipFile(root / 'Hermes_Plugin_Graphify.zip') as package:
                self.assertEqual(set(package.namelist()), set(EXPECTED))
                self.assertEqual(package.read('source/build_package.py'), script.read_bytes())

    def test_unexpected_publication_entries_fail_before_any_write(self):
        builder = self.builder()
        for unexpected in ('private.json', 'source/runtime', '.env', '.gitignore/child'):
            with self.subTest(unexpected=unexpected):
                with tempfile.TemporaryDirectory(prefix='tmp-package-', dir=Path(__file__).parent) as tmp:
                    root = Path(tmp)
                    self.fixture(root)
                    target = root / 'source/release-repo' / unexpected
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b'preserve me')
                    archive = root / 'Hermes_Plugin_Graphify.zip'
                    archive.write_bytes(b'previous archive')
                    with self.assertRaisesRegex(ValueError, 'Unexpected publication'):
                        builder.build(root)
                    self.assertEqual(target.read_bytes(), b'preserve me')
                    self.assertEqual(archive.read_bytes(), b'previous archive')
                    self.assertFalse((root / 'source/release-repo/README.md').exists())

    def test_missing_required_payload_fails_before_publication(self):
        builder = self.builder()
        with tempfile.TemporaryDirectory(prefix='tmp-package-', dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'source/plugin.yaml').unlink()
            with self.assertRaisesRegex(FileNotFoundError, 'plugin.yaml'):
                builder.build(root)
            self.assertFalse((root / 'source/release-repo').exists())
            self.assertFalse((root / 'Hermes_Plugin_Graphify.zip').exists())
    @unittest.skipUnless(os.name == 'nt', 'Windows junction check')
    def test_rejects_source_and_publication_junctions(self):
        import shutil
        import subprocess
        builder = self.builder()
        for relative in ('source/skills', 'source/release-repo', 'source/release-repo/source'):
            with self.subTest(relative=relative):
                with tempfile.TemporaryDirectory(prefix='tmp-package-', dir=Path(__file__).parent) as tmp:
                    root = Path(tmp)
                    self.fixture(root)
                    target = root / relative
                    outside = root / 'private'
                    if target.exists():
                        shutil.move(str(target), str(outside))
                    else:
                        outside.mkdir()
                        target.parent.mkdir(parents=True, exist_ok=True)
                    sentinel = outside / 'private.txt'
                    sentinel.write_bytes(b'keep private')
                    subprocess.run(['cmd', '/c', 'mklink', '/J', str(target), str(outside)],
                                   check=True, capture_output=True)
                    try:
                        with self.assertRaisesRegex(ValueError, 'linked path'):
                            builder.build(root)
                        self.assertEqual(sentinel.read_bytes(), b'keep private')
                        self.assertFalse((root / 'Hermes_Plugin_Graphify.zip').exists())
                    finally:
                        target.rmdir()


if __name__ == '__main__':
    unittest.main()
