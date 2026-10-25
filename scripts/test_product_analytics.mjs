import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../frontend/static/product-analytics.js',import.meta.url),'utf8');
async function boot({enabled=true,consent='granted',host='swimtech.vercel.app',path='/training_log',fails=false}={}){
 const appended=[],listeners={},store=new Map(consent?[['swimmate.analytics-consent.v2',consent]]:[]);
 const element=()=>({style:{},append(){},setAttribute(){}});
 const context={location:{hostname:host,pathname:path,origin:'https://'+host,reload(){}},navigator:{},
 localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},
 document:{readyState:'complete',addEventListener:(type,fn)=>listeners[type]=fn,getElementById:()=>null,createElement:element,head:{append:s=>appended.push(s)},body:{append(){}}},URL,
 fetch:async()=>{if(fails)throw Error('offline');return {ok:true,json:async()=>({enabled,policy_version:'2026-10-v2',container_id:'GTM-TEST123',measurement_id:'G-TEST123'})};}};
 context.window=context;vm.createContext(context);vm.runInContext(source,context);await new Promise(r=>setTimeout(r,0));
 return {context,appended,listeners};
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

test('general menus emit page views without falsely emitting report views',async()=>{
 for(const path of ['/landing','/dashboard','/community','/plan','/coach','/clubs','/challenge','/pool']){
   const {context:c}=await boot({path});
   assert.equal(c.dataLayer.filter(x=>x.event==='page_view').length,1);
   assert.equal(c.dataLayer.filter(x=>x.event==='report_view').length,0);
   assert(c.SwimMateAnalytics.track('community_post_create',{title:'SECRET'}));
   assert(!JSON.stringify(c.dataLayer).includes('SECRET'));
 }
});
test('menu destination is enum only and demo/admin pages stay excluded',async()=>{
 const {context:c}=await boot({path:'/community'});
 assert(c.SwimMateAnalytics.track('menu_navigate',{destination_screen:'plan'}));
 assert(!c.SwimMateAnalytics.track('menu_navigate',{destination_screen:'https://private.test?secret'}));
 for(const path of ['/community_demo','/admin_video_lab','/result/private-token'])assert.equal((await boot({path})).appended.length,0);
});
test('actual navigation listener strips destinations to enum and ignores external/unknown links',async()=>{
 const {context:c,listeners}=await boot({path:'/dashboard'});
 for(const href of ['https://swimtech.vercel.app/plan?private=SECRET#note','https://outside.test/plan','https://swimtech.vercel.app/admin','https://swimtech.vercel.app/plan/share/SECRET'])listeners.click({target:{closest:()=>({href})}});
 const events=c.dataLayer.filter(x=>x.event==='menu_navigate');assert.equal(events.length,1);assert.equal(events[0].destination_screen,'plan');assert(!JSON.stringify(c.dataLayer).includes('SECRET'));
});
test('each supported screen includes the analytics script exactly once',()=>{
 for(const page of ['landing','dashboard','my-data','plan','training_log','workout','report','pool','community','challenge','badge','coach','clubs','chat','profile','account','drill','equipment','glossary','faq','injury','videos','feedback','changelog','tutorial','tutorial_personal','tutorial_record','tutorial_data','tutorial_coach','tutorial_help']){
   const html=fs.readFileSync(new URL('../frontend/'+page+'.html',import.meta.url),'utf8');assert.equal(html.split('/static/product-analytics.js').length-1,1,page);
   for(const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi))if(!/\bsrc\s*=|application\//i.test(match[1]))new vm.Script(match[2],{filename:page+'.html'});
 }
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
