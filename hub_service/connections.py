from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
import os
from urllib.parse import urlparse

import httpx
from fastapi import WebSocket

from .models import Robot, Store

# WebSocket clients connected to /ws
ws_clients: List[WebSocket] = []

# Internal state
_poll_lock = asyncio.Lock()
_sse_tasks: Dict[str, asyncio.Task] = {}
_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None
_poll_task: Optional[asyncio.Task] = None
_process_watch_task: Optional[asyncio.Task] = None
_store: Optional[Store] = None
_ok_streak: Dict[str,int] = {}
_fail_streak: Dict[str,int] = {}

_DEBUG = str(os.environ.get("HUB_DEBUG_CONNECTIONS", "0")).lower() not in ("0", "false", "no", "off")


def _dbg(event: str, robot_id: Optional[str] = None, **info: Any) -> None:
    if not _DEBUG:
        return
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")
    payload = {**info}
    if robot_id:
        payload.setdefault("robot", robot_id)
    print(f"[hub.connections {stamp}] {event}: {payload}")

# Process accessors injected from app.py so we can detect runtime
_get_local_proc: Callable[[], Optional[Any]] = lambda: None
_get_local_id: Callable[[], Optional[str]] = lambda: None
_get_pump_proc: Callable[[], Optional[Any]] = lambda: None
_get_pump_id: Callable[[], Optional[str]] = lambda: None


def configure(
    store: Store,
    loop: asyncio.AbstractEventLoop,
    local_proc_getter: Callable[[], Optional[Any]],
    local_id_getter: Callable[[], Optional[str]],
    pump_proc_getter: Callable[[], Optional[Any]],
    pump_id_getter: Callable[[], Optional[str]],
) -> None:
    """Inject shared references from the FastAPI app."""
    global _store, _MAIN_LOOP, _get_local_proc, _get_local_id, _get_pump_proc, _get_pump_id
    _store = store
    _MAIN_LOOP = loop
    _get_local_proc = local_proc_getter
    _get_local_id = local_id_getter
    _get_pump_proc = pump_proc_getter
    _get_pump_id = pump_id_getter
    _dbg("configured", robots=len(_store.robots))


def reset_robot_status() -> None:
    """Mark all robots as offline until telemetry confirms otherwise."""
    if not _store:
        return
    for rb in _store.robots.values():
        _store.last_robot_status[rb.id] = {"ok": False, "error": "idle"}
        _store.last_robot_seen.pop(rb.id, None)
        _store.last_robot_error.pop(rb.id, None)
        _dbg("reset", rb.id, status="idle")


def status_snapshot() -> Dict[str, Any]:
    """Return the current robots status payload used by broadcasts."""
    if not _store:
        return {"type": "robots_status", "ts": datetime.now(timezone.utc).isoformat(), "robots": []}
    return {
        "type": "robots_status",
        "ts": datetime.now(timezone.utc).isoformat(),
        "robots": [
            {
                "id": rb.id,
                "name": rb.name,
                "base_url": rb.base_url,
                "kind": rb.kind,
                "status": _store.last_robot_status.get(rb.id, {"ok": False}),
                "runtime": robot_process_running(rb.id),
            }
            for rb in _store.robots.values()
        ],
    }


async def broadcast(payload: Dict[str, Any]) -> None:
    """Send payload to all connected websocket clients."""
    if not ws_clients:
        return
    msg = json.dumps(payload, ensure_ascii=False)
    to_remove: List[WebSocket] = []
    for ws in list(ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            to_remove.append(ws)
    for ws in to_remove:
        try:
            ws_clients.remove(ws)
        except ValueError:
            pass


async def broadcast_status_snapshot() -> None:
    await broadcast(status_snapshot())


def schedule_status_broadcast() -> None:
    if _MAIN_LOOP is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(broadcast_status_snapshot(), _MAIN_LOOP)
    except Exception:
        pass


def start_background_tasks() -> None:
    """Launch polling and process-watch tasks."""
    global _poll_task, _process_watch_task
    if _poll_task is None:
        _poll_task = asyncio.create_task(_poll_robots_loop())
        _dbg("poll_task_started")
    if _process_watch_task is None:
        _process_watch_task = asyncio.create_task(_monitor_local_processes())
        _dbg("process_watch_started")


async def shutdown_background_tasks() -> None:
    """Cancel background tasks and SSE loops."""
    global _poll_task, _process_watch_task
    tasks: List[asyncio.Task] = []
    if _poll_task:
        _poll_task.cancel()
        tasks.append(_poll_task)
        _poll_task = None
        _dbg("poll_task_cancelled")
    if _process_watch_task:
        _process_watch_task.cancel()
        tasks.append(_process_watch_task)
        _process_watch_task = None
        _dbg("process_watch_cancelled")
    for tid, task in list(_sse_tasks.items()):
        try:
            task.cancel()
        finally:
            _sse_tasks.pop(tid, None)
        tasks.append(task)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def start_sse_task(rb: Robot) -> None:
    if rb.id in _sse_tasks and not _sse_tasks[rb.id].done():
        return
    _sse_tasks[rb.id] = asyncio.create_task(_sse_loop(rb))
    _dbg("sse_started", rb.id)


def stop_sse_task(robot_id: str) -> None:
    task = _sse_tasks.pop(robot_id, None)
    if task and not task.done():
        task.cancel()
        _dbg("sse_cancelled", robot_id)


def robot_process_running(robot_id: str) -> bool:
    local_id = _get_local_id()
    proc = _get_local_proc()
    if local_id and robot_id == local_id and proc and proc.poll() is None:
        return True
    pump_id = _get_pump_id()
    pump_proc = _get_pump_proc()
    if pump_id and robot_id == pump_id and pump_proc and pump_proc.poll() is None:
        return True
    return False


def is_loopback(base_url: str) -> bool:
    try:
        parsed = urlparse(base_url)
        host = (parsed.hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "::1"}
    except Exception:
        return False


def wait_for_robot_online(base_url: str, api_key: Optional[str] = None, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    """Blocking helper used during start-up to ensure /api/status responds."""
    deadline = time.time() + timeout
    url = base_url.rstrip("/") + "/api/status"
    headers = {"X-API-Key": api_key} if api_key else None
    with httpx.Client(timeout=2.0) as client:
        while time.time() < deadline:
            try:
                res = client.get(url, headers=headers)
                if res.status_code == 200:
                    try:
                        return res.json()
                    except Exception:
                        return {}
            except Exception:
                pass
            time.sleep(0.5)
    return None


async def _poll_robots_loop() -> None:
    while True:
        changed = False
        try:
            if not _store:
                await asyncio.sleep(0.5)
                continue
            robots = list(_store.robots.values())
            if robots:
                timeout = httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=5.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    tasks = []
                for rb in robots:
                    url = rb.base_url.rstrip("/") + "/api/status"
                    headers = {"X-API-Key": rb.api_key} if rb.api_key else None
                    tasks.append(client.get(url, headers=headers))
                results = await asyncio.gather(*tasks, return_exceptions=True)
                now_iso = datetime.now(timezone.utc).isoformat()
                for rb, res in zip(robots, results):
                    status: Dict[str, Any] = {"ok": False}
                    prev = _store.last_robot_status.get(rb.id)
                    ok = False; cand: Dict[str,Any] = {"ok": False}
                    if isinstance(res, Exception):
                        err = str(res)
                        cand = {"ok": False, "error": err}
                        _store.last_robot_error[rb.id] = err
                        _dbg("poll_error", rb.id, error=err)
                    else:
                        if res.status_code == 200:
                            try:
                                data = res.json()
                                cand = {"ok": True, "data": data}
                            except Exception:
                                cand = {"ok": True, "raw": res.text}
                            _store.last_robot_seen[rb.id] = now_iso
                            _store.last_robot_error.pop(rb.id, None)
                            ok = True
                            _dbg("poll_ok", rb.id)
                        else:
                            cand = {"ok": False, "status": res.status_code}
                            _store.last_robot_error[rb.id] = f"http:{res.status_code}"
                            _dbg("poll_http", rb.id, status=res.status_code)

                    if ok:
                        _ok_streak[rb.id] = min(_ok_streak.get(rb.id,0)+1, 5)
                        _fail_streak[rb.id] = 0
                        if _ok_streak[rb.id] >= 2 and prev != cand:
                            _store.last_robot_status[rb.id] = cand
                            changed = True
                            _dbg("status_online", rb.id)
                    else:
                        _fail_streak[rb.id] = min(_fail_streak.get(rb.id,0)+1, 5)
                        _ok_streak[rb.id] = 0
                        if _fail_streak[rb.id] >= 2 and prev != cand:
                            _store.last_robot_status[rb.id] = cand
                            changed = True
                            _dbg("status_offline", rb.id)
                # If we have healthy HTTP status and no SSE loop yet, start it
                for rb in robots:
                    try:
                        if _store.last_robot_status.get(rb.id, {}).get('ok') and rb.id not in _sse_tasks:
                            start_sse_task(rb)
                            _dbg('sse_autostart', rb.id)
                    except Exception:
                        pass
                # also, if SSE reports updates and no task running, autostart SSE
                if changed:
                    await broadcast_status_snapshot()
                    _dbg("broadcast_status", robots=len(robots))
            elif changed:
                await broadcast_status_snapshot()
                _dbg("broadcast_status", robots=0)
            await _poll_tasks_status()
        except Exception:
            pass
        await asyncio.sleep(0.5)


async def _poll_tasks_status() -> None:
    if not _store or not _store.tasks:
        return
    async with _poll_lock:
        items = list(_store.tasks)
        async with httpx.AsyncClient(timeout=1.5) as client:
            for task_rec in items:
                if task_rec.get("status") in ("completed", "stopped", "error"):
                    continue
                rb = _store.robots.get(task_rec.get("robot_id") or "")
                if not rb:
                    continue
                execution_id = task_rec.get("execution_id")
                if not execution_id:
                    continue
                url = rb.base_url.rstrip("/") + f"/api/execution/{execution_id}"
                headers = {"X-API-Key": rb.api_key} if rb.api_key else None
                try:
                    res = await client.get(url, headers=headers)
                    if res.status_code == 200:
                        payload = res.json()
                        task_rec["status"] = payload.get("status") or task_rec.get("status")
                        task_rec["ended_at"] = payload.get("ended_at") or task_rec.get("ended_at")
                        if isinstance(payload, dict) and "progress" in payload:
                            task_rec["progress"] = payload.get("progress")
                    else:
                        task_rec["status"] = task_rec.get("status") or "unknown"
                except Exception:
                    task_rec["status"] = task_rec.get("status") or "unknown"
        _store.save()
        await broadcast({"type": "tasks_update", "tasks": _store.tasks})
        

async def _sse_loop(rb: Robot) -> None:
    url = rb.base_url.rstrip("/") + "/api/status/stream"
    headers = {"X-API-Key": rb.api_key} if rb.api_key else None
    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code != 200:
                        await asyncio.sleep(1.0)
                        continue
                    data_buf: Optional[str] = None
                    async for line in response.aiter_lines():
                        if line is None:
                            continue
                        text = line.strip()
                        if not text:
                            if data_buf:
                                try:
                                    parsed = json.loads(data_buf)
                                    status = {"ok": True, "data": parsed}
                                except Exception:
                                    status = {"ok": True, "raw": data_buf}
                                if _store and _store.last_robot_status.get(rb.id) != status:
                                    if is_loopback(rb.base_url) and not robot_process_running(rb.id):
                                        _dbg("sse_skip_local", rb.id)
                                    else:
                                        _store.last_robot_status[rb.id] = status
                                        _store.last_robot_seen[rb.id] = datetime.now(timezone.utc).isoformat()
                                        _store.last_robot_error.pop(rb.id, None)
                                        await broadcast_status_snapshot()
                                        _dbg("sse_update", rb.id)
                                data_buf = None
                            continue
                        if text.startswith(":"):
                            continue
                        if text.startswith("data:"):
                            data_buf = text[len("data:"):].strip()
        except asyncio.CancelledError:
            break
        except Exception:
            if _store:
                _store.last_robot_seen.pop(rb.id, None)
                _store.last_robot_error[rb.id] = "sse_disconnected"
                offline_status = {"ok": False, "error": "sse_disconnected"}
                if _store.last_robot_status.get(rb.id) != offline_status:
                    _store.last_robot_status[rb.id] = offline_status
                    await broadcast_status_snapshot()
                    _dbg("sse_disconnected", rb.id)
            await asyncio.sleep(1.0)


async def _monitor_local_processes() -> None:
    while True:
        try:
            local_proc = _get_local_proc()
            local_id = _get_local_id()
            if local_proc is not None and local_proc.poll() is not None and _store:
                if local_id:
                    _store.last_robot_seen.pop(local_id, None)
                    _store.last_robot_error[local_id] = "process_exited"
                    _store.last_robot_status[local_id] = {"ok": False, "error": "process_exited"}
                    stop_sse_task(local_id)
                    schedule_status_broadcast()
                    _dbg("proc_exit", local_id)
            pump_proc = _get_pump_proc()
            pump_id = _get_pump_id()
            if pump_proc is not None and pump_proc.poll() is not None and _store:
                if pump_id:
                    _store.last_robot_seen.pop(pump_id, None)
                    _store.last_robot_error[pump_id] = "process_exited"
                    _store.last_robot_status[pump_id] = {"ok": False, "error": "process_exited"}
                    stop_sse_task(pump_id)
                    schedule_status_broadcast()
                    _dbg("proc_exit", pump_id)
        except Exception:
            pass
        await asyncio.sleep(1.0)
