/**
 * Calendario Compartido - JavaScript para la interfaz integrada
 * =============================================================
 */

// Función para cambiar entre vistas del calendario
function switchCalendarView(viewName) {
    // Desactivar todos los botones y vistas
    document.querySelectorAll('.cal-view-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.style.background = 'var(--bg)';
        btn.style.color = 'var(--text)';
    });

    document.querySelectorAll('.cal-view').forEach(view => {
        view.style.display = 'none';
        view.classList.remove('active');
    });

    // Activar vista y botón seleccionados
    const btn = document.querySelector(`[data-view="${viewName}"]`);
    if (btn) {
        btn.classList.add('active');
        btn.style.background = 'var(--primary)';
        btn.style.color = 'white';
    }

    const view = document.getElementById(`cal-${viewName}`);
    if (view) {
        view.style.display = 'block';
        view.classList.add('active');
    }

    // Cargar datos de la vista
    if (viewName === 'dashboard') {
        loadCalendarDashboard();
    } else if (viewName === 'upcoming') {
        loadCalendarUpcoming();
    } else if (viewName === 'all') {
        loadCalendarAll();
    }
}

// Cargar dashboard
async function loadCalendarDashboard() {
    try {
        // Cargar estadísticas
        const statsRes = await fetch('/api/calendar/statistics');
        const statsData = await statsRes.json();

        if (statsData.status === 'ok') {
            const stats = statsData.statistics;
            document.getElementById('stat-total').textContent = stats.total_tasks || 0;
            document.getElementById('stat-pending').textContent = stats.by_state.pendiente || 0;
            document.getElementById('stat-completed').textContent = stats.by_state.completada || 0;
            document.getElementById('stat-overdue').textContent = stats.overdue_count || 0;
        }

        // Cargar próximas 5 tareas
        const upcomingRes = await fetch('/api/calendar/upcoming?limit=5');
        const upcomingData = await upcomingRes.json();

        renderTasks(upcomingData.tasks || [], 'upcoming-preview');

    } catch (e) {
        console.error('Error cargando dashboard:', e);
        const preview = document.getElementById('upcoming-preview');
        if (preview) {
            preview.innerHTML = '<div style="padding:20px; text-align:center; color:var(--danger)">Error cargando datos</div>';
        }
    }
}

// Cargar próximas tareas
async function loadCalendarUpcoming() {
    try {
        const robot = document.getElementById('filter-robot-upcoming').value;
        let url = '/api/calendar/upcoming?limit=20';
        if (robot) url += `&robot_id=${robot}`;

        const res = await fetch(url);
        const data = await res.json();

        renderTasks(data.tasks || [], 'upcoming-tasks');

    } catch (e) {
        console.error('Error cargando próximas:', e);
        const upcoming = document.getElementById('upcoming-tasks');
        if (upcoming) {
            upcoming.innerHTML = '<div style="padding:20px; text-align:center; color:var(--danger)">Error cargando datos</div>';
        }
    }
}

// Cargar todas las tareas
async function loadCalendarAll() {
    try {
        const robot = document.getElementById('filter-robot-all').value;
        const state = document.getElementById('filter-state-all').value;

        let url = '/api/calendar/tasks?';
        if (robot) url += `robot_id=${robot}&`;
        if (state) url += `state=${state}&`;

        const res = await fetch(url);
        const data = await res.json();

        renderTasks(data.tasks || [], 'all-tasks');

    } catch (e) {
        console.error('Error cargando todas:', e);
        const all = document.getElementById('all-tasks');
        if (all) {
            all.innerHTML = '<div style="padding:20px; text-align:center; color:var(--danger)">Error cargando datos</div>';
        }
    }
}

// Renderizar lista de tareas
function renderTasks(tasks, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!tasks || tasks.length === 0) {
        container.innerHTML = '<div style="padding:20px; text-align:center; color:var(--muted)">No hay tareas para mostrar</div>';
        return;
    }

    container.innerHTML = tasks.map(task => {
        const date = new Date(task.start_datetime);
        const dateStr = date.toLocaleString('es-ES', {
            day: 'numeric',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit'
        });

        // Color según robot
        const robotColors = {
            'reloj': 'var(--primary)',
            'pump': 'var(--accent)',
            'opuno': 'var(--success)'
        };
        const robotColor = robotColors[task.robot_id] || 'var(--muted)';

        // Color según prioridad
        const priorityColors = {
            'urgente': 'var(--danger)',
            'alta': '#ff9800',
            'media': '#ffc107',
            'baja': 'var(--success)'
        };
        const priorityColor = priorityColors[task.priority] || 'var(--muted)';

        return `
            <div class="card" style="padding:12px; cursor:pointer; transition:transform 0.2s" 
                 onmouseover="this.style.transform='translateY(-2px)'" 
                 onmouseout="this.style.transform='translateY(0)'">
                <div class="row" style="justify-content:space-between; margin-bottom:8px">
                    <strong style="font-size:1.1em">${task.title}</strong>
                    <span class="pill" style="background:${robotColor}; color:white; font-size:0.85em">
                        ${task.robot_id.toUpperCase()}
                    </span>
                </div>
                <div style="color:var(--muted); font-size:0.9em; margin-bottom:8px">
                    ${task.description || 'Sin descripción'}
                </div>
                <div class="row" style="gap:12px; font-size:0.85em; color:var(--muted); flex-wrap:wrap">
                    <span>📅 ${dateStr}</span>
                    <span style="color:${priorityColor}">⭐ ${task.priority}</span>
                    <span>🔧 ${task.protocol_name || task.action_type}</span>
                    <span>📊 ${task.state}</span>
                </div>
            </div>
        `;
    }).join('');
}

// Event listeners para botones de vista
document.addEventListener('DOMContentLoaded', () => {
    // Configurar botones de vista
    document.querySelectorAll('.cal-view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.getAttribute('data-view');
            switchCalendarView(view);
        });
    });

    // Configurar filtros
    const filterUpcoming = document.getElementById('filter-robot-upcoming');
    if (filterUpcoming) {
        filterUpcoming.addEventListener('change', loadCalendarUpcoming);
    }

    const filterRobot = document.getElementById('filter-robot-all');
    const filterState = document.getElementById('filter-state-all');
    if (filterRobot) filterRobot.addEventListener('change', loadCalendarAll);
    if (filterState) filterState.addEventListener('change', loadCalendarAll);

    // Manejar click en tab de calendario
    const calendarTab = document.getElementById('tab_calendar');
    if (calendarTab) {
        calendarTab.addEventListener('click', () => {
            // Esperar un poco para que el tab se active
            setTimeout(() => {
                initCalendar();
            }, 100);
        });
    }
});

// Cargar dashboard automáticamente cuando se activa el tab de calendario
function initCalendar() {
    switchCalendarView('dashboard');
}

// Auto-refresh cada 30 segundos si el tab está activo
setInterval(() => {
    const calendarSection = document.querySelector('section[data-tab="calendar"]');
    if (calendarSection && calendarSection.style.display !== 'none') {
        const activeView = document.querySelector('.cal-view.active');
        if (activeView) {
            const viewId = activeView.id.replace('cal-', '');
            if (viewId === 'dashboard') loadCalendarDashboard();
            else if (viewId === 'upcoming') loadCalendarUpcoming();
            else if (viewId === 'all') loadCalendarAll();
        }
    }
}, 30000);
