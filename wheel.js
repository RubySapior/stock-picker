/**
 * wheel.js — shared flash-card wheel (used by theories.html archive and the
 * main-page Theories Scorecard).
 *
 * makeWheel(stage, list, opts) renders the deck into a `.wheelStage` element
 * and wires drag / swipe / wheel / keys / prev-next / counter. Click the
 * front card to flip it and read the thesis + evidence log.
 *
 * opts: { stLabel, stClass } — status text/class helpers (defaults to plain
 * uppercase with no class).
 */
"use strict";

(function () {
  const escA = v => String(v==null?'':v).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

  function makeWheel(stage, list, opts) {
    opts = opts || {};
    const stLabel = opts.stLabel || (st => st.toUpperCase());
    const stClass = opts.stClass || (() => '');
    const wheel = stage.querySelector('.wheel') || (() => { const d = document.createElement('div'); d.className = 'wheel'; stage.appendChild(d); return d; })();
    const counter = stage.querySelector('.wheelCounter') || (() => { const d = document.createElement('div'); d.className = 'wheelCounter'; stage.appendChild(d); return d; })();
    const prev = stage.querySelector('.wheelBtn.prev');
    const next = stage.querySelector('.wheelBtn.next');

    let focus = 0;
    let dragX = 0, dragging = false, dragStart = 0, dragPos = 0, suppressClick = false, wheelLock = 0;

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
      wheel.querySelectorAll('.card').forEach(c => c.classList.remove('flipped'));
      layout();
    }

    function setList(newList) {
      list = newList;
      wheel.innerHTML = '';
      list.forEach(t => wheel.appendChild(buildCard(t)));
      focus = 0;
      dragX = 0;
      layout();
    }

    /* ---- pointer drag / swipe (no capture: card clicks must stay intact) ---- */
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

    /* ---- wheel scroll + keys + buttons ---- */
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
      else if (e.key === 'Escape') wheel.querySelectorAll('.card').forEach(c => c.classList.remove('flipped'));
    });
    if (prev) prev.addEventListener('click', () => goTo(focus - 1));
    if (next) next.addEventListener('click', () => goTo(focus + 1));

    window.addEventListener('resize', layout);
    setList(list);
    return { setList, goTo };
  }

  window.makeWheel = makeWheel;
})();