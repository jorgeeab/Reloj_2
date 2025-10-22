Reloj Hub Service (microservicio)
=================================

Servicio central para gestionar múltiples robots (cada uno con su propio server) y asignarles tareas basadas en plantas/regímenes. Expone WebSocket para actualizaciones rápidas de estado.

Requisitos
- Python 3.10+
- `pip install -r hub_service/requirements.txt`

Ejecución
- `uvicorn hub_service.app:app --reload --port 8080`
- Abre `http://localhost:8080/hub` si sirves el `static/index.html` con un server estático (o abre el archivo en el navegador y apunta a `http://localhost:8080`).

Endpoints principales
- `GET /robots` — lista robots con estado caché
- `POST /robots` — alta `{ id, name, base_url, kind?, api_key? }`
- `DELETE /robots/{id}` — elimina robot
- `GET /plants` — lista plantas
- `POST /plants` — alta/actualización de planta
- `DELETE /plants/{era}/{plant_id}` — elimina planta
- `POST /assign` — asigna tarea a robot:
  ```json
  {
    "robot_id": "r1",
    "plant_era": "Era 1",
    "plant_id": 1,
    "action": "move" | "water",
    "params": { "volume_ml": 50, "duration_seconds": 10 }
  }
  ```
- `WS /ws` — feed de estado (`robots_status`, `snapshot`)

Notas
- El Hub consulta `base_url/api/status` de cada robot ~2 Hz (ajustable en `poll_robots_loop`).
- Para ejecución de tareas llama `POST {base_url}/api/tasks/execute` con `protocol_name` `ir_posicion` o `riego_basico`.
- Almacenamiento: `hub_service/data/hub_data.json` (robots, plantas, etc.).

Próximos pasos
- Añadir regímenes/actividades y ejecución programada.
- Opcional: añadir WebSocket/Stream en robots para push de estado (el Hub se suscribe y reemite a la UI).
