/* Phase 1: opted-in regular accounts only. No automatic fetch interception. */
(() => {
 'use strict';
 const KEY='swimmate.analytics-consent.v1';
 const SCREENS={'/training_log':'training_log','/training-log':'training_log','/report':'report'};
 const screen=SCREENS[location.pathname];
 const hosts=['swimtech.vercel.app'];
 let ready=false,config=null,loaded=false,viewSent=false;
 const allowed={page_view:{},training_log_view:{},report_view:{},training_log_start:{input_method:['manual']},training_log_create:{input_method:['manual']},training_log_error:{input_method:['manual'],error_code:['validation','server','network']}};
 function choice(){try{return localStorage.getItem(KEY);}catch{return null;}}
 function push(event,params={}){
   if(!ready||!Object.hasOwn(allowed,event))return false;
   const safe={event,screen_name:screen,event_schema_version:'1'};
   for(const [key,values] of Object.entries(allowed[event])){
     if(!values.includes(params[key]))return false;
     safe[key]=params[key];
   }
   try{window.dataLayer.push(safe);return true;}catch{return false;}
 }
 function start(){
   if(loaded||choice()!=='granted'||!config?.enabled)return;
   loaded=true;window.dataLayer=window.dataLayer||[];
   function consent(){window.dataLayer.push(arguments);}
   consent('consent','default',{analytics_storage:'denied',ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied'});
   consent('consent','update',{analytics_storage:'granted'});
   // GTM tags must explicitly use these sanitized variables; never Page URL,
   // document title, forms, searches or enhanced automatic page collection.
   window.dataLayer.push({safe_page_location:location.origin+location.pathname,safe_page_referrer:'',safe_page_title:'SwimMate '+screen});
   window.dataLayer.push({'gtm.start':Date.now(),event:'gtm.js'});
   const script=document.createElement('script');script.async=true;
   script.src='https://www.googletagmanager.com/gtm.js?id='+encodeURIComponent(config.container_id);
   document.head.append(script);ready=true;
   window.dataLayer.push({event:'sm_analytics_ready'});
   if(!viewSent){viewSent=true;push('page_view');push(screen==='training_log'?'training_log_view':'report_view');}
 }
 function select(value){
   try{localStorage.setItem(KEY,value);}catch{return;}
   document.getElementById('analytics-choice')?.remove();
   if(value==='granted')start();
   else if(loaded){
     ready=false;
     function consent(){window.dataLayer.push(arguments);}
     consent('consent','update',{analytics_storage:'denied',ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied'});
     for(const cookie of document.cookie.split(';')){
       const name=cookie.split('=')[0].trim();
       if(name==='_ga'||name.startsWith('_ga_')){
         document.cookie=name+'=; Max-Age=0; path=/';
         document.cookie=name+'=; Max-Age=0; path=/; domain='+location.hostname;
       }
     }
     location.reload();
   }
 }
 function preferences(){
   if(!config?.enabled||document.getElementById('analytics-choice'))return;
   const box=document.createElement('section');box.id='analytics-choice';box.setAttribute('aria-label','선택 분석 설정');
   box.style.cssText='position:fixed;bottom:16px;left:16px;right:16px;max-width:620px;z-index:10000;padding:18px;border:1px solid #00b4d8;border-radius:12px;background:#10283e;color:white;box-shadow:0 8px 24px #0008;';
   const text=document.createElement('p');text.textContent='선택 분석 쿠키: Google Analytics로 훈련 일지 이용 흐름을 분석합니다. 동의하지 않아도 서비스를 이용할 수 있습니다. 이름·일지 내용·건강 정보는 보내지 않습니다.';box.append(text);
   const link=document.createElement('a');link.href='/privacy';link.textContent='개인정보 안내';link.style.color='#70d9f0';box.append(link);
   for(const [label,value] of [['거부','denied'],['동의','granted']]){const button=document.createElement('button');button.type='button';button.textContent=label;button.style.cssText='margin:10px;padding:8px 16px;';button.onclick=()=>select(value);box.append(button);}
   document.body.append(box);
 }
 window.SwimMateAnalytics=Object.freeze({track:push,preferences});
 async function init(){
   if(!screen||!hosts.includes(location.hostname)||navigator.globalPrivacyControl===true)return;
   try{const r=await fetch('/api/analytics/config',{credentials:'include',cache:'no-store'});if(!r.ok)return;config=await r.json();}catch{return;}
   if(!config?.enabled||!/^GTM-[A-Z0-9]+$/.test(config.container_id)||!/^G-[A-Z0-9]+$/.test(config.measurement_id))return;
   const settings=document.createElement('button');settings.type='button';settings.textContent='분석 설정';settings.onclick=preferences;settings.style.cssText='position:fixed;bottom:8px;right:8px;z-index:9999;padding:6px;border-radius:8px;';document.body.append(settings);
   if(choice()==='granted')start();else if(choice()!=='denied')preferences();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
