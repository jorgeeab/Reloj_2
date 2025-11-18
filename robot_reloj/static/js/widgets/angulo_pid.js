/* Widget: angulo_pid (PID Ángulo) */
(function(){
  function factory(ctx){
    function buildSettings(){
      const card = document.getElementById('cfg_angulo');
      if(!card) return;
      const btn = card.querySelector('#wg_apply_pid_a');
      if(btn){ btn.addEventListener('click', async ()=>{
        const kp = Number(card.querySelector('#wg_kpA').value||0);
        const ki = Number(card.querySelector('#wg_kiA').value||0);
        const kd = Number(card.querySelector('#wg_kdA').value||0);
        try{
          await ctx.ControlChannel.send({ pid_settings: { pidA: { kp, ki, kd } } });
          if(typeof ctx.jpost==='function'){
            await ctx.jpost('/api/settings', { kpA: kp, kiA: ki, kdA: kd });
          }
          ctx.toast && ctx.toast('PID A aplicado');
        }catch{ ctx.toast && ctx.toast('Error PID A'); }
      }); }
      const btnSteps = card.querySelector('#wg_apply_steps_deg');
      if(btnSteps){ btnSteps.addEventListener('click', async ()=>{
        try{
          const steps_deg = Number((card.querySelector('#wg_steps_deg')||{}).value||0);
          const z = Number((card.querySelector('#wg_z_mm_por_grado')||{}).value||1);
          await ctx.ControlChannel.send({ calibration: { steps_deg } });
          await ctx.ControlChannel.send({ z_mm_por_grado: z });
          if(typeof ctx.jpost==='function'){
            await ctx.jpost('/api/settings', { steps_deg, z_mm_por_grado: z });
          }
          ctx.toast && ctx.toast('Calibración aplicada');
        }catch{ ctx.toast && ctx.toast('Error calibración'); }
      }); }
    }
    function getDefault(sel, fallback){ try{ const el=document.querySelector(sel); const v=Number(el&&el.value); return Number.isFinite(v)?String(v):String(fallback); }catch{ return String(fallback); } }
    function buildControl(){
      const host = document.getElementById('wg_ctrl_angulo');
      if(!host) return;
      const box = document.createElement('div');
      box.className = 'row';
      box.style.gap = '8px';
      box.innerHTML = `
        <button type="button" id="wg_a_home">Home A</button>
        <button type="button" id="wg_a_zero">Ir a 0°</button>`;
      host.appendChild(box);
      const btnHome = box.querySelector('#wg_a_home');
      const btnZero = box.querySelector('#wg_a_zero');
      if(btnHome){ btnHome.addEventListener('click', async ()=>{ try{ await ctx.sendControl({ reset_a: 1 }); ctx.toast && ctx.toast('Homing A'); }catch{} }); }
      if(btnZero){ btnZero.addEventListener('click', async ()=>{ try{ await ctx.sendControl({ setpoints: { a_deg: 0 }, modo: 0 }); ctx.toast && ctx.toast('A=0°'); }catch{} }); }
      // Manual + energía A
      const manual = document.getElementById('wg_a_manual');
      const en = document.getElementById('wg_en_a');
      const out = document.getElementById('wg_en_a_o');
      const recomputeModo = ()=> (manual && manual.checked ? 2 : 0); // bit A
      if(manual){ manual.addEventListener('change', async ()=>{ try{ await ctx.sendControl({ modo: recomputeModo() }); }catch{} }); }
      if(en){ en.addEventListener('input', async ()=>{ if(out) out.textContent = en.value; try{ await ctx.sendControl({ energies: { a: Number(en.value||0) }, modo: recomputeModo() }); }catch{} }); }
    }
    function attachGear(){
      const gear = document.getElementById('gear_a');
      if(gear && typeof ctx.openSettings==='function'){
        gear.addEventListener('click', ()=> ctx.openSettings('cfg_angulo'));
      }
    }
    function updateGearTooltip(snapshot){
      try{
        const gear = document.getElementById('gear_a');
        if(!gear) return;
        const s = snapshot || (ctx.getStatus && ctx.getStatus());
        const kp = (s && s.kpA!=null) ? Number(s.kpA) : Number((document.getElementById('wg_kpA')||{}).value||0);
        const ki = (s && s.kiA!=null) ? Number(s.kiA) : Number((document.getElementById('wg_kiA')||{}).value||0);
        const kd = (s && s.kdA!=null) ? Number(s.kdA) : Number((document.getElementById('wg_kdA')||{}).value||0);
        gear.title = `PID A: kp=${kp.toFixed(2)} ki=${ki.toFixed(2)} kd=${kd.toFixed(2)}`;
      }catch{}
    }
    return {
      initSettings(){ buildSettings(); updateGearTooltip(); },
      initControl(){ buildControl(); attachGear(); },
      onTelemetry({ snapshot }){
        updateGearTooltip(snapshot);
        try{
          const s = snapshot || {};
          const manual = document.getElementById('wg_a_manual');
          if(manual && typeof s.modo==='number'){ manual.checked = !!(s.modo & 2); }
          const en = document.getElementById('wg_en_a'); const out = document.getElementById('wg_en_a_o');
          const val = (s.energies && typeof s.energies.a==='number') ? Number(s.energies.a) : null;
          if(en && val!=null){ en.value = String(val); if(out) out.textContent = String(val); }
          const sd = document.getElementById('wg_steps_deg');
          if(sd){
            const v = (s.steps_deg!=null) ? Number(s.steps_deg) : (s.pasosPorGrado!=null? Number(s.pasosPorGrado): null);
            if(v!=null) sd.value = String(v);
          }
          const z = document.getElementById('wg_z_mm_por_grado');
          if(z && s && s.z_mm_por_grado!=null){ z.value = String(Number(s.z_mm_por_grado)); }
        }catch{}
      }
    };
  }
  if(typeof window !== 'undefined' && window.RelojWidgets){
    window.RelojWidgets.register('angulo_pid', factory);
  }
})();
