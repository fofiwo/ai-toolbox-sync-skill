"""Public release gate. Run from the public repository root; Python standard library only."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BASE = 'd30213adaf3280a563fa8518a683ccc9c7beb135'
REMOTE = 'https://github.com/fofiwo/ai-toolbox-sync-skill.git'
DATA = 'skills/ai-toolbox-sync/catalog/data.js'
DISCOVERY = 'skills/ai-toolbox-sync/catalog/discovery-data.js'
EXTRA = {'release.py', 'test_release.py', 'AGENTS.md', 'PUBLICATION.md',
         'skills/ai-toolbox-sync/catalog/discovery-data.js',
         'skills/ai-toolbox-sync/catalog/inventory-app.js',
         'skills/ai-toolbox-sync/scripts/build_workspace.py',
         'skills/ai-toolbox-sync/scripts/test_workspace.py',
         'skills/ai-toolbox-sync/scripts/test_workspace.cjs',
         'skills/ai-toolbox-sync/references/self-maintenance.md'}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, timeout=60)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def allowed():
    # 白名单来自已审计公开基线，不能通过改摘要清单添加任意文件。
    return set(git('ls-tree', '-r', '--name-only', BASE).decode().splitlines()) | EXTRA


def validate(files, manifest=True):
    require(set(files) <= allowed(), 'Unexpected public paths; review the explicit allowlist')
    required = allowed() - EXTRA - {'SHA256SUMS.json'}
    require(required <= set(files), 'Required distribution file missing')
    raw = files[DATA].decode('utf-8').strip()
    require(raw.startswith('window.TOOLBOX_DATA ='), 'Invalid catalog assignment')
    require(json.loads(raw.split('=', 1)[1].rstrip(';')) ==
            {'exampleOnly': False, 'resources': []}, 'Public catalog must be empty')
    # Older audited commits predate this template. New workspace distributions need it.
    if 'skills/ai-toolbox-sync/scripts/build_workspace.py' in files:
        require(DISCOVERY in files, 'Discovery template missing')
    if DISCOVERY in files:
        require(files[DISCOVERY].decode('utf-8').strip() ==
                'window.TOOLBOX_DISCOVERY = null;', 'Public discovery must be empty')
    for name, body in files.items():
        require(len(body) <= 2_000_000, 'Oversized public file')
        require(not re.search(rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', body),
                'Credential pattern found; content suppressed')
    if manifest:
        expected = {p: hashlib.sha256(b).hexdigest() for p, b in files.items()
                    if p != 'SHA256SUMS.json'}
        require(json.loads(files['SHA256SUMS.json']) == expected, 'Manifest mismatch')


def tree(rev):
    entries = git('ls-tree', '-rz', rev).split(b'\0')
    paths = []
    for entry in filter(None, entries):
        meta, name = entry.split(b'\t', 1)
        require(meta.split()[0] == b'100644', 'Links/submodules/executables forbidden')
        paths.append(name.decode())
    require(set(paths) <= allowed(), 'Unexpected committed paths; content not read')
    return {p: git('show', rev + ':' + p) for p in paths}


def check():
    require(git('status', '--porcelain', '--untracked-files=all').strip() == b'', 'Working tree must be clean')
    head = git('rev-parse', 'HEAD').decode().strip()
    require(git('merge-base', BASE, head).decode().strip() == BASE, 'Untrusted release ancestry')
    for rev in git('rev-list', head, '^' + BASE).decode().splitlines():
        validate(tree(rev))
    validate(tree(head))
    return head


def compare(local, remote):
    bases = git('merge-base', '--all', local, remote).decode().splitlines()
    require(len(bases) == 1, 'No unique common ancestor; manual review required')
    base = bases[0]
    status = ('aligned' if local == remote else 'local-ahead' if base == remote
              else 'remote-ahead' if base == local else 'diverged')
    def changes(*args):
        return git('diff', '--no-ext-diff', '--no-renames', '--name-status', *args).decode('utf-8')
    return {'status': status, 'local': local, 'remote': remote, 'base': base,
            'localChanges': changes(base, local), 'remoteChanges': changes(base, remote),
            'staged': changes('--cached', local), 'unstaged': changes(),
            'untracked': git('ls-files', '--others', '--exclude-standard').decode('utf-8'),
            'localCommitTime': git('show', '-s', '--format=%cI', local).decode().strip(),
            'remoteCommitTime': git('show', '-s', '--format=%cI', remote).decode().strip()}


def inspect():
    require(git('remote', 'get-url', '--push', '--all', 'origin').decode().splitlines() == [REMOTE], 'Wrong/multiple push targets')
    local = git('rev-parse', 'HEAD').decode().strip()
    # 只获取对象用于比较，不合并、不改安装文件或工作区。
    git('fetch', '--no-tags', '--no-write-fetch-head', REMOTE, 'refs/heads/main')
    remote = git('ls-remote', REMOTE, 'refs/heads/main').decode().split()
    require(len(remote) == 2, 'Missing/ambiguous remote main')
    result = compare(local, remote[0])
    require(git('rev-parse', 'HEAD').decode().strip() == local, 'Local HEAD changed during comparison')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ''
    require(mode in {'inspect', 'manifest', 'check', 'push'}, 'Usage: python -B release.py inspect|manifest|check|push')
    if mode == 'inspect':
        inspect()
    elif mode == 'manifest':
        paths = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')
        paths = set(filter(None, paths))
        require(paths <= allowed(), 'Unexpected working paths; content not read')
        files = {}
        for p in paths:
            target = ROOT / p
            require(not any(x.is_symlink() or x.is_junction() for x in [target, *target.parents] if x != ROOT.parent), 'Linked path forbidden')
            files[p] = target.read_bytes()
        validate(files, manifest=False)
        (ROOT / 'SHA256SUMS.json').write_text(json.dumps({p: hashlib.sha256(b).hexdigest()
            for p, b in sorted(files.items()) if p != 'SHA256SUMS.json'}, indent=2) + '\n', encoding='utf-8')
    else:
        comparison = inspect() if mode == 'push' else None
        head = check()
        if mode == 'push':
            require(comparison['local'] == head, 'Local HEAD changed; compare again')
            require(comparison['status'] in {'aligned', 'local-ahead'}, 'Remote changes require explanation and user choice before merge')
            require(git('symbolic-ref', '--short', 'HEAD').decode().strip() == 'main', 'Publish only main')
            remote_head = git('ls-remote', REMOTE, 'refs/heads/main').decode().split()
            require(len(remote_head) == 2, 'Missing/ambiguous remote main')
            require(git('merge-base', remote_head[0], head).decode().strip() == remote_head[0], 'Remote changed or diverged; compare first')
            # 精确 SHA 推送，不随检查后的 HEAD 变化，不使用 force 或镜像推送。
            git('-c', 'push.followTags=false', '-c', 'remote.origin.mirror=false',
                'push', REMOTE, head + ':refs/heads/main')
        print('PASS', mode, head)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print('BLOCKED:', str(exc), file=sys.stderr)
        sys.exit(1)
