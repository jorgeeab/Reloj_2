# Reloj Core - Núcleo Compartido
==============================

Este paquete contiene la lógica de negocio compartida por todos los robots del sistema Reloj (Reloj, OpUno, Simple Pump).

## Módulos

### 1. `protocolos.py`
Sistema de definición y ejecución de protocolos.
- `Protocolo`: Clase base para definir secuencias de acciones.
- `ProtocolRunner`: Ejecutor que gestiona el ciclo de vida de un protocolo.

### 2. `task_executor.py`
Ejecutor unificado de tareas.
- Gestiona la ejecución síncrona y asíncrona de protocolos.
- Define `TaskDefinition` y `TaskResult`.
- Maneja timeouts y estados de tareas.

### 3. `task_scheduler.py`
Programador de tareas tipo cron.
- Permite programar tareas para ejecución futura (diaria, intervalos, etc.).
- Se integra con `TaskExecutor` para lanzar las tareas.

## Uso

Para usar estos módulos en un nuevo robot:

1. Asegúrate de que el directorio padre de `reloj_core` esté en el `sys.path`.
2. Importa directamente desde el paquete:

```python
from reloj_core import ProtocolRunner, Protocolo
from reloj_core import TaskExecutor, TaskDefinition
```

## Desarrollo

Cualquier cambio en estos archivos afectará a **todos** los robots.
- Si modificas `protocolos.py`, verifica que no rompa la compatibilidad con protocolos existentes.
- Si modificas `task_executor.py`, verifica que la API REST de los robots siga funcionando correctamente.
