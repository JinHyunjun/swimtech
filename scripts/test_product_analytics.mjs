import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../frontend/static/product-analytics.js',import.meta.url),'utf8');
async function boot({enabled=true,consent='granted',host='swimtech.vercel.app',path='/training_log',fails=false}={}){
 const appended=[],store=new Map(consent?[['swimmate.analytics-consent.v1',consent]]:[]);
 const element=()=>({style:{},append(){},setAttribute(){}});
 const context={location:{hostname:host,pathname:path,origin:'https://'+host,reload(){}},navigator:{},
 localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},
 document:{readyState:'complete',getElementById:()=>null,createElement:element,head:{append:s=>appended.push(s)},body:{append(){}}},
 fetch:async()=>{if(fails)throw Error('offline');return {ok:true,json:async()=>({enabled,container_id:'GTM-TEST123',measurement_id:'G-TEST123'})};}};
 context.window=context;vm.createContext(context);vm.runInContext(source,context);await new Promise(r=>setTimeout(r,0));
 return {context,appended};
}
test('disabled, denied, unresolved, offline, preview and admin load no Google code',async()=>{
 for(const options of [{enabled:false},{consent:'denied'},{consent:null},{fails:true},{host:'preview.vercel.app'},{path:'/admin'}]){
   const {context,appended}=await boot(options);assert.equal(appended.length,0);assert.equal(context.SwimMateAnalytics.track('training_log_create',{input_method:'manual'}),false);
 }
});
test('eligible consent loads once and allowlists event parameters',async()=>{
 const {context:c,appended}=await boot();assert.equal(appended.length,1);
 const view=c.dataLayer.filter(x=>x.event==='training_log_view');assert.equal(view.length,1);
 assert(c.SwimMateAnalytics.track('training_log_create',{input_method:'manual',memo:'SECRET',email:'SECRET'}));
 assert(!JSON.stringify(c.dataLayer).includes('SECRET'));
 assert(!c.SwimMateAnalytics.track('training_log_error',{input_method:'manual',error_code:'SECRET'}));
 assert(!c.SwimMateAnalytics.track('unknown_event'));
 assert(c.dataLayer.some(x=>x.safe_page_location==='https://swimtech.vercel.app/training_log'));
});
test('analytics transport failure never breaks application events',async()=>{
 const {context:c}=await boot();c.dataLayer.push=()=>{throw Error('blocked')};
 assert.equal(c.SwimMateAnalytics.track('training_log_create',{input_method:'manual'}),false);
});

const training=fs.readFileSync(new URL('../frontend/training_log.html',import.meta.url),'utf8');
const trackingHelper=training.slice(training.indexOf('function trackManualLog('),training.indexOf("document.getElementById('modal-backdrop').addEventListener('input'"));
const saveFunction=training.slice(training.indexOf('async function saveLog()'),training.indexOf('function showReportToast('));
async function saveFixture({edit=false,ok=true,network=false,twice=false}={}){
 const events=[],values={'edit-id':edit?'123':'','f-date':'2026-10-25','f-stroke':'freestyle','f-pool':'25','f-distance':'500','f-duration':'30','f-intensity':'easy','f-mood':'','f-memo':'PRIVATE HEALTH NOTE'};
 const elements=new Map(Object.entries(values).map(([k,value])=>[k,{value}]));elements.set('f-fins',{checked:false});elements.set('btn-modal-submit',{disabled:false});
 let writes=0;
 const c={document:{getElementById:id=>elements.get(id)},pendingPlanCompletion:null,pendingTrainingSets:[],savingLog:false,
 window:{SwimMateAnalytics:{track:(...args)=>{events.push(args);return true;}}},
 clearModalError(){},showModalError(){},closeModal(){},refresh(){},showReportToast(){},
 fetch:async()=>{writes++;await new Promise(r=>setTimeout(r,5));if(network)throw Error('offline');return {ok,json:async()=>({id:456})};}};
 vm.createContext(c);vm.runInContext(trackingHelper+saveFunction,c);
 if(twice)await Promise.all([c.saveLog(),c.saveLog()]);else await c.saveLog();
 return {events,writes,button:elements.get('btn-modal-submit')};
}
test('actual manual save code counts success once and excludes edits',async()=>{
 const saved=await saveFixture({twice:true});assert.equal(saved.writes,1);
 assert.deepEqual(saved.events.map(e=>e[0]),['training_log_create']);assert(!JSON.stringify(saved.events).includes('PRIVATE'));
 assert.equal(saved.button.disabled,false);
 assert.equal((await saveFixture({edit:true})).events.length,0);
});
test('actual save code distinguishes server and network failures, never success',async()=>{
 for(const [options,reason] of [[{ok:false},'server'],[{network:true},'network']]){
   const {events}=await saveFixture(options);assert.equal(events.length,1);assert.equal(events[0][0],'training_log_error');assert.equal(events[0][1].error_code,reason);
 }
});
