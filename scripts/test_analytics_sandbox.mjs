import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
const source=fs.readFileSync(new URL('../frontend/static/analytics-test.js',import.meta.url),'utf8');
async function boot({host='localhost',enabled=false,container='GTM-SANDBOX',measurement='G-SANDBOX',gpc=false}={}){
 const nodes={},requests=[],scripts=[],buttons=[];
 for(const id of ['status','log','connect','stop'])nodes[id]={textContent:'',disabled:true,addEventListener(type,fn){this[type]=fn;}};
 for(const event of ['page_view','training_log_create','training_log_error'])buttons.push({dataset:{event},addEventListener(type,fn){this[type]=fn;}});
 const window={};const context={window,document:{getElementById:id=>nodes[id],querySelectorAll:()=>buttons,head:{append:s=>scripts.push(s)},createElement:()=>({}),cookie:''},location:{hostname:host,origin:'http://'+host+':8766',reload(){}},navigator:{globalPrivacyControl:gpc},fetch:async url=>{requests.push(url);return {ok:true,json:async()=>({enabled,container_id:container,measurement_id:measurement})};}};
 vm.runInNewContext(source,context);await new Promise(resolve=>setImmediate(resolve));
 return {nodes,requests,scripts,buttons,window};
}
test('production hosts cannot fetch config or load Google, even on explicit click',async()=>{
 const a=await boot({host:'swimtech.vercel.app',enabled:true});a.nodes.connect.click();assert.equal(a.requests.length,0);assert.equal(a.scripts.length,0);
});
test('disabled and production IDs remain local-only',async()=>{
 for(const options of [{},{enabled:true,container:'GTM-5TQRKVQ5'},{enabled:true,measurement:'G-B43M43WPM9'},{enabled:true,gpc:true}]){
   const a=await boot(options);a.nodes.connect.click();a.buttons[0].click();assert.equal(a.scripts.length,0);assert.equal(a.window.dataLayer,undefined);
 }
});
test('isolated IDs require explicit consent, load once, and emit only synthetic fields',async()=>{
 const a=await boot({enabled:true});assert.equal(a.scripts.length,0);assert.equal(a.nodes.connect.disabled,false);
 a.nodes.connect.click();a.nodes.connect.click();assert.equal(a.scripts.length,1);assert.match(a.scripts[0].src,/GTM-SANDBOX$/);
 a.buttons[2].click();const event=a.window.dataLayer.at(-1);assert.equal(event.event,'training_log_error');assert.equal(event.error_code,'validation');assert.equal(event.debug_mode,true);
 assert.equal(JSON.stringify(a.window.dataLayer).includes('B43M43WPM9'),false);
});
