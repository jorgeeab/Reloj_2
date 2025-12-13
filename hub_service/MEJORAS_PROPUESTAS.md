# 📊 ANÁLISIS Y MEJORAS DEL HUB SERVICE

## 🎯 Propósito Actual del Hub Service

El `hub_service` es el **centro de control unificado** del sistema que:

1. **Gestiona múltiples robots** conectados (Reloj, Pump, OpUno, etc.)
2. **Control de plantas** con régimenes de riego y actividades programadas
3. **Calendario de actividades** generado automáticamente
4. **Ejecución coordinada de tareas** entre robots
5. **Vista en tiempo real** vía WebSocket de todos los robots

---

## 🏗️ Arquitectura Actual

### **Backend (FastAPI)**
```
hub_service/
├── app.py              # API principal (997 líneas)
├── models.py           # Modelos de datos
├── connections.py      # Gestión de conexiones
├── Gestor_plantas.py   # Gestión de plantas
└── data/              # Almacenamiento
    ├── hub_data.json   # Robots, plantas, tareas
    └── robots_catalog.json
```

###**Frontend**
```
hub_service/static/
├── hub_multi.html      # Interfaz principal (1915 líneas)
└── components/         # Widgets modulares
    ├── widgets.js
    ├── widgets.css
    └── registry/       # Configuraciones por tipo de robot
```

---

## ✅ Puntos Fuertes Actuales

1. ✅ **WebSocket en tiempo real** - Actualización instantánea de estados
2. ✅ **Arquitectura modular** - Widgets componibles por tipo de robot
3. ✅ **Polling inteligente** - 2Hz para estados de robots
4. ✅ **Gestión de plantas** - Sistema completo de eras y régimenes
5. ✅ **Calendario de actividades** - Generación automática basada en régimenes
6. ✅ **Proxy de control** - Envía comandos a robots remotos
7. ✅ **SSE/Stream** - Soporte para Server-Sent Events

---

## 🚀 Mejoras Propuestas

### **1. Integración con el Calendario Compartido** ⭐⭐⭐

**Problema:** El hub tiene su propio sistema de "actividades" separado del nuevo calendario compartido

**Solución:**
```python
# Agregar endpoints en app.py
@app.get("/calendar/tasks")
async def get_calendar_tasks():
    """Integra con el calendario compartido de reloj_core"""
    from reloj_core import get_shared_calendar
    calendar = get_shared_calendar(data_dir=DATA_DIR / "shared")
    return {"tasks": [t.to_dict() for t in calendar.get_all_tasks()]}

@app.post("/calendar/tasks/sync")
async def sync_activities_to_calendar():
    """Sincroniza actividades del hub al calendario compartido"""
    from reloj_core import get_shared_calendar, CalendarTask
    calendar = get_shared_calendar(data_dir=DATA_DIR / "shared")
    
    # Convertir actividades a tareas del calendario
    for activity in store.activities:
        if not activity.completada:
            plant = store.get_plant(activity.era, activity.planta_id)
            if plant:
                task = CalendarTask(
                    id="",
                    title=f"{activity.tipo_actividad} - {plant.nombre}",
                    start_datetime=activity.fecha,
                    robot_id="reloj",  # o determinar dinámicamente
                    description=activity.detalles,
                    params={"plant_id": plant.id_planta, "era": plant.era}
                )
                calendar.add_task(task)
    
    return {"status": "synced"}
```

**Beneficios:**
- Un solo calendario para todo el sistema
- Las plantas se pueden programar desde cualquier interfaz
- Mejor coordinación entre robots

---

### **2. Dashboard Mejorado** ⭐⭐⭐

**Agregar al hub_multi.html:**

```html
<!-- Nueva sección de Dashboard -->
<div class="row g-3 mb-4">
    <div class="col-12">
        <div class="card">
            <div class="card-header">
                <h5><i class="bi bi-speedometer2"></i> Dashboard Global</h5>
            </div>
            <div class="card-body">
                <!-- Stats Cards -->
                <div class="row g-3 mb-3">
                    <div class="col-md-3">
                        <div class="stat-card">
                            <div class="stat-icon"><i class="bi bi-robot"></i></div>
                            <div class="stat-value" id="stat-robots">0</div>
                            <div class="stat-label">Robots Activos</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="stat-card">
                            <div class="stat-icon"><i class="bi bi-flower1"></i></div>
                            <div class= "stat-value" id="stat-plants">0</div>
                            <div class="stat-label">Plantas</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="stat-card">
                            <div class="stat-icon"><i class="bi bi-calendar-check"></i></div>
                            <div class="stat-value" id="stat-tasks">0</div>
                            <div class="stat-label">Tareas Hoy</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="stat-card">
                            <div class="stat-icon"><i class="bi bi-clock-history"></i></div>
                            <div class="stat-value" id="stat-pending">0</div>
                            <div class="stat-label">Pendientes</div>
                        </div>
                    </div>
                </div>
                
                <!-- Calendario Integrado -->
                <div class="calendar-mini" id="hub-calendar"></div>
            </div>
        </div>
    </div>
</div>
```

---

### **3. Visualización de Plantas Mejorada** ⭐⭐

**Problema:** Tabla simple de plantas, sin contexto visual

**Solución:** Mapa 2D de plantas
```javascript
// Agregar al hub_multi.html
async function renderPlantsMap() {
    const res = await fetch(`${api}/map/plants`);
    const data = await res.json();
    const plants = data.plants || [];
    
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "-150 -150 300 300");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "400");
    
    // Dibujar plantas
    plants.forEach(p => {
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", p.x);
        circle.setAttribute("cy", p.y);
        circle.setAttribute("r", "8");
        circle.setAttribute("fill", "#4caf50");
        circle.setAttribute("stroke", "#2e7d32");
        circle.setAttribute("stroke-width", "2");
        circle.setAttribute("style", "cursor:pointer");
        circle.setAttribute("title", `${p.nombre} (${p.era})`);
        
        // Click para seleccionar planta
        circle.addEventListener("click", () => selectPlant(p));
        
        svg.appendChild(circle);
        
        // Etiqueta
        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", p.x);
        text.setAttribute("y", p.y - 12);
        text.setAttribute("text-anchor", "middle");
        text.setAttribute("font-size", "10");
        text.setAttribute("fill", "#212529");
        text.textContent = p.id_planta;
        svg.appendChild(text);
    });
    
    document.getElementById("plants-map").appendChild(svg);
}
```

---

### **4. Sistema de Notificaciones** ⭐⭐

```javascript
// Agregar sistema de notificaciones
class NotificationSystem {
    constructor() {
        this.container = document.createElement('div');
        this.container.className = 'notifications-container';
        this.container.style.cssText = `
            position: fixed;
            top: 80px;
            right: 20px;
            z-index: 9999;
            display: flex;
            flex-direction: column;
            gap: 10px;
        `;
        document.body.appendChild(this.container);
    }
    
    show(message, type = 'info', duration = 3000) {
        const notification = document.createElement('div');
        notification.className = `alert alert-${type} alert-dismissible fade show`;
        notification.style.cssText = `
            min-width: 300px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        `;
        notification.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        this.container.appendChild(notification);
        
        if (duration > 0) {
            setTimeout(() => {
                notification.classList.remove('show');
                setTimeout(() => notification.remove(), 150);
            }, duration);
        }
    }
}

const notifications = new NotificationSystem();

// Usar en eventos del WebSocket
ws.addEventListener('message', (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'task_added') {
        notifications.show(`Nueva tarea: ${data.task.action}`, 'success');
    } else if (data.type === 'robots_status') {
        // Detectar cambios importantes
        data.robots.forEach(robot => {
            if (!robot.status.ok) {
                notifications.show(`⚠️ Robot ${robot.name} desconectado`, 'warning');
            }
        });
    }
});
```

---

### **5. Historial de Tareas** ⭐

```python
# Agregar en app.py
@app.get("/tasks/history")
def get_tasks_history(days: int = 7, robot_id: Optional[str] = None):
    """Historial de tareas ejecutadas"""
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    history = []
    for task in store.tasks:
        started = task.get("started_at")
        if started:
            try:
                task_date = datetime.fromisoformat(started.replace('Z', '+00:00'))
                if task_date >= cutoff:
                    if robot_id is None or task.get("robot_id") == robot_id:
                        history.append(task)
            except:
                continue
    
    # Ordenar por fecha descendente
    history.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    
    # Estadísticas
    stats = {
        "total": len(history),
        "completed": sum(1 for t in history if t.get("status") == "completed"),
        "failed": sum(1 for t in history if t.get("status") in ["error", "failed"]),
        "by_robot": {}
    }
    
    for task in history:
        rid = task.get("robot_id", "unknown")
        stats["by_robot"][rid] = stats["by_robot"].get(rid, 0) + 1
    
    return {"history": history, "stats": stats}
```

---

### **6. Monitoreo de Salud de Robots** ⭐⭐

```python
# Agregar endpoint de salud
@app.get("/robots/health")
def robots_health_check():
    """Verifica la salud de todos los robots"""
    health = {}
    
    for robot in store.robots.values():
        status = store.last_robot_status.get(robot.id, {})
        
        health[robot.id] = {
            "id": robot.id,
            "name": robot.name,
            "online": status.get("ok", False),
            "last_seen": None,
            "issues": []
        }
        
        if status.get("ok") and status.get("data"):
            data = status["data"]
            
            # Verificar conexión serial
            if not data.get("serial_open"):
                health[robot.id]["issues"].append("Serial desconectado")
            
            # Verificar límites
            if data.get("lim_x") == 1:
                health[robot.id]["issues"].append("Límite X alcanzado")
            if data.get("lim_a") == 1:
                health[robot.id]["issues"].append("Límite A alcanzado")
            
            # Detectar anomalías
            if data.get("rx_age_ms", 0) > 5000:
                health[robot.id]["issues"].append("Sin RX reciente")
        
        health[robot.id]["healthy"] = len(health[robot.id]["issues"]) == 0
    
    return {"health": health}
```

---

### **7. Exportación de Datos** ⭐

```python
@app.get("/export/plants")
def export_plants():
    """Exporta plantas en formato CSV"""
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        'era', 'id_planta', 'nombre', 'fecha_plantacion',
        'angulo_h', 'angulo_y', 'longitud_slider', 'velocidad_agua'
    ])
    
    writer.writeheader()
    for plant in store.plants.values():
        writer.writerow(plant.__dict__)
    
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=plantas.csv"}
    )

@app.get("/export/tasks")
def export_tasks():
    """Exporta tareas en formato JSON"""
    return Response(
        content=json.dumps(store.tasks, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=tareas.json"}
    )
```

---

## 📋 Plan de Implementación Sugerido

### **Fase 1: Mejoras Inmediatas** (1-2 horas)
1. ✅ Integrar calendario compartido
2. ✅ Agregar endpoint de sincronización de actividades
3. ✅ Mejorar dashboard con stats

### **Fase 2: Visualización** (2-3 horas)
4. ✅ Implementar mapa 2D de plantas
5. ✅ Agregar sistema de notificaciones
6. ✅ Mejorar tabla de tareas con historial

### **Fase 3: Monitoreo** (1-2 horas)
7. ✅ Implementar health check de robots
8. ✅ Agregar alertas automáticas
9. ✅ Panel de métricas

### **Fase 4: Extras** (opcional)
10. ✅ Exportación de datos
11. ✅ Gráficos de tendencias
12. ✅ Modo oscuro

---

## 🎨 Mejoras de UX

### **Sidebar con Navegación**
```html
<div class="sidebar">
    <nav>
        <a href="#dashboard" class="active">
            <i class="bi bi-speedometer2"></i> Dashboard
        </a>
        <a href="#robots">
            <i class="bi bi-robot"></i> Robots
        </a>
        <a href="#plants">
            <i class="bi bi-flower1"></i> Plantas
        </a>
        <a href="#calendar">
            <i class="bi bi-calendar"></i> Calendario
        </a>
        <a href="#tasks">
            <i class="bi bi-list-check"></i> Tareas
        </a>
        <a href="#regimens">
            <i class="bi bi-gear"></i> Régimenes
        </a>
    </nav>
</div>
```

### **Tabs en lugar de páginas separadas**
```javascript
// Sistema de tabs interno
function setupTabs() {
    const tabs = ['dashboard', 'robots', 'plants', 'calendar', 'tasks'];
    
    tabs.forEach(tab => {
        document.querySelector(`[href="#${tab}"]`).addEventListener('click', (e) => {
            e.preventDefault();
            
            // Ocultar todos
            tabs.forEach(t => {
                document.getElementById(`${t}-section`).style.display = 'none';
                document.querySelector(`[href="#${t}"]`).classList.remove('active');
            });
            
            // Mostrar seleccionado
            document.getElementById(`${tab}-section`).style.display = 'block';
            e.currentTarget.classList.add('active');
            
            // Actualizar URL sin recargar
            history.pushState(null, '', `#${tab}`);
        });
    });
}
```

---

## 🔧 Optimizaciones Técnicas

### **Reducir tamaño del HTML monolítico**
```
Actual: hub_multi.html (1915 líneas)

Propuesto:
├── index.html (estructura base, 200 líneas)
├── dashboard.html (componente, 150 líneas)
├── robots.html (componente, 400 líneas)
├── plants.html (componente, 300 líneas)
└── calendar.html (componente, 250 líneas)
```

### **Lazy loading de componentes**
```javascript
async function loadSection(name) {
    const response = await fetch(`/hub/sections/${name}.html`);
    const html = await response.text();
    document.getElementById(`${name}-section`).innerHTML = html;
    
    // Inicializar scripts del componente
    if (window[`init${name.charAt(0).toUpperCase() + name.slice(1)}`]) {
        window[`init${name.charAt(0).toUpperCase() + name.slice(1)}`]();
    }
}
```

---

## 📊 Métricas y Analytics

```python
# Agregar endpoint de métricas
@app.get("/metrics")
def get_metrics():
    """Métricas del sistema"""
    from datetime import datetime, timedelta
    
    # Calcular métricas
    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)
    
    tasks_24h = [
        t for t in store.tasks
        if t.get("started_at") and 
           datetime.fromisoformat(t["started_at"].replace('Z', '+00:00')) >= last_24h
    ]
    
    return {
        "timestamp": now.isoformat(),
        "robots": {
            "total": len(store.robots),
            "online": sum(1 for r in store.robots.values()
                         if store.last_robot_status.get(r.id, {}).get("ok")),
        },
        "plants": {
            "total": len(store.plants),
            "by_era": _count_by_era()
        },
        "tasks": {
            "last_24h": len(tasks_24h),
            "completed_24h": sum(1 for t in tasks_24h if t.get("status") == "completed"),
            "failed_24h": sum(1 for t in tasks_24h if t.get("status") in ["error", "failed"]),
        },
        "activities": {
            "total": len(store.activities),
            "completed": sum(1 for a in store.activities if a.completada),
            "pending": sum(1 for a in store.activities if not a.completada),
        }
    }

def _count_by_era():
    era_counts = {}
    for plant in store.plants.values():
        era_counts[plant.era] = era_counts.get(plant.era, 0) + 1
    return era_counts
```

---

## 🎯 Resumen de Beneficios

Con estas mejoras, el Hub Service será:

1. ✅ **Más integrado** - Un solo calendario para todo
2. ✅ **Más visual** - Mapas, gráficos, dashboard
3. ✅ **Más informativo** - Notificaciones, health checks
4. ✅ **Más mantenible** - Código modularizado
5. ✅ **Más útil** - Exportación, historial, analytics

---

## ⚡ Priorización

**ALTA PRIORIDAD:**
- Integración con calendario compartido
- Dashboard mejorado
- Sistema de notificaciones

**MEDIA PRIORIDAD:**
- Mapa de plantas
- Health check de robots
- Historial de tareas

**BAJA PRIORIDAD:**
- Exportación de datos
- Gráficos de tendencias
- Modo oscuro

---

¿Qué mejora quieres que implemente primero?
