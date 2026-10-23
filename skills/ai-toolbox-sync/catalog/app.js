"use strict";
const M = ToolboxModel, $ = id => document.getElementById(id);
let demo = false, kind = "all", category = "all", selected = null;
const checked = new Set();
const text = (tag, value, className) => { const e = document.createElement(tag); e.textContent = typeof value === "string" && value !== "unknown" ? value : "未知"; if(className) e.className = className; return e; };
const tabs = Object.keys(M.kinds).map(key => {
  const b = text("button",M.kinds[key]); b.type="button"; b.id="tab-"+key; b.setAttribute("role","tab"); b.setAttribute("aria-controls","panel");
  b.onclick=()=>{kind=key;category="all";selected=null;render();};
  b.onkeydown=e=>{const i=tabs.indexOf(b);let n; if(e.key==="ArrowRight") n=(i+1)%tabs.length; if(e.key==="ArrowLeft") n=(i+tabs.length-1)%tabs.length; if(e.key==="Home") n=0; if(e.key==="End") n=tabs.length-1; if(n!==undefined){e.preventDefault();tabs[n].click();tabs[n].focus();}};
  $("tabs").append(b);return b;
});
function render() {
  const data = demo ? window.TOOLBOX_DEMO : window.TOOLBOX_DATA;
  const rows = data.resources;
  $("mode").textContent = demo ? "示例模式 · 以下 "+rows.length+" 项仅演示，不代表真实安装" : "我的目录 · 已导出的资源快照";
  $("demo").textContent = demo ? "返回我的目录" : "查看示例目录";
  tabs.forEach((b,i)=>{const key=Object.keys(M.kinds)[i];b.textContent=M.kinds[key]+" "+rows.filter(r=>key==="all"||r.kind===key).length;b.setAttribute("aria-selected",String(key===kind));b.tabIndex=key===kind?0:-1;});
  $("panel").setAttribute("aria-labelledby","tab-"+kind);
  $("categories").replaceChildren();
  const scopedCount = rows.filter(r => kind === "all" || r.kind === kind).length;
  [["all",scopedCount],...M.categoryCounts(rows,kind)].forEach(([name,count])=>{
    const b=text("button",(name==="all"?"全部能力":name)+" "+count);
    b.type="button";b.setAttribute("aria-pressed",String(category===name));
    b.onclick=()=>{category=name;selected=null;render();Array.from($("categories").children).find(el=>el.textContent===b.textContent)?.focus();};
    $("categories").append(b);
  });
  const visible=M.filter(rows,kind,$("search").value,$("status").value,category);
  renderOperations(rows, visible);
  if(!visible.includes(selected)) selected=visible[0]||null;
  $("count").textContent="显示 "+visible.length+" / "+rows.length+" 项";
  $("list").replaceChildren();$("detail").replaceChildren();
  if(!visible.length){const box=text("div","","empty");box.append(text("h2",rows.length?"没有匹配的资源":"目录还是空的"),text("p",rows.length?"试试其他关键词、分类或状态。":"选定资源并更新清单后，重新生成目录即可在这里查阅。"));$("list").append(box);$("detail").append(text("p","这里会显示资源来源、版本和验证信息。"));return;}
  visible.forEach(r=>{const row=document.createElement("div");row.className="resource-row";const check=document.createElement("input");check.type="checkbox";check.checked=checked.has(r.id);check.setAttribute("aria-label","选择 "+r.name);check.onchange=()=>{if(check.checked) checked.add(r.id);else checked.delete(r.id);renderOperations(rows,visible);};const b=text("button","","resource");b.type="button";b.setAttribute("aria-pressed",String(r===selected));b.append(text("small",M.kinds[r.kind]+" / "+(M.states[r.management]||"未知")),text("strong",r.name),text("span",r.summary||r.description||"暂无功能概要"),text("small",M.categories(r).join(" · ")));b.onclick=()=>{selected=r;render();Array.from($("list").children)[visible.indexOf(r)].querySelector("button").focus();};row.append(check,b);$("list").append(row);});
  const r=selected;$("detail").append(text("h2",r.name),text("h3","功能概要"),text("p",r.summary||r.description||"暂无功能概要"),text("small",M.categories(r).join(" · ")));
  if(r.kind==="skill" || r.kind==="agent-document") renderTrigger(r);
  const dl=document.createElement("dl");
  if(r.kind==="agent-document") {
    [["所属智能体",r.agent],["文档 ID",r.documentId],["复制来源",r.parent ? [r.parent.agent,r.parent.documentId,r.parent.commit].join(" / ") : "原创或来源待核实"],["最初来源",r.root ? [r.root.agent,r.root.documentId,r.root.commit].join(" / ") : "原创或来源待核实"]].forEach(([k,v])=>dl.append(text("dt",k),text("dd",v)));
  }
  [["类型",M.kinds[r.kind]],[r.ownership==="third-party"?"本机版本":"清单版本",r.version],["用户决定",M.stateText(r,"decision")],["收藏结果",M.stateText(r,"collection")],["本机安装",M.stateText(r,"installation")],["同步结果",r.ownership==="third-party"?"不参与源码同步（仅记录安装信息）":M.stateText(r,"sync")],["目录刷新",M.stateText(r,"catalog")],["验证状态",r.verification==="configured-only"?"仅配置，调用未验证":r.verification],["归属",({self:"自建或本地定制",derived:"独立派生","third-party":"第三方"})[r.ownership]||r.ownership],["许可",r.license==="owner-defined"?"由所有者定义":r.license],["固定提交",r.resolvedCommit]].forEach(([k,v])=>dl.append(text("dt",k),text("dd",v||"未知")));
  $("detail").append(dl);const url=M.safeUrl(r.projectUrl);if(url){const a=text("a","查看项目来源 ↗");a.href=url;a.target="_blank";a.rel="noopener noreferrer";$("detail").append(a);}else $("detail").append(text("p","暂无可用的公开来源链接"));
}
function renderTrigger(resource) {
  const label=resource.kind==="agent-document" ? "文档导入提示" : "技能触发提示";
  $("detail").append(text("h3",label));
  if(!resource.triggerPrompt){$("detail").append(text("p","尚未根据技能说明整理触发提示。"));return;}
  const prompt=document.createElement("textarea");
  prompt.readOnly=true;prompt.value=resource.triggerPrompt;prompt.rows=4;prompt.setAttribute("aria-label",label);
  const button=text("button","复制触发提示","copy");button.type="button";
  const notice=text("p","复制后粘贴到 AI 对话中；按实际任务替换方括号内容。","copy-notice");notice.setAttribute("role","status");
  button.onclick=async()=>{
    try {
      if(!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(prompt.value);
      notice.textContent="已复制触发提示";
    } catch {
      prompt.focus();prompt.select();
      notice.textContent="自动复制不可用，提示已选中，请按 Ctrl+C（Mac：⌘C）。";
    }
  };
  $("detail").append(prompt,button,notice);
}
function renderOperations(rows, visible) {
  const chosen=rows.filter(r=>checked.has(r.id));
  const hidden=chosen.filter(r=>!visible.includes(r)).length;
  $("selection-count").textContent="已选 "+chosen.length+" 项，其中筛选隐藏 "+hidden+" 项（仍包含在指令中）";
  $("operation-preview").value=M.operationPrompt(chosen,$("operation").value,demo);
  $("clear-selection").disabled=!chosen.length;
  const unsupported=chosen.filter(r=>!M.supportsAction(r,$("operation").value));
  $("copy-operation").disabled=!chosen.length || unsupported.length>0;
  $("operation-notice").textContent=unsupported.length ? "所选资源中有 "+unsupported.length+" 项不支持此操作：同步仅限自建资源或自己的 Agent 文档；检查更新和更新仅限第三方。请调整选择。" : demo?"示例指令只供说明，不得执行。":"复制后粘贴给 AI 即可。";
}
$("operation").onchange=render;
$("clear-selection").onclick=()=>{checked.clear();render();};
$("copy-operation").onclick=async()=>{
  const prompt=$("operation-preview"), notice=$("operation-notice");
  if(!prompt.value) return;
  try {
    if(!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
    await navigator.clipboard.writeText(prompt.value);
    notice.textContent="已复制操作指令";
  } catch {
    $("operation-disclosure").open=true;
    prompt.focus();prompt.select();
    notice.textContent="自动复制不可用，指令已选中，请按 Ctrl+C（Mac：⌘C）。";
  }
};
$("search").oninput=render;$("status").onchange=render;$("demo").onclick=()=>{demo=!demo;checked.clear();kind="all";category="all";selected=null;$("search").value="";$("status").value="all";render();};
render();
