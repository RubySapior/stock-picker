/**
 * theories.js — renders the Theory Archive (theories.html): every theory
 * ever recorded (pending / paused / right / wrong / abandoned) as a
 * flash-card wheel (shared wheel.js) with a plain-table toggle.
 *
 * Reads the same AUTO-GENERATED dashboard.js (window.DASH) as app.js.
 * Filters (status, tier, free-text search) shrink the deck; the wheel always
 * snaps back to index 0 when the deck changes.
 */
"use strict";

(function () {
  var s = document.createElement('script');
  s.src = 'dashboard.js?t=' + new Date().getTime();
  s.onload = init;
  document.head.appendChild(s);

  function init() {
    const D = window.DASH;
    const verEl = document.getElementById('verLine');
    if (verEl && D.meta && D.meta.version) {
      verEl.textContent = 'UI v' + D.meta.version.site + ' \u00b7 Engine v' + D.meta.version.algo;
    }
    const escA = v => String(v==null?'':v).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const ST_STATUS = ['pending', 'paused', 'right', 'wrong', 'abandoned'];
    const ST_TIERS = ['S', 'A', 'B', 'C', 'D'];
    const stLabel = st => st==='pending' ? 'PENDING' : st==='right' ? 'RIGHT' : st==='wrong' ? 'WRONG' : st==='abandoned' ? 'ABANDONED' : st.toUpperCase();
    const stClass = st => st==='pending' ? 'pending' : st==='right' ? 'right' : st==='wrong' ? 'wrong' : st==='abandoned' ? 'abandoned' : st;

    const stage = document.getElementById('wheelStage');
    const tableWrap = document.getElementById('tableView');
    const viewToggle = document.getElementById('viewToggle');
    const hintEl = document.getElementById('wheelHint');
    let list = [];
    const VIEW_KEY = 'stockpicker.theories.view';
    let view = 'wheel';
    try { view = localStorage.getItem(VIEW_KEY) === 'table' ? 'table' : 'wheel'; } catch(e) {}

    const wheel = makeWheel(stage, [], { stLabel, stClass });
    document.getElementById('asof').textContent = D.asof || '';

    /* ---- filters ---- */
    let fStatus = null, fTier = null, fQ = '';
    function buildButtons(holder, opts, onChange) {
      const wrap = document.getElementById(holder);
      wrap.innerHTML = opts.map(o =>
        `<button class="rangeBtn fBtn ${o === null ? 'active' : ''}" data-v="${o === null ? '' : o}">${o === null ? 'All' : o}</button>`
      ).join('');
      wrap.querySelectorAll('.fBtn').forEach(b => b.addEventListener('click', () => {
        wrap.querySelectorAll('.fBtn').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        onChange(b.dataset.v === '' ? null : b.dataset.v);
        applyFilters();
      }));
    }
    buildButtons('statusFilters', ST_STATUS, v => fStatus = v);
    buildButtons('tierFilters', ST_TIERS, v => fTier = v);
    document.getElementById('tSearch').addEventListener('input', e => {
      fQ = e.target.value.trim().toLowerCase();
      applyFilters();
    });

    function matches(t) {
      if (fStatus && t.status !== fStatus) return false;
      if (fTier && t.tier !== fTier) return false;
      if (fQ) {
        const hay = [t.id, t.title, t.prediction, t.tier_reason || '', (t.evidence || []).join(' ')]
          .join(' ').toLowerCase();
        if (!hay.includes(fQ)) return false;
      }
      return true;
    }

    /* ---- deck rebuild ---- */
    function applyFilters() {
      const tierOrder = {S:0,A:1,B:2,C:3,D:4};
      list = D.theories.filter(matches).slice().sort((a, b) => {
        const ta = tierOrder[a.tier] ?? 5, tb = tierOrder[b.tier] ?? 5;
        return ta - tb || a.id.localeCompare(b.id);
      });
      document.getElementById('tCount').textContent =
        `${list.length} of ${D.theories.length} theories`;
      if (view === 'wheel') wheel.setList(list); else renderTable();
    }

    /* ---- plain table view (easy copy-paste) ---- */
    function renderTable() {
      tableWrap.style.display = '';
      document.querySelector('#theoryTable tbody').innerHTML = list.map(t => {
        const evs = (t.evidence||[]).slice().reverse().map(e => `<div class="ev">${escA(e)}</div>`).join('');
        return `<tr id="theory-${t.id}">
          <td><span class="badge ${t.tier.toLowerCase()}">${t.tier}</span></td>
          <td><strong>${t.id}</strong></td>
          <td>${escA(t.title)}<div class="thesis">${escA(t.tier_reason || '')}</div></td>
          <td class="small">${escA(t.prediction)}</td>
          <td><span class="badge ${stClass(t.status)}">${stLabel(t.status)}</span></td>
          <td>${evs || '<span class="muted small">no evidence yet</span>'}</td>
        </tr>`;
      }).join('');
    }

    function applyView() {
      const wheelOn = view === 'wheel';
      stage.style.display = wheelOn ? '' : 'none';
      hintEl.style.display = wheelOn ? '' : 'none';
      tableWrap.style.display = wheelOn ? 'none' : '';
      viewToggle.textContent = wheelOn ? 'Table view \u2196' : 'Wheel view \u2196';
      if (list.length && wheelOn) wheel.setList(list);
      if (list.length && !wheelOn) renderTable();
    }
    viewToggle.addEventListener('click', () => {
      view = view === 'wheel' ? 'table' : 'wheel';
      try { localStorage.setItem(VIEW_KEY, view); } catch(e) {}
      applyView();
    });

    window.addEventListener('resize', () => { if (view === 'wheel') wheel.setList(list); });
    applyView();
  }
})();