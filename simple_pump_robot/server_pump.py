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
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import RedirectResponse, StreamingResponse
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

PUMP_SERIAL = os.environ.get("PUMP_SERIAL")  # e.g., COM4 or /dev/ttyUSB0
ML_PER_SEC = float(os.environ.get("PUMP_ML_PER_SEC", "10.0"))

_pump = PumpController(PUMP_SERIAL, ML_PER_SEC)
_runner = TaskRunner(_pump)

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


@app.get("/")
def home():
    # Prefer simple UI when available, keep JSON fallback
    if STATIC_DIR.exists():
        return RedirectResponse(url="/ui/")
    return {"name": "simple-pump-robot", "status": "ok"}


@app.get("/api/status")
def api_status():
    # base status payload used by SSE and polling
    return {
        "robot": "simple_pump",
        "pump_running": _pump.is_running,
        "ml_per_sec": _pump.ml_per_sec,
        "ts": datetime.utcnow().isoformat(),
        "serial": _pump.serial_status(),
        "sensors": {"ml_per_sec": _pump.ml_per_sec},
    }


@app.get("/api/protocols")
def api_protocols():
    """Describe available protocols and their parameters for dynamic UIs."""
    return {
        "protocols": [
            {
                "id": "riego_basico",
                "label": "Riego básico",
                "params": [
                    {"name": "volume_ml", "type": "number", "unit": "ml", "min": 0, "step": 1, "default": 50, "required": False},
                    {"name": "duration_seconds", "type": "number", "unit": "s", "min": 0, "step": 1, "default": None, "required": False}
                ]
            }
        ]
    }


@app.get("/api/status/stream")
async def api_status_stream():
    async def _gen():
        while True:
            try:
                payload = api_status()
                # include a hint about current execution progress if any
                running = None
                try:
                    running = next((t for t in _runner.tasks.values() if t.status in ("running", "queued")), None)
                except Exception:
                    running = None
                if running is not None:
                    payload["progress"] = running.progress
                    payload["execution_id"] = running.execution_id
                    payload["exec_status"] = running.status
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception:
                # On error, still keep the stream alive with a heartbeat
                yield f": keepalive\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(_gen(), media_type="text/event-stream")


class ExecuteIn(BaseModel):
    name: str
    protocol_name: str
    mode: Optional[str] = "async"
    params: Optional[Dict[str, float]] = None
    duration_seconds: Optional[float] = None


@app.post("/api/tasks/execute")
def api_tasks_execute(data: ExecuteIn):
    prot = (data.protocol_name or "").lower()
    p = data.params or {}
    if prot not in ("riego_basico", "riego", "pump"):
        # accept but no-op
        info = ExecInfo(execution_id=str(uuid.uuid4())[:8], status="completed", started_at=datetime.utcnow().isoformat(), ended_at=datetime.utcnow().isoformat())
        _runner.tasks[info.execution_id] = info
        return info.dict()
    vol = p.get("volume_ml")
    dur = data.duration_seconds
    info = _runner.start_riego(volume_ml=vol, duration_seconds=dur)
    return info.dict()


@app.get("/api/execution/{exec_id}")
def api_execution(exec_id: str):
    info = _runner.tasks.get(exec_id)
    if not info:
        raise HTTPException(status_code=404, detail="not found")
    return info.dict()


@app.get("/api/executions")
def api_executions():
    return {"executions": [t.dict() for t in _runner.tasks.values()]}


@app.post("/api/execution/{exec_id}/stop")
def api_execution_stop(exec_id: str):
    try:
        info = _runner.stop(exec_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    return info.dict()


# --------- Config & Serial endpoints (unificados con reloj) ---------
@app.get("/api/config")
def api_config():
    return {
        "id": "pump",
        "name": "Simple Pump",
        "kind": "pump",
        "ml_per_sec": _pump.ml_per_sec,
        "serial": _pump.serial_status(),
        "ui": {"visual_available": _viz is not None},
    }


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


