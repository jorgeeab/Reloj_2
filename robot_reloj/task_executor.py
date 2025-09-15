#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TaskExecutor - Ejecutor Unificado de Tareas y Protocolos
=======================================================

Nueva arquitectura donde:
- PROTOCOLOS: Mantienen capacidad de ejecutar continuamente su función
- TAREAS: Son indicadores de CUÁNDO ejecutar un protocolo y HASTA CUÁNTO TIEMPO

El TaskExecutor maneja tanto ejecución síncrona como asíncrona con timeout de 25 segundos.
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Callable, Union
from enum import Enum
import json

class ExecutionMode(Enum):
    """Modos de ejecución"""
    SYNC = "sync"      # Espera hasta completar o timeout
    ASYNC = "async"    # Devuelve inmediatamente con execution_id

class TaskStatus(Enum):
    """Estados de una tarea"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    STOPPED = "stopped"

@dataclass
class TaskResult:
    """Resultado de ejecución de una tarea"""
    task_id: str
    status: TaskStatus
    started_at: float
    ended_at: Optional[float] = None
    duration: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    log: list = field(default_factory=list)
    progress: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.ended_at and self.started_at:
            self.duration = self.ended_at - self.started_at

@dataclass
class TaskDefinition:
    """Definición de una tarea"""
    id: str
    name: str
    protocol_name: str
    duration_seconds: float = 10.0
    timeout_seconds: float = 25.0
    params: Dict[str, Any] = field(default_factory=dict)
    auto_stop: bool = True
    priority: int = 0  # Mayor número = mayor prioridad

class TaskExecutor:
    """
    Ejecutor unificado que coordina protocolos con tareas de tiempo.
    
    Arquitectura:
    - Los protocolos mantienen su función continua
    - Las tareas indican cuándo y cuánto tiempo ejecutar
    - Soporte para ejecución síncrona (espera) y asíncrona (inmediata)
    """
    
    def __init__(self, protocol_runner, robot_env, logger=None):
        self.protocol_runner = protocol_runner
        self.robot_env = robot_env
        self.logger = logger or print
        
        # Estado interno
        self._lock = threading.Lock()
        self._active_tasks: Dict[str, TaskResult] = {}
        self._completed_tasks: Dict[str, TaskResult] = {}
        self._task_counter = 0
        
        # Configuración por defecto
        self.default_timeout = 25.0
        self.max_concurrent_tasks = 3
        
    def execute_task(
        self, 
        task_def: TaskDefinition, 
        mode: ExecutionMode = ExecutionMode.SYNC
    ) -> Union[TaskResult, str]:
        """
        Ejecuta una tarea según el modo especificado.
        
        Args:
            task_def: Definición de la tarea
            mode: Modo de ejecución (SYNC o ASYNC)
            
        Returns:
            - SYNC: TaskResult con el resultado completo
            - ASYNC: str con execution_id para consultar estado
        """
        with self._lock:
            # Verificar límite de tareas concurrentes
            if len(self._active_tasks) >= self.max_concurrent_tasks:
                raise RuntimeError(f"Máximo {self.max_concurrent_tasks} tareas concurrentes permitidas")
            
            # Crear resultado de tarea
            task_result = TaskResult(
                task_id=task_def.id,
                status=TaskStatus.PENDING,
                started_at=time.time()
            )
            
            self._active_tasks[task_def.id] = task_result
            
        # Ejecutar según el modo
        if mode == ExecutionMode.SYNC:
            return self._execute_sync(task_def, task_result)
        else:
            return self._execute_async(task_def, task_result)
    
    def _execute_sync(self, task_def: TaskDefinition, task_result: TaskResult) -> TaskResult:
        """Ejecuta tarea de forma síncrona - espera hasta completar o timeout"""
        try:
            self.logger(f"[TaskExecutor] Iniciando ejecución síncrona: {task_def.name}")
            
            # Actualizar estado
            with self._lock:
                task_result.status = TaskStatus.RUNNING
                task_result.log.append(f"Iniciando protocolo '{task_def.protocol_name}' por {task_def.duration_seconds}s")
            
            # Activar protocolo
            self.protocol_runner.activate(
                task_def.protocol_name, 
                params=task_def.params
            )
            
            # Esperar hasta completar o timeout
            start_time = time.time()
            timeout_time = start_time + task_def.timeout_seconds
            duration_time = start_time + task_def.duration_seconds
            
            while time.time() < timeout_time:
                # Verificar si el protocolo terminó naturalmente
                status = self.protocol_runner.status()
                if status.done:
                    break
                
                # Verificar si se alcanzó la duración deseada
                if time.time() >= duration_time:
                    if task_def.auto_stop:
                        self.logger(f"[TaskExecutor] Duración alcanzada, deteniendo protocolo")
                        self.protocol_runner.stop()
                    break
                
                # Pequeña espera para no saturar CPU
                time.sleep(0.1)
            
            # Verificar si fue timeout
            if time.time() >= timeout_time:
                with self._lock:
                    task_result.status = TaskStatus.TIMEOUT
                    task_result.log.append(f"Timeout alcanzado ({task_def.timeout_seconds}s)")
                self.protocol_runner.stop()
            else:
                with self._lock:
                    task_result.status = TaskStatus.COMPLETED
                    task_result.log.append("Tarea completada exitosamente")
            
            # Obtener resultado final del protocolo
            final_status = self.protocol_runner.status()
            task_result.result = {
                "protocol_name": task_def.protocol_name,
                "final_status": final_status,
                "execution_history": final_status.execution_history,
                "final_obs": final_status.final_obs
            }
            
        except Exception as e:
            with self._lock:
                task_result.status = TaskStatus.FAILED
                task_result.error = str(e)
                task_result.log.append(f"Error: {e}")
            self.logger(f"[TaskExecutor] Error en ejecución síncrona: {e}")
            self.protocol_runner.stop()
        
        finally:
            # Finalizar tarea
            with self._lock:
                task_result.ended_at = time.time()
                # Mover a completadas
                self._completed_tasks[task_def.id] = task_result
                if task_def.id in self._active_tasks:
                    del self._active_tasks[task_def.id]
        
        return task_result
    
    def _execute_async(self, task_def: TaskDefinition, task_result: TaskResult) -> str:
        """Ejecuta tarea de forma asíncrona - devuelve execution_id inmediatamente"""
        def async_worker():
            try:
                with self._lock:
                    task_result.status = TaskStatus.RUNNING
                    task_result.log.append(f"Iniciando protocolo '{task_def.protocol_name}' por {task_def.duration_seconds}s")
                
                # Activar protocolo
                self.protocol_runner.activate(
                    task_def.protocol_name, 
                    params=task_def.params
                )
                
                # Esperar hasta completar o timeout
                start_time = time.time()
                timeout_time = start_time + task_def.timeout_seconds
                duration_time = start_time + task_def.duration_seconds
                
                while time.time() < timeout_time:
                    # Verificar si el protocolo terminó naturalmente
                    status = self.protocol_runner.status()
                    if status.done:
                        break
                    
                    # Verificar si se alcanzó la duración deseada
                    if time.time() >= duration_time:
                        if task_def.auto_stop:
                            self.logger(f"[TaskExecutor] Duración alcanzada, deteniendo protocolo")
                            self.protocol_runner.stop()
                        break
                    
                    time.sleep(0.1)
                
                # Verificar si fue timeout
                if time.time() >= timeout_time:
                    with self._lock:
                        task_result.status = TaskStatus.TIMEOUT
                        task_result.log.append(f"Timeout alcanzado ({task_def.timeout_seconds}s)")
                    self.protocol_runner.stop()
                else:
                    with self._lock:
                        task_result.status = TaskStatus.COMPLETED
                        task_result.log.append("Tarea completada exitosamente")
                
                # Obtener resultado final
                final_status = self.protocol_runner.status()
                task_result.result = {
                    "protocol_name": task_def.protocol_name,
                    "final_status": final_status,
                    "execution_history": final_status.execution_history,
                    "final_obs": final_status.final_obs
                }
                
            except Exception as e:
                with self._lock:
                    task_result.status = TaskStatus.FAILED
                    task_result.error = str(e)
                    task_result.log.append(f"Error: {e}")
                self.logger(f"[TaskExecutor] Error en ejecución asíncrona: {e}")
                self.protocol_runner.stop()
            
            finally:
                # Finalizar tarea
                with self._lock:
                    task_result.ended_at = time.time()
                    # Mover a completadas
                    self._completed_tasks[task_def.id] = task_result
                    if task_def.id in self._active_tasks:
                        del self._active_tasks[task_def.id]
        
        # Iniciar hilo de ejecución
        thread = threading.Thread(target=async_worker, daemon=True)
        thread.start()
        
        return task_def.id
    
    def stop_task(self, task_id: str) -> bool:
        """Detiene una tarea en ejecución"""
        with self._lock:
            if task_id in self._active_tasks:
                task_result = self._active_tasks[task_id]
                task_result.status = TaskStatus.STOPPED
                task_result.ended_at = time.time()
                task_result.log.append("Tarea detenida por solicitud")
                
                # Mover a completadas
                self._completed_tasks[task_id] = task_result
                del self._active_tasks[task_id]
                
                # Detener protocolo
                self.protocol_runner.stop()
                return True
            return False
    
    def get_task_status(self, task_id: str) -> Optional[TaskResult]:
        """Obtiene el estado de una tarea"""
        with self._lock:
            # Buscar en activas
            if task_id in self._active_tasks:
                return self._active_tasks[task_id]
            # Buscar en completadas
            if task_id in self._completed_tasks:
                return self._completed_tasks[task_id]
            return None
    
    def list_active_tasks(self) -> list:
        """Lista tareas activas"""
        with self._lock:
            return list(self._active_tasks.values())
    
    def list_recent_tasks(self, limit: int = 10) -> list:
        """Lista tareas recientes (completadas)"""
        with self._lock:
            recent = list(self._completed_tasks.values())
            # Ordenar por tiempo de finalización (más recientes primero)
            recent.sort(key=lambda x: x.ended_at or 0, reverse=True)
            return recent[:limit]
    
    def create_task_definition(
        self,
        name: str,
        protocol_name: str,
        duration_seconds: float = 10.0,
        timeout_seconds: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
        auto_stop: bool = True,
        priority: int = 0
    ) -> TaskDefinition:
        """Crea una definición de tarea"""
        with self._lock:
            self._task_counter += 1
            task_id = f"task_{self._task_counter:05d}"
        
        return TaskDefinition(
            id=task_id,
            name=name,
            protocol_name=protocol_name,
            duration_seconds=duration_seconds,
            timeout_seconds=timeout_seconds or self.default_timeout,
            params=params or {},
            auto_stop=auto_stop,
            priority=priority
        )

# Funciones de conveniencia para crear tareas comunes
def create_irrigation_task(
    name: str,
    duration_seconds: float = 10.0,
    volume_ml: float = 100.0,
    timeout_seconds: float = 25.0
) -> TaskDefinition:
    """Crea una tarea de riego"""
    return TaskDefinition(
        id=f"irrigation_{int(time.time())}",
        name=name,
        protocol_name="riego_basico",
        duration_seconds=duration_seconds,
        timeout_seconds=timeout_seconds,
        params={"volume_ml": volume_ml},
        auto_stop=True
    )

def create_movement_task(
    name: str,
    duration_seconds: float = 5.0,
    x_mm: float = 0.0,
    a_deg: float = 0.0,
    timeout_seconds: float = 25.0
) -> TaskDefinition:
    """Crea una tarea de movimiento"""
    return TaskDefinition(
        id=f"movement_{int(time.time())}",
        name=name,
        protocol_name="movimiento_basico",
        duration_seconds=duration_seconds,
        timeout_seconds=timeout_seconds,
        params={"x_mm": x_mm, "a_deg": a_deg},
        auto_stop=True
    )

def create_test_task(
    name: str,
    duration_seconds: float = 3.0,
    test_type: str = "basic",
    timeout_seconds: float = 25.0
) -> TaskDefinition:
    """Crea una tarea de prueba"""
    return TaskDefinition(
        id=f"test_{int(time.time())}",
        name=name,
        protocol_name="prueba_basica",
        duration_seconds=duration_seconds,
        timeout_seconds=timeout_seconds,
        params={"test_type": test_type},
        auto_stop=True
    )
