# Resumen de Cambios - Sistema de Calendario Compartido

## Cambios Realizados

### 1. ✅ Eliminación de Mensajes de "Render lento"

**Archivo modificado:** `pybullet_visualizer.py`

- **Línea 448-450**: Se comentaron los mensajes de "Render lento" que saturaban la consola
- Los mensajes ya no se imprimirán durante el renderizado de PyBullet

### 2. 🗓️ Sistema de Calendario Compartido

Se ha implementado un sistema completo de calendario compartido entre todos los robots del sistema.

#### Archivos Nuevos Creados:

1. **`reloj_core/shared_calendar.py`** (590 líneas)
   - Clase `SharedCalendar`: Gestor centralizado de tareas
   - Clase `CalendarTask`: Definición de tareas con metadatos completos
   - Enumeraciones: `TaskPriority`, `TaskState`
   - Funcionalidades:
     - CRUD completo de tareas
     - Vistas de calendario: día, semana, mes
     - Filtrado por robot, estado, prioridad
     - Tareas próximas y vencidas
     - Estadísticas del calendario
     - Persistencia en JSON
     - Limpieza automática de tareas antiguas
     - Sistema de callbacks para notificaciones

2. **`reloj_core/calendar_api.py`** (307 líneas)
   - Endpoints REST completos para el calendario
   - CRUD de tareas: GET, POST, PUT, DELETE
   - Vistas de calendario: día/semana/mes
   - Búsqueda y filtrado avanzado
   - Estadísticas
   - Página web del calendario

3. **`shared_templates/calendar.html`**
   - Interfaz web moderna y responsive
   - Dashboard con estadísticas
   - Vista de tareas próximas
   - Calendario mensual interactivo
   - Lista completa de tareas con filtros
   - Auto-actualización cada 30 segundos
   - Diseño glassmorphism moderno

#### Archivos Modificados:

1. **`reloj_core/__init__.py`**
   - Agregados exports para: `SharedCalendar`, `CalendarTask`, `TaskPriority`, `TaskState`, `get_shared_calendar`

2. **`robot_reloj/server_reloj.py`**
   - Linea 64: Import del calendario compartido
   - Línea 342-343: Variable global `shared_calendar`
   - Línea 544-550: Inicialización del calendario compartido
   - Utiliza directorio `data/` compartido en raíz del proyecto

3. **`simple_pump_robot/server_pump.py`**
   - Línea 34: Import del calendario compartido
   - Línea 164-165: Variable global `shared_calendar`
   - Línea 321-335: Inicialización y registro de endpoints

4. **`robot_opuno/server_opuno.py`**
   - Línea 67: Import del calendario compartido
   - Línea 338-340: Variable global `shared_calendar`
   - Línea 535-547: Inicialización y registro de endpoints

## Características del Sistema de Calendario

### Funcionalidades Principales:

1. **Gestión de Tareas**
   - Crear, editar, eliminar tareas
   - Asignar tareas a robots específicos (reloj, pump, opuno, etc.)
   - Programar fecha y hora de ejecución
   - Definir protocolo/acción a ejecutar
   - Establecer prioridades (baja, media, alta, urgente)
   - Marcar estados (pendiente, programada, ejecutando, completada, fallida)

2. **Vistas de Calendario**
   - Vista de día: Tareas organizadas por hora
   - Vista de semana: 7 días con tareas
   - Vista de mes: Calendario mensual completo
   - Próximas tareas: Lista de tareas futuras
   - Tareas vencidas: Tareas no ejecutadas

3. **Filtrado y Búsqueda**
   - Filtrar por robot
   - Filtrar por estado
   - Filtrar por prioridad
   - Búsqueda por texto
   - Rango de fechas

4. **Estadísticas**
   - Total de tareas
   - Tareas por estado
   - Tareas por robot
   - Tareas por prioridad
   - Próximas y vencidas

5. **Integración con Robots**
   - Cada robot accede al mismo calendario
   - Tareas compartidas entre todos
   - Sincronización automática
   - Persistencia en archivo JSON compartido

## Endpoints API Disponibles

### CRUD de Tareas
- `GET /api/calendar/tasks` - Obtener todas las tareas (con filtros opcionales)
- `POST /api/calendar/tasks` - Crear nueva tarea
- `GET /api/calendar/tasks/<task_id>` - Obtener tarea específica
- `PUT /api/calendar/tasks/<task_id>` - Actualizar tarea
- `DELETE /api/calendar/tasks/<task_id>` - Eliminar tarea

### Vistas de Calendario
- `GET /api/calendar/view/day?date=YYYY-MM-DD` - Vista del día
- `GET /api/calendar/view/week?date=YYYY-MM-DD` - Vista de la semana
- `GET /api/calendar/view/month?year=YYYY&month=MM` - Vista del mes

### Consultas
- `GET /api/calendar/upcoming?limit=N` - Próximas N tareas
- `GET /api/calendar/overdue` - Tareas vencidas
- `GET /api/calendar/statistics` - Estadísticas del calendario
- `GET /api/calendar/search?q=texto&robot_id=X&state=Y` - Búsqueda avanzada

### Página Web
- `GET /calendar` - Interfaz web del calendario

## Ejemplo de Uso

### Crear una Tarea desde la API

```bash
POST /api/calendar/tasks
Content-Type: application/json

{
  "title": "Riego de Plantas",
  "description": "Riego automático del jardín zona A",
  "start_datetime": "2025-12-08T16:00:00",
  "duration_seconds": 600,
  "robot_id": "reloj",
  "protocol_name": "riego_basico",
  "action_type": "irrigation",
  "params": {
    "volume_ml": 500,
    "flow_rate_mls": 10
  },
  "priority": "alta",
  "recurring": true,
  "recurrence_rule": {
    "type": "daily",
    "interval": 1,
    "hour": 16,
    "minute": 0
  },
  "tags": ["jardin", "automatico"]
}
```

### Acceder al Calendario desde el Navegador

1. **Robot Reloj**: `http://localhost:5000/calendar`
2. **Robot Pump**: `http://localhost:5010/calendar`
3. **Robot OpUno**: `http://localhost:5020/calendar`

Todos muestran el mismo calendario compartido.

## Estructura de Datos

### CalendarTask

```python
{
  "id": "task_1733689123_0001",
  "title": "Riego matutino",
  "description": "Riego automático de la mañana",
  "start_datetime": "2025-12-08T08:00:00",
  "end_datetime": null,
  "duration_seconds": 600.0,
  "robot_id": "reloj",
  "protocol_name": "riego_basico",
  "action_type": "irrigation",
  "params": {"volume_ml": 500},
  "state": "pendiente",
  "priority": "media",
  "recurring": false,
  "recurrence_rule": {},
  "created_at": "2025-12-08T11:52:03",
  "updated_at": "2025-12-08T11:52:03",
  "created_by": "user",
  "tags": ["jardin"],
  "notes": "",
  "execution_count": 0,
  "last_execution": null,
  "next_execution": "2025-12-08T08:00:00",
  "max_executions": null,
  "result": null,
  "error_message": null
}
```

## Persistencia

- **Archivo**: `<proyecto_raiz>/data/shared_calendar.json`
- **Formato**: JSON con versión y timestamp
- **Limpieza**: Tareas completadas >30 días se eliminan automáticamente
- **Sincronización**: Todos los robots leen/escriben el mismo archivo

## Próximos Pasos Sugeridos

1. **Integración con TaskScheduler**: Conectar el calendario con el sistema de ejecución de tareas actual
2. **Notificaciones**: Sistema de alertas para tareas próximas o vencidas
3. **Webhooks**: Notificar eventos del calendario a sistemas externos
4. **Importar/Exportar**: Funcionalidad para importar/exportar tareas en formato iCal
5. **UI Mejorada**: Drag & drop para reprogramar tareas, edición inline, etc.
6. **Integración con Protocolos**: Ejecutar protocolos directamente desde el calendario

## Notas Técnicas

- **Thread-safe**: Uso de `threading.RLock()` para operaciones concurrentes
- **Auto-limpieza**: Thread daemon que limpia tareas antiguas cada hora
- **Callbacks**: Sistema extensible de notificaciones para eventos del calendario
- **Singleton**: `get_shared_calendar()` retorna la misma instancia global
- **Validación**: Validación de formatos de fecha/hora ISO 8601

---

**Fecha de implementación**: 2025-12-08

**Robots soportados**: 
- ✅ Robot Reloj
- ✅ Robot Pump
- ✅ Robot OpUno

**Estado**: ✅ Totalmente funcional en TODOS los robots del sistema
