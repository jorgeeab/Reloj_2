/* Pump UI – Modular Flow Widget (SSE + REST)
   - Auto-detects actuators from /api/config
   - Controls only 'pump' (volume + flow) for this robot
   - Start: POST /api/tasks/execute (volume_ml)
   - Stop:  POST /api/execution/{id}/stop
   - Calib/mode: POST /api/flow/apply { ml_per_sec, usar_sensor_flujo }
   - Telemetry: /api/status/stream (SSE) with progress (0..1) and ml_per_sec
*/

(function(){
  const api = location.origin.replace(/\/$/, '');
  const $ = (s)=> document.querySelector(s);
  let lastExec = null;
  let lastSse = 0;

  function fmtMetric(v, u, p){
    if(v==null || Number.isNaN(v)) return '—';
    return `${Number(v).toFixed(p||0)} ${u}`.trim();
  }

  async function jget(u){ const r=await fetch(u); if(!r.ok) throw new Error(u); return r.json(); }
  async function jpost(u, body){ const r=await fetch(u,{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body||{})}); if(!r.ok) throw new Error(u); return r.json(); }

  async function applyFlowSettings(flowMlps, usarSensor){
    try{
      await jpost(api + '/api/flow/apply', { ml_per_sec: Number(flowMlps), usar_sensor_flujo: !!usarSensor });
    }catch(e){ console.warn('flow/apply failed', e); }
  }

  function buildPumpWidget(root){
    const el = typeof root==='string'? document.getElementById(root) : root;
    if(!el) return null;
    const refs = {
      vol: el.querySelector('#fw_volume'), flow: el.querySelector('#fw_flow'),
      btnStart: el.querySelector('#fw_start'), btnStop: el.querySelector('#fw_stop'), btnReset: el.querySelector('#fw_reset'),
      flowActual: el.querySelector('#fw_flow_actual'), flowTarget: el.querySelector('#fw_flow_target'),
      volActual: el.querySelector('#fw_volume_actual'), volTarget: el.querySelector('#fw_volume_target'),
      volRemaining: el.querySelector('#fw_volume_remaining'),
      chkSensor: el.querySelector('#fw_sensor_chk')
    };
    const bounds = { volume:{min:0,max:2000,precision:0}, flow:{min:0,max:100,precision:1} };
    const state = { execId:null, online:false, targetVol: Number(refs.vol&&refs.vol.value||0), targetFlow: Number(refs.flow&&refs.flow.value||0) };
    const clamp = (v,b)=> Math.min(b.max, Math.max(b.min, Number(v)||0));
    const setVal = (inp,val,b)=>{ if(!inp) return; const v=clamp(val,b); inp.value = v.toFixed(b.precision); return v; };

    function refreshDisable(){ const dis = !state.online; [refs.btnStart, refs.btnStop, refs.btnReset].forEach(b=> b && (b.disabled=dis)); }
    function toast(msg){ const t=document.getElementById('toast'); if(!t) return; t.textContent=String(msg||''); t.style.display='block'; clearTimeout(toast._t); toast._t=setTimeout(()=>{t.style.display='none'},1400); }

    // Actions
    refs.btnStart && refs.btnStart.addEventListener('click', async ()=>{
      state.targetVol = setVal(refs.vol, refs.vol.value, bounds.volume);
      state.targetFlow = setVal(refs.flow, refs.flow.value, bounds.flow);
      await applyFlowSettings(state.targetFlow, refs.chkSensor && refs.chkSensor.checked);
      const body = { name:'pump', protocol_name:'riego_basico', mode:'async', params:{ volume_ml: state.targetVol } };
      try{
        const res = await jpost(api + '/api/tasks/execute', body);
        state.execId = res.execution_id||null; lastExec = state.execId;
        toast('Tarea iniciada');
      }catch(e){ toast('No se pudo iniciar'); }
    });
    refs.btnStop && refs.btnStop.addEventListener('click', async ()=>{
      const id = state.execId || lastExec; if(!id) return;
      try{ await jpost(api + '/api/execution/' + id + '/stop', {}); toast('Detenida'); }catch(e){ toast('No se pudo detener'); }
    });
    refs.btnReset && refs.btnReset.addEventListener('click', ()=>{ state.execId=null; lastExec=null; refs.volActual && (refs.volActual.textContent='0 ml'); refs.volRemaining && (refs.volRemaining.textContent='—'); });

    // Steps
    el.querySelectorAll('[data-fw-step]')?.forEach(btn=>{
      btn.addEventListener('click', ()=>{
        const t = btn.getAttribute('data-target')==='flow'? 'flow':'volume';
        const inp = (t==='flow'? refs.flow: refs.vol);
        const b = bounds[t];
        const step = Number(btn.getAttribute('data-fw-step')||0);
        setVal(inp, Number(inp.value||0)+step, b);
      });
    });

    // SSE
    function onStatus(st){
      state.online = true; refreshDisable(); lastSse=Date.now();
      const mlps = Number(st.ml_per_sec||0);
      const progress = (st.progress!=null)? Number(st.progress): null;
      const running = !!st.pump_running;
      if(refs.flowActual) refs.flowActual.textContent = fmtMetric(mlps, 'ml/s', bounds.flow.precision);
      if(refs.flowTarget) refs.flowTarget.textContent = fmtMetric(state.targetFlow, 'ml/s', bounds.flow.precision);
      if(refs.chkSensor && st.sensors && 'usar_sensor_flujo' in st.sensors){ refs.chkSensor.checked = !!st.sensors.usar_sensor_flujo; }
      if(progress!=null && state.targetVol!=null){
        const delivered = Math.max(0, progress) * state.targetVol;
        if(refs.volActual) refs.volActual.textContent = fmtMetric(delivered, 'ml', bounds.volume.precision);
        if(refs.volTarget) refs.volTarget.textContent = fmtMetric(state.targetVol, 'ml', bounds.volume.precision);
        if(refs.volRemaining) refs.volRemaining.textContent = fmtMetric(Math.max(0, state.targetVol - delivered), 'ml', bounds.volume.precision);
      }
    }
    (function sse(){ try{ const es = new EventSource(api + '/api/status/stream'); es.onmessage = ev=>{ try{ onStatus(JSON.parse(ev.data||'{}')); }catch{} }; es.onerror=_=>{ state.online=false; refreshDisable(); }; }catch{ state.online=false; refreshDisable(); } })();

    return {
      setTargets(vml, flow){ state.targetVol = setVal(refs.vol, vml, bounds.volume); state.targetFlow = setVal(refs.flow, flow, bounds.flow); },
    };
  }

  // Public init for index_modular.html
  window.PumpUI = { buildPumpWidget };
})();

