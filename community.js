/* Community page logic (site 0.5.5.29): leaderboard tabs for the Community
 * section on the landing page (index.html) and the dashboard (dashboard.html).
 * Reads the AUTO-GENERATED leaderboards.js (window.LEADERBOARDS) — same
 * script-tag pattern as dashboard.js, so it works from file:// too.
 */

(function () {
  'use strict';

  const LB_KEY = 'aipp.lb.v1';
  const WINDOW_ORDER = ['weekly', 'monthly', 'quarterly', 'yearly', 'all_time'];
  /* Fixed per-column directions: Return high->low (default), Max DD least
     drawdown first (0.00% -> deepest), Sharpe largest first.
     dir=1 sorts descending: (vb - va) * 1 puts the larger value first. */
  const SORT_METRICS = {
    return: { label: 'Return', val: r => r.return_pct, dir: 1 },
    mdd: { label: 'Max DD', val: r => r.max_drawdown_pct, dir: 1 },
    sharpe: { label: 'Sharpe', val: r => r.sharpe, dir: 1 },
  };
  const esc = v => String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const sign = v => (v > 0 ? '+' : '') + Number(v).toFixed(2);
  /* textContent is assigned directly below - esc() is NOT applied to
     textContent values (that would double-escape). Kept only for any
     future innerHTML use. (issue #55) */

  function loadLb(onOk) {
    if (window.LEADERBOARDS) { onOk && onOk(window.LEADERBOARDS); return; }
    const s = document.createElement('script');
    s.src = 'leaderboards.js?t=' + Date.now();
    s.onload = () => onOk && onOk(window.LEADERBOARDS);
    s.onerror = () => { /* no leaderboards yet — show empty state */ };
    document.head.appendChild(s);
  }

  function init() {
    const root = document.getElementById('communityLb');
    if (!root) return;
    loadLb(render.bind(null, root));
  }

  function render(root, lb) {
    root.textContent = '';
    const metaLine = document.createElement('div');
    metaLine.className = 'lbMeta';
    if (lb && lb.strategy_count != null) {
      metaLine.textContent = lb.strategy_count + (lb.strategy_count === 1 ? ' strategy' : ' strategies') +
        ' ranked \u00b7 Top ' + lb.top_n + ' \u00b7 as of ' + (lb.asof || '').slice(0, 10);
    } else {
      metaLine.textContent = 'Leaderboards will appear after the first update run.';
    }
    root.appendChild(metaLine);

    const tabs = document.createElement('div');
    tabs.className = 'lbTabs';
    let active = WINDOW_ORDER[0];
    try { active = localStorage.getItem(LB_KEY) || active; } catch (e) { /* ignore */ }
    if (!WINDOW_ORDER.includes(active)) active = WINDOW_ORDER[0];
    let sortKey = 'return';

    const body = document.createElement('div');
    body.className = 'lbBody';

    function sortedRows(win) {
      const rows = (win && win.rows) || [];
      const m = SORT_METRICS[sortKey];
      return rows.slice().sort((a, b) => {
        const va = m.val(a);
        const vb = m.val(b);
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        return (vb - va) * m.dir;
      });
    }

    function sortHeader(label, key) {
      const h = document.createElement('span');
      h.className = 'lbNum lbSortable' + (sortKey === key ? ' on' : '');
      h.textContent = label + (sortKey === key ? ' \u25bc' : '');
      h.addEventListener('click', () => {
        sortKey = key;
        draw();
      });
      return h;
    }

    function draw() {
      body.textContent = '';
      const win = (lb && lb.windows && lb.windows[active]) || null;
      const head = document.createElement('div');
      head.className = 'lbHead';
      const h1 = document.createElement('span'); h1.textContent = 'Rank';
      const h2 = document.createElement('span'); h2.textContent = 'Strategy';
      const h3 = document.createElement('span'); h3.textContent = 'Author';
      const h4 = sortHeader('Return', 'return');
      const h5 = sortHeader('Max DD', 'mdd');
      const h6 = sortHeader('Sharpe', 'sharpe');
      head.appendChild(h1); head.appendChild(h2); head.appendChild(h3);
      head.appendChild(h4); head.appendChild(h5); head.appendChild(h6);
      body.appendChild(head);

      const rows = sortedRows(win);
      if (!rows.length) {
        const empty = document.createElement('div');
        empty.className = 'lbEmpty';
        empty.textContent = 'No ranked strategies yet \u2014 be the first to publish.';
        body.appendChild(empty);
        return;
      }
      rows.forEach((r, i) => {
        const row = document.createElement('div');
        row.className = 'lbRow' + (i < 3 ? ' rank' + (i + 1) : '');
        const rk = document.createElement('span');
        rk.className = 'lbRank';
        rk.textContent = String(i + 1);
        const nm = document.createElement('span');
        nm.className = 'lbName';
        nm.textContent = r.name || r.strategy_id;
        const au = document.createElement('span');
        au.className = 'lbAuthor';
        au.textContent = r.author || '\u2014';
        const rt = document.createElement('span');
        rt.className = 'lbNum ' + (r.return_pct >= 0 ? 'pos' : 'neg');
        rt.textContent = sign(r.return_pct) + '%';
        const dd = document.createElement('span');
        dd.className = 'lbNum lbDD ' + (r.max_drawdown_pct == null || r.max_drawdown_pct >= 0 ? 'pos' : 'neg');
        dd.textContent = r.max_drawdown_pct == null ? '\u2014' : sign(r.max_drawdown_pct) + '%';
        const sh = document.createElement('span');
        sh.className = 'lbNum lbSh ' + (r.sharpe == null || r.sharpe >= 0 ? 'pos' : 'neg');
        sh.textContent = r.sharpe == null ? '\u2014' : r.sharpe.toFixed(2);
        row.appendChild(rk); row.appendChild(nm); row.appendChild(au);
        row.appendChild(rt); row.appendChild(dd); row.appendChild(sh);
        body.appendChild(row);
      });
    }

    WINDOW_ORDER.forEach(key => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'lbTab';
      b.textContent = key === 'all_time' ? 'All time' : key.charAt(0).toUpperCase() + key.slice(1);
      b.dataset.key = key;
      if (key === active) b.classList.add('on');
      b.addEventListener('click', () => {
        active = key;
        try { localStorage.setItem(LB_KEY, key); } catch (e) { /* ignore */ }
        tabs.querySelectorAll('.lbTab').forEach(x => x.classList.toggle('on', x === b));
        draw();
      });
      tabs.appendChild(b);
    });

    root.appendChild(tabs);
    root.appendChild(body);
    draw();
  }

  init();
})();