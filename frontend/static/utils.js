/**
 * SwimMate — 프론트엔드 공통 유틸리티
 * 모든 HTML 페이지에서 공유하는 순수 함수 모음.
 * theme.js 다음, 각 페이지 인라인 스크립트 이전에 로드한다.
 */

/* ── HTML 이스케이프 ─────────────────────────────────────── */
function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/* ── 상대 시간 포맷 ──────────────────────────────────────── */
function fmtDate(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60)   return "방금 전";
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}일 전`;
  return new Date(iso).toLocaleDateString("ko-KR");
}

/* ── 날짜 포맷 (YYYY-MM-DD → M월 D일) ───────────────────── */
function fmtShortDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}

/* ── 숫자 단위 포맷 (1200 → 1.2km) ─────────────────────── */
function fmtDist(meters) {
  if (!meters) return "0m";
  return meters >= 1000
    ? `${(meters / 1000).toFixed(1)}km`
    : `${meters}m`;
}

/* ── 인증 체크 (미로그인 시 /login 이동) ─────────────────── */
function requireAuth() {
  const token = document.cookie.split(";").find(c => c.trim().startsWith("swimtech_token="));
  if (!token) {
    window.location.href = "/login";
    return false;
  }
  return true;
}

/* ── 로그인 여부만 반환 (리다이렉트 없음) ───────────────── */
function isLoggedIn() {
  return document.cookie.split(";").some(c => c.trim().startsWith("swimtech_token="));
}

/* ── 토스트 알림 ────────────────────────────────────────── */
function showToast(msg, type = "info", duration = 2800) {
  let container = document.getElementById("sw-toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "sw-toast-container";
    container.style.cssText =
      "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);" +
      "display:flex;flex-direction:column;gap:8px;z-index:9999;pointer-events:none;";
    document.body.appendChild(container);
  }
  const colors = { info: "var(--blue)", success: "#22c55e", error: "#ef4444", warn: "#f59e0b" };
  const toast = document.createElement("div");
  toast.textContent = msg;
  toast.style.cssText =
    `background:${colors[type] ?? colors.info};color:#fff;padding:10px 20px;` +
    "border-radius:var(--radius-md,8px);font-size:14px;box-shadow:0 4px 12px rgba(0,0,0,.18);" +
    "opacity:0;transition:opacity .25s;pointer-events:none;white-space:nowrap;";
  container.appendChild(toast);
  requestAnimationFrame(() => { toast.style.opacity = "1"; });
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 260);
  }, duration);
}

/* ── 모달 외부 클릭 닫기 헬퍼 ──────────────────────────── */
function onOutsideClick(modalEl, closeFn) {
  modalEl.addEventListener("click", e => { if (e.target === modalEl) closeFn(); });
}

/* ── 탭 전환 헬퍼 ───────────────────────────────────────── */
/**
 * @param {string} tabBarSelector   탭 버튼을 담은 컨테이너 CSS 선택자
 * @param {string} contentSelector  탭 콘텐츠 CSS 선택자 (data-tab 속성 기준)
 * @param {function} [onChange]     탭 전환 시 콜백 (tabKey: string)
 */
function initTabs(tabBarSelector, contentSelector, onChange) {
  const bar = document.querySelector(tabBarSelector);
  if (!bar) return;
  bar.querySelectorAll("[data-tab]").forEach(btn => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.tab;
      bar.querySelectorAll("[data-tab]").forEach(b => b.classList.toggle("active", b === btn));
      document.querySelectorAll(contentSelector).forEach(el => {
        el.classList.toggle("active", el.dataset.tab === key);
      });
      if (onChange) onChange(key);
    });
  });
}

/* ── 전역 노출 ──────────────────────────────────────────── */
window.SW = { esc, fmtDate, fmtShortDate, fmtDist, requireAuth, isLoggedIn, showToast, onOutsideClick, initTabs };
