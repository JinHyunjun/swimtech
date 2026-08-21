(function () {
  'use strict';

  var NAV_ID = 'global-service-nav';
  var MOBILE_QUERY = window.matchMedia('(max-width: 1100px)');
  var PATH_ALIASES = {
    '/badge': '/badges',
    '/training_log': '/training-log'
  };

  var primaryItems = [
    { href: '/landing', label: '오늘', icon: '⌂' },
    { href: '/training-log', label: '기록', icon: '＋' },
    { href: '/plan', label: '플랜', icon: '▦' },
    { href: '/report', label: '성장', icon: '↗' }
  ];

  var groups = [
    {
      title: '내 훈련 분석', icon: '◫',
      items: [
        { href: '/dashboard', label: '훈련 분석', icon: '◫' },
        { href: '/my-data', label: '내 수영 데이터', icon: '↗' },
        { href: '/workout', label: '풀사이드 실행', icon: '◉' },
        { href: '/badges', label: '뱃지 여정', icon: '◇' },
        { href: '/challenge', label: '수영 챌린지', icon: '⚡' }
      ]
    },
    {
      title: '코치·커뮤니티', icon: '◎',
      items: [
        { href: '/chat', label: 'AI 수영 코치', icon: '✦' },
        { href: '/coach', label: '코치 연동', icon: '◎' },
        { href: '/clubs', label: '클럽·반', icon: '≈' },
        { href: '/community', label: '커뮤니티', icon: '□' }
      ]
    },
    {
      title: '수영 정보·도구', icon: '?',
      items: [
        { href: '/pool', label: '수영장 찾기', icon: '⌖' },
        { href: '/drill', label: '드릴 가이드', icon: '≈' },
        { href: '/injury', label: '부상 예방', icon: '＋' },
        { href: '/equipment', label: '장비 가이드', icon: '○' },
        { href: '/equipment?tab=swimwear', label: '수영복 구매·사이즈', icon: '◇', matchQuery: 'swimwear' },
        { href: '/videos', label: '영상 라이브러리', icon: '▷' },
        { href: '/glossary', label: '수영 용어', icon: 'A' },
        { href: '/faq', label: '자주 묻는 질문', icon: '?' },
        { href: '/tutorial', label: '기능 안내', icon: 'i' }
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
      link.dataset.authorized = 'false';
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
    var title = document.createElement('button');
    title.type = 'button';
    title.className = 'global-service-nav-group-title';
    title.innerHTML = '<span class="global-service-nav-group-icon" aria-hidden="true">' + group.icon + '</span>' +
      '<span>' + group.title + '</span><span class="global-service-nav-chevron" aria-hidden="true">⌄</span>';
    var links = document.createElement('div');
    links.className = 'global-service-nav-links';
    group.items.forEach(function (item) { links.appendChild(makeLink(item)); });
    var active = Boolean(links.querySelector('.active'));
    section.classList.toggle('open', active);
    title.setAttribute('aria-expanded', String(active));
    title.addEventListener('click', function () {
      var open = !section.classList.contains('open');
      section.classList.toggle('open', open);
      title.setAttribute('aria-expanded', String(open));
    });
    section.append(title, links);
    return section;
  }

  function makePrimaryNavigation() {
    var section = document.createElement('section');
    section.className = 'global-service-nav-primary';
    primaryItems.forEach(function (item) { section.appendChild(makeLink(item)); });
    return section;
  }

  function makeSearch(sidebar) {
    var wrap = document.createElement('label');
    wrap.className = 'global-service-nav-search';
    wrap.innerHTML = '<span aria-hidden="true">⌕</span><span class="sr-only">기능 찾기</span>' +
      '<input type="search" placeholder="기능 찾기" autocomplete="off" aria-label="기능 찾기">';
    var input = wrap.querySelector('input');
    input.addEventListener('input', function () {
      var query = input.value.trim().toLocaleLowerCase('ko-KR');
      sidebar.classList.toggle('searching', Boolean(query));
      sidebar.querySelectorAll('.global-service-nav-group').forEach(function (group) {
        var matches = 0;
        group.querySelectorAll('.global-service-nav-link').forEach(function (link) {
          var match = !query || link.textContent.toLocaleLowerCase('ko-KR').indexOf(query) !== -1;
          link.classList.toggle('search-hidden', !match);
          if (match) matches += 1;
        });
        group.classList.toggle('search-hidden', Boolean(query) && matches === 0);
        if (query && matches) group.classList.add('open');
      });
      sidebar.querySelectorAll('.global-service-nav-primary .global-service-nav-link, .global-service-nav-footer .global-service-nav-link').forEach(function (link) {
        var authorized = link.dataset.authorized !== 'false';
        var match = !query || link.textContent.toLocaleLowerCase('ko-KR').indexOf(query) !== -1;
        link.classList.toggle('search-hidden', !authorized || !match);
      });
      var visible = sidebar.querySelectorAll('.global-service-nav-link:not(.search-hidden):not([hidden])').length;
      sidebar.classList.toggle('search-empty', Boolean(query) && visible === 0);
    });
    return wrap;
  }

  function makeMobileNavigation() {
    var nav = document.createElement('nav');
    nav.id = 'global-mobile-nav';
    nav.className = 'global-mobile-nav';
    nav.setAttribute('aria-label', '빠른 이동');
    primaryItems.forEach(function (item) { nav.appendChild(makeLink(item)); });
    var more = document.createElement('button');
    more.type = 'button';
    more.className = 'global-mobile-nav-more';
    more.innerHTML = '<span aria-hidden="true">•••</span><span>더보기</span>';
    nav.appendChild(more);
    return nav;
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
      if (admin) { admin.hidden = false; admin.dataset.authorized = 'true'; }
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

    var search = makeSearch(sidebar);
    var record = document.createElement('a');
    record.className = 'global-service-nav-record';
    record.href = '/training-log?quick=1';
    record.innerHTML = '<span aria-hidden="true">＋</span><span>오늘 훈련 기록</span>';

    var nav = document.createElement('nav');
    nav.className = 'global-service-nav-scroll';
    nav.setAttribute('aria-label', 'SwimMate 서비스');
    nav.appendChild(makePrimaryNavigation());
    groups.forEach(function (group) { nav.appendChild(makeGroup(group)); });

    var footer = document.createElement('div');
    footer.className = 'global-service-nav-footer';
    footerItems.forEach(function (item) { footer.appendChild(makeLink(item)); });
    nav.appendChild(footer);
    var empty = document.createElement('div');
    empty.className = 'global-service-nav-empty';
    empty.textContent = '일치하는 기능이 없습니다.';
    nav.appendChild(empty);
    sidebar.append(top, user, record, search, nav);

    var backdrop = document.createElement('div');
    backdrop.id = 'global-service-nav-backdrop';
    backdrop.className = 'global-service-nav-backdrop';
    backdrop.setAttribute('aria-hidden', 'true');
    var toggle = makeToggle();
    var mobileNav = makeMobileNavigation();

    document.body.prepend(backdrop);
    document.body.prepend(sidebar);
    document.body.appendChild(mobileNav);
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
    mobileNav.querySelector('.global-mobile-nav-more').addEventListener('click', function () { setOpen(true); });
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
