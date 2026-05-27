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
})();
