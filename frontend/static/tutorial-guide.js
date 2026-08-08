document.addEventListener('DOMContentLoaded', () => {
  const current = document.body.dataset.guidePage || 'home';
  document.querySelectorAll('[data-guide-link]').forEach(link => {
    if (link.dataset.guideLink === current) link.setAttribute('aria-current', 'page');
  });
});
