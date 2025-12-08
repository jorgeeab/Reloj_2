#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple Pump Robot Server - Flask + WebSocket
============================================
Servidor simplificado para control de bomba usando la misma
arquitectura que robot_reloj y robot_opuno.
"""

import os
import sys
import json
import time
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass, asdict

from flask import Flask, request, jsonify, render_template, Response, send_from_directory
from werkzeug.exceptions import NotFound
from flask_sock import Sock
from simple_websocket import ConnectionClosed
import logging

# Importar módulos compartidos desde reloj_core
if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from reloj_core import ProtocolRunner, Protocolo
from reloj_core import TaskExecutor, TaskDefinition, ExecutionMode
from reloj_core import TaskScheduler, TaskSchedule, ScheduleType
from jinja2 import ChoiceLoader, FileSystemLoader

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

BASE_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = BASE_DIR.parent
SHARED_TEMPLATES = PROJECT_ROOT / "shared_templates"
SHARED_STATIC_DIR = PROJECT_ROOT / "shared_static"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# Crear directorios
for directory in [TEMPLATES_DIR, STATIC_DIR, DATA_DIR, LOGS_DIR]:
    directory.mkdir(exist_ok=True)

SETTINGS_FILE = DATA_DIR / "settings.json"
PORT = int(os.environ.get("PUMP_HTTP_PORT", "5010"))

# =============================================================================
# SIMULACIÓN DE BOMBA (Simple)
# =============================================================================

@dataclass
class PumpState:
    """Estado simplificado de la bomba"""
    volumen_ml: float = 0.0
    volumen_objetivo_ml: float = 0.0
    caudal_bomba_mls: float = 5.0
    usar_sensor_flujo: bool = False
    energia_bomba: int = 0
    running: bool = False
    last_update: float = 0.0

class SimplePumpController:
    """Controlador simplificado de bomba para simulación"""
    
    def __init__(self):
        self.state = PumpState()
        self.state.last_update = time.time()
        self._lock = threading.RLock()
        self._timer = None
        
    def update_state(self):
        """Actualizar estado basado en el tiempo transcurrido"""
        with self._lock:
            if not self.state.running or self.state.energia_bomba == 0:
                return
                
            now = time.time()
            dt = now - self.state.last_update
            self.state.last_update = now
            
            # Incrementar volumen
            delta_ml = self.state.caudal_bomba_mls * dt
            self.state.volumen_ml += delta_ml
            
            # Auto-stop al alcanzar objetivo
            if self.state.volumen_objetivo_ml > 0:
                if self.state.volumen_ml >= self.state.volumen_objetivo_ml:
                    self.state.volumen_ml = self.state.volumen_objetivo_ml
                    self.state.running = False
                    self.state.energia_bomba = 0
    
    def set_target_volume(self, ml: float):
        """Establecer volumen objetivo"""
        with self._lock:
            self.state.volumen_objetivo_ml = max(0, float(ml))
    
    def set_flow_rate(self, mls: float):
        """Establecer caudal"""
        with self._lock:
            self.state.caudal_bomba_mls = max(0, float(mls))
    
    def set_energy(self, energy: int):
        """Establecer energía de bomba (0-255)"""
        with self._lock:
            self.state.energia_bomba = max(0, min(255, int(energy)))
            self.state.running = (energy > 0)
            if self.state.running:
                self.state.last_update = time.time()
    
    def reset_volume(self):
        """Resetear volumen acumulado"""
        with self._lock:
            self.state.volumen_ml = 0.0
            self.state.last_update = time.time()
    
    def get_state(self) -> Dict:
        """Obtener estado actual"""
        self.update_state()
        with self._lock:
            return {
                'volumen_ml': self.state.volumen_ml,
                'volumen_objetivo_ml': self.state.volumen_objetivo_ml,
                'caudalBombaMLs': self.state.caudal_bomba_mls,
                'usarSensorFlujo': self.state.usar_sensor_flujo,
                'energies': {'bomba': self.state.energia_bomba},
                'caudal_est_mls': self.state.caudal_bomba_mls if self.state.running else 0.0
            }

# =============================================================================
# FLASK APP
# =============================================================================

app = Flask(__name__, 
            template_folder=str(TEMPLATES_DIR),
            static_folder=None)
sock = Sock(app)

# Configurar Jinja loader para usar templates compartidos
app.jinja_loader = ChoiceLoader([
    FileSystemLoader(str(TEMPLATES_DIR)),
    FileSystemLoader(str(SHARED_TEMPLATES))
])

@app.route('/static/<path:filename>')
def custom_static(filename):
    """Serve static files with fallback to shared_static"""
    try:
        return send_from_directory(STATIC_DIR, filename)
    except NotFound:
        return send_from_directory(SHARED_STATIC_DIR, filename)

# Instancia global del controlador
pump = SimplePumpController()

# Lock para websockets
ws_clients = []
ws_lock = threading.RLock()

# Logger
logger = logging.getLogger("pump_server")
logger.setLevel(logging.INFO)

# =============================================================================
# RUTAS WEB
# =============================================================================

@app.route('/')
def index():
    """Página principal"""
    return render_template('pump.html')

@app.route('/manage')
def manage():
    """Página de gestión de tareas y protocolos"""
    return render_template('manage.html')

@app.route('/api/status')
def api_status():
    """Estado actual del robot"""
    return jsonify(pump.get_state())

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    """Configuración del robot"""
    if request.method == 'POST':
        data = request.json or {}
        if 'caudal_bomba_mls' in data:
            pump.set_flow_rate(data['caudal_bomba_mls'])
        if 'usar_sensor_flujo' in data:
            pump.state.usar_sensor_flujo = bool(data['usar_sensor_flujo'])
        
        # Guardar en archivo
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error guardando settings: {e}")
        
        return jsonify({'status': 'ok'})
    else:
        # Cargar desde archivo
        try:
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, 'r') as f:
                    return jsonify(json.load(f))
        except Exception:
            pass
        return jsonify({
            'caudal_bomba_mls': pump.state.caudal_bomba_mls,
            'usar_sensor_flujo': pump.state.usar_sensor_flujo
        })

# =============================================================================
# WEBSOCKET - CONTROL CHANNEL
# =============================================================================

@sock.route('/ws/control')
def ws_control(ws):
    """WebSocket para enviar comandos de control"""
    with ws_lock:
        ws_clients.append(ws)
    
    try:
        while True:
            data = ws.receive()
            if not data:
                break
            
            try:
                cmd = json.loads(data) if isinstance(data, str) else data
                
                # Procesar comandos
                if 'setpoints' in cmd:
                    sp = cmd['setpoints']
                    if 'volumen_ml' in sp:
                        pump.set_target_volume(sp['volumen_ml'])
                
                if 'flow' in cmd:
                    fl = cmd['flow']
                    if 'flow_target_mls' in fl:
                        pump.set_flow_rate(fl['flow_target_mls'])
                    if 'caudal_bomba_mls' in fl:
                        pump.set_flow_rate(fl['caudal_bomba_mls'])
                    if 'usar_sensor_flujo' in fl:
                        pump.state.usar_sensor_flujo = bool(fl['usar_sensor_flujo'])
                
                if 'energies' in cmd:
                    en = cmd['energies']
                    if 'bomba' in en:
                        pump.set_energy(en['bomba'])
                
                if 'execute' in cmd:
                    if cmd['execute']:
                        pump.set_energy(255)  # Encender bomba
                    else:
                        pump.set_energy(0)  # Apagar bomba
                
                if 'reset_volumen' in cmd and cmd['reset_volumen']:
                    pump.reset_volume()
                
                # Responder
                ws.send(json.dumps({
                    'type': 'control_ack',
                    'status': 'ok'
                }))
                
            except json.JSONDecodeError:
                logger.error("Error decodificando JSON")
            except Exception as e:
                logger.error(f"Error en ws_control: {e}")
    
    except ConnectionClosed:
        pass
    finally:
        with ws_lock:
            if ws in ws_clients:
                ws_clients.remove(ws)

# =============================================================================
# WEBSOCKET - TELEMETRY
# =============================================================================

@sock.route('/ws/telemetry')
def ws_telemetry(ws):
    """WebSocket para enviar telemetría"""
    try:
        ws.send(json.dumps({'type': 'telemetry_ready'}))
        
        while True:
            # Enviar estado cada 500ms
            state = pump.get_state()
            telemetry = {
                'type': 'telemetry',
                'nowMs': int(time.time() * 1000),
                'snapshot': state,
                'volumeActual': state['volumen_ml'],
                'volumeTarget': state['volumen_objetivo_ml'],
                'flowActual': state['caudal_est_mls'],
                'flowTarget': state['caudalBombaMLs']
            }
            ws.send(json.dumps(telemetry))
            time.sleep(0.5)
    
    except ConnectionClosed:
        pass
    except Exception as e:
        logger.error(f"Error en ws_telemetry: {e}")

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    # Auto-abrir navegador
    url = f"http://localhost:{PORT}"
    print(f"[SimplePump] Iniciando servidor en {url}")
    webbrowser.open(url)
    
    # Silenciar logs de Werkzeug
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    # Iniciar servidor
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        threaded=True
    )
