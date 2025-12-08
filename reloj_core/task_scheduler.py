#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TaskScheduler - Coordinador de Protocolos con Tareas de Tiempo
=============================================================

Nueva arquitectura donde las tareas son solo indicadores de:
- CUÁNDO ejecutar un protocolo
- HASTA CUÁNTO TIEMPO ejecutarlo
- QUÉ PARÁMETROS usar

El TaskScheduler coordina el ProtocolRunner con las tareas programadas.
"""

import time
import threading
import json
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, Callable
from enum import Enum
from pathlib import Path

from .task_executor import TaskExecutor, TaskDefinition, ExecutionMode, TaskStatus

class ScheduleType(Enum):
    """Tipos de programación de tareas"""
    ONCE = "una_vez"           # Ejecutar una sola vez
    INTERVAL = "cada_segundos"  # Cada X segundos
    DAILY = "diario"           # Diario a una hora
    WEEKLY = "semanal"         # Semanal en días específicos
    HOURLY = "cada_horas"      # Cada X horas
    CONTINUOUS = "continuo"    # Ejecución continua

@dataclass
class TaskSchedule:
    """Programación de una tarea"""
    task_id: str
    name: str
    protocol_name: str
    schedule_type: ScheduleType
    duration_seconds: float = 10.0
    timeout_seconds: float = 25.0
    params: Dict[str, Any] = field(default_factory=dict)
    auto_stop: bool = True
    priority: int = 0
    
    # Parámetros de programación
    schedule_params: Dict[str, Any] = field(default_factory=dict)
    
    # Estado
    active: bool = True
    last_execution: Optional[datetime] = None
    next_execution: Optional[datetime] = None
    execution_count: int = 0
    max_executions: Optional[int] = None  # None = ilimitado
    
    def __post_init__(self):
        if self.next_execution is None:
            self.next_execution = self._calculate_next_execution()

class TaskScheduler:
    """
    Coordinador que programa y ejecuta tareas según su programación.
    
    Las tareas indican CUÁNDO y CUÁNTO TIEMPO ejecutar protocolos.
    """
    
    def __init__(self, task_executor: TaskExecutor, logger=None):
        self.task_executor = task_executor
        self.logger = logger or print
        
        # Estado interno
        self._lock = threading.Lock()
        self._schedules: Dict[str, TaskSchedule] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Configuración
        self.check_interval = 1.0  # Verificar cada segundo
        self.max_concurrent_tasks = 3
        
    def start(self):
        """Inicia el programador de tareas"""
        if self._running:
            return
        
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        self.logger("[TaskScheduler] Programador iniciado")
    
    def stop(self):
        """Detiene el programador de tareas"""
        if not self._running:
            return
        
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.logger("[TaskScheduler] Programador detenido")
    
    def add_schedule(self, schedule: TaskSchedule) -> str:
        """Agrega una nueva programación de tarea"""
        with self._lock:
            self._schedules[schedule.task_id] = schedule
            self.logger(f"[TaskScheduler] Programación agregada: {schedule.name}")
        return schedule.task_id
    
    def remove_schedule(self, task_id: str) -> bool:
        """Elimina una programación de tarea"""
        with self._lock:
            if task_id in self._schedules:
                del self._schedules[task_id]
                self.logger(f"[TaskScheduler] Programación eliminada: {task_id}")
                return True
            return False
    
    def update_schedule(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """Actualiza una programación existente"""
        with self._lock:
            if task_id in self._schedules:
                schedule = self._schedules[task_id]
                for key, value in updates.items():
                    if hasattr(schedule, key):
                        setattr(schedule, key, value)
                
                # Recalcular próxima ejecución
                schedule.next_execution = schedule._calculate_next_execution()
                self.logger(f"[TaskScheduler] Programación actualizada: {task_id}")
                return True
            return False
    
    def get_schedule(self, task_id: str) -> Optional[TaskSchedule]:
        """Obtiene una programación por ID"""
        with self._lock:
            return self._schedules.get(task_id)
    
    def list_schedules(self) -> List[TaskSchedule]:
        """Lista todas las programaciones"""
        with self._lock:
            return list(self._schedules.values())
    
    def execute_task_now(self, task_id: str, mode: ExecutionMode = ExecutionMode.ASYNC) -> Any:
        """Ejecuta una tarea inmediatamente, ignorando su programación"""
        with self._lock:
            schedule = self._schedules.get(task_id)
            if not schedule:
                raise ValueError(f"Tarea no encontrada: {task_id}")
        
        # Crear definición de tarea
        task_def = TaskDefinition(
            id=f"{task_id}_manual_{int(time.time())}",
            name=f"{schedule.name} (manual)",
            protocol_name=schedule.protocol_name,
            duration_seconds=schedule.duration_seconds,
            timeout_seconds=schedule.timeout_seconds,
            params=schedule.params.copy(),
            auto_stop=schedule.auto_stop,
            priority=schedule.priority
        )
        
        # Ejecutar
        return self.task_executor.execute_task(task_def, mode)
    
    def _scheduler_loop(self):
        """Loop principal del programador"""
        self.logger("[TaskScheduler] Loop de programación iniciado")
        
        while not self._stop_event.is_set():
            try:
                current_time = datetime.now()
                
                # Verificar tareas que deben ejecutarse
                tasks_to_execute = []
                
                with self._lock:
                    for schedule in self._schedules.values():
                        if (schedule.active and 
                            schedule.next_execution and 
                            schedule.next_execution <= current_time):
                            
                            # Verificar límite de ejecuciones
                            if (schedule.max_executions is not None and 
                                schedule.execution_count >= schedule.max_executions):
                                schedule.active = False
                                continue
                            
                            tasks_to_execute.append(schedule)
                
                # Ejecutar tareas pendientes
                for schedule in tasks_to_execute:
                    self._execute_scheduled_task(schedule)
                
                # Pequeña espera
                time.sleep(self.check_interval)
                
            except Exception as e:
                self.logger(f"[TaskScheduler] Error en loop: {e}")
                time.sleep(1.0)
        
        self.logger("[TaskScheduler] Loop de programación terminado")
    
    def _execute_scheduled_task(self, schedule: TaskSchedule):
        """Ejecuta una tarea programada"""
        try:
            self.logger(f"[TaskScheduler] Ejecutando tarea programada: {schedule.name}")
            
            # Crear definición de tarea
            task_def = TaskDefinition(
                id=f"{schedule.task_id}_{int(time.time())}",
                name=schedule.name,
                protocol_name=schedule.protocol_name,
                duration_seconds=schedule.duration_seconds,
                timeout_seconds=schedule.timeout_seconds,
                params=schedule.params.copy(),
                auto_stop=schedule.auto_stop,
                priority=schedule.priority
            )
            
            # Ejecutar de forma asíncrona
            execution_id = self.task_executor.execute_task(task_def, ExecutionMode.ASYNC)
            
            # Actualizar estado de la programación
            with self._lock:
                schedule.last_execution = datetime.now()
                schedule.execution_count += 1
                schedule.next_execution = schedule._calculate_next_execution()
            
            self.logger(f"[TaskScheduler] Tarea {schedule.name} ejecutada (ID: {execution_id})")
            
        except Exception as e:
            self.logger(f"[TaskScheduler] Error ejecutando tarea {schedule.name}: {e}")

# Métodos de conveniencia para crear programaciones
def create_daily_schedule(
    name: str,
    protocol_name: str,
    hour: int = 8,
    minute: int = 0,
    duration_seconds: float = 10.0,
    **kwargs
) -> TaskSchedule:
    """Crea una programación diaria"""
    return TaskSchedule(
        task_id=f"daily_{int(time.time())}",
        name=name,
        protocol_name=protocol_name,
        schedule_type=ScheduleType.DAILY,
        duration_seconds=duration_seconds,
        schedule_params={"hour": hour, "minute": minute},
        **kwargs
    )

def create_interval_schedule(
    name: str,
    protocol_name: str,
    interval_seconds: int = 3600,
    duration_seconds: float = 10.0,
    **kwargs
) -> TaskSchedule:
    """Crea una programación por intervalo"""
    return TaskSchedule(
        task_id=f"interval_{int(time.time())}",
        name=name,
        protocol_name=protocol_name,
        schedule_type=ScheduleType.INTERVAL,
        duration_seconds=duration_seconds,
        schedule_params={"interval_seconds": interval_seconds},
        **kwargs
    )

def create_continuous_schedule(
    name: str,
    protocol_name: str,
    duration_seconds: float = 60.0,
    **kwargs
) -> TaskSchedule:
    """Crea una programación continua"""
    return TaskSchedule(
        task_id=f"continuous_{int(time.time())}",
        name=name,
        protocol_name=protocol_name,
        schedule_type=ScheduleType.CONTINUOUS,
        duration_seconds=duration_seconds,
        schedule_params={"start_immediately": True},
        **kwargs
    )

# Extensión de TaskSchedule para calcular próxima ejecución
def _calculate_next_execution(self) -> Optional[datetime]:
    """Calcula la próxima ejecución basada en el tipo de programación"""
    now = datetime.now()
    
    if self.schedule_type == ScheduleType.ONCE:
        # Una sola vez - ejecutar inmediatamente
        return now
    
    elif self.schedule_type == ScheduleType.INTERVAL:
        # Cada X segundos
        interval = self.schedule_params.get("interval_seconds", 3600)
        if self.last_execution:
            return self.last_execution + timedelta(seconds=interval)
        else:
            return now
    
    elif self.schedule_type == ScheduleType.DAILY:
        # Diario a una hora específica
        hour = self.schedule_params.get("hour", 8)
        minute = self.schedule_params.get("minute", 0)
        next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        if next_time <= now:
            next_time += timedelta(days=1)
        
        return next_time
    
    elif self.schedule_type == ScheduleType.WEEKLY:
        # Semanal en días específicos
        days = self.schedule_params.get("days", [0])  # 0 = lunes
        hour = self.schedule_params.get("hour", 8)
        minute = self.schedule_params.get("minute", 0)
        
        # Encontrar el próximo día de la semana
        for days_ahead in range(7):
            candidate = now + timedelta(days=days_ahead)
            if candidate.weekday() in days:
                next_time = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if next_time > now:
                    return next_time
        
        # Si no se encuentra, usar el próximo lunes
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=7)
    
    elif self.schedule_type == ScheduleType.HOURLY:
        # Cada X horas
        interval = self.schedule_params.get("interval_hours", 1)
        if self.last_execution:
            return self.last_execution + timedelta(hours=interval)
        else:
            return now
    
    elif self.schedule_type == ScheduleType.CONTINUOUS:
        # Continuo - ejecutar inmediatamente
        return now
    
    return None

# Agregar el método a la clase TaskSchedule
TaskSchedule._calculate_next_execution = _calculate_next_execution
