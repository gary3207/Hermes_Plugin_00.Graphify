"""Local Graphify operations. Generated graphs are caches, never edit gates."""
from pathlib import Path
from fnmatch import fnmatchcase
import hashlib
import os

SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', 'vendor', '__pycache__',
             '.graphify-cache', 'test-work', 'runtime', 'cache', 'dist', 'build'}
# Native Graphify 0.9.77's default reader limit, not an extraction target.
MAX_GRAPH_BYTES = 536_870_912


class GraphTooLargeError(ValueError):
    def __init__(self, size_bytes):
        super().__init__('GRAPH_TOO_LARGE')
        self.size_bytes = size_bytes
        self.limit_bytes = MAX_GRAPH_BYTES


def io_path(path):
    """Use Windows extended paths for I/O without changing source-relative names."""
    path = Path(path)
    if os.name != 'nt':
        return path
    absolute = os.path.abspath(path)
    if absolute.startswith('\\\\?\\'):
        return Path(absolute)
    return Path('\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\')
                else '\\\\?\\' + absolute)


def source_files(root, extensions, exclude_dirs=()):
    if not isinstance(exclude_dirs, (list, tuple)) or any(not isinstance(rule, str) for rule in exclude_dirs):
        raise ValueError('INVALID_SOURCE_EXCLUSIONS')
    source = io_path(Path(root) / 'source')
    files = {}

    def contained(path):
        info = path.lstat()
        return (not path.is_symlink()
                and not getattr(info, 'st_file_attributes', 0) & 0x400
                and path.resolve().is_relative_to(source.resolve()))

    try:
        source.lstat()
    except FileNotFoundError:
        return files
    if (not contained(source) or not source.is_dir()
            or not source.resolve().is_relative_to(io_path(root).resolve())):
        raise OSError('Source root is outside the scan boundary')

    def scan_error(error):
        raise OSError('Source scan incomplete; previous graph retained') from None

    for parent, dirs, names in os.walk(source, followlinks=False, onerror=scan_error):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS
                         and not any(fnmatchcase((Path(parent) / d).relative_to(source).as_posix(), rule)
                                     for rule in exclude_dirs)
                         and contained(Path(parent) / d))
        for name in sorted(names):
            p = Path(parent) / name
            if name.startswith('.env') or name.lower() in {'auth.json', 'credentials.json', 'secrets.json'}:
                continue
            if p.suffix.lower() in extensions and contained(p):
                files[p.relative_to(source).as_posix()] = p
    return dict(sorted(files.items()))


def fingerprint(files):
    digest = hashlib.sha256()
    for name, path in sorted(files.items()):
        digest.update(name.encode('utf-8') + b'\0' + hashlib.sha256(Path(path).read_bytes()).digest())
    return digest.hexdigest()


def publish(target, text, authored=False):
    target = Path(target)
    reject_links(target)
    data = text.encode('utf-8') if isinstance(text, str) else text
    if target.exists() and (authored or target.read_bytes() == data):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.graphify-', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
        reject_links(target)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    if target.read_bytes() != data:
        raise OSError('Publication verification failed: ' + str(target))
    return True


def install_managed(target, text, state):
    target = Path(target)
    data = text.encode('utf-8')
    wanted = hashlib.sha256(data).hexdigest()
    current = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
    key = str(target)
    if current is not None and current not in {wanted, state.get(key)}:
        return 'preserved-user-edit'
    changed = publish(target, data)
    state[key] = wanted
    return 'installed' if changed else 'unchanged'


def prepare_owned(cfg):
    """Only the reinstallable plugin uses this ledger; legacy CLI stays compatible."""
    root = Path(cfg['vault'])
    marker = root / '.graphify-owner.json'
    safe_vault_path(root, marker)
    owner = load(marker, None)
    if owner is None:
        reserved = [root / '00_Index.md', root / '10_Agent-Workflow.md',
                    root / 'Global/manifest.json', root / 'Global/graphify-out/graph.json']
        if any(p.exists() for p in reserved) or (root / 'Projects').exists():
            raise ValueError('UNOWNED_GRAPHIFY_DESTINATION')
        owner = {'owner': 'graphify-context', 'version': 1, 'files': {}}
    if (not isinstance(owner, dict) or owner.get('owner') != 'graphify-context'
            or owner.get('version') != 1 or not isinstance(owner.get('files'), dict)):
        raise ValueError('INVALID_OWNERSHIP_LEDGER')
    for relative, digest in owner['files'].items():
        safe_vault_path(root, root / relative)
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('INVALID_OWNERSHIP_LEDGER')
    cfg['_owner'] = owner
    return owner


def reject_links(target):
    target = Path(target)
    for path in (target, *target.parents):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('UNSAFE_OUTPUT_LINK')


def safe_vault_path(root, target):
    root, target = Path(root), Path(target)
    reject_links(target)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('OUTPUT_OUTSIDE_GRAPHIFY_ROOT')


def vault_publish(cfg, target, text, authored=False):
    if not cfg.get('managed_output'):
        return publish(target, text, authored)
    root, target = Path(cfg['vault']), Path(target)
    safe_vault_path(root, target)
    if authored:
        return publish(target, text, authored=True)
    owner = cfg['_owner']
    relative = target.relative_to(root).as_posix()
    wanted = hashlib.sha256(text.encode('utf-8') if isinstance(text, str) else text).hexdigest()
    if target.exists():
        current = hashlib.sha256(target.read_bytes()).hexdigest()
        previous = owner['files'].get(relative)
        if previous is None:
            raise ValueError('UNOWNED_GENERATED_FILE')
        if current not in {previous, wanted}:
            raise ValueError('EDITED_GENERATED_FILE_PRESERVED')
    changed = publish(target, text)
    owner['files'][relative] = wanted
    publish(root / '.graphify-owner.json', packed(owner))
    return changed


def merge_graphs(projects, graphs):
    """Namespace projects without collapsing direction or parallel relations."""
    nodes, links, hyperedges = [], [], []
    for project in projects:
        pid = project['id']
        prefix = pid + '::'
        root = prefix + 'PROJECT'
        nodes.append({'id': root, 'label': project['name'], 'file_type': 'project',
                      'project_id': pid, 'source_root': project['path']})
        graph = graphs.get(pid, {})
        valid = {str(n['id']) for n in graph.get('nodes', [])}
        for node in graph.get('nodes', []):
            item = {**node, 'id': prefix + str(node['id']), 'project_id': pid,
                    'repo': pid, 'source_root': project['path']}
            source = node.get('source_file')
            if source:
                item['source_file'] = str(Path(project['path']) / 'source' / source)
            nodes.append(item)
            if node.get('file_type') == 'code' and str(node.get('label', '')).endswith(('.py', '.pyw', '.js', '.ts', '.ps1')):
                links.append({'source': root, 'target': item['id'], 'relation': 'contains',
                              'confidence': 'EXTRACTED', 'project_id': pid, 'key': len(links)})
        for edge in graph.get('edges', graph.get('links', [])):
            source, target = str(edge['source']), str(edge['target'])
            if source not in valid or target not in valid:
                raise ValueError('Dangling relation in ' + pid)
            links.append({**edge, 'source': prefix + source, 'target': prefix + target,
                          'project_id': pid, 'key': len(links)})
        for edge in graph.get('hyperedges', []):
            item = {**edge, 'id': prefix + str(edge.get('id', len(hyperedges))), 'project_id': pid}
            for field in ('nodes', 'members'):
                if field in item:
                    item[field] = [prefix + str(n) for n in item[field]]
            hyperedges.append(item)
    return {'directed': True, 'multigraph': True, 'graph': {'hyperedges': hyperedges},
            'nodes': nodes, 'links': links, 'hyperedges': hyperedges}


import argparse
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time


def packed(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def graph_payload(graph):
    data = packed(graph).encode('utf-8')
    if len(data) > MAX_GRAPH_BYTES:
        raise GraphTooLargeError(len(data))
    return data


def failure_details(exc):
    # Fixed metadata only; extractor output and exception arguments can contain secrets.
    details: dict = {'error_type': type(exc).__name__}
    if isinstance(exc, GraphTooLargeError):
        details.update(error_code='GRAPH_TOO_LARGE', size_bytes=exc.size_bytes,
                       limit_bytes=exc.limit_bytes)
    elif isinstance(exc, subprocess.TimeoutExpired):
        details.update(error_code='EXTRACTION_TIMEOUT', timeout_seconds=exc.timeout)
    elif str(exc) == 'Source changed during extraction; previous graph retained':
        details['error_code'] = 'SOURCE_CHANGED_DURING_EXTRACTION'
    elif str(exc) in {'INVALID_EXTRACT_TIMEOUT_SECONDS', 'INVALID_SOURCE_EXCLUSIONS'}:
        details['error_code'] = str(exc)
    return details


def load(path, default):
    return json.loads(Path(path).read_text(encoding='utf-8-sig')) if Path(path).exists() else default


def command(args, timeout=180, env=None):
    args = [str(a) for a in args]
    if Path(args[0]).suffix.lower() in {'.cmd', '.bat'} and any(
            c in '&|<>^%!"' or ord(c) < 32 for arg in args for c in arg):
        raise ValueError('UNSAFE_BATCH_ARGUMENT')
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout, env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        # Do not persist source text or credentials from an extractor traceback.
        raise RuntimeError(Path(str(args[0])).name + ' exit ' + str(result.returncode))
    return result.stdout


def discover(cfg):
    by_path = {}
    base = Path(cfg['base_home'])
    db = base / 'projects.db'
    if db.exists():
        with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            folders = list(conn.execute('SELECT project_id,path FROM project_folders')) if 'project_folders' in tables else []
            for row in conn.execute('SELECT id,name,primary_path FROM projects'):
                paths = list(dict.fromkeys(p for p in [row['primary_path'], *[f['path'] for f in folders if f['project_id'] == row['id']]] if p))
                for i, path in enumerate(paths):
                    p = Path(path).resolve()
                    pid = row['id'] if i == 0 else row['id'] + '-' + hashlib.sha256(str(p).casefold().encode()).hexdigest()[:8]
                    by_path[str(p).casefold()] = {'id': pid, 'name': row['name'], 'path': str(p), 'origin': 'desktop', 'desktop_id': row['id']}
    for root in cfg['project_roots']:
        root = Path(root)
        if not root.exists():
            continue
        for category in sorted(root.iterdir()):
            if category.is_dir() and not category.is_symlink():
                for path in sorted(category.iterdir()):
                    if path.is_dir() and not path.is_symlink() and not path.name.startswith('.'):
                        key = str(path.resolve()).casefold()
                        by_path.setdefault(key, {'id': 'fs_' + hashlib.sha256(key.encode()).hexdigest()[:12],
                                                 'name': path.name, 'path': str(path.resolve()), 'origin': 'filesystem'})
    return sorted(by_path.values(), key=lambda p: (p['path'].casefold(), p['id']))


def project_id(project):
    import re
    pid = project['id']
    if (not isinstance(pid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', pid)
            or pid.upper() in {'CON', 'PRN', 'AUX', 'NUL',
                              *('COM' + str(i) for i in range(1, 10)),
                              *('LPT' + str(i) for i in range(1, 10))}):
        raise ValueError('INVALID_PROJECT_ID')
    return pid


def graph_path(cfg, project):
    target = Path(cfg['vault']) / 'Projects' / project_id(project) / 'graphify-out/graph.json'
    safe_vault_path(cfg['vault'], target)
    return target


def cache_path(cfg, project):
    root = Path(project['path'])
    pid = project_id(project)
    # Runtime data stays outside OneDrive; task-owned staging otherwise stays in source/.
    if 'onedrive' in str(root).casefold() or not root.exists():
        boundary = Path(cfg['runtime'])
        cache = boundary / 'cache' / pid
    else:
        boundary = root
        cache = root / 'source/.graphify-cache' / pid
    for target in (cache, cache / 'graphify-out/graph.json', cache / 'manifest.json'):
        safe_vault_path(boundary, target)
    return cache


def rebuild(cfg, project, previous, version):
    root = Path(project['path'])
    if not root.is_dir():
        raise FileNotFoundError('Project root not available')
    timeout = cfg.get('project_extract_timeout_seconds', {}).get(
        project['id'], cfg.get('extract_timeout_seconds', 300))
    if type(timeout) is not int or timeout <= 0:
        raise ValueError('INVALID_EXTRACT_TIMEOUT_SECONDS')
    exclude_dirs = cfg.get('source_exclusions', {}).get(project['id'], ())
    files = source_files(root, set(cfg['extensions']), exclude_dirs)
    source_present = (root / 'source').is_dir()
    if not source_present and (previous.get('files', 0)
                               or previous.get('source_present', 'fingerprint' in previous)):
        raise OSError('Previously indexed source is unavailable; previous graph retained')
    current = fingerprint(files)
    destination = graph_path(cfg, project)
    cache = cache_path(cfg, project)
    if previous.get('fingerprint') == current and previous.get('version') == version and destination.exists():
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if actual == previous.get('graph_hash'):
            return {**previous, 'status': 'current'}, False
    cache.mkdir(parents=True, exist_ok=True)
    graph = {'nodes': [], 'edges': [], 'hyperedges': [], 'input_tokens': 0, 'output_tokens': 0}
    extract_seconds = 0
    if files:
        # ponytail: rebuild only the changed project; native file-incremental staging if project size becomes a bottleneck.
        with tempfile.TemporaryDirectory(prefix='build-', dir=cache) as tmp:
            staging = Path(tmp) / 'input'
            staging.mkdir()
            aliases = {}
            staged_names = set()
            for relative, path in files.items():
                staged = relative + '.py' if path.suffix.lower() == '.pyw' else relative
                if os.name == 'nt' and len(str(staging / staged)) >= 240:
                    # Graphify normalizes away extended prefixes; shorten only staged paths.
                    staged = '_long_paths/' + hashlib.sha256(staged.encode('utf-8')).hexdigest() + (
                        '.py' if path.suffix.lower() == '.pyw' else path.suffix)
                if staged.casefold() in staged_names:
                    raise ValueError('Source staging collision; previous graph retained')
                staged_names.add(staged.casefold())
                aliases[staged] = relative
                target = staging / staged
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            started = time.perf_counter()
            command([cfg['graphify'], 'extract', staging, '--out', Path(tmp) / 'output',
                     '--code-only', '--no-cluster', '--no-dedup', '--max-workers', '1'], timeout=timeout)
            extract_seconds = round(time.perf_counter() - started, 3)
            graph = load(Path(tmp) / 'output/graphify-out/graph.json', None)
            if not isinstance(graph, dict) or 'nodes' not in graph:
                raise ValueError('Extractor did not produce a valid graph')
            for item in [*graph['nodes'], *graph.get('edges', graph.get('links', []))]:
                source = item.get('source_file')
                if source:
                    source = str(source).replace('\\', '/')
                    if Path(source).is_absolute():
                        source = Path(source).relative_to(staging).as_posix()
                    item['source_file'] = aliases.get(source, source)
                    if item.get('label') == source:
                        item['label'] = aliases.get(source, source)
                    elif source in aliases and item.get('label') == Path(source).name:
                        item['label'] = Path(aliases[source]).name
            graph['extracted_sources'] = [str(path) for path in files.values()]
    if (fingerprint(source_files(root, set(cfg['extensions']), exclude_dirs)) != current
            or (source_present and not (root / 'source').is_dir())):
        raise RuntimeError('Source changed during extraction; previous graph retained')
    # Raw AST output names external imports without creating their nodes. Preserve those
    # extracted references explicitly; do not pretend their implementation was indexed.
    ids = {str(n['id']) for n in graph['nodes']}
    for edge in graph.get('edges', graph.get('links', [])):
        for endpoint in (str(edge['source']), str(edge['target'])):
            if endpoint not in ids:
                graph['nodes'].append({'id': endpoint, 'label': endpoint, 'file_type': 'external',
                                       'resolution': 'out-of-scope-reference', '_origin': 'ast-reference'})
                ids.add(endpoint)
    # Catch dangling endpoints before publishing either per-project or global state.
    merge_graphs([project], {project['id']: graph})
    data = graph_payload(graph)
    vault_publish(cfg, destination, data)
    publish(cache / 'graphify-out/graph.json', data)
    try:
        git_head = command(['git', '-C', root, 'rev-parse', 'HEAD']).strip()
        dirty = bool(command(['git', '-C', root, 'status', '--porcelain']).strip())
    except (OSError, RuntimeError):
        git_head, dirty = None, None
    meta = {'fingerprint': current, 'version': version, 'graph_hash': hashlib.sha256(data).hexdigest(),
            'files': len(files), 'source_present': source_present,
            'extract_timeout_seconds': timeout, 'extract_seconds': extract_seconds,
            'graph_bytes': len(data),
            'nodes': len(graph['nodes']), 'edges': len(graph.get('edges', graph.get('links', []))),
            'indexed_at': datetime.now(timezone.utc).isoformat(), 'git_head': git_head, 'dirty': dirty,
            'status': 'current', 'graph': str(destination), 'cache': str(cache)}
    publish(cache / 'manifest.json', packed(meta))
    return meta, True


def project_notes(cfg, project, meta):
    folder = Path(cfg['vault']) / 'Projects' / project['id']
    root = Path(project['path'])
    archive = ''
    if project.get('desktop_id') and cfg.get('archive_folder'):
        archive = f"\n- 기존 기록: [[{cfg['archive_folder']}/10_Projects/{project['name']}--{project['desktop_id']}/00_Overview]]\n"
    body = ('---\ngenerated: true\n---\n\n# ' + project['name'] + '\n\n'
            + f"- Project ID: `{project['id']}`\n- 원본: `{root}`\n- 등록 근거: {project['origin']}\n"
            + '- 분석 범위: source/의 지원 코드 확장자. 문서·런타임·인증 파일 제외.\n'
            + f"- 상태: {meta.get('status', 'not-indexed')}\n- 코드 파일: {meta.get('files', '미분석')}\n"
            + f"- 분석 시각: {meta.get('indexed_at', '없음')}\n- 입력 지문: `{meta.get('fingerprint', '없음')}`\n"
            + f"- 그래프: `{graph_path(cfg, project)}`\n- 캐시: `{cache_path(cfg, project)}`\n" + archive)
    vault_publish(cfg, folder / '00_Project.md', body)
    vault_publish(cfg, folder / '10_Architecture.md', '---\ngenerated: false\n---\n\n# Architecture\n\n'
            '아직 사람이 확인한 설계 요약은 없습니다. 아래 항목은 실제 코드를 읽고 근거 위치와 함께 작성합니다.\n\n'
            '- 주요 실행 흐름 및 모듈 책임\n- 외부 계약·데이터 형식·변경 불변조건\n- 관련 테스트와 기존 Hermes 결정 링크\n', authored=True)
    vault_publish(cfg, folder / '20_Reuse.md', '---\ngenerated: false\n---\n\n# Reuse\n\n'
            '아직 검증된 재사용 목록은 없습니다. 글로벌 그래프의 유사 이름은 후보이지 기능 동일성의 증명이 아닙니다.\n\n'
            '| 기능 | 기존 구현·원본 위치 | 사용 조건 | 관련 테스트 |\n|---|---|---|---|\n', authored=True)


def global_graph(cfg, projects, state):
    graphs = {}
    for project in projects:
        path = graph_path(cfg, project)
        data = path.read_bytes() if path.is_file() else None
        if cfg.get('managed_output'):
            relative = path.relative_to(Path(cfg['vault'])).as_posix()
            expected = cfg['_owner']['files'].get(relative)
            if expected is not None and not path.is_file():
                raise ValueError('OWNED_PROJECT_GRAPH_UNAVAILABLE')
            if data is not None and (expected is None or
                    hashlib.sha256(data).hexdigest() != expected):
                raise ValueError('UNOWNED_OR_EDITED_PROJECT_GRAPH_PRESERVED')
        if data is not None:
            graphs[project['id']] = json.loads(data.decode('utf-8-sig'))
    merged = merge_graphs(projects, graphs)
    target = Path(cfg['vault']) / 'Global/graphify-out/graph.json'
    data = graph_payload(merged)
    changed = vault_publish(cfg, target, data)
    counts = {'projects': len(projects), 'nodes': len(merged['nodes']), 'edges': len(merged['links']),
              'indexed_projects': len(graphs), 'nonempty_projects': sum(bool(g.get('nodes')) for g in graphs.values()),
              'graph_bytes': len(data)}
    manifest = {**counts, 'graph_hash': hashlib.sha256(target.read_bytes()).hexdigest(),
                'projects': [{**p, **state.get('projects', {}).get(p['id'], {})} for p in projects],
                'cross_project_policy': 'namespace-preserved union; same names do not imply dependency'}
    vault_publish(cfg, target.parent.parent / 'manifest.json', packed(manifest))
    report = ('---\ngenerated: true\n---\n\n# 전체 프로젝트 통합 그래프\n\n'
              + f"- 프로젝트: {counts['projects']}\n- 코드 노드가 있는 프로젝트: {counts['nonempty_projects']}\n"
              + f"- 노드: {counts['nodes']}\n- 관계: {counts['edges']}\n\n"
              + '프로젝트별 namespace, 관계 방향, 동일 노드 사이의 여러 관계를 보존합니다.\n'
              + '이름이 같다는 이유로 프로젝트 간 의존 관계를 만들어내지 않습니다. 원본과 테스트로 확인하세요.\n')
    vault_publish(cfg, target.parent / 'GRAPH_REPORT.md', report)
    return counts, changed


def run(cfg, discovery_only=False, selected=None, provision=False):
    if provision:
        raise ValueError('Automatic Profile deployment is excluded')
    started = time.perf_counter()
    try:
        owner = prepare_owned(cfg) if cfg.get('managed_output') else None
    except (ValueError, OSError) as exc:
        return {'indexed': 0, 'errors': ['Ownership: ' + type(exc).__name__],
                'profiles': {}, 'global_changed': False}
    runtime = Path(cfg['runtime'])
    reject_links(runtime / 'state.json')
    reject_links(runtime / 'last-run.json')

    state: dict = load(runtime / 'state.json', (owner or {}).get('state',
                              {'projects': {}, 'profiles': {}, 'deployment': {}}))
    projects = discover(cfg)
    by_path = {p['path'].casefold(): p for p in projects}
    for p in state.get('manual_projects', []):
        by_path.setdefault(p['path'].casefold(), p)
    if selected:
        actual = Path(selected).resolve()
        if not any(actual.is_relative_to(Path(p['path'])) for p in by_path.values()):
            if not actual.is_dir():
                raise FileNotFoundError('Explicit project root does not exist')
            key = str(actual).casefold()
            p = {'id': 'fs_' + hashlib.sha256(key.encode()).hexdigest()[:12],
                 'name': actual.name, 'path': str(actual), 'origin': 'explicit-project'}
            state.setdefault('manual_projects', []).append(p)
            by_path[key] = p
    projects = sorted(by_path.values(), key=lambda p: p['path'].casefold())
    for project in projects:
        project_id(project)
    runtime.mkdir(parents=True, exist_ok=True)
    result: dict = {'indexed': 0, 'errors': [], 'profiles': {}, 'projects': len(projects)}

    if not discovery_only:
        try:
            version = command([cfg['graphify'], '--version']).strip()
        except Exception as exc:
            version = 'unavailable'
            result['errors'].append('Graphify unavailable: ' + type(exc).__name__)
        for project in projects:
            if selected and not Path(selected).resolve().is_relative_to(Path(project['path']).resolve()):
                continue
            previous = state['projects'].get(project['id'], {})
            try:
                meta, changed = rebuild(cfg, project, previous, version)
                state['projects'][project['id']] = meta
                result['indexed'] += int(changed)
            except Exception as exc:
                state['projects'][project['id']] = {**previous, 'status': 'stale' if previous else 'not-indexed',
                                                   'error_type': type(exc).__name__}
                result['errors'].append(project['id'] + ': ' + type(exc).__name__)
                result.setdefault('error_details', {})[project['id']] = failure_details(exc)
    for project in projects:
        project_notes(cfg, project, state['projects'].get(project['id'], {}))
    prefix = cfg.get('link_prefix', 'Graphify')
    index = ('---\ngenerated: true\n---\n\n# Graphify\n\n'
             + f'- [[{prefix}/10_Agent-Workflow]]\n'
             + f'- [[{prefix}/Global/graphify-out/GRAPH_REPORT|전체 프로젝트 통합 그래프]]\n\n')
    index += '| 프로젝트 | 실제 경로 | 상태 | 지식 |\n|---|---|---|---|\n'
    for p in projects:
        meta = state['projects'].get(p['id'], {})
        index += f"| {p['name']} | `{p['path']}` | {meta.get('status', 'not-indexed')} | [[{prefix}/Projects/{p['id']}/00_Project]] |\n"
    vault_publish(cfg, Path(cfg['vault']) / '00_Index.md', index)
    signature = hashlib.sha256(packed([{'id': p['id'], 'path': p['path'],
                          'graph': state['projects'].get(p['id'], {}).get('graph_hash'),
                          'fingerprint': state['projects'].get(p['id'], {}).get('fingerprint'),
                          'status': state['projects'].get(p['id'], {}).get('status')} for p in projects]).encode()).hexdigest()
    target = Path(cfg['vault']) / 'Global/graphify-out/graph.json'
    try:
        # Validate every input even when only another project (or no source) changed.
        result['global'], result['global_changed'] = global_graph(cfg, projects, state)
        state['global_signature'] = signature
        state['global_graph_hash'] = hashlib.sha256(target.read_bytes()).hexdigest()
        state['global_counts'] = result['global']
    except Exception as exc:
        result['errors'].append('Global graph: ' + type(exc).__name__)
        result.setdefault('error_details', {})['Global graph'] = failure_details(exc)
        result['global'], result['global_changed'] = state.get('global_counts', {}), False
    publish(runtime / 'state.json', packed(state))
    if owner is not None:
        owner['state'] = state
        safe_vault_path(Path(cfg['vault']), Path(cfg['vault']) / '.graphify-owner.json')
        publish(Path(cfg['vault']) / '.graphify-owner.json', packed(owner))
    result['seconds'] = round(time.perf_counter() - started, 3)
    publish(runtime / 'last-run.json', packed(result))
    return result


@contextmanager
def host_lock(runtime):
    target = Path(runtime) / 'sync.lock'
    reject_links(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    reject_links(target)
    with target.open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if not target.stat().st_size:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('graphify-config.json'))
    parser.add_argument('--discover-only', action='store_true', help='Project registration only; never deploys Profiles')
    parser.add_argument('--project', help='Actual project root or working subdirectory; otherwise all discovered projects')
    args = parser.parse_args()
    cfg = load(args.config, None)
    try:
        with host_lock(cfg['runtime']):
            result = run(cfg, args.discover_only, args.project)
    except OSError as exc:
        result = {'status': 'busy-or-unavailable', 'error_type': type(exc).__name__, 'fallback': 'search original code and run tests'}
    print(packed(result))
    return 0  # Advisory service never denies an Agent edit; diagnostics live in last-run.json.


if __name__ == '__main__':
    raise SystemExit(main())
