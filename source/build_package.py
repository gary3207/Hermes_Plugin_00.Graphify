"""Build an explicit public payload; never recurse over project source."""
from pathlib import Path
import os
import tempfile
import zipfile

ALLOWLIST = (
    'README.md', 'LICENSE', '.gitignore', '.gitattributes',
    'source/plugin.yaml', 'source/__init__.py', 'source/setup_graphify.py',
    'source/bootstrap.py', 'source/verify_install.py', 'source/graphify_ops.py', 'source/test_plugin.py',
    'source/test_graphify_ops.py', 'source/test_source_exclusions.py',
    'source/test_sync_safety.py', 'source/build_package.py',
    'source/test_build_package.py', 'source/skills/graphify-context/SKILL.md',
    'source/skills/setup/SKILL.md',
)


def build(root):
    root = Path(root).resolve()

    def reject_links(path):
        for candidate in (path, *path.parents):
            if candidate == root:
                break
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            if candidate.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Refusing linked path: ' + str(candidate))

    for name in ALLOWLIST:
        reject_links(root / name)
    payload = {name: (root / name).read_bytes() for name in ALLOWLIST}
    publication = root / 'source/release-repo'
    archive = root / 'Hermes_Plugin_Graphify.zip'
    reject_links(publication)
    reject_links(archive)
    directories = {parent.as_posix() for name in ALLOWLIST
                   for parent in Path(name).parents if parent != Path('.')}
    if publication.exists():
        if not publication.is_dir():
            raise ValueError('Unexpected publication entry: release-repo must be a directory')
        # Existing root .git is opaque metadata: never traverse, copy or remove it.
        def scan_error(error):
            raise error
        for parent, dirs, files in os.walk(publication, onerror=scan_error, followlinks=False):
            if Path(parent) == publication:
                dirs[:] = [name for name in dirs if name != '.git']
                files = [name for name in files if name != '.git']
            for name in dirs + files:
                path = Path(parent) / name
                reject_links(path)
                relative = path.relative_to(publication).as_posix()
                if not ((path.is_file() and relative in ALLOWLIST)
                        or (path.is_dir() and relative in directories)):
                    raise ValueError('Unexpected publication entry: ' + relative)
    for name, data in payload.items():
        target = publication / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if target.read_bytes() != data:
            raise OSError('Publication verification failed: ' + name)
    with tempfile.NamedTemporaryFile(prefix='tmp-package-', suffix='.zip',
                                     dir=root / 'source', delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as package:
            for name, data in payload.items():
                package.writestr(name, data)
        with zipfile.ZipFile(temporary) as package:
            if set(package.namelist()) != set(ALLOWLIST) or package.testzip():
                raise OSError('Archive verification failed')
            for name, data in payload.items():
                if package.read(name) != data:
                    raise OSError('Archive verification failed: ' + name)
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


if __name__ == '__main__':
    print(build(Path(__file__).resolve().parent.parent))
