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
EXTRA = {'release.py', 'test_release.py', 'AGENTS.md', 'PUBLICATION.md'}


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


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ''
    require(mode in {'manifest', 'check', 'push'}, 'Usage: python -B release.py manifest|check|push')
    if mode == 'manifest':
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
        head = check()
        if mode == 'push':
            require(git('remote', 'get-url', '--push', '--all', 'origin').decode().splitlines() == [REMOTE], 'Wrong/multiple push targets')
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
