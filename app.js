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
var snoozeTick = null;

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
  document.title = 'AI Port-picker';
  document.getElementById('pname').textContent = 'AI Port-picker';
  document.getElementById('asof').textContent = D.asof;
  const verEl = document.getElementById('verLine');
  if (verEl) {
    const v = D.meta.version;
    verEl.textContent = v ? `UI v${v.site} · Engine v${v.algo}` : '';
  }
  const mascot = document.getElementById('mascot');
  if (mascot) {
    const img = new Image();
    img.onload = () => mascot.classList.add('hasIcon');
    img.onerror = () => mascot.classList.remove('hasIcon');
    img.src = 'temp-logo.jpg?v=2';
  }

  /* ---- next-refresh countdown (meta.asof_ts + meta.refresh_interval) ---- */
  const nrEl = document.getElementById('nextRefresh');
  if (nrEl && D.meta && D.meta.asof_ts && D.meta.refresh_interval) {
    const target = (D.meta.asof_ts + D.meta.refresh_interval * 60) * 1000;
    const LAST_KEY = 'stockpicker.refresh.last';
    const fmt = s => {
      s = Math.max(0, Math.ceil(s));
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
      return h ? h + ':' + String(m).padStart(2, '0') + ':' + String(ss).padStart(2, '0')
               : String(m).padStart(2, '0') + ':' + String(ss).padStart(2, '0');
    };
    const tick = () => {
      const r = target - Date.now();
      if (r <= 0) {
        const last = +(sessionStorage.getItem(LAST_KEY) || 0);
        if (Date.now() - last > 20000) {
          sessionStorage.setItem(LAST_KEY, String(Date.now()));
          location.reload();
        } else {
          nrEl.textContent = 'waiting for new data';
        }
        return;
      }
      nrEl.textContent = fmt(r / 1000);
    };
    tick();
    setInterval(tick, 1000);
  }

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
      {label:'Cash + SGOV', val:fmt$(s.cash + stbVal), delta:fmt$(s.cash)+' cash', dcls:''},
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
    const aiFears = {}; (D.ai && D.ai.fears || []).forEach(f => aiFears[f.id] = f.sentiment_score);
    const top = F.slice(0, 5);
    document.getElementById('fearList').innerHTML = top.map((f, i) => {
      const filled = Math.max(1, Math.min(5, Math.round(f.score)));
      const segs = [1,2,3,4,5].map(k =>
        `<span class="fearSeg" style="background:${k <= filled ? segColor[k-1] : 'var(--panel2)'}"></span>`).join('');
      const arrow = f.trend_dir === 'rising' ? '&#9650;' : f.trend_dir === 'falling' ? '&#9660;' : '&#8226;';
      const trendWord = `<span class="small ${f.trend_dir==='rising'?'neg':(f.trend_dir==='falling'?'pos':'muted')}">${String(f.trend_dir||'flat').toUpperCase()}</span>`;
      const ai = aiFears[f.id];
      const why = (f.signals||[]).map(s => esc(s.label)).join(' &middot; ');
      const hedgeChips = (f.hedge_ticks||[]).map(t => `<span class="chip">${t}</span>`).join('');
      const thLinks = (f.theory_ids||[]).map(t => `<a class="theoryTag" href="#theory-${t}">${t}</a>`).join('');
      return `<div class="fearRow">
        <span class="fearRank">${i+1}</span>
        <div class="fearMain">
          <div class="fearName">${esc(f.name)} <span class="muted small">${esc(f.type)}</span>${ai != null ? ` <span class="aiWit">AI ${fmtN(ai,1)}</span>` : ''}</div>
          <div class="fearBar">${segs}</div>
        </div>
        <div class="fearScore" style="color:${segColor[filled-1]}">${fmtN(f.score,1)} <span class="fearArrow">${arrow}</span></div>
        <div class="fearWhy">${trendWord}${f.ai_adjusted ? ' <span class="aiWit">blended&middot;AI-adjusted</span>' : ''}${why ? ` &middot; <span class="muted small">${why}</span>` : ''}${hedgeChips ? '<span class="muted small"> &middot; hedges:</span> '+hedgeChips : ''} ${thLinks}</div>
      </div>`;
    }).join('');

    const C = D.complacency;
    const FG = D.fear_greed;
    let cLine = '';
    if (FG) {
      const idx = Math.max(0, Math.min(100, FG.index));
      const zoned = [
        ['#27ae60','greed','Extreme Greed',75,100], ['#7bb93c','greed','Greed',55,75],
        ['#f1c40f','neutral','Neutral',45,55], ['#e67e22','fear','Fear',25,45],
        ['#e74c3c','fear','Extreme Fear',0,25],
      ].map(([c,_,n,lo,hi]) => `<span class="fgZone" style="background:${c}" title="${n} (${lo}-${hi})"></span>`).join('');
      const pos = Math.max(0, Math.min(94, (idx/100)*94));
      cLine = `<span class="fgWrap" title="Crowding check: at >=75 additions are crowded; <=25 is panic-dip territory (CNN-style Fear &amp; Greed)">
        <span class="fgLabel">Fear &amp; Greed</span>
        <span class="fgTrack">${zoned}<span class="fgNeedle" style="left:${pos}%"></span></span>
        <span class="fgVal ${idx>=75?'neg':(idx<=25?'pos':'')}">${esc(FG.label)} ${idx}/100</span>
      </span>`;
    }
    if (C) {
      cLine += `<span class="${C.index >= 0.5 ? 'compHot' : (C.index >= 0.3 ? 'compMid' : 'compCool')}">Complacency ${fmtN(C.index,2)} &middot; ${esc(C.note)}</span>`;
      const pay = C.pay_check;
      if (pay && pay.checks.length) {
        const chips = pay.checks.map(x =>
          `<span class="sent ${x.paying ? 'positive' : 'negative'}" title="10-session return">${esc(x.ticker)} ${fmtN(x.ret_pct,1)}%</span>`
        ).join(' ');
        cLine += `<div class="muted small" style="margin-top:5px;">Check &mdash; ${esc(pay.fear_name)} (${fmtN(pay.score,1)}) expected payers: ${chips}</div>`;
      }
    }
    document.getElementById('complacency').innerHTML = cLine;

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
        <td><strong><span class="tick" title="${escA(p.name)}">${p.ticker}</span></strong>${p.leverage > 1 ? `<span class="levBadge">${p.leverage}x</span>` : ''}${isNew.positions[p.ticker] ? '<span class="newTag">NEW</span>' : ''}${p.scheduled_exit ? `<div class="schedTag" title="${escA((p.scheduled_exit.note || p.scheduled_exit.reason))}">SELL SCHEDULED</div>` : ''}</td>
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

  /* ---- theories scorecard (flash-card wheel + plain-table toggle) ---- */
  const thStLabel = st => st==='pending' ? 'PENDING' : st==='right' ? 'RIGHT' : st==='wrong' ? 'WRONG' : st==='abandoned' ? 'ABANDONED' : st.toUpperCase();
  const thStClass = st => st==='pending' ? 'pending' : st==='right' ? 'right' : st==='wrong' ? 'wrong' : st==='abandoned' ? 'abandoned' : st;
  let thWheel = null, thList = [], thView = 'wheel';
  try { thView = localStorage.getItem('stockpicker.main.theories.view') === 'table' ? 'table' : 'wheel'; } catch(e){}
  if (location.hash && location.hash.indexOf('#theory-') === 0) thView = 'table';
  function renderTheoryTable(){
    const clamp = (s, n) => { const t = String(s==null?'':s); return t.length > n ? t.slice(0, n-1).trimEnd() + '…' : t; };
    document.getElementById('tableView').style.display = '';
    const tRows = thList.map(t => {
      const st = t.status;
      const all = (t.evidence||[]).slice().reverse();
      const evs = all.slice(0, 2).map(e => `<div class="ev" title="${escA(e)}">${clamp(e, 140)}</div>`).join('');
      const more = all.length > 2 ? `<div class="ev muted small">+${all.length - 2} more &mdash; see archive</div>` : '';
      return `<tr id="theory-${t.id}">
        <td><span class="badge ${t.tier.toLowerCase()}">${t.tier}</span></td>
        <td><strong>${t.id}</strong></td>
        <td title="${escA(t.title)}">${clamp(t.title, 100)}<div class="thesis" title="${escA(t.tier_reason||'')}">${clamp(t.tier_reason||'', 150)}</div></td>
        <td class="small" title="${escA(t.prediction)}">${clamp(t.prediction, 160)}</td>
        <td><span class="badge ${thStClass(st)}">${thStLabel(st)}</span></td>
        <td>${evs || '<span class="muted small">no evidence yet</span>'}${more}</td>
      </tr>`;
    }).join('');
    document.querySelector('#theoryTable tbody').innerHTML = tRows;
  }
  function applyThView(){
    const wheelOn = thView === 'wheel';
    const stage = document.getElementById('wheelStage');
    const hint = document.getElementById('wheelHint');
    const tableWrap = document.getElementById('tableView');
    const toggle = document.getElementById('viewToggle');
    if (stage) stage.style.display = wheelOn ? '' : 'none';
    if (hint) hint.style.display = wheelOn ? '' : 'none';
    if (tableWrap) tableWrap.style.display = wheelOn ? 'none' : '';
    if (toggle) toggle.textContent = wheelOn ? 'Table view \u2196' : 'Wheel view \u2196';
    if (wheelOn && thWheel) thWheel.setList(thList);
    if (!wheelOn) renderTheoryTable();
  }
  function renderTheories(){
    const tierOrder = {S:0,A:1,B:2,C:3,D:4};
    thList = D.theories
      .filter(t => t.status === 'pending' || t.status === 'paused')
      .slice()
      .sort((a,b) => {
        const ta = tierOrder[a.tier] ?? 5, tb = tierOrder[b.tier] ?? 5;
        return ta - tb || a.id.localeCompare(b.id);
      });
    const tCount = document.getElementById('tCount');
    if (tCount) tCount.textContent = `${thList.length} of ${D.theories.length} theories active`;
    if (!thWheel) {
      thWheel = makeWheel(document.getElementById('wheelStage'), [], { stLabel: thStLabel, stClass: thStClass });
      const toggle = document.getElementById('viewToggle');
      if (toggle) toggle.addEventListener('click', () => {
        thView = thView === 'wheel' ? 'table' : 'wheel';
        try { localStorage.setItem('stockpicker.main.theories.view', thView); } catch(e){}
        applyThView();
      });
    }
    applyThView();
  }

  /* ---- trade events ---- */
  function renderEvents(){
    const evBox = document.getElementById('events');
    if (!D.events.length) evBox.innerHTML = '<div class="muted small">No closed trades yet. Take-profit / stop-loss exits will appear here.</div>';
    else {
      const asof = new Date(D.asof + 'T00:00:00');
      const cutoff = new Date(asof); cutoff.setDate(cutoff.getDate() - 6);
      let evs = D.events.filter(e => new Date(e.date + 'T00:00:00') >= cutoff);
      if (evs.length < 2) evs = D.events.slice(-2);
      evBox.innerHTML = evs.slice().reverse().map(e =>
        `<div class="eventline">
           <div class="evWho"><strong title="${escA(NAME[e.ticker]||e.ticker)}">${e.ticker || 'SYSTEM'}</strong> <span class="muted small">${e.date}${e.ts ? ' &middot; ' + e.ts : ''}</span></div>
           <div><span class="pill ${e.reason==='take_profit'?'tp':(e.reason==='stop_loss'?'sl':(e.reason==='rebalance_recommended'?'warn':'open'))}">${e.reason.toUpperCase()}</span>
           <span class="muted small">@ ${fmtN(e.price)}</span>
           <span class="${cls(e.realized_pnl)}"> ${sign(e.realized_pnl)}</span></div>
           ${e.note ? `<div class="small muted">${e.note}</div>` : ''}
         </div>`
      ).join('');
    }
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

    /* ---- custom feed scrollbar: visible while scrolling, fades on idle ---- */
    const wrap = feedEl.parentElement;
    const thumb = document.getElementById('feedThumb');
    let idleT = null;
    function matchFeedHeight(){
      const mb = el => (parseInt(getComputedStyle(el).marginBottom) || 0);
      const bsPanel = bigEl.closest('.panel');
      const bsH2 = bsPanel ? bsPanel.querySelector('h2') : null;
      const bsHeader = (bsH2 ? bsH2.offsetHeight + mb(bsH2) : 0);
      const bsContent = (bigEl.scrollHeight || 0) + bsHeader;
      const fp = wrap.closest('.panel');
      const fh2 = fp ? fp.querySelector('h2') : null;
      const feedHeader = (fh2 ? fh2.offsetHeight + mb(fh2) : 0);
      const sub = wrap.previousElementSibling;
      const subH = (sub ? sub.offsetHeight + mb(sub) : 0);
      feedEl.style.maxHeight = Math.max(bsContent - feedHeader - subH, 160) + 'px';
    }
    function updFeedBar(){
      const h = feedEl.clientHeight, sh = feedEl.scrollHeight, max = sh - h;
      const show = max > 4;
      thumb.style.display = show ? 'block' : 'none';
      if (!show) return;
      const th = Math.max(24, h * h / sh);
      thumb.style.height = th + 'px';
      thumb.style.top = (feedEl.scrollTop / max) * (h - th) + 'px';
    }
    function pokeFeed(){
      wrap.classList.add('scrolling');
      clearTimeout(idleT);
      idleT = setTimeout(() => wrap.classList.remove('scrolling'), 1100);
    }
    matchFeedHeight();
    feedEl.addEventListener('scroll', () => { updFeedBar(); pokeFeed(); });
    feedEl.addEventListener('wheel', pokeFeed, { passive: true });
    window.addEventListener('resize', () => { matchFeedHeight(); updFeedBar(); });
    updFeedBar();
  }

  /* ---- line chart (vs SPY, zoom/pan, range presets) ---- */
  function initValueChart(){
    const c = document.getElementById('chart'); const ctx = c.getContext('2d');
    const tip = document.getElementById('chartTip');
    const pad = {l:56, r:14, t:16, b:30};
    const H = 280; c.style.height = H+'px';
    const hist = D.history;
    const bmMap = D.benchmarks || {};
    const N = hist.length;
    let W = 0, showSpy = true, view = {i0:0, i1:N-1}, hoverI = -1;
    let bmKey = 'SPY';
    try {
      const saved = localStorage.getItem('stockpicker.chart.bm');
      if (saved && bmMap[saved]) bmKey = saved;
    } catch(e){}
    const bmSel = document.getElementById('bmSelect');
    if (bmSel) bmSel.value = bmKey;

    const statEl = document.getElementById('chartStat');
    if (statEl) statEl.innerHTML =
      `<span>Realized P&L <b class="${cls(s.realized_pnl)}">${sign(s.realized_pnl)}</b></span>` +
      `<span>Max Drawdown <b>${fmtN(s.max_drawdown_pct)}%</b></span>` +
      `<span>Sharpe (ann.) <b>${s.sharpe_annualized===null?'n/a':fmtN(s.sharpe_annualized)}</b></span>`;

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
      const curAl = (bmMap[bmKey] && bmMap[bmKey].aligned) || [];
      let mn = Infinity, mx = -Infinity;
      for(let i=i0;i<=i1;i++){
        const v = hist[i].total_value; if(v<mn)mn=v; if(v>mx)mx=v;
        if(showSpy && curAl[i] && curAl[i].value!==undefined){ const sv=curAl[i].value; if(sv<mn)mn=sv; if(sv>mx)mx=sv; }
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
      // benchmark overlay
      if(showSpy){
        ctx.beginPath(); let started = false;
        for(let i=i0;i<=i1;i++){
          const sv = curAl[i] && curAl[i].value;
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
      if(showSpy && curAl.length){ ctx.fillStyle='#f59e0b'; ctx.fillText(bmKey, pad.l+80, pad.t+11); }
    }

    function setRange(days){
      let i0 = 0;
      if(days !== 0 && String(days) !== '0'){
        let cut;
        if(String(days) === 'ytd') cut = Date.parse(hist[N-1].date.slice(0,4) + '-01-01');
        else cut = Date.parse(hist[N-1].date) - days*86400000;
        for(let i=0;i<N;i++){ if(Date.parse(hist[i].date) >= cut){ i0 = i; break; } }
      }
      view = {i0, i1:N-1};
      document.querySelectorAll('.rangeBtn').forEach(b => b.classList.toggle('active', String(b.dataset.days)===String(days)));
      draw();
    }

    document.querySelectorAll('.rangeBtn').forEach(b =>
      b.addEventListener('click', ()=> setRange(b.dataset.days)));
    if (bmSel) bmSel.addEventListener('change', ev=>{
      bmKey = ev.target.value;
      try { localStorage.setItem('stockpicker.chart.bm', bmKey); } catch(e){}
      draw();
    });

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
      const spy = showSpy && curAl[i] ? curAl[i].value : null;
      tip.innerHTML = `<strong>${h.date}</strong><div>Portfolio: ${fmt$(h.total_value)}</div>` +
        (spy===null||spy===undefined ? '' : `<div style="color:#f59e0b;">${bmKey}: ${fmt$(spy)}</div>`);
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

  /* ---- custom horizontal scrollbar (same style as the news feed) ---- */
  function initHScrollBar(sc, th){
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

  /* ---- AI Sentiment section (D.ai; null = disabled/degraded) ---- */
  function copyText(t){
    if(navigator.clipboard && window.isSecureContext){ navigator.clipboard.writeText(t).catch(()=>{}); return; }
    const ta = document.createElement('textarea');
    ta.value = t; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try{ document.execCommand('copy'); }catch(e){}
    document.body.removeChild(ta);
  }
  function renderAI(){
    const A = D.ai, cfg = D.meta.ai || {};
    const stEl = document.getElementById('aiStatus');
    const subEl = document.getElementById('aiSub');
    const hb = document.getElementById('aiHeartbeat');
    const pr = document.getElementById('aiProposals');
    const mc = document.getElementById('aiMacro');
    const th = document.getElementById('aiTheories');
    const cb = document.getElementById('aiCalib');
    const fp = document.getElementById('aiFearProps');
    const ctl = document.getElementById('aiCtl');
    if(!stEl || !hb) return;
    const model = cfg.provider ? `${String(cfg.provider).toUpperCase()} · ${cfg.model}` : '';
    const stancePill = s => `<span class="stancePill ${s}">${String(s||'neutral').toUpperCase()}</span>`;

    if(!A){
      const degraded = !!cfg.enabled;
      stEl.textContent = degraded ? 'DEGRADED' : 'OFF';
      stEl.className = 'aiBadge ' + (degraded ? 'degraded' : 'off');
      subEl.textContent = degraded ? 'Call failed or verdict invalid — book running on core rules' : 'Flip meta.ai.enabled to activate the layer';
      hb.innerHTML = `<div class="aiSlate">AI Sentiment is ${degraded ? 'degraded' : 'offline'} — the portfolio runs on deterministic price rules (TP/SL, index-referenced vol-halts, no idle cash). The AI layer adds proposals, theory reads and fear blending only when active.${model ? ' · ' + escA(model) : ''}</div>`;
      pr.innerHTML = ''; mc.innerHTML = ''; th.innerHTML = ''; cb.innerHTML = ''; fp.innerHTML = '';
      if(ctl) ctl.style.display = 'none';
      return;
    }

    stEl.textContent = 'ACTIVE';
    stEl.className = 'aiBadge active';
    subEl.textContent = `Last read ${escA(A.asof)} · Tier A grounded (prices, fears, exposures) · Tier B news: display only`;

    /* 0) mode toggle + Execute All (serve.py endpoints; file:// degrades) */
    const mode = A.mode || 'recommend';
    const mkBtn = (id, active) => {
      const b = document.getElementById(id);
      if(b){ b.classList.toggle('active', active); b.dataset.mode = mode; }
      return b;
    };
    mkBtn('modeRecommend', mode === 'recommend');
    mkBtn('modeExecute', mode === 'execute');
    const ea = document.getElementById('execAllBtn');
    if(ea){
      const hasActs = (A.proposals||[]).length > 0 || (A.rotations||[]).length > 0;
      ea.disabled = !hasActs;
      ea.title = hasActs ? 'Turn the current AI proposals + rotations into human-approved pending market orders' : 'No open proposals or rotations to execute';
    }
    async function post(path, body){
      const r = await fetch(path, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: body ? JSON.stringify(body) : undefined,
      });
      if(!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }
    const wireOnce = (el, fn) => {
      if(!el || el.dataset.wired) return;
      el.dataset.wired = '1';
      el.addEventListener('click', fn);
    };
    wireOnce(mkBtn('modeRecommend'), () => setMode('recommend'));
    wireOnce(mkBtn('modeExecute'), () => setMode('execute'));
    wireOnce(ea, async () => {
      ea.disabled = true;
      try{
        const j = await post('/execute_all');
        alert(`Execute All: ${j.created||0} order(s) written to portfolio.json (pending).\n\n` + (j.output||'').slice(-600));
      }catch(e){
        alert('Execute All needs the local server: run `python serve.py` and open http://localhost:8000.');
      }
      location.reload();
    });
    async function setMode(m){
      try{
        const j = await post('/mode', {mode: m});
        if(j.ok){ location.reload(); } else { alert('Mode switch failed:\n' + (j.error || (j.output||'').slice(-400))); }
      }catch(e){
        alert('Mode toggle needs the local server: run `python serve.py` and open http://localhost:8000.');
      }
    }
    if(ctl) ctl.style.display = '';

    /* 1) heartbeat & regime bar */
    const st = A.state || {};
    const G = D.fear_greed || A.gauge;
    const gaugeTxt = G ? `<span class="aiBarItem"><strong>Fear&Greed:</strong> <span class="${G.index>=75?'neg':(G.index<=25?'pos':'')}">${escA(G.label)} (${G.index}/100)</span></span>` : '';
    hb.innerHTML = `
      <div class="aiBar">
        <span class="aiBarItem"><strong>Stance:</strong> ${stancePill(A.macro_stance)}</span>
        <span class="aiBarItem"><strong>Last call:</strong> ${escA(st.last_call_date || '–')}${st.last_call_ts ? ' · ' + escA(st.last_call_ts) : ''}</span>
        <span class="aiBarItem"><strong>Calls today:</strong> ${st.calls_today || 0}/${cfg.max_daily_calls || 3}</span>
        ${gaugeTxt}
        <span class="aiBarItem"><strong>Model:</strong> ${escA(model)}</span>
      </div>
      <div class="muted small" style="margin:6px 0 2px;">${escA(A.summary)}</div>`;
    const modeNote = mode === 'execute'
      ? '<div class="small" style="margin-top:4px;"><span class="pill sl">EXECUTE MODE</span> <span class="muted">AI refresh auto-replaces pending orders with the verdict. Deterministic TP/SL and vol-halts still overrule everything.</span></div>'
      : '<div class="small" style="margin-top:4px;"><span class="pill warn">RECOMMEND MODE</span> <span class="muted">Proposals are advice — nothing becomes an order until you press Execute All. Change mode with the buttons above.</span></div>';
    hb.innerHTML += modeNote;

    /* 2) actionable proposal queue (snooze/dismiss in localStorage) */
    const Q_KEY = 'stockpicker.ai.q1';
    let q = {}; try{ q = JSON.parse(localStorage.getItem(Q_KEY)) || {}; }catch(e){}
    const now = Date.now();
    const pId = p => p.ticker + '|' + A.asof + '|' + p.action;
    const visProps = (A.proposals||[]).filter(p => {
      const id = pId(p);
      if(q.dismiss?.[id]) return false;
      if(q.snooze?.[id] && now < q.snooze[id]) return false;
      return true;
    });
    /* Auto-restore: poll for expired snoozes so cards return without a reload. */
    if(!snoozeTick){
      snoozeTick = setInterval(() => {
        let qq = {}; try{ qq = JSON.parse(localStorage.getItem(Q_KEY)) || {}; }catch(e){}
        const t = Date.now(); const s = qq.snooze || {}; let hit = false;
        Object.keys(s).forEach(id => { if(t >= s[id]){ delete s[id]; hit = true; } });
        if(hit){ localStorage.setItem(Q_KEY, JSON.stringify(qq)); renderAI(); }
      }, 10000);
    }
    const urgCls = p => p.urgency >= 75 ? 'red' : (p.urgency >= 50 ? 'amber' : 'low');
    pr.innerHTML = `
      <h3 class="aiColHead">Actionable Proposals <span class="muted small">(${visProps.length})</span></h3>
      ${visProps.length ? visProps.map(p => `
        <div class="propCard urg${urgCls(p)}" data-id="${escA(pId(p))}">
          <div class="propInner">
            <div class="propFace propFront">
              <div class="propTop">
                <span class="pill ${p.action==='add'||p.action==='buy'?'tp':'sl'}">${String(p.action).toUpperCase()}</span>
                <strong class="tick">${escA(p.ticker)}</strong>
                <span class="muted small">conv ${p.conviction_score>0?'+':''}${fmtN(p.conviction_score,2)}</span>
                <span class="urgTag urg${urgCls(p)}">URGENCY ${p.urgency}/100</span>
              </div>
              <div class="small muted" style="margin:6px 0;">${escA(p.rationale)}</div>
              <div class="aiBtns">
                <button class="aiBtn" data-act="copy">Review &amp; Copy Order</button>
                <button class="aiBtn ghost" data-act="snooze">Snooze (temp 1m)</button>
                <button class="aiBtn ghost" data-act="dismiss">Dismiss</button>
              </div>
            </div>
            <div class="propFace propBack">
              <strong>Dismiss this proposal?</strong>
              <div class="small muted" style="margin:6px 0;">It disappears from this page (and stays gone on reload) until the next data refresh.</div>
              <div class="aiBtns">
                <button class="aiBtn" data-act="dismiss-yes">Yes, Dismiss</button>
                <button class="aiBtn ghost" data-act="dismiss-no">Keep</button>
              </div>
            </div>
          </div>
        </div>`).join('')
      : '<div class="muted small">No open proposals. Low-urgency (&lt;50) reads stay silent — see the ledger below.</div>'}`;
    const rotRows = (A.rotations||[]).map(r => `
      <div class="rotRow">
        <span class="pill sl">SELL</span> <strong class="tick">${escA(r.sell)}</strong>
        <span class="rotArrow">&#8594;</span>
        <span class="pill tp">BUY</span> <strong class="tick">${escA(r.buy)}</strong>
        <span class="small muted" style="margin-left:8px;">${escA(r.rationale)}</span>
      </div>`).join('');
    pr.innerHTML += (rotRows ? `
      <h3 class="aiColHead" style="margin-top:12px;">Rotations <span class="muted small">(paired sell&#8594;buy, engine sizes both legs)</span></h3>
      ${rotRows}` : '');
    pr.querySelectorAll('.aiBtn').forEach(btn => {
      const card = btn.closest('.propCard');
      const id = card.dataset.id;
      btn.addEventListener('click', () => {
        const p = (A.proposals||[]).find(x => pId(x) === id);
        if(!p) return;
        const act = btn.dataset.act;
        if(act === 'copy'){
          copyText(`REVIEW: ${p.action.toUpperCase()} ${p.ticker} (conviction ${p.conviction_score}, urgency ${p.urgency}) — ${p.rationale} — Human confirmation required. No autonomous execution.`);
        } else if(act === 'snooze'){
          (q.snooze = q.snooze || {})[id] = now + 60*1000; // TEMP: 1min for verification (revert to 24*3600*1000)
          localStorage.setItem(Q_KEY, JSON.stringify(q)); renderAI();
        } else if(act === 'dismiss'){
          card.classList.add('flipped');
        } else if(act === 'dismiss-yes'){
          (q.dismiss = q.dismiss || {})[id] = true;
          localStorage.setItem(Q_KEY, JSON.stringify(q)); renderAI();
        } else if(act === 'dismiss-no'){
          card.classList.remove('flipped');
        }
      });
    });

    /* 3) macro stance + sector convictions + two-witness fear table */
    const sectRows = (A.sector_bias||[]).map(s => {
      const w = Math.round((s.conviction + 1) / 2 * 100);
      return `<div class="sectRow"><span class="sectName" title="${escA(s.driver)}">${escA(s.sector)}</span>
        <div class="sectBar"><div class="sectFill ${s.conviction>=0?'pos':'neg'}" style="width:${w}%;"></div></div>
        <span class="sectVal ${s.conviction>0.1?'pos':(s.conviction<-0.1?'neg':'muted')}">${s.conviction>0?'+':''}${fmtN(s.conviction,2)} ${String(s.stance).toUpperCase()}</span></div>`;
    }).join('');
    mc.innerHTML = `
      <h3 class="aiColHead">Macro &amp; Sector Convictions ${stancePill(A.macro_stance)}</h3>
      <div class="muted small" style="margin-bottom:8px;">AI witness on fears (AI score &middot; blended &middot; trend) is merged into the Market Fear Gauge panel above &mdash; news feed stays display-only</div>
      ${sectRows || '<div class="muted small">No sector reads this run.</div>'}`;

    /* 4) theory evolution ledger (AI reads — evidence only, no status changes) */
    const thRows = (A.theories||[]).map(t => `
      <tr>
        <td class="tick">${escA(t.id)}</td>
        <td><span class="pill ${t.verdict==='affirm'?'tp':(t.verdict==='abandon'?'sl':'warn')}">${String(t.verdict).toUpperCase()}</span></td>
        <td>${t.confidence}%</td>
        <td class="small">${escA(t.evidence)}</td>
      </tr>`).join('');
    th.innerHTML = `
      <h3 class="aiColHead">Theory Evolution <span class="muted small">(AI reads — deterministic rules override, status changes need human confirmation)</span></h3>
      <table class="aiFearTable">
        <thead><tr><th>Theory</th><th>AI Verdict</th><th>Confidence</th><th>Evidence</th></tr></thead>
        <tbody>${thRows || '<tr><td colspan="4" class="muted small">No theory reads this run.</td></tr>'}</tbody>
      </table>`;

    /* 4b) AI fear proposals (staged in the editable fear_scenarios.json) */
    const fprops = A.fear_proposals || [];
    if(fp){
      fp.innerHTML = fprops.length ? `
        <h3 class="aiColHead">Fear Scenario Proposals <span class="pill warn">PENDING REVIEW</span></h3>
        <div class="muted small" style="margin-bottom:6px;">The AI suggested these new crash scenarios — staged in fear_scenarios.json and NOT scored until you clear each entry's <code>pending_review</code> flag (and write its components).</div>
        ${fprops.map(f => `
          <div class="fpRow">
            <strong>${escA(f.id)}</strong> <span class="pill ${f.type==='structural'?'warn':'tp'}">${String(f.type).toUpperCase()}</span>
            <span class="tick">${escA(f.name)}</span>
            <div class="small muted">${escA(f.note||'')}</div>
            ${(f.watch_signals||[]).length ? `<div class="small muted">watch: ${f.watch_signals.map(escA).join(' &middot; ')}</div>` : ''}
            ${(f.hedge_ticks||[]).length ? `<div class="small muted">hedges: ${f.hedge_ticks.map(escA).join(' &middot; ')}</div>` : ''}
          </div>`).join('')}`
      : '';
    }

    /* 5) calibration & safety monitor (the trust engine) */
    const led = A.ledger || [];
    const calib = A.calibration || {};
    const calibRows = Object.keys(calib).map(tk => {
      const c = calib[tk];
      const rate = c.total ? Math.round(c.wrong / c.total * 100) : 0;
      return `<span class="calibBadge ${rate >= 50 ? 'neg' : (c.wrong >= 2 ? 'amber' : '')}" title="wrong ${c.wrong}/${c.total} verdicts${c.last_wrong ? ' · last ' + escA(c.last_wrong) : ''}">${escA(tk)} ${c.wrong}/${c.total} wrong</span>`;
    }).join(' ');
    const volHalts = (D.positions||[]).filter(p => p.status==='closed' && p.exit && p.exit.state==='vol_halt' && !p.exit.reentry_resolved).length;
    cb.innerHTML = `
      <h3 class="aiColHead">Calibration &amp; Safety Monitor</h3>
      <div class="calibGrid">
        <div>
          <div class="calibHead">AI TRACK RECORD</div>
          <div class="small" style="margin:6px 0;">Verdicts logged: <strong>${led.length}</strong> (rolling 28)</div>
          <div class="small" style="margin-bottom:4px;">Stance history:</div>
          <div style="margin-bottom:6px;">${led.map(l => `<span class="stancePill ${l.macro_stance}" title="${escA(l.date)}">${String(l.macro_stance).toUpperCase()}</span>`).join(' ') || '<span class="muted small">seeding track record…</span>'}</div>
          <div class="small" style="margin-bottom:4px;">Directionally wrong convictions <span class="muted">(confidence starts discounted — fed to the next prompt):</span></div>
          <div>${calibRows || '<span class="muted small">No wrong calls recorded yet.</span>'}</div>
        </div>
        <div>
          <div class="calibHead">DETERMINISTIC GUARDRAILS (UN-BYPASSABLE)</div>
          <div class="small" style="margin:6px 0;">Active vol-halts: <strong>${volHalts}</strong>${volHalts ? ' <span class="neg">— re-entry protocol engaged</span>' : ''}</div>
          <div class="small">TP/SL engine: <strong>active</strong> · No idle cash: <strong>SGOV-parked</strong></div>
          <div class="small">News (Tier B): <strong>display-only</strong>${cfg.news_to_sentiment ? ' — WARNING: feeding decisions' : ''}</div>
        </div>
      </div>`;
  }

  /* ---- market orders (D.orders; pending + recent executed) ---- */
  function renderOrders(){
    const el = document.getElementById('ordersSection');
    if(!el) return;
    const O = D.orders || [];
    if(!O.length){ el.style.display = 'none'; return; }
    el.style.display = '';
    const pending = O.filter(o => o.status === 'pending');
    const executed = O.filter(o => o.status !== 'pending');
    document.getElementById('ordersSub').innerHTML =
      `${pending.length} pending &middot; ${executed.length} executed (last ${executed.length})`;
    const mode = (D.ai && D.ai.mode) || 'recommend';
    const noteEl = document.getElementById('ordersNote');
    if(noteEl){
      noteEl.innerHTML = mode === 'execute'
        ? 'Human-approved orders. Executed at the live price on the next market-open run. <span class="pill sl">EXECUTE MODE</span> — AI refresh auto-replaces pending orders with each new verdict.'
        : 'Human-approved orders. Executed at the live price on the next market-open run. <span class="pill warn">RECOMMEND MODE</span> — orders are only written when you press <strong>Execute All</strong> on the AI panel.';
    }
    document.getElementById('ordersList').innerHTML = O.map(o => {
      const isBuy = o.action === 'buy';
      const pill = o.status === 'pending'
        ? `<span class="pill warn">PENDING</span>`
        : `<span class="pill ${isBuy ? 'tp' : 'sl'}">EXECUTED</span>`;
      const meta = o.status === 'executed'
        ? `<div class="small muted">exec ${o.exec_date} @ ${fmtN(o.exec_price)} &middot; ${fmtN(o.shares)} sh &middot; ${o.realized_pnl ? 'pnl '+sign(o.realized_pnl) : ''}</div>`
        : `<div class="small muted">created ${o.created} &middot; ${escA(o.source||'')}</div>`;
      return `<div class="orderRow">
        <span class="orderTicker">${o.ticker}</span>
        <span class="orderAct ${isBuy ? 'pos' : 'neg'}">${isBuy ? 'BUY' : 'SELL'}</span>
        <span class="orderAmt">${fmt$(o.amount)}</span>
        <div class="orderNote">${escA(o.note||'')}${meta}</div>
        ${pill}
      </div>`;
    }).join('');
  }

  /* ---- invoke every section renderer in DOM order ---- */
  renderCards();
  renderFears();
  renderAI();
  renderOrders();
  renderPositions();
  renderSectors();
  renderTheories();
  renderEvents();
  renderSleeves();
  renderNews();
  initValueChart();
  initDonut();
  initHScrollBar(document.querySelector('#posTable').closest('.scroll'), document.getElementById('posHThumb'));
  initHScrollBar(document.querySelector('#theoryTable').closest('.scroll'), document.getElementById('theoryHThumb'));
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
