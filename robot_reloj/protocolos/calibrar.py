#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protocolo: calibrar (Gym-style)
================================

Protocolo de calibración compatible con RL. Sin fases internas.
El runner controla duración.
"""

import math
from typing import Dict, Any
from protocolos import ProtocoloBase

class Calibrar(ProtocoloBase):
    """
    Protocolo de calibración: mueve motor a velocidad constante.
    
    SIN FASES. El ProtocolRunner controla duración.
    El protocolo solo envía velocidad y registra mediciones.
    """
    
    # Schema de parámetros para UI dinámica
    PARAMETERS = {
        "axis": {
            "type": "select",
            "label": "Eje a calibrar",
            "default": "x",
            "options": [
                {"value": "x", "label": "Eje X (Corredera)"},
                {"value": "a", "label": "Eje A (Ángulo)"}
            ],
            "required": True,
            "description": "Eje del robot a calibrar"
        },
        "direction": {
            "type": "select",
            "label": "Dirección",
            "default": "forward",
            "options": [
                {"value": "forward", "label": "Hacia adelante (+)"},
                {"value": "backward", "label": "Hacia atrás (-)"}
            ],
            "required": True,
            "description": "Dirección de movimiento"
        },
        "speed": {
            "type": "number",
            "label": "Velocidad",
            "default": 50,
            "min": 10,
            "max": 255,
            "step": 5,
            "required": False,
            "description": "Velocidad de calibración (0-255)"
        }
    }
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.axis = str(kwargs.get('axis', 'x')).lower()
        self.direction = str(kwargs.get('direction', 'forward'))
        self.speed = int(kwargs.get('speed', 50))
        self.measurements = []
        self.min_value = None
        self.max_value = None
    
    def reset(self):
        """Estado inicial"""
        super().reset()
        self.measurements = []
        self.min_value = None
        self.max_value = None
        return self._get_initial_observation()
    
    def setup(self, env):
        """Configuración inicial"""
        self.env = env
    
    def finalize(self, env):
        """Limpieza - detener motores y mostrar resultados"""
        try:
            env.set_energia_corredera(0)
            env.set_energia_angulo(0)
            
            if self.measurements:
                self.min_value = min(self.measurements)
                self.max_value = max(self.measurements)
                range_size = self.max_value - self.min_value
                print(f"[Calibrar] Rango {self.axis}: [{self.min_value:.1f}, {self.max_value:.1f}] = {range_size:.1f}")
        except:
            pass
    
    def step(self, action=None):
        """
        Un paso Gym: enviar velocidad constante y registrar posición
        
        El runner decide cuándo parar (por tiempo).
        """
        super().step(action)
        
        # 1. Obtener observación
        obs = self._get_observation()
        if isinstance(obs, dict):
            current_value = float(obs.get('x_mm' if self.axis == 'x' else 'a_deg', 0.0))
        else:
            current_value = 0.0
        
        # Registrar medición
        self.measurements.append(current_value)
        
        # 2. Calcular acción (velocidad constante)
        velocity = self.speed if self.direction == 'forward' else -self.speed
        
        patch = {
            "codigoModo": 1  # Manual mode
        }
        
        if self.axis == 'x':
            patch["energiaX"] = velocity
        else:
            patch["energiaA"] = velocity
        
        # 3. Calcular reward (rango explorado)
        if len(self.measurements) > 1:
            current_range = max(self.measurements) - min(self.measurements)
            reward = min(current_range, 300.0)  # Cap at 300
        else:
            reward = 0.0
        
        # 4. Done es siempre False (el runner controla duración)
        done = False
        
        # 5. Info y log
        log = f"📊 Calibrando {self.axis}: {current_value:.1f} (muestras: {len(self.measurements)})"
        
        info = {
            "patch": patch,
            "sleep_ms": 100,
            "log": log,
            "current_value": current_value,
            "samples": len(self.measurements)
        }
        
        return obs, reward, done, info

