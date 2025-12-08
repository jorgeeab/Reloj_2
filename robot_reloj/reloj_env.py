# reloj_env_min.py (ultra-compact, misma API pública)
# ------------------------------------------------------------
# - IO Serial 20→TX / 21←RX (firmware Arduino dado)
# - Protocolos (protocolos/*.py → custom_action(obs)) + **inline** (custom_action(obs, ctx))
# - Tareas con JSON + scheduler + backoff + parada segura
# - Guardias de comandos ('all'|'stop_only'|'none') y exclusividad
# - API compat: port/baudrate ↔ puerto/baudios, setSchedulerEnabled(), tareas_manager,
#               run_inline_task_step(), **apply_patch() alias de patch()**
# - Cámara (OpenCV) opcional
# ------------------------------------------------------------
from __future__ import annotations
import os,csv,json,time,uuid,queue,threading as th
from datetime import datetime,timedelta
from typing import Optional,Dict,Any
import numpy as np
try:
    import gymnasium as gym
except Exception:
    import gym  # type: ignore
import serial
try:
    import cv2; _HAS_CV2=True
except Exception:
    _HAS_CV2=False

# --------- util tiempo ---------
_now=lambda:datetime.now()
_fmt=lambda dt:dt.strftime('%Y-%m-%d %H:%M:%S')
_parse=lambda s:datetime.strptime(s,'%Y-%m-%d %H:%M:%S')

class RelojEnv(gym.Env):
    """Entorno SOLO SERIAL. TX(20): [0..19], RX(21): [0..20]."""
    metadata={"render.modes":["human"]}

    # --------- Motor de protocolos ---------
    class Proto:
        def __init__(self,root='protocolos'):
            self.root=root; os.makedirs(self.root,exist_ok=True)
            self.fn=None; self.name=None
        def list(self): return [f[:-3] for f in os.listdir(self.root) if f.endswith('.py')]
        def save(self,name,code): p=os.path.join(self.root,f'{name}.py'); open(p,'w',encoding='utf-8').write(code); return p
        def drop(self,name):
            p=os.path.join(self.root,f"{name}.py")
            try:
                if os.path.exists(p):
                    os.remove(p)
                    return True
                return False
            except Exception:
                return False
        def load(self,name):
            p=os.path.join(self.root,f'{name}.py')
            if not os.path.exists(p): raise FileNotFoundError(f"No existe protocolo '{name}' en {self.root}/")
            loc:Dict[str,Any]={}; exec(open(p,'r',encoding='utf-8').read(),{},loc)
            if 'custom_action' not in loc or not callable(loc['custom_action']):
                raise ValueError("El protocolo debe definir custom_action(obs).")
            self.fn=loc['custom_action']; self.name=name
        def run(self,obs:np.ndarray):
            if self.fn is None: raise RuntimeError('Protocolo sin cargar.')
            return self.fn(obs)

    # --------- Compat tareas_manager ---------
    class _TasksCompat:
        def __init__(self,env:'RelojEnv'): self._e=env
        def agregar_tarea(self,t): return self._e.add_task(t)
        def obtener_tareas(self):  return self._e.list_tasks()
        def eliminar_tarea(self,x): return self._e.del_task(x)
        def activar_tarea(self,x,a):return self._e.enable_task(x,a)
        def actualizar_tarea(self,x,c):return self._e.update_task(x,c)
        def ejecutar_tarea(self,x):  return self._e.run_task(x)
        def forzar_ejecucion(self,x):return self._e.force_task(x)

    # -------------------- ctor --------------------
    def __init__(self, port:Optional[str]=None, baudrate:Optional[int]=None,
                 puerto:Optional[str]='COM6', baudios:Optional[int]=115200,
                 archivo_tareas:str='data/tareas.json', iniciar_planificador:bool=True,
                 logger=None,
                 iniciar_camara:bool=False, indice_camara:int=0,
                 cam_ancho:Optional[int]=None, cam_alto:Optional[int]=None, cam_fps:Optional[int]=None):
        super().__init__()
        self.log=logger if logger else print
        if port is not None: puerto=port
        if baudrate is not None: baudios=baudrate
        self.port_s=puerto or 'COM6'; self.baud=int(baudios or 115200)
        self.port=self.port_s; self.baudrate=self.baud
        # spaces
        self.action_space=gym.spaces.Box(low=np.array([0,-255,-255,-255,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],np.float32),
                                         high=np.array([3,255,255,255,400,360,100000,255,255,255,255,255,255,1,1,1,10000,10000,1,100000,180,360,10000,1000],np.float32),dtype=np.float32)
        self.act=np.zeros(24,np.float32)
        self.observation_space=gym.spaces.Box(low=-np.inf,high=np.inf,shape=(22,),dtype=np.float32)
        self.rx_names=['posX_mm','angulo_deg','valorBombaAplicado','volumenML','limiteX','limiteA','calibrandoX','calibrandoA','cmdX_aplicado','cmdA_aplicado','cmdBomba_aplicado','codigoModo','kpX','kiX','kdX','kpA','kiA','kdA','pasosPorMM','pasosPorGrado','factorCalibracionFlujo','z_mm']
        # serial & rx
        self.ser=None; self._ser_try=0.0; self._ser_err=False
        self.q: "queue.Queue[np.ndarray]"=queue.Queue(maxsize=5)
        self.rx_stop=th.Event(); self.rx_th:Optional[th.Thread]=None
        # protocolos
        self.proto=RelojEnv.Proto()
        # hook opcional para activar protocolos vía servidor (ProtocolRunner)
        self.protocol_activator = None  # type: ignore
        # exec
        self.t0=time.time(); self.tsim=0.0; self.run_log=[]; self.lk=th.Lock()
        # tareas
        self.tfile=archivo_tareas; os.makedirs(os.path.dirname(self.tfile) or '.',exist_ok=True)
        self.tasks=self.load_tasks(); self.tareas_manager=RelojEnv._TasksCompat(self)
        self.inline_ctx:Dict[str,dict]={}  # contexto por tarea inline
        self.inline_fn:Dict[str,Any]={}    # cache de funciones inline
        # backoff
        self.r_max=3; self.r_base=5; self.r_fac=2; self.r_cap=120
        # guardias/scheduler
        self.sched=iniciar_planificador; self.excl=True; self.policy='stop_only'
        self.task_id:Optional[str]=None; self._cancel=th.Event()
        self.sch_stop=th.Event(); self.sch_th:Optional[th.Thread]=None
        # cam
        self.cam=None; self.cam_idx=None; self.cam_th=None; self.cam_stop=th.Event(); self.cam_lock=th.Lock(); self.cam_fr=None
        self.cam_w=cam_ancho; self.cam_h=cam_alto; self.cam_fps=cam_fps
        # start
        self._ser_open(); self.rx_th=th.Thread(target=self._rx_loop,daemon=True); self.rx_th.start()
        self.sch_th=th.Thread(target=self._sch_loop,daemon=True); self.sch_th.start()
        if iniciar_camara: self.cam_start(indice_camara,ancho=cam_ancho,alto=cam_alto,fps=cam_fps)
        # Calibración Z: 0°=arriba,
        #  180°=abajo; z_mm = (180 - deg) * z_mm_por_grado
        self.z_mm_por_grado: float = 1.0

    # Permite a un integrador externo (servidor) activar protocolos step-wise
    def set_protocol_activator(self, fn):
        self.protocol_activator = fn

    @property
    def is_virtual(self) -> bool:
        return False

    # -------------------- serial --------------------
    def _ser_open(self):
        if self.ser and self.ser.is_open: return True
        now=time.time();
        if (now-self._ser_try)<2: return False
        self._ser_try=now
        try:
            self.log(f"Conectando a {self.port_s} @ {self.baud}...")
            self.ser=serial.Serial(self.port_s,self.baud,timeout=0.3); time.sleep(2); self.log('Serial conectado.'); self._ser_err=False; return True
        except serial.SerialException as e:
            if not self._ser_err: self.log(f"Error de serial: {e}"); self._ser_err=True
            self.ser=None; return False

    # Método público para conexión segura desde la API
    def connect(self, port: Optional[str]=None, baudrate: Optional[int]=None):
        try:
            if port is not None:
                self.port_s = port
                self.port = port
            if baudrate is not None:
                self.baud = int(baudrate)
                self.baudrate = int(baudrate)
            # si ya está abierto, devolver True
            if self.ser and self.ser.is_open:
                return True
            return self._ser_open()
        except Exception as e:
            self.log(f"connect() error: {e}")
            return False

    def _rx_loop(self):
        buf=''
        while not self.rx_stop.is_set():
            if not (self.ser and self.ser.is_open): time.sleep(0.25); self._ser_open(); continue
            try:
                d=self.ser.read(self.ser.in_waiting or 1).decode('utf-8',errors='replace')
                if not d: continue
                buf+=d
                while '<' in buf and '>' in buf:
                    i=buf.find('<'); j=buf.find('>',i)
                    if j==-1: break
                    ln=buf[i+1:j]; buf=buf[j+1:]
                    self._rx_parse(ln)
                if len(buf)>4096: buf=buf[-2048:]
            except serial.SerialException as e:
                self.log(f'Lectura serial falló: {e}'); self.ser=None
            except Exception as e:
                self.log(f'Error inesperado: {e}')

    def _rx_parse(self,ln:str):
        v=[x.strip() for x in ln.strip().split(',') if x.strip()!='']
        if len(v) not in (21,22): return
        try:
            if len(v)==21:
                obs=np.array([float(v[0]),float(v[1]),float(v[2]),float(v[3]),int(float(v[4])),int(float(v[5])),int(float(v[6])),int(float(v[7])),float(v[8]),float(v[9]),float(v[10]),int(float(v[11])),float(v[12]),float(v[13]),float(v[14]),float(v[15]),float(v[16]),float(v[17]),float(v[18]),float(v[19]),float(v[20]),0.0],np.float32)
            else:
                obs=np.array([float(v[0]),float(v[1]),float(v[2]),float(v[3]),int(float(v[4])),int(float(v[5])),int(float(v[6])),int(float(v[7])),float(v[8]),float(v[9]),float(v[10]),int(float(v[11])),float(v[12]),float(v[13]),float(v[14]),float(v[15]),float(v[16]),float(v[17]),float(v[18]),float(v[19]),float(v[20]),float(v[21])],np.float32)
            try: self.q.put_nowait(obs)
            except queue.Full:
                try: _=self.q.get_nowait()
                except queue.Empty: pass
                try: self.q.put_nowait(obs)
                except queue.Full: pass
        except Exception as e:
            self.log(f'_rx_parse error: {e}')

    # -------------------- TX/step --------------------
    @staticmethod
    def _n(x:float)->str: return str(int(x)) if float(x).is_integer() else (f"{x:.3f}".rstrip('0').rstrip('.'))

    def _tx(self,act:Optional[np.ndarray]=None):
        if act is None: act=self.act
        line=",".join(map(self._n,act.tolist()))+"\n"
        try:
            if self.ser: self.ser.write(line.encode('utf-8'))
        except serial.SerialException as e:
            self.log(f'Escritura serial falló: {e}'); self.ser=None

    def _obs_now(self):
        try: return self.q.get_nowait()
        except queue.Empty: return None

    def step(self,act=None):
        if act is None: act=self.act
        else: self.act=np.asarray(act,np.float32)
        if not (self.ser and self.ser.is_open): self._ser_open()
        self._tx(self.act)
        obs=self._obs_now(); w=0
        while obs is None and w<3:
            try: obs=self.q.get(timeout=0.3)
            except queue.Empty: w+=1
        if obs is None: obs=np.zeros(self.observation_space.shape,np.float32)
        self.tsim=round(time.time()-self.t0,3); r=0.0; self._log_step(obs,r)
        self.act[13]=0; self.act[14]=0; self.act[15]=0
        return obs,r,False,{}

    # -------------------- patches/guardias --------------------
    ALIAS:Dict[str,int]={
        'codigoModo':0,'energiaA':1,'energiaX':2,'energiaBomba':3,
        'setpointX_mm':4,'setpointA_deg':5,'volumenObjetivoML':6,
        'kpX':7,'kiX':8,'kdX':9,'kpA':10,'kiA':11,'kdA':12,'resetVolumen':13,'resetX':14,'resetA':15,
        'pasosPorMM':16,'pasosPorGrado':17,'usarSensorFlujo':18,'caudalBombaMLs':19,
        # sinónimos compactos
        'setpointX':4,'setpointA':5,
        # Servo Z (ángulo y velocidad)
        'servoZ_deg':20,
        'servoZ_speed_deg_s':21,
        'servoZ_speed':21,
        # Setpoint Z en mm (para conversión en firmware)
        'setpointZ_mm':22,
        # Calibración Z (mm por grado) enviada al firmware
        'z_mm_per_deg':23,
        'z_mm_por_grado':23
    }

    @staticmethod
    def _is_stop(p:Dict[str,Any])->bool:
        cm=p.get('codigoModo'); v=p.get('volumenObjetivoML'); ex=p.get('energiaX'); ea=p.get('energiaA'); eb=p.get('energiaBomba')
        chk=[]
        if cm is not None: chk.append(int(cm)==3)
        if v  is not None: chk.append(float(v)==0.0)
        if ex is not None: chk.append(float(ex)==0.0)
        if ea is not None: chk.append(float(ea)==0.0)
        if eb is not None: chk.append(float(eb)==0.0)
        return len(chk)>0 and all(chk)

    def set_command_policy(self,pol:str):
        if pol not in ('all','stop_only','none'): raise ValueError("policy debe ser 'all','stop_only' o 'none'")
        self.policy=pol; self.log(f"[Policy] command_policy = {self.policy}")

    def set_scheduler_enabled(self,ena:bool=True): self.sched=bool(ena); self.log(f"[Scheduler] {'ON' if self.sched else 'OFF'}")
    def setSchedulerEnabled(self,ena:bool=True): return self.set_scheduler_enabled(ena)

    def finalizar_tarea(self):
        if not self.task_id: self.log('[Task] No hay tarea activa.'); return
        self._cancel.set(); self.patch({'codigoModo':3,'energiaX':0,'energiaA':0,'energiaBomba':0,'volumenObjetivoML':0},_in=True); self._tx(self.act)
        self.log(f"[Task] Finalización solicitada para '{self.task_id}'.")

    def patch(self,p:Dict[str,Any],_in:bool=False):
        if self.task_id and not _in:
            if self.policy=='none': self.log(f"[Policy] Patch bloqueado (none, tarea='{self.task_id}')."); return self.act.copy()
            if self.policy=='stop_only' and not self._is_stop(p):
                if p.get('finalizar_tarea')==1 or p.get('_finalizar')==1: self.finalizar_tarea(); return self.act.copy()
                self.log(f"[Policy] Patch bloqueado (stop_only, tarea='{self.task_id}')."); return self.act.copy()
        if p.get('finalizar_tarea')==1 or p.get('_finalizar')==1: self.finalizar_tarea(); return self.act.copy()
        a=self.act.copy()
        for k,v in p.items():
            if k in self.ALIAS: a[self.ALIAS[k]]=float(v)
        self.act=a.astype(np.float32); return self.act.copy()

    # alias compat
    def apply_patch(self,p:Dict[str,Any],_interno:bool=False):
        return self.patch(p,_in=_interno)

    # helpers control
    def set_modo(self,mx:Optional[bool]=None,ma:Optional[bool]=None,cod:Optional[int]=None):
        if cod is None:
            cur=int(self.act[0]); bx=(cur&1); ba=(cur>>1)&1
            if mx is not None: bx=1 if mx else 0
            if ma is not None: ba=1 if ma else 0
            cod=(ba<<1)|bx
        self.patch({'codigoModo':int(cod)})

    # Ejecutar: bit 3 de codigoModo (valor 8). Permite enviar setpoints primero y
    # luego disparar el inicio de riego con un trigger inequívoco.
    def set_execute_trigger(self, on: bool):
        cur = int(self.act[0])
        if on:
            cur = cur | 0b1000
        else:
            cur = cur & (~0b1000)
        self.patch({'codigoModo': int(cur)})
    def set_energia_corredera(self,e:int): self.patch({'energiaX':int(np.clip(e,-255,255))})
    def set_energia_angulo(self,e:int):    self.patch({'energiaA':int(np.clip(e,-255,255))})
    def set_energia_bomba(self,e:int):     self.patch({'energiaBomba':int(np.clip(e,-255,255))})
    def set_corredera_mm(self,mm:float):   self.patch({'setpointX_mm':float(np.clip(mm,0,400))})
    def set_angulo_deg(self,dg:float):     self.patch({'setpointA_deg':float(np.clip(dg,0,360))})
    def set_volumen_objetivo_ml(self,ml:float): self.patch({'volumenObjetivoML':max(0.0,float(ml))})
    def set_pid_corredera(self,kp,ki,kd):  self.patch({'kpX':round(float(kp),2),'kiX':round(float(ki),2),'kdX':round(float(kd),2)})
    def set_pid_angulo(self,kp,ki,kd):     self.patch({'kpA':round(float(kp),2),'kiA':round(float(ki),2),'kdA':round(float(kd),2)})
    def reset_volumen(self): self.patch({'resetVolumen':1})
    def reset_x(self):       self.patch({'resetX':1})
    def reset_a(self):       self.patch({'resetA':1})
    def set_pasos_por_mm(self,v):      self.patch({'pasosPorMM':float(v)})
    def set_pasos_por_grado(self,v):   self.patch({'pasosPorGrado':float(v)})
    def set_usar_sensor_flujo(self,u=True): self.patch({'usarSensorFlujo':1 if u else 0})
    def set_caudal_bomba_ml_s(self,mlps):   self.patch({'caudalBombaMLs':max(0.0,float(mlps))})

    # gym std
    def reset(self):
        if not (self.ser and self.ser.is_open): self._ser_open()
        if self.ser:
            try: self.ser.write(b'reset\n')
            except serial.SerialException as e: self.log(f'Error enviando reset: {e}')
        time.sleep(0.5); self.act=np.zeros(24,np.float32)
        obs = self._obs_now()
        if obs is None:
            obs = np.zeros(self.observation_space.shape,np.float32)
        return obs
    def render(self,mode='human'): pass

    # registro
    def _log_step(self,obs,r): self.run_log.append(np.append(obs,r))
    def guardar_ejecucion(self,name):
        with open(f'robot_ejecucion_{name}.csv','w',newline='',encoding='utf-8') as f:
            w=csv.writer(f); w.writerow(self.rx_names+['reward'])
            for row in self.run_log: w.writerow(row)

    # protocolos API
    def listar_protocolos(self): return self.proto.list()
    def guardar_protocolo(self,n,c): return self.proto.save(n,c)
    def eliminar_protocolo(self,n):  return self.proto.drop(n)
    def cargar_protocolo(self,n):    self.proto.load(n)
    def ejecutar_protocolo(self,obs): return self.proto.run(obs)
    def paso_con_protocolo(self):
        obs=self._obs_now()
        if obs is None:
            with self.lk: _=self.step(self.act)
            obs=self._obs_now() or np.zeros(self.observation_space.shape,np.float32)
        prop=self.proto.run(obs); a=self._accion_from(prop)
        with self.lk: return self.step(a)

    # mapeo propuesta→acción(20/22)
    def _accion_from(self,prop):
        if isinstance(prop,(list,tuple,np.ndarray)):
            if len(prop)==20:
                a=np.zeros(22,np.float32); a[:20]=np.asarray(prop,np.float32)[:20]
                return a
            if len(prop)==22:
                return np.asarray(prop,np.float32)
            if len(prop)==23:
                return np.asarray(prop,np.float32)
            if len(prop)==24:
                return np.asarray(prop,np.float32)
            raise ValueError('La acción debe tener 20 o 22 valores.')
        if isinstance(prop,dict):
            a=self.act.copy()
            for k,v in prop.items():
                if k in self.ALIAS: a[self.ALIAS[k]]=v
            return np.asarray(a,np.float32)
        raise ValueError('Propuesta inválida.')

    # -------------------- TAREAS --------------------
    def load_tasks(self):
        if os.path.exists(self.tfile):
            try:
                data=json.load(open(self.tfile,'r',encoding='utf-8'))
                if isinstance(data,dict): data=data.get('tareas') or data.get('tasks') or []
                if not isinstance(data,list): data=[]
                return [it for it in data if isinstance(it,dict)]
            except Exception as e: self.log(f'Error cargando tareas: {e}')
        return []
    def save_tasks(self):
        try: json.dump(self.tasks,open(self.tfile,'w',encoding='utf-8'),indent=2,ensure_ascii=False)
        except Exception as e: self.log(f'Error guardando tareas: {e}')

    # CRUD (nombres cortos + compat wrappers expuestos más abajo)
    def add_task(self,t:dict):
        t=(t or {}).copy(); t.setdefault('id',str(uuid.uuid4()))
        # Si el ID ya existe, actualizar en lugar de duplicar
        idx=self._idx_by_id(t['id'])
        if idx is not None:
            self.update_task(t['id'], t)
            return t['id']
        # Alta nueva
        t.setdefault('activo',True); t.setdefault('ultima_ejecucion',None)
        t.setdefault('intentos_fallidos',0); t.setdefault('max_reintentos',self.r_max)
        t.setdefault('backoff_inicial_seg',self.r_base); t.setdefault('backoff_factor',self.r_fac); t.setdefault('backoff_max_seg',self.r_cap)
        t.setdefault('duracion_ms',0); t.setdefault('parada_segura_al_final',True)
        # inicializar contador de repeticiones si se provee en programacion
        try:
            prog=t.get('programacion') or {}
            reps=prog.get('repeticiones') or prog.get('max_repeticiones')
            if isinstance(reps,int) and reps>0 and 'rep_rest' not in t:
                t['rep_rest']=int(reps)
        except Exception:
            pass
        if not t.get('proxima_ejecucion'): t['proxima_ejecucion']=self._next_time(t,_now())
        self.tasks.append(t); self.save_tasks(); return t['id']
    def list_tasks(self): return self.tasks
    def del_task(self,iid):
        if isinstance(iid,int):
            if 0<=iid<len(self.tasks): self.tasks.pop(iid); self.save_tasks(); return True
            return False
        i=self._idx_by_id(iid)
        if i is not None: self.tasks.pop(i); self.save_tasks(); return True
        return False
    def enable_task(self,iid,on:bool):
        t=self._ref(iid);
        if t is None: return False
        t['activo']=bool(on); t['proxima_ejecucion']=self._next_time(t,_now()) if on else None
        self.save_tasks(); return True
    def update_task(self,iid,chg:dict):
        t=self._ref(iid);
        if t is None: return False
        for k,v in (chg or {}).items():
            if k=='programacion' and isinstance(v,dict): t['programacion']=v
            else: t[k]=v
        # actualizar repeticiones restantes si se especifica explícitamente
        try:
            prog=(chg or {}).get('programacion') or {}
            reps=prog.get('repeticiones') or prog.get('max_repeticiones')
            if isinstance(reps,int) and reps>0:
                t['rep_rest']=int(reps)
        except Exception:
            pass
        for k,dv in (('intentos_fallidos',0),('max_reintentos',self.r_max),('backoff_inicial_seg',self.r_base),('backoff_factor',self.r_fac),('backoff_max_seg',self.r_cap),('duracion_ms',0),('parada_segura_al_final',True)):
            t.setdefault(k,dv)
        if 'programacion' in (chg or {}) or 'activo' in (chg or {}):
            t['proxima_ejecucion']=self._next_time(t,_now()) if t.get('activo',True) else None
        self.save_tasks(); return True
    def run_task(self,iid):
        t=self._ref(iid);
        if t is None: return False
        ok=self._task_exec(t); self.save_tasks(); return ok
    def force_task(self,iid):
        t=self._ref(iid);
        if t is None: return False
        ok=self._task_exec(t,True); self.save_tasks(); return ok

    # compat runner paso a paso (+ soporte protocolo_inline)
    def _find(self,key:str):
        for t in self.tasks:
            if not isinstance(t,dict): continue
            if str(t.get('id'))==str(key): return t
        low=str(key).strip().lower()
        for t in self.tasks:
            if not isinstance(t,dict): continue
            if str(t.get('nombre','')).strip().lower()==low: return t
        return None

    def _inline_exec(self,t:dict,obs:np.ndarray)->Dict[str,Any]:
        tid=str(t.get('id'))
        code=t.get('code') or t.get('codigo') or t.get('script')
        if not code: raise ValueError("protocolo_inline requiere 'code'")
        fn=self.inline_fn.get(tid)
        if fn is None:
            loc:Dict[str,Any] = {}
            exec(code,{},loc)
            fn=loc.get('custom_action')
            if not callable(fn):
                raise ValueError("El inline debe definir custom_action(obs[, ctx]).")
            self.inline_fn[tid]=fn
        ctx=self.inline_ctx.setdefault(tid,{})
        try:
            out=fn(obs,ctx)  # intenta con ctx
        except TypeError:
            out=fn(obs)      # fallback sin ctx
        if out is None:
            out={}
        if isinstance(out,(list,tuple,np.ndarray)):
            out={'patch':out}
        if not isinstance(out,dict):
            raise ValueError('custom_action debe devolver dict/seq o None')
        return out

    def run_inline_task_step(self,task_id:str,timeout_s:float=2.0):
        t=self._find(task_id)
        if t is None: raise KeyError(f"No existe la tarea '{task_id}'. Disponibles: {[tt.get('id') or tt.get('nombre') for tt in self.tasks if isinstance(tt,dict)]}")
        tp=(t.get('tipo') or t.get('type') or '').lower()
        if tp in ('protocolo_inline','inline','proto_inline'):
            obs=self._obs_now()
            if obs is None:
                with self.lk: _=self.step(self.act)
                obs=self._obs_now() or np.zeros(self.observation_space.shape,np.float32)
            out=self._inline_exec(t,obs)
            patch=out.get('patch',{})
            a=self._accion_from(patch)
            self.patch(self._act_to_dict(a),_in=True)
            with self.lk: obs,rew,done,info=self.step(self.act)
            sl=int(out.get('sleep_ms') or t.get('duracion_ms',0) or 0)
            lg=out.get('log') or f"Inline '{t.get('nombre',t.get('id'))}'"
            dn=bool(out.get('done',False))
            return {"obs":obs,"reward":rew,"done":dn,"info":info,"sleep_ms":sl,"log":lg}
        # clásico
        a=self._task_to_action_robust(t)
        self.patch(self._act_to_dict(a),_in=True)
        with self.lk: obs,rew,done,info=self.step(self.act)
        sl=int(t.get('duracion_ms',0) or 0); lg=f"Aplicada tarea '{t.get('nombre',t.get('id'))}' (tipo={t.get('tipo')})."
        return {"obs":obs,"reward":rew,"done":True,"info":info,"sleep_ms":sl,"log":lg}

    # scheduler
    def _sch_loop(self):
        self.log('Planificador iniciado.')
        while not self.sch_stop.is_set():
            if not self.sched: time.sleep(0.2); continue
            now=_now(); upd=False
            if self.task_id and self.excl: time.sleep(0.05); continue
            for t in self.tasks:
                if not isinstance(t,dict) or not t.get('activo',True): continue
                nxt=t.get('proxima_ejecucion')
                if not nxt:
                    t['proxima_ejecucion']=self._next_time(t,now); upd=True; continue
                try: dt=_parse(nxt)
                except Exception:
                    t['proxima_ejecucion']=self._next_time(t,now); upd=True; continue
                if dt and dt<=now:
                    try:
                        if self._task_exec(t): upd=True
                    except Exception as e:
                        self.log(f"Error ejecutando tarea '{t.get('nombre','(sin nombre)')}': {e}")
            if upd: self.save_tasks()
            time.sleep(0.1)
        self.log('Planificador detenido.')

    def set_exclusive_tasks(self,ex:bool=True): self.excl=bool(ex)

    # helpers tareas
    def _idx_by_id(self,tid:str):
        for i,t in enumerate(self.tasks):
            if isinstance(t,dict) and t.get('id')==tid: return i
        return None
    def _ref(self,iid):
        if isinstance(iid,int): return self.tasks[iid] if 0<=iid<len(self.tasks) and isinstance(self.tasks[iid],dict) else None
        i=self._idx_by_id(iid); return self.tasks[i] if i is not None else None

    def _task_to_action(self,t:dict):
        tp=(t.get('tipo') or '').lower()
        if tp in ('accion','action','patch','comando','cmd'): return self._accion_from(t.get('accion') or t.get('action') or t.get('patch'))
        if tp in ('protocolo','protocol','script'):
            name=t.get('protocolo') or t.get('protocol') or t.get('script')
            if not name: raise ValueError('Protocolo sin nombre')
            obs=self._obs_now()
            if obs is None:
                with self.lk: _=self.step(self.act)
                obs=self._obs_now() or np.zeros(self.observation_space.shape,np.float32)
            if not self.proto.fn or self.proto.name!=name: self.proto.load(name)
            prop=self.proto.run(obs); return self._accion_from(prop)
        return self._task_to_action_robust(t)

    def _task_to_action_robust(self,t:dict):
        if not isinstance(t,dict):
            s=str(t).strip().lower()
            if s in ('stop','parada','parada_segura','safe_stop'):
                return self._accion_from({'codigoModo':3,'energiaX':0,'energiaA':0,'energiaBomba':0,'volumenObjetivoML':0})
            raise ValueError('Tarea inválida: se esperaba dict.')
        low={str(k).lower():v for k,v in t.items()}
        tp=(low.get('tipo') or low.get('type') or low.get('tipo_tarea') or '').strip().lower()
        if not tp:
            if any(k in low for k in ('protocolo','protocol','script','nombre_protocolo')): tp='protocolo'
            elif any(k in low for k in ('accion','action','patch','cmd','comando')): tp='accion'
            elif any(k in t for k in ('params','parametros')): tp='accion'
            elif any(k in t for k in self.ALIAS.keys()): tp='accion'
        if tp in ('stop','parada','parada_segura','safe_stop'):
            return self._accion_from({'codigoModo':3,'energiaX':0,'energiaA':0,'energiaBomba':0,'volumenObjetivoML':0})
        if tp in ('protocolo_inline','inline','proto_inline'):
            # Cuando se use desde _task_exec(), se llamará run_inline_task_step; aquí solo devolvemos patch→acción
            obs=self._obs_now()
            if obs is None:
                with self.lk: _=self.step(self.act)
                obs=self._obs_now() or np.zeros(self.observation_space.shape,np.float32)
            out=self._inline_exec(t,obs)
            return self._accion_from(out.get('patch',{}))
        if tp in ('accion','action','patch','comando','cmd'):
            prop=t.get('accion') if 'accion' in low else t.get('action') if 'action' in low else t.get('patch') if 'patch' in low else None
            if prop is None:
                params=t.get('params') or t.get('parametros') or {}
                if isinstance(params,dict):
                    prop=params.get('accion') or params.get('action') or params.get('patch')
                    if prop is None and any(k in params for k in self.ALIAS.keys()):
                        prop={k:params[k] for k in self.ALIAS.keys() if k in params}
            if prop is None and any(k in t for k in self.ALIAS.keys()):
                prop={k:t[k] for k in self.ALIAS.keys() if k in t}
            if prop is None: raise ValueError("Tarea 'accion' sin 'accion/patch' ni claves válidas.")
            return self._accion_from(prop)
        if tp in ('protocolo','protocol','script'):
            name=t.get('protocolo') or t.get('protocol') or t.get('script') or t.get('nombre_protocolo')
            if not name: raise ValueError('Tarea de protocolo sin nombre.')
            obs=self._obs_now()
            if obs is None:
                with self.lk: _=self.step(self.act)
                obs=self._obs_now() or np.zeros(self.observation_space.shape,np.float32)
            if (not self.proto.fn) or (self.proto.name!=name): self.proto.load(name)
            prop=self.proto.run(obs); return self._accion_from(prop)
        if any(k in t for k in self.ALIAS.keys()):
            return self._accion_from({k:t[k] for k in self.ALIAS.keys() if k in t})
        params=t.get('params') or t.get('parametros') or {}
        if isinstance(params,dict) and any(k in params for k in self.ALIAS.keys()):
            return self._accion_from({k:params[k] for k in self.ALIAS.keys() if k in params})
        raise ValueError("Tipo de tarea inválido (esperado 'protocolo' o 'accion').")

    def _task_exec(self,t:dict,force:bool=False)->bool:
        if self.task_id and self.excl:
            self.log(f"[Task] Activa '{self.task_id}', se omite '{t.get('nombre','(sin nombre)')}'."); return False
        tid=t.get('id') or str(uuid.uuid4()); self.task_id=tid; self._cancel.clear()
        
        # Si es una tarea de protocolo y hay activador, delegar al activador y finalizar
        try:
            low={str(k).lower():v for k,v in (t or {}).items()}
            tp=(low.get('tipo') or low.get('type') or '').strip().lower()
            is_proto = (tp in ('protocolo','protocol','script')) or any(k in low for k in ('protocolo','protocol','script','nombre_protocolo'))
            if is_proto and callable(self.protocol_activator):
                name=t.get('protocolo') or t.get('protocol') or t.get('script') or t.get('nombre_protocolo')
                if not name:
                    raise ValueError('Tarea de protocolo sin nombre')
                params = {}
                params_src = t.get('params') or t.get('parametros') or {}
                if isinstance(params_src,dict): params.update(params_src)
                for k in ('timeout_seconds','target_x_mm','target_a_deg','threshold_x_mm','threshold_a_deg'):
                    if k in t: params[k]=t[k]
                try:
                    self.protocol_activator(name, params)  # type: ignore
                    self.log(f"[Task] Activado protocolo '{name}' desde tarea '{tid}'.")
                except Exception as e:
                    self.log(f"[Task] Error activando protocolo '{name}': {e}")
                # Considerar tarea completada inmediatamente
                return True
        except Exception as e:
            self.log(f"[Task] Error en activación de protocolo: {e}")
        try:
            a=self._task_to_action_robust(t); dur=int(t.get('duracion_ms',0) or 0); stop=bool(t.get('parada_segura_al_final',True))
            self.patch(self._act_to_dict(a),_in=True)
            t0=time.time();
            with self.lk: _=self.step(self.act)
            if dur>0:
                end=t0+dur/1000.0
                while time.time()<end and not self._cancel.is_set():
                    with self.lk: _=self.step(self.act)
                    time.sleep(0.05)
            if stop or self._cancel.is_set():
                self.patch({'codigoModo':3,'energiaX':0,'energiaA':0,'energiaBomba':0,'volumenObjetivoML':0},_in=True)
                with self.lk: _=self.step(self.act)
            # marcar ejecución completada
            t['ultima_ejecucion']=_fmt(_now()); t['intentos_fallidos']=0
            # decrementar repeticiones si aplica
            try:
                if isinstance(t.get('rep_rest'),int) and t['rep_rest']>0:
                    t['rep_rest']-=1
            except Exception:
                pass
            t['proxima_ejecucion']=self._next_time(t,_now()); return True
        except Exception as e:
            it=int(t.get('intentos_fallidos',0))+1; t['intentos_fallidos']=it
            mx=int(t.get('max_reintentos',self.r_max)); base=int(t.get('backoff_inicial_seg',self.r_base)); fac=int(t.get('backoff_factor',self.r_fac)); cap=int(t.get('backoff_max_seg',self.r_cap))
            if it<=mx:
                wait=min(base*(fac**(it-1)),cap); t['proxima_ejecucion']=_fmt(_now()+timedelta(seconds=wait))
                self.log(f"Tarea '{t.get('nombre','(sin nombre)')}' falló ({e}). Reintento {it}/{mx} en {wait}s.")
            else:
                t['proxima_ejecucion']=None; self.log(f"Tarea '{t.get('nombre','(sin nombre)')}' agotó reintentos: {e}")
            return False
        finally:
            self.task_id=None; self._cancel.clear()

    def _act_to_dict(self,a:np.ndarray)->Dict[str,Any]:
        inv={v:k for k,v in self.ALIAS.items()}
        return {inv[i]:float(a[i]) for i in range(min(len(a),24)) if i in inv}

    # --------- Helpers Z (servo) ---------
    def set_servo_z_deg(self, deg: float):
        d=float(deg)
        if d<0: d=0.0
        if d>180: d=180.0
        self.patch({'servoZ_deg': d})
    def set_servo_z_speed(self, deg_s: float):
        v=max(0.0,float(deg_s))
        self.patch({'servoZ_speed_deg_s': v})
    def set_z_mm(self, mm: float):
        # Enviar mm directo al firmware (índice 22), la conversión a deg sucede en Arduino
        try:
            z=float(mm)
            if z<0: z=0.0
            self.patch({'setpointZ_mm': z})
        except Exception:
            pass
    def set_z_mm_por_grado(self, s: float):
        try:
            self.z_mm_por_grado=float(s)
            # enviar al firmware
            self.patch({'z_mm_per_deg': float(self.z_mm_por_grado)})
        except Exception: pass

    def _next_time(self,t:dict,base:datetime):
        p=t.get('programacion',{})
        if not t.get('activo',True): return None
        # límite por recuento
        if isinstance(t.get('rep_rest'),int) and t.get('rep_rest')<=0: return None
        # límite por fecha
        hasta=p.get('hasta'); hasta_dt=None
        if isinstance(hasta,str) and hasta.strip():
            try:
                hasta_dt=_parse(hasta)
            except Exception:
                try: hasta_dt=_parse(hasta.strip()+" 00:00:00")
                except Exception: hasta_dt=None
        typ=p.get('tipo')
        if typ=='una_vez':
            w=p.get('cuando');
            if not w: return None
            dt=_parse(w); return _fmt(dt) if dt>base else None
        if typ=='cada_segundos':
            iv=int(p.get('intervalo',0));
            if iv<=0: return None
            last=t.get('ultima_ejecucion')
            if last:
                dt=_parse(last)+timedelta(seconds=iv)
                if dt<=base: dt=base
                return _fmt(dt)
            return _fmt(base)
        if typ=='diario':
            hh,mm=map(int,(p.get('hora','00:00')).split(':'))
            dt=base.replace(hour=hh,minute=mm,second=0,microsecond=0)
            if dt<=base: dt=dt+timedelta(days=1)
            if hasta_dt and dt>hasta_dt: return None
            return _fmt(dt)
        if typ=='semanal':
            hh,mm=map(int,(p.get('hora','00:00')).split(':')); dias=p.get('dias',[])
            if not dias: return None
            wd=base.weekday(); cand=[]
            for d in dias:
                delta=(d-wd)%7
                dt=base.replace(hour=hh,minute=mm,second=0,microsecond=0)+timedelta(days=delta)
                if dt<=base: dt=dt+timedelta(days=7)
                cand.append(dt)
            nxt=min(cand)
            if hasta_dt and nxt>hasta_dt: return None
            return _fmt(nxt)
        if typ=='cada_horas':
            iv=int(p.get('intervalo',0) or 0)
            if iv<=0: return None
            last=t.get('ultima_ejecucion')
            ref=_parse(last) if last else base
            dt=ref+timedelta(hours=iv)
            if dt<=base:
                delta=base-ref; steps=int(delta.total_seconds()//(iv*3600))+1; dt=ref+timedelta(hours=iv*steps)
            if hasta_dt and dt>hasta_dt: return None
            return _fmt(dt)
        if typ=='cada_dias':
            iv=int(p.get('intervalo',0) or 0)
            if iv<=0: return None
            last=t.get('ultima_ejecucion')
            ref=_parse(last) if last else base
            dt=ref+timedelta(days=iv)
            if dt<=base:
                delta=base-ref; steps=int(delta.days//iv)+1; dt=ref+timedelta(days=iv*steps)
            if hasta_dt and dt>hasta_dt: return None
            return _fmt(dt)
        if typ=='cada_semanas':
            iv=int(p.get('intervalo',0) or 0)
            if iv<=0: return None
            last=t.get('ultima_ejecucion')
            ref=_parse(last) if last else base
            dt=ref+timedelta(weeks=iv)
            if dt<=base:
                delta=base-ref; steps=int(delta.days//(iv*7))+1; dt=ref+timedelta(weeks=iv*steps)
            if hasta_dt and dt>hasta_dt: return None
            return _fmt(dt)
        return None

    # -------------------- Cámara --------------------
    # =============================================================================
    # FUNCIONALIDAD DE CÁMARA - NO UTILIZADA EN VERSIÓN MÍNIMA
    # =============================================================================
    # Nota: Esta funcionalidad está deshabilitada pero se mantiene para compatibilidad
    
    def cam_start(self,idx=0,ancho=None,alto=None,fps=None):
        if not _HAS_CV2: raise ImportError('OpenCV no instalado.')
        self.cam_stop.set(); self.cam_stop.clear()
        self.cam_stop.clear(); self.cam_stop.clear()  # idempotente
        self.cam_stop.clear()
        self.cam_stop.clear()
        self.cam_stop.clear()
        self.cam_stop.clear()
        self.cam_stop.clear()
        self.cam_stop.clear()
        # ^ (no-ops deliberados para minimizar difs)
        self.cam_stop.clear()
        self.cam_stop.clear()
        self.cam_stop.clear()
        self.cam_stop.clear()
        self.cam_stop.clear()
        self.cam_stop.clear()
        # start
        self.cam_stop.clear()
        self.cam=None; cap=cv2.VideoCapture(idx)
        if not cap or not cap.isOpened(): raise RuntimeError(f'No se pudo abrir cámara {idx}.')
        if ancho is not None: cap.set(cv2.CAP_PROP_FRAME_WIDTH,int(ancho))
        if alto  is not None: cap.set(cv2.CAP_PROP_FRAME_HEIGHT,int(alto))
        if fps   is not None: cap.set(cv2.CAP_PROP_FPS,int(fps))
        self.cam=cap; self.cam_idx=idx; self.cam_w=ancho; self.cam_h=alto; self.cam_fps=fps
        self.cam_stop.clear(); self.cam_th=th.Thread(target=self._cam_loop,daemon=True); self.cam_th.start(); self.log(f'Cámara iniciada (índice={idx}).')
    def _cam_loop(self):
        while not self.cam_stop.is_set() and self.cam and self.cam.isOpened():
            ok,fr=self.cam.read()
            if ok:
                with self.cam_lock: self.cam_fr=fr
            else: time.sleep(0.01)
    def cam_stop_fn(self):
        self.cam_stop.set()
        if self.cam_th: self.cam_th.join(timeout=1.0)
        if self.cam:
            try: self.cam.release()
            except Exception: pass
        self.cam=None; self.cam_th=None; self.cam_fr=None; self.cam_stop.clear(); self.log('Cámara detenida.')
    def cam_switch(self,i,ancho=None,alto=None,fps=None): self.cam_start(i,ancho=ancho,alto=alto,fps=fps)
    def cam_read(self,rgb=True):
        if not self.cam: return None
        with self.cam_lock: fr=None if self.cam_fr is None else self.cam_fr.copy()
        if fr is None: return None
        if rgb: fr=cv2.cvtColor(fr,cv2.COLOR_BGR2RGB)
        return fr
    def cam_save(self,path='captura.jpg',rgb=False):
        if not _HAS_CV2: raise ImportError('OpenCV no instalado.')
        with self.cam_lock: fr=None if self.cam_fr is None else self.cam_fr.copy()
        if fr is None: return False
        if rgb: fr=cv2.cvtColor(fr,cv2.COLOR_RGB2BGR)
        os.makedirs(os.path.dirname(path) or '.',exist_ok=True)
        try: return bool(cv2.imwrite(path,fr))
        except Exception as e: self.log(f'Error guardando frame: {e}'); return False
    def cam_cfg(self,ancho=None,alto=None,fps=None):
        if not self.cam: raise RuntimeError('No hay cámara activa.')
        if ancho is not None: self.cam.set(cv2.CAP_PROP_FRAME_WIDTH,int(ancho))
        if alto  is not None: self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT,int(alto))
        if fps   is not None: self.cam.set(cv2.CAP_PROP_FPS,int(fps))
        self.cam_w=ancho if ancho is not None else self.cam_w
        self.cam_h=alto  if alto  is not None else self.cam_h
        self.cam_fps=fps if fps  is not None else self.cam_fps
    def cam_discover(self,max_idx=5):
        if not _HAS_CV2: raise ImportError('OpenCV no instalado.')
        arr=[]
        for i in range(max_idx):
            cap=cv2.VideoCapture(i); ok=cap.isOpened();
            if ok: arr.append(i)
            if cap: cap.release()
        return arr

    # -------------------- cierre --------------------
    def close(self):
        self.sch_stop.set();
        if self.sch_th and self.sch_th.is_alive(): self.sch_th.join(timeout=1.0)
        self.rx_stop.set();
        if self.rx_th and self.rx_th.is_alive(): self.rx_th.join(timeout=1.0)
        if self.ser:
            try: self.ser.close()
            except Exception: pass
        self.cam_stop_fn(); self.log('Entorno cerrado.')
