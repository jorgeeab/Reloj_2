from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any
from contextlib import asynccontextmanager
import os
import sys
import subprocess

try:
    # when run as module
    from .models import Store, Robot, Plant
except Exception:
    # fallback when executed as script
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from hub_service.models import Store, Robot, Plant  # type: ignore


app = FastAPI(title="Reloj Hub Service", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = Store.load()

# Static UI under /hub
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/hub", StaticFiles(directory=str(STATIC_DIR), html=True), name="hub")

# Robots catalog file (preconfigurable list)
DATA_DIR = Path(__file__).resolve().parent / "data"
CATALOG_FILE = DATA_DIR / "robots_catalog.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)
if not CATALOG_FILE.exists():
    try:
        default_catalog = {
            "robots": [
                {"id": "reloj-local", "name": "Reloj Local", "base_url": "http://localhost:5005", "kind": "reloj"}
            ]
        }
        CATALOG_FILE.write_text(json.dumps(default_catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# Lifespan (reemplaza on_event deprecated)
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    poll_task = asyncio.create_task(poll_robots_loop())
    for rb in store.robots.values():
        _start_sse_task(rb)
    try:
        yield
    finally:
        try:
            poll_task.cancel()
        except Exception:
            pass
        for tid, t in list(_sse_tasks.items()):
            try:
                t.cancel()
            except Exception:
                pass

# Activar lifespan handler
app.router.lifespan_context = app_lifespan


class RobotIn(BaseModel):
    id: str
    name: str
    base_url: str
    kind: Optional[str] = "hardware"
    api_key: Optional[str] = None


class PlantIn(BaseModel):
    id_planta: int
    nombre: str
    fecha_plantacion: str
    angulo_h: float
    angulo_y: float
    longitud_slider: float
    velocidad_agua: float
    era: str


class AssignIn(BaseModel):
    robot_id: str
    plant_era: str
    plant_id: int
    action: str  # "move" | "water"
    params: Optional[Dict] = None


class ExecuteIn(BaseModel):
    """Ejecuta una tarea custom enviando el payload directamente al robot.
    task: debe incluir al menos name, protocol_name, params y opcionalmente
    duration_seconds, timeout_seconds, mode, etc.
    """
    robot_id: str
    task: Dict[str, Any]


class StartRobotIn(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    port: Optional[int] = 5005
    kind: Optional[str] = "reloj"


class StopLocalIn(BaseModel):
    force: Optional[bool] = False


ws_clients: List[WebSocket] = []
_poll_lock = asyncio.Lock()
_sse_tasks: Dict[str, asyncio.Task] = {}
_local_robot_proc: Optional[subprocess.Popen] = None
_local_robot_id: Optional[str] = None


async def broadcast(payload: Dict):
    if not ws_clients:
        return
    msg = json.dumps(payload, ensure_ascii=False)
    pending = []
    for ws in list(ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            pending.append(ws)
    for ws in pending:
        try:
            ws_clients.remove(ws)
        except ValueError:
            pass


async def poll_robots_loop():
    while True:
        try:
            if store.robots:
                async with httpx.AsyncClient(timeout=0.8) as client:
                    tasks = []
                    for rb in store.robots.values():
                        url = rb.base_url.rstrip("/") + "/api/status"
                        headers = {"X-API-Key": rb.api_key} if rb.api_key else None
                        tasks.append(client.get(url, headers=headers))
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                i = 0
                for rb in list(store.robots.values()):
                    res = results[i]; i += 1
                    status = {"ok": False}
                    if isinstance(res, Exception):
                        status = {"ok": False, "error": str(res)}
                    else:
                        if res.status_code == 200:
                            try:
                                status = {"ok": True, "data": res.json()}
                            except Exception:
                                status = {"ok": True, "raw": res.text}
                        else:
                            status = {"ok": False, "status": res.status_code}
                    store.last_robot_status[rb.id] = status
                await broadcast({
                    "type": "robots_status",
                    "ts": datetime.utcnow().isoformat(),
                    "robots": [
                        {
                            "id": rb.id,
                            "name": rb.name,
                            "base_url": rb.base_url,
                            "kind": rb.kind,
                            "status": store.last_robot_status.get(rb.id, {"ok": False}),
                            "runtime": _robot_runtime_flag(rb.id),
                        }
                        for rb in store.robots.values()
                    ]
                })
            # also poll tasks status tracked by the hub
            await _poll_tasks_status()
        except Exception:
            pass
        await asyncio.sleep(0.5)  # ~2 Hz; subir si quieres más rápido


async def _poll_tasks_status():
    if not store.tasks:
        return
    async with _poll_lock:
        # copy tasks to iterate
        items = list(store.tasks)
        async with httpx.AsyncClient(timeout=1.5) as client:
            for t in items:
                if t.get("status") in ("completed", "stopped", "error"):
                    continue
                rb = store.robots.get(t.get("robot_id") or "")
                if not rb:
                    continue
                eid = t.get("execution_id")
                if not eid:
                    continue
                url = rb.base_url.rstrip("/") + f"/api/execution/{eid}"
                headers = {"X-API-Key": rb.api_key} if rb.api_key else None
                try:
                    res = await client.get(url, headers=headers)
                    if res.status_code == 200:
                        rj = res.json()
                        t["status"] = rj.get("status") or t.get("status")
                        t["ended_at"] = rj.get("ended_at") or t.get("ended_at")
                    else:
                        t["status"] = t.get("status") or "unknown"
                except Exception:
                    t["status"] = t.get("status") or "unknown"
        # persist and broadcast
        store.save()
        await broadcast({"type": "tasks_update", "tasks": store.tasks})


# (startup manejado por lifespan)


def _start_sse_task(rb: Robot) -> None:
    if rb.id in _sse_tasks and not _sse_tasks[rb.id].done():
        return
    _sse_tasks[rb.id] = asyncio.create_task(_sse_loop(rb))


def _stop_sse_task(robot_id: str) -> None:
    t = _sse_tasks.pop(robot_id, None)
    if t and not t.done():
        t.cancel()


def _proc_alive(proc: Optional[subprocess.Popen]) -> bool:
    return proc is not None and proc.poll() is None


def _robot_runtime_flag(robot_id: str) -> bool:
    return bool(_local_robot_id and robot_id == _local_robot_id and _proc_alive(_local_robot_proc))


async def _sse_loop(rb: Robot):
    url = rb.base_url.rstrip("/") + "/api/status/stream"
    headers = {"X-API-Key": rb.api_key} if rb.api_key else None
    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url, headers=headers) as r:
                    if r.status_code != 200:
                        await asyncio.sleep(1.0)
                        continue
                    data_buf: Optional[str] = None
                    async for line in r.aiter_lines():
                        if line is None:
                            continue
                        s = line.strip()
                        if not s:
                            if data_buf:
                                try:
                                    js = json.loads(data_buf)
                                    store.last_robot_status[rb.id] = {"ok": True, "data": js}
                                    await broadcast({
                                        "type": "robots_status",
                                        "ts": datetime.utcnow().isoformat(),
                                        "robots": [
                                            {
                                                "id": rb.id,
                                                "name": rb.name,
                                                "base_url": rb.base_url,
                                                "kind": rb.kind,
                                                "status": store.last_robot_status.get(rb.id, {"ok": False}),
                                                "runtime": _robot_runtime_flag(rb.id),
                                            }
                                        ]
                                    })
                                except Exception:
                                    pass
                                data_buf = None
                            continue
                        if s.startswith(":"):
                            # comentario/heartbeat
                            continue
                        if s.startswith("data:"):
                            data_buf = s[len("data:"):].strip()
                        # ignorar otros campos SSE (event:, id:, retry:)
        except asyncio.CancelledError:
            break
        except Exception:
            # Reintento con backoff breve
            await asyncio.sleep(1.0)


@app.websocket("/ws")
async def websocket_feed(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    try:
        # send initial snapshot
        await broadcast({
            "type": "snapshot",
            "plants": list(store.plants.values()),
            "robots": [r.__dict__ for r in store.robots.values()],
            "tasks": store.tasks,
        })
        # keep connection alive without requiring client messages
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            ws_clients.remove(ws)
        except ValueError:
            pass


@app.get("/robots")
def list_robots():
    out = []
    for rb in store.robots.values():
        payload = {**rb.__dict__}
        payload["status"] = store.last_robot_status.get(rb.id, {"ok": False})
        payload["runtime"] = _robot_runtime_flag(rb.id)
        out.append(payload)
    return {"robots": out}


@app.post("/robots")
def add_robot(data: RobotIn):
    rb = Robot(**data.dict())
    store.add_robot(rb)
    store.save()
    # iniciar SSE para este robot
    _start_sse_task(rb)
    return {"status": "ok", "robot": rb.__dict__}


@app.delete("/robots/{robot_id}")
def del_robot(robot_id: str):
    ok = store.remove_robot(robot_id)
    store.save()
    _stop_sse_task(robot_id)
    return {"status": "ok" if ok else "not_found"}


@app.post("/robots/{robot_id}/control")
async def robot_control(robot_id: str, payload: Optional[Dict[str, Any]] = Body(default=None)):
    rb = store.robots.get(robot_id)
    if not rb:
        raise HTTPException(status_code=404, detail="robot not found")
    base = rb.base_url.rstrip("/")
    headers = {"X-API-Key": rb.api_key} if rb.api_key else None
    data = payload or {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            res = await client.post(base + "/api/control", json=data, headers=headers)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"control proxy error: {exc}") from exc
    try:
        reply = res.json()
    except Exception:
        reply = {"raw": res.text}
    if res.status_code >= 300:
        raise HTTPException(status_code=res.status_code, detail={"robot_response": reply})
    return {"status": "forwarded", "robot_id": rb.id, "robot_response": reply}


@app.get("/plants")
def get_plants():
    return {"plants": [p.__dict__ for p in store.plants.values()]}


@app.post("/plants")
def create_or_update_plant(p: PlantIn):
    plant = Plant(**p.dict())
    store.add_plant(plant)
    store.save()
    return {"status": "ok", "plant": plant.__dict__}


@app.delete("/plants/{era}/{plant_id}")
def delete_plant(era: str, plant_id: int):
    key = store.key_for_plant(era, plant_id)
    ok = store.plants.pop(key, None) is not None
    store.save()
    return {"status": "ok" if ok else "not_found"}


def _map_plant_to_targets(plant: Plant) -> Dict:
    # Simple mapping: longitud_slider -> x_mm, angulo_h -> a_deg
    return {
        "x_mm": float(plant.longitud_slider),
        "a_deg": float(plant.angulo_h),
    }


@app.post("/assign")
async def assign_task(data: AssignIn):
    rb = store.robots.get(data.robot_id)
    if not rb:
        raise HTTPException(status_code=404, detail="robot not found")
    plant = store.get_plant(data.plant_era, data.plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail="plant not found")

    base = rb.base_url.rstrip("/")
    headers = {"X-API-Key": rb.api_key} if rb.api_key else None
    params = _map_plant_to_targets(plant)
    extra = data.params or {}
    payload = {
        "name": f"{data.action}:{plant.nombre}",
        "protocol_name": "ir_posicion" if data.action == "move" else "riego_basico",
        "duration_seconds": float(extra.get("duration_seconds", 10.0)),
        "timeout_seconds": float(extra.get("timeout_seconds", 25.0)),
        "mode": "async",
        "params": {**params, **{k: v for k, v in extra.items() if k not in ("duration_seconds", "timeout_seconds")}},
    }
    # riego: permitir volume_ml
    if data.action == "water" and "volume_ml" in extra:
        payload["params"]["volume_ml"] = float(extra["volume_ml"])  # map UI -> robot

    async with httpx.AsyncClient(timeout=5.0) as client:
        url = base + "/api/tasks/execute"
        res = await client.post(url, json=payload, headers=headers)
        if res.status_code >= 300:
            raise HTTPException(status_code=res.status_code, detail=res.text)
        rj = res.json()
        # record hub task entry
        task_rec = {
            "id": f"t_{int(datetime.utcnow().timestamp()*1000)}",
            "robot_id": rb.id,
            "plant_era": plant.era,
            "plant_id": plant.id_planta,
            "action": data.action,
            "params": payload.get("params") or {},
            "execution_id": rj.get("execution_id") or rj.get("task_id"),
            "status": rj.get("status") or "executing",
            "started_at": rj.get("started_at") or datetime.utcnow().isoformat(),
        }
        store.tasks.insert(0, task_rec)
        store.save()
        await broadcast({"type": "task_added", "task": task_rec})
        return {"status": "ok", "task": task_rec, "robot_reply": rj}


@app.get("/tasks")
def list_tasks():
    return {"tasks": store.tasks}


@app.post("/execute")
async def execute_custom(data: ExecuteIn):
    """Proxy para ejecutar tareas personalizadas en el robot seleccionado.
    Registra la tarea en el hub para poder seguir su estado.
    """
    rb = store.robots.get(data.robot_id)
    if not rb:
        raise HTTPException(status_code=404, detail="robot not found")

    base = rb.base_url.rstrip("/")
    headers = {"X-API-Key": rb.api_key} if rb.api_key else None
    payload = dict(data.task or {})
    # Defaults razonables
    payload.setdefault("mode", "async")
    payload.setdefault("timeout_seconds", 30.0)

    async with httpx.AsyncClient(timeout=5.0) as client:
        url = base + "/api/tasks/execute"
        res = await client.post(url, json=payload, headers=headers)
        if res.status_code >= 300:
            raise HTTPException(status_code=res.status_code, detail=res.text)
        rj = res.json()
        task_rec = {
            "id": f"t_{int(datetime.utcnow().timestamp()*1000)}",
            "robot_id": rb.id,
            "plant_era": None,
            "plant_id": None,
            "action": "custom",
            "params": payload.get("params") or {},
            "execution_id": rj.get("execution_id") or rj.get("task_id"),
            "status": rj.get("status") or "executing",
            "started_at": rj.get("started_at") or datetime.utcnow().isoformat(),
        }
        store.tasks.insert(0, task_rec)
        store.save()
        await broadcast({"type": "task_added", "task": task_rec})
        return {"status": "ok", "task": task_rec, "robot_reply": rj}


class StopIn(BaseModel):
    robot_id: str
    execution_id: str


@app.post("/tasks/stop")
async def stop_task(data: StopIn):
    rb = store.robots.get(data.robot_id)
    if not rb:
        raise HTTPException(status_code=404, detail="robot not found")
    url = rb.base_url.rstrip("/") + f"/api/execution/{data.execution_id}/stop"
    headers = {"X-API-Key": rb.api_key} if rb.api_key else None
    async with httpx.AsyncClient(timeout=5.0) as client:
        res = await client.post(url, headers=headers)
        if res.status_code >= 300:
            raise HTTPException(status_code=res.status_code, detail=res.text)
    # update local record
    for t in store.tasks:
        if t.get("execution_id") == data.execution_id and t.get("robot_id") == data.robot_id:
            t["status"] = "stopped"
            t["ended_at"] = datetime.utcnow().isoformat()
    store.save()
    await broadcast({"type": "tasks_update", "tasks": store.tasks})
    return {"status": "stopped"}


@app.get("/")
def root():
    # Redirige a la nueva UI simplificada
    return RedirectResponse(url="/hub/index.html")


# ======================= ENDPOINTS DE CONTROL PARA IA =======================
# Estos endpoints permiten controlar todos los robots de forma unificada


class MoveRobotIn(BaseModel):
    """Mover robot a una posición"""
    robot_id: str
    x_mm: Optional[float] = None
    a_deg: Optional[float] = None
    duration_seconds: Optional[float] = 10.0


class WaterIn(BaseModel):
    """Regar con volumen específico"""
    robot_id: str
    volume_ml: float
    duration_seconds: Optional[float] = None


class HomeIn(BaseModel):
    """Enviar robot a home"""
    robot_id: str


class StopRobotIn(BaseModel):
    """Detener robot"""
    robot_id: str


@app.post("/ai/move")
async def ai_move_robot(data: MoveRobotIn):
    """
    🤖 Endpoint para IA: Mover robot a posición específica
    
    Ejemplo:
    {
        "robot_id": "reloj",
        "x_mm": 120.5,
        "a_deg": 45.0,
        "duration_seconds": 10.0
    }
    """
    rb = store.robots.get(data.robot_id)
    if not rb:
        raise HTTPException(status_code=404, detail=f"Robot {data.robot_id} no encontrado")
    
    # Construir payload para el robot
    payload = {
        "name": f"AI_Move_{data.robot_id}",
        "protocol_name": "ir_posicion",
        "duration_seconds": data.duration_seconds or 10.0,
        "mode": "async",
        "params": {}
    }
    
    if data.x_mm is not None:
        payload["params"]["x_mm"] = float(data.x_mm)
    if data.a_deg is not None:
        payload["params"]["a_deg"] = float(data.a_deg)
    
    # Enviar al robot
    base = rb.base_url.rstrip("/")
    headers = {"X-API-Key": rb.api_key} if rb.api_key else None
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        url = base + "/api/tasks/execute"
        res = await client.post(url, json=payload, headers=headers)
        if res.status_code >= 300:
            raise HTTPException(status_code=res.status_code, detail=res.text)
        rj = res.json()
        
        return {
            "status": "ok",
            "action": "move",
            "robot_id": data.robot_id,
            "target": {"x_mm": data.x_mm, "a_deg": data.a_deg},
            "execution_id": rj.get("execution_id"),
            "robot_response": rj
        }


@app.post("/ai/water")
async def ai_water(data: WaterIn):
    """
    🤖 Endpoint para IA: Regar con volumen específico
    
    Ejemplo:
    {
        "robot_id": "reloj",
        "volume_ml": 150.0,
        "duration_seconds": 15.0
    }
    """
    rb = store.robots.get(data.robot_id)
    if not rb:
        raise HTTPException(status_code=404, detail=f"Robot {data.robot_id} no encontrado")
    
    payload = {
        "name": f"AI_Water_{data.robot_id}",
        "protocol_name": "riego_basico",
        "duration_seconds": data.duration_seconds or (data.volume_ml / 10.0),  # ~10ml/s
        "mode": "async",
        "params": {
            "volume_ml": float(data.volume_ml)
        }
    }
    
    base = rb.base_url.rstrip("/")
    headers = {"X-API-Key": rb.api_key} if rb.api_key else None
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        url = base + "/api/tasks/execute"
        res = await client.post(url, json=payload, headers=headers)
        if res.status_code >= 300:
            raise HTTPException(status_code=res.status_code, detail=res.text)
        rj = res.json()
        
        return {
            "status": "ok",
            "action": "water",
            "robot_id": data.robot_id,
            "volume_ml": data.volume_ml,
            "execution_id": rj.get("execution_id"),
            "robot_response": rj
        }


@app.post("/ai/home")
async def ai_home(data: HomeIn):
    """
    🤖 Endpoint para IA: Enviar robot a posición home
    
    Ejemplo:
    {
        "robot_id": "reloj"
    }
    """
    rb = store.robots.get(data.robot_id)
    if not rb:
        raise HTTPException(status_code=404, detail=f"Robot {data.robot_id} no encontrado")
    
    base = rb.base_url.rstrip("/")
    headers = {"X-API-Key": rb.api_key} if rb.api_key else None
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        url = base + "/api/control"
        res = await client.post(url, json={"home": True}, headers=headers)
        if res.status_code >= 300:
            raise HTTPException(status_code=res.status_code, detail=res.text)
        
        try:
            rj = res.json()
        except:
            rj = {"raw": res.text}
        
        return {
            "status": "ok",
            "action": "home",
            "robot_id": data.robot_id,
            "robot_response": rj
        }


@app.post("/ai/stop")
async def ai_stop_robot(data: StopRobotIn):
    """
    🤖 Endpoint para IA: Detener robot inmediatamente
    
    Ejemplo:
    {
        "robot_id": "reloj"
    }
    """
    rb = store.robots.get(data.robot_id)
    if not rb:
        raise HTTPException(status_code=404, detail=f"Robot {data.robot_id} no encontrado")
    
    base = rb.base_url.rstrip("/")
    headers = {"X-API-Key": rb.api_key} if rb.api_key else None
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        url = base + "/api/control"
        res = await client.post(url, json={"stop": True}, headers=headers)
        if res.status_code >= 300:
            raise HTTPException(status_code=res.status_code, detail=res.text)
        
        try:
            rj = res.json()
        except:
            rj = {"raw": res.text}
        
        return {
            "status": "ok",
            "action": "stop",
            "robot_id": data.robot_id,
            "robot_response": rj
        }


@app.get("/ai/status/{robot_id}")
async def ai_get_robot_status(robot_id: str):
    """
    🤖 Endpoint para IA: Obtener estado actual del robot
    
    Retorna posición, volumen, límites, conexión serial, etc.
    """
    rb = store.robots.get(robot_id)
    if not rb:
        raise HTTPException(status_code=404, detail=f"Robot {robot_id} no encontrado")
    
    # Obtener status del caché
    status = store.last_robot_status.get(robot_id, {})
    
    return {
        "robot_id": robot_id,
        "robot_name": rb.name,
        "base_url": rb.base_url,
        "online": status.get("ok", False),
        "status": status.get("data", {}),
        "runtime": _robot_runtime_flag(robot_id)
    }


@app.get("/ai/robots/list")
def ai_list_robots():
    """
    🤖 Endpoint para IA: Listar todos los robots disponibles
    
    Retorna lista simple con id, nombre, tipo y estado
    """
    robots = []
    for rb in store.robots.values():
        status = store.last_robot_status.get(rb.id, {})
        robots.append({
            "id": rb.id,
            "name": rb.name,
            "kind": rb.kind,
            "online": status.get("ok", False),
            "runtime": _robot_runtime_flag(rb.id),
            "base_url": rb.base_url
        })
    
    return {
        "robots": robots,
        "total": len(robots),
        "online": sum(1 for r in robots if r["online"])
    }


@app.get("/ai/plants/list")
def ai_list_plants():
    """
    🤖 Endpoint para IA: Listar todas las plantas
    
    Retorna id, nombre, era y posición
    """
    plants = []
    for plant in store.plants.values():
        plants.append({
            "id": plant.id_planta,
            "era": plant.era,
            "name": plant.nombre,
            "position": {
                "x_mm": plant.longitud_slider,
                "a_deg": plant.angulo_h,
                "a_y_deg": plant.angulo_y
            },
            "water_speed": plant.velocidad_agua,
            "planted_date": plant.fecha_plantacion
        })
    
    return {
        "plants": plants,
        "total": len(plants)
    }


@app.post("/ai/goto_plant")
async def ai_goto_plant(robot_id: str, era: str, plant_id: int, duration_seconds: float = 10.0):
    """
    🤖 Endpoint para IA: Mover robot a posición de una planta
    
    Parámetros query:
    - robot_id: ID del robot
    - era: Era de la planta
    - plant_id: ID de la planta
    - duration_seconds: Duración del movimiento (opcional)
    """
    rb = store.robots.get(robot_id)
    if not rb:
        raise HTTPException(status_code=404, detail=f"Robot {robot_id} no encontrado")
    
    plant = store.get_plant(era, plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Planta {era}:{plant_id} no encontrada")
    
    # Usar el endpoint de move con los datos de la planta
    move_data = MoveRobotIn(
        robot_id=robot_id,
        x_mm=plant.longitud_slider,
        a_deg=plant.angulo_h,
        duration_seconds=duration_seconds
    )
    
    result = await ai_move_robot(move_data)
    result["plant"] = {
        "id": plant.id_planta,
        "era": plant.era,
        "name": plant.nombre
    }
    
    return result


# ======================= FIN ENDPOINTS PARA IA =======================

# ----------------------- Regimens & Activities & Calendar -----------------------
class RegimenIn(BaseModel):
    id_regimen: int
    planta_id: int
    era: str
    nombre: str
    descripcion: str
    frecuencia: float
    unidad_frecuencia: str
    fecha_inicio: str
    fecha_fin: Optional[str] = None
    tasks: Optional[List[Dict]] = None


@app.post("/regimens")
def add_regimen(data: RegimenIn):
    # validate plant exists
    if not store.get_plant(data.era, data.planta_id):
        raise HTTPException(status_code=404, detail="plant not found")
    from .models import Regimen
    payload = data.dict()
    tasks = payload.pop("tasks", None) or []
    r = Regimen(**payload)
    r.tasks = tasks
    # replace existing with same id
    store.regimens = [x for x in store.regimens if x.id_regimen != r.id_regimen]
    store.regimens.append(r)
    store.save()
    return {"status": "ok", "regimen": r.__dict__}


@app.get("/regimens")
def list_regimens():
    return {"regimens": [r.__dict__ for r in store.regimens]}


@app.get("/regimens/{regimen_id}/tasks")
def list_regimen_tasks(regimen_id: int):
    r = next((x for x in store.regimens if x.id_regimen == regimen_id), None)
    if not r:
        raise HTTPException(status_code=404, detail="regimen not found")
    return {"tasks": r.tasks}


class RegimenTaskIn(BaseModel):
    tarea: str
    numero_dia: int
    hora: str  # HH:MM
    tiempo_s: Optional[float] = None
    magnitud: Optional[float] = None
    unidades: Optional[str] = None
    detalles: Optional[str] = None


@app.post("/regimens/{regimen_id}/tasks")
def add_regimen_task(regimen_id: int, data: RegimenTaskIn):
    r = next((x for x in store.regimens if x.id_regimen == regimen_id), None)
    if not r:
        raise HTTPException(status_code=404, detail="regimen not found")
    task = data.dict()
    r.tasks.append(task)
    store.save()
    return {"status": "ok", "task": task, "count": len(r.tasks)}


@app.delete("/regimens/{regimen_id}/tasks/{index}")
def delete_regimen_task(regimen_id: int, index: int):
    r = next((x for x in store.regimens if x.id_regimen == regimen_id), None)
    if not r:
        raise HTTPException(status_code=404, detail="regimen not found")
    if index < 0 or index >= len(r.tasks):
        raise HTTPException(status_code=404, detail="task index out of range")
    removed = r.tasks.pop(index)
    store.save()
    return {"status": "ok", "removed": removed}


class ActivityIn(BaseModel):
    planta_id: int
    era: str
    id_regimen: int
    fecha: str
    tipo_actividad: str
    detalles: str


@app.post("/activities")
def add_activity(data: ActivityIn):
    from .models import Activity
    # basic validation
    if not store.get_plant(data.era, data.planta_id):
        raise HTTPException(status_code=404, detail="plant not found")
    if not any(r.id_regimen == data.id_regimen for r in store.regimens):
        raise HTTPException(status_code=404, detail="regimen not found")
    a = Activity(**data.dict(), completada=False)
    store.activities.append(a)
    store.save()
    return {"status": "ok", "activity": a.__dict__}


@app.get("/activities")
def list_activities():
    return {"activities": [a.__dict__ for a in store.activities]}


class GenerateIn(BaseModel):
    days_ahead: Optional[int] = 7


@app.post("/activities/generate")
def generate_activities(data: GenerateIn):
    # mirror of your PlantasManager.generar_actividades but simplified
    from datetime import datetime, timedelta
    msgs: List[str] = []
    existing = {(a.planta_id, a.era, a.id_regimen, a.fecha, a.tipo_actividad) for a in store.activities}
    end_limit = datetime.utcnow() + timedelta(days=int(data.days_ahead or 7))

    for r in store.regimens:
        # validate plant
        p = store.get_plant(r.era, r.planta_id)
        if not p:
            continue
        try:
            start = datetime.fromisoformat(r.fecha_inicio)
        except Exception:
            continue
        try:
            r_end = datetime.fromisoformat(r.fecha_fin) if r.fecha_fin else end_limit
        except Exception:
            r_end = end_limit
        # Si hay tareas definidas en el régimen: úsalas como plantilla calendarizada
        if r.tasks:
            for idx, t in enumerate(r.tasks):
                try:
                    d_off = int(t.get("numero_dia") or 0)
                    hora = str(t.get("hora") or "00:00")
                    hh, mm = [int(x) for x in hora.split(":")[:2]]
                except Exception:
                    continue
                cur = (start + timedelta(days=d_off)).replace(hour=hh, minute=mm, second=0, microsecond=0)
                if cur > end_limit or cur > r_end:
                    continue
                ts = cur.isoformat(timespec='minutes')
                tarea = t.get("tarea") or r.nombre
                key = (r.planta_id, r.era, r.id_regimen, ts, tarea)
                if key not in existing:
                    from .models import Activity
                    a = Activity(
                        planta_id=r.planta_id,
                        era=r.era,
                        id_regimen=r.id_regimen,
                        fecha=ts,
                        tipo_actividad=tarea,
                        detalles=t.get("detalles") or r.descripcion,
                        completada=False,
                        magnitud=(t.get("magnitud") if t.get("magnitud") is not None else None),
                        unidades=(t.get("unidades") if t.get("unidades") is not None else None),
                    )
                    store.activities.append(a)
                    existing.add(key)
                    msgs.append(f"+ {tarea} {ts} planta {r.planta_id} ({r.era})")
        else:
            # Fallback: generar por frecuencia
            cur = start
            step = timedelta(minutes=r.frecuencia) if (r.unidad_frecuencia or "").lower().startswith("min") else timedelta(days=r.frecuencia)
            while cur <= min(r_end, end_limit):
                ts = cur.isoformat(timespec='minutes')
                key = (r.planta_id, r.era, r.id_regimen, ts, r.nombre)
                if key not in existing:
                    from .models import Activity
                    a = Activity(planta_id=r.planta_id, era=r.era, id_regimen=r.id_regimen, fecha=ts, tipo_actividad=r.nombre, detalles=r.descripcion, completada=False)
                    store.activities.append(a)
                    existing.add(key)
                    msgs.append(f"+ {r.nombre} {ts} planta {r.planta_id} ({r.era})")
                cur += step
    store.save()
    return {"status": "ok", "messages": msgs, "count": len(msgs)}


@app.get("/calendar/events")
def calendar_events():
    # Flatten activities into events
    events = []
    for a in store.activities:
        mm = f" {a.magnitud} {a.unidades}" if a.magnitud is not None and a.unidades else ""
        title = f"{a.tipo_actividad}{mm} - {a.era}:{a.planta_id}"
        events.append({"title": title, "start": a.fecha, "meta": a.__dict__})
    return {"events": events}


@app.get("/map/plants")
def map_plants():
    import math
    out = []
    for p in store.plants.values():
        angle_rad = math.radians(float(p.angulo_h))
        x = float(p.longitud_slider) * math.cos(angle_rad)
        y = float(p.longitud_slider) * math.sin(angle_rad)
        out.append({
            "era": p.era,
            "id_planta": p.id_planta,
            "nombre": p.nombre,
            "x": round(x, 2),
            "y": round(y, 2),
            "a_deg": p.angulo_h,
            "len": p.longitud_slider,
        })
    return {"plants": out}


@app.get("/eras")
def list_eras():
    eras = sorted(set(p.era for p in store.plants.values()))
    return {"eras": eras}


@app.get("/robot-types")
def list_robot_types():
    """Enumera tipos de robot disponibles inspeccionando carpetas 'robot_*'.
    Esto permite agregar nuevos tipos creando una nueva carpeta en el repo.
    """
    types: List[Dict[str, Any]] = []
    root = Path(__file__).resolve().parent.parent
    try:
        for p in root.iterdir():
            if not p.is_dir():
                continue
            name = p.name
            if not name.startswith("robot_"):
                continue
            typ = name.split("_", 1)[1] or name
            item: Dict[str, Any] = {"id": typ, "folder": name}
            meta = p / "metadata.json"
            if meta.exists():
                try:
                    item.update(json.loads(meta.read_text(encoding="utf-8")))
                except Exception:
                    pass
            types.append(item)
    except Exception:
        pass
    return {"types": types}


@app.get("/robots/catalog")
def robots_catalog():
    try:
        raw = json.loads(CATALOG_FILE.read_text(encoding="utf-8") or "{}")
    except Exception:
        raw = {}
    robots = raw.get("robots") or []
    # validate shape minimally
    out = []
    for r in robots:
        if not isinstance(r, dict):
            continue
        if not r.get("id") or not r.get("base_url"):
            continue
        out.append({
            "id": r.get("id"),
            "name": r.get("name"),
            "base_url": r.get("base_url"),
            "kind": r.get("kind") or "hardware",
            "api_key": r.get("api_key"),
        })
    return {"robots": out}


class ImportFromCatalogIn(BaseModel):
    id: str


@app.post("/robots/catalog/import")
def robots_catalog_import(data: ImportFromCatalogIn):
    try:
        raw = json.loads(CATALOG_FILE.read_text(encoding="utf-8") or "{}")
    except Exception:
        raw = {}
    robots = raw.get("robots") or []
    itm = next((r for r in robots if isinstance(r, dict) and r.get("id") == data.id), None)
    if not itm:
        raise HTTPException(status_code=404, detail="catalog id not found")
    rb = Robot(
        id=str(itm.get("id")),
        name=str(itm.get("name") or itm.get("id")),
        base_url=str(itm.get("base_url")),
        kind=str(itm.get("kind") or "hardware"),
        api_key=(itm.get("api_key") or None),
    )
    store.add_robot(rb)
    store.save()
    _start_sse_task(rb)
    return {"status": "ok", "robot": rb.__dict__}


@app.get("/robots/test")
async def robots_test(base_url: str, api_key: Optional[str] = None):
    url = base_url.rstrip("/") + "/api/status"
    headers = {"X-API-Key": api_key} if api_key else None
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            res = await client.get(url, headers=headers)
        if res.status_code == 200:
            # attempt json parse
            try:
                js = res.json()
            except Exception:
                js = None
            return {"ok": True, "status": 200, "json": js}
        return {"ok": False, "status": res.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/robots/start")
def start_local_robot(data: StartRobotIn):
    """Inicia el servidor del robot reloj local.
    - Lanza `robot_reloj/server_reloj.py` en un proceso independiente.
    - Registra/actualiza el robot en el store con base_url http://localhost:PORT
    """
    global _local_robot_proc, _local_robot_id
    if _local_robot_proc and _local_robot_proc.poll() is None:
        rb = store.robots.get(_local_robot_id or "")
        return {
            "status": "already_running",
            "pid": _local_robot_proc.pid,
            "base_url": rb.base_url if rb else None,
            "robot": ({**rb.__dict__, "runtime": _robot_runtime_flag(rb.id)} if rb else None),
        }

    port = int((data.port or 5005))
    base_url = f"http://localhost:{port}"

    # Resolve script path
    root = Path(__file__).resolve().parent.parent
    script = root / "robot_reloj" / "server_reloj.py"
    if not script.exists():
        raise HTTPException(status_code=500, detail=f"server_reloj.py not found at {script}")
    env = os.environ.copy()
    env["RELOJ_PORT"] = str(port)

    try:
        _local_robot_proc = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(script.parent),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else 0),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"unable to start robot: {e}")

    # ensure robot entry in store
    rid = (data.id or "reloj-local").strip()
    name = (data.name or "Reloj Local").strip()
    rb = store.robots.get(rid)
    if rb:
        rb.base_url = base_url
        rb.name = name or rb.name
        rb.kind = data.kind or rb.kind
    else:
        rb = Robot(id=rid, name=name, base_url=base_url, kind=data.kind or "reloj")
        store.add_robot(rb)
    store.save()
    _local_robot_id = rid
    try:
        _start_sse_task(rb)
    except Exception:
        pass
    robot_payload = {**rb.__dict__}
    robot_payload["runtime"] = _robot_runtime_flag(rb.id)
    return {
        "status": "started",
        "pid": _local_robot_proc.pid if _local_robot_proc else None,
        "base_url": base_url,
        "robot": robot_payload,
    }


@app.post("/robots/stop")
def stop_local_robot(data: Optional[StopLocalIn] = None):
    global _local_robot_proc
    p = _local_robot_proc
    if not p or p.poll() is not None:
        return {"status": "not_running"}
    try:
        if os.name == "nt":
            # attempt graceful CTRL-BREAK then terminate as fallback
            try:
                p.send_signal(1)  # CTRL_BREAK_EVENT surrogate
            except Exception:
                pass
            p.terminate()
        else:
            p.terminate()
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    _local_robot_proc = None
    return {"status": "stopped"}


@app.get("/ensayos")
def list_ensayos():
    rows = []
    # Build rows like the Tkinter table
    # Nombre de la Planta, Día, Hora, Tarea, Regimen, Magnitud, Unidades, Detalles
    for a in store.activities:
        plant = store.get_plant(a.era, a.planta_id)
        reg = next((r for r in store.regimens if r.id_regimen == a.id_regimen), None)
        fecha = a.fecha or ""
        dia = fecha[:10]
        hora = fecha[11:16] if len(fecha) >= 16 else ""
        rows.append({
            "planta": plant.nombre if plant else f"{a.era}:{a.planta_id}",
            "dia": dia,
            "hora": hora,
            "tarea": a.tipo_actividad,
            "regimen": reg.nombre if reg else str(a.id_regimen),
            "magnitud": a.magnitud,
            "unidades": a.unidades,
            "detalles": a.detalles,
        })
    # sort by fecha
    rows.sort(key=lambda r: (r.get("dia") or "", r.get("hora") or ""))
    return {"rows": rows}


if __name__ == "__main__":
    # Ejecutar con: python hub_service/app.py
    import os
    import threading
    import time
    import webbrowser
    import uvicorn
    port = int(os.environ.get("HUB_PORT", "8080"))
    # Abrir automáticamente el navegador con la interfaz del Hub
    def _open_browser():
        # Permitir desactivar vía env var
        if str(os.environ.get("HUB_AUTO_OPEN", "1")).lower() in ("0", "false", "no"):  # opt-out
            return
        time.sleep(1.2)
        try:
            url = f"http://localhost:{port}/hub/index.html?v=2"
            print(f"HUB: Abriendo navegador: {url}")
            webbrowser.open(url)
        except Exception as e:
            print(f"HUB: WARNING no se pudo abrir el navegador: {e}")
    try:
        threading.Thread(target=_open_browser, daemon=True).start()
    except Exception:
        pass
    uvicorn.run("hub_service.app:app", host="0.0.0.0", port=port, reload=False)
