/* Leaderboards site (site 0.5.5.31): fills the header + hero stat cards of
 * leaderboards.html from the AUTO-GENERATED leaderboards.js (cache-busted
 * like dashboard.js). The tables themselves are rendered by community.js
 * (shared with the dashboard + landing sections).
 */

(function () {
  'use strict';

  function fill(lb) {
    const asof = document.getElementById('lbAsof');
    if (asof && lb && lb.asof) asof.textContent = lb.asof.slice(0, 10);

    const setCard = (id, whoId, win) => {
      const el = document.getElementById(id);
      const who = document.getElementById(whoId);
      if (!el) return;
      const best = win && win.rows && win.rows[0];
      if (!best) { el.textContent = '\u2014'; if (who) who.textContent = ''; return; }
      // issue #55: guard null return_pct (e.g. no history) — previously threw on null.toFixed
      if (best.return_pct == null) { el.textContent = '\u2014'; el.className = 'val'; if (who) who.textContent = best.name || best.strategy_id; return; }
      el.textContent = (best.return_pct > 0 ? '+' : '') + Number(best.return_pct).toFixed(2) + '%';
      el.className = 'val ' + (best.return_pct >= 0 ? 'pos' : 'neg');
      if (who) who.textContent = best.name || best.strategy_id;
    };
    if (lb) {
      const cnt = document.getElementById('lcCount');
      if (cnt) cnt.textContent = lb.strategy_count;
      setCard('lcWeekly', 'lcWeeklyWho', lb.windows && lb.windows.weekly);
      setCard('lcMonthly', 'lcMonthlyWho', lb.windows && lb.windows.monthly);
      setCard('lcAlltime', 'lcAlltimeWho', lb.windows && lb.windows.all_time);
      // Clarify all-time window to avoid +99% confusion
      const allEl = document.getElementById('lcAlltime');
      if (allEl) allEl.title = 'All-time = since 2026-08-10 (project inception) — same 10-day window for all strategies';
      const allLabel = document.querySelector('#lcAlltime')?.parentElement?.querySelector('.label');
      if (allLabel && !allLabel.textContent.includes('*')) {
        allLabel.textContent = 'Top all-time return *';
        allLabel.title = 'Since 2026-08-10 (project start) — not 2y';
      }
    }
  }

  const s = document.createElement('script');
  s.src = 'leaderboards.js?t=' + Date.now();
  const injectCommunity = () => {
    const c = document.createElement('script');
    c.src = 'community.js?t=' + Date.now();
    document.head.appendChild(c);
  };
  s.onload = () => {
    fill(window.LEADERBOARDS || null);
    injectCommunity();
  };
  s.onerror = () => {
    // leaderboards.js missing/failed - never throw, show the empty state
    fill(null);
    injectCommunity();
  };
  document.head.appendChild(s);

  const v = document.createElement('script');
  v.src = 'dashboard.js?t=' + Date.now();
  v.onload = () => {
    const el = document.getElementById('verLine');
    const D = window.DASH;
    if (el && D && D.meta && D.meta.version) {
      el.textContent = 'UI v' + D.meta.version.site + ' \u00b7 Engine v' + D.meta.version.algo;
    }
  };
  document.head.appendChild(v);
})();