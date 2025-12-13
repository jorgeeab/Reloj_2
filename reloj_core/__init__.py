"""
Reloj Core - Módulos compartidos para todos los robots
======================================================

Este paquete contiene la lógica común de protocolos, ejecución de tareas
y programación de tareas que comparten todos los robots del sistema Reloj.

Módulos:
- protocolos: Sistema de ejecución de protocolos personalizables
- task_executor: Ejecución de tareas con modos síncronos/asíncronos
- task_scheduler: Programación de tareas con cron-like scheduling
- shared_calendar: Calendario compartido para gestión unificada de tareas
"""

__version__ = "1.0.0"

# Exportar las clases principales para facilitar imports
from .protocolos import ProtocolRunner, Protocolo
from .task_executor import TaskExecutor, TaskDefinition, ExecutionMode, TaskStatus
from .task_scheduler import TaskScheduler, TaskSchedule, ScheduleType
from .shared_calendar import (
    SharedCalendar, 
    CalendarTask, 
    TaskPriority, 
    TaskState,
    get_shared_calendar
)

__all__ = [
    'ProtocolRunner',
    'Protocolo',
    'TaskExecutor',
    'TaskDefinition',
    'ExecutionMode',
    'TaskStatus',
    'TaskScheduler',
    'TaskSchedule',
    'ScheduleType',
    'SharedCalendar',
    'CalendarTask',
    'TaskPriority',
    'TaskState',
    'get_shared_calendar',
]
