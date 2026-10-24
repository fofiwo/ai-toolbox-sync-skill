"""Public release gate. Run from the public repository root; Python standard library only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
BASE = 'd30213adaf3280a563fa8518a683ccc9c7beb135'
REMOTE = 'https://github.com/fofiwo/ai-toolbox-sync-skill.git'
DATA = 'skills/ai-toolbox-sync/catalog/data.js'
DISCOVERY = 'skills/ai-toolbox-sync/catalog/discovery-data.js'
VERSION = 'skills/ai-toolbox-sync/VERSION'
SKILL = 'skills/ai-toolbox-sync/SKILL.md'
INDEX = 'skills/ai-toolbox-sync/catalog/index.html'
VERSION_FIELDS = {
    SKILL: rb'(?m)^  version: ([^\r\n]+)',
    'README.md': '公开分发版本：([^；\r\n]+)'.encode('utf-8'),
    INDEX: '个人 AI 工具箱 / ([^<\r\n]+)'.encode('utf-8'),
}
SEMVER = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?')
EXTRA = {'release.py', 'test_release.py', 'AGENTS.md', 'PUBLICATION.md',
         'skills/ai-toolbox-sync/catalog/discovery-data.js',
         'skills/ai-toolbox-sync/catalog/inventory-app.js',
         'skills/ai-toolbox-sync/scripts/build_workspace.py',
         'skills/ai-toolbox-sync/scripts/test_workspace.py',
         'skills/ai-toolbox-sync/scripts/test_workspace.cjs',
         'skills/ai-toolbox-sync/references/self-maintenance.md',
         'skills/ai-toolbox-sync/references/git-workflow.md',
         'skills/ai-toolbox-sync/scripts/test_native_git.py',
         'skills/ai-toolbox-sync/scripts/resource_files.py',
         'skills/ai-toolbox-sync/scripts/test_resource_files.py',
         'skills/ai-toolbox-sync/scripts/test_resource_migration.py', VERSION}


# Exact historical dependency files retired from the independent distribution.
# Still allowed for validating old commits; no other baseline file is optional.
RETIRED = {
    'skills/ai-toolbox-sync/assets/skillshare-v0.26.1-checksums.txt',
    'skills/ai-toolbox-sync/references/upstream/TROUBLESHOOTING.md',
    'skills/ai-toolbox-sync/references/upstream/audit.md',
    'skills/ai-toolbox-sync/references/upstream/backup.md',
    'skills/ai-toolbox-sync/references/upstream/extras.md',
    'skills/ai-toolbox-sync/references/upstream/hooks.md',
    'skills/ai-toolbox-sync/references/upstream/init.md',
    'skills/ai-toolbox-sync/references/upstream/install.md',
    'skills/ai-toolbox-sync/references/upstream/log.md',
    'skills/ai-toolbox-sync/references/upstream/mcp.md',
    'skills/ai-toolbox-sync/references/upstream/memory-review.md',
    'skills/ai-toolbox-sync/references/upstream/native-agents.md',
    'skills/ai-toolbox-sync/references/upstream/plugins.md',
    'skills/ai-toolbox-sync/references/upstream/status.md',
    'skills/ai-toolbox-sync/references/upstream/sync.md',
    'skills/ai-toolbox-sync/references/upstream/targets.md',
    'skills/ai-toolbox-sync/references/upstream/trash.md',
}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, timeout=60)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def semver(value):
    match = SEMVER.fullmatch(value)
    require(match is not None, 'Expected a semantic version: MAJOR.MINOR.PATCH[-prerelease][+build]')
    major, minor, patch, pre, build = match.groups()
    identifiers = (pre or '').split('.') if pre else []
    require(all(not (part.isdigit() and len(part) > 1 and part.startswith('0')) for part in identifiers),
            'Numeric prerelease identifiers cannot have leading zeroes')
    return (int(major), int(minor), int(patch)), identifiers


def version_key(value):
    core, pre = semver(value)
    # SemVer: numeric identifiers sort before text; a stable release follows prereleases.
    return core, not pre, tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre)


def version_from(files, managed=False):
    if VERSION in files:
        value = files[VERSION].decode('ascii').strip()
        semver(value)
        for name, pattern in VERSION_FIELDS.items():
            matches = list(re.finditer(pattern, files[name]))
            require(len(matches) == 1 and matches[0].group(1).decode('utf-8') == value,
                    'Version mismatch in ' + name + '; run release.py bump after reviewing local edits')
        return value
    require(not managed, 'Managed VERSION file missing')
    matches = list(re.finditer(VERSION_FIELDS[SKILL], files[SKILL]))
    require(len(matches) == 1, 'Missing/ambiguous legacy Skill version')
    value = matches[0].group(1).decode('utf-8')
    semver(value)
    return value


def next_version(value, part):
    core, pre = semver(value)
    numbers = list(core)
    if part == 'final':
        require(bool(pre), 'Version is already stable')
        pre = []
    elif part == 'prerelease':
        require(bool(pre), 'A stable version needs a patch/minor/major bump first')
        pre = pre[:-1] + [str(int(pre[-1]) + 1)] if pre[-1].isdigit() else pre + ['1']
    else:
        require(part in ('patch', 'minor', 'major'), 'Choose patch, minor, major, prerelease or final')
        index = {'major': 0, 'minor': 1, 'patch': 2}[part]
        numbers[index] += 1
        numbers[index + 1:] = [0] * (2 - index)
    return '.'.join(map(str, numbers)) + ('-' + '.'.join(pre) if pre else '')


def working_files(extra_paths=()):
    paths = set(filter(None, git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')))
    require(paths <= allowed() | set(extra_paths), 'Unexpected working paths; content not read')
    files = {}
    for name in sorted(paths):
        path = ROOT / name
        require(not any(p.is_symlink() or p.is_junction() for p in (path, *path.parents) if p != ROOT.parent),
                'Linked path forbidden')
        if not path.exists() and name in RETIRED:
            continue
        files[name] = path.read_bytes()
    return files


def with_manifest(files):
    result = dict(files)
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items()) if name != 'SHA256SUMS.json'}
    result['SHA256SUMS.json'] = (json.dumps(hashes, indent=2) + '\n').encode('utf-8')
    return result


def write_reviewed(before, after):
    changed = [name for name in after if before.get(name) != after[name]]
    for name in changed:
        path = ROOT / name
        require(path.read_bytes() == before[name], 'File changed while preparing version update: ' + name)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(after[name])
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def bump(part):
    before = working_files()
    validate(before, manifest=False)
    old = version_from(before, managed=True)
    new = next_version(old, part)
    after = dict(before)
    after[VERSION] = (new + '\n').encode('ascii')
    for name, pattern in VERSION_FIELDS.items():
        match = re.search(pattern, before[name])
        after[name] = before[name][:match.start(1)] + new.encode('ascii') + before[name][match.end(1):]
    after = with_manifest(after)
    validate(after)
    write_reviewed(before, after)
    return {'previousVersion': old, 'version': new, 'tag': 'v' + new, 'published': False}


def allowed():
    # 白名单来自已审计公开基线，不能通过改摘要清单添加任意文件。
    return set(git('ls-tree', '-r', '--name-only', BASE).decode().splitlines()) | EXTRA


def validate(files, manifest=True, extra_paths=()):
    require(set(files) <= allowed() | set(extra_paths), 'Unexpected public paths; review the explicit allowlist')
    required = allowed() - EXTRA - RETIRED - {'SHA256SUMS.json'}
    require(required <= set(files), 'Required distribution file missing')
    if 'skills/ai-toolbox-sync/references/git-workflow.md' in files:
        require(not (RETIRED & set(files)), 'Retired dependency files in independent distribution')
        require('skills/ai-toolbox-sync/scripts/test_native_git.py' in files,
                'Independent Git workflow validation missing')
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
    if VERSION in files:
        version_from(files, managed=True)
    for name, body in files.items():
        require(len(body) <= 2_000_000, 'Oversized public file')
        require(not re.search(rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', body),
                'Credential pattern found; content suppressed')
    if manifest:
        expected = {p: hashlib.sha256(b).hexdigest() for p, b in files.items()
                    if p != 'SHA256SUMS.json'}
        require(json.loads(files['SHA256SUMS.json']) == expected, 'Manifest mismatch')


def tree(rev, extra_paths=()):
    entries = git('ls-tree', '-rz', rev).split(b'\0')
    paths = []
    for entry in filter(None, entries):
        meta, name = entry.split(b'\t', 1)
        require(meta.split()[0] == b'100644', 'Links/submodules/executables forbidden')
        paths.append(name.decode())
    require(set(paths) <= allowed() | set(extra_paths), 'Unexpected committed paths; content not read')
    return {p: git('show', rev + ':' + p) for p in paths}


def check():
    require(git('status', '--porcelain', '--untracked-files=all').strip() == b'', 'Working tree must be clean')
    head = git('rev-parse', 'HEAD').decode().strip()
    require(git('merge-base', BASE, head).decode().strip() == BASE, 'Untrusted release ancestry')
    for rev in git('rev-list', head, '^' + BASE).decode().splitlines():
        validate(tree(rev))
    current = tree(head)
    validate(current)
    version_from(current, managed=True)
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
    result['localVersion'] = committed_version(local)
    result['remoteVersion'] = committed_version(remote[0])
    require(git('rev-parse', 'HEAD').decode().strip() == local, 'Local HEAD changed during comparison')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


def committed_version(revision):
    return version_from({SKILL: git('show', revision + ':' + SKILL)})


def remote_refs():
    result = {}
    for line in git('ls-remote', REMOTE, 'refs/heads/main', 'refs/tags/v*').decode().splitlines():
        oid, ref = line.split()
        require(ref not in result, 'Ambiguous remote reference')
        result[ref] = oid
    return result


def maintenance_state(allow_merge=False):
    branch = git('symbolic-ref', 'HEAD').decode().strip()
    require(branch.startswith('refs/heads/'), 'Detached HEAD; choose a maintenance branch first')
    for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply'):
        if allow_merge and name == 'MERGE_HEAD':
            continue
        path = git('rev-parse', '--path-format=absolute', '--git-path', name).decode().strip()
        require(not Path(path).exists(), 'Unfinished Git operation: ' + name)
    return branch


def local_path(name):
    return Path(git('rev-parse', '--path-format=absolute', '--git-path', name).decode().strip())


def save_local(path, value, expected):
    require(not path.is_symlink() and not path.is_junction(), 'Linked local record forbidden')
    lock = path.with_name(path.name + '.lock')
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    temporary = None
    try:
        require((path.read_bytes() if path.exists() else None) == expected, 'Local record changed; review again')
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        os.close(descriptor)
        lock.unlink()


def load_local(name):
    path = local_path(name)
    require(not path.is_symlink() and not path.is_junction(), 'Linked local record forbidden')
    raw = path.read_bytes() if path.exists() else None
    return path, raw, json.loads(raw) if raw is not None else None


def hashes(files):
    return {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())}


def safe_name(name):
    parts = name.split('/')
    require(bool(parts) and all(p and p.lower() not in {'.', '..', '.git'} and ':' not in p and '\\' not in p for p in parts),
            'Unsafe relative path')
    require(not any(p.lower().startswith('.env') or p.lower() in
                    {'auth.json', 'credentials.json', 'id_rsa', 'id_ed25519'} or
                    p.lower().endswith(('.pem', '.key', '.p12', '.pfx')) for p in parts),
            'Credential/environment path forbidden; content not read')


def installation_snapshot(installed, receipt):
    root, record = Path(installed).absolute(), Path(receipt).absolute()
    for path in (root, record):
        require(not path.is_relative_to(ROOT) and not any(p.is_symlink() or p.is_junction()
                for p in (path, *path.parents)), 'Installation and receipt must be independent, unlinked local paths')
    require(not record.is_relative_to(root), 'Installation receipt must be outside the installed Skill')
    root, record = root.resolve(strict=True), record.resolve(strict=True)
    require(not root.is_relative_to(ROOT.resolve()) and not record.is_relative_to(ROOT.resolve()),
            'Resolved installation and receipt must remain outside the public checkout')
    safe_name(record.name)
    raw = record.read_bytes()
    data = json.loads(raw)
    require(data.get('source', '').removesuffix('.git').rstrip('/') == REMOTE.removesuffix('.git').rstrip('/'),
            'Installation receipt source does not match the public repository')
    expected = data.get('installedFilesSHA256') or data.get('localCustomization', {}).get('filesSHA256')
    require(isinstance(expected, dict) and bool(expected), 'No trusted installed file baseline; review before starting')
    for name, digest in expected.items():
        safe_name(name)
        require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'Invalid installed baseline hash')
    require(root.is_dir(), 'Installed Skill directory missing')
    actual = {}
    def visit(directory):
        for path in sorted(directory.iterdir()):
            require(not path.is_symlink() and not path.is_junction(), 'Linked installation path; content not read')
            name = path.relative_to(root).as_posix()
            safe_name(name)
            if path.is_dir():
                visit(path)
            elif path.is_file():
                actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                require(False, 'Unsupported installation entry; content not read')
    visit(root)
    changed = {name: ('added' if name not in expected else 'deleted' if name not in actual else 'modified')
               for name in sorted(set(actual) | set(expected)) if actual.get(name) != expected.get(name)}
    return {'path': str(root), 'receipt': str(record), 'receiptSHA256': hashlib.sha256(raw).hexdigest(),
            'filesSHA256': actual, 'changes': changed}


def session_record():
    path, raw, value = load_local('ai-toolbox-maintenance.json')
    require(value is not None and value.get('schemaVersion') == 1, 'Missing maintenance baseline; run start first')
    require(value['remote'] == REMOTE and value['branch'] == maintenance_state(), 'Maintenance baseline belongs to another source/branch')
    head = git('rev-parse', 'HEAD').decode().strip()
    require(git('merge-base', value['startHead'], head).decode().strip() == value['startHead'],
            'History no longer contains the start baseline; review and restart')
    if value['installation'] is not None:
        snapshot = value['installation']
        require(installation_snapshot(snapshot['path'], snapshot['receipt']) == snapshot,
                'Installed files or receipt changed since start; compare and explicitly restart')
    return path, raw, value


def update_review(target, approve_paths=None):
    comparison = inspect()
    require(target == comparison['remote'] and comparison['status'] == 'remote-ahead',
            'Review only the current remote descendant of local HEAD')
    revisions = git('rev-list', target, '^' + comparison['local']).decode().splitlines()
    entries = {rev: git('ls-tree', '-rz', rev).split(b'\0') for rev in revisions}
    unknown = set()
    for items in entries.values():
        for item in filter(None, items):
            meta, raw_name = item.split(b'\t', 1)
            require(meta.split()[0] == b'100644', 'Linked update file forbidden')
            name = raw_name.decode('utf-8')
            safe_name(name)
            if name not in allowed():
                unknown.add(name)
    result = {'target': target, 'from': comparison['local'], 'newPaths': sorted(unknown),
              'revisions': revisions, 'approved': False}
    if approve_paths is not None:
        require(set(approve_paths) == unknown, 'Approval must name every new path exactly; no directory/wildcard approval')
        for rev in revisions:
            validate(tree(rev, unknown), extra_paths=unknown)
        require(remote_refs().get('refs/heads/main') == target and
                git('rev-parse', 'HEAD').decode().strip() == comparison['local'], 'Update changed during approval')
        path, raw, _ = load_local('ai-toolbox-upgrade.json')
        result.update(approved=True, remote=REMOTE)
        save_local(path, result, raw)
    return result


def upgrade_paths(local, target):
    _, _, value = load_local('ai-toolbox-upgrade.json')
    if value is not None and value.get('approved') and value.get('remote') == REMOTE and \
            value.get('from') == local and value.get('target') == target:
        for name in value['newPaths']:
            safe_name(name)
        return set(value['newPaths'])
    return set()


def start(align=False, accept_local=False, source_only=False, installed=None, receipt=None,
          accept_installed=False, restart=False, paths=None):
    """Enter maintenance explicitly; only a clean fast-forward may change source files."""
    branch = maintenance_state()
    require(source_only and installed is None and receipt is None or
            not source_only and installed is not None and receipt is not None,
            'Choose --source-only or both --installed and --receipt')
    snapshot = None if source_only else installation_snapshot(installed, receipt)
    require(snapshot is None or not snapshot['changes'] or accept_installed,
            'Installed customizations require comparison and --accept-installed; nothing overwritten')
    record_path, record_raw, previous = load_local('ai-toolbox-maintenance.json')
    result = inspect()
    if previous is not None and not restart:
        require(previous.get('schemaVersion') == 1 and previous.get('remote') == REMOTE and
                previous.get('branch') == branch and previous.get('remoteHead') == result['remote'] and
                previous.get('installation') == snapshot and
                git('merge-base', previous['startHead'], result['local']).decode().strip() == previous['startHead'],
                'Existing baseline changed; review and use --restart (old baseline is retained)')
    dirty = bool(result['staged'] or result['unstaged'] or result['untracked'])
    require(result['status'] != 'diverged', 'Both sides changed; explain and review a merge first')
    approved = upgrade_paths(result['local'], result['remote'])
    if align:
        require(not dirty, 'Local edits exist; preserve and review them before alignment')
        require(result['status'] in {'aligned', 'remote-ahead'},
                'Local commits exist; alignment cannot discard them')
        if result['status'] == 'remote-ahead':
            require(version_key(result['remoteVersion']) >= version_key(result['localVersion']),
                    'Remote ancestry advances but version goes backwards; review required')
            require(git('merge-base', BASE, result['remote']).decode().strip() == BASE,
                    'Untrusted update ancestry')
            for rev in git('rev-list', result['remote'], '^' + result['local']).decode().splitlines():
                validate(tree(rev, approved), extra_paths=approved)
            require(remote_refs().get('refs/heads/main') == result['remote'],
                    'Remote changed before alignment; compare again')
            maintenance_state()
            require(git('rev-parse', 'HEAD').decode().strip() == result['local'],
                    'Local HEAD changed before alignment')
            require(not git('status', '--porcelain', '--untracked-files=all').strip(),
                    'Local files changed before alignment')
            git('-c', 'merge.autoStash=false', '-c', 'submodule.recurse=false',
                'merge', '--ff-only', '--no-overwrite-ignore', '--no-edit', result['remote'])
            require(git('rev-parse', 'HEAD').decode().strip() == result['remote'],
                    'Alignment result unconfirmed')
            result = inspect()
            require(result['status'] == 'aligned' and
                    not (result['staged'] or result['unstaged'] or result['untracked']),
                    'State changed during alignment; inspect before editing')
    require(result['status'] in {'aligned', 'local-ahead'},
            'Remote is ahead; use start --align only for a reviewed clean source update')
    require(not dirty and result['status'] == 'aligned' or accept_local,
            'Existing local changes require review and start --accept-local')
    if previous is not None and not restart:
        # Resume retains the original starting files and commit, rather than blessing later edits as a new baseline.
        value = previous
        require(paths is None or set(paths) == set(previous['scope']), 'Scope changed; review and restart')
    else:
        scope = sorted(set(paths) if paths is not None else allowed() | approved)
        require(set(scope) <= allowed() | approved, 'Maintenance scope contains unreviewed paths')
        value = {'schemaVersion': 1, 'id': uuid.uuid4().hex, 'remote': REMOTE, 'branch': branch,
                 'startHead': result['local'], 'remoteHead': result['remote'], 'status': 'active',
                 'startFilesSHA256': hashes(working_files(approved)),
                 'startIndexTree': git('write-tree').decode().strip(), 'scope': scope,
                 'installation': snapshot, 'extraPaths': sorted(approved)}
        if previous is not None:
            archive = record_path.with_name(record_path.stem + '.' + uuid.uuid4().hex + '.json')
            save_local(archive, previous, None)
        save_local(record_path, value, record_raw)
    source_hashes = {name.removeprefix('skills/ai-toolbox-sync/'): digest
                     for name, digest in hashes(working_files(approved)).items()
                     if name.startswith('skills/ai-toolbox-sync/')}
    return {**result, 'readyToEdit': True, 'installationUpdated': False,
            'localChangesAccepted': accept_local, 'installationVerified': snapshot is not None,
            'installationChanges': snapshot['changes'] if snapshot is not None else None,
            'installationSourceAligned': snapshot['filesSHA256'] == source_hashes if snapshot is not None else None,
            'sessionId': value['id'], 'baselineRecord': str(record_path)}


def staged_snapshot(extra_paths=(), scope=None):
    branch = maintenance_state(allow_merge=True)
    parent = git('rev-parse', 'HEAD').decode().strip()
    staged = set(filter(None, git('diff', '--cached', '--name-only', '-z', parent).decode().split('\0')))
    require(scope is None or staged <= set(scope), 'Staged files outside the approved maintenance scope')
    unstaged = set(filter(None, git('diff', '--name-only', '-z').decode().split('\0')))
    require(not staged & unstaged, 'Staged files differ from working files; review and stage final contents')
    index = git('write-tree').decode().strip()
    files = tree(index, extra_paths)
    validate(files, extra_paths=extra_paths)
    version = version_from(files, managed=True)
    merge = local_path('MERGE_HEAD')
    parents = [parent] + (merge.read_text(encoding='ascii').splitlines() if merge.exists() else [])
    require(git('rev-parse', 'HEAD').decode().strip() == parent and
            git('symbolic-ref', 'HEAD').decode().strip() == branch and
            git('write-tree').decode().strip() == index, 'Index or branch changed while checking')
    return {'branch': branch, 'parents': parents, 'indexTree': index, 'version': version,
            'stagedPaths': sorted(staged), 'readyToCommit': bool(staged or len(parents) > 1)}


def stage_check():
    """Offline checkpoint validation, intentionally independent of release versions or remote state."""
    result = staged_snapshot()
    path, raw, _ = load_local('ai-toolbox-stage.json')
    save_local(path, {**result, 'schemaVersion': 1, 'remote': REMOTE, 'sessionId': None}, raw)
    return {**result, 'checkpointOnly': True, 'remoteStatus': 'not-checked',
            'installationVerified': False, 'committed': False, 'published': False}


def finish():
    """Validate the actual index; remote problems block publication, never local saving."""
    record_path, record_raw, session = session_record()
    result = staged_snapshot(session['extraPaths'], session['scope'])
    require(result['readyToCommit'], 'No staged changes; nothing to commit')
    remote = {'remoteStatus': 'unverified', 'remoteVerified': False, 'publicationReady': False}
    try:
        comparison = inspect()
        current = remote_refs().get('refs/heads/main')
        verified = current == comparison['remote']
        compatible = verified and comparison['status'] in {'aligned', 'local-ahead'}
        remote = {'remoteStatus': comparison['status'] if verified else 'changed-during-check',
                  'remoteVerified': verified, 'remoteHead': current,
                  'remoteChangedSinceStart': current != session['remoteHead'],
                  'remoteCompatible': compatible,
                  'versionIncreaseRequired': version_key(result['version']) <= version_key(comparison['remoteVersion']),
                  'publicationReady': False}
    except (OSError, subprocess.SubprocessError):
        remote['reason'] = 'Remote check failed; local checkpoint remains available, publication requires a fresh check'
    require(staged_snapshot(session['extraPaths'], session['scope']) == result, 'Prepared index changed; review again')
    session_record()
    path, raw, _ = load_local('ai-toolbox-stage.json')
    save_local(path, {**result, 'schemaVersion': 1, 'remote': REMOTE, 'sessionId': session['id']}, raw)
    session.update(status='prepared', preparedTree=result['indexTree'])
    save_local(record_path, session, record_raw)
    prepared_hashes = hashes(tree(result['indexTree'], session['extraPaths']))
    return {**result, **remote, 'sessionId': session['id'], 'reviewRequired': True,
            'changedSinceStart': sorted(name for name in set(session['startFilesSHA256']) |
                                       set(prepared_hashes)
                                       if session['startFilesSHA256'].get(name) !=
                                       prepared_hashes.get(name)),
            'committed': False, 'published': False, 'installationUpdated': False,
            'installationVerified': session['installation'] is not None}


def verify_commit():
    path, raw, prepared = load_local('ai-toolbox-stage.json')
    require(prepared is not None and prepared.get('schemaVersion') == 1 and prepared.get('remote') == REMOTE,
            'Missing prepared index; run finish or stage-check before the authorized commit')
    require(maintenance_state() == prepared['branch'], 'Branch differs from prepared commit')
    session = None
    if prepared['sessionId'] is not None:
        _, _, session = session_record()
        require(session['id'] == prepared['sessionId'], 'Maintenance session changed since preparation')
    head = git('rev-parse', 'HEAD').decode().strip()
    require(git('show', '-s', '--format=%P', head).decode().split() == prepared['parents'] and
            git('rev-parse', head + '^{tree}').decode().strip() == prepared['indexTree'],
            'Actual commit differs from reviewed tree or parents; retain for review, do not publish')
    validate(tree(head, session['extraPaths'] if session else ()), extra_paths=session['extraPaths'] if session else ())
    prepared.update(verifiedCommit=head)
    save_local(path, prepared, raw)
    return {'commit': head, 'tree': prepared['indexTree'], 'commitVerified': True, 'published': False}


def publish():
    comparison = inspect()
    head = check()
    _, _, prepared = load_local('ai-toolbox-stage.json')
    require(prepared is None or prepared.get('verifiedCommit') == head,
            'Prepared commit is not verified at HEAD; run verify-commit before publishing')
    require(comparison['local'] == head, 'Local HEAD changed; compare again')
    require(comparison['status'] in {'aligned', 'local-ahead'}, 'Remote changes require explanation and user choice before merge')
    require(git('symbolic-ref', '--short', 'HEAD').decode().strip() == 'main', 'Publish only main')
    refs = remote_refs()
    previous = refs.get('refs/heads/main')
    require(previous == comparison['remote'], 'Remote changed; compare again')
    require(git('merge-base', previous, head).decode().strip() == previous, 'Remote changed or diverged; compare first')
    version = committed_version(head)
    if head != previous:
        require(version_key(version) > version_key(committed_version(previous)),
                'Changed release must increase the published version; run release.py bump')
    tag = 'refs/tags/v' + version
    existing = refs.get(tag)
    require(existing is None or existing == head, 'Version tag already exists at another object; never overwrite it')
    for ref in refs:
        if ref.startswith('refs/tags/v') and not ref.endswith('^{}'):
            candidate = ref.removeprefix('refs/tags/v')
            try:
                candidate_key = version_key(candidate)
            except ValueError:
                continue
            require(candidate_key <= version_key(version), 'A newer version tag already exists; choose a higher version')
            require(candidate_key != version_key(version) or ref == tag,
                    'An equivalent SemVer version is already published under another tag')
    local = git('for-each-ref', '--format=%(refname) %(objectname) %(objecttype)', tag).decode().splitlines()
    local = [line.split() for line in local if line.split()[0] == tag]
    require(not local or local == [[tag, head, 'commit']], 'Local version tag conflicts; retain it for review')
    require(git('rev-parse', 'HEAD').decode().strip() == head, 'Local HEAD changed before publication')
    require(not git('status', '--porcelain', '--untracked-files=all').strip(), 'Working tree changed before publication')
    if not local:
        git('-c', 'tag.gpgSign=false', 'tag', tag.removeprefix('refs/tags/'), head)
    if previous != head or existing != head:
        # Pin both objects. The server updates branch and version tag together, or neither.
        git('-c', 'push.followTags=false', '-c', 'remote.origin.mirror=false', 'push', '--atomic',
            REMOTE, head + ':refs/heads/main', head + ':' + tag)
    verified = remote_refs()
    require(verified.get('refs/heads/main') == head and verified.get(tag) == head,
            'Publication result unconfirmed; inspect remote branch and tag before retrying')
    return {'version': version, 'commit': head, 'tag': tag.removeprefix('refs/tags/'),
            'remoteVerified': True, 'alreadyPublished': previous == head and existing == head}


def main():
    args = sys.argv[1:]
    mode = args[0] if args else ''
    require((mode in {'inspect', 'manifest', 'check', 'push', 'version', 'finish', 'stage-check', 'verify-commit'} and len(args) == 1)
            or mode == 'start' or (mode == 'review-update' and len(args) == 2)
            or (mode == 'approve-update' and len(args) >= 2)
            or (mode == 'bump' and len(args) == 2),
            'Usage: python -B release.py inspect|start --help|finish|stage-check|verify-commit|review-update SHA|approve-update SHA [EXACT_PATH ...]|version|bump <patch|minor|major|prerelease|final>|manifest|check|push')
    if mode == 'inspect':
        inspect()
    elif mode == 'start':
        parser = argparse.ArgumentParser(description='Start or resume manager maintenance; installation is a separate, explicit check')
        for flag in ('align', 'accept-local', 'accept-installed', 'source-only', 'restart'):
            parser.add_argument('--' + flag, action='store_true')
        parser.add_argument('--installed')
        parser.add_argument('--receipt')
        parser.add_argument('--paths', nargs='+')
        print(json.dumps(start(**vars(parser.parse_args(args[1:]))), ensure_ascii=False, indent=2))
    elif mode == 'finish':
        print(json.dumps(finish(), ensure_ascii=False, indent=2))
    elif mode == 'stage-check':
        print(json.dumps(stage_check(), ensure_ascii=False, indent=2))
    elif mode == 'verify-commit':
        print(json.dumps(verify_commit(), ensure_ascii=False, indent=2))
    elif mode in {'review-update', 'approve-update'}:
        print(json.dumps(update_review(args[1], args[2:] if mode == 'approve-update' else None),
                         ensure_ascii=False, indent=2))
    elif mode == 'version':
        files = working_files()
        validate(files)
        value = version_from(files, managed=True)
        print(json.dumps({'version': value, 'tag': 'v' + value,
                          'head': git('rev-parse', 'HEAD').decode().strip(),
                          'headVersion': committed_version('HEAD'),
                          'dirty': bool(git('status', '--porcelain', '--untracked-files=all').strip())}))
    elif mode == 'bump':
        print(json.dumps(bump(args[1])))
    elif mode == 'manifest':
        files = working_files()
        validate(files, manifest=False)
        write_reviewed(files, with_manifest(files))
    elif mode == 'push':
        print(json.dumps(publish()))
    else:
        head = check()
        print('PASS', mode, head)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print('BLOCKED:', str(exc), file=sys.stderr)
        sys.exit(1)
