#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calendar API Endpoints - Endpoints compartidos para el calendario
================================================================

Este módulo proporciona todos los endpoints API REST para interactuar
con el calendario compartido. Estos endpoints pueden ser utilizados
por todos los robots del sistema.
"""

from flask import jsonify, request, render_template
from datetime import datetime, date, timedelta
from typing import Any, Dict, Optional


def register_calendar_routes(app, shared_calendar, logger):
    """
    Registra todos los endpoints relacionados con el calendario compartido.
    
    Args:
        app: Instancia de Flask
        shared_calendar: Instancia de SharedCalendar
        logger: Logger para mensajes
    """
    
    # =========================================================================
    # Página Web del Calendario
    # =========================================================================
    
    @app.route("/calendar")
    def calendar_page():
        """Página principal del calendario"""
        return render_template("calendar.html")
    
    # Helper para obtener datos del request
    def get_request_data() -> Optional[Dict]:
        try:
            if request.is_json:
                return request.get_json() or {}
            return request.form.to_dict() or {}
        except:
            return {}
    
    # =========================================================================
    # CRUD de Tareas
    # =========================================================================
    
    @app.route("/api/calendar/tasks", methods=["GET", "POST"])
    def api_calendar_tasks():
        """
        GET: Obtiene todas las tareas
        POST: Crea una nueva tarea
        """
        if request.method == "GET":
            try:
                # Filtros opcionales
                robot_id = request.args.get("robot_id")
                state = request.args.get("state")
                
                if robot_id:
                    tasks = shared_calendar.get_tasks_by_robot(robot_id)
                elif state:
                    from reloj_core import TaskState
                    tasks = shared_calendar.get_tasks_by_state(TaskState(state))
                else:
                    tasks = shared_calendar.get_all_tasks()
                
                return jsonify({
                    "status": "ok",
                    "count": len(tasks),
                    "tasks": [t.to_dict() for t in tasks]
                })
            except Exception as e:
                logger(f"[Calendar API] Error obteniendo tareas: {e}")
                return jsonify({"error": str(e)}), 500
        
        else:  # POST
            try:
                data = get_request_data()
                from reloj_core import CalendarTask
                
                # Crear tarea
                task = CalendarTask(
                    id="",  # Se generará automáticamente
                    title=data.get("title", "Nueva tarea"),
                    description=data.get("description", ""),
                    start_datetime=data.get("start_datetime", datetime.now().isoformat()),
                    end_datetime=data.get("end_datetime"),
                    duration_seconds=float(data.get("duration_seconds", 600)),
                    robot_id=data.get("robot_id", "reloj"),
                    protocol_name=data.get("protocol_name", ""),
                    action_type=data.get("action_type", "custom"),
                    params=data.get("params", {}),
                    state=data.get("state", "pendiente"),
                    priority=data.get("priority", "media"),
                    recurring=data.get("recurring", False),
                    recurrence_rule=data.get("recurrence_rule", {}),
                    tags=data.get("tags", []),
                    notes=data.get("notes", "")
                )
                
                task_id = shared_calendar.add_task(task)
                
                return jsonify({
                    "status": "ok",
                    "task_id": task_id,
                    "task": shared_calendar.get_task(task_id).to_dict()
                })
            except Exception as e:
                logger(f"[Calendar API] Error creando tarea: {e}")
                return jsonify({"error": str(e)}), 500
    
    @app.route("/api/calendar/tasks/<task_id>", methods=["GET", "PUT", "DELETE"])
    def api_calendar_task(task_id):
        """
        GET: Obtiene una tarea específica
        PUT: Actualiza una tarea
        DELETE: Elimina una tarea
        """
        if request.method == "GET":
            try:
                task = shared_calendar.get_task(task_id)
                if not task:
                    return jsonify({"error": "Tarea no encontrada"}), 404
                return jsonify({
                    "status": "ok",
                    "task": task.to_dict()
                })
            except Exception as e:
                logger(f"[Calendar API] Error obteniendo tarea: {e}")
                return jsonify({"error": str(e)}), 500
        
        elif request.method == "PUT":
            try:
                data = get_request_data()
                success = shared_calendar.update_task(task_id, data)
                
                if not success:
                    return jsonify({"error": "Tarea no encontrada"}), 404
                
                return jsonify({
                    "status": "ok",
                    "task": shared_calendar.get_task(task_id).to_dict()
                })
            except Exception as e:
                logger(f"[Calendar API] Error actualizando tarea: {e}")
                return jsonify({"error": str(e)}), 500
        
        else:  # DELETE
            try:
                success = shared_calendar.delete_task(task_id)
                
                if not success:
                    return jsonify({"error": "Tarea no encontrada"}), 404
                
                return jsonify({"status": "ok", "deleted": task_id})
            except Exception as e:
                logger(f"[Calendar API] Error eliminando tarea: {e}")
                return jsonify({"error": str(e)}), 500
    
    # =========================================================================
    # Vistas de Calendario
    # =========================================================================
    
    @app.route("/api/calendar/view/day", methods=["GET"])
    def api_calendar_day_view():
        """Vista del calendario para un día"""
        try:
            date_str = request.args.get("date")
            target_date = date.fromisoformat(date_str) if date_str else None
            
            view = shared_calendar.get_day_view(target_date)
            return jsonify({"status": "ok", "view": view})
        except Exception as e:
            logger(f"[Calendar API] Error obteniendo vista del día: {e}")
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/calendar/view/week", methods=["GET"])
    def api_calendar_week_view():
        """Vista del calendario para una semana"""
        try:
            date_str = request.args.get("date")
            target_date = date.fromisoformat(date_str) if date_str else None
            
            view = shared_calendar.get_week_view(target_date)
            return jsonify({"status": "ok", "view": view})
        except Exception as e:
            logger(f"[Calendar API] Error obteniendo vista de la semana: {e}")
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/calendar/view/month", methods=["GET"])
    def api_calendar_month_view():
        """Vista del calendario para un mes"""
        try:
            year = int(request.args.get("year", datetime.now().year))
            month = int(request.args.get("month", datetime.now().month))
            
            view = shared_calendar.get_month_view(year, month)
            return jsonify({"status": "ok", "view": view})
        except Exception as e:
            logger(f"[Calendar API] Error obteniendo vista del mes: {e}")
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/calendar/upcoming", methods=["GET"])
    def api_calendar_upcoming():
        """Próximas tareas a ejecutar"""
        try:
            limit = int(request.args.get("limit", 10))
            tasks = shared_calendar.get_upcoming_tasks(limit)
            
            return jsonify({
                "status": "ok",
                "count": len(tasks),
                "tasks": [t.to_dict() for t in tasks]
            })
        except Exception as e:
            logger(f"[Calendar API] Error obteniendo próximas tareas: {e}")
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/calendar/overdue", methods=["GET"])
    def api_calendar_overdue():
        """Tareas vencidas"""
        try:
            tasks = shared_calendar.get_overdue_tasks()
            
            return jsonify({
                "status": "ok",
                "count": len(tasks),
                "tasks": [t.to_dict() for t in tasks]
            })
        except Exception as e:
            logger(f"[Calendar API] Error obteniendo tareas vencidas: {e}")
            return jsonify({"error": str(e)}), 500
    
    # =========================================================================
    # Estadísticas
    # =========================================================================
    
    @app.route("/api/calendar/statistics", methods=["GET"])
    def api_calendar_statistics():
        """Estadísticas del calendario"""
        try:
            stats = shared_calendar.get_statistics()
            return jsonify({"status": "ok", "statistics": stats})
        except Exception as e:
            logger(f"[Calendar API] Error obteniendo estadísticas: {e}")
            return jsonify({"error": str(e)}), 500
    
    # =========================================================================
    # Búsqueda y Filtrado
    # =========================================================================
    
    @app.route("/api/calendar/search", methods=["GET"])
    def api_calendar_search():
        """Búsqueda de tareas"""
        try:
            # Obtener parámetros de búsqueda
            robot_id = request.args.get("robot_id")
            start_date_str = request.args.get("start_date")
            end_date_str = request.args.get("end_date")
            state = request.args.get("state")
            priority = request.args.get("priority")
            search_text = request.args.get("q", "").lower()
            
            # Obtener todas las tareas
            tasks = shared_calendar.get_all_tasks()
            
            # Aplicar filtros
            if robot_id:
                tasks = [t for t in tasks if t.robot_id == robot_id]
            
            if state:
                tasks = [t for t in tasks if t.state == state]
            
            if priority:
                tasks = [t for t in tasks if t.priority == priority]
            
            if start_date_str and end_date_str:
                start_date = date.fromisoformat(start_date_str)
                end_date = date.fromisoformat(end_date_str)
                filtered = []
                for task in tasks:
                    try:
                        task_date = datetime.fromisoformat(task.start_datetime).date()
                        if start_date <= task_date <= end_date:
                            filtered.append(task)
                    except:
                        continue
                tasks = filtered
            
            if search_text:
                tasks = [
                    t for t in tasks 
                    if search_text in t.title.lower() or 
                       search_text in t.description.lower() or
                       search_text in t.notes.lower()
                ]
            
            return jsonify({
                "status": "ok",
                "count": len(tasks),
                "tasks": [t.to_dict() for t in tasks]
            })
        except Exception as e:
            logger(f"[Calendar API] Error en búsqueda: {e}")
            return jsonify({"error": str(e)}), 500
    
    logger("[Calendar API] Endpoints registrados correctamente")
