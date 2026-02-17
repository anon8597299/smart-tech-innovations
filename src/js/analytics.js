(function () {
  const cfg = Object.assign(
    {
      ga4MeasurementId: '', // e.g. G-XXXXXXXXXX
      gtmId: '', // e.g. GTM-XXXXXXX
      metaPixelId: '', // e.g. 123456789012345
      clarityId: '', // e.g. abc123def4
      googleAdsId: '', // e.g. AW-123456789
      googleAdsLabel: '', // e.g. abcDEFghiJKLmnopQR
      debug: false,
    },
    window.__IYS_ANALYTICS__ || {}
  );

  const loaded = new Set();

  function loadScript(src, attrs) {
    if (!src || loaded.has(src)) return;
    const s = document.createElement('script');
    s.src = src;
    s.async = true;
    Object.entries(attrs || {}).forEach(([k, v]) => s.setAttribute(k, String(v)));
    document.head.appendChild(s);
    loaded.add(src);
  }

  function ensureDataLayer() {
    window.dataLayer = window.dataLayer || [];
    window.gtag = window.gtag || function gtag() { window.dataLayer.push(arguments); };
  }

  function initGtm() {
    if (!cfg.gtmId) return;
    const existing = document.querySelector(`script[src*="googletagmanager.com/gtm.js?id=${cfg.gtmId}"]`);
    if (existing || (window.google_tag_manager && window.google_tag_manager[cfg.gtmId])) return;
    ensureDataLayer();
    window.dataLayer.push({ 'gtm.start': Date.now(), event: 'gtm.js' });
    loadScript(`https://www.googletagmanager.com/gtm.js?id=${cfg.gtmId}`);
  }

  function initGa4() {
    if (!cfg.ga4MeasurementId) return;
    ensureDataLayer();
    loadScript(`https://www.googletagmanager.com/gtag/js?id=${cfg.ga4MeasurementId}`);
    window.gtag('js', new Date());
    window.gtag('config', cfg.ga4MeasurementId, {
      send_page_view: true,
      debug_mode: !!cfg.debug,
    });
  }

  function initMetaPixel() {
    if (!cfg.metaPixelId || window.fbq) return;
    !(function (f, b, e, v, n, t, s) {
      if (f.fbq) return;
      n = f.fbq = function () {
        n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments);
      };
      if (!f._fbq) f._fbq = n;
      n.push = n;
      n.loaded = true;
      n.version = '2.0';
      n.queue = [];
      t = b.createElement(e);
      t.async = true;
      t.src = v;
      s = b.getElementsByTagName(e)[0];
      s.parentNode.insertBefore(t, s);
    })(window, document, 'script', 'https://connect.facebook.net/en_US/fbevents.js');

    window.fbq('init', cfg.metaPixelId);
    window.fbq('track', 'PageView');
  }

  function initClarity() {
    if (!cfg.clarityId) return;
    (function (c, l, a, r, i, t, y) {
      c[a] =
        c[a] ||
        function () {
          (c[a].q = c[a].q || []).push(arguments);
        };
      t = l.createElement(r);
      t.async = 1;
      t.src = 'https://www.clarity.ms/tag/' + i;
      y = l.getElementsByTagName(r)[0];
      y.parentNode.insertBefore(t, y);
    })(window, document, 'clarity', 'script', cfg.clarityId);
  }

  window.iysTrackEvent = function iysTrackEvent(eventName, params) {
    try {
      if (window.gtag) window.gtag('event', eventName, params || {});
      if (window.fbq) window.fbq('trackCustom', eventName, params || {});
    } catch (_) {}
  };

  window.iysTrackLead = function iysTrackLead(payload) {
    try {
      const value = payload && payload.estimatedValue ? Number(payload.estimatedValue) : undefined;
      const params = {
        source: (payload && payload.source) || 'website-direct',
        goal: (payload && payload.goal) || '',
        value: Number.isFinite(value) ? value : undefined,
        currency: 'AUD',
      };

      if (window.gtag && cfg.ga4MeasurementId) {
        window.gtag('event', 'generate_lead', params);
        if (cfg.googleAdsId && cfg.googleAdsLabel) {
          window.gtag('event', 'conversion', {
            send_to: `${cfg.googleAdsId}/${cfg.googleAdsLabel}`,
            value: Number.isFinite(value) ? value : undefined,
            currency: 'AUD',
          });
        }
      }

      if (window.fbq) window.fbq('track', 'Lead');
    } catch (_) {}
  };

  initGtm();
  if (!cfg.gtmId) initGa4();
  initMetaPixel();
  initClarity();
})();
