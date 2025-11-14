/* Reloj Labs — Cabina Única (single page)
   Robusta ante falta de RX: no pisa los checks manual/auto desde /status.
   Añade watchdog RX usando /debug/serial.last_rx_text y muestra modo TX desde /debug/serial.act[0].
*/

(() => {
  // ------------- Utils -------------
  const $ = s => document.querySelector(s);
  const $$ = s => Array.from(document.querySelectorAll(s));
  const toast = (m, ms=1500)=>{ const t=$("#toast"); t.textContent=m; t.hidden=false; setTimeout(()=>t.hidden=true, ms); };
  const fmt = (v,d=2)=> Number(v).toFixed(d);
  const clamp = (v,lo,hi)=> Math.max(lo, Math.min(hi, v));
  const debounce = (fn, ms)=>{ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a), ms); }; };

  async function jget(url){ const r=await fetch(url); if(!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); }
  async function jpost(url, body){ const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}); if(!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); }
  async function jdel(url){ const r=await fetch(url,{method:'DELETE'}); if(!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); }

  const WS_BASE = (location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host;
  const connectionFlags = { control: false, telemetry: false };
  let isSerialOpen = false;
  let rxAgeMs = 999999;
  let FlowWidgetCtrl = null;
  const pillRx = document.getElementById('pill-rx');
  const overlayEl = document.getElementById('op_overlay');
  const overlayMsg = document.getElementById('overlay_msg');
  const overlayReconnect = document.getElementById('btn_overlay_reconnect');

  function refreshOverlay(){
    if(!overlayEl) return;
    const issues = [];
    if(!connectionFlags.telemetry) issues.push("Sin telemetría");
    if(!connectionFlags.control) issues.push("Sin canal de control");
    if(!isSerialOpen && !connectionFlags.telemetry){
      issues.push("Esperando datos del robot");
    }
    if(issues.length){
      if(overlayMsg){ overlayMsg.textContent = issues.join(" · "); }
      overlayEl.hidden = false;
      if(overlayReconnect){
        const showBtn = !connectionFlags.control || !connectionFlags.telemetry;
        overlayReconnect.style.display = showBtn ? 'inline-flex' : 'none';
      }
    }else{
      overlayEl.hidden = true;
      if(overlayReconnect){ overlayReconnect.style.display = 'none'; }
    }
  }

  if(overlayReconnect){
    overlayReconnect.addEventListener('click', ()=>{
      if(typeof window !== 'undefined'){
        const ctrl = window.ControlChannel;
        if(ctrl && typeof ctrl.restart === 'function'){
          ctrl.restart();
        }
        const telem = window.TelemetryChannel;
        if(telem && typeof telem.restart === 'function'){
          telem.restart();
        }
      }
    });
  }

  refreshOverlay();

  function updateRxPillLabel(customText){
    if(!pillRx) return;
    if(!connectionFlags.telemetry){
      pillRx.textContent = "RX: SIN DATOS";
      pillRx.classList.add('warn');
      return;
    }
    const label = customText || (Number.isFinite(rxAgeMs) ? `RX ${Math.round(rxAgeMs)} ms` : "RX OK");
    pillRx.textContent = label;
    pillRx.classList.toggle('warn', Number.isFinite(rxAgeMs) && rxAgeMs > 4000);
  }

  function setConnectionState(kind, value){
    if(connectionFlags[kind] === value) return;
    connectionFlags[kind] = value;
    const label = `[ws/${kind}] ${value ? 'connected' : 'disconnected'}`;
    console[value ? 'info' : 'warn'](label);
    if(kind === 'telemetry'){
      updateRxPillLabel();
    }
    refreshOverlay();
  }

  function createControlChannel(){
    let socket = null;
    let reconnectTimer = null;
    const sendQueue = [];
    const awaiting = [];
    let lastPayload = null;

    const enqueue = (entry)=>{
      sendQueue.push(entry);
      flush();
    };

    const flush = ()=>{
      if(!socket || socket.readyState !== WebSocket.OPEN) return;
      while(sendQueue.length){
        const entry = sendQueue.shift();
        try{
          socket.send(JSON.stringify(entry.body));
          lastPayload = entry.body;
          entry.timeout = setTimeout(()=>{
            const idx = awaiting.indexOf(entry);
            if(idx !== -1){
              awaiting.splice(idx,1);
              entry.reject(new Error("control timeout"));
            }
          }, 4000);
          awaiting.push(entry);
        }catch(err){
          entry.reject(err);
        }
      }
    };

    const handleClose = ()=>{
      setConnectionState('control', false);
      awaiting.splice(0).forEach(entry=>{
        clearTimeout(entry.timeout);
        entry.reject(new Error("control socket cerrado"));
      });
      scheduleReconnect();
    };

    const handleMessage = (event)=>{
      let data = null;
      try{
        data = JSON.parse(event.data || "{}");
      }catch{
        return;
      }
      if(data.type === "control_ready"){
        setConnectionState('control', true);
        flush();
        return;
      }
      if(data.type === "control_ack"){
        const entry = awaiting.shift();
        if(!entry) return;
        clearTimeout(entry.timeout);
        if(data.status === "ok"){
          entry.resolve(data.body || {});
        }else{
          entry.reject(new Error(data.error || "control_error"));
        }
        flush();
        return;
      }
    };

    const connect = ()=>{
      if(socket){
        try{ socket.close(); }catch{}
      }
      setConnectionState('control', false);
      console.info('[ws/control] connecting...');
      socket = new WebSocket(`${WS_BASE}/ws/control`);
      socket.addEventListener('open', ()=>{
        setConnectionState('control', true);
        flush();
      });
      socket.addEventListener('message', handleMessage);
      socket.addEventListener('close', handleClose);
      socket.addEventListener('error', (err)=>{
        console.error('[ws/control] error', err);
        socket && socket.close();
      });
    };

    const scheduleReconnect = ()=>{
      if(reconnectTimer) return;
      reconnectTimer = setTimeout(()=>{
        reconnectTimer = null;
        connect();
      }, 1200);
    };

    connect();

    return {
      send(body){
        if(!body || typeof body !== 'object'){
          return Promise.resolve({});
        }
        return new Promise((resolve, reject)=> enqueue({ body, resolve, reject }));
      },
      restart(){ connect(); },
      getLastPayload(){ return lastPayload; }
    };
  }

  const ControlChannel = createControlChannel();
  if(typeof window !== 'undefined'){
    window.ControlChannel = ControlChannel;
  }
  updateRxPillLabel();

  // ------------- Serial (toggle único) -------------
  async function refreshPorts(){
    const info = await jget("/api/serial/ports");
    const hwRow = document.getElementById('serial_hw_row');
    if(hwRow){
      hwRow.hidden = !!info.is_virtual;
    }
    const virtualMsg = document.getElementById('serial_virtual_msg');
    if(virtualMsg){
      virtualMsg.style.display = info.is_virtual ? 'inline-flex' : 'none';
    }
    const sel = $("#sel_port");
    if(sel){
      sel.innerHTML="";
      if(info.is_virtual){
        const opt = document.createElement("option");
        opt.value = info.current || "VIRTUAL";
        opt.textContent = info.current || "VIRTUAL";
        opt.selected = true;
        sel.appendChild(opt);
        sel.disabled = true;
      }else{
        sel.disabled = false;
        (info.ports||[]).forEach(p=>{
          const opt=document.createElement("option");
          opt.value=p; opt.textContent=p; if(p===info.current) opt.selected=true; sel.appendChild(opt);
        });
        if(!sel.children.length && info.current){
          const opt=document.createElement("option");
          opt.value = info.current;
          opt.textContent = info.current;
          opt.selected = true;
          sel.appendChild(opt);
        }
      }
    }
    const ports = (info.ports||[]).join(', ');
    const showHwAlert = !info.is_virtual && !info.open;
    const hwAlert = document.getElementById('serial_hw_alert');
    if(hwAlert){
      hwAlert.style.display = showHwAlert ? 'inline-flex' : 'none';
    }
    const statusEl = $("#serial_status");
    if(statusEl){
      if(info.is_virtual){
        statusEl.textContent = "Modo virtual activo — serial simulado";
        statusEl.classList.remove('warn-text');
      }else{
        const status = info.open ? `Conectado a ${info.current || '(puerto actual)'}` : "Robot físico sin conexión";
        const portsLabel = ports || "sin puertos detectados";
        statusEl.textContent = `${status} · Puertos: ${portsLabel}`;
        statusEl.classList.toggle('warn-text', showHwAlert);
      }
    }
    const btn = $("#btn_toggle_serial");
    if(btn){
      if(info.is_virtual){
        btn.textContent = "Virtual";
        btn.disabled = true;
        btn.classList.remove('warn');
        btn.title = "Modo virtual activo, no se requiere COM";
      }else{
        btn.disabled = false;
        btn.textContent = info.open ? "Desconectar" : "Conectar";
        btn.removeAttribute('title');
        if(info.open) btn.classList.add('warn'); else btn.classList.remove('warn');
      }
    }
    const baudEl = document.getElementById('sel_baud');
    if(baudEl && window._statusCache && _statusCache.baudrate){
      baudEl.value = String(_statusCache.baudrate);
    }
  }
  const _btnToggleSerial = document.getElementById('btn_toggle_serial');
  if(_btnToggleSerial) _btnToggleSerial.onclick = async ()=>{
    try{
      const info = await jget("/api/serial/ports");
      if(info.is_virtual){
        toast("Modo virtual activo, no se requiere puerto serial.");
        return;
      }
      if(info.open){ await jpost("/api/serial/close",{}); toast("Desconectado"); }
      else {
        const port=$("#sel_port").value||info.current||"";
        const baudEl=document.getElementById('sel_baud'); const baud=baudEl?Number(baudEl.value||115200):115200;
        await jpost("/api/serial/open",{port, baudrate: baud}); toast(`Conectado ${port||"(actual)"} @ ${baud}`);
      }
      await refreshPorts();
    }catch(e){
      try{ await jpost('/api/disconnect',{}); toast('Desconectado'); }
      catch{}
      await refreshPorts();
    }
  };
  refreshPorts();

  const robotSel = document.getElementById('robotSel');
  const robotSel2 = document.getElementById('robotSel2');
  const robotPill = document.getElementById('pill-robot');
  let robotsCache = [];

  async function refreshRobots(){
    try{
      const info = await jget('/api/robots');
      robotsCache = info.robots || [];
      const syncSelect = (sel)=>{
        if(!sel) return;
        sel.innerHTML = '';
        if(robotsCache.length === 0){
          const opt = document.createElement('option');
          opt.value = '';
          opt.textContent = 'Sin robots';
          sel.appendChild(opt);
          sel.disabled = true;
        }else{
          robotsCache.forEach(r=>{
            const opt = document.createElement('option');
            opt.value = r.id;
            opt.textContent = r.label || r.id;
            sel.appendChild(opt);
          });
          if(info.active){ sel.value = info.active; }
          sel.disabled = false; // siempre visible, incluso si hay un solo perfil
        }
      };
      syncSelect(robotSel);
      syncSelect(robotSel2);
      if(robotPill){
        const active = robotsCache.find(r=>r.id === info.active) || null;
        if(active){
          robotPill.textContent = `Robot: ${active.label || active.id}`;
          robotPill.classList.toggle('warn', !!active.is_virtual);
        }else{
          robotPill.textContent = `Robot: ${info.active || '—'}`;
          robotPill.classList.add('warn');
        }
      }
    }catch(e){
      if(robotPill){
        robotPill.textContent = 'Robot: error';
        robotPill.classList.add('warn');
      }
    }
  }

  const onRobotChange = async (sel)=>{
    const id = sel && sel.value;
    if(!id) return;
    try{
      await jpost('/api/robots/select', { id });
      const label = sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : id;
      toast(`Robot activo: ${label}`);
      // Sin vaciado físico: no hay barra de “vaciado”.
      await refreshRobots();
      try{ await refreshPorts(); }catch{}
      TelemetryChannel.restart();
    }catch(e){
      toast('No se pudo cambiar el robot');
      await refreshRobots();
    }
  };
  if(robotSel){ robotSel.addEventListener('change', ()=> onRobotChange(robotSel)); }
  if(robotSel2){ robotSel2.addEventListener('change', ()=> onRobotChange(robotSel2)); }

  refreshRobots();

  // ------------- Tabs (simple) -------------
  (function initTabs(){
    const tabs = Array.from(document.querySelectorAll('.tabs button'));
    const views = Array.from(document.querySelectorAll('.tabview'));
    const activate = (tab)=>{
      tabs.forEach(b=> b.classList.toggle('active', b===tab));
      const k = tab.dataset.tab;
      views.forEach(v=>{ v.style.display = (v.dataset.tab===k)? 'block':'none'; });
      if(k==='op'){
        document.querySelectorAll('[data-tab="op"]').forEach(s=> s.style.display='block');
      }
      try{ if(k) location.hash = '#' + k; }catch{}
    };
    if(tabs.length){
      tabs.forEach(b=> b.onclick = ()=> activate(b));
      // hash -> tab
      const h = (location.hash||'').replace('#','');
      const first = tabs.find(b=> b.dataset.tab===h) || tabs.find(b=>b.dataset.tab==='op') || tabs[0];
      activate(first);
    }
  })();

  // Selector de tema (tabs cambian de color)
  const themeSel = document.getElementById('themeSel');
  const bodyRoot = document.getElementById('bodyRoot');
  if(themeSel && bodyRoot){
    themeSel.onchange = ()=>{
      bodyRoot.classList.remove('theme-blue','theme-teal','theme-purple');
      const v = themeSel.value || 'theme-blue';
      bodyRoot.classList.add(v);
    };
  }

  // ------------- Settings modal -------------
  const btnSettings = document.getElementById('btn_settings');
  if(btnSettings){ btnSettings.onclick = ()=>{ const bt=document.querySelector('.tabs button[data-tab="set"]'); if(bt){ bt.click(); } refreshPorts(); }; }

  // Guardar/Cargar Settings
  async function loadSettings(){
    try{
      const s = await jget('/api/settings');
      const baudEl=document.getElementById('sel_baud'); if(baudEl && s.baudrate){ baudEl.value=String(s.baudrate); }
      const mm=document.getElementById('steps_mm'); if(mm && s.steps_mm!=null){ mm.value=String(s.steps_mm); }
      const dg=document.getElementById('steps_deg'); if(dg && s.steps_deg!=null){ dg.value=String(s.steps_deg); }
      const cf=document.getElementById('caudal'); if(cf && s.caudal_bomba_mls!=null){ cf.value=String(s.caudal_bomba_mls); }
      const uf=document.getElementById('chk_sensor_flujo'); if(uf && s.usar_sensor_flujo!=null){ uf.checked = !!s.usar_sensor_flujo; }
      const zsc=document.getElementById('z_mm_por_grado'); if(zsc && s.z_mm_por_grado!=null){ zsc.value=String(s.z_mm_por_grado); }
      // Guardar/cargar últimos setpoints
      const spx=document.getElementById('sp_x'); if(spx && s.last_sp_x_mm!=null){ spx.value=String(s.last_sp_x_mm); }
      const spa=document.getElementById('sp_a'); if(spa && s.last_sp_a_deg!=null){ spa.value=String(s.last_sp_a_deg); }
      const spz=document.getElementById('sp_z'); if(spz && s.last_sp_z_mm!=null){ spz.value=String(s.last_sp_z_mm); }
      const spv=document.getElementById('sp_vol'); if(spv && s.last_sp_vol_ml!=null){ spv.value=String(s.last_sp_vol_ml); }
      // PID defaults
      const dk=['def_kpX','def_kiX','def_kdX','def_kpA','def_kiA','def_kdA'];
      dk.forEach(k=>{ const el=document.getElementById(k); const key=k.replace('def_',''); if(el && s[key]!=null){ el.value=String(s[key]); } });
      // policy/scheduler
      const pol=document.getElementById('sel_policy'); if(pol && s.command_policy){ pol.value = String(s.command_policy); }
      const sch=document.getElementById('chk_scheduler'); if(sch && typeof s.scheduler_enabled!=='undefined'){ sch.checked = !!s.scheduler_enabled; }
    }catch{}
  }
  async function saveSettings(){
    const baud=Number((document.getElementById('sel_baud')||{}).value||115200);
    const steps_mm=Number((document.getElementById('steps_mm')||{}).value||0);
    const steps_deg=Number((document.getElementById('steps_deg')||{}).value||0);
    const caudal_bomba_mls=Number((document.getElementById('caudal')||{}).value||0);
    const usar_sensor_flujo=(document.getElementById('chk_sensor_flujo')||{}).checked?1:0;
    const z_scale=Number((document.getElementById('z_mm_por_grado')||{}).value||1);
    const last_sp_x_mm=Number((document.getElementById('sp_x')||{}).value||0);
    const last_sp_a_deg=Number((document.getElementById('sp_a')||{}).value||0);
    const last_sp_z_mm=Number((document.getElementById('sp_z')||{}).value||0);
    const last_sp_vol_ml=Number((document.getElementById('sp_vol')||{}).value||0);
    const payload={ baudrate: baud, steps_mm, steps_deg, caudal_bomba_mls, usar_sensor_flujo, z_mm_por_grado: z_scale, last_sp_x_mm, last_sp_a_deg, last_sp_z_mm, last_sp_vol_ml };
    // PID defaults
    const getv=id=> Number((document.getElementById(id)||{}).value||0);
    Object.assign(payload, {
      kpX:getv('def_kpX'), kiX:getv('def_kiX'), kdX:getv('def_kdX'),
      kpA:getv('def_kpA'), kiA:getv('def_kiA'), kdA:getv('def_kdA')
    });
    // policy/scheduler
    const polEl=document.getElementById('sel_policy'); if(polEl){ payload.command_policy = polEl.value; }
    const schEl=document.getElementById('chk_scheduler'); if(schEl){ payload.scheduler_enabled = schEl.checked; }
    try{
      await jpost('/api/settings', payload);
      toast('Settings guardados');
    }catch{ toast('Error guardando settings'); }
  }
  const btnSaveSettings=document.getElementById('btn_save_settings'); if(btnSaveSettings){ btnSaveSettings.onclick = saveSettings; }

  const btnApplyPIDDef=document.getElementById('btn_apply_pid_defaults'); if(btnApplyPIDDef){ btnApplyPIDDef.onclick = async ()=>{
    const payload={ pid_settings: {
      pidX:{ kp:Number(document.getElementById('def_kpX').value||0), ki:Number(document.getElementById('def_kiX').value||0), kd:Number(document.getElementById('def_kdX').value||0) },
      pidA:{ kp:Number(document.getElementById('def_kpA').value||0), ki:Number(document.getElementById('def_kiA').value||0), kd:Number(document.getElementById('def_kdA').value||0) }
    } };
    try{ await ControlChannel.send(payload); toast('PID aplicados'); }catch{ toast('Error aplicando PID'); }
  }; }

  const btnApplyPolicy=document.getElementById('btn_apply_policy'); if(btnApplyPolicy){
    btnApplyPolicy.onclick = ()=> toast('Políticas gestionadas automáticamente por el hub');
    btnApplyPolicy.disabled = true;
  }

  // ------------- Real-time Chart -------------
  const canvas = document.getElementById('chart');
  const ctx = canvas? canvas.getContext('2d') : null;
  const history = []; // gráfica local
  const MAX_SEC = 120;
  let freeze = false;
  const btnFreeze = document.getElementById('btn-freeze'); if(btnFreeze){ btnFreeze.onclick = ()=>{ freeze=!freeze; btnFreeze.textContent = freeze? 'Reanudar':'Pausar'; }; }
  const btnClear = document.getElementById('btn-clear'); if(btnClear){ btnClear.onclick = ()=>{ history.length=0; drawChart(); }; }

  function drawChart(){
    if(!canvas || !ctx) return;
    const W=canvas.width, H=canvas.height;
    ctx.clearRect(0,0,W,H);
    ctx.globalAlpha=0.3; ctx.strokeStyle="#273059";
    for(let i=0;i<10;i++){ const y=(H/10)*i; ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke(); }
    ctx.globalAlpha=1;

    if(history.length<2) return;
    const t0=history[0].t, tN=history[history.length-1].t, span=Math.max(1,tN-t0);
    const xMax=Math.max(...history.map(p=>p.x),1), aMax=Math.max(...history.map(p=>p.a),1),
          vMax=Math.max(...history.map(p=>p.vol),1), fMax=Math.max(...history.map(p=>p.flow),1), zMax=Math.max(...history.map(p=>p.z||0),1);

    // Autoescala por serie (independiente) y eje secundario para flow
    const scaleY = (key, maxVal)=>{
      if(maxVal<=0) return v=>H/2;
      return v=> H - (Math.max(0, Math.min(1, v/maxVal))) * (H-10) - 5;
    };
    const sx = scaleY('x', xMax), sa=scaleY('a', aMax), sv=scaleY('vol', vMax), sf=scaleY('flow', fMax), sz=scaleY('z', zMax);

    const plot=(key,color,yf)=>{
      ctx.strokeStyle=color; ctx.lineWidth=1.5; ctx.beginPath();
      history.forEach((p,i)=>{
        const px=((p.t-t0)/span)*(W-10)+5, py=yf(p[key]||0);
        if(i===0) ctx.moveTo(px,py); else ctx.lineTo(px,py);
      });
      ctx.stroke();
      // dibujar puntos sutiles para flow
      if(key==='flow'){
        ctx.fillStyle=color; ctx.globalAlpha=0.7;
        history.forEach(p=>{ const px=((p.t-t0)/span)*(W-10)+5, py=yf(p[key]||0); ctx.beginPath(); ctx.arc(px,py,1.5,0,Math.PI*2); ctx.fill(); });
        ctx.globalAlpha=1;
      }
    };
    plot('x','#7affc2',sx);
    plot('a','#ffc07a',sa);
    plot('vol','#7ab6ff',sv);
    plot('flow','#ff7ae0',sf);
    // Z opcional
    if(history.some(p=>typeof p.z!=='undefined')){
      plot('z','#c77dff',sz);
    }
  }

  // ------------- SVG anim (corredera + ángulo) -------------
  const svgCarro = document.getElementById("carro");
  const svgAguja = document.getElementById("aguja");
  function updateSVG(x_mm, a_deg){
    if(svgCarro){
      const x = 55 + Math.max(0, Math.min(400, Number(x_mm||0))) * (110/400);
      svgCarro.setAttribute("x", String(x));
    }
    if(svgAguja){
      const ang = Math.max(0, Math.min(360, Number(a_deg||0)));
      const rad = (ang-90) * Math.PI/180;
      const cx=110, cy=110, r=80;
      const x2 = cx + Math.cos(rad)*r;
      const y2 = cy + Math.sin(rad)*r;
      svgAguja.setAttribute("x2", String(x2));
      svgAguja.setAttribute("y2", String(y2));
    }
  }

  // Arrastre sobre el SVG para cambiar ángulo (arrastrando la punta de la aguja)
  (function enableAngleDrag(){
    const svg = document.getElementById('robot_svg'); if(!svg || !svgAguja) return;
    let dragging = false;
    const cx=110, cy=110;
    const setAFromEvent = (ev)=>{
      const rect = svg.getBoundingClientRect();
      const x = (ev.clientX||0) - rect.left;
      const y = (ev.clientY||0) - rect.top;
      const dx = x - cx, dy = y - cy;
      let ang = Math.atan2(dy, dx) * 180/Math.PI + 90; // invertir para nuestro 0° arriba
      while(ang < 0) ang += 360; while(ang >= 360) ang -= 360;
      const elA = document.getElementById('sp_a'); if(!elA) return;
      elA.value = String(Math.max(0, Math.min(360, ang)));
      elA.dispatchEvent(new Event('input'));
    };
    svg.addEventListener('mousedown', (ev)=>{ dragging = true; setAFromEvent(ev); });
    window.addEventListener('mousemove', (ev)=>{ if(dragging) setAFromEvent(ev); });
    window.addEventListener('mouseup',   ()=>{ dragging = false; });
    // soporte táctil simple
    svg.addEventListener('touchstart', (ev)=>{ dragging=true; if(ev.touches&&ev.touches[0]) setAFromEvent(ev.touches[0]); ev.preventDefault(); }, {passive:false});
    svg.addEventListener('touchmove',  (ev)=>{ if(!dragging) return; if(ev.touches&&ev.touches[0]) setAFromEvent(ev.touches[0]); ev.preventDefault(); }, {passive:false});
    svg.addEventListener('touchend',   ()=>{ dragging=false; });
  })();

  // ------------- Arena Control (drag → setpoints) -------------
  (function initArenaDrag(){
    const svg = document.getElementById('arena_svg'); if(!svg) return;
    const track = document.getElementById('arena_track');
    const carro = document.getElementById('arena_carro');
    const center = {x:160, y:160};
    let drag = null; // 'x' | 'a'
    const sendX = debounce((mm)=>{ if(chkX) chkX.checked=false; sendControl({ x_mm:mm, modo:(Number(chkX.checked)*1)|(Number(chkA.checked)*2) }); }, 80);
    const sendA = debounce((dg)=>{ if(chkA) chkA.checked=false; sendControl({ a_deg:dg, modo:(Number(chkX.checked)*1)|(Number(chkA.checked)*2) }); }, 80);

    function clientToLocal(ev){ const r=svg.getBoundingClientRect(); return { x:(ev.clientX||0)-r.left, y:(ev.clientY||0)-r.top }; }
    function onDown(ev){ const t=ev.target; if(t===carro){ drag='x'; ev.preventDefault(); return; } drag='a'; ev.preventDefault(); }
    function onMove(ev){ if(!drag) return; const p=clientToLocal(ev); if(drag==='x'){
        // Convertir p al marco rotado: rotar inverso por -ángulo actual
        const ang = (window._statusCache && _statusCache.a_deg) ? Number(_statusCache.a_deg)||0 : 0;
        const a = (-(ang-0))*Math.PI/180; // rotación inversa
        const dx = p.x-center.x, dy=p.y-center.y; const rx = dx*Math.cos(a)-dy*Math.sin(a); // x en marco pista
        // map rx en [-90, +90] a [0,400]
        const localX = clamp(rx, -90, 90); const mm = (localX+90)*(400/180);
        sendX(mm);
      }else if(drag==='a'){
        let dg = Math.atan2(p.y-center.y, p.x-center.x)*180/Math.PI + 90; while(dg<0) dg+=360; while(dg>=360) dg-=360; sendA(dg);
      }
    }
    function onUp(){ drag=null; }
    svg.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    // Touch
    svg.addEventListener('touchstart', (ev)=>{ const t=ev.touches&&ev.touches[0]; if(!t) return; drag='a'; ev.preventDefault(); }, {passive:false});
    svg.addEventListener('touchmove', (ev)=>{ const t=ev.touches&&ev.touches[0]; if(!t||!drag) return; onMove(t); ev.preventDefault(); }, {passive:false});
    svg.addEventListener('touchend', onUp);
  })();

  // ------------- Telemetría vía WebSocket -------------
  let lastSerialOpenTs = 0;
  window._statusCache = null;

  function applyStatusSnapshot(s){
    if(!s) return;
    window._statusCache = s;
    if(typeof s.rx_age_ms === 'number'){ rxAgeMs = Number(s.rx_age_ms); }
    updateRxPillLabel();
    $("#t_x").textContent = fmt(s.x_mm||0);
    $("#t_a").textContent = fmt(s.a_deg||0);
    const zmm = Number(s.z_mm||0);
    const flowActual = Number((s.caudal_est_mls!=null?s.caudal_est_mls:s.flow_est)||0);
    const tz=document.getElementById('t_z'); if(tz){ tz.textContent = fmt(zmm||0); }
    const rewardEl = document.getElementById('t_reward');
    if(rewardEl && s.reward !== undefined) { rewardEl.textContent = Number(s.reward).toFixed(3); }
    const rdz=document.getElementById('rd_z_mm'); if(rdz){ rdz.textContent = fmt(zmm||0); }
    const rdX=document.getElementById('rd_x_mm'); if(rdX){ rdX.textContent = fmt(s.x_mm||0); }
    const rdA=document.getElementById('rd_a_deg'); if(rdA){ rdA.textContent = fmt(s.a_deg||0); }
    updateSVG(s.x_mm, s.a_deg);
    $("#t_vol").textContent = fmt(s.volumen_ml||0);
    $("#t_flow").textContent = fmt(flowActual);
    const rdV=document.getElementById('rd_vol_ml'); if(rdV){ rdV.textContent = fmt(s.volumen_ml||0); }
    $("#t_limx").textContent = s.lim_x||0; $("#t_lima").textContent = s.lim_a||0;
    $("#t_homx").textContent = s.homing_x||0; $("#t_homa").textContent = s.homing_a||0;
    const portLabel = document.getElementById('t_port'); if(portLabel){ portLabel.textContent = s.serial_port || "—"; }
    const serialPill = $("#pill-serial"); if(serialPill){ serialPill.textContent = `Serial: ${s.serial_port||'—'} @ ${s.baudrate||''}`; }
    if(robotPill){
      const label = s.robot_label || s.robot_id || '—';
      robotPill.textContent = `Robot: ${label}`;
      robotPill.classList.toggle('warn', !!s.is_virtual);
    }
    if(robotSel && s.robot_id && robotSel.value !== s.robot_id){
      robotSel.value = s.robot_id;
    }
    isSerialOpen = !!s.serial_open;
    if(isSerialOpen){ lastSerialOpenTs = Date.now(); }
    refreshOverlay();
    const modoEl = document.getElementById('t_modo_tx'); if(modoEl){ modoEl.textContent = String(s.modo!=null?s.modo:"—"); }

    const setText=(id,val)=>{ const el=document.getElementById(id); if(el){ el.textContent=String(val); } };
    setText('k_steps_mm', (s.pasosPorMM!=null?fmt(s.pasosPorMM,2):'—'));
    setText('k_steps_deg', (s.pasosPorGrado!=null?fmt(s.pasosPorGrado,2):'—'));
    setText('k_usar_flujo', (s.usarSensorFlujo? 'sí':'no'));
    setText('k_caudal_bomba', (s.caudalBombaMLs!=null?fmt(s.caudalBombaMLs,1):'—'));
    setText('k_kpX', (s.kpX!=null?fmt(s.kpX,2):'—'));
    setText('k_kiX', (s.kiX!=null?fmt(s.kiX,2):'—'));
    setText('k_kdX', (s.kdX!=null?fmt(s.kdX,2):'—'));
    setText('k_kpA', (s.kpA!=null?fmt(s.kpA,2):'—'));
    setText('k_kiA', (s.kiA!=null?fmt(s.kiA,2):'—'));
    setText('k_kdA', (s.kdA!=null?fmt(s.kdA,2):'—'));

    const ex = clamp((Math.abs((s.energies&&s.energies.x)||0)/255)*100,0,100);
    const ea = clamp((Math.abs((s.energies&&s.energies.a)||0)/255)*100,0,100);
    const eb = clamp((Math.abs((s.energies&&s.energies.bomba)||0)/255)*100,0,100);
    $("#g_ex").style.width = ex+"%";
    $("#g_ea").style.width = ea+"%";
    $("#g_eb").style.width = eb+"%";
    const rdEX=document.getElementById('rd_en_x'); if(rdEX){ rdEX.textContent = String((s.energies&&s.energies.x)||0); }
    const rdEA=document.getElementById('rd_en_a'); if(rdEA){ rdEA.textContent = String((s.energies&&s.energies.a)||0); }
    const pumpEnergy = (s.energies&&s.energies.bomba)||0;
    const rdEB=document.getElementById('rd_en_b'); if(rdEB){ rdEB.textContent = String(pumpEnergy); }
    const pumpSlider = document.getElementById('en_b');
    if(pumpSlider){
      pumpSlider.value = String(pumpEnergy);
      const out = document.getElementById('en_b_o'); if(out){ out.textContent = String(pumpEnergy); }
    }

    try{
      const goal = Number((s.volumen_objetivo_ml!=null)?s.volumen_objetivo_ml:0);
      const cur = Number(s.volumen_ml||0);
      const bar = document.getElementById('g_vol_goal');
      if(bar){
        if(goal>0){
          const pct = clamp((cur/goal)*100,0,100);
          bar.style.width = pct+"%";
          let eta='';
          const flow = flowActual;
          if(flow>0 && cur<goal){
            const secs = Math.max(0, (goal-cur)/flow);
            const mm = Math.floor(secs/60), ss = Math.round(secs%60);
            eta = ` • ETA ${mm}m ${ss}s`;
          }
          bar.dataset.goal = `${fmt(cur,1)} / ${fmt(goal,1)}${eta}`;
          bar.parentElement.dataset.visible = "1";
        }else{
          bar.style.width = "0%";
          if(bar.parentElement) bar.parentElement.dataset.visible = "0";
        }
      }
    }catch{}

    try{
      const tank = document.getElementById('tank_water');
      const tankHighlight = document.getElementById('tank_highlight');
      const tankPct = document.getElementById('tank_pct');
      if(tank && tankPct){
        const goal = Number.isFinite(s.volumen_objetivo_ml) ? Number(s.volumen_objetivo_ml) : 0;
        const cur = Number.isFinite(s.volumen_ml) ? Number(s.volumen_ml) : 0;
        const manualInput = document.getElementById('fw_volume') || document.getElementById('sp_vol');
        let fallback = manualInput ? Number(manualInput.value) : NaN;
        if(!Number.isFinite(fallback) || fallback <= 0){
          fallback = 100;
        }
        let ref = goal > 0 ? goal : fallback;
        if(!Number.isFinite(ref) || ref <= 0){
          ref = 100;
        }
        const safeCur = Math.max(0, cur);
        const p = clamp(safeCur / ref, 0, 1);
        const H = 140, Y0 = 25;
        const h = Math.round(H * p);
        const y = Y0 + (H - h);
        const updateRect = (el)=>{
          if(!el) return;
          el.setAttribute('y', String(y));
          el.setAttribute('height', String(h));
        };
        updateRect(tank);
        updateRect(tankHighlight);
        tankPct.textContent = `${Math.round(p*100)}%`;
        const fill = p>0.5? '#29d3b0' : (p>0.2? '#ffb84d' : '#ff6a6a');
        tank.style.filter = `drop-shadow(0 0 6px ${fill}88)`;
      }
    }catch{}

    const setT=(id,val)=>{ const el=document.getElementById(id); if(el){ el.textContent = fmt(val); } };
    setT('gx', s.x_mm||0); setT('ga', s.a_deg||0); setT('gvol', s.volumen_ml||0); setT('gflow', flowActual);
    if(FlowWidgetCtrl){
      FlowWidgetCtrl.updateTelemetry({
        flowActual,
        flowTarget: (s.caudalBombaMLs!=null)?Number(s.caudalBombaMLs):null,
        volumeActual: Number(s.volumen_ml||0),
        volumeTarget: (s.volumen_objetivo_ml!=null)?Number(s.volumen_objetivo_ml):null
      });
    }

    const ang = Math.max(0, Math.min(360, Number(s.a_deg||0)));
    const track = document.getElementById('arena_track'); if(track){ track.setAttribute('transform', `rotate(${ang} 160 160)`); }
    const ac = document.getElementById('arena_carro'); if(ac){ const x = 70 + Math.max(0, Math.min(400, Number(s.x_mm||0))) * (180/400); ac.setAttribute('x', String(x)); }
    const aa = document.getElementById('arena_aguja'); if(aa){ const rad=(ang-90)*Math.PI/180; const cx=160, cy=160, r=120; aa.setAttribute('x2', String(cx+Math.cos(rad)*r)); aa.setAttribute('y2', String(cy+Math.sin(rad)*r)); }

    if(!freeze){
      const now=Date.now()/1000;
      history.push({t:now, x:s.x_mm, a:s.a_deg, vol:s.volumen_ml, flow:(s.caudal_est_mls!=null?s.caudal_est_mls:s.flow_est), z:zmm});
      while(history.length && (now-history[0].t)>MAX_SEC) history.shift();
      drawChart();
    }
    refreshOverlay();
  }

  function createTelemetryChannel(onSnapshot){
    let socket = null;
    let reconnectTimer = null;
    const connect = ()=>{
      if(socket){
        try{ socket.close(); }catch{}
      }
      console.info('[ws/telemetry] connecting...');
      socket = new WebSocket(`${WS_BASE}/ws/telemetry`);
      socket.addEventListener('open', ()=> setConnectionState('telemetry', true));
      socket.addEventListener('message', (event)=>{
        let data = null;
        try{ data = JSON.parse(event.data || "{}"); }catch{ return; }
        if(data.type === "telemetry"){
          const status = data.status || {};
          if(onSnapshot) onSnapshot(status);
        }
      });
      socket.addEventListener('close', ()=>{
        setConnectionState('telemetry', false);
        scheduleReconnect();
      });
      socket.addEventListener('error', (err)=>{
        console.error('[ws/telemetry] error', err);
        socket && socket.close();
      });
    };
    const scheduleReconnect = ()=>{
      if(reconnectTimer) return;
      reconnectTimer = setTimeout(()=>{ reconnectTimer=null; connect(); }, 1500);
    };
    connect();
    return { restart: ()=> connect() };
  }

  const TelemetryChannel = createTelemetryChannel(applyStatusSnapshot);
  if(typeof window !== 'undefined'){
    window.TelemetryChannel = TelemetryChannel;
  }

  function pollDebug(){
    const status = window._statusCache;
    const dbg = document.getElementById('dbg_serial');
    if(dbg){
      dbg.textContent = status ? JSON.stringify(status, null, 2) : 'Sin telemetría disponible.';
    }
    const rxEl = document.getElementById('rx_age_ms'); if(rxEl) rxEl.textContent = String(Math.round(rxAgeMs||0));
    const txEl = document.getElementById('tx_age_ms'); if(txEl) txEl.textContent = connectionFlags.control ? 'WS' : '—';
    updateRxPillLabel();
  }

  // Botones depuración
  const bRef = document.getElementById('btn_refresh_dbg'); if(bRef){ bRef.onclick = ()=>{ pollDebug(); toast('Refrescado'); }; }
  const bCopy = document.getElementById('btn_copy_tx'); if(bCopy){ bCopy.onclick = async ()=>{
    try{
      const payload = ControlChannel.getLastPayload();
      if(!payload){ toast('Sin TX reciente'); return; }
      await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
      toast('TX copiado');
    }catch{ toast('No se pudo copiar'); }
  }; }
  const bClr = document.getElementById('btn_clear_dbg'); if(bClr){ bClr.onclick = ()=>{ const el=document.getElementById('dbg_serial'); if(el) el.textContent=''; }; }

  // ------------- PyBullet frame polling -------------
  (function initPyBulletFeed(){
    const img = document.getElementById('pybullet_view');
    const status = document.getElementById('pybullet_status');
    if(!img || !window.fetch) return;
    let lastUrl = null;
    let timer = null;
    const setState = (msg, ok)=>{
      if(status) status.textContent = msg;
      img.style.opacity = ok ? 1 : 0.2;
    };
    const fetchFrame = async ()=>{
      try{
        const res = await fetch(`/api/pybullet/frame?ts=${Date.now()}`, { cache: 'no-store' });
        if(res.status === 404){
          setState("PyBullet no disponible en este servidor.", false);
          if(timer){ clearInterval(timer); timer = null; }
          return;
        }
        if(!res.ok){
          throw new Error(`HTTP ${res.status}`);
        }
        const blob = await res.blob();
        if(lastUrl){ URL.revokeObjectURL(lastUrl); }
        lastUrl = URL.createObjectURL(blob);
        img.src = lastUrl;
        setState("Visualización PyBullet en vivo", true);
      }catch(err){
        setState("Esperando frame PyBullet...", false);
      }
    };
    fetchFrame();
    timer = setInterval(fetchFrame, 1500);
    window.addEventListener('beforeunload', ()=>{
      if(lastUrl){ URL.revokeObjectURL(lastUrl); }
      if(timer){ clearInterval(timer); }
    });
  })();

  function initFlowWidget(){
    const widget = document.getElementById('flow_widget');
    const volumeInput = document.getElementById('fw_volume');
    const flowInput = document.getElementById('fw_flow');
    const startBtn = document.getElementById('fw_start');
    const stopBtn = document.getElementById('fw_stop');
    const resetBtn = document.getElementById('fw_reset');
    if(!widget || !volumeInput || !flowInput || !startBtn || !stopBtn){
      return null;
    }
    const stats = {
      flowActual: document.getElementById('fw_flow_actual'),
      flowTarget: document.getElementById('fw_flow_target'),
      volumeActual: document.getElementById('fw_volume_actual'),
      volumeTarget: document.getElementById('fw_volume_target'),
      volumeRemaining: document.getElementById('fw_volume_remaining')
    };
    const limits = {
      volume: { min: Number(volumeInput.min||0), max: Number(volumeInput.max||2000), precision: 0 },
      flow: { min: Number(flowInput.min||0), max: Number(flowInput.max||40), precision: 1 }
    };
    const state = {
      targetVolume: 0,
      targetFlow: 0,
      lastVolumeActual: null,
      lastFlowActual: null,
      userOverrideVolume: false,
      userOverrideFlow: false,
      editingVolume: false,
      editingFlow: false
    };

    const clampValue = (value, bounds)=>
      Math.min(bounds.max, Math.max(bounds.min, Number.isFinite(value)?value:bounds.min));

    const formatNumber = (value, precision)=> Number(value).toFixed(precision);

    const getValue = (input, bounds)=>{
      const num = Number(input.value);
      return clampValue(num, bounds);
    };

    const setValue = (input, value, bounds)=>{
      const v = clampValue(value, bounds);
      input.value = formatNumber(v, bounds.precision);
      return v;
    };

    const formatMetric = (value, unit, precision)=>{
      if(value === null || value === undefined || Number.isNaN(value)){
        return '—';
      }
      return `${Number(value).toFixed(precision)} ${unit}`.trim();
    };

    const refreshStats = ()=>{
      if(stats.flowActual){
        stats.flowActual.textContent = formatMetric(state.lastFlowActual, 'ml/s', limits.flow.precision);
      }
      if(stats.volumeActual){
        stats.volumeActual.textContent = formatMetric(state.lastVolumeActual, 'ml', limits.volume.precision);
      }
      if(stats.flowTarget){
        stats.flowTarget.textContent = formatMetric(state.targetFlow, 'ml/s', limits.flow.precision);
      }
      if(stats.volumeTarget){
        stats.volumeTarget.textContent = formatMetric(state.targetVolume, 'ml', limits.volume.precision);
      }
      if(stats.volumeRemaining){
        const remaining = (Number.isFinite(state.targetVolume) && Number.isFinite(state.lastVolumeActual))
          ? Math.max(0, state.targetVolume - state.lastVolumeActual)
          : null;
        stats.volumeRemaining.textContent = formatMetric(remaining, 'ml', limits.volume.precision);
      }
    };

    const setStateTarget = (target, value, {fromTelemetry=false}={})=>{
      const key = target === 'flow' ? 'targetFlow' : 'targetVolume';
      const bounds = limits[target === 'flow' ? 'flow' : 'volume'];
      const input = target === 'flow' ? flowInput : volumeInput;
      const editingKey = target === 'flow' ? 'editingFlow' : 'editingVolume';
      const overrideKey = target === 'flow' ? 'userOverrideFlow' : 'userOverrideVolume';
      const val = clampValue(value, bounds);
      state[key] = val;
      if(!state[editingKey]){
        setValue(input, val, bounds);
      }
      if(!fromTelemetry){
        state[overrideKey] = true;
      }
      refreshStats();
    };

    state.targetVolume = getValue(volumeInput, limits.volume);
    state.targetFlow = getValue(flowInput, limits.flow);
    refreshStats();

    const adjustValue = (target, delta)=>{
      const input = target==='flow' ? flowInput : volumeInput;
      const bounds = limits[target==='flow' ? 'flow' : 'volume'];
      const next = getValue(input, bounds) + delta;
      setStateTarget(target, next);
    };

    widget.querySelectorAll('[data-fw-step]').forEach(btn=>{
      btn.addEventListener('click', ()=>{
        const target = btn.dataset.target === 'flow' ? 'flow' : 'volume';
        const step = Number(btn.dataset.fwStep||0);
        if(!step) return;
        adjustValue(target, step);
      });
    });

    const bindInput = (input, target)=>{
      input.addEventListener('focus', ()=>{
        state[target==='flow'?'editingFlow':'editingVolume'] = true;
      });
      input.addEventListener('blur', ()=>{
        state[target==='flow'?'editingFlow':'editingVolume'] = false;
        setStateTarget(target, getValue(input, limits[target==='flow'?'flow':'volume']));
      });
      input.addEventListener('change', ()=>{
        setStateTarget(target, getValue(input, limits[target==='flow'?'flow':'volume']));
      });
      input.addEventListener('input', ()=>{
        const val = Number(input.value);
        if(Number.isFinite(val)){
          setStateTarget(target, val);
        }
      });
    };
    bindInput(volumeInput, 'volume');
    bindInput(flowInput, 'flow');

    const adoptTelemetryTarget = (target, value)=>{
      if(value===null || value===undefined) return;
      const overrideKey = target==='flow'?'userOverrideFlow':'userOverrideVolume';
      if(state[overrideKey]) return;
      setStateTarget(target, value, { fromTelemetry: true });
    };

    const sendPayload = async (payload, okMsg)=>{
      if(!connectionFlags.control){
        toast('Sin conexión con el canal de control');
        if(ControlChannel && typeof ControlChannel.restart === 'function'){
          ControlChannel.restart();
        }
        return;
      }
      try{
        await ControlChannel.send(payload);
        toast(okMsg || 'Comando enviado');
      }catch(err){
        toast('No se pudo enviar');
      }
    };

    startBtn.addEventListener('click', ()=>{
      const payload = {
        setpoints: { volumen_ml: getValue(volumeInput, limits.volume) },
        flow: { caudal_bomba_mls: getValue(flowInput, limits.flow) }
      };
      setStateTarget('volume', payload.setpoints.volumen_ml);
      setStateTarget('flow', payload.flow.caudal_bomba_mls);
      sendPayload(payload, 'Flujo aplicado');
    });
    stopBtn.addEventListener('click', ()=>{
      const curVol = (window._statusCache && typeof window._statusCache.volumen_ml === 'number')
        ? Number(window._statusCache.volumen_ml) : null;
      const payload = { flow: { caudal_bomba_mls: 0 } };
      if(Number.isFinite(curVol)){
        payload.setpoints = { volumen_ml: curVol };
      }
      sendPayload(payload, 'Bomba detenida');
    });
    if(resetBtn){
      resetBtn.addEventListener('click', ()=>{
        state.userOverrideVolume = false;
        state.targetVolume = 0;
        setValue(volumeInput, 0, limits.volume);
        refreshStats();
        sendPayload({ reset_volumen: 1 }, 'Volumen reiniciado');
      });
    }

    return {
      updateTelemetry({ flowActual, flowTarget, volumeActual, volumeTarget }){
        if(Number.isFinite(flowActual)){
          state.lastFlowActual = Number(flowActual);
        }
        if(Number.isFinite(volumeActual)){
          state.lastVolumeActual = Number(volumeActual);
        }
        if(Number.isFinite(flowTarget)){
          adoptTelemetryTarget('flow', flowTarget);
        }
        if(Number.isFinite(volumeTarget)){
          adoptTelemetryTarget('volume', volumeTarget);
        }
        refreshStats();
      }
    };
  }

  FlowWidgetCtrl = initFlowWidget();

  // ------------- Control helpers (POST unificado a /api/control) -------------
  async function sendControl(params){
    // Mapear params sueltos (compat UI) a payload unificado
    const body={};
    // Passthrough para objetos anidados (nuevo Control)
    if(params && typeof params.setpoints==='object' && params.setpoints!==null){
      body.setpoints = {};
      const sp = params.setpoints || {};
      if(sp.x_mm!=null) body.setpoints.x_mm = Number(sp.x_mm);
      if(sp.a_deg!=null) body.setpoints.a_deg = Number(sp.a_deg);
      if(sp.volumen_ml!=null) body.setpoints.volumen_ml = Number(sp.volumen_ml);
      if(sp.vol_ml!=null && body.setpoints.volumen_ml==null) body.setpoints.volumen_ml = Number(sp.vol_ml);
      if(sp.z_mm!=null) body.setpoints.z_mm = Number(sp.z_mm);
    }
    // Motion (velocidades opcionales)
    if(params && typeof params.motion==='object' && params.motion!==null){
      body.motion = {};
      const mv = params.motion || {};
      if(mv.z_speed_deg_s!=null) body.motion.z_speed_deg_s = Number(mv.z_speed_deg_s);
    }
    if(params && typeof params.energies==='object' && params.energies!==null){
      body.energies = {};
      const en = params.energies || {};
      if(en.x!=null) body.energies.x = Number(en.x);
      if(en.a!=null) body.energies.a = Number(en.a);
      if(en.bomba!=null) body.energies.bomba = Number(en.bomba);
      if(en.energy_x!=null && body.energies.x==null) body.energies.x = Number(en.energy_x);
      if(en.energy_a!=null && body.energies.a==null) body.energies.a = Number(en.energy_a);
      if(en.energy_bomba!=null && body.energies.bomba==null) body.energies.bomba = Number(en.energy_bomba);
    }
    if(params.x_mm!=null || params.a_deg!=null || params.vol_ml!=null || params.z_mm!=null){
      body.setpoints={};
      if(params.x_mm!=null) body.setpoints.x_mm=Number(params.x_mm);
      if(params.a_deg!=null) body.setpoints.a_deg=Number(params.a_deg);
      if(params.vol_ml!=null) body.setpoints.volumen_ml=Number(params.vol_ml);
      if(params.z_mm!=null) body.setpoints.z_mm=Number(params.z_mm);
    }
    if(params.energy_x!=null || params.energy_a!=null || params.energy_bomba!=null){
      body.energies={};
      if(params.energy_x!=null) body.energies.x=Number(params.energy_x);
      if(params.energy_a!=null) body.energies.a=Number(params.energy_a);
      if(params.energy_bomba!=null) body.energies.bomba=Number(params.energy_bomba);
    }
    if(params.modo!=null){ body.modo=Number(params.modo); }
    if(params.reset_x){ body.reset_x=1; }
    if(params.reset_a){ body.reset_a=1; }
    if(params.reset_vol || params.reset_volumen){ body.reset_volumen=1; }
    await ControlChannel.send(body);
  }

  // ------------- Operación -------------
  const chkX = $("#chk_manual_x"), chkA = $("#chk_manual_a");

  const recomputeModoBits = ()=> (Number(chkX.checked)*1) | (Number(chkA.checked)*2);

  chkX.onchange = async ()=>{ await sendControl({modo:recomputeModoBits()}); toast("Modo actualizado"); };
  chkA.onchange = async ()=>{ await sendControl({modo:recomputeModoBits()}); toast("Modo actualizado"); };

  const btnPidOn = document.getElementById('btn_pid_on');
  if(btnPidOn){ btnPidOn.style.display='none'; }

  // Auto-aplicar setpoints con debounce + botón aplicar
  const applySetpointsNow = async ()=>{
    const sx = Number($("#sp_x") && $("#sp_x").value || 0);
    const sa = Number($("#sp_a") && $("#sp_a").value || 0);
    const sv = Number($("#sp_vol") && $("#sp_vol").value || 0);
    const sz = Number($("#sp_z") && $("#sp_z").value || 0);
    // Forzar automático en ambos ejes al aplicar setpoints
    if(chkX) chkX.checked = false;
    if(chkA) chkA.checked = false;
    const motion={};
    const zspeedEl=document.getElementById('sp_z_speed'); if(zspeedEl){ motion.z_speed_deg_s = Number(zspeedEl.value||0); }
    await sendControl({ setpoints:{ x_mm: sx, a_deg: sa, volumen_ml: sv, z_mm: sz }, motion, modo: (Number(chkX.checked)*1) | (Number(chkA.checked)*2) });
  };
  const debouncedSetpoints = debounce(applySetpointsNow, 250);
  const spX = document.getElementById('sp_x'); if(spX){ spX.oninput = debouncedSetpoints; spX.onchange = applySetpointsNow; }
  const spA = document.getElementById('sp_a'); if(spA){ spA.oninput = debouncedSetpoints; spA.onchange = applySetpointsNow; }
  const spV = document.getElementById('sp_vol'); if(spV){ spV.oninput = debouncedSetpoints; spV.onchange = applySetpointsNow; }
  const spZ = document.getElementById('sp_z'); if(spZ){ spZ.oninput = debouncedSetpoints; spZ.onchange = applySetpointsNow; }
  // Sliders sincronizados y botones +/- para X/A/Z/Vol
  const byId = (id)=> document.getElementById(id);
  const sl_x = byId('sl_x'), sl_a = byId('sl_a'), sl_z = byId('sl_z'), sl_vol = byId('sl_vol');
  if(sl_x && spX){ sl_x.oninput = ()=>{ spX.value = sl_x.value; spX.oninput && spX.oninput(); }; }
  if(sl_a && spA){ sl_a.oninput = ()=>{ spA.value = sl_a.value; spA.oninput && spA.oninput(); }; }
  if(sl_z && spZ){ sl_z.oninput = ()=>{ spZ.value = sl_z.value; spZ.oninput && spZ.oninput(); }; }
  if(sl_vol && spV){ sl_vol.oninput = ()=>{ spV.value = sl_vol.value; spV.oninput && spV.oninput(); }; }
  const inc = (el, delta, min, max)=>{ if(!el) return; const v = Math.max(min, Math.min(max, Number(el.value||0) + delta)); el.value = String(v); el.oninput && el.oninput(); };
  const bind = (btnId, el, delta, min, max)=>{ const b=byId(btnId); if(b&&el){ b.onclick = ()=> inc(el, delta, min, max); } };
  bind('btn_x_dec10', spX, -10, 0, 400); bind('btn_x_dec1', spX, -1, 0, 400); bind('btn_x_inc1', spX, +1, 0, 400); bind('btn_x_inc10', spX, +10, 0, 400);
  bind('btn_a_dec10', spA, -10, 0, 300); bind('btn_a_dec1', spA, -1, 0, 300); bind('btn_a_inc1', spA, +1, 0, 300); bind('btn_a_inc10', spA, +10, 0, 300);
  bind('btn_z_dec10', spZ, -10, 0, 200); bind('btn_z_dec1', spZ, -1, 0, 200); bind('btn_z_inc1', spZ, +1, 0, 200); bind('btn_z_inc10', spZ, +10, 0, 200);
  bind('btn_v_dec10', spV, -10, 0, 100); bind('btn_v_dec1', spV, -1, 0, 100); bind('btn_v_inc1', spV, +1, 0, 100); bind('btn_v_inc10', spV, +10, 0, 100);
  const btnApplySP = document.getElementById('btn_apply_sp'); if(btnApplySP){ btnApplySP.onclick = async ()=>{ await applySetpointsNow(); toast('Setpoints aplicados'); }; }

  // Controles rápidos de ángulo ±1/±10
  const stepA = (delta)=>{ const el=document.getElementById('sp_a'); if(!el) return; const cur=Number(el.value||0); el.value=String(Math.max(0, Math.min(300, cur+delta))); el.dispatchEvent(new Event('input')); };
  const bDec10 = document.getElementById('btn_a_dec10'); if(bDec10){ bDec10.onclick = ()=> stepA(-10); }
  const bDec1  = document.getElementById('btn_a_dec1');  if(bDec1){  bDec1.onclick  = ()=> stepA(-1); }
  const bInc1  = document.getElementById('btn_a_inc1');  if(bInc1){  bInc1.onclick  = ()=> stepA(+1); }
  const bInc10 = document.getElementById('btn_a_inc10'); if(bInc10){ bInc10.onclick = ()=> stepA(+10); }

  const btnResetVol = document.getElementById('btn_reset_vol');
  if(btnResetVol){ btnResetVol.onclick = async ()=>{ await sendControl({reset_volumen:1}); toast("Volumen reseteado"); }; }

  $("#en_x").oninput = e=> { $("#en_x_o").textContent = e.target.value; };
  $("#en_a").oninput = e=> { $("#en_a_o").textContent = e.target.value; };
  $("#en_b").oninput = e=> { $("#en_b_o").textContent = e.target.value; };

  // Auto-aplicar energías con debounce continuo y forzar modo manual según sliders
  const ALLOW_MANUAL_PUMP_ENERGY = false;

  const applyEnergiesNow = async ()=>{
    const vx = Number($("#en_x") && $("#en_x").value || 0);
    const va = Number($("#en_a") && $("#en_a").value || 0);
    const vb = Number($("#en_b") && $("#en_b").value || 0);
    if(chkX && Math.abs(vx) > 0){ chkX.checked = true; }
    if(chkA && Math.abs(va) > 0){ chkA.checked = true; }
    const payload = {
      modo: recomputeModoBits(),
      energy_x: vx,
      energy_a: va
    };
    if(ALLOW_MANUAL_PUMP_ENERGY){
      payload.energy_bomba = vb;
    }
    await sendControl(payload);
  };
  const debouncedEnergies = debounce(applyEnergiesNow, 120);
  const enX = document.getElementById('en_x'); if(enX){ enX.oninput = ()=>{ $("#en_x_o").textContent = enX.value; debouncedEnergies(); }; }
  const enA = document.getElementById('en_a'); if(enA){ enA.oninput = ()=>{ $("#en_a_o").textContent = enA.value; debouncedEnergies(); }; }
  const enB = document.getElementById('en_b'); 
  if(enB){
    if(!ALLOW_MANUAL_PUMP_ENERGY){
      enB.disabled = true;
      enB.title = "La bomba se controla desde Ejecutar/Detener";
      enB.addEventListener('input', ()=>{ $("#en_b_o").textContent = enB.value; });
    }else{
      enB.oninput = ()=>{ $("#en_b_o").textContent = enB.value; debouncedEnergies(); };
    }
  }

  $("#btn_stop_all").onclick = async ()=>{
    $("#en_x").value=0; $("#en_a").value=0; $("#en_b").value=0; $("#en_x_o").textContent="0"; $("#en_a_o").textContent="0"; $("#en_b_o").textContent="0";
    await sendControl({energy_x:0, energy_a:0, energy_bomba:0});
    toast("Paro enviado");
  };

  const btnHomeX = document.getElementById('btn_home_x'); if(btnHomeX){ btnHomeX.onclick = async ()=>{ await sendControl({reset_x:1}); toast("Homing X"); }; }
  const btnHomeA = document.getElementById('btn_home_a'); if(btnHomeA){ btnHomeA.onclick = async ()=>{ await sendControl({reset_a:1}); toast("Homing A"); }; }
  const btnResetAll = document.getElementById('btn_reset_all'); if(btnResetAll){ btnResetAll.onclick = async ()=>{ await sendControl({reset_x:1, reset_a:1, reset_volumen:1}); toast("Reset X+A+Volumen"); }; }

  // Acciones rápidas
  const btnWater = document.getElementById('btn_water'); if(btnWater){ btnWater.onclick = async ()=>{ try{ await jpost('/api/water',{}); toast('Agua ON'); }catch{ toast('Error agua'); } }; }
  const btnHomeG = document.getElementById('btn_home_global'); if(btnHomeG){ btnHomeG.onclick = async ()=>{ try{ await jpost('/api/home',{}); toast('Home enviado'); }catch{ toast('Error home'); } }; }
  const btnStopG = document.getElementById('btn_stop_global'); if(btnStopG){ btnStopG.onclick = async ()=>{ try{ await jpost('/api/stop',{}); toast('PARO'); }catch{ toast('Error paro'); } }; }

  // ------------- PID / Calibración / Flujo -------------
  // (Controles PID removidos de la UI)
  const btnApplySteps = document.getElementById('btn_apply_steps');
  if(btnApplySteps){ btnApplySteps.onclick = async ()=>{
    await ControlChannel.send({calibration:{steps_mm:Number($("#steps_mm").value||0), steps_deg:Number($("#steps_deg").value||0)}});
    toast("Calibración aplicada");
  }; }
  const btnApplyFlujo = document.getElementById('btn_apply_flujo');
  if(btnApplyFlujo){ btnApplyFlujo.onclick = async ()=>{
    await ControlChannel.send({flow:{
      usar_sensor_flujo: $("#chk_sensor_flujo").checked?1:0,
      caudal_bomba_mls: Number($("#caudal").value||0)
    } });
    toast("Ajustes de flujo aplicados");
  }; }

  // ------------- Hotkeys -------------
  // ------------- Hotkeys -------------
  window.addEventListener("keydown", async (e)=>{
    if(e.target && ["INPUT","TEXTAREA","SELECT"].includes(e.target.tagName)) return;
    const k=e.key.toLowerCase();
    if(k==="m"){
      chkX.checked=!chkX.checked; chkA.checked=!chkA.checked;
      await sendControl({modo:recomputeModoBits()}); toast("Toggle manual/auto");
    }else if(k==="h"){
      await sendControl({reset_x:1, reset_a:1}); toast("Homing X/A");
    }else if(k==="v"){
      await sendControl({reset_vol:1}); toast("Reset Volumen");
    }else if(k==="arrowleft" || k==="arrowright"){
      const step = e.shiftKey?10:(e.altKey?0.5:1);
      const delta = (k==="arrowright"?+step:-step);
      const elA=document.getElementById('sp_a'); if(elA){ elA.value=String(Math.max(0, Math.min(360, Number(elA.value||0)+delta))); elA.dispatchEvent(new Event('input')); }
      e.preventDefault();
    }else if(k==="arrowup" || k==="arrowdown"){
      const step = e.shiftKey?10:(e.altKey?0.5:1);
      const delta = (k==="arrowup"?+step:-step);
      const elX=document.getElementById('sp_x'); if(elX){ elX.value=String(Math.max(0, Math.min(400, Number(elX.value||0)+delta))); elX.dispatchEvent(new Event('input')); }
      e.preventDefault();
    }
  });

  // Sin pestaña Control
  
})();
