"""
Reloj Core - Módulos compartidos para todos los robots
======================================================

Este paquete contiene la lógica común de protocolos, ejecución de tareas
y programación de tareas que comparten todos los robots del sistema Reloj.

Módulos:
- protocolos: Sistema de ejecución de protocolos personalizables
- task_executor: Ejecución de tareas con modos síncronos/asíncronos
- task_scheduler: Programación de tareas con cron-like scheduling
"""

__version__ = "1.0.0"

# Exportar las clases principales para facilitar imports
from .protocolos import ProtocolRunner, Protocolo
from .task_executor import TaskExecutor, TaskDefinition, ExecutionMode, TaskStatus
from .task_scheduler import TaskScheduler, TaskSchedule, ScheduleType

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
]
