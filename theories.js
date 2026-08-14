/**
 * theories.js — renders the Theory Archive (theories.html) as a flash-card
 * wheel.
 *
 * Reads the same AUTO-GENERATED dashboard.js (window.DASH) as app.js and
 * lists EVERY theory, including abandoned ones. Browse like a character
 * select: the focused card sits front-and-center, neighbours peek at the
 * edges, and drag / wheel / arrows / buttons move the camera. Click a card
 * to flip it and read the evidence log.
 *
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
    const escA = v => String(v==null?'':v).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const ST_STATUS = ['pending', 'paused', 'right', 'wrong', 'abandoned'];
    const ST_TIERS = ['S', 'A', 'B', 'C', 'D'];
    const stLabel = st => st==='pending' ? 'PENDING' : st==='right' ? 'RIGHT' : st==='wrong' ? 'WRONG' : st==='abandoned' ? 'ABANDONED' : st.toUpperCase();
    const stClass = st => st==='pending' ? 'pending' : st==='right' ? 'right' : st==='wrong' ? 'wrong' : st==='abandoned' ? 'abandoned' : st;

    const stage = document.getElementById('wheelStage');
    const wheel = document.getElementById('wheel');
    const counter = document.getElementById('wCounter');
    let list = [];          // filtered theories
    let focus = 0;          // index of the front card
    let dragX = 0, dragging = false, dragStart = 0, dragPos = 0;

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
      wheel.innerHTML = '';
      list.forEach(t => wheel.appendChild(buildCard(t)));
      focus = 0;
      layout();
    }

    function buildCard(t) {
      const el = document.createElement('div');
      el.className = 'card';
      el.innerHTML =
        `<div class="cardInner">
         <div class="face front">
           <div class="cTop">
             <span class="cTier ${t.tier.toLowerCase()}">${t.tier}</span>
             <span class="cId">${t.id}</span>
             <span class="badge ${stClass(t.status)}">${stLabel(t.status)}</span>
           </div>
           <div class="cTitle">${escA(t.title)}</div>
           <div class="cPred">${escA(t.prediction)}</div>
           <div class="cFoot muted small">created ${escA(t.created)}${t.last_updated && t.last_updated !== t.created ? ' &middot; updated ' + escA(t.last_updated) : ''}</div>
         </div>
         <div class="face back">
           <div class="cTop">
             <span class="cId">${t.id}</span>
             <span class="badge ${stClass(t.status)}">${stLabel(t.status)}</span>
           </div>
           <div class="cSection">Thesis</div>
           <div class="cThesis">${escA(t.tier_reason || 'no thesis recorded')}</div>
           <div class="cSection">Evidence log</div>
           <div class="cEvs">${(t.evidence||[]).length ? (t.evidence||[]).slice().reverse().map(e => `<div class="ev">${escA(e)}</div>`).join('') : '<span class="muted small">no evidence yet</span>'}</div>
         </div>
       </div>`;
      el.addEventListener('click', () => {
        if (suppressClick) { suppressClick = false; return; }
        const i = list.indexOf(t);
        if (i === focus) el.classList.toggle('flipped');
        else goTo(i);
      });
      return el;
    }

    /* ---- wheel layout ---- */
    function spacing() {
      const w = stage.clientWidth;
      return Math.min(320, Math.max(110, w * 0.30));
    }
    function layout() {
      const gap = spacing();
      const listEl = wheel.children;
      for (let i = 0; i < list.length; i++) {
        const el = listEl[i];
        const d = i - focus;
        const x = d * gap + dragX;
        const scale = 1 - Math.min(Math.abs(d), 3) * 0.14;
        const tilt = Math.max(-18, Math.min(18, d * -10));
        el.style.transform = `translate(-50%,-50%) translateX(${x}px) scale(${scale}) rotateY(${tilt}deg)`;
        el.style.opacity = Math.abs(d) <= 1 ? 1 : (Math.abs(d) === 2 ? 0.30 : 0);
        el.style.zIndex = 100 - Math.abs(d);
        el.classList.toggle('dim', Math.abs(d) === 2);
      }
      counter.textContent = list.length ? `${focus + 1} / ${list.length}` : '0 / 0';
    }
    function goTo(i) {
      i = Math.max(0, Math.min(list.length - 1, i));
      focus = i;
      dragX = 0;
      document.querySelectorAll('.card').forEach(c => c.classList.remove('flipped'));
      layout();
    }

    /* ---- pointer drag / swipe (no capture: card clicks must stay intact) ---- */
    let suppressClick = false;
    stage.addEventListener('pointerdown', e => {
      if (e.target.closest('.wheelBtn')) return;
      dragging = true;
      suppressClick = false;
      dragStart = dragPos = e.clientX;
      stage.classList.add('dragging');
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
      window.addEventListener('pointercancel', onUp);
    });
    function onMove(e) {
      if (!dragging) return;
      dragPos = e.clientX;
      if (Math.abs(dragPos - dragStart) > 6) suppressClick = true;
      dragX = dragPos - dragStart;
      layout();
    }
    function onUp() {
      if (!dragging) return;
      dragging = false;
      stage.classList.remove('dragging');
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      const gap = spacing();
      if (dragX < -gap * 0.28) goTo(focus + 1);
      else if (dragX > gap * 0.28) goTo(focus - 1);
      else { dragX = 0; layout(); }
    }

    /* ---- wheel + keys + buttons ---- */
    let wheelLock = 0;
    stage.addEventListener('wheel', e => {
      if (e.deltaY === 0) return;
      e.preventDefault();
      const now = Date.now();
      if (now - wheelLock < 90) return;
      wheelLock = now;
      goTo(focus + (e.deltaY > 0 ? 1 : -1));
    }, { passive: false });
    window.addEventListener('keydown', e => {
      if (e.key === 'ArrowRight') goTo(focus + 1);
      else if (e.key === 'ArrowLeft') goTo(focus - 1);
      else if (e.key === 'Escape') document.querySelectorAll('.card').forEach(c => c.classList.remove('flipped'));
    });
    document.getElementById('wPrev').addEventListener('click', () => goTo(focus - 1));
    document.getElementById('wNext').addEventListener('click', () => goTo(focus + 1));

    window.addEventListener('resize', layout);
    applyFilters();
  }
})();
