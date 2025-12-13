#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ejemplo de Uso del Calendario Compartido
========================================

Este script demuestra cómo usar el sistema de calendario compartido
para crear, consultar y gestionar tareas entre robots.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Agregar path del proyecto
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reloj_core import (
    get_shared_calendar,
    CalendarTask,
    TaskPriority,
    TaskState
)


def ejemplo_basico():
    """Ejemplo básico de uso del calendario"""
    print("\n" + "="*60)
    print("EJEMPLO 1: Uso Básico del Calendario")
    print("="*60)
    
    # Obtener instancia del calendario
    data_dir = PROJECT_ROOT / "data"
    calendar = get_shared_calendar(data_dir=data_dir)
    
    print(f"\n📅 Calendario inicializado")
    print(f"   Tareas actuales: {len(calendar.get_all_tasks())}")
    
    # Crear una tarea simple
    task = CalendarTask(
        id="",  # Se generará automáticamente
        title="Riego Matutino",
        description="Riego automático del jardín cada mañana",
        start_datetime=(datetime.now() + timedelta(hours=1)).isoformat(),
        duration_seconds=600,  # 10 minutos
        robot_id="reloj",
        protocol_name="riego_basico",
        action_type="irrigation",
        params={
            "volume_ml": 500,
            "flow_rate_mls": 10
        },
        priority=TaskPriority.MEDIUM.value,
        tags=["jardin", "automatico"]
    )
    
    task_id = calendar.add_task(task)
    print(f"\n✅ Tarea creada: {task_id}")
    print(f"   Título: {task.title}")
    print(f"   Robot: {task.robot_id}")
    print(f"   Inicio: {task.start_datetime}")


def ejemplo_tareas_recurrentes():
    """Ejemplo de tareas recurrentes"""
    print("\n" + "="*60)
    print("EJEMPLO 2: Tareas Recurrentes")
    print("="*60)
    
    calendar = get_shared_calendar()
    
    # Tarea diaria
    task_diaria = CalendarTask(
        id="",
        title="Riego Diario",
        description="Riego automático todos los días a las 8:00",
        start_datetime=datetime.now().replace(hour=8, minute=0, second=0).isoformat(),
        duration_seconds=600,
        robot_id="reloj",
        protocol_name="riego_basico",
        priority=TaskPriority.HIGH.value,
        recurring=True,
        recurrence_rule={
            "type": "daily",
            "interval": 1,
            "hour": 8,
            "minute": 0
        }
    )
    
    task_id = calendar.add_task(task_diaria)
    print(f"\n✅ Tarea recurrente creada: {task_id}")
    print(f"   Recurrencia: Diaria a las 8:00")


def ejemplo_multiples_robots():
    """Ejemplo con múltiples robots"""
    print("\n" + "="*60)
    print("EJEMPLO 3: Coordinación entre Robots")
    print("="*60)
    
    calendar = get_shared_calendar()
    
    # Secuencia de tareas coordinadas
    tareas = [
        {
            "title": "Preparación - Reloj",
            "robot_id": "reloj",
            "protocol_name": "preparacion",
            "start_time": datetime.now() + timedelta(minutes=5),
            "duration": 300,
            "priority": TaskPriority.HIGH.value
        },
        {
            "title": "Bombeo - Pump",
            "robot_id": "pump",
            "protocol_name": "bombeo_agua",
            "start_time": datetime.now() + timedelta(minutes=10),
            "duration": 600,
            "priority": TaskPriority.HIGH.value
        },
        {
            "title": "Operación - OpUno",
            "robot_id": "opuno",
            "protocol_name": "operacion_final",
            "start_time": datetime.now() + timedelta(minutes=20),
            "duration": 400,
            "priority": TaskPriority.MEDIUM.value
        }
    ]
    
    print("\n🤖 Creando secuencia coordinada de tareas:")
    for i, tarea_info in enumerate(tareas, 1):
        task = CalendarTask(
            id="",
            title=tarea_info["title"],
            description=f"Paso {i} de la secuencia coordinada",
            start_datetime=tarea_info["start_time"].isoformat(),
            duration_seconds=tarea_info["duration"],
            robot_id=tarea_info["robot_id"],
            protocol_name=tarea_info["protocol_name"],
            priority=tarea_info["priority"],
            tags=["secuencia", "coordinada"]
        )
        
        task_id = calendar.add_task(task)
        print(f"   {i}. {task.title} ({task.robot_id}) - {task_id}")


def ejemplo_consultas():
    """Ejemplo de consultas al calendario"""
    print("\n" + "="*60)
    print("EJEMPLO 4: Consultas y Filtros")
    print("="*60)
    
    calendar = get_shared_calendar()
    
    # Próximas tareas
    print("\n📋 Próximas 5 tareas:")
    upcoming = calendar.get_upcoming_tasks(limit=5)
    for i, task in enumerate(upcoming, 1):
        print(f"   {i}. {task.title} - {task.start_datetime}")
    
    # Tareas por robot
    print("\n🤖 Tareas del Robot Reloj:")
    reloj_tasks = calendar.get_tasks_by_robot("reloj")
    print(f"   Total: {len(reloj_tasks)} tareas")
    
    # Estadísticas
    print("\n📊 Estadísticas:")
    stats = calendar.get_statistics()
    print(f"   Total de tareas: {stats['total_tasks']}")
    print(f"   Por robot: {stats['by_robot']}")
    print(f"   Por estado: {stats['by_state']}")
    print(f"   Por prioridad: {stats['by_priority']}")
    print(f"   Próximas: {stats['upcoming_count']}")
    print(f"   Vencidas: {stats['overdue_count']}")


def ejemplo_vistas_calendario():
    """Ejemplo de vistas de calendario"""
    print("\n" + "="*60)
    print("EJEMPLO 5: Vistas de Calendario")
    print("="*60)
    
    calendar = get_shared_calendar()
    
    # Vista del día de hoy
    print("\n📅 Vista del día de hoy:")
    today_view = calendar.get_day_view()
    print(f"   Fecha: {today_view['date']}")
    print(f"   Tareas: {today_view['total_tasks']}")
    
    # Vista de la semana
    print("\n📅 Vista de la semana:")
    week_view = calendar.get_week_view()
    print(f"   Desde: {week_view['start_date']}")
    print(f"   Hasta: {week_view['end_date']}")
    print(f"   Tareas: {week_view['total_tasks']}")
    
    # Vista del mes
    print("\n📅 Vista del mes actual:")
    now = datetime.now()
    month_view = calendar.get_month_view(now.year, now.month)
    print(f"   Mes: {now.month}/{now.year}")
    print(f"   Tareas: {month_view['total_tasks']}")
    
    # Días con tareas
    days_with_tasks = sum(1 for tasks in month_view['tasks_by_day'].values() if len(tasks) > 0)
    print(f"   Días con tareas: {days_with_tasks}")


def ejemplo_actualizacion_eliminacion():
    """Ejemplo de actualización y eliminación de tareas"""
    print("\n" + "="*60)
    print("EJEMPLO 6: Actualización y Eliminación")
    print("="*60)
    
    calendar = get_shared_calendar()
    
    # Crear una tarea temporal
    task = CalendarTask(
        id="",
        title="Tarea Temporal de Prueba",
        description="Esta tarea será modificada y luego eliminada",
        start_datetime=(datetime.now() + timedelta(days=1)).isoformat(),
        duration_seconds=300,
        robot_id="reloj",
        protocol_name="test"
    )
    
    task_id = calendar.add_task(task)
    print(f"\n✅ Tarea creada: {task_id}")
    
    # Actualizar la tarea
    calendar.update_task(task_id, {
        "title": "Tarea Modificada",
        "description": "Descripción actualizada",
        "priority": TaskPriority.URGENT.value
    })
    print(f"📝 Tarea actualizada")
    
    # Consultar la tarea actualizada
    updated_task = calendar.get_task(task_id)
    if updated_task:
        print(f"   Nuevo título: {updated_task.title}")
        print(f"   Nueva prioridad: {updated_task.priority}")
    
    # Eliminar la tarea
    calendar.delete_task(task_id)
    print(f"🗑️  Tarea eliminada: {task_id}")


def ejemplo_callbacks():
    """Ejemplo de callbacks para eventos del calendario"""
    print("\n" + "="*60)
    print("EJEMPLO 7: Callbacks y Notificaciones")
    print("="*60)
    
    calendar = get_shared_calendar()
    
    # Definir callback
    def on_calendar_change(event_type, task):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"   [{timestamp}] Evento: {event_type} - Tarea: {task.title}")
    
    # Registrar callback
    calendar.register_callback(on_calendar_change)
    print("\n🔔 Callback registrado, probando eventos...")
    
    # Crear una tarea (debería disparar el callback)
    test_task = CalendarTask(
        id="",
        title="Tarea de Prueba para Callbacks",
        start_datetime=datetime.now().isoformat(),
        robot_id="reloj",
        protocol_name="test"
    )
    
    task_id = calendar.add_task(test_task)
    
    # Actualizar la tarea
    calendar.update_task(task_id, {"title": "Tarea Actualizada"})
    
    # Eliminar la tarea
    calendar.delete_task(task_id)
    
    # Desregistrar callback
    calendar.unregister_callback(on_calendar_change)
    print("\n✅ Callback desregistrado")


def main():
    """Ejecuta todos los ejemplos"""
    print("\n" + "="*60)
    print("EJEMPLOS DE USO DEL CALENDARIO COMPARTIDO")
    print("Sistema de Gestión de Tareas para Robots")
    print("="*60)
    
    try:
        # Ejecutar ejemplos
        ejemplo_basico()
        ejemplo_tareas_recurrentes()
        ejemplo_multiples_robots()
        ejemplo_consultas()
        ejemplo_vistas_calendario()
        ejemplo_actualizacion_eliminacion()
        ejemplo_callbacks()
        
        print("\n" + "="*60)
        print("✅ Todos los ejemplos ejecutados correctamente")
        print("="*60)
        print("\n💡 Consejos:")
        print("   - Accede al calendario web en:")
        print("     · Robot Reloj: http://localhost:5000/calendar")
        print("     · Robot Pump:  http://localhost:5010/calendar")
        print("     · Robot OpUno: http://localhost:5020/calendar")
        print("   - Usa los endpoints API para integración programática")
        print("   - El calendario es compartido entre TODOS los robots")
        print("   - Las tareas se persisten en: data/shared_calendar.json")
        print("\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
