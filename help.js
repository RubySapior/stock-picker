"use strict";

/* Help page: toggle between the Simple notes and the Advanced math. */
(function(){
  const tabs = document.querySelectorAll('.helpTab');
  if(!tabs.length) return;
  const simple = document.getElementById('helpSimple');
  const adv = document.getElementById('helpAdvanced');
  function show(name){
    tabs.forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    if(simple) simple.style.display = name === 'simple' ? '' : 'none';
    if(adv) adv.style.display = name === 'advanced' ? '' : 'none';
  }
  tabs.forEach(b => b.addEventListener('click', () => show(b.dataset.tab)));
})();