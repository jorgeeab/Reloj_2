// Bootstrap stub so widget modules can register before main reloj.js is loaded
(function(){
  if(typeof window === 'undefined') return;
  if(window.RelojWidgets) return; // already present
  const queue = [];
  window.__WIDGET_QUEUE__ = queue;
  window.RelojWidgets = {
    register(name, factory){ queue.push({ name, factory }); },
    // no-op placeholders until reloj.js upgrades this object
    _mods: [], initAll(){}, broadcast(){}, get(){ return null; }
  };
})();

