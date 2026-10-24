'use strict';
// Deliberately isolated, read-only fixtures. No customer IDs, credentials, API
// writes, backdated database timestamps, notifications or activity metrics.
const DEMO_PROFILES=Object.freeze({a:'물결따라 [QA 데모]',b:'꾸준한자유형 [QA 데모]',c:'턴연습중 [QA 데모]',d:'새벽레인 [QA 데모]'});
const DEMO_POSTS=[
 {id:1,category:'영법 연습',author:'a',date:'2026-09-07 07:30',title:'자유형 호흡할 때 고개가 자꾸 들리는 느낌이에요',body:'오늘 연습을 떠올려 만든 샘플입니다. 옆으로 숨을 쉬려다가 앞을 보는 느낌이 나고, 숨을 쉰 직후 다리가 내려가는 것 같습니다. 속도보다 편안하게 25m를 가는 연습부터 해보려는데 어떤 점을 관찰하면 좋을까요?',comments:[
 ['b','2026-09-07 12:10','저는 빨리 가려고 하기보다 짧은 구간을 편하게 반복하며 호흡 전후 자세를 살펴봤어요. 원인은 사람마다 달라서 강사님께 옆에서 봐달라고 부탁하는 것도 좋겠습니다.'],
 ['a','2026-09-08 08:00','답변 고맙습니다. 다음 수업 때 호흡 순간을 봐달라고 말씀드리고, 전후 느낌을 일지에 남겨볼게요.',0],
 ['d','2026-09-08 18:20','후속 기록에는 거리·휴식·호흡이 편했던 구간을 같이 적으면 비교하기 좋겠네요. 다른 사람의 횟수를 그대로 맞추지는 않아도 될 것 같아요.']]},
 {id:2,category:'훈련 기록',author:'b',date:'2026-09-12 19:10',title:'거리만 쓰던 일지에 휴식과 체감 난도를 추가해봤어요',body:'가상의 훈련 기록 예시입니다. 총거리만 적으면 같은 800m라도 어떻게 수영했는지 기억이 잘 안 나더라고요. 준비운동·주운동·정리운동, 반복 사이 휴식, 체감 난도를 따로 기록하는 형식으로 바꿔보려고 합니다. 여러분은 어떤 항목을 비교하나요?',comments:[
 ['d','2026-09-13 06:50','저는 기록보다 그날 목표를 먼저 적는 형식이 좋아요. 호흡 연습인지 일정한 속도 유지인지 구분하면 다음 일지 읽을 때 도움이 되더라고요.'],
 ['c','2026-09-13 13:10','수영장 길이도 적어두면 좋겠네요. 25m와 50m에서는 턴 횟수가 달라 총거리만으로 비교하기 어려우니까요.'],
 ['b','2026-09-14 20:00','목표와 수영장 길이를 추가한 예시 양식으로 정리해보겠습니다. 서로 다른 환경의 기록은 따로 비교할게요.',1]]},
 {id:3,category:'대회 준비',author:'c',date:'2026-09-20 15:30',title:'첫 50m 대회 영상을 볼 때 어디부터 확인할까요?',body:'50m 대회 영상 리뷰를 가정한 질문입니다. 기록만 보기보다 출발, 첫 출수, 중간 수면 구간, 도착을 나누어 보고 싶습니다. 카메라가 움직이고 다른 레인도 같이 보이는데, 분석할 선수를 놓치지 않으려면 어떤 정보를 먼저 정리하면 좋을까요?',comments:[
 ['a','2026-09-20 17:10','레인과 영법, 수영장 길이를 먼저 적어두면 좋겠습니다. 50m 경기라도 25m 수영장이면 턴이 한 번 있겠네요.'],
 ['b','2026-09-21 08:40','출발 신호와 터치가 영상에 찍혔는지도 확인해보세요. 영상 끝이나 전광판 전환을 도착으로 잡으면 시간이 달라질 수 있겠어요.'],
 ['c','2026-09-21 18:00','좋네요. 팔 동작은 보이는 구간만 확인하고 물속 발차기는 안 보이면 판독 불가로 남기는 샘플 리뷰를 만들겠습니다.',1]]},
 {id:4,category:'수영 생활',author:'d',date:'2026-09-28 06:40',title:'새벽 자유수영 준비물을 잊지 않는 나만의 체크리스트',body:'수영 생활 공유용 샘플입니다. 전날 가방을 챙길 때 수모·수경·수영복·수건·세면도구·물병을 확인하고 있습니다. 시설마다 규정이 달라서 오리발이나 패들 같은 도구는 먼저 사용 가능 여부를 확인하려고 해요. 더 추가할 것이 있을까요?',comments:[
 ['c','2026-09-28 12:30','입장 시간과 레인 운영 공지도 챙기면 좋겠습니다. 강습 시간에는 자유수영 공간이 달라질 수 있으니까요.'],
 ['a','2026-09-29 09:00','수경은 입수 전 상태를 확인하는 습관도 좋겠네요. 렌즈 관리는 제품 안내에 맞추고요.'],
 ['d','2026-09-29 19:20','체크리스트 맨 위에 시설 공지 확인을 추가했습니다. 준비물만이 아니라 이용 규칙도 같이 확인하는 예시로 바꿔둘게요.',0]]},
 {id:5,category:'영법 연습',author:'a',date:'2026-10-05 18:50',title:'평영 스트로크 횟수를 셀 때 기준을 맞추고 싶어요',body:'평영 동작 집계에 관한 샘플 질문입니다. 서로 영상을 보고 세었는데 숫자가 달랐다는 상황을 가정해봤어요. 양팔이 함께 움직이는 한 주기를 같은 지점에서 세고, 출발 후 수중 구간은 별도로 구분하면 비교가 쉬워질까요?',comments:[
 ['c','2026-10-05 20:15','먼저 세는 구간과 동작 기준을 글로 적으면 좋겠어요. 시작과 끝이 다르면 같은 영상도 숫자가 달라질 수 있습니다.'],
 ['b','2026-10-06 07:50','가려진 장면은 억지로 채우지 않고 따로 표시하는 것도 중요하겠네요. 확인 가능한 구간의 횟수와 경기 전체 횟수는 구분하고요.'],
 ['a','2026-10-06 18:10','동일한 주기 지점과 시작·끝을 정하고, 판독 불가 구간을 남기는 방식으로 예시를 정리하겠습니다.',1]]},
 {id:6,category:'훈련 기록',author:'b',date:'2026-10-12 20:20',title:'계획보다 적게 수영한 날도 일지를 남기나요?',body:'꾸준한 기록에 관한 가상 대화입니다. 계획한 거리를 채우지 못하면 일지를 건너뛰는 상황을 가정했습니다. 실제로 한 거리와 쉬었던 이유, 다음에 확인할 점까지 적어두면 결과를 과장하지 않고 흐름을 볼 수 있을 것 같아요.',comments:[
 ['d','2026-10-13 07:00','완주 여부보다 실제로 한 내용을 남기는 방식에 한 표입니다. 컨디션과 휴식을 짧게 적는 칸도 있으면 좋겠어요.'],
 ['c','2026-10-13 12:40','계획과 실제를 나란히 두면 차이가 보이겠네요. 부족한 거리를 다음 날 무조건 몰아서 채우는 목표보다는 코치와 계획을 조정하는 쪽이 좋겠습니다.'],
 ['b','2026-10-14 19:30','계획·실제·메모 세 칸으로 정리했습니다. 기록을 좋게 보이게 고치지 않고, 실제 수행 내용부터 남기는 예시로 사용할게요.',0]]}
];
function node(tag,text,cls){const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;}
function renderDemo(){
 const search=document.getElementById('search').value.trim().toLowerCase();const category=document.getElementById('category').value;
 const posts=DEMO_POSTS.filter(p=>(!category||p.category===category)&&(!search||(p.title+' '+p.body).toLowerCase().includes(search)));
 const root=document.getElementById('posts');root.replaceChildren();
 document.getElementById('count').textContent=`샘플 게시물 ${posts.length}개 · 샘플 댓글 ${posts.reduce((n,p)=>n+p.comments.length,0)}개 · 실제 활동 통계가 아닙니다`;
 for(const p of posts){const article=document.createElement('article');const details=document.createElement('details');details.open=posts.length===1||p.id===6;
 const summary=document.createElement('summary');summary.append(node('span',`데모 · ${p.category}`,'badge'),node('h2',p.title),node('div',`${DEMO_PROFILES[p.author]} · 예시 날짜 ${p.date} · 샘플 댓글 ${p.comments.length}개`,'meta'));details.append(summary,node('div',p.body,'body'));
 const comments=node('section','','comments');comments.setAttribute('aria-label','샘플 댓글 대화');comments.append(node('h3','샘플 댓글 대화'));
 p.comments.forEach(([author,date,text,parent])=>{const comment=node('div','','comment'+(parent!==undefined?' reply':''));comment.append(node('div',`${DEMO_PROFILES[author]} · 예시 날짜 ${date}`,'meta'));if(parent!==undefined)comment.append(node('span',`↳ ${DEMO_PROFILES[p.comments[parent][0]]}에게 답글`,'badge'));comment.append(node('p',text));comments.append(comment);});details.append(comments);article.append(details);root.append(article);}
 if(!posts.length)root.append(node('p','검색에 맞는 샘플 글이 없습니다.'));
}
document.getElementById('search').addEventListener('input',renderDemo);document.getElementById('category').addEventListener('change',renderDemo);renderDemo();
