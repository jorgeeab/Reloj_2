Simple Pump Robot
=================

Robot HTTP muy simple que solo controla una bomba de agua (sin ejes). Expone una API mínima compatible con el Hub:

- GET `/api/status`
- POST `/api/tasks/execute` (protocolo `riego_basico` con `params.volume_ml` o `duration_seconds`)
- GET `/api/execution/{id}`
- POST `/api/execution/{id}/stop`

Arranque
--------

1) Instalar dependencias:

   pip install -r simple_pump_robot/requirements.txt

2) (Opcional) Conectar Arduino y fijar el puerto serie en la variable `PUMP_SERIAL` (por ejemplo `COM4` en Windows o `/dev/ttyUSB0` en Linux). Si no se define, el servidor funciona en modo simulación.

3) Ejecutar el servidor en el puerto 5010:

   PUMP_SERIAL=COM4 PUMP_ML_PER_SEC=12 python simple_pump_robot/server_pump.py

   Nota: `PUMP_ML_PER_SEC` es la calibración (mililitros por segundo) para transformar volumen en tiempo de bombeo.

Arduino
-------

Sube el sketch de `arduino/pump_robot/pump_robot.ino`. Protocolo serie muy simple:

- `RUN <ms>` enciende la bomba por `<ms>` milisegundos
- `STOP` apaga la bomba

Catálogo del Hub
----------------

Para que aparezca en el Hub, agrega (o verifica) esta entrada en `hub_service/data/robots_catalog.json`:

```
{
  "id": "pump-local",
  "name": "Bomba Local",
  "base_url": "http://localhost:5010",
  "kind": "pump"
}
```

Luego abre el Hub en `http://localhost:8080/` y pulsa “Recargar” en la UI simple para sincronizar robots desde el JSON.

