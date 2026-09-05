/* Landing page logic: live hero stats from dashboard.js + mock sign-in. */

(function () {
  'use strict';

  const USER_KEY = 'aipp.user.v1';
  const esc = v => String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  /* ---------- live stats from the auto-generated dashboard.js ---------- */
  function loadDash(onOk) {
    const s = document.createElement('script');
    s.src = 'dashboard.js?t=' + Date.now();
    s.onload = () => {
      const D = window.DASH;
      if (!D || !D.summary) return;
      const verEl = document.getElementById('verLine');
      if (verEl && D.meta && D.meta.version) {
        verEl.textContent = 'UI v' + D.meta.version.site + ' \u00b7 Engine v' + D.meta.version.algo;
      }
      const s = D.summary;
      const $ = id => document.getElementById(id);
      const fmt$ = v => '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
      const fmtN = (v, d = 2) => Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
      const sign = v => (v > 0 ? '+' : '') + fmtN(v);
      const day = document.createElement('span');
      day.textContent = sign(s.day_change);
      day.className = s.day_change >= 0 ? 'pos' : 'neg';
      const el = $('hsDay');
      el.textContent = '';
      el.appendChild(day);
      const ret = document.createElement('span');
      ret.textContent = sign(s.total_return_pct) + '%';
      ret.className = s.total_return_pct >= 0 ? 'pos' : 'neg';
      $('hsReturn').textContent = '';
      $('hsReturn').appendChild(ret);
      $('hsValue').textContent = fmt$(s.total_value);
      const bmRet = D.benchmark && D.benchmark.summary && D.benchmark.summary.total_return_pct;
      const ex = (bmRet == null || s.total_return_pct == null) ? null : s.total_return_pct - bmRet;
      const exEl = $('hsStrategy');
      if (exEl) {
        if (ex == null) {
          exEl.textContent = '\u2014';
        } else {
          exEl.textContent = '';
          const sp = document.createElement('span');
          sp.textContent = sign(ex) + ' pp';
          sp.className = ex >= 0 ? 'pos' : 'neg';
          exEl.appendChild(sp);
        }
      }
      onOk && onOk(D);
    };
    s.onerror = () => { /* file:// without a dashboard.js run — leave dashes */ };
    document.head.appendChild(s);
  }

  /* ---------- mascot ---------- */
  const mascot = document.getElementById('mascot');
  if (mascot) {
    const img = new Image();
    img.onload = () => mascot.classList.add('hasIcon');
    img.onerror = () => mascot.classList.remove('hasIcon');
    img.src = 'temp-logo.jpg?v=2';
  }

  /* ---------- hero chart: live portfolio vs SPY when data exists, mock otherwise ---------- */
  function initHeroChart(D) {
    const c = document.getElementById('heroChart');
    if (!c) return;
    const ctx = c.getContext('2d');
    const H = 300;
    const dpr = window.devicePixelRatio || 1;
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const panel = document.querySelector('.heroChartPanel');
    const headTag = panel ? panel.querySelector('.heroChartTag') : null;
    const headTitle = panel ? panel.querySelector('.heroChartHead') : null;
    const cap = panel ? panel.querySelector('.heroChartCap') : null;

    // Try live data: D.history + D.benchmark.aligned
    let live = null;
    try {
      if (D && Array.isArray(D.history) && D.history.length >= 2) {
        const start = (D.meta && D.meta.start_value) || 100000;
        let bm = D.benchmark;
        if (!bm || !Array.isArray(bm.aligned)) {
          const bms = D.benchmarks || {};
          bm = bms.SPY || bms[Object.keys(bms)[0]];
        }
        if (bm && Array.isArray(bm.aligned) && bm.aligned.length >= 2) {
          const aligned = bm.aligned;
          // Align lengths: benchmark history trimmed to portfolio dates
          const n = Math.min(D.history.length, aligned.length);
          const portPts = D.history.slice(-n).map(h => h.total_value / start);
          const bmPts = aligned.slice(-n).map(a => a.value / start);
          const dates = D.history.slice(-n).map(h => h.date);
          if (portPts.length >= 2 && bmPts.length >= 2) {
            live = { portPts, bmPts, dates, bmLabel: bm.label || 'S&P 500', start };
          }
        }
      }
    } catch (e) { live = null; }

    if (live) {
      if (headTag) headTag.textContent = 'live';
      if (headTag) { headTag.style.color = 'var(--green)'; headTag.style.borderColor = 'rgba(34,197,94,.45)'; }
      if (cap) cap.textContent = 'Live portfolio vs ' + live.bmLabel + ' from ' + live.dates[0] + ' to ' + live.dates[live.dates.length - 1] +
        ' — both normalized to $' + (live.start).toLocaleString() + '. Past performance is not indicative of future results.';
      // update heading prefix if still "What your portfolio could look like"
      if (headTitle && headTitle.firstChild && headTitle.firstChild.nodeType === 3) {
        // keep structure, update text node
        const t = headTitle.childNodes[0];
        if (t && /could look like/i.test(t.textContent)) t.textContent = 'Portfolio vs ' + live.bmLabel + ' — live track record ';
      }

      let W = 0;
      function setSize() {
        W = Math.max(60, c.clientWidth || c.parentNode.clientWidth);
        const pw = Math.round(W * dpr), ph = Math.round(H * dpr);
        if (c.width !== pw || c.height !== ph) { c.width = pw; c.height = ph; }
        if (c.style.width !== W + 'px') c.style.width = W + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
      const N = live.portPts.length;
      const pad = { l: 46, r: 84, t: 18, b: 18 };
      const fmtK = v => '$' + Math.round(v * live.start / 1000 * 10) / 10 + 'k';
      const all = live.portPts.concat(live.bmPts);
      const mn = Math.min.apply(null, all), mx = Math.max.apply(null, all);
      // nice 10% padding and 0.05 step
      const STEP = 0.05;
      const minA = Math.floor((mn - 0.02) / STEP) * STEP;
      const maxA = Math.ceil((mx + 0.02) / STEP) * STEP;
      const X = i => pad.l + (W - pad.l - pad.r) * (i / (N - 1));
      const Y = v => pad.t + (H - pad.t - pad.b) * (1 - (v - minA) / (maxA - minA));

      function drawLive(prog, pulse) {
        setSize();
        ctx.clearRect(0, 0, W, H);
        ctx.font = '11px Segoe UI'; ctx.fillStyle = '#8b95a8'; ctx.textAlign = 'right';
        for (let g = 0; g <= (maxA - minA) / STEP + 1e-9; g++) {
          const v = minA + STEP * g;
          const y = Math.round(Y(v)) + 0.5;
          ctx.strokeStyle = '#1b2231'; ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
          ctx.fillText(fmtK(v), pad.l - 7, y + 4);
        }
        const k = Math.max(1, Math.floor(prog * N));
        // SPY area (amber, faint) — draw first so portfolio sits on top
        const bmGrad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
        bmGrad.addColorStop(0, 'rgba(245,158,11,0.10)');
        bmGrad.addColorStop(1, 'rgba(245,158,11,0)');
        ctx.beginPath();
        ctx.moveTo(X(0), Y(live.bmPts[0]));
        for (let i = 1; i < k; i++) ctx.lineTo(X(i), Y(live.bmPts[i]));
        ctx.lineTo(X(k - 1), H - pad.b); ctx.lineTo(X(0), H - pad.b); ctx.closePath();
        ctx.fillStyle = bmGrad; ctx.fill();
        ctx.beginPath();
        ctx.moveTo(X(0), Y(live.bmPts[0]));
        for (let i = 1; i < k; i++) ctx.lineTo(X(i), Y(live.bmPts[i]));
        ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 1.8; ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
        // Portfolio area (blue)
        const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
        grad.addColorStop(0, 'rgba(56,189,248,0.28)');
        grad.addColorStop(1, 'rgba(56,189,248,0)');
        ctx.beginPath();
        ctx.moveTo(X(0), Y(live.portPts[0]));
        for (let i = 1; i < k; i++) ctx.lineTo(X(i), Y(live.portPts[i]));
        ctx.lineTo(X(k - 1), H - pad.b); ctx.lineTo(X(0), H - pad.b); ctx.closePath();
        ctx.fillStyle = grad; ctx.fill();
        ctx.beginPath();
        ctx.moveTo(X(0), Y(live.portPts[0]));
        for (let i = 1; i < k; i++) ctx.lineTo(X(i), Y(live.portPts[i]));
        ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 2.2; ctx.stroke();
        // Legend
        const lx = pad.l + 8, ly = pad.t + 6;
        ctx.font = '10.5px Segoe UI'; ctx.textAlign = 'left';
        ctx.fillStyle = '#38bdf8'; ctx.fillRect(lx, ly, 12, 3);
        ctx.fillStyle = '#e6ebf4'; ctx.fillText('Portfolio', lx + 16, ly + 8);
        ctx.fillStyle = '#f59e0b'; ctx.fillRect(lx + 78, ly, 12, 3);
        ctx.fillStyle = '#e6ebf4'; ctx.fillText(live.bmLabel.replace(' (SPY)',''), lx + 94, ly + 8);
        // End dots + labels
        if (k >= N) {
          const fmtPct = v => ((v - 1) * 100).toFixed(1);
          const pV = live.portPts[N - 1], bV = live.bmPts[N - 1];
          const px = X(N - 1), py = Y(pV), bx = X(N - 1), by = Y(bV);
          let r = 3.5 + Math.sin(pulse * 5) * 1.2;
          ctx.beginPath(); ctx.arc(px, py, r, 0, 7); ctx.fillStyle = '#38bdf8'; ctx.fill();
          ctx.strokeStyle = 'rgba(56,189,248,.35)'; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.arc(px, py, r + 7 + Math.sin(pulse * 3) * 2, 0, 7); ctx.stroke();
          ctx.textAlign = 'left'; ctx.font = 'bold 13px Segoe UI'; ctx.fillStyle = '#e6ebf4';
          ctx.fillText(fmtK(pV), px + 12, py - 2);
          ctx.font = '10.5px Segoe UI'; ctx.fillStyle = pV >= bV ? '#22c55e' : '#ef4444';
          ctx.fillText((pV >= 1 ? '+' : '') + fmtPct(pV) + '%', px + 12, py + 14);
          ctx.beginPath(); ctx.arc(bx, by, 3.2, 0, 7); ctx.fillStyle = '#f59e0b'; ctx.fill();
          ctx.font = '10.5px Segoe UI'; ctx.fillStyle = '#f59e0b';
          ctx.fillText((bV >= 1 ? '+' : '') + fmtPct(bV) + '%', bx + 12, by + (Math.abs(by - py) < 18 ? -12 : 14));
          // Excess badge
          const ex = (pV - bV) * 100;
          ctx.font = 'bold 11px Segoe UI'; ctx.fillStyle = ex >= 0 ? '#22c55e' : '#ef4444';
          ctx.textAlign = 'right'; ctx.fillText((ex >= 0 ? '+' : '') + ex.toFixed(1) + ' pp vs SPY', W - pad.r + 76, pad.t + 10);
          ctx.textAlign = 'left';
        }
      }
      if (reduce) { drawLive(1, 0); return; }
      const t0 = performance.now(), DUR = 1800;
      let done = false;
      (function frame(now) {
        const t = Math.min(1, (now - t0) / DUR);
        drawLive(t, now / 1000);
        if (t >= 1) {
          if (!done) {
            done = true;
            const p0 = performance.now();
            (function pulse(now) {
              drawLive(1, (now - p0) / 1000);
              if (now - p0 < 4500) requestAnimationFrame(pulse);
            })(p0);
          }
          return;
        }
        requestAnimationFrame(frame);
      })(t0);
      window.addEventListener('resize', () => drawLive(1, 0));
      return;
    }

    // Fallback: illustrative mock (no live data — file:// before first update.py)
    const N = 96;
    const AI_AT = Math.floor(N * 0.3);
    const rand = (function () {
      let s = 20260816;
      return function () {
        s |= 0; s = s + 0x6D2B79F5 | 0;
        let t = Math.imul(s ^ s >>> 15, 1 | s);
        t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
        return ((t ^ t >>> 14) >>> 0) / 4294967296;
      };
    })();
    const target = 1.38 + rand() * 0.28;
    const pts = (function () {
      const a = [];
      let v = 1.0;
      for (let i = 0; i < AI_AT; i++) {
        v += 0.002 + (rand() - 0.5) * 0.05;
        if (rand() < 0.05) v -= 0.02 + rand() * 0.03;
        if (rand() < 0.035) v += 0.015 + rand() * 0.025;
        v = Math.max(0.85, Math.min(v, 1.16));
        a.push(v);
      }
      const v0 = v;
      const slope = (target - v0) / (N - 1 - AI_AT);
      for (let i = AI_AT; i < N - 1; i++) {
        v += slope + (rand() - 0.5) * 0.045;
        if (rand() < 0.045) v -= 0.02 + rand() * 0.015;
        if (rand() < 0.03) v += 0.015 + rand() * 0.01;
        if (v < 0.85) v = 0.85;
        a.push(v);
      }
      if (a[N - 2] > target) a[N - 2] = target - (a[N - 2] - target) * 0.6;
      const lift = target - a[N - 2];
      if (lift > 0.005) {
        for (let j = 0; j < 12; j++) a[N - 13 + j] += lift * (j + 1) / 13;
      }
      a.push(target);
      return a;
    })();

    let W = 0;
    function setSize() {
      W = Math.max(60, c.clientWidth || c.parentNode.clientWidth);
      const pw = Math.round(W * dpr), ph = Math.round(H * dpr);
      if (c.width !== pw || c.height !== ph) { c.width = pw; c.height = ph; }
      if (c.style.width !== W + 'px') c.style.width = W + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    const pad = { l: 46, r: 84, t: 14, b: 18 };
    const fmtK = v => '$' + Math.round(v * 1000) / 10 + 'k';
    const mn = Math.min.apply(null, pts), mx = Math.max.apply(null, pts);
    const STEP = 0.2;
    const minA = Math.floor(mn / STEP) * STEP;
    const maxA = Math.ceil(mx / STEP) * STEP;
    const X = i => pad.l + (W - pad.l - pad.r) * (i / (N - 1));
    const Y = v => pad.t + (H - pad.t - pad.b) * (1 - (v - minA) / (maxA - minA));

    function draw(prog, pulse) {
      setSize();
      ctx.clearRect(0, 0, W, H);
      ctx.font = '11px Segoe UI'; ctx.fillStyle = '#8b95a8'; ctx.textAlign = 'right';
      for (let g = 0; g <= (maxA - minA) / STEP; g++) {
        const v = minA + STEP * g;
        const y = Math.round(Y(v)) + 0.5;
        ctx.strokeStyle = '#1b2231'; ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
        ctx.fillText(fmtK(v), pad.l - 7, y + 4);
      }
      const k = Math.max(1, Math.floor(prog * N));
      const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
      grad.addColorStop(0, 'rgba(56,189,248,0.28)');
      grad.addColorStop(1, 'rgba(56,189,248,0)');
      ctx.beginPath();
      ctx.moveTo(X(0), Y(pts[0]));
      for (let i = 1; i < k; i++) ctx.lineTo(X(i), Y(pts[i]));
      ctx.lineTo(X(k - 1), H - pad.b); ctx.lineTo(X(0), H - pad.b); ctx.closePath();
      ctx.fillStyle = grad; ctx.fill();
      ctx.beginPath();
      ctx.moveTo(X(0), Y(pts[0]));
      for (let i = 1; i < k; i++) ctx.lineTo(X(i), Y(pts[i]));
      ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 2; ctx.stroke();

      if (k > AI_AT) {
        const mx = X(AI_AT), my = Y(pts[AI_AT]);
        ctx.setLineDash([5, 4]);
        ctx.strokeStyle = 'rgba(34,197,94,.55)';
        ctx.beginPath(); ctx.moveTo(mx, pad.t); ctx.lineTo(mx, H - pad.b); ctx.stroke();
        ctx.setLineDash([]);
        ctx.beginPath(); ctx.arc(mx, my, 3.4, 0, 7); ctx.fillStyle = '#22c55e'; ctx.fill();
        const label = 'AI ON';
        ctx.font = 'bold 10px Segoe UI';
        const tw = ctx.measureText(label).width + 14;
        const ly = pad.t + 8;
        ctx.fillStyle = 'rgba(34,197,94,.92)';
        ctx.fillRect(mx + 5, ly, tw, 16);
        ctx.fillStyle = '#0b0e14'; ctx.textAlign = 'left';
        ctx.fillText(label, mx + 12, ly + 11.5);
      }

      if (k >= N) {
        const ex = X(N - 1), ey = Y(target);
        const r = 3.5 + Math.sin(pulse * 5) * 1.2;
        ctx.beginPath(); ctx.arc(ex, ey, r, 0, 7); ctx.fillStyle = '#38bdf8'; ctx.fill();
        ctx.strokeStyle = 'rgba(56,189,248,.35)'; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(ex, ey, r + 7 + Math.sin(pulse * 3) * 2, 0, 7); ctx.stroke();
        ctx.textAlign = 'left'; ctx.font = 'bold 13px Segoe UI'; ctx.fillStyle = '#e6ebf4';
        ctx.fillText(fmtK(target), ex + 12, ey - 2);
        ctx.font = '10.5px Segoe UI'; ctx.fillStyle = '#22c55e';
        ctx.fillText('+' + Math.round((target - 1) * 1000) / 10 + '%', ex + 12, ey + 14);
      }
    }

    if (reduce) { draw(1, 0); return; }
    const t0 = performance.now(), DUR = 2400;
    let done = false;
    (function frame(now) {
      const t = Math.min(1, (now - t0) / DUR);
      const ease = t;
      draw(ease, now / 1000);
      if (t >= 1) {
        if (!done) {
          done = true;
          const p0 = performance.now();
          (function pulse(now) {
            draw(1, (now - p0) / 1000);
            if (now - p0 < 3500) requestAnimationFrame(pulse);
          })(p0);
        }
        return;
      }
      requestAnimationFrame(frame);
    })(t0);
    window.addEventListener('resize', () => draw(1, 0));
  }

  /* ---------- mock sign-in ---------- */
  const modal = document.getElementById('authModal');
  const form = document.getElementById('authForm');
  const errEl = document.getElementById('authErr');
  const chip = document.getElementById('authChip');
  const signInBtn = document.getElementById('signInBtn');
  const stateEl = document.getElementById('authState');

  function getUser() {
    try { return JSON.parse(localStorage.getItem(USER_KEY)) || null; } catch (e) { return null; }
  }

  function setUser(u) {
    if (u) localStorage.setItem(USER_KEY, JSON.stringify(u));
    else localStorage.removeItem(USER_KEY);
    renderAuth();
  }

  function renderAuth() {
    const u = getUser();
    if (u) {
      chip.style.display = 'inline-flex';
      chip.innerHTML = 'Signed in: <strong>' + esc(u.email) + '</strong>';
      const out = document.createElement('button');
      out.type = 'button';
      out.className = 'chipOut';
      out.textContent = 'Sign out';
      out.onclick = () => setUser(null);
      chip.appendChild(out);
      signInBtn.textContent = 'Switch account';
    } else {
      chip.style.display = 'none';
      signInBtn.textContent = 'Sign up';
    }
  }

  function openModal() {
    modal.style.display = 'flex';
    errEl.textContent = '';
    const u = getUser();
    stateEl.textContent = u ? 'Signed in as ' + u.email + ' — switch to a different account below.' : '';
    document.getElementById('authEmail').focus();
  }
  function closeModal() { modal.style.display = 'none'; }

  signInBtn.addEventListener('click', openModal);
  document.getElementById('modalX').addEventListener('click', closeModal);
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

  form.addEventListener('submit', e => {
    e.preventDefault();
    const email = document.getElementById('authEmail').value.trim().toLowerCase();
    const pass = document.getElementById('authPass').value;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      errEl.textContent = 'Enter a valid email address.';
      return;
    }
    if (!pass) {
      errEl.textContent = 'Please choose a password.';
      return;
    }
    setUser({ email, name: email.split('@')[0], ts: Date.now() });
    closeModal();
  });

  document.getElementById('guestBtn').addEventListener('click', () => { setUser(null); closeModal(); });

  document.querySelectorAll('a[href="#signup"]').forEach(a => {
    a.addEventListener('click', e => { e.preventDefault(); openModal(); });
  });

  loadDash(initHeroChart);
  renderAuth();
  if (!window.DASH) initHeroChart();
})();