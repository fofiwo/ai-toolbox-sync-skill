"use strict";
const ToolboxModel = (() => {
  const kinds = {all:"全部",skill:"Skills",mcp:"MCP",plugin:"插件","agent-document":"Agent 文档"};
  const states = {managed:"已收藏",approved:"已同意",pending:"待决定",declined:"不加入",deferred:"稍后处理",unknown:"未知"};
  function safeUrl(value) {
    if (typeof value !== "string" || /[\\\s]/.test(value)) return null;
    try { const u = new URL(value); return ["http:","https:"].includes(u.protocol) && !u.username && !u.password && !u.search && !u.hash ? u.href : null; } catch { return null; }
  }
  function filter(rows, kind, query, state, category = "all") {
    const q = query.trim().toLocaleLowerCase();
    return rows.filter(r => (kind === "all" || r.kind === kind) && (state === "all" || (r.management || "unknown") === state) && (category === "all" || categories(r).includes(category)) && [r.name,r.description,r.summary,r.version,...categories(r)].some(v => typeof v === "string" && v.toLocaleLowerCase().includes(q)));
  }
  function categories(row) {
    return Array.isArray(row.categories) && row.categories.length ? row.categories : ["未分类"];
  }
  function categoryCounts(rows, kind) {
    const counts = new Map();
    rows.filter(r => kind === "all" || r.kind === kind).forEach(r => categories(r).forEach(c => counts.set(c,(counts.get(c)||0)+1)));
    return Array.from(counts.entries());
  }
  const statusLabels = {
    decision:{pending:"未决定",approved:"加入",declined:"不加入",deferred:"稍后",unknown:"未知"},
    collection:{"not-collected":"未收藏",collected:"已收藏",failed:"收藏失败",unknown:"未知"},
    installation:{"source-only":"仅源码",configured:"仅配置",installed:"已安装",failed:"安装失败",uninstalled:"本机已卸载",unknown:"未知"},
    sync:{"not-requested":"未请求同步",pending:"待同步",synced:"已同步",failed:"同步失败",unknown:"未知"},
    catalog:{pending:"待刷新",current:"已刷新",failed:"刷新失败",unknown:"未知"}
  };
  function stateText(row, axis) {
    let value = row.state?.[axis];
    if (!value && axis === "decision") value = row.management === "managed" ? "approved" : row.management;
    if (!value && axis === "collection" && row.management === "managed") value = "collected";
    return statusLabels[axis]?.[value] || "未知";
  }
  function supportsAction(row, action) {
    if (row.kind === "agent-document") return action === "install" || (action === "sync" && ["self", "derived"].includes(row.ownership));
    return action === "install" || (action === "sync" ? row.ownership === "self" :
      ["check", "update"].includes(action) && row.ownership === "third-party");
  }
  function operationPrompt(rows, action, demo) {
    if (!rows.length) return "";
    if (!["install", "sync", "check", "update"].includes(action)) throw new Error("未知操作");
    if (rows.some(r => !supportsAction(r, action))) return "";
    const label = {install:"安装",sync:"同步",check:"检查更新",update:"检查并更新"}[action];
    const lines = rows.map(r => {
      if (r.kind === "agent-document") {
        if (action === "install") return "请使用 $ai-toolbox-sync 导入这份整份 Agent 文档：" + JSON.stringify(r.id) + "。来源：" + (safeUrl(r.projectUrl) || "从权威清单核实") + "；提交：" + JSON.stringify(/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(r.resolvedCommit) ? r.resolvedCommit : "需先解析并固定提交") + "。先核实来源并与我确认目标宿主、文档路径及覆盖/重新整理/追加末尾/插入位置，再登记独立派生版本；仅绑定我自己的全文，不回写来源或其他文档。";
        return "请使用 $ai-toolbox-sync 同步我本机已绑定的整份 Agent 文档：" + JSON.stringify(r.id) + "。先核对安装实例与精确路径；没有自己的绑定则停止，不把来源文档当成本机版本，不修改其他文档。";
      }
      const target = safeUrl(r.projectUrl) || JSON.stringify(r.name || "未知") + "（ID：" + JSON.stringify(r.id) + "）";
      const version = r.resolvedCommit && r.resolvedCommit !== "unknown" ? r.resolvedCommit : r.version;
      return label + "这个 " + (kinds[r.kind] || r.kind) + "：" + target +
        (action === "install" && r.ownership === "third-party" ? "（最新版）" :
          action === "check" ? "（核对最新版与本机实际版本）" : action === "update" ? "（核对实际版本，有更新则更新至最新稳定版）" : version && version !== "unknown" ? "，版本：" + JSON.stringify(version) : "");
    });
    return (demo ? "【仅演示，不可执行】\n" : "") + lines.join("\n");
  }
  return {kinds,states,safeUrl,filter,categories,categoryCounts,stateText,supportsAction,operationPrompt};
})();
if (typeof module !== "undefined") module.exports = ToolboxModel;
