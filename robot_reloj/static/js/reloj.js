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

  // ------------- Serial (toggle único) -------------
  async function refreshPorts(){
    const info = await jget("/api/serial/ports");
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
    const statusEl = $("#serial_status");
    if(statusEl){
      if(info.is_virtual){
        statusEl.textContent = "Modo virtual activo - Serial simulado";
      }else{
        const status = info.open ? `Conectado a ${info.current}` : "Desconectado";
        statusEl.textContent = `${status} · Puertos: ${ports}`;
      }
    }
    const btn = $("#btn_toggle_serial");
    if(btn){
      if(info.is_virtual){
        btn.textContent = "Virtual";
        btn.disabled = true;
        btn.classList.remove('warn');
      }else{
        btn.disabled = false;
        btn.textContent = info.open ? "Desconectar" : "Conectar";
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
      // Abrir/cerrar GUI PyBullet automáticamente según perfil
      try{
        if(id === 'virtual') await jpost('/api/visual/gui/start',{});
        else await jpost('/api/visual/gui/stop',{});
      }catch{}
      await refreshRobots();
      try{ await refreshPorts(); }catch{}
      try{ await refreshPbGui(); }catch{}
      pollStatus();
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

  // ------------- PyBullet GUI controls -------------
  const pbGuiStatus = document.getElementById('pb_gui_status');
  const btnPbStart = document.getElementById('btn_pb_gui_start');
  const btnPbStop  = document.getElementById('btn_pb_gui_stop');
  async function refreshPbGui(){
    try{
      const s = await jget('/api/visual/gui/status');
      if(pbGuiStatus) pbGuiStatus.textContent = s.running? 'ejecutándose':'detenida';
    }catch{ if(pbGuiStatus) pbGuiStatus.textContent = 'error'; }
  }
  if(btnPbStart){ btnPbStart.onclick = async ()=>{ try{ await jpost('/api/visual/gui/start',{}); toast('GUI iniciada'); }catch{ toast('No se pudo iniciar GUI'); } await refreshPbGui(); }; }
  if(btnPbStop){  btnPbStop.onclick  = async ()=>{ try{ await jpost('/api/visual/gui/stop',{});  toast('GUI detenida'); }catch{ toast('No se pudo detener GUI'); } await refreshPbGui(); }; }
  refreshPbGui();

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
    try{ await jpost('/api/control', payload); toast('PID aplicados'); }catch{ toast('Error aplicando PID'); }
  }; }

  const btnApplyPolicy=document.getElementById('btn_apply_policy'); if(btnApplyPolicy){ btnApplyPolicy.onclick = async ()=>{
    try{
      const pol = (document.getElementById('sel_policy')||{}).value||'stop_only';
      const sch = !!((document.getElementById('chk_scheduler')||{}).checked);
      await jpost('/api/command_policy', {policy: pol});
      await jpost('/api/scheduler', {enabled: sch});
      toast('Políticas aplicadas');
    }catch{ toast('Error políticas'); }
  }; }

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

  // ------------- Pollers (/status + /debug/serial) -------------
  let lastRxText = "";        // para watchdog RX
  let lastRxSeenTs = 0;
  let rxOK = false;
  let statusFetching = false;  // evita solapamiento de peticiones
  let isSerialOpen = false;    // estado serial para overlays
  let rxAgeMs = 999999;        // edad de RX para heurística de conexión
  let lastSerialOpenTs = 0;    // última vez visto abierto

  window._statusCache = null;
  async function pollStatus(){
    if(statusFetching) return; statusFetching = true;
    try{
      const s = await jget("/api/status");
      window._statusCache = s;
      if(!s) return;
      
      // Debug: mostrar datos recibidos
      console.log("[DEBUG] pollStatus recibió:", s);
      console.log("[DEBUG] x_mm:", s.x_mm, "a_deg:", s.a_deg);
      $("#t_x").textContent = fmt(s.x_mm||0);
      $("#t_a").textContent = fmt(s.a_deg||0);
      const zmm = Number(s.z_mm||0);
      const tz=document.getElementById('t_z'); if(tz){ tz.textContent = fmt(zmm||0); }
      
      // Actualizar reward en telemetría
      const rewardEl = document.getElementById('t_reward');
      if(rewardEl && s.reward !== undefined) {
        rewardEl.textContent = Number(s.reward).toFixed(3);
      }
      const rdz=document.getElementById('rd_z_mm'); if(rdz){ rdz.textContent = fmt(zmm||0); }
      const rdX=document.getElementById('rd_x_mm'); if(rdX){ rdX.textContent = fmt(s.x_mm||0); }
      const rdA=document.getElementById('rd_a_deg'); if(rdA){ rdA.textContent = fmt(s.a_deg||0); }
      updateSVG(s.x_mm, s.a_deg);
      $("#t_vol").textContent = fmt(s.volumen_ml||0);
      $("#t_flow").textContent = fmt((s.caudal_est_mls!=null?s.caudal_est_mls:s.flow_est)||0);
      const rdV=document.getElementById('rd_vol_ml'); if(rdV){ rdV.textContent = fmt(s.volumen_ml||0); }
      $("#t_limx").textContent = s.lim_x||0; $("#t_lima").textContent = s.lim_a||0;
      $("#t_homx").textContent = s.homing_x||0; $("#t_homa").textContent = s.homing_a||0;
      $("#t_port").textContent = s.serial_port || "—";
      $("#pill-serial").textContent = `Serial: ${s.serial_port} @ ${s.baudrate||''}`;
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
      // Modo en telemetría (desde RX/status)
      const modoEl = document.getElementById('t_modo_tx'); if(modoEl){ modoEl.textContent = String(s.modo!=null?s.modo:"—"); }

      // KPIs (calibración/flujo y PID)
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
      const rdEB=document.getElementById('rd_en_b'); if(rdEB){ rdEB.textContent = String((s.energies&&s.energies.bomba)||0); }

      // Progreso de volumen (si hay objetivo)
      try{
        const goal = Number((s.volumen_objetivo_ml!=null)?s.volumen_objetivo_ml:0);
        const cur = Number(s.volumen_ml||0);
        const bar = document.getElementById('g_vol_goal');
        if(bar){
          if(goal>0){
            const pct = clamp((cur/goal)*100,0,100);
            bar.style.width = pct+"%";
            // ETA si se puede estimar
            let eta='';
            const flow = Number((s.caudal_est_mls!=null?s.caudal_est_mls:s.flow_est)||0);
            if(flow>0 && cur<goal){
              const secs = Math.max(0, (goal-cur)/flow);
              const mm = Math.floor(secs/60), ss = Math.round(secs%60);
              eta = ` • ETA ${mm}m ${ss}s`;
            }
            bar.parentElement.title = `${cur.toFixed(1)} / ${goal.toFixed(1)} ml${eta}`;
          }else{
            bar.style.width = "0%"; bar.parentElement.title = "";
          }
        }
      }catch{}

      // Gauges SVG: porcentaje respecto a sus máximos
      const cLen = 2*Math.PI*48; // circunferencia del radio 48
      const setGauge = (id, value, maxVal, textId)=>{
        const fg = document.getElementById(id);
        const tx = document.getElementById(textId);
        if(!fg || !tx) return;
        const p = clamp(maxVal>0? (value/maxVal):0, 0, 1);
        fg.style.strokeDasharray = cLen+" "+999;
        fg.style.strokeDashoffset = String(cLen*(1-p));
        tx.textContent = fmt(value);
      };
      setGauge('sg_x_fg', Number(s.x_mm||0), 400, 'sg_x_txt');
      setGauge('sg_a_fg', Number(s.a_deg||0), 360, 'sg_a_txt');
      setGauge('sg_vol_fg', Number(s.volumen_ml||0), Math.max(Number(s.volumen_objetivo_ml||0), 1), 'sg_vol_txt');
      const zMaxGauge = Math.max((history.reduce((m,p)=>Math.max(m,p.z||0),0)) || 1, 1);
      const sgz=document.getElementById('sg_z_fg'); if(sgz){ setGauge('sg_z_fg', zmm, zMaxGauge, 'sg_z_txt'); }
      setGauge('sg_flow_fg', Number((s.caudal_est_mls!=null?s.caudal_est_mls:s.flow_est)||0), Math.max( (history.reduce((m,p)=>Math.max(m,p.flow||0),0)) || 1, 1), 'sg_flow_txt');

      // Actualizar mini panel Control
      const setT=(id,val)=>{ const el=document.getElementById(id); if(el){ el.textContent = fmt(val); } };
      setT('gx', s.x_mm||0); setT('ga', s.a_deg||0); setT('gvol', s.volumen_ml||0); setT('gflow', (s.caudal_est_mls!=null?s.caudal_est_mls:s.flow_est)||0);

      // Arena: rotar pista según ángulo y desplazar carro en la pista
      const ang = Math.max(0, Math.min(360, Number(s.a_deg||0)));
      const track = document.getElementById('arena_track'); if(track){ track.setAttribute('transform', `rotate(${ang} 160 160)`); }
      const ac = document.getElementById('arena_carro'); if(ac){ const x = 70 + Math.max(0, Math.min(400, Number(s.x_mm||0))) * (180/400); ac.setAttribute('x', String(x)); }
      const aa = document.getElementById('arena_aguja'); if(aa){ const rad=(ang-90)*Math.PI/180; const cx=160, cy=160, r=120; aa.setAttribute('x2', String(cx+Math.cos(rad)*r)); aa.setAttribute('y2', String(cy+Math.sin(rad)*r)); }

      // Gráfico
      if(!freeze){
        const now=Date.now()/1000;
        history.push({t:now, x:s.x_mm, a:s.a_deg, vol:s.volumen_ml, flow:(s.caudal_est_mls!=null?s.caudal_est_mls:s.flow_est), z:zmm});
        while(history.length && (now-history[0].t)>MAX_SEC) history.shift();
        drawChart();
      }
      refreshOverlay();
    }catch(e){ /* silencio */ }
    finally{ statusFetching = false; }
  }

  async function pollDebug(){
    try{
      const d = await jget("/debug/serial");
      const txt = JSON.stringify(d,null,2);
      $("#dbg_serial").textContent = txt;
      // también TX
      const tx = await jget("/debug/serial_tx");
      $("#dbg_serial").textContent += "\n--- TX ---\n"+JSON.stringify(tx,null,2);
      // edades para UI
      const rxAge = d.age_ms||0; const txAge = tx.age_ms||0;
      const rxEl = document.getElementById('rx_age_ms'); if(rxEl) rxEl.textContent = String(rxAge);
      const txEl = document.getElementById('tx_age_ms'); if(txEl) txEl.textContent = String(txAge);
      // mostrar modo (TX) si es posible
      try{
        let payload = tx && tx.last_tx;
        if(typeof payload === 'string'){
          let obj;
          try{ obj = JSON.parse(payload); }
          catch{ obj = JSON.parse(JSON.parse(payload)); }
          if(obj && typeof obj.modo !== 'undefined'){
            const el = document.getElementById('t_modo_tx'); if(el) el.textContent = String(obj.modo);
          }
        }else if(payload && typeof payload === 'object' && typeof payload.modo !== 'undefined'){
          const el = document.getElementById('t_modo_tx'); if(el) el.textContent = String(payload.modo);
        }
      }catch{}
      // color según antigüedad
      const age = d.age_ms||0; rxAgeMs = age;
      $("#pill-rx").className = age<1500? "pill ok": age<5000?"pill warn":"pill err";
      $("#pill-rx").textContent = age<1500? "RX OK": age<5000? "RX LENTO":"RX SIN DATOS";
      refreshOverlay();
    }catch{}
  }
  // Desactivar polling periódico de debug para no saturar el server
  // pollDebug solo bajo demanda (botón) o ante error
  pollStatus();
  setInterval(pollStatus, 150);

  // Botones depuración
  const bRef = document.getElementById('btn_refresh_dbg'); if(bRef){ bRef.onclick = ()=>{ pollDebug(); toast('Refrescado'); }; }
  const bCopy = document.getElementById('btn_copy_tx'); if(bCopy){ bCopy.onclick = async ()=>{
    try{
      const tx = await jget('/debug/serial_tx');
      const s = typeof tx.last_tx==='string'? tx.last_tx: JSON.stringify(tx.last_tx);
      await navigator.clipboard.writeText(s||''); toast('TX copiado');
    }catch{ toast('No se pudo copiar'); }
  }; }
  const bClr = document.getElementById('btn_clear_dbg'); if(bClr){ bClr.onclick = ()=>{ const el=document.getElementById('dbg_serial'); if(el) el.textContent=''; }; }

  // Cámara (simple)
  const camImg = document.getElementById('cam_img');
  const btnCamStart = document.getElementById('btn_cam_start'); if(btnCamStart){ btnCamStart.onclick = async ()=>{
    try{ await jpost('/api/camera/start',{}); toast('Cámara iniciada'); if(camImg){ camImg.src = '/static/camera_placeholder.jpg?'+Date.now(); } }
    catch{ toast('No se pudo iniciar cámara'); }
  }; }
  const btnCamShot = document.getElementById('btn_cam_snapshot'); if(btnCamShot){ btnCamShot.onclick = async ()=>{
    try{ await jpost('/api/camera/snapshot',{}); toast('Snapshot guardado'); }
    catch{ toast('Error snapshot'); }
  }; }
  // PyBullet visualizer
  const pbPanel = document.getElementById('pybullet_panel');
  const pbImg = document.getElementById('pybullet_view');
  const pbStatus = document.getElementById('pybullet_status');
  if(pbImg){
    const pbPlaceholder = pbImg.getAttribute('data-placeholder') || 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
    let lastUrl = null;
    let fetchingFrame = false;
    async function updatePybulletFrame(){
      if(fetchingFrame){ return; }
      fetchingFrame = true;
      try{
        const resp = await fetch(`/api/visual/frame?ts=${Date.now()}`, { cache: 'no-store' });
        if(!resp.ok){ throw new Error(`status ${resp.status}`); }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        if(lastUrl){ URL.revokeObjectURL(lastUrl); }
        lastUrl = url;
        pbImg.src = url;
        pbImg.style.opacity = '1';
        if(pbStatus){ pbStatus.textContent = `Actualizado ${new Date().toLocaleTimeString()}`; pbStatus.classList.remove('warn'); }
        if(pbPanel){ pbPanel.classList.remove('warn'); }
      }catch(e){
        if(pbStatus){ pbStatus.textContent = 'Visualizador no disponible'; pbStatus.classList.add('warn'); }
        pbImg.src = pbPlaceholder;
        pbImg.style.opacity = '0.2';
        if(pbPanel){ pbPanel.classList.add('warn'); }
      }finally{
        fetchingFrame = false;
      }
    }
    updatePybulletFrame();
    setInterval(updatePybulletFrame, 250);
    window.addEventListener('beforeunload', ()=>{ if(lastUrl){ URL.revokeObjectURL(lastUrl); } });
  }

  // ------------- Guard de ejecuciones (desactivar controles) -------------
  const execBanner = document.getElementById('exec_banner');
  const execInfo = document.getElementById('exec_info');
  const opSection = document.querySelector('section.tabview[data-tab="op"]');
  const opOverlay = document.getElementById('op_overlay');
  const opOverlayText = opOverlay? opOverlay.querySelector('.overlay-content') : null;
  const overlayMsg = document.getElementById('overlay_msg');
  const overlayReconnect = document.getElementById('btn_overlay_reconnect'); if(overlayReconnect){ overlayReconnect.onclick = async ()=>{
    try{
      const info = await jget('/api/serial/ports');
      const port=(document.getElementById('sel_port')||{}).value||info.current||'';
      const baud=Number((document.getElementById('sel_baud')||{}).value||info.baudrate||115200);
      await jpost('/api/serial/open',{port, baudrate: baud}); toast('Reconectado'); refreshPorts();
      const pill=document.getElementById('pill-serial'); if(pill){ pill.classList.add('ok'); setTimeout(()=>pill.classList.remove('ok'), 1200); }
    }catch{ toast('No se pudo reconectar'); }
  }; }
  let activeExecutionId = null;
  const gameSection = null;
  const gameOverlay = null;
  const gameOverlayMsg = null;

  async function pollExecutions(){
    try{
      if(!activeExecutionId){ refreshOverlay(); return; }
      const st = await jget(`/api/execution/${encodeURIComponent(activeExecutionId)}`);
      const pct = (st && st.progress && typeof st.progress.percentage==='number')? st.progress.percentage : 0;
      const typ = st && st.type || 'unknown';
      const tgt = st && st.target_id || '';
      if(execBanner) execBanner.style.display='block';
      if(execInfo) execInfo.textContent = `ID: ${activeExecutionId} • ${typ} '${tgt}' • ${pct}%`;
      const logEl = document.getElementById('exec_log');
      if(logEl && st && Array.isArray(st.log)){
        const lines = st.log.slice(-50); // últimas 50 entradas
        logEl.textContent = lines.join('\n');
        logEl.scrollTop = logEl.scrollHeight;
      }
      // Mostrar reward y logs del runner (consultar con menor cadencia)
      try{
        const now = Date.now();
        if(!window._lastProtoStatusAt || (now - window._lastProtoStatusAt) > 2000){
          window._lastProtoStatusAt = now;
          const ps = await jget('/api/protocols/status');
          if(ps){
            const rsum = (ps.reward_sum!=null)? Number(ps.reward_sum).toFixed(3) : '—';
            const rthr = (ps.reward_threshold!=null)? String(ps.reward_threshold) : '—';
            const rlast= (ps.last_reward!=null)? Number(ps.last_reward).toFixed(3) : '—';
            const info = document.getElementById('exec_info');
            if(info){
              const base = info.textContent||'';
              info.textContent = base.replace(/\s*\|\s*R:.*/, '') + ` | R:${rsum}/${rthr} (last ${rlast})`;
            }
            if(Array.isArray(ps.logs)){
              const l2 = ps.logs.slice(-80);
              const logEl2 = document.getElementById('exec_log');
              if(logEl2){
                const base = logEl2.textContent? (logEl2.textContent+'\n') : '';
                logEl2.textContent = base + l2.join('\n');
                logEl2.scrollTop = logEl2.scrollHeight;
              }
            }
          }
        }
      }catch{}
      // NO tocar elementos durante polling - solo actualizar datos
      // Cargar historial filtrado para debug rápido (x_mm,a_deg,volumen_ml)
      try{
        const cfg = collectSensorConfig();
        const wanted = Object.keys(cfg).filter(k=>cfg[k]);
        const qs = wanted.length? `sensors=${encodeURIComponent(wanted.join(','))}&limit=50` : 'limit=50';
        const hist = await jget(`/api/execution/${encodeURIComponent(activeExecutionId)}/history?${qs}`);
        const logEl = document.getElementById('dbg_serial');
        if(logEl){
          const rows = (hist.samples||[]).map(s=>{
            const ts = new Date((s.timestamp||0)*1000).toLocaleTimeString();
            const parts = Object.keys(s).filter(k=>k!=='timestamp').map(k=> `${k}:${s[k]}`);
            return `${ts}  ${parts.join('  ')}`;
          });
          logEl.textContent = rows.join('\n');
        }
      }catch{}
      // limpiar solo si terminó
      if(st && (st.status==='completed' || st.status==='error' || st.status==='timeout' || st.status==='stopped' || st.status==='done')){
        activeExecutionId = null;
        window._controlsDisabled = false; // Reset flag
        if(execBanner) execBanner.style.display='none';
        const logEl2=document.getElementById('exec_log'); if(logEl2){ logEl2.textContent=''; }
        if(opSection){ opSection.style.opacity='1'; }
        const b=document.getElementById('btn_proto_execute'); if(b){ b.textContent='▶ Ejecutar tarea'; b.classList.remove('warn'); }
      }
      // Fin del ciclo de polling
      refreshOverlay();
    }catch(e){ /* silencio */ }
  }
  let pollExecTimer = setInterval(pollExecutions, 800);
  pollExecutions();

  function refreshOverlay(){
    const setDisabledAll = (flag)=>{
      try{
        document.querySelectorAll('input,button,select,textarea').forEach(el=>{
          const id=el.id||'';
          if(flag){
            // Mantener activos elementos de telemetría (no interactivos) y debug
            const isTelemetry = id.startsWith('t_') || id.startsWith('rd_') || id.startsWith('sg_') || 
                               id.startsWith('k_') || id.startsWith('g_') || id.startsWith('pill-') ||
                               id==='dbg_serial' || id==='exec_log' || id==='exec_info' || id==='chart' ||
                               id==='robot_svg' || id==='carro' || id==='aguja' || id==='cam_img' ||
                               id==='debug_info' || id==='proto_debug' || id==='observations_info' || id==='observations_display' || // Mantener debug activo
                               id==='proto_sel' || id.startsWith('pp_') || // Mantener controles de protocolo activos
                               id==='btn_settings' || id==='robotSel' || id==='robotSel2' || // permitir cambiar robot y abrir Settings
                               id==='btn_pb_gui_start' || id==='btn_pb_gui_stop' || id==='pb_gui_status' ||
                               el.closest && (el.closest('.telemetry') || el.closest('#proto_debug') || el.closest('#observations_display'));
            if(!isTelemetry && id!=='btn_kill_exec' && id!=='tl_reload') el.disabled=true;
          }else{
            el.disabled=false;
          }
        });
      }catch{}
    };
    // Prioridad 1: ejecución activa
    if(activeExecutionId){
      if(overlayMsg) overlayMsg.textContent = 'Ejecución en curso — Controles deshabilitados. Usa "Detener ejecución".';
      if(overlayReconnect) overlayReconnect.style.display='none';
      // Mostrar overlay para indicar ejecución activa
      if(opOverlay) opOverlay.style.display = 'flex';
      if(opSection){ opSection.style.opacity='0.7'; } // Ligeramente oscurecido para indicar desactivado
      // Asegurar que el debug permanezca visible durante la ejecución
      const debugEl = document.getElementById('proto_debug');
      const obsEl = document.getElementById('observations_display');
      if(debugEl) debugEl.style.display = 'block';
      if(obsEl) obsEl.style.display = 'block';
      // Deshabilitar controles una sola vez (no en cada polling)
      if(!window._controlsDisabled){
        setDisabledAll(true);
        window._controlsDisabled = true;
      }
      return;
    }
    // Prioridad 2: conexión (RX reciente o serial_open true)
    const connected = isSerialOpen || (rxAgeMs < 5000);
    if(connected){
      if(opOverlay) opOverlay.style.display = 'none';
      if(opSection){ opSection.style.opacity='1'; }
      setDisabledAll(false);
      window._controlsDisabled = false; // Reset flag
      // botón ejecutar habilitado
      const b=document.getElementById('btn_proto_execute'); if(b){ b.disabled=false; }
    }else{
      if(overlayMsg) overlayMsg.textContent = 'Serial desconectado. Abra Settings para conectar.';
      if(overlayReconnect) overlayReconnect.style.display='inline-block';
      if(opOverlay) opOverlay.style.display = 'flex';
      if(opSection){ opSection.style.opacity='0.5'; }
      setDisabledAll(true);
      const b=document.getElementById('btn_proto_execute'); if(b){ b.disabled=true; }
      // Forzar que botones clave permanezcan habilitados aunque el overlay esté activo
      try{
        ['btn_settings','robotSel','robotSel2','btn_pb_gui_start','btn_pb_gui_stop','pb_gui_status']
          .forEach(k=>{ const el=document.getElementById(k); if(el){ el.disabled=false; } });
      }catch{}
    }
  }

  const btnKill = document.getElementById('btn_kill_exec');
  if(btnKill){ btnKill.onclick = async ()=>{ if(!activeExecutionId) return; await jpost(`/api/execution/${encodeURIComponent(activeExecutionId)}/stop`,{}); toast('Parando ejecución...'); }; }

  // Reproductor simple (ejecuta protocolo con params {x_mm,a_deg,volumen_ml})
  const btnPlPlay = document.getElementById('btn_pl_play'); if(btnPlPlay){ btnPlPlay.onclick = async ()=>{
    const nameEl=(document.getElementById('pl_prot')||{});
    const name = (nameEl&&nameEl.value)||'';
    const x = Number((document.getElementById('pl_x')||{}).value||0);
    const a = Number((document.getElementById('pl_a')||{}).value||0);
    const vol = Number((document.getElementById('pl_vol')||{}).value||0);
    const toEl=document.getElementById('pl_timeout'); const timeoutSeconds = toEl? Number(toEl.value||25): undefined;
    if(!name){ toast('Nombre de protocolo vacío'); return; }
    try{
      // validar existencia
      try{ await jget(`/api/protocols/${encodeURIComponent(name)}`); if(nameEl){ nameEl.classList.remove('err'); nameEl.classList.add('ok'); } }
      catch{ if(nameEl){ nameEl.classList.remove('ok'); nameEl.classList.add('err'); } toast('Protocolo inexistente'); return; }
      const body={ type:'protocol', id:name, params:{ x_mm:x, a_deg:a, volumen_ml:vol } };
      if(!isNaN(timeoutSeconds)) body.timeout_seconds = timeoutSeconds;
      const r = await jpost('/api/execute', body);
      activeExecutionId = r.execution_id || null; if(execInfo) execInfo.textContent = `ID: ${activeExecutionId}`; if(execBanner) execBanner.style.display='block';
      toast(`Ejecutando protocolo (${r.execution_id||''})`);
    }catch{ toast('Error ejecutando protocolo'); }
  }; }
  const btnPlStop = document.getElementById('btn_pl_stop'); if(btnPlStop){ btnPlStop.onclick = async ()=>{
    if(!activeExecutionId){ toast('Sin ejecución activa'); return; }
    try{ await jpost(`/api/execution/${encodeURIComponent(activeExecutionId)}/stop`,{}); toast('Deteniendo'); }catch{ toast('Error deteniendo'); }
  }; }

  // Plantillas del reproductor
  const tplSel=document.getElementById('pl_tpl'); if(tplSel){ tplSel.onchange = ()=>{
    const v = tplSel.value||'';
    const set=(id,val)=>{ const el=document.getElementById(id); if(el) el.value=String(val); };
    if(v==='regar_pos'){
      set('pl_prot','regar_pos'); set('pl_x',100); set('pl_a',30); set('pl_vol',50);
    }else if(v==='ir_pos'){
      set('pl_prot','ir_pos'); set('pl_x',100); set('pl_a',30); set('pl_vol',0);
    }else if(v==='regar_rapido'){
      set('pl_prot','regar_rapido'); set('pl_x',80); set('pl_a',20); set('pl_vol',30);
    }
  }; }

  // Guardar plantilla personalizada en /api/settings (key: player_favorites)
  const btnSaveTpl=document.getElementById('btn_pl_saveTpl'); if(btnSaveTpl){ btnSaveTpl.onclick = async ()=>{
    const name = prompt('Nombre de la plantilla:'); if(!name) return;
    const prot = (document.getElementById('pl_prot')||{}).value||'';
    const x = Number((document.getElementById('pl_x')||{}).value||0);
    const a = Number((document.getElementById('pl_a')||{}).value||0);
    const vol = Number((document.getElementById('pl_vol')||{}).value||0);
    try{
      const cur = await jget('/api/settings');
      const fav = Array.isArray(cur.player_favorites)? cur.player_favorites: [];
      fav.push({ name, prot, x, a, vol });
      await jpost('/api/settings', { player_favorites: fav });
      // añadir al select
      const sel=document.getElementById('pl_tpl'); if(sel){ const opt=document.createElement('option'); opt.value=prot; opt.textContent=name; sel.appendChild(opt); sel.value=opt.value; sel.onchange&&sel.onchange(); }
      toast('Plantilla guardada');
    }catch{ toast('Error guardando plantilla'); }
  }; }

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
    await jpost('/api/control', body);
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
  const applyEnergiesNow = async ()=>{
    const vx = Number($("#en_x") && $("#en_x").value || 0);
    const va = Number($("#en_a") && $("#en_a").value || 0);
    const vb = Number($("#en_b") && $("#en_b").value || 0);
    if(chkX && Math.abs(vx) > 0){ chkX.checked = true; }
    if(chkA && Math.abs(va) > 0){ chkA.checked = true; }
    await sendControl({
      modo: recomputeModoBits(),
      energy_x: vx,
      energy_a: va,
      energy_bomba: vb,
    });
  };
  const debouncedEnergies = debounce(applyEnergiesNow, 120);
  const enX = document.getElementById('en_x'); if(enX){ enX.oninput = ()=>{ $("#en_x_o").textContent = enX.value; debouncedEnergies(); }; }
  const enA = document.getElementById('en_a'); if(enA){ enA.oninput = ()=>{ $("#en_a_o").textContent = enA.value; debouncedEnergies(); }; }
  const enB = document.getElementById('en_b'); if(enB){ enB.oninput = ()=>{ $("#en_b_o").textContent = enB.value; debouncedEnergies(); }; }

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
    await jpost("/api/control", {calibration:{steps_mm:Number($("#steps_mm").value||0), steps_deg:Number($("#steps_deg").value||0)}});
    toast("Calibración aplicada");
  }; }
  const btnApplyFlujo = document.getElementById('btn_apply_flujo');
  if(btnApplyFlujo){ btnApplyFlujo.onclick = async ()=>{
    await jpost("/api/control", {flow:{
      usar_sensor_flujo: $("#chk_sensor_flujo").checked?1:0,
      caudal_bomba_mls: Number($("#caudal").value||0)
    } });
    toast("Ajustes de flujo aplicados");
  }; }

  // ------------- Protocolos -------------
  // meta + inputs dinámicos
  let protoMeta = null;
  let protoPrefs = { current: null, params: {}, sensor_config: {} };
  async function loadProtoMeta(){
    try{
      const r = await jget('/api/protocols');
      protoMeta = r && r.meta || {};
      const arr = (r && r.protocols) || [];
      const sel = document.getElementById('proto_sel'); if(!sel) return;
      sel.innerHTML='';
      arr.forEach(n=>{ const o=document.createElement('option'); o.value=n; o.textContent=n; sel.appendChild(o); });
      // cargar preferencias guardadas
      try{
        const s = await jget('/api/settings');
        if(s && s.proto_preferences){ protoPrefs = Object.assign({current:null, params:{}, sensor_config:{}}, s.proto_preferences); }
      }catch{}
      const initial = (protoPrefs && protoPrefs.current && arr.includes(protoPrefs.current))? protoPrefs.current : (arr[0]||'');
      if(initial){ sel.value = initial; buildProtoInputs(initial); applyParamsToInputs(initial); await loadProtoCode(initial); applySensorChecksFromPrefs(); applyRewardDefaults(initial); }
      // Restaurar reward prefs
      try{
        const rwd = (protoPrefs && protoPrefs.reward) || {};
        const setv = (id, v)=>{ const el=document.getElementById(id); if(el && typeof v!=='undefined' && v!==null){ el.value = String(v); }};
        setv('pp_max_dur', rwd.max_duration_seconds);
        setv('pp_reward_key', rwd.reward_key);
        setv('pp_reward_thr', rwd.reward_threshold);
        setv('pp_reward_expr', rwd.reward_expr);
        const rc=document.getElementById('pp_reward_cum'); if(rc && typeof rwd.reward_cumulative!=='undefined'){ rc.checked = !!rwd.reward_cumulative; }
      }catch{}
    }catch{}
  }

  function buildProtoInputs(name){
    const box = document.getElementById('proto_params'); if(!box) return;
    box.innerHTML = '';
    const spec = protoMeta && protoMeta[name];
    const params = spec && spec.params || {};
    const grid=document.createElement('div'); grid.className='row'; grid.style.flexWrap='wrap'; grid.style.gap='8px';
    Object.keys(params).forEach(k=>{
      const p=params[k]||{}; const f=document.createElement('div'); f.className='field';
      const label=document.createElement('label'); label.textContent=p.label||k; f.appendChild(label);
      const inp=document.createElement('input'); inp.type=p.type||'number'; if(p.min!=null) inp.min=String(p.min); if(p.max!=null) inp.max=String(p.max); if(p.step!=null) inp.step=String(p.step);
      inp.value = (p.default!=null? String(p.default): ''); inp.id = `pp_${k}`;
      inp.oninput = debounce(()=>{ tryLiveUpdate(name); saveProtoPrefsDebounced(); }, 150);
      f.appendChild(inp); grid.appendChild(f);
    });
    box.appendChild(grid);
  }

  function applyParamsToInputs(name){
    try{
      const saved = (protoPrefs && protoPrefs.params && protoPrefs.params[name]) || {};
      Object.keys(saved).forEach(k=>{ const el=document.getElementById(`pp_${k}`); if(el){ el.value = String(saved[k]); }});
    }catch{}
  }

  async function tryLiveUpdate(name){
    // si hay ejecución activa, enviar vars al vuelo
    if(activeExecutionId){
      const params = collectParamsFromUI();
      try{ await jpost(`/api/protocols/${encodeURIComponent(name)}/vars`, {params}); }catch{}
    }
  }

  function collectParamsFromUI(){
    const params={};
    const box=document.getElementById('proto_params'); if(!box) return params;
    Array.from(box.querySelectorAll('input[id^="pp_"]')).forEach(inp=>{
      const key=inp.id.replace('pp_',''); const v=Number(inp.value);
      params[key] = isNaN(v)? inp.value : v;
    });
    return params;
  }

  function collectSensorConfig(){
    const cfg={};
    const cont=document.getElementById('sensor_checks'); if(!cont) return cfg;
    Array.from(cont.querySelectorAll('input.sensor_chk')).forEach(ch=>{ cfg[ch.value] = !!ch.checked; });
    return cfg;
  }

  function applySensorChecksFromPrefs(){
    try{
      const cont=document.getElementById('sensor_checks'); if(!cont) return;
      const cfg = (protoPrefs && protoPrefs.sensor_config) || {};
      Array.from(cont.querySelectorAll('input.sensor_chk')).forEach(ch=>{ if(typeof cfg[ch.value] !== 'undefined'){ ch.checked = !!cfg[ch.value]; }});
    }catch{}
  }

  const saveProtoPrefsDebounced = debounce(async ()=>{
    try{
      const name = (document.getElementById('proto_sel')||{}).value||'';
      const params = collectParamsFromUI();
      const sensor_config = collectSensorConfig();
      const reward = {
        max_duration_seconds: Number((document.getElementById('pp_max_dur')||{}).value||0) || undefined,
        reward_key: (document.getElementById('pp_reward_key')||{}).value||undefined,
        reward_threshold: Number((document.getElementById('pp_reward_thr')||{}).value||0) || undefined,
        reward_expr: (document.getElementById('pp_reward_expr')||{}).value||undefined,
        reward_cumulative: !!((document.getElementById('pp_reward_cum')||{}).checked)
      };
      const payload = { proto_preferences: { current: name, params: Object.assign({}, protoPrefs.params, { [name]: params }), sensor_config, reward } };
      await jpost('/api/settings', payload);
      protoPrefs = payload.proto_preferences;
    }catch{}
  }, 250);

  async function loadProtoCode(name){
    try{
      const r = await jget(`/api/protocols/${encodeURIComponent(name)}`);
      const cont = document.getElementById('proto_params'); if(!cont) return;
      let pre = cont.querySelector('pre'); if(!pre){ pre=document.createElement('pre'); pre.className='log small'; pre.style.maxHeight='180px'; pre.style.overflow='auto'; pre.style.marginTop='8px'; cont.appendChild(pre); }
      pre.textContent = r && r.code || '';
    }catch{}
  }

  function applyRewardDefaults(name){
    const rk=document.getElementById('pp_reward_key');
    const rthr=document.getElementById('pp_reward_thr');
    const rex=document.getElementById('pp_reward_expr');
    if(!rk||!rthr) return;
    const spec = (protoMeta && protoMeta[name]) || {};
    const rwd = (spec && spec.reward && spec.reward.defaults) || {};
    if(typeof rwd.key !== 'undefined') rk.value = String(rwd.key||'');
    if(typeof rwd.threshold !== 'undefined') rthr.value = rwd.threshold>0? String(rwd.threshold): '';
    if(rex && typeof rwd.expr !== 'undefined') rex.value = String(rwd.expr||'');
    const rc=document.getElementById('pp_reward_cum'); if(rc && typeof rwd.cumulative!=='undefined') rc.checked = !!rwd.cumulative;
    // opciones sugeridas (simple placeholder en title)
    const sugg = (spec && spec.reward && spec.reward.suggested_keys) || [];
    rk.placeholder = sugg.join(', ');
  }

  const protoSel=document.getElementById('proto_sel'); if(protoSel){ protoSel.onchange = async ()=>{ const v=protoSel.value||''; console.log('[UI] protocolo seleccionado:', v); buildProtoInputs(v); applyParamsToInputs(v); await loadProtoCode(v); applyRewardDefaults(v); saveProtoPrefsDebounced(); }; }
  // guardar cuando se cambien checks de sensores
  (function bindSensorChecks(){ const cont=document.getElementById('sensor_checks'); if(!cont) return; Array.from(cont.querySelectorAll('input.sensor_chk')).forEach(ch=>{ ch.onchange = saveProtoPrefsDebounced; }); })();
  loadProtoMeta();

  // ejecutar/stop desde reproductor dinámico
  const btnProtoExec=document.getElementById('btn_proto_execute'); if(btnProtoExec){ btnProtoExec.onclick = async ()=>{
    // Usar la nueva lógica simplificada
    if (typeof executeProtocolSimple === 'function') {
      await executeProtocolSimple();
      return;
    }
    // Fallback a la lógica original si no está disponible
    // Bloqueo si no hay serial
    if(!isSerialOpen && !(rxAgeMs<5000)) { toast('Serial desconectado. Conecta en Settings.'); return; }
    if(activeExecutionId){
      try{ 
        await jpost(`/api/protocols/stop`,{}); 
        toast('Deteniendo...'); 
        activeExecutionId = null; 
        btnProtoExec.textContent = '▶ Ejecutar'; 
        btnProtoExec.classList.remove('warn'); 
        const btnStop = document.getElementById('btn_proto_stop');
        if(btnStop) btnStop.style.display = 'none';
        // NO ocultar el debug de protocolos - siempre visible en la pestaña
        const debugInfo = document.getElementById('debug_info');
        if(debugInfo) debugInfo.innerHTML = '<div class="muted">Protocolo detenido</div>';
        const obsInfo = document.getElementById('observations_info');
        if(obsInfo) obsInfo.innerHTML = '<div class="muted">Esperando observaciones...</div>';
      }catch{ toast('Error deteniendo'); }
      return;
    }
    const name = (document.getElementById('proto_sel')||{}).value||'ir_posicion';
    const params = collectParamsFromUI();
    
    try{
      const startedAt = Date.now();
      console.log('[UI] POST /api/protocols/' + name + '/execute', params);
      const resp = await fetch(`/api/protocols/${encodeURIComponent(name)}/execute`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(params)});
      let r={}; try{ r = await resp.json(); }catch{ r={}; }
      if(!resp.ok){ console.error('[UI] execute error', r); toast(r.error||'Error ejecutando'); return; }
      activeExecutionId = r.execution_id || 'protocolo_activo';
      // No usar execution_id para protocolos directos
      if (activeExecutionId === 'protocolo_activo') {
        activeExecutionId = 'protocolo_activo';
      }
      const el=document.getElementById('proto_active'); if(el){ el.textContent = name; }
      toast(`Ejecutando ${name} (protocolo activo)`);
      
      // Mostrar debug del protocolo (siempre visible en la pestaña de protocolos)
      const debugEl = document.getElementById('proto_debug');
      const debugInfo = document.getElementById('debug_info');
      if(debugEl) debugEl.style.display = 'block';
      if(debugInfo) debugInfo.innerHTML = '<div class="muted">Iniciando protocolo...</div>';
      
      // Mostrar observaciones en tiempo real
      const obsEl = document.getElementById('observations_display');
      const obsInfo = document.getElementById('observations_info');
      if(obsEl) obsEl.style.display = 'block';
      if(obsInfo) obsInfo.innerHTML = '<div class="muted">Esperando observaciones...</div>';
      
      // Mostrar tiempo de ejecución en vivo - VERSIÓN CORREGIDA
      const info = document.getElementById('exec_info');
      let updateCount = 0;
      window.protoUpdateInterval = setInterval(async ()=>{
        updateCount++;
        
        // CORRECCIÓN 1: Verificar si el protocolo sigue activo
        if(!activeExecutionId){ 
          clearInterval(window.protoUpdateInterval); 
          window.protoUpdateInterval = null;
          return; 
        }
        
        const secs = Math.floor((Date.now()-startedAt)/1000);
        if(info){ info.textContent = `ID: ${activeExecutionId} • ${name} • ${secs}s`; }
        
        // CORRECCIÓN 2: Usar /api/protocols/status para obtener estado del protocolo
        try {
          const protocolStatusResponse = await fetch('/api/protocols/status');
          const protocolStatus = await protocolStatusResponse.json();
          
          // CORRECCIÓN 3: También obtener estado del robot para observaciones
          // Usar endpoint que fuerza actualización completa de datos
          const forceUpdateResponse = await fetch('/api/debug/force_update');
          const forceUpdate = await forceUpdateResponse.json();
          
          // DEBUG: Conectar y probar comunicación serial
          const serialConnectResponse = await fetch('/api/debug/serial_connect');
          const serialConnect = await serialConnectResponse.json();
          
          const serialTestResponse = await fetch('/api/debug/serial_test');
          const serialTest = await serialTestResponse.json();
          
          let robotStatus = {};
          let rawObs = {};
          
          if (forceUpdate.success) {
            robotStatus = forceUpdate.status;
            rawObs = {
              raw_obs: forceUpdate.raw_obs,
              length: forceUpdate.raw_obs.length,
              x_mm: forceUpdate.raw_obs[0],
              a_deg: forceUpdate.raw_obs[1],
              z_mm: forceUpdate.raw_obs[21]
            };
          } else {
            // Fallback a endpoint normal si falla
            const robotStatusResponse = await fetch('/api/status/fresh');
            robotStatus = await robotStatusResponse.json();
            
            const rawObsResponse = await fetch('/api/debug/raw_obs');
            rawObs = await rawObsResponse.json();
          }
          
          // CORRECCIÓN 4: Actualizar debug con datos correctos
          if(debugInfo){
            const currentTime = new Date().toLocaleTimeString();
            const isRunning = protocolStatus.status === 'running' && !protocolStatus.done;
            const statusIcon = isRunning ? '🔄' : '✅';
            const statusText = isRunning ? 'Ejecutando...' : 'Completado';
            
            let debugText = `[${currentTime}] 🚀 PROTOCOLO: ${name}\n`;
            debugText += `⏱️  Tiempo: ${secs}s | Estado: ${statusIcon} ${statusText}\n`;
            
            if (protocolStatus.last_log) {
              debugText += `📝 Último log: ${protocolStatus.last_log}\n`;
            }
            
            debugText += `\n📍 Estado del Robot:\n`;
            debugText += `   X: ${robotStatus.x_mm || 0}mm (target: ${params.x_mm || 0}mm)\n`;
            debugText += `   A: ${robotStatus.a_deg || 0}° (target: ${params.a_deg || 0}°)\n`;
            debugText += `   Z: ${robotStatus.z_mm || 0}mm\n`;
            debugText += `   Volumen: ${robotStatus.volumen_ml || 0}ml\n`;
            debugText += `   Modo: ${robotStatus.modo || 'N/A'}\n`;
            debugText += `   Serial: ${robotStatus.serial_open ? 'Conectado' : 'Desconectado'}\n`;
            
            if (robotStatus.rx_age_ms !== undefined) {
              debugText += `   Edad RX: ${robotStatus.rx_age_ms} ms\n`;
            }
            
            // DEBUG: Mostrar datos raw y diagnóstico
            if (rawObs && rawObs.raw_obs) {
              debugText += `\n🔍 DEBUG - Datos Raw:\n`;
              debugText += `   Raw X: ${rawObs.x_mm || 'N/A'}\n`;
              debugText += `   Raw A: ${rawObs.a_deg || 'N/A'}\n`;
              debugText += `   Raw Z: ${rawObs.z_mm || 'N/A'}\n`;
              debugText += `   Array length: ${rawObs.length || 0}\n`;
              if (rawObs.raw_obs && rawObs.raw_obs.length > 0) {
                debugText += `   Primeros 5 valores: [${rawObs.raw_obs.slice(0, 5).map(v => v.toFixed(2)).join(', ')}]\n`;
              }
            } else {
              debugText += `\n🔍 DEBUG - Sin datos raw disponibles\n`;
            }
            
            // DEBUG: Mostrar información de diagnóstico
            if (forceUpdate && forceUpdate.debug_info) {
              const diag = forceUpdate.debug_info;
              debugText += `\n🔧 DIAGNÓSTICO DE COMUNICACIÓN:\n`;
              debugText += `   Serial disponible: ${diag.serial_available ? 'Sí' : 'No'}\n`;
              debugText += `   Serial abierto: ${diag.serial_open ? 'Sí' : 'No'}\n`;
              debugText += `   Puerto: ${diag.serial_port || 'N/A'}\n`;
              debugText += `   Baudrate: ${diag.baudrate || 'N/A'}\n`;
              debugText += `   Tamaño cola: ${diag.queue_size || 0}\n`;
              debugText += `   Última RX: ${diag.last_rx_ts ? new Date(diag.last_rx_ts * 1000).toLocaleTimeString() : 'N/A'}\n`;
              debugText += `   Texto RX: ${diag.last_rx_text || 'N/A'}\n`;
              debugText += `   Obs array: ${diag.obs_arr ? 'Disponible' : 'No disponible'}\n`;
              debugText += `   Longitud obs: ${diag.obs_length || 0}\n`;
            }
            
            // DEBUG: Mostrar conexión serial
            if (serialConnect) {
              debugText += `\n🔌 CONEXIÓN SERIAL:\n`;
              debugText += `   Éxito: ${serialConnect.success ? 'Sí' : 'No'}\n`;
              debugText += `   Mensaje: ${serialConnect.message || 'N/A'}\n`;
              debugText += `   Puerto: ${serialConnect.port || 'N/A'}\n`;
              debugText += `   Baudrate: ${serialConnect.baudrate || 'N/A'}\n`;
              if (serialConnect.error) {
                debugText += `   Error: ${serialConnect.error}\n`;
              }
            }
            
            // DEBUG: Mostrar prueba de comunicación serial
            if (serialTest) {
              debugText += `\n📡 PRUEBA DE COMUNICACIÓN SERIAL:\n`;
              debugText += `   Comando enviado: ${serialTest.command_sent || 'N/A'}\n`;
              debugText += `   Respuesta: ${serialTest.response || 'N/A'}\n`;
              debugText += `   Longitud respuesta: ${serialTest.response_length || 0}\n`;
              debugText += `   Timeout alcanzado: ${serialTest.timeout_reached ? 'Sí' : 'No'}\n`;
              debugText += `   Éxito: ${serialTest.success ? 'Sí' : 'No'}\n`;
              if (serialTest.error) {
                debugText += `   Error: ${serialTest.error}\n`;
              }
            }
            
            debugText += `\n📋 Parámetros: ${JSON.stringify(params, null, 2)}`;
            debugInfo.innerHTML = `<pre>${debugText}</pre>`;
          }
          
          // CORRECCIÓN 5: Actualizar observaciones en tiempo real
          const obsInfo = document.getElementById('observations_info');
          if(obsInfo) {
            const currentTime = new Date().toLocaleTimeString();
            let obsText = `[${currentTime}] 📊 OBSERVACIONES: ${name}\n\n`;
            obsText += `Posición X: ${(robotStatus.x_mm || 0).toFixed(2)} mm\n`;
            obsText += `Posición A: ${(robotStatus.a_deg || 0).toFixed(2)}°\n`;
            obsText += `Posición Z: ${(robotStatus.z_mm || 0).toFixed(2)} mm\n`;
            obsText += `Volumen: ${(robotStatus.volumen_ml || 0).toFixed(2)} ml\n`;
            obsText += `Modo: ${robotStatus.modo || 'N/A'}\n`;
            obsText += `Serial: ${robotStatus.serial_open ? 'Conectado' : 'Desconectado'}\n`;
            
            if (robotStatus.rx_age_ms !== undefined) {
              obsText += `Edad RX: ${robotStatus.rx_age_ms} ms\n`;
            }
            
            obsText += `\n🔄 Actualizando cada 1s...`;
            obsInfo.innerHTML = `<pre>${obsText}</pre>`;
          }
          
          // CORRECCIÓN 6: Verificar si el protocolo terminó
          if (protocolStatus.done || protocolStatus.status === 'stopped') {
            console.log('[UI] Protocolo terminado, limpiando intervalo');
            clearInterval(window.protoUpdateInterval);
            window.protoUpdateInterval = null;
            
            // Actualizar UI para mostrar que terminó
            if(debugInfo) {
              const finalTime = new Date().toLocaleTimeString();
              const finalSecs = Math.floor((Date.now() - startedAt) / 1000);
              debugInfo.innerHTML = `<pre>[${finalTime}] ✅ PROTOCOLO COMPLETADO: ${name}\n⏱️  Tiempo total: ${finalSecs}s\n📊 Estado final: ${JSON.stringify(protocolStatus, null, 2)}</pre>`;
            }
            
            // Restaurar botones
            const executeBtn = document.getElementById('btn_proto_execute');
            const stopBtn = document.getElementById('btn_proto_stop');
            if(executeBtn) executeBtn.style.display = 'inline-block';
            if(stopBtn) stopBtn.style.display = 'none';
            
            activeExecutionId = null;
            window.activeExecutionId = null;
          }
          
        } catch(error) {
          console.error('[UI] Error obteniendo estado:', error);
          // Actualizar debug con error
          if(debugInfo) {
            const currentTime = new Date().toLocaleTimeString();
            let debugText = `[${currentTime}] 🚀 PROTOCOLO: ${name}\n`;
            debugText += `⏱️  Tiempo: ${secs}s | Estado: 🔄 Ejecutando...\n`;
            debugText += `❌ Error obteniendo estado: ${error.message}\n`;
            debugText += `📋 Parámetros: ${JSON.stringify(params, null, 2)}`;
            debugInfo.innerHTML = `<pre>${debugText}</pre>`;
          }
        }
      }, 1000); // CORRECCIÓN 7: Cambiar a 1 segundo para evitar spam
      // Mostrar botón de detener separado
      const btnStop = document.getElementById('btn_proto_stop');
      if(btnStop) btnStop.style.display = 'inline-block';
      
      // Mostrar debug unificado
      const debugInfoInit = document.getElementById('debug_info');
      if(debugInfoInit) {
        debugInfoInit.innerHTML = '<div class="muted">Iniciando protocolo...</div>';
      }
    }catch{ toast('Error ejecutando'); }
  }; }
  const btnProtoStop=document.getElementById('btn_proto_stop'); 
  if(btnProtoStop){ 
    btnProtoStop.onclick = async ()=>{ 
      // Usar la nueva lógica simplificada
      if (typeof stopProtocol === 'function') {
        await stopProtocol();
        return;
      }
      // Fallback a la lógica original si no está disponible
      try{ 
        await jpost(`/api/protocols/stop`,{}); 
        toast('Protocolo detenido'); 
        
        // CORRECCIÓN 8: Limpiar intervalo ANTES de limpiar el estado
        if(window.protoUpdateInterval) {
          clearInterval(window.protoUpdateInterval);
          window.protoUpdateInterval = null;
        }
        
        // Limpiar estado de ejecución
        activeExecutionId = null; 
        window.activeExecutionId = null;
        
        // Restaurar botón de ejecutar
        const executeBtn = document.getElementById('btn_proto_execute');
        if(executeBtn) {
          executeBtn.style.display = 'inline-block';
          executeBtn.disabled = false;
        }
        
        // Ocultar botón de detener
        const stopBtn = document.getElementById('btn_proto_stop');
        if(stopBtn) stopBtn.style.display = 'none';
        
        // Limpiar debug
        const debugInfo = document.getElementById('debug_info'); 
        if(debugInfo) debugInfo.innerHTML = '<div class="muted">🛑 Protocolo detenido por el usuario</div>';
        
        // Limpiar observaciones
        const obsInfo = document.getElementById('observations_info');
        if(obsInfo) obsInfo.innerHTML = '<div class="muted">Esperando observaciones...</div>';
        
      }catch{ toast('Error deteniendo protocolo'); } 
    }; 
  }

  const bNewProt=document.getElementById('btn_new_prot'); if(bNewProt){ bNewProt.onclick = ()=>{
    const ed=document.getElementById('prot_editor'); if(ed){ ed.style.display='block'; }
    const n=document.getElementById('prot_name'); if(n){ n.value='nuevo_protocolo'; }
    const c=document.getElementById('prot_code'); if(c){ c.value = (
`#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protocolo de ejemplo (Gym-like)
==============================

Ejemplo de protocolo usando la nueva estructura compatible con Gym.
"""

import numpy as np
from protocolos import ProtocoloBase

class MiProtocolo(ProtocoloBase):
    """
    Protocolo de ejemplo que hereda de ProtocoloBase.
    
    Parámetros:
        x_mm: Posición objetivo en X (mm)
        a_deg: Ángulo objetivo en A (grados)
        threshold: Umbral de llegada (mm/grados)
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target_x = self.params.get('x_mm', 100.0)
        self.target_a = self.params.get('a_deg', 45.0)
        self.threshold = float(self.params.get('threshold', 1.0))
        self.current_x = 0.0
        self.current_a = 0.0
        
    def reset(self):
        """Reset del protocolo"""
        super().reset()
        self.current_x = 0.0
        self.current_a = 0.0
        return self._get_initial_observation()
    
    def step(self, action=None):
        """Un paso del protocolo"""
        super().step(action)
        
        # Obtener observación actual
        obs = self._get_observation()
        self.current_x = float(obs[0]) if len(obs) > 0 else 0.0
        self.current_a = float(obs[1]) if len(obs) > 1 else 0.0
        
        # Calcular distancias al objetivo
        dx = abs(self.current_x - self.target_x)
        da = abs(self.current_a - self.target_a)
        
        # Verificar si llegamos al objetivo
        if dx <= self.threshold and da <= self.threshold:
            self.done = True
            patch = {"codigoModo": 0}  # Parar motores
            log = f"Objetivo alcanzado: X={self.current_x:.1f}mm, A={self.current_a:.1f}°"
        else:
            # Mover hacia el objetivo
            patch = {
                "codigoModo": 0,  # Modo automático
                "setpointX": float(self.target_x),
                "setpointX_mm": float(self.target_x),
                "setpointA": float(self.target_a),
                "setpointA_deg": float(self.target_a)
            }
            log = f"Movimiento: X={self.current_x:.1f}→{self.target_x}mm, A={self.current_a:.1f}→{self.target_a}°"
        
        # Calcular recompensa
        reward = self._calculate_reward()
        
        # Información adicional
        info = {
            "patch": patch,
            "sleep_ms": 100,
            "log": log,
            "distance_x": dx,
            "distance_a": da
        }
        
        return obs, reward, self.done, info
    
    def _calculate_reward(self):
        """Calcula recompensa basada en la distancia al objetivo"""
        dx = abs(self.current_x - self.target_x)
        da = abs(self.current_a - self.target_a)
        return max(0.0, 100.0 - (dx + da))
    
    def _get_observation(self):
        """Obtener observación actual del entorno"""
        return np.array([
            self.current_x,  # x_mm
            self.current_a,  # a_deg
            0.0,  # z_mm
            0.0,  # volumen_ml
            0.0,  # caudal_est_mls
            0,    # modo
        ], dtype=np.float32)
    
    def render(self, mode='human'):
        """Renderizado opcional del protocolo"""
        if mode == 'human':
            print(f"MiProtocolo: X={self.current_x:.1f}→{self.target_x}mm, A={self.current_a:.1f}→{self.target_a}°")
    
    def close(self):
        """Limpieza al finalizar"""
        super().close()
        print("MiProtocolo: Protocolo finalizado")


# Compatibilidad con estructura antigua (opcional)
def custom_action(obs, ctx):
    """Wrapper para compatibilidad con estructura antigua"""
    protocolo = MiProtocolo(**ctx.get('vars', {}))
    obs_array = np.array(obs, dtype=np.float32)
    _, reward, done, info = protocolo.step()
    
    return {
        "patch": info.get("patch", {}),
        "done": done,
        "sleep_ms": info.get("sleep_ms", 100),
        "log": info.get("log", ""),
        "reward": reward
    }
`); }
    const p=document.getElementById('prot_params'); if(p){ p.value = '{\n  "x_mm": 150.0,\n  "a_deg": 90.0,\n  "threshold": 2.0\n}'; }
  }; }

  $("#btn_load_prot").onclick = async ()=>{
    const name=($("#prot_name").value||"").trim(); if(!name){toast("Nombre vacío"); return;}
    try{ const r=await jget(`/api/protocols/${encodeURIComponent(name)}`); $("#prot_code").value=r.code||""; toast("Protocolo cargado"); }
    catch{ toast("No existe / error al cargar"); }
  };
  $("#btn_save_prot").onclick = async ()=>{
    const name=($("#prot_name").value||"").trim(), code=$("#prot_code").value||"";
    if(!name||!code){ toast("Completa nombre y código"); return; }
    await jpost("/api/protocols",{name, code}); toast("Protocolo guardado");
  };
  $("#btn_delete_prot").onclick = async ()=>{
    const name=($("#prot_name").value||"").trim(); if(!name){toast("Nombre vacío"); return;}
    const r=await fetch(`/api/protocols/${encodeURIComponent(name)}`,{method:'DELETE'});
    if(r.ok) toast("Protocolo eliminado"); else toast("Error al eliminar");
  };
  $("#btn_run_prot").onclick = async ()=>{
    const name=($("#prot_name").value||"").trim(); if(!name){toast("Nombre vacío"); return;}
    let params={}; const raw=($("#prot_params").value||"").trim();
    if(raw){ try{ params=JSON.parse(raw);}catch{ toast("Params JSON inválido"); return; } }
    const toEl=document.getElementById('prot_timeout'); const timeoutSeconds = toEl? Number(toEl.value||25): undefined;
    const body={type:"protocol", id:name, params}; if(!isNaN(timeoutSeconds)) body.timeout_seconds = timeoutSeconds;
    const r=await jpost("/api/execute", body); $("#job_id").value=r.execution_id||""; activeExecutionId=r.execution_id||null; if(execInfo) execInfo.textContent = `ID: ${activeExecutionId}`; if(execBanner) execBanner.style.display='block'; toast(`Ejecutado (exec ${r.execution_id||''})`);
  };
  $("#btn_list_jobs").onclick = async ()=>{ const eid=($("#job_id").value||"").trim(); if(!eid){ $("#jobs_out").textContent='{"error":"Execution ID vacío"}'; return;} const r=await jget(`/api/execution/${encodeURIComponent(eid)}`); $("#jobs_out").textContent=JSON.stringify(r,null,2); };
  $("#btn_stop_job").onclick = async ()=>{ const eid=($("#job_id").value||"").trim(); if(!eid){toast("Execution ID vacío"); return;} await jpost(`/api/execution/${encodeURIComponent(eid)}/stop`,{}); toast("Stop enviado"); };

  // Acción inmediata (UI)
  const btnImm=document.getElementById('btn_imm_exec'); if(btnImm){ btnImm.onclick = async ()=>{
    const action=(document.getElementById('imm_action')||{}).value||'movement';
    const duration=Number((document.getElementById('imm_duration')||{}).value||10);
    const timeoutSeconds=Number((document.getElementById('imm_timeout')||{}).value||25);
    const autoStop=Boolean((document.getElementById('imm_autostop')||{checked:true}).checked);
    try{
      const body={ type:'immediate', action_type: action, duration, auto_stop: autoStop };
      if(!isNaN(timeoutSeconds)) body.timeout_seconds = timeoutSeconds;
      const r = await jpost('/api/execute', body);
      activeExecutionId = r.execution_id || null; if(execInfo) execInfo.textContent = `ID: ${activeExecutionId}`; if(execBanner) execBanner.style.display='block';
      toast(`Acción inmediata en ejecución (${activeExecutionId||''})`);
    }catch{ toast('Error en acción inmediata'); }
  }; }

  // ------------- Tareas -------------
  async function reloadTasks(){
    const arr=await jget("/api/tasks"); const tb=$("#tasks_tbl tbody"); tb.innerHTML="";
    (arr||[]).forEach(t=>{
      const tr=document.createElement("tr");
      tr.innerHTML=`
        <td>${t.id}</td><td>${t.nombre||t.n||""}</td>
        <td>${(t.programacion&&t.programacion.dias)?(t.programacion.dias.join(',')):(t.dow!=null?t.dow:"")}</td>
        <td>${(t.programacion&&t.programacion.hora)||((t.h!=null&&t.m!=null)?`${String(t.h).padStart(2,'0')}:${String(t.m).padStart(2,'0')}`:"")}</td>
        <td>${t.volumenObjetivoML||t.vol||0}</td><td>${t.protocolo||t.protocol||""}</td><td>${(t.activo!=null?t.activo:t.enabled)?"Sí":"No"}</td>
        <td>
          <button data-act="load" data-id="${t.id}">Editar</button>
          <button data-act="exec" data-id="${t.id}">Ejecutar</button>
          <button class="warn" data-act="del" data-id="${t.id}">Borrar</button>
        </td>`;
      tb.appendChild(tr);
    });
    tb.querySelectorAll("button").forEach(b=>{
      b.onclick = async ()=>{
        const id=b.dataset.id, act=b.dataset.act;
        if(act==="load"){
          const arr=await jget("/api/tasks"); const t=(arr||[]).find(x=>String(x.id)===String(id)); if(!t) return;
          $("#t_id").value=t.id;
          $("#t_n").value=t.nombre||t.n||"";
          // Programación
          if(t.programacion && typeof t.programacion.hora==="string"){
            const hm=(t.programacion.hora||"00:00").split(":");
            $("#t_h").value=Number(hm[0]||0);
            $("#t_m").value=Number(hm[1]||0);
            const dias=(t.programacion.dias||[]);
            $("#t_dow").value=Array.isArray(dias) && dias.length?Number(dias[0]):0;
          }else{
            $("#t_h").value=t.h||0; $("#t_m").value=t.m||0; $("#t_dow").value=t.dow||0;
          }
          $("#t_vol").value=(t.volumenObjetivoML!=null?t.volumenObjetivoML:(t.vol||0));
          $("#t_protocol").value=t.protocolo||t.protocol||"";
          $("#t_enabled").value=(t.activo!=null?t.activo:t.enabled)?"1":"0";
          $("#t_params").value=t.params?JSON.stringify(t.params):"";
          toast("Tarea cargada");
        }else if(act==="exec"){
          let timeoutSeconds=25; const tto=document.getElementById('t_timeout'); if(tto){ const v=Number(tto.value||25); if(!isNaN(v)) timeoutSeconds=v; }
          const r=await jpost(`/api/execute`,{type:"task", id, timeout_seconds: timeoutSeconds}); activeExecutionId=r.execution_id||null; if(execInfo) execInfo.textContent = `ID: ${activeExecutionId}`; if(execBanner) execBanner.style.display='block'; toast("Tarea ejecutada");
        }else if(act==="del"){
          await jdel(`/api/tasks/${encodeURIComponent(id)}`); await reloadTasks(); toast("Tarea borrada");
        }
      };
    });
  }
  $("#btn_reload_tasks").onclick = reloadTasks;
  $("#btn_save_task").onclick = async ()=>{
    let parsedParams={};
    const raw=($("#t_params").value||"").trim();
    if(raw){ try{ parsedParams=JSON.parse(raw);}catch{ parsedParams={}; } }
    const payload={
      id: ($("#t_id").value||"").trim(),
      nombre: $("#t_n").value||"",
      activo: ($("#t_enabled").value||"1")==="1",
      protocolo: ($("#t_protocol").value||"").trim()||undefined,
      params: parsedParams,
      tipo: (($("#t_protocol").value||"").trim()?"protocolo":"accion"),
      programacion: { tipo: "semanal", hora: `${String(Number($("#t_h").value||0)).padStart(2,'0')}:${String(Number($("#t_m").value||0)).padStart(2,'0')}`, dias: [Number($("#t_dow").value||0)] },
      volumenObjetivoML: Number($("#t_vol").value||0)
    };
    await jpost("/api/tasks", payload); await reloadTasks(); toast("Tarea guardada");
  };
  reloadTasks();

  // Logs deshabilitados

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
