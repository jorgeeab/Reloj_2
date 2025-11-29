## Robot Base — Plantilla de UI

Este directorio contiene una copia “estándar” de la UI (templates + JS + widgets) que usan los robots `reloj` y `opuno`.  
Se actualiza cada vez que agregamos funcionalidades nuevas para que sirva como referencia al momento de crear un robot nuevo.

### Qué incluye

- `templates/reloj.html` y `templates/widgets/*` con la misma estructura modular.
- `static/js/reloj.js`, `static/js/widgets/*` y `static/js/widgets_bootstrap.js`.
- `static/styles.css` y el registro `static/components/registry/reloj.json`.

### Endpoints requeridos

Para que la UI funcione correctamente, el servidor del robot debe exponer al menos:

- `/api/status` y `/api/status/stream`
- `/api/control`
- `/api/settings` (GET/POST)
- `/api/robots`, `/api/robots/select`
- `/ws/control` y `/ws/telemetry`
- `/debug/serial`, `/debug/serial_tx`
- `/api/debug/logs` (GET/DELETE)
- `/api/serial/*` y `/api/pybullet/*` (opcionales, pero soportados por la UI)

Así garantizamos que todos los robots compartan el mismo panel de depuración (RX/TX + logs circulares) y las mejoras que vayamos agregando.

> **Tip:** cuando necesites crear un nuevo robot, copia este directorio como base o impórtalo en tu proyecto y adapta únicamente la lógica del servidor y del `robot_env`.
