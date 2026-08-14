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
    let lockAxis = null, startY = 0, lastT = 0, lastX = 0, velX = 0;

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
        el.classList.toggle('front', d === 0);
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

    /* ---- drag / swipe ----
       Mouse + pen drive via pointer events; touch drives via NATIVE touch
       events (pointer events are unreliable on mobile — browsers can
       withhold or cancel them depending on where the finger lands).
       The stage's touch-action:pan-y lets the browser own vertical
       gestures (page scroll); we claim horizontal ones with preventDefault
       the moment the gesture commits to the horizontal axis, so the
       browser can never steal or cancel them.
       Fast flicks advance by velocity; dragging past CATCH of the card gap
       brings the next card to the front WHILE dragging (carousel catch,
       re-anchors and can chain through several cards in one drag). */
    const SLOP = 8;          // px of travel before committing to an axis
    const FLICK = 0.35;      // px/ms release velocity that counts as a flick
    const CATCH = 0.45;      // fraction of the gap that triggers the catch
    const CATCH_COOLDOWN = 150; // ms a catch must wait before another can fire
    let touchId = null;
    let caught = false;      // gesture already advanced via the carousel catch
    let lastCatch = 0;       // performance.now() of the last catch

    function startDrag(x, y) {
      dragging = true;
      suppressClick = false;
      caught = false;
      lockAxis = null;
      dragStart = dragPos = x;
      startY = y;
      lastT = performance.now(); lastX = x; velX = 0;
      stage.classList.add('dragging');
    }
    function moveDrag(x, y, ts) {
      if (!dragging) return;
      const dx = x - dragStart;
      const dy = y - startY;
      if (!lockAxis) {
        if (Math.abs(dx) < SLOP && Math.abs(dy) < SLOP) return;
        lockAxis = Math.abs(dx) > Math.abs(dy) ? 'h' : 'v';
        if (lockAxis === 'v') { endDrag(); return; }   // browser scrolls the page
        suppressClick = true;
      }
      if (lockAxis !== 'h') return;
      dragPos = x;
      dragX = dx;
      if (ts > lastT) velX = (x - lastX) / (ts - lastT);
      lastT = ts; lastX = x;
      layout();
      const gap = spacing();
      const now = performance.now();
      if (dragX < -gap * CATCH && now - lastCatch > CATCH_COOLDOWN) { goTo(focus + 1); caught = true; lastCatch = now; dragStart = x; dragX = 0; }
      else if (dragX > gap * CATCH && now - lastCatch > CATCH_COOLDOWN) { goTo(focus - 1); caught = true; lastCatch = now; dragStart = x; dragX = 0; }
    }
    function finishDrag() {
      if (!dragging) return;
      const gap = spacing();
      endDrag();
      if (!caught && Math.abs(velX) > FLICK) goTo(focus + (velX < 0 ? 1 : -1));
      else if (dragX < -gap * 0.28) goTo(focus + 1);
      else if (dragX > gap * 0.28) goTo(focus - 1);
      else { dragX = 0; layout(); }
    }
    function endDrag() {
      dragging = false;
      lockAxis = null;
      touchId = null;
      stage.classList.remove('dragging');
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', finishDrag);
      window.removeEventListener('pointercancel', onPointerCancel);
    }

    /* pointer path (mouse + pen) */
    stage.addEventListener('pointerdown', e => {
      if (e.pointerType === 'touch') return;
      if (dragging || e.target.closest('.wheelBtn')) return;
      startDrag(e.clientX, e.clientY);
      window.addEventListener('pointermove', onPointerMove);
      window.addEventListener('pointerup', finishDrag);
      window.addEventListener('pointercancel', onPointerCancel);
    });
    function onPointerMove(e) {
      if (e.pointerType === 'touch') return;
      moveDrag(e.clientX, e.clientY, e.timeStamp);
    }
    function onPointerCancel() {
      if (lockAxis === 'h') return;   // never abandon an owned horizontal drag
      endDrag();
    }

    /* touch path (phones / tablets) */
    stage.addEventListener('touchstart', e => {
      if (dragging || e.target.closest('.wheelBtn')) return;
      const t = e.changedTouches[0];
      touchId = t.identifier;
      startDrag(t.clientX, t.clientY);
    }, { passive: true });
    stage.addEventListener('touchmove', e => {
      let t = null;
      for (const c of e.changedTouches) if (c.identifier === touchId) { t = c; break; }
      if (!t) return;
      moveDrag(t.clientX, t.clientY, performance.now());
      if (lockAxis === 'h') e.preventDefault();   // browser must not steal the drag
    }, { passive: false });
    stage.addEventListener('touchend', e => {
      let t = null;
      for (const c of e.changedTouches) if (c.identifier === touchId) { t = c; break; }
      if (!t) return;
      touchId = null;
      finishDrag();
    }, { passive: true });
    stage.addEventListener('touchcancel', () => { endDrag(); }, { passive: true });

    /* ---- wheel scroll + keys + buttons ----
       Both axes rotate the deck: vertical wheel/trackpad scroll and
       horizontal swipes (deltaX) are claimed with preventDefault so the
       browser can never pan the page sideways from the stage. */
    stage.addEventListener('wheel', e => {
      const dx = e.deltaX, dy = e.deltaY;
      if (Math.abs(dx) === 0 && Math.abs(dy) === 0) return;
      e.preventDefault();
      const now = Date.now();
      if (now - wheelLock < 400) return;
      wheelLock = now;
      if (Math.abs(dy) >= Math.abs(dx)) goTo(focus + (dy > 0 ? 1 : -1));
      else goTo(focus + (dx > 0 ? 1 : -1));
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