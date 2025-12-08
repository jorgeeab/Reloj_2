# Sistema Unificado Reloj 2.0

Este proyecto utiliza una arquitectura modular compartida para garantizar consistencia y facilitar el mantenimiento entre múltiples robots (Reloj, OpUno, Simple Pump).

## Componentes Compartidos

### 1. `shared_templates/` (Interfaz UI)
Contiene los templates HTML base y widgets.
- `base.html`: Estructura común con navegación y estilos.
- `widgets/`: Componentes UI reutilizables (bomba, corredera, etc.).
- `manage.html`: Interfaz de gestión de tareas.

### 2. `shared_static/` (Assets Frontend)
Contiene archivos CSS y JS servidos automáticamente a todos los robots.
- `styles.css`: Estilos globales.
- `js/reloj.js`: Lógica principal del frontend.
- `js/widgets/`: Lógica de los widgets.

### 3. `reloj_core/` (Lógica Backend)
Paquete Python con la lógica de negocio común.
- `protocolos.py`: Sistema de protocolos.
- `task_executor.py`: Ejecución de tareas.
- `task_scheduler.py`: Programación de tareas.

## Configuración de un Nuevo Robot

Para crear un nuevo robot que se integre en este sistema:

### 1. Estructura de Directorios
```
nuevo_robot/
├── server_nuevo.py
├── templates/
│   └── nuevo.html  (extiende base.html)
└── static/         (opcional, solo para overrides)
```

### 2. Configuración del Servidor (Flask)

En `server_nuevo.py`:

```python
# 1. Importar lógica compartida
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent)) # Añadir raíz del proyecto
from reloj_core import ProtocolRunner, TaskExecutor

# 2. Configurar Static Files Compartidos
SHARED_STATIC_DIR = Path(__file__).parent.parent / "shared_static"
app = Flask(__name__, static_folder=None) # Desactivar default

@app.route('/static/<path:filename>')
def custom_static(filename):
    try:
        return send_from_directory(STATIC_DIR, filename) # Local primero
    except NotFound:
        return send_from_directory(SHARED_STATIC_DIR, filename) # Shared fallback

# 3. Configurar Templates Compartidos
from jinja2 import ChoiceLoader, FileSystemLoader
SHARED_TEMPLATES = Path(__file__).parent.parent / "shared_templates"
app.jinja_loader = ChoiceLoader([
    FileSystemLoader(str(TEMPLATES_DIR)),
    FileSystemLoader(str(SHARED_TEMPLATES))
])
```

### 3. Frontend

En `templates/nuevo.html`:

```html
{% extends "base.html" %}

{% block main_content %}
    <!-- Tu contenido específico -->
    {% include 'widgets/bomba_operacion.html' %}
{% endblock %}
```

## Mantenimiento

- **Cambios Visuales:** Modificar `shared_static/styles.css` afecta a todos los robots.
- **Cambios Lógicos:** Modificar `reloj_core/` afecta el comportamiento de todos.
- **Widgets:** Modificar `shared_templates/widgets/` actualiza la UI en todos lados.
