/**
 * trades.js — renders the Trade Archive (trades.html): every recorded
 * event (take-profit / stop-loss exits, re-entries, cash deploys, rebalance
 * flags) in a plain table, newest first, with per-second timestamps.
 *
 * Reads the same AUTO-GENERATED dashboard.js (window.DASH) as app.js.
 */
"use strict";

(function () {
  var s = document.createElement('script');
  s.src = 'dashboard.js?t=' + new Date().getTime();
  s.onload = init;
  document.head.appendChild(s);

  function init() {
    const D = window.DASH;
    const escA = v => String(v==null?'':v).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const fmtN = (v,d=2) => Number(v).toLocaleString(undefined,{minimumFractionDigits:d, maximumFractionDigits:d});
    const sign = v => (v > 0 ? '+' : '') + fmtN(v);
    const cls = v => v > 0 ? 'pos' : (v < 0 ? 'neg' : 'muted');
    const NAME = {}; (D.positions||[]).forEach(p => NAME[p.ticker] = p.name);

    document.getElementById('asof').textContent = D.asof;
    document.getElementById('eventCount').textContent = `(${D.events.length} events)`;

    const pill = r => r==='take_profit' ? 'tp' : (r==='stop_loss' ? 'sl' : (r==='rebalance_recommended' ? 'warn' : 'open'));
    const isBuy = e => e.reason === 'market_order'
      ? /^BUY/.test(e.note || '') : (e.reason === 're_entry');
    const moneyOf = e => e.amount != null ? e.amount
      : (e.shares != null && e.price != null ? e.shares * e.price : null);
    const tbody = document.querySelector('#tradeTable tbody');
    tbody.innerHTML = D.events.length
      ? D.events.slice().reverse().map(e => {
          const m = moneyOf(e);
          return `
          <tr>
            <td style="white-space:nowrap;">${e.date}${e.ts ? ' <span class="muted small">' + escA(e.ts) + '</span>' : ''}</td>
            <td><strong title="${escA(NAME[e.ticker]||e.ticker)}">${e.ticker || 'SYSTEM'}</strong></td>
            <td><span class="pill ${pill(e.reason)}">${e.reason.toUpperCase()}${isBuy(e) ? ' / BUY' : ''}</span></td>
            <td>${e.price == null ? '&mdash;' : fmtN(e.price)}</td>
            <td>${e.buy_price == null ? '&mdash;' : fmtN(e.buy_price)}</td>
            <td>${e.shares == null ? '&mdash;' : fmtN(e.shares, 4)}</td>
            <td class="${isBuy(e) ? 'pos' : 'neg'}">${m == null ? '&mdash;' : (isBuy(e) ? '&minus;' : '+') + fmtN(m)}</td>
            <td class="${cls(e.realized_pnl)}">${e.realized_pnl == null ? '&mdash;' : sign(e.realized_pnl)}</td>
            <td class="small muted">${e.note ? escA(e.note) : '&mdash;'}</td>
          </tr>`;
        }).join('')
      : '<tr><td colspan="9" class="muted small">No events recorded yet.</td></tr>';

    const sc = tbody.closest('.scroll');
    const th = document.getElementById('tradeHThumb');
    if (sc && th) {
      const wrap = sc.parentElement;
      let idleT = null;
      function upd(){
        const w = sc.clientWidth, sw = sc.scrollWidth, max = sw - w;
        const show = max > 4;
        th.style.display = show ? 'block' : 'none';
        if(!show) return;
        const tw = Math.max(24, w * w / sw);
        th.style.width = tw + 'px';
        th.style.left = (sc.scrollLeft / max) * (w - tw) + 'px';
      }
      function poke(){
        wrap.classList.add('scrolling');
        clearTimeout(idleT);
        idleT = setTimeout(() => wrap.classList.remove('scrolling'), 1100);
      }
      sc.addEventListener('scroll', () => { upd(); poke(); });
      sc.addEventListener('wheel', poke, { passive: true });
      window.addEventListener('resize', upd);
      upd();
    }
  }
})();