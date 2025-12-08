#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protocolo: regar (Gym-style)
=============================

Protocolo de riego simple: SOLO volumen y caudal.
NO tiene movimiento, solo bombeo.
"""

import math
from typing import Dict, Any
from protocolos import ProtocoloBase

class Regar(ProtocoloBase):
    """
    Protocolo de riego SIMPLE: solo bombea volumen con caudal específico.
    
    NO HAY MOVIMIENTO. Solo llenado de contenedor.
    """
    
    # Schema de parámetros para UI dinámica
    PARAMETERS = {
        "volume_ml": {
            "type": "number",
            "label": "Volumen (ml)",
            "default": 100.0,
            "min": 1,
            "max": 2000,
            "step": 10,
            "required": True,
            "description": "Volumen de agua a bombear"
        },
        "flow_ml_s": {
            "type": "number",
            "label": "Caudal (ml/s)",
            "default": 5.0,
            "min": 0.1,
            "max": 40,
            "step": 0.5,
            "required": True,
            "description": "Velocidad de bombeo"
        }
    }
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target_volume = float(kwargs.get('volume_ml', 100.0))
        self.target_flow = float(kwargs.get('flow_ml_s', 5.0))
    
    def reset(self):
        """Estado inicial"""
        super().reset()
        return self._get_initial_observation()
    
    def setup(self, env):
        """Configuración inicial"""
        self.env = env
        # Resetear volumen acumulado
        try:
            env.reset_volumen()
        except:
            pass
    
    def finalize(self, env):
        """Limpieza - detener bomba y resetear volumen"""
        try:
            import time
            env.set_energia_bomba(0)
            env.set_volumen_objetivo_ml(0)
            env.set_caudal_objetivo_mls(0)
            # Simular comportamiento de UI: espera y reset
            time.sleep(1.0)
            env.reset_volumen()
        except:
            pass
    
    def step(self, action=None):
        """
        Un paso Gym: observación → acción → reward → done
        
        Lógica simple:
        1. Leer volumen bombeado actual
        2. Si no alcanzó objetivo, seguir bombeando
        3. Si alcanzó objetivo, marcar done=True
        """
        super().step(action)
        
        # 1. Obtener observación
        obs = self._get_observation()
        pumped_vol = float(obs.get('volumen_ml', 0.0)) if isinstance(obs, dict) else 0.0
        
        # 2. Comandos de bombeo
        patch = {
            "volumenObjetivoML": self.target_volume,
            "caudalObjetivoMLS": self.target_flow,
            "codigoModo": 0  # Modo automático
        }
        
        # 3. Calcular progreso y reward
        progress = min(pumped_vol / max(self.target_volume, 1.0), 1.0)
        reward = 100.0 * progress
        
        # 4. Verificar done (objetivo alcanzado)
        remaining = self.target_volume - pumped_vol
        done = remaining <= 1.0  # Tolerancia de 1ml
        
        # 5. Info y log
        if done:
            log = f"✅ Riego completo: {pumped_vol:.1f}ml bombeados"
        else:
            log = f"💧 Bombeando: {pumped_vol:.1f}/{self.target_volume}ml ({progress*100:.1f}%) @ {self.target_flow}ml/s"
        
        info = {
            "patch": patch,
            "sleep_ms": 100,
            "log": log
        }
        
        return obs, reward, done, info

