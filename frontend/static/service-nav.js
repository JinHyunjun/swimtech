(function () {
  'use strict';

  var NAV_ID = 'global-service-nav';
  var MOBILE_QUERY = window.matchMedia('(max-width: 900px)');
  var PATH_ALIASES = {
    '/badge': '/badges',
    '/training_log': '/training-log'
  };

  var groups = [
    {
      title: '홈',
      items: [
        { href: '/landing', label: '내 훈련 홈', icon: '🏠' },
        { href: '/dashboard', label: '상세 훈련 대시보드', icon: '📊' }
      ]
    },
    {
      title: '기록과 훈련',
      items: [
        { href: '/training-log', label: '훈련 일지', icon: '📝' },
        { href: '/plan', label: '훈련 플랜', icon: '🗓' },
        { href: '/workout', label: '풀사이드 훈련', icon: '⏱' },
        { href: '/report', label: '월간 성장 리포트', icon: '📈' },
        { href: '/my-data', label: '내 수영 데이터', icon: '📊' },
        { href: '/badges', label: '뱃지 여정', icon: '🏅' }
      ]
    },
    {
      title: '코칭과 함께',
      items: [
        { href: '/chat', label: 'AI 수영 코치', icon: '🤖' },
        { href: '/coach', label: '코치 연동', icon: '🧑‍🏫' },
        { href: '/clubs', label: '클럽·반', icon: '🏊' },
        { href: '/challenge', label: '수영 챌린지', icon: '🔥' },
        { href: '/community', label: '커뮤니티', icon: '💬' }
      ]
    },
    {
      title: '탐색과 도움',
      items: [
        { href: '/pool', label: '수영장 찾기', icon: '📍' },
        { href: '/drill', label: '드릴 가이드', icon: '🏊' },
        { href: '/injury', label: '부상 예방', icon: '🛡' },
        { href: '/equipment', label: '수영 장비 가이드', icon: '🥽' },
        { href: '/equipment?tab=swimwear', label: '수영복 구매·사이즈', icon: '🩱', matchQuery: 'swimwear' },
        { href: '/videos', label: '영상 라이브러리', icon: '🎬' },
        { href: '/glossary', label: '수영 용어 사전', icon: '📖' },
        { href: '/faq', label: '자주 묻는 질문', icon: '❓' },
        { href: '/tutorial', label: '기능 안내', icon: '🧭' }
      ]
    }
  ];

  var footerItems = [
    { href: '/profile', label: '프로필', icon: '👤' },
    { href: '/changelog', label: '릴리즈 노트', icon: '📣' },
    { href: '/feedback', label: '의견 보내기', icon: '✉️' },
    { href: '/admin', label: '관리자', icon: '⚙️', adminOnly: true }
  ];

  function canonicalPath(path) {
    var normalized = (path || '/').replace(/\/+$/, '') || '/';
    return PATH_ALIASES[normalized] || normalized;
  }

  function isActive(item) {
    var currentPath = canonicalPath(window.location.pathname);
    var itemUrl = new URL(item.href, window.location.origin);
    var itemPath = canonicalPath(itemUrl.pathname);
    var tutorialDetail = itemPath === '/tutorial' && currentPath.indexOf('/tutorial/') === 0;
    if (itemPath !== currentPath && !tutorialDetail) return false;
    var currentTab = new URLSearchParams(window.location.search).get('tab');
    if (item.matchQuery) return currentTab === item.matchQuery;
    if (currentPath === '/equipment') return currentTab !== 'swimwear';
    return true;
  }

  function makeLink(item) {
    var link = document.createElement('a');
    link.className = 'global-service-nav-link';
    link.href = item.href;
    link.dataset.route = canonicalPath(new URL(item.href, window.location.origin).pathname);
    if (item.adminOnly) {
      link.id = 'global-service-nav-admin';
      link.hidden = true;
    }
    if (isActive(item)) {
      link.classList.add('active');
      link.setAttribute('aria-current', 'page');
    }

    var icon = document.createElement('span');
    icon.className = 'global-service-nav-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = item.icon;
    var label = document.createElement('span');
    label.textContent = item.label;
    link.append(icon, label);
    return link;
  }

  function makeGroup(group) {
    var section = document.createElement('section');
    section.className = 'global-service-nav-group';
    var title = document.createElement('h2');
    title.className = 'global-service-nav-group-title';
    title.textContent = group.title;
    var links = document.createElement('div');
    links.className = 'global-service-nav-links';
    group.items.forEach(function (item) { links.appendChild(makeLink(item)); });
    section.append(title, links);
    return section;
  }

  function makeToggle() {
    var button = document.createElement('button');
    button.type = 'button';
    button.id = 'global-service-nav-toggle';
    button.className = 'global-service-nav-toggle';
    button.setAttribute('aria-controls', NAV_ID);
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-label', '전체 서비스 메뉴 열기');
    button.innerHTML = '<span aria-hidden="true">☰</span><span class="global-service-nav-toggle-label">메뉴</span>';
    return button;
  }

  function placeToggle(button) {
    var target = document.querySelector('.global-app-header-left') ||
      document.querySelector('.header .header-left') ||
      document.querySelector('.club-header') ||
      document.querySelector('.workout-header') ||
      document.querySelector('.profile-topbar') ||
      document.querySelector('.navbar');
    if (target) {
      target.insertBefore(button, target.firstChild);
      return;
    }
    button.classList.add('global-service-nav-toggle-floating');
    document.body.appendChild(button);
  }

  function updateUser(profile) {
    var name = document.getElementById('global-service-nav-name');
    var role = document.getElementById('global-service-nav-role');
    var avatar = document.getElementById('global-service-nav-avatar');
    var admin = document.getElementById('global-service-nav-admin');
    if (!name || !role || !avatar) return;

    var displayName = profile && (profile.nickname || profile.name || profile.username);
    displayName = displayName || '둘러보는 방문자';
    name.textContent = displayName;
    avatar.textContent = displayName.trim().charAt(0).toUpperCase() || 'S';
    if (profile && profile.is_admin) {
      role.textContent = '서비스 관리자';
      if (admin) admin.hidden = false;
    } else if (profile && profile.is_demo) {
      role.textContent = '비회원 체험 계정';
    } else if (profile) {
      role.textContent = '수영 훈련 회원';
    } else {
      role.textContent = '로그인 없이 기능 둘러보기';
    }
  }

  function loadUser() {
    fetch('/auth/me', { credentials: 'include' })
      .then(function (response) {
        if (!response.ok) throw new Error('guest');
        return response.json();
      })
      .then(updateUser)
      .catch(function () { updateUser(null); });
  }

  function init() {
    if (document.getElementById(NAV_ID) || canonicalPath(window.location.pathname) === '/landing') return;

    var sidebar = document.createElement('aside');
    sidebar.id = NAV_ID;
    sidebar.className = 'global-service-nav';
    sidebar.setAttribute('aria-label', 'SwimMate 전체 서비스 메뉴');

    var top = document.createElement('div');
    top.className = 'global-service-nav-top';
    var brand = document.createElement('a');
    brand.className = 'global-service-nav-brand';
    brand.href = '/landing';
    brand.setAttribute('aria-label', 'SwimMate 내 훈련 홈');
    brand.innerHTML = '<img src="/static/icons/favicon.svg" alt=""><span><strong>SwimMate</strong><small>내 수영 훈련 도우미</small></span>';
    var close = document.createElement('button');
    close.type = 'button';
    close.id = 'global-service-nav-close';
    close.className = 'global-service-nav-close';
    close.setAttribute('aria-label', '전체 서비스 메뉴 닫기');
    close.textContent = '×';
    top.append(brand, close);

    var user = document.createElement('div');
    user.className = 'global-service-nav-user';
    user.innerHTML = '<div class="global-service-nav-avatar" id="global-service-nav-avatar">S</div>' +
      '<div><strong id="global-service-nav-name">내 훈련</strong><span id="global-service-nav-role">계정 확인 중</span></div>';

    var nav = document.createElement('nav');
    nav.className = 'global-service-nav-scroll';
    nav.setAttribute('aria-label', 'SwimMate 서비스');
    groups.forEach(function (group) { nav.appendChild(makeGroup(group)); });

    var footer = document.createElement('div');
    footer.className = 'global-service-nav-footer';
    footerItems.forEach(function (item) { footer.appendChild(makeLink(item)); });
    nav.appendChild(footer);
    sidebar.append(top, user, nav);

    var backdrop = document.createElement('div');
    backdrop.id = 'global-service-nav-backdrop';
    backdrop.className = 'global-service-nav-backdrop';
    backdrop.setAttribute('aria-hidden', 'true');
    var toggle = makeToggle();

    document.body.prepend(backdrop);
    document.body.prepend(sidebar);
    placeToggle(toggle);
    document.body.classList.add('global-service-nav-enabled');

    function setOpen(open) {
      var mobile = MOBILE_QUERY.matches;
      var nextOpen = mobile && Boolean(open);
      sidebar.classList.toggle('open', nextOpen);
      backdrop.classList.toggle('open', nextOpen);
      document.body.classList.toggle('global-service-nav-open', nextOpen);
      toggle.setAttribute('aria-expanded', String(nextOpen));
      toggle.setAttribute('aria-label', nextOpen ? '전체 서비스 메뉴 닫기' : '전체 서비스 메뉴 열기');
      backdrop.setAttribute('aria-hidden', String(!nextOpen));
      sidebar.setAttribute('aria-hidden', String(mobile && !nextOpen));
      if ('inert' in sidebar) sidebar.inert = mobile && !nextOpen;
    }

    toggle.addEventListener('click', function () { setOpen(!sidebar.classList.contains('open')); });
    close.addEventListener('click', function () { setOpen(false); toggle.focus(); });
    backdrop.addEventListener('click', function () { setOpen(false); toggle.focus(); });
    sidebar.addEventListener('click', function (event) {
      if (event.target.closest('a') && MOBILE_QUERY.matches) setOpen(false);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && sidebar.classList.contains('open')) {
        setOpen(false);
        toggle.focus();
      }
    });
    var syncViewport = function () { setOpen(false); };
    if (MOBILE_QUERY.addEventListener) MOBILE_QUERY.addEventListener('change', syncViewport);
    else MOBILE_QUERY.addListener(syncViewport);

    setOpen(false);
    loadUser();
    window.dispatchEvent(new CustomEvent('swimmate:service-nav-ready'));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
