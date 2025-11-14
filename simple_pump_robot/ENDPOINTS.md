# Simple Pump Robot – API

Referencia rápida de los endpoints que expone `simple_pump_robot/server_pump.py`.

## WebSockets

| Ruta | Descripción |
| --- | --- |
| `GET /ws/control` | Canal bidireccional para enviar `setpoints` y `flow` (por ahora `volumen_ml` y `caudal_bomba_mls`). Acepta `{"type":"ping"}` y devuelve `{"type":"pong"}`. Responde `control_ack` con el estado actualizado. |
| `GET /ws/telemetry` | Telemetría continua. Envía `telemetry_ready` al conectar y luego mensajes `{"type":"telemetry","status":{...}}` cada ~0.5s. Incluye `progress`, `execution_id` y alias de métricas compatibles con el hub. |

## HTTP

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/` | Redirige a la UI (`/ui/`) si existe, o responde JSON básico. |
| GET | `/api` | Resumen de rutas disponibles (UI opcional). |
| GET | `/api/status` | Estado instantáneo (usado por SSE y monitoreo). |
| GET | `/api/status/stream` | SSE con estado + progreso de la tarea en curso. |
| POST | `/api/control` | Control unificado (equivalente a `ws/control`). |
| GET | `/api/ui/registry` | JSON de widgets para construir la UI de este robot. |
| GET | `/api/protocols` | Describe los protocolos disponibles (`riego_basico`). |
| POST | `/api/tasks/execute` | Ejecuta una tarea/protocolo en modo async o sync. |
| GET | `/api/execution/{exec_id}` | Estado puntual de una ejecución. |
| GET | `/api/executions` | Lista todas las ejecuciones conocidas por el runner. |
| POST | `/api/execution/{exec_id}/stop` | Solicita detener la ejecución indicada. |
| GET | `/api/config` | Configuración básica (ml/s, estado del serial). |
| GET | `/api/serial/ports` | Puertos serial detectados (cuando pyserial está disponible). |
| POST | `/api/serial/open` | Abre el puerto solicitado y guarda en `config.json`. |
| POST | `/api/serial/close` | Cierra el puerto serial. |
| GET | `/api/calibration` | Obtiene el valor actual de `ml_per_sec`. |
| POST | `/api/calibration/apply` | Establece un nuevo `ml_per_sec`. |
| POST | `/api/calibration/run` | Ejecuta una corrida de calibración por duración. |
| GET | `/api/visual/status` | Indica si el visualizador PyBullet está disponible. |
| GET | `/api/visual/frame` | Imagen JPEG renderizada del nivel de agua simulado. |
| POST | `/api/visual/reset` | Reinicia el visualizador. |
