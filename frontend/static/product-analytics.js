/* Service-wide opted-in regular-account analytics. No fetch/body interception. */
(() => {
 'use strict';
 const POLICY='2026-10-v2';
 const KEY='swimmate.analytics-consent.v2';
 const SCREENS={'/landing':'landing','/dashboard':'dashboard','/my-data':'my_data','/plan':'plan',
 '/training_log':'training_log','/training-log':'training_log','/workout':'workout','/report':'report',
 '/pool':'pool','/community':'community','/challenge':'challenge','/badge':'badges','/badges':'badges',
 '/coach':'coach','/clubs':'clubs','/chat':'chat','/profile':'profile','/account':'account',
 '/drill':'drill','/equipment':'equipment','/glossary':'glossary','/faq':'faq','/injury':'injury',
 '/videos':'videos','/feedback':'feedback','/changelog':'changelog','/tutorial':'tutorial',
 '/tutorial_personal':'tutorial_personal','/tutorial/personal':'tutorial_personal',
 '/tutorial_record':'tutorial_record','/tutorial/record':'tutorial_record',
 '/tutorial_data':'tutorial_data','/tutorial/data':'tutorial_data',
 '/tutorial_coach':'tutorial_coach','/tutorial/coach':'tutorial_coach',
 '/tutorial_help':'tutorial_help','/tutorial/help':'tutorial_help'};
 const screen=SCREENS[location.pathname];
 const hosts=['swimtech.vercel.app'];
 let ready=false,config=null,loaded=false,viewSent=false;
 const allowed={page_view:{},training_log_view:{},report_view:{},training_log_start:{input_method:['manual']},training_log_create:{input_method:['manual']},training_log_error:{input_method:['manual'],error_code:['validation','server','network']}};
 Object.assign(allowed,{menu_navigate:{destination_screen:[...new Set(Object.values(SCREENS))]},
 community_post_create:{},community_comment_create:{},plan_create:{},plan_share_link_ready:{},
 coach_join:{},coach_task_create:{},coach_task_complete:{},challenge_join:{}});
 function choice(){try{return localStorage.getItem(KEY);}catch{return null;}}
 function push(event,params={}){
   if(!ready||!Object.hasOwn(allowed,event))return false;
   const safe={event,screen_name:screen,event_schema_version:'2'};
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
   if(!viewSent){viewSent=true;push('page_view');if(screen==='training_log')push('training_log_view');else if(screen==='report')push('report_view');}
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
   const text=document.createElement('p');text.textContent='선택 분석 쿠키: Google Analytics로 메뉴 이동과 일지·플랜·커뮤니티·코치 기능의 이용 흐름을 분석합니다. 동의하지 않아도 서비스를 이용할 수 있습니다. 이름·입력 내용·건강 정보는 보내지 않습니다.';box.append(text);
   const link=document.createElement('a');link.href='/privacy';link.textContent='개인정보 안내';link.style.color='#70d9f0';box.append(link);
   for(const [label,value] of [['거부','denied'],['동의','granted']]){const button=document.createElement('button');button.type='button';button.textContent=label;button.style.cssText='margin:10px;padding:8px 16px;';button.onclick=()=>select(value);box.append(button);}
   document.body.append(box);
 }
 window.SwimMateAnalytics=Object.freeze({track:push,preferences});
 document.addEventListener('click',event=>{
   if(!ready)return;
   const link=event.target?.closest?.('a[href]');if(!link)return;
   try{const to=new URL(link.href,location.origin);
     if(to.origin!==location.origin||!SCREENS[to.pathname]||SCREENS[to.pathname]===screen)return;
     push('menu_navigate',{destination_screen:SCREENS[to.pathname]});
   }catch{/* Navigation must never depend on analytics. */}
 });
 async function init(){
   if(!screen||!hosts.includes(location.hostname)||navigator.globalPrivacyControl===true)return;
   try{const r=await fetch('/api/analytics/config',{credentials:'include',cache:'no-store'});if(!r.ok)return;config=await r.json();}catch{return;}
   if(!config?.enabled||config.policy_version!==POLICY||!/^GTM-[A-Z0-9]+$/.test(config.container_id)||!/^G-[A-Z0-9]+$/.test(config.measurement_id))return;
   const settings=document.createElement('button');settings.type='button';settings.textContent='분석 설정';settings.onclick=preferences;settings.style.cssText='position:fixed;bottom:8px;right:8px;z-index:9999;padding:6px;border-radius:8px;';document.body.append(settings);
   if(choice()==='granted')start();else if(choice()!=='denied')preferences();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
