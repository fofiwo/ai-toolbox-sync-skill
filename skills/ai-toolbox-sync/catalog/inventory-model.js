/* Pure functions shared by the offline page and adversarial tests. */
const InventoryModel = (() => {
  function stats(groups) {
    return {projects: groups.filter(g => g.identityStatus !== 'unknown').length,
      unknown: groups.filter(g => g.identityStatus === 'unknown').length,
      components: groups.reduce((n,g) => n + g.components.length, 0),
      occurrences: groups.reduce((n,g) => n + g.components.reduce((m,c) => m + c.installations.length, 0), 0)};
  }
  function selected(groups, ids) {
    return groups.map(g => ({...g, components:g.components.filter(c => ids.has(c.id))}))
      .filter(g => g.components.length);
  }
  function prompt(snapshot, ids) {
    const groups = selected(snapshot.groups, ids);
    if (!groups.length) return '';
    const quote = value => JSON.stringify(String(value || ''));
    const lines = groups.map(g => {
      const original = snapshot.groups.find(x => x.id === g.id);
      const partial = original.components.length !== g.components.length;
      const names = g.components.map(c => c.kind + ' ' + quote(c.name) +
        (g.components.filter(x => x.kind === c.kind && x.name === c.name).length > 1 ? '（' + quote(c.componentKey || c.id) + '）' : '')).join('、');
      const result = ['- ' + quote(g.name),
        g.source ? '  来源：' + quote(g.source) : '  来源：待核实',
        '  ' + (partial ? '仅收集这些组件：' : '本次所选组件：') + names];
      if (!g.source) {
        for (const c of g.components) {
          const paths = [...new Set(c.installations.map(i => i.path))];
          result.push('  ' + quote(c.name) + ' 的本机位置：' + paths.map(quote).join('、'));
        }
      }
      return result.join('\n');
    });
    return '请使用 $ai-toolbox-sync，按既定流程收集以下所选资源：\n\n' +
      lines.join('\n\n') + '\n\n已收藏且无变化的跳过；来源或归属不明的先核实。';
  }
  return {stats,selected,prompt};
})();
if (typeof module !== 'undefined') module.exports = InventoryModel;
