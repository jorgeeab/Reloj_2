# Robot Reloj — Guía rápida (Servidor + UI)

## Arranque

- Servidor del robot (UI en http://localhost:5001):
  - `python robots/robot_reloj/server_reloj.py`
- Hub (lista de robots, http://localhost:5002):
  - `python hub/hub_server.py`

## Pestañas de la UI

- Operación:
  - Setpoints X(mm)/A(°)/Volumen(ml) (al aplicar, fuerza modo automático).
  - Quick actions: Agua, Home, Paro.
  - Reproductor de Protocolo (con plantillas y stop).
  - Overlay de bloqueo: durante ejecución o si el serial está desconectado (incluye Reconectar).
- Telemetría:
  - Gauges SVG de X/A/Vol/Flow; barras de energía; progreso a objetivo con ETA.
  - Chips KPI: pasos/mm, pasos/°, usar sensor de flujo, caudal bomba, kp/ki/kd (X y A).
  - Gráfico en tiempo real con autoescala por serie y puntos para Flow.
- Settings:
  - Serial (puerto/baudrate, Conectar/Desconectar, Depuración RX/TX con copiar/limpiar).
  - Calibración/Flujo, PID por defecto (Aplicar ahora), políticas y Scheduler.
- Protocolos:
  - Botones por protocolo; editor/carga/guardado/ejecución; jobs (listar/detener).
- Calendario:
  - Vistas Día/Semana/Mes; crear/editar/eliminar tareas; ejecutar ahora.

## Endpoints principales (REST)

- Estado
  - GET `/api/status`
    - x_mm, a_deg, volumen_ml, caudal_est_mls (o flow_est), lim_x/lim_a, homing_x/homing_a, modo, serial_open, serial_port, baudrate
    - energies.{x,a,bomba}
    - PID: kpX/kiX/kdX, kpA/kiA/kdA
    - Calibración/Flujo: pasosPorMM, pasosPorGrado, usarSensorFlujo, caudalBombaMLs
    - Objetivo: volumen_objetivo_ml; rx_age_ms
- Control (unificado)
  - POST `/api/control`
    - `{ setpoints:{x_mm,a_deg,volumen_ml}, energies:{x,a,bomba}, modo, reset_x, reset_a, reset_volumen, calibration:{steps_mm,steps_deg}, flow:{usar_sensor_flujo,caudal_bomba_mls}, pid_settings:{ pidX:{kp,ki,kd}, pidA:{kp,ki,kd} } }`
- Acciones rápidas
  - POST `/api/water`, `/api/home`, `/api/stop`
- Serial
  - GET `/api/serial/ports` → `{ports,current,open}`
  - POST `/api/serial/open` `{port, baudrate}`
  - POST `/api/serial/close`
  - POST `/api/disconnect` (fallback)
  - POST `/api/connect` `{port?, baudrate?}` (equivalente a abrir)
- Ajustes UI (persistencia)
  - GET/POST `/api/settings`
    - Guarda: baudrate, steps_mm, steps_deg, usar_sensor_flujo, caudal_bomba_mls, PID defaults (kpX/kiX/kdX, kpA/kiA/kdA), command_policy, scheduler_enabled, `player_favorites` (plantillas del reproductor)
- Políticas y Planificador
  - POST `/api/command_policy` `{policy:'all'|'stop_only'|'none'}`
  - POST `/api/scheduler` `{enabled:true|false}`
    - stop_only recomendado: bloquea todo salvo paradas mientras hay ejecución
- Tareas
  - GET `/api/tasks`
  - POST `/api/tasks` (crear/actualizar, ver payloads en `calendar.js`)
  - GET `/api/tasks/<id>`
  - PUT `/api/tasks/<id>`
  - DELETE `/api/tasks/<id>`
  - POST `/api/tasks/<id>/execute`
- Ejecuciones
  - POST `/api/execute` `{type:'task'|'protocol'|'immediate', id?, params?}`
  - GET `/api/executions`
  - GET `/api/execution/<execution_id>`
  - POST `/api/execution/<execution_id>/stop`
- Protocolos
  - GET `/api/protocols` → `{protocols:[...]}`
  - GET `/api/protocols/<name>` → `{name, code}`
  - POST `/api/protocols` `{name, code}` (guardar)
  - DELETE `/api/protocols/<name>`
  - POST `/api/protocols/<name>/execute` `{params}`
- Depuración
  - GET `/debug/serial` → `{last_rx, age_ms}`
  - GET `/debug/serial_tx` → `{last_tx, age_ms}`

## Flujo de ejecución y bloqueos

- Al iniciar/terminar una ejecución, la UI actualiza un overlay sobre Operación.
- `command_policy: stop_only` impide sobrescribir acciones durante tareas, salvo paradas.
- El servidor envía un keepalive (TX) periódico para mantener la comunicación con firmware.

## Protocolos e IA (futuro)

- Inline: `custom_action(obs)` o `custom_action(obs, ctx)` que devuelva patch/acción.
- IA externa: el protocolo puede POSTear `obs` a una API (local o Cloud) y mapear la respuesta.
- Modelo local ligero: cargar modelo (sklearn/onnx) desde protocolo o microservicio local.

## Tareas (concepto)

- Una tarea puede ser de acción directa (patch) o ejecutar un protocolo con parámetros.
- Calendario persiste tareas y muestra próximas ejecuciones; también permite “Ejecutar ahora”.

## Pruebas rápidas (smoke test)

- `python robots/robot_reloj/tests/smoke_server.py`
  - Recorre status, settings, control, serial, tasks, executions, debug.

## Notas

- Firmware (Arduino) envía 21 valores por RX; el servidor deriva `caudal_est_mls` y expone PID/calibración.
- Bomba: sólo FORWARD (sin reversa). No hay “aspirar”.
