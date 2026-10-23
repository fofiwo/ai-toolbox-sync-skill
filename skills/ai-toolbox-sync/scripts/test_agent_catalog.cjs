const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const base=path.resolve(__dirname,'..'),M=require(path.join(base,'catalog/model.js'));
const doc={id:'agent-document:abc',documentId:'abc',name:'Codex 全局规则',kind:'agent-document',ownership:'derived',agent:'codex',projectUrl:'https://github.com/example/toolbox',resolvedCommit:'a'.repeat(40),triggerPrompt:'导入并确认整份文件',parent:{agent:'claude',documentId:'parent',commit:'b'.repeat(40)},root:{agent:'codex',documentId:'root',commit:'c'.repeat(40)}};
assert.equal(M.kinds['agent-document'],'Agent 文档');
assert.equal(M.filter([doc],'agent-document','','all').length,1);
const prompt=M.operationPrompt([doc],'install',false);
for(const term of ['abc','a'.repeat(40),'覆盖','重新整理','追加','插入','独立派生','自己的全文']) assert.ok(prompt.includes(term),term);
assert.ok(M.operationPrompt([doc],'sync',false).includes('没有自己的绑定则停止'));
assert.equal(M.operationPrompt([doc],'update',false),'');
assert.equal(M.supportsAction({...doc,ownership:'unknown'},'sync'),false);
assert.ok(M.operationPrompt([doc],'install',true).startsWith('【仅演示，不可执行】'));
function el(tag){return {tag,children:[],value:'',textContent:'',attributes:{},append(...v){this.children.push(...v)},replaceChildren(){this.children=[]},setAttribute(k,v){this.attributes[k]=v},focus(){this.focused=true},select(){this.selected=true},querySelector(){return this.children.find(x=>x.tag==='button')}};}
const ids={},$=id=>ids[id]??=el(id);$('search').value='';$('status').value='all';$('operation').value='install';
const context={ToolboxModel:M,document:{getElementById:$,createElement:el},window:{TOOLBOX_DATA:{resources:[doc]},TOOLBOX_DEMO:{resources:[]}},navigator:{clipboard:{writeText:async value=>{context.copied=value}}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(base,'catalog/app.js'),'utf8'),context);
(async()=>{
  assert.ok($('detail').children.some(e=>e.textContent==='文档导入提示'));
  const info=$('detail').children.find(e=>e.tag==='dl');
  assert.ok(info.children.some(e=>e.textContent.includes('parent')));
  assert.ok(info.children.some(e=>e.textContent.includes('root')));
  const copy=$('detail').children.find(e=>e.tag==='button');
  await copy.onclick();assert.equal(context.copied,doc.triggerPrompt);
  const selection=$('list').children[0].children[0];selection.checked=true;selection.onchange();
  await $('copy-operation').onclick();assert.ok(context.copied.includes('独立派生'));
  context.navigator.clipboard=undefined;await $('copy-operation').onclick();
  assert.equal($('operation-preview').selected,true);
  console.log('PASS Agent document tab, provenance, import/sync scope, clipboard and fallback');
})().catch(error=>{console.error(error);process.exitCode=1});
