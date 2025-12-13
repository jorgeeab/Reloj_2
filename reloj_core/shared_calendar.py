#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Calendario Compartido - Gestión unificada de tareas entre robots
=========================================================================

Este módulo proporciona:
- Calendario centralizado para tareas de todos los robots
- Gestión de tareas por fecha/hora
- Vistas de calendario: diaria, semanal, mensual
- Sincronización automática entre robots
- Persistencia de tareas en JSON

Similar al sistema de actuadores compartidos, este calendario permite
que todos los robots accedan al mismo conjunto de tareas programadas.
"""

import json
import threading
import time
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum

# =============================================================================
# TIPOS Y CLASES DE DATOS
# =============================================================================

class TaskPriority(Enum):
    """Prioridades de tareas"""
    LOW = "baja"
    MEDIUM = "media"
    HIGH = "alta"
    URGENT = "urgente"

class TaskState(Enum):
    """Estados de una tarea"""
    PENDING = "pendiente"      # No ha empezado
    SCHEDULED = "programada"   # Programada pero no ejecutada
    RUNNING = "ejecutando"     # En ejecución
    COMPLETED = "completada"   # Terminada con éxito
    FAILED = "fallida"         # Terminada con error
    CANCELLED = "cancelada"    # Cancelada por el usuario
    EXPIRED = "expirada"       # No ejecutada antes de deadline

@dataclass
class CalendarTask:
    """Tarea en el calendario compartido"""
    # Campos requeridos (sin valores por defecto) - DEBEN IR PRIMERO
    id: str
    title: str
    start_datetime: str  # ISO format: "2025-12-08T14:30:00"
    
    # Campos opcionales (con valores por defecto)
    description: str = ""
    end_datetime: Optional[str] = None
    duration_seconds: float = 600.0  # 10 minutos por defecto
    robot_id: str = "reloj"  # reloj, opuno, pump, etc.
    protocol_name: str = ""
    action_type: str = "custom"  # custom, irrigation, movement, test, etc.
    params: Dict[str, Any] = field(default_factory=dict)
    state: str = TaskState.PENDING.value
    priority: str = TaskPriority.MEDIUM.value
    recurring: bool = False
    recurrence_rule: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    created_by: str = "user"
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    execution_count: int = 0
    last_execution: Optional[str] = None
    next_execution: Optional[str] = None
    max_executions: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
        if not self.next_execution and self.start_datetime:
            self.next_execution = self.start_datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalendarTask":
        """Crea desde diccionario"""
        return cls(**data)

# =============================================================================
# CALENDARIO COMPARTIDO
# =============================================================================

class SharedCalendar:
    """
    Calendario compartido entre todos los robots del sistema.
    
    Características:
    - Tareas organizadas por fecha
    - Filtrado por robot, prioridad, estado
    - Vistas de calendario: día, semana, mes
    - Sincronización automática
    - Persistencia en JSON
    """
    
    def __init__(self, data_dir: Path, logger: Optional[Callable] = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.calendar_file = self.data_dir / "shared_calendar.json"
        self.logger = logger or print
        
        # Estado interno
        self._lock = threading.RLock()
        self._tasks: Dict[str, CalendarTask] = {}
        self._task_counter = 0
        
        # Callbacks para notificar cambios
        self._change_callbacks: List[Callable] = []
        
        # Cargar tareas existentes
        self._load_calendar()
        
        # Iniciar thread de limpieza y verificación
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
    
    # -------------------------------------------------------------------------
    # CRUD de Tareas
    # -------------------------------------------------------------------------
    
    def add_task(self, task: CalendarTask) -> str:
        """Agrega una tarea al calendario"""
        with self._lock:
            if not task.id:
                self._task_counter += 1
                task.id = f"task_{int(time.time())}_{self._task_counter:04d}"
            
            task.updated_at = datetime.now().isoformat()
            self._tasks[task.id] = task
            self._save_calendar()
            self._notify_change("task_added", task)
            
            self.logger(f"[SharedCalendar] Tarea agregada: {task.title} ({task.id})")
            return task.id
    
    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """Actualiza una tarea existente"""
        with self._lock:
            if task_id not in self._tasks:
                return False
            
            task = self._tasks[task_id]
            for key, value in updates.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            
            task.updated_at = datetime.now().isoformat()
            self._save_calendar()
            self._notify_change("task_updated", task)
            
            self.logger(f"[SharedCalendar] Tarea actualizada: {task.title}")
            return True
    
    def delete_task(self, task_id: str) -> bool:
        """Elimina una tarea del calendario"""
        with self._lock:
            if task_id not in self._tasks:
                return False
            
            task = self._tasks.pop(task_id)
            self._save_calendar()
            self._notify_change("task_deleted", task)
            
            self.logger(f"[SharedCalendar] Tarea eliminada: {task.title}")
            return True
    
    def get_task(self, task_id: str) -> Optional[CalendarTask]:
        """Obtiene una tarea por ID"""
        with self._lock:
            return self._tasks.get(task_id)
    
    def get_all_tasks(self) -> List[CalendarTask]:
        """Obtiene todas las tareas"""
        with self._lock:
            return list(self._tasks.values())
    
    # -------------------------------------------------------------------------
    # Filtros y Vistas
    # -------------------------------------------------------------------------
    
    def get_tasks_by_robot(self, robot_id: str) -> List[CalendarTask]:
        """Obtiene tareas de un robot específico"""
        with self._lock:
            return [t for t in self._tasks.values() if t.robot_id == robot_id]
    
    def get_tasks_by_date(self, target_date: date) -> List[CalendarTask]:
        """Obtiene tareas para una fecha específica"""
        with self._lock:
            tasks = []
            for task in self._tasks.values():
                try:
                    task_date = datetime.fromisoformat(task.start_datetime).date()
                    if task_date == target_date:
                        tasks.append(task)
                except:
                    continue
            return tasks
    
    def get_tasks_by_date_range(self, start_date: date, end_date: date) -> List[CalendarTask]:
        """Obtiene tareas en un rango de fechas"""
        with self._lock:
            tasks = []
            for task in self._tasks.values():
                try:
                    task_date = datetime.fromisoformat(task.start_datetime).date()
                    if start_date <= task_date <= end_date:
                        tasks.append(task)
                except:
                    continue
            return tasks
    
    def get_day_view(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        """Vista del calendario para un día"""
        if target_date is None:
            target_date = date.today()
        
        tasks = self.get_tasks_by_date(target_date)
        
        # Organizar por hora
        tasks_by_hour = {}
        for task in tasks:
            try:
                hour = datetime.fromisoformat(task.start_datetime).hour
                if hour not in tasks_by_hour:
                    tasks_by_hour[hour] = []
                tasks_by_hour[hour].append(task)
            except:
                continue
        
        return {
            "date": target_date.isoformat(),
            "total_tasks": len(tasks),
            "tasks_by_hour": tasks_by_hour,
            "tasks": [t.to_dict() for t in tasks]
        }
    
    def get_week_view(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        """Vista del calendario para una semana"""
        if target_date is None:
            target_date = date.today()
        
        # Calcular inicio y fin de semana (lunes a domingo)
        start_of_week = target_date - timedelta(days=target_date.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        
        tasks = self.get_tasks_by_date_range(start_of_week, end_of_week)
        
        # Organizar por día
        tasks_by_day = {}
        for i in range(7):
            day = start_of_week + timedelta(days=i)
            tasks_by_day[day.isoformat()] = []
        
        for task in tasks:
            try:
                task_date = datetime.fromisoformat(task.start_datetime).date()
                day_key = task_date.isoformat()
                if day_key in tasks_by_day:
                    tasks_by_day[day_key].append(task)
            except:
                continue
        
        return {
            "start_date": start_of_week.isoformat(),
            "end_date": end_of_week.isoformat(),
            "total_tasks": len(tasks),
            "tasks_by_day": {k: [t.to_dict() for t in v] for k, v in tasks_by_day.items()},
            "tasks": [t.to_dict() for t in tasks]
        }
    
    def get_month_view(self, year: int, month: int) -> Dict[str, Any]:
        """Vista del calendario para un mes"""
        # Calcular primer y último día del mes
        first_day = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        
        tasks = self.get_tasks_by_date_range(first_day, last_day)
        
        # Organizar por día
        tasks_by_day = {}
        current_day = first_day
        while current_day <= last_day:
            tasks_by_day[current_day.isoformat()] = []
            current_day += timedelta(days=1)
        
        for task in tasks:
            try:
                task_date = datetime.fromisoformat(task.start_datetime).date()
                day_key = task_date.isoformat()
                if day_key in tasks_by_day:
                    tasks_by_day[day_key].append(task)
            except:
                continue
        
        return {
            "year": year,
            "month": month,
            "start_date": first_day.isoformat(),
            "end_date": last_day.isoformat(),
            "total_tasks": len(tasks),
            "tasks_by_day": {k: [t.to_dict() for t in v] for k, v in tasks_by_day.items()},
            "tasks": [t.to_dict() for t in tasks]
        }
    
    def get_upcoming_tasks(self, limit: int = 10) -> List[CalendarTask]:
        """Obtiene las próximas tareas a ejecutar"""
        with self._lock:
            now = datetime.now()
            upcoming = []
            
            for task in self._tasks.values():
                if task.state in [TaskState.PENDING.value, TaskState.SCHEDULED.value]:
                    try:
                        task_time = datetime.fromisoformat(task.start_datetime)
                        if task_time > now:
                            upcoming.append((task_time, task))
                    except:
                        continue
            
            # Ordenar por fecha
            upcoming.sort(key=lambda x: x[0])
            return [task for _, task in upcoming[:limit]]
    
    def get_tasks_by_state(self, state: TaskState) -> List[CalendarTask]:
        """Obtiene tareas por estado"""
        with self._lock:
            return [t for t in self._tasks.values() if t.state == state.value]
    
    def get_overdue_tasks(self) -> List[CalendarTask]:
        """Obtiene tareas vencidas (no ejecutadas después de su hora)"""
        with self._lock:
            now = datetime.now()
            overdue = []
            
            for task in self._tasks.values():
                if task.state in [TaskState.PENDING.value, TaskState.SCHEDULED.value]:
                    try:
                        task_time = datetime.fromisoformat(task.start_datetime)
                        if task_time < now:
                            overdue.append(task)
                    except:
                        continue
            
            return overdue
    
    # -------------------------------------------------------------------------
    # Estadísticas
    # -------------------------------------------------------------------------
    
    def get_statistics(self) -> Dict[str, Any]:
        """Obtiene estadísticas del calendario"""
        with self._lock:
            total = len(self._tasks)
            by_state = {}
            by_robot = {}
            by_priority = {}
            
            for task in self._tasks.values():
                # Por estado
                state = task.state
                by_state[state] = by_state.get(state, 0) + 1
                
                # Por robot
                robot = task.robot_id
                by_robot[robot] = by_robot.get(robot, 0) + 1
                
                # Por prioridad
                priority = task.priority
                by_priority[priority] = by_priority.get(priority, 0) + 1
            
            return {
                "total_tasks": total,
                "by_state": by_state,
                "by_robot": by_robot,
                "by_priority": by_priority,
                "upcoming_count": len(self.get_upcoming_tasks()),
                "overdue_count": len(self.get_overdue_tasks())
            }
    
    # -------------------------------------------------------------------------
    # Persistencia
    # -------------------------------------------------------------------------
    
    def _save_calendar(self):
        """Guarda el calendario en disco"""
        try:
            data = {
                "version": "1.0",
                "updated_at": datetime.now().isoformat(),
                "tasks": {task_id: task.to_dict() for task_id, task in self._tasks.items()}
            }
            
            with open(self.calendar_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger(f"[SharedCalendar] Error guardando calendario: {e}")
    
    def _load_calendar(self):
        """Carga el calendario desde disco"""
        try:
            if not self.calendar_file.exists():
                self.logger("[SharedCalendar] No hay calendario previo, iniciando nuevo")
                return
            
            with open(self.calendar_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            tasks_data = data.get("tasks", {})
            for task_id, task_dict in tasks_data.items():
                try:
                    self._tasks[task_id] = CalendarTask.from_dict(task_dict)
                except Exception as e:
                    self.logger(f"[SharedCalendar] Error cargando tarea {task_id}: {e}")
            
            self.logger(f"[SharedCalendar] Cargadas {len(self._tasks)} tareas")
        except Exception as e:
            self.logger(f"[SharedCalendar] Error cargando calendario: {e}")
    
    # -------------------------------------------------------------------------
    # Callbacks y Notificaciones
    # -------------------------------------------------------------------------
    
    def register_callback(self, callback: Callable):
        """Registra un callback para cambios en el calendario"""
        with self._lock:
            if callback not in self._change_callbacks:
                self._change_callbacks.append(callback)
    
    def unregister_callback(self, callback: Callable):
        """Elimina un callback"""
        with self._lock:
            if callback in self._change_callbacks:
                self._change_callbacks.remove(callback)
    
    def _notify_change(self, event_type: str, task: CalendarTask):
        """Notifica cambios a los callbacks registrados"""
        for callback in self._change_callbacks:
            try:
                callback(event_type, task)
            except Exception as e:
                self.logger(f"[SharedCalendar] Error en callback: {e}")
    
    # -------------------------------------------------------------------------
    # Limpieza automática
    # -------------------------------------------------------------------------
    
    def _cleanup_loop(self):
        """Loop de limpieza automática de tareas antiguas"""
        while True:
            try:
                time.sleep(3600)  # Cada hora
                self._cleanup_old_tasks()
            except Exception as e:
                self.logger(f"[SharedCalendar] Error en limpieza: {e}")
    
    def _cleanup_old_tasks(self, days: int = 30):
        """Elimina tareas completadas más antiguas que X días"""
        with self._lock:
            cutoff_date = datetime.now() - timedelta(days=days)
            to_delete = []
            
            for task_id, task in self._tasks.items():
                if task.state in [TaskState.COMPLETED.value, TaskState.FAILED.value, TaskState.CANCELLED.value]:
                    try:
                        task_date = datetime.fromisoformat(task.updated_at)
                        if task_date < cutoff_date:
                            to_delete.append(task_id)
                    except:
                        continue
            
            for task_id in to_delete:
                del self._tasks[task_id]
            
            if to_delete:
                self._save_calendar()
                self.logger(f"[SharedCalendar] Limpiadas {len(to_delete)} tareas antiguas")


# =============================================================================
# INSTANCIA GLOBAL
# =============================================================================

_global_calendar: Optional[SharedCalendar] = None


def get_shared_calendar(data_dir: Optional[Path] = None, logger: Optional[Callable] = None) -> SharedCalendar:
    """Obtiene o crea la instancia global del calendario compartido"""
    global _global_calendar
    
    if _global_calendar is None:
        if data_dir is None:
            # Usar directorio por defecto
            data_dir = Path(__file__).parent / "data"
        _global_calendar = SharedCalendar(data_dir, logger)
    
    return _global_calendar
