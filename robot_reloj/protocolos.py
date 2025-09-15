#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de protocolos compatible con Gym para entrenamiento de redes neuronales.

Contrato de protocolo (Gym-like):
- Archivo Python en 'protocolos/<nombre>.py'
- Debe definir una clase que herede de ProtocoloBase o implemente la interfaz Gym
- Métodos requeridos: __init__, reset, step
- Métodos opcionales: render, close, setup, finalize

El ProtocolRunner se encarga de:
- Ejecutar protocolos usando la interfaz Gym estándar
- Capturar observaciones y rewards durante la ejecución
- Manejar timeouts y condiciones de parada
- Integración con el entorno físico del robot
- Soporte para entrenamiento y ejecución de redes neuronales
"""

from __future__ import annotations

import os
import time
import threading
import numpy as np
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, List, Tuple, Union
from abc import ABC, abstractmethod


# -----------------------------------------------------------------------------
# Clase base para protocolos (Gym-like)
# -----------------------------------------------------------------------------
class ProtocoloBase(ABC):
    """
    Clase base para protocolos compatible con Gym.
    
    Los protocolos deben implementar:
    - __init__(self, **kwargs): Inicialización con parámetros
    - reset(self): Reset del protocolo, retorna observación inicial
    - step(self, action=None): Un paso del protocolo, retorna (obs, reward, done, info)
    
    Métodos opcionales:
    - render(self, mode='human'): Renderizado visual
    - close(self): Limpieza al finalizar
    - setup(self, env): Configuración inicial con acceso al entorno
    - finalize(self, env): Limpieza final con acceso al entorno
    """
    
    def __init__(self, **kwargs):
        """Inicialización del protocolo con parámetros"""
        self.params = kwargs
        self.done = False
        self.step_count = 0
        self.total_reward = 0.0
        
    @abstractmethod
    def reset(self):
        """Reset del protocolo - estado inicial"""
        self.done = False
        self.step_count = 0
        self.total_reward = 0.0
        return self._get_initial_observation()
    
    @abstractmethod
    def step(self, action=None):
        """
        Un paso del protocolo
        
        Args:
            action: Acción del agente (opcional)
            
        Returns:
            observation: Observación actual
            reward: Recompensa del paso
            done: Si el protocolo terminó
            info: Información adicional (dict)
        """
        self.step_count += 1
        return self._get_observation(), self._get_reward(), self._is_done(), self._get_info()
    
    def render(self, mode='human'):
        """Renderizado opcional"""
        pass
    
    def close(self):
        """Limpieza al finalizar"""
        pass
    
    def setup(self, env):
        """Configuración inicial con acceso al entorno"""
        pass
    
    def finalize(self, env):
        """Limpieza final con acceso al entorno"""
        pass
    
    # Métodos auxiliares que pueden ser sobrescritos
    def _get_initial_observation(self):
        """Obtener observación inicial"""
        return np.zeros(22, dtype=np.float32)
    
    def _get_observation(self):
        """Obtener observación actual del robot"""
        try:
            # Obtener datos reales del robot desde el entorno
            if hasattr(self, 'env') and self.env:
                # Si tenemos acceso al entorno, obtener datos reales
                status = self.env.get_status()
                if status:
                    return [
                        float(status.get('x_mm', 0.0)),
                        float(status.get('a_deg', 0.0)),
                        float(status.get('z_mm', 0.0)),
                        float(status.get('volumen_ml', 0.0)),
                        float(status.get('caudal_est_mls', 0.0)),
                        int(status.get('modo', 0))
                    ]
            
            # Fallback: devolver datos simulados
            return [0.0, 0.0, 0.0, 0.0, 0.0, 0]
        except Exception as e:
            print(f"Error obteniendo observación: {e}")
            return [0.0, 0.0, 0.0, 0.0, 0.0, 0]
    
    def _get_reward(self):
        """Calcular recompensa del paso"""
        return 0.0
    
    def _is_done(self):
        """Verificar si el protocolo terminó"""
        return self.done
    
    def _get_info(self):
        """Obtener información adicional"""
        return {
            'step_count': self.step_count,
            'total_reward': self.total_reward,
            'done': self.done
        }


class LegacyProtocoloWrapper(ProtocoloBase):
    """
    Wrapper para protocolos con estructura antigua (setup/loop/reward/finalize)
    Convierte la estructura antigua a la nueva interfaz Gym-like
    """
    
    def __init__(self, setup=None, loop=None, custom_action=None, **kwargs):
        super().__init__(**kwargs)
        self.setup_fn = setup
        self.loop_fn = loop
        self.custom_action_fn = custom_action
        self.ctx = {"vars": kwargs}
        self.last_obs = None
        self.last_patch = None
        self.last_log = None
        
    def reset(self):
        """Reset del protocolo"""
        super().reset()
        self.ctx = {"vars": self.params}
        self.last_obs = None
        self.last_patch = None
        self.last_log = None
        
        # Llamar setup si existe
        if self.setup_fn:
            try:
                self.setup_fn(self.ctx)
            except Exception as e:
                print(f"Error en setup: {e}")
        
        return self._get_initial_observation()
    
    def step(self, action=None):
        """Un paso del protocolo"""
        super().step(action)
        
        # Obtener observación actual del entorno
        obs = self._get_observation()
        self.last_obs = obs
        
        # Llamar función principal (loop o custom_action)
        result = None
        if self.loop_fn:
            try:
                result = self.loop_fn(obs, self.ctx)
            except Exception as e:
                print(f"Error en loop: {e}")
                result = {"done": True, "log": f"Error: {e}"}
        elif self.custom_action_fn:
            try:
                result = self.custom_action_fn(obs, self.ctx) if self.custom_action_fn.__code__.co_argcount > 1 else self.custom_action_fn(obs)
            except Exception as e:
                print(f"Error en custom_action: {e}")
                result = {"done": True, "log": f"Error: {e}"}
        
        if result is None:
            result = {}
        
        # Procesar resultado
        self.last_patch = result.get("patch", {})
        self.last_log = result.get("log", "")
        self.done = result.get("done", False)
        
        # Calcular reward
        reward = result.get("reward", 0.0)
        if hasattr(self, 'reward_fn') and callable(self.reward_fn):
            try:
                reward = self.reward_fn(obs, self.ctx)
            except Exception as e:
                print(f"Error en reward: {e}")
        
        self.total_reward += reward
        
        # Información adicional
        info = self._get_info()
        info.update({
            "patch": self.last_patch,
            "log": self.last_log,
            "sleep_ms": result.get("sleep_ms", 100)
        })
        
        return obs, reward, self.done, info
    
    def close(self):
        """Limpieza al finalizar"""
        if hasattr(self, 'finalize_fn') and callable(self.finalize_fn):
            try:
                self.finalize_fn(self.ctx)
            except Exception as e:
                print(f"Error en finalize: {e}")
        super().close()


# -----------------------------------------------------------------------------
# Loader de protocolos en disco
# -----------------------------------------------------------------------------
class Protocolo:
    def __init__(self, nombre: str, root: str = "protocolos"):
        self.nombre = nombre
        self.root = root
        os.makedirs(self.root, exist_ok=True)
        self.path = os.path.join(self.root, f"{self.nombre}.py")
        self.clase_protocolo: Optional[type] = None
        self.instancia: Optional[ProtocoloBase] = None
        
        # Compatibilidad con estructura antigua
        self.funcion: Optional[Callable] = None
        self.setup: Optional[Callable] = None
        self.loop: Optional[Callable] = None

    def cargar(self):
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"Protocolo '{self.nombre}' no encontrado en {self.root}/")
        
        local_vars: Dict[str, Any] = {}
        with open(self.path, "r", encoding="utf-8") as f:
            codigo = f.read()
        exec(codigo, {}, local_vars)
        
        # Buscar clase que herede de ProtocoloBase (nueva estructura)
        protocolo_class = None
        for name, obj in local_vars.items():
            if (isinstance(obj, type) and 
                issubclass(obj, ProtocoloBase) and 
                obj != ProtocoloBase):
                protocolo_class = obj
                break
        
        if protocolo_class:
            # Nueva estructura Gym-like
            self.clase_protocolo = protocolo_class
            return {"clase": protocolo_class, "tipo": "gym"}
        else:
            # Compatibilidad con estructura antigua
            self.setup = local_vars.get("setup") if callable(local_vars.get("setup")) else None
            self.loop = local_vars.get("loop") if callable(local_vars.get("loop")) else None
            fn = local_vars.get("custom_action")
            
            # Al menos una de loop/custom_action debe existir
            if not callable(self.loop) and not callable(fn):
                raise ValueError("El protocolo debe definir una clase que herede de ProtocoloBase, o 'loop(obs, ctx)' o 'custom_action(obs[, ctx])'.")
            
            self.funcion = fn if callable(fn) else None
            return {"setup": self.setup, "loop": self.loop, "custom_action": self.funcion, "tipo": "legacy"}
    
    def crear_instancia(self, **kwargs) -> ProtocoloBase:
        """Crear una instancia del protocolo con parámetros"""
        if self.clase_protocolo:
            # Nueva estructura Gym-like
            self.instancia = self.clase_protocolo(**kwargs)
            return self.instancia
        else:
            # Crear wrapper para estructura antigua
            return LegacyProtocoloWrapper(
                setup=self.setup,
                loop=self.loop,
                custom_action=self.funcion,
                **kwargs
            )

    @staticmethod
    def listar(root: str = "protocolos") -> list[str]:
        if not os.path.exists(root):
            return []
        return [f[:-3] for f in os.listdir(root) if f.endswith('.py') and not f.startswith('__')]


# -----------------------------------------------------------------------------
# ProtocolRunner
# -----------------------------------------------------------------------------
class ProtocolRunner:
    def __init__(
        self,
        env,
        protocols_dir: str,
        *,
        tick_hz: float = 50.0,
        default_timeout_s: float = 60.0,
    ):
        self._env = env
        self._dir = protocols_dir
        self._tick = max(0.005, 1.0 / float(tick_hz))
        self._default_timeout_s = float(default_timeout_s)

        self._thr: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()

        # Protocolo actual
        self._nombre: Optional[str] = None
        self._protocolo: Optional[ProtocoloBase] = None
        self._started_at: Optional[float] = None
        self._timeout_s: float = self._default_timeout_s
        self._done: bool = False
        self._last_log: Optional[str] = None
        
        # Objetivos y umbrales
        self._target_x: Optional[float] = None
        self._target_a: Optional[float] = None
        self._thr_x: float = 1.0
        self._thr_a: float = 1.0
        
        # Observaciones y configuración
        self._final_obs: Optional[Dict[str, Any]] = None
        self._final_state: Optional[Dict[str, Any]] = None
        self._execution_history: List[Dict[str, Any]] = []
        self._sensor_config: Dict[str, bool] = self._get_default_sensor_config()
        self._log_lines: List[str] = []
        
        # Control de tareas
        self._task_controlled: bool = False
        self._task_duration: Optional[float] = None
        self._task_start_time: Optional[float] = None
        self._continuous_mode: bool = False
        
        # Recompensas
        self._reward_sum: float = 0.0
        self._last_reward_value: Optional[float] = None
        
        # Debug unificado
        self._debug_buffer: List[str] = []
        self._max_debug_lines: int = 50

    def _get_default_sensor_config(self) -> Dict[str, bool]:
        """Configuración por defecto de sensores - todos activos"""
        return {
            "x_mm": True, "a_deg": True, "z_mm": True, "modo": True,
            "volumen_ml": True, "caudal_est_mls": True, "energiaX": True, "energiaA": True,
            "energiaBomba": True, "setpointX": True, "setpointA": True, "setpointZ": True,
            "kp_x": True, "ki_x": True, "kd_x": True, "kp_a": True, "ki_a": True, "kd_a": True,
            "rx_age_ms": True, "serial_open": True, "stale": True
        }
    
    def _add_debug(self, message: str):
        """Agregar mensaje al buffer de debug unificado"""
        timestamp = time.strftime("%H:%M:%S")
        debug_line = f"[{timestamp}] {message}"
        self._debug_buffer.append(debug_line)
        
        # Mantener solo las últimas N líneas
        if len(self._debug_buffer) > self._max_debug_lines:
            self._debug_buffer = self._debug_buffer[-self._max_debug_lines:]
        
        print(debug_line)  # También imprimir en terminal
    
    def get_debug_log(self) -> str:
        """Obtener el log de debug unificado"""
        return "\n".join(self._debug_buffer[-20:])  # Últimas 20 líneas

    def activate(self, nombre: str, params: Optional[Dict[str, Any]] = None) -> bool:
        """Activa un protocolo por nombre con parámetros opcionales."""
        try:
            params = params or {}
            self.stop()
            
            # Cargar nuevo protocolo
            protocolo = Protocolo(nombre, self._dir)
            meta = protocolo.cargar()
            
            # Crear copia de parámetros originales para el protocolo ANTES de modificar params
            protocolo_params = params.copy()
            print(f"[DEBUG] ProtocolRunner: parámetros originales: {params}")
            print(f"[DEBUG] ProtocolRunner: copia para protocolo: {protocolo_params}")
            
            with self._lock:
                self._nombre = nombre
                self._started_at = time.time()
                self._timeout_s = float(params.get("timeout_seconds", self._default_timeout_s))
                self._done = False
                self._last_log = None
                self._reward_sum = 0.0
                self._last_reward_value = None
                
                # Objetivos y umbrales (con fallback desde x_mm/a_deg/threshold)
                self._target_x = _maybe_float(params.get("target_x_mm"))
                self._target_a = _maybe_float(params.get("target_a_deg"))
                if self._target_x is None:
                    self._target_x = _maybe_float(params.get("x_mm"))
                if self._target_a is None:
                    self._target_a = _maybe_float(params.get("a_deg"))
                self._thr_x = float(params.get("threshold_x_mm", params.get("threshold", 1.0)))
                self._thr_a = float(params.get("threshold_a_deg", params.get("threshold", 1.0)))
                
                # Crear instancia del protocolo con parámetros originales
                # Los parámetros originales se pasan al protocolo para que los maneje internamente
                print(f"[DEBUG] ProtocolRunner: pasando parámetros al protocolo: {protocolo_params}")
                self._protocolo = protocolo.crear_instancia(**protocolo_params)
                
                # Pasar el entorno al protocolo para que pueda obtener datos reales
                if hasattr(self._protocolo, 'env'):
                    self._protocolo.env = self._env
                
                # Limpiar observaciones y configurar sensores
                self._final_obs = None
                self._final_state = None
                self._execution_history = []
                self._log_lines = []
                
                # Configurar sensores según parámetros del cliente
                if "sensor_config" in params:
                    self._sensor_config.update(params["sensor_config"])
                
                # Configurar control de tareas
                self._task_controlled = bool(params.get("task_controlled", False))
                self._task_duration = _maybe_float(params.get("task_duration"))
                self._task_start_time = time.time() if self._task_controlled else None
                self._continuous_mode = bool(params.get("continuous_mode", True))
                self._stop_evt.clear()
            
            # Llamar setup si existe
            if hasattr(self._protocolo, 'setup'):
                try:
                    self._protocolo.setup(self._env)
                except Exception as e:
                    print(f"Error en setup del protocolo {nombre}: {e}")
            
            # Reset del protocolo
            try:
                self._protocolo.reset()
            except Exception as e:
                print(f"Error en reset del protocolo {nombre}: {e}")
            
            # Iniciar hilo de ejecución
            self._thr = threading.Thread(target=self._loop, daemon=True)
            self._thr.start()
            
            return True
            
        except Exception as e:
            print(f"Error activando protocolo {nombre}: {e}")
            return False

    def stop(self):
        """Detener el protocolo activo"""
        self._stop_evt.set()
        thr = self._thr
        if thr and thr.is_alive():
            thr.join(timeout=1.0)
        with self._lock:
            self._thr = None
            self._nombre = None
            self._started_at = None
            self._done = True

    def _loop(self):
        """Loop principal que ejecuta el protocolo usando la interfaz Gym-like"""
        try:
            while not self._stop_evt.is_set():
                # timeout (solo si no está en modo continuo)
                if not self._continuous_mode and self._started_at and (time.time() - self._started_at) > self._timeout_s:
                    with self._lock:
                        self._done = True
                        self._last_log = "Timeout alcanzado"
                    break
                
                # Verificar si se alcanzó la duración de la tarea
                if self._task_controlled and self.is_task_duration_reached():
                    with self._lock:
                        self._done = True
                        self._last_log = f"Duración de tarea alcanzada ({self._task_duration}s)"
                    break

                # Obtener observación actual del entorno
                obs = self._obs_asegurada()
                if obs is None:
                    time.sleep(self._tick)
                    continue
                
                # Capturar observación en el historial
                self._capture_observation(obs)
                
                # Ejecutar un paso del protocolo usando la interfaz Gym
                try:
                    if self._protocolo:
                        # Convertir obs a formato esperado por el protocolo
                        obs_array = self._obs_to_array(obs)
                        
                        # Pasar las observaciones reales al protocolo
                        self._protocolo._last_obs = obs
                        
                        # FORZAR actualización de posiciones en el protocolo
                        if hasattr(self._protocolo, 'current_x') and isinstance(obs, dict):
                            new_x = float(obs.get('x_mm', 0.0))
                            new_a = float(obs.get('a_deg', 0.0))
                            self._protocolo.current_x = new_x
                            self._protocolo.current_a = new_a
                            self._add_debug(f"ProtocolRunner: Actualizando posiciones - current_x={new_x}, current_a={new_a}")
                        
                        # Ejecutar step del protocolo
                        obs_protocolo, reward, done, info = self._protocolo.step()
                        
                        # Procesar resultado
                        patch = info.get("patch", {}) if isinstance(info, dict) else {}
                        sleep_ms = info.get("sleep_ms", 100) if isinstance(info, dict) else 100
                        log = info.get("log", "") if isinstance(info, dict) else ""
                        
                        # Actualizar reward
                        self._last_reward_value = float(reward)
                        self._reward_sum += float(reward)
                        
                        # Aplicar patch al entorno si existe
                        if patch:
                            try:
                                self._env.apply_patch(patch, _interno=True) if hasattr(self._env, "apply_patch") else self._env.patch(patch, _in=True)
                            except Exception as e:
                                print(f"Error aplicando patch: {e}")
                            self._step_env()
                        
                        # Verificar si el protocolo terminó
                        if done:
                            debug_msg = f"[DEBUG] ProtocolRunner: Protocolo marcó DONE=True, deteniendo ejecución"
                            print(debug_msg)
                            with self._lock:
                                self._done = True
                                self._last_log = (log or "Protocolo completado") + f"\n{debug_msg}"
                            break
                        
                        # Log del protocolo
                        if log:
                            try:
                                self._append_log(log)
                            except Exception:
                                pass
                        
                        # Criterio de llegada si hay target
                        if self._target_reached(obs):
                            should_stop = (not self._continuous_mode) or bool(self._protocolo.params.get('stop_on_reach', False))
                            if should_stop:
                                with self._lock:
                                    self._done = True
                                    self._last_log = "Objetivo alcanzado"
                                break
                        
                        # Espera según el protocolo
                        if sleep_ms > 0:
                            time.sleep(max(self._tick, sleep_ms / 1000.0))
                        else:
                            time.sleep(self._tick)
                    else:
                        time.sleep(self._tick)
                        
                except Exception as e:
                    print(f"Error en step del protocolo: {e}")
                    with self._lock:
                        self._done = True
                        self._last_log = f"Error: {e}"
                    break
                    
        finally:
            # Capturar observaciones finales antes de parada segura
            self._capture_final_state()
            
            # Llamar finalize si existe
            if self._protocolo and hasattr(self._protocolo, 'finalize'):
                try:
                    self._protocolo.finalize(self._env)
                except Exception as e:
                    print(f"Error en finalize del protocolo: {e}")

    def _obs_asegurada(self):
        """Obtiene una observación del entorno de forma segura"""
        try:
            # Intentar obtener observación sin hacer step
            if hasattr(self._env, '_obs_now'):
                obs = self._env._obs_now()
                if obs is not None:
                    return obs
        except Exception:
            pass
        
        # Si no se pudo obtener sin step, hacer un step
        try:
            step_result = self._step_env()
            if step_result is not None:
                return step_result[0]  # El primer elemento del resultado del step
        except Exception:
            pass
        
        return None

    def _obs_to_array(self, obs):
        """Convierte observación del entorno a array numpy para el protocolo"""
        try:
            if isinstance(obs, np.ndarray):
                return obs
            elif isinstance(obs, (list, tuple)):
                return np.array(obs, dtype=np.float32)
            elif isinstance(obs, dict):
                # Convertir dict a array usando las claves conocidas
                array_data = []
                keys = ['x_mm', 'a_deg', 'z_mm', 'volumen_ml', 'caudal_est_mls', 'modo']
                for key in keys:
                    array_data.append(obs.get(key, 0.0))
                return np.array(array_data, dtype=np.float32)
            else:
                return np.zeros(22, dtype=np.float32)
        except Exception:
            return np.zeros(22, dtype=np.float32)

    def _step_env(self):
        """Ejecuta un step del entorno físico"""
        try:
            with getattr(self._env, "lk", threading.Lock()):
                act = getattr(self._env, "act", None)
                result = self._env.step(act)
                return result
        except Exception:
            # Fallback: intentar con acción None
            try:
                result = self._env.step(None)
                return result
            except Exception:
                return None

    def _append_log(self, msg: str):
        try:
            ts = time.strftime("%H:%M:%S")
            line = f"[{ts}] {str(msg)}"
            self._log_lines.append(line)
            if len(self._log_lines) > 500:
                self._log_lines = self._log_lines[-500:]
        except Exception:
            pass

    def _capture_observation(self, obs):
        """Captura una observación en el historial de ejecución"""
        try:
            if isinstance(obs, dict):
                self._execution_history.append(obs.copy())
            else:
                # Convertir array a dict si es necesario
                obs_dict = {
                    'x_mm': float(obs[0]) if len(obs) > 0 else 0.0,
                    'a_deg': float(obs[1]) if len(obs) > 1 else 0.0,
                    'z_mm': float(obs[2]) if len(obs) > 2 else 0.0,
                    'volumen_ml': float(obs[3]) if len(obs) > 3 else 0.0,
                    'caudal_est_mls': float(obs[4]) if len(obs) > 4 else 0.0,
                    'modo': int(obs[5]) if len(obs) > 5 else 0
                }
                self._execution_history.append(obs_dict)
        except Exception:
            pass

    def _capture_final_state(self):
        """Captura el estado final antes de parar"""
        try:
            if self._execution_history:
                self._final_obs = self._execution_history[-1]
            self._final_state = {
                'total_steps': len(self._execution_history),
                'total_reward': self._reward_sum,
                'final_log': self._last_log
            }
        except Exception as e:
            with self._lock:
                self._last_log = f"Error capturando estado final: {e}"

    def _target_reached(self, obs):
        """Verifica si se alcanzó el objetivo"""
        if self._target_x is None and self._target_a is None:
            return False
        
        try:
            if isinstance(obs, dict):
                x = obs.get('x_mm', 0.0)
                a = obs.get('a_deg', 0.0)
            else:
                x = float(obs[0]) if len(obs) > 0 else 0.0
                a = float(obs[1]) if len(obs) > 1 else 0.0
            
            x_ok = self._target_x is None or abs(x - self._target_x) <= self._thr_x
            a_ok = self._target_a is None or abs(a - self._target_a) <= self._thr_a
            
            return x_ok and a_ok
        except Exception:
            return False

    def is_task_duration_reached(self) -> bool:
        """Verifica si se alcanzó la duración de la tarea"""
        if not self._task_controlled or self._task_duration is None or self._task_start_time is None:
            return False
        return (time.time() - self._task_start_time) >= self._task_duration

    def get_task_elapsed_time(self) -> float:
        """Obtiene el tiempo transcurrido desde el inicio de la tarea"""
        if not self._task_controlled or self._task_start_time is None:
            return 0.0
        return time.time() - self._task_start_time

    def get_task_remaining_time(self) -> Optional[float]:
        """Obtiene el tiempo restante de la tarea"""
        if not self._task_controlled or self._task_duration is None or self._task_start_time is None:
            return None
        elapsed = self.get_task_elapsed_time()
        remaining = self._task_duration - elapsed
        return max(0.0, remaining)
    
    @property
    def nombre(self):
        """Obtener el nombre del protocolo activo"""
        return self._nombre
    
    @property
    def is_active(self):
        """Verificar si hay un protocolo activo"""
        return self._thr is not None and self._thr.is_alive()
    
    @property
    def done(self):
        """Verificar si el protocolo terminó"""
        return self._done
    
    def status(self):
        """Obtener estado del runner (compatible con servidor)"""
        from dataclasses import dataclass
        
        @dataclass
        class RunnerStatus:
            activo: bool
            nombre: Optional[str]
            started_at: Optional[float]
            elapsed_s: float
            done: bool
            last_log: Optional[str]
            message: Optional[str] = None
            final_obs: Optional[Dict[str, Any]] = None
            final_state: Optional[Dict[str, Any]] = None
            execution_history: Optional[List[Dict[str, Any]]] = None
            sensor_config: Optional[Dict[str, bool]] = None
            logs: Optional[List[str]] = None
            reward_sum: Optional[float] = None
            reward_threshold: Optional[float] = None
            last_reward: Optional[float] = None
        
        with self._lock:
            activo = self._thr is not None and self._thr.is_alive()
            started_at = self._started_at
            elapsed = 0.0 if not started_at else max(0.0, time.time() - started_at)
            
            return RunnerStatus(
                activo=activo,
                nombre=self._nombre,
                started_at=started_at,
                elapsed_s=elapsed,
                done=self._done,
                last_log=self._last_log,
                message=None,
                final_obs=self._final_obs,
                final_state=self._final_state,
                execution_history=self._execution_history,
                sensor_config=self._sensor_config,
                logs=self._log_lines[-100:] + [f"=== DEBUG UNIFICADO ===\n{self.get_debug_log()}"],
                reward_sum=self._reward_sum,
                reward_threshold=None,
                last_reward=self._last_reward_value
            )


def _maybe_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None
