// Simple widget library for ROBOTS Hub
export const WidgetFactory = {
  create(item){
    const type = (item.type||'value').toLowerCase();
    if(type==='gauge') return createGauge(item);
    if(type==='toggle') return createToggle(item);
    if(type==='slider') return createSlider(item);
    if(type==='flow-control' || type==='flow_control') return createFlowControl(item);
    if(type==='button') return createButton(item);
    return createValue(item);
  }
};

function el(tag, cls){ const e=document.createElement(tag); if(cls) e.className=cls; return e; }

function setStateClasses(el, {online, error}){
  if(!el) return;
  el.classList.toggle('offline', !online);
  el.classList.toggle('error', !!error);
}

function createValue(item){
    const wrap = el('div','w-card');
    const title = el('div','w-title'); title.textContent = item.title||item.id||'Valor';
    const row = el('div','w-row');
    const val = el('div','w-value'); val.textContent = '—';
    const unit = el('span','w-unit'); unit.textContent = item.unit||'';
    row.appendChild(val); row.appendChild(unit);
    wrap.appendChild(title); wrap.appendChild(row);
    return {
      el: wrap,
      update(payload){
        const data = payload?.data;
        const online = payload?.online !== false;
        setStateClasses(wrap, {online, error: payload?.error});
        let v = data ? readPath(data, item.path) : null;
        if(v===undefined||v===null||v==='') { val.textContent='—'; return; }
        if(typeof v==='number'){
          const d = (item.decimals!=null)? item.decimals : 2;
          val.textContent = v.toFixed(d);
        }else{ val.textContent = String(v); }
      },
      destroy(){ wrap.remove(); }
    }
}

function createGauge(item){
  const wrap = el('div','w-card');
  const title = el('div','w-title'); title.textContent = item.title||'Gauge';
  const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 120 120'); svg.setAttribute('class','gauge');
  const bg = document.createElementNS(svg.namespaceURI,'circle'); bg.setAttribute('cx','60'); bg.setAttribute('cy','60'); bg.setAttribute('r','48'); bg.setAttribute('class','bg');
  const fg = document.createElementNS(svg.namespaceURI,'circle'); fg.setAttribute('cx','60'); fg.setAttribute('cy','60'); fg.setAttribute('r','48'); fg.setAttribute('class','fg'); fg.setAttribute('transform','rotate(-90 60 60)');
  const txt = document.createElementNS(svg.namespaceURI,'text'); txt.setAttribute('x','60'); txt.setAttribute('y','64'); txt.setAttribute('text-anchor','middle'); txt.setAttribute('class','txt'); txt.textContent='0';
  const lbl = document.createElementNS(svg.namespaceURI,'text'); lbl.setAttribute('x','60'); lbl.setAttribute('y','100'); lbl.setAttribute('text-anchor','middle'); lbl.setAttribute('class','lbl'); lbl.textContent = item.unit||'';
  svg.appendChild(bg); svg.appendChild(fg); svg.appendChild(txt); svg.appendChild(lbl);
  wrap.appendChild(title); wrap.appendChild(svg);
  const R=48, C=2*Math.PI*R;
  return {
    el: wrap,
    update(payload){
      const data = payload?.data;
      const online = payload?.online !== false;
      setStateClasses(wrap, {online, error: payload?.error});
      const v = Number(readPath(data, item.path)||0);
      const max = Number(item.max || (Math.abs(v)||1)*1.5);
      const frac = max>0? Math.max(0, Math.min(1, v/max)) : 0;
      fg.style.strokeDashoffset = String(C * (1-frac));
      const d = (item.decimals!=null)? item.decimals : 1;
      const suffix = item.unit||'';
      txt.textContent = (item.percent? Math.round(frac*100)+'%': v.toFixed(d));
      lbl.textContent = suffix || '';
    },
    destroy(){ wrap.remove(); }
  }
}

function createToggle(item){
  const wrap = el('div','w-card');
  const title = el('div','w-title'); title.textContent = item.title||'Toggle';
  const btn = document.createElement('button'); btn.className='btn btn-sm btn-outline-secondary'; btn.textContent='—';
  wrap.appendChild(title); wrap.appendChild(btn);
  const state = {value:false};
  btn.addEventListener('click', async ()=>{
    if(item.onCommand){ try{ await item.onCommand(!state.value); }catch(e){} }
  });
  return {
    el: wrap,
    update(payload){
      const data = payload?.data;
      const online = payload?.online !== false;
      setStateClasses(wrap, {online, error: payload?.error});
      const v = !!readPath(data, item.path);
      state.value = v; btn.className = v? 'btn btn-sm btn-success':'btn btn-sm btn-outline-secondary';
      btn.textContent = v? (item.onLabel||'Encendido') : (item.offLabel||'Apagado');
      btn.disabled = !online || !!item.disabled;
    },
    destroy(){ wrap.remove(); }
  }
}

function createSlider(item){
  const wrap = el('div','w-card w-slider');
  const title = el('div','w-title'); title.textContent = item.title||'Slider';
  const body = el('div','w-slider-body');
  const btnDec = document.createElement('button'); btnDec.type='button'; btnDec.className='btn btn-sm btn-outline-secondary w-slider-btn'; btnDec.textContent='◀';
  const btnInc = document.createElement('button'); btnInc.type='button'; btnInc.className='btn btn-sm btn-outline-secondary w-slider-btn'; btnInc.textContent='▶';
  const input = document.createElement('input'); input.type='range'; input.className='form-range';
  const min = Number(item.min ?? 0);
  const max = Number(item.max ?? 100);
  const stepRaw = Number(item.step ?? 1);
  const step = Number.isFinite(stepRaw) && stepRaw > 0 ? stepRaw : 1;
  const cmdCfg = item.command || {};
  let holdDelay = Number(item.holdDelay ?? cmdCfg.hold_delay_ms ?? cmdCfg.holdDelay ?? 350);
  if(!Number.isFinite(holdDelay) || holdDelay < 0) holdDelay = 350;
  let holdInterval = Number(item.holdInterval ?? cmdCfg.hold_interval_ms ?? cmdCfg.holdInterval ?? 120);
  if(!Number.isFinite(holdInterval) || holdInterval < 50) holdInterval = 120;
  let overrideMs = Number(item.overrideMs ?? cmdCfg.override_ms ?? cmdCfg.overrideMs ?? 1500);
  if(!Number.isFinite(overrideMs) || overrideMs < 0) overrideMs = 1500;
  let sendDelay = Number(item.sendDelay ?? cmdCfg.debounce_ms ?? cmdCfg.debounceMs ?? 120);
  if(!Number.isFinite(sendDelay) || sendDelay < 0) sendDelay = 120;
  const telemetryToleranceRaw = Number(item.telemetryTolerance ?? cmdCfg.telemetry_tolerance ?? cmdCfg.telemetryTolerance ?? step);
  const telemetryTolerance = Number.isFinite(telemetryToleranceRaw) && telemetryToleranceRaw >= 0 ? telemetryToleranceRaw : step;
  let telemetryTimeout = Number(item.commandEchoMs ?? cmdCfg.echo_timeout_ms ?? cmdCfg.echoTimeout ?? 12000);
  if(!Number.isFinite(telemetryTimeout) || telemetryTimeout < 0) telemetryTimeout = 12000;
  input.min = String(min);
  input.max = String(max);
  input.step = String(step);
  body.appendChild(btnDec);
  body.appendChild(input);
  body.appendChild(btnInc);
  const row = el('div','w-row');
  const val = el('div','w-value'); val.textContent='—';
  const unit = el('span','w-unit'); unit.textContent=item.unit||'';
  row.appendChild(val); row.appendChild(unit);
  wrap.appendChild(title);
  wrap.appendChild(body);
  wrap.appendChild(row);

  const clamp = (value)=> Math.max(min, Math.min(max, value));
  const format = (value)=>{
    if(value==null || Number.isNaN(value)) return '—';
    const d = (item.decimals!=null)? item.decimals : 1;
    return Number(value).toFixed(d);
  };

  let lastTelemetry = min;
  let manualValue = null;
  let overrideUntil = 0;
  let pendingValue = null;
  let sendTimer = null;
  let awaitingTelemetryUntil = 0;
  let lastCommandValue = null;

  const updateDisplay = (value)=>{
    val.textContent = format(value);
  };

  const queueSend = (value)=>{
    if(!item.onCommand) return;
    pendingValue = value;
    if(sendTimer!==null) return;
    sendTimer = window.setTimeout(async ()=>{
      const target = pendingValue;
      pendingValue = null;
      sendTimer = null;
      lastCommandValue = target;
      awaitingTelemetryUntil = Date.now() + telemetryTimeout;
      try{
        await item.onCommand(target, { value: target });
      }catch(err){
        console.error('[widget slider] command failed', err);
      }
    }, sendDelay);
  };

  const markOverride = ()=>{
    overrideUntil = Date.now() + overrideMs;
  };

  const applyValue = (value, {send} = {send:false})=>{
    const clamped = clamp(value);
    manualValue = clamped;
    input.value = String(clamped);
    updateDisplay(clamped);
    markOverride();
    if(send){ queueSend(clamped); }
  };

  input.addEventListener('input', ()=>{
    const v = clamp(Number(input.value));
    manualValue = v;
    updateDisplay(v);
    markOverride();
  });

  input.addEventListener('change', ()=>{
    const v = clamp(Number(input.value));
    manualValue = v;
    updateDisplay(v);
    markOverride();
    queueSend(v);
  });

  const stepValue = (delta)=>{
    const base = manualValue != null && Date.now() < overrideUntil ? manualValue : lastTelemetry;
    applyValue(base + delta, {send:true});
  };

  const bindHold = (btn, delta)=>{
    let holdTimer = null;
    let repeatTimer = null;
    const clear = ()=>{
      if(holdTimer){ window.clearTimeout(holdTimer); holdTimer = null; }
      if(repeatTimer){ window.clearInterval(repeatTimer); repeatTimer = null; }
    };
    btn.addEventListener('pointerdown', ev=>{
      if(btn.disabled) return;
      ev.preventDefault();
      try{ btn.setPointerCapture(ev.pointerId); }catch{}
      stepValue(delta);
      holdTimer = window.setTimeout(()=>{
        repeatTimer = window.setInterval(()=> stepValue(delta), holdInterval);
      }, holdDelay);
    });
    const release = ev=>{
      clear();
      if(ev && ev.pointerId!=null){ try{ btn.releasePointerCapture(ev.pointerId); }catch{} }
    };
    btn.addEventListener('pointerup', release);
    btn.addEventListener('pointercancel', release);
    btn.addEventListener('pointerleave', clear);
    btn.addEventListener('lostpointercapture', clear);
  };

  bindHold(btnDec, -step);
  bindHold(btnInc, step);

  return {
    el: wrap,
    update(payload){
      const data = payload?.data;
      const online = payload?.online !== false;
      setStateClasses(wrap, {online, error: payload?.error});
      const disabled = !online || !!item.disabled;
      input.disabled = disabled;
      btnDec.disabled = disabled;
      btnInc.disabled = disabled;
      const raw = readPath(data, item.path);
      let numeric = null;
      if(raw !== undefined && raw !== null && raw !== ''){
        const num = Number(raw);
        if(Number.isFinite(num)){
          numeric = clamp(num);
          lastTelemetry = numeric;
        }
      }
      const now = Date.now();
      const inOverride = overrideUntil > now && manualValue != null;
      let allowTelemetryControl = numeric != null;
      if(numeric != null){
        const awaiting = awaitingTelemetryUntil > now;
        const matchesCommand = lastCommandValue != null && Math.abs(numeric - lastCommandValue) <= telemetryTolerance;
        if(matchesCommand){
          awaitingTelemetryUntil = 0;
        }
        if(awaiting && !matchesCommand){
          allowTelemetryControl = false;
        }
      }
      if(allowTelemetryControl && !inOverride){
        manualValue = numeric;
        input.value = String(numeric);
        updateDisplay(numeric);
      }else if(manualValue != null){
        input.value = String(manualValue);
        updateDisplay(manualValue);
      }else if(allowTelemetryControl){
        input.value = String(numeric);
        updateDisplay(numeric);
      }else{
        updateDisplay(null);
      }
    },
    destroy(){
      if(sendTimer!==null){ window.clearTimeout(sendTimer); }
      wrap.remove();
    }
  }
}

function createButton(item){
  const wrap = el('div','w-card w-button');
  const title = el('div','w-title'); title.textContent = item.title || item.id || 'Acción';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn btn-sm btn-primary w-button-btn';
  btn.textContent = item.label || item.title || 'Ejecutar';
  wrap.appendChild(title);
  wrap.appendChild(btn);

  btn.addEventListener('click', async ()=>{
    if(btn.disabled) return;
    if(item.confirm && !window.confirm(item.confirm)) return;
    if(typeof item.onCommand === 'function'){
      try{
        await item.onCommand();
      }catch(err){
        console.error('[widget button] command failed', err);
      }
    }
  });

  return {
    el: wrap,
    update(payload){
      const online = payload?.online !== false;
      setStateClasses(wrap, {online, error: payload?.error});
      btn.disabled = !online || !!item.disabled;
    },
    destroy(){ wrap.remove(); }
  };
}

function createFlowControl(item){
  const wrap = el('div','w-card w-flow-control');
  const title = el('div','w-title'); title.textContent = item.title || item.id || 'Control de flujo';
  wrap.appendChild(title);

  const volCfg = item.volume || {};
  const flowCfg = item.flow || {};
  const decimalsVolume = Number.isInteger(volCfg.decimals)? volCfg.decimals : (item.decimals != null ? item.decimals : 1);
  const decimalsFlow = Number.isInteger(flowCfg.decimals)? flowCfg.decimals : (item.decimals != null ? item.decimals : 1);
  const showRemaining = item.show_remaining !== false;

  const layout = el('div','w-flow-layout');
  wrap.appendChild(layout);

  const infoCol = el('div','w-flow-info');
  layout.appendChild(infoCol);

  const statusList = el('dl','w-flow-status');
  infoCol.appendChild(statusList);

  const addStat = (label)=> createHorizStat(statusList, label);

  const statFlow = addStat(flowCfg.metric_label || flowCfg.label || 'Flujo actual');
  const statMaxFlow = addStat(flowCfg.max_label || 'Máx caudal');
  const statDelivered = addStat(volCfg.metric_label || 'Volumen entregado');
  const statTarget = addStat(volCfg.target_label || 'Objetivo volumen');
  const statRemaining = showRemaining ? addStat(item.remaining_label || 'Restante') : null;

  const steppersCol = el('div','w-flow-steppers');
  layout.appendChild(steppersCol);

  const volumeStepper = createStepperControl({
    label: volCfg.label || 'Volumen objetivo',
    unit: volCfg.unit || 'ml',
    min: volCfg.min ?? 0,
    max: volCfg.max ?? 500,
    step: volCfg.step ?? 1,
    defaultValue: volCfg.default ?? volCfg.target_default ?? volCfg.min ?? 0,
    decimals: decimalsVolume,
    holdDelay: volCfg.hold_delay_ms ?? volCfg.holdDelay ?? item.holdDelay,
    holdInterval: volCfg.hold_interval_ms ?? volCfg.holdInterval ?? item.holdInterval,
    wide: true
  });
  steppersCol.appendChild(volumeStepper.el);

  let flowStepper = null;
  if(flowCfg !== false){
    flowStepper = createStepperControl({
      label: flowCfg.label || 'Caudal objetivo',
      unit: flowCfg.unit || 'ml/s',
      min: flowCfg.min ?? 0,
      max: flowCfg.max ?? 50,
      step: flowCfg.step ?? 0.5,
      defaultValue: flowCfg.default ?? flowCfg.target_default ?? flowCfg.min ?? 0,
      decimals: decimalsFlow,
      holdDelay: flowCfg.hold_delay_ms ?? flowCfg.holdDelay ?? item.holdDelay,
      holdInterval: flowCfg.hold_interval_ms ?? flowCfg.holdInterval ?? item.holdInterval,
      wide: true
    });
    steppersCol.appendChild(flowStepper.el);
  }

  const actions = el('div','w-flow-actions');
  wrap.appendChild(actions);
  const startBtn = document.createElement('button');
  startBtn.type = 'button';
  startBtn.className = 'btn btn-sm btn-primary';
  startBtn.textContent = item.start_label || 'Iniciar';
  const stopBtn = document.createElement('button');
  stopBtn.type = 'button';
  stopBtn.className = 'btn btn-sm btn-outline-danger';
  stopBtn.textContent = item.stop_label || 'Detener';
  actions.appendChild(startBtn);
  actions.appendChild(stopBtn);
  let resetBtn = null;
  if(typeof item.onReset === 'function'){
    resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.className = 'btn btn-sm btn-outline-secondary';
    resetBtn.textContent = item.reset_label || 'Reiniciar';
    actions.appendChild(resetBtn);
  }

  let online = true;
  let busy = false;

  const getValues = ()=>({
    volume: volumeStepper.getValue(),
    flow: flowStepper ? flowStepper.getValue() : undefined
  });

  const refreshDisabled = ()=>{
    const disabled = !online || busy;
    startBtn.disabled = disabled || typeof item.onExecute !== 'function';
    stopBtn.disabled = disabled || typeof item.onStop !== 'function';
    if(resetBtn){
      resetBtn.disabled = disabled;
    }
    volumeStepper.setDisabled(disabled);
    if(flowStepper){
      flowStepper.setDisabled(disabled);
    }
  };

  startBtn.addEventListener('click', async ()=>{
    if(startBtn.disabled || typeof item.onExecute !== 'function') return;
    busy = true;
    refreshDisabled();
    try{
      await item.onExecute(getValues());
    }catch(err){
      console.error('[widget flow-control] execute failed', err);
    }
    busy = false;
    refreshDisabled();
  });

  stopBtn.addEventListener('click', async ()=>{
    if(stopBtn.disabled || typeof item.onStop !== 'function') return;
    busy = true;
    refreshDisabled();
    try{
      await item.onStop(getValues());
    }catch(err){
      console.error('[widget flow-control] stop failed', err);
    }
    busy = false;
    refreshDisabled();
  });

  if(resetBtn){
    resetBtn.addEventListener('click', async ()=>{
      if(resetBtn.disabled || typeof item.onReset !== 'function') return;
      busy = true;
      refreshDisabled();
      try{
        await item.onReset();
      }catch(err){
        console.error('[widget flow-control] reset failed', err);
      }
      busy = false;
      refreshDisabled();
    });
  }

  const toNumber = (value)=>{
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
  };

  return {
    el: wrap,
    update(payload){
      const data = payload?.data || null;
      online = payload?.online !== false;
      setStateClasses(wrap, {online, error: payload?.error});

      const hasFlowCfg = flowCfg !== false && flowCfg && typeof flowCfg === 'object';
      const flowCurrent = hasFlowCfg ? toNumber(readPath(data, flowCfg.path)) : null;
      const volCurrent = toNumber(readPath(data, volCfg.path));
      const volTarget = toNumber(readPath(data, volCfg.target_path || volCfg.targetPath || volCfg.path));
      const flowTarget = hasFlowCfg ? toNumber(readPath(data, flowCfg.target_path || flowCfg.targetPath || flowCfg.path)) : null;

      const fmt = (value, decimals)=>{
        if(value === null || value === undefined || Number.isNaN(value)) return '—';
        return Number(value).toFixed(decimals);
      };

      statFlow.textContent = fmt(flowCurrent, decimalsFlow) + (flowCfg.unit ? ` ${flowCfg.unit}` : '');
      const maxFlowCfg = (flowCfg.visual_max != null ? Number(flowCfg.visual_max) : null)
        ?? (flowCfg.max != null ? Number(flowCfg.max) : null);
      if(Number.isFinite(maxFlowCfg)){
        statMaxFlow.textContent = `${maxFlowCfg.toFixed(decimalsFlow)} ${flowCfg.unit || ''}`.trim();
      }else{
        statMaxFlow.textContent = '—';
      }
      statDelivered.textContent = fmt(volCurrent, decimalsVolume) + (volCfg.unit ? ` ${volCfg.unit}` : '');
      statTarget.textContent = fmt(volTarget, decimalsVolume) + (volCfg.unit ? ` ${volCfg.unit}` : '');
      if(statRemaining){
        const remaining = (volTarget != null && volCurrent != null) ? Math.max(0, volTarget - volCurrent) : null;
        statRemaining.textContent = fmt(remaining, decimalsVolume) + (volCfg.unit ? ` ${volCfg.unit}` : '');
      }

      if(volTarget != null){
        volumeStepper.setTelemetry(volTarget);
      }
      if(flowStepper && flowTarget != null){
        flowStepper.setTelemetry(flowTarget);
      }

      refreshDisabled();
    },
    destroy(){
      wrap.remove();
    }
  };
}

function createStepperControl(config){
  const min = Number(config.min ?? 0);
  const max = Number(config.max ?? 100);
  const stepRaw = Number(config.step ?? 1);
  const step = Number.isFinite(stepRaw) && stepRaw > 0 ? stepRaw : 1;
  const decimals = Number.isInteger(config.decimals) ? config.decimals : 1;
  const holdDelay = Number(config.holdDelay ?? 350);
  const holdInterval = Number(config.holdInterval ?? 180);
  const overrideMs = Number(config.overrideMs ?? 2500);

  const wrap = el('div', config.wide ? 'w-flow-stepper w-flow-stepper-wide' : 'w-flow-stepper');
  const label = el('div','w-flow-stepper-label'); label.textContent = config.label || 'Objetivo';
  const controls = el('div','w-flow-stepper-controls');
  const btnDec = document.createElement('button'); btnDec.type='button'; btnDec.className='btn btn-sm btn-outline-secondary w-flow-btn'; btnDec.textContent='◀';
  const btnInc = document.createElement('button'); btnInc.type='button'; btnInc.className='btn btn-sm btn-outline-secondary w-flow-btn'; btnInc.textContent='▶';
  const valueWrap = el('div','w-flow-stepper-readout');
  const value = el('div','w-flow-stepper-value');
  const unit = el('span','w-unit'); unit.textContent = config.unit || '';
  valueWrap.appendChild(value);
  valueWrap.appendChild(unit);
  controls.appendChild(btnDec);
  controls.appendChild(valueWrap);
  controls.appendChild(btnInc);
  wrap.appendChild(label);
  wrap.appendChild(controls);

  const clampValue = (val)=>{
    const num = Number(val);
    if(!Number.isFinite(num)) return min;
    return Math.max(min, Math.min(max, num));
  };
  const format = (val)=>{
    if(val === null || val === undefined || Number.isNaN(val)) return '—';
    return Number(val).toFixed(decimals);
  };

  const initial = clampValue(config.defaultValue ?? min);
  let lastTelemetry = initial;
  let manualValue = initial;
  let overrideUntil = 0;
  let disabled = false;

  const setDisplay = (val)=>{ value.textContent = format(val); };
  setDisplay(manualValue);

  const setManual = (val)=>{
    const clamped = clampValue(val);
    manualValue = clamped;
    overrideUntil = Date.now() + overrideMs;
    setDisplay(clamped);
    return clamped;
  };

  const applyTelemetry = (val)=>{
    if(val === null || val === undefined || Number.isNaN(val)) return;
    const clamped = clampValue(val);
    lastTelemetry = clamped;
    if(Date.now() > overrideUntil){
      manualValue = clamped;
      setDisplay(clamped);
    }
  };

  const stepOnce = (delta)=>{
    if(disabled) return;
    const base = (Date.now() < overrideUntil && manualValue != null) ? manualValue : lastTelemetry;
    const next = clampValue(base + delta);
    setManual(next);
  };

  const bindHold = (btn, delta)=>{
    let holdTimer = null;
    let repeatTimer = null;
    const clearTimers = ()=>{
      if(holdTimer){ window.clearTimeout(holdTimer); holdTimer = null; }
      if(repeatTimer){ window.clearInterval(repeatTimer); repeatTimer = null; }
    };
    btn.addEventListener('pointerdown', ev=>{
      if(disabled) return;
      ev.preventDefault();
      try{ btn.setPointerCapture(ev.pointerId); }catch{}
      stepOnce(delta);
      holdTimer = window.setTimeout(()=>{
        repeatTimer = window.setInterval(()=> stepOnce(delta), holdInterval);
      }, holdDelay);
    });
    const release = ev=>{
      clearTimers();
      if(ev && ev.pointerId != null){
        try{ btn.releasePointerCapture(ev.pointerId); }catch{}
      }
    };
    btn.addEventListener('pointerup', release);
    btn.addEventListener('pointercancel', release);
    btn.addEventListener('pointerleave', clearTimers);
    btn.addEventListener('lostpointercapture', clearTimers);
  };

  bindHold(btnDec, -step);
  bindHold(btnInc, step);

  return {
    el: wrap,
    getValue: ()=> manualValue,
    setTelemetry: applyTelemetry,
    setDisabled(state){
      disabled = !!state;
      btnDec.disabled = disabled;
      btnInc.disabled = disabled;
    }
  };
}

function createMiniGauge(options){
  const wrap = el('div','w-flow-visual');
  const title = el('div','w-flow-visual-title'); title.textContent = options.label || 'Dato';
  const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 96 96');
  svg.setAttribute('class','w-flow-visual-gauge');
  const bg = document.createElementNS(svg.namespaceURI,'circle');
  bg.setAttribute('cx','48'); bg.setAttribute('cy','48'); bg.setAttribute('r','36'); bg.setAttribute('class','bg');
  const fg = document.createElementNS(svg.namespaceURI,'circle');
  fg.setAttribute('cx','48'); fg.setAttribute('cy','48'); fg.setAttribute('r','36');
  fg.setAttribute('class','fg');
  fg.setAttribute('transform','rotate(-90 48 48)');
  if(options.color){
    fg.style.stroke = options.color;
  }
  svg.appendChild(bg); svg.appendChild(fg);
  const valueWrap = el('div','w-flow-visual-value');
  const numberEl = el('span','w-flow-visual-number'); numberEl.textContent = '—';
  const unitEl = el('span','w-unit'); unitEl.textContent = options.unit || '';
  unitEl.hidden = !unitEl.textContent;
  valueWrap.appendChild(numberEl);
  valueWrap.appendChild(unitEl);
  const subEl = el('div','w-flow-visual-sub');
  wrap.appendChild(title);
  wrap.appendChild(svg);
  wrap.appendChild(valueWrap);
  wrap.appendChild(subEl);

  const R = 36;
  const C = 2 * Math.PI * R;
  fg.style.strokeDasharray = `${C} ${C}`;
  fg.style.strokeDashoffset = String(C);

  return {
    el: wrap,
    update(value, max, extras = {}){
      const decimals = Number.isInteger(options.decimals) ? options.decimals : 1;
      const num = Number(value);
      const valid = Number.isFinite(num);
      const displayValue = (extras.displayValue != null)
        ? String(extras.displayValue)
        : (valid ? num.toFixed(decimals) : '—');
      numberEl.textContent = displayValue;
      const unitText = extras.displayUnit != null ? extras.displayUnit : (options.unit || '');
      unitEl.textContent = unitText;
      unitEl.hidden = !unitText;
      const maxCandidate = Number(max);
      const limit = Number.isFinite(maxCandidate) && maxCandidate > 0
        ? maxCandidate
        : Math.max(valid ? Math.abs(num) : 1, 1);
      const frac = valid ? Math.max(0, Math.min(1, limit === 0 ? 0 : num / limit)) : 0;
      fg.style.strokeDashoffset = String(C * (1 - frac));
      subEl.textContent = extras.subText || '';
    }
  };
}

function makeMetric(label, unit){
  const row = el('div','w-flow-metric');
  const lbl = el('span','w-flow-metric-label'); lbl.textContent = label || '';
  const valueWrapper = el('span','w-flow-metric-value');
  const value = el('span','w-flow-metric-number'); value.textContent = '—';
  const unitEl = el('span','w-unit'); unitEl.textContent = unit || '';
  valueWrapper.appendChild(value);
  if(unit){
    valueWrapper.appendChild(unitEl);
  }
  row.appendChild(lbl);
  row.appendChild(valueWrapper);
  return {
    el: row,
    update(v, decimals = 1){
      if(v === null || v === undefined || Number.isNaN(v)){
        value.textContent = '—';
        return;
      }
      const num = Number(v);
      const d = Number.isInteger(decimals) ? decimals : 1;
      value.textContent = num.toFixed(d);
    }
  };
}

function createHorizStat(listEl, label){
  const row = el('div','w-flow-stat');
  const lbl = el('span','w-flow-stat-label'); lbl.textContent = label;
  const val = el('span','w-flow-stat-value'); val.textContent = '—';
  row.appendChild(lbl);
  row.appendChild(val);
  listEl.appendChild(row);
  return val;
}

// Resolve data path with fallbacks separated by '|', dot-notation
export function readPath(obj, path){
  if(!obj || !path) return null;
  const alts = String(path).split('|');
  for(const p of alts){
    const parts = p.split('.');
    let cur = obj; let ok = true;
    for(const part of parts){
      if(cur && Object.prototype.hasOwnProperty.call(cur, part)) cur = cur[part]; else { ok=false; break; }
    }
    if(ok && cur!==undefined && cur!==null) return cur;
  }
  return null;
}
