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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from contextlib import nullcontext

from flask import Flask, request, jsonify, Response

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
from protocolos import ProtocolRunner, Protocolo
from task_executor import TaskExecutor, TaskDefinition, ExecutionMode, TaskStatus
from task_scheduler import TaskScheduler, TaskSchedule, ScheduleType
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
import sys
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

# Crear directorios si no existen
for directory in [DATA_DIR, PROTOCOLS_DIR, TEMPLATES_DIR, STATIC_DIR, LOGS_DIR]:
    directory.mkdir(exist_ok=True)

# Archivos de datos
SETTINGS_FILE = DATA_DIR / "settings_ui.json"

# Inicializar archivos si no existen
if not SETTINGS_FILE.exists():
    SETTINGS_FILE.write_text('{"version":1}', encoding="utf-8")

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
    reward: float = 0.0
    robot_id: str = "real"
    robot_label: str = ""
    robot_kind: str = "hardware"
    is_virtual: bool = False



# =============================================================================
# SISTEMA DE LOGGING
# =============================================================================

class RobotLogger:
    """Sistema de logging circular para el robot"""
    
    def __init__(self, capacity: int = 1000):
        self._capacity = capacity
        self._buffer: List[str] = []
        self._lock = threading.Lock()
    
    def log(self, message: str, level: str = "INFO"):
        """Registra un mensaje con timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        
        with self._lock:
            self._buffer.append(log_entry)
            if len(self._buffer) > self._capacity:
                self._buffer = self._buffer[-self._capacity:]
        
        print(log_entry, flush=True)
    
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
            static_folder=str(STATIC_DIR))

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

def _set_last_rx(txt: str):
    global last_rx_text
    global last_rx_ts
    last_rx_text = txt.strip(); last_rx_ts = time.time()


def _set_last_tx(txt: str):
    global last_tx_text, last_tx_ts
    last_tx_text = txt.strip(); last_tx_ts = time.time()

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
                    obs = obs_arr.tolist()
                    _set_last_rx(" ".join(f"{v:.2f}" for v in obs))
                    print(f"[DEBUG] get_robot_status: Datos frescos - X={obs[0]}, A={obs[1]}, Z={obs[21] if len(obs) > 21 else 'N/A'}")
                else:
                    print("[DEBUG] get_robot_status: No hay datos frescos disponibles")
                    obs = [0.0]*21
            else:
                # Sin RX reciente: usar caché si existe
                if last_status_cache is not None:
                    cached_dict = asdict(last_status_cache)
                    cached_dict["stale"] = True
                    # Actualizar edad de RX
                    try:
                        cached_dict["rx_age_ms"] = int(max(0.0, time.time() - last_rx_ts) * 1000)
                    except Exception:
                        cached_dict["rx_age_ms"] = 0
                    print(f"[DEBUG] get_robot_status: Usando caché - X={cached_dict.get('x_mm', 0)}, A={cached_dict.get('a_deg', 0)}")
                    return RobotStatus(**cached_dict)
                # Sin caché disponible: caerá a valores por defecto (ceros)
                obs = [0.0]*21
                print("[DEBUG] get_robot_status: Usando valores por defecto (ceros)")

            # Conexión serial actual
            ser = getattr(robot_env, "ser", None)
            status.serial_open = bool(ser and ser.is_open)
            status.serial_port = robot_env.port
            try:
                status.baudrate = int(getattr(robot_env, 'baudrate', DEFAULT_BAUDRATE) or DEFAULT_BAUDRATE)
            except Exception:
                status.baudrate = DEFAULT_BAUDRATE

            if len(obs) >= 21:
                status.x_mm       = float(obs[0])
                status.a_deg      = float(obs[1])
                status.volumen_ml = float(obs[3])
                status.lim_x      = int(obs[4])
                status.lim_a      = int(obs[5])
                status.homing_x   = int(obs[6])
                status.homing_a   = int(obs[7])
                status.modo       = int(obs[11])
                # PID gains desde RX (indices 12..17)
                status.kpX        = float(obs[12])
                status.kiX        = float(obs[13])
                status.kdX        = float(obs[14])
                status.kpA        = float(obs[15])
                status.kiA        = float(obs[16])
                status.kdA        = float(obs[17])
                # Calibraciones desde RX (si el firmware las reporta)
                status.pasosPorMM    = float(obs[18])
                status.pasosPorGrado = float(obs[19])

            # Z desde RX si está presente (índice 21): ahora en mm
            had_z_from_rx = False
            try:
                if len(obs) >= 22:
                    status.z_mm = float(obs[21])
                    had_z_from_rx = True
            except Exception:
                pass

            # Energías y Z desde el último comando TX (vector de acción actual)
            try:
                act = getattr(robot_env, 'act', None)
                if act is not None and len(act) >= 4:
                    # ALIAS: energiaA=1, energiaX=2, energiaBomba=3
                    status.energies = {
                        "x": int(act[2]),
                        "a": int(act[1]),
                        "bomba": int(act[3])
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
                if prev_ts and now_ts > prev_ts:
                    dvol = max(0.0, status.volumen_ml - prev_vol)
                    dt = now_ts - prev_ts
                    deriv = dvol / dt if dt > 0 else 0.0
                    # Si no se usa sensor de flujo, estimar con caudalBombaMLs cuando bomba activa
                    if status.usarSensorFlujo:
                        status.caudal_est_mls = float(deriv)
                    else:
                        status.caudal_est_mls = float(status.energies.get("bomba", 0) != 0 and status.caudalBombaMLs or 0.0)
                setattr(get_robot_status, "_last_vol_ts", now_ts)
                setattr(get_robot_status, "_last_vol_ml", status.volumen_ml)
            except Exception:
                pass

            status.flow_est = float(status.caudal_est_mls or 0.0)
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
    """Indica si el puerto serial está abierto y listo para operar."""
    try:
        return hasattr(robot_env, 'ser') and robot_env.ser and robot_env.ser.is_open
    except Exception:
        return False

def list_serial_ports() -> List[str]:
    """Lista puertos serial disponibles"""
    if not SERIAL_AVAILABLE:
        return []
    
    try:
        return [p.device for p in list_ports.comports()]
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
            robot_env.step()
        except Exception as e:
            logger.log(f"[stop_all_actuators] Error apagando actuadores: {e}", "ERROR")

# === FILTRO DE ENDPOINTS PERMITIDOS ===

ALLOWED_ENDPOINTS = {
    "/",               # página principal
    "/calendar",       # vista calendario
    "/api/config",     # configuración básica
    "/api/serial/ports",
    "/api/serial/open",
    "/api/serial/close"
}

@app.before_request
def restrict_endpoints():
    path = request.path
    if path.startswith( ("/static", "/favicon.ico") ):
        return  # recursos estáticos permitidos
    # Permitir APIs mínimas
    allowed_prefixes = ("/api/", "/serial/", "/entorno/", "/control", "/debug/", "/robots")
    if path in {"/"} or path.startswith(allowed_prefixes):
        return  # permitido
    # bloquea cualquier ruta antigua no usada (por ejemplo /game, /calendar eliminada)
    return jsonify({"error": "Endpoint deshabilitado"}), 404

# =============================================================================
# RAÍZ MÍNIMA
# =============================================================================

@app.route("/")
def root_index():
    # Mostrar la interfaz HTML existente
    from flask import render_template  # import local para mantener import global mínimo
    return render_template("reloj.html")

@app.route("/api")
def api_index():
    return jsonify({
        "name": "Robot Reloj API",
        "version": "1.0",
        "endpoints": {
            "status": "/api/status",
            "serial": {
                "ports": "/api/serial/ports",
                "open": "/api/serial/open",
                "close": "/api/serial/close"
            },
            "control": "/api/control",
            "protocols": {
                "list": "/api/protocols",
                "execute": "/api/protocols/<name>/execute",
                "status": "/api/protocols/status",
                "stop": "/api/protocols/stop"
            },
            "tasks": {
                "execute": "/api/tasks/execute",
                "execute_id": "/api/tasks/<task_id>/execute",
                "list": "/api/tasks"
            }
        }
    })

## Versión mínima: sin rutas de UI

@app.route("/api/status")
def api_status():
    """API para obtener estado del robot"""
    status = get_robot_status()
    return jsonify(asdict(status))

@app.route("/api/status/fresh")
def api_status_fresh():
    """API para obtener estado del robot forzando actualización de datos"""
    global last_status_cache
    # Limpiar caché para forzar actualización
    last_status_cache = None
    
    # Forzar actualización de datos del robot
    try:
        with env_lock:
            # Intentar obtener datos frescos del robot
            obs_arr = robot_env._obs_now()
            if obs_arr is not None:
                obs = obs_arr.tolist()
                _set_last_rx(" ".join(f"{v:.2f}" for v in obs))
                print(f"[DEBUG] Datos frescos obtenidos: X={obs[0]}, A={obs[1]}, Z={obs[21] if len(obs) > 21 else 'N/A'}")
            else:
                print("[DEBUG] No se obtuvieron datos frescos del robot")
    except Exception as e:
        print(f"[DEBUG] Error obteniendo datos frescos: {e}")
    
    status = get_robot_status(force_fresh=True)
    return jsonify(asdict(status))

@app.route("/api/visual/frame")
def api_visual_frame():
    if visualizer is None:
        logger.log("[Visualizer] unavailable (not initialized)", "WARNING")
        return jsonify({"error": "visualizer unavailable"}), 503
    frame = None
    try:
        frame = visualizer.render_frame()
    except Exception as exc:
        logger.log(f"[Visualizer] render exception: {exc}", "WARNING")
        frame = None
    if not frame:
        detail = getattr(visualizer, "last_error", None)
        if detail:
            logger.log(f"[Visualizer] frame unavailable: {detail}", "WARNING")
        return jsonify({"error": "frame unavailable", "detail": detail}), 503
    mime = getattr(visualizer, "mimetype", "image/jpeg")
    response = Response(frame, mimetype=mime)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/visual/debug")
def api_visual_debug():
    if visualizer is None:
        return jsonify({
            "available": False,
            "reason": "not initialized",
            "imported": PyBulletVisualizer is not None,
            "search_paths": [
                str((BASE_DIR.parent / "Protocolo_Reloj" / "Reloj_1_description" / "urdf" / "Reloj_1.xacro").resolve()),
                str((BASE_DIR / "Robot Virtual" / "Robot Virtual" / "urdf" / "Reloj_1.xacro").resolve()),
            ],
        })
    info = {
        "available": True,
        "client_id": getattr(visualizer, "client_id", None),
        "robot_id": getattr(visualizer, "robot_id", None),
        "have_fallback": getattr(visualizer, "_have_fallback", False),
        "mimetype": getattr(visualizer, "mimetype", None),
        "last_error": getattr(visualizer, "last_error", None),
        "size": [getattr(visualizer, "width", None), getattr(visualizer, "height", None)],
        "urdf": getattr(visualizer, "robot_urdf", None),
        "resolved_urdf": getattr(visualizer, "_debug_urdf_path", None),
        "package_dir": getattr(visualizer, "_debug_pkg_dir", None),
    }
    return jsonify(info)


@app.route("/api/visual/init", methods=["POST"])
def api_visual_init():
    ok = _start_visualizer()
    return jsonify({"ok": ok, "available": visualizer is not None})


@app.route("/api/visual/gui/status")
def api_visual_gui_status():
    return jsonify({"running": _pb_gui_is_running()})


@app.route("/api/visual/gui/start", methods=["POST"])
def api_visual_gui_start():
    ok = _pb_gui_start()
    if not ok:
        return jsonify({"ok": False}), 500
    return jsonify({"ok": True, "running": True})


@app.route("/api/visual/gui/stop", methods=["POST"])
def api_visual_gui_stop():
    ok = _pb_gui_stop()
    if not ok:
        return jsonify({"ok": False}), 500
    return jsonify({"ok": True, "running": False})

@app.route("/api/debug/raw_obs")
def api_debug_raw_obs():
    """API para debug - obtener observaciones raw del robot"""
    try:
        with env_lock:
            obs_arr = robot_env._obs_now()
            if obs_arr is not None:
                obs_list = obs_arr.tolist()
                return jsonify({
                    "raw_obs": obs_list,
                    "length": len(obs_list),
                    "x_mm": obs_list[0] if len(obs_list) > 0 else None,
                    "a_deg": obs_list[1] if len(obs_list) > 1 else None,
                    "z_mm": obs_list[21] if len(obs_list) > 21 else None,
                    "timestamp": time.time()
                })
            else:
                return jsonify({
                    "raw_obs": None,
                    "error": "No data available",
                    "timestamp": time.time()
                })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "timestamp": time.time()
        })

def parse_robot_response(response_text):
    """Parsea la respuesta del robot y la convierte a array de observaciones"""
    try:
        # Limpiar la respuesta
        response = response_text.strip()
        if response.startswith('.'):
            response = response[1:]  # Quitar el punto inicial
        if response.endswith(','):
            response = response[:-1]  # Quitar la coma final
        
        # Dividir por comas y convertir a float
        values = []
        for val in response.split(','):
            try:
                values.append(float(val.strip()))
            except ValueError:
                values.append(0.0)
        
        # Rellenar con ceros si no hay suficientes valores
        while len(values) < 22:
            values.append(0.0)
        
        print(f"[DEBUG] Respuesta parseada: {values[:10]}... (total: {len(values)})")
        return values
        
    except Exception as e:
        print(f"[DEBUG] Error parseando respuesta: {e}")
        return [0.0] * 22

@app.route("/api/debug/force_update")
def api_debug_force_update():
    """API para debug - forzar actualización completa de datos"""
    global last_status_cache, last_rx_ts, last_rx_text
    
    try:
        # Limpiar todo el caché
        last_status_cache = None
        last_rx_ts = None
        last_rx_text = None
        
        # Diagnóstico completo de la comunicación
        debug_info = {
            "serial_available": hasattr(robot_env, 'ser'),
            "serial_open": False,
            "serial_port": None,
            "baudrate": None,
            "queue_size": 0,
            "last_rx_ts": last_rx_ts,
            "last_rx_text": last_rx_text,
            "obs_arr": None,
            "obs_length": 0
        }
        
        # Verificar estado de la comunicación serial
        if hasattr(robot_env, 'ser'):
            debug_info["serial_open"] = robot_env.ser.is_open if robot_env.ser else False
            debug_info["serial_port"] = getattr(robot_env, 'port', None)
            debug_info["baudrate"] = getattr(robot_env, 'baudrate', None)
            
            if hasattr(robot_env, 'q'):
                debug_info["queue_size"] = robot_env.q.qsize()
        
        # Forzar actualización de datos
        with env_lock:
            # Intentar obtener datos frescos del sistema normal
            obs_arr = robot_env._obs_now()
            debug_info["obs_arr"] = obs_arr is not None
            debug_info["obs_length"] = len(obs_arr) if obs_arr is not None else 0
            
            print(f"[DEBUG] Diagnóstico completo:")
            print(f"  Serial disponible: {debug_info['serial_available']}")
            print(f"  Serial abierto: {debug_info['serial_open']}")
            print(f"  Puerto: {debug_info['serial_port']}")
            print(f"  Baudrate: {debug_info['baudrate']}")
            print(f"  Tamaño cola: {debug_info['queue_size']}")
            print(f"  Última RX: {debug_info['last_rx_ts']}")
            print(f"  Texto RX: {debug_info['last_rx_text']}")
            print(f"  Obs array: {debug_info['obs_arr']}")
            print(f"  Longitud obs: {debug_info['obs_length']}")
            
            # Si no hay datos del sistema normal, obtener datos directamente del serial
            if obs_arr is None and debug_info["serial_open"]:
                print("[DEBUG] Obteniendo datos directamente del serial...")
                try:
                    # Enviar comando STATUS y obtener respuesta
                    robot_env.ser.write("STATUS\n".encode())
                    robot_env.ser.flush()
                    
                    # Leer respuesta
                    response = ""
                    start_time = time.time()
                    timeout = 1.0
                    
                    while time.time() - start_time < timeout:
                        if robot_env.ser.in_waiting > 0:
                            data = robot_env.ser.read(robot_env.ser.in_waiting)
                            response += data.decode('utf-8', errors='ignore')
                            if '\n' in response:
                                break
                        time.sleep(0.01)
                    
                    if response:
                        print(f"[DEBUG] Respuesta directa del serial: {response.strip()}")
                        obs = parse_robot_response(response.strip())
                        obs_arr = np.array(obs, dtype=np.float32)
                        debug_info["obs_arr"] = True
                        debug_info["obs_length"] = len(obs)
                        _set_last_rx(" ".join(f"{v:.2f}" for v in obs))
                        print(f"[DEBUG] Datos parseados - X={obs[0]}, A={obs[1]}, Z={obs[21] if len(obs) > 21 else 'N/A'}")
                except Exception as e:
                    print(f"[DEBUG] Error obteniendo datos del serial: {e}")
            
            if obs_arr is not None:
                obs = obs_arr.tolist()
                print(f"[DEBUG] Force update: Datos frescos - X={obs[0]}, A={obs[1]}, Z={obs[21] if len(obs) > 21 else 'N/A'}")
                
                # Crear status directamente
                status = RobotStatus()
                status.serial_open = debug_info["serial_open"]
                status.serial_port = debug_info["serial_port"]
                status.baudrate = debug_info["baudrate"] or DEFAULT_BAUDRATE
                
                if len(obs) >= 21:
                    status.x_mm = float(obs[0])
                    status.a_deg = float(obs[1])
                    status.volumen_ml = float(obs[3])
                    status.lim_x = int(obs[4])
                    status.lim_a = int(obs[5])
                    status.homing_x = int(obs[6])
                    status.homing_a = int(obs[7])
                    status.modo = int(obs[11])
                    status.kpX = float(obs[12])
                    status.kiX = float(obs[13])
                    status.kdX = float(obs[14])
                    status.kpA = float(obs[15])
                    status.kiA = float(obs[16])
                    status.kdA = float(obs[17])
                    status.pasosPorMM = float(obs[18])
                    status.pasosPorGrado = float(obs[19])
                
                if len(obs) >= 22:
                    status.z_mm = float(obs[21])
                
                return jsonify({
                    "success": True,
                    "status": asdict(status),
                    "raw_obs": obs,
                    "debug_info": debug_info,
                    "timestamp": time.time()
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "No data available from robot",
                    "debug_info": debug_info,
                    "timestamp": time.time()
                })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "debug_info": debug_info if 'debug_info' in locals() else {},
            "timestamp": time.time()
        })

@app.route("/api/debug/serial_connect")
def api_debug_serial_connect():
    """API para abrir la conexión serial automáticamente"""
    try:
        # Verificar si ya está abierto
        if hasattr(robot_env, 'ser') and robot_env.ser and robot_env.ser.is_open:
            return jsonify({
                "success": True,
                "message": "Puerto serial ya está abierto",
                "port": robot_env.port,
                "baudrate": getattr(robot_env, 'baudrate', DEFAULT_BAUDRATE),
                "timestamp": time.time()
            })
        
        # Intentar abrir la conexión serial
        port = robot_env.port or "COM3"
        baudrate = getattr(robot_env, 'baudrate', DEFAULT_BAUDRATE) or DEFAULT_BAUDRATE
        
        print(f"[DEBUG] Intentando abrir puerto serial: {port} @ {baudrate}")
        
        # Importar serial si no está disponible
        try:
            import serial
        except ImportError:
            return jsonify({
                "success": False,
                "error": "Módulo serial no disponible",
                "timestamp": time.time()
            })
        
        # Crear conexión serial
        ser = serial.Serial(port, baudrate, timeout=1)
        robot_env.ser = ser
        robot_env.port = port
        robot_env.baudrate = baudrate
        
        # Esperar un poco para que se establezca la conexión
        time.sleep(0.5)
        
        return jsonify({
            "success": True,
            "message": "Puerto serial abierto exitosamente",
            "port": port,
            "baudrate": baudrate,
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Error abriendo puerto serial: {str(e)}",
            "timestamp": time.time()
        })

@app.route("/api/debug/serial_test")
def api_debug_serial_test():
    """API para probar la comunicación serial con el robot"""
    try:
        # Primero intentar abrir la conexión si no está abierta
        if not hasattr(robot_env, 'ser') or not robot_env.ser or not robot_env.ser.is_open:
            # Intentar abrir automáticamente
            connect_response = api_debug_serial_connect()
            if not connect_response[0].get('success', False):
                return jsonify({
                    "success": False,
                    "error": "No se pudo abrir el puerto serial",
                    "connect_error": connect_response[0].get('error', 'Unknown error'),
                    "timestamp": time.time()
                })
        
        # Enviar comando de prueba al robot
        test_command = "STATUS\n"
        robot_env.ser.write(test_command.encode())
        robot_env.ser.flush()
        
        # Esperar respuesta
        response = ""
        start_time = time.time()
        timeout = 2.0  # 2 segundos de timeout
        
        while time.time() - start_time < timeout:
            if robot_env.ser.in_waiting > 0:
                data = robot_env.ser.read(robot_env.ser.in_waiting)
                response += data.decode('utf-8', errors='ignore')
                if '\n' in response:
                    break
            time.sleep(0.01)
        
        return jsonify({
            "success": True,
            "command_sent": test_command.strip(),
            "response": response.strip(),
            "response_length": len(response),
            "timeout_reached": time.time() - start_time >= timeout,
            "timestamp": time.time()
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "timestamp": time.time()
        })

@app.route("/api/health")
def api_health():
    """API de salud del sistema"""
    # Verificar estado de conexión
    connection_status = "disconnected"
    try:
        if hasattr(robot_env, 'ser') and robot_env.ser and robot_env.ser.is_open:
            connection_status = "connected"
        else:
            connection_status = "disconnected"
    except:
        connection_status = "error"
    
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0 Compatible",
        "robot_connection": connection_status,
        "serial_port": robot_env.port
    })

# === CONFIG ENDPOINT ===

@app.route("/api/config", methods=["GET"])
def api_config():
    """Devuelve configuración básica necesaria para la UI mínima."""
    return jsonify({
        "serial_port": robot_env.port,
        "baudrate": robot_env.baudrate,
        "robot_connected": getattr(robot_env, 'ser', None) is not None and getattr(robot_env.ser, 'is_open', False)
    })

# === SETTINGS (guardar/cargar) ===

def _load_settings_dict() -> dict:
    try:
        txt = SETTINGS_FILE.read_text(encoding="utf-8")
        return json.loads(txt or "{}")
    except Exception:
        return {}

def _save_settings_dict(d: dict) -> bool:
    try:
        SETTINGS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False

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
# RUTAS DE CONTROL DEL ROBOT (CORREGIDAS PARA COMPATIBILIDAD)
# =============================================================================

@app.route("/api/control", methods=["POST"])
def api_control():
    """API para control del robot"""
    try:
        if not _is_serial_connected():
            logger.log("/api/control rechazado: serial desconectado", "WARN")
            return jsonify({
                "error": "Serial desconectado. No se pueden enviar comandos.",
                "robot_connection": "disconnected"
            }), 409
        data = get_request_data()
        logger.log(f"/api/control payload: {data}")
        logger.log(f"Control recibido: {data}")
        
        with env_lock:
            # Setpoints (USANDO MÉTODOS CORRECTOS)
            if "setpoints" in data:
                sp = data["setpoints"]
                if "x_mm" in sp:
                    robot_env.set_corredera_mm(float(sp["x_mm"]))  # ✅ Método correcto
                if "a_deg" in sp:
                    robot_env.set_angulo_deg(float(sp["a_deg"]))    # ✅ Método correcto
                if "volumen_ml" in sp:
                    robot_env.set_volumen_objetivo_ml(float(sp["volumen_ml"]))  # ✅ Método correcto
                # Z: puede venir en mm o grados
                if "z_mm" in sp:
                    robot_env.set_z_mm(float(sp["z_mm"]))
                if "servo_z_deg" in sp:
                    robot_env.set_servo_z_deg(float(sp["servo_z_deg"]))
            
            # Energías manuales (USANDO MÉTODOS CORRECTOS)
            if "energies" in data:
                en = data["energies"]
                if "x" in en:
                    robot_env.set_energia_corredera(int(en["x"]))  # ✅ Método correcto
                if "a" in en:
                    robot_env.set_energia_angulo(int(en["a"]))     # ✅ Método correcto
                if "bomba" in en:
                    robot_env.set_energia_bomba(int(en["bomba"]))  # ✅ Método correcto

            # Movimiento (velocidad Z en deg/s)
            if "motion" in data:
                mv = data["motion"] or {}
                if "z_speed_deg_s" in mv:
                    robot_env.set_servo_z_speed(float(mv["z_speed_deg_s"]))
            
            # PID (USANDO MÉTODOS CORRECTOS)
            if "pid_settings" in data:
                pid_settings = data["pid_settings"]
                if "pidX" in pid_settings:
                    pid = pid_settings["pidX"]
                    if all(k in pid for k in ["kp", "ki", "kd"]):
                        robot_env.set_pid_corredera(
                            float(pid["kp"]), float(pid["ki"]), float(pid["kd"])
                        )  # ✅ Método correcto
                
                if "pidA" in pid_settings:
                    pid = pid_settings["pidA"]
                    if all(k in pid for k in ["kp", "ki", "kd"]):
                        robot_env.set_pid_angulo(
                            float(pid["kp"]), float(pid["ki"]), float(pid["kd"])
                        )  # ✅ Método correcto

            # Calibración (pasos/mm y pasos/grado)
            if "calibration" in data:
                calib = data["calibration"] or {}
                if "steps_mm" in calib:
                    robot_env.set_pasos_por_mm(float(calib["steps_mm"]))
                if "steps_deg" in calib:
                    robot_env.set_pasos_por_grado(float(calib["steps_deg"]))

            # Flujo (sensor y caudal)
            if "flow" in data:
                fl = data["flow"] or {}
                if "usar_sensor_flujo" in fl:
                    robot_env.set_usar_sensor_flujo(bool(int(fl["usar_sensor_flujo"])) if isinstance(fl["usar_sensor_flujo"], (int, str)) else bool(fl["usar_sensor_flujo"]))
                if "caudal_bomba_mls" in fl:
                    robot_env.set_caudal_bomba_ml_s(float(fl["caudal_bomba_mls"]))
            
            # Modo (USANDO MÉTODOS CORRECTOS)
            if "modo" in data:
                modo = int(data["modo"])
                robot_env.set_modo(
                    mx=bool(modo & 1),
                    ma=bool(modo & 2)
                )  # ✅ Método correcto
            
            # Resets (USANDO MÉTODOS CORRECTOS)
            if data.get("reset_volumen"):
                robot_env.reset_volumen()  # ✅ Método correcto
            if data.get("reset_x"):
                robot_env.reset_x()        # ✅ Método correcto
            if data.get("reset_a"):
                robot_env.reset_a()        # ✅ Método correcto
            
            # Aplicar cambios
            robot_env.step()
            _set_last_tx(json.dumps(data))
        
        # Preparar respuesta con comandos aplicados
        commands_applied = {}
        if "setpoints" in data:
            commands_applied["setpoints"] = data["setpoints"]
        if "energies" in data:
            commands_applied["energies"] = data["energies"]
        if "motion" in data:
            commands_applied["motion"] = data["motion"]
        if "pid_settings" in data:
            commands_applied["pid_settings"] = data["pid_settings"]
        if "modo" in data:
            commands_applied["modo"] = data["modo"]
        
        return jsonify({
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "commands_applied": commands_applied
        })
        
    except Exception as e:
        logger.log(f"Error en control: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

# =============================================================================
# ENDPOINTS DE POLÍTICAS Y SCHEDULER
# =============================================================================

@app.route("/api/command_policy", methods=["POST"])
def api_command_policy():
    try:
        data = get_request_data() or {}
        pol = str(data.get("policy", "stop_only"))
        with env_lock:
            robot_env.set_command_policy(pol)
        return jsonify({"status": "ok", "policy": pol})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/scheduler", methods=["POST"])
def api_scheduler_toggle():
    try:
        data = get_request_data() or {}
        ena = bool(data.get("enabled", True))
        with env_lock:
            robot_env.set_scheduler_enabled(ena)
        return jsonify({"status": "ok", "enabled": ena})
    except Exception as e:
        return jsonify({"error": str(e)}), 400





@app.route("/api/protocols/<name>/execute", methods=["POST"])
def api_execute_protocol(name: str):
    """Activa el protocolo step-wise en el runner (reemplaza al anterior)."""
    try:
        if not _is_serial_connected():
            logger.log(f"/api/protocols/{name}/execute rechazado: serial desconectado", "WARN")
            return jsonify({"error": "Serial desconectado"}), 409
        data = get_request_data()
        logger.log(f"/api/protocols/{name}/execute payload: {data}")
        
        # Usar el payload completo como parámetros del protocolo
        # El payload ya contiene x_mm, a_deg, threshold, etc.
        params = data.copy() if data else {}
        
        # Permitir timeout y objetivos con umbral desde el body
        # params: { timeout_seconds?, target_x_mm?, target_a_deg?, threshold_x_mm?, threshold_a_deg? }
        # Permitir comandos durante ejecución de protocolo para que funcione
        try:
            with env_lock:
                robot_env.set_command_policy("all")
        except Exception:
            pass
        protocol_runner.activate(name, params=params)
        logger.log(f"Protocolo '{name}' activado en runner")
        st = protocol_runner.status()
        return jsonify({
            "status": "running" if st.activo else "stopped",
            "name": st.nombre,
            "started_at": st.started_at,
            "elapsed_s": st.elapsed_s,
            "done": st.done,
            "last_log": st.last_log
        })
    except Exception as e:
        logger.log(f"Error activando protocolo: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

@app.route("/api/protocols/status", methods=["GET"])
def api_protocol_status():
    """Consulta estado del protocolo activo del runner."""
    st = protocol_runner.status()
    return jsonify({
        "status": "running" if st.activo else "stopped",
        "name": st.nombre,
        "started_at": st.started_at,
        "elapsed_s": st.elapsed_s,
        "done": st.done,
        "last_log": st.last_log,
        "final_obs": st.final_obs,
        "execution_history": st.execution_history,
        "sensor_config": st.sensor_config
    })

@app.route("/api/protocols/stop", methods=["POST"])
def api_protocol_stop():
    """Detiene el protocolo activo del runner (parada segura)."""
    protocol_runner.stop()
    return jsonify({"status": "stopped"})

@app.route("/api/protocols/execute_direct", methods=["POST"])
def api_execute_protocol_direct():
    """Ejecuta un protocolo directamente sin guardarlo - para pruebas rápidas"""
    try:
        data = get_request_data()
        codigo = data.get("code")
        if not codigo:
            return jsonify({"error": "Se requiere 'code' para ejecución directa"}), 400
        
        params = data.get("params", {})
        
        # Permitir comandos durante ejecución de tarea para que funcione
        try:
            with env_lock:
                robot_env.set_command_policy("all")
        except Exception:
            pass
        
        # Ejecutar protocolo directamente
        temp_name = protocol_runner.execute_direct(codigo, params)
        logger.log(f"Protocolo temporal '{temp_name}' ejecutado directamente")
        
        # Esperar a que termine y obtener estado final
        time.sleep(0.5)  # Pequeña espera para que termine
        st = protocol_runner.status()
        
        return jsonify({
            "status": "completed",
            "temp_name": temp_name,
            "name": st.nombre,
            "started_at": st.started_at,
            "elapsed_s": st.elapsed_s,
            "done": st.done,
            "last_log": st.last_log,
            "final_obs": st.final_obs,
            "execution_history": st.execution_history,
            "sensor_config": st.sensor_config
        })
        
    except Exception as e:
        logger.log(f"Error en ejecución directa: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

@app.route("/api/protocols/configure_sensors", methods=["POST"])
def api_configure_sensors():
    """Configura qué sensores devolver al cliente"""
    try:
        data = get_request_data()
        sensor_config = data.get("sensor_config", {})
        
        # Validar configuración de sensores
        valid_sensors = {
            "x_mm", "a_deg", "z_mm", "modo", "energia_x", "energia_a", "energia_bomba",
            "volumen_ml", "caudal_est_mls", "flow_est", "homing_x", "homing_a",
            "lim_x", "lim_a", "servo_z_deg", "usar_sensor_flujo", "baudrate",
            "pasos_por_mm", "pasos_por_grado", "kp_x", "ki_x", "kd_x",
            "kp_a", "ki_a", "kd_a", "rx_age_ms", "serial_open", "stale"
        }
        
        # Filtrar solo sensores válidos
        filtered_config = {}
        for sensor, enabled in sensor_config.items():
            if sensor in valid_sensors:
                filtered_config[sensor] = bool(enabled)
        
        # Aplicar configuración al runner actual
        if hasattr(protocol_runner, '_sensor_config'):
            protocol_runner._sensor_config.update(filtered_config)
        
        logger.log(f"Configuración de sensores actualizada: {filtered_config}")
        
        return jsonify({
            "status": "configured",
            "sensor_config": filtered_config,
            "message": f"Configuración aplicada. {len(filtered_config)} sensores configurados."
        })
        
    except Exception as e:
        logger.log(f"Error configurando sensores: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

# =============================================================================
# CRUD DE PROTOCOLOS (Compatibilidad con la UI)
# =============================================================================

@app.route("/api/protocols", methods=["GET"])
def api_list_protocols():
    """Lista restringida: solo 'riego_basico' con metadata de parámetros."""
    try:
        return jsonify({
            "protocols": ["riego_basico", "ir_posicion"],
            "meta": {
                "riego_basico": {
                    "label": "Riego básico",
                    "params": {
                        "x_mm": {"type": "number", "min": 0, "max": 400, "step": 0.5, "label": "X (mm)", "default": 0},
                        "a_deg": {"type": "number", "min": 0, "max": 360, "step": 0.5, "label": "A (°)", "default": 0},
                        "volume_ml": {"type": "number", "min": 0, "max": 1000, "step": 1, "label": "Volumen (ml)", "default": 50},
                        "intensity": {"type": "number", "min": 0, "max": 255, "step": 1, "label": "Intensidad", "default": 100}
                    },
                    "reward": {
                        "defaults": {"key": "volumen_ml", "threshold": 0, "expr": "", "cumulative": True},
                        "suggested_keys": ["volumen_ml", "flow_est", "caudal_est_mls"]
                    }
                },
                "ir_posicion": {
                    "label": "Ir a posición",
                    "params": {
                        "x_mm": {"type": "number", "min": 0, "max": 400, "step": 0.5, "label": "X (mm)", "default": 0},
                        "a_deg": {"type": "number", "min": 0, "max": 360, "step": 0.5, "label": "A (°)", "default": 0},
                        "threshold": {"type": "number", "min": 0, "max": 10, "step": 0.1, "label": "Umbral (mm)", "default": 1.0}
                    },
                    "reward": {
                        "defaults": {"key": "", "threshold": 0, "expr": "", "cumulative": True},
                        "suggested_keys": ["x_mm", "a_deg", "volumen_ml"]
                    }
                }
            }
        })
    except Exception as e:
        logger.log(f"Error listando protocolos: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

@app.route("/api/areas", methods=["GET"])
def api_areas_stub():
    """Compat: algunas vistas piden /api/areas; devolvemos lista vacía."""
    return jsonify([])

@app.route("/api/protocols/<name>/vars", methods=["POST"])
def api_protocol_update_vars(name: str):
    """Actualiza en vivo los vars del protocolo activo (ctx.vars)."""
    try:
        data = get_request_data() or {}
        params = data.get("params") or {}
        if not isinstance(params, dict):
            return jsonify({"error": "'params' debe ser objeto"}), 400
        st = protocol_runner.status()
        if not st.activo:
            return jsonify({"error": "No hay protocolo activo"}), 400
        if hasattr(protocol_runner, 'update_vars'):
            protocol_runner.update_vars(params)
        return jsonify({"status": "vars_updated", "protocol": st.nombre, "applied": params})
    except Exception as e:
        logger.log(f"Error actualizando vars: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

@app.route("/api/protocols/<name>", methods=["GET"])
def api_get_protocol(name: str):
    """Obtiene el código fuente del protocolo permitido desde disco."""
    try:
        if name not in ("riego_basico", "ir_posicion"):
            return jsonify({"error": "Protocolo deshabilitado"}), 404
        # Leer directamente el archivo del protocolo
        proto_path = PROTOCOLS_DIR / f"{name}.py"
        if not proto_path.exists():
            return jsonify({"error": "Protocolo no encontrado"}), 404
        with open(proto_path, "r", encoding="utf-8") as f:
            code = f.read()
        return jsonify({"name": name, "code": code})
    except Exception as e:
        logger.log(f"Error obteniendo protocolo: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

@app.route("/api/protocols", methods=["POST"])
def api_save_protocol():
    """Deshabilitado: no se permite guardar otros protocolos."""
    return jsonify({"error": "Guardar protocolos está deshabilitado en modo simplificado"}), 404

@app.route("/api/protocols/<name>", methods=["DELETE"])
def api_delete_protocol(name: str):
    """Deshabilitado en modo simplificado."""
    return jsonify({"error": "Eliminar protocolos está deshabilitado"}), 404

# =============================================================================
# NUEVOS ENDPOINTS PARA ARQUITECTURA UNIFICADA
# =============================================================================

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
        # Forzar protocolo único permitido
        if protocol_name not in ("riego_basico", "ir_posicion"):
            logger.log(f"Protocolo no habilitado: {protocol_name}", "WARN")
            return jsonify({"error": "Protocolo no habilitado"}), 400
        
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

@app.route("/api/execute", methods=["POST"])
def api_execute_compat():
    """Endpoint de compatibilidad que mapea a /api/tasks/execute."""
    try:
        data = get_request_data() or {}
        typ = (data.get("type") or "").lower()
        timeout_seconds = float(data.get("timeout_seconds", 25.0))

        if typ == "protocol":
            prot = data.get("id")
            if prot != "riego_basico":
                return jsonify({"error": "Solo 'riego_basico' está habilitado"}), 400
            params = data.get("params", {})
            duration = float(data.get("duration", 10.0))
            # delegar a tareas v2 async
            payload = {
                "name": f"Run {prot}",
                "protocol_name": prot,
                "duration_seconds": duration,
                "timeout_seconds": timeout_seconds,
                "params": params,
                "mode": "async"
            }
            # ejecutar directamente y devolver execution_id
            with app.test_request_context(json=payload):
                resp = api_execute_task_v2().json
            eid = resp.get("execution_id") or resp.get("task_id") or _track_exec_start("protocol", prot)
            # track local (para UI legacy) y enlazar con TaskExecutor
            if eid and eid not in _active_exec:
                _track_exec_start("protocol", prot)
            return jsonify({"execution_id": eid})

        if typ == "task":
            task_id = data.get("id") or ""
            # Ejecutar la tarea programada ahora a través del scheduler si existe
            try:
                result = task_scheduler.execute_task_now(task_id, ExecutionMode.ASYNC)
                eid = str(result)
            except Exception:
                # fallback: ejecutar como protocolo con params de la tarea guardada
                if _tasks_mgr is None:
                    return jsonify({"error": "Tarea no encontrada"}), 404
                try:
                    t = _tasks_mgr.get_tarea(task_id)
                except Exception:
                    return jsonify({"error": "Tarea no encontrada"}), 404
                prot = t.get("protocolo") or t.get("protocol")
                params = t.get("params") or {}
                duration = float(t.get("duration_seconds") or 10.0)
                payload = {
                    "name": t.get("nombre") or task_id,
                    "protocol_name": prot,
                    "duration_seconds": duration,
                    "timeout_seconds": timeout_seconds,
                    "params": params,
                    "mode": "async"
                }
                with app.test_request_context(json=payload):
                    resp = api_execute_task_v2().json
                eid = resp.get("execution_id") or _track_exec_start("task", task_id)
            # track
            if eid and eid not in _active_exec:
                _track_exec_start("task", task_id)
            return jsonify({"execution_id": eid})

        if typ == "immediate":
            action_type = data.get("action_type") or "irrigation"
            duration = float(data.get("duration", 5.0))
            payload = {
                "name": f"Immediate {action_type}",
                "protocol_name": "riego_basico",
                "duration_seconds": duration,
                "timeout_seconds": timeout_seconds,
                "params": data.get("params", {}),
                "mode": "async"
            }
            with app.test_request_context(json=payload):
                resp = api_execute_task_v2().json
            eid = resp.get("execution_id") or _track_exec_start("immediate", action_type)
            if eid and eid not in _active_exec:
                _track_exec_start("immediate", action_type)
            return jsonify({"execution_id": eid})

        return jsonify({"error": "Tipo no soportado"}), 400
    except Exception as e:
        logger.log(f"Error en /api/execute: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

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

@app.route("/api/execution/<execution_id>/history", methods=["GET"])
def api_execution_history(execution_id: str):
    """Devuelve historial de observaciones con timestamp, filtrable por sensores.
    Params opcionales:
      - sensors: lista separada por comas (ej. x_mm,a_deg,volumen_ml)
      - limit: máximo de muestras (por defecto 100)
      - since_ts: epoch seconds; devuelve muestras con timestamp > since_ts
    """
    try:
        sensors_q = (request.args.get("sensors") or "").strip()
        wanted = [s.strip() for s in sensors_q.split(",") if s.strip()]
        limit = int(request.args.get("limit", 100))
        since_ts = request.args.get("since_ts")
        try:
            since_ts = float(since_ts) if since_ts is not None else None
        except Exception:
            since_ts = None

        st = protocol_runner.status()
        hist = st.execution_history or []
        # Filtrar por since_ts
        if since_ts is not None:
            hist = [h for h in hist if (h.get("timestamp") or 0) > since_ts]
        # Limitar
        if limit and limit > 0:
            hist = hist[-limit:]
        # Seleccionar sensores
        def pick(d):
            if not isinstance(d, dict):
                return {}
            out = {"timestamp": d.get("timestamp")}
            if wanted:
                for k in wanted:
                    if k in d:
                        out[k] = d[k]
            else:
                out.update(d)
            return out

        data = [pick(h) for h in hist]
        last_ts = data[-1]["timestamp"] if data else None
        return jsonify({"execution_id": execution_id, "count": len(data), "last_ts": last_ts, "samples": data})
    except Exception as e:
        logger.log(f"Error en /api/execution/history: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

@app.route("/api/execution/protocolo_activo", methods=["GET"])
def api_execution_protocolo_activo():
    """Endpoint especial para 'protocolo_activo' que devuelve el estado del protocolo runner."""
    try:
        st = protocol_runner.status()
        return jsonify({
            "execution_id": "protocolo_activo",
            "status": "running" if st.activo else "stopped",
            "protocol_name": st.nombre,
            "started_at": st.started_at,
            "elapsed_s": st.elapsed_s,
            "done": st.done,
            "last_log": st.last_log,
            "type": "protocol",
            "target_id": st.nombre
        })
    except Exception as e:
        logger.log(f"Error en /api/execution/protocolo_activo: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

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

@app.route("/api/tasks/status/<task_id>", methods=["GET"])
def api_task_status_v2(task_id: str):
    """Consulta el estado de una tarea"""
    try:
        status = task_executor.get_task_status(task_id)
        if status is None:
            return jsonify({"error": "Tarea no encontrada"}), 404
        
        return jsonify({
            "task_id": status.task_id,
            "status": status.status.value,
            "started_at": status.started_at,
            "ended_at": status.ended_at,
            "duration": status.duration,
            "result": status.result,
            "error": status.error,
            "log": status.log,
            "progress": status.progress
        })
        
    except Exception as e:
        logger.log(f"Error consultando estado de tarea: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

@app.route("/api/tasks/stop/<task_id>", methods=["POST"])
def api_stop_task_v2(task_id: str):
    """Detiene una tarea en ejecución"""
    try:
        if task_executor.stop_task(task_id):
            return jsonify({
                "status": "stopped",
                "task_id": task_id,
                "stopped_at": datetime.now().isoformat()
            })
        else:
            return jsonify({"error": "Tarea no encontrada o ya completada"}), 404
        
    except Exception as e:
        logger.log(f"Error deteniendo tarea: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

@app.route("/api/tasks/active", methods=["GET"])
def api_list_active_tasks_v2():
    """Lista tareas activas"""
    try:
        active_tasks = task_executor.list_active_tasks()
        return jsonify({
            "active_tasks": [
                {
                    "task_id": task.task_id,
                    "status": task.status.value,
                    "started_at": task.started_at,
                    "duration": task.duration,
                    "log": task.log[-5:] if task.log else []  # Últimos 5 logs
                }
                for task in active_tasks
            ]
        })
        
    except Exception as e:
        logger.log(f"Error listando tareas activas: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

@app.route("/api/tasks/recent", methods=["GET"])
def api_list_recent_tasks_v2():
    """Lista tareas recientes"""
    try:
        limit = int(request.args.get("limit", 10))
        recent_tasks = task_executor.list_recent_tasks(limit)
        
        return jsonify({
            "recent_tasks": [
                {
                    "task_id": task.task_id,
                    "status": task.status.value,
                    "started_at": task.started_at,
                    "ended_at": task.ended_at,
                    "duration": task.duration,
                    "error": task.error,
                    "log": task.log[-3:] if task.log else []  # Últimos 3 logs
                }
                for task in recent_tasks
            ]
        })
        
    except Exception as e:
        logger.log(f"Error listando tareas recientes: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

# =============================================================================
# ENDPOINTS PARA PROGRAMACIÓN DE TAREAS
# =============================================================================

@app.route("/api/schedules", methods=["GET", "POST"])
def api_schedules():
    """API para gestión de programaciones de tareas"""
    if request.method == "GET":
        try:
            schedules = task_scheduler.list_schedules()
            return jsonify({
                "schedules": [
                    {
                        "task_id": s.task_id,
                        "name": s.name,
                        "protocol_name": s.protocol_name,
                        "schedule_type": s.schedule_type.value,
                        "duration_seconds": s.duration_seconds,
                        "active": s.active,
                        "last_execution": s.last_execution.isoformat() if s.last_execution else None,
                        "next_execution": s.next_execution.isoformat() if s.next_execution else None,
                        "execution_count": s.execution_count,
                        "max_executions": s.max_executions
                    }
                    for s in schedules
                ]
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    
    # POST - Crear nueva programación
    try:
        data = get_request_data()
        
        # Parámetros requeridos
        name = data.get("name")
        protocol_name = data.get("protocol_name")
        schedule_type = data.get("schedule_type", "una_vez")
        
        if not name or not protocol_name:
            return jsonify({"error": "Se requiere 'name' y 'protocol_name'"}), 400
        if protocol_name != "riego_basico":
            return jsonify({"error": "Solo 'riego_basico' está habilitado"}), 400
        
        # Crear programación
        schedule = TaskSchedule(
            task_id=f"schedule_{int(time.time())}",
            name=name,
            protocol_name=protocol_name,
            schedule_type=ScheduleType(schedule_type),
            duration_seconds=float(data.get("duration_seconds", 10.0)),
            timeout_seconds=float(data.get("timeout_seconds", 25.0)),
            params=data.get("params", {}),
            auto_stop=bool(data.get("auto_stop", True)),
            schedule_params=data.get("schedule_params", {}),
            max_executions=data.get("max_executions")
        )
        
        task_id = task_scheduler.add_schedule(schedule)
        
        return jsonify({
            "status": "created",
            "task_id": task_id,
            "schedule": {
                "name": schedule.name,
                "protocol_name": schedule.protocol_name,
                "schedule_type": schedule.schedule_type.value,
                "next_execution": schedule.next_execution.isoformat() if schedule.next_execution else None
            }
        })
        
    except Exception as e:
        logger.log(f"Error creando programación: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400


# =============================================================================
# CRUD DE TAREAS (Compatibilidad con la UI existente)
# =============================================================================

# control_tareas.py eliminado - era un sistema legacy no utilizado
# El sistema actual usa TaskScheduler y TaskExecutor
_tasks_mgr = None

@app.route("/api/tasks", methods=["GET"])
def api_tasks_list():
    """Lista tareas persistidas para el calendario."""
    try:
        if _tasks_mgr is None:
            return jsonify([])
        return jsonify(_tasks_mgr.obtener_tareas())
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/tasks", methods=["POST"])
def api_tasks_create_or_update():
    """Crea o actualiza una tarea (por id)."""
    try:
        if _tasks_mgr is None:
            return jsonify({"error": "Task manager no disponible"}), 500
        data = get_request_data() or {}
        # Normalizar payload básico que usa la UI
        tarea = {
            "id": data.get("id") or f"t_{int(time.time())}",
            "nombre": data.get("nombre") or data.get("n") or "",
            "activo": bool(data.get("activo", True)),
            # Forzar protocolo único
            "protocolo": "riego_basico",
            "volumenObjetivoML": data.get("volumenObjetivoML") or data.get("vol") or 0,
            "params": data.get("params") or {},
            "programacion": data.get("programacion") or {},
        }
        # Normalizar params volumen
        if "volume_ml" not in tarea["params"] and tarea.get("volumenObjetivoML"):
            try:
                tarea["params"]["volume_ml"] = float(tarea["volumenObjetivoML"])
            except Exception:
                pass
        _tasks_mgr.agregar_tarea(tarea)
        return jsonify({"status": "saved", "id": tarea["id"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/tasks/<task_id>", methods=["GET"])
def api_tasks_get(task_id: str):
    try:
        if _tasks_mgr is None:
            return jsonify({"error": "Task manager no disponible"}), 500
        return jsonify(_tasks_mgr.get_tarea(task_id))
    except KeyError:
        return jsonify({"error": "No existe"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/tasks/<task_id>", methods=["PUT"])
def api_tasks_update(task_id: str):
    try:
        if _tasks_mgr is None:
            return jsonify({"error": "Task manager no disponible"}), 500
        data = get_request_data() or {}
        data["id"] = task_id
        _tasks_mgr.agregar_tarea(data)
        return jsonify({"status": "updated", "id": task_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def api_tasks_delete(task_id: str):
    try:
        if _tasks_mgr is None:
            return jsonify({"error": "Task manager no disponible"}), 500
        _tasks_mgr.eliminar_tarea(task_id)
        return jsonify({"status": "deleted", "id": task_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/tasks/<task_id>/execute", methods=["POST"])
def api_task_execute_now(task_id: str):
    """Compatibilidad: ejecutar una tarea por ID ahora (async por defecto)."""
    try:
        mode = request.args.get("mode", "async")
        execution_mode = ExecutionMode.SYNC if mode == "sync" else ExecutionMode.ASYNC
        try:
            result = task_scheduler.execute_task_now(task_id, execution_mode)
            if execution_mode == ExecutionMode.SYNC:
                return jsonify({
                    "status": "completed",
                    "task_id": result.task_id,
                    "execution_status": result.status.value,
                    "duration": result.duration,
                    "result": result.result
                })
            else:
                eid = str(result)
                # Registrar en tracker de compatibilidad
                if eid and eid not in _active_exec:
                    _track_exec_start("task", task_id)
                return jsonify({"execution_id": eid})
        except Exception:
            # Fallback a TaskExecutor directo usando _tasks_mgr
            if _tasks_mgr is None:
                return jsonify({"error": "Tarea no encontrada"}), 404
            try:
                t = _tasks_mgr.get_tarea(task_id)
            except Exception:
                return jsonify({"error": "Tarea no encontrada"}), 404
            prot = t.get("protocolo") or t.get("protocol")
            params = t.get("params") or {}
            duration = float(t.get("duration_seconds") or 10.0)
            payload = {
                "name": t.get("nombre") or task_id,
                "protocol_name": prot,
                "duration_seconds": duration,
                "timeout_seconds": float(request.args.get("timeout_seconds", 25) or 25),
                "params": params,
                "mode": "async" if execution_mode == ExecutionMode.ASYNC else "sync"
            }
            with app.test_request_context(json=payload):
                resp = api_execute_task_v2()
            return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/schedules/<task_id>/execute", methods=["POST"])
def api_execute_schedule_now(task_id: str):
    """Ejecuta una tarea programada inmediatamente"""
    try:
        mode = request.args.get("mode", "async")
        execution_mode = ExecutionMode.SYNC if mode == "sync" else ExecutionMode.ASYNC
        
        result = task_scheduler.execute_task_now(task_id, execution_mode)
        
        if execution_mode == ExecutionMode.SYNC:
            return jsonify({
                "status": "completed",
                "task_id": result.task_id,
                "execution_status": result.status.value,
                "duration": result.duration,
                "result": result.result
            })
        else:
            return jsonify({
                "status": "executing",
                "execution_id": result,
                "message": f"Tarea programada ejecutándose. Use /api/tasks/v2/status/{result} para consultar estado."
            })
        
    except Exception as e:
        logger.log(f"Error ejecutando tarea programada: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400



# =============================================================================
# RUTAS DE PUERTO SERIAL (CORREGIDAS PARA COMPATIBILIDAD)
# =============================================================================


@app.route("/api/robots", methods=["GET"])
def api_list_robots():
    return jsonify({
        "active": active_robot_id,
        "robots": _available_robot_profiles(),
    })

# Alias de compatibilidad
@app.route("/robots", methods=["GET"])
def robots_alias():
    return api_list_robots()

@app.route("/api/robots/select", methods=["POST"])
def api_select_robot():
    data = request.get_json(silent=True) or {}
    robot_id = str(data.get("id") or data.get("robot_id") or "").strip().lower()
    if not robot_id or robot_id not in ROBOT_PROFILES:
        return jsonify({"error": "robot desconocido"}), 400
    summary = switch_robot(robot_id)
    return jsonify({
        "active": summary["id"],
        "profile": summary,
        "robots": _available_robot_profiles(),
    })

# Alias de compatibilidad
@app.route("/robots/select", methods=["POST"])
def robots_select_alias():
    return api_select_robot()

@app.route("/api/serial/ports")
def api_serial_ports():
    """API para listar puertos serial"""
    ports = list_serial_ports()
    is_virtual = bool(getattr(robot_env, "is_virtual", False))
    ser = getattr(robot_env, "ser", None)
    open_state = bool(ser and getattr(ser, "is_open", False))
    if is_virtual:
        open_state = True
    return jsonify({
        "ports": ports,
        "current": robot_env.port,
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

@app.route("/api/move_to", methods=["POST"])
def api_move_to():
    """API para mover robot a posición específica"""
    try:
        if not _is_serial_connected():
            logger.log("/api/move_to rechazado: serial desconectado", "WARN")
            return jsonify({"error": "Serial desconectado"}), 409
        data = get_request_data()
        logger.log(f"/api/move_to payload: {data}")
        x = data.get("x")
        y = data.get("y")
        # Alias de compatibilidad con test: x_mm / a_deg
        if x is None:
            x = data.get("x_mm")
        if y is None:
            y = data.get("a_deg")
        
        with env_lock:
            if x is not None:
                robot_env.set_corredera_mm(float(x))
            if y is not None:
                robot_env.set_angulo_deg(float(y))
            
            robot_env.step()
        
        return jsonify({"status": "moved_to", "x": x, "y": y})
    except Exception as e:
        logger.log(f"Error moviendo robot a posición: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500

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

@app.route("/api/water", methods=["POST"])
def api_water():
    """API para activar riego"""
    try:
        with env_lock:
            robot_env.set_energia_bomba(100)
            robot_env.step()
        
        return jsonify({"status": "watering"})
    except Exception as e:
        logger.log(f"Error activando riego: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500

@app.route("/api/suck", methods=["POST"])
def api_suck():
    """API para activar aspiración"""
    try:
        with env_lock:
            robot_env.set_energia_bomba(-100)
            robot_env.step()
        
        return jsonify({"status": "sucking"})
    except Exception as e:
        logger.log(f"Error activando aspiración: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500

## Versión mínima: sin rutas de cámara

## Versión mínima: solo compatibilidad necesaria

@app.route("/entorno/actualizar_acciones", methods=["POST"])
def compat_entorno_actualizar_acciones():
    """Ruta de compatibilidad para interfaces antiguas"""
    try:
        data = get_request_data()
        logger.log(f"Compatibilidad: {data}")
        
        with env_lock:
            # Modo manual (USANDO MÉTODOS CORRECTOS)
            if "manual_corredera" in data or "manual_angulo" in data:
                x_manual = bool(int(data.get("manual_corredera", 0)))
                a_manual = bool(int(data.get("manual_angulo", 0)))
                robot_env.set_modo(mx=x_manual, ma=a_manual)  # ✅ Método correcto
            
            # Setpoints (USANDO MÉTODOS CORRECTOS)
            if "setpoints" in data:
                sp = data["setpoints"]
                if "slide" in sp:
                    robot_env.set_corredera_mm(float(sp["slide"]))  # ✅ Método correcto
                if "angle" in sp:
                    robot_env.set_angulo_deg(float(sp["angle"]))     # ✅ Método correcto
                if "volume" in sp:
                    robot_env.set_volumen_objetivo_ml(float(sp["volume"]))  # ✅ Método correcto
            
            # Resets (USANDO MÉTODOS CORRECTOS)
            if data.get("reset_volume"):
                robot_env.reset_volumen()  # ✅ Método correcto
            
            # PID (USANDO MÉTODOS CORRECTOS)
            if "pid_settings" in data:
                pid = data["pid_settings"]
                if all(k in pid for k in ["kpX", "kiX", "kdX"]):
                    robot_env.set_pid_corredera(
                        float(pid["kpX"]), float(pid["kiX"]), float(pid["kdX"])
                    )  # ✅ Método correcto
                if all(k in pid for k in ["kpA", "kiA", "kdA"]):
                    robot_env.set_pid_angulo(
                        float(pid["kpA"]), float(pid["kiA"]), float(pid["kdA"])
                    )  # ✅ Método correcto
            
            robot_env.step()
        
        return jsonify({"status": "ok"})
        
    except Exception as e:
        logger.log(f"Error en compatibilidad: {e}", "ERROR")
        return jsonify({"error": str(e)}), 400

# === ALIAS DE COMPATIBILIDAD (evitar 404 de la UI antigua) ===

@app.route("/status")
def compat_status():
    return api_config()

@app.route("/serial/ports")
def compat_serial_ports():
    return api_serial_ports()

@app.route("/serial/open", methods=["POST"])
def compat_serial_open():
    return api_serial_open()

@app.route("/serial/close", methods=["POST"])
def compat_serial_close():
    return api_serial_close()

## Versión mínima: sin endpoints /debug
@app.route("/debug/serial", methods=["GET"])
def debug_serial():
    """Devuelve última RX y edad en ms (para watchdog de UI)."""
    try:
        now = time.time()
        age_ms = int(max(0, (now - (last_rx_ts or 0)) * 1000)) if 'last_rx_ts' in globals() else None
        return jsonify({
            "last_rx": last_rx_text if 'last_rx_text' in globals() else None,
            "age_ms": age_ms
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/debug/serial_tx", methods=["GET"])
def debug_serial_tx():
    """Devuelve último TX y edad en ms (para UI)."""
    try:
        now = time.time()
        age_ms = int(max(0, (now - (last_tx_ts or 0)) * 1000)) if 'last_tx_ts' in globals() else None
        return jsonify({
            "last_tx": last_tx_text if 'last_tx_text' in globals() else None,
            "age_ms": age_ms
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---- Alias GET /control (compat UI) ----

@app.route("/control")
def compat_control_get():
    """Permite llamadas GET /control?x_mm=...&a_deg=... etc. Convierte a JSON y reenvía a api_control."""
    data = {}
    # map query params
    for k,v in request.args.items():
        if k in ("x_mm","a_deg","vol_ml"):  # setpoints directos
            data.setdefault("setpoints",{})
            if k=="x_mm": data["setpoints"]["x_mm"] = float(v)
            elif k=="a_deg": data["setpoints"]["a_deg"] = float(v)
            else: data["setpoints"]["volumen_ml"] = float(v)
        elif k=="modo":
            data["modo"] = int(v)
        elif k=="pid_on":
            data["pid_settings"] = {"pidX":{"kp":1,"ki":1,"kd":0.1}}  # placeholder
        elif k.startswith("energy_"):
            axis=k.split("_")[1]
            key_map={"x":"x","a":"a","bomba":"bomba"}
            data.setdefault("energies",{})[key_map.get(axis,axis)] = int(v)
    # Reutilizar lógica de api_control
    with app.test_request_context(json=data):
        resp = api_control()
        _set_last_tx(json.dumps(data))
        return resp

ALLOWED_ENDPOINTS.add("/control")

## Versión mínima: sin API /simple

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
        logger.log("[Visualizer] PyBulletVisualizer no disponible (import falló)", "WARNING")
        visualizer = None
        return False
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
        # Crear visualizador con mayor resolución para que se vea más grande en la UI
        visualizer = PyBulletVisualizer(str(chosen) if chosen else "", width=720, height=480)
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
        """Abre automáticamente la interfaz del calendario en el navegador"""
        time.sleep(1.5)  # Esperar a que el servidor esté listo
        try:
            url = f"http://localhost:{PORT}/"
            logger.log(f"WEB: Abriendo navegador automáticamente: {url}")
            webbrowser.open(url)
        except Exception as e:
            logger.log(f"WARNING: Error abriendo navegador: {e}")
    
    # Iniciar hilo para abrir el navegador
    threading.Thread(target=open_browser, daemon=True).start()
    
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )
