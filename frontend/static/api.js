/**
 * SwimMate — 공통 API fetch 래퍼
 * 모든 페이지에서 반복되던 fetch + 에러 핸들링을 한 곳으로 모은다.
 *
 * 사용 예:
 *   const data = await apiFetch("/api/training-logs");
 *   await apiFetch("/api/training-logs", { method: "POST", body: JSON.stringify(payload) });
 */

/**
 * @param {string} url
 * @param {RequestInit} [options]
 * @param {{ silent?: boolean }} [swOpts]  silent=true 이면 401 시 리다이렉트 안 함
 * @returns {Promise<any>}  JSON 응답 또는 null (204 No Content)
 */
async function apiFetch(url, options = {}, swOpts = {}) {
  const defaults = {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
  };
  const res = await fetch(url, { ...defaults, ...options, headers: { ...defaults.headers, ...(options.headers ?? {}) } });

  if (res.status === 401 && !swOpts.silent) {
    window.location.href = "/login";
    return null;
  }

  if (res.status === 204) return null;

  const text = await res.text();
  let json;
  try { json = text ? JSON.parse(text) : null; } catch { json = null; }

  if (!res.ok) {
    const msg = json?.detail ?? json?.message ?? `오류 ${res.status}`;
    if (window.SW?.showToast) window.SW.showToast(msg, "error");
    throw Object.assign(new Error(msg), { status: res.status, body: json });
  }

  return json;
}

/* ── 전역 노출 ── */
window.apiFetch = apiFetch;
if (window.SW) window.SW.apiFetch = apiFetch;
