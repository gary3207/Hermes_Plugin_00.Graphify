"""Graphify CLI, bundled Skills and read-only new-session guidance."""
import argparse
from datetime import datetime, timezone
import json
import os

from . import setup_graphify as service


def parser(existing=None):
    p = existing or argparse.ArgumentParser(prog='hermes graphify')
    commands = p.add_subparsers(dest='action', required=True)
    setup = commands.add_parser('setup', help='Configure this Profile only')
    vault = os.environ.get('_HERMES_GRAPHIFY_SETUP_VAULT')
    folder = os.environ.get('_HERMES_GRAPHIFY_SETUP_FOLDER')
    setup.add_argument('--vault', required=not vault, default=vault)
    setup.add_argument('--folder', required=not folder, default=folder)
    setup.add_argument('--install-graphify', action='store_true', help='Consent to isolated uv tool installation')
    commands.add_parser('status', help='Read configuration and health without writes')
    commands.add_parser('discover', help='Refresh registered projects; no source scanning')
    sync = commands.add_parser('sync', help='Refresh one actual project and integrated graph')
    sync.add_argument('--project', required=True)
    for name in ('query', 'explain', 'affected'):
        q = commands.add_parser(name)
        q.add_argument('text')
        q.add_argument('--project', required=name != 'query')
    return p


def execute(ctx, args):
    if args.action == 'setup':
        return service.setup(ctx, args.vault, args.folder, install_graphify=args.install_graphify)
    if args.action == 'status':
        result = service.status(ctx)
        result['bundled_skills'] = ['graphify-context:graphify-context', 'graphify-context:setup']
        result['startup_guidance'] = guidance(ctx, {})
        return result
    if args.action == 'discover':
        return service.sync(ctx, discovery_only=True)
    if args.action == 'sync':
        return service.sync(ctx, project=args.project)
    return service.query(ctx, args.text, mode=args.action, project=args.project)


def cli(ctx, args):
    try:
        result = execute(ctx, args)
    except Exception as exc:
        code = str(exc)
        if not code or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for c in code):
            code = 'GRAPHIFY_OPERATION_FAILED'
        result = {'success': False, 'operation': args.action, 'error_type': type(exc).__name__,
                  'error_code': code, 'timestamp': datetime.now(timezone.utc).isoformat(),
                  'fallback': 'Search original code and run tests; Graphify is advisory'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get('success') is False else 0


def guidance(ctx, info):
    prefix = ('# Graphify code context\n'
              '코드 작업은 graphify-context:graphify-context Skill을 로드한다.\n')
    try:
        cfg = service.configured(ctx)
    except (ValueError, OSError):
        return prefix + '미설정: graphify-context:setup Skill로 Vault·상대 폴더를 설정한다. 임의 Vault를 만들지 않는다.\n'
    return (prefix + '등록부: ' + str(service.Path(cfg['vault']) / '00_Index.md') + '\n'
            '전체 그래프에서 재사용 후보를 찾고 프로젝트 그래프·원본 코드의 모든 호출자를 확인한다.\n'
            '작업 후 hermes graphify sync --project <실제 프로젝트 루트>.\n'
            '실패·stale·잠금 충돌이면 원본 검색·테스트로 계속한다. 편집 차단·commit/stash 요구 없음.\n'
            '다른 Profile 자동 배포·스케줄 없음. 원격 호스트는 별도 수동 설치한다.\n')


def register(ctx):
    from pathlib import Path
    required = ('get_config', 'set_config', 'register_cli_command',
                'register_skill', 'register_system_prompt_section')
    if any(not callable(getattr(ctx, key, None)) for key in required):
        raise RuntimeError('HERMES_PLUGIN_API_INCOMPATIBLE')
    root = Path(__file__).parent
    ctx.register_cli_command('graphify', 'Graphify code context for this Profile', parser,
                             lambda args: cli(ctx, args))
    ctx.register_skill('graphify-context', root / 'skills/graphify-context/SKILL.md',
                       description='Find code reuse and impact; refresh changed project')
    ctx.register_skill('setup', root / 'skills/setup/SKILL.md',
                       description='Install and configure Graphify with Vault and relative folder')
    ctx.register_system_prompt_section('graphify-context', lambda info: guidance(ctx, info),
                                       position='after_memory', max_chars=1200)
