#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protocolo: ir_posicion (Gym-like) - VERSIÓN MEJORADA
====================================================

Protocolo que mueve el robot hacia una posición X/A y mantiene la posición.
Compatible con entrenamiento de redes neuronales.

Mejoras incluidas:
- Validación robusta de parámetros
- Sistema de logging unificado
- Recompensas normalizadas
- Manejo de errores mejorado
- Métricas de rendimiento
"""

import numpy as np
import math
from typing import Dict, Any, Optional, Tuple
from protocolos import ProtocoloBase
from config_system import get_config

# Asegurar que numpy esté disponible globalmente
if 'np' not in globals():
    import numpy as np

class IrPosicion(ProtocoloBase):
    """
    Protocolo para ir a una posición específica y mantenerla.
    
    Parámetros:
        x_mm: Posición objetivo en X (mm)
        a_deg: Ángulo objetivo en A (grados)
        threshold: Umbral de llegada (mm/grados)
        stop_on_reach: Si parar al llegar al objetivo
        max_speed: Velocidad máxima de movimiento
        safety_margin: Margen de seguridad para evitar límites
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Sistema de logging simplificado
        self.logger = None
        
        # Validar y establecer parámetros
        self._validate_and_set_params(kwargs)
        
        # Estado interno
        self.current_x = 0.0
        self.current_a = 0.0
        self.start_x = 0.0
        self.start_a = 0.0
        self.target_reached = False
        self.safety_violations = 0
        self.movement_start_time = None
        
        # Métricas de rendimiento
        self.performance_metrics = {
            'total_distance_traveled': 0.0,
            'max_deviation': 0.0,
            'movement_time': 0.0,
            'efficiency_score': 0.0
        }
        
        print(f"ir_posicion: Protocolo inicializado: target_x={self.target_x}, target_a={self.target_a}, threshold={self.threshold}")
    
    def _validate_and_set_params(self, params: Dict[str, Any]):
        """Valida y establece parámetros con valores por defecto"""
        # Obtener valores con fallback
        self.target_x = self._safe_float(params.get('x_mm') or params.get('target_x_mm'))
        self.target_a = self._safe_float(params.get('a_deg') or params.get('target_a_deg'))
        self.threshold = self._safe_float(params.get('threshold', get_config('hardware.position_threshold', 1.0)))
        self.stop_on_reach = bool(params.get('stop_on_reach', True))
        self.max_speed = self._safe_float(params.get('max_speed', get_config('hardware.motor_max_energy', 255)))
        self.safety_margin = self._safe_float(params.get('safety_margin', 5.0))
        
        # Validaciones
        if self.target_x is None and self.target_a is None:
            raise ValueError("Debe especificar al menos x_mm o a_deg")
        
        if self.threshold <= 0:
            raise ValueError("Threshold debe ser positivo")
        
        if self.max_speed <= 0 or self.max_speed > 255:
            raise ValueError("max_speed debe estar entre 0 y 255")
        
        # Límites de seguridad
        self.x_limits = (0.0, 300.0)  # Límites físicos del robot
        self.a_limits = (-180.0, 180.0)
        
        # Verificar que los objetivos estén dentro de límites
        if self.target_x is not None:
            if not (self.x_limits[0] + self.safety_margin <= self.target_x <= self.x_limits[1] - self.safety_margin):
                print(f"ir_posicion WARNING: Objetivo X {self.target_x} está cerca de los límites {self.x_limits}")
        
        if self.target_a is not None:
            if not (self.a_limits[0] + self.safety_margin <= self.target_a <= self.a_limits[1] - self.safety_margin):
                print(f"ir_posicion WARNING: Objetivo A {self.target_a} está cerca de los límites {self.a_limits}")
    
    def _safe_float(self, value: Any) -> Optional[float]:
        """Convierte valor a float de forma segura"""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
        
    def reset(self):
        """Reset del protocolo"""
        super().reset()
        self.current_x = 0.0
        self.current_a = 0.0
        return self._get_initial_observation()
    
    def step(self, action=None):
        """Un paso del protocolo"""
        super().step(action)
        
        # Las posiciones ya están actualizadas por el ProtocolRunner
        # Solo verificar que tenemos datos válidos
        if not hasattr(self, 'current_x') or self.current_x is None:
            self.current_x = 0.0
        if not hasattr(self, 'current_a') or self.current_a is None:
            self.current_a = 0.0
        
        # Crear array de observaciones para compatibilidad con Gym
        obs_array = [self.current_x, self.current_a]
        
        # Debug: mostrar posiciones actuales (solo cada 10 pasos para reducir spam)
        debug_pos = ""
        if self.step_count % 10 == 0:
            debug_pos = f"[DEBUG] ir_posicion: current_x={self.current_x:.1f}, target_x={self.target_x}, current_a={self.current_a:.1f}, target_a={self.target_a}"
            print(debug_pos)
        
        # Configurar patch para mantener posición
        patch = {"codigoModo": 0}
        
        if self.target_x is not None:
            patch["setpointX"] = float(self.target_x)
            patch["setpointX_mm"] = float(self.target_x)
        
        if self.target_a is not None:
            patch["setpointA"] = float(self.target_a)
            patch["setpointA_deg"] = float(self.target_a)
        
        # Enviar comandos al robot si tenemos acceso al entorno
        if hasattr(self, 'env') and self.env:
            try:
                # Enviar comandos de movimiento al robot
                if self.target_x is not None:
                    self.env.send_command(f"setpointX:{self.target_x}")
                if self.target_a is not None:
                    self.env.send_command(f"setpointA:{self.target_a}")
                # Activar modo de control
                self.env.send_command("codigoModo:0")
            except Exception as e:
                print(f"Error enviando comandos al robot: {e}")
        
        # Calcular recompensa
        reward = self._calculate_reward()
        
        # Agregar reward al patch para que se incluya en la respuesta
        patch["reward"] = float(reward)
        
        # Verificar si llegamos al objetivo
        dx = abs(self.current_x - self.target_x) if self.target_x is not None else 0.0
        da = abs(self.current_a - self.target_a) if self.target_a is not None else 0.0
        
        # Debug detallado de verificación de llegada (solo cada 20 pasos para reducir spam)
        debug_msg = ""
        if self.step_count % 20 == 0:
            debug_msg = f"[DEBUG] ir_posicion verificación: dx={dx:.2f}mm (threshold={self.threshold}mm), da={da:.2f}° (threshold={self.threshold}°), stop_on_reach={self.stop_on_reach}"
            print(debug_msg)
        
        if dx <= self.threshold and da <= self.threshold:
            debug_msg += f"\n[DEBUG] ir_posicion: ¡OBJETIVO ALCANZADO! dx={dx:.2f}mm <= {self.threshold}mm, da={da:.2f}° <= {self.threshold}°"
            print(f"[DEBUG] ir_posicion: ¡OBJETIVO ALCANZADO! dx={dx:.2f}mm <= {self.threshold}mm, da={da:.2f}° <= {self.threshold}°")
            if self.stop_on_reach:
                self.done = True
                debug_msg += f"\n[DEBUG] ir_posicion: Marcando como DONE=True"
                print(f"[DEBUG] ir_posicion: Marcando como DONE=True")
                log = f"✅ Objetivo alcanzado: X={self.current_x:.1f}mm (target={self.target_x}mm, dx={dx:.2f}mm), A={self.current_a:.1f}° (target={self.target_a}°, da={da:.2f}°)\n{debug_msg}"
            else:
                log = f"Manteniendo posición: X={self.current_x:.1f}mm, A={self.current_a:.1f}°\n{debug_msg}"
        else:
            log = f"🎯 Moviendo: X={self.current_x:.1f}→{self.target_x}mm (dx={dx:.2f}mm), A={self.current_a:.1f}→{self.target_a}° (da={da:.2f}°)\n{debug_msg}"
        
        # Agregar debug de posiciones si existe
        if debug_pos:
            log += f"\n{debug_pos}"
        
        # Información adicional
        info = {
            "patch": patch,
            "sleep_ms": 120,
            "log": log,
            "distance_x": dx,
            "distance_a": da,
            "target_x": self.target_x,
            "target_a": self.target_a
        }
        
        return obs_array, reward, self.done, info
    
    def _calculate_reward(self):
        """Calcula recompensa basada en la proximidad al objetivo (versión mejorada con función exponencial)"""
        if self.target_x is None and self.target_a is None:
            return 0.0
        
        reward = 0.0
        
        # Reward por posición X (mejorado con función exponencial)
        if self.target_x is not None:
            dx = abs(self.current_x - self.target_x)
            if dx <= self.threshold:
                # Recompensa máxima si está dentro del umbral
                reward += 100.0
            else:
                # Recompensa que decrece suavemente con la distancia
                # Usar una función exponencial para mejor comportamiento
                max_distance = 200.0  # Distancia máxima esperada en mm
                normalized_distance = min(dx / max_distance, 1.0)
                # Función exponencial: reward = 100 * e^(-k * normalized_distance)
                k = 3.0  # Factor de decaimiento (mayor = más rápido decae)
                # Implementación de exp sin numpy
                import math
                reward += 100.0 * math.exp(-k * normalized_distance)
        
        # Reward por ángulo A (mejorado con función exponencial)
        if self.target_a is not None:
            da = abs(self.current_a - self.target_a)
            if da <= self.threshold:
                # Recompensa máxima si está dentro del umbral
                reward += 100.0
            else:
                # Recompensa que decrece suavemente con la distancia angular
                max_angle_distance = 180.0  # Distancia angular máxima en grados
                normalized_angle_distance = min(da / max_angle_distance, 1.0)
                k = 3.0  # Factor de decaimiento
                # Implementación de exp sin numpy
                import math
                reward += 100.0 * math.exp(-k * normalized_angle_distance)
        
        # Penalización por tiempo (incentivar llegar rápido)
        time_penalty = -0.1
        reward += time_penalty
        
        return reward
    
    def _get_observation(self):
        """Obtener observación actual del entorno"""
        # En implementación real, esto vendría del entorno físico
        return [
            self.current_x,  # x_mm
            self.current_a,  # a_deg
            0.0,  # z_mm
            0.0,  # volumen_ml
            0.0,  # caudal_est_mls
            0,    # modo
            # ... otros valores según sea necesario
        ]
    
    def render(self, mode='human'):
        """Renderizado opcional del protocolo"""
        if mode == 'human':
            print(f"IrPosicion: X={self.current_x:.1f}→{self.target_x}mm, A={self.current_a:.1f}→{self.target_a}°")
    
    def close(self):
        """Limpieza al finalizar"""
        super().close()
        print("IrPosicion: Protocolo finalizado")


# Compatibilidad con estructura antigua (wrapper)
def setup(ctx):
    """Wrapper para compatibilidad con estructura antigua"""
    try:
        dbg = ctx.get('debug') if isinstance(ctx, dict) else None
        if dbg:
            dbg("ir_pos setup: Iniciando protocolo ir_posicion")
    except Exception:
        pass
    return None

def loop(obs, ctx):
    """Wrapper para compatibilidad con estructura antigua"""
    protocolo = IrPosicion(**ctx.get('vars', {}))
    obs_array = np.array(obs, dtype=np.float32)
    _, reward, done, info = protocolo.step()
    
    return {
        "patch": info.get("patch", {}),
        "done": done,
        "sleep_ms": info.get("sleep_ms", 120),
        "log": info.get("log", ""),
        "reward": reward
    }

def reward(obs_dict, ctx):
    """Wrapper para compatibilidad con estructura antigua"""
    protocolo = IrPosicion(**ctx.get('vars', {}))
    return protocolo._calculate_reward()

def finalize(ctx):
    """Wrapper para compatibilidad con estructura antigua"""
    protocolo = IrPosicion(**ctx.get('vars', {}))
    protocolo.close()
    return None