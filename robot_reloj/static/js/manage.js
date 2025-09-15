(()=>{
  const $ = s=>document.querySelector(s);
  const toast=(m,ms=1500)=>{const t=$("#toast"); if(!t) return; t.textContent=m; t.hidden=false; setTimeout(()=>t.hidden=true,ms);};
  const jget=async u=>{const r=await fetch(u); if(!r.ok) throw new Error(`${r.status} ${u}`); return r.json();};
  const jpost=async (u,b)=>{const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})}); if(!r.ok) throw new Error(`${r.status} ${u}`); return r.json();};
  const jdel=async u=>{const r=await fetch(u,{method:'DELETE'}); if(!r.ok) throw new Error(`${r.status} ${u}`); return r.json();};

  // Protocolos
  $("#btn_load_prot").onclick=async()=>{
    const name=($("#prot_name").value||"").trim(); if(!name){toast("Nombre vacío"); return;}
    try{ const r=await jget(`/api/protocols/${encodeURIComponent(name)}`); $("#prot_code").value=r.code||""; toast("Protocolo cargado"); }
    catch{ toast("No existe / error al cargar"); }
  };
  $("#btn_save_prot").onclick=async()=>{
    const name=($("#prot_name").value||"").trim(), code=$("#prot_code").value||""; if(!name||!code){toast("Completa nombre y código"); return;}
    await jpost('/api/protocols',{name,code}); toast('Protocolo guardado');
  };
  $("#btn_delete_prot").onclick=async()=>{
    const name=($("#prot_name").value||"").trim(); if(!name){toast("Nombre vacío"); return;}
    const r=await fetch(`/api/protocols/${encodeURIComponent(name)}`,{method:'DELETE'}); toast(r.ok?"Protocolo eliminado":"Error al eliminar");
  };
  $("#btn_run_prot").onclick=async()=>{
    const name=($("#prot_name").value||"").trim(); if(!name){toast("Nombre vacío"); return;}
    let params={}; const raw=($("#prot_params").value||"").trim(); if(raw){ try{params=JSON.parse(raw);}catch{ toast("Params inválido"); return; } }
    const r=await jpost('/api/execute',{type:'protocol', id:name, params}); $("#job_id").value=r.execution_id||""; toast(`Ejecutado (exec ${r.execution_id||''})`);
  };
  $("#btn_list_jobs").onclick=async()=>{ const r=await jget('/api/executions'); $("#jobs_out").textContent=JSON.stringify(r,null,2); };
  $("#btn_stop_job").onclick=async()=>{ const eid=($("#job_id").value||"").trim(); if(!eid){toast('Execution ID vacío'); return;} await jpost(`/api/execution/${encodeURIComponent(eid)}/stop`,{}); toast('Stop enviado'); };

  // Tareas
  async function reloadTasks(){
    const arr=await jget('/api/tasks'); const tb=$("#tasks_tbl tbody"); tb.innerHTML="";
    (arr||[]).forEach(t=>{
      const tr=document.createElement('tr');
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
    tb.querySelectorAll('button').forEach(b=>{
      b.onclick=async()=>{
        const id=b.dataset.id, act=b.dataset.act;
        if(act==='load'){
          const arr=await jget('/api/tasks'); const t=(arr||[]).find(x=>String(x.id)===String(id)); if(!t) return;
          $("#t_id").value=t.id; $("#t_n").value=t.nombre||t.n||"";
          if(t.programacion&&t.programacion.hora){ const hm=t.programacion.hora.split(':'); $("#t_h").value=Number(hm[0]||0); $("#t_m").value=Number(hm[1]||0); const dias=t.programacion.dias||[]; $("#t_dow").value=Array.isArray(dias)&&dias.length?Number(dias[0]):0; } else { $("#t_h").value=t.h||0; $("#t_m").value=t.m||0; $("#t_dow").value=t.dow||0; }
          $("#t_vol").value=(t.volumenObjetivoML!=null?t.volumenObjetivoML:(t.vol||0));
          $("#t_protocol").value=t.protocolo||t.protocol||"";
          $("#t_enabled").value=(t.activo!=null?t.activo:t.enabled)?'1':'0';
          $("#t_params").value=t.params?JSON.stringify(t.params):''; toast('Tarea cargada');
        } else if(act==='exec'){
          await jpost('/api/execute',{type:'task',id}); toast('Tarea ejecutada');
        } else if(act==='del'){
          await jdel(`/api/tasks/${encodeURIComponent(id)}`); await reloadTasks(); toast('Tarea borrada');
        }
      };
    });
  }
  $("#btn_reload_tasks").onclick=reloadTasks;
  $("#btn_save_task").onclick=async()=>{
    let parsedParams={}; const raw=($("#t_params").value||'').trim(); if(raw){ try{ parsedParams=JSON.parse(raw);}catch{ parsedParams={}; } }
    const payload={
      id: ($("#t_id").value||'').trim(),
      nombre: $("#t_n").value||'',
      activo: ($("#t_enabled").value||'1')==='1',
      protocolo: ($("#t_protocol").value||'').trim()||undefined,
      params: parsedParams,
      tipo: (($("#t_protocol").value||'').trim()? 'protocolo':'accion'),
      programacion: { tipo:'semanal', hora:`${String(Number($("#t_h").value||0)).padStart(2,'0')}:${String(Number($("#t_m").value||0)).padStart(2,'0')}`, dias:[Number($("#t_dow").value||0)] },
      volumenObjetivoML: Number($("#t_vol").value||0)
    };
    await jpost('/api/tasks',payload); await reloadTasks(); toast('Tarea guardada');
  };
  reloadTasks();
})();

