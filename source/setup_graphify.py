"""Portable, current-Profile-only Graphify setup and operations."""
from pathlib import Path, PureWindowsPath
import os
import shutil

if __package__:
    from . import graphify_ops as ops
else:
    import graphify_ops as ops

PLUGIN = 'graphify-context'
GRAPHIFY_VERSION = '0.9.77'
EXTENSIONS = ['.py', '.pyw', '.ts', '.tsx', '.mts', '.cts', '.js', '.jsx', '.mjs',
              '.cjs', '.go', '.rs', '.java', '.cpp', '.cc', '.cxx', '.c', '.h',
              '.hpp', '.cs', '.rb', '.swift', '.kt', '.kts', '.scala', '.php',
              '.lua', '.ps1', '.psm1', '.psd1', '.sql', '.sh', '.bash', '.vue',
              '.svelte', '.dart', '.ex', '.exs', '.r', '.tf', '.hcl']


def reject_links(path):
    ops.reject_links(path)


def destination(vault, folder):
    vault = Path(vault).expanduser()
    if not vault.is_absolute() or not vault.is_dir():
        raise ValueError('VAULT_MUST_BE_AN_EXISTING_ABSOLUTE_DIRECTORY')
    reject_links(vault)
    raw = str(folder).replace('\\', '/')
    parts = raw.split('/')
    if (PureWindowsPath(raw).drive or PureWindowsPath(raw).root
            or any(not p or p.startswith('.') or p.endswith((' ', '.'))
                   or any(c in '<>:"|?*' or ord(c) < 32 for c in p) for p in parts)):
        raise ValueError('FOLDER_MUST_BE_A_SAFE_VAULT_RELATIVE_PATH')
    vault = vault.resolve()
    root = vault.joinpath(*parts)
    reject_links(root)
    if not root.resolve().is_relative_to(vault):
        raise ValueError('DESTINATION_OUTSIDE_VAULT')
    return {'vault_path': str(vault), 'graphify_folder': '/'.join(parts),
            'graphify_root': str(root)}


def active_home():
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home()).resolve()
    except ImportError:
        fallback = (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'hermes'
                    if os.name == 'nt' else Path.home() / '.hermes')
        return Path(os.environ.get('HERMES_HOME') or fallback).resolve()


def graphify_executable(home):
    bin_dir = Path(home) / 'plugin-data' / PLUGIN / 'tool-bin'
    candidates = [bin_dir / ('graphify.exe' if os.name == 'nt' else 'graphify'),
                  Path(shutil.which('graphify') or 'missing-graphify')]
    for path in candidates:
        if path.is_file():
            try:
                if ops.command([path, '--version'], timeout=30).strip() == 'graphify ' + GRAPHIFY_VERSION:
                    return str(path.resolve())
            except (OSError, RuntimeError):
                continue
    raise RuntimeError('GRAPHIFY_0_9_77_NOT_FOUND_USE_INSTALL_GRAPHIFY')


def configuration(location, home):
    home = Path(home).resolve()
    runtime = home / 'plugin-data' / PLUGIN
    reject_links(runtime)
    binding = runtime / 'destination.json'
    reject_links(binding)
    prior = ops.load(binding, None)
    if prior is not None and prior != {'graphify_root': location['graphify_root']}:
        raise ValueError('DESTINATION_CHANGE_REQUIRES_SEPARATE_MIGRATION')
    return {**location, 'vault': location['graphify_root'], 'runtime': str(runtime),
            'base_home': str(home), 'project_roots': [], 'extensions': EXTENSIONS,
            'managed_output': True, 'link_prefix': location['graphify_folder']}


def configured(ctx, home=None):
    vault = ctx.get_config('vault_path', '')
    folder = ctx.get_config('graphify_folder', '')
    if not vault or not folder:
        raise ValueError('GRAPHIFY_NOT_CONFIGURED')
    return configuration(destination(vault, folder), home or active_home())


def status(ctx, home=None):
    home = Path(home or active_home())
    report = {'configured': False, 'profile_home': str(home),
              'automatic_profile_deployment': False, 'scheduler': False,
              'validated_graphify_version': GRAPHIFY_VERSION}
    if not ctx.get_config('vault_path', '') or not ctx.get_config('graphify_folder', ''):
        return report
    cfg = configured(ctx, home)
    report.update(configured=True, vault_path=cfg['vault_path'],
                  graphify_folder=cfg['graphify_folder'], graphify_root=cfg['vault'])
    try:
        report.update(graphify_ready=True, graphify=graphify_executable(home))
    except RuntimeError:
        report['graphify_ready'] = False
    marker = Path(cfg['vault']) / '.graphify-owner.json'
    report['ownership_ledger_present'] = marker.is_file()
    report['global_graph_present'] = (Path(cfg['vault']) / 'Global/graphify-out/graph.json').is_file()
    report['last_run'] = ops.load(Path(cfg['runtime']) / 'last-run.json', None)
    return report


def setup(ctx, vault, folder, *, home=None, install_graphify=False):
    home = Path(home or active_home())
    location = destination(vault, folder)
    if ctx.get_config('vault_path', '') and ctx.get_config('graphify_folder', ''):
        current = configured(ctx, home)
        if Path(current['vault']) != Path(location['graphify_root']):
            raise ValueError('DESTINATION_CHANGE_REQUIRES_SEPARATE_MIGRATION')
    cfg = configuration(location, home)
    ops.prepare_owned(cfg)  # Refuse foreign files before dependency/configuration writes.
    try:
        executable = graphify_executable(home)
    except RuntimeError:
        if not install_graphify:
            raise
        uv = shutil.which('uv')
        if not uv:
            raise RuntimeError('UV_NOT_FOUND') from None
        env = {**os.environ, 'UV_TOOL_DIR': str(Path(cfg['runtime']) / 'tools'),
               'UV_TOOL_BIN_DIR': str(Path(cfg['runtime']) / 'tool-bin')}
        ops.command([uv, 'tool', 'install', 'graphifyy==' + GRAPHIFY_VERSION],
                    timeout=600, env=env)
        executable = graphify_executable(home)
    cfg['graphify'] = executable
    with ops.host_lock(Path(cfg['vault']) / '.graphify-lock'):
        result = ops.run(cfg, discovery_only=True)
        workflow = ('---\ngenerated: true\n---\n\n# Agent Workflow\n\n'
                    'Load graphify-context:graphify-context before code work.\n'
                    'Use hermes graphify query, explain and affected; verify original callers.\n'
                    'After changes: hermes graphify sync --project <actual-project-root>.\n'
                    'Graph failure is advisory: continue source search and tests.\n'
                    'No Profile deployment, scheduler, watcher or LLM extraction.\n')
        ops.vault_publish(cfg, Path(cfg['vault']) / '10_Agent-Workflow.md', workflow)
    if result['errors']:
        raise RuntimeError('GRAPHIFY_SETUP_INCOMPLETE')
    ops.publish(Path(cfg['runtime']) / 'destination.json',
                ops.packed({'graphify_root': location['graphify_root']}))
    ctx.set_config('vault_path', location['vault_path'])
    ctx.set_config('graphify_folder', location['graphify_folder'])
    return {'success': True, **location, 'graphify': executable,
            'automatic_profile_deployment': False, 'discovery': result}


def sync(ctx, *, project=None, discovery_only=False, home=None):
    cfg = configured(ctx, home)
    if not discovery_only:
        if project is None or not Path(project).is_absolute() or not Path(project).is_dir():
            raise ValueError('SYNC_REQUIRES_AN_EXISTING_ABSOLUTE_PROJECT_ROOT')
        cfg['graphify'] = graphify_executable(home or active_home())
    with ops.host_lock(Path(cfg['vault']) / '.graphify-lock'):
        result = ops.run(cfg, discovery_only=discovery_only, selected=project)
    return {'success': not result['errors'], **result}


def query(ctx, text, *, mode='query', project=None, home=None):
    if mode not in {'query', 'explain', 'affected'}:
        raise ValueError('INVALID_QUERY_MODE')
    cfg = configured(ctx, home)
    owner = ops.prepare_owned(cfg)
    graph = Path(cfg['vault']) / 'Global/graphify-out/graph.json'
    if project is not None:
        actual = Path(project).resolve()
        projects = list(owner.get('state', {}).get('manual_projects', [])) + ops.discover(cfg)
        matches = [p for p in projects if actual.is_relative_to(Path(p['path']).resolve())]
        if not matches:
            raise ValueError('PROJECT_NOT_REGISTERED_RUN_SYNC_FIRST')
        selected = max(matches, key=lambda p: len(Path(p['path']).parts))
        graph = ops.graph_path(cfg, selected)
    elif mode != 'query':
        raise ValueError('EXPLAIN_AND_AFFECTED_REQUIRE_PROJECT')
    ops.safe_vault_path(Path(cfg['vault']), graph)
    relative = graph.relative_to(Path(cfg['vault'])).as_posix()
    if not graph.is_file() or relative not in owner['files']:
        raise ValueError('GRAPH_NOT_AVAILABLE_RUN_SYNC_FIRST')
    if ops.hashlib.sha256(graph.read_bytes()).hexdigest() != owner['files'][relative]:
        raise ValueError('EDITED_GRAPH_PRESERVED')
    args = [graphify_executable(home or active_home()), mode, text, '--graph', graph]
    if mode == 'query':
        args += ['--budget', '1200']
    elif mode == 'affected':
        args += ['--depth', '2']
    return {'success': True, 'graph': str(graph), 'output': ops.command(args, timeout=60)}
