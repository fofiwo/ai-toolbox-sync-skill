"""Adversarial discovery tests; fixtures never touch real host state."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import inventory as m


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        return target

    def test_strict_scan_does_not_turn_access_failure_into_empty_success(self):
        self.put('skills/demo/SKILL.md', '---\nname: demo\n---')
        def denied(*args, **kwargs):
            kwargs['onerror'](PermissionError('fixture denied'))
            return iter(())
        with patch.object(m.os, 'walk', side_effect=denied), self.assertRaises(PermissionError):
            m.Inventory(strict=True).skills(self.root / 'skills')
        with self.assertRaises(OSError):
            m.Inventory(strict=True).skills(self.root / 'missing')

    def test_project_components_and_repeated_scan(self):
        self.put('host/.skill-lock.json', json.dumps({'skills': {
            'a': {'sourceUrl': 'https://github.com/Team/Bundle.git', 'skillPath':'skills/a/SKILL.md'},
            'b': {'sourceUrl': 'https://github.com/team/bundle', 'skillPath':'skills/b/SKILL.md'}}}))
        for n in ('a','b'):
            self.put('host/skills/'+n+'/SKILL.md','---\nname: '+n+'\n---')
        inv=m.Inventory(); inv.skills(self.root/'host/skills'); inv.skills(self.root/'host/skills')
        g=inv.result()['groups']; self.assertEqual(len(g),1); self.assertEqual(len(g[0]['components']),2)
        self.assertTrue(all(len(c['installations'])==1 for c in g[0]['components']))

    def test_same_name_unknown_and_nested_lock_do_not_merge(self):
        self.put('host/.skill-lock.json',json.dumps({'skills':{'a':{'sourceUrl':'https://github.com/x/y','skillPath':'skills/a/SKILL.md'}}}))
        for p in ('host/skills/a','host/skills/nested/a','other/skills/a'):
            self.put(p+'/SKILL.md','---\nname: same\n---')
        inv=m.Inventory();inv.skills(self.root/'host/skills');inv.skills(self.root/'other/skills')
        g=inv.result()['groups'];self.assertEqual(len(g),3)
        self.assertEqual(sum(x['identityStatus']=='unknown' for x in g),2)

    def test_plugin_versions_containment_and_dual_manifest(self):
        for version in ('1','2'):
            base='cache/vendor/pkg/'+version
            manifest=json.dumps({'name':'pkg','repository':'https://github.com/x/y','skills':['./skills','../../../../escape']})
            self.put(base+'/.codex-plugin/plugin.json',manifest)
            self.put(base+'/.claude-plugin/plugin.json',manifest)
            self.put(base+'/skills/a/SKILL.md','---\nname: a\n---')
        self.put('escape/e/SKILL.md','---\nname: escape\n---')
        inv=m.Inventory(); inv.plugins(self.root/'cache')
        groups=inv.result()['groups'];self.assertEqual(len(groups),1)
        self.assertEqual(len(groups[0]['components']),2)
        self.assertTrue(all(len(c['installations'])==2 for c in groups[0]['components']))
        self.assertTrue(all(i['status']=='cache-only' for c in groups[0]['components'] for i in c['installations']))
        self.assertEqual(len(inv.warnings),2)

    def test_mcp_projects_only_names_enabled_no_credentials(self):
        config=self.put('config.toml', '[mcp_servers.browser]\nenabled = false\ncommand="do not execute"\n[mcp_servers.browser.env]\nTOKEN="never-export-this"\n[mcp_servers.other]\nurl="https://user:secret@example.org/?key=secret"\n')
        inv=m.Inventory();inv.mcp(config);out=inv.result();raw=json.dumps(out)
        self.assertNotIn('never-export-this',raw);self.assertNotIn('user:secret',raw)
        self.assertEqual(len(out['groups']),2)
        states={i['status'] for g in out['groups'] for c in g['components'] for i in c['installations']}
        self.assertEqual(states,{'disabled','configured-unverified'})

    def test_multiline_fake_mcp_not_discovered(self):
        config=self.put('config.toml','description = """\n[mcp_servers.fake]\n"""\n[mcp_servers.real]\n')
        inv=m.Inventory();inv.mcp(config)
        names=[c['name'] for g in inv.result()['groups'] for c in g['components']]
        self.assertEqual(names,['real'])

    def test_bad_url_and_invalid_metadata(self):
        for value in ['https://u:p@github.com/x/y','https://github.com/x/y?token=a','javascript:alert(1)','https://github.com/x/y/tree/main','https://github.com/x/y#token']:
            self.assertIsNone(m.repo_url(value))
        self.put('host/.skill-lock.json','not-json');self.put('host/skills/a/SKILL.md','---\nname: a\n---')
        inv=m.Inventory();inv.skills(self.root/'host/skills')
        self.assertEqual(inv.result()['groups'][0]['identityStatus'],'unknown');self.assertTrue(inv.warnings)

    def test_html_injection_and_no_overwrite(self):
        inv=m.Inventory();inv.add('</script><script>alert(1)</script>','skill',self.root/'x')
        out=self.root/'out';m.build(inv.result(),out)
        html=(out/'index.html').read_text(encoding='utf-8')
        self.assertNotIn('</script><script>alert(1)',html)
        self.assertIn('\\u003c/script',html)
        with self.assertRaises(FileExistsError):m.build(inv.result(),out)

    def test_plugin_namespace_avoids_false_component_merge(self):
        for name in ('one','two'):
            base='cache/vendor/'+name+'/1'
            self.put(base+'/.codex-plugin/plugin.json',json.dumps({'name':name,'repository':'https://github.com/team/mono'}))
            self.put(base+'/skills/shared/SKILL.md','---\nname: shared\n---')
        inv=m.Inventory();inv.plugins(self.root/'cache')
        groups=inv.result()['groups']
        self.assertEqual(len(groups),1)
        self.assertEqual(len(groups[0]['components']),4)

    def test_mcp_paths_are_real_and_same_name_different_config_is_separate(self):
        one=self.put('one/config.toml','[mcp_servers.same]\n')
        two=self.put('two/config.toml','[mcp_servers.same]\n')
        inv=m.Inventory();inv.mcp(one);inv.mcp(two);inv.mcp(one)
        groups=inv.result()['groups'];self.assertEqual(len(groups),2)
        for group in groups:
            self.assertEqual(group['name'],'same')
            self.assertTrue(Path(group['components'][0]['installations'][0]['path']).is_file())

    def test_conflicting_plugin_sources_are_not_guessed(self):
        base='cache/vendor/pkg/1'
        self.put(base+'/.codex-plugin/plugin.json',json.dumps({'name':'pkg','repository':'https://github.com/a/b'}))
        self.put(base+'/.codex-marketplace-install.json',json.dumps({'source':'https://github.com/c/d'}))
        inv=m.Inventory();inv.plugins(self.root/'cache')
        self.assertEqual(inv.result()['groups'][0]['identityStatus'],'unknown')
        self.assertTrue(inv.warnings)

    def test_env_not_read_as_mcp(self):
        env=self.put('.env.toml','[mcp_servers.must_not_read]\n')
        inv=m.Inventory();inv.mcp(env)
        self.assertFalse(inv.result()['groups']);self.assertTrue(inv.warnings)

    def test_symlink_not_followed(self):
        self.put('outside/a/SKILL.md','---\nname: external\n---')
        scan=self.root/'scan';scan.mkdir()
        try:(scan/'link').symlink_to(self.root/'outside',target_is_directory=True)
        except OSError:self.skipTest('symlink privilege unavailable')
        inv=m.Inventory();inv.skills(scan)
        self.assertFalse(inv.result()['groups']);self.assertTrue(inv.warnings)


if __name__=='__main__':unittest.main(verbosity=2)
