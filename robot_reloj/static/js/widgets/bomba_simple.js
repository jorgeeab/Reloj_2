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
        toggle: document.getElementById('fw_toggle'),
        reset: document.getElementById('fw_reset'),
        flowActual: document.getElementById('fw_flow_actual'),
        flowTarget: document.getElementById('fw_flow_target'),
        volumeActual: document.getElementById('fw_volume_actual'),
        volumeTarget: document.getElementById('fw_volume_target'),
        volumeRemaining: document.getElementById('fw_volume_remaining')
      };
      if(!refs.volume || !refs.flow || !refs.toggle){ return; }
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
        lastTs: 0,
        running: false,
        autoResetDone: false,
        autoStopDone: false,
        completeHold: 0
      };

      const updateRunUI = (running, completed=false)=>{
        state.running = !!running;
        const btn = refs.toggle;
        if(!btn) return;
        btn.textContent = running ? 'Detener' : (completed ? 'Empezar de nuevo' : 'Ejecutar');
        try{ btn.classList.toggle('warn', !!running); }catch{}
      };

      // Stepper buttons: solo click simple (sin mantener presionado)
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
      buttons.forEach(btn=>{
        btn.addEventListener('click', ()=> applyStep(btn));
      });

      // Bind inputs
      const bind = (input, kind)=>{
        const isFlow = (kind === 'flow');
        const b = isFlow ? limits.flow : limits.volume;
        input.addEventListener('input', ()=>{
          setTarget(kind, getInputNumber(input));
        });
        input.addEventListener('change', async ()=>{
          const valRaw = clamp(getInputNumber(input), b.min, b.max);
          if(isFlow){
            setTarget('flow', valRaw);
            if(state.running){
              await ctx.ControlChannel.send({ flow: { flow_target_mls: valRaw } });
            }
          }else{
            // Si está ejecutando, tratamos el valor como "restante"
            const base = state.running ? (Number.isFinite(state.lastVolumeActual) ? Number(state.lastVolumeActual) : 0) : 0;
            const absTarget = state.running ? (base + valRaw) : valRaw;
            setTarget('volume', absTarget);
            if(state.running){
              await ctx.ControlChannel.send({ setpoints: { volumen_ml: absTarget } });
            }
          }
        });
      };
      bind(refs.flow, 'flow');
      bind(refs.volume, 'volume');

      async function startRun(){
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
        refs.toggle.disabled = true;
        try{
          await ctx.ControlChannel.send({
            setpoints: { volumen_ml: vTargetAbs },
            flow: { flow_target_mls: f, usar_sensor_flujo: usarSensor },
            execute: 1
          });
          // Activar estimación inmediata (por si la telemetría tarda)
          try{
            const s = (ctx.getStatus && ctx.getStatus()) || null;
            state.estActive = true;
            state.lastTs = Date.now();
            const base = s && s.volumen_ml!=null ? Number(s.volumen_ml) : (state.lastVolumeActual!=null?Number(state.lastVolumeActual):0);
            state.estVol = Number.isFinite(base) ? base : 0;
            state.lastVolumeActual = state.estVol;
          }catch{}
          try{ ctx.debug && ctx.debug({ bomba:'ejecutar', volumen_ml:vTargetAbs, caudal_mls:f, usar_sensor:usarSensor }); }catch{}
          state.autoResetDone = false;
          state.autoStopDone = false;
          state.completeHold = 0;
          updateRunUI(true, false);
          ctx.toast && ctx.toast('Ejecución iniciada');
        }catch{
          ctx.toast && ctx.toast('Error');
        }finally{
          refs.toggle.disabled = false;
        }
      }
      async function stopRun(){
        setTarget('flow', 0);
        try{
          await ctx.ControlChannel.send({ flow: { flow_target_mls: 0 }, energies: { bomba: 0 }, execute: 0 });
          try{ ctx.debug && ctx.debug({ bomba:'detener' }); }catch{}
          updateRunUI(false, false);
          ctx.toast && ctx.toast('Detenido');
        }catch{ ctx.toast && ctx.toast('Error'); }
      }
      refs.toggle.addEventListener('click', async ()=>{
        if(state.running){ await stopRun(); } else { await startRun(); }
      });
      if(refs.reset){
        refs.reset.addEventListener('click', async ()=>{
          // Cancelar ejecución y reiniciar volumen y objetivo
          const payload = {
            reset_volumen: 1,
            setpoints: { volumen_ml: 0 },
            flow: { caudal_bomba_mls: 0 },
            energies: { bomba: 0 }
          };
          try{
            await ctx.ControlChannel.send(payload);
            // Sincronizar estado UI inmediatamente
            state.userOverrideVolume = false;
            state.targetVolume = 0;
            state.lastVolumeActual = 0;
            if(refs.volume){ refs.volume.value = fmt(0, limits.volume.precision); }
            updateRunUI(false, false);
            state.autoStopDone = false;
            state.completeHold = 0;
            refreshStats();
            try{ ctx.debug && ctx.debug({ bomba:'reset_volumen' }); }catch{}
            ctx.toast && ctx.toast('Volumen reiniciado');
          }catch{
            ctx.toast && ctx.toast('Error');
          }
        });
      }

      // Gear
      const gear = document.getElementById('gear_bomba');
      if(gear && typeof ctx.openSettings==='function'){
        gear.addEventListener('click', ()=> ctx.openSettings('cfg_bomba'));
      }
      try{
        const snap = ctx.getStatus && ctx.getStatus();
        if(snap){
          if(Number.isFinite(snap.volumen_ml)) state.lastVolumeActual = Number(snap.volumen_ml);
          if(Number.isFinite(snap.caudal_est_mls) || Number.isFinite(snap.flow_est)){
            const fv = Number.isFinite(snap.caudal_est_mls)?Number(snap.caudal_est_mls):Number(snap.flow_est||0);
            state.lastFlowActual = fv;
          }
          if(Number.isFinite(snap.volumen_objetivo_ml)) state.targetVolume = Number(snap.volumen_objetivo_ml);
          refreshStats();
        }
      }catch{}
      updateRunUI(false, false);
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
              const deadband = document.getElementById('wg_deadband');
              const db = Number(deadband && deadband.value || 0);
              await ctx.ControlChannel.send({ flow: {
                usar_sensor_flujo: chk && chk.checked ? 1 : 0,
                caudal_bomba_mls: Number(caudal && caudal.value || 0),
                deadband_energy: db
              } });
              if(typeof ctx.jpost==='function'){
                await ctx.jpost('/api/settings', {
                  usar_sensor_flujo: chk && chk.checked ? 1 : 0,
                  caudal_bomba_mls: Number(caudal && caudal.value || 0),
                  deadband_energy: db
                });
              }
              ctx.toast && ctx.toast('Ajustes de flujo aplicados');
            }catch{ ctx.toast && ctx.toast('Error aplicando flujo'); }
          });
        }
        // Inicializar campos desde settings (sin await para no romper init)
        try{
          if(typeof ctx.jget==='function'){
            ctx.jget('/api/settings').then((s)=>{
              try{
                const deadband = document.getElementById('wg_deadband');
                if(deadband && s && s.deadband_energy!=null){ deadband.value = String(Number(s.deadband_energy)); }
                const caudal = document.getElementById('wg_caudal');
                if(caudal && s && s.caudal_bomba_mls!=null){ caudal.value = String(Number(s.caudal_bomba_mls)); }
                const chk2 = document.getElementById('wg_chk_sensor_flujo');
                if(chk2 && s && s.usar_sensor_flujo!=null){ chk2.checked = !!s.usar_sensor_flujo; }
              }catch{}
            }).catch(()=>{});
          }
        }catch{}
      },
      onTelemetry(data){
        if(!state || !data) return;
        const s = data.snapshot || {};
        const now = Number(data.nowMs || Date.now());
        const usarSensor = !!(s && s.usarSensorFlujo);
        const energiaBomba = (s && s.energies && typeof s.energies.bomba==='number') ? Number(s.energies.bomba) : 0;
        const caudalCfg = Number((s && s.caudalBombaMLs!=null)?s.caudalBombaMLs:(state.targetFlow||0));
        const volActual = Number.isFinite(data.volumeActual) ? Number(data.volumeActual)
          : (s && s.volumen_ml!=null ? Number(s.volumen_ml) : state.lastVolumeActual);
        const volTarget = Number.isFinite(data.volumeTarget) ? Number(data.volumeTarget)
          : (s && s.volumen_objetivo_ml!=null ? Number(s.volumen_objetivo_ml) : state.targetVolume);
        const margin = 0.05;
        const objetivoPendiente = Number.isFinite(volTarget) && Number.isFinite(volActual)
          ? (volTarget - volActual) > margin : false;
        const bombaActiva = usarSensor ? objetivoPendiente : (energiaBomba > 0);
        const flowActual = Number.isFinite(data.flowActual) ? Number(data.flowActual)
          : (bombaActiva ? caudalCfg : 0);
        state.lastFlowActual = flowActual;
        if(!usarSensor && bombaActiva && caudalCfg>0){
          if(!state.estActive){
            state.estActive = true;
            state.lastTs = now;
            state.estVol = Number.isFinite(volActual) ? volActual : (state.lastVolumeActual!=null?Number(state.lastVolumeActual):0);
            try{ ctx.debug && ctx.debug({ bomba:'estimacion_local_on', base: state.estVol, caudal: caudalCfg }); }catch{}
          }else{
            const dt = Math.max(0, (now - (state.lastTs||now))/1000);
            state.lastTs = now;
            state.estVol += caudalCfg * dt;
            if(Number.isFinite(volTarget)) state.estVol = Math.min(state.estVol, volTarget);
          }
          state.lastVolumeActual = state.estVol;
          try{ window._ui_est_vol = state.estVol; }catch{}
        }else{
          if(state.estActive){ try{ ctx.debug && ctx.debug({ bomba:'estimacion_local_off' }); }catch{} }
          state.estActive = false;
          state.lastTs = now;
          if(Number.isFinite(volActual)) state.lastVolumeActual = volActual;
          try{ window._ui_est_vol = null; }catch{}
        }
        const completed = (Number.isFinite(volTarget) && Number.isFinite(volActual)) ? ((volTarget - volActual) <= margin) : false;
        const runningNow = (flowActual > 0.01);
        // contar ticks en estado completado para evitar falsos positivos
        state.completeHold = completed ? Math.min(3, (state.completeHold||0)+1) : 0;
        // Auto-stop una sola vez cuando detectamos fin sostenido y aún hay flujo
        if(state.completeHold>=2 && !state.autoStopDone && runningNow){
          try{ ctx.ControlChannel.send({ flow: { flow_target_mls: 0 }, energies: { bomba: 0 }, execute: 0 }); }catch{}
          state.autoStopDone = true;
        }
        updateRunUI(!!runningNow && !completed, completed);
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
