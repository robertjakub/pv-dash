(function () {
  const bootQs = new URLSearchParams(location.search);
  const load = src => new Promise(res => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => res(true);
    s.onerror = () => { s.remove(); res(false); };
    document.head.appendChild(s);
  });
  const cfgPaths = [...new Set([bootQs.get('config'), 'config.js'].filter(Boolean))];
  const i18nPaths = [...new Set([bootQs.get('i18n'), 'i18n.js'].filter(Boolean))];
  window.__boot = (async () => {
    for (const p of cfgPaths) if (await load(p)) break;
    for (const p of i18nPaths) if (await load(p)) break;
  })();
})();
