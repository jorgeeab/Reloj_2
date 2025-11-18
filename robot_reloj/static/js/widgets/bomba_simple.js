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
        userOverrideFlow: false,
        estActive: false,
        estVol: 0,
        lastTs: 0
      };

      // Stepper buttons: click + hold-to-repeat support
      const buttons = refs.wrap.querySelectorAll('[data-fw-step]');
      const applyStep = (btn)=>{
        const isFlow = (btn.dataset.target === 'flow');
        const b = isFlow ? limits.flow : limits.volume;
        const input = isFlow ? refs.flow : refs.volume;
        const step = Number(btn.dataset.fwStep || 0);
        if(!Number.isFinite(step) || step === 0) return;
        const next = clamp(getInputNumber(input) + step, b.min, b.max);
        input.value = fmt(next, b.precision);
        input.dispatchEvent(new Event('change'));
      };
      // Hold behavior: start repeating only after a longer press
      const HOLD_DELAY = 650;      // ms to start repeating
      const HOLD_INTERVAL = 300;   // ms between repeats (slower)
      buttons.forEach(btn=>{
        // Simple click
        btn.addEventListener('click', ()=> applyStep(btn));
        // Hold repeat
        let holdTimer = null;
        let repeatTimer = null;
        const clearTimers = ()=>{ if(holdTimer){ clearTimeout(holdTimer); holdTimer=null; } if(repeatTimer){ clearInterval(repeatTimer); repeatTimer=null; } };
        btn.addEventListener('pointerdown', ev=>{
          ev.preventDefault();
          try{ btn.setPointerCapture(ev.pointerId); }catch{}
          // Do not apply immediately on press; only start after HOLD_DELAY
          holdTimer = setTimeout(()=>{ repeatTimer = setInterval(()=> applyStep(btn), HOLD_INTERVAL); }, HOLD_DELAY);
        });
        const release = (ev)=>{
          clearTimers();
          if(ev && ev.pointerId!=null){ try{ btn.releasePointerCapture(ev.pointerId); }catch{} }
        };
        btn.addEventListener('pointerup', release);
        btn.addEventListener('pointercancel', release);
        btn.addEventListener('pointerleave', clearTimers);
        btn.addEventListener('lostpointercapture', clearTimers);
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
        // Leer valores objetivo desde inputs
        const vIn = clamp(getInputNumber(refs.volume), limits.volume.min, limits.volume.max);
        const f = clamp(getInputNumber(refs.flow), limits.flow.min, limits.flow.max);

        // Objetivo ABSOLUTO (volumen total requerido)
        const vTargetAbs = vIn;

        // Reflejar en UI el objetivo absoluto que usaremos
        setTarget('volume', vTargetAbs);
        setTarget('flow', f);

        // Preparar bandera de sensor de flujo según snapshot para no forzar configuración inesperada
        let usarSensor = 0;
        try{
          const s = (ctx.getStatus && ctx.getStatus()) || null;
          if(s && typeof s.usarSensorFlujo !== 'undefined') usarSensor = Number(!!s.usarSensorFlujo);
        }catch{}

        // Evitar doble envío accidental
        refs.start.disabled = true;
        try{
          await ctx.ControlChannel.send({
            setpoints: { volumen_ml: vTargetAbs },
            flow: { caudal_bomba_mls: f, usar_sensor_flujo: usarSensor },
            energies: { bomba: 200 }
          });
          try{ ctx.debug && ctx.debug({ bomba:'ejecutar', volumen_ml:vTargetAbs, caudal_mls:f, usar_sensor:usarSensor }); }catch{}
          ctx.toast && ctx.toast('Ejecución iniciada');
        }catch{
          ctx.toast && ctx.toast('Error');
        }finally{
          refs.start.disabled = false;
        }
      });
      refs.stop.addEventListener('click', async ()=>{
        setTarget('flow', 0);
        try{
          await ctx.ControlChannel.send({ flow: { caudal_bomba_mls: 0 }, energies: { bomba: 0 } });
          try{ ctx.debug && ctx.debug({ bomba:'detener' }); }catch{}
          ctx.toast && ctx.toast('Detenido');
        }catch{ ctx.toast && ctx.toast('Error'); }
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
        const s = data.snapshot || {};
        const now = Number(data.nowMs || Date.now());
        const usarSensor = !!(s && s.usarSensorFlujo);
        const energiaBomba = (s && s.energies && typeof s.energies.bomba==='number') ? Number(s.energies.bomba) : 0;
        const caudalCfg = Number((s && s.caudalBombaMLs!=null)?s.caudalBombaMLs:(state.targetFlow||0));
          if(!usarSensor && energiaBomba>0 && caudalCfg>0){
            if(!state.estActive){
              state.estActive = true;
              state.estVol = Number(s && s.volumen_ml!=null ? s.volumen_ml : (data.volumeActual!=null? data.volumeActual : 0));
              state.lastTs = now;
              try{ ctx.debug && ctx.debug({ bomba:'estimacion_local_on', base: state.estVol, caudal: caudalCfg }); }catch{}
            }else{
              const dt = Math.max(0, (now - (state.lastTs||now))/1000);
              state.lastTs = now;
              state.estVol += caudalCfg * dt;
              if(Number.isFinite(state.targetVolume)) state.estVol = Math.min(state.estVol, state.targetVolume);
            }
            state.lastVolumeActual = state.estVol;
            try{ window._ui_est_vol = state.estVol; }catch{}
          }else{
            if(state.estActive){ try{ ctx.debug && ctx.debug({ bomba:'estimacion_local_off' }); }catch{} }
            state.estActive = false;
            state.lastTs = now;
            if(Number.isFinite(data.volumeActual)) state.lastVolumeActual = Number(data.volumeActual);
            else if(s && s.volumen_ml!=null) state.lastVolumeActual = Number(s.volumen_ml);
            try{ window._ui_est_vol = null; }catch{}
          }
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
