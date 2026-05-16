// 페이지 로드 시 세션 확인
(async () => {
  try {
    const res = await fetch('/auth/me', { credentials: 'include' });
    if (!res.ok) window.location.href = '/login';
  } catch {
    window.location.href = '/login';
  }
})();

// 로그아웃
async function logout() {
  await fetch('/auth/logout', { method: 'POST', credentials: 'include' });
  window.location.href = '/login';
}

"use strict";

const API_BASE = window.location.origin;  // 현재 접속 호스트 자동 사용

// ── 상태 ──────────────────────────────────────────────
const state = {
  file: null,
  localPath: null,
  frameData: [],
  sse: null,
  kickCount: 0,
  analyzing: false,
  // 메타 정보
  selectedStroke: null,
  selectedContext: null,
  selectedPurpose: null,
};

// 영법/촬영환경 한글 매핑
const STROKE_KO = {
  freestyle: '자유형', backstroke: '배영',
  breaststroke: '평영', butterfly: '접영', unknown: '미선택'
};
const PURPOSE_KO = {
  record:      '🏅 기록 단축',
  health:      '💪 건강하게 오래',
  technique:   '🎯 영법 교정',
  competition: '🏆 대회 준비',
  hobby:       '😊 취미/건강유지',
};

const CONTEXT_KO = {
  free_swim: '자유수영', lesson: '강습 후',
  competition: '대회', training: '훈련', drill: '드릴 연습'
};

// ← 영법 선택으로 돌아가기
function backToMeta() {
  document.getElementById('dropzone').style.display   = 'none';
  document.getElementById('meta-panel').style.display = 'flex';

  // 선택 상태 초기화
  state.selectedStroke  = null;
  state.selectedContext = null;
  state.selectedPurpose = null;

  // 버튼 선택 해제
  document.querySelectorAll('.meta-btn').forEach(b => b.classList.remove('selected'));
  document.getElementById('meta-next-btn').disabled = true;

  // 파일 input 초기화
  const fi = document.getElementById('file-input');
  if (fi) fi.value = '';
  const sf = document.getElementById('selected-file');
  if (sf) sf.style.display = 'none';
}

// ✕ 영상 제거 → 업로드 화면으로
function removeVideo() {
  // 분석 중이면 중단
  if (state.sse) { state.sse.close(); state.sse = null; }
  state.file      = null;
  state.localPath = null;
  state.analyzing = false;

  // 비디오 초기화
  video.src = '';
  video.load();

  // 파일 input 초기화
  const fi = document.getElementById('file-input');
  if (fi) fi.value = '';
  const sf = document.getElementById('selected-file');
  if (sf) sf.style.display = 'none';

  // 플레이어 숨기고 드롭존 표시
  playerWrap.style.display = 'none';
  document.getElementById('dropzone').style.display = 'flex';

  // 우측 수치 초기화
  resetPanel();
  setStatus('idle', '대기 중');
  analyzeBtn.disabled = true;
}

// 우측 패널 수치 초기화
function resetPanel() {
  ['score-val','m-sym','m-kick','m-freq','m-head'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '--';
  });
  ['score-bar','b-sym','b-kick','b-freq','b-head'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.width = '0%';
  });
  const fb = document.getElementById('feedback-card');
  if (fb) fb.style.display = 'none';
  const dc = document.getElementById('drill-card');
  if (dc) dc.style.display = 'none';
  document.getElementById('analysis-bar').style.width = '0%';
  document.getElementById('progress-pct').textContent = '0%';
}

// 메타 버튼 선택
function selectMeta(type, btn) {
  // 같은 그룹 버튼 선택 해제
  const groupId = type === 'stroke' ? 'stroke-options' : 'context-options';
  document.querySelectorAll(`#${groupId} .meta-btn`).forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');

  if (type === 'stroke')  state.selectedStroke  = btn.dataset.value;
  if (type === 'context') state.selectedContext = btn.dataset.value;
  if (type === 'purpose') state.selectedPurpose = btn.dataset.value;

  // 세 가지 다 선택됐으면 다음 버튼 활성화
  const nextBtn = document.getElementById('meta-next-btn');
  if (state.selectedStroke && state.selectedContext && state.selectedPurpose) {
    nextBtn.disabled = false;
  }
}

// 메타 선택 완료 → 업로드 단계로
function proceedToUpload() {
  if (!state.selectedStroke || !state.selectedContext || !state.selectedPurpose) return;
  document.getElementById('meta-panel').style.display = 'none';
  document.getElementById('dropzone').style.display   = 'flex';
  // 드롭존 표시 후 input 이벤트 재바인딩
  setTimeout(bindFileInput, 100);

  // 사이드에 선택 정보 표시
  const card = document.getElementById('meta-info-card');
  if (card) {
    card.innerHTML = `
      <div class="meta-info-item">영법 <span>${STROKE_KO[state.selectedStroke]}</span></div>
      <div class="meta-info-item">환경 <span>${CONTEXT_KO[state.selectedContext]}</span></div>
      <div class="meta-info-item">목적 <span>${PURPOSE_KO[state.selectedPurpose]}</span></div>
    `;
    card.style.display = 'flex';
  }
}

// ── DOM refs ──────────────────────────────────────────
const video       = document.getElementById("video");
const canvas      = document.getElementById("overlay-canvas");
const ctx         = canvas.getContext("2d");
const dropzone    = document.getElementById("dropzone");
const fileInput   = document.getElementById("file-input");
const playerWrap  = document.getElementById("player-wrap");
const analyzeBtn  = document.getElementById("analyze-btn");

// ── 스켈레톤 연결 정의 (랜드마크 인덱스 쌍) ──────────
const CONNECTIONS = [
  [11,13],[13,15],   // 왼팔
  [12,14],[14,16],   // 오른팔
  [11,12],           // 어깨
  [23,24],           // 골반
  [11,23],[12,24],   // 몸통
  [23,27],[24,28],   // 다리
];
const KEY_PTS = [11,12,13,14,15,16,23,24,27,28,0];

// ── 파일 선택 ─────────────────────────────────────────
// label로 감싼 input은 change 이벤트로 처리
function bindFileInput() {
  const fi = document.getElementById("file-input");
  if (!fi) return;
  // 중복 바인딩 방지
  fi.onchange = (e) => {
    const file = e.target.files[0];
    if (file) loadFile(file);
  };
}
bindFileInput();

// 드래그&드롭
dropzone.addEventListener("dragover", e => {
  e.preventDefault();
  dropzone.classList.add("drag-over");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag-over"));
dropzone.addEventListener("drop", e => {
  e.preventDefault();
  dropzone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) loadFile(file);
});

// proceedToUpload 후 새로 생성된 input에도 이벤트 바인딩
const _origProceed = typeof proceedToUpload === "function" ? proceedToUpload : null;

function loadFile(file) {
  state.file = file;
  state.localPath = null;

  const filename = file.name;
  state.localPath = `/app/video/${filename}`;

  // 선택된 파일 정보 표시
  const selectedFileEl = document.getElementById('selected-file');
  const fileNameLabel  = document.getElementById('file-name-label');
  const fileSizeLabel  = document.getElementById('file-size-label');
  if (selectedFileEl) {
    const sizeMB = (file.size / 1024 / 1024).toFixed(1);
    fileNameLabel.textContent = filename;
    fileSizeLabel.textContent = sizeMB + ' MB';
    selectedFileEl.style.display = 'flex';
  }

  // 비디오 미리보기용 blob URL
  video.src = URL.createObjectURL(file);
  video.load();

  // 파일 선택 후 1초 뒤 플레이어로 전환 (파일명 확인할 수 있도록)
  setTimeout(() => {
    dropzone.style.display = "none";
    playerWrap.style.display = "flex";
    playerWrap.style.flexDirection = "column";
  }, 800);

  setStatus("ready", "영상 로드 완료 — " + filename);
  analyzeBtn.disabled = false;
}

// C:\swimideo 폴더 열기 (API 경유)
async function openVideoFolder() {
  try {
    const res = await fetch('/api/open-folder', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: 'C:\\swim\\video' })
    });
    if (!res.ok) {
      // API가 없으면 파일 선택 다이얼로그 열기
      document.getElementById('file-input').click();
    }
  } catch {
    document.getElementById('file-input').click();
  }
}

// ── 재생 컨트롤 ───────────────────────────────────────
function togglePlay() {
  if (video.paused) video.play();
  else video.pause();
}

video.addEventListener("play",  () => document.getElementById("play-btn").textContent = "⏸");
video.addEventListener("pause", () => document.getElementById("play-btn").textContent = "▶");

video.addEventListener("timeupdate", () => {
  const cur = video.currentTime, dur = video.duration || 1;
  document.getElementById("progress-fill").style.width = (cur / dur * 100).toFixed(1) + "%";
  document.getElementById("time-display").textContent =
    fmtTime(cur) + " / " + fmtTime(dur);
  document.getElementById("ov-time").textContent = fmtTime(cur);

  // 현재 재생 시간에 맞는 캐시된 프레임 데이터로 오버레이 갱신
  updateOverlayFromCache(cur);
});

video.addEventListener("loadedmetadata", () => {
  canvas.width  = video.videoWidth;
  canvas.height = video.videoHeight;
});

function seekVideo(e) {
  const bar  = document.getElementById("progress-bar");
  const rect = bar.getBoundingClientRect();
  const pct  = (e.clientX - rect.left) / rect.width;
  video.currentTime = pct * video.duration;
}

// ── 분석 시작 ─────────────────────────────────────────
function startAnalysis() {
  if (state.analyzing) return;
  if (!state.localPath) { alert("영상을 먼저 선택해주세요."); return; }

  state.analyzing = true;
  state.frameData = [];
  state.kickCount = 0;

  analyzeBtn.textContent = "⏳ 분석 중...";
  analyzeBtn.classList.add("running");
  analyzeBtn.disabled = true;

  document.getElementById("feedback-card").style.display = "none";
  document.getElementById("drill-card").style.display    = "none";
  setStatus("running", "분석 중...");

  // 선택한 영법을 API에 전달 (강제 지정)
  const url = `${API_BASE}/stream/analyze?local_path=${encodeURIComponent(state.localPath)}&forced_stroke=${state.selectedStroke}&context=${state.selectedContext}&purpose=${state.selectedPurpose}`;

  // 영법 뱃지 바로 표시
  const sb = document.getElementById('stroke-badge');
  sb.textContent = `${STROKE_KO[state.selectedStroke]} · ${PURPOSE_KO[state.selectedPurpose]}`;
  sb.style.display = 'block';
  const evtSrc = new EventSource(url);
  state.sse = evtSrc;

  evtSrc.onmessage = e => {
    const d = JSON.parse(e.data);

    if (d.type === "meta") {
      console.log("[SwimTech] 분석 시작 — 총", d.total_frames, "프레임, ", d.duration, "초");
    }

    else if (d.type === "frame") {
      state.frameData.push(d);   // 캐시에 저장
      updateLivePanel(d);
    }

    else if (d.type === "done") {
      finishAnalysis(d);
      evtSrc.close();
    }

    else if (d.type === "error") {
      console.error("[SwimTech] 분석 오류:", d.message);
      alert("분석 오류: " + d.message);
      resetAnalyzeBtn();
      evtSrc.close();
    }
  };

  evtSrc.onerror = () => {
    alert("서버 연결 오류\nFastAPI 서버가 실행 중인지 확인해주세요.\n" + API_BASE);
    resetAnalyzeBtn();
    evtSrc.close();
  };

  // 영상 자동 재생
  video.play();
}

// ── 프레임 데이터 → 실시간 패널 업데이트 ─────────────
function updateLivePanel(d) {
  // 진행률
  const pct = d.progress || 0;
  document.getElementById("analysis-bar").style.width = pct + "%";
  document.getElementById("progress-pct").textContent = Math.round(pct) + "%";

  if (!d.landmarks_visible) return;

  // 팔꿈치 각도
  setOvVal("ov-le",   d.left_elbow_angle,  "°", 80, 120);
  setOvVal("ov-re",   d.right_elbow_angle, "°", 80, 120);
  setOvVal("ov-head", d.head_angle,        "°", 155, 180);

  // 발차기
  if (d.kick_detected) {
    state.kickCount = d.kick_count;
    const kb = document.getElementById("kick-badge");
    kb.classList.add("show");
    setTimeout(() => kb.classList.remove("show"), 300);
    document.getElementById("m-kick").textContent = state.kickCount;
    document.getElementById("b-kick").style.width = Math.min(100, state.kickCount * 3) + "%";
  }

  // 대칭 점수 실시간
  if (d.left_elbow_angle && d.right_elbow_angle) {
    const diff = Math.abs(d.left_elbow_angle - d.right_elbow_angle);
    const sym  = Math.max(0, 100 - diff * 2);
    document.getElementById("m-sym").textContent = sym.toFixed(1);
    document.getElementById("b-sym").style.width = sym + "%";
  }
}

// ── 캐시된 프레임 데이터로 영상 재생 시 오버레이 동기화 ──
function updateOverlayFromCache(currentTime) {
  if (!state.frameData.length) return;
  const target = state.frameData.find(f => Math.abs(f.timestamp - currentTime) < 0.12);
  if (!target || !target.landmarks_visible) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  drawSkeleton(target.skeleton);
  setOvVal("ov-le",   target.left_elbow_angle,  "°", 80, 120);
  setOvVal("ov-re",   target.right_elbow_angle, "°", 80, 120);
  setOvVal("ov-head", target.head_angle,        "°", 155, 180);
}

// ── Canvas 스켈레톤 그리기 ────────────────────────────
function drawSkeleton(skeleton) {
  if (!skeleton) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const W = canvas.width, H = canvas.height;

  // 연결선
  ctx.strokeStyle = "rgba(0,255,100,0.7)";
  ctx.lineWidth = 2;
  for (const [a, b] of CONNECTIONS) {
    const pa = skeleton[a], pb = skeleton[b];
    if (!pa || !pb) continue;
    ctx.beginPath();
    ctx.moveTo(pa.x * W, pa.y * H);
    ctx.lineTo(pb.x * W, pb.y * H);
    ctx.stroke();
  }

  // 관절 점
  for (const idx of KEY_PTS) {
    const p = skeleton[idx];
    if (!p) continue;
    ctx.beginPath();
    ctx.arc(p.x * W, p.y * H, 5, 0, Math.PI * 2);
    ctx.fillStyle = "#3b82f6";
    ctx.fill();
  }
}

// ── 분석 완료 처리 ────────────────────────────────────
function finishAnalysis(d) {
  state.analyzing = false;
  setStatus("done", "분석 완료");

  // 영법 뱃지
  const strokeNames = {
    freestyle: "자유형", backstroke: "배영",
    breaststroke: "평영", butterfly: "접영", unknown: "미확인"
  };
  const sb = document.getElementById("stroke-badge");
  sb.textContent = `${strokeNames[d.stroke_type] || d.stroke_type} · 신뢰도 ${Math.round(d.confidence)}%`;
  sb.style.display = "block";

  // 종합 점수
  const sym  = d.arm_symmetry_score  || 0;
  const head = d.head_rotation_score || 0;
  const freq = Math.min(100, (d.kick_frequency_hz || 0) * 20);
  const score = Math.round(sym * 0.4 + head * 0.3 + freq * 0.3);

  document.getElementById("score-val").textContent = score;
  document.getElementById("score-bar").style.width = score + "%";
  document.getElementById("m-head").textContent    = head.toFixed(1);
  document.getElementById("b-head").style.width    = head + "%";
  document.getElementById("m-freq").textContent    = (d.kick_frequency_hz || 0).toFixed(2) + "/s";
  document.getElementById("b-freq").style.width    = Math.min(100, (d.kick_frequency_hz || 0) * 33) + "%";

  // ── 강점 표시 ✅ ──────────────────────────────────
  const feedbackCard = document.getElementById("feedback-card");
  const feedbackBody = document.getElementById("feedback-body");
  feedbackBody.innerHTML = "";

  if (d.strengths && d.strengths.length) {
    const strengthTitle = document.createElement("div");
    strengthTitle.className = "feedback-section-title strength";
    strengthTitle.textContent = "✅ 강점";
    feedbackBody.appendChild(strengthTitle);

    d.strengths.forEach(s => {
      const item = document.createElement("div");
      item.className = "feedback-item strength-item";
      item.innerHTML = `
        <div class="fb-header">
          <span class="fb-item-name">${s.item}</span>
          <span class="fb-value good">${s.value}</span>
          <span class="fb-ideal">이상: ${s.ideal}</span>
        </div>
        <div class="fb-comment">${s.comment}</div>
        ${s.reason ? `<div class="fb-reason">💡 ${s.reason}</div>` : ""}
      `;
      feedbackBody.appendChild(item);
    });
  }

  // ── 개선점 표시 ⚠️ ─────────────────────────────────
  if (d.improvements && d.improvements.length) {
    const impTitle = document.createElement("div");
    impTitle.className = "feedback-section-title improvement";
    impTitle.textContent = "⚠️ 개선점";
    feedbackBody.appendChild(impTitle);

    d.improvements.forEach(imp => {
      const item = document.createElement("div");
      item.className = "feedback-item improvement-item";
      item.innerHTML = `
        <div class="fb-header">
          <span class="fb-item-name">${imp.item}</span>
          <span class="fb-value warn">${imp.value}</span>
          <span class="fb-ideal">이상: ${imp.ideal}</span>
        </div>
        <div class="fb-comment">${imp.comment}</div>
        ${imp.worst_moment ? `<div class="fb-moment">📍 ${imp.worst_moment}</div>` : ""}
        ${imp.reason ? `<div class="fb-reason">💡 ${imp.reason}</div>` : ""}
      `;
      feedbackBody.appendChild(item);
    });
  }

  // 기존 feedback 텍스트 fallback
  if (!d.strengths && !d.improvements && d.feedback) {
    feedbackBody.textContent = d.feedback;
  }

  feedbackCard.style.display = "block";

  // ── 드릴 추천 ─────────────────────────────────────
  if (d.drills && d.drills.length) {
    const list = document.getElementById("drill-list");
    list.innerHTML = "";
    const drills = typeof d.drills === "string"
      ? d.drills.replace(/[\[\]']/g, "").split(",").map(s => s.trim())
      : d.drills;
    drills.forEach(drill => {
      const li = document.createElement("li");
      li.textContent = drill;
      list.appendChild(li);
    });
    document.getElementById("drill-card").style.display = "block";
  }

  document.getElementById("analysis-bar").style.width  = "100%";
  document.getElementById("progress-pct").textContent  = "100%";
  resetAnalyzeBtn();
}

// ── 유틸 ─────────────────────────────────────────────
function setOvVal(id, val, unit, min, max) {
  if (val == null) return;
  const el  = document.getElementById(id);
  el.textContent = val.toFixed(1) + unit;
  el.className = "ov-val " + (val >= min && val <= max ? "good" : "warn");
}

function fmtTime(sec) {
  if (!sec || isNaN(sec)) return "0:00";
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return m + ":" + String(s).padStart(2, "0");
}

function setStatus(type, label) {
  const dot = document.getElementById("status-dot");
  dot.className = "status-dot " + type;
  document.getElementById("status-label").textContent = label;
}

function resetAnalyzeBtn() {
  state.analyzing = false;
  analyzeBtn.textContent = "▶ 분석 시작";
  analyzeBtn.classList.remove("running");
  analyzeBtn.disabled = false;
}

function resetAll() {
  if (state.sse) { state.sse.close(); state.sse = null; }
  video.pause();
  video.src = "";
  state.file = null;
  state.localPath = null;
  state.frameData = [];
  state.kickCount = 0;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  dropzone.style.display  = "flex";
  playerWrap.style.display = "none";
  document.getElementById("feedback-card").style.display = "none";
  document.getElementById("drill-card").style.display    = "none";
  document.getElementById("stroke-badge").style.display  = "none";
  document.getElementById("score-val").textContent = "--";
  document.getElementById("score-bar").style.width = "0%";
  document.getElementById("analysis-bar").style.width = "0%";
  document.getElementById("progress-pct").textContent = "0%";
  setStatus("", "대기 중");
  resetAnalyzeBtn();
}
