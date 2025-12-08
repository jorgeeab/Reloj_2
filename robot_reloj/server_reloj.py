#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor Robot Reloj - Versión Reformulada y Compatible
======================================================

Servidor Flask para el robot de riego automatizado con:
- Interfaz web moderna y responsiva
- Control de hardware Arduino vía serial
- Sistema de tareas programadas (usando reloj_env.py existente)
- Protocolos de control personalizables
- Gestión de estado en tiempo real
- API REST completa
- Compatibilidad total con archivos existentes
- Control de energías de motores en modo manual
- Sistema de ejecución asíncrona con timeout de 28 segundos

Autor: Sistema Robot Reloj
Versión: 2.1 Compatible
"""

import os
import re
import sys
import json
import time
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from contextlib import nullcontext

from flask import Flask, request, jsonify, make_response, render_template, Response, stream_with_context, send_from_directory
from werkzeug.exceptions import NotFound
import logging
from logging.handlers import RotatingFileHandler
from flask_sock import Sock
try:
    from werkzeug.serving import WSGIRequestHandler as _WerkReq
except Exception:
    _WerkReq = None  # type: ignore
from simple_websocket import ConnectionClosed

# Importaciones opcionales
try:
    from serial.tools import list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    list_ports = None

# Cámara no utilizada en versión mínima

# Importar el entorno del robot (EXISTENTE)
from reloj_env import RelojEnv

# Importar módulos compartidos desde reloj_core
if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from reloj_core import ProtocolRunner, Protocolo
from reloj_core import TaskExecutor, TaskDefinition, ExecutionMode, TaskStatus
from reloj_core import TaskScheduler, TaskSchedule, ScheduleType
try:
    from pybullet_visualizer import PyBulletVisualizer
except ImportError:
    # Intentar agregar el directorio padre al sys.path si se ejecuta como script dentro de robot_reloj
    try:
        PARENT = Path(__file__).resolve().parent.parent
        if str(PARENT) not in sys.path:
            sys.path.insert(0, str(PARENT))
        from pybullet_visualizer import PyBulletVisualizer  # type: ignore
    except Exception:
        PyBulletVisualizer = None

try:
    from virtual_robot import VirtualRelojEnv
except ImportError:
    VirtualRelojEnv = None  # type: ignore

from collections import deque
import subprocess

# =============================================================================
# CONFIGURACIÓN Y CONSTANTES
# =============================================================================

# Directorios del proyecto
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
PROTOCOLS_DIR = BASE_DIR / "protocolos"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
LOGS_DIR = BASE_DIR / "logs"
SHARED_STATIC_DIR = BASE_DIR.parent / "shared_static"

# Crear directorios si no existen
for directory in [DATA_DIR, PROTOCOLS_DIR, TEMPLATES_DIR, STATIC_DIR, LOGS_DIR]:
    directory.mkdir(exist_ok=True)

# Archivos de datos
SETTINGS_FILE = DATA_DIR / "settings_ui.json"

# Inicializar archivos si no existen
if not SETTINGS_FILE.exists():
    SETTINGS_FILE.write_text('{"version":1}', encoding="utf-8")


def _load_settings_dict() -> dict:
    """Lee el archivo de settings de forma segura incluso si aún no hay datos."""
    try:
        txt = SETTINGS_FILE.read_text(encoding="utf-8")
        return json.loads(txt or "{}")
    except Exception:
        return {}


def _save_settings_dict(d: dict) -> bool:
    """Persiste el diccionario de settings en disco."""
    try:
        SETTINGS_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as exc:
        if "logger" in globals() and logger is not None:
            logger.log(f"WARNING: No se pudo guardar settings: {exc}")
        else:
            print(f"[WARNING] No se pudo guardar settings: {exc}")
        return False


# Configuración del robot
DEFAULT_SERIAL_PORT = "COM3"
DEFAULT_BAUDRATE = 115200

# =============================================================================
# CLASES DE DATOS
# =============================================================================

@dataclass
class RobotStatus:
    """Estado actual del robot"""
    x_mm: float = 0.0
    a_deg: float = 0.0
    z_mm: float = 0.0
    servo_z_deg: float = 0.0
    volumen_ml: float = 0.0
    caudal_est_mls: float = 0.0
    # Alias de compatibilidad para la UI
    flow_est: float = 0.0
    lim_x: int = 0
    lim_a: int = 0
    homing_x: int = 0
    homing_a: int = 0
    modo: int = 0
    serial_open: bool = False
    serial_port: str = DEFAULT_SERIAL_PORT
    baudrate: int = DEFAULT_BAUDRATE
    # Energías actuales (basadas en el último comando TX)
    energies: Dict[str, int] = field(default_factory=lambda: {"x": 0, "a": 0, "bomba": 0})
    # Marca si los datos son de caché (sin RX reciente)
    stale: bool = False
    # Nuevos campos expuestos
    kpX: float = 0.0
    kiX: float = 0.0
    kdX: float = 0.0
    kpA: float = 0.0
    kiA: float = 0.0
    kdA: float = 0.0
    pasosPorMM: float = 0.0
    pasosPorGrado: float = 0.0
    usarSensorFlujo: int = 0
    caudalBombaMLs: float = 0.0
    rx_age_ms: int = 0
    volumen_objetivo_ml: float = 0.0
    volumen_restante_ml: float = 0.0
    reward: float = 0.0
    robot_id: str = "real"
    robot_label: str = ""
    robot_kind: str = "hardware"
    is_virtual: bool = False
    # Campos de conveniencia para UI/telemetría unificada
    running: bool = False
    objective_pending: bool = False
    objective_margin_ml: float = 0.05
    flow_target_est_mls: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)



# =============================================================================
# SISTEMA DE LOGGING
# =============================================================================

class RobotLogger:
    """Sistema de logging circular para el robot"""
    
    def __init__(self, capacity: int = 1000):
        self._capacity = capacity
        self._buffer: List[str] = []
        self._lock = threading.Lock()
        # Logger de archivo con rotación
        try:
            self._py_logger = logging.getLogger('reloj_server')
            self._py_logger.setLevel(logging.INFO)
            log_path = str((LOGS_DIR / 'reloj_server.log').resolve())
            handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding='utf-8')
            handler.setLevel(logging.INFO)
            fmt = logging.Formatter('%(message)s')
            handler.setFormatter(fmt)
            # Evitar duplicados si se reimporta
            if not any(isinstance(h, RotatingFileHandler) for h in self._py_logger.handlers):
                self._py_logger.addHandler(handler)
        except Exception:
            self._py_logger = None  # type: ignore
    
    def log(self, message: str, level: str = "INFO"):
        """Registra un mensaje con timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        
        with self._lock:
            self._buffer.append(log_entry)
            if len(self._buffer) > self._capacity:
                self._buffer = self._buffer[-self._capacity:]
        
        # Consola
        print(log_entry, flush=True)
        # Archivo (rotativo)
        try:
            if self._py_logger is not None:
                lvl = level.upper().strip()
                if   lvl == 'DEBUG':   self._py_logger.debug(log_entry)
                elif lvl == 'WARNING': self._py_logger.warning(log_entry)
                elif lvl == 'ERROR':   self._py_logger.error(log_entry)
                else:                  self._py_logger.info(log_entry)
        except Exception:
            pass
    
    def get_logs(self) -> List[str]:
        """Obtiene todos los logs"""
        with self._lock:
            return list(self._buffer)
    
    def clear(self):
        """Limpia el buffer de logs"""
        with self._lock:
            self._buffer.clear()







# =============================================================================
# INSTANCIAS GLOBALES
# =============================================================================

# Logger global
logger = RobotLogger()

# Aplicación Flask
app = Flask(__name__,
            template_folder=str(TEMPLATES_DIR),
            static_folder=None)
sock = Sock(app)

# Configurar Jinja loader para usar templates compartidos
from jinja2 import ChoiceLoader, FileSystemLoader
PROJECT_ROOT = BASE_DIR.parent  # Reloj_2/
SHARED_TEMPLATES = PROJECT_ROOT / "shared_templates"
app.jinja_loader = ChoiceLoader([
    FileSystemLoader(str(TEMPLATES_DIR)),     # Local primero
    FileSystemLoader(str(SHARED_TEMPLATES))   # Shared como fallback
])

@app.route('/static/<path:filename>')
def custom_static(filename):
    """Serve static files with fallback to shared_static"""
    try:
        return send_from_directory(STATIC_DIR, filename)
    except NotFound:
        return send_from_directory(SHARED_STATIC_DIR, filename)

# Verbose flags (pueden habilitarse temporalmente para depurar)
STATUS_DEBUG = False
# Modelo lineal open-loop (sin sensor): parámetros configurables
FLOW_DEADBAND_ENERGY = 0  # 0..255
FLOW_CMAX_MLS = 50.0      # ml/s @ 255 por defecto

# Lock global para operaciones sobre el entorno
env_lock = threading.Lock()

# Registro de robots disponibles y runtime activo

def _create_real_env() -> RelojEnv:
    return RelojEnv(
        port=DEFAULT_SERIAL_PORT,
        baudrate=DEFAULT_BAUDRATE,
        logger=logger.log
    )


def _create_virtual_env() -> "VirtualRelojEnv":
    if VirtualRelojEnv is None:
        raise RuntimeError("VirtualRelojEnv no disponible")
    return VirtualRelojEnv(logger=logger.log)


ROBOT_PROFILES: Dict[str, Dict[str, Any]] = {
    "real": {
        "id": "real",
        "label": "Robot físico (Arduino)",
        "kind": "hardware",
        "is_virtual": False,
        "factory": _create_real_env,
    }
}

if VirtualRelojEnv is not None:
    ROBOT_PROFILES["virtual"] = {
        "id": "virtual",
        "label": "Robot virtual PyBullet",
        "kind": "virtual",
        "is_virtual": True,
        "factory": _create_virtual_env,
    }

DEFAULT_ROBOT_ID = "virtual" if "virtual" in ROBOT_PROFILES else "real"

robot_env: Optional[RelojEnv] = None
protocol_runner: Optional[ProtocolRunner] = None
task_executor: Optional[TaskExecutor] = None
task_scheduler: Optional[TaskScheduler] = None
active_robot_id: Optional[str] = None


def _runtime_summary(profile_id: str) -> Dict[str, Any]:
    profile = ROBOT_PROFILES.get(profile_id, {})
    return {
        "id": profile_id,
        "label": profile.get("label", profile_id),
        "kind": profile.get("kind", "hardware"),
        "is_virtual": bool(profile.get("is_virtual", False)),
        "active": profile_id == active_robot_id,
        "serial_port": getattr(robot_env, "port", None),
    }


def _shutdown_runtime() -> None:
    global robot_env, protocol_runner, task_executor, task_scheduler
    if task_scheduler is not None:
        try:
            task_scheduler.stop()
        except Exception as exc:
            logger.log(f"[Runtime] Error deteniendo scheduler: {exc}", "WARNING")
    if protocol_runner is not None:
        try:
            protocol_runner.stop()
        except Exception as exc:
            logger.log(f"[Runtime] Error deteniendo protocolo: {exc}", "WARNING")
    if robot_env is not None:
        try:
            robot_env.close()
        except Exception as exc:
            logger.log(f"[Runtime] Error cerrando entorno: {exc}", "WARNING")
    robot_env = None
    protocol_runner = None
    task_executor = None
    task_scheduler = None


def _start_runtime(profile_id: str) -> Dict[str, Any]:
    global robot_env, protocol_runner, task_executor, task_scheduler, active_robot_id
    profile = ROBOT_PROFILES[profile_id]
    env = profile["factory"]()
    runner = ProtocolRunner(
        env=env,
        protocols_dir=str(PROTOCOLS_DIR),
        tick_hz=10.0,
        default_timeout_s=60.0,
    )
    try:
        env.set_protocol_activator(lambda name, params: runner.activate(name, params))
    except Exception:
        pass
    executor = TaskExecutor(
        protocol_runner=runner,
        robot_env=env,
        logger=logger.log
    )
    scheduler = TaskScheduler(
        task_executor=executor,
        logger=logger.log
    )
    robot_env = env
    protocol_runner = runner
    task_executor = executor
    task_scheduler = scheduler
    active_robot_id = profile_id
    return profile


def reset_scheduler_defaults(lock_held: bool = False) -> None:
    if robot_env is None:
        return
    ctx = nullcontext() if lock_held else env_lock
    with ctx:
        if robot_env is None:
            return
        try:
            robot_env.set_scheduler_enabled(False)
            logger.log("[Scheduler] Desactivado por defecto")
            changed = False
            for t in list(getattr(robot_env, "tasks", [])):
                if isinstance(t, dict):
                    tp = str(t.get("tipo") or t.get("type") or "").lower()
                    if tp in ("protocolo_inline", "inline", "proto_inline"):
                        has_code = bool(t.get("code") or t.get("codigo") or t.get("script"))
                        if not has_code:
                            t["activo"] = False
                            changed = True
            if changed:
                try:
                    robot_env.save_tasks()
                    logger.log("Se desactivaron tareas inline sin 'code'")
                except Exception:
                    pass
        except Exception as exc:
            logger.log(f"No se pudo desactivar scheduler al inicio: {exc}")


def apply_persisted_settings(lock_held: bool = False) -> None:
    if robot_env is None:
        return
    ctx = nullcontext() if lock_held else env_lock
    with ctx:
        if robot_env is None:
            return
        try:
            s = _load_settings_dict()
            try:
                if s.get("baudrate"):
                    robot_env.baudrate = int(s["baudrate"])
                    robot_env.baud = int(s["baudrate"])
            except Exception:
                pass
            try:
                if s.get("z_mm_por_grado") is not None:
                    robot_env.set_z_mm_por_grado(float(s["z_mm_por_grado"]))
            except Exception:
                pass
            # Modelo de flujo (deadband energía)
            try:
                db = s.get("deadband_energy")
                if db is not None:
                    val = int(float(db))
                    globals()["FLOW_DEADBAND_ENERGY"] = max(0, min(255, val))
                    try:
                        if hasattr(robot_env, 'set_deadband_energy'):
                            robot_env.set_deadband_energy(globals()["FLOW_DEADBAND_ENERGY"])  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
            # Modelo de flujo (cmax ml/s @255). Si no hay settings, usar default
            try:
                cm = s.get("caudal_bomba_mls")
                if cm is None:
                    cm = globals().get("FLOW_CMAX_MLS", 50.0)
                globals()["FLOW_CMAX_MLS"] = max(0.0, float(cm))
                try:
                    robot_env.set_caudal_bomba_ml_s(globals()["FLOW_CMAX_MLS"])  # act[19]
                except Exception:
                    pass
            except Exception:
                pass
            # Aplicar calibraciones persistidas de pasos
            try:
                if s.get("steps_mm") is not None:
                    robot_env.set_pasos_por_mm(float(s["steps_mm"]))
                if s.get("steps_deg") is not None:
                    robot_env.set_pasos_por_grado(float(s["steps_deg"]))
            except Exception:
                pass
            try:
                kpx = s.get("kpX"); kix = s.get("kiX"); kdx = s.get("kdX")
                if kpx is not None and kix is not None and kdx is not None:
                    robot_env.set_pid_corredera(float(kpx), float(kix), float(kdx))
                kpa = s.get("kpA"); kia = s.get("kiA"); kda = s.get("kdA")
                if kpa is not None and kia is not None and kda is not None:
                    robot_env.set_pid_angulo(float(kpa), float(kia), float(kda))
            except Exception:
                pass
            try:
                if s.get("command_policy"):
                    robot_env.set_command_policy(str(s["command_policy"]))
                if s.get("scheduler_enabled") is not None:
                    robot_env.set_scheduler_enabled(bool(s["scheduler_enabled"]))
            except Exception:
                pass
            logger.log("Settings aplicados al iniciar")
        except Exception as exc:
            logger.log(f"WARNING: No se pudieron aplicar settings al inicio: {exc}")


def switch_robot(profile_id: str, *, start_scheduler: bool = True) -> Dict[str, Any]:
    if profile_id not in ROBOT_PROFILES:
        raise KeyError(profile_id)
    restarted = False
    with env_lock:
        global active_robot_id
        if active_robot_id != profile_id or robot_env is None:
            _shutdown_runtime()
            profile = _start_runtime(profile_id)
            reset_scheduler_defaults(lock_held=True)
            logger.log(f"[Runtime] Entorno activo: {profile['label']}")
            restarted = True
        summary = _runtime_summary(profile_id)
    if restarted:
        if start_scheduler and task_scheduler is not None:
            try:
                task_scheduler.start()
            except Exception as exc:
                logger.log(f"[Runtime] Error iniciando scheduler: {exc}", "WARNING")
        apply_persisted_settings()
    return summary


# Inicializar entorno por defecto
switch_robot(DEFAULT_ROBOT_ID, start_scheduler=False)

def _available_robot_profiles() -> List[Dict[str, Any]]:
    return [
        {
            "id": rid,
            "label": profile.get("label", rid),
            "kind": profile.get("kind", "hardware"),
            "is_virtual": bool(profile.get("is_virtual", False)),
            "active": rid == active_robot_id,
        }
        for rid, profile in ROBOT_PROFILES.items()
    ]


@app.route("/api/robots", methods=["GET"])
def api_list_robots():
    """Lista los perfiles disponibles y cuál está activo."""
    return jsonify({
        "active": active_robot_id,
        "robots": _available_robot_profiles(),
    })


@app.route("/api/robots/select", methods=["POST"])
def api_select_robot():
    """Permite alternar entre robot físico y virtual desde la UI."""
    data = get_request_data() or {}
    rid = data.get("id")
    if not rid:
        return jsonify({"error": "id requerido"}), 400
    if rid not in ROBOT_PROFILES:
        return jsonify({"error": f"robot '{rid}' no encontrado"}), 404
    try:
        summary = switch_robot(rid)
    except Exception as exc:
        logger.log(f"[robots.select] error cambiando a {rid}: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500
    return jsonify({
        "status": "ok",
        "active": summary,
        "robots": _available_robot_profiles(),
    })


# Estado del robot y caché del último válido
# Estado del robot y caché del último válido
robot_status = RobotStatus()
last_status_cache: Optional[RobotStatus] = None

visualizer: Optional["PyBulletVisualizer"] = None
# --------- DEBUG SERIAL ---------
last_rx_text = ""
last_rx_ts = 0.0

# último comando TX enviado al robot
last_tx_text = ""
last_tx_ts = 0.0

# --------- PyBullet GUI external process management ---------
_pb_gui_proc: Optional[subprocess.Popen] = None

def _pb_gui_is_running() -> bool:
    global _pb_gui_proc
    return _pb_gui_proc is not None and _pb_gui_proc.poll() is None

def _pb_gui_start() -> bool:
    global _pb_gui_proc
    if _pb_gui_is_running():
        return True
    try:
        script = (BASE_DIR.parent / "pybullet_virtual_gui.py").resolve()
        if not script.exists():
            logger.log(f"[PyBullet GUI] Script no encontrado: {script}", "WARNING")
            return False
        creationflags = 0
        # En Windows, evitar que bloquee la consola del server
        if sys.platform.startswith("win"):
            try:
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            except Exception:
                creationflags = 0
        _pb_gui_proc = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(BASE_DIR.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            start_new_session=(not sys.platform.startswith("win")),
            creationflags=creationflags,
        )
        logger.log("[PyBullet GUI] Proceso iniciado")
        return True
    except Exception as exc:
        logger.log(f"[PyBullet GUI] Error al iniciar: {exc}", "WARNING")
        _pb_gui_proc = None
        return False

def _pb_gui_stop() -> bool:
    global _pb_gui_proc
    if not _pb_gui_is_running():
        _pb_gui_proc = None
        return True
    try:
        assert _pb_gui_proc is not None
        _pb_gui_proc.terminate()
        try:
            _pb_gui_proc.wait(timeout=2.0)
        except Exception:
            _pb_gui_proc.kill()
        logger.log("[PyBullet GUI] Proceso detenido")
        _pb_gui_proc = None
        return True
    except Exception as exc:
        logger.log(f"[PyBullet GUI] Error al detener: {exc}", "WARNING")
        return False


@app.route("/api/pybullet/frame")
def api_pybullet_frame():
    """Devuelve la última imagen renderizada por PyBullet (si está disponible)."""
    if visualizer is None:
        return jsonify({"error": "pybullet_unavailable"}), 503
    try:
        frame = visualizer.render_frame()
    except Exception as exc:
        logger.log(f"[Visualizer] Error renderizando frame: {exc}", "WARNING")
        frame = None
    if not frame:
        return jsonify({"error": "no_frame"}), 503
    resp = make_response(frame)
    resp.headers["Content-Type"] = getattr(visualizer, "mimetype", "image/jpeg")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/pybullet/camera", methods=["GET", "POST"])
def api_pybullet_camera():
    """GET: Obtiene configuración actual de cámara. POST: Actualiza configuración de cámara."""
    if visualizer is None:
        return jsonify({"error": "pybullet_unavailable"}), 503
    
    if request.method == "GET":
        try:
            config = visualizer.get_camera_config()
            return jsonify({"status": "ok", "camera": config})
        except Exception as exc:
            logger.log(f"[PyBullet/camera] Error obteniendo config: {exc}", "WARNING")
            return jsonify({"error": str(exc)}), 500
    
    # POST: Actualizar cámara
    try:
        data = get_request_data() or {}
        target = data.get("target")
        distance = data.get("distance")
        yaw = data.get("yaw")
        pitch = data.get("pitch")
        up_axis = data.get("up_axis")
        
        visualizer.set_camera(
            target=target,
            distance=distance,
            yaw=yaw,
            pitch=pitch,
            up_axis=up_axis
        )
        
        config = visualizer.get_camera_config()
        logger.log(f"[PyBullet/camera] Actualizada: {config}")
        return jsonify({"status": "ok", "camera": config})
    except Exception as exc:
        logger.log(f"[PyBullet/camera] Error actualizando: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/pybullet/resize", methods=["POST"])
def api_pybullet_resize():
    """Cambia el tamaño de renderizado de PyBullet."""
    if visualizer is None:
        return jsonify({"error": "pybullet_unavailable"}), 503
    
    try:
        data = get_request_data() or {}
        width = int(data.get("width", 1280))
        height = int(data.get("height", 720))
        
        visualizer.set_render_size(width, height)
        logger.log(f"[PyBullet/resize] Tamaño cambiado a {width}x{height}")
        return jsonify({
            "status": "ok",
            "width": visualizer.width,
            "height": visualizer.height
        })
    except Exception as exc:
        logger.log(f"[PyBullet/resize] Error: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/pybullet/camera/save", methods=["POST"])
def api_pybullet_camera_save():
    """Guarda la configuración actual de cámara en settings."""
    if visualizer is None:
        return jsonify({"error": "pybullet_unavailable"}), 503
    
    try:
        config = visualizer.get_camera_config()
        settings = _load_settings_dict()
        settings["pybullet_camera"] = config
        _save_settings_dict(settings)
        logger.log("[PyBullet/camera/save] Vista guardada")
        return jsonify({"status": "ok", "camera": config})
    except Exception as exc:
        logger.log(f"[PyBullet/camera/save] Error: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/pybullet/camera/load", methods=["GET", "POST"])
def api_pybullet_camera_load():
    """Carga la configuración de cámara guardada desde settings."""
    if visualizer is None:
        return jsonify({"error": "pybullet_unavailable"}), 503
    
    try:
        settings = _load_settings_dict()
        saved_camera = settings.get("pybullet_camera")
        
        if not saved_camera:
            return jsonify({"status": "not_found", "message": "No hay vista guardada"}), 404
        
        # Aplicar la configuración guardada
        visualizer.set_camera(
            target=saved_camera.get("target"),
            distance=saved_camera.get("distance"),
            yaw=saved_camera.get("yaw"),
            pitch=saved_camera.get("pitch"),
            up_axis=saved_camera.get("up_axis")
        )
        
        config = visualizer.get_camera_config()
        logger.log("[PyBullet/camera/load] Vista cargada")
        return jsonify({"status": "ok", "camera": config})
    except Exception as exc:
        logger.log(f"[PyBullet/camera/load] Error: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def _set_last_rx(txt: str):
    global last_rx_text
    global last_rx_ts
    last_rx_text = txt.strip(); last_rx_ts = time.time()


def _set_last_tx(txt: str):
    global last_tx_text, last_tx_ts
    last_tx_text = txt.strip(); last_tx_ts = time.time()


def _serial_debug_payload(kind: str) -> Dict[str, Any]:
    """Construye el payload de depuración RX/TX."""
    if kind == "rx":
        text = last_rx_text
        ts = last_rx_ts
        field = "last_rx"
    else:
        text = last_tx_text
        ts = last_tx_ts
        field = "last_tx"
    age_ms = int(max(0.0, time.time() - ts) * 1000) if ts else None
    payload: Dict[str, Any] = {
        field: text,
        "age_ms": age_ms,
        "ts": ts or None,
    }
    if ts:
        try:
            payload["ts_iso"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except Exception:
            payload["ts_iso"] = datetime.utcfromtimestamp(ts).isoformat()  # type: ignore[attr-defined]
    if text:
        payload["lines"] = text.splitlines()
        payload["chars"] = len(text)
    else:
        payload["lines"] = []
        payload["chars"] = 0
    payload["kind"] = kind
    return payload

# --------------------------------

# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def get_robot_status(force_fresh=False) -> RobotStatus:
    global last_status_cache
    # Variables para derivar caudal
    global last_rx_ts
    if not hasattr(get_robot_status, "_last_vol_ts"):
        setattr(get_robot_status, "_last_vol_ts", 0.0)
        setattr(get_robot_status, "_last_vol_ml", 0.0)
    """Obtiene el estado actual del robot de forma segura y sin evaluar arrays como booleanos."""

    status = RobotStatus()  # instancia nueva cada llamada
    obs_list: Optional[List[float]] = None
    try:
        with env_lock:
            # Obtener observación cruda
            obs_arr = robot_env._obs_now()
            data_fresh = True
            if obs_arr is None:
                # Espera breve por RX (hasta ~300ms) antes de decidir caché
                waited = 0
                while obs_arr is None and waited < 3:
                    try:
                        obs_arr = robot_env.q.get(timeout=0.1)
                    except Exception:
                        obs_arr = None
                    waited += 1
                if obs_arr is None:
                    data_fresh = False

            if data_fresh or force_fresh:
                if obs_arr is not None:
                    obs_list = obs_arr.tolist()
                    _set_last_rx(" ".join(f"{v:.2f}" for v in obs_list))
                    if STATUS_DEBUG:
                        print(f"[DEBUG] get_robot_status: Datos frescos - X={obs_list[0]}, A={obs_list[1]}, Z={obs_list[21] if len(obs_list) > 21 else 'N/A'}")
                else:
                    if STATUS_DEBUG:
                        print("[DEBUG] get_robot_status: No hay datos frescos disponibles")
                    obs_list = [0.0]*21
            else:
                # Sin RX reciente: usar caché si existe para mantener valores previos
                if last_status_cache is not None:
                    cached_dict = asdict(last_status_cache)
                    cached_dict["stale"] = True
                    try:
                        cached_dict["rx_age_ms"] = int(max(0.0, time.time() - last_rx_ts) * 1000)
                    except Exception:
                        cached_dict["rx_age_ms"] = 0
                    status = RobotStatus(**cached_dict)
                    if STATUS_DEBUG:
                        print(f"[DEBUG] get_robot_status: Usando caché - X={status.x_mm}, A={status.a_deg}")
                else:
                    # Sin caché disponible: caerá a valores por defecto (ceros)
                    obs_list = [0.0]*21
                    if STATUS_DEBUG:
                        print("[DEBUG] get_robot_status: Usando valores por defecto (ceros)")

            # Conexión serial actual
            ser = getattr(robot_env, "ser", None)
            status.serial_open = bool(ser and ser.is_open)
            status.serial_port = robot_env.port
            try:
                status.baudrate = int(getattr(robot_env, 'baudrate', DEFAULT_BAUDRATE) or DEFAULT_BAUDRATE)
            except Exception:
                status.baudrate = DEFAULT_BAUDRATE

            valor_bomba_rx: Optional[float] = None
            if obs_list is not None and len(obs_list) >= 21:
                status.x_mm       = float(obs_list[0])
                status.a_deg      = float(obs_list[1])
                try:
                    valor_bomba_rx = float(obs_list[2])
                except Exception:
                    valor_bomba_rx = None
                status.volumen_ml = float(obs_list[3])
                status.lim_x      = int(obs_list[4])
                status.lim_a      = int(obs_list[5])
                status.homing_x   = int(obs_list[6])
                status.homing_a   = int(obs_list[7])
                status.modo       = int(obs_list[11])
                # PID gains desde RX (indices 12..17)
                status.kpX        = float(obs_list[12])
                status.kiX        = float(obs_list[13])
                status.kdX        = float(obs_list[14])
                status.kpA        = float(obs_list[15])
                status.kiA        = float(obs_list[16])
                status.kdA        = float(obs_list[17])
                # Calibraciones desde RX (si el firmware las reporta)
                status.pasosPorMM    = float(obs_list[18])
                status.pasosPorGrado = float(obs_list[19])
            had_z_from_rx = False
            if obs_list is not None:
                try:
                    if len(obs_list) >= 22:
                        status.z_mm = float(obs_list[21])
                        had_z_from_rx = True
                except Exception:
                    pass

            # Energías y Z desde el último comando TX (vector de acción actual)
            try:
                act = getattr(robot_env, 'act', None)
                if act is not None and len(act) >= 4:
                    # ALIAS: energiaA=1, energiaX=2, energiaBomba=3
                    bomba_eff = int(act[3])
                    try:
                        if valor_bomba_rx is not None:
                            bomba_eff = int(round(valor_bomba_rx))
                    except Exception:
                        pass
                    status.energies = {
                        "x": int(act[2]),
                        "a": int(act[1]),
                        "bomba": bomba_eff,
                    }
                    # Volumen objetivo (índice 6)
                    try:
                        if len(act) >= 7:
                            status.volumen_objetivo_ml = float(act[6])
                    except Exception:
                        pass
                    # Servo Z (ángulo en índice 20 y velocidad en 21)
                    # Ya no forzamos servo_z_deg si reportamos z_mm
                    # Exponer flags/flujo desde TX actuales
                    if len(act) >= 20:
                        try:
                            status.usarSensorFlujo = int(act[18])
                        except Exception:
                            status.usarSensorFlujo = 0
                        try:
                            status.caudalBombaMLs = float(act[19])
                        except Exception:
                            status.caudalBombaMLs = 0.0
            except Exception:
                pass

            # Alias de compatibilidad para la UI
            # Derivar caudal si es posible
            try:
                now_ts = time.time()
                prev_ts = getattr(get_robot_status, "_last_vol_ts")
                prev_vol = getattr(get_robot_status, "_last_vol_ml")
                allow_deriv = prev_ts and now_ts > prev_ts
                if allow_deriv:
                    dvol = max(0.0, status.volumen_ml - prev_vol)
                    dt = now_ts - prev_ts
                    deriv = dvol / dt if dt > 0 else 0.0
                    if status.usarSensorFlujo or getattr(robot_env, "is_virtual", False):
                        status.caudal_est_mls = float(deriv)
                    else:
                        # Sin sensor: estimar desde energía proporcional (no asumir cmax completa)
                        try:
                            e = abs(int(status.energies.get("bomba", 0)))
                            db = int(globals().get("FLOW_DEADBAND_ENERGY", 0))
                            cmax = float(status.caudalBombaMLs or 0.0) or float(globals().get("FLOW_CMAX_MLS", 50.0))
                            alpha = 0.0 if e <= db else float(e - db) / float(max(1, 255 - db))
                            status.caudal_est_mls = float(max(0.0, min(cmax, alpha * cmax)))
                        except Exception:
                            status.caudal_est_mls = 0.0
                setattr(get_robot_status, "_last_vol_ts", now_ts)
                setattr(get_robot_status, "_last_vol_ml", status.volumen_ml)
            except Exception:
                pass

            # Estimador local cuando no hay sensor de flujo (para telemetría/UI)
            if not getattr(robot_env, "is_virtual", False):
                try:
                    if not hasattr(get_robot_status, "_est_vol"):
                        setattr(get_robot_status, "_est_vol", {
                            "ts": 0.0,
                            "vol": 0.0,
                        })
                    est = getattr(get_robot_status, "_est_vol")
                    now_est = time.time()
                    bomba_activa = bool(status.energies.get("bomba", 0))
                    if status.usarSensorFlujo:
                        est["vol"] = status.volumen_ml
                        est["ts"] = now_est
                    else:
                        if bomba_activa and status.caudalBombaMLs > 0:
                            if est["ts"] == 0:
                                est["vol"] = status.volumen_ml
                                est["ts"] = now_est
                            else:
                                dt = max(0.0, now_est - est["ts"])
                                est["ts"] = now_est
                                est["vol"] = max(status.volumen_ml, est["vol"] + status.caudalBombaMLs * dt)
                            status.caudal_est_mls = float(status.caudalBombaMLs)
                            status.flow_est = status.caudal_est_mls
                            status.volumen_ml = est["vol"]
                        else:
                            est["vol"] = status.volumen_ml
                            est["ts"] = now_est
                except Exception:
                    pass

            status.flow_est = float(status.caudal_est_mls or 0.0)
            try:
                status.volumen_restante_ml = max(0.0, float(status.volumen_objetivo_ml) - float(status.volumen_ml))
            except Exception:
                status.volumen_restante_ml = 0.0
            # Campos de conveniencia (uniformes entre robots)
            try:
                # Ejecutándose si hay flujo o si EXECUTE está ON y hay objetivo pendiente
                exec_on = bool(int(status.modo) & 0x08)
            except Exception:
                exec_on = False
            try:
                margin = float(getattr(status, 'objective_margin_ml', 0.05) or 0.05)
            except Exception:
                margin = 0.05
            try:
                status.objective_pending = bool(status.volumen_restante_ml > margin)
            except Exception:
                status.objective_pending = False
            try:
                status.running = bool((status.caudal_est_mls or 0.0) > 0.01 or (exec_on and status.objective_pending))
            except Exception:
                status.running = False
            # Estimar objetivo de flujo desde energía (modo sin sensor)
            try:
                usar_sens = bool(status.usarSensorFlujo)
            except Exception:
                usar_sens = False
            try:
                db = globals().get('FLOW_DEADBAND_ENERGY', 0)
                cmax = 0.0
                act = getattr(robot_env, 'act', None)
                if act is not None and len(act) > 19:
                    cmax = float(act[19])
                if not cmax or cmax <= 0:
                    cmax = float(globals().get('FLOW_CMAX_MLS', 50.0))
                e = abs(int(status.energies.get('bomba', 0)))
                alpha = 0.0 if e <= db else (float(e - db) / float(max(1, 255 - db)))
                status.flow_target_est_mls = 0.0 if usar_sens else max(0.0, min(cmax, alpha * cmax))
            except Exception:
                status.flow_target_est_mls = 0.0
            profile = ROBOT_PROFILES.get(active_robot_id or "real", {})
            status.robot_id = active_robot_id or "real"
            status.robot_label = profile.get("label", status.robot_id)
            status.robot_kind = profile.get("kind", "hardware")
            status.is_virtual = bool(profile.get("is_virtual", False))
            # Si no hay z_mm en RX, calcular desde TX/deg como fallback
            try:
                if not had_z_from_rx:
                    # Intentar con TX actual deg
                    act = getattr(robot_env, 'act', None)
                    if act is not None and len(act) >= 21:
                        deg = float(act[20])
                        settings = _load_settings_dict()
                        z_scale = float(settings.get('z_mm_por_grado', getattr(robot_env, 'z_mm_por_grado', 1.0) or 1.0))
                        status.z_mm = max(0.0, (180.0 - deg) * z_scale)
            except Exception:
                pass

            # Edad de RX
            try:
                status.rx_age_ms = int(max(0.0, time.time() - last_rx_ts) * 1000)
            except Exception:
                status.rx_age_ms = 0

            # Agregar reward del protocolo activo
            try:
                st = protocol_runner.status()
                if st.activo and st.last_reward is not None:
                    status.reward = float(st.last_reward)
                else:
                    status.reward = 0.0
            except Exception:
                status.reward = 0.0

            # Actualizar caché solo cuando los datos son frescos
            status.stale = not data_fresh
            if data_fresh:
                last_status_cache = status

            if visualizer is not None:
                try:
                    visualizer.update_from_status(status)
                except Exception as exc:
                    logger.log(f"[Visualizer] Error actualizando escena: {exc}", "WARNING")
    except Exception as e:
        logger.log(f"Error obteniendo estado del robot: {e}", "ERROR")
    return status

def _is_serial_connected() -> bool:
    """Indica si el puerto serial está abierto, o si estamos en modo virtual."""
    try:
        if getattr(robot_env, "is_virtual", False):
            return True
        port_value = str(getattr(robot_env, "port", "") or "").strip().upper()
        if port_value == "VIRTUAL":
            return True
        ser = getattr(robot_env, "ser", None)
        return bool(ser and getattr(ser, "is_open", False))
    except Exception:
        return False

def list_serial_ports() -> List[str]:
    """Lista puertos serial disponibles"""
    if not SERIAL_AVAILABLE:
        return []
    
    try:
        ports = [p.device for p in list_ports.comports()]
        if not ports:
            ports = []
        return ports
    except Exception:
        return []

def get_request_data() -> Dict:
    """Obtiene datos de la petición (JSON o form)"""
    if request.is_json:
        return request.get_json(silent=True) or {}
    elif request.form:
        return dict(request.form)
    else:
        return {}

# === UTILIDAD GLOBAL: APAGAR TODO ===

def stop_all_actuators():
    """Apaga corredera, ángulo y bomba, y pone modo STOP (codigoModo=3).
    Esta función es segura y puede llamarse desde cualquier parte.
    """
    with env_lock:
        try:
            robot_env.set_energia_corredera(0)
            robot_env.set_energia_angulo(0)
            robot_env.set_energia_bomba(0)
            robot_env.set_volumen_objetivo_ml(0)
            robot_env.set_modo(cod=3)
            try:
                robot_env.set_execute_trigger(False)
            except Exception:
                pass
            robot_env.step()
        except Exception as e:
            logger.log(f"[stop_all_actuators] Error apagando actuadores: {e}", "ERROR")

# === FILTRO DE ENDPOINTS PERMITIDOS ===

ALLOWED_ENDPOINTS = {
    "/",               # página principal
    "/api",
    "/api/control",
    "/api/status",
    "/api/status/stream",
    "/api/config",
    "/api/settings",
    "/api/robots",
    "/api/robots/select",
    "/api/tasks/execute",
    "/api/executions",
    "/api/serial/ports",
    "/api/serial/open",
    "/api/serial/close",
    "/api/stop",
    "/api/home",
    "/api/emergency_stop",
}

ALLOWED_PREFIXES = (
    "/api/execution/",
    "/ws/",
    "/static",
    "/hub",
    "/api/pybullet/",
)

ENFORCE_ENDPOINT_FILTER = False

@app.before_request
def restrict_endpoints():
    if not ENFORCE_ENDPOINT_FILTER:
        return
    path = request.path
    upgrade = request.headers.get("Upgrade", "").lower()
    if path.startswith("/ws/") or upgrade == "websocket":
        return
    if path in ALLOWED_ENDPOINTS:
        return
    if any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        return
    if path.startswith("/favicon.ico"):
        return
    logger.log(f"[HTTP] Bloqueado {path}", "WARNING")
    return jsonify({"error": "Endpoint deshabilitado"}), 404

# =============================================================================
# RAÍZ MÍNIMA
# =============================================================================

@app.route("/")
def root_index():
    """Entrega la interfaz principal y evita que el navegador use una versión en caché."""
    html = render_template("reloj.html")
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.post("/api/pybullet/start")
def api_pybullet_start():
    ok = _pb_gui_start()
    return jsonify({ "status": "ok" if ok else "error", "running": ok })

@app.post("/api/pybullet/stop")
def api_pybullet_stop():
    ok = _pb_gui_stop()
    return jsonify({ "status": "ok" if ok else "error", "running": _pb_gui_is_running() })


@app.route("/api")
def api_index():
    return jsonify({
        "name": "Robot Reloj API",
        "version": "1.0",
        "endpoints": {
            "ws": {
                "control": "/ws/control",
                "telemetry": "/ws/telemetry"
            },
            "tasks": {
                "execute": "/api/tasks/execute",
                "executions": "/api/executions",
                "execution": "/api/execution/<execution_id>",
                "stop": "/api/execution/<execution_id>/stop"
            },
            "config": "/api/config",
            "ui_registry": "/api/ui/registry",
            "serial": {
                "ports": "/api/serial/ports",
                "open": "/api/serial/open",
                "close": "/api/serial/close"
            },
            "safety": {
                "stop": "/api/stop",
                "home": "/api/home",
                "emergency": "/api/emergency_stop"
            }
        }
    })

@app.route("/api/control", methods=["POST"])
def api_control():
    """REST endpoint compatible with hub_service to enviar comandos directos."""
    if not _is_serial_connected():
        return jsonify({
            "error": "Serial desconectado. Conéctalo antes de enviar comandos.",
            "robot_connection": "disconnected",
        }), 409
    try:
        data = get_request_data() or {}
        result = apply_control_payload(data)
        snapshot = _status_payload(force_fresh=False)
        return jsonify({
            "status": "ok",
            "result": result,
            "status_snapshot": snapshot,
        })
    except Exception as exc:
        logger.log(f"/api/control error: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500

def _status_payload(force_fresh: bool = False) -> Dict[str, Any]:
    """Helper to package the current robot status for REST/SSE consumers."""
    status = get_robot_status(force_fresh=force_fresh)
    payload = asdict(status)
    payload["ts"] = datetime.now(timezone.utc).isoformat()
    payload["robot"] = {
        "id": status.robot_id,
        "label": status.robot_label,
        "kind": status.robot_kind,
        "is_virtual": status.is_virtual,
        "serial_port": status.serial_port,
        "baudrate": status.baudrate,
    }
    return payload


@app.route("/api/status", methods=["GET"])
def api_status():
    """Instant snapshot for hub_service and other clients."""
    fresh_flags = {"1", "true", "yes", "on"}
    force_fresh = str(request.args.get("fresh", "")).lower() in fresh_flags
    return jsonify(_status_payload(force_fresh=force_fresh))


@app.route("/api/status/stream")
def api_status_stream():
    """Server-Sent Events stream mirroring the /ws/telemetry feed."""
    interval = max(0.1, TELEMETRY_INTERVAL)

    def _event_stream():
        while True:
            try:
                payload = _status_payload(force_fresh=False)
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except GeneratorExit:
                break
            except Exception as exc:
                logger.log(f"[SSE/status] error: {exc}", "ERROR")
                time.sleep(1.0)
            else:
                time.sleep(interval)

    resp = Response(stream_with_context(_event_stream()), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@app.route("/debug/serial", methods=["GET"])
def debug_serial_rx():
    """Devuelve el último RX recibido por el firmware y su edad."""
    return jsonify(_serial_debug_payload("rx"))


@app.route("/debug/serial_tx", methods=["GET"])
def debug_serial_tx():
    """Devuelve el último comando TX enviado al firmware y su edad."""
    return jsonify(_serial_debug_payload("tx"))


@app.route("/api/debug/logs", methods=["GET"])
def api_debug_logs():
    """Entrega los logs circulares del servidor (para la consola UI)."""
    try:
        limit = int(request.args.get("limit", 150))
    except Exception:
        limit = 150
    limit = max(1, min(limit, 500))
    logs = logger.get_logs()
    total = len(logs)
    if total > limit:
        logs = logs[-limit:]
    return jsonify({
        "logs": logs,
        "count": len(logs),
        "total": total,
    })


@app.route("/api/debug/logs", methods=["DELETE"])
def api_debug_logs_clear():
    """Limpia el buffer circular de logs."""
    logger.clear()
    return jsonify({"status": "cleared"})

## Versión mínima: sin rutas de UI




# PROMPT(config): exponer solo parámetros necesarios para el hub
@app.route("/api/config", methods=["GET"])
def api_config():
    """Devuelve configuración básica necesaria para la UI mínima."""
    return jsonify({
        "serial_port": robot_env.port,
        "baudrate": robot_env.baudrate,
        "robot_connected": getattr(robot_env, 'ser', None) is not None and getattr(robot_env.ser, 'is_open', False)
    })

@app.route("/api/ui/registry", methods=["GET"])
def api_ui_registry():
    """Entrega el registro de widgets para que una UI dinámica se construya sola."""
    try:
        reg_path = (STATIC_DIR / "components" / "registry" / "reloj.json")
        if reg_path.exists():
            return jsonify(json.loads(reg_path.read_text(encoding="utf-8")))
    except Exception:
        pass
    return jsonify({"widgets": []})

@app.route("/api/settings", methods=["GET"])  # carga
def api_settings_get():
    return jsonify(_load_settings_dict())

@app.route("/api/settings", methods=["POST"])  # guarda
def api_settings_save():
    try:
        data = get_request_data() or {}
        cur = _load_settings_dict()
        cur.update(data or {})
        if not _save_settings_dict(cur):
            return jsonify({"error":"no se pudo guardar"}), 500
        # Aplicar calibraciones al entorno si están disponibles
        try:
            if 'z_mm_por_grado' in cur:
                robot_env.set_z_mm_por_grado(float(cur.get('z_mm_por_grado') or 1.0))
        except Exception:
            pass
        return jsonify({"status":"ok", "message":"Settings guardados (incluye últimos setpoints)", "saved_keys": list((data or {}).keys())})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# === SERIAL ENDPOINTS ===

# (bloque duplicado eliminado; se conservan las definiciones originales)

# =============================================================================
# CONTROL VIA WEBSOCKET
# =============================================================================

TELEMETRY_INTERVAL = float(os.environ.get("RELOJ_TELEMETRY_INTERVAL", "0.2"))


def apply_control_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica un payload de control directo sobre el robot."""
    if not _is_serial_connected():
        raise RuntimeError("Serial desconectado. No se pueden enviar comandos.")
    logger.log(f"[control] payload: {data}")
    # PROMPT(ws/control): definir handshake, payloads y reintentos
    with env_lock:
        if "setpoints" in data:
            sp = data["setpoints"] or {}
            if "x_mm" in sp:
                robot_env.set_corredera_mm(float(sp["x_mm"]))
            if "a_deg" in sp:
                robot_env.set_angulo_deg(float(sp["a_deg"]))
            if "volumen_ml" in sp:
                v = float(sp["volumen_ml"])
                robot_env.set_volumen_objetivo_ml(v)
                logger.log(f"[FLOW] set objetivo volumen_ml={v}", "DEBUG")
            if "z_mm" in sp:
                robot_env.set_z_mm(float(sp["z_mm"]))
            if "servo_z_deg" in sp:
                robot_env.set_servo_z_deg(float(sp["servo_z_deg"]))

        if "energies" in data:
            en = data["energies"] or {}
            if "x" in en:
                robot_env.set_energia_corredera(int(en["x"]))
            if "a" in en:
                robot_env.set_energia_angulo(int(en["a"]))
            if "bomba" in en:
                eb = int(en["bomba"])
                robot_env.set_energia_bomba(eb)
                logger.log(f"[FLOW] energia bomba={eb}", "DEBUG")

        if "motion" in data:
            mv = data["motion"] or {}
            if "z_speed_deg_s" in mv:
                robot_env.set_servo_z_speed(float(mv["z_speed_deg_s"]))

        if "pid_settings" in data:
            pid_settings = data["pid_settings"] or {}
            pid_x = pid_settings.get("pidX")
            pid_a = pid_settings.get("pidA")
            if pid_x and all(k in pid_x for k in ("kp", "ki", "kd")):
                robot_env.set_pid_corredera(float(pid_x["kp"]), float(pid_x["ki"]), float(pid_x["kd"]))
            if pid_a and all(k in pid_a for k in ("kp", "ki", "kd")):
                robot_env.set_pid_angulo(float(pid_a["kp"]), float(pid_a["ki"]), float(pid_a["kd"]))

        if "calibration" in data:
            calib = data["calibration"] or {}
            if "steps_mm" in calib:
                robot_env.set_pasos_por_mm(float(calib["steps_mm"]))
            if "steps_deg" in calib:
                robot_env.set_pasos_por_grado(float(calib["steps_deg"]))

        if "flow" in data:
            fl = data["flow"] or {}
            if "usar_sensor_flujo" in fl:
                val = fl["usar_sensor_flujo"]
                u = bool(int(val)) if isinstance(val, (int, str)) else bool(val)
                robot_env.set_usar_sensor_flujo(u)
                logger.log(f"[FLOW] usar_sensor_flujo={int(u)}", "DEBUG")
            # cmax (calibración)
            if "caudal_bomba_mls" in fl:
                try:
                    c = float(fl["caudal_bomba_mls"])
                    globals()["FLOW_CMAX_MLS"] = max(0.0, c)
                    robot_env.set_caudal_bomba_ml_s(globals()["FLOW_CMAX_MLS"])  # act[19]
                    logger.log(f"[FLOW] cmax (caudal_bomba_mls)={globals()['FLOW_CMAX_MLS']}", "DEBUG")
                except Exception as exc:
                    logger.log(f"[FLOW] cmax inválido: {exc}", "WARNING")
            if "deadband_energy" in fl:
                try:
                    db = int(float(fl["deadband_energy"]))
                    globals()["FLOW_DEADBAND_ENERGY"] = max(0, min(255, db))
                    if hasattr(robot_env, 'set_deadband_energy'):
                        try:
                            robot_env.set_deadband_energy(globals()["FLOW_DEADBAND_ENERGY"])  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    logger.log(f"[FLOW] deadband_energy={globals()['FLOW_DEADBAND_ENERGY']}", "DEBUG")
                except Exception as exc:
                    logger.log(f"[FLOW] deadband_energy inválido: {exc}", "WARNING")

        if "modo" in data:
            modo = int(data["modo"])
            robot_env.set_modo(mx=bool(modo & 1), ma=bool(modo & 2))
        # Trigger de ejecutar (bit 3 de codigoModo)
        if "execute" in data:
            try:
                robot_env.set_execute_trigger(bool(int(data.get("execute"))))
            except Exception:
                try:
                    robot_env.set_execute_trigger(bool(data.get("execute")))
                except Exception:
                    pass

        if data.get("reset_volumen"):
            robot_env.reset_volumen()
        if data.get("reset_x"):
            robot_env.reset_x()
        if data.get("reset_a"):
            robot_env.reset_a()

        # Si no hay sensor, mapear flujo objetivo → energía (modelo lineal)
        try:
            fl = data.get("flow") or {}
            en = data.get("energies") or {}
            set_has_bomba = ("bomba" in en)
            if isinstance(fl, dict):
                # Config actual (cmax)
                cmax = None
                try:
                    act = getattr(robot_env, 'act', None)
                    if act is not None and len(act) > 19:
                        cmax = float(act[19])
                except Exception:
                    cmax = None
                if not cmax or cmax <= 0:
                    cmax = float(globals().get("FLOW_CMAX_MLS", 50.0) or 50.0)
                # ¿Sin sensor? entonces mapear flujo objetivo → energía
                usar_sens = None
                try:
                    usar_sens = bool(int(fl.get("usar_sensor_flujo")))
                except Exception:
                    usar_sens = None
                if usar_sens is None:
                    try:
                        act = getattr(robot_env, 'act', None)
                        if act is not None and len(act) > 18:
                            usar_sens = bool(int(act[18]))
                    except Exception:
                        usar_sens = False
                # Extraer flujo objetivo (nuevo campo); mantener compat compat si venía con el nombre viejo
                f_tgt = 0.0
                try:
                    if "flow_target_mls" in fl:
                        f_tgt = float(fl.get("flow_target_mls") or 0.0)
                    elif ("caudal_target_mls" in fl):
                        f_tgt = float(fl.get("caudal_target_mls") or 0.0)
                except Exception:
                    f_tgt = 0.0
                if not usar_sens:
                    try:
                        db = globals()["FLOW_DEADBAND_ENERGY"]
                        if f_tgt <= 0 or cmax <= 0:
                            e = 0
                        else:
                            alpha = max(0.0, min(1.0, f_tgt / float(cmax)))
                            e = int(round(db + alpha * (255 - db)))
                        # Solo si no vino energia explícita
                        if not set_has_bomba:
                            robot_env.set_energia_bomba(e)
                        logger.log(f"[FLOW] map f={f_tgt} ml/s @cmax={cmax} db={db} → energia={e}", "DEBUG")
                    except Exception as exc:
                        logger.log(f"[FLOW] mapeo flujo→energía falló: {exc}", "WARNING")
        except Exception:
            pass

        # Paso de control → envía TX al firmware / virtual
        robot_env.step()
        try:
            act = getattr(robot_env, 'act', None)
            if act is not None and len(act) >= 7:
                logger.log(f"[TX] modo={int(act[0])} eA={int(act[1])} eX={int(act[2])} eB={int(act[3])} volObj={float(act[6]):.2f} caudal={float(act[19]) if len(act)>19 else 0.0}", "DEBUG")
        except Exception:
            pass
        try:
            _set_last_tx(json.dumps(data, ensure_ascii=False))
        except Exception:
            _set_last_tx(str(data))

    commands_applied: Dict[str, Any] = {}
    for key in ("setpoints", "energies", "motion", "pid_settings", "calibration", "flow", "modo"):
        if key in data:
            commands_applied[key] = data[key]
    if data.get("reset_volumen") or data.get("reset_x") or data.get("reset_a"):
        commands_applied["reset"] = {
            "volumen": bool(data.get("reset_volumen")),
            "x": bool(data.get("reset_x")),
            "a": bool(data.get("reset_a")),
        }
    return {
        "commands_applied": commands_applied,
        "serial": {
            "port": robot_env.port if robot_env else None,
            "baudrate": getattr(robot_env, "baudrate", DEFAULT_BAUDRATE),
        },
    }


@sock.route("/ws/control")
def ws_control(ws):
    """Canal principal para control manual del robot."""
    session_id = f"ctrl-{int(time.time()*1000)}"
    logger.log(f"[ws/control] sesión abierta ({session_id})")
    hello = {
        "type": "control_ready",
        "robot_id": active_robot_id,
        "kind": ROBOT_PROFILES.get(active_robot_id or "real", {}).get("kind", "hardware"),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        ws.send(json.dumps(hello, ensure_ascii=False))
    except Exception:
        pass
    try:
        while True:
            raw = ws.receive()
            if raw is None:
                continue
            try:
                payload = json.loads(raw)
            except Exception as exc:
                ws.send(json.dumps({"type": "control_ack", "status": "error", "error": f"invalid_json: {exc}"}))
                continue
            if isinstance(payload, dict) and payload.get("type") == "ping":
                ws.send(json.dumps({"type": "pong", "ts": datetime.now(timezone.utc).isoformat()}))
                continue
            body = payload.get("body") if isinstance(payload, dict) and "body" in payload else payload
            if not isinstance(body, dict):
                ws.send(json.dumps({"type": "control_ack", "status": "error", "error": "body_required"}))
                continue
            try:
                result = apply_control_payload(body)
                snapshot = _status_payload(force_fresh=False)
                ws.send(json.dumps({
                    "type": "control_ack",
                    "status": "ok",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "body": result,
                    "status_snapshot": snapshot,
                }, ensure_ascii=False))
            except Exception as exc:
                logger.log(f"[ws/control] error: {exc}", "ERROR")
                ws.send(json.dumps({"type": "control_ack", "status": "error", "error": str(exc)}))
    except ConnectionClosed:
        logger.log(f"[ws/control] sesión cerrada ({session_id})", "INFO")
    except Exception as exc:
        logger.log(f"[ws/control] fallo crítico ({session_id}): {exc}", "ERROR")
        try:
            ws.send(json.dumps({"type": "control_ack", "status": "error", "error": str(exc)}))
        except Exception:
            pass
    finally:
        try:
            ws.close()
        except Exception:
            pass


@sock.route("/ws/telemetry")
def ws_telemetry(ws):
    """Canal SSE->WS para telemetría periódica."""
    # PROMPT(ws/telemetry): campos mínimos (ts, axes, energies, tasks)
    session_id = f"tele-{int(time.time()*1000)}"
    logger.log(f"[ws/telemetry] sesión abierta ({session_id})")
    try:
        ws.send(json.dumps({
            "type": "telemetry_ready",
            "robot_id": active_robot_id,
            "interval_s": TELEMETRY_INTERVAL,
            "ts": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False))
        while True:
            status_payload = _status_payload(force_fresh=False)
            payload = {
                "type": "telemetry",
                "ts": datetime.now(timezone.utc).isoformat(),
                "robot_id": active_robot_id,
                "status": status_payload,
            }
            ws.send(json.dumps(payload, ensure_ascii=False))
            time.sleep(max(0.05, TELEMETRY_INTERVAL))
    except ConnectionClosed:
        logger.log(f"[ws/telemetry] sesión cerrada ({session_id})", "INFO")
    except Exception as exc:
        logger.log(f"[ws/telemetry] error ({session_id}): {exc}", "ERROR")
        try:
            ws.send(json.dumps({"type": "telemetry_error", "error": str(exc)}))
        except Exception:
            pass
    finally:
        try:
            ws.close()
        except Exception:
            pass

# =============================================================================
# ENDPOINTS HTTP PARA TAREAS
# =============================================================================

# Endpoint para listar protocolos disponibles con sus parámetros
@app.route("/api/protocols/list", methods=["GET"])
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
                logger.log(f"Error cargando protocolo {protocol_name}: {e}", "WARN")
                protocols_list.append({
                    "name": protocol_name,
                    "type": "error",
                    "parameters": {},
                    "has_parameters": False,
                    "error": str(e)
                })
        
        return jsonify({
            "protocols": protocols_list,
            "count": len(protocols_list)
        })
        
    except Exception as e:
        logger.log(f"Error listando protocolos: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500

# PROMPT(tasks-http): validar payloads y mapear a ProtocolRunner
@app.route("/api/tasks/execute", methods=["POST"])
def api_execute_task_v2():
    """Nuevo endpoint para ejecutar tareas con arquitectura unificada"""
    try:
        # Bloqueo si serial desconectado
        if not _is_serial_connected():
            logger.log("/api/tasks/execute rechazado: serial desconectado", "WARN")
            return jsonify({
                "error": "Serial desconectado. Conéctelo en Settings antes de ejecutar.",
                "robot_connection": "disconnected",
                "message": "Controles deshabilitados hasta conectar el serial"
            }), 409
        data = get_request_data()
        logger.log(f"/api/tasks/execute recibido: {data}")
        
        # Parámetros requeridos
        name = data.get("name", "Tarea sin nombre")
        protocol_name = data.get("protocol_name")
        if not protocol_name:
            return jsonify({"error": "Se requiere 'protocol_name'"}), 400
        # Validar existencia del protocolo
        if not Protocolo.existe(protocol_name, str(PROTOCOLS_DIR)):
            logger.log(f"Protocolo no encontrado: {protocol_name}", "WARN")
            return jsonify({"error": f"Protocolo '{protocol_name}' no encontrado"}), 404
        
        # Parámetros opcionales
        duration_seconds = float(data.get("duration_seconds", 10.0))
        timeout_seconds = float(data.get("timeout_seconds", 25.0))
        params = data.get("params", {})
        sensor_config_req = data.get("sensor_config") or {}
        continuous_flag = bool(data.get("continuous", False))
        # Nota: la lógica de "parar al llegar" para ir_posicion se define en el protocolo
        # Normalización mínima desde UI: mapear volumenObjetivoML -> volume_ml si viene así
        if "volumenObjetivoML" in params and "volume_ml" not in params:
            try:
                params["volume_ml"] = float(params.get("volumenObjetivoML"))
            except Exception:
                pass
        auto_stop = bool(data.get("auto_stop", True))
        mode = data.get("mode", "sync")  # sync o async
        # Si el cliente define sensor_config, pasarlo al protocolo (runner lo tomará)
        if isinstance(sensor_config_req, dict) and sensor_config_req:
            params.setdefault("sensor_config", sensor_config_req)
        else:
            # Si no viene sensor_config, usar el del runner (todos habilitados por defecto)
            try:
                params.setdefault("sensor_config", getattr(protocol_runner, "_sensor_config", {}))
            except Exception:
                pass

        # Mapear objetivos simples desde UI a nombres internos del runner
        try:
            logger.log(f"Parámetros antes del mapeo: {params}")
            if "x_mm" in params and "target_x_mm" not in params:
                params["target_x_mm"] = float(params.get("x_mm"))
            if "a_deg" in params and "target_a_deg" not in params:
                params["target_a_deg"] = float(params.get("a_deg"))
            # Umbrales: permitir "threshold" único o específicos
            thr = params.get("threshold")
            if thr is not None:
                try:
                    fthr = float(thr)
                    params.setdefault("threshold_x_mm", fthr)
                    params.setdefault("threshold_a_deg", fthr)
                except Exception:
                    pass
            logger.log(f"Parámetros después del mapeo: {params}")
        except Exception:
            pass

        # Modo continuo (sin timeout) para protocolos en loop
        if continuous_flag:
            params["continuous_mode"] = True
            auto_stop = False
            # Asegurar un timeout alto por compatibilidad (TaskExecutor)
            timeout_seconds = max(timeout_seconds, 3600.0)
        # Límites por tiempo/reward
        max_dur = data.get("max_duration_seconds")
        reward_key = data.get("reward_key")
        reward_threshold = data.get("reward_threshold")
        if max_dur is not None:
            try:
                params["task_controlled"] = True
                params["task_duration"] = float(max_dur)
            except Exception:
                pass
        # Asegurar control por duración si vino duration_seconds explícito
        try:
            if duration_seconds and duration_seconds>0:
                params["task_controlled"] = True
                params["task_duration"] = float(duration_seconds)
        except Exception:
            pass
        if reward_key:
            params["reward_key"] = str(reward_key)
            try:
                if reward_threshold is not None:
                    params["reward_threshold"] = float(reward_threshold)
            except Exception:
                pass
        
        # Evitar múltiples ejecuciones paralelas (simple guard) pero tolerar estados obsoletos
        try:
            active = task_executor.list_active_tasks()
            runner_active = False
            try:
                st = protocol_runner.status()
                runner_active = bool(getattr(st, 'activo', False))
            except Exception:
                runner_active = False
            if runner_active:
                logger.log("Ejecución rechazada: runner activo", "WARN")
                return jsonify({
                    "error": "Ya hay una ejecución en curso. Detén la actual antes de iniciar otra.",
                    "active": [ {"task_id": getattr(t,'task_id',None), "status": getattr(getattr(t,'status',None),'value',None), "started_at": getattr(t,'started_at',None)} for t in (active or []) ]
                }), 409
            # Si el runner NO está activo, permitimos lanzar aunque el ejecutor reporte items antiguos
        except Exception:
            pass

        # Crear definición de tarea
        task_def = task_executor.create_task_definition(
            name=name,
            protocol_name=protocol_name,
            duration_seconds=duration_seconds,
            timeout_seconds=timeout_seconds,
            params=params,
            auto_stop=auto_stop
        )
        
        # Helper para filtrar sensores
        def _filter_sensors(snapshot: dict, cfg: dict) -> dict:
            if not isinstance(snapshot, dict):
                return {}
            if not isinstance(cfg, dict) or not cfg:
                return snapshot
            return {k: v for k, v in snapshot.items() if cfg.get(k, True)}

        # Ejecutar según el modo
        if mode == "sync":
            # Ejecución síncrona - esperar hasta completar o timeout
            result = task_executor.execute_task(task_def, ExecutionMode.SYNC)
            # Sensores finales filtrados
            try:
                st = protocol_runner.status()
                sensors = _filter_sensors(st.final_obs or {}, sensor_config_req or getattr(protocol_runner, '_sensor_config', {}) )
            except Exception:
                sensors = {}
            logger.log(f"/api/tasks/execute sync FIN: {result.status.value} dur={result.duration}s")
            return jsonify({
                "status": "completed",
                "task_id": result.task_id,
                "execution_status": result.status.value,
                "duration": result.duration,
                "result": None,
                "sensors": sensors,
                "error": result.error,
                "log": result.log,
                "completed_at": datetime.now().isoformat(),
                "message": "Ejecución finalizada; controles habilitados"
            })
        else:
            # Ejecución asíncrona - devolver execution_id
            execution_id = task_executor.execute_task(task_def, ExecutionMode.ASYNC)
            logger.log(f"/api/tasks/execute async INICIADA: eid={execution_id} task={task_def.id}")
            # Snapshot de sensores actuales para clientes lentos
            try:
                rs = get_robot_status()
                snap = asdict(rs)
            except Exception:
                snap = {}
            sensors = _filter_sensors(snap, sensor_config_req or {})

            return jsonify({
                "status": "executing",
                "execution_id": execution_id,
                "task_id": task_def.id,
                "estimated_duration": duration_seconds,
                "timeout_seconds": timeout_seconds,
                "started_at": datetime.now().isoformat(),
                "message": f"Tarea '{name}' ejecutándose. Controles deshabilitados hasta finalizar.",
                "sensors": sensors
            })
        
    except Exception as e:
        logger.log(f"Error ejecutando tarea v2: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

# =============================================================================
# COMPATIBILIDAD: /api/execute y tracking de ejecuciones
# =============================================================================

# Estructura simple de tracking para compatibilidad con la UI
_exec_lock = threading.Lock()
_active_exec: Dict[str, Dict[str, Any]] = {}
_recent_exec: List[Dict[str, Any]] = []
_taskq_lock = threading.Lock()
_task_queue: deque = deque()

def _track_exec_start(kind: str, target_id: str) -> str:
    eid = f"exec_{int(time.time()*1000)}"
    with _exec_lock:
        _active_exec[eid] = {
            "execution_id": eid,
            "type": kind,
            "target_id": target_id,
            "status": "running",
            "started_at": time.time(),
            "log": []
        }
    return eid

def _track_exec_end(eid: str, status: str):
    with _exec_lock:
        item = _active_exec.pop(eid, None)
        if not item:
            return
        item["status"] = status
        item["ended_at"] = time.time()
        _recent_exec.insert(0, item)
        # limitar historial
        if len(_recent_exec) > 50:
            _recent_exec[:] = _recent_exec[:50]

@app.route("/api/executions", methods=["GET"])
def api_executions_list():
    with _exec_lock:
        return jsonify({
            "active_executions": list(_active_exec.values()),
            "recent_executions": list(_recent_exec[:20])
        })

@app.route("/api/execution/<execution_id>", methods=["GET"])
def api_execution_get(execution_id: str):
    # Buscar en TaskExecutor
    try:
        st = task_executor.get_task_status(execution_id)
        if st:
            return jsonify({
                "execution_id": execution_id,
                "status": st.status.value,
                "started_at": st.started_at,
                "ended_at": st.ended_at,
                "log": st.log,
                "progress": st.progress,
                "type": "task",
                "target_id": st.result.get("protocol_name") if isinstance(st.result, dict) else None
            })
    except Exception:
        pass
    # Fallback a tracker local
    with _exec_lock:
        item = _active_exec.get(execution_id) or next((x for x in _recent_exec if x.get("execution_id")==execution_id), None)
        if not item:
            return jsonify({"error": "No encontrado"}), 404
        return jsonify(item)

@app.route("/api/execution/<execution_id>/stop", methods=["POST"])
def api_execution_stop(execution_id: str):
    try:
        # Manejar caso especial de protocolo_activo
        if execution_id == "protocolo_activo":
            protocol_runner.stop()
            return jsonify({"status": "stopped", "execution_id": execution_id})
        
        if task_executor.stop_task(execution_id):
            _track_exec_end(execution_id, "stopped")
            return jsonify({"status": "stopped", "execution_id": execution_id})
        # Fallback: marcar como detenido en tracker local
        _track_exec_end(execution_id, "stopped")
        return jsonify({"status": "stopped", "execution_id": execution_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/serial/ports")
def api_serial_ports():
    """API para listar puertos serial"""
    # Determinar si es virtual basado en el perfil activo y el entorno
    profile = ROBOT_PROFILES.get(active_robot_id or "real", {})
    profile_is_virtual = profile.get("is_virtual", False)
    env_is_virtual = bool(getattr(robot_env, "is_virtual", False))
    
    # Es virtual si el perfil lo dice (prioridad) o el entorno lo reporta
    is_virtual = profile_is_virtual or env_is_virtual

    ports = list_serial_ports()
    if is_virtual:
        ports = ["VIRTUAL"]
        
    ser = getattr(robot_env, "ser", None)
    open_state = bool(ser and getattr(ser, "is_open", False))
    
    if is_virtual:
        open_state = True
        if robot_env and not getattr(robot_env, "port", None):
            try:
                robot_env.port = "VIRTUAL"
            except Exception:
                pass

    current_port = getattr(robot_env, "port", None) if robot_env else None

    return jsonify({
        "ports": ports,
        "current": current_port,
        "open": open_state,
        "is_virtual": is_virtual,
        "robot_id": active_robot_id
    })

@app.route("/api/serial/open", methods=["POST"])
def api_serial_open():
    """API para abrir puerto serial"""
    try:
        data = get_request_data()
        port = data.get("port", DEFAULT_SERIAL_PORT)
        baud = int(data.get("baudrate", DEFAULT_BAUDRATE))

        if getattr(robot_env, "is_virtual", False):
            robot_env.port = "VIRTUAL"
            robot_env.baudrate = baud
            return jsonify({
                "status": "ok",
                "port": "VIRTUAL",
                "baudrate": baud,
                "open": True,
                "virtual": True,
            })
        
        with env_lock:
            # Usar métodos existentes de reloj_env.py
            if port != robot_env.port:
                # Cambiar puerto usando método existente
                robot_env.port_s = port
                robot_env.port = port
                robot_env.baudrate = baud
                robot_env.baud = baud
                robot_env._ser_open()  # ✅ Método existente
            else:
                robot_env.baudrate = baud
                robot_env.baud = baud
                robot_env._ser_open()  # ✅ Método existente
        
        logger.log(f"Puerto serial abierto: {port}")
        return jsonify({
            "status": "ok",
            "port": robot_env.port,
            "baudrate": robot_env.baudrate,
            "open": robot_env.ser and robot_env.ser.is_open
        })
        
    except Exception as e:
        logger.log(f"Error abriendo puerto serial: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500

@app.route("/api/serial/close", methods=["POST"])
def api_serial_close():
    """API para cerrar puerto serial"""
    try:
        if getattr(robot_env, "is_virtual", False):
            return jsonify({
                "status": "ok",
                "port": "VIRTUAL",
                "open": False,
                "virtual": True,
            })
        with env_lock:
            # Usar método existente
            if robot_env.ser:
                robot_env.ser.close()  # ✅ Método existente
        
        logger.log("Puerto serial cerrado")
        return jsonify({
            "status": "ok",
            "port": robot_env.port,
            "open": False
        })
        
    except Exception as e:
        logger.log(f"Error cerrando puerto serial: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500

## Versión mínima: sin rutas de conexión rápida

## Versión mínima: sin API direccional

# PROMPT(safety): garantizar ejecución aunque ws/control falle
@app.route("/api/stop", methods=["POST"])
def api_stop():
    """API para detener inmediatamente todos los actuadores y apagar la bomba"""
    try:
        if not _is_serial_connected():
            logger.log("/api/stop rechazado: serial desconectado", "WARN")
            return jsonify({"error": "Serial desconectado"}), 409
        with env_lock:
            # Establecer energías a 0 y modo stop (códigoModo = 3)
            robot_env.set_energia_corredera(0)
            robot_env.set_energia_angulo(0)
            robot_env.set_energia_bomba(0)
            robot_env.set_volumen_objetivo_ml(0)
            robot_env.set_modo(cod=3)
            robot_env.step()

        return jsonify({"status": "stopped"})
    except Exception as e:
        logger.log(f"Error deteniendo robot: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500

@app.route("/api/home", methods=["POST"])
def api_home():
    """API para ir a posición home"""
    try:
        if not _is_serial_connected():
            logger.log("/api/home rechazado: serial desconectado", "WARN")
            return jsonify({"error": "Serial desconectado"}), 409
        with env_lock:
            robot_env.set_corredera_mm(0)
            robot_env.set_angulo_deg(0)
            robot_env.step()
        
        return jsonify({"status": "home"})
    except Exception as e:
        logger.log(f"Error yendo a home: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500

@app.route("/api/emergency_stop", methods=["POST"])
def api_emergency_stop():
    """API para parada de emergencia"""
    try:
        with env_lock:
            # Detener todo
            robot_env.set_energia_corredera(0)
            robot_env.set_energia_angulo(0)
            robot_env.set_energia_bomba(0)
            robot_env.set_modo(mx=False, ma=False)
            
            if robot_env.ser and robot_env.ser.is_open:
                robot_env.ser.close()
        
        logger.log("¡PARADA DE EMERGENCIA ACTIVADA!")
        return jsonify({"status": "emergency_stop"})
    except Exception as e:
        logger.log(f"Error en parada de emergencia: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500

# =============================================================================
# HILOS EN BACKGROUND
# =============================================================================
# HILOS EN BACKGROUND
# =============================================================================

def status_update_loop():
    """Hilo para actualización de estado del robot"""
    logger.log("Hilo de actualización de estado iniciado")
    error_count = 0
    while True:
        try:
            # Obtener estado (lee RX)
            get_robot_status()
            # Enviar keepalive de TX con el vector actual para asegurar recepción continua en el firmware
            try:
                with env_lock:
                    if hasattr(robot_env, 'ser') and robot_env.ser and robot_env.ser.is_open:
                        robot_env.step()
                        _set_last_tx("{\"keepalive\":true}")
            except Exception:
                pass
            error_count = 0  # Reset error count on success
            time.sleep(0.05)  # 20 Hz
        except Exception as e:
            error_count += 1
            if error_count <= 3:  # Solo logear los primeros 3 errores
                logger.log(f"Error en actualización de estado: {e}", "ERROR")
            elif error_count == 4:
                logger.log("Silenciando errores de actualización de estado...", "WARNING")
            time.sleep(1.0)



# =============================================================================
# INICIALIZACIÓN Y MAIN
# =============================================================================

def initialize_system():
    """Inicializa el sistema completo"""
    logger.log("Iniciando Sistema Robot Reloj v2.0 Compatible")
    profile = _runtime_summary(active_robot_id or "real")
    logger.log(f"Robot activo inicial: {profile['label']} ({profile['id']})")
    
    # Desactivar scheduler por defecto y sanear tareas inline sin 'code'
    reset_scheduler_defaults()
    
    # Verificar estado de conexión inicial
    try:
        if hasattr(robot_env, 'ser') and robot_env.ser and robot_env.ser.is_open:
            logger.log(f"OK: Robot conectado en {robot_env.port}")
        else:
            logger.log(f"WARNING: Robot no conectado en {getattr(robot_env,'port',None)} - Activando modo virtual si est3 disponible")
            # Si no hay hardware conectado, pasar autom3ticamente al perfil virtual (si existe)
            if 'virtual' in ROBOT_PROFILES and active_robot_id != 'virtual':
                try:
                    logger.log("Cambiando a robot virtual por ausencia de hardware")
                    switch_robot('virtual', start_scheduler=False)
                except Exception as _exc:
                    logger.log(f"WARNING: No se pudo activar el robot virtual: {_exc}")
    except Exception as e:
        logger.log(f"WARNING: Error verificando conexión: {e} - Modo demo activado")
    
    # Iniciar hilos en background
    threading.Thread(target=status_update_loop, daemon=True).start()
    
    # Iniciar el nuevo programador de tareas
    task_scheduler.start()
    
    # Cargar settings guardados y aplicarlos
    apply_persisted_settings()
    
    logger.log("Sistema iniciado correctamente")
    _start_visualizer()


def _start_visualizer() -> bool:
    """Inicializa el visualizador PyBullet si es posible."""
    global visualizer
    if PyBulletVisualizer is None:
        logger.log("[Visualizer] PyBulletVisualizer es None (import falló previamente)", "ERROR")
        visualizer = None
        return False
    logger.log("[Visualizer] Intentando iniciar PyBulletVisualizer...")
    try:
        # Preferimos el URDF incluido en el repo bajo 'Robot Virtual/Robot Virtual/urdf'
        candidates = [
            (BASE_DIR / "Robot Virtual" / "Robot Virtual" / "urdf" / "Reloj_1.xacro").resolve(),
            (BASE_DIR.parent / "Protocolo_Reloj" / "Reloj_1_description" / "urdf" / "Reloj_1.xacro").resolve(),
        ]
        chosen = None
        for path in candidates:
            if path.exists():
                chosen = path
                break
        # Crear visualizador con resolución moderada para fluidez en CPU (TinyRenderer)
        visualizer = PyBulletVisualizer(str(chosen) if chosen else "", width=640, height=360)
        if chosen:
            logger.log(f"Visualizador PyBullet iniciado con URDF: {chosen} ({visualizer.width}x{visualizer.height})")
        else:
            logger.log("Visualizador PyBullet iniciado en modo simplificado (sin URDF)")
        return True
    except Exception as e:
        visualizer = None
        logger.log(f"WARNING: Visualizador PyBullet deshabilitado: {e}")
        return False




if __name__ == "__main__":
    initialize_system()
    
    PORT = int(os.environ.get("RELOJ_PORT", "5005"))
    logger.log(f"Servidor iniciando en puerto {PORT}")
    logger.log(f"Directorio base: {BASE_DIR}")
    logger.log(f"Puerto serial: {robot_env.port}")
    logger.log(f"Usando sistema de tareas existente de reloj_env.py")
    
    # Función para abrir el navegador automáticamente
    def open_browser():
        """Abre la interfaz del Reloj en el navegador por defecto."""
        time.sleep(1.5)
        url = f"http://127.0.0.1:{PORT}/"
        try:
            logger.log(f"WEB: Abriendo navegador automáticamente: {url}")
            webbrowser.open(url, new=1, autoraise=True)
        except Exception as exc:
            logger.log(f"WARNING: Error abriendo navegador: {exc} (seguirá ejecutando)")
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Handler silencioso para no imprimir 'GET ... 200' en consola
    QuietHandler = None
    if _WerkReq is not None:
        class QuietHandler(_WerkReq):  # type: ignore
            def log(self, type, message, *args):
                pass
            def log_request(self, *args, **kwargs):
                pass

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
        request_handler=QuietHandler if QuietHandler is not None else None,
    )
# Silenciar logs verbosos de HTTP (por ejemplo, /api/pybullet/frame) y dejar nuestros debug propios
try:
    # Reduce o desactiva logs HTTP del devserver (GET ... 200)
    wl = logging.getLogger('werkzeug')
    wl.setLevel(logging.ERROR)
    wl.disabled = True
    app.logger.disabled = True  # solo afecta a app.logger, no a nuestro RobotLogger
except Exception:
    pass
