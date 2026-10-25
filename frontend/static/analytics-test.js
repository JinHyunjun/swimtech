/* Synthetic sandbox. No production IDs, user data, or application mutations. */
(() => {
 'use strict';
 const status=document.getElementById('status'), log=document.getElementById('log');
 const connect=document.getElementById('connect');
 let config=null,active=false;
 const write=value=>{log.textContent+=JSON.stringify(value)+'\n';};
 const events=new Set(['page_view','training_log_view','training_log_start','training_log_create','training_log_error','report_view','menu_navigate']);
 document.querySelectorAll('[data-event]').forEach(button=>button.addEventListener('click',()=>{
   const event=button.dataset.event;if(!events.has(event))return;
   const payload={event,screen_name:'training_log',event_schema_version:'2',debug_mode:true};
   if(['training_log_start','training_log_create','training_log_error'].includes(event))payload.input_method='manual';
   if(event==='training_log_error')payload.error_code='validation';
   if(event==='menu_navigate')payload.destination_screen='report';
   write({mode:active?'test-container':'local-only',payload});
   if(active)window.dataLayer.push(payload);
 }));
 connect.addEventListener('click',()=>{
   if(!config||active||navigator.globalPrivacyControl===true)return;
   active=true;connect.disabled=true;window.dataLayer=[];
   function consent(){window.dataLayer.push(arguments);}
   consent('consent','default',{analytics_storage:'denied',ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied'});
   consent('consent','update',{analytics_storage:'granted'});
   window.dataLayer.push({safe_page_location:location.origin+'/analytics_test',safe_page_referrer:'',safe_page_title:'SwimMate synthetic analytics test',debug_mode:true});
   window.dataLayer.push({'gtm.start':Date.now(),event:'gtm.js'});
   const script=document.createElement('script');script.async=true;
   script.src='https://www.googletagmanager.com/gtm.js?id='+encodeURIComponent(config.container_id);
   script.onerror=()=>{status.textContent='테스트 태그 다운로드 실패. 차단 설정과 네트워크를 확인하세요.';};
   document.head.append(script);window.dataLayer.push({event:'sm_analytics_ready'});
   status.textContent='테스트 컨테이너 로드 요청됨. 실제 연결·전송 성공은 Tag Assistant에서 확인하세요.';
 });
 document.getElementById('stop').addEventListener('click',()=>{
   if(active){function consent(){window.dataLayer.push(arguments);}consent('consent','update',{analytics_storage:'denied',ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied'});}
   for(const entry of document.cookie.split(';')){const name=entry.split('=')[0].trim();if(name==='_ga'||name.startsWith('_ga_')){document.cookie=name+'=; Max-Age=0; path=/';document.cookie=name+'=; Max-Age=0; path=/; domain='+location.hostname;}}
   location.reload();
 });
 (async()=>{
   if(!['localhost','127.0.0.1'].includes(location.hostname)){status.textContent='이 검증실은 localhost 전용입니다. 운영 주소에서는 Google 태그를 로드하지 않습니다.';return;}
   try{const response=await fetch('/api/analytics/test-config',{credentials:'omit',cache:'no-store'});
     if(!response.ok)throw new Error('config');const data=await response.json();
     if(!data.enabled||!/^GTM-[A-Z0-9]+$/.test(data.container_id)||!/^G-[A-Z0-9]+$/.test(data.measurement_id)||data.container_id==='GTM-5TQRKVQ5'||data.measurement_id==='G-B43M43WPM9')throw new Error('disabled');
     if(navigator.globalPrivacyControl===true){status.textContent='브라우저 개인정보 보호 신호로 테스트 태그 로드를 차단했습니다.';return;}
     config=data;connect.disabled=false;status.textContent='별도 테스트 설정 준비됨: '+data.container_id+' / '+data.measurement_id+' · 아직 Google 요청 없음';
   }catch{status.textContent='로컬 검증 모드: 별도 테스트 GTM·GA4 설정이 없어 Google 태그를 로드하지 않습니다.';}
 })();
})();
