"""Persistent, administrator-managed pure-Python wheel store.

Never executes pip/build backends in the API process. A wheel is staged, checked
in a disposable interpreter, then published through an atomic catalog replace.
The configured directory must be shared by every web and worker process.
"""
from __future__ import annotations

import configparser
import contextlib
import email
import fcntl
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from radd.config import settings

MAX_BYTES = 32 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
_managed_paths: set[str] = set()


class PackageError(ValueError):
    pass


def root() -> Path:
    return Path(settings.plugins_dir).resolve()


@contextlib.contextmanager
def locked(*, blocking: bool = True):
    folder = root()
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield folder


def catalog() -> dict[str, dict]:
    file = root() / 'catalog.json'
    return json.loads(file.read_text()) if file.exists() else {}


def _save(entries: dict) -> None:
    fd, name = tempfile.mkstemp(prefix='.catalog-', dir=root())
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(entries, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, root() / 'catalog.json')
    finally:
        Path(name).unlink(missing_ok=True)


def refresh_paths() -> None:
    """Make committed packages discoverable; no .pth execution or site.addsitedir."""
    paths = {str(root() / 'packages' / info['sha256']) for info in catalog().values()}
    if paths == _managed_paths:
        return
    for old in _managed_paths - paths:
        if old in sys.path:
            sys.path.remove(old)
    for path in sorted(paths):
        if path not in sys.path:
            sys.path.append(path)
    _managed_paths.clear()
    _managed_paths.update(paths)
    importlib.invalidate_caches()


def _extract(payload: bytes, stage: Path) -> tuple[str, str, str]:
    if len(payload) > MAX_BYTES:
        raise PackageError('Package exceeds the 32 MiB upload limit')
    try:
        archive = zipfile.ZipFile(__import__('io').BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise PackageError('Upload a valid .whl package') from exc
    with archive:
        members = archive.infolist()
        if len(members) > 10000 or sum(m.file_size for m in members) > MAX_EXPANDED:
            raise PackageError('Package expands beyond the allowed limit')
        names = [m.filename for m in members]
        if len(names) != len(set(names)):
            raise PackageError('Package contains duplicate archive paths')
        metadata = [n for n in names if n.count('/') == 1 and n.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise PackageError('Package must contain exactly one wheel distribution')
        prefix = metadata[0].rsplit('/', 1)[0]
        try:
            meta = email.message_from_bytes(archive.read(metadata[0]))
            wheel = email.message_from_bytes(archive.read(f'{prefix}/WHEEL'))
            entries = configparser.ConfigParser(interpolation=None)
            entries.read_string(archive.read(f'{prefix}/entry_points.txt').decode())
            plugins = list(entries['radd.plugins'].values())
        except (KeyError, ValueError, configparser.Error) as exc:
            raise PackageError('Wheel needs WHEEL metadata and one radd.plugins entry point') from exc
        if len(plugins) != 1 or wheel.get('Root-Is-Purelib', '').lower() != 'true':
            raise PackageError('Upload one pure-Python plugin per wheel')
        tags = wheel.get_all('Tag', [])
        if not tags or any(not tag.endswith('-none-any') for tag in tags):
            raise PackageError('Native/platform-specific wheels require deployment installation')
        module = plugins[0].split(':', 1)[0].strip()
        if not re.fullmatch(r'[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*', module):
            raise PackageError('Invalid plugin entry point module')
        top = module.split('.')[0]
        if top in sys.stdlib_module_names or importlib.util.find_spec(top) is not None:
            raise PackageError(f'Module {top} already exists; use a unique module or restart after removal')
        distribution = canonicalize_name(meta.get('Name', ''))
        version = meta.get('Version', '')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', distribution) or not version:
            raise PackageError('Missing or invalid package name/version')
        from packaging.specifiers import SpecifierSet
        if meta.get('Requires-Python') and not SpecifierSet(meta['Requires-Python']).contains(
            '.'.join(map(str, sys.version_info[:3]))
        ):
            raise PackageError('Package requires a different Python version')
        for raw in meta.get_all('Requires-Dist', []):
            req = Requirement(raw)
            if req.marker and not req.marker.evaluate({'extra': ''}):
                continue
            if req.url:
                raise PackageError(f'Direct dependency {req.name} requires deployment installation')
            try:
                installed = importlib.metadata.version(req.name)
            except importlib.metadata.PackageNotFoundError as exc:
                raise PackageError(f'Dependency {req.name} is not installed; add it to the deployment') from exc
            if installed not in req.specifier:
                raise PackageError(f'Dependency {req.name} {installed} does not satisfy {req.specifier}')
        for member in members:
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (path.is_absolute() or '..' in path.parts or '\\' in member.filename
                    or not path.parts or path.parts[0] not in {top, prefix}
                    or stat.S_ISLNK(mode) or (mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR})
                    or set(path.suffixes) & {'.pth', '.so', '.pyd', '.dll', '.dylib'}):
                raise PackageError(f'Unsupported archive path: {member.filename}')
            destination = stage.joinpath(*path.parts)
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, destination.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
    return distribution, version, module


_PROBE = '''
import importlib,json,sys
sys.path.insert(0,sys.argv[1])
from radd.kernel import RaddPlugin
from radd.kernel.loader import plugin_problems
p=getattr(importlib.import_module(sys.argv[2]),"plugin",None)
if not isinstance(p,RaddPlugin) or p.core: raise ValueError("Export RaddPlugin(core=False)")
problems=plugin_problems(p,set(p.depends_on))
if problems: raise ValueError("; ".join(problems))
print("RADD_PLUGIN_RESULT="+json.dumps({"id":p.id,"name":p.name,"version":p.version,"ui":p.ui.remote if p.ui else None}))
'''


def _prune_interrupted(folder: Path, entries: dict) -> None:
    """Exclusive lock proves no other installer owns these temporary paths."""
    for stage in folder.glob('.staging-*'):
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage)
    for temporary in folder.glob('.catalog-*'):
        temporary.unlink()
    referenced = {info['sha256'] for info in entries.values()}
    packages = folder / 'packages'
    if packages.exists():
        for artifact in packages.iterdir():
            if (re.fullmatch(r'[a-f0-9]{64}', artifact.name) and artifact.name not in referenced
                    and artifact.is_dir() and not artifact.is_symlink()):
                shutil.rmtree(artifact)


def install_wheel(payload: bytes) -> dict:
    with locked() as folder:
        entries = catalog()
        _prune_interrupted(folder, entries)
        with tempfile.TemporaryDirectory(prefix='.staging-', dir=folder) as temporary:
            stage = Path(temporary)
            try:
                distribution, version, module = _extract(payload, stage)
            except (zipfile.BadZipFile, UnicodeError, RuntimeError, NotImplementedError) as exc:
                raise PackageError('Wheel archive is corrupt or uses unsupported compression') from exc
            if distribution in entries:
                raise PackageError('Package already installed. Disable and remove it before uploading another version')
            try:
                probe = subprocess.run([sys.executable, '-c', _PROBE, str(stage), module],
                                       capture_output=True, text=True, timeout=20, check=True)
                result = next(line.removeprefix('RADD_PLUGIN_RESULT=')
                              for line in reversed(probe.stdout.splitlines())
                              if line.startswith('RADD_PLUGIN_RESULT='))
                info = json.loads(result)
            except (subprocess.SubprocessError, StopIteration, ValueError) as exc:
                raise PackageError('Plugin validation failed. Check its manifest, imports and SDK compatibility locally') from exc
            if info['version'] != version:
                raise PackageError('Package and plugin manifest versions differ')
            if not re.fullmatch(r'[a-z][a-z0-9_.-]*', info['id']) or not re.fullmatch(r'[a-z][a-z0-9_-]*', info['name']):
                raise PackageError('Invalid plugin id/name')
            from . import discovery
            known = discovery.all_known()
            if any(p.id == info['id'] or p.name == info['name'] for p, _ in known.values()):
                raise PackageError('Plugin identity collides with an existing plugin')
            if info['ui']:
                if info['ui'] != f"/plugins/{info['name']}/remoteEntry.js":
                    raise PackageError('UI must use the packaged /plugins/<name>/remoteEntry.js URL')
                if not (stage / module.replace('.', '/') / 'ui/dist/remoteEntry.js').is_file():
                    raise PackageError('Wheel is missing its built UI bundle')
            digest = hashlib.sha256(payload).hexdigest()
            target = folder / 'packages' / digest
            target.parent.mkdir(exist_ok=True)
            if target.exists():
                raise PackageError('Package artifact already exists; inspect the plugin store before retrying')
            info.update(distribution=distribution, module=module, sha256=digest)
            os.replace(stage, target)
            try:
                _save({**entries, distribution: info})
            except BaseException:
                shutil.rmtree(target)
                raise
        refresh_paths()
        return info


def remove(plugin_id: str) -> None:
    """Caller verifies desired state and process acknowledgements first."""
    with locked() as folder:
        from .live import ensure_unused
        ensure_unused(plugin_id)
        entries = catalog()
        match = next(((key, info) for key, info in entries.items() if info['id'] == plugin_id), None)
        if match is None:
            raise PackageError('This plugin was not installed through the managed directory')
        key, info = match
        target = folder / 'packages' / info['sha256']
        # Withdraw discovery first; no process will begin loading it after removal.
        del entries[key]
        _save(entries)
        shutil.rmtree(target, ignore_errors=False)
        refresh_paths()
