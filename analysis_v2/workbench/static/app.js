'use strict';
const $ = id => document.getElementById(id);
let token = '', current = null, roi = [0, 0, 1, 1], arm = [], kick = [], history = [], prediction = null;
let selecting = false, dragStart = null, selectedId = null, dirty = false, polling = false;
const video = $('video'), canvas = $('overlay'), ctx = canvas.getContext('2d');
const stateText = {uploaded:'분석 조건을 정해 주세요', queued:'분석 대기 중', running:'PC에서 분석 중', complete:'분석 완료', failed:'분석 실패', interrupted:'실행 중단', cancelled:'분석 취소'};
function message(text) { $('message').textContent = text; $('message').hidden = false; clearTimeout(message.timer); message.timer = setTimeout(() => $('message').hidden = true, 7500); }
async function api(path, options={}) {
  const response = await fetch(path, {...options, headers:{'X-Review-Token':token, ...(options.body && !(options.body instanceof Blob) ? {'Content-Type':'application/json'}:{}), ...options.headers}});
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '입력값을 확인해 주세요.');
  return data;
}
const post = (path, body) => api(path, {method:'POST', body:body === undefined ? undefined : JSON.stringify(body)});
const endpoint = suffix => `/api/videos/${current.id}${suffix}`;
function act(id, fn) { $(id).addEventListener('click', async () => { try { await fn(); } catch(error) { message(error.message); } }); }
function textNode(tag, text, className='') { const node=document.createElement(tag); node.textContent=text; node.className=className; return node; }
async function refreshProjects() {
  const items=await api('/api/videos'); $('projects').replaceChildren();
  for(const item of items) {
    const button=textNode('button','',`project${current?.id===item.id?' selected':''}`);
    button.append(textNode('strong',item.name),textNode('small',`${item.duration.toFixed(1)}초 · ${stateText[item.state]||item.state}`));
    button.onclick=()=>openProject(item.id).catch(error=>message(error.message)); $('projects').append(button);
  }
}
async function openProject(id) {
  if(dirty && !confirm('저장하지 않은 수기 기록이 있습니다. 이동할까요?')) return;
  selectedId=id;
  const data=await api(`/api/videos/${id}`); if(selectedId!==id) return;
  current=data; prediction=null; arm=[]; kick=[]; history=[]; dirty=false;
  $('file').value=''; $('uploadPanel').hidden=true; $('workspace').hidden=false; $('results').hidden=true;
  $('poseToggleWrap').hidden=true; $('poseToggle').checked=false; $('playbackError').hidden=true;
  $('videoName').textContent=data.name; video.src=`/media/${id}`;
  const settings=data.settings;
  roi=settings?.roi||[0,0,1,1]; $('stroke').value=settings?.stroke||'freestyle';
  $('start').value=settings?.start_sec||0; $('end').value=settings?.end_sec??Math.min(60,Math.floor(data.duration*1000)/1000);
  $('distance').value=settings?.distance_m||''; $('rotation').value=settings?.rotation||'clockwise';
  $('annotator').value=''; $('armUnresolvable').checked=false; $('kickUnresolvable').checked=false; $('blindClaim').checked=false;
  $('saveStatus').textContent='';
  const label=await api(`/api/videos/${id}/labels`); if(selectedId!==id) return;
  if(label) {
    arm=label.arm_event_times_sec; kick=label.kick_event_times_sec; $('annotator').value=label.annotator;
    $('armUnresolvable').checked=label.arm_label_status==='unresolvable'; $('kickUnresolvable').checked=label.kick_label_status==='unresolvable';
    $('blindClaim').checked=label.label_mode==='blinded_manual'; $('saveStatus').textContent='저장한 기록을 불러왔습니다.';
  }
  updateState(); renderEvents(); updateRoiLabel(); await refreshProjects();
}
function updateState() {
  if(!current) return;
  const configured=!!current.settings, busy=['running','queued'].includes(current.state);
  const locked=configured && !['failed','cancelled','interrupted'].includes(current.state);
  $('settingsFields').disabled=locked; $('analyzeButton').disabled=locked||current.revealed;
  $('roiButton').disabled=locked; $('resetRoi').disabled=locked;
  $('cancelButton').hidden=!busy; $('saveLabel').disabled=!configured; $('revealButton').disabled=current.state!=='complete';
  $('armButton').disabled=!configured||$('armUnresolvable').checked; $('kickButton').disabled=!configured||$('kickUnresolvable').checked;
  $('mobileArm').disabled=$('armButton').disabled; $('mobileKick').disabled=$('kickButton').disabled;
  $('labelMode').textContent=current.revealed?'모델 확인 후 · 보정용':'모델 답안 숨김';
  if(current.revealed) { $('blindClaim').checked=false; $('blindClaim').disabled=true; } else $('blindClaim').disabled=false;
  $('jobStatus').textContent=(current.error||stateText[current.state]||'')+(current.state==='running'&&current.started_at?` · ${Math.max(0,Math.round(Date.now()/1000-current.started_at))}초 경과`:'');
  $('step1').classList.toggle('active',!configured); $('step2').classList.toggle('active',configured&&!current.revealed); $('step3').classList.toggle('active',current.revealed);
}
async function upload(file) {
  if(!file) return;
  if(file.size>200*1024*1024) throw Error('200MB 이하의 영상을 선택해 주세요.');
  if(dirty&&!confirm('저장하지 않은 수기 기록이 있습니다. 새 영상을 올릴까요?')) return;
  $('uploadProgress').hidden=false; $('uploadProgress').value=0;
  try {
    const data=await new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest(); xhr.open('POST',`/api/videos?filename=${encodeURIComponent(file.name)}`);
      xhr.setRequestHeader('X-Review-Token',token); xhr.setRequestHeader('Content-Type','application/octet-stream');
      xhr.upload.onprogress=e=>{if(e.lengthComputable) { $('uploadProgress').value=e.loaded/e.total*100; if(e.loaded===e.total)message('PC에서 재생용 영상을 준비하고 있습니다. 잠시 기다려 주세요.'); }};
      xhr.onload=()=>{try{const body=JSON.parse(xhr.responseText);xhr.status<300?resolve(body):reject(Error(body.detail||'업로드 실패'));}catch{reject(Error('업로드 응답을 읽지 못했습니다.'));}};
      xhr.onerror=()=>reject(Error('로컬 서버 연결을 확인해 주세요.')); xhr.send(file);
    });
    dirty=false; await openProject(data.id); message('영상이 이 PC에 저장됐습니다. 구간과 선수를 선택하세요.');
  } finally { $('uploadProgress').hidden=true; }
}
$('file').addEventListener('change',()=>upload($('file').files[0]).catch(e=>message(e.message)));
for(const name of ['dragenter','dragover']) $('uploadPanel').addEventListener(name,e=>{e.preventDefault();$('uploadPanel').classList.add('dragging');});
for(const name of ['dragleave','drop']) $('uploadPanel').addEventListener(name,e=>{e.preventDefault();$('uploadPanel').classList.remove('dragging');});
$('uploadPanel').addEventListener('drop',e=>upload(e.dataTransfer.files[0]).catch(error=>message(error.message)));
act('newVideo',()=>{ if(dirty&&!confirm('저장하지 않은 기록을 남겨두고 이동할까요?'))return; video.pause();current=null;selectedId=null;dirty=false;$('workspace').hidden=true;$('uploadPanel').hidden=false;$('step1').classList.add('active');$('step2').classList.remove('active');$('step3').classList.remove('active');refreshProjects(); });
act('helpButton',()=>{$('helpPanel').hidden=!$('helpPanel').hidden;if(!$('helpPanel').hidden)$('helpPanel').scrollIntoView({behavior:'smooth'});});
act('analyzeButton',async()=>{
  const start=Number($('start').value),end=Number($('end').value);
  if(end<=start||end-start>60) throw Error('시작보다 늦은 종료 시각과 60초 이하 구간을 지정하세요.');
  const settings={stroke:$('stroke').value,start_sec:start,end_sec:end,distance_m:$('distance').value?Number($('distance').value):null,roi,rotation:$('rotation').value};
  await post(endpoint('/analyze'),settings); current=await api(endpoint('')); video.currentTime=start; selecting=false;$('stage').classList.remove('selecting');updateState();await refreshProjects();
  message('모델은 백그라운드에서 분석합니다. 답안을 보기 전에 직접 기록해 보세요.');
});
act('cancelButton',async()=>{await post(endpoint('/cancel'));current=await api(endpoint(''));updateState();});
act('deleteButton',async()=>{if(confirm('이 영상과 모델 결과·수기 기록을 이 PC에서 모두 삭제할까요?')){await api(endpoint(''),{method:'DELETE'});video.pause();video.removeAttribute('src');video.load();current=null;selectedId=null;dirty=false;$('workspace').hidden=true;$('uploadPanel').hidden=false;await refreshProjects();}});
act('exportButton',()=>{if(dirty)message('저장하지 않은 수정은 내보내기에 포함되지 않습니다.');const a=document.createElement('a');a.href=endpoint('/export');a.download='swimmate-review.json';a.click();});
function seek(time) { video.pause(); video.currentTime=Math.max(0,Math.min(current?.duration||0,time)); }
act('backFrame',()=>seek(video.currentTime-1/(current?.fps||30))); act('nextFrame',()=>seek(video.currentTime+1/(current?.fps||30)));
act('playButton',()=>video.paused?video.play():video.pause()); $('speed').onchange=()=>video.playbackRate=Number($('speed').value);
video.addEventListener('error',()=>{$('playbackError').hidden=false;});
function mark(type) {
  if(!current?.settings||$(type==='arm'?'armUnresolvable':'kickUnresolvable').checked)return;
  const time=Math.round(video.currentTime*1000)/1000, s=current.settings;
  if(time<s.start_sec||time>=s.end_sec){message('분석 구간 안에서 기록하세요.');return;}
  const list=type==='arm'?arm:kick;if(list.some(t=>Math.abs(t-time)<.04)){message('같은 시점에 이미 기록했습니다.');return;}
  list.push(time);list.sort((a,b)=>a-b);history.push({type,time});dirty=true;renderEvents();
}
act('armButton',()=>mark('arm'));act('kickButton',()=>mark('kick'));
act('mobileArm',()=>mark('arm'));act('mobileKick',()=>mark('kick'));act('mobileUndo',()=>$('undoButton').click());
act('undoButton',()=>{const last=history.pop();if(!last)return;removeEvent(last.type,last.time);});
function removeEvent(type,time){if(type==='arm')arm=arm.filter(t=>t!==time);else kick=kick.filter(t=>t!==time);history=history.filter(x=>x.type!==type||x.time!==time);dirty=true;renderEvents();}
function renderEvents(){
  $('mobileArmCount').textContent=$('armUnresolvable').checked?'—':arm.length;$('mobileKickCount').textContent=$('kickUnresolvable').checked?'—':kick.length;
  $('armCount').textContent=$('armUnresolvable').checked?'—':arm.length;$('kickCount').textContent=$('kickUnresolvable').checked?'—':kick.length;
  $('events').replaceChildren(); const values=[...arm.map(time=>({type:'arm',time})),...kick.map(time=>({type:'kick',time}))].sort((a,b)=>a.time-b.time);
  for(const item of values){const row=textNode('div','','event'),jump=textNode('button',`${item.type==='arm'?'팔':'킥'} ${item.time.toFixed(3)}초`),remove=textNode('button','×','remove');jump.onclick=()=>seek(item.time);remove.setAttribute('aria-label',`${item.time}초 ${item.type==='arm'?'팔':'킥'} 기록 삭제`);remove.onclick=()=>removeEvent(item.type,item.time);row.append(jump,remove);$('events').append(row);}
  if(!values.length)$('events').append(textNode('p',current?.settings?'영상을 보면서 A / K로 동작을 기록하세요.':'분석 조건 확정 후 기록할 수 있습니다.','muted'));
  updateState();
}
for(const type of ['arm','kick']) $(type==='arm'?'armUnresolvable':'kickUnresolvable').onchange=()=>{
  const box=$(type==='arm'?'armUnresolvable':'kickUnresolvable'),list=type==='arm'?arm:kick;
  if(box.checked&&list.length&&!confirm('판독 불가로 바꾸면 해당 동작 기록은 비워집니다. 계속할까요?')){box.checked=false;return;}
  if(box.checked){if(type==='arm')arm=[];else kick=[];history=history.filter(item=>item.type!==type);}dirty=true;renderEvents();
};
for(const id of ['annotator','blindClaim']) $(id).addEventListener('change',()=>dirty=true);
act('saveLabel',async()=>{
  const label=await post(endpoint('/labels'),{annotator:$('annotator').value.trim(),arm_events:arm,kick_events:kick,arm_status:$('armUnresolvable').checked?'unresolvable':'labeled',kick_status:$('kickUnresolvable').checked?'unresolvable':'labeled',never_seen_predictions:$('blindClaim').checked});
  dirty=false;$('saveStatus').textContent=`저장 완료 · ${label.label_mode==='blinded_manual'?'모델 미확인 수기 기록':'모델 확인 가능성이 있는 보정용 기록'}`;message('수기 기록을 저장했습니다.');
  if(current.revealed){prediction=await post(endpoint('/reveal'));renderResults();}
});
act('revealButton',async()=>{
  if(!current.revealed&&!confirm('모델 결과를 열면 이후 기록은 보정용으로 분류됩니다. 수기 기록을 먼저 저장하셨나요?'))return;
  prediction=await post(endpoint('/reveal'));current.revealed=true;updateState();renderResults();$('results').scrollIntoView({behavior:'smooth'});
});
const reasonLabels={arm_evidence_gap:'팔 관절 관측 공백',leg_evidence_gap:'다리 관절 관측 공백',possible_tracking_or_camera_jump:'추적·카메라 급변 의심'};
function renderResults(){
  $('results').hidden=false;$('poseToggleWrap').hidden=false;$('resultCards').replaceChildren();$('candidates').replaceChildren();$('reviewWindows').replaceChildren();
  const track=prediction.result.tracks[0],comparison=prediction.comparison;
  for(const [key,title,field,diagnostic] of [['arm','팔 동작','arm_strokes','merged_arm_candidate_times_sec'],['kick','발차기','kicks','kick_candidate_times_sec']]){
    const measured=track?.[field],times=measured?.available?measured.event_times_sec:track?.diagnostics?.[diagnostic]||[],ref=comparison?.[key];
    const card=textNode('div','','result-card');card.append(textNode('h3',title),textNode('strong',`내 기록 ${ref?.manual_count??'—'} · 모델 ${measured?.available?measured.count:'보류'}`),textNode('p',`관측 후보 ${times.length}개 · ${measured?.available?'미검증 모델 추정치':`전체 횟수 미확정 (${measured?.reason||'선수 미검출'})`}`));
    if(ref?.timing)card.append(textNode('p',`후보 시점 일치 F1 ${(ref.timing.f1*100).toFixed(1)}% · ±0.25초 / 1인 참고 비교`));$('resultCards').append(card);
    for(const time of times){const button=textNode('button',`${title} ${time.toFixed(3)}초`);button.onclick=()=>seek(time);$('candidates').append(button);}
  }
  if(!$('candidates').children.length)$('candidates').append(textNode('p','동작 후보를 찾지 못했습니다. 선수 영역과 영상을 확인해 주세요.'));
  for(const window of prediction.review.windows){const button=textNode('button',`${reasonLabels[window.reason]||window.reason} · ${window.start_sec.toFixed(2)}–${window.end_sec.toFixed(2)}초`);button.onclick=()=>seek(window.start_sec);$('reviewWindows').append(button);}
  if(!prediction.review.windows.length)$('reviewWindows').append(textNode('p','이 검사에서 큰 공백을 찾지 못했습니다. 정확한 횟수가 보장되는 것은 아닙니다.'));
  const metric=prediction.result.distance_metrics[0];$('dpsResult').textContent=`모델 DPS: ${metric?.available?`${metric.dps_m_per_stroke}m/회`:'보류 또는 거리 미입력'}${comparison?.manual_dps?` · 수기 기록 기준: ${comparison.manual_dps}m/회 (사용자 제공 거리·미검증)`:''}. 후보를 전체 횟수나 검증된 정확도로 해석하지 마세요.`;
  draw();
}
function bounds(){const w=canvas.clientWidth,h=canvas.clientHeight,ratio=(video.videoWidth||1)/(video.videoHeight||1);let width=w,height=w/ratio;if(height>h){height=h;width=h*ratio;}return{x:(w-width)/2,y:(h-height)/2,width,height};}
function pointer(event){const box=canvas.getBoundingClientRect(),b=bounds();return[Math.max(0,Math.min(1,(event.clientX-box.left-b.x)/b.width)),Math.max(0,Math.min(1,(event.clientY-box.top-b.y)/b.height))];}
function updateRoiLabel(){$('roiLabel').textContent=roi.join(',')==='0,0,1,1'?'전체 화면 · 다른 인물이 포함되지 않게 선택하세요':`선택 영역: 가로 ${Math.round((roi[2]-roi[0])*100)}% · 세로 ${Math.round((roi[3]-roi[1])*100)}%`;draw();}
act('roiButton',()=>{selecting=!selecting;video.pause();$('stage').classList.toggle('selecting',selecting);message(selecting?'영상 위에서 선수/레인을 드래그하세요.':'영역 선택을 종료했습니다.');});
act('resetRoi',()=>{roi=[0,0,1,1];updateRoiLabel();});
canvas.onpointerdown=e=>{if(!selecting)return;dragStart=pointer(e);canvas.setPointerCapture(e.pointerId);};
canvas.onpointermove=e=>{if(!dragStart)return;const p=pointer(e);roi=[Math.min(p[0],dragStart[0]),Math.min(p[1],dragStart[1]),Math.max(p[0],dragStart[0]),Math.max(p[1],dragStart[1])];draw();};
canvas.onpointerup=()=>{if(!dragStart)return;dragStart=null;selecting=false;$('stage').classList.remove('selecting');updateRoiLabel();};
function draw(){
  if(canvas.width!==canvas.clientWidth)canvas.width=canvas.clientWidth;if(canvas.height!==canvas.clientHeight)canvas.height=canvas.clientHeight;ctx.clearRect(0,0,canvas.width,canvas.height);if(!current||!video.videoWidth)return;
  const b=bounds();ctx.strokeStyle='#63eed1';ctx.lineWidth=2;
  if(!current.settings||selecting){ctx.strokeRect(b.x+roi[0]*b.width,b.y+roi[1]*b.height,(roi[2]-roi[0])*b.width,(roi[3]-roi[1])*b.height);}
  if(!$('poseToggle').checked||!prediction)return;
  const frames=prediction.review.overlays;let lo=0,hi=frames.length-1;while(lo<hi){const mid=Math.floor((lo+hi)/2);if(frames[mid].time<video.currentTime)lo=mid+1;else hi=mid;}
  let frame=frames[lo];if(lo>0&&Math.abs(frames[lo-1].time-video.currentTime)<Math.abs((frame?.time||0)-video.currentTime))frame=frames[lo-1];
  if(!frame||Math.abs(frame.time-video.currentTime)>.1)return;
  const pairs=[[11,12],[11,13],[13,15],[12,14],[14,16],[11,23],[12,24],[23,24],[23,25],[25,27],[24,26],[26,28]];
  for(const pose of frame.poses){for(const [left,right] of pairs){const a=pose.points[left],c=pose.points[right];if(a[3]<.25||c[3]<.25)continue;ctx.beginPath();ctx.moveTo(b.x+a[0]*b.width,b.y+a[1]*b.height);ctx.lineTo(b.x+c[0]*b.width,b.y+c[1]*b.height);ctx.stroke();}for(const index of [0,11,12,13,14,15,16,23,24,25,26,27,28]){const p=pose.points[index];if(p[3]<.25)continue;ctx.fillStyle='#f5bc5e';ctx.beginPath();ctx.arc(b.x+p[0]*b.width,b.y+p[1]*b.height,3,0,Math.PI*2);ctx.fill();}}
}
$('poseToggle').onchange=draw;new ResizeObserver(draw).observe($('stage'));
function animation(){$('currentTime').textContent=`${video.currentTime.toFixed(3)}초`;draw();requestAnimationFrame(animation);}requestAnimationFrame(animation);
document.addEventListener('keydown',e=>{if(!current||['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)||e.target.isContentEditable||e.ctrlKey||e.metaKey||e.altKey||e.repeat)return;const key=e.key.toLowerCase();if(key===' '&&e.target.tagName==='BUTTON')return;if(['a','k',' ','arrowleft','arrowright'].includes(key)){e.preventDefault();if(key==='a')mark('arm');if(key==='k')mark('kick');if(key===' ')video.paused?video.play().catch(error=>message(error.message)):video.pause();if(key==='arrowleft')seek(video.currentTime-1/current.fps);if(key==='arrowright')seek(video.currentTime+1/current.fps);}});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
act('compareReviewers',async()=>{
  const a=$('reviewA').files[0],b=$('reviewB').files[0];if(!a||!b)throw Error('두 기록 파일을 선택해 주세요.');if(a.size+b.size>1024*1024)throw Error('라벨 파일이 너무 큽니다.');
  const extract=async file=>{const data=JSON.parse(await file.text());return data.blind_label||data.label||data;};
  const report=await post('/api/adjudicate',{first:await extract(a),second:await extract(b)});
  $('agreement').textContent=`독립 기록 합의: ${report.comparison?.verified_independent_consensus?'완료':'미완료 / 상세 확인'}\n`+JSON.stringify(report,null,2);
});
setInterval(async()=>{if(!current||polling)return;const id=current.id;polling=true;try{const data=await api(`/api/videos/${id}`);if(current?.id!==id)return;const changed=current.state!==data.state;current=data;updateState();if(changed)await refreshProjects();}catch(e){message(e.message);}finally{polling=false;}},2500);
(async()=>{try{token=(await api('/api/session')).token;await refreshProjects();}catch(error){message(error.message);}})();
