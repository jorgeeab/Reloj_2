/* Widget: energies (controles de energías X/A/Bomba) */
(function(){
  function factory(ctx){
    let refs = null;
    const clamp = (v, lo, hi)=> Math.max(lo, Math.min(hi, Number(v)||0));
    const recomputeModo = ()=>{
      const xm = document.getElementById('chk_manual_x');
      const am = document.getElementById('chk_manual_a');
      const bitX = xm && xm.checked ? 1 : 0;
      const bitA = am && am.checked ? 2 : 0;
      return bitX | bitA;
    };
    function bind(){
      refs = {
        ex: document.getElementById('wg_en_x'),
        ea: document.getElementById('wg_en_a'),
        eb: document.getElementById('wg_en_b'),
        exo: document.getElementById('wg_en_x_o'),
        eao: document.getElementById('wg_en_a_o'),
        ebo: document.getElementById('wg_en_b_o')
      };
      const apply = async ()=>{
        if(!refs) return;
        const vx = clamp(refs.ex.value, -255, 255);
        const va = clamp(refs.ea.value, -255, 255);
        const vb = clamp(refs.eb.value, 0, 255);
        if(refs.exo) refs.exo.textContent = String(vx);
        if(refs.eao) refs.eao.textContent = String(va);
        if(refs.ebo) refs.ebo.textContent = String(vb);
        await ctx.sendControl({ energies: { x: vx, a: va, bomba: vb }, modo: recomputeModo() });
      };
      const debounce = (fn, ms)=>{ let t=null; return ()=>{ if(t) clearTimeout(t); t=setTimeout(fn, ms); }; };
      const debApply = debounce(apply, 120);
      if(refs.ex){ refs.ex.addEventListener('input', ()=>{ if(refs.exo) refs.exo.textContent=refs.ex.value; debApply(); }); }
      if(refs.ea){ refs.ea.addEventListener('input', ()=>{ if(refs.eao) refs.eao.textContent=refs.ea.value; debApply(); }); }
      if(refs.eb){ refs.eb.addEventListener('input', ()=>{ if(refs.ebo) refs.ebo.textContent=refs.eb.value; debApply(); }); }
    }
    return {
      initControl: bind,
      onTelemetry({ snapshot }){
        try{
          if(!snapshot || !refs) return;
          const en = snapshot.energies || {};
          if(refs.ex && typeof en.x==='number') refs.ex.value = String(en.x);
          if(refs.ea && typeof en.a==='number') refs.ea.value = String(en.a);
          if(refs.eb && typeof en.bomba==='number') refs.eb.value = String(en.bomba);
          if(refs.exo && typeof en.x==='number') refs.exo.textContent = String(en.x);
          if(refs.eao && typeof en.a==='number') refs.eao.textContent = String(en.a);
          if(refs.ebo && typeof en.bomba==='number') refs.ebo.textContent = String(en.bomba);
        }catch{}
      }
    };
  }
  if(typeof window !== 'undefined' && window.RelojWidgets){
    window.RelojWidgets.register('energies', factory);
  }
})();

