const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/startup.js'),'utf8');
function harness(){
 const listeners={},dom={},nodes={};let timeout=null,reloads=0,consent=false;
 for(const id of ['startup-error','startup-error-detail','startup-reload'])nodes[id]={hidden:true,textContent:'',addEventListener(type,fn){this[type]=fn}};
 const window={addEventListener:(type,fn)=>listeners[type]=fn,confirm:()=>consent,location:{reload:()=>reloads++}};
 const context={window,document:{getElementById:id=>nodes[id],addEventListener:(type,fn)=>dom[type]=fn},
   setTimeout:fn=>{timeout=fn;return 1},clearTimeout:()=>timeout=null};
 vm.runInNewContext(source,context);
 return {window,nodes,listeners,dom,timeout:()=>timeout?.(),consent:v=>consent=v,reloads:()=>reloads};
}
test('startup script failure is visible independently of the app bundle',()=>{
 const h=harness();h.listeners.error({target:{tagName:'SCRIPT',src:'http://localhost/app.js?v=1'}});
 h.dom.DOMContentLoaded();assert.equal(h.nodes['startup-error'].hidden,false);
 assert.match(h.nodes['startup-error-detail'].textContent,/app.js/);
 assert.equal(h.reloads(),0);
});
test('successful bootstrap clears the startup warning and timer',()=>{
 const h=harness();h.dom.DOMContentLoaded();h.timeout();assert.equal(h.nodes['startup-error'].hidden,false);
 h.window.toolkitStartup.ready();h.timeout();assert.equal(h.nodes['startup-error'].hidden,true);
 h.listeners.error({message:'later unrelated error'});assert.equal(h.nodes['startup-error'].hidden,true);
});
test('failed bootstrap remains actionable; reload requires explicit confirmation',()=>{
 const h=harness();h.dom.DOMContentLoaded();h.window.toolkitStartup.fail('读取超时');
 assert.match(h.nodes['startup-error-detail'].textContent,/读取超时/);
 h.nodes['startup-reload'].click();assert.equal(h.reloads(),0);
 h.consent(true);h.nodes['startup-reload'].click();assert.equal(h.reloads(),1);
});
test('errors are bounded and unhandled startup rejection is captured',()=>{
 const h=harness();h.dom.DOMContentLoaded();
 for(let i=0;i<20;i++)h.listeners.unhandledrejection({reason:{message:'a'.repeat(5000)}});
 assert.equal(h.window.toolkitStartup.errors.length,10);
 assert.equal(h.window.toolkitStartup.errors[0].length,1200);
});
