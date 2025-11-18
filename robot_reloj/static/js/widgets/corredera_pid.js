/* Widget: corredera_pid (PID X) */
(function(){
  function factory(ctx){
    function buildSettings(){
      const card = document.getElementById('cfg_corredera');
      if(!card) return;
      const btn = card.querySelector('#wg_apply_pid_x');
      if(btn){ btn.addEventListener('click', async ()=>{
        const kp = Number(card.querySelector('#wg_kpX').value||0);
        const ki = Number(card.querySelector('#wg_kiX').value||0);
        const kd = Number(card.querySelector('#wg_kdX').value||0);
        try{
          await ctx.ControlChannel.send({ pid_settings: { pidX: { kp, ki, kd } } });
          if(typeof ctx.jpost==='function'){
            await ctx.jpost('/api/settings', { kpX: kp, kiX: ki, kdX: kd });
          }
          ctx.toast && ctx.toast('PID X aplicado');
        }catch{ ctx.toast && ctx.toast('Error PID X'); }
      }); }
      const mmInput = card.querySelector('#wg_steps_mm');
      const cmOutput = card.querySelector('#wg_steps_cm');
      const syncCm = ()=>{ try{ const v=Number(mmInput&&mmInput.value||0); if(cmOutput){ cmOutput.value = String((v*10).toFixed(3)); } }catch{} };
      if(mmInput){ mmInput.addEventListener('input', syncCm); }
      syncCm();
      const btnSteps = card.querySelector('#wg_apply_steps_mm');
      if(btnSteps){ btnSteps.addEventListener('click', async ()=>{
        try{
          const steps_mm = Number((card.querySelector('#wg_steps_mm')||{}).value||0);
          await ctx.ControlChannel.send({ calibration: { steps_mm } });
          if(typeof ctx.jpost==='function'){
            await ctx.jpost('/api/settings', { steps_mm });
          }
          ctx.toast && ctx.toast('pasos/mm aplicado');
        }catch{ ctx.toast && ctx.toast('Error pasos/mm'); }
      }); }
    }
    function getDefault(sel, fallback){ try{ const el=document.querySelector(sel); const v=Number(el&&el.value); return Number.isFinite(v)?String(v):String(fallback); }catch{ return String(fallback); } }
    function buildControl(){
      const host = document.getElementById('wg_ctrl_corredera');
      if(!host) return;
      const box = document.createElement('div');
      box.className = 'row';
      box.style.gap = '8px';
      box.innerHTML = `
        <button type="button" id="wg_x_home">Home X</button>
        <button type="button" id="wg_x_zero">Ir a 0</button>`;
      host.appendChild(box);
      const btnHome = box.querySelector('#wg_x_home');
      const btnZero = box.querySelector('#wg_x_zero');
      if(btnHome){ btnHome.addEventListener('click', async ()=>{ try{ await ctx.sendControl({ reset_x: 1 }); ctx.toast && ctx.toast('Homing X'); }catch{} }); }
      if(btnZero){ btnZero.addEventListener('click', async ()=>{ try{ await ctx.sendControl({ setpoints: { x_mm: 0 }, modo: 0 }); ctx.toast && ctx.toast('X=0'); }catch{} }); }
      const gear = document.getElementById('gear_x');
      if(gear && typeof ctx.openSettings==='function'){
        gear.addEventListener('click', ()=> ctx.openSettings('cfg_corredera'));
      }
      // Manual + energía X dentro del widget
      const manual = document.getElementById('wg_x_manual');
      const en = document.getElementById('wg_en_x');
      const out = document.getElementById('wg_en_x_o');
      const recomputeModo = ()=> (manual && manual.checked ? 1 : 0);
      if(manual){
        manual.addEventListener('change', async ()=>{
          try{ await ctx.sendControl({ modo: recomputeModo() }); }catch{}
        });
      }
      if(en){
        en.addEventListener('input', async ()=>{
          if(out) out.textContent = en.value;
          // Si el usuario usa energía, activar manual automáticamente cuando |value|>0
          try{
            const v = Number(en.value||0) || 0;
            if(manual){ manual.checked = Math.abs(v) > 0; }
            const gx = document.getElementById('chk_manual_x'); if(gx){ gx.checked = !!(manual && manual.checked); }
            await ctx.sendControl({ energies: { x: v }, modo: recomputeModo() });
          }catch{}
        });
      }
    }
    function updateGearTooltip(snapshot){
      try{
        const gear = document.getElementById('gear_x');
        if(!gear) return;
        const s = snapshot || (ctx.getStatus && ctx.getStatus());
        const kp = (s && s.kpX!=null) ? Number(s.kpX) : Number((document.getElementById('wg_kpX')||{}).value||0);
        const ki = (s && s.kiX!=null) ? Number(s.kiX) : Number((document.getElementById('wg_kiX')||{}).value||0);
        const kd = (s && s.kdX!=null) ? Number(s.kdX) : Number((document.getElementById('wg_kdX')||{}).value||0);
        gear.title = `PID X: kp=${kp.toFixed(2)} ki=${ki.toFixed(2)} kd=${kd.toFixed(2)}`;
      }catch{}
    }
    return {
      initSettings(){ buildSettings(); updateGearTooltip(); },
      initControl: buildControl,
      onTelemetry({ snapshot }){
        updateGearTooltip(snapshot);
        try{
          const s = snapshot || {};
          const mm = document.getElementById('wg_steps_mm');
          if(mm){
            const v = (s.steps_mm!=null) ? Number(s.steps_mm) : (s.pasosPorMM!=null? Number(s.pasosPorMM): null);
            if(v!=null) mm.value = String(v);
          }
          const cm = document.getElementById('wg_steps_cm'); if(cm){ const v = Number(mm && mm.value || 0); cm.value = String((v*10).toFixed(3)); }
          const manual = document.getElementById('wg_x_manual');
          if(manual && typeof s.modo==='number'){ manual.checked = !!(s.modo & 1); }
          const en = document.getElementById('wg_en_x'); const out = document.getElementById('wg_en_x_o');
          const val = (s.energies && typeof s.energies.x==='number') ? Number(s.energies.x) : null;
          if(en && val!=null){ en.value = String(val); if(out) out.textContent = String(val); }
        }catch{}
      }
    };
  }
  if(typeof window !== 'undefined' && window.RelojWidgets){
    window.RelojWidgets.register('corredera_pid', factory);
  }
})();
