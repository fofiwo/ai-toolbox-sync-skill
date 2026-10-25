"""Bounded local discovery. Never installs, collects, syncs or executes discovered content."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

SKIP = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'backups'}
LIMIT = 2_000_000


def uid(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]


def clean(value, limit=300):
    if not isinstance(value, str):
        return ''
    if re.search(r'(?i)(bearer\s|(?:token|password|secret|api[_-]?key)\s*[:=]|sk-[\w-]{12})', value):
        return '[敏感字段已隐藏]'
    return ''.join(c for c in value if c.isprintable())[:limit]


def repo_url(value):
    if not isinstance(value, str) or re.search(r'[\s\\]', value):
        return None
    try:
        u = urlsplit(value)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment:
            return None
        path = u.path.rstrip('/')
        if path.endswith('.git'):
            path = path[:-4]
        if not path or '/tree/' in path or '/blob/' in path:
            return None
        # GitHub repository identity is case insensitive; other hosts may not be.
        if u.hostname.lower() == 'github.com':
            if len(path.strip('/').split('/')) != 2:
                return None
            path = path.lower()
        return urlunsplit(('https', u.netloc.lower(), path, '', ''))
    except ValueError:
        return None


def linked(p):
    return p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())


def read_json(p):
    if linked(p) or p.stat().st_size > LIMIT:
        raise ValueError('linked or oversized metadata')
    data = json.loads(p.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('metadata must be an object')
    return data


def walk(root, warnings, strict=False):
    """Do not follow nested links; a supplied root is the explicit scan boundary."""
    root = Path(root)
    if not root.is_dir():
        if strict:
            raise OSError('Discovery scope is unavailable')
        warnings.append('范围不存在：' + clean(str(root)))
        return
    if linked(root):
        if strict:
            raise ValueError('Discovery root must not be a link')
        warnings.append('跳过链接根目录，请核实后显式指定真实目标：' + clean(str(root)))
        return
    visited = 0
    def onerror(error):
        if strict:
            raise error
        warnings.append('无法遍历目录，结果不完整：' + clean(str(error.filename)))

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        visited += 1
        if visited > 20000:
            if strict:
                raise ValueError('Discovery directory limit exceeded')
            warnings.append('扫描达到目录上限，结果不完整：' + clean(str(root)))
            return
        base = Path(directory)
        retained = []
        for name in sorted(dirs):
            p = base / name
            if name in SKIP or name.lower().startswith('.env'):
                continue
            if linked(p):
                warnings.append('跳过目录链接：' + clean(str(p)))
            else:
                retained.append(name)
        dirs[:] = retained
        yield base, set(files)


def skill_name(path):
    if linked(path) or path.stat().st_size > LIMIT:
        raise ValueError('linked or oversized skill')
    # Only the frontmatter name is a label; markdown instructions are never executed.
    with path.open(encoding='utf-8-sig') as stream:
        text = stream.read(8192)
    match = re.search(r'\A---\s*\n(.*?)\n---', text, re.S)
    if match:
        name = re.search(r'^name:\s*(.+)$', match[1], re.M)
        if name:
            return clean(name[1].strip().strip('\"\''))
    return clean(path.parent.name)


class Inventory:
    def __init__(self, strict=False):
        self.strict = strict
        self.groups = {}
        self.warnings = []
        self.seen = set()
        self.scopes = []

    def add(self, name, kind, path, *, source=None, component=None, evidence='', status='files-present', package=None):
        actual = str(Path(path).resolve())
        occurrence = (kind, os.path.normcase(actual), component if kind == 'mcp' else '')
        if occurrence in self.seen:
            return
        self.seen.add(occurrence)
        project = source or 'local:' + str(Path(package or path).resolve()) + ('|' + str(component) if kind == 'mcp' else '')
        gid = 'project:' + uid(project)
        group = self.groups.setdefault(gid, dict(id=gid, name=clean(source.rsplit('/', 1)[-1] if source else name),
                    source=source, identityStatus='metadata-backed' if source else 'unknown', components={}, evidence=[]))
        cid = 'component:' + uid(project + '|' + kind + '|' + (component or actual))
        row = group['components'].setdefault(cid, dict(id=cid, name=clean(name), kind=kind, componentKey=clean(component or '', 700), installations=[]))
        row['installations'].append(dict(path=clean(actual, 1500), status=status))
        if evidence and evidence not in group['evidence']:
            group['evidence'].append(clean(evidence, 1500))

    def skills(self, root):
        root = Path(root)
        self.scopes.append(dict(kind='skill-root', path=str(root)))
        lock = root.parent / '.skill-lock.json'
        entries = {}
        if root.name == 'skills' and lock.is_file():
            try:
                entries = read_json(lock).get('skills', {})
                if not isinstance(entries, dict):
                    raise ValueError('invalid skill lock')
            except (ValueError, OSError):
                if self.strict:
                    raise
                self.warnings.append('安装来源索引无效，按未知来源处理：' + clean(str(lock)))
                entries = {}
        for folder, files in walk(root, self.warnings, self.strict):
            if 'SKILL.md' not in files:
                continue
            path = folder / 'SKILL.md'
            try:
                rel = folder.relative_to(root)
                # Lock keys only bind direct children; a nested same-name skill is not evidence.
                entry = entries.get(rel.name, {}) if len(rel.parts) == 1 else {}
                if not isinstance(entry, dict):
                    entry = {}
                source = repo_url(entry.get('sourceUrl'))
                component = entry.get('skillPath')
                if not isinstance(component, str) or not component or '..' in Path(component).parts or Path(component).is_absolute():
                    source, component = None, None
                elif component.endswith('/SKILL.md'):
                    component = component[:-len('/SKILL.md')]
                self.add(skill_name(path), 'skill', folder, source=source, component=component,
                         evidence=str(lock) if source else '缺少可核实安装来源；不凭名称或内容相同合并')
            except (ValueError, OSError):
                if self.strict:
                    raise
                self.warnings.append('无法读取 Skill 元数据：' + clean(str(path)))

    def plugins(self, root):
        root = Path(root)
        self.scopes.append(dict(kind='plugin-root', path=str(root)))
        # Codex cache layout: marketplace / package / version. Manifest is required.
        for folder, files in walk(root, self.warnings):
            if folder.name not in ('.codex-plugin', '.claude-plugin') or 'plugin.json' not in files:
                continue
            package = folder.parent
            if folder.name == '.claude-plugin' and (package / '.codex-plugin' / 'plugin.json').is_file():
                continue
            try:
                manifest = read_json(folder / 'plugin.json')
                receipt = package / '.codex-marketplace-install.json'
                meta = read_json(receipt) if receipt.is_file() else {}
                receipt_source = repo_url(meta.get('source'))
                manifest_source = repo_url(manifest.get('repository'))
                source = receipt_source or manifest_source
                if receipt_source and manifest_source and receipt_source != manifest_source:
                    source = None
                    self.warnings.append('安装记录与插件清单来源冲突，保留未知归属：' + clean(str(package)))
                name = clean(manifest.get('name')) or clean(package.name)
                # Distinct plugin packages from the same repository stay distinct components.
                key = 'plugin/' + name
                status = 'receipt-present' if receipt.is_file() else 'cache-only'
                self.add(name, 'plugin', package, source=source, component=key, package=package,
                         evidence=str(receipt if receipt.is_file() else folder / 'plugin.json'), status=status)
                skills = manifest.get('skills', './skills')
                skill_dirs = [skills] if isinstance(skills, str) else skills if isinstance(skills, list) else []
                for entry in skill_dirs:
                    if not isinstance(entry, str):
                        continue
                    target = package / entry
                    if not target.resolve().is_relative_to(package.resolve()):
                        self.warnings.append('插件 skills 路径越界，已跳过：' + clean(name))
                        continue
                    if not target.is_dir():
                        continue
                    for sf, names in walk(target, self.warnings):
                        if 'SKILL.md' in names:
                            self.add(skill_name(sf / 'SKILL.md'), 'skill', sf, source=source,
                                     component=key + '/' + sf.relative_to(package).as_posix(), package=package,
                                     evidence='插件清单声明的 skills 范围', status=status)
            except (OSError, ValueError):
                self.warnings.append('插件元数据无效：' + clean(str(folder)))

    def mcp(self, config):
        """Project a TOML file to MCP section headers and enabled flags only.

        Never parse, retain or export commands, args, env, URLs or credential values.
        Multiline TOML strings are skipped so embedded fake headers cannot become servers.
        """
        config = Path(config)
        self.scopes.append(dict(kind='codex-mcp-config', path=str(config)))
        if config.name.lower().startswith('.env') or config.suffix.lower() != '.toml':
            self.warnings.append('仅接受显式 Codex TOML 配置，未读取：' + clean(str(config)))
            return
        if not config.is_file() or linked(config) or config.stat().st_size > LIMIT:
            self.warnings.append('MCP 配置缺失、过大或为链接：' + clean(str(config)))
            return
        import tomllib
        projected = []
        multiline = None
        active = False
        with config.open(encoding='utf-8-sig') as stream:
            for line in stream:
                if multiline:
                    if multiline in line.split('#', 1)[0]:
                        multiline = None
                    continue
                # This conservative parser ignores potentially ambiguous multiline content.
                if '"""' in line or "'''" in line:
                    delimiter = '"""' if '"""' in line else "'''"
                    if line.count(delimiter) % 2:
                        multiline = delimiter
                    active = False
                    continue
                text = line.strip()
                if text.startswith('['):
                    active = bool(re.fullmatch(r'\[mcp_servers\.(?:[A-Za-z0-9_-]+|"[^"\\\r\n]+"|\'[^\'\r\n]+\')\]\s*(?:#.*)?', text))
                    if active:
                        projected.append(text)
                elif active and re.fullmatch(r'enabled\s*=\s*(true|false)\s*(?:#.*)?', text):
                    projected.append(text)
        try:
            servers = tomllib.loads('\n'.join(projected)).get('mcp_servers', {})
        except ValueError:
            self.warnings.append('MCP 安全投影有歧义，未生成 MCP 条目：' + clean(str(config)))
            return
        for name, options in servers.items():
            self.add(name, 'mcp', config, component=name,
                     evidence='仅 MCP 配置名称/启用标志；来源与调用能力未验证',
                     status='disabled' if options.get('enabled') is False else 'configured-unverified')

    def result(self):
        groups = []
        for group in self.groups.values():
            row = dict(group)
            row['components'] = sorted(group['components'].values(), key=lambda c: (c['kind'], c['name'], c['id']))
            groups.append(row)
        groups.sort(key=lambda g: (g['identityStatus'] == 'unknown', g['name'], g['id']))
        return dict(schemaVersion=1, snapshotType='discovery-not-collection', generatedAt=datetime.now(timezone.utc).isoformat(),
                    scopes=self.scopes, warnings=self.warnings, groups=groups)


def write_new(path, text):
    # A new dated output directory avoids clobbering an earlier selection or snapshot.
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


def build(snapshot, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    template = Path(__file__).parent.parent / 'catalog' / 'inventory.html'
    model = Path(__file__).parent.parent / 'catalog' / 'inventory-model.js'
    payload = json.dumps(snapshot, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    html = template.read_text(encoding='utf-8').replace('/* INVENTORY_MODEL */', model.read_text(encoding='utf-8'))
    html = html.replace('/* INVENTORY_APP */', (template.parent / 'inventory-app.js').read_text(encoding='utf-8'))
    html = html.replace('/* INVENTORY_BASE_STYLE */', (template.parent / 'style.css').read_text(encoding='utf-8'))
    html = html.replace('__CATALOG_URI__', (template.parent / 'index.html').resolve().as_uri())
    html = html.replace('/* INVENTORY_DATA */', payload)
    write_new(output / 'inventory.json', json.dumps(snapshot, ensure_ascii=False, indent=2))
    write_new(output / 'index.html', html)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--skill-root', action='append', default=[])
    p.add_argument('--plugin-root', action='append', default=[])
    p.add_argument('--codex-mcp-config', action='append', default=[])
    p.add_argument('--output', required=True, help='New local output directory; never a shared catalog')
    a = p.parse_args()
    if not (a.skill_root or a.plugin_root or a.codex_mcp_config):
        p.error('Specify at least one explicit discovery scope')
    inv = Inventory()
    for root in a.plugin_root:
        inv.plugins(root)
    for root in a.skill_root:
        inv.skills(root)
    for config in a.codex_mcp_config:
        inv.mcp(config)
    snapshot = inv.result()
    build(snapshot, a.output)
    print(json.dumps({'output': str(Path(a.output).resolve() / 'index.html'), 'groups': len(snapshot['groups']), 'warnings': len(snapshot['warnings'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
