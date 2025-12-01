from __future__ import annotations

import os
import time
import threading
import uuid
from datetime import datetime
from typing import Dict, Optional

try:
    import serial  # type: ignore
    from serial.tools import list_ports  # type: ignore
except Exception:  # pyserial optional; allow simulation
    serial = None  # type: ignore
    list_ports = None  # type: ignore

import asyncio
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Response, WebSocket
from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.websockets import WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


class ExecInfo(BaseModel):
    execution_id: str
    status: str  # queued | running | completed | stopped | error
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    requested_ms: Optional[int] = None
    progress: Optional[float] = None
    error: Optional[str] = None


class PumpController:
    def __init__(self, serial_port: Optional[str], ml_per_sec: float = 10.0):
        self.serial_port = serial_port
        self.ml_per_sec = float(ml_per_sec)
        self._ser = None
        self._lock = threading.Lock()
        self._running = False
        self._stop_flag = False
        self._baud = 115200
        if self.serial_port:
            # best-effort open; ignore failure when pyserial not available
            try:
                self.open_serial(self.serial_port, self._baud)
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        return self._running

    def open_serial(self, port: str, baud: int = 115200) -> bool:
        try:
            if self._ser:
                self._ser.close()
        except Exception:
            pass
        self._ser = None
        self.serial_port = port
        self._baud = baud
        if serial is None:
            return False
        try:
            self._ser = serial.Serial(port, baud, timeout=0.1)
            time.sleep(1.0)
            return True
        except Exception:
            self._ser = None
            return False

    def close_serial(self) -> None:
        try:
            if self._ser:
                self._ser.close()
        except Exception:
            pass
        self._ser = None

    def serial_status(self) -> Dict:
        return {"opened": bool(self._ser), "port": self.serial_port, "baud": getattr(self, "_baud", 115200)}

    def run_ms(self, ms: int, on_progress=None) -> None:
        """Run the pump for ms milliseconds (blocking)."""
        ms = max(0, int(ms))
        with self._lock:
            self._stop_flag = False
            self._running = True
            try:
                if self._ser:
                    try:
                        self._ser.write(f"RUN {ms}\n".encode("utf-8"))
                    except Exception:
                        pass
                    # Still wait locally for completion
                t0 = time.time()
                while (time.time() - t0) * 1000.0 < ms:
                    if self._stop_flag:
                        break
                    if on_progress is not None:
                        try:
                            on_progress((time.time() - t0) * 1000.0 / max(1, ms))
                        except Exception:
                            pass
                    time.sleep(0.02)
            finally:
                if self._ser:
                    try:
                        self._ser.write(b"STOP\n")
                    except Exception:
                        pass
                self._running = False
                self._stop_flag = False

    def stop(self):
        with self._lock:
            self._stop_flag = True
            if self._ser:
                try:
                    self._ser.write(b"STOP\n")
                except Exception:
                    pass


class TaskRunner:
    def __init__(self, pump: PumpController):
        self.pump = pump
        self.tasks: Dict[str, ExecInfo] = {}
        self._threads: Dict[str, threading.Thread] = {}

    def start_riego(self, volume_ml: Optional[float] = None, duration_seconds: Optional[float] = None) -> ExecInfo:
        # Compute time to run
        ms: int
        if volume_ml is not None:
            ms = int(max(0.0, float(volume_ml)) / max(0.001, self.pump.ml_per_sec) * 1000.0)
        elif duration_seconds is not None:
            ms = int(max(0.0, float(duration_seconds)) * 1000.0)
        else:
            ms = int(10_000)  # default 10s
        exec_id = str(uuid.uuid4())[:8]
        info = ExecInfo(execution_id=exec_id, status="running", started_at=datetime.utcnow().isoformat(), requested_ms=ms)
        self.tasks[exec_id] = info

        def _run():
            try:
                def _on_prog(frac: float):
                    try:
                        info.progress = max(0.0, min(1.0, float(frac)))
                    except Exception:
                        pass
                    if _viz:
                        try:
                            _viz.on_progress(frac)
                        except Exception:
                            pass
                self.pump.run_ms(ms, on_progress=_on_prog)
                info.status = "completed" if not self.pump.is_running else info.status
            except Exception as e:
                info.status = "error"
                info.error = str(e)
            finally:
                info.ended_at = datetime.utcnow().isoformat()
                if info.status == "completed":
                    info.progress = 1.0

        th = threading.Thread(target=_run, daemon=True)
        self._threads[exec_id] = th
        th.start()
        return info

    def stop(self, exec_id: str) -> ExecInfo:
        info = self.tasks.get(exec_id)
        if not info:
            raise KeyError(exec_id)
        self.pump.stop()
        info.status = "stopped"
        info.ended_at = datetime.utcnow().isoformat()
        return info


app = FastAPI(title="Simple Pump Robot", version="0.1")

# Serve simple UI if available
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")

# Importar sistema de protocolos
from protocolos import ProtocolRunner, Protocolo
from task_executor import TaskExecutor, ExecutionMode
from task_scheduler import TaskScheduler, TaskSchedule, ScheduleType, create_daily_schedule, create_interval_schedule

# Adapter para que ProtocolRunner vea a PumpController como un robot_env estándar
class RobotEnvAdapter:
    def __init__(self, pump_controller: PumpController):
        self.pump = pump_controller
        self.act = [0] * 20 # Mock de estado
        self.port = pump_controller.serial_port
        self.baudrate = 115200
        self.is_virtual = False # Asumimos hardware real si hay puerto
        
        # State tracking
        self._pumping_start_time = None
        self._accumulated_volume = 0.0
        self._last_update_time = time.time()

    def set_energia_bomba(self, val: int):
        # Mapear energía 0-255 a start/stop
        if val > 0:
            if not self.pump.is_running:
                self.pump.run_ms(3600000) # Run "forever"
                self._pumping_start_time = time.time()
        else:
            if self.pump.is_running:
                self.pump.stop()
                self._update_volume()
                self._pumping_start_time = None

    def set_volumen_objetivo_ml(self, val: float):
        # El protocolo maneja la lógica de parada, solo necesitamos tracking
        pass

    def set_corredera_mm(self, val: float): pass
    def set_angulo_deg(self, val: float): pass
    def set_z_mm(self, val: float): pass
    def set_servo_z_deg(self, val: float): pass
    def set_modo(self, mx=None, ma=None, cod=None): pass
    
    def step(self):
        # Actualizar estado simulado
        self._update_volume()
        
    def _update_volume(self):
        now = time.time()
        if self.pump.is_running and self._pumping_start_time:
            dt = now - self._last_update_time
            # ml/s * s = ml
            self._accumulated_volume += self.pump.ml_per_sec * dt
        self._last_update_time = now

    def get_volumen_acumulado_ml(self) -> float:
        self._update_volume()
        return self._accumulated_volume
        
    def reset_volumen(self):
        self._accumulated_volume = 0.0
        self._pumping_start_time = None if not self.pump.is_running else time.time()

    def reset_x(self): pass
    def reset_a(self): pass

PUMP_SERIAL = os.environ.get("PUMP_SERIAL")  # e.g., COM4 or /dev/ttyUSB0
ML_PER_SEC = float(os.environ.get("PUMP_ML_PER_SEC", "10.0"))

_pump = PumpController(PUMP_SERIAL, ML_PER_SEC)
_env_adapter = RobotEnvAdapter(_pump)

# Inicializar sistema de protocolos
PROTOCOLS_DIR = Path(__file__).resolve().parent / "protocolos"
protocol_runner = ProtocolRunner(_env_adapter, str(PROTOCOLS_DIR))
task_executor = TaskExecutor(protocol_runner, _env_adapter)
task_scheduler = TaskScheduler(task_executor)

# Iniciar hilos
task_scheduler.start()

# _runner = TaskRunner(_pump) # Deprecated

# ---------- Simple PyBullet visual ----------
try:
    import pybullet as p  # type: ignore
    import pybullet_data  # type: ignore
except Exception:
    p = None  # type: ignore
    pybullet_data = None  # type: ignore


class PumpVisualizer:
    def __init__(self, width: int = 400, height: int = 300):
        self.width = width
        self.height = height
        self.client = None
        self.water_id = None
        self.base_id = None
        self.level = 0.0  # 0..1
        self.max_ml = 200.0
        self._init()

    def _init(self):
        if p is None:
            return
        self.client = p.connect(p.DIRECT)
        if pybullet_data is not None:
            p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=self.client)
        p.resetSimulation(physicsClientId=self.client)
        p.setGravity(0, 0, -9.8, physicsClientId=self.client)
        plane = p.loadURDF("plane.urdf", physicsClientId=self.client)
        self.base_id = plane
        # Create a simple blue box that we scale on Z to represent water level
        visual = p.createVisualShape(p.GEOM_BOX, halfExtents=[0.2, 0.2, 0.001], rgbaColor=[0.2, 0.4, 0.9, 0.9], physicsClientId=self.client)
        collision = p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.2, 0.2, 0.001], physicsClientId=self.client)
        self.water_id = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=collision, baseVisualShapeIndex=visual, basePosition=[0, 0, 0.001], physicsClientId=self.client)

    def on_progress(self, frac: float):
        # frac 0..1 while pumping; map to level 0..1
        self.level = max(0.0, min(1.0, float(frac)))

    def set_ml(self, ml: float):
        self.level = max(0.0, min(1.0, float(ml) / self.max_ml))

    def reset(self):
        self.level = 0.0

    def render_frame(self) -> Optional[bytes]:
        if p is None or self.client is None or self.water_id is None:
            return None
        # Update water height
        height = 0.001 + 0.2 * self.level
        p.resetBasePositionAndOrientation(self.water_id, [0, 0, height], [0, 0, 0, 1], physicsClientId=self.client)
        # Render camera looking at origin
        view = p.computeViewMatrixFromYawPitchRoll(cameraTargetPosition=[0, 0, 0], distance=1.2, yaw=45, pitch=-30, roll=0, upAxisIndex=2, physicsClientId=self.client)
        proj = p.computeProjectionMatrixFOV(fov=60, aspect=self.width/self.height, nearVal=0.01, farVal=5)
        img = p.getCameraImage(self.width, self.height, view, proj, renderer=p.ER_TINY_RENDERER, physicsClientId=self.client)
        rgba = img[2]
        # Convert to JPEG
        try:
            from PIL import Image  # type: ignore
            import io
            image = Image.fromarray(rgba, 'RGBA').convert('RGB')
            buf = io.BytesIO()
            image.save(buf, format='JPEG', quality=85)
            return buf.getvalue()
        except Exception:
            return None


_viz = None
try:
    _viz = PumpVisualizer()
except Exception:
    _viz = None

# -------------- Config persistence --------------
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONF_FILE = BASE_DIR / "config.json"


def _load_config() -> Dict:
    try:
        raw = json.loads(CONF_FILE.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return raw or {}


def _save_config(data: Dict) -> None:
    try:
        CONF_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

_cfg = _load_config()
if _cfg.get("ml_per_sec"):
    try:
        _pump.ml_per_sec = float(_cfg.get("ml_per_sec"))
    except Exception:
        pass
if _cfg.get("serial_port") and not _pump.serial_port:
    try:
        _pump.open_serial(str(_cfg.get("serial_port")), int(_cfg.get("baud") or 115200))
    except Exception:
        pass

# Flow flags (persisted)
_use_sensor_flow = bool(_cfg.get("usar_sensor_flujo", False))
_actuators = _cfg.get("actuators") or ["pump"]


@app.get("/")
def home():
    # Prefer simple UI when available, keep JSON fallback
    if STATIC_DIR.exists():
        return RedirectResponse(url="/ui/")
    return {"name": "simple-pump-robot", "status": "ok"}


@app.get("/api")
def api_index():
    return {
        "name": "Simple Pump Robot API",
        "version": "0.1",
        "endpoints": {
            "ws": {"control": "/ws/control", "telemetry": "/ws/telemetry"},
            "status": "/api/status",
            "status_stream": "/api/status/stream",
            "control": "/api/control",
            "ui_registry": "/api/ui/registry",
            "tasks": {
                "execute": "/api/tasks/execute",
                "executions": "/api/executions",
                "execution": "/api/execution/{exec_id}",
                "stop": "/api/execution/{exec_id}/stop"
            },
            "config": "/api/config",
            "serial": {"ports": "/api/serial/ports", "open": "/api/serial/open", "close": "/api/serial/close"},
            "calibration": {"get": "/api/calibration", "apply": "/api/calibration/apply", "run": "/api/calibration/run"},
            "visual": {"status": "/api/visual/status", "frame": "/api/visual/frame", "reset": "/api/visual/reset"}
        }
    }


@app.get("/api/status")
def api_status():
    # base status payload used by SSE and polling
    return {
        "robot": "simple_pump",
        "pump_running": _pump.is_running,
        "ml_per_sec": _pump.ml_per_sec,
        "ts": datetime.utcnow().isoformat(),
        "serial": _pump.serial_status(),
        "sensors": {"ml_per_sec": _pump.ml_per_sec, "usar_sensor_flujo": _use_sensor_flow},
    }


def _status_snapshot() -> Dict:
    """Build a richer status payload compatible with hub widgets and WS telemetry."""
    payload = api_status().copy()
    # include execution hint if any
    try:
        running = next((t for t in _runner.tasks.values() if t.status in ("running", "queued")), None)
    except Exception:
        running = None
    if running is not None:
        payload["progress"] = running.progress
        payload["execution_id"] = running.execution_id
        payload["exec_status"] = running.status
    # aliases for widget registry paths
    payload.setdefault("metrics", {})
    payload["metrics"]["flow_ml_s"] = payload.get("ml_per_sec")
    payload.setdefault("flow", {})
    payload["flow"]["current"] = payload.get("ml_per_sec")
    payload.setdefault("setpoints", {})
    # volume/flow targets are tracked on demand; leave empty by default
    return payload


@app.get("/api/protocols/list")
def api_list_protocols():
    """Lista protocolos disponibles con sus PARAMETERS para UI dinámica"""
    try:
        protocols_list = []
        # Listar protocolos en directorio
        available = Protocolo.listar(str(PROTOCOLS_DIR))
        
        for protocol_name in available:
            try:
                # Cargar cada protocolo
                proto = Protocolo(protocol_name, str(PROTOCOLS_DIR))
                meta = proto.cargar()
                
                # Intentar obtener PARAMETERS del protocolo
                parameters = {}
                if meta.get("tipo") == "gym" and proto.clase_protocolo:
                    # Clase Gym - buscar atributo PARAMETERS
                    parameters = getattr(proto.clase_protocolo, 'PARAMETERS', {})
                
                protocols_list.append({
                    "name": protocol_name,
                    "type": meta.get("tipo", "unknown"),
                    "parameters": parameters,
                    "has_parameters": bool(parameters)
                })
            except Exception as e:
                protocols_list.append({
                    "name": protocol_name,
                    "type": "error",
                    "parameters": {},
                    "has_parameters": False,
                    "error": str(e)
                })
        
        return {
            "protocols": protocols_list,
            "count": len(protocols_list)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
                

# Alias legacy
@app.get("/api/protocols")
def api_protocols_legacy():
    return api_list_protocols()


@app.get("/api/status/stream")
async def api_status_stream():
    async def _gen():
        while True:
            try:
                payload = _status_snapshot()
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception:
                yield f": keepalive\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(_gen(), media_type="text/event-stream")


class ExecuteIn(BaseModel):
    name: str = "Tarea sin nombre"
    protocol_name: str
    mode: Optional[str] = "async"
    params: Optional[Dict] = {}
    duration_seconds: Optional[float] = None
    timeout_seconds: Optional[float] = 25.0
    continuous: Optional[bool] = False
    auto_stop: Optional[bool] = True


@app.post("/api/tasks/execute")
def api_tasks_execute(data: ExecuteIn):
    try:
        # Validar existencia del protocolo
        if not Protocolo.existe(data.protocol_name, str(PROTOCOLS_DIR)):
             raise HTTPException(status_code=404, detail=f"Protocolo '{data.protocol_name}' no encontrado")

        # Preparar parámetros
        params = data.params or {}
        
        # Mapeo simple de parámetros comunes
        if data.duration_seconds:
            params["task_controlled"] = True
            params["task_duration"] = float(data.duration_seconds)
        
        if data.continuous:
            params["continuous_mode"] = True
            data.timeout_seconds = max(data.timeout_seconds or 25.0, 3600.0)

        # Crear definición de tarea
        task_def = task_executor.create_task_definition(
            name=data.name,
            protocol_name=data.protocol_name,
            duration_seconds=data.duration_seconds,
            timeout_seconds=data.timeout_seconds,
            params=params,
            auto_stop=data.auto_stop
        )

        if data.mode == "sync":
            result = task_executor.execute_task(task_def, ExecutionMode.SYNC)
            return {
                "status": "completed",
                "task_id": result.task_id,
                "execution_status": result.status.value,
                "duration": result.duration,
                "result": None,
                "error": result.error,
                "log": result.log
            }
        else:
            execution_id = task_executor.execute_task(task_def, ExecutionMode.ASYNC)
            return {
                "status": "executing",
                "execution_id": execution_id,
                "task_id": task_def.id,
                "estimated_duration": data.duration_seconds,
                "timeout_seconds": data.timeout_seconds
            }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/execution/{exec_id}")
def api_execution(exec_id: str):
    st = task_executor.get_task_status(exec_id)
    if not st:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "execution_id": exec_id,
        "status": st.status.value,
        "started_at": st.started_at,
        "ended_at": st.ended_at,
        "log": st.log,
        "progress": st.progress,
        "type": "task",
        "target_id": st.result.get("protocol_name") if isinstance(st.result, dict) else None
    }


@app.get("/api/executions")
def api_executions():
    # Listar activas
    active = task_executor.list_active_tasks()
    return {"executions": [
        {"execution_id": t.task_id, "status": t.status.value, "started_at": t.started_at} 
        for t in active
    ]}


@app.post("/api/execution/{exec_id}/stop")
def api_execution_stop(exec_id: str):
    if task_executor.stop_task(exec_id):
        return {"status": "stopped", "execution_id": exec_id}
    raise HTTPException(status_code=404, detail="not found or could not stop")


class ScheduleIn(BaseModel):
    name: str
    protocol_name: str
    schedule_type: str # once, interval, daily
    duration_seconds: float = 10.0
    params: Optional[Dict] = {}
    
    # Interval params
    interval_seconds: Optional[int] = 3600
    
    # Daily params
    hour: Optional[int] = 8
    minute: Optional[int] = 0

@app.get("/api/schedules/list")
def api_schedules_list():
    schedules = task_scheduler.list_schedules()
    return {
        "schedules": [
            {
                "task_id": s.task_id,
                "name": s.name,
                "protocol": s.protocol_name,
                "type": s.schedule_type.value,
                "next_execution": s.next_execution.isoformat() if s.next_execution else None,
                "last_execution": s.last_execution.isoformat() if s.last_execution else None,
                "active": s.active
            }
            for s in schedules
        ]
    }

@app.post("/api/schedules/create")
def api_schedules_create(data: ScheduleIn):
    try:
        if data.schedule_type == "daily":
            schedule = create_daily_schedule(
                name=data.name,
                protocol_name=data.protocol_name,
                hour=data.hour,
                minute=data.minute,
                duration_seconds=data.duration_seconds,
                params=data.params
            )
        elif data.schedule_type == "interval":
            schedule = create_interval_schedule(
                name=data.name,
                protocol_name=data.protocol_name,
                interval_seconds=data.interval_seconds,
                duration_seconds=data.duration_seconds,
                params=data.params
            )
        else:
            raise HTTPException(status_code=400, detail="Unsupported schedule type")
            
        task_id = task_scheduler.add_schedule(schedule)
        return {"status": "created", "task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/schedules/{task_id}/delete")
def api_schedules_delete(task_id: str):
    if task_scheduler.remove_schedule(task_id):
        return {"status": "deleted", "task_id": task_id}
    raise HTTPException(status_code=404, detail="Schedule not found")


# --------- Config & Serial endpoints (unificados con reloj) ---------
@app.get("/api/config")
def api_config():
    return {
        "id": "pump",
        "name": "Simple Pump",
        "kind": "pump",
        "ml_per_sec": _pump.ml_per_sec,
        "serial": _pump.serial_status(),
        "actuators": _actuators,
        "ui": {"visual_available": _viz is not None},
    }


# ---- UI registry (widgets) ----
@app.get("/api/ui/registry")
def api_ui_registry():
    """Return UI widget registry so UIs can build controls dynamically."""
    reg_path = (BASE_DIR / "static" / "components" / "registry" / "pump.json")
    try:
        return json.loads(reg_path.read_text(encoding="utf-8"))
    except Exception:
        # Fallback minimal
        return {"widgets": []}


@app.get("/api/serial/ports")
def api_serial_ports():
    out = []
    try:
        if list_ports is not None:
            for pinfo in list_ports.comports():
                out.append({"device": pinfo.device, "name": getattr(pinfo, 'name', '') or pinfo.device, "description": getattr(pinfo, 'description', '') or ''})
    except Exception:
        pass
    return {"ports": out}


class SerialOpenIn(BaseModel):
    port: str
    baud: Optional[int] = 115200


@app.post("/api/serial/open")
def api_serial_open(data: SerialOpenIn):
    ok = _pump.open_serial(data.port, int(data.baud or 115200))
    cfg = _load_config(); cfg.update({"serial_port": data.port, "baud": int(data.baud or 115200)})
    _save_config(cfg)
    return {"ok": ok, "serial": _pump.serial_status()}


@app.post("/api/serial/close")
def api_serial_close():
    _pump.close_serial()
    return {"ok": True, "serial": _pump.serial_status()}


class CalibApplyIn(BaseModel):
    ml_per_sec: float


@app.get("/api/calibration")
def api_calib_status():
    return {"ml_per_sec": _pump.ml_per_sec}


@app.post("/api/calibration/apply")
def api_calib_apply(data: CalibApplyIn):
    _pump.ml_per_sec = float(data.ml_per_sec)
    cfg = _load_config(); cfg.update({"ml_per_sec": _pump.ml_per_sec}); _save_config(cfg)
    return {"ok": True, "ml_per_sec": _pump.ml_per_sec}


class FlowApplyIn(BaseModel):
    ml_per_sec: float | None = None
    usar_sensor_flujo: bool | None = None


@app.post("/api/flow/apply")
def api_flow_apply(data: FlowApplyIn):
    global _use_sensor_flow
    if data.ml_per_sec is not None:
        _pump.ml_per_sec = float(data.ml_per_sec)
    if data.usar_sensor_flujo is not None:
        _use_sensor_flow = bool(data.usar_sensor_flujo)
    cfg = _load_config(); cfg.update({"ml_per_sec": _pump.ml_per_sec, "usar_sensor_flujo": _use_sensor_flow}); _save_config(cfg)
    return {"ok": True, "ml_per_sec": _pump.ml_per_sec, "usar_sensor_flujo": _use_sensor_flow}


class CalibRunIn(BaseModel):
    duration_seconds: float


@app.post("/api/calibration/run")
def api_calib_run(data: CalibRunIn):
    info = _runner.start_riego(volume_ml=None, duration_seconds=float(data.duration_seconds))
    return info.dict()


@app.get("/api/visual/status")
def api_visual_status():
    return {"available": _viz is not None}


@app.get("/api/visual/frame")
def api_visual_frame():
    if _viz is None:
        raise HTTPException(status_code=503, detail="visualizer unavailable")
    data = _viz.render_frame()
    if not data:
        raise HTTPException(status_code=503, detail="frame unavailable")
    return Response(content=data, media_type="image/jpeg")


@app.post("/api/visual/reset")
def api_visual_reset():
    if _viz is None:
        raise HTTPException(status_code=503, detail="visualizer unavailable")
    try:
        _viz.reset()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------- WebSockets: control + telemetry ----------------

def _apply_control_payload(data: Dict) -> Dict:
    """Apply a control payload. Aligns with reloj robot schema where possible.

    Supported fields:
      - setpoints.volumen_ml
      - flow.caudal_bomba_mls
      - usar_sensor_flujo (bool) either top-level or in flow
      - reset_volumen
    """
    global _use_sensor_flow
    ack: Dict[str, any] = {"ok": True}

    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid payload"}

    sp = data.get("setpoints") or {}
    flow = data.get("flow") or {}

    target_vol = sp.get("volumen_ml") if isinstance(sp, dict) else None
    target_flow = None
    if isinstance(flow, dict):
        target_flow = flow.get("caudal_bomba_mls") or flow.get("flow_ml_s") or flow.get("ml_per_sec")
        if "usar_sensor_flujo" in flow:
            _use_sensor_flow = bool(flow.get("usar_sensor_flujo"))
    # top-level override for sensor flag
    if "usar_sensor_flujo" in data:
        _use_sensor_flow = bool(data.get("usar_sensor_flujo"))

    # persist settings if changed
    dirty = False
    if target_flow is not None:
        try:
            _pump.ml_per_sec = float(target_flow)
            dirty = True
        except Exception:
            pass
    if dirty:
        cfg = _load_config(); cfg.update({"ml_per_sec": _pump.ml_per_sec, "usar_sensor_flujo": _use_sensor_flow}); _save_config(cfg)

    # reset volume hint (client-side in this simple robot)
    if data.get("reset_volumen"):
        ack["reset_volumen"] = True

    # Execute/stop logic: if flow > 0 and volume target provided → start; if flow==0 → stop
    try:
        flow_value = float(target_flow) if target_flow is not None else None
    except Exception:
        flow_value = None
    try:
        vol_value = float(target_vol) if target_vol is not None else None
    except Exception:
        vol_value = None

    if flow_value is not None and flow_value <= 0.0:
        _pump.stop()
        # mark running task stopped if any
        try:
            running = next((k for k, t in _runner.tasks.items() if t.status == "running"), None)
            if running:
                try:
                    _runner.stop(running)
                except Exception:
                    pass
        except Exception:
            pass
        ack["action"] = "stopped"
    elif flow_value is not None and flow_value > 0.0 and vol_value is not None and vol_value > 0.0:
        info = _runner.start_riego(volume_ml=vol_value, duration_seconds=None)
        ack["action"] = "started"
        ack["execution_id"] = info.execution_id
    else:
        # Only setpoints/settings updated
        ack["action"] = "updated"

    ack["status"] = _status_snapshot()
    return ack


@app.websocket("/ws/control")
async def ws_control(ws: WebSocket):
    await ws.accept()
    try:
        await ws.send_json({"type": "control_ready"})
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg or "{}")
            except Exception:
                data = {}
            if isinstance(data, dict) and data.get("type") == "ping":
                await ws.send_json({"type": "pong", "ts": datetime.utcnow().isoformat()})
                continue
            ack = _apply_control_payload(data if isinstance(data, dict) else {})
            await ws.send_json({"type": "control_ack", **ack})
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass


@app.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket):
    await ws.accept()
    try:
        await ws.send_json({"type": "telemetry_ready"})
        while True:
            await ws.send_json({"type": "telemetry", "status": _status_snapshot()})
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass


# HTTP control endpoint for hubs bridging
@app.post("/api/control")
def api_control(payload: Optional[Dict] = None):
    ack = _apply_control_payload(payload or {})
    return ack


if __name__ == "__main__":
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    import pathlib

    # Mount a simple static UI if available
    try:
        base = pathlib.Path(__file__).resolve().parent / "static"
        if base.exists():
            app.mount("/", StaticFiles(directory=str(base), html=True), name="ui")
    except Exception:
        pass

    port = int(os.environ.get("PUMP_HTTP_PORT", os.environ.get("PORT", "5010")))
    uvicorn.run("server_pump:app", host="0.0.0.0", port=port, reload=False)


