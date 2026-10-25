'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=path.join(__dirname,'../catalog');
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.value='';this.hidden=false;this.textContent='';}
  append(...nodes){this.children.push(...nodes)}
  replaceChildren(...nodes){this.children=nodes}
  setAttribute(k,v){this[k]=v}
  focus(){this.focused=true} select(){this.selected=true}
  querySelector(){return this.children.find(e=>e.tag==='button')}
}
const row={id:'official',name:'Collected',kind:'skill',management:'managed',ownership:'self'};
const discovery={generatedAt:'2026-10-23T00:00:00Z',scopes:[],warnings:[],groups:[
  {id:'group',name:'Unknown',source:null,identityStatus:'unknown',components:[
    {id:'found',name:'Pending',kind:'skill',installations:[{path:'C:/pending',status:'files-present'}]}]}]};
function load(snapshot,hash='') {
  const ids={},get=id=>ids[id]??=new Element(id);
  get('status').value='all';get('operation').value='install';get('pending-kind').value='all';
  const listeners={},location={hash};
  const ctx=vm.createContext({document:{getElementById:get,createElement:t=>new Element(t)},URLSearchParams,
    window:{TOOLBOX_DATA:{resources:[row]},TOOLBOX_DEMO:{resources:[]},TOOLBOX_DISCOVERY:snapshot,
      location,addEventListener:(event,fn)=>listeners[event]=fn},navigator:{}});
  for(const file of ['model.js','inventory-model.js','inventory-app.js','app.js'])vm.runInContext(fs.readFileSync(path.join(base,file),'utf8'),ctx);
  return Object.assign(ids,{location,listeners});
}
(async()=>{
  const ids=load(discovery);
  assert.equal(ids['pending-content'].hidden,false);
  assert.equal(ids['pending-empty'].hidden,true);
  const collected=ids.list.children[0].children[0];collected.checked=true;collected.onchange();
  const saved=ids['operation-preview'].value;
  ids['view-pending'].onclick();
  assert.equal(ids['collected-view'].hidden,true);assert.equal(ids['pending-view'].hidden,false);
  ids['pending-select-visible'].onclick();
  assert.ok(ids['pending-prompt'].value.includes('C:/pending'));
  assert.equal(ids['operation-preview'].value,saved);
  ids['pending-query'].value='no-match';ids['pending-query'].oninput();
  assert.equal(ids['pending-list'].children.length,1); // empty-state paragraph
  assert.ok(ids['pending-selection'].textContent.includes('仍选中 1'));
  await ids['pending-copy'].onclick();
  assert.equal(ids['pending-prompt'].selected,true);
  ids['view-collected'].onclick();assert.equal(ids['collected-view'].hidden,false);
  assert.equal(ids['operation-preview'].value,saved);
  ids['view-pending'].onclick();assert.ok(ids['pending-prompt'].value.includes('Pending'));
  ids['pending-clear'].onclick();assert.equal(ids['pending-prompt'].value,'');
  const empty=load(null);empty['view-pending'].onclick();
  assert.equal(empty['pending-view'].hidden,false);
  assert.equal(empty['pending-content'],undefined); // HTML retains its initial hidden state.
  const html=fs.readFileSync(path.join(base,'index.html'),'utf8');
  const all=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
  assert.equal(new Set(all).size,all.length,'unique IDs across both panels');
  assert.equal(ids['workspace-check'].hidden,true,'direct offline opening makes no fresh-check claim');
  ids.location.hash='#toolbox-check=stale-cache&checkedAt=2026-10-25T00%3A00%3A00Z';ids.listeners.hashchange();
  assert.equal(ids['workspace-check'].hidden,false);
  assert.ok(ids['workspace-check'].textContent.includes('未确认最新状态'));
  ids.location.hash='#toolbox-check=cached&checkedAt=2026-10-25T00%3A01%3A00Z';ids.listeners.hashchange();
  assert.ok(ids['workspace-check'].textContent.includes('入口已检查'));
  assert.equal(ids['operation-preview'].value,saved,'hash updates preserve user selections');
  const stale=load(discovery,'#toolbox-check=stale-cache&checkedAt=invalid');
  assert.ok(stale['workspace-check'].textContent.includes('时间未知'));
  assert.equal(load(discovery,'#toolbox-check=unexpected')['workspace-check'].hidden,true);
  console.log('PASS workspace views, independent selections, hidden selections, clipboard fallback and empty discovery');
})().catch(e=>{console.error(e);process.exitCode=1});
