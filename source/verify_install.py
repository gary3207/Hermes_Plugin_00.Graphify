"""Actual local/ZIP or pinned-private-Git install smoke check; isolated home only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from bootstrap import hermes_command, PAYLOAD


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--repository', help='Private GitHub owner/repo/source; requires authenticated Git')
    parser.add_argument('--ref', help='Exact reviewed 40-character SHA for Git mode')
    parser.add_argument('--work-root', type=Path,
                        help='Short fixture folder under project source; avoids deep Windows runtime paths')
    args = parser.parse_args()
    if args.repository and (not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/source', args.repository)
                            or any(part in {'.', '..'} for part in args.repository.split('/'))):
        parser.error('--repository must be a literal owner/repo/source without shell metacharacters')
    if args.repository and (not args.ref or len(args.ref) != 40
                            or any(c not in '0123456789abcdef' for c in args.ref)):
        parser.error('--repository requires an exact lowercase 40-character --ref')
    package = args.package.resolve()
    parent = (args.work_root or Path(__file__).resolve().parent / 'test-work').resolve()
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='installation-', dir=parent, ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        home, vault, project = root / 'home', root / '한글 Vault', root / 'Project'
        home.mkdir()
        vault.mkdir()
        (home / 'config.yaml').write_text('plugins:\n  enabled: []\n  disabled: []\n', encoding='utf-8')
        other = home / 'profiles/other/config.yaml'
        other.parent.mkdir(parents=True)
        other.write_text('plugins:\n  disabled: [graphify-context]\n', encoding='utf-8')
        other_before = other.read_bytes()
        env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'Never',
               'GIT_CONFIG_COUNT': '2', 'GIT_CONFIG_KEY_0': 'credential.helper',
               'GIT_CONFIG_VALUE_0': '', 'GIT_CONFIG_KEY_1': 'credential.helper',
               'GIT_CONFIG_VALUE_1': '!gh auth git-credential'}
        if args.repository:
            hermes_command(['plugins', 'install', args.repository, '--ref', args.ref,
                            '--enable', '--yes-deps'], home, env)
        else:
            command = [sys.executable, str(package / 'source/bootstrap.py'), '--home', str(home),
                       '--vault', str(vault), '--folder', 'Nested/Graphify']
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=240, env=env)
            if result.returncode:
                raise RuntimeError('LOCAL_BOOTSTRAP_FAILED: ' + result.stdout[-1000:])
            assert json.loads(result.stdout)['success']
        installed = home / 'plugins/graphify-context'
        for relative in PAYLOAD:
            assert (installed / relative).read_bytes() == (package / 'source' / relative).read_bytes(), relative
        listing = hermes_command(['plugins', 'list', '--json'], home)
        assert any(p['name'] == 'graphify-context' and p['status'] == 'enabled' for p in json.loads(listing))
        hermes_command(['plugins', 'doctor', 'graphify-context', '--ci'], home)
        hermes_command(['graphify', '--help'], home)

        setup_env = {'_HERMES_GRAPHIFY_SETUP_VAULT': str(vault),
                     '_HERMES_GRAPHIFY_SETUP_FOLDER': 'Nested/Graphify'}
        setup = json.loads(hermes_command(['graphify', 'setup'], home, setup_env))
        assert setup['success']
        graph_root = vault / 'Nested/Graphify'
        index = graph_root / '00_Index.md'
        stamp = index.stat().st_mtime_ns
        assert '[[Nested/Graphify/' in index.read_text(encoding='utf-8')
        assert json.loads(hermes_command(['graphify', 'setup'], home, setup_env))['success']
        assert index.stat().st_mtime_ns == stamp
        (project / 'source').mkdir(parents=True)
        (project / 'source/example.py').write_text('def normalize(x):\n    return x.strip()\n\ndef greeting(x):\n    return normalize(x)\n', encoding='utf-8')
        # Batch launchers must fail safely before interpreting arbitrary project paths.
        dangerous = root / 'Project&literal%TEMP%'
        (dangerous / 'source').mkdir(parents=True)
        try:
            forwarded = hermes_command(['graphify', 'sync', '--project', str(dangerous)], home)
        except ValueError as exc:
            assert str(exc) == 'UNSAFE_BATCH_ARGUMENT'
        else:
            assert json.loads(forwarded)['success']  # A non-batch launcher may forward it literally.
        result = json.loads(hermes_command(['graphify', 'sync', '--project', str(project)], home))
        assert result['success'] and result['indexed'] == 1
        query = json.loads(hermes_command(['graphify', 'query', 'greeting'], home))
        assert 'example.py' in query['output'] and str(project) in query['output']
        explain = json.loads(hermes_command(['graphify', 'explain', 'normalize', '--project', str(project)], home))
        affected = json.loads(hermes_command(['graphify', 'affected', 'normalize', '--project', str(project)], home))
        assert 'normalize' in explain['output'] and 'greeting' in affected['output']
        project_graph = next(graph_root.glob('Projects/*/graphify-out/graph.json'))
        graph = json.loads(project_graph.read_text(encoding='utf-8'))
        assert graph['input_tokens'] == 0 and graph['output_tokens'] == 0
        note = next(graph_root.glob('Projects/*/10_Architecture.md'))
        note.write_text('human verified architecture', encoding='utf-8')
        again = json.loads(hermes_command(['graphify', 'sync', '--project', str(project)], home))
        assert again['success'] and again['indexed'] == 0
        assert note.read_text() == 'human verified architecture'
        health = json.loads(hermes_command(['graphify', 'status'], home))
        assert health['configured'] and health['graphify_ready']
        assert 'graphify-context:setup' in health['bundled_skills']
        assert str(graph_root / '00_Index.md') in health['startup_guidance']
        assert health['automatic_profile_deployment'] is False and health['scheduler'] is False
        assert other.read_bytes() == other_before and not (other.parent / 'plugins').exists()
        print(json.dumps({'success': True, 'mode': 'private-git' if args.repository else 'local-package',
                          'ref': args.ref, 'payload_files_verified': len(PAYLOAD),
                          'native_doctor': True, 'bundled_skill_payloads_verified': True,
                          'metacharacter_project_safe': True,
                          'configuration_guidance_readback': True,
                          'repeat_setup': True, 'actual_extract_query_explain_affected': True,
                          'llm_tokens': 0, 'unchanged_sync': True, 'authored_note_preserved': True,
                          'other_profile_unchanged': True, 'fresh_os_verified': False,
                          'global_graph_sha256': hashlib.sha256((graph_root / 'Global/graphify-out/graph.json').read_bytes()).hexdigest()}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
