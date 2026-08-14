/**
 * theories.js — renders the Theory Archive (theories.html).
 *
 * Reads the same AUTO-GENERATED dashboard.js (window.DASH) as app.js and
 * lists EVERY theory, including abandoned ones. Filters: status, tier,
 * free-text search across title / prediction / id / tier_reason / evidence.
 *
 * No changes here affect the main dashboard; it is a pure archive view.
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
    const ST_STATUS = ['pending', 'paused', 'right', 'wrong', 'abandoned'];
    const ST_TIERS = ['S', 'A', 'B', 'C', 'D'];
    const stLabel = st => st==='pending' ? 'PENDING' : st==='right' ? 'RIGHT' : st==='wrong' ? 'WRONG' : st==='abandoned' ? 'ABANDONED' : st.toUpperCase();
    const stClass = st => st==='pending' ? 'pending' : st==='right' ? 'right' : st==='wrong' ? 'wrong' : st==='abandoned' ? 'abandoned' : st;

    let fStatus = null, fTier = null, fQ = '';

    document.getElementById('asof').textContent = D.asof || '&mdash;';

    function buildButtons(holder, opts, onChange) {
      const wrap = document.getElementById(holder);
      wrap.innerHTML = opts.map(o =>
        `<button class="rangeBtn fBtn ${o === null ? 'active' : ''}" data-v="${o === null ? '' : o}">${o === null ? 'All' : o}</button>`
      ).join('');
      wrap.querySelectorAll('.fBtn').forEach(b => b.addEventListener('click', () => {
        wrap.querySelectorAll('.fBtn').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        onChange(b.dataset.v === '' ? null : b.dataset.v);
        renderRows();
      }));
    }
    buildButtons('statusFilters', ST_STATUS, v => fStatus = v);
    buildButtons('tierFilters', ST_TIERS, v => fTier = v);

    document.getElementById('tSearch').addEventListener('input', e => {
      fQ = e.target.value.trim().toLowerCase();
      renderRows();
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

    function renderRows() {
      const tierOrder = {S:0,A:1,B:2,C:3,D:4};
      const list = D.theories.filter(matches).slice().sort((a, b) => {
        const ta = tierOrder[a.tier] ?? 5, tb = tierOrder[b.tier] ?? 5;
        return ta - tb || a.id.localeCompare(b.id);
      });
      document.getElementById('tCount').textContent =
        `${list.length} of ${D.theories.length} theories`;
      document.querySelector('#theoryTable tbody').innerHTML = list.map(t => {
        const st = t.status;
        const evs = (t.evidence || []).slice().reverse().map(e => `<div class="ev">${e}</div>`).join('');
        return `<tr id="theory-${t.id}">
          <td><span class="badge ${t.tier.toLowerCase()}">${t.tier}</span></td>
          <td><strong>${t.id}</strong></td>
          <td>${escA(t.title)}<div class="thesis">${escA(t.tier_reason || '')}</div></td>
          <td class="small">${escA(t.prediction)}</td>
          <td><span class="badge ${stClass(st)}">${stLabel(st)}</span></td>
          <td>${evs || '<span class="muted small">no evidence yet</span>'}</td>
        </tr>`;
      }).join('');
    }
    renderRows();
  }
})();
