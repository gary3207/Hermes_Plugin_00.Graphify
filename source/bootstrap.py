"""Allowlisted local/ZIP install into the intended current Hermes home only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

if __package__:
    from . import setup_graphify as service
else:
    import setup_graphify as service

PAYLOAD = ('plugin.yaml', '__init__.py', 'setup_graphify.py', 'graphify_ops.py',
           'skills/graphify-context/SKILL.md', 'skills/setup/SKILL.md')


def install_payload(home, source):
    home, source = Path(home).resolve(), Path(source).resolve()
    target = home / 'plugins' / service.PLUGIN
    receipt_path = home / 'plugin-data' / service.PLUGIN / 'install-receipt.json'
    service.reject_links(target)
    service.reject_links(receipt_path)
    receipt = service.ops.load(receipt_path, {'owner': service.PLUGIN, 'files': {}})
    if receipt.get('owner') != service.PLUGIN or not isinstance(receipt.get('files'), dict):
        raise ValueError('INVALID_INSTALL_RECEIPT')
    if target.exists() and any(target.iterdir()):
        manifest = target / 'plugin.yaml'
        if not manifest.is_file() or not re.search(r'^name:\s*graphify-context\s*$',
                                                   manifest.read_text(encoding='utf-8-sig'), re.M):
            raise ValueError('UNRELATED_PLUGIN_COLLISION')
    wanted = {}
    for relative in PAYLOAD:
        origin, dest = source / relative, target / relative
        service.reject_links(origin)
        service.reject_links(dest)
        data = origin.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() not in {
                digest, receipt['files'].get(relative)}:
            raise ValueError('USER_EDITED_PLUGIN_PRESERVED')
        wanted[relative] = (data, digest)
    changed = []
    for relative, (data, digest) in wanted.items():
        if service.ops.publish(target / relative, data):
            changed.append(relative)
        receipt['files'][relative] = digest
    service.ops.publish(receipt_path, service.ops.packed(receipt))
    return {'profile_home': str(home), 'plugin': str(target), 'changed': changed,
            'automatic_profile_deployment': False}


def hermes_command(args, home, extra_env=None):
    launcher = shutil.which('hermes')
    if not launcher:
        raise RuntimeError('HERMES_LAUNCHER_NOT_FOUND')
    env = {**os.environ, **(extra_env or {}), 'HERMES_HOME': str(home),
           'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    return service.ops.command([launcher, '--profile', 'default', *args], timeout=700, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', required=True)
    parser.add_argument('--folder', required=True)
    parser.add_argument('--home', type=Path, help='Explicit isolated/test home; otherwise discover active home')
    parser.add_argument('--install-graphify', action='store_true')
    args = parser.parse_args()
    home = (args.home or service.active_home()).resolve()
    try:
        if not (home / 'config.yaml').is_file():
            raise ValueError('INITIALIZE_HERMES_CONFIGURATION_FIRST')
        service.destination(args.vault, args.folder)
        # Inspect only this Plugin's disablement, not authentication or other Profiles.
        disabled = hermes_command(['config', 'get', 'plugins.disabled'], home)
        if service.PLUGIN in json.loads(disabled):
            raise ValueError('PLUGIN_EXPLICITLY_DISABLED_ENABLE_MANUALLY')
        result = install_payload(home, Path(__file__).parent)
        hermes_command(['plugins', 'enable', service.PLUGIN, '--no-allow-tool-override'], home)
        command = ['graphify', 'setup']
        if args.install_graphify:
            command.append('--install-graphify')
        # Keep arbitrary user paths out of batch-launcher arguments on Windows.
        configured = json.loads(hermes_command(command, home, {
            '_HERMES_GRAPHIFY_SETUP_VAULT': args.vault,
            '_HERMES_GRAPHIFY_SETUP_FOLDER': args.folder}))
        observed = json.loads(hermes_command(['graphify', 'status'], home))
        if not configured.get('success') or not observed.get('configured'):
            raise RuntimeError('SETUP_READBACK_FAILED')
        result.update(success=True, status=observed)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        message = str(exc)
        code = message if message and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for c in message) else 'BOOTSTRAP_FAILED'
        print(json.dumps({'success': False, 'operation': 'bootstrap', 'error_type': type(exc).__name__,
                          'error_code': code}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
