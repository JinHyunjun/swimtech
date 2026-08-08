(function () {
  'use strict';
  var STORAGE_KEY = 'swimtech_theme';
 
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(STORAGE_KEY, theme);
    var btn = document.getElementById('theme-toggle-btn');
    if (btn) btn.textContent = theme === 'light' ? '🌙' : '☀️';
  }
 
  function toggle() {
    var current = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
  }
 
  // 저장된 테마 즉시 적용 (FOUC 방지)
  var saved = localStorage.getItem(STORAGE_KEY) || 'dark';
  document.documentElement.setAttribute('data-theme', saved);

  // 랜딩에서 사용하던 서비스 메뉴를 주요 기능 페이지에서도 계속 사용할 수 있게 한다.
  function loadServiceNavigation() {
    var servicePaths = [
      '/dashboard', '/my-data', '/plan', '/training-log', '/training_log',
      '/workout', '/report', '/pool', '/drill', '/faq', '/glossary',
      '/badges', '/badge', '/changelog', '/community', '/challenge', '/equipment',
      '/feedback', '/chat', '/videos', '/profile', '/injury', '/coach',
      '/clubs', '/tutorial', '/tutorial/personal', '/tutorial/record',
      '/tutorial/data', '/tutorial/coach', '/tutorial/help'
    ];
    var currentPath = window.location.pathname.replace(/\/+$/, '') || '/';
    if (servicePaths.indexOf(currentPath) === -1) return;
    if (document.querySelector('script[data-service-navigation]')) return;
    var script = document.createElement('script');
    script.src = '/static/service-nav.js';
    script.dataset.serviceNavigation = 'true';
    document.head.appendChild(script);
  }
  loadServiceNavigation();
 
  function injectButton() {
    if (document.getElementById('theme-toggle-btn')) return;
    var header = document.querySelector('.header');
    if (!header) return;
 
    var btn = document.createElement('button');
    btn.id = 'theme-toggle-btn';
    btn.className = 'theme-btn';
    btn.title = '다크/라이트 모드 전환';
    btn.textContent = saved === 'light' ? '🌙' : '☀️';
    btn.addEventListener('click', toggle);
 
    var headerRight = header.querySelector('.header-right');
    if (headerRight) {
      headerRight.insertBefore(btn, headerRight.firstChild);
    } else {
      var headerLeft = header.querySelector('.header-left');
      if (headerLeft) {
        headerLeft.after(btn);
      } else {
        header.appendChild(btn);
      }
    }
  }
 
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectButton);
  } else {
    injectButton();
  }
 
  // 메뉴 사용 분석: 페이지 방문을 백엔드에 기록 (실패해도 화면에 영향 없음)
  try {
    var trackPath = encodeURIComponent(window.location.pathname);
    fetch('/api/admin/track?page=' + trackPath, {
      method: 'POST',
      credentials: 'include',
    }).catch(function () {});
  } catch (e) {}

  // 자동 로그인: refresh token이 유효하면 조용히 access token을 갱신 (실패해도 화면에 영향 없음)
  try {
    fetch('/auth/refresh', {
      method: 'POST',
      credentials: 'include',
    }).catch(function () {});
  } catch (e) {}
})();
