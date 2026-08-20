(function () {
  'use strict';
  var STORAGE_KEY = 'swimtech_theme';
  var APP_HEADER_PATHS = [
    '/landing', '/dashboard', '/my-data', '/plan', '/training-log', '/training_log',
    '/workout', '/report', '/pool', '/drill', '/faq', '/glossary',
    '/badges', '/badge', '/changelog', '/community', '/challenge', '/equipment',
    '/feedback', '/chat', '/videos', '/profile', '/injury', '/coach',
    '/clubs', '/tutorial', '/tutorial/personal', '/tutorial/record',
    '/tutorial/data', '/tutorial/coach', '/tutorial/help', '/admin', '/privacy', '/terms', '/onboarding'
  ];
  var SERVICE_NAV_PATHS = [
    '/dashboard', '/my-data', '/plan', '/training-log', '/training_log',
    '/workout', '/report', '/pool', '/drill', '/faq', '/glossary',
    '/badges', '/badge', '/changelog', '/community', '/challenge', '/equipment',
    '/feedback', '/chat', '/videos', '/profile', '/injury', '/coach',
    '/clubs', '/tutorial', '/tutorial/personal', '/tutorial/record',
    '/tutorial/data', '/tutorial/coach', '/tutorial/help'
  ];
  var CONTENT_FRAME_SELECTOR = [
    '.admin-page', '.badge-page', '.ch-page', '.coach-page', '.club-main',
    '.comm-wrap', '.dash-page', '.data-page', '.drill-page', '.eq-page',
    '.plan-page', '.rp-page', '.tl-page', '.vids-page', '.guide-page'
  ].join(', ');

  function currentPath() {
    return window.location.pathname.replace(/\/+$/, '') || '/';
  }

  function isServicePage() {
    return APP_HEADER_PATHS.indexOf(currentPath()) !== -1;
  }

  function markGlobalContentFrame() {
    document.querySelectorAll(CONTENT_FRAME_SELECTOR).forEach(function (element) {
      element.classList.add('global-content-frame');
    });
  }

  // 브라우저 탭과 홈 화면에서 같은 수영 아이콘을 사용한다.
  function ensureSiteIcons() {
    var favicon = document.querySelector('link[rel="icon"]');
    if (!favicon) {
      favicon = document.createElement('link');
      favicon.rel = 'icon';
      document.head.appendChild(favicon);
    }
    favicon.type = 'image/svg+xml';
    favicon.href = '/static/icons/favicon.svg';

    if (!document.querySelector('link[rel="apple-touch-icon"]')) {
      var appleIcon = document.createElement('link');
      appleIcon.rel = 'apple-touch-icon';
      appleIcon.href = '/static/icons/icon-192.png';
      document.head.appendChild(appleIcon);
    }
  }
  ensureSiteIcons();
 
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

  function headerContextLabel() {
    var labels = {
      '/landing': '내 훈련 홈', '/dashboard': '상세 훈련 대시보드', '/my-data': '내 수영 데이터',
      '/plan': '훈련 플랜', '/training-log': '훈련 일지', '/training_log': '훈련 일지',
      '/workout': '풀사이드 훈련', '/report': '월간 성장 리포트', '/pool': '수영장 찾기',
      '/drill': '드릴 가이드', '/faq': '자주 묻는 질문', '/glossary': '수영 용어 사전',
      '/badges': '뱃지 여정', '/badge': '뱃지 여정', '/changelog': '릴리즈 노트',
      '/community': '커뮤니티', '/challenge': '수영 챌린지', '/equipment': '수영 장비 가이드',
      '/feedback': '의견 보내기', '/chat': 'AI 수영 코치', '/videos': '영상 라이브러리',
      '/profile': '프로필·훈련 설정', '/injury': '부상 예방', '/coach': '코치 연동',
      '/clubs': '클럽·반', '/tutorial': '기능 안내', '/tutorial/personal': '개인 훈련 시작',
      '/tutorial/record': '기록·스크린샷', '/tutorial/data': '성장 데이터',
      '/tutorial/coach': '코치·클럽 운영', '/tutorial/help': '수영 정보·도움', '/admin': '관리자 운영 센터',
      '/privacy': '개인정보처리방침', '/terms': '이용약관', '/onboarding': '맞춤 훈련 설정'
    };
    return labels[currentPath()] || '수영 훈련 도우미';
  }

  function logoutFromHeader() {
    var button = document.getElementById('global-app-logout');
    if (button) button.disabled = true;
    fetch('/auth/logout', { method: 'POST', credentials: 'include' })
      .catch(function () {})
      .finally(function () { window.location.href = '/login'; });
  }

  function updateHeaderSession(profile) {
    var profileLink = document.getElementById('global-app-profile');
    var logoutButton = document.getElementById('global-app-logout');
    var loginLink = document.getElementById('global-app-login');
    var authenticated = Boolean(profile);
    if (profileLink) profileLink.hidden = !authenticated;
    if (logoutButton) logoutButton.hidden = !authenticated;
    if (loginLink) loginLink.hidden = authenticated;
  }

  function loadHeaderSession() {
    function requestProfile() {
      return fetch('/auth/me', { credentials: 'include' })
        .then(function (response) {
          if (!response.ok) throw new Error('guest');
          return response.json();
        });
    }
    requestProfile()
      .catch(function () {
        return fetch('/auth/refresh', { method: 'POST', credentials: 'include' })
          .then(function (response) {
            if (!response.ok) throw new Error('guest');
            return requestProfile();
          });
      })
      .then(updateHeaderSession)
      .catch(function () { updateHeaderSession(null); });
  }

  function installGlobalHeader() {
    if (!isServicePage() || document.getElementById('global-app-header')) return;

    var header = document.createElement('header');
    header.id = 'global-app-header';
    header.className = 'global-app-header';
    header.setAttribute('aria-label', 'SwimMate 공통 상단 메뉴');
    header.innerHTML =
      '<div class="global-app-header-left">' +
        '<a class="global-app-home" href="/landing" aria-label="SwimMate 내 훈련 홈으로 이동">' +
          '<img src="/static/icons/favicon.svg" alt=""><span>SwimMate 홈</span>' +
        '</a>' +
        '<span class="global-app-context">' + headerContextLabel() + '</span>' +
      '</div>' +
      '<div class="global-app-header-actions">' +
        '<a id="global-app-profile" class="global-app-action" href="/profile" hidden><span aria-hidden="true">👤</span><span class="global-app-action-label">프로필 수정</span></a>' +
        '<button id="global-app-logout" class="global-app-action" type="button" hidden><span aria-hidden="true">↪</span><span class="global-app-action-label">로그아웃</span></button>' +
        '<a id="global-app-login" class="global-app-action" href="/login" hidden><span aria-hidden="true">👤</span><span class="global-app-action-label">로그인</span></a>' +
        '<button id="theme-toggle-btn" class="theme-btn global-app-theme" type="button" title="다크/라이트 모드 전환" aria-label="테마 변경"></button>' +
      '</div>';

    var anchor = document.body.firstElementChild;
    document.body.insertBefore(header, anchor);
    document.body.classList.add('global-app-header-enabled');
    markGlobalContentFrame();
    var headerLeft = header.querySelector('.global-app-header-left');
    var pageMenu = document.getElementById('menu-toggle') || document.getElementById('admin-menu-toggle');
    var contextualMenu = document.getElementById('sidebar-toggle-btn');
    if (pageMenu) headerLeft.insertBefore(pageMenu, header.querySelector('.global-app-home'));
    if (contextualMenu) headerLeft.insertBefore(contextualMenu, header.querySelector('.global-app-home'));
    var syncHeaderMetrics = function () {
      var rect = header.getBoundingClientRect();
      var height = Math.ceil(rect.height);
      var visibleHeight = Math.max(0, Math.min(height, Math.ceil(rect.bottom)));
      document.documentElement.style.setProperty('--global-app-header-height', height + 'px');
      document.documentElement.style.setProperty('--global-app-header-visible-height', visibleHeight + 'px');
    };
    syncHeaderMetrics();

    var themeButton = document.getElementById('theme-toggle-btn');
    themeButton.textContent = (document.documentElement.getAttribute('data-theme') || 'dark') === 'light' ? '🌙' : '☀️';
    themeButton.addEventListener('click', toggle);
    document.getElementById('global-app-logout').addEventListener('click', logoutFromHeader);

    loadHeaderSession();
    window.addEventListener('resize', syncHeaderMetrics);
    window.addEventListener('scroll', syncHeaderMetrics, { passive: true });
    window.dispatchEvent(new CustomEvent('swimmate:app-header-ready'));
  }
 
  // 저장된 테마 즉시 적용 (FOUC 방지)
  var saved = localStorage.getItem(STORAGE_KEY) || 'dark';
  document.documentElement.setAttribute('data-theme', saved);

  // 랜딩에서 사용하던 서비스 메뉴를 주요 기능 페이지에서도 계속 사용할 수 있게 한다.
  function loadServiceNavigation() {
    var currentPath = window.location.pathname.replace(/\/+$/, '') || '/';
    if (SERVICE_NAV_PATHS.indexOf(currentPath) === -1) return;
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
    document.addEventListener('DOMContentLoaded', function () {
      installGlobalHeader();
      injectButton();
    });
  } else {
    installGlobalHeader();
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
