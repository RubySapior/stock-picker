/**
 * app.js — renders the Stock Picker dashboard.
 *
 * Data flow:
 *   portfolio.json (source of truth)
 *       -> update.py  (fetch prices, TP/SL exits, deploy cash, snapshot, metrics)
 *       -> dashboard.js  (window.DASH = <json>)   <-- AUTO-GENERATED, never hand-edit
 *       -> app.js        (this file renders every section of index.html)
 *
 * Run:
 *   python update.py    # regenerate dashboard.js
 *   python serve.py     # optional localhost:8000 (Update button posts /refresh)
 *   open index.html     # also works via file:// double-click
 *
 * window.DASH data contract (owned by write_dashboard() in update.py):
 *   meta.{name, strategy, start_date, start_value}
 *   asof                                        last snapshot date (YYYY-MM-DD)
 *   summary.{total_value, cash, day_change, total_return_pct, realized_pnl,
 *            max_drawdown_pct, sharpe_annualized, cagr_annualized, start_value}
 *   positions[]                                 {ticker, name, sleeve, buy_date,
 *                                               buy_price, shares, cost,
 *                                               current_price, current_value,
 *                                               pnl_pct, take_profit_pct,
 *                                               stop_loss_pct, status, exit,
 *                                               sector, leverage, effective_value}
 *   sleeves[]                                   {sleeve, value}
 *   sectors[]                                   {sector, value, effective,
 *                                               leverage, pct, max_pct, status,
 *                                               note}
 *   leverage_factor                             book effective ÷ market value
 *   history[]                                   {date, total_value, cash,
 *                                               invested_value, day_change,
 *                                               prices{ticker: px}}
 *   events[]                                    {date, ticker, name, reason,
 *                                               price, buy_price, shares,
 *                                               realized_pnl}
 *   theories[]                                  {id, title, prediction, tier,
 *                                               tier_reason, status, created,
 *                                               last_updated, evidence[]}
 *   benchmark                                   null | {label, start_value,
 *                                               history[], aligned[], summary{}}
 *   news                                        {asof, big_stories[], feed[]}
 *
 * Each UI section is rendered by one named function below; `render()` is the
 * single entry point called once dashboard.js has loaded.
 */
"use strict";

/* Load dashboard.js (cache-busted), then run the callback. */
function loadDash(cb) {
  var s = document.createElement('script');
  s.src = 'dashboard.js?t=' + new Date().getTime();
  s.onload = cb;
  document.head.appendChild(s);
}

function render() {
  const D = window.DASH;
  const escA = v => String(v==null?'':v).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const NAME = {}; (D.positions||[]).forEach(p => NAME[p.ticker] = p.name);
  const fmt$ = v => '$' + Number(v).toLocaleString(undefined,{minimumFractionDigits:2, maximumFractionDigits:2});
  const fmtN = (v,d=2) => Number(v).toLocaleString(undefined,{minimumFractionDigits:d, maximumFractionDigits:d});
  const cls = v => v > 0 ? 'pos' : (v < 0 ? 'neg' : 'muted');
  const sign = v => (v > 0 ? '+' : '') + fmtN(v);
  const s = D.summary;

  /* ---- new-since-last-load tracking (localStorage 'stockpicker.seen.v1') ---- */
  const NEW_KEY = 'stockpicker.seen.v1';
  let base = {}; try{ base = JSON.parse(localStorage.getItem(NEW_KEY)) || {}; }catch(e){}
  const cur = {positions:{}, news:{}};
  (D.positions||[]).forEach(p => cur.positions[p.ticker] = true);
  (D.news ? (D.news.big_stories||[]).concat(D.news.feed||[]) : []).forEach(n => cur.news[n.link||n.title] = true);
  const isNew = {positions:{}, news:{}};
  if(base._init){
    (D.positions||[]).forEach(p => { if(!base.positions?.[p.ticker]) isNew.positions[p.ticker] = true; });
    (D.news ? (D.news.big_stories||[]).concat(D.news.feed||[]) : []).forEach(n => { if(!base.news?.[n.link||n.title]) isNew.news[n.link||n.title] = true; });
  }
  base = {_init:true, ...cur};
  try{ localStorage.setItem(NEW_KEY, JSON.stringify(base)); }catch(e){}

  /* ---- header ---- */
  document.title = D.meta.name;
  document.getElementById('pname').textContent = D.meta.name;
  document.getElementById('psub').textContent = D.meta.strategy;
  document.getElementById('asof').textContent = D.asof;

  /* ---- rebalance flags (passive drift alerts, never trades) ---- */
  const rebal = D.rebalance ? (Array.isArray(D.rebalance) ? D.rebalance : [D.rebalance]) : [];
  const rebalEl = document.getElementById('rebalBanner');
  if (rebalEl) {
    if (rebal.length) {
      rebalEl.style.display = 'block';
      rebalEl.innerHTML = rebal.map(f =>
        `<div><strong>Risk-budget flag:</strong> ${String(f.message||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>`).join('');
    } else rebalEl.style.display = 'none';
  }

  /* ---- summary cards ---- */
  function renderCards(){
    const stb = D.positions.find(p => p.ticker === 'SGOV' && p.status === 'open');
    const stbVal = stb ? stb.current_value : 0;
    const cards = [
      {label:'Total Value', val:fmt$(s.total_value), delta:'', dcls:''},
      {label:'Day Change', val:sign(s.day_change), delta:'', dcls:cls(s.day_change)},
      {label:'Total Return', val:sign(s.total_return_pct)+'%', delta:'', dcls:cls(s.total_return_pct)},
      {label:'Cash + Bonds', val:fmt$(s.cash + stbVal), delta:fmt$(s.cash)+' cash · '+fmt$(stbVal)+' SGOV', dcls:''},
      {label:'Realized P&L', val:sign(s.realized_pnl), delta:'', dcls:cls(s.realized_pnl)},
      {label:'Max Drawdown', val:fmtN(s.max_drawdown_pct)+'%', delta:'', dcls:''},
      {label:'Sharpe (ann.)', val: s.sharpe_annualized===null?'n/a':fmtN(s.sharpe_annualized), delta:'', dcls:''},
      {label:'CAGR (ann.)', val: s.cagr_annualized===null?'n/a':sign(s.cagr_annualized)+'%', delta:'', dcls:cls(s.cagr_annualized)},
    ];
    document.getElementById('cards').innerHTML = cards.map(c =>
      `<div class="card"><div class="label">${c.label}</div><div class="val ${c.dcls}">${c.val}</div><div class="delta ${c.dcls}">${c.delta}</div></div>`
    ).join('');
  }

  /* ---- market fear gauge (top 5) ---- */
  function renderFears(){
    const el = document.getElementById('fearSection');
    const F = D.fears;
    if (!el) return;
    if (!F || !F.length) { el.style.display = 'none'; return; }
    el.style.display = '';
    const esc = x => String(x==null?'':x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const segColor = ['#27ae60','#7bb93c','#f1c40f','#e67e22','#e74c3c'];
    const top = F.slice(0, 5);
    document.getElementById('fearList').innerHTML = top.map((f, i) => {
      const filled = Math.max(1, Math.min(5, Math.round(f.score)));
      const segs = [1,2,3,4,5].map(k =>
        `<span class="fearSeg" style="background:${k <= filled ? segColor[k-1] : 'var(--panel2)'}"></span>`).join('');
      const arrow = f.trend_dir === 'rising' ? '&#9650;' : f.trend_dir === 'falling' ? '&#9660;' : '&#8226;';
      const why = (f.signals||[]).map(s => esc(s.label)).join(' &middot; ');
      const hedgeChips = (f.hedge_ticks||[]).map(t => `<span class="chip">${t}</span>`).join('');
      const thLinks = (f.theory_ids||[]).map(t => `<a class="theoryTag" href="#theory-${t}">${t}</a>`).join('');
      return `<div class="fearRow">
        <span class="fearRank">${i+1}</span>
        <div class="fearMain">
          <div class="fearName">${esc(f.name)} <span class="muted small">${esc(f.type)}</span></div>
          <div class="fearBar">${segs}</div>
        </div>
        <div class="fearScore" style="color:${segColor[filled-1]}">${fmtN(f.score,1)} <span class="fearArrow">${arrow}</span></div>
        <div class="fearWhy">${why ? `<span class="muted small">${why}</span>` : ''}${hedgeChips ? '<span class="muted small"> &middot; hedges:</span> '+hedgeChips : ''} ${thLinks}</div>
      </div>`;
    }).join('');

    const C = D.complacency;
    document.getElementById('complacency').innerHTML = C
      ? `<span class="${C.index >= 0.5 ? 'compHot' : (C.index >= 0.3 ? 'compMid' : 'compCool')}">Complacency ${fmtN(C.index,2)} &middot; ${esc(C.note)}</span>`
      : '';

    const S = D.fear_sizing;
    const szEl = document.getElementById('fearSizing');
    if (S && S.length) {
      szEl.style.display = '';
      szEl.innerHTML = `<strong>Suggested hedge actions (review only &mdash; not executed):</strong> ` +
        S.map(x => `${x.instrument} +${fmtN(x.pct)}pp (${x.reasons.join(',')})`).join(' &middot; ');
    } else szEl.style.display = 'none';
  }

  /* ---- positions table (sortable) ---- */
  const posSort = {key:'current_value', dir:-1};
  function sortP(key){
    if(posSort.key===key) posSort.dir *= -1;
    else { posSort.key = key; posSort.dir = key==='ticker' || key==='name' || key==='status' ? 1 : -1; }
    renderPositions();
  }
  function posVal(p, key){
    switch(key){
      case 'ticker': return p.ticker.toUpperCase();
      case 'name': return p.name.toLowerCase();
      case 'status': return p.status==='open' ? 0 : 1;
      case 'pct': return p.current_value / s.total_value;
      case 'take_profit_pct': return p.take_profit_pct===null ? -Infinity : p.take_profit_pct;
      case 'stop_loss_pct': return p.stop_loss_pct===null ? -Infinity : p.stop_loss_pct;
      default: return p[key];
    }
  }
  function renderPositions(){
    const dir = posSort.dir;
    const sorted = D.positions.slice().sort((a,b) => {
      let x = posVal(a,posSort.key), y = posVal(b,posSort.key);
      if(x<y) return -1*dir; if(x>y) return 1*dir; return 0;
    });
    const rows = sorted.map(p => {
      const st = p.status;
      const badge = st==='open' ? 'open' : (p.exit && p.exit.reason==='take_profit' ? 'tp' : 'sl');
      const label = st==='open' ? 'OPEN' : (p.exit && p.exit.reason==='take_profit' ? 'TAKE PROFIT' : 'STOP LOSS');
      const pnl = p.pnl_pct===null ? '—' : sign(p.pnl_pct)+'%';
      return `<tr>
        <td><strong><span class="tick" title="${escA(p.name)}">${p.ticker}</span></strong>${p.leverage > 1 ? `<span class="levBadge">${p.leverage}x</span>` : ''}${isNew.positions[p.ticker] ? '<span class="newTag">NEW</span>' : ''}</td>
        <td>${p.name}<div class="small muted">${p.sleeve}</div></td>
        <td>${fmtN(p.buy_price)}</td>
        <td>${fmtN(p.current_price)}</td>
        <td>${fmt$(p.current_value)}</td>
        <td>${fmtN(p.current_value / s.total_value * 100, 1)}%</td>
        <td class="${cls(p.pnl_pct)}">${pnl}</td>
        <td class="pos">${p.take_profit_pct ? (p.take_profit_pct*100).toFixed(0)+'%' : '—'}</td>
        <td class="neg">${p.underlying ? p.underlying+' '+(p.underlying_stop_pct*100).toFixed(0)+'%' : (p.stop_loss_pct ? (p.stop_loss_pct*100).toFixed(0)+'%' : '—')}</td>
        <td><span class="pill ${badge}">${label}</span></td>
      </tr>`;
    }).join('');
    document.querySelector('#posTable tbody').innerHTML = rows;
    document.querySelectorAll('#posTable thead th').forEach(th => {
      th.classList.toggle('sorted', th.dataset.key === posSort.key);
      let ca = th.querySelector('.caret');
      if(!ca){ ca = document.createElement('span'); ca.className='caret'; th.appendChild(ca); }
      ca.textContent = th.dataset.key===posSort.key ? (dir===1 ? '▲' : '▼') : '';
    });
  }
  document.querySelectorAll('#posTable thead th').forEach(th =>
    th.addEventListener('click', ()=> sortP(th.dataset.key)));

  /* ---- sector limits (incl. leverage) ---- */
  function renderSectors(){
    document.getElementById('levFactor').textContent = D.leverage_factor + 'x';
    document.getElementById('sectorList').innerHTML = (D.sectors || []).map(sr => {
      const ratio = sr.max_pct > 0 ? Math.min(100, sr.pct / sr.max_pct * 100) : 100;
      const color = sr.status === 'over' ? 'var(--red)' : sr.status === 'warn' ? 'var(--amber)' : 'var(--green)';
      const label = sr.status === 'over' ? 'OVER' : sr.status === 'warn' ? 'NEAR' : 'OK';
      return `<div class="srow">
        <span class="sname">${sr.sector}${sr.note ? `<div class="small muted" style="font-size:10.5px;">${sr.note}</div>` : ''}</span>
        <span class="sbar">
          <span class="fill" style="width:${ratio}%; background:${color};"></span>
          <span class="capmark" style="left:100%;"></span>
        </span>
        <span class="sval">${fmt$(sr.effective)}<div class="small muted">${sr.leverage > 1 ? sr.leverage + 'x eff' : '1x'}</div></span>
        <span class="scap">${fmtN(sr.pct, 1)}/${sr.max_pct}%</span>
        <span class="sstat stat ${sr.status}">${label}</span>
      </div>`;
    }).join('');
  }

  /* ---- portfolio vs SPY ---- */
  function renderComparison(){
    const bm = D.benchmark;
    const cmpEl = document.getElementById('cmpWrap');
    const row = (label, p, b, fmt) => {
      const ps = (p === null || p === undefined) ? 'n/a' : fmt(p);
      const bs = (b === null || b === undefined) ? 'n/a' : fmt(b);
      const d = (typeof p === 'number' && typeof b === 'number') ? fmt(p - b) : '—';
      return `<tr>
        <td>${label}</td>
        <td class="${cls(p)}">${ps}</td>
        <td>${bs}</td>
        <td class="${(typeof p === 'number' && typeof b === 'number') ? cls(p - b) : 'muted'}">${d}</td>
      </tr>`;
    };
    cmpEl.innerHTML = bm ? `
      <table class="cmpTable">
        <thead><tr><th>Metric</th><th>Portfolio</th><th>SPY</th><th>&Delta;</th></tr></thead>
        <tbody>
          ${row('Total Return', s.total_return_pct, bm.summary.total_return_pct, v => sign(v) + '%')}
          ${row('Max Drawdown', s.max_drawdown_pct, bm.summary.max_drawdown_pct, v => fmtN(v) + '%')}
          ${row('Sharpe (ann.)', s.sharpe_annualized, bm.summary.sharpe_annualized, v => fmtN(v))}
        </tbody>
      </table>
      <div class="muted small" style="margin-top:8px;">Both normalized to $${fmtN(s.start_value, 0)} at ${D.meta.start_date}. SPY overlay is toggled on the history chart.</div>`
      : '<div class="muted small">Benchmark unavailable — run <code>python update.py</code> with internet access.</div>';
  }

  /* ---- theories scorecard ---- */
  function renderTheories(){
    const tierOrder = {S:0,A:1,B:2,C:3,D:4};
    const sortedTheories = D.theories.slice().sort((a,b) => {
      const ta = tierOrder[a.tier] ?? 5, tb = tierOrder[b.tier] ?? 5;
      return ta - tb || a.id.localeCompare(b.id);
    });
    const tRows = sortedTheories.map(t => {
      const st = t.status;
      const statusLabel = st==='pending' ? 'PENDING' : st==='right' ? 'RIGHT' : st==='wrong' ? 'WRONG' : st==='abandoned' ? 'ABANDONED' : st.toUpperCase();
      const badgeClass = st==='pending' ? 'pending' : st==='right' ? 'right' : st==='wrong' ? 'wrong' : st==='abandoned' ? 'abandoned' : st;
      const evs = (t.evidence||[]).slice().reverse().map(e => `<div class="ev">${e}</div>`).join('');
      return `<tr id="theory-${t.id}">
        <td><span class="badge ${t.tier.toLowerCase()}">${t.tier}</span></td>
        <td><strong>${t.id}</strong></td>
        <td>${t.title}<div class="thesis">${t.tier_reason || ''}</div></td>
        <td class="small">${t.prediction}</td>
        <td><span class="badge ${badgeClass}">${statusLabel}</span></td>
        <td>${evs || '<span class="muted small">no evidence yet</span>'}</td>
      </tr>`;
    }).join('');
    document.querySelector('#theoryTable tbody').innerHTML = tRows;
  }

  /* ---- trade events ---- */
  function renderEvents(){
    const evBox = document.getElementById('events');
    if (!D.events.length) evBox.innerHTML = '<div class="muted small">No closed trades yet. Take-profit / stop-loss exits will appear here.</div>';
    else evBox.innerHTML = D.events.slice().reverse().map(e =>
      `<div class="eventline">
         <div><strong title="${escA(NAME[e.ticker]||e.ticker)}">${e.ticker || 'SYSTEM'}</strong> <span class="muted small">${e.date}</span></div>
         <div><span class="pill ${e.reason==='take_profit'?'tp':(e.reason==='stop_loss'?'sl':(e.reason==='rebalance_recommended'?'warn':'open'))}">${e.reason.toUpperCase()}</span>
         <span class="muted small">@ ${fmtN(e.price)}</span>
         <span class="${cls(e.realized_pnl)}"> ${sign(e.realized_pnl)}</span></div>
         ${e.note ? `<div class="small muted">${e.note}</div>` : ''}
       </div>`
    ).join('');
  }

  /* ---- sleeve list ---- */
  function renderSleeves(){
    document.getElementById('sleeveList').innerHTML = D.sleeves.map(sl =>
      `<div style="display:flex; justify-content:space-between; font-size:12.5px; padding:3px 0;">
         <span class="muted">${sl.sleeve}</span><span>${fmt$(sl.value)}</span>
       </div>`
    ).join('');
  }

  /* ---- news (big stories + feed) ---- */
  function renderNews(){
    const N = D.news || {};
    const bigEl = document.getElementById('bigStories');
    const feedEl = document.getElementById('newsFeed');
    const esc = x => String(x==null?'':x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const href = x => String(x==null?'':x).replace(/"/g,'&quot;');
    const trunc20 = s => { const w = String(s).split(/\s+/); return w.length>20 ? w.slice(0,20).join(' ')+'…' : s; };
    const thTitle = {}; (D.theories||[]).forEach(t => thTitle[t.id] = t.title);
    const sentChip = sn => `<span class="sent ${sn}">${sn}</span>`;
    const chips = it => (it.theory||[]).map(t =>
      `<a class="theoryTag" href="#theory-${t}" title="${esc(thTitle[t]||t)}">${t}</a>`).join('');
    const meta = it =>
      `${sentChip(it.sent)}<span class="tick" title="${esc(NAME[it.ticker]||it.ticker)}">${it.ticker}</span><span class="ind">${esc(it.industry)}</span><span class="small">${esc(it.when)}</span>${isNew.news[it.link||it.title] ? '<span class="newTag">NEW</span>' : ''}`;
    const empty = '<div class="muted small">No news yet — run <code>python update.py</code> with internet access.</div>';

    bigEl.innerHTML = (N.big_stories && N.big_stories.length)
      ? N.big_stories.map((it,i)=>`
          <div class="story">
            <div class="snum">${i+1}</div>
            <div class="sbody">
              <a class="stitle" href="${href(it.link)}" target="_blank" rel="noopener">${esc(it.title)}</a>
              <div class="smeta">${meta(it)}</div>
            </div>
          </div>`).join('')
      : empty;

    feedEl.innerHTML = (N.feed && N.feed.length)
      ? N.feed.map(it=>`
          <div class="feedItem">
            <a class="fTitle" href="${href(it.link)}" target="_blank" rel="noopener">${esc(trunc20(it.title))}</a>
            <div class="fMeta">${meta(it)} ${chips(it)}</div>
          </div>`).join('')
      : empty;
  }

  /* ---- line chart (vs SPY, zoom/pan, range presets) ---- */
  function initValueChart(){
    const c = document.getElementById('chart'); const ctx = c.getContext('2d');
    const tip = document.getElementById('chartTip');
    const pad = {l:56, r:14, t:16, b:30};
    const H = 280; c.style.height = H+'px';
    const hist = D.history;
    const spyAl = (D.benchmark && D.benchmark.aligned) ? D.benchmark.aligned : [];
    const N = hist.length;
    let W = 0, showSpy = true, view = {i0:0, i1:N-1}, hoverI = -1;

    function setSize(){
      W = Math.max(60, c.clientWidth || c.parentNode.clientWidth);
      const dpr = window.devicePixelRatio||1;
      const pw = Math.round(W*dpr), ph = Math.round(H*dpr);
      if(c.width!==pw || c.height!==ph){ c.width = pw; c.height = ph; }
      if(c.style.width !== W+'px') c.style.width = W+'px';
      ctx.setTransform(dpr,0,0,dpr,0,0);
    }

    function draw(){
      setSize();
      const i0 = view.i0, i1 = view.i1, len = (i1-i0)||1;
      let mn = Infinity, mx = -Infinity;
      for(let i=i0;i<=i1;i++){
        const v = hist[i].total_value; if(v<mn)mn=v; if(v>mx)mx=v;
        if(showSpy && spyAl[i] && spyAl[i].value!==undefined){ const sv=spyAl[i].value; if(sv<mn)mn=sv; if(sv>mx)mx=sv; }
      }
      if(!isFinite(mn)){ mn = hist[i0].total_value; mx = mn; }
      const rng = (mx-mn)||1, minA = mn - rng*0.08, maxA = mx + rng*0.08;
      const X = i => pad.l + (W-pad.l-pad.r)*((i-i0)/len);
      const Y = v => pad.t + (H-pad.t-pad.b)*(1-(v-minA)/(maxA-minA));
      ctx.clearRect(0,0,W,H);
      // grid + y labels
      ctx.font = '11px Segoe UI'; ctx.fillStyle = '#8b95a8'; ctx.textAlign='right';
      for(let g=0; g<=4; g++){
        const v = minA + (maxA-minA)*g/4; const y = Math.round(Y(v))+0.5;
        ctx.strokeStyle='#1b2231'; ctx.beginPath(); ctx.moveTo(pad.l,y); ctx.lineTo(W-pad.r,y); ctx.stroke();
        ctx.fillText('$'+fmtN(v,0), pad.l-6, y+4);
      }
      // SPY overlay
      if(showSpy){
        ctx.beginPath(); let started = false;
        for(let i=i0;i<=i1;i++){
          const sv = spyAl[i] && spyAl[i].value;
          if(sv===undefined) continue;
          if(!started){ ctx.moveTo(X(i),Y(sv)); started = true; } else ctx.lineTo(X(i),Y(sv));
        }
        ctx.strokeStyle='rgba(245,158,11,.9)'; ctx.lineWidth=1.6; ctx.setLineDash([5,4]); ctx.stroke(); ctx.setLineDash([]);
      }
      // portfolio area
      const grad = ctx.createLinearGradient(0,pad.t,0,H-pad.b);
      grad.addColorStop(0,'rgba(56,189,248,0.30)'); grad.addColorStop(1,'rgba(56,189,248,0.0)');
      ctx.beginPath();
      for(let i=i0;i<=i1;i++){ i===i0 ? ctx.moveTo(X(i),Y(hist[i].total_value)) : ctx.lineTo(X(i),Y(hist[i].total_value)); }
      ctx.lineTo(X(i1), H-pad.b); ctx.lineTo(X(i0), H-pad.b); ctx.closePath();
      ctx.fillStyle=grad; ctx.fill();
      // portfolio line
      ctx.beginPath();
      for(let i=i0;i<=i1;i++){ i===i0 ? ctx.moveTo(X(i),Y(hist[i].total_value)) : ctx.lineTo(X(i),Y(hist[i].total_value)); }
      ctx.strokeStyle='#38bdf8'; ctx.lineWidth=2; ctx.stroke();
      // dots when zoomed in enough
      if(len<=60){
        ctx.fillStyle='#38bdf8';
        for(let i=i0;i<=i1;i++){ ctx.beginPath(); ctx.arc(Math.round(X(i)), Math.round(Y(hist[i].total_value)), 2.6, 0, 7); ctx.fill(); }
      }
      // start line
      if(i0===0){
        const ys = Math.round(Y(D.meta.start_value))+0.5;
        ctx.strokeStyle='rgba(245,158,11,.6)'; ctx.setLineDash([4,4]); ctx.beginPath(); ctx.moveTo(pad.l,ys); ctx.lineTo(W-pad.r,ys); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle='#f59e0b'; ctx.textAlign='left'; ctx.fillText('start $100,000', pad.l+4, ys-4);
      }
      // hover crosshair + dot
      if(hoverI>=i0 && hoverI<=i1){
        const x = Math.round(X(hoverI))+0.5;
        ctx.strokeStyle='rgba(139,149,168,.5)'; ctx.setLineDash([3,3]);
        ctx.beginPath(); ctx.moveTo(x,pad.t); ctx.lineTo(x,H-pad.b); ctx.stroke(); ctx.setLineDash([]);
        ctx.beginPath(); ctx.arc(x, Math.round(Y(hist[hoverI].total_value)), 3.2, 0, 7);
        ctx.fillStyle='#38bdf8'; ctx.fill(); ctx.strokeStyle='#0b0e14'; ctx.lineWidth=1.5; ctx.stroke();
      }
      // x labels (5 ticks)
      ctx.textAlign='center'; ctx.fillStyle='#8b95a8'; ctx.font='10px Segoe UI';
      for(let k=0;k<5;k++){
        const i = Math.round(i0 + len*k/4);
        const x = Math.round(X(Math.min(i,i1)));
        if(x>=pad.l && x<=W-pad.r) ctx.fillText(hist[Math.min(i,i1)].date.slice(5), x, H-10);
      }
      // legend
      ctx.textAlign='left'; ctx.font='10.5px Segoe UI';
      ctx.fillStyle='#38bdf8'; ctx.fillText('Portfolio', pad.l+2, pad.t+11);
      if(showSpy){ ctx.fillStyle='#f59e0b'; ctx.fillText('SPY', pad.l+80, pad.t+11); }
    }

    function setRange(days){
      let i0 = 0;
      if(days>0){
        const cut = Date.parse(hist[N-1].date) - days*86400000;
        for(let i=0;i<N;i++){ if(Date.parse(hist[i].date) >= cut){ i0 = i; break; } }
      }
      view = {i0, i1:N-1};
      document.querySelectorAll('.rangeBtn').forEach(b => b.classList.toggle('active', Number(b.dataset.days)===days));
      draw();
    }

    document.querySelectorAll('.rangeBtn').forEach(b =>
      b.addEventListener('click', ()=> setRange(Number(b.dataset.days))));
    document.getElementById('spyToggle').addEventListener('change', ev=>{ showSpy = ev.target.checked; draw(); });

    c.addEventListener('wheel', ev=>{
      ev.preventDefault();
      const rect = c.getBoundingClientRect();
      const mx = ev.clientX - rect.left;
      const f = Math.min(1, Math.max(0, (mx-pad.l)/((W-pad.l-pad.r)||1)));
      const cur = view.i1-view.i0+1;
      const z = ev.deltaY>0 ? 1.25 : 0.8;
      let nl = Math.round(cur*z); nl = Math.min(Math.max(nl,2), N);
      const anchor = view.i0 + cur*f;
      let i0 = Math.round(anchor - nl*f);
      i0 = Math.max(0, Math.min(i0, N-nl));
      view = {i0, i1:i0+nl-1};
      document.querySelectorAll('.rangeBtn').forEach(b => b.classList.remove('active'));
      draw();
    }, {passive:false});

    c.addEventListener('mousedown', ev=>{
      const len = view.i1-view.i0+1;
      const x0 = ev.clientX, iStart = view.i0;
      c.style.cursor = 'grabbing';
      function mm(ev){
        const perPx = len / ((W-pad.l-pad.r)||1);
        let i0 = Math.round(iStart - (ev.clientX - x0)*perPx);
        i0 = Math.max(0, Math.min(i0, N-len));
        view = {i0, i1:i0+len-1};
        draw();
      }
      function up(){
        window.removeEventListener('mousemove', mm);
        window.removeEventListener('mouseup', up);
        c.style.cursor = '';
      }
      window.addEventListener('mousemove', mm);
      window.addEventListener('mouseup', up);
    });

    c.addEventListener('dblclick', ()=> setRange(0));

    c.addEventListener('mousemove', ev=>{
      const r = c.getBoundingClientRect();
      const mx = ev.clientX - r.left;
      const len = view.i1-view.i0+1;
      const frac = Math.max(0, Math.min(1, (mx-pad.l)/((W-pad.l-pad.r)||1)));
      const i = Math.round(view.i0 + frac*len);
      if(i<view.i0 || i>view.i1){
        if(hoverI!==-1){ hoverI = -1; draw(); }
        tip.style.opacity = 0;
        return;
      }
      const changed = hoverI !== i;
      hoverI = i;
      if(changed) draw();
      const h = hist[i];
      const spy = showSpy && spyAl[i] ? spyAl[i].value : null;
      tip.innerHTML = `<strong>${h.date}</strong><div>Portfolio: ${fmt$(h.total_value)}</div>` +
        (spy===null||spy===undefined ? '' : `<div style="color:#f59e0b;">SPY: ${fmt$(spy)}</div>`);
      tip.style.opacity = 1;
      let x = mx + 14;
      if(x + tip.offsetWidth > W) x = mx - tip.offsetWidth - 10;
      tip.style.left = Math.max(0,x)+'px';
      tip.style.top = '20px';
    });
    c.addEventListener('mouseleave', ()=>{
      if(hoverI!==-1){ hoverI = -1; draw(); }
      tip.style.opacity = 0;
    });

    let rsT;
    window.addEventListener('resize', ()=>{ clearTimeout(rsT); rsT = setTimeout(draw, 120); });

    draw();
  }

  /* ---- donut (growth animation) ---- */
  function initDonut(){
    const c = document.getElementById('donut'); const ctx = c.getContext('2d');
    const tip = document.getElementById('donutTip');
    const H = 200; c.style.height = H+'px';
    const colors = ['#38bdf8','#a78bfa','#22c55e','#f59e0b','#ef4444','#f472b6','#2dd4bf','#fbbf24','#64748b'];
    const UP = 2*Math.PI, LOAD_MS = 950, STAG = 110, GROW = 0.08;
    const ease = t => 1 - Math.pow(1-t, 3);
    let W = 0, hoverI = null, hoverR = 0, anim = false, t0 = 0;
    let radii = [];
    let loaded = false, failT = null;

    function setSize(){
      W = Math.max(60, c.clientWidth || c.parentNode.clientWidth);
      const dpr = window.devicePixelRatio||1;
      const pw = Math.round(W*dpr), ph = Math.round(H*dpr);
      if(c.width!==pw || c.height!==ph){ c.width = pw; c.height = ph; }
      if(c.style.width !== W+'px') c.style.width = W+'px';
      ctx.setTransform(dpr,0,0,dpr,0,0);
    }

    const norm = a => ((a % UP) + UP) % UP;
    function geometry(){
      const total = D.sleeves.reduce((a,b)=>a+b.value,0) + s.cash || 1;
      const cx = W/2, cy = H/2, R = Math.min(W,H)/2 - 8, hole = R*0.62;
      let a0 = -Math.PI/2;
      const segs = D.sleeves.concat([{sleeve:'Cash (buffer)', value:s.cash}]).map((sl,i)=>{
        const a1 = a0 + (sl.value/total)*UP;
        const seg = {name: sl.sleeve, value: sl.value, pct:(sl.value/total)*100, start: norm(a0), end: norm(a1), color: colors[i%colors.length]};
        a0 = a1;
        return seg;
      });
      if(radii.length !== segs.length) radii = segs.map(()=>0);
      return {total, cx, cy, R, hole, segs};
    }

    function draw(){
      setSize();
      const g = geometry();
      ctx.clearRect(0,0,W,H);
      // every slice grows from the hole edge outward to its full size
      g.segs.forEach((seg,i)=>{
        if(i===hoverI) return;
        const r = g.hole + (g.R-g.hole)*radii[i];
        ctx.globalAlpha = (hoverI===null) ? 1 : 0.35;
        ctx.beginPath(); ctx.moveTo(g.cx,g.cy); ctx.arc(g.cx,g.cy, r, seg.start, seg.end); ctx.closePath();
        ctx.fillStyle = seg.color; ctx.fill();
      });
      ctx.globalAlpha = 1;
      // hovered slice keeps growing outward (visualizes its growth) over the hole
      if(hoverI!==null){
        const seg = g.segs[hoverI];
        const r = g.hole + (g.R-g.hole)*radii[hoverI] + g.R*GROW*ease(hoverR);
        ctx.beginPath(); ctx.moveTo(g.cx,g.cy); ctx.arc(g.cx,g.cy, r, seg.start, seg.end); ctx.closePath();
        ctx.fillStyle = seg.color; ctx.fill();
      }
      // center text (translucent disc keeps it readable over the grown slice)
      ctx.fillStyle='rgba(11,14,20,.62)'; ctx.beginPath(); ctx.arc(g.cx,g.cy,g.hole,0,7); ctx.fill();
      ctx.fillStyle='#e6ebf4'; ctx.font='bold 15px Segoe UI'; ctx.textAlign='center';
      ctx.fillText(fmt$(g.total), g.cx, Math.round(g.cy+2));
      ctx.fillStyle='#8b95a8'; ctx.font='10px Segoe UI';
      ctx.fillText('total value', g.cx, Math.round(g.cy+16));
    }

    function inSeg(ang, seg){
      return seg.start<=seg.end
        ? (ang>=seg.start && ang<=seg.end)
        : (ang>=seg.start || ang<=seg.end);
    }

    function hitTest(mx,my){
      const g = geometry();
      for(let i=0;i<g.segs.length;i++){
        const seg = g.segs[i];
        const r = g.hole + (g.R-g.hole)*radii[i] + (i===hoverI ? g.R*GROW*ease(hoverR) : 0);
        const dx=mx-g.cx, dy=my-g.cy;
        const d=Math.hypot(dx,dy);
        if(d<g.hole || d>r) continue;
        if(inSeg(norm(Math.atan2(dy,dx)), seg)) return i;
      }
      return -1;
    }

    function tick(){
      const g = geometry();
      const now = performance.now();
      let any = false;
      // staggered load growth, then hover growth
      g.segs.forEach((_,i)=>{
        const p = Math.max(0, Math.min(1, (now - t0 - i*STAG)/LOAD_MS));
        // half-size growth: slices start at half radius and animate to full,
        // so the movement is only half as dramatic as a full hole-to-rim grow.
        const target = 0.5 + 0.5*ease(p);
        if(Math.abs(radii[i]-target) > 0.002){ radii[i] += (target-radii[i])*0.18; any = true; }
        else radii[i] = target;
      });
      const ht = hoverI===null ? 0 : 1;
      if(Math.abs(hoverR-ht) > 0.01){ hoverR += (ht-hoverR)*0.22; any = true; }
      else hoverR = ht;
      draw();
      if(any) requestAnimationFrame(tick); else { anim = false; if(radii.every(r=>r>0.99)) loaded = true; }
    }
    function wake(){ if(!anim){ anim = true; requestAnimationFrame(tick); } }
    function finishLoad(){
      // Force the final state regardless of rAF throttling (background tab,
      // battery saver, etc.) so the pie is never stuck "shriveled".
      radii = radii.map(()=>1);
      hoverR = hoverI===null ? 0 : hoverR;
      loaded = true; anim = false;
      draw();
    }
    function startLoad(){
      radii = radii.map(()=>0.5);
      loaded = false;
      t0 = performance.now();
      wake();
      // Guaranteed-completion deadline: even if rAF barely fires, the donut
      // is fully grown shortly after load.
      clearTimeout(failT);
      failT = setTimeout(finishLoad, LOAD_MS + STAG*(radii.length||12) + 500);
    }

    c.addEventListener('mousemove', ev=>{
      const r = c.getBoundingClientRect();
      const mx = ev.clientX - r.left, my = ev.clientY - r.top;
      const i = hitTest(mx,my);
      if(i<0){
        tip.style.opacity = 0;
        if(hoverI!==null){ hoverI = null; wake(); }
        else if(!anim) draw();
        return;
      }
      const g = geometry(); const seg = g.segs[i];
      tip.innerHTML = '<strong>'+seg.name+'</strong><div>'+fmt$(seg.value)+'</div><div class="small" style="color:#8b95a8;">'+fmtN(seg.pct,1)+'%</div>';
      tip.style.opacity = 1;
      let x = mx + 14, y = my + 14;
      if(x + tip.offsetWidth  > W) x = mx - tip.offsetWidth  - 10;
      if(y + tip.offsetHeight > H) y = my - tip.offsetHeight - 10;
      tip.style.left = Math.max(0,x)+'px';
      tip.style.top  = Math.max(0,y)+'px';
      if(hoverI!==i){ hoverI = i; wake(); }
    });

    c.addEventListener('mouseleave', ()=>{
      tip.style.opacity = 0;
      if(hoverI!==null){ hoverI = null; wake(); }
    });

    let rsT;
    window.addEventListener('resize', ()=>{ clearTimeout(rsT); rsT = setTimeout(()=>draw(), 120); });

    // If the tab was hidden/inactive during load, run the growth animation
    // the moment it becomes visible instead of leaving the pie shriveled.
    document.addEventListener('visibilitychange', ()=>{
      if(document.visibilityState === 'visible' && !loaded){ setSize(); startLoad(); }
    });
    document.addEventListener('pageshow', ()=>{ setSize(); draw(); if(!loaded) startLoad(); });

    startLoad();
  }

  /* ---- invoke every section renderer in DOM order ---- */
  renderCards();
  renderFears();
  renderPositions();
  renderSectors();
  renderComparison();
  renderTheories();
  renderEvents();
  renderSleeves();
  renderNews();
  initValueChart();
  initDonut();
}
loadDash(render);

/* ---- update button: POST /refresh (runs update.py), then reload ---- */
(function(){
  const btn = document.getElementById('updateBtn');
  if(!btn) return;
  btn.addEventListener('click', async ()=>{
    const old = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = 'Updating&hellip;';
    try{
      const r = await fetch('refresh', {method:'POST'});
      if(r.ok){
        const j = await r.json().catch(()=>({}));
        if(window.console && j.output) console.log(j.output);
      }
    }catch(e){ /* file:// or offline -> just refresh the page */ }
    location.reload();
  });
})();
