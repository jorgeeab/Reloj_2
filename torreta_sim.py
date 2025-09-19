import math
import time
from dataclasses import dataclass, asdict
import os
import json
from pid_model import PID


@dataclass
class Regimen:
    id: int
    name: str
    description: str = ""


@dataclass
class Plant:
    id: int
    regimen_id: int
    name: str
    description: str = ""
    servo1pos: int = 90
    servo2pos: int = 90
    flow_setpoint: float = 1.0
    day: int = 1
    month: int = 1
    year: int = 2025


@dataclass
class Task:
    id: int
    regimen_id: int
    name: str
    description: str = ""
    offset: int = 0
    hour: int = 0
    minute: int = 0
    volume: float = 0.0
    executed: bool = False

@dataclass
class Servo:
    angle: float = 90.0

class RelojVirtualSim:
    """Pequeña simulación del firmware de la reloj virtual."""

    def __init__(self, max_flow=30.0, curve_k=1.2, data_dir=None):
        self.servo1 = Servo()
        self.servo2 = Servo()
        self.valve = Servo(170)
        self.setpoint = 0.0
        self.pid_on = True
        self.ff_on = True
        self.pid = PID()
        self.ff_a0 = 180.0
        self.ff_b0 = -170.0 / max_flow
        self.max_flow = max_flow
        self.curve_k = curve_k
        self.flow = 0.0
        self.vol_req = 0.0
        self.vol_disp_task = 0.0
        self.vol_disp_acum_day = 0.0
        self.logs = []
        self.auto_exec_enabled = False
        self.regimens = []
        self.plants = []
        self.tasks = []
        self.data_dir = data_dir or os.path.dirname(__file__)
        self.f_regs = os.path.join(self.data_dir, 'regs.json')
        self.f_plants = os.path.join(self.data_dir, 'plants.json')
        self.f_tasks = os.path.join(self.data_dir, 'tasks.json')
        # Tabla de calibración (pares flow-angle)
        self.ff_points = []
        self._generate_default_ff()
        self.load_regs()
        self.load_plants()
        self.load_tasks()

    # ------------------------------------------------------------------
    # CRUD helpers for regimens, plants and tasks
    # ------------------------------------------------------------------
    def _next_id(self, items):
        return max((it.id for it in items), default=0) + 1

    # Regimens ---------------------------------------------------------
    def add_or_update_regimen(self, data):
        rid = int(data.get('id', 0) or 0)
        name = data.get('name', data.get('n', ''))
        desc = data.get('description', data.get('d', ''))
        if rid:
            for r in self.regimens:
                if r.id == rid:
                    r.name = name or r.name
                    r.description = desc or r.description
                    self.save_regs()
                    return r
        rid = self._next_id(self.regimens)
        r = Regimen(rid, name, desc)
        self.regimens.append(r)
        self.save_regs()
        return r

    def delete_regimen(self, rid):
        self.regimens = [r for r in self.regimens if r.id != rid]
        # remove related tasks and plants
        self.tasks = [t for t in self.tasks if t.regimen_id != rid]
        self.plants = [p for p in self.plants if p.regimen_id != rid]
        self.save_regs()
        self.save_tasks()
        self.save_plants()

    # Plants -----------------------------------------------------------
    def add_or_update_plant(self, data):
        pid = self._to_int(data.get('id'), 0)
        if pid:
            for p in self.plants:
                if p.id == pid:
                    p.regimen_id = self._to_int(data.get('reg'), p.regimen_id)
                    p.name = data.get('name', data.get('n', p.name))
                    p.description = data.get('description', data.get('d', p.description))
                    p.servo1pos = self._to_int(data.get('s1'), p.servo1pos)
                    p.servo2pos = self._to_int(data.get('s2'), p.servo2pos)
                    p.flow_setpoint = self._to_float(data.get('sp'), p.flow_setpoint)
                    p.day = self._to_int(data.get('day'), p.day)
                    p.month = self._to_int(data.get('mon'), p.month)
                    p.year = self._to_int(data.get('yr'), p.year)
                    self.save_plants()
                    return p
        pid = self._next_id(self.plants)
        p = Plant(
            pid,
            self._to_int(data.get('reg'), 0),
            data.get('name', data.get('n', '')),
            data.get('description', data.get('d', '')),
            self._to_int(data.get('s1'), 90),
            self._to_int(data.get('s2'), 90),
            self._to_float(data.get('sp'), 1.0),
            self._to_int(data.get('day'), 1),
            self._to_int(data.get('mon'), 1),
            self._to_int(data.get('yr'), 2025),
        )
        self.plants.append(p)
        self.save_plants()
        return p

    def delete_plant(self, pid):
        self.plants = [p for p in self.plants if p.id != pid]
        self.save_plants()

    # Tasks ------------------------------------------------------------
    def add_or_update_task(self, data):
        tid = self._to_int(data.get('id'), 0)
        if tid:
            for t in self.tasks:
                if t.id == tid:
                    t.regimen_id = self._to_int(data.get('reg'), t.regimen_id)
                    t.name = data.get('name', data.get('n', t.name))
                    t.description = data.get('description', data.get('d', t.description))
                    t.offset = self._to_int(data.get('off'), t.offset)
                    t.hour = self._to_int(data.get('h'), t.hour)
                    t.minute = self._to_int(data.get('m'), t.minute)
                    t.volume = self._to_float(data.get('vol'), t.volume)
                    t.executed = data.get('exe', 'false') == 'true'
                    self.save_tasks()
                    return t
        tid = self._next_id(self.tasks)
        t = Task(
            tid,
            self._to_int(data.get('reg'), 0),
            data.get('name', data.get('n', '')),
            data.get('description', data.get('d', '')),
            self._to_int(data.get('off'), 0),
            self._to_int(data.get('h'), 0),
            self._to_int(data.get('m'), 0),
            self._to_float(data.get('vol'), 0.0),
            data.get('exe', 'false') == 'true'
        )
        self.tasks.append(t)
        self.save_tasks()
        return t

    def delete_task(self, tid):
        self.tasks = [t for t in self.tasks if t.id != tid]
        self.save_tasks()

    # ------------------------------------------------------------
    # Persistence helpers (JSON format)
    # ------------------------------------------------------------

    @staticmethod
    def _to_int(value, default=0):
        """Convert ``value`` to ``int`` returning ``default`` on failure."""
        try:
            if value in (None, ""):
                return default
            return int(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _to_float(value, default=0.0):
        """Convert ``value`` to ``float`` returning ``default`` on failure."""
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    def save_regs(self):
        with open(self.f_regs, 'w', encoding='utf-8') as f:
            json.dump([asdict(r) for r in self.regimens], f, ensure_ascii=False, indent=2)

    def load_regs(self):
        self.regimens = []
        if not os.path.exists(self.f_regs):
            self.save_regs()
            return
        with open(self.f_regs, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
        self.regimens = [Regimen(**r) for r in data]

    def save_plants(self):
        with open(self.f_plants, 'w', encoding='utf-8') as f:
            json.dump([asdict(p) for p in self.plants], f, ensure_ascii=False, indent=2)

    def load_plants(self):
        self.plants = []
        if not os.path.exists(self.f_plants):
            self.save_plants()
            return
        with open(self.f_plants, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
        self.plants = [Plant(**p) for p in data]

    def save_tasks(self):
        with open(self.f_tasks, 'w', encoding='utf-8') as f:
            json.dump([asdict(t) for t in self.tasks], f, ensure_ascii=False, indent=2)

    def load_tasks(self):
        self.tasks = []
        if not os.path.exists(self.f_tasks):
            self.save_tasks()
            return
        with open(self.f_tasks, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
        self.tasks = [Task(**t) for t in data]

    # ------------------------------------------------------------------

    def _generate_default_ff(self):
        """Crea una tabla lineal de feed-forward y ajusta la recta."""
        self.ff_points = []
        for i in range(20):
            r = i / 19
            flow = r * self.max_flow
            angle = 170 - r * 170
            self.ff_points.append((flow, angle))
        self._fit_ff()

    def _fit_ff(self):
        if not self.ff_points:
            self.ff_a0 = 180.0
            self.ff_b0 = -170.0 / self.max_flow
            return
        flows, angles = zip(*self.ff_points)
        n = len(flows)
        sx = sum(flows)
        sy = sum(angles)
        sxy = sum(f*a for f, a in self.ff_points)
        sx2 = sum(f*f for f in flows)
        d = n*sx2 - sx*sx
        self.ff_b0 = (n*sxy - sx*sy)/d if d else 0.0
        self.ff_a0 = (sy - self.ff_b0*sx)/n if n else 180.0

    def calibrate_ff(self):
        """Realiza una calibración simple capturando puntos."""
        self.ff_points = []
        for i in range(20):
            angle = 170 - i * (170/19)
            flow = self._valve_to_flow(angle)
            self.ff_points.append((flow, angle))
        self._fit_ff()
        self.logs.append("Calibración FF completada")

    def _valve_to_flow(self, angle):
        x = max(0.0, min(1.0, (170 - angle) / 170.0))
        exp_max = math.exp(self.curve_k) - 1.0
        ratio = (math.exp(x * self.curve_k) - 1.0) / exp_max if exp_max else x
        return ratio * self.max_flow

    def step(self, dt):
        self.flow = self._valve_to_flow(self.valve.angle)
        if self.ff_on and not self.pid_on:
            self.valve.angle = max(50, min(180, self.ff_a0 + self.ff_b0 * self.setpoint))
        if self.pid_on:
            corr = self.pid.update(self.setpoint, self.flow, dt)
            self.valve.angle = max(50, min(180, self.valve.angle + corr))
        if self.vol_req:
            self.vol_disp_task += self.flow * dt
        dbg = (f"[STEP dt={dt:.2f}] sp={self.setpoint:.2f} "
               f"angle={self.valve.angle:.1f} flow={self.flow:.2f}")
        print(dbg)
        self.logs.append(dbg)

    def ejecutar_tarea_vol(self, volumen, setpoint=None):
        """Simula la ejecución de una tarea de riego por volumen."""
        if setpoint is not None:
            self.setpoint = setpoint

        self.vol_req = volumen
        self.vol_disp_task = 0.0
        last = time.time()
        while self.vol_disp_task < self.vol_req:
            now = time.time()
            dt = now - last
            last = now
            self.step(dt)
            time.sleep(0.2)

        # Tarea finalizada, cerrar válvula
        self.valve.angle = 170
        self.vol_disp_acum_day += self.vol_disp_task
        self.logs.append(f"Tarea completada {self.vol_disp_task:.1f} ml")
        self.vol_req = 0.0

    def ejecutar_tarea(self, task_id, mark=False):
        """Ejecuta una tarea por ID similar al firmware real."""
        tarea = next((t for t in self.tasks if t.id == task_id), None)
        if not tarea:
            raise ValueError('Tarea no encontrada')

        planta = next((p for p in self.plants if p.regimen_id == tarea.regimen_id), None)
        if not planta:
            raise ValueError('Planta no encontrada')

        self.servo1.angle = planta.servo1pos
        self.servo2.angle = planta.servo2pos
        self.ejecutar_tarea_vol(tarea.volume, planta.flow_setpoint)

        if mark:
            tarea.executed = True


