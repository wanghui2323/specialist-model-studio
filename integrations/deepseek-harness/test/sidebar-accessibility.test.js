import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import{readFileSync}from'node:fs';
const source=readFileSync(new URL('../../../model_harness/web/app.js',import.meta.url),'utf8');
const code=source.slice(source.indexOf('function syncInspectorIsolation()'),source.indexOf('function inspectorFocusables()'));
test('closed offscreen navigation is inert and hidden from assistive/automation trees, while open and wide navigation is usable',()=>{
  const node=()=>({dataset:{},attrs:{},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];}});
  const context={ui:{sidebar:node(),menuButton:node(),conversationMain:node(),mobileViewNav:node(),inspector:node()},sidebarMedia:{matches:true},overlayWorkspace:()=>false};
  vm.runInNewContext(code+';globalThis.sync=syncInspectorIsolation;',context);
  context.sync();assert.equal(context.ui.sidebar.inert,true);assert.equal(context.ui.sidebar.attrs['aria-hidden'],'true');assert.equal(context.ui.conversationMain.inert,false);
  context.ui.sidebar.dataset.open='true';context.sync();assert.equal(context.ui.sidebar.inert,false);assert.equal(context.ui.sidebar.attrs['aria-hidden'],'false');
  context.ui.sidebar.dataset.open='false';context.sidebarMedia.matches=false;context.sync();assert.equal(context.ui.sidebar.inert,false);
  context.overlayWorkspace=()=>true;context.ui.inspector.dataset.open='true';context.sync();assert.equal(context.ui.sidebar.inert,true);assert.equal(context.ui.conversationMain.inert,true);
});
