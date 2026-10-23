/* Synthetic DOM branch coverage, deliberately not a real-browser acceptance test. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.value='';this.textContent='';this.disabled=false;this.checked=false;this.indeterminate=false;}
 append(...nodes){this.children.push(...nodes)}
 replaceChildren(...nodes){this.children=nodes}
 setAttribute(key,value){this[key]=value}
 focus(){this.focused=true} select(){this.selected=true}
}
const ids={};const document={getElementById:id=>ids[id]??=new Element(id),createElement:tag=>new Element(tag)};
const snapshot={generatedAt:'2026-10-22T00:00:00Z',scopes:[],warnings:[],groups:[
 {id:'p',name:'Bundle',source:'https://github.com/x/y',identityStatus:'metadata-backed',evidence:[],components:[
  {id:'a',kind:'skill',name:'Alpha',componentKey:'a',installations:[{path:'C:/a',status:'files-present'}]},
  {id:'b',kind:'plugin',name:'Beta',componentKey:'b',installations:[{path:'C:/b',status:'cache-only'}]}]},
 {id:'q',name:'Unknown',source:null,identityStatus:'unknown',evidence:[],components:[
  {id:'c',kind:'skill',name:'Gamma',componentKey:'c',installations:[{path:'C:/c',status:'files-present'}]}]}]};
document.getElementById('kind').value='all';
let copied='';const ctx=vm.createContext({document,navigator:{clipboard:{writeText:async t=>{copied=t}}},Set,Date});
const template=fs.readFileSync(path.join(__dirname,'../catalog/inventory.html'),'utf8');
const html=template.replace('/* INVENTORY_MODEL */',fs.readFileSync(path.join(__dirname,'../catalog/inventory-model.js'),'utf8')).replace('/* INVENTORY_DATA */',JSON.stringify(snapshot));
for(const m of html.matchAll(/<script>([\s\S]*?)<\/script>/g))vm.runInContext(m[1],ctx);
assert.equal(ids.list.children.length,2);assert.equal(ids.copy.disabled,true);
ids['select-visible'].onclick();assert.equal(ids.copy.disabled,false);
assert.ok(ids.prompt.value.includes('"id"')===false); // selection uses discoveryId, never official ID.
ids.query.value='Alpha';ids.query.oninput();assert.equal(ids.list.children.length,1);
assert.ok(ids.selection.textContent.includes('2 个'));
const parent=ids.list.children[0].children[0].children[0];parent.checked=false;parent.onchange();
assert.ok(ids.prompt.value.includes('skill "Alpha"')===false);
assert.ok(ids.prompt.value.includes('plugin "Beta"'));
ids.clear.onclick();assert.equal(ids.copy.disabled,true);assert.equal(ids.prompt.value,'');
ids.kind.value='skill';ids.query.value='';ids.kind.onchange();ids['select-visible'].onclick();
assert.ok(!ids.prompt.value.includes('plugin "Beta"'));
(async()=>{await ids.copy.onclick();assert.equal(copied,ids.prompt.value);assert.ok(ids.notice.textContent.includes('已复制'));
 ctx.navigator.clipboard.writeText=async()=>{throw Error('denied')};await ids.copy.onclick();
 assert.equal(ids.prompt.selected,true);assert.ok(ids.notice.textContent.includes('手动复制'));
 console.log('Synthetic DOM: filtering, hidden selections, partial parents, clear, clipboard success/failure passed');
})().catch(e=>{console.error(e);process.exitCode=1});
