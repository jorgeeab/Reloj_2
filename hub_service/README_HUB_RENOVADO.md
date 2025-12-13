# 🎯 HUB SERVICE - RESUMEN DE MEJORAS IMPLEMENTADAS

## ✅ Cambios Completados

### 1. 🎨 **Interfaz Completamente Rediseñada**

**Archivo:** `hub_service/static/index.html`

#### **Antes:**
- 1915 líneas de HTML/JS monolítico
- Gradientes coloridos (púrpura/violeta)
- Widgets complejos
- Difícil de mantener

#### **Ahora:**
- ~500 líneas limpias
- Colores neutros y profesionales
- Interfaz simple y directa
- Fácil de entender

### 2. 🔌 **Control de Servidores Integrado**

Cada robot ahora muestra:

```
┌─────────────────────────────────────┐
│ Robot Reloj                         │
│ ✓ Conectado / ✗ Desconectado       │
├─────────────────────────────────────┤
│ [▶ Iniciar Servidor]               │
│ [⏹ Detener Servidor]               │
│ [🔗 Abrir Interfaz]                │
├─────────────────────────────────────┤
│ WIDGETS (solo si está corriendo)   │
│ X: 120mm | A: 45° | V: 150ml       │
│ [🏠 Home] [⏹ Stop]                 │
└─────────────────────────────────────┘
```

**Lógica de Widgets:**
- ✅ Solo aparecen si `runtime: true` AND `status.ok: true`
- ✅ Si el servidor está detenido: mensaje claro
- ✅ Botón "Abrir Interfaz" se deshabilita si no está corriendo

### 3. 🤖 **Endpoints para IA - Control Completo**

**Prefix:** `/ai/*`

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/ai/robots/list` | GET | Listar todos los robots |
| `/ai/plants/list` | GET | Listar todas las plantas |
| `/ai/status/{robot_id}` | GET | Estado actual del robot |
| `/ai/move` | POST | Mover robot a posición |
| `/ai/water` | POST | Regar con volumen específico |
| `/ai/home` | POST | Enviar robot a home |
| `/ai/stop` | POST | Detener robot |
| `/ai/goto_plant` | POST | Ir a posición de una planta |

#### **Ejemplos de Uso para IA:**

**1. Listar robots disponibles:**
```bash
curl http://localhost:8080/ai/robots/list
```

**Response:**
```json
{
  "robots": [
    {
      "id": "reloj",
      "name": "Robot Reloj",
      "kind": "reloj",
      "online": true,
      "runtime": true,
      "base_url": "http://localhost:5000"
    }
  ],
  "total": 1,
  "online": 1
}
```

**2. Obtener estado de un robot:**
```bash
curl http://localhost:8080/ai/status/reloj
```

**Response:**
```json
{
  "robot_id": "reloj",
  "robot_name": "Robot Reloj",
  "base_url": "http://localhost:5000",
  "online": true,
  "status": {
    "x_mm": 120.5,
    "a_deg": 45.2,
    "volumen_ml": 150
  },
  "runtime": true
}
```

**3. Mover robot:**
```bash
curl -X POST http://localhost:8080/ai/move \
  -H "Content-Type: application/json" \
  -d '{
    "robot_id": "reloj",
    "x_mm": 150.0,
    "a_deg": 60.0,
    "duration_seconds": 10.0
  }'
```

**Response:**
```json
{
  "status": "ok",
  "action": "move",
  "robot_id": "reloj",
  "target": {"x_mm": 150.0, "a_deg": 60.0},
  "execution_id": "exec_12345"
}
```

**4. Regar:**
```bash
curl -X POST http://localhost:8080/ai/water \
  -H "Content-Type: application/json" \
  -d '{
    "robot_id": "reloj",
    "volume_ml": 200.0,
    "duration_seconds": 20.0
  }'
```

**5. Ir a una planta:**
```bash
curl -X POST "http://localhost:8080/ai/goto_plant?robot_id=reloj&era=Era1&plant_id=1&duration_seconds=10"
```

**6. Enviar a home:**
```bash
curl -X POST http://localhost:8080/ai/home \
  -H "Content-Type: application/json" \
  -d '{"robot_id": "reloj"}'
```

**7. Detener robot:**
```bash
curl -X POST http://localhost:8080/ai/stop \
  -H "Content-Type: application/json" \
  -d '{"robot_id": "reloj"}'
```

**8. Listar plantas:**
```bash
curl http://localhost:8080/ai/plants/list
```

**Response:**
```json
{
  "plants": [
    {
      "id": 1,
      "era": "Era 1",
      "name": "Tomate Cherry",
      "position": {
        "x_mm": 120.0,
        "a_deg": 45.0,
        "a_y_deg": 0.0
      },
      "water_speed": 10.0,
      "planted_date": "2025-01-01"
    }
  ],
  "total": 1
}
```

### 4. 🌐 **Auto-apertura del Navegador**

Cuando inicias el hub con:
```bash
python -m hub_service.app
```

Automáticamente:
1. ✅ Inicia el servidor en puerto 8080 (configurable con `HUB_PORT`)
2. ✅ Espera 1.2 segundos
3. ✅ Abre `http://localhost:8080` en el navegador predeterminado

**Desactivar auto-apertura:**
```bash
HUB_AUTO_OPEN=0 python -m hub_service.app
```

### 5. 🎨 **Nueva Paleta de Colores**

```css
/* Colores Profesionales */
--primary:      #2563eb  /* Azul sobrio */
--success:      #10b981  /* Verde suave */
--danger:       #ef4444  /* Rojo no agresivo */
--warning:      #f59e0b  /* Amarillo cálido */
--bg:           #f8fafc  /* Gris muy claro */
--surface:      #ffffff  /* Blanco */
--border:       #e2e8f0  /* Gris claro */
--text:         #1e293b  /* Gris oscuro */
--text-muted:   #64748b  /* Gris medio */
```

### 6. 📱 **3 Tabs Principales**

1. **🤖 Robots**
   - Grid de tarjetas de robots
   - Control de inicio/detención
   - Widgets condicionales
   - Botón para abrir interfaz completa

2. **📅 Calendario**
   - Iframe con calendario compartido integrado
   - Botón para abrir en nueva ventana
   - Mismo calendario que usan todos los robots

3. **🌱 Plantas**
   - Grid de tarjetas de plantas
   - Info: era, ID, posición, ángulo
   - Click para seleccionar

### 7. 📊 **Header con Stats en Tiempo Real**

```
┌─────────────────────────────────────────────┐
│ Hub de Control                              │
│ [🤖 3 Robots] [🌱 12 Plantas] [📅 5 Tareas]│
└─────────────────────────────────────────────┘
```

- Actualización vía WebSocket
- Contadores dinámicos

---

## 🚀 **Cómo Usar el Hub**

### **Iniciar el Hub:**

```bash
# Opción 1: Desde raíz del proyecto
python -m hub_service.app

# Opción 2: Con puerto personalizado
HUB_PORT=9000 python -m hub_service.app

# Opción 3: Sin auto-abrir navegador
HUB_AUTO_OPEN=0 python -m hub_service.app
```

### **Acceder a la Interfaz:**

```
http://localhost:8080
```

### **Usar Endpoints desde otra IA:**

#### **Ejemplo en Python:**
```python
import requests

HUB_URL = "http://localhost:8080"

# Listar robots
robots = requests.get(f"{HUB_URL}/ai/robots/list").json()
print(f"Robots disponibles: {robots['total']}")

# Obtener estado
status = requests.get(f"{HUB_URL}/ai/status/reloj").json()
print(f"Robot online: {status['online']}")
print(f"Posición X: {status['status']['x_mm']}mm")

# Mover robot
response = requests.post(f"{HUB_URL}/ai/move", json={
    "robot_id": "reloj",
    "x_mm": 150.0,
    "a_deg": 45.0,
    "duration_seconds": 10.0
})
print(f"Resultado: {response.json()['status']}")

# Regar
response = requests.post(f"{HUB_URL}/ai/water", json={
    "robot_id": "reloj",
    "volume_ml": 200.0
})
print(f"Regado iniciado: {response.json()['execution_id']}")
```

#### **Ejemplo en JavaScript:**
```javascript
const HUB_URL = 'http://localhost:8080';

// Listar robots
const robots = await fetch(`${HUB_URL}/ai/robots/list`).then(r => r.json());
console.log('Robots:', robots.total);

// Mover robot
const moveResult = await fetch(`${HUB_URL}/ai/move`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    robot_id: 'reloj',
    x_mm: 150.0,
    a_deg: 45.0,
    duration_seconds: 10.0
  })
}).then(r => r.json());

console.log('Movimiento iniciado:', moveResult.execution_id);
```

---

## 📋 **Flujo de Trabajo Típico**

### **Para Usuario Humano:**

1. Abrir hub: `http://localhost:8080`
2. Ver robots disponibles
3. Iniciar servidor de un robot si está detenido
4. Esperar que aparezcan los widgets
5. Usar botones rápidos (Home, Stop) o
6. Click en "Abrir Interfaz" para control completo

### **Para IA/Script:**

1. Listar robots: `GET /ai/robots/list`
2. Verificar estado: `GET /ai/status/{robot_id}`
3. Si online, enviar comandos:
   - `POST /ai/move` - Mover
   - `POST /ai/water` - Regar
   - `POST /ai/home` - Home
   - `POST /ai/goto_plant` - Ir a planta
4. Opcional: listar plantas `GET /ai/plants/list`

---

## 🎯 **Beneficios de la Nueva Arquitectura**

### **Para Usuarios:**
- ✅ Interfaz limpia y profesional
- ✅ Control de servidores integrado
- ✅ Feedback visual claro
- ✅ Acceso directo a interfaces completas
- ✅ Calendario integrado

### **Para Desarrolladores:**
- ✅ Código simple y mantenible
- ✅ Menos de 500 líneas HTML/JS
- ✅ Colores CSS con variables
- ✅ WebSocket para tiempo real
- ✅ Responsive design

### **Para IAs/Scripts:**
- ✅ Endpoints RESTful claros
- ✅ Respuestas JSON estructuradas
- ✅ Control completo de todos los robots
- ✅ No necesita interacción con UI
- ✅ Documentación en los docstrings

---

## 📖 **Documentación de Endpoints para IA**

### **GET /ai/robots/list**
Lista todos los robots conectados al hub.

**Response:**
```json
{
  "robots": [...],
  "total": 3,
  "online": 2
}
```

### **GET /ai/status/{robot_id}**
Obtiene el estado actual de un robot específico.

**Response:**
```json
{
  "robot_id": "reloj",
  "robot_name": "Robot Reloj",
  "base_url": "http://localhost:5000",
  "online": true,
  "status": {
    "x_mm": 120.5,
    "a_deg": 45.2,
    "volumen_ml": 150,
    "serial_open": true
  },
  "runtime": true
}
```

### **POST /ai/move**
Mueve un robot a una posición específica.

**Body:**
```json
{
  "robot_id": "reloj",
  "x_mm": 150.0,
  "a_deg": 60.0,
  "duration_seconds": 10.0
}
```

### **POST /ai/water**
Riega con un volumen específico.

**Body:**
```json
{
  "robot_id": "reloj",
  "volume_ml": 200.0,
  "duration_seconds": 20.0
}
```

### **POST /ai/home**
Envía el robot a posición home.

**Body:**
```json
{
  "robot_id": "reloj"
}
```

### **POST /ai/stop**
Detiene el robot inmediatamente.

**Body:**
```json
{
  "robot_id": "reloj"
}
```

### **GET /ai/plants/list**
Lista todas las plantas registradas.

**Response:**
```json
{
  "plants": [...],
  "total": 12
}
```

### **POST /ai/goto_plant**
Mueve el robot a la posición de una planta.

**Query Params:**
- `robot_id`: ID del robot
- `era`: Era de la planta
- `plant_id`: ID de la planta
- `duration_seconds`: Duración (opcional)

---

## ✅ **Estado Final**

| Característica | Estado |
|---------------|--------|
| Interfaz rediseñada | ✅ Completado |
| Colores neutros | ✅ Completado |
| Control de servidores | ✅ Completado |
| Widgets condicionales | ✅ Completado |
| Endpoints para IA | ✅ Completado |
| Auto-apertura navegador | ✅ Completado |
| Calendario integrado | ✅ Completado |
| WebSocket tiempo real | ✅ Completado |
| Responsive design | ✅ Completado |

---

## 🎉 **¡Hub Completamente Renovado!**

El Hub Service ahora es:
- **Simple** - Interfaz clara y directa
- **Profesional** - Colores neutros y diseño limpio
- **Potente** - Endpoints completos para IA
- **Inteligente** - Widgets condicionales
- **Automático** - Abre navegador al iniciar

**Perfecto para:**
- 👨‍💻 Control manual por humanos
- 🤖 Automatización por IAs
- 📊 Monitoreo en tiempo real
- 🌱 Gestión de plantas
- 📅 Programación de tareas
