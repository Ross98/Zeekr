// Blocking head script: resolve appearance before the first painted content.
(() => {
  'use strict';
  const key = 'zeekr.theme';
  const valid = value => ['light', 'dark', 'system'].includes(value) ? value : 'system';
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try { preference = valid(window.localStorage.getItem(key)); } catch { /* Session-only fallback. */ }
  function apply() {
    const resolved = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved;
    document.querySelectorAll('[data-theme-select]').forEach(select => { select.value = preference; });
  }
  apply();
  document.addEventListener('DOMContentLoaded', apply);
  document.addEventListener('change', event => {
    if (!event.target.matches('[data-theme-select]')) return;
    preference = valid(event.target.value);
    try { window.localStorage.setItem(key, preference); } catch { /* Keep current session choice. */ }
    apply();
  });
  media.addEventListener('change', () => { if (preference === 'system') apply(); });
  window.addEventListener('storage', event => {
    try { if (event.storageArea !== window.localStorage) return; } catch { return; }
    if (event.key !== key && event.key !== null) return;
    preference = valid(event.newValue);
    apply();
  });
})();
