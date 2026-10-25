"""Fail-closed resource snapshots and Git commit coverage; never write Git or run filters."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile


def linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def safe_relative(value):
    path = Path(value)
    if not isinstance(value, str) or not value or path.is_absolute() or path.drive or '..' in path.parts:
        raise ValueError('Expected a resource-relative path')
    return path.as_posix()


def snapshot(root, excluded=(), expected_root=None):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('Resource directory missing')
    if linked(root) and (expected_root is None or root.resolve() != Path(expected_root).resolve()):
        raise ValueError('Resource root link does not match approved binding')
    excluded = {safe_relative(p) for p in excluded}
    entries = {}
    def failed(error):
        raise error
    for directory, dirs, files in os.walk(root, onerror=failed, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            if name.lower().startswith('.env') or name.lower() == '.git' or linked(path):
                raise ValueError('Sensitive or linked resource entry; review without reading it')
        dirs[:] = [name for name in dirs if (Path(directory) / name).relative_to(root).as_posix() not in excluded]
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative in excluded:
                continue
            if not path.is_file():
                raise ValueError('Non-regular resource file')
            before = path.stat()
            content = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError('Resource changed during scan')
            entries[relative] = hashlib.sha256(content).hexdigest()
    return entries


def digest(entries):
    # Retains the v0.1.9 digest format, so existing trusted baselines remain comparable.
    return hashlib.sha256(json.dumps(sorted(entries.items()), ensure_ascii=False).encode('utf-8')).hexdigest()


def git(repo, *args, input=None, timeout=30, env=None, accepted=(0,), return_result=False):
    # Windows Git 启动器的后代可持有管道；临时文件避免超时后的输出回收无限等待。
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors, tempfile.TemporaryFile() as incoming:
        if input is not None:
            incoming.write(input)
        incoming.seek(0)
        process = subprocess.Popen(['git', '-C', str(repo), *args], stdin=incoming,
            env=dict(os.environ, **(env or {})), stdout=output, stderr=errors,
            start_new_session=os.name != 'nt')
        try:
            process.wait(timeout=timeout)
        except BaseException:
            if os.name == 'nt':
                try:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                except (OSError, subprocess.SubprocessError):
                    pass
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            raise
        if process.returncode not in accepted:
            raise ValueError('Git evidence command failed; no completeness claim')
        output.seek(0)
        if return_result:
            errors.seek(0)
            return subprocess.CompletedProcess(process.args, process.returncode, output.read(), errors.read())
        return output.read()


def verify_commit(repo, source, head, excluded=()):
    """Compare all non-excluded files with a concrete commit, including ignored files."""
    if linked(Path(source)):
        raise ValueError('Source link requires a separately reviewed binding')
    repo, source = Path(repo).resolve(), Path(source).resolve()
    if len(head) not in (40, 64) or any(c not in '0123456789abcdef' for c in head):
        raise ValueError('A concrete commit is required')
    prefix = source.relative_to(repo).as_posix()
    if prefix == '.':
        raise ValueError('Bind an explicit resource subtree, not the Git root')
    if git(repo, 'rev-parse', 'HEAD').decode().strip() != head:
        raise ValueError('HEAD changed')
    before = snapshot(source, excluded)
    excluded = {safe_relative(p) for p in excluded}
    def omitted(name):
        return any(name == p or name.startswith(p + '/') for p in excluded)
    tree = {}
    for item in git(repo, 'ls-tree', '-r', '-z', head, '--', prefix + '/').split(b'\0'):
        if not item:
            continue
        metadata, raw_path = item.split(b'\t', 1)
        mode, kind, oid = metadata.decode('ascii').split()
        name = raw_path.decode('utf-8')
        relative = name[len(prefix) + 1:]
        if not name.startswith(prefix + '/') or any(p.lower().startswith('.env') or p.lower() == '.git' for p in Path(relative).parts):
            raise ValueError('Unsafe committed path')
        if mode not in ('100644', '100755') or kind != 'blob':
            raise ValueError('Links/submodules are not complete source snapshots')
        if not omitted(relative):
            tree[relative] = oid
    if set(tree) != set(before):
        raise ValueError('Commit coverage mismatch: missing=' + repr(sorted(set(before)-set(tree))) +
                         ', extra=' + repr(sorted(set(tree)-set(before))))
    for relative, oid in tree.items():
        name = prefix + '/' + relative
        # Never run repository-supplied clean filters; built-in newline normalization only.
        attrs = git(repo, 'check-attr', '-z', 'filter', 'working-tree-encoding', '--', name).split(b'\0')
        if any(attrs[i] not in (b'unspecified', b'unset') for i in range(2, len(attrs)-1, 3)):
            raise ValueError('Custom filter/encoding requires explicit restore verification')
        content = (source / relative).read_bytes()
        if hashlib.sha256(content).hexdigest() != before[relative]:
            raise ValueError('Source changed during commit verification')
        # 当前换行设置改变时，已提交的原始字节仍是有效的完整副本。
        actual = git(repo, 'hash-object', '--no-filters', '--stdin', input=content).decode().strip()
        if actual != oid and git(repo, 'hash-object', '--path=' + name, '--stdin', input=content).decode().strip() != oid:
            raise ValueError('Committed content differs: ' + relative)
    if snapshot(source, excluded) != before or git(repo, 'rev-parse', 'HEAD').decode().strip() != head:
        raise ValueError('Evidence changed during commit verification')
    return dict(head=head, sourceDigest=digest(before), fileCount=len(before),
                files=before, policy='git-built-in-newline-only')


def verify_file(repo, source, head):
    """Verify one explicitly bound document bundle without inspecting other documents."""
    repo, source = Path(repo).resolve(), Path(source)
    if linked(source) or not source.is_file() or source.name.lower().startswith('.env'):
        raise ValueError('Expected regular bound source file')
    relative = source.resolve().relative_to(repo).as_posix()
    if len(head) not in (40, 64) or any(c not in '0123456789abcdef' for c in head):
        raise ValueError('Expected concrete commit')
    if git(repo, 'rev-parse', 'HEAD').decode().strip() != head:
        raise ValueError('HEAD changed')
    entry = git(repo, 'ls-tree', '-z', head, '--', relative).split(b'\0')
    if len(entry) != 2 or not entry[0]:
        raise ValueError('Bound document missing from commit')
    metadata, raw_path = entry[0].split(b'\t', 1)
    mode, kind, oid = metadata.decode().split()
    if mode not in ('100644', '100755') or kind != 'blob' or raw_path.decode() != relative:
        raise ValueError('Invalid bound committed file')
    attrs = git(repo, 'check-attr', '-z', 'filter', 'working-tree-encoding', '--', relative).split(b'\0')
    if any(attrs[i] not in (b'unspecified', b'unset') for i in range(2,len(attrs)-1,3)):
        raise ValueError('Custom filter/encoding requires explicit restore verification')
    content = source.read_bytes()
    actual = git(repo, 'hash-object', '--no-filters', '--stdin', input=content).decode().strip()
    if actual != oid and git(repo, 'hash-object', '--path='+relative, '--stdin', input=content).decode().strip() != oid:
        raise ValueError('Committed document bundle differs')
    if source.read_bytes() != content or git(repo,'rev-parse','HEAD').decode().strip() != head:
        raise ValueError('Document changed during verification')
    return content
