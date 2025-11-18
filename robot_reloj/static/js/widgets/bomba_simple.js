/* Widget: bomba_simple (control de flujo/volumen) */
(function(){
  function factory(ctx){
    let refs = null;
    let limits = null;
    let state = null;

    function clamp(v, lo, hi){ return Math.min(hi, Math.max(lo, Number.isFinite(v)?v:lo)); }
    function fmt(v, p){ return Number(v).toFixed(p); }

    function getInputNumber(input){ const n = Number(input && input.value); return Number.isFinite(n) ? n : 0; }

    function refreshStats(){
      if(!refs) return;
      if(refs.flowActual){ refs.flowActual.textContent = (state.lastFlowActual==null? '—' : `${fmt(state.lastFlowActual, limits.flow.precision)} ml/s`); }
      if(refs.volumeActual){ refs.volumeActual.textContent = (state.lastVolumeActual==null? '—' : `${fmt(state.lastVolumeActual, limits.volume.precision)} ml`); }
      if(refs.flowTarget){ refs.flowTarget.textContent = `${fmt(state.targetFlow, limits.flow.precision)} ml/s`; }
      if(refs.volumeTarget){ refs.volumeTarget.textContent = `${fmt(state.targetVolume, limits.volume.precision)} ml`; }
      if(refs.volumeRemaining){
        const rem = (Number.isFinite(state.targetVolume) && Number.isFinite(state.lastVolumeActual))
          ? Math.max(0, state.targetVolume - state.lastVolumeActual)
          : null;
        refs.volumeRemaining.textContent = rem==null? '—' : `${fmt(rem, limits.volume.precision)} ml`;
      }
    }

    function setTarget(kind, value, { fromTelemetry = false } = {}){
      const isFlow = kind === 'flow';
      const b = isFlow ? limits.flow : limits.volume;
      const val = clamp(Number(value), b.min, b.max);
      if(isFlow){ state.targetFlow = val; if(refs.flow){ refs.flow.value = fmt(val, b.precision); } }
      else { state.targetVolume = val; if(refs.volume){ refs.volume.value = fmt(val, b.precision); } }
      if(!fromTelemetry){ if(isFlow) state.userOverrideFlow = true; else state.userOverrideVolume = true; }
      refreshStats();
    }

    function adoptTelemetry(kind, value){
      if(kind === 'flow'){ if(state.userOverrideFlow) return; }
      else { if(state.userOverrideVolume) return; }
      setTarget(kind, value, { fromTelemetry: true });
    }

    function wireControls(){
      const w = document.getElementById('flow_widget');
      if(!w){ return; }
      refs = {
        wrap: w,
        volume: document.getElementById('fw_volume'),
        flow: document.getElementById('fw_flow'),
        start: document.getElementById('fw_start'),
        stop: document.getElementById('fw_stop'),
        reset: document.getElementById('fw_reset'),
        flowActual: document.getElementById('fw_flow_actual'),
        flowTarget: document.getElementById('fw_flow_target'),
        volumeActual: document.getElementById('fw_volume_actual'),
        volumeTarget: document.getElementById('fw_volume_target'),
        volumeRemaining: document.getElementById('fw_volume_remaining')
      };
      if(!refs.volume || !refs.flow || !refs.start || !refs.stop){ return; }
      limits = {
        volume: { min: Number(refs.volume.min||0), max: Number(refs.volume.max||2000), precision: 0 },
        flow: { min: Number(refs.flow.min||0), max: Number(refs.flow.max||40), precision: 1 }
      };
      state = {
        targetVolume: clamp(getInputNumber(refs.volume), limits.volume.min, limits.volume.max),
        targetFlow: clamp(getInputNumber(refs.flow), limits.flow.min, limits.flow.max),
        lastVolumeActual: null,
        lastFlowActual: null,
        userOverrideVolume: false,
        userOverrideFlow: false
      };

      const buttons = refs.wrap.querySelectorAll('.fw-btn');
      buttons.forEach(btn=>{
        btn.addEventListener('click', ()=>{
          const isFlow = (btn.dataset.target === 'flow');
          const b = isFlow ? limits.flow : limits.volume;
          const input = isFlow ? refs.flow : refs.volume;
          const step = Number(btn.dataset.step || (isFlow?0.5:1));
          const delta = btn.dataset.dir === 'inc' ? +step : -step;
          const next = clamp(getInputNumber(input) + delta, b.min, b.max);
          input.value = fmt(next, b.precision);
          input.dispatchEvent(new Event('change'));
        });
      });

      // Bind inputs
      const bind = (input, kind)=>{
        const isFlow = (kind === 'flow');
        const b = isFlow ? limits.flow : limits.volume;
        input.addEventListener('input', ()=>{
          setTarget(kind, getInputNumber(input));
        });
        input.addEventListener('change', async ()=>{
          const val = clamp(getInputNumber(input), b.min, b.max);
          setTarget(kind, val);
          if(isFlow){
            await ctx.ControlChannel.send({ flow: { caudal_bomba_mls: val } });
          }else{
            await ctx.ControlChannel.send({ setpoints: { volumen_ml: val } });
          }
        });
      };
      bind(refs.flow, 'flow');
      bind(refs.volume, 'volume');

      refs.start.addEventListener('click', async ()=>{
        const v = clamp(getInputNumber(refs.volume), limits.volume.min, limits.volume.max);
        const f = clamp(getInputNumber(refs.flow), limits.flow.min, limits.flow.max);
        setTarget('volume', v);
        setTarget('flow', f);
        try{ await ctx.ControlChannel.send({ setpoints: { volumen_ml: v }, flow: { caudal_bomba_mls: f } }); ctx.toast && ctx.toast('Ejecución iniciada'); }catch{ ctx.toast && ctx.toast('Error'); }
      });
      refs.stop.addEventListener('click', async ()=>{
        setTarget('flow', 0);
        try{ await ctx.ControlChannel.send({ flow: { caudal_bomba_mls: 0 } }); ctx.toast && ctx.toast('Detenido'); }catch{ ctx.toast && ctx.toast('Error'); }
      });
      if(refs.reset){
        refs.reset.addEventListener('click', async ()=>{
          try{ await ctx.ControlChannel.send({ reset_volumen: 1 }); ctx.toast && ctx.toast('Volumen reiniciado'); }catch{ ctx.toast && ctx.toast('Error'); }
        });
      }

      // Gear
      const gear = document.getElementById('gear_bomba');
      if(gear && typeof ctx.openSettings==='function'){
        gear.addEventListener('click', ()=> ctx.openSettings('cfg_bomba'));
      }
      refreshStats();
    }

    return {
      initControl(){ wireControls(); },
      initSettings(){
        const card = document.getElementById('cfg_bomba');
        if(!card) return;
        const btnStop = card.querySelector('#wg_bomba_stop');
        const btnReset = card.querySelector('#wg_bomba_reset');
        if(btnStop) btnStop.addEventListener('click', async ()=>{ try{ await ctx.ControlChannel.send({ flow: { caudal_bomba_mls: 0 } }); ctx.toast && ctx.toast('Detenido'); }catch{} });
        if(btnReset) btnReset.addEventListener('click', async ()=>{ try{ await ctx.ControlChannel.send({ reset_volumen: 1 }); ctx.toast && ctx.toast('Volumen reiniciado'); }catch{} });
        const chk = card.querySelector('#wg_chk_sensor_flujo');
        const caudal = card.querySelector('#wg_caudal');
        const apply = card.querySelector('#wg_btn_apply_flujo');
        if(apply){
          apply.addEventListener('click', async ()=>{
            try{
              await ctx.ControlChannel.send({ flow: {
                usar_sensor_flujo: chk && chk.checked ? 1 : 0,
                caudal_bomba_mls: Number(caudal && caudal.value || 0)
              } });
              if(typeof ctx.jpost==='function'){
                await ctx.jpost('/api/settings', {
                  usar_sensor_flujo: chk && chk.checked ? 1 : 0,
                  caudal_bomba_mls: Number(caudal && caudal.value || 0)
                });
              }
              ctx.toast && ctx.toast('Ajustes de flujo aplicados');
            }catch{ ctx.toast && ctx.toast('Error aplicando flujo'); }
          });
        }
      },
      onTelemetry(data){
        if(!state || !data) return;
        if(Number.isFinite(data.flowActual)) state.lastFlowActual = Number(data.flowActual);
        if(Number.isFinite(data.volumeActual)) state.lastVolumeActual = Number(data.volumeActual);
        if(Number.isFinite(data.flowTarget)) adoptTelemetry('flow', data.flowTarget);
        if(Number.isFinite(data.volumeTarget)) adoptTelemetry('volume', data.volumeTarget);
        try{
          const gear = document.getElementById('gear_bomba');
          if(gear){
            const txt = `Vol objetivo=${Number.isFinite(state.targetVolume)?state.targetVolume.toFixed(limits.volume.precision):'—'} ml; `+
                        `Flow objetivo=${Number.isFinite(state.targetFlow)?state.targetFlow.toFixed(limits.flow.precision):'—'} ml/s`;
            gear.title = `Bomba: ${txt}`;
          }
        }catch{}
        // Actualizar ajustes de flujo en Settings si existen
        try{
          const s = data.snapshot || null;
          const chk = document.getElementById('wg_chk_sensor_flujo');
          const caudal = document.getElementById('wg_caudal');
          if(s){
            if(chk && s.usarSensorFlujo!=null){ chk.checked = !!s.usarSensorFlujo; }
            if(caudal && s.caudalBombaMLs!=null){ caudal.value = String(Number(s.caudalBombaMLs)); }
          }
        }catch{}
        refreshStats();
      }
    };
  }

  if(typeof window !== 'undefined' && window.RelojWidgets){
    window.RelojWidgets.register('bomba_simple', factory);
  }
})();
