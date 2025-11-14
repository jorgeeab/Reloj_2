"""Virtual robot simulation compatible with RelojEnv."""
from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

try:
    import numpy as np  # type: ignore
except ImportError:  # Fallback mínimo si numpy no está instalado
    class _NP:
        float32 = float
        integer = int
        @staticmethod
        def zeros(n, dtype=None):
            return [0.0 for _ in range(int(n))]
        @staticmethod
        def clip(x, a, b):
            return a if x < a else b if x > b else x
    np = _NP()  # type: ignore

try:
    import pybullet as p  # type: ignore
    import pybullet_data  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    p = None  # type: ignore
    pybullet_data = None  # type: ignore

from reloj_env import RelojEnv


@dataclass
class VirtualRobotState:
    x_mm: float = 0.0
    a_deg: float = 0.0
    volumen_ml: float = 0.0
    z_mm: float = 0.0
    valor_bomba: float = 0.0
    limite_x: int = 0
    limite_a: int = 0
    calibrando_x: int = 0
    calibrando_a: int = 0
    cmd_x: float = 0.0
    cmd_a: float = 0.0
    cmd_bomba: float = 0.0
    codigo_modo: int = 0
    kpX: float = 0.0
    kiX: float = 0.0
    kdX: float = 0.0
    kpA: float = 0.0
    kiA: float = 0.0
    kdA: float = 0.0
    pasos_por_mm: float = 1.0
    pasos_por_grado: float = 1.0
    usar_sensor_flujo: int = 0
    caudal_bomba_ml_s: float = 1.0
    factor_calibracion_flujo: float = 1.0
    servo_z_deg: float = 180.0
    servo_z_speed: float = 0.0
    z_mm_per_deg: float = 1.0


class VirtualRobotController:
    def __init__(
        self,
        urdf_path: Optional[str] = None,
        log: Optional[Callable[[str], None]] = None,
        use_gui: bool = False,
    ) -> None:
        self._log = log or (lambda msg: None)
        self.state = VirtualRobotState()
        self._lock = threading.RLock()
        self._max_x_mm = 400.0
        self._max_z_mm = 150.0
        self._max_speed_x = 160.0
        self._max_speed_a = 120.0
        self._max_speed_z = 120.0
        self._target_x = 0.0
        self._target_a = 0.0
        self._target_z = 0.0
        self._target_volume = 0.0
        self._manual_x = False
        self._manual_a = False
        self._last_command = np.zeros(24, dtype=np.float32)
        self._robot_id: Optional[int] = None
        self._client_id: Optional[int] = None
        self._angle_joint = 0
        self._slide_joints = (1, 2, 4, 5)
        self._fallback_ids: dict[str, Optional[int]] = {"base": None, "pointer": None, "slider": None}
        resolved_urdf = urdf_path
        if not resolved_urdf:
            base_dir = Path(__file__).resolve().parent
            candidates = [
                base_dir.parent / "Protocolo_Reloj" / "Reloj_1_description" / "urdf" / "Reloj_1.xacro",
                base_dir / "Robot Virtual" / "Robot Virtual" / "urdf" / "Reloj_1.xacro",
            ]
            for cand in candidates:
                if cand.exists():
                    resolved_urdf = str(cand)
                    break
        self._urdf_path = resolved_urdf if resolved_urdf and os.path.exists(resolved_urdf) else None
        if p is not None:
            try:
                self._client_id = p.connect(p.GUI if use_gui else p.DIRECT)
                p.resetSimulation(physicsClientId=self._client_id)
                if pybullet_data is not None:
                    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=self._client_id)
                p.setGravity(0, 0, -9.8, physicsClientId=self._client_id)
                p.loadURDF("plane.urdf", physicsClientId=self._client_id)
                if self._urdf_path and os.path.exists(self._urdf_path):
                    try:
                        self._robot_id = p.loadURDF(
                            self._urdf_path,
                            [0, 0, 0.01],
                            useFixedBase=True,
                            physicsClientId=self._client_id,
                        )
                    except Exception:
                        self._robot_id = None
                if self._robot_id is None:
                    # Build simple fallback visuals (base, pointer, slider)
                    base_col = p.createCollisionShape(p.GEOM_CYLINDER, radius=0.02, height=0.02, physicsClientId=self._client_id)
                    base_vis = p.createVisualShape(p.GEOM_CYLINDER, radius=0.02, length=0.02, rgbaColor=[0.3, 0.3, 0.35, 1], physicsClientId=self._client_id)
                    self._fallback_ids["base"] = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=base_col, baseVisualShapeIndex=base_vis, basePosition=[0, 0, 0.01], physicsClientId=self._client_id)

                    pointer_col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.12, 0.003, 0.003], physicsClientId=self._client_id)
                    pointer_vis = p.createVisualShape(p.GEOM_BOX, halfExtents=[0.12, 0.003, 0.003], rgbaColor=[0.2, 0.9, 0.6, 1], physicsClientId=self._client_id)
                    self._fallback_ids["pointer"] = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=pointer_col, baseVisualShapeIndex=pointer_vis, basePosition=[0, 0, 0.05], physicsClientId=self._client_id)

                    slider_col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.01, 0.01, 0.01], physicsClientId=self._client_id)
                    slider_vis = p.createVisualShape(p.GEOM_BOX, halfExtents=[0.01, 0.01, 0.01], rgbaColor=[0.48, 0.72, 1.0, 1], physicsClientId=self._client_id)
                    self._fallback_ids["slider"] = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=slider_col, baseVisualShapeIndex=slider_vis, basePosition=[-0.2, 0, 0.02], physicsClientId=self._client_id)
            except Exception as exc:
                self._log(f"[VirtualRobot] PyBullet init failed: {exc}")
                if self._client_id is not None:
                    try:
                        p.disconnect(self._client_id)
                    except Exception:
                        pass
                self._client_id = None
                self._robot_id = None

    @staticmethod
    def _approach(current: float, target: float, max_delta: float) -> float:
        if max_delta <= 0:
            return float(target)
        delta = target - current
        if abs(delta) <= max_delta:
            return float(target)
        return float(current + math.copysign(max_delta, delta))

    @staticmethod
    def _mm_to_joint(mm: float) -> float:
        # Map the 0-400 mm slide range into the URDF travel used by the sim
        return float(max(-0.2, min(0.0, -(mm / 1000.0) * 0.2)))

    def reset(self) -> str:
        with self._lock:
            self.state = VirtualRobotState()
            self._target_x = 0.0
            self._target_a = 0.0
            self._target_z = 0.0
            self._target_volume = 0.0
            self._manual_x = False
            self._manual_a = False
            self._last_command = np.zeros(24, dtype=np.float32)
            return self._format_observation_locked()

    def apply_command(self, values: Sequence[float]) -> None:
        data = np.zeros(24, dtype=np.float32)
        for idx, raw in enumerate(values[:24]):
            try:
                data[idx] = float(raw)
            except (TypeError, ValueError):
                data[idx] = 0.0
        with self._lock:
            self._last_command = data
            self.state.codigo_modo = int(round(data[0]))
            self.state.cmd_a = float(data[1])
            self.state.cmd_x = float(data[2])
            self.state.cmd_bomba = float(data[3])
            self.state.valor_bomba = float(data[3])
            self._target_x = float(np.clip(data[4], 0.0, self._max_x_mm))
            # Limitar A a 355° máx para el robot virtual
            self._target_a = float(np.clip(data[5], 0.0, 355.0))
            self._target_volume = max(0.0, float(data[6]))
            self.state.kpX = float(data[7])
            self.state.kiX = float(data[8])
            self.state.kdX = float(data[9])
            self.state.kpA = float(data[10])
            self.state.kiA = float(data[11])
            self.state.kdA = float(data[12])
            if data[13]:
                self.state.volumen_ml = 0.0
            if data[14]:
                self.state.x_mm = 0.0
            if data[15]:
                self.state.a_deg = 0.0
            self.state.pasos_por_mm = float(data[16])
            self.state.pasos_por_grado = float(data[17])
            self.state.usar_sensor_flujo = int(data[18])
            self.state.caudal_bomba_ml_s = float(data[19])
            self.state.factor_calibracion_flujo = float(data[19])
            self.state.servo_z_deg = float(data[20])
            self.state.servo_z_speed = float(data[21])
            if data[23] > 0:
                self.state.z_mm_per_deg = float(data[23])
            z_set = float(data[22])
            if z_set > 0:
                self._target_z = min(self._max_z_mm, max(0.0, z_set))
            else:
                self._target_z = max(0.0, (180.0 - self.state.servo_z_deg) * self.state.z_mm_per_deg)
            modo = int(self.state.codigo_modo)
            self._manual_x = bool(modo & 0x01)
            self._manual_a = bool((modo >> 1) & 0x01)

    def advance(self, dt: float) -> str:
        if dt <= 0:
            dt = 0.0
        with self._lock:
            if self._manual_x:
                velocity = (self.state.cmd_x / 255.0) * self._max_speed_x
                self.state.x_mm += velocity * dt
            else:
                self.state.x_mm = self._approach(self.state.x_mm, self._target_x, self._max_speed_x * dt)
            self.state.x_mm = max(0.0, min(self._max_x_mm, self.state.x_mm))
            if self._manual_a:
                velocity_a = (self.state.cmd_a / 255.0) * self._max_speed_a
                self.state.a_deg += velocity_a * dt
            else:
                self.state.a_deg = self._approach(self.state.a_deg, self._target_a, self._max_speed_a * dt)
            # Limitar rango a [0, 355]
            if self.state.a_deg < 0.0:
                self.state.a_deg = 0.0
            elif self.state.a_deg > 355.0:
                self.state.a_deg = 355.0
            # --- Bomba (modo virtual armonizado con firmware) ---
            # Si hay objetivo pendiente, la bomba virtual se enciende automáticamente
            # a energía equivalente 255 y se detiene al alcanzar el objetivo.
            # Si no hay objetivo, respeta la energía manual (cmd_bomba).
            margin = 0.05
            objective_pending = (self._target_volume - self.state.volumen_ml) > margin
            manual_cmd = float(self.state.cmd_bomba)
            energy_eff = 255.0 if objective_pending else manual_cmd
            flow = abs(energy_eff) / 255.0 * (self.state.caudal_bomba_ml_s or 0.0)
            if energy_eff >= 0:
                # Evitar sobrepasar el objetivo cuando hay meta
                if objective_pending and self._target_volume > 0:
                    max_add = max(0.0, self._target_volume - self.state.volumen_ml)
                    self.state.volumen_ml += min(max_add, flow * dt)
                else:
                    self.state.volumen_ml += flow * dt
            else:
                self.state.volumen_ml = max(0.0, self.state.volumen_ml - flow * dt)

            # Clamp final por seguridad
            if self._target_volume > 0:
                self.state.volumen_ml = min(self.state.volumen_ml, self._target_volume)

            # Reportar el valor aplicado de bomba
            self.state.valor_bomba = float(energy_eff)
            self.state.z_mm = self._approach(self.state.z_mm, self._target_z, self._max_speed_z * dt)
            self._update_pybullet_locked()
            frame = self._format_observation_locked()
        return frame

    def _update_pybullet_locked(self) -> None:
        if p is None or self._client_id is None or self._robot_id is None:
            return
        try:
            angle_rad = math.radians(self.state.a_deg)
            slide = self._mm_to_joint(self.state.x_mm)
            if self._robot_id is not None:
                p.resetJointState(self._robot_id, self._angle_joint, angle_rad, physicsClientId=self._client_id)
                for idx in self._slide_joints:
                    p.resetJointState(self._robot_id, idx, slide, physicsClientId=self._client_id)
            else:
                # Fallback visuals update
                quat = p.getQuaternionFromEuler([0, 0, angle_rad])
                if self._fallback_ids["pointer"] is not None:
                    p.resetBasePositionAndOrientation(self._fallback_ids["pointer"], [0, 0, 0.05], quat, physicsClientId=self._client_id)
                x = -slide  # slide in [-0.2..0] -> [0..0.2]
                x_mm = max(0.0, min(0.2, x))
                xpos = -0.2 + (x_mm / 0.2) * 0.4
                if self._fallback_ids["slider"] is not None:
                    p.resetBasePositionAndOrientation(self._fallback_ids["slider"], [xpos, 0, 0.02], [0, 0, 0, 1], physicsClientId=self._client_id)
            p.stepSimulation(physicsClientId=self._client_id)
        except Exception as exc:
            self._log(f"[VirtualRobot] PyBullet update failed: {exc}")

    def _format_observation_locked(self) -> str:
        s = self.state
        values = [
            s.x_mm,
            s.a_deg,
            s.valor_bomba,
            s.volumen_ml,
            s.limite_x,
            s.limite_a,
            s.calibrando_x,
            s.calibrando_a,
            s.cmd_x,
            s.cmd_a,
            s.cmd_bomba,
            s.codigo_modo,
            s.kpX,
            s.kiX,
            s.kdX,
            s.kpA,
            s.kiA,
            s.kdA,
            s.pasos_por_mm,
            s.pasos_por_grado,
            s.factor_calibracion_flujo,
            s.z_mm,
        ]
        parts = []
        for idx, value in enumerate(values):
            if idx in (4, 5, 6, 7, 11):
                parts.append(str(int(round(value))))
            elif isinstance(value, (int, np.integer)):
                parts.append(str(int(value)))
            else:
                parts.append(f"{float(value):.4f}".rstrip("0").rstrip("."))
        return "<" + ",".join(parts) + ">"

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "x_mm": self.state.x_mm,
                "a_deg": self.state.a_deg,
                "z_mm": self.state.z_mm,
                "volumen_ml": self.state.volumen_ml,
                "codigo_modo": self.state.codigo_modo,
                "usar_sensor_flujo": self.state.usar_sensor_flujo,
                "caudal_bomba_ml_s": self.state.caudal_bomba_ml_s,
                "servo_z_deg": self.state.servo_z_deg,
            }

    def last_command(self) -> np.ndarray:
        with self._lock:
            return self._last_command.copy()

    def shutdown(self) -> None:
        with self._lock:
            if p is not None and self._client_id is not None:
                try:
                    p.disconnect(self._client_id)
                except Exception:
                    pass
            self._client_id = None
            self._robot_id = None


class VirtualSerial:
    def __init__(
        self,
        controller: VirtualRobotController,
        log: Optional[Callable[[str], None]] = None,
        update_hz: float = 20.0,
        timeout: float = 0.3,
    ) -> None:
        self.controller = controller
        self.log = log or (lambda msg: None)
        self.timeout = timeout
        self.is_open = True
        self._update_period = 1.0 / max(1.0, float(update_hz))
        self._rx_buffer = bytearray()
        self._buffer_lock = threading.Lock()
        self._buffer_event = threading.Condition(self._buffer_lock)
        self._pending_tx = ""
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

    def _run_loop(self) -> None:
        last = time.time()
        while self.is_open:
            now = time.time()
            dt = now - last
            last = now
            try:
                frame = self.controller.advance(dt)
                self._push_rx((frame + "\n").encode("utf-8"))
            except Exception as exc:
                self.log(f"[VirtualSerial] loop error: {exc}")
            next_tick = now + self._update_period
            remaining = next_tick - time.time()
            if remaining > 0:
                time.sleep(remaining)

    def _push_rx(self, data: bytes) -> None:
        if not data:
            return
        with self._buffer_event:
            self._rx_buffer.extend(data)
            if len(self._rx_buffer) > 8192:
                del self._rx_buffer[:-4096]
            self._buffer_event.notify_all()

    def write(self, data: bytes) -> int:
        if not self.is_open:
            return len(data)
        text = data.decode("utf-8", errors="ignore")
        if not text:
            return len(data)
        self._pending_tx += text
        lines = self._pending_tx.split("\n")
        self._pending_tx = lines[-1]
        for raw_line in lines[:-1]:
            line = raw_line.strip()
            if not line:
                continue
            if line.lower() == "reset":
                try:
                    frame = self.controller.reset()
                    self._push_rx((frame + "\n").encode("utf-8"))
                except Exception as exc:
                    self.log(f"[VirtualSerial] reset error: {exc}")
                continue
            try:
                values = [float(chunk.strip()) for chunk in line.split(",") if chunk.strip()]
            except ValueError as exc:
                self.log(f"[VirtualSerial] invalid command '{line}': {exc}")
                continue
            self.controller.apply_command(values)
        return len(data)

    def flush(self) -> None:  # pragma: no cover - serial compatibility
        return None

    def close(self) -> None:
        if not self.is_open:
            return
        self.is_open = False
        with self._buffer_event:
            self._buffer_event.notify_all()
        try:
            self.controller.shutdown()
        except Exception:
            pass
        if self._loop_thread.is_alive():
            self._loop_thread.join(timeout=0.5)

    def read(self, size: int = 1) -> bytes:
        if size <= 0:
            size = 1
        deadline = None if self.timeout is None else time.time() + self.timeout
        chunk = bytearray()
        while len(chunk) < size:
            with self._buffer_event:
                if not self.is_open and not self._rx_buffer:
                    break
                while self.is_open and not self._rx_buffer:
                    if deadline is not None:
                        remaining = deadline - time.time()
                        if remaining <= 0:
                            return bytes(chunk)
                        self._buffer_event.wait(timeout=remaining)
                    else:
                        self._buffer_event.wait(timeout=0.1)
                    if not self.is_open and not self._rx_buffer:
                        break
                if not self._rx_buffer:
                    if not self.is_open:
                        break
                    if deadline is not None and time.time() >= deadline:
                        break
                    continue
                take = min(size - len(chunk), len(self._rx_buffer))
                chunk += self._rx_buffer[:take]
                del self._rx_buffer[:take]
            if self.timeout == 0:
                break
        return bytes(chunk)

    @property
    def in_waiting(self) -> int:
        with self._buffer_lock:
            return len(self._rx_buffer)


class VirtualRelojEnv(RelojEnv):
    """Drop-in replacement for RelojEnv backed by the virtual robot."""

    def __init__(
        self,
        urdf_path: Optional[str] = None,
        archivo_tareas: str = "data/tareas_virtual.json",
        logger=None,
        iniciar_planificador: bool = False,
        **kwargs,
    ) -> None:
        kwargs = dict(kwargs)
        kwargs.pop("port", None)
        kwargs.pop("puerto", None)
        kwargs.pop("baudrate", None)
        kwargs.pop("baudios", None)
        baudrate = 115200
        self._virtual_logger = logger if logger else print
        self._virtual_controller = VirtualRobotController(urdf_path=urdf_path, log=self._virtual_logger)
        self._virtual_serial = VirtualSerial(self._virtual_controller, log=self._virtual_logger)
        super().__init__(
            port="VIRTUAL",
            puerto="VIRTUAL",
            baudrate=baudrate,
            baudios=baudrate,
            archivo_tareas=archivo_tareas,
            iniciar_planificador=iniciar_planificador,
            logger=logger,
            **kwargs,
        )

    def _ser_open(self) -> bool:  # type: ignore[override]
        if self.ser and getattr(self.ser, "is_open", False):
            return True
        self.ser = self._virtual_serial
        self.port = "VIRTUAL"
        self.port_s = "VIRTUAL"
        self._ser_err = False
        self._virtual_logger("[VirtualRelojEnv] Serial virtual conectado.")
        return True

    @property
    def is_virtual(self) -> bool:
        return True

    def close(self) -> None:
        super().close()
        self._virtual_serial.close()
        self._virtual_controller.shutdown()


__all__ = ["VirtualRobotController", "VirtualSerial", "VirtualRelojEnv", "VirtualRobotState"]
