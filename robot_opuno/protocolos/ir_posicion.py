#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protocolo: ir_posicion (Gym-like)
==================================

Protocolo que mueve el robot hacia una posición X/A específica.
"""

import numpy as np
import math
from typing import Dict, Any
from protocolos import ProtocoloBase

class IrPosicion(ProtocoloBase):
    """
    Protocolo para mover el robot a una posición específica.
    
    Mueve los ejes X y A hasta alcanzar las coordenadas objetivo.
    """
    
    # Schema de parámetros para UI dinámica
    PARAMETERS = {
        "x_mm": {
            "type": "number",
            "label": "Posición X (mm)",
            "default": 150.0,
            "min": 0,
            "max": 300,
            "step": 1,
            "required": True,
            "description": "Posición objetivo en el eje X"
        },
        "a_deg": {
            "type": "number",
            "label": "Ángulo (grados)",
            "default": 0.0,
            "min": -180,
            "max": 180,
            "step": 1,
            "required": True,
            "description": "Ángulo objetivo de rotación"
        },
        "threshold": {
            "type": "number",
            "label": "Umbral (mm)",
            "default": 2.0,
            "min": 0.1,
            "max": 10,
            "step": 0.1,
            "required": False,
            "description": "Tolerancia para considerar posición alcanzada"
        }
    }
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target_x = float(kwargs.get('x_mm', 150.0))
        self.target_a = float(kwargs.get('a_deg', 0.0))
        self.threshold = float(kwargs.get('threshold', 2.0))
        
        # Estado interno
        self.current_x = 0.0
        self.current_a = 0.0
    
    def reset(self):
        """Estado inicial"""
        super().reset()
        self.current_x = 0.0
        self.current_a = 0.0
        return self._get_initial_observation()
    
    def setup(self, env):
        """Configuración inicial"""
        self.env = env
    
    def finalize(self, env):
        """Limpieza - detener motores"""
        try:
            env.set_energia_x(0)
            env.set_energia_a(0)
        except:
            pass
    
    def step(self, action=None):
        """
        Un paso Gym: observación → acción → reward → done
        
        Lógica simple:
        1. Leer posición actual
        2. Si no alcanzó objetivo, seguir moviéndose
        3. Si alcanzó objetivo, marcar done=True
        """
        super().step(action)
        
        # 1. Obtener observación
        obs = self._get_observation()
        self.current_x = float(obs.get('x_mm', 0.0)) if isinstance(obs, dict) else 0.0
        self.current_a = float(obs.get('a_deg', 0.0)) if isinstance(obs, dict) else 0.0
        
        # 2. Calcular distancias
        dx = abs(self.current_x - self.target_x)
        da = abs(self.current_a - self.target_a)
        
        # 3. Comandos de movimiento (setpoints)
        patch = {
            "setpointX_mm": self.target_x,
            "setpointA_deg": self.target_a,
            "codigoModo": 0  # PID mode
        }
        
        # 4. Calcular reward (proximidad al objetivo)
        max_distance = 300  # Distancia máxima posible
        distance = math.sqrt(dx**2 + da**2)
        reward = 100.0 * (1.0 - min(distance / max_distance, 1.0))
        
        # 5. Verificar done (objetivo alcanzado)
        x_reached = dx <= self.threshold
        a_reached = da <= self.threshold
        done = x_reached and a_reached
        
        # 6. Info y log
        if done:
            log = f"✅ Posición alcanzada: X={self.current_x:.1f}mm, A={self.current_a:.1f}°"
        else:
            log = f"→ Moviendo: X={self.current_x:.1f}/{self.target_x:.1f}mm (Δ{dx:.1f}), A={self.current_a:.1f}/{self.target_a:.1f}° (Δ{da:.1f})"
        
        info = {
            "patch": patch,
            "sleep_ms": 100,
            "log": log
        }
        
        return obs, reward, done, info
