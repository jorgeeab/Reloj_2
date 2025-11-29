/* Widget: acciones_rapidas (agua/home/paro y homing/reset) */
(function(){
  function factory(ctx){
    function bind(){
      const byId = (id)=> document.getElementById(id);
      const btnHX = byId('wg_btn_home_x');
      const btnHA = byId('wg_btn_home_a');
      const btnReset = byId('wg_btn_reset_all');
      const btnHome = byId('wg_btn_home');
      const btnStop = byId('wg_btn_stop');
      if(btnHX){ btnHX.addEventListener('click', async ()=>{ try{ await ctx.sendControl({ reset_x:1 }); ctx.toast && ctx.toast('Homing X'); }catch{} }); }
      if(btnHA){ btnHA.addEventListener('click', async ()=>{ try{ await ctx.sendControl({ reset_a:1 }); ctx.toast && ctx.toast('Homing A'); }catch{} }); }
      if(btnReset){ btnReset.addEventListener('click', async ()=>{ try{ await ctx.sendControl({ reset_x:1, reset_a:1, reset_volumen:1 }); ctx.toast && ctx.toast('Reset X+A+Volumen'); }catch{} }); }
      if(btnHome){ btnHome.addEventListener('click', async ()=>{ try{ await ctx.jpost('/api/home',{}); ctx.toast && ctx.toast('Home enviado'); }catch{ ctx.toast && ctx.toast('Error home'); } }); }
      if(btnStop){ btnStop.addEventListener('click', async ()=>{ try{ await ctx.jpost('/api/stop',{}); ctx.toast && ctx.toast('PARO'); }catch{ ctx.toast && ctx.toast('Error paro'); } }); }
    }
    return { initControl: bind };
  }
  if(typeof window !== 'undefined' && window.RelojWidgets){
    window.RelojWidgets.register('acciones_rapidas', factory);
  }
})();

